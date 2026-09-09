@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV=.venv"
set "PYTHON_EXE=%VENV%\Scripts\python.exe"

echo ================================================
echo   TVPlayout PRO V24.0.2.3 - INSTALADOR
echo ================================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python Launcher encontrado.
    py -3.13 --version >nul 2>&1
    if %errorlevel%==0 (
        set "PY=py -3.13"
    ) else (
        py -3 --version >nul 2>&1
        if errorlevel 1 goto :no_python
        set "PY=py -3"
    )
) else (
    where python >nul 2>&1
    if errorlevel 1 goto :no_python
    set "PY=python"
)

for /f "tokens=*" %%A in ('%PY% --version 2^>^&1') do echo [OK] %%A

if exist "%PYTHON_EXE%" goto :venv_ok

echo [1/5] Creando entorno virtual...
%PY% -m venv "%VENV%"
if errorlevel 1 goto :error
:venv_ok
if not exist "%PYTHON_EXE%" goto :error

echo [OK] Entorno virtual listo.

echo.
echo [2/5] Reparando pip...
"%PYTHON_EXE%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error

echo.
echo [3/5] Limpiando restos de PySide6...
"%PYTHON_EXE%" -m pip uninstall -y PySide6 PySide6_Addons PySide6_Essentials shiboken6 >nul 2>&1

if not exist requirements.txt goto :no_requirements

echo.
echo [4/5] Instalando PySide6 + PyAV/libav para Python 3.13...
"%PYTHON_EXE%" -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt
if errorlevel 1 goto :error

goto :verify

:no_requirements
echo [ERROR] No existe requirements.txt
goto :error

:verify
echo.
echo [5/5] Verificando instalacion...
"%PYTHON_EXE%" -c "import sys, PySide6, av; print('Python:',sys.version.split()[0]); print('PySide6:',PySide6.__version__); print('PyAV:',av.__version__)"
if errorlevel 1 goto :error

if not exist logs mkdir logs
if not exist cache mkdir cache

echo.
echo ================================================
echo   INSTALACION COMPLETADA CORRECTAMENTE
echo ================================================
echo.
echo Coloca ffmpeg.exe + ffprobe.exe en esta carpeta para la salida RTMP.
echo Ejecuta INICIAR.bat
pause
exit /b 0

:no_python
echo [ERROR] Python 3.13/3.x no esta disponible.
echo Instala Python 3.13 x64 y vuelve a ejecutar este instalador.
pause
exit /b 1

:error
echo.
echo ================================================
echo   ERROR DURANTE LA INSTALACION
echo ================================================
echo Revisa el mensaje anterior.
echo.
pause
exit /b 1
