# Empaquetar TVPlayout PRO V24.0.2.0 para Windows

## Camino recomendado

En Windows, desde la raíz del checkout, ejecuta:

```bat
build_exe.bat
```

El script crea un entorno aislado `.venv-build`, instala las dependencias,
construye PySide6 + PyAV/libav con PyInstaller y genera una distribución
**onedir** portable en:

```text
dist\TVPlayoutPRO\
├── TVPlayoutPRO.exe
├── _internal\              librerías Python, PySide6 y PyAV
├── ffmpeg.exe              salida RTMP/SRT/UDP (si está disponible)
├── ffprobe.exe             análisis de biblioteca (si está disponible)
├── mpv.exe                 preview externo opcional (si está disponible)
├── tvplayout.db            se copia si existe en la raíz al construir
├── INICIAR_EXE.bat
└── LEEME_PORTABLE.txt
```

**No copies solo `TVPlayoutPRO.exe`**: la carpeta `_internal` contiene las
librerías necesarias para PySide6 y PyAV. Copia la carpeta completa
`dist\TVPlayoutPRO` al equipo de emisión y ejecuta `INICIAR_EXE.bat`.

La aplicación congelada usa la carpeta donde está el EXE como raíz persistente.
Ahí quedan `tvplayout.db`, `cache\`, `logs\` y `.env`; no se usa la carpeta
TEMP de PyInstaller para datos permanentes.

## Herramientas externas

Coloca antes del build cualquiera de estas opciones:

```text
ffmpeg.exe                         raíz del proyecto
ffprobe.exe                        raíz del proyecto
bin\ffmpeg.exe / bin\ffprobe.exe
ffmpeg\bin\ffmpeg.exe / ffmpeg\bin\ffprobe.exe
mpv-x86_64\mpv.exe                solo para preview externo
```

El BAT copia también las DLL que estén junto a FFmpeg o mpv. El aire local usa
PyAV/libav y no necesita mpv; FFmpeg sí es necesario para RTMP/SRT/UDP y ffprobe
para escanear metadatos y generar miniaturas.

## Requisitos del equipo de build

- Windows 10/11 de 64 bits.
- Python x64 3.13 recomendado; el BAT acepta otra versión `py -3` compatible.
- Internet durante el primer build para descargar PySide6, PyAV y PyInstaller.
- Aproximadamente 1 GB libre para el entorno y los artefactos temporales.

## Build manual

```bat
py -3.13 -m venv .venv-build
.venv-build\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt PyInstaller==6.*
python -m PyInstaller --noconfirm --clean tvplayout.spec
```

Después copia `ffmpeg.exe`, `ffprobe.exe`, `mpv.exe` y sus DLL vecinas a
`dist\TVPlayoutPRO\`.

## Diagnóstico

Para ver errores de Python en una build de prueba, cambia temporalmente
`console=False` por `console=True` en `tvplayout.spec` y vuelve a ejecutar el
BAT. En producción se recomienda mantener la build sin consola y revisar
`logs\tvplayout.log`.

Para eliminar solo los artefactos de build:

```bat
rmdir /s /q .venv-build
rmdir /s /q build
rmdir /s /q dist
```
