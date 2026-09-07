"""Registro del sistema (logs/tvplayout.log con rotación) + buffer en memoria para la ventana de registros."""
import collections
import logging
import threading
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR

LOG_FILE = LOG_DIR / "tvplayout.log"
_buffer = collections.deque(maxlen=2000)
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
    root.setLevel(logging.INFO)
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
    root._tvplayout_ready = True  # type: ignore[attr-defined]
    return root


def recent_lines(n=500):
    with _lock:
        return list(_buffer)[-n:]


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
