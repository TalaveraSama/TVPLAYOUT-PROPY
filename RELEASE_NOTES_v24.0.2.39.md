# V24.0.2.39 — La salida ya no puede desincronizarse de la playlist

## Qué mostró tu log de la madrugada (00:14–00:27)

Tenías razón: el RTMP terminó emitiendo contenido sin relación con la
playlist. Dos fallos encadenados, ahora corregidos:

**1) A las 00:14:10** — `gap de arranque 175.25s`: el FFmpeg con el filtro de
subtítulos sobre la unidad de red (comportamiento de la V24.0.2.37; la .38 ya
lo elimina) tardó **4 minutos** en emitir su primer frame. Cuando por fin
emitió, iba por el segundo 1.73 mientras el playout iba por el minuto 3.
El vigilante de la v35 aceptó ese gap de 175 s como "latencia de arranque
normal" y lo usó de línea base: la señal quedó 3 minutos atrás del playout
para siempre, sin que nada la corrigiera.

**2) A las 00:18:24** — `Error number -10053` (el servidor RTMP cortó la
conexión). El FFmpeg murió y el worker, en vez de reconectar la MISMA
película, **avanzó a la siguiente** («Retrato de una mujer en llamas»).
Resultado: la señal emitía una película que no era la del playout, y el
vigilante volvió a bendecir el desfase (`gap de arranque 710.18s` a las
00:27).

**3) Además**, el auto-recorte de 568 películas (arrancó a las 00:09:43, al
inicio) leía la unidad de red a full compitiendo con la emisión al aire.

## Qué cambia en esta versión

1. **Un error de conexión NUNCA cambia de película.** Si la conexión RTMP se
   corta a mitad de película, se reconecta **la misma película en la última
   posición emitida** (breve pausa de un par de segundos, la señal continúa
   donde estaba). Sólo tras 3 reintentos fallidos pasa al siguiente evento.
2. **Gap de arranque acotado a 45 s.** El primer frame de un arranque normal
   llega con 2–10 s de latencia; eso sigue siendo línea base. Pero un gap de
   45 s o más (señal que tardó minutos en arrancar) ya no se acepta: se
   realinea al minuto del playout, hasta 3 veces; después se acepta para no
   cortar la señal en bucle.
3. **Identidad de evento vigilada.** Si la salida queda en **otro evento**
   que el playout: si va ATRÁS (el playout ya cambió), se realinea de
   inmediato. Si va ADELANTE (terminó antes el evento), se avisa una vez con
   recomendación del modo Reloj — sin reinicios en bucle al final de evento.
4. **Auto-recorte más amable con la red**: pausa de 1.5 s entre archivos para
   no competir con la emisión al aire.

## Verificación

- 42/42 tests de continuidad v24 (nuevos: reintento del mismo evento con
  reconexión en la última posición y "reintentos agotados"; gap patológico se
  realinea; salida en otro evento atrás/adelante).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Smoke del fallo exacto de la madrugada: (1) arranque que tarda 12 s en dar
  frame → se realinea UNA vez y estabiliza con gap 1 s; (2) corte -10053 a
  los 8 s → 3 arranques TODOS en la misma película retomando en 7 s y 14 s,
  la siguiente jamás arranca.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.39.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Sin cambios de
ajustes. Nota: tu log de la madrugada es de la **V24.0.2.37** — la **.38**
(elimina la doble apertura del vídeo por los subtítulos) y esta **.39**
componen entre las dos todo lo visto esa noche. Y para el VPS sigue siendo
la recomendación clave: Ajustes → Monitor de programa → **Reloj del sistema**.
