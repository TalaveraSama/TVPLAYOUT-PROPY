# TVPlayout PRO V24.0.2.14

## Audio, subtítulos y estabilidad RTMP

- Editar el evento al aire guarda y usa el índice exacto de audio/subtítulo (`#0`, `#1`, etc.), aunque el archivo no tenga etiquetas de idioma.
- El cambio en vivo registra en el log `audio_id`, `subtitle_id` y el offset usado para reiniciar PyAV/RTMP.
- El watchdog de drift ahora tolera diferencias transitorias y exige dos lecturas consecutivas antes de realinear.
- Se amplía la ventana de enfriamiento después de una reconexión para evitar que RTMP entre en un ciclo de reinicios.

## Validación

- `python tests/test_v24_continuity.py` — 12/12
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/main_window.py app/playout.py app/dialogs.py app/output.py app/pyav_player.py app/tmdb.py tests/test_v24_continuity.py`
