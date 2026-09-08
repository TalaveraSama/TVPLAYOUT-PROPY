"""Control del reproductor mpv embebido mediante IPC JSON.

Windows: named pipe (\\\\.\\pipe\\...) con E/S solapada (lectura y escritura simultáneas desde hilos distintos).
Linux/macOS: socket UNIX.
"""
import ctypes
import json
import os
import socket
import subprocess
import threading
import time
import uuid

from PySide6.QtCore import QObject, Signal, QTimer

from . import logger

log = logger.get("mpv")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROP_IDS = {"time-pos": 1, "duration": 2, "pause": 3, "idle-active": 4, "eof-reached": 5, "volume": 6, "mute": 7}
# v22.2.9: formato del filtro VU actualizado. Antes usábamos
# "lavfi=[astats=...:measure_perchannel=Peak_level:measure_overall=none]"
# que asume 2 canales separados (lavfi.astats.1.P y lavfi.astats.2.P).
# En builds nuevos de mpv (0.41+) las keys son distintas y los
# corchetes ya no se aceptan. El formato correcto es:
#   lavfi=astats=metadata=1:reset=1
# Y las keys de salida son lavfi.astats.Overall.Peak_level y
# lavfi.astats.Overall.RMS_level (no .1. ni .2. para peak).
# Si querés canales separados, podés usar
#   lavfi=astats=metadata=1:reset=1:length=0.1
# pero Overall.Peak_level es suficiente para un VU estéreo en vivo.
VU_FILTER = "@vu:lavfi=astats=metadata=1:reset=1"


class _PipeConn:
    """Conexión IPC bidireccional (pipe Windows o socket UNIX)."""

    def __init__(self, path):
        self.path = path
        self._win = os.name == "nt"
        if self._win:
            import _winapi  # noqa: WPS433
            from multiprocessing.connection import PipeConnection  # type: ignore
            handle = _winapi.CreateFile(path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                                        _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
            self._conn = PipeConnection(handle)
        else:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(path)

    def send(self, data: bytes):
        if self._win:
            self._conn.send_bytes(data)
        else:
            self._sock.sendall(data)

    def recv(self) -> bytes:
        if self._win:
            return self._conn.recv_bytes(65536)
        return self._sock.recv(65536)

    def close(self):
        try:
            if self._win:
                self._conn.close()
            else:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._sock.close()
        except Exception:  # noqa: BLE001
            pass


class MPVPlayer(QObject):
    status = Signal(str)
    ended = Signal(str)               # motivo: eof | stop | error | quit | redirect | unknown
    loaded = Signal()                 # file-loaded
    position = Signal(float, float)   # time-pos, duration
    levels = Signal(float, float)     # dBFS canal izq / der
    idle = Signal(bool)
    process_died = Signal()
    _vu_ready = Signal(bool)          # interno: resultado de añadir el filtro VU (emitido desde el hilo lector)

    def __init__(self, video_widget, mpv_path, parent=None):
        super().__init__(parent)
        self.widget = video_widget
        self.mpv_path = mpv_path
        self.proc = None
        self.ipc_path = None
        self._conn = None
        self._reader = None
        self._req_id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._time = 0.0
        self._duration = 0.0
        self._vu_state = None      # None = sin intentar, True = activo, False = no disponible
        self._current_path = ""
        self.hwdec = "auto-safe"
        self.audio_device = ""
        self.alang = "es-MX,es-419,spa,es"
        self.slang = ""
        self.volume = 100
        self.muted = False
        self._watch = QTimer(self)
        self._watch.setInterval(500)
        self._watch.timeout.connect(self._check_process)
        self._vu_timer = QTimer(self)
        self._vu_timer.setInterval(120)
        self._vu_timer.timeout.connect(self._poll_vu)
        self._vu_ready.connect(self._on_vu_ready)
        try:
            self.widget.resized.connect(self._fit_child_window)
        except AttributeError:
            pass

    # ------------------------------------------------------------- proceso
    @property
    def available(self):
        return bool(self.mpv_path) and os.path.isfile(self.mpv_path)

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def current_path(self):
        return self._current_path

    def _build_cmd(self):
        wid = str(int(self.widget.winId()))
        cmd = [self.mpv_path, f"--wid={wid}", "--idle=yes", "--force-window=yes", "--keep-open=no",
               "--input-default-bindings=no", "--input-vo-keyboard=no", "--osc=no", "--osd-level=0",
               "--no-terminal", "--really-quiet", "--cursor-autohide=no",
               "--input-ipc-server=" + self.ipc_path, f"--hwdec={self.hwdec or 'no'}",
               f"--volume={int(self.volume)}", f"--mute={'yes' if self.muted else 'no'}",
               "--audio-file-auto=no", "--sub-auto=no", "--ytdl=no", "--load-scripts=no"]
        if self.alang:
            cmd.append(f"--alang={self.alang}")
        if self.slang:
            cmd.append(f"--slang={self.slang}")
        else:
            cmd.append("--sid=no")
        if self.audio_device:
            cmd.append(f"--audio-device={self.audio_device}")
        return cmd

    def start(self):
        if self.running and self._conn is not None:
            return True
        if not self.available:
            self.status.emit("MPV no encontrado (mpv-x86_64\\mpv.exe)")
            return False
        token = uuid.uuid4().hex[:10]
        if os.name == "nt":
            self.ipc_path = r"\\.\pipe\TVPlayoutPRO_" + token
        else:
            self.ipc_path = f"/tmp/tvplayout_mpv_{token}.sock"
        cmd = self._build_cmd()
        try:
            self.proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo iniciar mpv: %s", e)
            self.status.emit(f"MPV: {e}")
            self.proc = None
            return False
        conn = self._connect(timeout=8.0)
        if conn is None:
            code = self.proc.poll() if self.proc else None
            log.error("mpv no abrió el IPC en %s (código %s)", self.ipc_path, code)
            self.status.emit("MPV: no se pudo conectar al IPC" + (f" (mpv terminó con código {code})" if code is not None else ""))
            self._kill()
            return False
        self._attach(conn)
        self.status.emit("MPV listo")
        log.info("mpv iniciado: %s", subprocess.list2cmdline(cmd))
        QTimer.singleShot(300, self._fit_child_window)
        return True

    def _connect(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return None
            try:
                return _PipeConn(self.ipc_path)
            except OSError:
                time.sleep(0.05)
        return None

    def _attach(self, conn):
        self._conn = conn
        self._vu_state = None
        self._reader = threading.Thread(target=self._read_loop, args=(conn,), name="mpv-ipc", daemon=True)
        self._reader.start()
        for name, pid in PROP_IDS.items():
            self.command(["observe_property", pid, name])
        self._watch.start()

    def _kill(self):
        p = self.proc
        self.proc = None
        conn = self._conn
        self._conn = None
        if conn is not None:
            conn.close()
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        if self.ipc_path and os.name != "nt":
            try:
                os.unlink(self.ipc_path)
            except OSError:
                pass

    def shutdown(self):
        self._watch.stop()
        self._vu_timer.stop()
        if self.running:
            self.command(["quit"])
            try:
                self.proc.wait(timeout=1.5)
            except Exception:  # noqa: BLE001
                pass
        self._kill()

    def _check_process(self):
        if self.proc is not None and self.proc.poll() is not None:
            code = self.proc.returncode
            log.warning("mpv terminó inesperadamente (código %s)", code)
            self._kill()
            self._watch.stop()
            self._vu_timer.stop()
            self._current_path = ""
            self.process_died.emit()

    def _fit_child_window(self):
        """Windows: ajusta la ventana hija de mpv al tamaño del widget contenedor."""
        if os.name != "nt" or not self.running:
            return
        try:
            user32 = ctypes.windll.user32
            parent = int(self.widget.winId())
            w = max(1, self.widget.width())
            h = max(1, self.widget.height())
            EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def cb(hwnd, _lparam):
                user32.MoveWindow(ctypes.c_void_p(hwnd), 0, 0, w, h, True)
                return True

            user32.EnumChildWindows(ctypes.c_void_p(parent), EnumChildProc(cb), 0)
        except Exception as e:  # noqa: BLE001
            log.debug("fit child window: %s", e)

    # ----------------------------------------------------------------- IPC
    def command(self, cmd, callback=None):
        conn = self._conn
        if conn is None:
            return False
        with self._lock:
            self._req_id += 1
            rid = self._req_id
            if callback:
                self._pending[rid] = callback
        try:
            conn.send((json.dumps({"command": cmd, "request_id": rid, "async": True}) + "\n").encode("utf-8"))
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("IPC send falló: %s", e)
            with self._lock:
                self._pending.pop(rid, None)
            return False

    def set_property(self, name, value):
        return self.command(["set_property", name, value])

    def _read_loop(self, conn):
        buf = b""
        while conn is self._conn:
            try:
                data = conn.recv()
            except Exception:  # noqa: BLE001
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                try:
                    self._handle(msg)
                except Exception as e:  # noqa: BLE001
                    log.debug("evento mpv: %s", e)
        log.debug("hilo IPC finalizado")

    def _handle(self, msg):
        if "request_id" in msg and "event" not in msg:
            with self._lock:
                cb = self._pending.pop(msg["request_id"], None)
            if cb:
                cb(msg.get("error"), msg.get("data"))
            return
        ev = msg.get("event")
        if ev == "property-change":
            name, data = msg.get("name"), msg.get("data")
            if name == "time-pos":
                if isinstance(data, (int, float)):
                    self._time = float(data)
                    self.position.emit(self._time, self._duration)
            elif name == "duration":
                if isinstance(data, (int, float)):
                    self._duration = float(data)
                    self.position.emit(self._time, self._duration)
            elif name == "idle-active":
                self.idle.emit(bool(data))
        elif ev == "file-loaded":
            self._time = 0.0
            self.loaded.emit()
            if self._vu_state is None:
                self._vu_state = False
                self.command(["af", "add", VU_FILTER], self._vu_added)
        elif ev == "end-file":
            reason = msg.get("reason", "unknown")
            if reason == "error":
                log.warning("mpv error de archivo: %s", msg.get("file_error", ""))
            self._current_path = ""
            self.ended.emit(reason)

    # hilo lector → señal → hilo Qt
    def _vu_added(self, error, _data):
        self._vu_ready.emit(error == "success")

    def _on_vu_ready(self, ok):
        self._vu_state = bool(ok)
        if ok:
            self._vu_timer.start()
        else:
            # v22.2.5: el VU usa el filtro lavfi=astats, que no está en
            # todos los builds de mpv (especialmente los recortados). Si
            # falla, lo dejamos en WARNING para que el operador se entere
            # de que tiene que actualizar el binario de mpv.
            log.warning("VU meter no disponible en este mpv (lavfi/astats no soportado). Actualizá mpv a una build con lavfi (shinchiro/zhongfly).")

    def _poll_vu(self):
        if not self._vu_state or not self.running:
            return
        self.command(["get_property", "af-metadata/vu"], self._vu_data)

    def _vu_data(self, error, data):
        if error != "success" or not isinstance(data, dict):
            return

        def val(key):
            try:
                v = float(data.get(key, "-inf"))
            except (TypeError, ValueError):
                v = -90.0
            return max(-90.0, v)

        # v22.2.9: las keys de astats cambiaron en builds nuevos de mpv.
        # Antes leíamos lavfi.astats.1.Peak_level y lavfi.astats.2.Peak_level
        # (formato viejo que asume canales separados). En mpv 0.40+ las
        # keys son lavfi.astats.Overall.Peak_level y lavfi.astats.Overall.RMS_level.
        # Leemos Overall.Peak_level (que es el pico instantáneo del audio
        # en dBFS, lo que se ve en un VU meter).
        left = val("lavfi.astats.Overall.Peak_level")
        right = val("lavfi.astats.Overall.RMS_level")
        self.levels.emit(left, right)

    # ------------------------------------------------------------ control
    def play(self, path, audio_id=None, sub_id=None, start=0.0, loop=False):
        if not self.start():
            return False
        self._current_path = path
        # v22.2.7: bug crítico de sincronización. Antes mandábamos 7
        # set_property ANTES del loadfile (aid/sid/start/loop-file/
        # volume/mute/pause). Esto causaba tres problemas en builds
        # modernos de mpv:
        #  1) set_property("start", "none") podía conservarse del
        #     archivo anterior (#15544 en mpv repo: loadfile a veces
        #     ignora start cuando viene de un set_property previo).
        #  2) set_property("pause", false) ANTES del loadfile hacía
        #     que el nuevo archivo arrancara con un frame del archivo
        #     anterior (estado interno de mpv inconsistente).
        #  3) Los set_property y el loadfile entran en cola en orden,
        #     pero mpv puede procesarlos fuera de orden. Las propiedades
        #     de la sesión anterior (volume, mute, start) se aplicaban
        #     al archivo viejo.
        # Síntoma: el panel mostraba "AL AIRE" el nuevo clip pero el
        # monitor seguía mostrando el frame del clip anterior.
        #
        # Fix: usar loadfile con opciones embebidas (start, pause, volume,
        # mute, loop-file, sid, aid) en un solo comando atómico. Las
        # opciones embebidas en loadfile SÍ se aplican en orden, antes
        # de decodificar el primer frame del nuevo archivo.
        # v22.2.8: NO usar opciones embebidas en loadfile — mpv las
        # rechaza (issue #5770). Volvemos a set_property separados.
        # El método _post_load_apply se encarga de reaplicar las
        # propiedades críticas 200ms después del loadfile.
        if isinstance(audio_id, int) and audio_id >= 0:
            self.set_property("aid", int(audio_id) + 1)
        else:
            self.set_property("aid", "auto")
        if sub_id is None:
            self.set_property("sid", "auto" if self.slang else "no")
        elif sub_id < 0:
            self.set_property("sid", "no")
        else:
            self.set_property("sid", int(sub_id) + 1)
        # start=0 → "none" para que mpv no herede offset anterior
        self.set_property("start", f"{float(start):.3f}" if start and start > 0 else "none")
        self.set_property("loop-file", "inf" if loop else "no")
        self.set_property("volume", float(self.volume))
        self.set_property("mute", "yes" if self.muted else "no")
        ok = self.command(["loadfile", path, "replace"])
        if ok:
            self.status.emit("MPV ▶ " + os.path.basename(path))
            # v22.2.8: reaplicar pause/volume/mute 200ms después del
            # loadfile. Cubre el caso donde mpv procesa los
            # set_property que llegaron antes que el loadfile y los
            # aplica al archivo anterior.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, self._post_load_apply)
        return ok

    def stop(self):
        self._current_path = ""
        return self.command(["stop"])

    def _post_load_apply(self):
        """v22.2.8: reaplica pause/volume/mute 200ms después del loadfile.

        Por qué: en v22.2.1-v22.2.6 mandábamos los set_property ANTES del
        loadfile. En algunos builds de mpv, esos set_property se aplicaban
        al archivo anterior (que estaba saliendo) y el nuevo archivo
        quedaba con el frame del anterior, mute, o pause.
        En v22.2.7 intentamos embeber las opciones en el loadfile, pero
        mpv RECHAZA opciones embebidas (issue #5770: "loadfile sólo
        acepta 3 opciones"). El loadfile fallaba silenciosamente.

        La solución: mandar los set_property ANTES (como hasta v22.2.6) y
        REPETIRLOS 200ms después con un QTimer.singleShot. Eso cubre
        ambos casos: builds que procesan los set_property antes del
        loadfile (v22.2.1) y builds que los procesan después (v22.2.7).
        """
        if not self.running:
            return
        try:
            self.set_property("pause", "no")
            self.set_property("volume", float(self.volume))
            self.set_property("mute", "yes" if self.muted else "no")
        except Exception as e:  # noqa: BLE001
            log.debug("post_load_apply: %s", e)

    def set_pause(self, paused):
        return self.set_property("pause", bool(paused))

    def set_mute(self, muted):
        # v22.2.5: mpv acepta 'yes'/'no' para propiedades booleanas. Antes
        # mandábamos True/False como JSON, que mpv puede rechazar según
        # la versión, dejando el audio sin silenciar.
        self.muted = bool(muted)
        return self.set_property("mute", "yes" if muted else "no")

    def set_volume(self, value):
        self.volume = int(value)
        return self.set_property("volume", float(value))

    def seek(self, seconds, absolute=False):
        return self.command(["seek", float(seconds), "absolute" if absolute else "relative"])

    def set_track_langs(self, alang, slang):
        self.alang, self.slang = alang, slang
        if self.running:
            self.set_property("alang", alang)
            self.set_property("slang", slang)

    def open_external_preview(self, path, title="PREVIEW"):
        """Abre el clip en una ventana mpv independiente (previsualización sin afectar el aire)."""
        if not self.available:
            self.status.emit("MPV no encontrado")
            return False
        cmd = [self.mpv_path, f"--title={title} — {os.path.basename(path)}", "--force-window=yes", "--keep-open=yes",
               "--osc=yes", "--geometry=40%", "--no-terminal", "--ytdl=no", "--load-scripts=no", path]
        if self.alang:
            cmd.insert(1, f"--alang={self.alang}")
        try:
            subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:  # noqa: BLE001
            self.status.emit(f"MPV preview: {e}")
            return False
