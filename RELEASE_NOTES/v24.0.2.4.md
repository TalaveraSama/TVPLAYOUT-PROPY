# TVPlayout PRO V24.0.2.4

## Corrección de NDI

El error del release anterior era:

```text
Requested output format 'libndi_newtek' is not known
```

NDI Runtime instalado en Windows no agrega el muxer a un `ffmpeg.exe` genérico.
El FFmpeg debe haber sido compilado con soporte NDI.

### Cambios

- El programa comprueba el muxer `libndi_newtek` antes de lanzar una salida NDI.
- Si no está disponible, muestra un error claro y no entra en reintentos infinitos.
- La salida NDI ya no intenta hacer fallback incorrecto de NVENC a CPU/x264.
- Se puede colocar una build especial como `ffmpeg-ndi.exe`; RTMP y SRT siguen
  usando el `ffmpeg.exe` normal.
- El build portable copia `ffmpeg-ndi.exe` y sus DLL vecinas si existe.
- El panel Dispositivos muestra el estado de `ffmpeg-ndi` y del muxer NDI.
- Se corrigió la estructura interna del diálogo de Logo / CG.

### Requisito NDI

Coloca en la raíz del proyecto o distribución:

```text
ffmpeg-ndi.exe
```

y verifica:

```bat
ffmpeg-ndi.exe -hide_banner -muxers | findstr libndi_newtek
```

Debe aparecer `libndi_newtek`. Instalar solamente NDI Runtime no es suficiente.

### Verificación

- Integración: 32/32.
- Scheduler: 10/10.
- Compilación Python y del spec: correcta.
