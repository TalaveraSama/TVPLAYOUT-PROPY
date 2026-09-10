# TVPlayout PRO V24.0.1.8

## Fallback de encoder RTMP para equipos sin NVIDIA

Hotfix sobre V24.0.1.7 para corregir el fallo de salida RTMP observado cuando
FFmpeg seleccionaba `h264_nvenc` en un equipo sin NVIDIA o sin `nvcuda.dll`.

### Cambios

- Los encoders de hardware se prueban antes de iniciar la salida; que FFmpeg
  los liste ya no se considera suficiente.
- Si NVENC, QSV o AMF no están disponibles, la salida usa automáticamente
  `CPU/x264` en lugar de terminar con `Cannot load nvcuda.dll`.
- Si el encoder de hardware supera la prueba pero falla al abrir el stream
  real, se reintenta el mismo evento con CPU/x264 y el mismo offset.
- Se conservan RTMP/SRT/UDP, selección de audio, subtítulos, logo y la
  continuidad de playlist.
- La reproducción local PyAV/libav y el monitor de audio no se modifican.

### Verificación

- Integración estática: 29/29.
- Scheduler: 10/10.
- Compilación Python correcta.
- Falta validación final en Windows con el FFmpeg y URL RTMP habituales.
