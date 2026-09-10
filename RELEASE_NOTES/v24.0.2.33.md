# TVPlayout PRO V24.0.2.33

## NDI: cómo verificar que realmente está saliendo + tarjeta de prueba

### Nuevo: tarjeta de prueba con reloj (sin necesidad de reproducir nada)
Cuando activas **Salidas IP** con un destino NDI y el playout local no está reproduciendo, TVPlayout envía automáticamente una **tarjeta de prueba con barras de color, el nombre de la fuente y un reloj en vivo**. Así puedes confirmar en OBS, vMix o Studio Monitor que el NDI sale correctamente **antes** de poner cualquier película. Al reproducir algo, la tarjeta desaparece sola y sale la señal real; si el playout se detiene más de 30 segundos, la tarjeta vuelve.

### Nuevo: contador de frames en el monitor de salidas
El panel **Monitor de salidas** de la app muestra ahora, para cada destino NDI activo: **frames enviados** y el estado (**señal en vivo** / **tarjeta de prueba**). Si el contador sube, TVPlayout está emitiendo NDI — si el receptor no lo ve, el problema está en la red, el Runtime o el plugin.

## Guía de verificación paso a paso

1. **Runtime**: instala el **NDI Runtime x64** (gratis, [ndi.video/tools](https://ndi.video/tools)). En la app: **Dispositivos → NDI DIRECTO** debe decir OK con la ruta de la DLL. Si dice «no encontrado», el NDI nunca va a salir.
2. **Destino**: en **Salidas IP** agrega un destino **NDI** con nombre (p. ej. «TVPlayout PRO»), actívalo y cambia a **Salidas IP activas**. El estado debe decir **«NDI directo activo»**.
3. **Tarjeta de prueba**: sin reproducir nada, en 2–3 segundos el contador de frames del monitor de salidas empieza a subir con estado **«tarjeta de prueba»**.
4. **Studio Monitor** (viene con NDI Tools): ábrelo y selecciona tu fuente. Deberías ver las barras con el reloj avanzando.
5. **vMix**: Add Input → **NDI** → aparece tu fuente (NDI viene integrado en vMix).
6. **OBS**: ⚠️ **OBS NO trae NDI de fábrica** — instala el plugin **DistroAV** (antes «obs-ndi», gratis en obsproject.com → Plugins). Sin ese plugin, jamás vas a ver fuentes NDI en OBS.
7. **Si la fuente no aparece en ninguna app**: revisa que emisor y receptor estén en la **misma red/subred**, que el **firewall de Windows permita la aplicación y mDNS (UDP 5353)**, y desactiva VPN/adaptadores virtuales (confunden el descubrimiento de NDI).

El diálogo **Dispositivos** incluye ahora esta guía dentro de la app.

## Validación

- `python tests/test_v24_continuity.py` — 31/31 (nuevas: tarjeta de prueba generada correctamente, contadores y estadísticas en el monitor de salidas, guía en Dispositivos)
- `python tests/test_v22_1_integration.py` — 41/41
- `python tests/test_scheduler_v22_1.py` — 10/10
- `python tests/test_core.py` — todas las pruebas pasaron
- Smoke headless: lógica de la tarjeta (inmediata sin señal, cede ante playout, retoma a los 30 s, intervalo de 0,5 s), imagen 1280x720 válida, contador visible en la ventana real y aviso claro sin Runtime.
