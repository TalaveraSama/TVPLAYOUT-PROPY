# TVPlayout PRO V24.0.2.10

## Continuidad y publicidad

- Se conserva la tanda automática al finalizar cada película/evento.
- Se añade una tanda intermedia independiente, activable desde el botón **Tanda intermedia** o Ajustes.
- La tanda intermedia permite elegir categoría y definir el intervalo en minutos.
- Sólo se dispara en categorías `Películas` y `Música`.
- La película/vídeo musical se reanuda desde el offset exacto guardado por PyAV después de terminar todos los anuncios intermedios.
- RTMP/SRT recibe el mismo índice y offset; NDI directo continúa recibiendo los frames y el audio del PyAV local mediante el sender nativo.

## Identificadores

- Se pueden configurar dos archivos independientes: identificador de entrada e identificador de salida.
- Están pensados para clips de aproximadamente 8 segundos.
- Se aplican sólo a `Películas` y `Música`.
- No se insertan en `Publicidad`, filler ni slate.
- Son transitorios y no se acumulan en la playlist al repetir la continuidad.

## Validación

- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_v24_continuity.py` — 7/7
- `python -m py_compile app/playout.py app/dialogs.py app/main_window.py tests/test_v24_continuity.py`
