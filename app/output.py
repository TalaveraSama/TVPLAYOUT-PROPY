"""Motor de salida RTMP/SRT/UDP con FFmpeg.

Emite la playlist clip a clip por la misma URL. El playout local (mpv) es el «master»: cada vez que
empieza un evento, la salida salta al mismo evento (`sync_items(..., force_jump=True)`). Si un clip
termina en FFmpeg antes de recibir la orden del master, espera un breve periodo de gracia y después
continúa solo con el siguiente evento (red de seguridad para la continuidad 24/7).
"""
import json
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QThread, Signal

from . import logger
from .prober import pick_audio, pick_subtitle

log = logger.get("rtmp")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LOGO_POSITIONS = {
    "arriba-izquierda": ("{m}", "{m}"),
    "arriba-derecha": ("W-w-{m}", "{m}"),
    "abajo-izquierda": ("{m}", "H-h-{m}"),
    "abajo-derecha": ("W-w-{m}", "H-h-{m}"),
}


def _ffmpeg_filter_path(path):
    """Escapa una ruta para usarla dentro de un filtro de FFmpeg (subtitles=...)."""
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
    return p


class OutputWorker(QThread):
    log = Signal(str)
    state = Signal(bool, str)       # on_air, mensaje
    now_playing = Signal(int, str)  # índice, ruta
    ended = Signal()

    ENCODERS = {
        "CPU/x264": "libx264",
        "NVIDIA NVENC": "h264_nvenc",
        "Intel QSV": "h264_qsv",
        "AMD AMF": "h264_amf",
    }
    GRACE_SECONDS = 3.0

    def __init__(self, ffmpeg, items, url, resolution, fps, encoder, bitrate,
                 audio_preference="AUTO", subtitle_preference="OFF", subtitle_burn=False,
                 audio_bitrate=192, loop=True, start_index=0, start_offset=0.0, extra_args="", logo=None):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.items = self._norm_items(items)
        self.url = url
        self.resolution = resolution
        self.fps = fps
        self.encoder = encoder
        self.bitrate = int(bitrate)
        self.audio_bitrate = int(audio_bitrate)
        self.audio_preference = audio_preference
        self.subtitle_preference = subtitle_preference
        self.subtitle_burn = subtitle_burn
        self.loop = loop
        self.start_index = int(start_index or 0)
        self.start_offset = float(start_offset or 0)
        self.extra_args = extra_args or ""
        self.logo = logo
        self.proc = None
        self.stop_requested = False
        self._lock = threading.RLock()
        self._jump = threading.Event()
        self._jump_index = None
        self._jump_offset = 0.0
        self._current_index = -1
        self._clip_started = 0.0
        self._resolved = None
        # v22.1: control de pausa/seek desde el playout local. Si el playout
        # pausa/seek-ea, el RTMP se reinicia en el mismo offset.
        self._paused = False
        self._paused_index = None
        self._paused_offset = 0.0
        # v22.2.1: offset actual del clip en emisión (lo que persiste el
        # watcher de drift del playout local).
        self._current_offset = 0.0
        # v22.2.2: timestamp de cuándo arrancó EFECTIVAMENTE el FFmpeg para
        # este clip (cuando se hizo Popen y empezó a decodificar). Se usa para
        # estimar la posición actual del FFmpeg como
        # _current_offset + (now - _clip_emit_started). Sin esto, el watcher
        # de drift compara el offset ESTÁTICO contra la posición DINÁMICA de
        # mpv, y nunca converge.
        self._clip_emit_started = 0.0

    @staticmethod
    def _norm_items(items):
        out = []
        for it in items or []:
            if isinstance(it, str):
                out.append({"path": it, "tracks": []})
            elif isinstance(it, dict) and it.get("path"):
                out.append(dict(it))
        return out

    # ------------------------------------------------------------- helpers
    def _available_encoders(self):
        try:
            p = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                               timeout=15, creationflags=CREATE_NO_WINDOW)
            return p.stdout or ""
        except Exception:  # noqa: BLE001
            return ""

    def _resolve_encoder(self, requested):
        if self._resolved:
            return self._resolved
        text = self._available_encoders()
        if requested == "AUTO":
            for label in ("NVIDIA NVENC", "Intel QSV", "AMD AMF", "CPU/x264"):
                codec = self.ENCODERS[label]
                if re.search(rf"\b{re.escape(codec)}\b", text) and self._encoder_works(codec):
                    self._resolved = (label, codec)
                    return self._resolved
            self._resolved = ("CPU/x264", "libx264")
            return self._resolved
        codec = self.ENCODERS.get(requested)
        if not codec:
            self._resolved = ("CPU/x264", "libx264")
            return self._resolved
        if text and not re.search(rf"\b{re.escape(codec)}\b", text):
            log.warning("Encoder solicitado %s (%s) no está en FFmpeg; usando CPU/x264", requested, codec)
            self._resolved = ("CPU/x264", "libx264")
            return self._resolved
        # Que FFmpeg liste un encoder no significa que exista la GPU o su
        # controlador. Esto ocurre con frecuencia con NVENC en equipos sin
        # NVIDIA: probarlo aquí evita arrancar un proceso RTMP condenado a
        # fallar con `Cannot load nvcuda.dll`.
        if codec != "libx264" and not self._encoder_works(codec):
            log.warning("Encoder solicitado %s (%s) no funciona en este equipo; usando CPU/x264",
                        requested, codec)
            self._resolved = ("CPU/x264", "libx264")
            return self._resolved
        self._resolved = (requested, codec)
        return self._resolved

    def _encoder_works(self, codec):
        """Prueba rápida del encoder por hardware (evita elegir NVENC sin GPU)."""
        if codec == "libx264":
            return True
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=25",
               "-frames:v", "3", "-c:v", codec, "-f", "null", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
            return p.returncode == 0
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _tracks_of(item):
        tracks = item.get("tracks") or []
        if isinstance(tracks, str):
            try:
                tracks = json.loads(tracks or "[]")
            except ValueError:
                tracks = []
        return tracks

    def _build_command(self, item, offset=0.0):
        source = item["path"]
        if not self.ffmpeg or not os.path.isfile(self.ffmpeg):
            raise RuntimeError("FFmpeg no encontrado. Coloca ffmpeg.exe en la raíz del proyecto o define FFMPEG_PATH.")
        if not source or not os.path.isfile(source):
            raise RuntimeError("Archivo no encontrado: " + str(source))
        low = self.url.lower()
        if not low.startswith(("rtmp://", "rtmps://", "srt://", "udp://")):
            raise RuntimeError("La salida debe comenzar por rtmp://, rtmps://, srt:// o udp://")
        try:
            w, h = [int(x) for x in self.resolution.lower().split("x", 1)]
        except Exception:
            raise RuntimeError("Resolución inválida")
        label, codec = self._resolve_encoder(self.encoder)
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
            mark_in = mark_out = source_offset = local_offset = trim_duration = remaining_duration = 0.0
        tracks = self._tracks_of(item)
        aid = pick_audio(tracks, item.get("audio_lang") or self.audio_preference)
        sid = pick_subtitle(tracks, item.get("subtitle_lang") or self.subtitle_preference) if self.subtitle_burn else -1

        vf = [f"scale={w}:{h}:force_original_aspect_ratio=decrease", f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
              f"fps={self.fps}", "format=yuv420p"]
        if self.subtitle_burn and sid is not None and sid >= 0:
            vf.insert(0, f"subtitles='{_ffmpeg_filter_path(source)}':si={sid}")
        gop = int(round(float(self.fps) * 2))
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-re"]
        if source_offset > 0:
            # offset es relativo al corte de playlist; FFmpeg debe buscar en
            # la posición absoluta mark-in + offset dentro del archivo.
            cmd += ["-ss", f"{source_offset:.3f}"]
        cmd += ["-i", source]
        logo = self.logo if (self.logo and os.path.isfile(self.logo.get("path", ""))) else None
        amap = f"0:a:{aid}?" if isinstance(aid, int) and aid >= 0 else "0:a:0?"
        if logo:
            cmd += ["-loop", "1", "-framerate", "1", "-i", logo["path"]]
            lw = max(16, int(w * int(logo.get("scale", 12)) / 100))
            op = max(0.05, min(1.0, int(logo.get("opacity", 90)) / 100))
            xe, ye = LOGO_POSITIONS.get(logo.get("position", "arriba-derecha"), LOGO_POSITIONS["arriba-derecha"])
            m = int(logo.get("margin", 24))
            fc = (f"[0:v]{','.join(vf)}[base];"
                  f"[1:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={op:.2f}[logo];"
                  f"[base][logo]overlay={xe.format(m=m)}:{ye.format(m=m)}:shortest=1:format=auto,format=yuv420p[out]")
            cmd += ["-filter_complex", fc, "-map", "[out]", "-map", amap]
        else:
            cmd += ["-map", "0:v:0", "-map", amap, "-vf", ",".join(vf)]
        cmd += ["-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1", "-c:v", codec,
                "-b:v", f"{self.bitrate}k", "-maxrate", f"{self.bitrate}k", "-bufsize", f"{self.bitrate * 2}k",
                "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                "-pix_fmt", "yuv420p", "-r", str(self.fps)]
        if codec == "libx264":
            cmd += ["-preset", "veryfast", "-profile:v", "high", "-bf", "2", "-x264-params", "nal-hrd=cbr:force-cfr=1"]
        elif codec == "h264_nvenc":
            cmd += ["-preset", "p4", "-tune", "ll", "-rc", "cbr", "-profile:v", "high", "-bf", "2"]
        elif codec == "h264_qsv":
            cmd += ["-preset", "medium", "-profile:v", "high", "-look_ahead", "0"]
        elif codec == "h264_amf":
            cmd += ["-quality", "balanced", "-rc", "cbr", "-profile:v", "high"]
        cmd += ["-c:a", "aac", "-b:a", f"{self.audio_bitrate}k", "-ar", "48000", "-ac", "2", "-af", "aresample=async=1:first_pts=0"]
        if remaining_duration > 0:
            # -t es una duración de salida: no corta el archivo fuente y
            # hace efectivo el mark-out también para RTMP/SRT/UDP.
            cmd += ["-t", f"{remaining_duration:.3f}"]
        if self.extra_args.strip():
            cmd += self.extra_args.split()
        if low.startswith(("rtmp://", "rtmps://")):
            cmd += ["-flvflags", "no_duration_filesize", "-f", "flv", self.url]
        else:
            cmd += ["-f", "mpegts", self.url]
        return cmd, label, aid, sid

    # ---------------------------------------------------------- control
    def sync_items(self, items, current_index, force_jump=False, start_offset=0.0):
        """Actualiza la lista de eventos y, si `force_jump`, salta al evento `current_index`.

        Sin `force_jump` solo se sincroniza la estructura (inserciones/borrados) manteniendo el clip actual.
        `start_offset` (v22.1) permite reanudar en un offset distinto de cero
        (usado por seek/pause).
        """
        new_items = self._norm_items(items)
        if not new_items:
            return False
        with self._lock:
            cur_path = self.items[self._current_index]["path"] if 0 <= self._current_index < len(self.items) else None
            self.items = new_items
            idx = max(0, min(int(current_index), len(new_items) - 1))
            if not force_jump:
                if cur_path is not None:
                    same = [i for i, it in enumerate(new_items) if it["path"] == cur_path]
                    if same:
                        self._current_index = min(same, key=lambda i: abs(i - self._current_index))
                    else:
                        self._current_index = min(self._current_index, len(new_items) - 1)
                return True
            recently_started = time.time() - self._clip_started < 4.0
            if idx == self._current_index and self.proc is not None and self.proc.poll() is None and recently_started and not start_offset:
                return True
            self._jump_index = idx
            # v22.1: el offset sobrevive al próximo loop para que un seek/pause
            # se aplique correctamente.
            self._jump_offset = float(start_offset or 0.0)
            self._jump.set()
            proc = self.proc
        self._terminate(proc)
        self.log.emit(f"RTMP → evento {idx + 1}: {os.path.basename(new_items[idx]['path'])}")
        return True

    def replace_items(self, items, start_index=0):
        return self.sync_items(items, start_index, force_jump=True)

    def skip_to(self, index):
        with self._lock:
            items = self.items
        return self.sync_items(items, index, force_jump=True)

    def pause_here(self, paused):
        """v22.1: el playout local pausa/reanuda — el RTMP se reinicia en el
        mismo índice y offset al reanudar. Mientras está pausado, el FFmpeg
        actual sigue corriendo (no se mata) para evitar desconexiones del
        servidor; al reanudar se mata y se relanza con el offset guardado."""
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self._paused_index = self._current_index
                # No tenemos un offset exacto del FFmpeg (sólo del playout);
                # usamos 0 porque al reanudar vamos a recibir un seek explícito
                # o seguir desde el frame que el playout indique.
                self._paused_offset = 0.0
                return
            idx = self._paused_index
            off = self._paused_offset
            self._paused_index = None
            self._paused_offset = 0.0
        if idx is None or idx < 0:
            return
        self.sync_items(self.items, idx, force_jump=True, start_offset=off)

    def seek_to(self, index, offset):
        """v22.1: el playout local hizo seek. Reiniciamos FFmpeg en el mismo
        índice con el offset dado (en segundos)."""
        if index is None or index < 0:
            return
        self.sync_items(self.items, index, force_jump=True, start_offset=max(0.0, float(offset)))

    def set_logo(self, logo):
        with self._lock:
            self.logo = logo

    @staticmethod
    def _terminate(proc):
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    @property
    def current_index(self):
        return self._current_index

    @property
    def current_offset(self):
        """v22.2.1: offset (en segundos) con el que se está emitiendo el clip
        actual en el RTMP. 0.0 si todavía no se arrancó ningún clip o si el
        FFmpeg todavía no emitió nada del nuevo clip."""
        with self._lock:
            return getattr(self, "_current_offset", 0.0)

    @property
    def current_position(self):
        """v22.2.2: posición estimada actual del FFmpeg (en segundos dentro
        del clip que se está emitiendo). Se calcula como
        current_offset + (now - clip_emit_started).

        Esto es lo que el watcher de drift del playout local debe comparar
        contra self.player._time (la posición actual de mpv local).

        Si el FFmpeg no está corriendo, devuelve current_offset sin
        acumular tiempo (no tiene sentido).
        """
        with self._lock:
            offset = float(getattr(self, "_current_offset", 0.0) or 0.0)
            started = float(getattr(self, "_clip_emit_started", 0.0) or 0.0)
            proc = getattr(self, "proc", None)
        if not proc or proc.poll() is not None or started <= 0:
            return offset
        return offset + max(0.0, time.time() - started)

    NOISE = ("Immediate exit requested", "Last message repeated", "Error muxing a packet", "Error writing trailer",
             "Error closing file", "Terminating thread", "Error submitting a packet")

    def _drain_stderr(self, proc, last_lines):
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                if any(n in line for n in self.NOISE):     # ruido normal al cortar FFmpeg para saltar de evento
                    continue
                last_lines.append(line)
                del last_lines[:-5]
                self.log.emit("FFmpeg • " + line)
                log.warning("ffmpeg: %s", line)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------------- loop
    def run(self):
        try:
            with self._lock:
                items = list(self.items)
            if not items:
                raise RuntimeError("No hay eventos para emitir por RTMP.")
            self.stop_requested = False
            index = max(0, min(self.start_index, len(items) - 1))
            offset = self.start_offset
            first = True
            consecutive_errors = 0
            while not self.stop_requested:
                with self._lock:
                    items = list(self.items)
                    if self._jump.is_set():
                        self._jump.clear()
                        if self._jump_index is not None:
                            index = self._jump_index
                            self._jump_index = None
                            # v22.1: consumir el offset pedido por seek/pause
                            offset = getattr(self, "_jump_offset", 0.0) or 0.0
                            self._jump_offset = 0.0
                    if not items:
                        break
                    if index >= len(items):
                        if not self.loop:
                            break
                        index = 0
                    item = items[index]
                    self._current_index = index
                try:
                    cmd, label, aid, sid = self._build_command(item, offset)
                except RuntimeError as e:
                    self.log.emit(f"OMITIDO • {os.path.basename(item.get('path', ''))} • {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max(3, len(items)):
                        raise RuntimeError("Ningún evento de la playlist se pudo emitir: " + str(e))
                    index += 1
                    offset = 0.0
                    continue
                # v22.2.1: persistir el offset con el que arranca este clip
                # para que el watcher de drift del playout local pueda comparar.
                with self._lock:
                    self._current_offset = float(offset)
                offset = 0.0
                self.now_playing.emit(index, item["path"])
                self.log.emit(("FFmpeg iniciado" if first else "FFmpeg siguiente") +
                              f" • {label} • {os.path.basename(item['path'])} • audio #{aid if aid is not None else 'auto'} • offset {self._current_offset:.2f}s")
                log.info("RTMP %s: %s", label, subprocess.list2cmdline(cmd))
                with self._lock:
                    self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                                 text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
                    self._clip_started = time.time()
                    # v22.2.2: marca de cuándo arrancó el FFmpeg. La estimación
                    # de posición usa este timestamp (no _clip_started) para
                    # descontar el tiempo de arranque de FFmpeg.
                    self._clip_emit_started = time.time()
                    proc = self.proc
                if first:
                    self.state.emit(True, f"RTMP ON AIR • {label} • {self.resolution}@{self.fps} • {self.bitrate} kbps")
                    first = False
                started = time.time()
                last_lines = []
                threading.Thread(target=self._drain_stderr, args=(proc, last_lines), name="ffmpeg-stderr", daemon=True).start()
                # Espera activa: reacciona a STOP o a un salto aunque FFmpeg no escriba nada en stderr.
                while proc.poll() is None:
                    if self.stop_requested or self._jump.is_set():
                        self._terminate(proc)
                        break
                    time.sleep(0.15)
                code = proc.wait()
                with self._lock:
                    self.proc = None
                if self.stop_requested:
                    break
                if self._jump.is_set():
                    continue
                elapsed = time.time() - started
                if code not in (0, 255, -15):
                    self.log.emit(f"FFmpeg terminó con código {code} tras {elapsed:.0f}s")
                    if elapsed < 5:
                        # Un encoder de hardware puede pasar la prueba de
                        # disponibilidad y aun así fallar al abrir el
                        # stream real (por ejemplo, `Cannot load nvcuda.dll`).
                        # Cambiar a x264 y repetir el mismo evento evita el
                        # loop de drift que relanzaba NVENC cada pocos segundos.
                        active_codec = self._resolved[1] if self._resolved else ""
                        if active_codec != "libx264":
                            old_label = self._resolved[0] if self._resolved else active_codec
                            self._resolved = ("CPU/x264", "libx264")
                            retry_offset = float(self._current_offset or 0.0)
                            offset = retry_offset
                            consecutive_errors = 0
                            self.log.emit(
                                f"Fallback encoder • {old_label} no pudo iniciar; reintentando con CPU/x264"
                            )
                            log.warning(
                                "RTMP encoder %s falló al iniciar; fallback a CPU/x264 en offset %.3fs",
                                old_label, retry_offset,
                            )
                            time.sleep(0.2)
                            continue
                        consecutive_errors += 1
                        if consecutive_errors >= max(3, len(items)):
                            raise RuntimeError("FFmpeg falla repetidamente: " + (last_lines[-1] if last_lines else f"código {code}"))
                        time.sleep(1.0)
                    else:
                        consecutive_errors = 0
                else:
                    consecutive_errors = 0
                # Periodo de gracia: el master (mpv) suele ordenar el salto al mismo evento en este momento.
                if self._jump.wait(self.GRACE_SECONDS):
                    continue
                index += 1
            self.state.emit(False, "RTMP detenido")
        except Exception as e:  # noqa: BLE001
            log.error("RTMP error: %s", e)
            self.state.emit(False, f"RTMP ERROR • {e}")
        finally:
            with self._lock:
                proc = self.proc
                self.proc = None
            self._terminate(proc)
            self.ended.emit()

    def stop(self):
        self.stop_requested = True
        self._jump.set()
        with self._lock:
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
