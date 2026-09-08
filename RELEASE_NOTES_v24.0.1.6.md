# TVPlayout PRO V24.0.1.6

## Corrección del resampler de audio del monitor

Hotfix sobre V24.0.0.6 para evitar los avisos repetidos de Qt Multimedia en
Windows:

```text
qt.multimedia.audioresampler: Resampling failed -1072875851
```

### Cambios

- Se mantiene el prebuffer de seis segundos para alinear audio y vídeo del
  monitor local.
- La transferencia PCM hacia `QAudioSink` queda limitada a aproximadamente
  10 ms por ciclo, evitando entregar todo el prebuffer de golpe al resampler
  de Windows.
- Se mantiene la cola local de 6,5 segundos.
- El crossfader continúa eliminado; la transición entre clips es directa.
- Mute, volumen y VU meter permanecen disponibles para el monitor local.
- La salida RTMP/SRT/UDP de FFmpeg permanece independiente y sin cambios.
- Se actualizó la versión visible a `V24.0.1.6`.

### Verificación

- Compilación Python correcta.
- Integración estática: 27/27.
- Scheduler: 10/10.
- Validación recomendada en Windows con audio real y el dispositivo de
  salida habitual.
