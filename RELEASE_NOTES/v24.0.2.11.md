# TVPlayout PRO V24.0.2.11

## Cambio de idioma y subtítulos en vivo

- Audio y subtítulos pueden cambiarse desde **Ajustes** mientras hay un evento al aire.
- El cambio reinicia PyAV en el mismo offset del evento actual.
- RTMP/SRT reciben el mismo salto con las nuevas pistas; se acepta un corte breve de aproximadamente 1–2 segundos para evitar desincronización.
- Si está activado el quemado de subtítulos, FFmpeg vuelve a iniciar con la pista seleccionada sin esperar al siguiente evento.
- Se añadieron preferencias explícitas `en`, `eng` y `English`, además de las opciones españolas existentes.
- El índice de audio/subtítulos se conserva en el flujo PyAV y en la selección FFmpeg.

## Validación

- `python tests/test_v24_continuity.py` — 9/9
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/playout.py app/pyav_player.py app/output.py app/dialogs.py app/main_window.py tests/test_v24_continuity.py`
