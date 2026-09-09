# TVPlayout PRO V24.0.2.2 — Consola de playout

Playout de televisión 24/7 para Windows con interfaz inspirada en la distribución de **XPlayout** (Axel Technology),
sin usar código ni recursos propietarios. Reproductor local **PyAV/libavcodec** + salida **RTMP/SRT/UDP** con **FFmpeg**.

![Panel principal](docs/panel.png)

## Distribución del panel

| Zona | Contenido |
|---|---|
| Cabecera | Título, resolución/fps de salida, reloj principal, fecha |
| Transporte | ▶ PLAY · ❚❚ PAUSA (solo local) · ■ STOP · ▶▏ SIGUIENTE · miniatura · nombre/ruta/formato del clip · barra de progreso · indicador **ON-AIR** |
| Contadores | CATEGORÍA · DURACIÓN · POSICIÓN · RESTANTE (naranja, rojo en los últimos 10 s) · RESTA PLAYLIST · DESFASE · CODEC · SIGUIENTE |
| Modos | Autofill · Tandas auto · Hora exacta · Loop · Autoscroll · Modo Automático/Manual |
| GRID MODE | Playlist con filas coloreadas por categoría: #, Día, Hora (estimada), Hora real, Duración, Categoría, Título, Estado, ⏰ hora fija, Archivo, Formato. Fila azul = AL AIRE, lila = LISTO (cue), gris = emitido |
| GRAPHIC MODE | La misma playlist con miniaturas |
| BIBLIOTECA | Buscador + filtro por categoría, añadir al final / tras el aire / en selección / emitir ahora |
| Botonera | Insertar archivo, Preparar, Editar clip (título, pistas y corte no destructivo), Subir/Bajar, Quitar, Limpiar emitidos, Ir al aire, Hora fija, Reiniciar estados, Duplicar, Vaciar, Previsualizar, Mezclar pendientes, Playlist Manager |
| Monitor | VU meter estéreo (dBFS) + vídeo PyAV/libavcodec pintado en Qt, volumen/mute **solo local**, aspecto |
| FUNCIONES | Playlist Manager · Biblioteca · Programador · Registros As-Run · Fuentes/Categorías · Ajustes del sistema · Escanear · Logo/CG (RTMP) · Dispositivos · 🚨 EMERGENCIA |
| SALIDA RTMP | URL, INICIAR/DETENER, estado (encoder, resolución, bitrate) |
| Reloj de estación | Anillo de 60 segundos + HH:MM / SS, bloqueo de consola, minimizar/salir |

Atajos: **F1** Play · **F2** Pausa · **F3** Stop · **F4** Siguiente · **F5** Preparar · **Supr** quitar · **Ctrl+↑/↓** mover ·
**Ctrl+F** buscar en biblioteca · **Ctrl+L** bloquear · **F11** pantalla completa. Doble clic en una fila = emitir ahora.
Se pueden **arrastrar archivos o carpetas** desde el Explorador a la grid.

## Continuidad

- **Automático**: al terminar un evento pasa al siguiente pendiente. **Manual**: se detiene y deja el siguiente en LISTO esperando PLAY.
- **Hora exacta**: los eventos con hora fija (⏰) cortan lo que esté al aire a su hora; la columna DESFASE muestra el retraso real.
- **Loop**: al acabar la playlist vuelve a empezar. **Autofill**: rellena con medios aleatorios de la categoría configurada.
- **Tandas auto**: inserta N anuncios (categoría Publicidad) después de cada evento que no sea publicidad.
- **Emergencia**: emite de inmediato el clip de emergencia configurado (se pide la primera vez).
- La playlist actual se guarda sola y se restaura al abrir; opción de **poner al aire automáticamente** e **iniciar RTMP** al arrancar.
- **As-Run log**: todo lo emitido queda registrado (inicio, fin, estado EMITIDO/CORTADO/ERROR) y se exporta a CSV.

## Salida RTMP

La salida sigue al playout local: cada vez que empieza un evento en PyAV, FFmpeg salta al mismo evento. Se emite clip por clip
sobre la misma URL (el servidor ve una reconexión breve entre clips). Encoders: AUTO (prueba NVENC → QSV → AMF → x264),
CPU/x264, NVIDIA NVENC, Intel QSV, AMD AMF. Audio AAC 48 kHz estéreo, pista de audio elegida por preferencia
(es-MX / es-419 / Latino / spa / es…). Opcional: quemar subtítulos preferidos y superponer un **logo PNG** (posición, tamaño,
opacidad). También acepta `srt://` y `udp://`.

## Instalación (Windows)

1. Instala **Python 3.13 x64** (o 3.11/3.12).
2. Ejecuta `INSTALL.bat` (crea `.venv` e instala PySide6 y PyAV/libav).
3. Copia `ffmpeg.exe` y `ffprobe.exe` en la raíz del proyecto (o en `ffmpeg\bin\`, `bin\`) para RTMP y análisis.
4. Coloca opcionalmente `assets\logo.png` y `assets\logo.ico` para la identidad visual.
5. Ejecuta `INICIAR.bat` (`INICIAR_CONSOLA.bat` para ver mensajes de depuración).

Opcional: archivo `.env` con `FFMPEG_PATH=...`, `FFPROBE_PATH=...`, `TVPLAYOUT_DB=...`. El monitor local usa PyAV/libav y no necesita mpv.

Primer uso: **Fuentes / Categorías** → añadir carpetas (locales o UNC) → **Escanear biblioteca**. Con ffprobe se analizan
duración, resolución, códecs, pistas de audio/subtítulos y se generan miniaturas (en `cache\thumbs`).

## Estructura

```
main.py                 punto de entrada
app/main_window.py      consola principal (layout XPlayout)
app/playout.py          controlador de continuidad (auto/manual, cue, hora fija, loop, autofill, tandas)
app/pyav_player.py       PyAV/libavcodec: decodificación local de vídeo/audio
app/mpv_player.py        legado no usado en el aire (solo compatibilidad)
app/output.py           motor RTMP/SRT/UDP con FFmpeg (sigue al playout local, logo, subtítulos)
app/prober.py           ffprobe: metadatos, pistas, miniaturas; selección de pista preferida
app/scanner.py          escaneo recursivo de fuentes
app/scheduler.py        programador diario/semanal/mensual/trimestral
app/db.py               SQLite: biblioteca, playlists, programaciones, ajustes, as-run
app/dialogs*.py         Playlist Manager, Fuentes, Programador, Registros, Ajustes, Logo, Dispositivos
app/widgets.py          reloj de estación, VU meter, superficie de vídeo, barra de progreso
app/theme.py            hoja de estilos oscura
tests/                  pruebas estáticas y de continuidad del playout
```

## Registro de cambios

### V24.0.2.2
- Se corrigió el build PyInstaller en Windows: los archivos `.spec` no dependen de `__file__`, que PyInstaller no define al ejecutar el spec.
- El empaquetado usa `SPECPATH` o la raíz actual del proyecto como ruta de análisis.

### V24.0.2.1
- La edición de cortes ahora pide segundos a quitar del inicio y del final: para eliminar 5 segundos iniciales y 2 finales se escriben simplemente `5` y `2`.
- El resultado efectivo se muestra en el diálogo y se conserva el corte no destructivo interno.

### V24.0.2.0
- Se agregaron cortes no destructivos por evento: mark-in/mark-out se guardan en la playlist y se aplican al monitor PyAV y a la salida FFmpeg.
- El archivo original nunca se modifica; el corte se realiza en tiempo de reproducción y el tiempo efectivo aparece en la playlist.

### V24.0.1.9
- Cortes no destructivos por evento con mark-in/mark-out, persistidos en SQLite, JSON y M3U8.
- PyAV y FFmpeg respetan el mismo segmento; el archivo fuente nunca se sobrescribe.

### V24.0.1.8
- RTMP ya no selecciona NVENC/QSV/AMF solo porque FFmpeg los liste: prueba el encoder y usa CPU/x264 si falta la GPU o el controlador.
- Si un encoder de hardware falla al iniciar, la salida reintenta el mismo evento con CPU/x264 en el mismo offset.

### V24.0.1.7
- Corrección del ruido constante del monitor local: se descarta el padding de alineación de FFmpeg antes de enviar PCM a QAudioSink.
- Se conserva el prebuffer local de seis segundos y la salida RTMP/SRT/UDP continúa independiente.

### V24.0.1.6
- Hotfix: buffer de audio del monitor local reducido para evitar atraso y desfase; la salida RTMP/FFmpeg permanece independiente.
- Rediseño completo de la interfaz al estilo XPlayout: cabecera con reloj, transporte, contadores, modos, grid coloreada,
  modo gráfico, biblioteca integrada, botonera, VU meter, monitor, funciones, salida RTMP y reloj de estación.
- Continuidad real: encadenado automático por eventos de fin de PyAV, modo manual con cue, hora fija, loop,
  autofill, tandas, emergencia, bloqueo de consola, as-run log.
- PyAV/libav decodifica vídeo y audio localmente; QAudioSink entrega PCM y VideoSurface pinta los frames.
- RTMP sincronizado con el playout local (mismo evento), logo PNG, subtítulos quemados opcionales, SRT/UDP.
- ffprobe en segundo plano: duración, formato, pistas, miniaturas. Filtro de audio español latino mejorado.
- Playlist Manager (guardar/cargar/renombrar/exportar/importar M3U/JSON), Fuentes con edición, Programador con próxima
  ejecución, Registros (as-run + sistema), Ajustes del sistema, Dispositivos.
- Ajustes persistentes en SQLite, restauración de playlist, arranque automático opcional.

### V21 / V20.x
- RTMP clip a clip, programador funcional, corrección de presets NVENC, playlist persistente (ver historial de git).
