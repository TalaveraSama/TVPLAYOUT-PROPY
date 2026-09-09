# TVPlayout PRO V24.0.2.13

## Tarjeta TMDB de la película actual

- Integración opcional con la API de The Movie Database (TMDB).
- Busca la película actual de forma asíncrona, sin bloquear PyAV ni la emisión.
- Genera una tarjeta con backdrop, póster, título y año.
- Se muestra cada 18 minutos por defecto durante 15 segundos.
- El intervalo y la duración son configurables desde Ajustes.
- Se compone en el monitor PyAV, en RTMP/SRT y en el frame que recibe NDI directo.
- Las imágenes se guardan en `cache/tmdb` para reutilizarlas.
- La API key se configura desde Ajustes y se mantiene fuera del código fuente.

## Validación

- `python tests/test_v24_continuity.py` — 10/10
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python -m py_compile app/tmdb.py app/pyav_player.py app/playout.py app/output.py app/dialogs.py app/main_window.py tests/test_v24_continuity.py`
