# TVPlayout PRO V24.0.2.6

## Compatibilidad con NDI Runtime 6

Se corrigió el arranque NDI en equipos donde `Processing.NDI.Lib.x64.dll`
exporta el símbolo de vídeo asíncrono con el orden usado por el NDI Runtime 6:

```text
NDIlib_send_send_video_async_v2
```

La versión anterior solo intentaba:

```text
NDIlib_send_send_video_v2_async
```

### Cambios

- El puente ctypes acepta ambos nombres de API:
  `NDIlib_send_send_video_v2_async` y `NDIlib_send_send_video_async_v2`.
- Se añadió la ruta habitual de NDI Tools 6:
  `C:\Program Files\NDI\NDI 6 Tools\Runtime`.
- El diagnóstico registra qué símbolo de vídeo fue seleccionado.
- Se añadió una prueba mock que reproduce la exportación alternativa del Runtime 6.
- Se mantiene la salida NDI directa, sin `ffmpeg-ndi.exe` ni `libndi_newtek`.
- RTMP/SRT continúan usando el FFmpeg normal sin cambios.

### Validación

- `py_compile`: correcto.
- Integración: 39/39.
- Scheduler: 10/10.
- `git diff --check`: correcto.

La comprobación final de recepción NDI en OBS/vMix debe realizarse en Windows
con el Runtime instalado.
