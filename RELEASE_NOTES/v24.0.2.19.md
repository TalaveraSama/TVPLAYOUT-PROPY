# TVPlayout PRO V24.0.2.19

## Ventanas adaptables para laptop y TV

- La ventana principal calcula su tamaño inicial a partir del área visible del monitor y ya no queda bloqueada en 1280x720.
- Se reduce el tamaño mínimo para permitir trabajar con resoluciones lógicas reducidas por el escalado DPI de Windows/TV.
- La ventana principal tiene control de redimensionado y el panel derecho conserva una proporción útil en pantallas pequeñas.
- Ajustes, Playlist Manager, Fuentes, Programador y Registros pueden maximizarse y redimensionarse.
- Las páginas largas de Ajustes tienen scroll vertical para que los botones Guardar/Cancelar permanezcan accesibles en televisores de 768 píxeles o con escala 125/150%.
- Logo/CG, Salidas IP, Dispositivos y Editar clip también se adaptan al área visible.

## Validación

- `python tests/test_v24_continuity.py` — 15/15
- `python tests/test_v22_1_integration.py` — 41/41
- `python -m py_compile app/main_window.py app/dialogs.py app/dialogs_extra.py`
