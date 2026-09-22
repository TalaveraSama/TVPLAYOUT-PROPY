@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo.
echo ============================================================
echo   NEXORA AIR V25.6.0 - INSTALADOR TODO-EN-UNO WINDOWS X64
echo ============================================================
echo.

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
  echo [ERROR] Python 3 no encontrado en el equipo de build.
  exit /b 1
)

%PY_CMD% installer\build_windows_setup.py all
if errorlevel 1 (
  echo.
  echo [ERROR] No se pudo crear el instalador.
  echo Instala NSIS 3 desde https://nsis.sourceforge.io/ o define MAKENSIS.
  exit /b 1
)

echo.
echo [OK] dist\Setup_NexoraAir_V25.6.0.exe
echo      Runtime Python, PySide6, PyAV y FFmpeg incluidos.
echo      Migra automaticamente los datos de TVPlayout PRO.
endlocal
