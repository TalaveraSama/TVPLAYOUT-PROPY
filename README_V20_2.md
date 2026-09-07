# TVPlayout PRO V20.2

Correcciones incluidas:

- RTMP toma los elementos de la playlist, no solamente el elemento seleccionado.
- FFmpeg muestra el error real en la barra de estado.
- NVIDIA NVENC usa un preset compatible (`fast`) y no `veryfast`/x264.
- CPU/x264 mantiene `veryfast`.
- Se valida que `ffmpeg.exe` exista y que el encoder elegido exista en ese build.
- Playlist: clic derecho para eliminar el elemento seleccionado o vaciar la playlist.
- Programador: diario, semanal, mensual y trimestral.
- Programador incluye **Ejecutar ahora** para comprobar una programación sin esperar a la hora.
- Las programaciones se guardan en SQLite.
- MPV sigue siendo el reproductor embebido de `mpv-x86_64`.

## Importante RTMP

El RTMP utiliza FFmpeg para codificar. Si los archivos de una playlist tienen codecs/estructuras incompatibles, el concat demuxer de FFmpeg puede rechazar la transición. En ese caso el siguiente paso será separar el motor de continuidad del motor de preview y crear el conmutador de salida por eventos, para evitar depender de que todos los MKV/MP4 tengan exactamente los mismos streams.
