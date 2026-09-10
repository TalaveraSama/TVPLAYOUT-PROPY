# TVPlayout PRO V24.0.2.24

## Corrección del IPC de mpv en Windows (fin de clip y VU mudos)

- El named pipe de `--input-ipc-server` de mpv en Windows es un **stream de bytes**; la versión anterior lo envolvía con `PipeConnection`, que asume pipes en modo MESSAGE.
- Resultado: `time-pos`, `duration`, `file-loaded` y `end-file` nunca llegaban — el VU quedaba mudo, la barra de progreso dependía sólo de la estimación por reloj de pared y el playout avanzaba con el watchdog en vez del evento real de fin de clip.
- Ahora el pipe se abre con `_winapi.CreateFile` en modo **síncrono** (sin `FILE_FLAG_OVERLAPPED`) y se lee/escribe con `ReadFile`/`WriteFile` bloqueantes; `_read_loop` arma las líneas JSON delimitadas por `\n` como siempre.
- El watchdog queda como red de seguridad y cualquier fallo inesperado abriendo el pipe se degrada a «MPV no conectado» sin tumbar la aplicación.
- Se integra el fix de los PR #4 (dos commits, autoría original conservada) mediante cherry-pick.
- Nueva prueba estructural en `test_v24_continuity.py` que impide volver al modo MESSAGE.

## Cobertura de `fmt_tc`

- `test_core.py` cubre ahora `fmt_tc(None)`, `show_hours=False` (con y sin horas) y el modo frames con fps (PR #5, autoría original conservada).

## Validación

- `python tests/test_v24_continuity.py` — 18/18
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- `python -m py_compile app/mpv_player.py app/config.py`
