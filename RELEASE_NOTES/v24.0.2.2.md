# TVPlayout PRO V24.0.2.2

## Corrección del empaquetado PyInstaller en Windows

Se corrigió el error que detenía `build_exe.bat` con:

```text
NameError: name '__file__' is not defined
```

PyInstaller ejecuta el contenido del archivo `.spec` con `exec()` y no siempre
define `__file__`. El spec ahora usa `SPECPATH` y la raíz actual como fallback,
por lo que el build portable puede continuar correctamente.

### Verificación

- Integración estática: 31/31.
- Scheduler: 10/10.
- Compilación Python y del spec correctas.
- Build real pendiente de repetir en Windows con el BAT actualizado.
