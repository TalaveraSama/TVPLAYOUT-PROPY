import os, re, subprocess, tempfile, threading
from PySide6.QtCore import QThread, Signal

class OutputWorker(QThread):
    log = Signal(str)
    state = Signal(bool, str)
    ended = Signal()

    ENCODERS = {
        "CPU/x264": "libx264",
        "NVIDIA NVENC": "h264_nvenc",
        "Intel QSV": "h264_qsv",
        "AMD AMF": "h264_amf",
    }

    def __init__(self, ffmpeg, sources, url, resolution, fps, encoder, bitrate,
                 audio_preference="AUTO / Español preferido", subtitle_preference="OFF", subtitle_burn=False):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.sources = [str(x) for x in (sources if isinstance(sources, (list, tuple)) else [sources]) if x]
        self.url = url
        self.resolution = resolution
        self.fps = fps
        self.encoder = encoder
        self.bitrate = int(bitrate)
        self.audio_preference = audio_preference
        self.subtitle_preference = subtitle_preference
        self.subtitle_burn = subtitle_burn
        self.proc = None
        self.stop_requested = False
        self._lock = threading.RLock()
        self._switch_requested = False
        self._new_sources = None

    def _available_encoders(self):
        try:
            p = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
            return p.stdout or ""
        except Exception:
            return ""

    def _resolve_encoder(self, requested):
        text = self._available_encoders()
        if requested == "AUTO":
            for label in ("NVIDIA NVENC", "Intel QSV", "AMD AMF", "CPU/x264"):
                codec = self.ENCODERS[label]
                if re.search(rf"\b{re.escape(codec)}\b", text):
                    return label, codec
            return "CPU/x264", "libx264"
        codec = self.ENCODERS.get(requested)
        if not codec:
            return "CPU/x264", "libx264"
        if text and not re.search(rf"\b{re.escape(codec)}\b", text):
            raise RuntimeError(f"El encoder {requested} ({codec}) no está disponible en este FFmpeg.")
        return requested, codec

    def _build_command(self, source):
        if not self.ffmpeg or not os.path.isfile(self.ffmpeg):
            raise RuntimeError("FFmpeg no encontrado. Coloca ffmpeg.exe en la carpeta indicada por el proyecto.")
        if not source or not os.path.isfile(source):
            raise RuntimeError("Archivo no encontrado: " + str(source))
        if not self.url.lower().startswith(("rtmp://", "rtmps://")):
            raise RuntimeError("La salida debe comenzar por rtmp:// o rtmps://")
        try:
            w, h = [int(x) for x in self.resolution.lower().split("x", 1)]
        except Exception:
            raise RuntimeError("Resolución inválida")
        label, codec = self._resolve_encoder(self.encoder)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={self.fps}"
        # Un FFmpeg por clip permite cambiar el programa en caliente. El servidor RTMP
        # recibe la misma URL; al cambiar de clip FFmpeg reconecta automáticamente.
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-re", "-i", source,
               "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, "-c:v", codec,
               "-b:v", f"{self.bitrate}k", "-maxrate", f"{self.bitrate}k",
               "-bufsize", f"{self.bitrate*2}k", "-pix_fmt", "yuv420p", "-r", str(self.fps)]
        if codec == "libx264":
            cmd += ["-preset", "veryfast", "-profile:v", "high"]
        elif codec == "h264_nvenc":
            cmd += ["-preset", "fast", "-profile:v", "high"]
        elif codec == "h264_qsv":
            cmd += ["-preset", "medium", "-profile:v", "high"]
        elif codec == "h264_amf":
            cmd += ["-quality", "balanced", "-profile:v", "high"]
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-flvflags", "no_duration_filesize", "-f", "flv", self.url]
        return cmd, label

    def replace_sources(self, sources):
        new_sources = [str(x) for x in sources if x]
        if not new_sources:
            return False
        with self._lock:
            self._new_sources = new_sources
            self._switch_requested = True
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.log.emit(f"CAMBIO DE PROGRAMA RTMP • {len(new_sources)} medios")
        return True

    def run(self):
        try:
            with self._lock:
                sources = list(self.sources)
            if not sources:
                raise RuntimeError("No hay medios para emitir por RTMP.")
            self.stop_requested = False
            index = 0
            first = True
            while not self.stop_requested:
                with self._lock:
                    if self._new_sources:
                        sources = self._new_sources
                        self._new_sources = None
                        self._switch_requested = False
                        index = 0
                    if index >= len(sources):
                        index = 0
                    source = sources[index]
                cmd, label = self._build_command(source)
                self.log.emit(("FFmpeg iniciado" if first else "FFmpeg siguiente") + f" • {label} • {os.path.basename(source)}")
                self.log.emit(subprocess.list2cmdline(cmd))
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                             text=True, encoding="utf-8", errors="replace", creationflags=creationflags)
                if first:
                    self.state.emit(True, f"RTMP ON AIR • {label} • {self.resolution}@{self.fps}")
                    first = False
                assert self.proc.stderr is not None
                for line in self.proc.stderr:
                    line = line.rstrip()
                    if line:
                        self.log.emit("FFmpeg • " + line)
                    if self.stop_requested:
                        break
                    with self._lock:
                        if self._switch_requested:
                            break
                code = self.proc.wait()
                self.proc = None
                if self.stop_requested:
                    break
                with self._lock:
                    switched = self._switch_requested
                    if switched and self._new_sources:
                        sources = self._new_sources
                        self._new_sources = None
                        self._switch_requested = False
                        index = 0
                        self.log.emit("RTMP cambiado al nuevo programa")
                        continue
                if code not in (0, 255):
                    self.log.emit(f"FFmpeg terminó con código {code}")
                index += 1
            self.state.emit(False, "RTMP detenido")
        except Exception as e:
            self.proc = None
            self.state.emit(False, f"RTMP ERROR • {e}")
        finally:
            self.proc = None
            self.ended.emit()

    def stop(self):
        self.stop_requested = True
        with self._lock:
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate(); proc.wait(timeout=3)
            except Exception:
                try: proc.kill()
                except Exception: pass
