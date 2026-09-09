# TVPlayout PRO V24.0.2.9

## Inicio automático de perfiles activos

Se completó el flujo de activación por perfil introducido en v24.0.2.8.

- Si se guarda un destino como activo antes de cargar la playlist, se inicia
  automáticamente cuando el primer evento entra al aire.
- La pantalla principal continúa siendo únicamente un monitor.
- La casilla **Destino activo** del diálogo de salidas sigue controlando la
  participación de cada perfil.

### Validación

- `py_compile`: correcto.
- Integración: 41/41.
- Scheduler: 10/10.
- `git diff --check`: correcto.
