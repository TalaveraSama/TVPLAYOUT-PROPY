# TVPlayout PRO V24.0.0.4

## Nuevo reproductor local PyAV/libavcodec

Esta release reemplaza el reproductor local basado en QtMultimedia y la
integración IPC de mpv por un decoder PyAV/libavcodec integrado en la
aplicación.

### Cambios

- El aire local usa `app/pyav_player.py`.
- PyAV decodifica vídeo y entrega frames RGB directamente a `VideoSurface`.
- El audio PCM se reproduce con `QAudioSink`, sin que `QMediaPlayer` controle
  el vídeo.
- Se conserva la continuidad de playlist, pausa, seek, loop, filler, slate,
  crossfade y selección de pista de audio.
- El slate ya no depende de `lavfi`, `drawtext`, fuentes de Windows ni mpv.
- El VU meter calcula niveles L/R a partir de los samples PCM decodificados.
- mpv queda únicamente como preview externo opcional.
- La salida RTMP/SRT/UDP de FFmpeg no se reemplaza ni se mezcla con el
  decoder local.
- `requirements.txt`, `INSTALL.bat`, `build_exe.bat` y `tvplayout.spec` ahora
  instalan y empaquetan PyAV.
- Se actualizó la versión visible a `V24.0.0.4`.

### Instalación

Ejecutar `INSTALL.bat` para instalar PySide6 y PyAV. Después colocar
`ffmpeg.exe` y `ffprobe.exe` junto al programa para el análisis y la salida
RTMP. `mpv.exe` solo es necesario si se desea la previsualización externa.

### Verificación

- Compilación Python correcta.
- Integración estática: 29/29.
- Scheduler: 10/10.
- La reproducción real debe validarse en Windows con PyAV instalado y un
  archivo de vídeo representativo de la biblioteca.
