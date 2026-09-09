"""Emisor NDI directo mediante el Runtime instalado en Windows.

No usa FFmpeg ni ``libndi_newtek``. Reutiliza los QImage y PCM que ya produce
PyAVPlayer y llama a la API C de Processing.NDI.Lib.x64.dll mediante ctypes.
La integración es opcional: en Linux/desarrollo o si el Runtime no está
instalado, el módulo informa la causa y no interfiere con RTMP/SRT.
"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
from fractions import Fraction
from pathlib import Path

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
except ImportError:  # permite py_compile/test estático sin PySide6
    Qt = QImage = QPainter = None

from . import logger

log = logger.get("ndi")

_CREATE_NO_WINDOW = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)


def _fourcc(a, b, c, d):
    return (ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24))


FOURCC_BGRA = _fourcc("B", "G", "R", "A")
FOURCC_BGRX = _fourcc("B", "G", "R", "X")
FOURCC_FLTP = _fourcc("F", "L", "T", "p")
FRAME_PROGRESSIVE = 1


class _SendCreate(ctypes.Structure):
    _fields_ = [
        ("p_ndi_name", ctypes.c_char_p),
        ("p_groups", ctypes.c_char_p),
        ("clock_video", ctypes.c_bool),
        ("clock_audio", ctypes.c_bool),
    ]


class _VideoFrame(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_int),
        ("yres", ctypes.c_int),
        ("FourCC", ctypes.c_int),
        ("frame_rate_N", ctypes.c_int),
        ("frame_rate_D", ctypes.c_int),
        ("picture_aspect_ratio", ctypes.c_float),
        ("frame_format_type", ctypes.c_int),
        ("timecode", ctypes.c_int64),
        ("p_data", ctypes.POINTER(ctypes.c_uint8)),
        ("line_stride_in_bytes", ctypes.c_int),
        ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]


class _AudioFrameV3(ctypes.Structure):
    _fields_ = [
        ("sample_rate", ctypes.c_int),
        ("no_channels", ctypes.c_int),
        ("no_samples", ctypes.c_int),
        ("timecode", ctypes.c_int64),
        ("FourCC", ctypes.c_int),
        ("p_data", ctypes.POINTER(ctypes.c_uint8)),
        ("channel_stride_in_bytes", ctypes.c_int),
        ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]


class NDISender:
    """Publicador NDI para un nombre de fuente."""

    _lock = threading.RLock()
    _runtime = None
    _runtime_dir = None
    _runtime_users = 0

    @staticmethod
    def _candidates():
        out = []
        for env in ("NDI_RUNTIME_DIR_V6", "NDI_RUNTIME_DIR_V5", "NDI_RUNTIME_DIR_V4", "NDI_SDK_DIR"):
            value = os.environ.get(env, "").strip()
            if value:
                root = Path(value)
                out.extend([root,
                            root / "Processing.NDI.Lib.x64.dll", root / "bin" / "x64" / "Processing.NDI.Lib.x64.dll",
                            root / "v6" / "Processing.NDI.Lib.x64.dll", root / "v5" / "Processing.NDI.Lib.x64.dll",
                            root / "Lib" / "x64" / "Processing.NDI.Lib.x64.dll", root / "lib" / "x64" / "Processing.NDI.Lib.x64.dll"])
        for base in (os.environ.get("ProgramFiles", "C:\\Program Files"),
                     os.environ.get("ProgramW6432", "C:\\Program Files")):
            root = Path(base)
            for product in ("NDI", "NDI 6 Runtime", "NDI 5 Runtime", "NewTek\\NDI 5 Runtime", "NewTek\\NDI 4 Runtime"):
                out.extend([root / product / "v6" / "Processing.NDI.Lib.x64.dll",
                            root / product / "v5" / "Processing.NDI.Lib.x64.dll",
                            root / product / "Processing.NDI.Lib.x64.dll",
                            root / product / "bin" / "x64" / "Processing.NDI.Lib.x64.dll"])
        out.extend([Path.cwd() / "Processing.NDI.Lib.x64.dll",
                     Path(__file__).resolve().parent.parent / "Processing.NDI.Lib.x64.dll"])
        return out

    @classmethod
    def find_library(cls):
        if os.name != "nt":
            return ""
        for path in cls._candidates():
            try:
                if path.is_file():
                    return str(path.resolve())
            except OSError:
                pass
        return ""

    @classmethod
    def available(cls):
        return cls.probe()[0]

    @classmethod
    def probe(cls, name="TVPlayout PRO (prueba)"):
        """Prueba la DLL completa: carga, initialize, create y destroy."""
        sender = cls(name)
        if not sender.start():
            return False, sender.error, cls.find_library()
        sender.stop()
        return True, "NDI Runtime x64 listo", cls.find_library()

    @classmethod
    def _load_runtime(cls):
        with cls._lock:
            if cls._runtime is not None:
                cls._runtime_users += 1
                return cls._runtime
            path = cls.find_library()
            if not path:
                raise RuntimeError("Processing.NDI.Lib.x64.dll no encontrado")
            try:
                dll_dir = str(Path(path).parent)
                if hasattr(os, "add_dll_directory"):
                    cls._runtime_dir = os.add_dll_directory(dll_dir)
                lib = ctypes.WinDLL(path, use_last_error=True)
                lib.NDIlib_initialize.restype = ctypes.c_bool
                if not lib.NDIlib_initialize():
                    raise RuntimeError("NDIlib_initialize devolvió FALSE")
                lib.NDIlib_destroy.restype = None
                cls._runtime = lib
                cls._runtime_users = 1
                log.info("NDI Runtime cargado: %s", path)
                return lib
            except Exception:
                if cls._runtime_dir is not None:
                    cls._runtime_dir.close()
                    cls._runtime_dir = None
                raise

    @classmethod
    def _release_runtime(cls):
        with cls._lock:
            if cls._runtime is None:
                return
            cls._runtime_users = max(0, cls._runtime_users - 1)
            if cls._runtime_users == 0:
                try:
                    cls._runtime.NDIlib_destroy()
                finally:
                    cls._runtime = None
                    if cls._runtime_dir is not None:
                        cls._runtime_dir.close()
                        cls._runtime_dir = None

    def __init__(self, name, logo=None, fps="29.97"):
        self.name = str(name or "TVPlayout PRO").removeprefix("ndi://")
        self.logo = logo
        self.frame_rate_N, self.frame_rate_D = self._fps_ratio(fps)
        self.lib = None
        self.sender = None
        self._name_bytes = self.name.encode("utf-8", "replace")
        self._last_video_buffer = None
        self._last_audio_buffer = None
        self._tx_queue = queue.Queue(maxsize=24)
        self._tx_stop = threading.Event()
        self._tx_thread = None
        self.running = False
        self.last_position = 0.0
        self.last_duration = 0.0
        self.error = ""

    @staticmethod
    def _fps_ratio(value):
        try:
            rate = float(value)
            known = {23.976: (24000, 1001), 29.97: (30000, 1001), 59.94: (60000, 1001)}
            for key, ratio in known.items():
                if abs(rate - key) < 0.001:
                    return ratio
            fraction = Fraction(str(value or "25")).limit_denominator(1001)
            return max(1, fraction.numerator), max(1, fraction.denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return 25, 1

    def start(self):
        try:
            self.lib = self._load_runtime()
            self.lib.NDIlib_send_create.argtypes = [ctypes.POINTER(_SendCreate)]
            self.lib.NDIlib_send_create.restype = ctypes.c_void_p
            self.lib.NDIlib_send_destroy.argtypes = [ctypes.c_void_p]
            self.lib.NDIlib_send_destroy.restype = None
            self.lib.NDIlib_send_send_video_v2_async.argtypes = [ctypes.c_void_p, ctypes.POINTER(_VideoFrame)]
            self.lib.NDIlib_send_send_video_v2_async.restype = None
            self.lib.NDIlib_send_send_audio_v3.argtypes = [ctypes.c_void_p, ctypes.POINTER(_AudioFrameV3)]
            self.lib.NDIlib_send_send_audio_v3.restype = None
            opts = _SendCreate(self._name_bytes, None, False, True)
            self.sender = self.lib.NDIlib_send_create(ctypes.byref(opts))
            if not self.sender:
                raise RuntimeError("NDIlib_send_create devolvió NULL")
            self.running = True
            self._tx_stop.clear()
            self._tx_thread = threading.Thread(target=self._tx_loop, name=f"ndi-{self.name}", daemon=True)
            self._tx_thread.start()
            log.info("NDI sender activo: %s", self.name)
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            log.error("NDI no pudo iniciar (%s): %s", self.name, exc)
            self.stop()
            return False

    def set_logo(self, logo):
        self.logo = logo

    def _with_logo(self, image):
        if not self.logo or not self.logo.get("path") or not os.path.isfile(self.logo.get("path", "")):
            return image
        if QImage is None or QPainter is None:
            return image
        try:
            logo = QImage(self.logo["path"])
            if logo.isNull():
                return image
            canvas = image.copy()
            width, height = canvas.width(), canvas.height()
            lw = max(16, int(width * int(self.logo.get("scale", 10)) / 100))
            lh = max(1, int(lw * logo.height() / max(1, logo.width())))
            safe_width = min(width, height * 4 / 3)
            safe_left = (width - safe_width) / 2
            safe_right = safe_left + safe_width
            margin = int(self.logo.get("margin", 48))
            if "izquierda" in self.logo.get("position", "arriba-derecha"):
                x = int(safe_left + margin)
            else:
                x = int(safe_right - lw - margin)
            if "arriba" in self.logo.get("position", "arriba-derecha"):
                y = margin
            else:
                y = height - lh - margin
            painter = QPainter(canvas)
            painter.setOpacity(max(0.05, min(1.0, int(self.logo.get("opacity", 90)) / 100.0)))
            painter.drawImage(x, y, logo.scaled(lw, lh, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            painter.end()
            return canvas
        except Exception as exc:  # noqa: BLE001
            log.debug("NDI logo: %s", exc)
            return image

    def send_frame(self, image, position=0.0, duration=0.0):
        """Encola el frame para no convertir/copiar vídeo en el hilo de UI."""
        if not self.running or image is None:
            return
        try:
            self._tx_queue.put_nowait(("video", image, position, duration))
        except queue.Full:
            # El video es asíncrono: si el Runtime se atasca, descartamos el
            # frame viejo en lugar de frenar PyAV y el monitor local.
            pass

    def _tx_loop(self):
        while not self._tx_stop.is_set():
            try:
                kind, payload, position, duration = self._tx_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if kind == "video":
                    self._send_frame_now(payload, position, duration)
                else:
                    self._send_audio_now(payload)
            finally:
                self._tx_queue.task_done()

    def _send_frame_now(self, image, position=0.0, duration=0.0):
        if not self.running or self.sender is None or image is None or QImage is None:
            return
        try:
            image = self._with_logo(image).convertToFormat(QImage.Format.Format_BGRX8888)
            width, height = image.width(), image.height()
            stride = image.bytesPerLine()
            bits = image.constBits()
            try:
                bits.setsize(stride * height)
            except AttributeError:
                pass
            raw = bytes(bits)
            buf = (ctypes.c_uint8 * len(raw)).from_buffer_copy(raw)
            frame = _VideoFrame(width, height, FOURCC_BGRX, self.frame_rate_N, self.frame_rate_D,
                                width / max(1.0, height),
                                FRAME_PROGRESSIVE, 0, ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8)),
                                stride, None, 0)
            # El SDK conserva el buffer hasta la siguiente llamada async.
            old = self._last_video_buffer
            self._last_video_buffer = buf
            self.lib.NDIlib_send_send_video_v2_async(self.sender, ctypes.byref(frame))
            del old
            self.last_position = float(position or 0.0)
            self.last_duration = float(duration or 0.0)
        except Exception as exc:  # noqa: BLE001
            log.debug("NDI frame: %s", exc)

    def send_audio(self, pcm):
        """Encola audio sin bloquear la reproducción local."""
        if not self.running or not pcm:
            return
        try:
            self._tx_queue.put_nowait(("audio", bytes(pcm), 0.0, 0.0))
        except queue.Full:
            # Si el enlace no da abasto, perder un bloque corto es preferible
            # a crear una cola creciente y atrasar el aire.
            pass

    def _send_audio_now(self, pcm):
        if not self.running or self.sender is None or not pcm:
            return
        try:
            raw = bytes(pcm)
            sample_count = len(raw) // 4  # s16 interleaved estéreo
            if sample_count <= 0:
                return
            src = (ctypes.c_int16 * (sample_count * 2)).from_buffer_copy(raw[:sample_count * 4])
            dst = (ctypes.c_float * (sample_count * 2))()
            for i in range(sample_count):
                dst[i] = max(-1.0, min(1.0, src[i * 2] / 32768.0))
                dst[sample_count + i] = max(-1.0, min(1.0, src[i * 2 + 1] / 32768.0))
            frame = _AudioFrameV3(48000, 2, sample_count, 0, FOURCC_FLTP,
                                  ctypes.cast(dst, ctypes.POINTER(ctypes.c_uint8)),
                                  sample_count * ctypes.sizeof(ctypes.c_float), None, 0)
            self._last_audio_buffer = dst
            self.lib.NDIlib_send_send_audio_v3(self.sender, ctypes.byref(frame))
        except Exception as exc:  # noqa: BLE001
            log.debug("NDI audio: %s", exc)

    def stop(self):
        sender, lib = self.sender, self.lib
        self.running = False
        self._tx_stop.set()
        tx_thread = self._tx_thread
        self._tx_thread = None
        if tx_thread is not None and tx_thread is not threading.current_thread():
            # No se destruye el sender mientras el hilo pudiera seguir dentro
            # de la llamada async del SDK; así los buffers permanecen válidos.
            tx_thread.join()
        while True:
            try:
                self._tx_queue.get_nowait()
                self._tx_queue.task_done()
            except queue.Empty:
                break
        self.sender = None
        if sender and lib:
            try:
                # Sincroniza el último frame async antes de liberar su buffer
                # y destruir únicamente este sender.
                empty = ctypes.POINTER(_VideoFrame)()
                lib.NDIlib_send_send_video_v2_async(sender, empty)
            except Exception:
                pass
            try:
                lib.NDIlib_send_destroy(sender)
            except Exception:
                pass
        self._last_video_buffer = None
        self._last_audio_buffer = None
        if lib:
            self._release_runtime()
        self.lib = None
