"""Reproductor local basado en PyAV/libavcodec.

El aire local no depende de mpv, IPC, named pipes ni QMediaPlayer. PyAV abre
el contenedor y decodifica vídeo/audio en un hilo de trabajo; los frames RGB
se entregan a ``VideoSurface`` y el audio PCM se reproduce con QAudioSink.
FFmpeg sigue siendo el motor de la salida RTMP.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from array import array
try:
    import av
except ImportError:  # La aplicación puede arrancar y explicar la dependencia.
    av = None

from PySide6.QtCore import QObject, QTimer, Signal, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtMultimedia import QAudioFormat, QAudioSink

from . import logger

log = logger.get("pyav-player")
AUDIO_RATE = 48000
AUDIO_BYTES_PER_SECOND = AUDIO_RATE * 2 * 2  # s16 estéreo
AUDIO_PREBUFFER_SECONDS = 6.0
AUDIO_BUFFER_BYTES = int(AUDIO_BYTES_PER_SECOND * AUDIO_PREBUFFER_SECONDS)
AUDIO_QUEUE_LIMIT = int(AUDIO_BYTES_PER_SECOND * (AUDIO_PREBUFFER_SECONDS + 0.5))


class _DecodeJob(QObject):
    """Trabajo de decodificación ejecutado en un hilo Python separado."""

    loaded = Signal(object, int)
    ready = Signal(int)                             # audio prebuffer listo
    frame = Signal(object, float, float, int)       # QImage, posición, duración, generación
    audio = Signal(object, int)                     # bytes PCM, generación
    levels = Signal(float, float, int)              # dBFS L/R, generación
    finished = Signal(str, int)                     # eof | stop | error, generación
    error = Signal(str, int)

    def __init__(self, path, generation, loop=False, audio_id=None, subtitle_id=None,
                 start_at=0.0, end_at=0.0, parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.generation = generation
        self.loop = bool(loop)
        self.audio_id = audio_id
        # Se conserva el índice seleccionado para que el reinicio en vivo y
        # las salidas mantengan una API de pistas coherente. El monitor PyAV
        # no quema subtítulos en la imagen; RTMP/SRT los quema en FFmpeg cuando
        # está activada la opción correspondiente.
        self.subtitle_id = subtitle_id
        self.start_at = max(0.0, float(start_at or 0.0))
        self.end_at = max(0.0, float(end_at or 0.0))
        self.stop_event = threading.Event()
        self._condition = threading.Condition()
        self._paused = False
        self._seek_request = None
        self._subtitle_events = []
        self._subtitle_event_count = 0

    def stop(self):
        self.stop_event.set()
        with self._condition:
            self._condition.notify_all()

    def set_paused(self, paused):
        with self._condition:
            self._paused = bool(paused)
            self._condition.notify_all()

    def seek(self, seconds):
        with self._condition:
            self._seek_request = max(0.0, float(seconds))
            self._condition.notify_all()

    def _take_seek(self):
        with self._condition:
            value = self._seek_request
            self._seek_request = None
            return value

    def _wait_until(self, position, clock_origin):
        """Espera al PTS del frame, preservando la pausa sin acelerar vídeo."""
        while not self.stop_event.is_set():
            with self._condition:
                if self._paused:
                    paused_at = time.monotonic()
                    while self._paused and not self.stop_event.is_set():
                        self._condition.wait(0.2)
                    clock_origin += time.monotonic() - paused_at
                    continue
            delay = clock_origin + position - time.monotonic()
            if delay <= 0:
                return clock_origin
            self.stop_event.wait(min(0.02, delay))
        return clock_origin

    @staticmethod
    def _frame_image(frame):
        rgb = frame.reformat(format="rgb24")
        plane = rgb.planes[0]
        # copy() desacopla la imagen de la memoria reutilizable de FFmpeg.
        return QImage(bytes(plane), rgb.width, rgb.height, plane.line_size,
                      QImage.Format.Format_RGB888).copy()

    @staticmethod
    def _subtitle_text(subtitle):
        """Extrae texto ASS/SRT sin tags para el monitor PyAV."""
        value = ""
        for name in ("dialogue", "text"):
            try:
                value = getattr(subtitle, name, "") or ""
                if callable(value):
                    value = value()
            except Exception:
                value = ""
            if value:
                break
        if not value:
            return ""
        value = re.sub(r"\\{[^}]*\\}", "", str(value))
        value = value.replace("\\N", "\n").replace("\\n", "\n")
        value = re.sub(r"<[^>]+>", "", value)
        return value.strip()

    def _remember_subtitle_packet(self, subtitle_stream, packet, timeline_start):
        """Guarda subtítulos de texto como intervalos relativos al clip."""
        try:
            decoded = subtitle_stream.decode(packet)
        except Exception as exc:  # noqa: BLE001
            try:
                decoded = packet.decode()
            except Exception:
                log.warning("PyAV no pudo decodificar subtítulo %s: %s", self.path, exc)
                return
        for subtitle_set in decoded or []:
            rects = getattr(subtitle_set, "rects", []) or []
            text = "\n".join(filter(None, (self._subtitle_text(rect) for rect in rects))).strip()
            if not text:
                continue
            base = None
            pts = getattr(subtitle_set, "pts", None)
            time_base = getattr(subtitle_stream, "time_base", None)
            if pts is not None and time_base is not None:
                try:
                    base = float(pts * time_base)
                except (TypeError, ValueError):
                    base = None
            if base is None:
                try:
                    base = float(packet.pts * packet.time_base) if packet.pts is not None else 0.0
                except (TypeError, ValueError):
                    base = 0.0
            start_ms = float(getattr(subtitle_set, "start_display_time", 0) or 0)
            end_ms = float(getattr(subtitle_set, "end_display_time", 0) or 0)
            start = max(0.0, base + start_ms / 1000.0 - timeline_start)
            end = base + end_ms / 1000.0 - timeline_start if end_ms > 0 else start + 6.0
            self._subtitle_events.append((start, max(start, end), text))
            self._subtitle_event_count += 1
            if self._subtitle_event_count <= 3:
                log.info("PyAV subtitle event #%d start=%.3f end=%.3f text=%s",
                         self._subtitle_event_count, start, end, text[:80])

    @staticmethod
    def _paint_subtitle(image, text):
        if not text:
            return image
        try:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            size = max(18, int(image.height() * 0.042))
            font = QFont("Arial", size)
            font.setBold(True)
            painter.setFont(font)
            flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap
            box = QRectF(image.width() * 0.06, image.height() * 0.76, image.width() * 0.88, image.height() * 0.19)
            metrics = QFontMetrics(font)
            bounds = metrics.boundingRect(box.toRect(), int(flags), text)
            background = QRectF(box.left(), max(box.top(), box.top() + (box.height() - bounds.height()) / 2 - 10),
                                box.width(), min(box.height(), bounds.height() + 20))
            painter.setBrush(QColor(0, 0, 0, 185))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(background, 8, 8)
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(box, int(flags), text)
            painter.end()
        except Exception as exc:  # noqa: BLE001
            log.debug("subtitle paint: %s", exc)
        return image

    def _subtitle_for_position(self, position):
        active = [text for start, end, text in self._subtitle_events if start <= position <= end]
        return "\n".join(active[-1:]) if active else ""

    @staticmethod
    def _duration(container, video_stream=None, audio_stream=None):
        try:
            if container.duration:
                return max(0.0, float(container.duration) / float(av.time_base))
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            pass
        for stream in (video_stream, audio_stream):
            if stream is not None and stream.duration and stream.time_base:
                try:
                    return max(0.0, float(stream.duration * stream.time_base))
                except (TypeError, ValueError):
                    pass
        return 0.0

    @staticmethod
    def _stream_info(stream):
        if stream is None:
            return {}
        rate = getattr(stream, "average_rate", None)
        return {
            "codec": getattr(getattr(stream, "codec_context", None), "name", ""),
            "width": int(getattr(stream, "width", 0) or 0),
            "height": int(getattr(stream, "height", 0) or 0),
            "fps": float(rate) if rate else 0.0,
        }

    @staticmethod
    def _pcm_bytes(frame):
        """Devuelve solo las muestras útiles del plano PCM empaquetado.

        FFmpeg alinea la memoria de los ``AudioFrame`` y PyAV puede exponer
        esos bytes de relleno al convertir el plano a ``bytes``. Si el relleno
        llega a QAudioSink, se reproduce como ruido y además puede desfasar el
        siguiente bloque de muestras. El resampler de abajo siempre produce
        s16 estéreo empaquetado, por lo que el tamaño válido es exactamente
        ``samples * 2 canales * 2 bytes``.
        """
        try:
            samples = int(getattr(frame, "samples", 0) or 0)
            useful = samples * 2 * 2
            if samples <= 0 or not getattr(frame, "planes", None):
                return b""
            plane = frame.planes[0]
            raw = plane.to_bytes() if hasattr(plane, "to_bytes") else bytes(plane)
            if len(raw) < useful:
                log.warning(
                    "PCM incompleto: %d bytes para %d muestras (%d esperados)",
                    len(raw), samples, useful,
                )
                return b""
            # No enviar el padding de alineación de FFmpeg al dispositivo.
            return raw[:useful]
        except (AttributeError, TypeError, ValueError, IndexError):
            return b""

    def _decode_audio(self, packet, resampler, emit_from=0.0, stop_at=None,
                      audio_clock=None, timeline_start=0.0):
        """Decodifica PCM usando una línea de tiempo relativa al corte.

        ``frame.time`` es absoluto dentro del archivo; ``timeline_start``
        permite que el prebuffer comience en mark-in sin reproducir el audio
        anterior al corte. ``emit_from`` y ``stop_at`` están expresados en
        segundos relativos a ese mark-in.
        """
        last_relative = audio_clock[0] if audio_clock else 0.0
        try:
            frames = packet.decode()
            for frame in frames:
                frame_time = frame.time
                if frame_time is None:
                    frame_time = timeline_start + last_relative
                frame_time = max(0.0, float(frame_time))
                converted = resampler.resample(frame)
                if converted is None:
                    continue
                if not isinstance(converted, (list, tuple)):
                    converted = [converted]
                cursor = frame_time - timeline_start
                for out in converted:
                    if not out.planes:
                        continue
                    raw = self._pcm_bytes(out)
                    if not raw:
                        continue
                    out_samples = int(getattr(out, "samples", 0) or 0)
                    out_duration = float(out_samples) / AUDIO_RATE
                    out_end = cursor + out_duration
                    window_end = stop_at if stop_at is not None else out_end
                    if cursor < window_end and out_end > emit_from:
                        # El seek puede devolver un frame que cruza mark-in o
                        # el límite del prebuffer. Recortar por muestras evita
                        # unos milisegundos fuera del corte y evita duplicar
                        # la muestra que cruza la frontera de 6 segundos.
                        first_sample = max(0, int(math.ceil((emit_from - cursor) * AUDIO_RATE - 1e-9)))
                        last_sample = min(out_samples, int(math.ceil((window_end - cursor) * AUDIO_RATE - 1e-9)))
                        if last_sample > first_sample:
                            pcm = raw[first_sample * 4:last_sample * 4]
                            try:
                                samples = array("h")
                                samples.frombytes(pcm)
                                left = samples[0::2]
                                right = samples[1::2]
                                peak_l = max((abs(v) for v in left), default=0) / 32768.0
                                peak_r = max((abs(v) for v in right), default=0) / 32768.0
                                db_l = 20.0 * math.log10(max(1e-5, peak_l))
                                db_r = 20.0 * math.log10(max(1e-5, peak_r))
                                self.levels.emit(db_l, db_r, self.generation)
                            except (TypeError, ValueError, OverflowError):
                                pass
                            self.audio.emit(pcm, self.generation)
                    cursor = out_end
                    last_relative = cursor
                    if stop_at is not None and cursor >= stop_at:
                        if audio_clock is not None:
                            audio_clock[0] = cursor
                        return cursor, True
            if audio_clock is not None:
                audio_clock[0] = last_relative
            return last_relative, False
        except Exception as exc:  # noqa: BLE001
            log.debug("audio decode %s: %s", self.path, exc)
            if audio_clock is not None:
                audio_clock[0] = last_relative
            return last_relative, False

    def run(self):
        if av is None:
            self.error.emit("PyAV no está instalado", self.generation)
            self.finished.emit("error", self.generation)
            return
        if not os.path.isfile(self.path):
            self.error.emit(f"archivo no encontrado: {self.path}", self.generation)
            self.finished.emit("error", self.generation)
            return

        first_open = True
        try:
            while not self.stop_event.is_set():
                container = None
                try:
                    container = av.open(self.path)
                    videos = list(container.streams.video)
                    audios = list(container.streams.audio)
                    subtitles = list(container.streams.subtitles)
                    video_stream = videos[0] if videos else None
                    audio_stream = audios[0] if audios else None
                    subtitle_stream = None
                    if isinstance(self.audio_id, int) and 0 <= self.audio_id < len(audios):
                        audio_stream = audios[self.audio_id]
                    if isinstance(self.subtitle_id, int) and self.subtitle_id >= 0 and self.subtitle_id < len(subtitles):
                        subtitle_stream = subtitles[self.subtitle_id]
                    self._subtitle_events = []
                    source_duration = self._duration(container, video_stream, audio_stream)
                    start_at = min(self.start_at, source_duration) if source_duration > 0 else self.start_at
                    end_at = self.end_at if self.end_at > 0 else source_duration
                    if source_duration > 0:
                        end_at = min(end_at, source_duration)
                    if end_at > 0 and end_at < start_at:
                        end_at = start_at
                    duration = max(0.0, end_at - start_at) if end_at > 0 else 0.0
                    info = {
                        "duration": duration,
                        "source_duration": source_duration,
                        "mark_in": start_at,
                        "mark_out": end_at if end_at < source_duration else 0.0,
                        "video": self._stream_info(video_stream),
                        "audio": self._stream_info(audio_stream),
                        "subtitle": self._stream_info(subtitle_stream),
                        "subtitle_id": self.subtitle_id,
                    }
                    opening_first = first_open
                    if opening_first:
                        self.loaded.emit(info, self.generation)
                        first_open = False
                        log.info(
                            "PyAV abierto gen=%d path=%s duration=%.3fs video=%s audio=%s",
                            self.generation, self.path, duration, info["video"], info["audio"],
                        )
                        log.info("PyAV pistas seleccionadas gen=%d audio_id=%s subtitle_id=%s subtitle=%s",
                                 self.generation, self.audio_id, self.subtitle_id, info["subtitle"])

                    streams = [s for s in (video_stream, audio_stream, subtitle_stream) if s is not None]
                    if not streams:
                        raise RuntimeError("el archivo no contiene pistas de vídeo ni audio")
                    resampler = None
                    if audio_stream is not None:
                        resampler = av.audio.resampler.AudioResampler(
                            format="s16", layout="stereo", rate=AUDIO_RATE
                        )

                    # Prebuffer real de seis segundos, comenzando en
                    # mark-in. El archivo original nunca se modifica: sólo
                    # se desplaza la línea de tiempo de lectura.
                    audio_skip_until = 0.0
                    if opening_first and audio_stream is not None and resampler is not None:
                        audio_clock = [0.0]
                        reached = False
                        container.seek(int(start_at * float(av.time_base)), backward=True, any_frame=False)
                        prebuffer_limit = min(AUDIO_PREBUFFER_SECONDS, duration) if duration > 0 else AUDIO_PREBUFFER_SECONDS
                        for audio_packet in container.demux(audio_stream):
                            if self.stop_event.is_set():
                                break
                            _end, reached = self._decode_audio(
                                audio_packet, resampler, emit_from=0.0,
                                stop_at=prebuffer_limit, audio_clock=audio_clock,
                                timeline_start=start_at,
                            )
                            if reached:
                                audio_skip_until = prebuffer_limit
                                break
                        if not reached:
                            # Clip corto o sin duración declarada: ya quedó
                            # toda la pista disponible en la cola.
                            audio_skip_until = audio_clock[0]
                        if not self.stop_event.is_set():
                            container.seek(int(start_at * float(av.time_base)), backward=True, any_frame=False)
                            # El resampler puede conservar muestras de cola;
                            # reiniciarlo evita repetir audio tras el seek.
                            resampler = av.audio.resampler.AudioResampler(
                                format="s16", layout="stereo", rate=AUDIO_RATE
                            )
                        log.info("PyAV audio prebuffer gen=%d start=%.3f seconds=%.3f reached=%s",
                                 self.generation, start_at, audio_clock[0], reached)
                    if not self.stop_event.is_set():
                        self.ready.emit(self.generation)

                    base_raw = start_at
                    clock_origin = time.monotonic()
                    audio_clock = [audio_skip_until]
                    clip_finished = False
                    for packet in container.demux(*streams):
                        if self.stop_event.is_set():
                            break
                        requested = self._take_seek()
                        if requested is not None:
                            requested = max(start_at, float(requested))
                            if end_at > 0:
                                requested = min(requested, end_at)
                            log.info("PyAV seek gen=%d target=%.3f", self.generation, requested)
                            container.seek(int(requested * float(av.time_base)), backward=True, any_frame=False)
                            base_raw = start_at
                            audio_skip_until = max(0.0, requested - start_at)
                            audio_clock = [audio_skip_until]
                            clock_origin = time.monotonic() - audio_skip_until
                            continue
                        if packet.stream == subtitle_stream and subtitle_stream is not None:
                            self._remember_subtitle_packet(subtitle_stream, packet, start_at)
                            continue
                        if packet.stream == audio_stream and resampler is not None:
                            self._decode_audio(
                                packet, resampler, emit_from=audio_skip_until,
                                stop_at=duration if duration > 0 else None,
                                audio_clock=audio_clock,
                                timeline_start=start_at,
                            )
                            continue
                        if packet.stream != video_stream:
                            continue
                        for frame in packet.decode():
                            if self.stop_event.is_set():
                                break
                            raw_time = frame.time
                            if raw_time is None:
                                raw_time = base_raw
                            raw_time = float(raw_time)
                            if raw_time < start_at:
                                continue
                            if end_at > 0 and raw_time >= end_at:
                                clip_finished = True
                                break
                            position = max(0.0, raw_time - start_at)
                            clock_origin = self._wait_until(position, clock_origin)
                            if self.stop_event.is_set():
                                break
                            image = self._frame_image(frame)
                            image = self._paint_subtitle(image, self._subtitle_for_position(position))
                            self.frame.emit(image, position, duration, self.generation)
                        if clip_finished:
                            break
                    if self.stop_event.is_set():
                        break
                    if not self.loop:
                        self.finished.emit("eof", self.generation)
                        return
                    log.debug("PyAV loop gen=%d path=%s", self.generation, self.path)
                finally:
                    if container is not None:
                        try:
                            container.close()
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("PyAV error gen=%d path=%s", self.generation, self.path)
            self.error.emit(str(exc), self.generation)
            self.finished.emit("error", self.generation)
            return
        self.finished.emit("stop", self.generation)


class PyAVPlayer(QObject):
    """API compatible con el reproductor anterior, sin depender de mpv."""

    status = Signal(str)
    ended = Signal(str)
    loaded = Signal()
    position = Signal(float, float)
    levels = Signal(float, float)
    ndi_frame = Signal(object, float, float)  # QImage, posición, duración
    ndi_audio = Signal(object)                # PCM s16le estéreo
    idle = Signal(bool)
    process_died = Signal()

    def __init__(self, video_widget, mpv_path="", parent=None, vlc_path=""):
        super().__init__(parent)
        self.widget = video_widget
        self.preview_mpv_path = mpv_path or ""
        # v24.0.2.32: VLC como reproductor alternativo para la vista previa.
        self.preview_vlc_path = vlc_path or ""
        self.proc = None
        self.ipc_path = None
        self.hwdec = "software/libav"
        self.audio_device = ""
        self.alang = "es-MX,es-419,spa,es"
        self.slang = ""
        self.volume = 100
        self.muted = False
        self._current_path = ""
        self._time = 0.0
        self._duration = 0.0
        self._running = False
        self._paused = False
        self._loop = False
        self._trim_start = 0.0
        self._trim_end = 0.0
        self._program_overlay = QImage()
        self._program_overlay_interval = 1080.0
        self._program_overlay_duration = 15.0
        self._generation = 0
        self._job = None
        self._thread = None
        self._audio_queue = bytearray()
        self._ndi_audio_enabled = False
        self._audio_io = None
        self._audio_sink = None
        self._audio_format = None
        self._target_volume = 1.0
        self._audio_timer = QTimer(self)
        self._audio_timer.setInterval(10)
        self._audio_timer.timeout.connect(self._drain_audio)
        self._setup_audio()
        try:
            self.widget.resized.connect(lambda: log.debug(
                "VideoSurface resized %dx%d visible=%s", self.widget.width(), self.widget.height(), self.widget.isVisible()
            ))
        except AttributeError:
            pass
        log.info("PyAVPlayer inicializado available=%s QAudioSink=%s", self.available, bool(self._audio_sink))

    @property
    def available(self):
        return av is not None

    @property
    def running(self):
        return bool(self._running and self._thread and self._thread.is_alive())

    @property
    def current_path(self):
        return self._current_path

    def _setup_audio(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(AUDIO_RATE)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._audio_format = fmt
            self._audio_sink = QAudioSink(fmt, self)
            # Preparamos seis segundos en el monitor para que PyAV pueda
            # alinear el audio PCM con los frames de vídeo. RTMP no usa este
            # sink y queda completamente independiente.
            self._audio_sink.setBufferSize(AUDIO_BUFFER_BYTES)
            self._audio_sink.setVolume(1.0)
        except Exception as exc:  # noqa: BLE001
            self._audio_sink = None
            log.warning("QAudioSink no disponible: %s", exc)

    def _start_audio(self):
        # El prebuffer ya está en _audio_queue; no se puede limpiar aquí.
        # stop()/seek() ya vacían la cola antes de iniciar otra sesión.
        self._target_volume = max(0.0, min(1.0, float(self.volume) / 100.0))
        if self._audio_sink is None:
            return
        try:
            self._audio_sink.stop()
            self._audio_sink.setVolume(0.0 if self.muted else self._target_volume)
            self._audio_io = self._audio_sink.start()
            self._audio_timer.start()
            log.debug("QAudioSink iniciado rate=%d channels=2 buffer=%dB volume=%.2f",
                      AUDIO_RATE, AUDIO_BUFFER_BYTES, self._target_volume)
        except Exception as exc:  # noqa: BLE001
            self._audio_io = None
            log.warning("No se pudo iniciar QAudioSink: %s", exc)

    def _stop_audio(self):
        self._ndi_audio_enabled = False
        self._audio_timer.stop()
        self._audio_queue.clear()
        self._audio_io = None
        if self._audio_sink is not None:
            try:
                self._audio_sink.stop()
            except Exception:  # noqa: BLE001
                pass

    def _queue_audio(self, data, generation):
        if generation != self._generation or not data:
            return
        # Mantener como máximo aproximadamente un segundo de PCM para que un
        # decoder lento no acumule latencia infinita.
        pcm = bytes(data)
        # El prebuffer local de seis segundos no debe salir antes del primer
        # frame NDI: habilitamos el envío cuando PyAV emite ready.
        if self._ndi_audio_enabled:
            self.ndi_audio.emit(pcm)
        self._audio_queue.extend(pcm)
        if len(self._audio_queue) > AUDIO_QUEUE_LIMIT:
            # Nunca conservar un segundo completo de audio: ese backlog se
            # escucha como desfase. Se conserva solo la ventana corta del
            # monitor local y la salida RTMP queda completamente separada.
            del self._audio_queue[:-AUDIO_QUEUE_LIMIT]

    def _drain_audio(self):
        if not self._audio_io or self._audio_sink is None or not self._audio_queue:
            return
        try:
            free = max(0, int(self._audio_sink.bytesFree()))
            # QAudioSink/Media Foundation puede devolver MF_E_NOTACCEPTING
            # (0xC00D36B5) si recibe los seis segundos de prebuffer de golpe.
            # Transferimos solo un intervalo de audio por tick: la cola de
            # seis segundos permanece en Python, pero el dispositivo recibe
            # PCM a velocidad real y no se desborda el resampler de Windows.
            budget = max(1, int(AUDIO_BYTES_PER_SECOND * 0.010))
            while free and self._audio_queue and budget > 0:
                n = min(free, len(self._audio_queue), budget)
                written = int(self._audio_io.write(bytes(self._audio_queue[:n])))
                if written <= 0:
                    break
                del self._audio_queue[:written]
                free -= written
                budget -= written
        except Exception as exc:  # noqa: BLE001
            log.debug("QAudioSink write: %s", exc)

    def _disconnect_job(self, job):
        if job is None:
            return
        try:
            job.stop()
        except Exception:  # noqa: BLE001
            pass

    def start(self):
        if not self.available:
            self.status.emit("PyAV no está instalado; ejecuta INSTALL.bat")
            return False
        return True

    def _begin(self, path, loop=False, audio_id=None, sub_id=None, start=0.0, end=0.0):
        absolute = os.path.abspath(path)
        if not os.path.isfile(absolute):
            log.error("PyAV source missing path=%s", absolute)
            self.status.emit("PyAV: archivo no encontrado")
            return False
        self._generation += 1
        generation = self._generation
        self._ndi_audio_enabled = False
        self._disconnect_job(self._job)
        self._stop_audio()
        self._trim_start = max(0.0, float(start or 0.0))
        self._trim_end = max(0.0, float(end or 0.0))
        self._job = _DecodeJob(absolute, generation, loop=loop, audio_id=audio_id,
                               subtitle_id=sub_id, start_at=self._trim_start, end_at=self._trim_end)
        self._job.loaded.connect(self._on_loaded)
        self._job.ready.connect(self._on_ready)
        self._job.frame.connect(self._on_frame)
        self._job.audio.connect(self._queue_audio)
        self._job.levels.connect(self._on_levels)
        self._job.finished.connect(self._on_finished)
        self._job.error.connect(self._on_error)
        self._thread = threading.Thread(target=self._job.run, name=f"pyav-{generation}", daemon=True)
        self._current_path = absolute
        self._time = 0.0
        self._duration = 0.0
        self._running = True
        self._paused = False
        self._loop = bool(loop)
        self.widget.set_active(True, "")
        self.widget.clear_frame()
        self._thread.start()
        log.info("PyAV play request gen=%d loop=%s path=%s size=%d bytes", generation, loop, absolute, os.path.getsize(absolute))
        self.status.emit("PyAV ▶ " + os.path.basename(absolute))
        return True

    def play(self, path, audio_id=None, sub_id=None, start=0.0, end=0.0, loop=False):
        if not self.start():
            return False
        ok = self._begin(path, loop=loop, audio_id=audio_id, sub_id=sub_id, start=start, end=end)
        log.debug("PyAV track request gen=%d audio_id=%s subtitle_id=%s trim=%.3f..%.3f",
                  self._generation, audio_id, sub_id, self._trim_start, self._trim_end)
        return ok

    def play_loop(self, path):
        # El slate lavfi anterior se dibuja ahora directamente en Qt.
        if str(path).startswith("av://"):
            self.stop()
            self._generation += 1
            self._current_path = str(path)
            self._running = True
            self._loop = True
            self.widget.clear_frame()
            self.widget.set_active(False, "TVPlayout PRO\nPROXIMAMENTE")
            self.status.emit("PyAV ▶ slate nativo")
            log.info("slate nativo PyAV path=%s", path)
            return True
        return self.play(path, loop=True)

    def stop(self):
        log.info("PyAV stop gen=%d path=%s pos=%.3f", self._generation, self._current_path, self._time)
        self._generation += 1
        self._disconnect_job(self._job)
        self._job = None
        self._thread = None
        self._stop_audio()
        self._running = False
        self._current_path = ""
        self._trim_start = 0.0
        self._trim_end = 0.0
        self.widget.clear_frame()
        self.idle.emit(True)
        return True

    def shutdown(self):
        self.stop()
        log.info("PyAVPlayer shutdown")

    def _on_loaded(self, info, generation):
        if generation != self._generation:
            return
        self._duration = float(info.get("duration", 0.0) or 0.0)
        log.info("PyAV loaded gen=%d duration=%.3fs info=%s", generation, self._duration, info)
        self.loaded.emit()
        self.position.emit(self._time, self._duration)
        self.idle.emit(False)

    def _on_ready(self, generation):
        if generation != self._generation:
            return
        self._ndi_audio_enabled = True
        log.info("PyAV monitor audio ready gen=%d buffer=%.1fs", generation, AUDIO_PREBUFFER_SECONDS)
        self._start_audio()

    def set_program_overlay(self, path="", interval_seconds=1080.0, duration_seconds=15.0):
        """Configura la tarjeta TMDB periódica sobre monitor y NDI."""
        self._program_overlay = QImage(str(path)) if path else QImage()
        self._program_overlay_interval = max(1.0, float(interval_seconds or 1080.0))
        self._program_overlay_duration = max(0.0, float(duration_seconds or 15.0))

    def _paint_program_overlay(self, image, position):
        overlay = self._program_overlay
        if overlay.isNull() or self._program_overlay_duration <= 0:
            return image
        phase = float(position or 0.0) % self._program_overlay_interval
        if phase > self._program_overlay_duration:
            return image
        if overlay.size() != image.size():
            overlay = overlay.scaled(image.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        try:
            painter = QPainter(image)
            painter.drawImage(0, 0, overlay)
            painter.end()
        except Exception as exc:  # noqa: BLE001
            log.debug("program overlay paint: %s", exc)
        return image

    def _on_frame(self, image, position, duration, generation):
        if generation != self._generation:
            return
        self._time = max(0.0, float(position))
        if duration > 0:
            self._duration = float(duration)
        image = self._paint_program_overlay(image, self._time)
        self.widget.set_frame(image)
        self.ndi_frame.emit(image, self._time, self._duration)
        self.position.emit(self._time, self._duration)

    def _on_levels(self, left, right, generation):
        if generation == self._generation:
            self.levels.emit(float(left), float(right))

    def _on_error(self, message, generation):
        if generation != self._generation:
            return
        log.error("PyAV error gen=%d path=%s: %s", generation, self._current_path, message)
        self.status.emit("PyAV: " + str(message))

    def _on_finished(self, reason, generation):
        if generation != self._generation:
            return
        if reason == "stop":
            return
        log.info("PyAV finished gen=%d reason=%s path=%s", generation, reason, self._current_path)
        self._stop_audio()
        self._running = False
        if reason in ("eof", "error"):
            self.widget.clear_frame()
            self.ended.emit(reason)
            self.idle.emit(True)

    def set_pause(self, paused):
        self._paused = bool(paused)
        if self._job:
            self._job.set_paused(self._paused)
        if self._audio_sink is not None:
            try:
                self._audio_sink.suspend() if self._paused else self._audio_sink.resume()
            except Exception as exc:  # noqa: BLE001
                log.debug("QAudioSink pause: %s", exc)
        log.info("PyAV pause=%s gen=%d pos=%.3f", self._paused, self._generation, self._time)
        return True

    def set_mute(self, muted):
        self.muted = bool(muted)
        if self._audio_sink is not None:
            self._audio_sink.setVolume(0.0 if self.muted else self._target_volume)
        return True

    def set_volume(self, value):
        self.volume = max(0, min(100, int(value)))
        self._target_volume = self.volume / 100.0
        if self._audio_sink is not None:
            self._audio_sink.setVolume(0.0 if self.muted else self._target_volume)
        return True

    def seek(self, seconds, absolute=False):
        target = float(seconds) if absolute else self._time + float(seconds)
        target = max(0.0, target)
        if self._duration > 0:
            target = min(target, self._duration)
        source_target = self._trim_start + target
        if self._job:
            self._job.seek(source_target)
            self._time = target
            self._stop_audio()
            if self._running:
                self._start_audio()
            self.position.emit(self._time, self._duration)
        log.info("PyAV seek gen=%d target=%.3f source=%.3f absolute=%s",
                 self._generation, target, source_target, absolute)
        return True

    def set_property(self, name, value):
        if name == "video-aspect-override":
            self.widget.set_aspect_mode(value)
        return True

    def set_track_langs(self, alang, slang):
        self.alang, self.slang = alang, slang
        log.debug("PyAV track preference audio=%s subtitle=%s", alang, slang)

    def open_external_preview(self, path, title="PREVIEW"):
        """La previsualización es opcional y separada del aire PyAV.

        v24.0.2.32: usa mpv si está disponible y VLC como alternativa. El
        resultado se informa por la señal de estado para que la ventana
        pueda avisar con un cuadro claro si no hay ningún reproductor.
        """
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        candidates = []
        if self.preview_mpv_path and os.path.isfile(self.preview_mpv_path):
            candidates.append(("mpv", [self.preview_mpv_path,
                                       f"--title={title} — {os.path.basename(path)}", "--force-window=yes",
                                       "--keep-open=yes", "--osc=yes", "--geometry=40%", "--no-terminal", path]))
        if self.preview_vlc_path and os.path.isfile(self.preview_vlc_path):
            candidates.append(("VLC", [self.preview_vlc_path, "--no-one-instance", "--no-video-title-show",
                                       f"--meta-title={title} — {os.path.basename(path)}", path]))
        for name, cmd in candidates:
            try:
                subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.status.emit(f"Preview abierto en {name} • {os.path.basename(path)}")
                return True
            except Exception as exc:  # noqa: BLE001
                log.debug("Preview con %s falló: %s", name, exc)
        self.status.emit("Preview externo: no se encontró mpv.exe ni VLC")
        return False
