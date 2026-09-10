# TVPlayout PRO V24.0.2.1

## Edición de cortes más sencilla

Se refinó la interfaz de trim para que el operador no tenga que calcular la
posición absoluta del final del video.

### Uso

En **Editar clip** ahora se introducen directamente los segundos a eliminar:

```text
Recortar inicio: 5
Recortar final: 2
```

Para un video de 2:20, el resultado será automáticamente desde 00:05 hasta
02:18, con una duración efectiva de 2:13. Ya no es necesario escribir 138 como
posición final ni calcular la duración total.

### Cambios

- El diálogo muestra la duración original y la duración resultante.
- Se validan los valores para que siempre quede contenido reproducible.
- `Restablecer corte` deja ambos valores en cero y reproduce el archivo completo.
- El modelo interno continúa usando `mark_in`/`mark_out` absolutos para no
  romper playlists existentes ni las salidas PyAV y FFmpeg.
- El archivo original no se modifica.

### Verificación

- Integración estática: 31/31.
- Scheduler: 10/10.
- Compilación Python correcta.
