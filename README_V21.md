# TVPlayout PRO V21

## Cambios principales
- El RTMP ya no usa un `concat.txt` estático. Emite clip por clip y repite la playlist continuamente.
- El Programador Diario/Semanal/Mensual/Trimestral cambia también el programa RTMP cuando dispara una nueva programación.
- Al cambiar la playlist manualmente durante RTMP, la salida se actualiza.
- MPV sigue siendo el reproductor local desde `mpv-x86_64`.
- Se añadieron pausa, volumen y mute del audio **solo local**. El audio del RTMP no se silencia.
- Playlist con botones explícitos para eliminar y vaciar, además del menú contextual.
- El scheduler usa las fuentes/categorías guardadas en SQLite.

### Nota RTMP
Al cambiar de clip o programación, FFmpeg se reinicia para ese clip sobre la misma URL RTMP. Esto evita que el RTMP siga usando la película anterior, que era el problema de V20. Dependiendo del servidor RTMP puede existir un pequeño reconectado entre clips; el siguiente paso para eliminar ese gap será un motor de continuidad con buffer/conmutador persistente.
