@echo off
REM ============================================================================
REM TVPlayout PRO V24.0.2.35 - Instalador completo para Windows
REM
REM Genera UN SOLO ejecutable de instalacion:
REM   dist\Setup_TVPlayoutPRO_V24.0.2.35.exe
REM
REM El instalador lleva empaquetados la aplicacion, ffmpeg.exe, ffprobe.exe
REM y mpv.exe en la raiz del programa, y opcionalmente los instaladores de
REM NDI Runtime x64 y VLC (se descargan a vendor\ si no estan).
REM
REM Requisitos en el equipo de build:
REM   - Windows 10/11 x64 con Python 3.10+ y curl (incluido en Windows 10+)
REM   - Inno Setup 6 (https://jrsoftware.org/isdl.php)
REM Ejecutar desde la raiz del proyecto o desde installer\ (da igual).
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

set "APP_VERSION=V24.0.2.35"
set "VENDOR=vendor"
set "DIST_APP=dist\TVPlayoutPRO"
set "SETUP_NAME=Setup_TVPlayoutPRO_%APP_VERSION%"

echo.
echo ============================================================
echo   TVPlayout PRO %APP_VERSION% - BUILD DEL INSTALADOR
echo ============================================================
echo.

REM ---------------------------------------------------------------------------
REM 1) Carpeta vendor: binarios externos que se empaquetan
REM ---------------------------------------------------------------------------
if not exist "%VENDOR%" mkdir "%VENDOR%"

REM ---------------------------------------------------------------------------
REM 2) FFmpeg + ffprobe (build esencial oficial) si faltan
REM ---------------------------------------------------------------------------
if exist "%VENDOR%\ffmpeg.exe" if exist "%VENDOR%\ffprobe.exe" (
    echo [OK] ffmpeg.exe y ffprobe.exe ya estan en vendor\
) else (
    echo [..] Descargando FFmpeg esencial ^(~90 MB^) ...
    curl -L --fail --retry 3 -o "%VENDOR%\ffmpeg.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    if errorlevel 1 goto :ffmpeg_error
    echo [..] Extrayendo ...
    tar -xf "%VENDOR%\ffmpeg.zip" -C "%VENDOR%"
    for /r "%VENDOR%" %%F in (ffmpeg.exe)  do if not exist "%VENDOR%\ffmpeg.exe"  copy /Y "%%~fF" "%VENDOR%\ffmpeg.exe"  >nul
    for /r "%VENDOR%" %%F in (ffprobe.exe) do if not exist "%VENDOR%\ffprobe.exe" copy /Y "%%~fF" "%VENDOR%\ffprobe.exe" >nul
    del /q "%VENDOR%\ffmpeg.zip" >nul 2>&1
    for /d %%D in ("%VENDOR%\ffmpeg-*") do rmdir /s /q "%%~D" >nul 2>&1
)
if not exist "%VENDOR%\ffmpeg.exe"  goto :ffmpeg_error
if not exist "%VENDOR%\ffprobe.exe" goto :ffmpeg_error
echo [OK] ffmpeg listo.

REM ---------------------------------------------------------------------------
REM 3) mpv (vistas previas) si falta: instalador oficial silencioso y extraccion
REM ---------------------------------------------------------------------------
if exist "%VENDOR%\mpv.exe" (
    echo [OK] mpv.exe ya esta en vendor\
) else (
    echo [..] Descargando mpv ^(instalador oficial^) ...
    curl -L --fail --retry 3 -o "%VENDOR%\mpv-setup.exe" "https://sourceforge.net/projects/mpv-player-windows/files/latest/download"
    if errorlevel 1 (
        echo [AVISO] No se pudo descargar mpv; coloca mpv.exe en vendor\ para empaquetarlo.
    ) else (
        echo [..] Extrayendo mpv.exe ...
        "%VENDOR%\mpv-setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="%CD%\%VENDOR%\mpv-extract"
        if exist "%VENDOR%\mpv-extract\mpv.exe" (
            copy /Y "%VENDOR%\mpv-extract\*.exe" "%VENDOR%\" >nul
            copy /Y "%VENDOR%\mpv-extract\*.dll" "%VENDOR%\" >nul
        )
        rmdir /s /q "%VENDOR%\mpv-extract" >nul 2>&1
        del /q "%VENDOR%\mpv-setup.exe" >nul 2>&1
    )
)
if exist "%VENDOR%\mpv.exe" (echo [OK] mpv listo.) else (echo [AVISO] mpv.exe no disponible; las vistas previas usaran VLC.)

REM ---------------------------------------------------------------------------
REM 4) Opcionales: NDI Runtime x64 y VLC (fallos no son fatales)
REM ---------------------------------------------------------------------------
if not exist "%VENDOR%\ndi-runtime.exe" (
    echo [..] Descargando NDI Runtime x64 ^(opcional^) ...
    curl -L --fail --retry 2 --max-time 300 -o "%VENDOR%\ndi-runtime.exe" "https://downloads.ndi.tv/tools/NDI%%206%%20Runtime.exe" || del /q "%VENDOR%\ndi-runtime.exe" >nul 2>&1
)
if exist "%VENDOR%\ndi-runtime.exe" (echo [OK] NDI Runtime listo para empaquetar.) else (echo [AVISO] NDI Runtime no descargado; podras instalarlo aparte.)

if not exist "%VENDOR%\vlc-setup.exe" (
    echo [..] Descargando VLC ^(opcional^) ...
    curl -L --fail --retry 2 --max-time 300 -o "%VENDOR%\vlc-setup.exe" "https://get.videolan.org/vlc/last/win64/" || del /q "%VENDOR%\vlc-setup.exe" >nul 2>&1
)
if exist "%VENDOR%\vlc-setup.exe" (echo [OK] VLC listo para empaquetar.) else (echo [AVISO] VLC no descargado; el instalador seguira sin el.)

REM ---------------------------------------------------------------------------
REM 5) Compilar la aplicacion (PyInstaller onedir + ffmpeg/ffprobe/mpv en raiz)
REM ---------------------------------------------------------------------------
echo.
echo [..] Compilando la aplicacion ...
call build_exe.bat --no-pause
if errorlevel 1 goto :build_error
if not exist "%DIST_APP%\TVPlayoutPRO.exe" goto :build_error

REM Asegurar binarios de vendor en la raiz de la distribucion
copy /Y "%VENDOR%\ffmpeg.exe"  "%DIST_APP%\" >nul
copy /Y "%VENDOR%\ffprobe.exe" "%DIST_APP%\" >nul
if exist "%VENDOR%\mpv.exe" (
    copy /Y "%VENDOR%\mpv.exe" "%DIST_APP%\" >nul
    copy /Y "%VENDOR%\*.dll"   "%DIST_APP%\" >nul
)
echo [OK] Distribucion completa en %DIST_APP%

REM ---------------------------------------------------------------------------
REM 6) Compilar el instalador con Inno Setup 6
REM ---------------------------------------------------------------------------
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "tokens=*" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC (
    echo [ERROR] Inno Setup 6 no encontrado. Instalalo desde https://jrsoftware.org/isdl.php
    start "" "https://jrsoftware.org/isdl.php"
    goto :error
)

echo [..] Compilando el instalador con Inno Setup ...
"%ISCC%" "installer\TVPLAYOUT-PROPY.iss"
if errorlevel 1 goto :error

echo.
echo ============================================================
echo   INSTALADOR LISTO
echo ============================================================
echo   Archivo:  dist\%SETUP_NAME%.exe
echo   Contiene: TVPlayoutPRO.exe + ffmpeg + ffprobe + mpv
echo             (+ NDI Runtime y VLC si se descargaron)
echo.
echo   Instala por usuario en %%LOCALAPPDATA%%\Programs\TVPlayoutPRO
echo   y crea accesos directos. La BD y logs quedan junto al EXE.
echo ============================================================
pause
endlocal
exit /b 0

:ffmpeg_error
echo [ERROR] No se pudo descargar FFmpeg. Coloca ffmpeg.exe y ffprobe.exe en vendor\ y reintenta.
goto :error
:build_error
echo [ERROR] La compilacion de la aplicacion fallo. Revisa los mensajes de PyInstaller.
goto :error
:error
echo.
echo BUILD DEL INSTALADOR CANCELADO.
pause
endlocal
exit /b 1
