import json, os, subprocess, time
from PySide6.QtCore import QObject, Signal, QTimer

class MPVPlayer(QObject):
    status = Signal(str)
    ended = Signal()

    def __init__(self, video_widget, mpv_path):
        super().__init__()
        self.widget = video_widget
        self.mpv_path = mpv_path
        self.proc = None
        self.ipc_path = None
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._read_events)

    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        if not self.mpv_path:
            self.status.emit("MPV no encontrado")
            return False
        self.ipc_path = r"\\.\pipe\TVPlayoutPRO_MPV"
        wid = str(int(self.widget.winId()))
        cmd = [self.mpv_path, f"--wid={wid}", "--force-window=no", "--idle=yes",
               "--keep-open=no", "--input-default-bindings=no", "--input-ipc-server=" + self.ipc_path,
               "--osd-level=0", "--no-terminal", "--really-quiet"]
        try:
            self.proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for _ in range(40):
                if os.path.exists(self.ipc_path): break
                time.sleep(0.05)
            self._poll.start(); self.status.emit("MPV listo"); return True
        except Exception as e:
            self.status.emit(f"MPV: {e}"); return False

    def _send(self, command):
        if not self.ipc_path: return False
        try:
            with open(self.ipc_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"command": command}) + "\n"); f.flush()
            return True
        except Exception as e:
            self.status.emit(f"MPV IPC: {e}"); return False

    def play(self, path):
        if not self.start(): return False
        ok = self._send(["loadfile", path, "replace"])
        if ok: self.status.emit(os.path.basename(path))
        return ok

    def pause(self): return self._send(["cycle", "pause"])
    def set_mute(self, muted): return self._send(["set_property", "mute", bool(muted)])
    def set_volume(self, value): return self._send(["set_property", "volume", float(value)])

    def stop(self):
        self._send(["stop"]); self._poll.stop()
        if self.proc:
            try: self.proc.terminate(); self.proc.wait(timeout=2)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
        self.proc = None

    def _read_events(self):
        if self.proc and self.proc.poll() is not None:
            self._poll.stop(); self.proc = None; self.ended.emit()
