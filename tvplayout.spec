# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para TVPlayout PRO V23.3.

Uso:
    pyinstaller tvplayout.spec --clean --noconfirm

Salida: dist/TVPlayoutPRO/TVPlayoutPRO.exe (modo onedir, más rápido de arrancar)
       dist/TVPlayoutPRO.exe                   (modo onefile, un solo .exe grande)
"""

import sys
from pathlib import Path

block_cipher = None

# Recolectar submódulos de la app (todos los archivos .py bajo app/)
a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PySide6.QtSvg',
        'PySide6.QtMultimedia',
        'app.config',
        'app.db',
        'app.dialogs',
        'app.dialogs_extra',
        'app.logger',
        'app.main_window',
        'app.mpv_player',
        'app.output',
        'app.playout',
        'app.prober',
        'app.scanner',
        'app.scheduler',
        'app.theme',
        'app.widgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TVPlayoutPRO',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # No usar UPX: corrompe binarios de PySide6 a veces
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # Sin consola (ventana GUI pura)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',   # descomentar si tenés un .ico
)
