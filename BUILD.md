# Generar ejecutable de TVPlayout PRO V24.0.0.1

## Camino rápido (recomendado)

Doble clic en `build_exe.bat`. El script:

1. Detecta Python 3.13 / 3.10.
2. Crea un entorno virtual `.venv-build` (no toca el `.venv` de runtime).
3. Instala PySide6 y PyInstaller dentro de ese venv.
4. Empaqueta todo en `dist\TVPlayoutPRO.exe`.
5. Copia `mpv.exe` y `ffmpeg.exe` al lado del .exe si están en sus
   ubicaciones estándar del proyecto (`mpv-x86_64\mpv.exe` y
   `ffmpeg\ffmpeg.exe` o `ffmpeg.exe` en la raíz).

Tiempo total: 5-10 minutos (depende de la conexión y la CPU).

## Requisitos

- **Python 3.10 o 3.13** instalado y en el PATH.
  - Descarga: https://www.python.org/downloads/
  - Al instalar, **tildar "Add Python to PATH"** (es la primera casilla
    del instalador, abajo del todo).
- **Windows 10/11 64 bits**.
- **~500 MB libres** en disco (el venv de build + el .exe final pesan).
- **Conexión a internet** en el momento del build (pip baja PySide6 y
  PyInstaller, pesan ~200 MB juntos).

## Camino manual (si el .bat falla)

```bat
py -3.13 -m venv .venv-build
.venv-build\Scripts\activate
pip install PySide6==6.7.* PyInstaller==6.*
pyinstaller --noconfirm --clean --windowed --onefile --name TVPlayoutPRO ^
    --collect-submodules app --collect-data app ^
    --hidden-import PySide6.QtSvg --hidden-import PySide6.QtMultimedia ^
    main.py
```

Después copiá `mpv.exe` y `ffmpeg.exe` al lado de
`dist\TVPlayoutPRO.exe`.

## Estructura final esperada

Una vez generado, la carpeta donde lo pongas tiene que verse así:

```
TVPLAYOUT-PROPY-22.2.3\
├── TVPlayoutPRO.exe          (el .exe generado, ~80-120 MB)
├── mpv.exe                    (binario externo, mismo de antes)
├── ffmpeg.exe                 (binario externo, mismo de antes)
├── tvplayout.db               (la base de datos, se crea sola al iniciar)
├── cache\                     (se crea sola)
└── logs\                      (se crea sola)
```

## Si algo falla

1. **"No se encontró Python"**: instalalo desde python.org, **tildá
   "Add Python to PATH"**, y reiniciá la consola.

2. **"Fallo la instalación de dependencias"**: probablemente sin
   internet o pip desactualizado. Probá:
   ```
   .venv-build\Scripts\python.exe -m pip install --upgrade pip
   .venv-build\Scripts\python.exe -m pip install PySide6==6.7.* PyInstaller==6.* --verbose
   ```

3. **"PyInstaller falló"**: leé el error completo. Lo más común es un
   módulo de la app que no se está recolectando. Reportá el error y
   ajustamos.

4. **El .exe arranca pero crashea**: abrí un CMD y ejecutá
   `TVPlayoutPRO.exe` desde ahí (sin doble clic) para ver la traza
   completa. Después mandame el error.

5. **"No se encontró mpv.exe" o "No se encontró ffmpeg.exe"**: la
   consola principal los busca en subcarpetas estándar. Si no los
   tenés, descargalos:
   - mpv: https://mpv.io/installation/ (Windows: build de shinchiro o
     zhongfly)
   - ffmpeg: https://ffmpeg.org/download.html#build-windows (cualquier
     build gpl/shared sirve)

## Desinstalar el venv de build

```
rmdir /s /q .venv-build
```

No afecta al runtime.
