@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TVPlayout PRO portable

if not exist "TVPlayoutPRO.exe" (
  echo No se encontro TVPlayoutPRO.exe en esta carpeta.
  echo Ejecuta build_exe.bat y copia la carpeta dist\TVPlayoutPRO completa.
  pause
  exit /b 1
)

if not exist "ffmpeg.exe" echo [AVISO] No se encontro ffmpeg.exe: RTMP quedara deshabilitado.
if not exist "ffprobe.exe" echo [AVISO] No se encontro ffprobe.exe: el escaneo no tendra metadatos.

start "TVPlayout PRO" "%~dp0TVPlayoutPRO.exe"
exit /b 0
