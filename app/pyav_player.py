"""Reproductor local basado en PyAV/libavcodec.

El aire local no depende de mpv, IPC, named pipes ni QMediaPlayer. PyAV abre
el contenedor y decodifica vídeo/audio en un hilo de trabajo; los frames RGB
se entregan a ``VideoSurface`` y el audio PCM se reproduce con QAudioSink.
FFmpeg sigue siendo el motor de la salida RTMP.
"""
from __future__ import annotations

import math
import os
import threading
import time
from array import array
try:
    import av
except ImportError:  # La aplicación puede arrancar y explicar la dependencia.
    av = None

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage
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

    def __init__(self, path, generation, loop=False, audio_id=None, parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.generation = generation
        self.loop = bool(loop)
        self.audio_id = audio_id
        self.stop_event = threading.Event()
        self._condition = threading.Condition()
        self._paused = False
        self._seek_request = None

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

    def _decode_audio(self, packet, resampler, emit_from=0.0, stop_at=None, audio_clock=None):
        """Decodifica PCM y opcionalmente lo limita a una ventana temporal.

        Durante el prebuffer se emiten los primeros seis segundos. En la
        reproducción normal se omite esa misma ventana porque ya está en la
        cola del monitor; así el audio no vuelve a empezar desde cero cuando
        comienza el vídeo.
        """
        last_time = audio_clock[0] if audio_clock else 0.0
        try:
            frames = packet.decode()
            for frame in frames:
                frame_time = frame.time
                if frame_time is None:
                    frame_time = last_time
                frame_time = max(0.0, float(frame_time))
                converted = resampler.resample(frame)
                if converted is None:
                    continue
                if not isinstance(converted, (list, tuple)):
                    converted = [converted]
                cursor = frame_time
                for out in converted:
                    if not out.planes:
                        continue
                    raw = bytes(out.planes[0])
                    out_duration = float(getattr(out, "samples", 0) or 0) / AUDIO_RATE
                    out_end = cursor + out_duration
                    if (cursor < (stop_at if stop_at is not None else float("inf"))
                            and out_end > emit_from):
                        try:
                            samples = array("h")
                            samples.frombytes(raw)
                            left = samples[0::2]
                            right = samples[1::2]
                            peak_l = max((abs(v) for v in left), default=0) / 32768.0
                            peak_r = max((abs(v) for v in right), default=0) / 32768.0
                            db_l = 20.0 * math.log10(max(1e-5, peak_l))
                            db_r = 20.0 * math.log10(max(1e-5, peak_r))
                            self.levels.emit(db_l, db_r, self.generation)
                        except (TypeError, ValueError, OverflowError):
                            pass
                        self.audio.emit(raw, self.generation)
                    cursor = out_end
                    last_time = cursor
                    if stop_at is not None and cursor >= stop_at:
                        if audio_clock is not None:
                            audio_clock[0] = cursor
                        return cursor, True
            if audio_clock is not None:
                audio_clock[0] = last_time
            return last_time, False
        except Exception as exc:  # noqa: BLE001
            log.debug("audio decode %s: %s", self.path, exc)
            if audio_clock is not None:
                audio_clock[0] = last_time
            return last_time, False

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
                    video_stream = videos[0] if videos else None
                    audio_stream = audios[0] if audios else None
                    if isinstance(self.audio_id, int) and 0 <= self.audio_id < len(audios):
                        audio_stream = audios[self.audio_id]
                    duration = self._duration(container, video_stream, audio_stream)
                    info = {
                        "duration": duration,
                        "video": self._stream_info(video_stream),
                        "audio": self._stream_info(audio_stream),
                    }
                    opening_first = first_open
                    if opening_first:
                        self.loaded.emit(info, self.generation)
                        first_open = False
                        log.info(
                            "PyAV abierto gen=%d path=%s duration=%.3fs video=%s audio=%s",
                            self.generation, self.path, duration, info["video"], info["audio"],
                        )

                    streams = [s for s in (video_stream, audio_stream) if s is not None]
                    if not streams:
                        raise RuntimeError("el archivo no contiene pistas de vídeo ni audio")
                    resampler = None
                    if audio_stream is not None:
                        resampler = av.audio.resampler.AudioResampler(
                            format="s16", layout="stereo", rate=AUDIO_RATE
                        )

                    # Prebuffer real de seis segundos. El audio se decodifica
                    # rápido mientras se descartan los paquetes de vídeo; al
                    # terminar se vuelve al inicio para que vídeo y audio
                    # comiencen juntos en t=0.
                    audio_skip_until = 0.0
                    if opening_first and audio_stream is not None and resampler is not None:
                        audio_clock = [0.0]
                        reached = False
                        for audio_packet in container.demux(audio_stream):
                            if self.stop_event.is_set():
                                break
                            _end, reached = self._decode_audio(
                                audio_packet, resampler, emit_from=0.0,
                                stop_at=AUDIO_PREBUFFER_SECONDS, audio_clock=audio_clock,
                            )
                            if reached:
                                audio_skip_until = AUDIO_PREBUFFER_SECONDS
                                break
                        if not reached:
                            # Clip corto: ya quedó toda su pista en la
                            # cola, por lo que no se debe emitir dos veces.
                            audio_skip_until = audio_clock[0]
                        if not self.stop_event.is_set():
                            container.seek(0, backward=True, any_frame=False)
                            # El resampler puede conservar muestras de cola;
                            # reiniciarlo evita repetir audio tras el seek.
                            resampler = av.audio.resampler.AudioResampler(
                                format="s16", layout="stereo", rate=AUDIO_RATE
                            )
                        log.info("PyAV audio prebuffer gen=%d seconds=%.3f reached=%s",
                                 self.generation, audio_clock[0], reached)
                    if not self.stop_event.is_set():
                        self.ready.emit(self.generation)

                    base_raw = None
                    logical_base = 0.0
                    clock_origin = time.monotonic()
                    audio_clock = [0.0]
                    for packet in container.demux(*streams):
                        if self.stop_event.is_set():
                            break
                        requested = self._take_seek()
                        if requested is not None:
                            log.info("PyAV seek gen=%d target=%.3f", self.generation, requested)
                            container.seek(int(requested * float(av.time_base)), backward=True, any_frame=False)
                            base_raw = None
                            logical_base = requested
                            clock_origin = time.monotonic() - requested
                            continue
                        if packet.stream == audio_stream and resampler is not None:
                            self._decode_audio(
                                packet, resampler, emit_from=audio_skip_until,
                                audio_clock=audio_clock,
                            )
                            continue
                        if packet.stream != video_stream:
                            continue
                        for frame in packet.decode():
                            if self.stop_event.is_set():
                                break
                            raw_time = frame.time
                            if raw_time is None:
                                raw_time = 0.0 if base_raw is None else base_raw
                            raw_time = float(raw_time)
                            if base_raw is None:
                                base_raw = raw_time
                            position = max(0.0, logical_base + raw_time - base_raw)
                            clock_origin = self._wait_until(position, clock_origin)
                            if self.stop_event.is_set():
                                break
                            image = self._frame_image(frame)
                            self.frame.emit(image, position, duration, self.generation)
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
    idle = Signal(bool)
    process_died = Signal()

    def __init__(self, video_widget, mpv_path="", parent=None):
        super().__init__(parent)
        self.widget = video_widget
        self.preview_mpv_path = mpv_path or ""
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
        self._generation = 0
        self._job = None
        self._thread = None
        self._audio_queue = bytearray()
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
        self._audio_queue.extend(bytes(data))
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
            while free and self._audio_queue:
                n = min(free, len(self._audio_queue), 16384)
                written = int(self._audio_io.write(bytes(self._audio_queue[:n])))
                if written <= 0:
                    break
                del self._audio_queue[:written]
                free -= written
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

    def _begin(self, path, loop=False, audio_id=None):
        absolute = os.path.abspath(path)
        if not os.path.isfile(absolute):
            log.error("PyAV source missing path=%s", absolute)
            self.status.emit("PyAV: archivo no encontrado")
            return False
        self._generation += 1
        generation = self._generation
        self._disconnect_job(self._job)
        self._stop_audio()
        self._job = _DecodeJob(absolute, generation, loop=loop, audio_id=audio_id)
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

    def play(self, path, audio_id=None, sub_id=None, start=0.0, loop=False):
        if not self.start():
            return False
        ok = self._begin(path, loop=loop, audio_id=audio_id)
        log.debug("PyAV track request gen=%d audio_id=%s subtitle_id=%s", self._generation, audio_id, sub_id)
        if ok and start and self._job:
            self._job.seek(float(start))
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
        log.info("PyAV monitor audio ready gen=%d buffer=%.1fs", generation, AUDIO_PREBUFFER_SECONDS)
        self._start_audio()

    def _on_frame(self, image, position, duration, generation):
        if generation != self._generation:
            return
        self._time = max(0.0, float(position))
        if duration > 0:
            self._duration = float(duration)
        self.widget.set_frame(image)
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
        if self._job:
            self._job.seek(target)
            self._time = target
            self._stop_audio()
            if self._running:
                self._start_audio()
            self.position.emit(self._time, self._duration)
        log.info("PyAV seek gen=%d target=%.3f absolute=%s", self._generation, target, absolute)
        return True

    def set_property(self, name, value):
        if name == "video-aspect-override":
            self.widget.set_aspect_mode(value)
        return True

    def set_track_langs(self, alang, slang):
        self.alang, self.slang = alang, slang
        log.debug("PyAV track preference audio=%s subtitle=%s", alang, slang)

    def open_external_preview(self, path, title="PREVIEW"):
        """La previsualización es opcional y separada del aire PyAV."""
        if not self.preview_mpv_path or not os.path.isfile(self.preview_mpv_path):
            self.status.emit("Preview externo: mpv.exe no encontrado")
            return False
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [self.preview_mpv_path, f"--title={title} — {os.path.basename(path)}", "--force-window=yes",
               "--keep-open=yes", "--osc=yes", "--geometry=40%", "--no-terminal", path]
        try:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Preview: {exc}")
            return False
