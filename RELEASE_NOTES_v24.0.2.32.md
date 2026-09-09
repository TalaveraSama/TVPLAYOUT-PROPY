# TVPlayout PRO V24.0.2.32

## Vista previa de biblioteca/playlist: mpv con VLC de reserva y avisos claros

### ¿Para qué sirve cada reproductor?
- **Monitor local (PyAV, integrado)**: lo que ves DENTRO de la app durante el playout. No necesita mpv ni VLC; también alimenta la salida NDI.
- **mpv**: abre las **vistas previas** (👁 Previsualizar en Biblioteca y en Playlist) en una ventana aparte, sin afectar el aire. También puede actuar como reproductor del monitor de programa FFmpeg.
- **VLC**: reproductor alternativo. Si mpv no está, **las vistas previas ahora se abren con VLC**; sigue disponible para el modo «Programa FFmpeg → reproductor externo».

### Mejoras
- **VLC como reserva de la vista previa**: si no hay mpv.exe, la vista previa se abre con VLC detectado automáticamente (instalación típica en `Program Files\VideoLAN\VLC`, PATH o `VLC_PATH` en `.env`).
- **Aviso claro cuando no hay reproductor**: antes, si faltaba mpv, el botón 👁 parecía no hacer nada (solo un mensaje fugaz en la barra de estado). Ahora sale un cuadro explicando dónde colocar mpv.exe o instalar VLC.
- **Confirmación visible**: al abrir la vista previa, la barra de estado muestra «👁 Preview abierto en mpv/VLC • archivo».
- **Verificación en la app**: Ajustes → Sistema muestra el estado de mpv y VLC; Dispositivos lista ambos binarios con su versión.

### Cómo comprobar que mpv funciona
1. Barra de estado al arrancar: «Preview mpv: OK» (o NO si falta).
2. Ajustes → Sistema: chip verde con la ruta de mpv (y de VLC).
3. Dispositivos: sección MPV con la versión.
4. En Biblioteca, selecciona una película y pulsa **👁 Previsualizar**: se abre la ventana de mpv con el archivo.

## Validación

- `python tests/test_v24_continuity.py` — 28/28 (nuevas: preferencia mpv→VLC en runtime con procesos reales de prueba, aviso claro sin reproductores y chips en Ajustes/Dispositivos)
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke headless (PySide6 offscreen): `preview_library` abre el reproductor de prueba y muestra la confirmación; sin reproductores aparece el cuadro de aviso.
