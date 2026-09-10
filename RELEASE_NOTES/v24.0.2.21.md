# TVPlayout PRO V24.0.2.21

## Escaneo TMDB completo y búsqueda manual

- El botón **Escanear TMDB biblioteca** procesa todos los medios de la biblioteca.
- El escaneo usa una cola limitada para no abrir cientos de conexiones simultáneas.
- El clic derecho sobre una película ofrece **Escanear esta película en TMDB…**.
- La búsqueda manual permite escribir el título exacto cuando el nombre del archivo no coincide con TMDB.
- La ficha guarda póster y backdrop y actualiza la imagen de la biblioteca.

## Validación

- `python tests/test_v24_continuity.py` — 15/15
- `python tests/test_v22_1_integration.py` — 41/41
- `python -m py_compile app/main_window.py`
