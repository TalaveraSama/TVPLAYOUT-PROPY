@echo off
REM ====================================================================
REM   TVPlayout PRO V22 - Generador de ejecutable
REM   Uso: doble clic en este archivo desde la carpeta del proyecto.
REM   Genera: dist\TVPlayoutPRO.exe
REM ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ================================================
echo   TVPlayout PRO V22 - BUILD
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
echo [..] Instalando PySide6 y PyInstaller (puede tardar unos minutos)...
%PYEXE% -m pip install --upgrade pip >nul 2>&1
%PYEXE% -m pip install PySide6==6.7.* PyInstaller==6.*
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
echo [..] Empaquetando TVPlayout PRO V22 (esto puede tardar 2-5 minutos)...
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
echo [..] Copiando mpv.exe y ffmpeg.exe al lado del ejecutable...
if exist "mpv-x86_64\mpv.exe" (
    copy /Y "mpv-x86_64\mpv.exe" "dist\mpv.exe" >nul
    echo [OK] mpv.exe copiado.
) else (
    echo [AVISO] No se encontro mpv-x86_64\mpv.exe en el proyecto.
    echo        Descargalo de https://mpv.io/installation/ y ponelo en mpv-x86_64\
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
echo   1. Copia dist\TVPlayoutPRO.exe a la carpeta donde corrias v22.1.0
echo   2. Ahi mismo tiene que estar mpv.exe y ffmpeg.exe (o en subcarpetas
echo      mpv-x86_64\ y ffmpeg\)
echo   3. Doble clic en TVPlayoutPRO.exe
echo.
pause
endlocal
