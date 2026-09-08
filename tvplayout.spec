# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para TVPlayout PRO.

Produce una distribución onedir portable:
    dist/TVPlayoutPRO/TVPlayoutPRO.exe

Las DLL de PySide6/PyAV quedan en _internal junto al ejecutable. El BAT de
build copia ffmpeg.exe, ffprobe.exe y mpv.exe (si están disponibles) al nivel
del EXE, porque son herramientas externas y no deben mezclarse con el runtime
Python.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
APP_ROOT = Path(__file__).resolve().parent

# PyAV carga parte de libav dinámicamente; collect_all evita que una versión
# nueva de PyAV quede incompleta por depender de un nombre de DLL no listado.
av_datas, av_binaries, av_hidden = collect_all("av")
app_hidden = collect_submodules("app")

analysis = Analysis(
    [str(APP_ROOT / "main.py")],
    pathex=[str(APP_ROOT)],
    binaries=av_binaries,
    datas=av_datas,
    hiddenimports=sorted(set(av_hidden + app_hidden + [
        "PySide6.QtSvg",
        "PySide6.QtMultimedia",
        "app.pyav_player",
    ])),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pandas",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="TVPlayoutPRO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    name="TVPlayoutPRO",
)
