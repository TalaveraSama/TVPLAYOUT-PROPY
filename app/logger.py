"""Registro del sistema (logs/tvplayout.log con rotación) + buffer en memoria para la ventana de registros."""
import collections
import logging
import os
import threading
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR

LOG_FILE = LOG_DIR / "tvplayout.log"
_buffer = collections.deque(maxlen=10000)
_lock = threading.Lock()
_listeners = []


class _MemoryHandler(logging.Handler):
    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001
            return
        with _lock:
            _buffer.append(line)
            listeners = list(_listeners)
        for cb in listeners:
            try:
                cb(line)
            except Exception:  # noqa: BLE001
                pass


def setup():
    root = logging.getLogger()
    if getattr(root, "_tvplayout_ready", False):
        return root
    # En modo debug se conserva todo el detalle, incluyendo eventos de
    # QtMultimedia/IPC. El archivo y la consola nunca pierden DEBUG; la UI
    # puede filtrar por nivel.
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = RotatingFileHandler(str(LOG_FILE), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    mh = _MemoryHandler()
    mh.setFormatter(fmt)
    root.addHandler(mh)
    # INICIAR_CONSOLA.bat activa TVPLAYOUT_DEBUG=1 para que el operador
    # pueda copiar el diagnóstico también desde la ventana de consola.
    if os.environ.get("TVPLAYOUT_DEBUG", "").lower() in ("1", "true", "yes", "on"):
        sh = logging.StreamHandler()
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    root._tvplayout_ready = True  # type: ignore[attr-defined]
    return root


def recent_lines(n=500):
    with _lock:
        return list(_buffer)[-n:]


def count_by_level(n=500):
    """Cuenta cuántas líneas recientes hay de cada nivel (INFO/WARNING/ERROR/DEBUG).

    Útil para mostrar un badge en la UI.
    """
    counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "DEBUG": 0}
    with _lock:
        for line in list(_buffer)[-n:]:
            up = line.upper()
            if "ERROR" in up:
                counts["ERROR"] += 1
            elif "WARNING" in up:
                counts["WARNING"] += 1
            elif "DEBUG" in up:
                counts["DEBUG"] += 1
            else:
                counts["INFO"] += 1
    return counts


def add_listener(cb):
    with _lock:
        _listeners.append(cb)


def remove_listener(cb):
    with _lock:
        if cb in _listeners:
            _listeners.remove(cb)


def get(name):
    setup()
    return logging.getLogger(name)
