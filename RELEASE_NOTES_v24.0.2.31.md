# TVPlayout PRO V24.0.2.31

## Corregido: RTMP/SRT/NDI no arrancaban (salida DETENIDA)

### El bug
Al pulsar **ON AIR / Salidas IP**, la aplicación intentaba construir el gestor de salidas con el parámetro `monitor_feed_url` (introducido con el monitor de programa FFmpeg exacto), pero `MultiOutputManager` **no lo aceptaba en su constructor**. El resultado: un `TypeError` silencioso al arrancar y **ninguna salida RTMP, SRT o NDI llegaba a iniciarse** — el chip quedaba en DETENIDO aunque FFmpeg y la playlist estuvieran perfectos.

### La corrección
- `MultiOutputManager.__init__` ahora acepta `monitor_feed_url`, así que **RTMP, SRT y NDI vuelven a arrancar normalmente**.
- El feed del monitor de programa (modo «Programa FFmpeg → reproductor externo») se asigna al primer destino, exactamente como estaba previsto.

## NDI: más robusto y con mensajes claros

- **Detección del Runtime mejorada**: ahora se intenta cargar `Processing.NDI.Lib.x64.dll` por nombre directo primero, cubriendo la instalación típica del **NDI Runtime oficial** (que registra la DLL en System32), además de todas las rutas de NDI 4/5/6 Tools y SDK que ya se buscaban.
- Si el Runtime no está, el mensaje ahora indica la solución: **«instala el NDI Runtime x64 desde ndi.video/tools»**.
- Corregido además el directorio de DLL cuando el Runtime se carga por nombre (rutas absolutas para `add_dll_directory`).
- NDI sigue publicando **directamente contra el Runtime** (vídeo BGRA + audio FLTP desde el playout local, con logo y tarjeta TMDB), sin depender de builds especiales de FFmpeg.

## Cómo verificarlo
1. Configura tu destino en **Salidas IP** (RTMP `rtmp://…`, SRT `srt://…` o NDI con nombre de fuente).
2. Pulsa **ON AIR**: el chip pasa a CONECTANDO… y luego **ON AIR** con el encoder y la resolución.
3. Para NDI: instala el **NDI Runtime x64** (gratis, ndi.video/tools) si aún no lo tienes; la fuente «TVPlayout PRO» aparece en Studio Monitor u OBS.

## Validación

- `python tests/test_v24_continuity.py` — 26/26 (nuevas: el constructor acepta exactamente los kwargs de `_rtmp_start`, propagación del feed de monitor al primer destino, y NDI degrada sin Runtime sin romper nada)
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke headless (PySide6 offscreen) con FFmpeg simulado: `MultiOutputManager` arranca, el worker RTMP emite ON AIR con el comando tee correcto y la parada es limpia; perfil NDI sin Runtime emite «NDI no disponible» con la pista de instalación.
