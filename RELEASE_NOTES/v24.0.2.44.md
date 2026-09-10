# V24.0.2.44 — El auto-recorte ya no compite con la emisión al aire

## Qué decía tu log de hoy (12:43, V24.0.2.42)

Nada de publicidad — eran tres avisos distintos:

**1) `Auto-recorte iniciado (1500 película(s) nueva(s))` a las 13:12.** El
cortador de intro/final (el de los logos de Netflix/HBO que corre solo tras
cada escaneo, v24.0.2.36) arrancó para las **1500 películas nuevas** de la
biblioteca mientras estabas AL AIRE. Cada detección lee la película por la
unidad de red Z: — y compite con el FFmpeg de la salida por el mismo canal.

**2) `Resumed reading at pts … after a lag of 0.3–1.8s`** cada pocos minutos
desde las 13:16. Efecto de lo anterior: el hilo de entrada del RTMP se
atrasaba un instante por la red compartida y **se recuperaba solo** (rate
1.05). La señal nunca se cortó, pero el log se llenaba de avisos.

**3) `extracción de subtítulos vacía o con error (código 4294967274)` a las
12:43:47.** La extracción de subtítulos de la película falló una vez (leer el
MKV de 3 GB por red con el RTMP y el monitor leyéndolo a la vez) y el sistema
hizo exactamente lo diseñado: **la señal siguió sin subtítulos y sin cortes**.
El único defecto: ese único fallo descartaba los subtítulos de esa película
para toda la sesión.

## Qué cambia en esta versión

1. **Auto-recorte amable con la emisión**: mientras haya señal al aire, la
   pausa entre archivos pasa de 1.5 s a **5 s** (y las detecciones corren con
   prioridad baja en Windows). Sin emisión, sigue a máxima velocidad. La
   primera pasada sobre una biblioteca grande (1500 películas) tardará más en
   segundo plano, pero **no roba ancho de banda a la salida** — y sólo pasa
   una vez: después, cada escaneo sólo toca las películas nuevas.
2. **Subtítulos con reintento**: un fallo transitorio (red saturada un
   momento) ya no descarta la película para toda la sesión: se reintenta
   (hasta 2 intentos) y al triunfar el contador se reinicia. Todo con
   prioridad baja y sin tocar la señal, como antes.
3. **Menos ruido en el log**: las líneas `Resumed reading …` (recuperación
   automática del hilo de entrada) dejan de inundar el log de la interfaz —
   se registran en el archivo a nivel debug. Las pausas mayores del
   auto-recorte reducen además su frecuencia de raíz.

## Verificación

- 46/46 tests de continuidad v24 (nuevo: pausa de 5 s con emisión al aire y
  de 1.5 s sin ella; reintento de subtítulos tras 1 fallo y bloqueo tras 2;
  prioridad baja; «Resumed reading» demovido).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.44.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — acepta tu mpv local como argumento).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Sin cambios de
ajustes. Nota: esta versión incluye la V24.0.2.43 (continuidad al reiniciar
por reloj) que aún no tenías instalada — al actualizar la recibes junto con
esta.
