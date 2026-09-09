@echo off
setlocal
cd /d "%~dp0"
title TVPlayout PRO V24.0.2.4 (consola de depuracion)
if not exist ".venv\Scripts\python.exe" (
  echo No existe el entorno virtual. Ejecuta INSTALL.bat primero.
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
if errorlevel 1 (
  echo.
  echo TVPlayout PRO se cerro con error. Revisa logs\tvplayout.log
  pause
)
