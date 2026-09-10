# TVPlayout PRO V24.0.2.8

## Monitor de salidas y activación por perfil

Se reorganizó la operación de salidas IP para que la configuración se haga en
un único lugar y la pantalla principal quede dedicada al monitoreo.

### Cambios

- El diálogo **Salidas IP / RTMP / SRT / NDI** conserva la casilla **Destino
  activo** para cada perfil.
- Un perfil desactivado permanece guardado, pero no participa en la emisión.
- Al guardar perfiles activos se inicia la salida configurada.
- Al guardar todos los perfiles desactivados se detienen las salidas.
- La pantalla principal ya no muestra el editor de URL/nombre ni los radios de
  modo local/remoto.
- El panel principal muestra un monitor con destinos, protocolo, cantidad de
  perfiles activos, estado emitiendo/detenido y mensajes del sender/FFmpeg.
- RTMP/SRT/NDI conservan sus workers y emisores independientes.

### Validación

- `py_compile`: correcto.
- Integración: 41/41.
- Scheduler: 10/10.
- `git diff --check`: correcto.
