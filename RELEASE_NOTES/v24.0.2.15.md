# TVPlayout PRO V24.0.2.15

## Subtítulos y continuidad RTMP

- FFmpeg usa la forma explícita `subtitles=filename=...` con la unidad Windows escapada.
- Si el filtro de subtítulos del build instalado falla, el worker desactiva sólo ese filtro y mantiene vídeo/audio RTMP en lugar de detener la transmisión.
- PyAV registra `audio_id`, `subtitle_id`, el stream de subtítulos y los primeros eventos decodificados.
- El cambio de pista sigue usando índices exactos (`#0`, `#1`) y el mismo offset.

## Validación

- `python tests/test_v24_continuity.py` — 13/13
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/main_window.py app/playout.py app/dialogs.py app/output.py app/pyav_player.py app/tmdb.py tests/test_v24_continuity.py`
