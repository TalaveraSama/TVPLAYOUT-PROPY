"""Ciclo de vida de procesos hijos FFmpeg (anti-huérfanos).

Problema que resuelve: si la aplicación se cierra (o muere) mientras FFmpeg
está emitiendo por RTMP, el proceso hijo queda huérfano y el servidor sigue
recibiendo la señal para siempre — el operador cierra Nexora Air y vMix
sigue viendo el stream.

Estrategia por plataforma:
  * Windows: cada hijo se asigna a un *Job Object* con
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. Si el proceso padre muere por
    cualquier motivo (cierre limpio, cierre de consola, Task Manager, crash),
    Windows mata a todos los hijos del job de forma automática.
  * Linux/macOS: los hijos heredan ``PR_SET_PDEATHSIG`` (SIGKILL si el padre
    muere) y además se registran en una lista global que un handler
    ``atexit`` termina de forma ordenada.
"""
import atexit
import logging
import os
import subprocess
import threading

log = logging.getLogger("nexora.proc")

_IS_WINDOWS = os.name == "nt"

# Registro global de procesos vivos, para el barrido de atexit.
_lock = threading.Lock()
_live_procs = set()

_job_handle = None          # HANDLE del Job Object (Windows)


def _win_job_handle():
    """Crea (una sola vez) el Job Object kill-on-close de Windows."""
    global _job_handle
    if _job_handle is not None or not _IS_WINDOWS:
        return _job_handle
    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JobObjectExtendedLimitInformation = 9
        JobObjectAssignProcess = 0
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        PROCESS_ALL_ACCESS = 0x1F0FFF

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitClass = 0
        ctypes.memset(ctypes.byref(info), 0, ctypes.sizeof(info))
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        if not kernel32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                ctypes.sizeof(info)):
            return None
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        _job_handle = job
        # Nunca se cierra el handle: al morir el proceso, Windows cierra el
        # job y mata a todos los hijos (exactamente lo que queremos).
        return _job_handle
    except Exception as exc:  # noqa: BLE001
        log.warning("Job Object no disponible; los hijos se limpian por atexit: %s", exc)
        return None


def _pdeathsig_preexec():
    """preexec_fn para Linux/macOS: pide SIGKILL si el padre muere."""
    try:
        import ctypes
        import signal
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    except Exception:  # noqa: BLE001
        pass


def _register(proc):
    with _lock:
        _live_procs.add(proc)
    return proc


def _unregister(proc):
    with _lock:
        _live_procs.discard(proc)


def popen(cmd, **kwargs):
    """``subprocess.Popen`` con protección anti-huérfanos.

    Todos los FFmpeg de la aplicación deben nacer por aquí: productores de
    spool, consumidores RTMP/SRT/UDP, extracción de subtítulos y generación
    de barras. El retorno es un ``Popen`` normal.
    """
    if _IS_WINDOWS:
        job = _win_job_handle()
        if job is not None:
            # Asignar al job en cuanto exista el proceso. subprocess no
            # ofrece "spawn suspended", así que hay una ventana mínima; los
            # FFmpeg no bifurcan hijos propios, el riesgo es despreciable.
            kwargs.setdefault("creationflags", 0)
            original = kwargs.pop("preexec_fn", None)
            proc = subprocess.Popen(cmd, **kwargs)
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.AssignProcessToJobObject(
                    job, int(proc._handle))     # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass
            _register(proc)
            return proc
        return _register(subprocess.Popen(cmd, **kwargs))
    kwargs.setdefault("preexec_fn", _pdeathsig_preexec)
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except ValueError:
        # preexec_fn no permitido en algún contexto (p. ej. subinterprete);
        # lanzar sin él antes que fallar.
        kwargs.pop("preexec_fn", None)
        proc = subprocess.Popen(cmd, **kwargs)
    return _register(proc)


def forget(proc):
    """Quita un proceso del registro de limpieza (ya terminó)."""
    _unregister(proc)


def terminate(proc, timeout=2.5):
    """Cierra un hijo de forma acotada (terminate → kill)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        _unregister(proc)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.kill()
        proc.wait(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass
    _unregister(proc)


def kill_all_live():
    """Barrido final (atexit): termina todos los hijos aún vivos."""
    with _lock:
        procs = list(_live_procs)
        _live_procs.clear()
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    for proc in procs:
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


atexit.register(kill_all_live)
