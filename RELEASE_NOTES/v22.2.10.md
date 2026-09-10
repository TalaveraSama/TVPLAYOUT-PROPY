# TVPlayout PRO V22.2.10

## Bug fix crítico: monitor negro después de cada corte de clip

### Síntoma

Después de v22.2.9, el watchdog detectaba correctamente el fin del clip y el grid avanzaba
al siguiente clip (la fila se ponía azul "AL AIRE" y la próxima se pintaba amarilla).
Pero el **monitor local quedaba en negro** durante toda la reproducción del nuevo clip.
El audio funcionaba bien, los "1 warning" del statusBar (antes 105) se habían resuelto
con el fix de VU en v22.2.9, pero el video no se mostraba.

### Causa raíz

mpv, por defecto, tiene **dos opciones activas** que son letales para un playout:

- `--resume-playback=yes` (default): cuando mpv carga un archivo, busca en
  `~/.config/mpv/watch_later/` si hay una posición guardada para ese archivo
  y, si la hay, hace seek a esa posición antes de decodificar el primer frame.
- `--save-position-on-quit=yes` (implícito en `loadfile replace` según la doc
  oficial): cuando se hace `loadfile path replace`, mpv **guarda la posición
  actual del clip saliente en watch_later**.

La combinación es:

1. El operador reproduce un clip hasta el final (o casi).
2. El watchdog o el `end-file` event cierra ese clip.
3. mpv guarda `start=03:08.000` (o lo que sea) en
   `%APPDATA%/mpv/watch_later/STREET FIGHTER.mp4.cfg`.
4. La próxima vez que `STREET FIGHTER` se carga (vía `loadfile path replace`),
   mpv ve el `.cfg` y **arranca en esa posición guardada** (al final del clip).
5. El clip arranca al final, la ventana se queda en negro (frame al EOF), el
   watchdog detecta `elapsed > duration + 2.0`, llama a `_on_ended("eof")` y
   avanza al siguiente. La UI dice "AL AIRE" pero el monitor está en negro.

El `set_property("start", "none")` que mandamos en `play()` **no gana**: la
doc oficial de mpv dice textualmente
("The playback position is always saved as start, so adding start to this list
has no effect" — el watch_later siempre pisa el start del clip).

### Fix

`app/mpv_player.py`:

1. `_build_cmd()` ahora pasa `--no-resume-playback` y `--no-save-position-on-quit`
   a la línea de comando de mpv. mpv ya no restaura ni guarda posiciones.
2. Nuevo método `_purge_watch_later()` que se llama al arrancar y borra los
   archivos `.cfg` que mpv pueda haber dejado en `watch_later` de versiones
   anteriores o de otras instancias. Garantiza que ningún clip va a "arrancar"
   en una posición vieja.
3. Busca los directorios de watch_later en:
   - `$MPV_HOME/watch_later` (override)
   - `$XDG_STATE_HOME/mpv/watch_later` (Linux/macOS)
   - `%APPDATA%/mpv/watch_later` (Windows)
   - `~/AppData/Roaming/mpv/watch_later` (Windows sin APPDATA)
   - `~/.config/mpv/watch_later` (Linux/macOS)
   - `~/.local/state/mpv/watch_later` (Linux/macOS)

`tests/test_v22_1_integration.py`:

- Nuevo test `test_mpv_player_disables_watch_later` que verifica la presencia
  de los dos flags en `_build_cmd`, la existencia del método
  `_purge_watch_later()`, su invocación desde `_build_cmd`, y que limpia
  archivos `.cfg` en las rutas correctas (Windows APPDATA y Linux .config /
  XDG_STATE_HOME).

Total tests: **19/19 OK**.

### Por qué este fix es el correcto y no otro

Otras hipótesis que se consideraron y descartaron:

- ❌ "el `wid` se stale después del loadfile replace" — si fuera esto, ni el
  audio ni los property-change events (time-pos 33s) llegarían. Ambos llegan.
  El `wid` está bien.
- ❌ "vo=gpu swap chain stale" — el rendering pipeline está vivo (audio +
  property changes). Si vo=gpu estuviera roto, mpv no reportaría nada.
- ❌ "el `loadfile` se rechaza y mpv sigue con el archivo viejo" — mpv SÍ
  cambió de archivo (la duración reportada es 03:08, que es del nuevo clip).
- ❌ "el clip no tiene video track" — si así fuera, mpv reportaría
  `eof-reached` con `reason=error`, no `reason=eof`.
- ✅ "mpv está cargando el archivo en una posición guardada en watch_later"
  — explica perfectamente todos los síntomas observados.

### Cómo verificar

1. Bajar el binario de v22.2.10 desde
   [Releases](https://github.com/TalaveraSama/TVPLAYOUT-PROPY/releases/tag/v22.2.10).
2. Reemplazar el binario actual.
3. Reproducir un clip de la tanda hasta el final.
4. Cortar al siguiente clip (automático por watchdog o manual con el botón
   "Siguiente" del playout).
5. **El monitor debe mostrar el primer frame del nuevo clip inmediatamente.**
6. Repetir varias veces para confirmar que el fix es estable.

Si en la primera ejecución ves el log
`watch_later purgado: N archivos en ...`, eso confirma que se estaban
usando posiciones viejas y que la app las limpió. En ejecuciones
posteriores no debería aparecer (ya no hay nada que limpiar).

### Downgrade

Si por alguna razón v22.2.10 rompe algo en tu entorno, el binario de
v22.2.9 sigue disponible en la lista de releases. Sin embargo, v22.2.9
tiene el bug del monitor negro — al volver a v22.2.9 deberías también
borrar manualmente `%APPDATA%/mpv/watch_later/` para evitar el problema.
