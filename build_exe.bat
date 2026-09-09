@echo off
REM ============================================================================
REM TVPlayout PRO V24.0.2.21 - Empaquetado portable para Windows x64
REM
REM Genera una distribución onedir profesional en:
REM   dist\TVPlayoutPRO\
REM
REM El ejecutable y las librerías Python quedan dentro de esa carpeta. El
REM script copia además ffmpeg/ffprobe y los recursos de identidad visual
REM (si existen) al mismo nivel del EXE, que es la raíz persistente usada
REM por la aplicación congelada.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "APP_VERSION=V24.0.2.21"
set "VENV=.venv-build"
set "PYEXE=%VENV%\Scripts\python.exe"
set "OUT=%~dp0dist\TVPlayoutPRO"
set "PY_CMD="

echo.
echo ============================================================
echo   TVPlayout PRO %APP_VERSION% - BUILD PORTABLE
echo ============================================================
echo.

REM 1. Detectar Python ---------------------------------------------------------
where py >nul 2>&1
if not errorlevel 1 (
    py -3.13 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.13"
    if not defined PY_CMD (
        py -3 --version >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3"
    )
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD goto :no_python

for /f "tokens=*" %%A in ('%PY_CMD% --version 2^>^&1') do echo [OK] Python: %%A

REM 2. Entorno aislado de build ------------------------------------------------
if not exist "%PYEXE%" (
    echo [..] Creando entorno virtual %VENV% ...
    %PY_CMD% -m venv "%VENV%"
    if errorlevel 1 goto :build_error
)
if not exist "%PYEXE%" goto :build_error

REM 3. Dependencias reproducibles ---------------------------------------------
echo [..] Actualizando herramientas de build ...
"%PYEXE%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :dependency_error

echo [..] Instalando PySide6, PyAV/libav y PyInstaller ...
"%PYEXE%" -m pip install --upgrade -r requirements.txt PyInstaller==6.*
if errorlevel 1 goto :dependency_error

REM 4. Limpiar solamente artefactos generados ---------------------------------
echo [..] Limpiando build y dist anteriores ...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM 5. PyInstaller onedir ------------------------------------------------------
REM onedir es más estable para una aplicación 24/7 que onefile: no extrae las
REM DLL de Qt/PyAV a TEMP en cada arranque y permite diagnosticar librerías.
echo [..] Empaquetando %APP_VERSION% ...
"%PYEXE%" -m PyInstaller --noconfirm --clean "tvplayout.spec"
if errorlevel 1 goto :build_error
if not exist "%OUT%\TVPlayoutPRO.exe" (
    echo [ERROR] PyInstaller terminó pero no creó %OUT%\TVPlayoutPRO.exe
    goto :build_error
)
echo [OK] Ejecutable y librerías Python generados.

REM 6. Copiar FFmpeg/ffprobe al nivel del EXE -------------------------------
REM Se aceptan estas ubicaciones en el checkout: raíz, bin\, ffmpeg\ o
REM ffmpeg\bin\. También se copian DLL vecinas de builds compartidos.
set "FFMPEG_SRC="
for %%P in ("%~dp0ffmpeg.exe" "%~dp0bin\ffmpeg.exe" "%~dp0ffmpeg\ffmpeg.exe" "%~dp0ffmpeg\bin\ffmpeg.exe") do (
    if not defined FFMPEG_SRC if exist "%%~fP" set "FFMPEG_SRC=%%~fP"
)
set "FFPROBE_SRC="
for %%P in ("%~dp0ffprobe.exe" "%~dp0bin\ffprobe.exe" "%~dp0ffmpeg\ffprobe.exe" "%~dp0ffmpeg\bin\ffprobe.exe") do (
    if not defined FFPROBE_SRC if exist "%%~fP" set "FFPROBE_SRC=%%~fP"
)

if defined FFMPEG_SRC (
    copy /Y "!FFMPEG_SRC!" "%OUT%\ffmpeg.exe" >nul
    echo [OK] ffmpeg.exe copiado a la raíz portable.
    for %%D in ("!FFMPEG_SRC!") do set "FFMPEG_DIR=%%~dpD"
    for %%L in ("!FFMPEG_DIR!*.dll") do if exist "%%~fL" copy /Y "%%~fL" "%OUT%\" >nul
) else (
    echo [AVISO] No se encontró ffmpeg.exe; RTMP y análisis necesitarán instalarlo.
)
if defined FFPROBE_SRC (
    copy /Y "!FFPROBE_SRC!" "%OUT%\ffprobe.exe" >nul
    echo [OK] ffprobe.exe copiado a la raíz portable.
    for %%D in ("!FFPROBE_SRC!") do set "FFPROBE_DIR=%%~dpD"
    for %%L in ("!FFPROBE_DIR!*.dll") do if exist "%%~fL" copy /Y "%%~fL" "%OUT%\" >nul
) else (
    echo [AVISO] No se encontró ffprobe.exe; el escaneo no tendrá metadatos.
)

REM Compatibilidad heredada opcional: NDI directo ya usa el Runtime x64 por ctypes.
set "FFMPEG_NDI_SRC="
for %%P in ("%~dp0ffmpeg-ndi.exe" "%~dp0bin\ffmpeg-ndi.exe" "%~dp0ffmpeg\bin\ffmpeg-ndi.exe") do (
    if not defined FFMPEG_NDI_SRC if exist "%%~fP" set "FFMPEG_NDI_SRC=%%~fP"
)
if defined FFMPEG_NDI_SRC (
    copy /Y "!FFMPEG_NDI_SRC!" "%OUT%\ffmpeg-ndi.exe" >nul
    echo [INFO] ffmpeg-ndi.exe heredado copiado (no es necesario para NDI directo).
    for %%D in ("!FFMPEG_NDI_SRC!") do set "FFMPEG_NDI_DIR=%%~dpD"
    for %%L in ("!FFMPEG_NDI_DIR!*.dll") do if exist "%%~fL" copy /Y "%%~fL" "%OUT%\" >nul
) else (
    echo [INFO] ffmpeg-ndi.exe heredado no encontrado; NDI directo usa el Runtime x64 instalado.
)

REM 7. Copiar logo/identidad visual opcional -------------------------------
REM logo.png se usa como identidad de la ventana y como ruta sugerida para
REM Logo / CG. logo.ico se incrusta como icono del EXE cuando está disponible.
if exist "%~dp0assets\logo.png" (
    if not exist "%OUT%\assets" mkdir "%OUT%\assets"
    copy /Y "%~dp0assets\logo.png" "%OUT%\assets\logo.png" >nul
    echo [OK] assets\logo.png copiado.
)
if exist "%~dp0assets\logo.ico" (
    if not exist "%OUT%\assets" mkdir "%OUT%\assets"
    copy /Y "%~dp0assets\logo.ico" "%OUT%\assets\logo.ico" >nul
    echo [OK] assets\logo.ico copiado.
)

REM 8. Datos persistentes opcionales ------------------------------------------
REM Se copia la base actual si existe; al iniciar, la aplicación usa siempre la
REM carpeta del EXE como ROOT y conserva DB, cache y logs junto al programa.
if exist "%~dp0tvplayout.db" copy /Y "%~dp0tvplayout.db" "%OUT%\tvplayout.db" >nul
if exist "%~dp0.env" copy /Y "%~dp0.env" "%OUT%\.env" >nul
if exist "%~dp0INICIAR_EXE.bat" copy /Y "%~dp0INICIAR_EXE.bat" "%OUT%\INICIAR_EXE.bat" >nul

>"%OUT%\LEEME_PORTABLE.txt" (
    echo TVPlayout PRO %APP_VERSION%
    echo.
    echo Ejecuta TVPlayoutPRO.exe o INICIAR_EXE.bat.
    echo ffmpeg.exe y ffprobe.exe deben estar junto al EXE para RTMP y biblioteca.
    echo NDI directo requiere instalar el NDI Runtime x64 en Windows; ffmpeg-ndi.exe es solo compatibilidad heredada.
    echo assets\logo.png y assets\logo.ico son opcionales para identidad visual.
    echo tvplayout.db, cache y logs se guardan junto al EXE.
)

REM 9. Limpiar artefactos temporales de PyInstaller ---------------------------
REM Si el build llegó hasta aquí, dist ya contiene todo lo necesario. La carpeta
REM build solo contiene .toc, .pyz, warn-*.txt y reportes de diagnóstico.
if exist "%~dp0build" (
    rmdir /s /q "%~dp0build"
    if not exist "%~dp0build" echo [OK] Artefactos temporales build\ eliminados.
)

echo.
echo ============================================================
echo   BUILD COMPLETADO
echo ============================================================
echo Distribución portable: %OUT%
echo Ejecutable:             %OUT%\TVPlayoutPRO.exe
echo.
echo Copia la carpeta completa dist\TVPlayoutPRO a otro Windows 10/11 x64.
echo No copies solo el EXE: también necesita la carpeta _internal.
echo.
pause
endlocal
exit /b 0

:no_python
echo [ERROR] No se encontró Python 3.13/3.x.
echo Instala Python x64 desde https://www.python.org/downloads/ y activa Add to PATH.
pause
exit /b 1

:dependency_error
echo [ERROR] No se pudieron instalar las dependencias de build.
echo Revisa internet, pip y requirements.txt.
pause
exit /b 1

:build_error
echo [ERROR] Falló el empaquetado. Revisa el error anterior.
pause
exit /b 1
