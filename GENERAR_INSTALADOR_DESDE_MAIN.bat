@echo off
setlocal EnableExtensions

REM ============================================================================
REM Genera el instalador usando exactamente origin/main.
REM No cambia la rama de trabajo ni modifica el checkout actual.
REM ============================================================================

set "ROOT=%~dp0"
set "WORK=%TEMP%\NexoraAir-main-%RANDOM%"
set "OUT=%ROOT%dist"

cd /d "%ROOT%"
if errorlevel 1 goto :error

echo.
echo ============================================================
echo   NEXORA AIR - INSTALADOR DESDE origin/main
echo ============================================================
echo.

git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git no esta instalado o no esta en PATH.
    goto :error
)

echo [..] Actualizando la referencia remota main...
git fetch origin main
if errorlevel 1 (
    echo [ERROR] No se pudo actualizar origin/main.
    goto :error
)

mkdir "%WORK%" >nul 2>&1
if errorlevel 1 goto :error

echo [..] Preparando una copia limpia de origin/main...
git archive --format=tar origin/main > "%WORK%\source.tar"
if errorlevel 1 goto :error

tar -xf "%WORK%\source.tar" -C "%WORK%"
if errorlevel 1 (
    echo [ERROR] No se pudo extraer origin/main. Se necesita tar de Windows.
    goto :error
)

del /q "%WORK%\source.tar" >nul 2>&1

echo [..] Construyendo el instalador desde origin/main...
call "%WORK%\installer\BUILD_INSTALLER.bat"
if errorlevel 1 goto :error

if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1
for %%F in ("%WORK%\dist\Setup_NexoraAir_*.exe") do (
    copy /y "%%~fF" "%OUT%\" >nul
    if errorlevel 1 goto :error
    echo.
    echo [OK] Instalador copiado a dist\%%~nxF
)

for %%F in ("%WORK%\dist\Setup_NexoraAir_*.sha256") do (
    copy /y "%%~fF" "%OUT%\" >nul
)

echo.
echo [OK] Instalador generado usando exactamente origin/main.
goto :cleanup

:error
echo.
echo [ERROR] No se pudo generar el instalador desde origin/main.
set "EXIT_CODE=1"
goto :cleanup

:cleanup
if exist "%WORK%" rmdir /s /q "%WORK%" >nul 2>&1
if not defined EXIT_CODE set "EXIT_CODE=0"
endlocal & exit /b %EXIT_CODE%
