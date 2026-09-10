# TVPlayout PRO V24.0.2.17

## RTMP restaurado sobre la base v24.0.2.13

La comparación de código confirmó que v24.0.2.13 tenía el motor RTMP estable. La regresión posterior estaba en el control de drift de `MainWindow`, que podía enviar un `seek_to` mientras el worker seguía vivo pero FFmpeg ya estaba entre un proceso y otro.

- `app/output.py` vuelve al código RTMP de v24.0.2.13, incluida la misma construcción de comando, NVENC/x264, mapa de audio y filtro de subtítulos.
- El watcher de drift conserva el enfriamiento, pero no interviene si no existe un proceso FFmpeg activo.
- Se conservan los índices exactos para el cambio de pistas en vivo.
- Se conservan los diagnósticos PyAV de pista y eventos.
- NDI permanece sin modificaciones.

## Validación

- `python tests/test_v24_continuity.py` — 13/13
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/main_window.py app/playout.py app/dialogs.py app/output.py app/pyav_player.py app/tmdb.py tests/test_v24_continuity.py`
