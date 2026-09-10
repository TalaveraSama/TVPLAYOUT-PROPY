# TVPlayout PRO V24.0.0.5

## Corrección de latencia del audio de monitoreo

Hotfix sobre V24.0.0.4. Corrige la acumulación de audio en el monitor local
cuando el reproductor PyAV decodifica la señal para la ventana.

### Cambios

- Se redujo el buffer interno de `QAudioSink` a una ventana de baja latencia.
- La cola PCM del monitor local se limita para evitar que el audio se atrase
  progresivamente respecto al vídeo.
- Se conserva el formato de monitoreo a 48 kHz, S16 estéreo.
- El VU meter, mute y control de volumen siguen funcionando.
- **No se modificó la salida RTMP/SRT/UDP**: FFmpeg continúa generando la
  señal de emisión de forma independiente y normal.
- Se actualizó la versión visible a `V24.0.0.5`.

### Verificación

- Compilación Python correcta.
- Integración estática: 29/29.
- Scheduler: 10/10.
- Validar el desfase de audio en Windows con un clip real y confirmar que la
  salida RTMP mantiene su sincronía.
