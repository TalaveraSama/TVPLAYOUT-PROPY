@echo off
setlocal
cd /d "%~dp0"
title Nexora Air V25.3.2 (consola de depuracion)
if not exist ".venv\Scripts\python.exe" (
  echo No existe el entorno virtual. Ejecuta INSTALL.bat primero.
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
if errorlevel 1 (
  echo.
  echo Nexora Air se cerro con error. Revisa logs\nexora-air.log
  pause
)
