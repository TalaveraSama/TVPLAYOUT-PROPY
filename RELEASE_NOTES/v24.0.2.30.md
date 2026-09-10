# TVPlayout PRO V24.0.2.30

## Auto-recorte de intro y final + Editar clip en biblioteca

### ✂ Auto-recortar biblioteca
- Nuevo botón **✂ Auto-recortar biblioteca** (y opción de menú contextual **✂ Auto-recortar selección…**): detecta y recorta automáticamente la intro del inicio y el remate del final de las películas.
- Cómo funciona: se analizan el primer minuto y medio y los dos últimos minutos de cada archivo con el filtro `blackdetect` de FFmpeg. El arranque se recorta **desde el final del último tramo negro de la cabecera**, de modo que el ident del estudio (p. ej. el «Netflix» rodeado de negro) queda saltado; el final se recorta **en el primer tramo negro de la cola**.
- El botón procesa toda la categoría **Películas** en segundo plano y salta lo que ya está recortado; la selección contextual fuerza el re-análisis de los medios elegidos (cualquier categoría).
- Guardas de seguridad: nunca deja menos de un minuto de película, ignora cortes menores a 0,5 s (inicio) y 1 s (final), aplica un colchón de 0,25 s para no morder el primer/último fotograma y **hace caso omiso de parpadeos negros breves** (menores a 0,6 s) aunque el detector no los hubiera filtrado.
- Progreso visible en la barra de estado de la biblioteca; se puede detener volviendo a pulsar el botón.

### ✎ Editar clip (biblioteca)
- Nuevo botón **✎ Editar clip** en la biblioteca (también en el menú contextual): título, categoría y recorte manual de inicio/fin para el medio seleccionado, con vista previa de la duración al aire.
- Los recortes se guardan **en la biblioteca** (no por evento): cada vez que ese medio se añada a la playlist —manualmente, con aleatorios, desde el programador o cargando una playlist— el recorte se aplica solo.
- El archivo original nunca se modifica.

### Integración con la playlist
- Los recortes de biblioteca llegan también a los eventos **ya cargados** en la playlist (si no tienen recortes propios) al actualizar metadatos o al terminar el auto-recorte.
- La columna **Duración** de la biblioteca ahora muestra la duración al aire con marca ✂ y el detalle del recorte en el tooltip.
- Al cargar una playlist guardada, los eventos sin recortes propios heredan los de la biblioteca.

## Validación

- `python tests/test_v24_continuity.py` — 22/22 (incluye prueba pura del detector con patrón intro «negro → ident → negro → película»)
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): worker end-to-end con detector simulado (DB actualizada con las marcas), herencia de recortes al cargar playlists, make_item aplicando los recortes y diálogo Editar clip.
- Smoke UI completo con FFmpeg simulado que emite líneas `blackdetect` reales: pipeline completo de subprocess, progreso en la barra de estado, columna Duración con ✂, segunda pasada que salta lo ya recortado y re-análisis forzado desde la selección.
