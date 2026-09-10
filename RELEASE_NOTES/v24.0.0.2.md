# TVPlayout PRO V24.0.0.2

## Consola de diagnóstico de reproducción

Hotfix para recopilar evidencia cuando QtMultimedia/QVideoWidget no muestra
el vídeo en el monitor local. No cambia el backend de reproducción nativo ni
la salida RTMP/FFmpeg.

### Cambios

- Se agregó **Consola Debug** visible desde Funciones, desde el indicador de
  registros y con **F12**.
- La consola permanece en vivo mientras se reproduce y permite filtrar por
  nivel, pausar la vista, copiar todo el contenido y guardar un diagnóstico
  de texto.
- El logger conserva hasta 10.000 líneas en memoria y registra DEBUG en el
  archivo `logs/tvplayout.log`.
- `INICIAR_CONSOLA.bat` activa `TVPLAYOUT_DEBUG=1`, `PYTHONUNBUFFERED=1` y
  muestra el mismo diagnóstico en la consola de Windows.
- `NativePlayer` registra generación, ruta absoluta, solicitud de play,
  `mediaStatus`, duración, posición (una vez por segundo), fin de media,
  pausa y errores de QtMultimedia.
- `PlayoutController` registra las solicitudes de playlist y las transiciones
  de fin/error; la ventana registra el estado que llega a la UI, plataforma,
  versión de Python y disponibilidad de binarios.

### Cómo obtener un diagnóstico

1. Iniciar con `INICIAR_CONSOLA.bat`.
2. Abrir **Funciones → Consola Debug** o pulsar **F12**.
3. Intentar reproducir el archivo que no muestra vídeo.
4. Pulsar **Guardar diagnóstico…** y enviar el `.txt` junto con
   `logs/tvplayout.log`.

### Verificación

- Compilación Python correcta.
- Integración estática: 29/29.
- Scheduler: 10/10.
- La ventana QtMultimedia real debe verificarse en Windows con PySide6 y los
  codecs/backend instalados.
