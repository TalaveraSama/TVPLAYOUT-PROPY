# TVPlayout PRO V24.0.1.7

## Corrección del ruido del monitor local

Hotfix sobre V24.0.1.6 para corregir el sonido constante tipo `prrrrr` o ruido
rosa que podía escucharse en el monitor local mientras el audio de RTMP salía
correctamente.

### Cambios

- Se descarta el padding de alineación que FFmpeg puede dejar al final de los
  planos de un `AudioFrame` de PyAV.
- QAudioSink recibe únicamente `samples × 2 canales × 2 bytes` de PCM s16
  estéreo válido, evitando que los bytes de relleno se reproduzcan como ruido.
- Se conserva el prebuffer local de aproximadamente seis segundos.
- La escritura PCM continúa limitada a velocidad real para evitar saturar el
  resampler de Windows.
- La salida RTMP/SRT/UDP de FFmpeg permanece independiente y sin cambios.
- Crossfade continúa eliminado.

### Verificación

- Integración estática: 28/28.
- Scheduler: 10/10.
- Compilación Python correcta.
- Falta validación final en Windows con el dispositivo de audio habitual.
