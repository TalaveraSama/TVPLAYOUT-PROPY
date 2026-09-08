# TVPlayout PRO V24.0.0.1

## Corrección de continuidad del reproductor

Esta versión corrige el problema por el que el primer clip se reproducía,
pero la playlist no avanzaba correctamente al siguiente evento.

### Cambios principales

- El encadenado automático usa `end-file` como evento principal.
- Se agregó un respaldo con `idle-active` para builds de mpv que no entregan
  correctamente el evento de fin de archivo.
- Se agregó protección durante `loadfile replace` para ignorar eventos atrasados
  del clip anterior y evitar saltos o cortes prematuros del clip nuevo.
- Se limpian posición y duración entre cambios de archivo para evitar que el
  siguiente evento herede la metadata del anterior.
- Se fuerza la salida de pausa al iniciar cada nuevo clip.
- El filler/slate ahora respeta correctamente `filler_enabled`.
- El monitor muestra el filler como vídeo activo y no como "SIN SEÑAL".
- Se actualizó la versión visible de la aplicación, scripts de inicio,
  instalador, documentación de build y especificación de PyInstaller.

### Verificación

- Compilación Python correcta.
- Scheduler: 10/10 pruebas correctas.
- Integración: 27/27 pruebas correctas.
- Simulación de continuidad: clip 1 → clip 2 → clip 3.

## Instalación

Reemplazar la versión anterior conservando la base de datos y los archivos
multimedia. El ejecutable debe ejecutarse junto a `mpv.exe` y `ffmpeg.exe`.

Tag de release: `v24.0.0.1`
