# TVPlayout PRO V24.0.2.27

## Año de la película omitido en la tarjeta TMDB

- La tarjeta TMDB al aire ya **no muestra el año** junto al título — sólo el título de la película.
- Si quieres recuperarlo, la ventana **Tarjeta TMDB** (panel FUNCIONES) tiene la nueva casilla **«Mostrar año junto al título»**, con vista previa en vivo antes de guardar.
- El ajuste se guarda y se aplica de inmediato al aire si hay una tarjeta activa, igual que la posición y el estilo.
- El año sigue visible donde es útil para identificar la película: resultados del buscador de fichas y tooltip de la biblioteca.

## Validación

- `python tests/test_v24_continuity.py` — 20/20
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): render con y sin año (diferencia de píxeles verificada en la línea del título), normalización del ajuste y casilla del diálogo.
