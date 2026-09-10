# TVPlayout PRO V24.0.2.34

## Installer completo para Windows: todo en UN SOLO ejecutable

### Nuevo: `installer\BUILD_INSTALLER.bat`
Desde Windows 10/11 x64, un solo comando genera **`dist\Setup_TVPlayoutPRO_V24.0.2.34.exe`**, un instalador único que lo lleva todo:

- **TVPlayoutPRO.exe** — la aplicación completa (PySide6 + PyAV congeladas), sin necesidad de Python.
- **ffmpeg.exe + ffprobe.exe + mpv.exe empaquetados en la raíz** del programa — salidas RTMP/SRT, análisis de biblioteca, auto-recorte y vistas previas funcionan recién instalado, sin configurar nada.
- **Opcional (casillas del instalador)**: NDI Runtime x64 y VLC empaquetados dentro del setup, para instalarlos en el equipo de emisión.
- **Opcional**: regla de firewall para el descubrimiento NDI (mDNS UDP 5353).
- Accesos directos en escritorio y menú Inicio, asistente en español, desinstalador limpio.

El script de build **descarga automáticamente** FFmpeg (build esencial), mpv, NDI Runtime y VLC a la carpeta `vendor\`. Si ya tienes los archivos, los colocas ahí y no descarga nada. Requisitos del equipo donde compilas: Python 3.10+, internet e [Inno Setup 6](https://jrsoftware.org/isdl.php) (gratuito).

### ¿Dónde instala?
Instalación **por usuario** (sin pedir administrador) en `%LOCALAPPDATA%\Programs\TVPlayoutPRO` — la aplicación guarda base de datos, logs, miniaturas y caché junto al EXE, así que necesita una carpeta con permisos de escritura (Program Files no los daría). Al desinstalar se conserva la base de datos y los logs del usuario.

### Mejoras adicionales
- `build_exe.bat` actualizado a V24.0.2.34: ahora **también empaqueta mpv.exe** (con sus DLL) en la raíz de la distribución portable, acepta binarios desde `vendor\` y admite `--no-pause` para encadenarlo en builds automáticos.
- BUILD.md reorganizado: sección «Instalador completo» con los pasos y el contenido del setup.
- Verificado con test de regresión: la raíz portable congelada apunta a la carpeta del EXE (por eso el instalador funciona sin cambiar nada del código).

## Cómo usarlo
1. En tu Windows de desarrollo, clona/descarga el proyecto e instala [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Ejecuta `installer\BUILD_INSTALLER.bat` y espera (descarga ~150 MB la primera vez).
3. Comparte el único archivo `dist\Setup_TVPlayoutPRO_V24.0.2.34.exe` con el equipo de emisión.
4. Doble clic → Siguiente → casillas de NDI Runtime/VLC si quieres → listo: acceso directo en el escritorio y todo funcionando.

## Validación

- `python tests/test_v24_continuity.py` — 33/33 (nuevas: el instalador empaqueta app + ffmpeg/ffprobe/mpv + opcionales con la versión sincronizada, instalación por usuario en carpeta con permisos de escritura, y la raíz congelada resuelve a la carpeta del EXE)
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
