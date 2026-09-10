# TVPlayout PRO V24.0.2.23

## Escaneo TMDB general y ventana de edición con buscador

- El botón **🎬 Escanear TMDB biblioteca** ahora es un escaneo general inteligente: recorre toda la biblioteca y procesa sólo los medios que aún no tienen ficha TMDB; lo que ya está escaneado se salta y no se vuelve a descargar.
- Si toda la biblioteca ya tiene ficha, pregunta si se desea re-escanear todo de todas formas.
- Al terminar muestra un resumen en la biblioteca: cuántas fichas se cargaron, cuántas no se encontraron y cuántas se procesaron en total.
- Nueva ventana **✎ Editar ficha TMDB…** en la biblioteca (botón y menú contextual).
- La ventana abre un buscador de TMDB por título: hasta 20 resultados con miniatura de póster, año y sinopsis.
- Al elegir un resultado se descarga la galería completa de la película (hasta 12 pósters y 12 backdrops, español primero) para elegir exactamente qué imagen guardar.
- Permite guardar la ficha sin póster o sin backdrop («✕ Sin póster» / «✕ Sin backdrop») o quitar por completo la ficha TMDB del medio.
- Las imágenes elegidas se guardan en la caché en calidad final (póster w342, backdrop w780) y se reflejan de inmediato en la biblioteca y en la tarjeta al aire.
- La búsqueda arranca sola al abrir la ventana con el título actual del medio; también puede escribirse cualquier otro título.

## Validación

- `python tests/test_v24_continuity.py` — 17/17
- `python tests/test_v22_1_integration.py` — 41/41
- `python -m py_compile app/main_window.py app/tmdb.py app/dialogs_tmdb.py`
