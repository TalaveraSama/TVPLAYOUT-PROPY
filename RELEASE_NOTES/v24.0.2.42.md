# V24.0.2.42 — El instalador ya no descarga mpv si ya lo tienes local

## Qué pasaba

`installer\BUILD_INSTALLER.bat` descargaba mpv de SourceForge **siempre** que
`vendor\mpv.exe` no existiera, y esa descarga se queda colgada o tarda una
eternidad — justo donde se te quedó el build (la ventana con el `curl` al 0%).

## Qué cambia en esta versión

El orden de prioridad para conseguir mpv es ahora:

1. **`vendor\mpv.exe` ya extraído** → se usa directo (como antes).
2. **El instalador que TÚ ya tienes**, de dos formas:
   - Como argumento: `installer\BUILD_INSTALLER.bat "C:\Descargas\mpv-x86_64-installer.exe"`
   - O sin argumento: copia tu instalador a `vendor\` (como
     `vendor\mpv-setup.exe` o cualquier nombre `mpv*-installer.exe`) y se
     detecta solo.
   - También acepta la ruta de un **mpv.exe portable** (se copia con sus DLL).
3. **Descarga de SourceForge sólo si no hay nada de lo anterior.**

La extracción sigue siendo silenciosa (Inno `/VERYSILENT`) y el resto del
build no cambia: FFmpeg/ffprobe se reutilizan si ya están en `vendor\` (tu
caso: ya los tenías), y NDI/VLC siguen siendo opcionales.

## Cómo usarlo HOY con tu mpv local

```
installer\BUILD_INSTALLER.bat "C:\ruta\donde\lo\tengas\mpv-installer.exe"
```

…o simplemente copia ese instalador a la carpeta `vendor\` del proyecto y
ejecuta `installer\BUILD_INSTALLER.bat` sin argumentos. Nunca más esperará a
SourceForge si ya hay uno disponible.

## Verificación

- 44/44 tests de continuidad v24 (nuevo: orden de prioridad local-antes-de-
  descargar, aceptación de instalador y de mpv.exe portable, extracción
  silenciosa, aviso sin abortar).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Sanity del .bat (ASCII + CRLF) y del .iss (BOM + CRLF + versión).
- Instalador resultante: `dist\Setup_TVPlayoutPRO_V24.0.2.42.exe`.

## Cómo actualizar

Descarga el `Source code (zip)` de esta release (o `git pull`), coloca tu
instalador de mpv en `vendor\` (o pásalo como argumento) y vuelve a ejecutar
`installer\BUILD_INSTALLER.bat`. La aplicación en sí no cambia: es la misma
V24.0.2.41 con todo lo ya publicado, sólo mejora el build.
