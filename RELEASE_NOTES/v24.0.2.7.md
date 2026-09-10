# TVPlayout PRO V24.0.2.7

## Logo oculto durante publicidad

El logo/CG configurado ya no aparece durante los anuncios. La regla se aplica
al evento que está al aire, no al archivo original ni a la configuración global
del logo.

### Comportamiento

- Los eventos con categoría `Publicidad` salen sin logo.
- La comparación ignora mayúsculas y espacios.
- La categoría configurada para las tandas automáticas también se oculta.
- La regla se aplica a RTMP/SRT mediante FFmpeg y a NDI directo.
- Cada frame NDI recibe la decisión de logo correspondiente a su evento para
evitar arrastres de logo al cambiar de tanda.
- Las películas, series y demás categorías continúan mostrando el logo.
- El monitor local PyAV no recibe logo y no cambia su comportamiento.

### Validación

- `py_compile`: correcto.
- Integración: 40/40.
- Scheduler: 10/10.
- `git diff --check`: correcto.
