@echo off
REM ====================================================================
REM   TVPlayout PRO V24.0.0.4 - Generador de ejecutable
REM   Uso: doble clic en este archivo desde la carpeta del proyecto.
REM   Genera: dist\TVPlayoutPRO.exe
REM ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ================================================
echo   TVPlayout PRO V24.0.0.4 - BUILD
echo ================================================
echo.

REM --- 1. Detectar Python ----------------------------------------------
set "PY="
where py >nul 2>&1
if %errorlevel%==0 (
    py -3.13 --version >nul 2>&1
    if !errorlevel!==0 ( set "PY=py -3.13" ) else (
        py -3 --version >nul 2>&1
        if !errorlevel!==0 ( set "PY=py -3" ) else (
            py --version >nul 2>&1
            if !errorlevel!==0 ( set "PY=py" )
        )
    )
)
if not defined PY (
    where python >nul 2>&1
    if %errorlevel%==0 ( set "PY=python" )
)
if not defined PY (
    echo [ERROR] No se encontro Python. Instala Python 3.10 o 3.13 desde
    echo         https://www.python.org/downloads/  (tildar "Add to PATH").
    pause
    exit /b 1
)
for /f "tokens=*" %%A in ('%PY% --version 2^>^&1') do echo [OK] Python: %%A

REM --- 2. Crear / usar venv dedicado al build -------------------------
if not exist ".venv-build" (
    echo [..] Creando entorno virtual .venv-build ...
    %PY% -m venv .venv-build
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el venv.
        pause
        exit /b 1
    )
)
set "VENV=.venv-build"
set "PYEXE=%VENV%\Scripts\python.exe"

REM --- 3. Instalar dependencias de runtime + build ---------------------
echo [..] Instalando PySide6, PyAV y PyInstaller (puede tardar unos minutos)...
%PYEXE% -m pip install --upgrade pip >nul 2>&1
%PYEXE% -m pip install -r requirements.txt PyInstaller==6.*
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.

REM --- 4. Limpiar builds previos --------------------------------------
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM --- 5. Construir ----------------------------------------------------
echo.
echo [..] Empaquetando TVPlayout PRO V24.0.0.4 (esto puede tardar 2-5 minutos)...
echo.
%PYEXE% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name "TVPlayoutPRO" ^
    --collect-submodules app ^
    --collect-data app ^
    --hidden-import "PySide6.QtSvg" ^
    --hidden-import "PySide6.QtMultimedia" ^
    --hidden-import "av" ^
    --hidden-import "app.pyav_player" ^
    --exclude-module "tkinter" ^
    --exclude-module "matplotlib" ^
    --exclude-module "numpy" ^
    --exclude-module "pandas" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller fallo. Revisa el log arriba.
    pause
    exit /b 1
)

REM --- 6. Copiar binarios externos al lado del .exe --------------------
echo.
echo [..] Copiando binarios opcionales al lado del ejecutable...
if exist "mpv-x86_64\mpv.exe" (
    copy /Y "mpv-x86_64\mpv.exe" "dist\mpv.exe" >nul
    echo [OK] mpv.exe copiado para preview externo.
) else (
    echo [INFO] mpv.exe no encontrado: preview externo desactivado.
)
if exist "ffmpeg\ffmpeg.exe" (
    copy /Y "ffmpeg\ffmpeg.exe" "dist\ffmpeg.exe" >nul
    echo [OK] ffmpeg.exe copiado.
) else if exist "ffmpeg.exe" (
    copy /Y "ffmpeg.exe" "dist\ffmpeg.exe" >nul
    echo [OK] ffmpeg.exe copiado.
) else (
    echo [AVISO] No se encontro ffmpeg.exe. Descargalo de https://ffmpeg.org/
)
if exist "ffmpeg\ffprobe.exe" (
    copy /Y "ffmpeg\ffprobe.exe" "dist\ffprobe.exe" >nul
    echo [OK] ffprobe.exe copiado.
) else if exist "ffprobe.exe" (
    copy /Y "ffprobe.exe" "dist\ffprobe.exe" >nul
    echo [OK] ffprobe.exe copiado.
) else (
    echo [AVISO] No se encontro ffprobe.exe: no se podra analizar la biblioteca.
)

REM --- 7. Crear acceso directo e instrucciones -------------------------
echo.
echo ================================================
echo   BUILD COMPLETADO
echo ================================================
echo.
echo Ejecutable:  dist\TVPlayoutPRO.exe
echo Tamaño aproximado: 80-120 MB
echo.
echo Como usar:
echo   1. Copia dist\TVPlayoutPRO.exe a la carpeta de emisión
echo   2. Ahi mismo deben estar ffmpeg.exe y ffprobe.exe
echo      (mpv.exe es opcional para preview externo)
echo   3. Doble clic en TVPlayoutPRO.exe
echo.
pause
endlocal
