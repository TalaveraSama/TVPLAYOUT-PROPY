# V24.0.2.36 — El corte de intro/final ahora corre SOLO tras cada escaneo

## Respuesta corta

Sí: las películas ya se recortan automáticamente al inicio y al final para
saltar los idents de **Netflix, HBO, Amazon Prime** y cualquier otra marca.
Desde esta versión ni siquiera hay que tocar el botón: **al terminar cada
escaneo de biblioteca, las películas nuevas se analizan y recortan solas** en
segundo plano.

## Cómo detecta los logos

Netflix, HBO, Amazon y compañía envuelven sus idents en **tramos de negro**
(negro → logo → negro → contenido). El auto-recorte analiza los primeros 90 s
y los últimos 120 s de cada película con el filtro `blackdetect` de FFmpeg:

- **Inicio**: corta desde el final del ÚLTIMO tramo negro de la cabecera —
  así se salta también el logo que queda entre negros (el «ta-dum» de Netflix,
  el ident de HBO, etc.).
- **Final**: corta en el primer tramo negro de la cola — se van los créditos
  de cierre y los idents/«made with» que ponen al final.

Las marcas se guardan en la biblioteca (`mark_in`/`mark_out`) y se aplican
solas al añadir la película a la playlist. **El archivo original nunca se
modifica.**

## Qué cambia en esta versión

1. **Pase automático post-escaneo.** Al terminar el análisis de metadatos
   (que ya corría solo tras escanear), la aplicación lanza el auto-recorte de
   las películas todavía sin analizar. Sin clics, para siempre.
2. **No re-analiza.** Cada película procesada queda marcada (`autotrim_done`),
   incluso cuando no había nada que cortar. El siguiente escaneo sólo toca las
   películas nuevas — importante con la biblioteca en unidad de red, donde
   cada análisis lee vídeo por la red.
3. **Ajuste configurable.** Nueva casilla en Ajustes → REPRODUCCIÓN /
   AUTOMATIZACIÓN: «Recortar intro/final de películas automáticamente tras
   escanear» (activada por defecto).
4. Los controles manuales siguen: **✂ Auto-recortar biblioteca** (panel
   FUNCIONES) para lanzarlo cuando quieras, y **✂ Auto-recortar selección…**
   (clic derecho en Biblioteca) para re-analizar archivos concretos aunque ya
   estuvieran marcados.

## Límite conocido (y su solución)

El detector se guía por los negros que envuelven los idents, que es el formato
estándar de Netflix/HBO/Amazon y de prácticamente todos los WebRip. Si algún
archivo arranca con el logo **directamente sobre la imagen** (sin negro
alrededor), no hay frontera detectable: ese caso se ajusta a mano en segundos
con **✎ Editar clip** (clic derecho en Biblioteca → definir inicio/fin).

## Verificación

- 37/37 tests de continuidad v24 (nuevo: el worker marca lo analizado y el
  pase automático sólo toma películas sin analizar; forzado re-analiza).
- 41/41 tests de integración v22.1, 10/10 del programador.
- Smoke end-to-end: película nueva → pase automático → `mark_in` 4.75 s /
  `mark_out` 3479.75 s → en la playlist reproduce 4.75 s → 3479.75 s
  (3475 s al aire en vez de 3600 s); segundo pase: 0 invocaciones a FFmpeg;
  ajuste desactivado: no arranca.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.36.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Descarga `Source code (zip)` de esta release, o el instalador compilado, y
reemplaza la carpeta del programa. Base de datos, biblioteca, marcas de
recorte y ajustes no se tocan.
