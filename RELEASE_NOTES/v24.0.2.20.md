# TVPlayout PRO V24.0.2.20

## Hotfix de inicio

- Se corrige el error `AttributeError: 'MainWindow' object has no attribute 'setSizeGripEnabled'`.
- El control de redimensionado se configura correctamente en la barra de estado de `QMainWindow`.
- Se conserva el comportamiento adaptable de ventanas y diálogos de v24.0.2.19.

## Validación

- `python tests/test_v24_continuity.py` — 15/15
- `python tests/test_v22_1_integration.py` — 41/41
- `python -m py_compile app/main_window.py app/dialogs.py app/dialogs_extra.py`
