"""Diagnóstico del IPC de mpv en Windows — SIN tocar la app.

Arranca mpv igual que TVPlayout (named pipe, --idle) y prueba tres formas
de LEER el stream de eventos JSON. Imprime cuál recibe respuesta.

Uso:
    .venv\\Scripts\\python tools\\diag_ipc.py
(o simplemente:  python tools\\diag_ipc.py)

No abre ventana de vídeo, no necesita clips, no modifica nada.
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MPV = os.path.join(ROOT, "mpv-x86_64", "mpv.exe")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _start_mpv(pipe_path):
    cmd = [
        MPV, "--idle=yes", "--no-terminal", "--really-quiet", "--vo=null", "--ao=null",
        "--no-config", "--load-scripts=no", "--input-ipc-server=" + pipe_path,
    ]
    p = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def _probe(name, conn_factory):
    """conn_factory() -> objeto con .send(bytes), .recv()->bytes, .close()."""
    print("\n=== Estrategia %s ===" % name)
    token = uuid.uuid4().hex[:10]
    pipe = r"\\.\pipe\diag_" + token
    p = _start_mpv(pipe)
    time.sleep(1.0)  # que mpv cree el pipe
    if p.poll() is not None:
        print("  mpv terminó solo (código %s) — no se pudo probar" % p.returncode)
        return
    conn = None
    received = []
    try:
        deadline = time.time() + 5
        while conn is None and time.time() < deadline:
            try:
                conn = conn_factory(pipe)
            except OSError as e:
                time.sleep(0.1)
                last = e
        if conn is None:
            print("  NO se pudo abrir el pipe: %s" % last)
            return

        stop = threading.Event()

        def reader():
            buf = b""
            while not stop.is_set():
                try:
                    data = conn.recv()
                except Exception as e:  # noqa: BLE001
                    received.append(("<error lectura: %r>" % e))
                    return
                if not data:
                    received.append("<pipe cerrado (b'')>")
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        received.append(line.decode("utf-8", "replace"))

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        for i, cmd in enumerate([
            ["get_property", "mpv-version"],
            ["observe_property", 1, "time-pos"],
            ["get_property", "idle-active"],
        ], 1):
            try:
                conn.send((json.dumps({"command": cmd, "request_id": i}) + "\n").encode("utf-8"))
                print("  -> enviado: %s" % cmd)
            except Exception as e:  # noqa: BLE001
                print("  -> ERROR enviando %s: %r" % (cmd, e))
        time.sleep(2.5)
        stop.set()

        if received:
            print("  RECIBIDO (%d líneas):" % len(received))
            for ln in received[:12]:
                print("     " + ln)
            print("  >>> ESTA ESTRATEGIA FUNCIONA <<<")
        else:
            print("  RECIBIDO: nada. Esta estrategia NO lee eventos.")
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------
# Estrategia A: multiprocessing.connection.PipeConnection (lo que usa la app hoy)
def _factory_pipeconnection(path):
    import _winapi
    from multiprocessing.connection import PipeConnection
    h = _winapi.CreateFile(path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                           _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
    c = PipeConnection(h)

    class W:
        def send(self, b):
            c.send_bytes(b)

        def recv(self):
            return bytes(c.recv_bytes(65536))

        def close(self):
            c.close()

    return W()


# Estrategia B: open() binario sin buffer
def _factory_openfile(path):
    f = open(path, "r+b", buffering=0)

    class W:
        def send(self, b):
            f.write(b)
            f.flush()

        def recv(self):
            return f.read(65536)

        def close(self):
            f.close()

    return W()


# Estrategia C: _winapi con E/S SOLAPADA cancelable (lectura por overlapped)
def _factory_overlapped(path):
    import _winapi
    h = _winapi.CreateFile(path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
                           _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)

    class W:
        def __init__(self):
            self._h = h
            self._pending = None

        def send(self, b):
            ov, err = _winapi.WriteFile(self._h, b, overlapped=True)
            try:
                if err == _winapi.ERROR_IO_PENDING:
                    _winapi.WaitForMultipleObjects([ov.event], False, _winapi.INFINITE)
                ov.GetOverlappedResult(True)
            except OSError:
                pass

        def recv(self):
            ov, err = _winapi.ReadFile(self._h, 65536, overlapped=True)
            self._pending = ov
            try:
                if err == _winapi.ERROR_IO_PENDING:
                    _winapi.WaitForMultipleObjects([ov.event], False, _winapi.INFINITE)
                nread, rerr = ov.GetOverlappedResult(True)
            except OSError as e:
                if getattr(e, "winerror", None) in (_winapi.ERROR_BROKEN_PIPE, 995):  # 995 = OPERATION_ABORTED
                    return b""
                raise
            finally:
                self._pending = None
            return bytes(ov.getbuffer()[:nread]) if nread else b""

        def close(self):
            try:
                if self._pending is not None:
                    self._pending.cancel()
            except Exception:  # noqa: BLE001
                pass
            _winapi.CloseHandle(self._h)

    return W()


_STRATS = {
    "A": ("A  PipeConnection (actual)", _factory_pipeconnection),
    "B": ("B  open() binario", _factory_openfile),
    "C": ("C  _winapi overlapped cancelable", _factory_overlapped),
}

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    print("mpv:", MPV, "| existe:", os.path.isfile(MPV), flush=True)
    print("python:", sys.version, flush=True)
    if not os.path.isfile(MPV):
        sys.exit("No se encuentra mpv.exe")
    which = [a.upper() for a in sys.argv[1:]] or ["A", "B", "C"]
    for key in which:
        if key in _STRATS:
            name, fac = _STRATS[key]
            _probe(name, fac)
            sys.stdout.flush()
    print("\nListo. Copia TODO esto y pégalo en el chat.", flush=True)
    os._exit(0)  # evita colgarse si un hilo lector quedó bloqueado
