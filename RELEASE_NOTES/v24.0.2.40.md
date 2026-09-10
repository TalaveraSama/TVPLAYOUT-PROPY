# V24.0.2.40 — Por qué el RTMP se desfasaba POR HORAS de la playlist (y el cierre del caso)

## El mecanismo completo, con tu log de la madrugada

El desfase de horas no tenía una sola causa: eran **tres, apiladas**, y tu
log (V24.0.2.37) las muestra todas:

**1. Tu reloj local avanza a ~66% (la causa del desfase acumulable).**
El monitor PyAV decodifica a ⅔ de tiempo real (en tu log: 946 s de película
en 1391 s de pared = 68%). El playout sólo avanza al siguiente evento cuando
el monitor termina la película actual → el RTMP (que sí va a 1x) **consume la
playlist un 50% más rápido que el playout** → cada hora de pared el RTMP gana
~20 minutos de lista → en una noche, **horas** de desfase. Este es el
mecanismo que hace que la señal y la playlist acaben en películas distintas.

**2. El error de conexión saltaba de película (00:18:24).** `Error -10053` →
el worker avanzaba a «Retrato de una mujer en llamas» sin que el playout lo
pidiera (corregido en V24.0.2.39: reconecta la MISMA película en la última
posición emitida).

**3. Los gaps gigantes se bendecían (00:14 y 00:27).** Con la doble apertura
del vídeo por los subtítulos (eliminada en V24.0.2.38), el primer frame
tardaba minutos: `gap de arranque 175s` y luego `710s` se aceptaban como
"latencia normal" y nada volvía a corregirlos (corregido en V24.0.2.39: gap
> 45 s se realinea al playout, máx. 3 veces por clip).

## Qué añade esta versión (.40)

Al revisar el caso una vez más encontré un último borde en la v39: si la
salida empezaba un clip **muy por delante** del playout (exactamente lo que
pasa con tu reloj al 66%: el RTMP ya lleva 46 minutos del clip cuando el
playout lo empieza), la v39 la realineaba hacia atrás — **repitiendo 46
minutos de contenido ya emitido**. Ahora:

- Gap de arranque **positivo** gigante (salida muy ATRÁS, el caso 00:14) → se
  realinea **hacia adelante** al punto en vivo (nunca repite).
- Gap de arranque **negativo** gigante (salida muy ADELANTE por reloj local
  lento) → **no se toca la señal**: se avisa una vez con la magnitud en
  minutos («La salida va 46.0 minutos por delante del playout… usa el modo
  Reloj del sistema») y ese desfase queda como línea base estable. Sin
  cortes, sin repeticiones.

## La cura de fondo para tu VPS (importante)

Las .38/.39/.40 eliminan los saltos, las repeticiones y los desfases
"pegados"; pero mientras el reloj local siga al 66%, la señal seguirá
ganándole minutos a la lista (ahora sin cortes y avisado, pero ganando).
**El modo «Reloj del sistema» elimina la causa raíz**: el playout avanza por
reloj de pared a 1x exacto (sin decodificar), RTMP y playlist quedan
enganchados para siempre y el drift queda en ~0.

**Ajustes → Monitor de programa → «Reloj del sistema (sin decodificar — ideal
VPS)» → guardar → reiniciar las salidas.**

## Verificación

- 42/42 tests de continuidad v24 (nuevo caso: salida 46 min por delante al
  empezar el clip → sin realineo, sin repetición, aviso único con minutos, y
  estabilidad posterior sin reinicios).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.40.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Esta versión
incluye y completa todo el trabajo .38–.40; sin cambios de ajustes
obligatorios, pero **activa el modo Reloj del sistema** en el VPS.
