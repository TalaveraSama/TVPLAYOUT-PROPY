# Empaquetar Nexora Air V25.6.0 para Windows

## Instalador offline todo-en-uno (recomendado)

El builder es reproducible y funciona desde Linux o Windows x64:

```bash
python3 installer/build_windows_setup.py all
```

En Windows también se puede ejecutar:

```bat
installer\BUILD_INSTALLER.bat
```

La salida es:

```text
dist/Setup_NexoraAir_V25.6.0.exe
dist/Setup_NexoraAir_V25.6.0.exe.sha256
```

El Setup contiene, sin instalaciones manuales en el equipo destino:

- Nexora Air V25.6.0 y los launchers `NexoraAir.exe` / `NexoraAir-Console.exe`.
- Python 3.13.2 embebido.
- PySide6 6.8.3 y Shiboken.
- PyAV 16 con sus bibliotecas multimedia.
- `ffmpeg.exe` y `ffprobe.exe` para RTMP/SRT/UDP y metadatos.
- El icono y los recursos de identidad.

La compilación necesita conexión a Internet la primera vez y **NSIS 3**
(`makensis`). Las descargas se conservan en `.installer-build/downloads/` para
repetir el build sin volver a bajarlas.

### Pasos separados

```bash
# Verifica identidad y versión sin descargar nada
python3 installer/build_windows_setup.py check

# Descarga y arma .installer-build/payload
python3 installer/build_windows_setup.py prepare

# Compila el payload ya preparado con NSIS
python3 installer/build_windows_setup.py setup
```

### Actualización y migración

El instalador trabaja por usuario en:

```text
%LOCALAPPDATA%\Programs\NexoraAir
```

Si encuentra la instalación anterior en
`%LOCALAPPDATA%\Programs\TVPlayoutPRO`, migra `tvplayout.db`, `.env`, caché y
logs. Una base ya migrada (`nexora-air.db`) siempre tiene prioridad. Al
desinstalar se copian la base y `.env` al Escritorio antes de retirar el
runtime; caché y logs se conservan en el directorio de instalación.

## Portable PyInstaller (alternativo)

En un Windows x64 con Python instalado:

```bat
build_exe.bat
```

Genera:

```text
dist\NexoraAir\
├── NexoraAir.exe
├── _internal\
├── ffmpeg.exe             si existe en raíz/vendor/bin/ffmpeg
├── ffprobe.exe            si existe en raíz/vendor/bin/ffmpeg
├── mpv.exe                opcional para vistas previas
├── assets\logo.png
├── assets\logo.ico
└── INICIAR_EXE.bat
```

No copies solamente el EXE: la distribución `onedir` necesita `_internal`.
La raíz del ejecutable es persistente; allí se guardan la base, `.env`, caché
y logs.

## Binarios externos para el build portable

`build_exe.bat` busca FFmpeg/ffprobe en la raíz, `vendor/`, `bin/`, `ffmpeg/` o
`ffmpeg/bin/`. También copia DLL vecinas. Para previews busca `mpv.exe` en
`mpv-x86_64/`, `vendor/` o la raíz. NDI directo usa el Runtime NDI x64 instalado,
no necesita `ffmpeg-ndi.exe` y tampoco necesita el muxer `libndi_newtek`.

## Identidad visual

- `assets/logo.png`: ventana y documentación.
- `assets/logo.ico`: ejecutable, instalador y accesos directos.
- El logo de canal al aire sigue siendo configurable por el operador desde
  **Logo / CG** y no se confunde con el icono del producto.

## Limpieza

Los siguientes directorios son generados y están ignorados por Git:

```text
.installer-build/
.venv-build/
build/
dist/
vendor/
```

Se pueden borrar sin afectar el código ni los datos de operación.
