# TVPlayout PRO V24.0.2.18

## Biblioteca: metadatos e imágenes TMDB

- La Biblioteca ahora muestra una columna **Imagen** con el póster TMDB cargado o, como respaldo, la miniatura local.
- El clic derecho sobre una película incluye **Escanear metadatos de selección** y **Escanear TMDB • imagen/película**.
- Se añadió el botón **🎬 Escanear TMDB** en la botonera de Biblioteca.
- El escaneo TMDB guarda título, año, resumen, póster y backdrop en SQLite y actualiza también la imagen del clip en la vista gráfica si está en la playlist.
- La selección de metadatos con ffprobe puede repetirse sólo sobre los clips elegidos.
- La API key continúa configurándose desde Ajustes.

## Validación

- `python tests/test_v24_continuity.py` — 14/14
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/main_window.py app/db.py app/prober.py app/playout.py app/tmdb.py tests/test_v24_continuity.py`
