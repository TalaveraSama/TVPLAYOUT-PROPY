# V24.0.2.45 — Auto-recorte ELIMINADO por completo

## Qué se quitó

El **auto-recorte** (el detector automático de intro/final que corría solo
tras cada escaneo analizando películas en segundo plano) queda **eliminado
del programa por completo**:

- Ya **no se analiza ni se recorta nada automáticamente** al escanear la
  biblioteca. El escaneo y el análisis de metadatos (duración, miniaturas)
  siguen igual — sólo desaparece el recorte automático.
- Desaparecen el botón «✂ Auto-recortar biblioteca», el «✂ Auto-recortar
  selección…» del menú contextual y la casilla de Ajustes.
- **Se limpian una sola vez los recortes que ya había aplicado** en la
  biblioteca y en las playlists guardadas (heredaban y persistían esas
  marcas): **las películas vuelven a emitirse completas, de principio a fin**.
- El recorte **manual** sigue disponible: «✎ Editar clip…» permite ajustar a
  mano el inicio/fin de un evento cuando TÚ lo decidas. Lo que edites a mano
  a partir de ahora no se toca nunca más.

## Por qué se quitó

El análisis en segundo plano leía la biblioteca completa por la unidad de
red mientras la emisión estaba al aire, compitiendo con la salida RTMP por
el disco y la red (avisos «Resumed reading after a lag» en el log). Sin
auto-recorte, esa competencia desaparece de raíz: tras escanear ya no se
lee película alguna en segundo plano.

## Sobre el desfase monitor vs RTMP (transmisiones separadas)

Es inherente a decodificar el video dos veces (monitor local + RTMP). El
programa ofrece dos modos que lo eliminan, en **Ajustes → Monitor de
programa**:

- **«Reloj del sistema (sin decodificar — ideal VPS)»**: el monitor pasa a
  ser un reloj; sólo FFmpeg decodifica (la salida). Es el modo recomendado
  para el VPS: cero competencia de CPU y el playout avanza con el reloj de
  pared. La lista y los cambios de evento quedan atados a la HORA, no a la
  decodificación local.
- **«Programa FFmpeg → reproductor externo»**: el MISMO FFmpeg que emite por
  RTMP entrega además su video ya codificado a un reproductor aparte (mpv o
  VLC): lo que ves en el monitor es **exactamente el mismo video que sale
  por RTMP** — sin segunda decodificación ni desfase posible entre ambos.

En el VPS con CPU justa (el log mostró que no decodifica 1080p en tiempo
real), usa «Reloj del sistema»; si quieres ver video, usa el modo
«Programa FFmpeg» en lugar del PyAV predeterminado.

## Verificación

- 45/45 tests de continuidad v24 (nuevo: el auto-recorte no existe en el
  código; la limpieza de marcas ocurre una sola vez y un recorte manual
  hecho tras actualizar sobrevive a reinicios).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.45.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — acepta tu mpv local como argumento).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Al abrir por
primera vez esta versión, la limpieza de recortes es automática. Ajustes
recomendados para 24/7 en el VPS: Restaurar playlist ✓ + Poner AL AIRE
automáticamente ✓ + Monitor «Reloj del sistema».
