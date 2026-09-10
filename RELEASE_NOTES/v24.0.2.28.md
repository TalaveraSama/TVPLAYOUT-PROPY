# TVPlayout PRO V24.0.2.28

## Póster de la tarjeta TMDB totalmente editable + descripción más compacta

- **Póster editable completo** en la ventana Tarjeta TMDB (panel FUNCIONES), con vista previa en vivo:
  - **Tamaño del póster**: 40–160 % de la altura de la franja; con más de 100 % el póster sobresale de la franja (estilo overlay).
  - **Forma del póster**: **cuadrado** (nuevo diseño por defecto, con la descripción a su derecha), original 2:3 o panorámica 16:9; la imagen se recorta al centro para llenar la forma elegida.
- **Diseño por defecto renovado**: póster cuadrado a la altura completa de la franja con el título y la descripción a su derecha, como un bloque compacto.
- **Descripción más reducida**: la tipografía base del título y de la sinopsis bajó de tamaño para que el texto ocupe mucho menos; además se puede ajustar con **Tamaño del texto** (60–150 %).
- En el estilo **tarjeta compacta**, la caja redondeada crece junto con el póster cuando éste sobresale de la franja.
- Todos los ajustes se guardan y se aplican de inmediato al aire si hay una tarjeta activa.

## Validación

- `python tests/test_v24_continuity.py` — 20/20
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke test headless (PySide6 offscreen): póster cuadrado verificado por píxeles (bloque ancho==alto con la descripción a su derecha), sobresalida de la franja al 130 %, formas original/16:9, escala del texto y sin regresiones en posiciones/estilos.
