# V24.0.2.38 — Activar subtítulos ya no mata el RTMP (biblioteca en red)

## Qué pasó esta noche (log 00:05)

La V24.0.2.37 hizo su trabajo: a las 00:01:22 el nuevo guard evitó el bucle de
reinicios («RTMP va 7.1s por delante del monitor local … NO se reinicia») y la
señal iba bien. Lo que rompió la transmisión fue **la ventana de Ajustes**:
guardaste con **Subtítulos preferidos = Español**. A partir de ahí, cada
comando de FFmpeg quedó así:

```
-vf subtitles='Z\:/PELICULAS/ Abracadabra.mkv':si=0,scale=...
```

Ese filtro le ordena a FFmpeg **abrir el MKV de 5.6 GB una segunda vez por la
unidad de red** para leer los subtítulos intercalados. El resultado, visible
en tu log: FFmpeg corría **sin error pero sin emitir un solo frame** (nunca
volvió a aparecer «RTMP en vivo»), y la señal quedaba muerta. Cada vez que
reiniciabas las salidas (00:05:37, 00:06:43, 00:08:39) el nuevo FFmpeg volvía
a quedarse clavado en lo mismo.

En bibliotecas locales el filtro funciona; en **red** (Z:) es un cuello de
botella silencioso.

## Qué cambia en esta versión

1. **Los subtítulos se queman desde un archivo SRT LOCAL, nunca reabriendo el
   vídeo por red.**
   - Si hay un `.srt` junto a la película, se usa directamente (pesa KBs).
   - Si no, la pista de subtítulos se **extrae una sola vez a un SRT local**
     (caché por archivo+pista) **en segundo plano**: la señal arranca de
     inmediato sin subtítulos y, cuando la extracción termina, hay un único
     reinicio breve para activarlos. Las siguientes veces la caché es
     instantánea.
2. **Subtítulos alineados al punto de la película.** El SRT se corre al
   offset actual de la emisión: si el stream arranca en el minuto 14, los
   subtítulos quemados corresponden al minuto 14 (antes quedaban
   desplazados).
3. **Watchdog de arranque: la señal va antes que los subtítulos.** Si un
   FFmpeg con subtítulos no emitió nada en 25 segundos, se retiran los
   subtítulos y se reinicia automáticamente, con aviso en el log. Nunca más
   un subtítulo puede dejar la transmisión muerta en silencio.
4. Si la película no tiene pista de subtítulos (o la extracción falla), la
   emisión continúa sin ellos y se avisa una sola vez.

**Probado con tu escenario exacto** (película en unidad de red + subtítulos
español activados al aire): la señal arranca viva, los subtítulos se activan
desde el SRT local, y aunque se simula un subtítulo que bloquea la salida,
el watchdog retira los subtítulos y recupera la emisión solo.

## Verificación

- 41/41 tests de continuidad v24 (nuevos: corrimiento de tiempos del SRT,
  caché local con sidecar/extracción, watchdog que retira subtítulos).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Smoke end-to-end del fallo de esta noche: activar subtítulos en red ya no
  corta el RTMP.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.38.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). No hay que
tocar ajustes: los subtítulos que activaste siguen en "spa" y ahora funcionan
sobre la biblioteca de red. La primera vez que cada película pase por la
extracción verás en el log «Subtítulos extraídos • reinicio breve para
activarlos»; después queda en caché.
