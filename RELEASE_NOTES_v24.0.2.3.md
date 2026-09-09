# TVPlayout PRO V24.0.2.3

## Salidas IP múltiples y configuración profesional

Esta versión toma como base estable `v24.0.2.2` y agrega distribución hacia
varios destinos RTMP, SRT y NDI.

### Salidas RTMP, SRT y NDI

Desde **Salidas IP · RTMP / SRT / NDI** se pueden crear perfiles como:

```text
OBS principal       RTMP   rtmp://servidor/app/clave
vMix estudio        SRT    srt://192.168.1.50:9000?mode=caller&latency=200000
NDI producción      NDI    TVPlayout PRO
```

- Cada perfil puede activarse o desactivarse individualmente.
- Cada destino utiliza un proceso FFmpeg independiente.
- Todos los destinos siguen el mismo evento, trim y reloj del playout local.
- Se conserva compatibilidad con la URL RTMP única de versiones anteriores.
- RTMP/SRT pueden recibirse en OBS y vMix mediante sus fuentes de stream.
- La cámara virtual de OBS sigue siendo una salida de OBS, no una entrada para
  TVPlayout.
- NDI directo necesita NDI Runtime y un `ffmpeg.exe` con el muxer
  `libndi_newtek`. Si el FFmpeg no lo tiene, RTMP y SRT continúan disponibles.

### Logo y áreas seguras

- La vista previa del logo muestra el lienzo 16:9 y el área 4:3 central.
- Las líneas amarillas marcan los límites `12.5%` y `87.5%`.
- La salida FFmpeg mantiene automáticamente el logo dentro del área 4:3.
- Tamaño profesional predeterminado: 10% del ancho.
- Margen predeterminado: 48 px en 1920x1080.

### Limpieza portable

- `build_exe.bat` elimina la carpeta `build\` al completar correctamente.
- No se conservan junto a la distribución los `.toc`, `.pyz`, `warn-*.txt` ni
  reportes temporales de PyInstaller.
- Si el build falla, `build\` se conserva para diagnóstico.

### Verificación

- Integración: 32/32.
- Scheduler: 10/10.
- Compilación Python y del spec: correcta.
