# V24.0.2.35 — Corrige la lentitud del RTMP en VPS: fin del bucle de "realineando"

## Qué pasaba en tu VPS

Los logs que enviaste (09/09/2026, V24.0.2.33) mostraban esto, una y otra vez:

```
18:12:49  RTMP drift 9.48s (mpv=5.38s, ffmpeg_est=14.86s) — realineando
18:13:03  RTMP drift 7.86s (mpv=18.99s, ffmpeg_est=26.85s) — realineando
18:13:15  RTMP drift 7.52s (…)
18:13:29  RTMP drift 9.33s (…)
```

Un reinicio de FFmpeg **cada ~13 segundos, sin fin**. Cada reinicio congelaba la
señal unos segundos y volvía a arrancar desde atrás: eso era la lentitud (la
emisión iba a trompicones y la salida nunca avanzaba a tiempo real).

**La causa no era la tarjeta AMD** (h264_amf codificaba perfectamente). El
problema era el *vigilante de desincronización* (drift watcher):

- Estimaba la posición de FFmpeg con el **reloj de pared** desde que lo lanzaba:
  `posición = offset + (ahora − hora_de_arranque)`.
- En tu VPS, FFmpeg tarda **7–9 segundos** en arrancar: abrir un MKV grande por
  la **unidad de red Z:** + conectar al RTMP + inicializar AMF.
- Esa espera se contaba como si fuera **contenido ya emitido**: FFmpeg "parecía"
  ir 8 s por delante de su posición real cuando en realidad apenas empezaba.
- El vigilante lo interpretaba como desincronización → reiniciaba FFmpeg "hacia
  atrás" → el nuevo FFmpeg tardaba otra vez 7–9 s en arrancar → otro "drift"
  fantasma → otro reinicio. Bucle infinito.

Los mensajes `Resumed reading at pts … rate 1.050 after a lag of 0.3–1.4s` eran
síntoma de lo mismo: FFmpeg recién arrancado leyendo el archivo desde la unidad
de red en cada reinicio.

## Qué cambia en esta versión

1. **Posición REAL de FFmpeg en vez de estimación.** El comando ahora incluye
   `-stats`: FFmpeg reporta su posición exacta (`time=`) y la aplicación la lee
   directamente. Ya nada se estima con reloj de pared.
2. **El arranque ya no es drift.** Mientras FFmpeg calienta (abre el archivo,
   conecta), el vigilante **no compara**. En el primer frame emitido registra el
   *gap de arranque* (p. ej. 6–8 s en tu VPS) como línea base.
3. **Solo se realinea si el gap CRECE.** Una salida estable con 8 s de latencia
   de arranque es normal y saludable (los espectadores la ven completa, con un
   pequeño retardo fijo respecto a tu monitor local). Si el gap crece de forma
   sostenida — encoder que no da abasto o entrada atascada en la unidad de red —
   ahí sí realinea, una sola vez, y recalcula la línea base.
4. **Menos ruido en el log**: `-sc_threshold 0` ahora solo se pasa a x264. En
   h264_amf no está soportado y generaba el warning
   `Codec AVOption sc_threshold … not used` en cada arranque.

**Resultado en la prueba que reproduce tu escenario** (arranque lento de 6 s +
lectura de red): antes se reiniciaba cada ~13 s; ahora **0 reinicios en 30 s**,
con la salida estable y el gap fijo.

## Recomendaciones para tu VPS

- La corrección elimina el bucle, pero el origen de la latencia es la **unidad
  de red Z:**: el reproductor local (monitor de programa) y FFmpeg leen el mismo
  archivo a la vez por red. Si más adelante quieres menos latencia de arranque
  por clip, lo ideal es tener la biblioteca en **disco local del VPS** (o SSD).
- El monitor de programa (preview local) decodifica por software; en un VPS con
  poca CPU puedes minimizarlo mientras emites: no afecta a la señal RTMP.

## Verificación

- 36/36 tests de continuidad v24 (3 nuevos: medición real, tolerancia al gap de
  arranque, detección de atasco real).
- 41/41 tests de integración v22.1, 10/10 del programador.
- Smoke end-to-end del escenario del VPS: arranque lento + `time=` real →
  posición medida, línea base fijada, **sin reinicios**.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.35.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Descarga `Source code (zip)` de esta release, o el instalador compilado, y
reemplaza la carpeta del programa. Tu base de datos, biblioteca y ajustes no se
tocan.
