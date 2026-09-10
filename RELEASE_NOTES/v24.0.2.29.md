# TVPlayout PRO V24.0.2.29

## Franja de la tarjeta TMDB transparente, sin foto

- La franja rectangular de la tarjeta TMDB ya **no muestra la foto del backdrop**: sólo el póster, el título y la descripción sobre un fondo translúcido que deja ver el vídeo.
- El oscurecido de la franja sigue siendo ajustable con **Opacidad del fondo** (0–100 %); en 0 % la franja queda totalmente transparente.
- Para recuperar la foto de fondo, la ventana **Tarjeta TMDB** tiene la nueva casilla **«Foto de fondo (backdrop) en la franja»**, desactivada por defecto, con vista previa en vivo.
- La casilla aplica tanto a la banda completa como a la tarjeta compacta.
- Como siempre, el ajuste se guarda y se aplica de inmediato al aire si hay una tarjeta activa.

## Corregido además

- Ajustes en 0 respetados: por un detalle de la versión anterior, poner **Opacidad del fondo** o **Margen** en 0 hacía que el valor cayera al predeterminado (70 % / 18 px) sin efecto. Ya no ocurre.

## Validación

- `python tests/test_v24_continuity.py` — 20/20
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): verificación por píxeles de que la franja no contiene la foto (sólo oscurecido + póster + texto) con la casilla apagada, y de que la foto aparece al activarla, en ambos estilos.
