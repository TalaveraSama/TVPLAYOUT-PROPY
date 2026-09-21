@echo off
REM Compatibilidad de actualización: el nombre anterior era TVPlayoutPRO.exe.
setlocal EnableExtensions
cd /d "%~dp0"
title Nexora Air portable

if not exist "NexoraAir.exe" (
  echo No se encontro NexoraAir.exe en esta carpeta.
  echo Ejecuta build_exe.bat y copia la carpeta dist\NexoraAir completa.
  pause
  exit /b 1
)

if not exist "ffmpeg.exe" echo [AVISO] No se encontro ffmpeg.exe: RTMP quedara deshabilitado.
if not exist "ffprobe.exe" echo [AVISO] No se encontro ffprobe.exe: el escaneo no tendra metadatos.

start "Nexora Air" "%~dp0NexoraAir.exe"
exit /b 0
