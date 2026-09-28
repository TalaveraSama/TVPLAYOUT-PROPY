"""Detección segura del runtime nativo de OBS Studio.

Esta capa no ejecuta ``obs.exe`` ni confunde el proceso FFmpeg con OBS. El
backend libobs solo se puede activar cuando están presentes las DLL y plugins
nativos compilados para la arquitectura de Nexora. Mientras tanto, el
orquestador conserva FFmpeg como fallback explícito.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from .config import ROOT

_REQUIRED = ("obs.dll", "obs-outputs.dll")


def candidate_roots() -> tuple[Path, ...]:
    values = []
    configured = os.environ.get("NEXORA_OBS_ROOT", "").strip()
    if configured:
        values.append(Path(configured))
    values.extend((ROOT / "obs", ROOT / "obs-studio", ROOT / "libobs"))
    return tuple(dict.fromkeys(values))


def locate_runtime() -> dict:
    """Return paths and a loadable flag without starting an OBS output."""
    for root in candidate_roots():
        bin_root = root / "bin" / "64bit"
        candidates = (root, bin_root, root / "bin")
        for directory in candidates:
            if all((directory / name).is_file() for name in _REQUIRED):
                return {
                    "available": True,
                    "root": str(root),
                    "directory": str(directory),
                    "libraries": {name: str(directory / name) for name in _REQUIRED},
                }
    return {"available": False, "root": "", "directory": "", "libraries": {}}


def load_probe() -> tuple[bool, str]:
    """Load libobs only as a probe; no scene/output is created here."""
    info = locate_runtime()
    if not info["available"]:
        return False, "runtime libobs no encontrado"
    try:
        ctypes.WinDLL(info["libraries"]["obs.dll"])
        ctypes.WinDLL(info["libraries"]["obs-outputs.dll"])
    except (AttributeError, OSError) as exc:
        return False, f"runtime libobs no se pudo cargar: {exc}"
    return True, f"runtime libobs disponible en {info['directory']}"


def status_line() -> str:
    """Human-readable diagnostic line for the UI log."""
    ok, message = load_probe()
    return f"obs: {'disponible' if ok else 'no disponible'} • {message}"
