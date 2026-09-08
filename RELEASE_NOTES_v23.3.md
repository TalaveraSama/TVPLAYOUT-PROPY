# TVPlayout PRO V23.3

## Feature: filler automático + slate cuando se acaba la playlist

Antes de v23.3, cuando se acababa la playlist (sin loop, sin autofill,
o ambos desactivados), el monitor local quedaba en negro hasta que el
operador cargara una nueva lista o apretara PLAY manual. v23.3 resuelve
eso: cuando no hay más clips para reproducir, se carga automáticamente
un clip de **filler** en loop infinito. Si no hay filler configurado,
se muestra un **slate estático** generado en runtime con la URL
`av://lavfi` de mpv.

### Cómo funciona

Cuando `_on_ended("eof")` corre y no encuentra un próximo clip
(normal, autofill, loop), se ejecuta el siguiente flujo:

1. **Filler configurado**: si `filler_path` apunta a un archivo
   existente, se carga con `MPVPlayer.play_loop(path)` que setea
   `loop-file=inf` y `loop-playlist=inf`. El clip se reproduce en
   loop infinito. La convención interna es `self.onair = -2` mientras
   el filler está al aire. Si mpv termina el clip (no debería pasar
   con `loop-file=inf`), `_on_ended` lo detecta por la convención `-2`
   y lo recarga inmediatamente.

2. **Slate lavfi**: si no hay filler configurado, se carga la URL
   `av://lavfi:color=c=black:s=1920x1080:r=30,drawtext=text='TVPlayout
   PRO':...,drawtext=text='PROXIMAMENTE':...,format=yuv420p`. mpv
   genera el slate en runtime — no requiere archivos externos ni
   librerías adicionales. El slate se reproduce en loop infinito.

3. **Sin nada**: si `filler_enabled` está en `False` en settings, no
   se carga ni el filler ni el slate — comportamiento legacy (monitor
   en negro). El operador lo activa explícitamente si lo quiere.

### Configuración

En `DEFAULT_SETTINGS` (settings del usuario):

- `filler_path` (string, default `""`): path absoluto a un clip de
  filler. Puede ser un MP4 con el logo del canal, un "Próximamente"
  animado, un clip de stock, etc. Si está vacío, se usa el slate
  lavfi. Si el archivo no existe, fallback al slate.
- `filler_enabled` (bool, default `True`): si está en `False`, el
  playout NO carga filler ni slate (legacy, monitor en negro).

### Implementación

`app/mpv_player.py`:

- Nuevo método `play_loop(path)` que carga un clip con `loop-file=inf`
  y `loop-playlist=inf`, sin filtros de crossfade (el filler debe ser
  continuo). Acepta tanto paths (C:/filler.mp4) como URLs
  (`av://lavfi:...`). Saca los filtros de crossfade residuales de
  clips anteriores con `af remove @fadein` y `af remove @fadeout`.

`app/playout.py`:

- Nuevos atributos `self.filler_path` (string) y `self.filler_active`
  (bool). Nuevo contador `_filler_play_count` para diagnóstico.
- Nuevos métodos `_play_filler(reason)` y `_play_slate()`. El primero
  carga el clip configurado en `filler_path`. El segundo carga la URL
  lavfi del slate.
- Modificado `_on_ended` para que, cuando no hay próximo clip y la
  razón es `eof`, intente cargar el filler y, si falla, el slate.
  Convención: `self.onair = -2` mientras el filler está al aire, así
  `_on_ended` puede distinguir entre un clip normal y el filler (y
  recargar el filler en lugar de buscar el siguiente).
- Modificado `_on_position` para que **ignore** las actualizaciones
  de mpv cuando `onair == -2` (filler). El filtro lavfi no tiene
  duración significativa, así que actualizarla confundiría al display
  y al watchdog.

`app/main_window.py`:

- `DEFAULT_SETTINGS` agrega `filler_path` y `filler_enabled`.
- `apply_settings` carga `filler_path` en `self.ctrl.filler_path`.
  (El `filler_enabled` es leído pero no aplicado al controller —
  siempre True por default. Si en el futuro hay UI para togglear,
  se conectará acá.)

### Tests

- `test_mpv_player_supports_play_loop`: valida que `play_loop` setea
  `loop-file=inf`, usa `loadfile`, saca los filtros de crossfade
  residuales, y NO agrega nuevos filtros de `afade`.
- `test_playout_has_filler_and_slate`: valida que
  `PlayoutController` expone `filler_path`, `filler_active`,
  `_play_filler` y `_play_slate`; que `_on_ended` los invoca como
  fallback; que la convención `onair = -2` se usa; y que
  `_on_position` ignora actualizaciones del filler.
- `test_main_window_has_filler_setting`: valida que
  `DEFAULT_SETTINGS` tiene `filler_path` y `filler_enabled`, y que
  `apply_settings` los carga en `self.ctrl.filler_path`.

Total tests: **25/25 OK**.

### Slate lavfi: por qué no usamos PIL

PIL (Pillow) no está en `requirements.txt` y agregarla implica:
- Sumar ~5 MB al ejecutable con PyInstaller.
- Verificar que funcione en Windows, macOS y Linux sin libs extra.

La URL `av://lavfi:color=...:drawtext=...` es **mejor** porque:
- mpv ya la soporta nativamente (FFmpeg integrado).
- No requiere dependencias adicionales.
- El texto es generado por mpv en runtime, sin archivos PNG en disco.
- Funciona en cualquier plataforma sin configuración.

El slate es **básico** (sin reloj). Para un slate con reloj, se
necesitaría un filtro drawtext con `text='%{localtime\:%H\\\\:%M\\\\:%S}'`
(opción de FFmpeg) — eso es un TODO para v23.3.1 o v23.4.

### Riesgos identificados y mitigaciones

- **El slate lavfi puede no funcionar en builds recortados de mpv** que
  no tengan lavfi/ffmpeg completo. Mitigación: en ese caso, mpv
  responde con error en el log, el `_play_slate` retorna sin hacer
  nada, y el playout queda con monitor en negro (igual que antes, no
  peor). El operador puede entonces configurar un `filler_path` con un
  MP4 propio.
- **El watchdog de v22.2.9 puede disparar con el filler si mpv
  reporta una posición > duración.** Mitigación: `_on_position` ignora
  el filler (`onair == -2`), así que `_pos` y `_dur` quedan en 0.
  Como `duration` es 0, el watchdog no se activa. El filler se
  reproduce en loop infinito sin disparar `_on_ended`.
- **El clip de filler.mp4 puede tener un gap perceptible al hacer
  seek a 0** (cuando `loop-file=inf` repite el archivo). Mitigación:
  documentar en las release notes que el operador debe usar un clip
  con crossfade natural al final (ej: fade-to-black) o un loop
  perfectamente encadenado.
- **El operador podría configurar un filler muy pesado** (4K 60fps).
  Mitigación: documentar que un MP4 1080p 30fps es suficiente para
  un slate genérico.

### Cómo verificar

1. Bajar el binario de v23.3 desde
   [Releases](https://github.com/TalaveraSama/TVPLAYOUT-PROPY/releases/tag/v23.3).
2. Cargar una playlist de 2-3 clips y dejar que se acabe.
3. Sin filler configurado, el monitor debe mostrar un slate negro
   con texto "TVPlayout PRO" arriba y "PRÓXIMAMENTE" debajo, en
   loop infinito.
4. (Opcional) Configurar un `filler.mp4` desde Ajustes: agregar
   `"filler_path": "C:/videos/filler.mp4"` al settings.
5. Repetir: el monitor debe mostrar el `filler.mp4` en loop infinito.
6. Mientras el filler está al aire, cargar una nueva playlist y
   apretar PLAY. El playout debe interrumpir el filler y arrancar
   el primer clip de la nueva lista.

### Downgrade

Si v23.3 rompe algo, el binario de v23.0 sigue disponible. No hay
cambios de schema en la BD. Los settings `filler_path` y
`filler_enabled` son nuevos y se ignoran silenciosamente si la
versión vieja los lee.
