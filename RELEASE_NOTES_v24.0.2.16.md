# TVPlayout PRO V24.0.2.16

## Regresión RTMP corregida

- Se restaura la sintaxis exacta de subtítulos FFmpeg usada en v24.0.2.13, que era la última versión confirmada por el operador como funcional para RTMP y subtítulos.
- El cambio de audio/subtítulos en vivo continúa usando índices exactos y reinicia sólo el evento actual.
- Se conserva el diagnóstico PyAV de pista y eventos de subtítulos.
- NDI permanece sin modificaciones.

## Validación

- `python tests/test_v24_continuity.py` — 13/13
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/main_window.py app/playout.py app/dialogs.py app/output.py app/pyav_player.py app/tmdb.py tests/test_v24_continuity.py`
