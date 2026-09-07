@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No existe el entorno virtual.
  echo Ejecuta INSTALL.bat primero.
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
if errorlevel 1 (
  echo.
  echo TVPlayout PRO se cerro con error.
  pause
)
