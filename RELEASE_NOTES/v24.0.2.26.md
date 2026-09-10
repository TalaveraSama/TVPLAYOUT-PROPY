# TVPlayout PRO V24.0.2.26

## Editor de ficha TMDB simplificado + corrección del cierre bloqueado

### Corregido: la ventana no dejaba cerrar ni guardar
- Al cerrar o guardar, el diálogo esperaba bloqueando hasta 4 s a los hilos de descarga de TMDB; si la red iba lenta, la ventana se congelaba y al destruirse con un hilo vivo Qt abortaba con el error **«QThread: Destroyed while thread is still running»**.
- Ahora los hilos de búsqueda y galería cuelgan de la **ventana principal**, no del diálogo: cerrar y guardar es **inmediato**, sin esperas ni crashes.
- Los resultados que llegan tarde (después de cerrar o de cambiar de película) se ignoran de forma segura.

### Buscador de imágenes renovado, más simple
- **Una sola galería**: al elegir una película se muestran todas sus imágenes juntas (pósters y fondos), cada una con su etiqueta.
- **Haz clic en la imagen correcta** y queda elegida al instante: marcada con **✓ Póster** o **✓ Fondo** según su tipo.
- Abajo, dos miniaturas muestran siempre el póster y el fondo elegidos, con su botón ✕ para guardar sin esa imagen.
- Se redujo a 8 pósters y 8 fondos por película para que la galería cargue más rápido.
- La búsqueda sigue arrancando sola al abrir la ventana con el título actual del medio.

## Validación

- `python tests/test_v24_continuity.py` — 20/20
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): galería única con marcas ✓, elección por clic, guardado sin póster/fondo y **cierre instantáneo con un hilo de descarga aún corriendo** (el caso que crasheaba antes).
