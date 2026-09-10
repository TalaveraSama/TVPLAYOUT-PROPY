# TVPlayout PRO V24.0.2.0

## Distribución portable profesional para Windows

Se refinó el empaquetado para que el programa se distribuya como una carpeta
portable completa, con el ejecutable y sus librerías en la raíz de la build.

### Cambios

- `build_exe.bat` crea un entorno aislado y genera una build PyInstaller
  **onedir** en `dist\\TVPlayoutPRO`.
- PySide6, PyAV/libav, plugins y DLL quedan en `_internal`, evitando el
  arranque frágil y la extracción temporal de una build onefile.
- El BAT copia `ffmpeg.exe`, `ffprobe.exe`, sus DLL vecinas y `mpv.exe` opcional
  al nivel de `TVPlayoutPRO.exe`.
- Se agregó `INICIAR_EXE.bat` y `LEEME_PORTABLE.txt` para la distribución.
- El ejecutable congelado usa su propia carpeta como raíz persistente; conserva
  `tvplayout.db`, `cache`, `logs` y `.env` junto al programa.
- `tvplayout.spec` recolecta submódulos de la aplicación y dependencias
  dinámicas de PyAV de forma explícita.
- La reproducción local sigue usando PyAV/libav; mpv continúa siendo opcional
  únicamente para preview externo.

### Contenido de la distribución

```text
TVPlayoutPRO\\
├── TVPlayoutPRO.exe
├── _internal\\
├── ffmpeg.exe
├── ffprobe.exe
├── mpv.exe (opcional)
└── INICIAR_EXE.bat
```

### Verificación

- Integración estática: 31/31.
- Scheduler: 10/10.
- Compilación Python correcta.
- La generación final del EXE debe ejecutarse en Windows x64.
