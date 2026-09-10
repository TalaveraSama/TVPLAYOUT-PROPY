# V24.0.2.37 — Fin de los cortes RTMP en el VPS + NDI deshabilitado temporalmente

## Qué decía tu log de esta noche (23:05)

```
23:27:04  RTMP en vivo • mpv=1.67s, ffmpeg=2.23s, gap de arranque -0.56s
23:27:22  RTMP drift 7.28s (mpv=13.15s, ffmpeg=20.98s) — realineando
23:27:48  RTMP drift 7.23s (mpv=30.04s, ffmpeg=38.60s) — realineando
23:28:14  RTMP drift 6.97s (…) — realineando        ← cada ~25 s, sin fin
```

La medición de la v24.0.2.35 funcionó (ya se ve la posición real de FFmpeg), y
el número revelador apareció: **mpv=13.15 s a los 23 s reales** — el monitor
local (PyAV) de tu VPS decodifica a **~66% de tiempo real** (201 s de película
en 303 s reales) porque el CPU no da para más. El RTMP con AMF, en cambio,
lee el archivo directamente y va al **100%**.

Resultado: la salida iba "adelantada" al reloj del playout, el vigilante la
interpretó como desincronización y la **reiniciaba hacia atrás cada ~25 s**.
Cada reinicio = un corte en la transmisión. La señal estaba sana; el que iba
atrasado era el monitor local.

## Qué corrige esta versión

### 1. La salida adelantada NUNCA se reinicia (guard direccional)

El vigilante ahora mide el drift **con signo**:

- **Salida por DETRÁS** del playout (señal atrasada de verdad): se realinea
  como antes, una sola vez.
- **Salida por DELANTE** del playout (monitor local lento): **la señal RTMP
  está sana a 1x y no se toca**. Se avisa una sola vez por clip:
  «Monitor local más lento que la señal • la emisión RTMP sigue en tiempo real
  y no se corta».

En la prueba que reproduce tu log exacto (monitor al 66%, salida al 100%):
**0 reinicios en 30 s** — antes era 1 corte cada ~25 s.

### 2. Nuevo modo de monitor: «Reloj del sistema» — la cura para tu VPS

Ajustes → Monitor de programa → **«Reloj del sistema (sin decodificar — ideal
VPS)»**. Con este modo:

- **PyAV deja de decodificar localmente** (ese era el consumo de CPU que
  atrasaba todo el reloj de la emisión). Sólo FFmpeg decodifica, una vez, para
  las salidas IP.
- El playout avanza con el **reloj de pared a 1x exacto**: películas, tandas
  intermedias y avances de evento se disparan a su hora real.
- El monitor de programa muestra «RELOJ DEL SISTEMA» en vez del vídeo (en un
  VPS sin pantalla nadie lo mira; la señal que importa es la del RTMP).

Con este modo activo, RTMP y playout van los dos a 1x: el drift queda en ~0 y
no hay nada que realinear. **Actívalo en tu VPS.**

### 3. NDI deshabilitado temporalmente (a tu pedido)

- Nueva casilla en Ajustes: **«Deshabilitar salidas NDI temporalmente (dejar
  solo RTMP y SRT)»** — **activada por defecto**.
- Los destinos NDI no arrancan mientras esté marcada; quedan solo RTMP y SRT.
- Los diálogos de Salidas IP y Dispositivos ya no prueban la DLL de NDI (tu
  VPS no tiene el NDI Runtime y el reintento llenaba el log de
  «Processing.NDI.Lib.x64.dll no encontrado»).
- Cuando quieras NDI de vuelta: desmarca la casilla y reinicia las salidas.

## Verificación

- 39/39 tests de continuidad v24 (nuevos: guard direccional con el caso exacto
  del VPS, modo Reloj con avance por reloj/pausa/seek, filtrado de destinos
  NDI).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Smoke end-to-end con tu escenario: monitor al 66% + salida al 100% →
  0 reinicios y aviso único; modo Reloj → evento de 6 s avanza solo a los 6 s
  exactos por reloj de pared; destino NDI omitido con la casilla activada.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.37.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

1. Descarga `Source code (zip)` de esta release (o compila el instalador) y
   reemplaza la carpeta del programa.
2. En el VPS: Ajustes → Monitor de programa → **Reloj del sistema** →
   guardar → reiniciar las salidas.
3. Verifica en el log: debería aparecer «RELOJ DEL SISTEMA» y ya no haber
   realineaciones.

Base de datos, biblioteca, marcas de recorte y ajustes no se tocan.
