# TVPlayout PRO V24.0.0.6

## Sincronización de audio del monitor local

Hotfix sobre V24.0.0.5 para corregir el audio mudo o atrasado en el monitor
local del reproductor PyAV.

### Cambios

- Se eliminó el crossfader del reproductor local, la interfaz y el flujo de
  continuidad. Los clips realizan cortes directos.
- Se agregó un prebuffer real de seis segundos de audio PCM antes de iniciar
  el monitoreo.
- `QAudioSink` utiliza un buffer de seis segundos y la cola local conserva
  hasta 6,5 segundos para alinear audio y vídeo.
- Se corrigió la limpieza prematura de la cola prebufferizada que podía dejar
  el monitor sin audio.
- Se mantienen el VU meter, mute y volumen local.
- La señal RTMP/SRT/UDP de FFmpeg no utiliza este buffer y permanece
  independiente, sin cambios en su sincronización ni nivel.
- Se actualizó la versión visible a `V24.0.0.6`.

### Verificación

- Compilación Python correcta.
- Integración estática: 27/27.
- Scheduler: 10/10.
- Validación real recomendada en Windows con un clip de vídeo y audio.
