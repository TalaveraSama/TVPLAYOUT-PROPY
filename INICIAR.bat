@echo off
setlocal
cd /d "%~dp0"
title TVPlayout PRO V22
if not exist ".venv\Scripts\pythonw.exe" (
  echo No existe el entorno virtual.
  echo Ejecuta INSTALL.bat primero.
  pause
  exit /b 1
)
if not exist "mpv-x86_64\mpv.exe" (
  echo [AVISO] No se encontro mpv-x86_64\mpv.exe  ^(el monitor local no funcionara^)
)
if not exist "ffmpeg.exe" if not exist "ffmpeg\bin\ffmpeg.exe" if not exist "bin\ffmpeg.exe" (
  echo [AVISO] No se encontro ffmpeg.exe  ^(la salida RTMP y el analisis de medios no funcionaran^)
)
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0
