# TVPlayout PRO V24.0.2.5

## NDI nativo mediante NDI Runtime

Esta versión reemplaza la dependencia del muxer `libndi_newtek` de FFmpeg para
la salida NDI. TVPlayout publica directamente mediante
`Processing.NDI.Lib.x64.dll` del NDI Runtime x64 instalado en Windows.

### Cambios

- Detección automática de `Processing.NDI.Lib.x64.dll` mediante variables de
  entorno del Runtime y rutas habituales de `Program Files`.
- NDI solo aparece disponible después de cargar la DLL, ejecutar
  `NDIlib_initialize` y crear correctamente un sender de prueba.
- Un sender independiente por cada destino NDI.
- Vídeo BGRA/BGRX enviado desde los `QImage` producidos por PyAV.
- Audio PCM estéreo `s16le` convertido a `float32` planar `FLTP` para
  `NDIlib_audio_frame_v3_t`.
- Envío de vídeo asíncrono y cola controlada para no detener la reproducción
  local ni el monitor PyAV.
- Sincronización del buffer asíncrono antes de destruir un sender NDI.
- El logo/CG configurado se aplica también a la imagen NDI.
- RTMP y SRT continúan usando FFmpeg normal y workers independientes.
- `ffmpeg-ndi.exe` y `libndi_newtek` quedan como compatibilidad heredada
  opcional, no como requisitos de NDI directo.
- Se conserva el trim no destructivo, playlist, loop, filler, slate, VU meter,
  prebuffer local aproximado de seis segundos y operación 24/7.

### Validación de código

- `py_compile`: correcto.
- Integración: 38/38.
- Scheduler: 10/10.
- `git diff --check`: correcto.

### Requisito de Windows

Instala el **NDI Runtime x64** antes de iniciar TVPlayout. La validación final
debe comprobar el estado OK en **Dispositivos** y la recepción de vídeo y audio
en NDI Studio Monitor, OBS o vMix. La DLL no puede validarse desde Linux.
