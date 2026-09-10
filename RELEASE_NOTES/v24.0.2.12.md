# TVPlayout PRO V24.0.2.12

## Correcciones de pistas en vivo

- El menú contextual **Editar clip** cambia audio y subtítulos del evento que está actualmente al aire.
- El cambio reinicia una sola vez PyAV en la posición actual; RTMP/SRT reciben un único salto en el mismo offset.
- Se añadieron opciones explícitas de inglés: `en`, `eng` y `English`.
- PyAV ahora decodifica subtítulos de texto seleccionados y los muestra en el monitor local.
- Cuando se selecciona una pista de subtítulos, FFmpeg la compone automáticamente en RTMP/SRT, aunque la salida hubiese arrancado con quemado desactivado.
- Se mantiene la salida NDI en pausa, sin cambios de arquitectura.

## Validación

- `python tests/test_v24_continuity.py` — 9/9
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/pyav_player.py app/playout.py app/output.py app/dialogs.py app/main_window.py tests/test_v24_continuity.py`
