"""Registro del sistema (logs/tvplayout.log con rotación) + buffer en memoria para la ventana de registros."""
import collections
import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR

LOG_FILE = LOG_DIR / "tvplayout.log"
_buffer = collections.deque(maxlen=2000)
_lock = threading.Lock()
_listeners = []
# DEBUG se activa con la variable de entorno TVPLAYOUT_DEBUG=1 (o .env) o
# en caliente desde la consola de debug (menú Registros → casilla DEBUG).
_DEBUG_ENV = os.environ.get("TVPLAYOUT_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
_hooks_installed = False


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
    root.setLevel(logging.DEBUG if _DEBUG_ENV else logging.INFO)
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


def is_debug():
    return logging.getLogger().level <= logging.DEBUG


def set_debug(on):
    """Cambia el nivel del logger raíz en caliente (consola de debug)."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if on else logging.INFO)
    root.log(logging.INFO, "log: nivel DEBUG %s", "ACTIVADO" if on else "desactivado")


def install_excepthooks():
    """Envía toda excepción no controlada (hilo principal, hilos de trabajo y
    mensajes de Qt) al log: archivo + buffer en memoria + consola de debug.

    Sin esto, una excepción dentro de un slot de Qt o de un hilo puede cerrar
    la app sin dejar rastro en logs/tvplayout.log.
    """
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    log = get("uncaught")

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Excepción no controlada:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _hook

    if hasattr(threading, "excepthook"):
        def _thook(args):
            if issubclass(args.exc_type, SystemExit):
                return
            log.error("Excepción no controlada en hilo %s:\n%s", getattr(args.thread, "name", "?"),
                      "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        threading.excepthook = _thook

    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        _levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }

        def _qt_handler(mode, _ctx, message):
            get("qt").log(_levels.get(mode, logging.INFO), "%s", message)

        qInstallMessageHandler(_qt_handler)
    except Exception:  # noqa: BLE001
        pass
