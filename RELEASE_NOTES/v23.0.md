# TVPlayout PRO V23.0

## Feature: crossfade de audio entre clips (la killer feature)

Cuando termina un clip (sea por watchdog, fin natural, o botón "Siguiente"
del operador), **el audio del clip saliente se desvanece suavemente
mientras el clip entrante entra con un fade-in**. En vez de un corte
abrupto, hay una transición suave — al estilo de lo que hacen XPlayout
y los playouts profesionales.

### Cómo funciona

mpv soporta nativamente el filtro `lavfi=afade` (audio fade). V23.0
lo usa como una capa de presentación sobre el motor mpv existente
(sin reescribir nada, sin cambiar de motor, sin procesos nuevos).

- **Fade-in**: cuando se carga un clip nuevo, si crossfade está
  habilitado, se agrega el filtro `@fadein:lavfi=afade=t=in:st=0:d=N`
  al chain de audio de mpv. El audio arranca en silencio y sube
  linealmente durante N segundos.
- **Fade-out**: cuando quedan N segundos para terminar el clip al
  aire, `playout._tick()` (timer cada 500ms) detecta el momento y
  llama a `player.fade_out(N)`, que agrega `@fadeout:lavfi=afade=t=out`
  al chain. El audio baja linealmente durante N segundos.
- **Cuando mpv emite `end-file`**, el siguiente clip ya está
  reproduciéndose con su fade-in, y los dos fades se solapan.

El resultado es una transición suave **sin artefactos**, porque
los dos clips están decodificándose en paralelo y los filtros están
en el mismo chain de audio de mpv.

### Configuración

En la barra de herramientas del playout:

- **Toggle `Crossfade`**: habilita/deshabilita el crossfade.
  Si está OFF, los cortes son instantáneos (como en v22.2.10).
  Por defecto: **ON**.
- **Slider `CF: 0.5s`**: duración del crossfade, en pasos de 0.1s.
  Rango: 0.0s–3.0s. Por defecto: **0.5s** (default de mpv, suficiente
  para que el oído no note el corte sin generar sensación de overlap
  largo).
- Los dos valores se persisten en settings (`crossfade_enabled` y
  `crossfade_duration`).

### Aplica a

- **TODAS las transiciones** (consistente y profesional):
  - El primer clip del playout (con fade-in desde silencio).
  - Los cambios automáticos (tandas, hora exacta, autofill, loop).
  - Los cambios manuales con el botón "Siguiente".
  - Los cambios por watchdog de fin de clip (v22.2.9).

### Implementación

`app/mpv_player.py`:

- Nuevos atributos `self.crossfade_enabled` (bool, default True) y
  `self.crossfade_duration` (float, default 0.5).
- Nuevo flag `self._fade_out_applied` (bool) que se resetea en cada
  `play()` y se setea en `fade_out()` para no aplicar el fade-out
  dos veces al mismo clip.
- `play()` ahora agrega el filtro `@fadein:lavfi=afade=t=in:st=0:d=N`
  antes del `loadfile` si crossfade está habilitado. Si no, saca
  los filtros residuales con `af remove @fadein` y `af remove @fadeout`.
- Nuevo método `set_crossfade(enabled=None, duration=None)` para
  que la UI cambie el estado en tiempo real.
- Nuevo método `fade_out(duration)` que agrega el filtro
  `@fadeout:lavfi=afade=t=out:st=0:d=N` al chain. Se llama una
  sola vez por clip (chequeado por `_fade_out_applied`).

`app/playout.py`:

- `_tick()` ahora invoca `self.player.fade_out(self.player.crossfade_duration)`
  cuando `remain <= crossfade_duration + 0.05` y todavía no se aplicó
  el fade al clip actual. Se hace **antes** del watchdog de v22.2.9
  para que el fade esté completo cuando mpv emita end-file.
- El bloque del crossfade está al principio de `_tick()` y usa
  `getattr` con defaults seguros para que no rompa si el player
  no expone los atributos (caso defensivo).

`app/main_window.py`:

- Nuevo toggle `Crossfade` en la barra de herramientas (al lado de
  los toggles de modo: Autofill, Tandas auto, Hora exacta, Loop,
  Autoscroll).
- Nuevo slider `CF: N.Ns` (rango 0–30, paso 1, cada unidad = 0.1s)
  con label dinámico.
- Handlers `_crossfade_toggle_changed` y `_crossfade_duration_changed`
  que invocan `self.player.set_crossfade(...)` y persisten en
  settings con `self._save_setting(...)`.
- `apply_settings(first=True)` ahora aplica el estado del crossfade
  desde settings (con `blockSignals` para no triggerear handlers
  durante el restore).

### Tests

- `test_mpv_player_supports_crossfade`: valida atributos, métodos,
  filtros y la lógica de play().
- `test_playout_triggers_fade_out`: valida que `_tick` llama a
  `player.fade_out` con la duración correcta.
- `test_main_window_has_crossfade_controls`: valida toggle, slider,
  handlers, persistencia y restauración desde settings.

Total tests: **22/22 OK**.

### Por qué no usamos `acrossfade` (el filtro "nativo" de crossfade de mpv)

mpv tiene un filtro `lavfi=acrossfade` que está específicamente
diseñado para crossfade. Pero tiene una limitación importante: solo
funciona cuando los dos archivos están en la playlist de mpv al mismo
tiempo. Para eso, tendríamos que pre-cargar el próximo clip con
`loadfile next_path append-play` antes de que termine el actual, y
manejar la playlist de mpv manualmente. Eso es más complejo y más
frágil que el enfoque de dos `afade` separados.

El enfoque de `afade` que elegimos:
- ✅ No requiere manipular la playlist de mpv.
- ✅ No requiere pre-cargar el próximo clip.
- ✅ Compatible con el watchdog de v22.2.9 sin cambios adicionales.
- ✅ Compatible con el loadfile replace existente.
- ✅ Si crossfade está OFF, los filtros se quitan y el corte es
   instantáneo sin artifact.
- ❌ No hace crossfade de **video** (solo audio). El video sigue
   haciendo corte directo en el frame del end-file. Para crossfade
   de video haría falta dos instancias de mpv o libavfilter con
   `xfade`, que es el scope de v23.1 o v23.2.

### Riesgos identificados y mitigaciones

- **El filtro `afade` puede no estar en todos los builds de mpv.**
  Mitigación: el filtro `lavfi=afade` es estándar de FFmpeg y está
  en TODOS los builds de mpv con lavfi (que son todos los que
  recomienda mpv.io). Si no estuviera, `af add` falla silenciosamente
  y el audio se reproduce normal sin fade. (No es bloqueante.)
- **El watchdog de v22.2.9 puede cortar antes de que termine el
  fade-out.** Mitigación: el bloque de crossfade está **antes** del
  bloque del watchdog en `_tick()`, así que se evalúa primero. Si el
  watchdog dispara con `elapsed > duration + 2.0` mientras el fade
  está en curso, simplemente se llama a `_on_ended("eof")` y mpv
  emite end-file. El audio del clip saliente puede cortarse un poco
  antes, pero el efecto es despreciable (50ms).
- **El crossfade_duration puede ser muy largo y solapar dos clips
  cortos.** Mitigación: el rango es 0.0–3.0s, así que el peor caso
  es 3s de solape, que es aceptable hasta para clips de 5–10s.

### Cómo verificar

1. Bajar el binario de v23.0 desde
   [Releases](https://github.com/TalaveraSama/TVPLAYOUT-PROPY/releases/tag/v23.0).
2. Reemplazar el binario actual.
3. Cargar una playlist con al menos 2 clips de más de 5s cada uno.
4. Reproducir el primero, dejar que llegue al final.
5. **El audio del primer clip debe bajar gradualmente durante 0.5s
   mientras el audio del segundo sube gradualmente durante 0.5s.**
6. Mover el slider a 2.0s y repetir: el crossfade debe ser
   claramente más largo y perceptible.
7. Apagar el toggle "Crossfade" y repetir: el corte debe ser
   instantáneo (sin fade).

### Downgrade

Si v23.0 rompe algo, el binario de v22.2.10 sigue disponible en la
lista de releases. No hay cambio de schema en settings — los campos
`crossfade_enabled` y `crossfade_duration` son nuevos y se ignoran
silenciosamente si la versión vieja los lee.
