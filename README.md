# TVPlayout PRO V21

Nueva base de playout tipo broadcast inspirada en la distribución funcional de XPlayout, sin copiar código ni recursos propietarios.

## Arquitectura

- Biblioteca SQLite persistente.
- Escaneo recursivo de carpetas locales y UNC.
- MKV/MP4 y otros formatos habituales.
- Reproductor de preview/ON AIR basado en `mpv-x86_64`.
- Motor de salida basado en FFmpeg.
- Resoluciones: 1280x720, 1920x1080 y personalizada.
- FPS: 23.976, 24, 25, 29.97, 30, 50, 59.94, 60.
- Encoder: AUTO, CPU/x264, NVIDIA NVENC, Intel QSV, AMD AMF.
- Audio/subtítulos preferidos: es-MX, es-419, spa, es.
- Playlist persistente.
- Fuentes y categorías persistentes.
- Base preparada para Scheduler y Tandas.

## Dependencias

Instala:

    py -3.13 -m pip install -r requirements.txt

No incluye MPV ni FFmpeg.

Coloca:

    mpv-x86_64\mpv.exe
    ffmpeg.exe

La aplicación los busca automáticamente en la raíz del proyecto.

## Ejecución

    py -3.13 main.py

También puedes crear `.env` con:

    MPV_PATH=mpv-x86_64\\mpv.exe
    FFMPEG_PATH=ffmpeg.exe

La salida RTMP se configura desde Ajustes de salida.


## V20.1 Output Engine

La salida RTMP ya toma el primer elemento de la playlist (o el elemento seleccionado) y lo procesa con FFmpeg en tiempo real:
- escala al canvas elegido;
- adapta FPS;
- conserva audio y busca preferentemente pistas españolas;
- codifica con x264/NVENC/QSV/AMF según selección;
- envía H.264/AAC a RTMP.

Esta primera base todavía no hace transición frame-accurate entre eventos ni inserta tandas automáticamente. Esos son los siguientes módulos del motor de continuidad.


## Programador V20 — funcional

El Programador ya no es un módulo reservado. Guarda las reglas en SQLite y las ejecuta automáticamente:
- Diario: todos los días a una hora.
- Semanal: uno o varios días de lunes a domingo.
- Mensual: día 1–31.
- Trimestral: día del mes + mes 1/2/3 dentro de cada trimestre.
- Selección por categoría.
- Cantidad de medios por evento.
- Orden secuencial, aleatorio o recientes.
- Al dispararse una regla, reemplaza la playlist con los medios seleccionados y comienza el primero automáticamente.
- Cada ejecución queda marcada para evitar doble disparo dentro del mismo minuto.

La siguiente etapa será convertir la playlist programada en una continuidad 24/7 real, con siguiente evento precargado y tandas comerciales insertadas según reglas.


## V20.1 — RTMP corregido

Se corrigió el error que aparecía como `FFmpeg terminó (4294967274)`, equivalente a `-22` en Windows.
La causa era aplicar el preset `veryfast` de x264 al encoder NVIDIA NVENC. Ahora cada encoder recibe únicamente opciones compatibles:

- CPU/x264 → `veryfast`
- NVIDIA NVENC → `p5` + `hq`
- Intel QSV → `veryfast`
- AMD AMF → `balanced`

Antes de iniciar una salida se comprueba que el encoder exista en el FFmpeg seleccionado. `AUTO` intenta hardware disponible y finalmente CPU/x264.

## Programador V20.1

Las reglas se mantienen persistentes en SQLite y funcionan por reloj local:

- Diario: todos los días a la hora indicada.
- Semanal: uno o varios días de lunes a domingo.
- Mensual: día 1–31.
- Trimestral: día del mes + mes 1/2/3 de cada trimestre.
- Categoría, cantidad y orden secuencial/aleatorio/reciente.
- Protección contra doble ejecución en el mismo minuto.

El escáner V20 no se modifica en esta revisión.
