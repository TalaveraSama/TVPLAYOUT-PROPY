"""Motor de emisión continua estilo OBS: dos mundos separados.

Arquitectura replicada de OBS Studio:

  MUNDO 1 — PRODUCTOR (el "lienzo"): un proceso FFmpeg por clip normaliza el
  contenido (escala, logo, zócalos, subtítulos quemados, DSP de audio) y lo
  codifica a MPEG-TS con **timestamps globales** (``-output_ts_offset``),
  escribiéndolo a un *spool* temporal a ritmo 1x (``-re``).

  MUNDO 2 — CONSUMIDOR (el "camión"): UN solo proceso FFmpeg por destino que
  vive desde "Iniciar Transmisión" hasta "Detener": lee el flujo TS continuo
  por stdin y lo envía a RTMP/SRT/UDP con ``-c copy``. Cambiar de clip, saltar,
  pausar o quedarse sin playlist **nunca reinicia este proceso**: la conexión
  TCP con el servidor (vMix, YouTube, …) permanece abierta.

  LA BOMBA (pump): un hilo por destino lee los spools en orden y escribe los
  bytes al stdin del consumidor. El corte entre clips es un empalme a nivel de
  bytes: el servidor ve un único flujo con timestamps monótonos (validado con
  libav: clips heterogéneos empalmados demuxean con cero saltos hacia atrás).

Si la playlist se vacía, el productor genera spools de barras/pantalla negra
("slate") para que el camión siga rodando. Si la aplicación muere, el stdin
del consumidor recibe EOF (cierra el RTMP con su trailer) y el Job Object de
``proc_tools`` mata a los productores huérfanos.
"""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from . import logger
from . import proc_tools
from .config import APP_SLUG
from .output import (CREATE_NO_WINDOW, OutputWorker, _PROGRESS_RE,
                     _ffmpeg_filter_path, get_or_create_fallback_slate,
                     logo_overlay_position)
from .prober import pick_audio, pick_subtitle
from .ndi_sender import logo_suppressed_for_category
from .audio_processor import build_audio_filters
from .music_titling import is_music_item

log = logger.get("feed")

_URL_RE = re.compile(r"^(https?|rtmp|rtmps|srt|udp|rtsp)://", re.IGNORECASE)


class _Segment:
    """Un spool TS: el contenido listo-para-emitir de un evento de la playlist."""

    __slots__ = ("seq", "path", "index", "item", "item_offset", "t_start",
                 "duration", "proc", "done", "failed", "dead", "started_at",
                 "last_size", "last_growth_at", "finished_emitted")

    def __init__(self, seq, path, index, item, item_offset, t_start, duration):
        self.seq = seq
        self.path = path
        self.index = index              # índice en la playlist (-1 = slate)
        self.item = item                # dict del item (None para slate)
        self.item_offset = item_offset  # offset de arranque dentro del clip
        self.t_start = t_start          # inicio en la línea de tiempo global
        self.duration = max(0.0, float(duration or 0.0))
        self.proc = None                # proceso productor
        self.done = False               # el productor terminó de escribir
        self.failed = False             # el productor terminó con error
        self.dead = False               # abandonado (salto/conmutación)
        self.started_at = time.time()
        self.last_size = 0
        self.last_growth_at = time.time()
        self.finished_emitted = False

    @property
    def t_end(self):
        return self.t_start + self.duration

    @property
    def is_slate(self):
        return self.index < 0 or not self.item

    def producing(self):
        return self.proc is not None and self.proc.poll() is None


class _Pump(threading.Thread):
    """Hilo por destino: alimenta el consumidor persistente con bytes de spool."""

    CHUNK = 512 * 1024

    def __init__(self, engine, label, is_master):
        super().__init__(name=f"feed-pump-{label}", daemon=True)
        self.engine = engine
        self.label = label
        self.is_master = is_master
        self.consumer = None
        self.stdin = None
        self.cur_seq = -1          # segmento que se está escribiendo al pipe
        self._last_seq = -1        # último segmento terminado o abandonado
        self._inside = False       # True mientras alimenta cur_seq
        self._fh = None            # fd propio del spool en curso
        self._offset = 0           # posición de byte dentro del spool
        self.air_time = -1.0       # último time= del consumidor (línea global)
        self._reconnect_backoff = 1.0
        self._stderr_thread = None

    # ------------------------------------------------------------- consumer
    def _consumer_cmd(self):
        e = self.engine
        low = str(e.url).lower()
        cmd = [e.ffmpeg, "-hide_banner", "-loglevel", "warning", "-stats",
               "-re", "-f", "mpegts", "-i", "pipe:0",
               "-map", "0:v:0", "-map", "0:a:0?",
               "-c", "copy",
               "-max_muxing_queue_size", "4096",
               "-flush_packets", "0",
               "-muxdelay", f"{e.output_buffer_seconds:.3f}",
               "-muxpreload", f"{e.output_buffer_seconds:.3f}",
               "-max_interleave_delta", str(int(e.output_buffer_seconds * 1000000))]
        if e.protocol == "RTMP" or low.startswith(("rtmp://", "rtmps://")):
            if e.monitor_feed_url:
                tee = (f"[f=flv:onfail=ignore]{e.url}|"
                       f"[f=mpegts:onfail=ignore]{e.monitor_feed_url}")
                cmd += ["-flvflags", "no_duration_filesize", "-f", "tee", tee]
            else:
                cmd += ["-flvflags", "no_duration_filesize", "-f", "flv", e.url]
        elif e.monitor_feed_url:
            tee = f"[f=mpegts:onfail=ignore]{e.url}|[f=mpegts:onfail=ignore]{e.monitor_feed_url}"
            cmd += ["-f", "tee", tee]
        else:
            cmd += ["-f", "mpegts", e.url]
        return cmd

    def _start_consumer(self):
        try:
            self.consumer = proc_tools.popen(
                self._consumer_cmd(),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        except Exception as exc:  # noqa: BLE001
            self.engine.log.emit(f"[{self.label}] no se pudo abrir el consumidor: {exc}")
            return False
        self.stdin = self.consumer.stdin
        self._reconnect_backoff = 1.0
        self.air_time = -1.0
        if self.is_master:
            self.engine.state.emit(
                True, f"{self.engine.protocol} ON AIR • motor continuo persistente • "
                      f"{self.engine.resolution}@{self.engine.fps} • {self.engine.bitrate} kbps")
            self.engine.log.emit(
                f"[{self.label}] consumidor persistente activo — la conexión "
                f"{self.engine.protocol} no se reinicia al cambiar de clip")
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name=f"feed-stderr-{self.label}", daemon=True)
        self._stderr_thread.start()
        return True

    def _drain_stderr(self):
        proc = self.consumer
        try:
            # TextIOWrapper con newline=None traduce los «\r» de las líneas
            # -stats (FFmpeg no usa «\n»); en modo binario jamái llegarían.
            import io
            stream = io.TextIOWrapper(proc.stderr, encoding="utf-8",
                                      errors="replace", newline=None)
            for line in stream:
                line = line.rstrip()
                if not line:
                    continue
                m = _PROGRESS_RE.search(line)
                if m and ("frame=" in line or "speed=" in line):
                    try:
                        t = (int(m.group(1)) * 3600.0 + int(m.group(2)) * 60.0
                             + float(m.group(3)))
                        if t >= 0:
                            self.air_time = t
                            if self.is_master:
                                self.engine._on_air_time(t)
                    except (TypeError, ValueError, IndexError):
                        pass
                    continue
                if any(n in line for n in OutputWorker.NOISE):
                    continue
                self.engine.log.emit(f"[{self.label}] FFmpeg • {line}")
        except Exception:  # noqa: BLE001
            pass

    def _consumer_alive(self):
        return self.consumer is not None and self.consumer.poll() is None

    # ---------------------------------------------------------------- feed
    def run(self):
        while not self.engine.stop_requested:
            if not self._start_consumer():
                time.sleep(min(10.0, self._reconnect_backoff))
                self._reconnect_backoff = min(10.0, self._reconnect_backoff * 2)
                continue
            self._feed_until_consumer_dies()
            if self.engine.stop_requested:
                break
            # El consumidor murió (típicamente la red): reconectar SIN perder
            # la posición — el spool conserva los bytes no entregados.
            self.engine.log.emit(
                f"[{self.label}] consumidor terminó (código {self.consumer.returncode}); "
                f"reconectando…")
            if self.is_master:
                self.engine.state.emit(
                    False, f"{self.engine.protocol} reconectando ({self.label})…")
            self._close_files()
            time.sleep(min(10.0, self._reconnect_backoff))
            self._reconnect_backoff = min(10.0, self._reconnect_backoff * 2)
        self._close_files()

    def _feed_until_consumer_dies(self):
        while not self.engine.stop_requested and self._consumer_alive():
            if self.engine.paused:
                time.sleep(0.1)
                continue
            if not self._inside:
                seg = self.engine._next_segment_for(self._last_seq)
                if seg is None:
                    self.engine._segments_event.wait(0.25)
                    self.engine._segments_event.clear()
                    continue
                if not self._enter_segment(seg):
                    continue
            seg = self.engine._segment_by_seq(self.cur_seq)
            if seg is None or seg.dead:
                # conmutación: el segmento actual fue retirado; saltar al
                # siguiente vivo sin cortar la conexión
                self._inside = False
                self._close_files()
                self._last_seq = max(self._last_seq, self.cur_seq)
                continue
            data = self._read_segment(seg)
            if data:
                try:
                    self.stdin.write(data)
                    self.stdin.flush()
                    self._offset += len(data)
                except (BrokenPipeError, OSError, ValueError):
                    # El consumidor murió a mitad de chunk: reintentar los
                    # mismos bytes con el proceso nuevo.
                    self._offset = max(0, self._offset - len(data))
                    return
            elif seg.producing():
                time.sleep(0.05)     # tail: el productor sigue escribiendo
            else:
                self._advance_past(seg)

    def _read_segment(self, seg):
        if self._fh is None or self._fh.closed:
            try:
                self._fh = open(seg.path, "rb")
                self._fh.seek(self._offset)
            except OSError:
                return b""
        try:
            return self._fh.read(self.CHUNK)
        except OSError:
            return b""

    def _enter_segment(self, seg):
        """Abre el spool y notifica; False si hay que saltarlo (muerto)."""
        self._close_files()
        if seg.dead:
            self._last_seq = seg.seq
            return False
        self.cur_seq = seg.seq
        self._offset = 0
        try:
            self._fh = open(seg.path, "rb")
        except OSError:
            if seg.producing():
                # El productor todavía no creó el archivo (calentando): no es
                # un error. _read_segment lo abrirá cuando haya bytes y el
                # lazo principal hace tail-wait mientras tanto.
                self._inside = True
                self.engine._on_segment_entered(self, seg)
                return True
            seg.failed = True
            self._last_seq = seg.seq
            self.engine._on_segment_exited(self, seg)
            return False
        self._inside = True
        self.engine._on_segment_entered(self, seg)
        return True

    def _advance_past(self, seg):
        """Terminó (o murió) el segmento: notifica y apunta al siguiente."""
        self._close_files()
        self._inside = False
        self._last_seq = seg.seq
        self.engine._on_segment_exited(self, seg)

    def _close_files(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def stop_and_join(self, timeout=4.0):
        """Cierre ordenado: EOF en stdin → el consumidor escribe el trailer
        RTMP y termina solo; si no alcanza, se termina el proceso."""
        self.join(timeout=max(0.5, timeout - 2.0))
        try:
            if self.stdin is not None and not self.stdin.closed:
                self.stdin.close()
        except (OSError, ValueError):
            pass
        proc = self.consumer
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=1.5)
            except Exception:  # noqa: BLE001
                proc_tools.terminate(proc, timeout=1.0)


class ContinuousOutputEngine(OutputWorker):
    """Salida persistente con productor/spool + consumidor único por destino.

    Expone la misma API y señales que ``OutputWorker`` para que
    ``MultiOutputManager`` y la interfaz funcionen sin cambios.
    """

    # Margen entre spools: los saltos de timestamp sólo pueden ser hacia
    # adelante (microcongelamiento invisible), nunca hacia atrás (rompería
    # el muxer FLV del servidor).
    SAFETY = 0.25
    # Segundos antes del fin del segmento actual para empezar a producir el
    # siguiente: absorbe la apertura del archivo (red) y el arranque del
    # codificador, de modo que la transición sea invisible.
    LEAD = 25.0
    # Un productor que no escribe nada en este tiempo se da por colgado.
    PRODUCER_STALL = 30.0
    # Duración de cada spool de slate (barras/negro) en espera.
    SLATE_CHUNK = 600.0
    # Tiempo mínimo entre intentos de producir slate (evita churn si falla).
    SLATE_RETRY = 5.0
    # Bytes de cabeza que debe tener un spool antes de retirar al zombi.
    HEAD_BYTES = 2 * 1024 * 1024

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spool_dir = None
        self._segments = []              # orden cronológico de spools
        self._seg_by_seq = {}
        self._seq_counter = 0
        self._t_cursor = 0.0             # t_start del próximo segmento
        self._pumps = []
        self._paused_flag = False
        self._segments_event = threading.Event()
        self._next_provider = None       # callable(idx) -> (idx, item) | None
        self._switch_zombie = None       # segmento que sigue al aire durante una conmutación
        self._slate_retry_at = 0.0
        self._master_air_time = -1.0
        self._master_air_at = 0.0

    # ------------------------------------------------------------- especulación
    def set_next_provider(self, provider):
        """Instala el proveedor de "¿qué sigue?" del controlador master.

        Permite pre-producir el siguiente evento con anticipación (identificadores,
        tandas, loop) para que las transiciones sean invisibles. Debe devolver
        ``(index, item_dict)`` o ``None``. Si falla, se usa el avance lineal.
        """
        self._next_provider = provider

    def _speculate_next(self, current_index):
        """Elige el siguiente evento a pre-producir (o None → slate)."""
        if callable(self._next_provider):
            try:
                answer = self._next_provider(current_index)
                if answer is None:
                    return None
                if isinstance(answer, dict):
                    if answer.get("path"):
                        return (current_index + 1, answer)
                    return None
                idx, item = answer
                if item and item.get("path"):
                    return (int(idx), item)
            except Exception as exc:  # noqa: BLE001
                log.warning("proveedor de siguiente evento falló: %s", exc)
        # Por defecto: avance lineal con loop (como una lista física).
        items = self.items
        if not items:
            return None
        n = len(items)
        nxt = (current_index + 1) % n if self.loop else current_index + 1
        for _ in range(n):
            if 0 <= nxt < n and items[nxt].get("path"):
                return (nxt, items[nxt])
            nxt = (nxt + 1) % n if self.loop else nxt + 1
            if nxt >= n:
                return None
        return None

    # ------------------------------------------------------------- productor
    def _build_producer_command(self, item, offset, t_start, out_path):
        """FFmpeg que normaliza un clip y escribe el spool TS con t global."""
        source = item["path"]
        is_url = bool(_URL_RE.match(str(source)))
        if not self.ffmpeg or not os.path.isfile(self.ffmpeg):
            raise RuntimeError("FFmpeg no encontrado. Coloca ffmpeg.exe en la raíz del proyecto o define FFMPEG_PATH.")
        if not is_url and (not source or not os.path.isfile(source)):
            raise RuntimeError("Archivo no encontrado: " + str(source))
        low = str(self.url).lower()
        if self.protocol != "NDI" and not low.startswith(("rtmp://", "rtmps://", "srt://", "udp://")):
            raise RuntimeError("La salida debe comenzar por rtmp://, rtmps://, srt:// o udp://")
        try:
            w, h = [int(x) for x in self.resolution.lower().split("x", 1)]
        except Exception:  # noqa: BLE001
            raise RuntimeError("Resolución inválida")
        label, codec = self._resolve_encoder(self.encoder)

        # --- marcas y duración (misma aritmética que _build_command) ---
        try:
            mark_in = max(0.0, float(item.get("mark_in") or 0.0))
            mark_out = max(0.0, float(item.get("mark_out") or 0.0))
            source_duration = max(0.0, float(item.get("source_duration") or item.get("duration") or 0.0))
            if source_duration > 0:
                mark_in = min(mark_in, source_duration)
                if mark_out > 0:
                    mark_out = min(mark_out, source_duration)
            if mark_out > 0 and mark_out < mark_in:
                mark_out = mark_in
            has_trim = mark_in > 0 or mark_out > 0
            trim_duration = (mark_out - mark_in) if mark_out > 0 else max(0.0, source_duration - mark_in)
            local_offset = max(0.0, float(offset or 0.0))
            source_offset = mark_in + local_offset
            remaining_duration = (max(0.0, trim_duration - local_offset)
                                  if has_trim and trim_duration > 0 else 0.0)
        except (TypeError, ValueError):
            mark_in = mark_out = source_offset = local_offset = 0.0
            trim_duration = remaining_duration = 0.0
        # Duración efectiva del segmento en la línea de tiempo global: si no
        # hay -t (archivo sin marcas, hasta EOF natural) se usa la duración
        # conocida del clip para que el reloj y la pre-producción funcionen.
        effective_duration = remaining_duration
        if effective_duration <= 0:
            effective_duration = (max(0.0, trim_duration - local_offset)
                                  if trim_duration > 0
                                  else max(0.0, float(item.get("duration")
                                                      or item.get("source_duration") or 0.0)))

        # --- pistas ---
        tracks = self._tracks_of(item)
        audio_preference = item.get("_live_audio_preference")
        subtitle_preference = item.get("_live_subtitle_preference")
        if audio_preference is None:
            audio_preference = item.get("audio_lang") or self.audio_preference
        if subtitle_preference is None:
            subtitle_preference = item.get("subtitle_lang") or self.subtitle_preference
        aid = pick_audio(tracks, audio_preference)
        subtitle_burn = self.subtitle_burn or str(subtitle_preference or "OFF").upper() != "OFF"
        sid = pick_subtitle(tracks, subtitle_preference) if subtitle_burn else -1

        vf = ["setpts=PTS-STARTPTS",
              f"scale={w}:{h}:force_original_aspect_ratio=decrease",
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
              "setsar=1",
              f"fps={self.fps}", "format=yuv420p"]
        self._cmd_has_subs = False
        if subtitle_burn and sid is not None and sid >= 0 and not self._subs_dropped:
            local_srt = self._local_subtitles(source, sid, source_offset)
            if local_srt:
                vf.insert(0, f"subtitles='{_ffmpeg_filter_path(local_srt)}'")
                self._cmd_has_subs = True

        gop = max(1, int(round(float(self.fps) * self.keyframe_interval)))
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
               "-hwaccel", "none"]
        if is_url:
            if str(source).lower().startswith(("http://", "https://")):
                cmd += ["-reconnect", "1", "-reconnect_at_eof", "1", "-reconnect_streamed", "1",
                        "-reconnect_delay_max", "5"]
            elif str(source).lower().startswith("rtmp"):
                cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
        else:
            cmd += ["-re"]
            if source_offset > 0:
                cmd += ["-ss", f"{source_offset:.3f}"]
        cmd += ["-i", source]

        # --- overlays (logo / tarjeta TMDB / zócalo musical) ---
        logo = (self.logo if (self.logo and os.path.isfile(self.logo.get("path", ""))
                and not logo_suppressed_for_category(item.get("category", ""), self.logo)) else None)
        program = (self.program_overlay if (self.program_overlay and os.path.isfile(self.program_overlay)
                   and item.get("category") in {"Películas", "Música"}) else None)
        program_expr = self._program_enable_expression(local_offset, trim_duration) if program else ""
        if not program_expr:
            program = None
        music = (self.music_overlay if (self.music_overlay and os.path.isfile(self.music_overlay)
                 and is_music_item(item)) else None)
        music_expr = self._music_enable_expression(local_offset, trim_duration) if music else ""
        if not music_expr:
            music = None

        amap = f"0:a:{aid}?" if isinstance(aid, int) and aid >= 0 else "0:a:0?"

        overlay_list = []
        if logo:
            overlay_list.append(("logo", logo["path"], None))
        if program:
            overlay_list.append(("program", program, program_expr))
        if music:
            overlay_list.append(("music", music, music_expr))
        for item_op in overlay_list:
            if item_op[0] == "logo" and os.path.splitext(item_op[1])[1].lower() in {".mov", ".webm", ".mkv", ".avi", ".mp4"}:
                cmd += ["-stream_loop", "-1", "-i", item_op[1]]
            else:
                cmd += ["-loop", "1", "-framerate", "1", "-i", item_op[1]]

        if overlay_list:
            filters = [f"[0:v]{','.join(vf)}[base]"]
            stage = "base"
            for inp_idx, (lbl, _path, expr) in enumerate(overlay_list, start=1):
                if lbl == "logo":
                    lw = max(16, int(w * int(logo.get("width_pct", logo.get("scale", 10))) / 100))
                    lh = max(16, int(h * int(logo.get("height_pct", logo.get("scale", 10))) / 100)) if logo.get("custom_size") else -1
                    op = max(0.05, min(1.0, int(logo.get("opacity", 90)) / 100))
                    m = int(logo.get("margin", 48))
                    xe, ye = logo_overlay_position(logo.get("position", "arriba-derecha"), w, h, m)
                    filters.append(f"[{inp_idx}:v]setpts=PTS-STARTPTS,scale={lw}:{lh},format=rgba,"
                                   f"colorchannelmixer=aa={op:.2f}[logo]")
                    filters.append(f"[{stage}][logo]overlay={xe.format(m=m)}:{ye.format(m=m)}:"
                                   f"shortest=1:format=auto[withlogo]")
                    stage = "withlogo"
                elif lbl == "program":
                    filters.append(f"[{inp_idx}:v]format=rgba[program]")
                    filters.append(f"[{stage}][program]overlay=0:0:enable='{expr}':eof_action=repeat[withprogram]")
                    stage = "withprogram"
                elif lbl == "music":
                    filters.append(f"[{inp_idx}:v]format=rgba[music]")
                    filters.append(f"[{stage}][music]overlay=0:0:enable='{expr}':eof_action=repeat[withmusic]")
                    stage = "withmusic"
            filters.append(f"[{stage}]format=yuv420p[out]")
            cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-map", amap]
        else:
            cmd += ["-map", "0:v:0", "-map", amap, "-vf", ",".join(vf)]

        cmd += ["-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
                "-c:v", codec,
                "-b:v", f"{self.bitrate}k", "-maxrate", f"{self.bitrate}k",
                "-bufsize", f"{self.bitrate * 2}k",
                "-g", str(gop), "-keyint_min", str(gop),
                "-pix_fmt", "yuv420p", "-r", str(self.fps), "-fps_mode", "cfr"]
        if codec == "libx264":
            cmd += ["-preset", self.x264_preset, "-profile:v", self.video_profile,
                    "-bf", "0" if self.video_profile == "baseline" else "2",
                    "-sc_threshold", "0",
                    "-x264-params", "nal-hrd=cbr:force-cfr=1:scenecut=0"]
        elif codec == "h264_nvenc":
            cmd += ["-preset", "p4", "-tune", "ll", "-rc", "cbr", "-profile:v", "high", "-bf", "2"]
        elif codec == "h264_qsv":
            cmd += ["-preset", "medium", "-profile:v", "high", "-look_ahead", "0"]
        elif codec == "h264_amf":
            cmd += ["-quality", "balanced", "-rc", "cbr", "-profile:v", "high"]

        af = build_audio_filters(self.audio_processor_config)
        if "aresample" not in af:
            if af:
                af += ","
            af += "aresample=48000:async=1:first_pts=0"
        cmd += ["-c:a", "aac", "-b:a", f"{self.audio_bitrate}k", "-ar", "48000",
                "-ac", "2", "-af", af]
        if remaining_duration > 0:
            cmd += ["-t", f"{remaining_duration:.3f}"]
        if self.extra_args.strip():
            cmd += self.extra_args.split()
        # La clave de todo el diseño: timestamps GLOBALES + mux TS sin retardo.
        cmd += ["-muxdelay", "0", "-muxpreload", "0",
                "-output_ts_offset", f"{t_start:.3f}",
                "-f", "mpegts", out_path]
        return cmd, label, aid, effective_duration

    def _build_slate_command(self, t_start, out_path):
        """Productor de un tramo de barras/negro para mantener el flujo vivo."""
        slate = get_or_create_fallback_slate(
            self.ffmpeg, getattr(self, "fallback_mode", "bars"),
            self.resolution, self.fps)
        try:
            w, h = [int(x) for x in self.resolution.lower().split("x", 1)]
        except Exception:  # noqa: BLE001
            w, h = 1920, 1080
        label, codec = self._resolve_encoder(self.encoder)
        gop = max(1, int(round(float(self.fps) * self.keyframe_interval)))
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
               "-re", "-stream_loop", "-1", "-i", slate,
               "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                       f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                       f"fps={self.fps},format=yuv420p"),
               "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
               "-c:v", codec, "-b:v", f"{self.bitrate}k",
               "-maxrate", f"{self.bitrate}k", "-bufsize", f"{self.bitrate * 2}k",
               "-g", str(gop), "-keyint_min", str(gop),
               "-pix_fmt", "yuv420p", "-r", str(self.fps), "-fps_mode", "cfr"]
        if codec == "libx264":
            cmd += ["-preset", self.x264_preset, "-profile:v", self.video_profile,
                    "-bf", "0" if self.video_profile == "baseline" else "2",
                    "-x264-params", "nal-hrd=cbr:force-cfr=1:scenecut=0"]
        cmd += ["-c:a", "aac", "-b:a", f"{self.audio_bitrate}k", "-ar", "48000",
                "-ac", "2", "-af", "aresample=48000:async=1:first_pts=0",
                "-t", f"{self.SLATE_CHUNK:.3f}",
                "-muxdelay", "0", "-muxpreload", "0",
                "-output_ts_offset", f"{t_start:.3f}",
                "-f", "mpegts", out_path]
        return cmd, label

    # ------------------------------------------------------------- segmentos
    def _ensure_spool_dir(self):
        if not self._spool_dir:
            self._spool_dir = tempfile.mkdtemp(prefix=f"{APP_SLUG}_feed_",
                                               dir=tempfile.gettempdir())
        return self._spool_dir

    def _new_segment(self, index, item, item_offset, duration):
        with self._lock:
            seq = self._seq_counter
            self._seq_counter += 1
            path = os.path.join(self._ensure_spool_dir(), f"seg_{seq:06d}.ts")
            seg = _Segment(seq, path, index, item, item_offset, self._t_cursor, duration)
            self._segments.append(seg)
            self._seg_by_seq[seq] = seg
            self._t_cursor = seg.t_end + self.SAFETY
        self._segments_event.set()
        return seg

    def _start_producer(self, seg, cmd):
        log.info("productor seg %d: %s", seg.seq, subprocess.list2cmdline(cmd))
        seg.proc = proc_tools.popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        seg.started_at = time.time()
        seg.last_growth_at = time.time()

    def _produce_item_segment(self, index, item, item_offset=0.0):
        """Crea y produce el spool de un item; devuelve el segmento o None."""
        seq = self._seq_counter
        path = os.path.join(self._ensure_spool_dir(), f"seg_{seq:06d}.ts")
        try:
            cmd, label, aid, duration = self._build_producer_command(
                item, item_offset, self._t_cursor, path)
        except RuntimeError as exc:
            self.log.emit(f"OMITIDO • {os.path.basename(str(item.get('path', '')))} • {exc}")
            return None
        seg = self._new_segment(index, item, item_offset, duration)
        try:
            self._start_producer(seg, cmd)
        except OSError as exc:
            self.log.emit(f"No se pudo iniciar el productor: {exc}")
            seg.dead = True
            return None
        self.log.emit(f"Productor • {label} • {os.path.basename(item['path'])} • "
                      f"audio #{aid if aid is not None else 'auto'} • "
                      f"offset {item_offset:.2f}s • T+{seg.t_start:.1f}s")
        return seg

    def _produce_slate_segment(self):
        if time.time() < self._slate_retry_at:
            return None
        self._slate_retry_at = time.time() + self.SLATE_RETRY
        seq = self._seq_counter
        path = os.path.join(self._ensure_spool_dir(), f"seg_{seq:06d}.ts")
        try:
            cmd, label = self._build_slate_command(self._t_cursor, path)
        except RuntimeError as exc:
            self.log.emit(f"Slate no disponible: {exc}")
            return None
        seg = self._new_segment(-1, None, 0.0, self.SLATE_CHUNK)
        try:
            self._start_producer(seg, cmd)
        except OSError as exc:
            self.log.emit(f"No se pudo iniciar el productor de slate: {exc}")
            seg.dead = True
            return None
        mode = "Barras SMPTE" if getattr(self, "fallback_mode", "bars") == "bars" else "Pantalla Negra"
        self.log.emit(f"Productor • {label} • {mode} (mantener flujo vivo) • T+{seg.t_start:.1f}s")
        return seg

    # ------------------------------------------------------------- consultas pump
    def _next_segment_for(self, seq):
        """Primer segmento vivo con seq > dado (los muertos se saltan)."""
        with self._lock:
            for seg in self._segments:
                if seg.seq > seq and not seg.dead:
                    return seg
            return None

    def _segment_by_seq(self, seq):
        with self._lock:
            return self._seg_by_seq.get(seq)

    def _current_master_segment(self):
        """Segmento que el pump master está emitiendo (o el primero vivo)."""
        pump = self._pumps[0] if self._pumps else None
        if pump is not None:
            seg = self._segment_by_seq(pump.cur_seq)
            if seg is not None and not seg.dead:
                return seg
        with self._lock:
            for seg in self._segments:
                if not seg.dead:
                    return seg
        return None

    def _has_live_segment_after(self, seq):
        with self._lock:
            return any(not s.dead and s.seq > seq for s in self._segments)

    # ------------------------------------------------------------- eventos pump
    def _on_segment_entered(self, pump, seg):
        if not pump.is_master:
            return
        if seg.is_slate:
            self.log.emit("Al aire • señal de espera (flujo RTMP intacto)")
            self.state.emit(True, f"{self.protocol} ON AIR • Modo Espera (motor continuo)")
        else:
            self.now_playing.emit(seg.index, seg.item["path"])

    def _on_segment_exited(self, pump, seg):
        if not pump.is_master:
            return
        if seg.is_slate or seg.dead:
            # Un segmento muerto por salto no avisa: el controlador ya tomó
            # su decisión al pedir la conmutación.
            return
        if not seg.finished_emitted:
            seg.finished_emitted = True
            self.clip_finished.emit(int(seg.index), bool(not seg.failed))

    def _on_air_time(self, t):
        """time= del consumidor master: mueve el reloj de la playlist."""
        with self._lock:
            self._master_air_time = t
            self._master_air_at = time.time()
            seg = None
            for cand in self._segments:
                if cand.t_start <= t and not cand.dead:
                    seg = cand
                elif cand.t_start > t:
                    break
        if seg is None or seg.is_slate:
            return
        pos = seg.item_offset + max(0.0, t - seg.t_start)
        if seg.duration > 0:
            pos = min(pos, seg.duration)
        self.progress.emit(int(seg.index), pos)

    # ------------------------------------------------------------- orquestación
    def _maybe_speculate(self):
        cur = self._current_master_segment()
        if cur is None:
            with self._lock:
                has_any = bool(self._segments)
            if has_any:
                return              # ya hay algo produciéndose (p. ej. un salto previo al arranque)
            items = self.items
            if items:
                idx = max(0, min(self.start_index, len(items) - 1))
                item = items[idx]
                if not item.get("path") or _URL_RE.match(str(item.get("path", ""))):
                    self._produce_slate_segment()
                else:
                    if self._produce_item_segment(idx, item, max(0.0, self.start_offset)) is None:
                        self._produce_slate_segment()
            else:
                self._produce_slate_segment()
            return
        if cur.is_slate:
            # En espera sólo se encadena más slate; el contenido entra por
            # saltos del controlador (play_index → sync_items(force_jump)).
            if not self._has_live_segment_after(cur.seq):
                elapsed = (self._master_air_time - cur.t_start) if self._master_air_time >= 0 else 0.0
                if cur.duration - elapsed < self.LEAD or cur.done:
                    self._produce_slate_segment()
            return
        if self._has_live_segment_after(cur.seq):
            return
        # Tope de cola: nunca más de 2 segmentos vivos por delante del que
        # está al aire. Con -re la producción va a 1x y la cola se mantiene
        # en 1; el tope sólo actúa ante casos patológicos (p. ej. un destino
        # que consume más despacio que la producción).
        with self._lock:
            queued = sum(1 for s in self._segments
                         if not s.dead and s.seq > cur.seq)
        if queued >= 2:
            return
        remaining = cur.t_end - (self._master_air_time if self._master_air_time >= 0 else cur.t_start)
        if remaining > self.LEAD and not cur.done:
            return
        nxt = self._speculate_next(cur.index)
        if nxt is not None:
            index, item = nxt
            if _URL_RE.match(str(item.get("path", ""))):
                return          # el vivo entra por salto en su momento
            if self._produce_item_segment(index, item, 0.0) is not None:
                return
        self._produce_slate_segment()

    def _reap_producers(self):
        with self._lock:
            segs = list(self._segments)
        for seg in segs:
            if seg.proc is not None and not seg.done and seg.proc.poll() is not None:
                seg.done = True
                if seg.proc.returncode not in (0, 255, -15) and not seg.dead:
                    seg.failed = True
                    self.log.emit(
                        f"Productor terminó con código {seg.proc.returncode} • "
                        f"{os.path.basename(str((seg.item or {}).get('path', 'slate')))}")
                proc_tools.forget(seg.proc)

    def _watchdog_producers(self):
        now = time.time()
        with self._lock:
            segs = list(self._segments)
        for seg in segs:
            if seg.dead or not seg.producing():
                continue
            try:
                size = os.path.getsize(seg.path)
            except OSError:
                size = 0
            if size > seg.last_size:
                seg.last_size = size
                seg.last_growth_at = now
            elif now - seg.last_growth_at > self.PRODUCER_STALL:
                self.log.emit(
                    f"Productor sin avance {int(now - seg.last_growth_at)}s • se cancela "
                    f"({os.path.basename(str((seg.item or {}).get('path', 'slate')))})")
                proc_tools.terminate(seg.proc)
                seg.done = True
                seg.failed = True

    def _gc_segments(self):
        """Borra spools que todos los pumps ya pasaron."""
        with self._lock:
            if not self._segments:
                return
            min_seq = min((p._last_seq for p in self._pumps), default=-1)
            while self._segments and self._segments[0].seq <= min_seq:
                seg = self._segments.pop(0)
                self._seg_by_seq.pop(seg.seq, None)
                try:
                    if os.path.isfile(seg.path):
                        os.remove(seg.path)
                except OSError:
                    pass

    def _orchestrate_loop(self):
        while not self.stop_requested:
            self._reap_producers()
            self._maybe_speculate()
            self._finalize_switch()
            self._watchdog_producers()
            self._gc_segments()
            time.sleep(0.2)

    # ------------------------------------------------------------- control API
    def sync_items(self, items, current_index, force_jump=False, start_offset=0.0):
        """Actualiza la lista; con ``force_jump`` conmuta el flujo (sin cortar RTMP)."""
        new_items = self._norm_items(items)
        with self._lock:
            self.items = new_items
        if not new_items:
            return False
        idx = max(0, min(int(current_index), len(new_items) - 1))
        target = new_items[idx]
        if not force_jump:
            return True
        start_offset = max(0.0, float(start_offset or 0.0))
        with self._lock:
            cur = self._current_master_segment()
            # ¿el flujo ya está emitiendo ese mismo contenido en ese punto?
            if (cur is not None and not cur.is_slate
                    and str((cur.item or {}).get("path")) == str(target.get("path"))):
                fed_pos = cur.item_offset + max(
                    0.0, (self._master_air_time - cur.t_start) if self._master_air_time >= 0 else 0.0)
                if abs(start_offset - fed_pos) <= 2.0:
                    return True
            # ¿la especulación ya encoló exactamente ese evento?
            cur_seq = cur.seq if cur is not None else -1
            for seg in self._segments:
                if (not seg.dead and seg.seq != cur_seq and not seg.is_slate
                        and str((seg.item or {}).get("path")) == str(target.get("path"))
                        and abs(seg.item_offset - start_offset) < 0.5):
                    return True
        self._switch_to(idx, target, start_offset)
        return True

    def _switch_to(self, index, item, start_offset):
        """Conmutación: produce el objetivo y retira lo anterior cuando esté listo.

        El segmento que está al aire se convierte en "zombi": sigue emitiendo
        mientras el productor del objetivo calienta (abrir archivo por red,
        arrancar codificador). Cuando el objetivo tiene datos, el zombi se
        retira y el corte entra con imagen en lugar de un frame congelado.
        """
        with self._lock:
            t_now = self._master_air_time
            cur = self._current_master_segment()
            if t_now < 0:
                t_now = cur.t_start if cur is not None else 0.0
            self._t_cursor = t_now + self.SAFETY
            zombie = cur if cur is not None else None
            for seg in self._segments:
                if seg is zombie or seg.dead:
                    continue
                seg.dead = True
                if seg.producing():
                    proc_tools.terminate(seg.proc)
            self._switch_zombie = zombie
        self.log.emit(f"{self.protocol} → evento {index + 1}: "
                      f"{os.path.basename(str(item.get('path', '')))} • "
                      f"conmutación sin cortar la conexión")
        if self._produce_item_segment(index, item, start_offset) is None:
            # ni siquiera arrancó (archivo perdido): slate inmediato
            self._produce_slate_segment()

    def _finalize_switch(self):
        """Retira el zombi cuando el objetivo de la conmutación ya tiene datos."""
        zombie = self._switch_zombie
        if zombie is None:
            return
        if zombie.dead:
            self._switch_zombie = None
            return
        target = self._next_segment_for(zombie.seq)
        ready = target is None      # sin objetivo: cortar igual (el pump esperará)
        if target is not None:
            if target.done or target.failed:
                ready = True
            else:
                try:
                    ready = os.path.getsize(target.path) >= self.HEAD_BYTES
                except OSError:
                    ready = False
        if ready:
            zombie.dead = True
            if zombie.producing():
                proc_tools.terminate(zombie.proc)
            self._switch_zombie = None

    def replace_items(self, items, start_index=0):
        return self.sync_items(items, start_index, force_jump=True)

    def skip_to(self, index):
        with self._lock:
            items = list(self.items)
        if not (0 <= index < len(items)):
            return False
        return self.sync_items(items, index, force_jump=True)

    def seek_to(self, index, offset):
        if index is None or index < 0:
            return
        with self._lock:
            items = list(self.items)
        self.sync_items(items, index, force_jump=True, start_offset=max(0.0, float(offset)))

    def pause_here(self, paused):
        """Congela el flujo sin cerrar la conexión (frame congelado en el servidor)."""
        with self._lock:
            self._paused_flag = bool(paused)

    def _restart_current(self):
        """Reinicio breve del segmento actual (p. ej. subtítulos recién extraídos).

        Aquí NO se toca la conexión: sólo se re-produce el spool desde la
        posición actual y la bomba conmuta al nuevo segmento.
        """
        cur = self._current_master_segment()
        if cur is None or cur.is_slate:
            return
        fed_pos = cur.item_offset + max(
            0.0, (self._master_air_time - cur.t_start) if self._master_air_time >= 0 else 0.0)
        item = dict(cur.item or {})
        index = cur.index
        with self._lock:
            t_now = self._master_air_time if self._master_air_time >= 0 else cur.t_start
            self._t_cursor = t_now + self.SAFETY
            for seg in self._segments:
                if not seg.dead:
                    seg.dead = True
                    if seg.producing():
                        proc_tools.terminate(seg.proc)
        self.log.emit("Reinicio del productor para activar subtítulos (conexión intacta)")
        self._produce_item_segment(index, item, fed_pos)

    # ------------------------------------------------------------- ciclo Qt
    def run(self):
        try:
            if self.protocol == "NDI" or str(self.url).lower().startswith("ndi://"):
                self.state.emit(False, "El motor continuo no gestiona NDI; usa salidas RTMP/SRT/UDP")
                return
            self._ensure_spool_dir()
            self.log.emit(f"Motor continuo (dos mundos) • {self.protocol} • "
                          f"consumidor persistente + productores de spool")
            self._maybe_speculate()          # crea y lanza el primer segmento
            self._pumps = [_Pump(self, f"{self.protocol}-1", is_master=True)]
            for pump in self._pumps:
                pump.start()
            self._orchestrate_loop()
            self.state.emit(False, f"{self.protocol} detenido")
        except Exception as exc:  # noqa: BLE001
            log.error("motor continuo: %s", exc, exc_info=True)
            self.state.emit(False, f"{self.protocol} ERROR • {exc}")
        finally:
            self._shutdown()
            self.ended.emit()

    def _shutdown(self):
        self.stop_requested = True
        self._segments_event.set()
        for pump in self._pumps:
            try:
                pump.stop_and_join(timeout=4.0)
            except Exception:  # noqa: BLE001
                pass
        self._pumps = []
        with self._lock:
            segs = list(self._segments)
            for seg in segs:
                if seg.producing():
                    proc_tools.terminate(seg.proc)
                seg.dead = True
                try:
                    if os.path.isfile(seg.path):
                        os.remove(seg.path)
                except OSError:
                    pass
            self._segments = []
            self._seg_by_seq = {}
        if self._spool_dir:
            shutil.rmtree(self._spool_dir, ignore_errors=True)
            self._spool_dir = None

    def stop(self):
        self.stop_requested = True
        self._segments_event.set()

    # ------------------------------------------------------------- propiedades
    @property
    def paused(self):
        with self._lock:
            return self._paused_flag

    @property
    def proc(self):
        """Proceso del consumidor master (compatibilidad con el watcher)."""
        if self._pumps:
            proc = self._pumps[0].consumer
            if proc is not None and proc.poll() is None:
                return proc
        return None

    @proc.setter
    def proc(self, _value):
        # OutputWorker.__init__ asigna None; el motor gestiona el suyo.
        pass

    @property
    def has_active_process(self):
        for pump in self._pumps:
            if pump._consumer_alive():
                return True
        with self._lock:
            return any(seg.producing() for seg in self._segments)

    @property
    def current_index(self):
        seg = self._current_master_segment()
        return seg.index if seg is not None and not seg.is_slate else -1

    @property
    def current_offset(self):
        seg = self._current_master_segment()
        return float(seg.item_offset) if seg is not None else 0.0

    @property
    def current_position(self):
        with self._lock:
            t = self._master_air_time
            measured = self._master_air_at
        seg = self._current_master_segment()
        if seg is None or seg.is_slate:
            return -1.0
        if t < 0 or time.time() - measured > 5.0:
            return -1.0        # calentando / sin medición reciente
        pos = seg.item_offset + max(0.0, t - seg.t_start)
        if seg.duration > 0:
            pos = min(pos, seg.duration)
        return pos
