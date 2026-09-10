# TVPlayout PRO V24.0.2.25

## Tarjeta TMDB con posición y estilo configurables (con vista previa)

- Nueva ventana **Tarjeta TMDB** en el panel FUNCIONES, junto a Logo / CG, para editar cómo se ven las imágenes TMDB al aire.
- **Vista previa exacta**: el diálogo renderiza la tarjeta con el mismo código que la salida al aire (RTMP/SRT/NDI y monitor), dentro de un lienzo 16:9 con guías del área segura 4:3 (12.5% — 87.5%), igual que la vista previa del logo.
- Opciones configurables, todas con actualización en vivo de la vista previa:
  - **Posición**: arriba o abajo.
  - **Alineación**: izquierda, centro o derecha (en la alineación derecha el póster queda en el extremo derecho y el texto alineado a la derecha).
  - **Estilo**: banda completa a lo ancho (clásico) o tarjeta compacta redondeada con borde sutil.
  - **Opacidad** del fondo (0–100 %) para garantizar la lectura del texto sobre cualquier vídeo.
  - **Margen** en px de referencia a 1080p, escalado automáticamente a cualquier resolución de salida.
- La muestra de la vista previa se toma de las películas reales de la biblioteca con ficha TMDB (botón ↻ para rotar); si no hay ninguna, se dibuja una muestra sintética con póster, backdrop, título y sinopsis.
- Al guardar, si hay una película con tarjeta activa, el nuevo layout se **aplica inmediatamente al aire**; si no, queda guardado para la próxima.
- Todo el render es proporcional a la resolución de salida: la misma tarjeta se ve idéntica en 1080p, 720p o la resolución configurada.
- La nota de Ajustes ahora indica que la posición de la tarjeta se administra desde esta ventana.

## Validación

- `python tests/test_v24_continuity.py` — 19/19
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): render en 1920x1080 y 480x270 con las 12 combinaciones de layout y verificación de píxeles (banda arriba/abajo, tarjeta compacta, alineaciones).
