# TVPlayout PRO V24.0.1.9

## Cortes no destructivos por evento

Se agregó trim real para clips de la playlist sin modificar ni generar una
copia del archivo original.

### Uso

En **Editar clip** aparecen los campos:

- **Inicio**: segundo donde comienza el evento.
- **Final**: segundo donde termina; `0` significa el final original.
- **Restablecer corte**: vuelve a reproducir el archivo completo.

El tiempo efectivo del corte se guarda con el evento y se refleja en la
playlist, en el cálculo de horarios y en el registro de emisión.

### Implementación

- Las marcas `mark_in`, `mark_out` y la duración original se guardan en SQLite.
- PyAV busca el inicio, prebufferiza desde el mark-in y termina en el mark-out.
- El audio también se recorta por muestras, sin reproducir audio fuera de los
  límites seleccionados.
- FFmpeg recibe el desplazamiento absoluto y `-t` para que RTMP/SRT/UDP respeten
  exactamente el mismo corte.
- M3U8 y JSON conservan las marcas cuando se exportan/importan.
- El archivo fuente nunca se escribe, reemplaza ni modifica.

### Verificación

- Integración estática: 30/30.
- Scheduler: 10/10.
- Compilación Python correcta.
- Persistencia SQLite de cortes verificada.
- Falta validación final en Windows con vídeo real y salida RTMP activa.
