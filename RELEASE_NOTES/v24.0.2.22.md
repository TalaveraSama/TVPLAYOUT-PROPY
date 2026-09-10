# TVPlayout PRO V24.0.2.22

## Monitor de programa exacto

- PyAV/libav continúa siendo el monitor predeterminado.
- Nuevo modo opcional **Programa FFmpeg → reproductor externo** en Ajustes.
- FFmpeg duplica la señal ya procesada, con subtítulos quemados, audio seleccionado y overlays, a un feed MPEG-TS local.
- VLC, mpv o ffplay configurado por el usuario puede reproducir ese feed y mostrar exactamente lo que se está enviando por RTMP/SRT.
- El monitor externo no depende de capturar la pantalla ni del audio de Windows: recibe el audio interno codificado por FFmpeg.
- Al reiniciar FFmpeg por un cambio de pista en vivo, el proceso se termina con espera y kill de respaldo para evitar que RTMP quede colgado.
- Se añadió el puerto configurable del feed local.

## Validación

- `python tests/test_v24_continuity.py` — 16/16
- `python tests/test_v22_1_integration.py` — 41/41
- `python -m py_compile app/main_window.py app/output.py app/dialogs.py`
