# V24.0.2.43 — Al reiniciar, lo emitido se conserva y la lista continúa por la HORA

## Qué pasaba

Al reiniciar el programa, la playlist restaurada volvía **todo a pendiente**:
lo ya emitido perdía su estado y la lista empezaba de nuevo desde el
principio (o desde el primer pendiente), repitiendo contenido ya salido al
aire.

## Qué cambia en esta versión

1. **Lo EMITIDO sobrevive al reinicio.** El estado de cada evento
   (EMITIDO / CORTADO / ERROR / OMITIDO) y su hora de salida al aire ahora se
   guardan con la playlist.
2. **Continuación por reloj.** Mientras la aplicación está abierta se guarda
   un pequeño snapshot del aire: qué evento está al aire, en qué posición y a
   qué hora. Al reiniciar, la aplicación avanza la línea de tiempo **el
   tiempo que estuvo cerrada**:
   - Lo que ya se emitió queda EMITIDO (no se repite nada).
   - Lo que debía emitirse mientras estaba cerrada queda EMITIDO.
   - La lista **continúa en el evento que corresponde a la hora actual**, con
     el offset exacto (ej.: cerraste al minuto 40 de una película y reinicias
     5 minutos después → continúa en el minuto 45 de esa película).
3. **Con «Poner AL AIRE automáticamente al abrir» activado**, el arranque
   retoma solo: mismo evento, offset calculado por reloj, salidas IP
   incluidas (si tienes «arrancar salidas» activo). Sin autoplay, la lista
   queda lista y el estado muestra «continúa en el evento N según la hora».

## Detalles que importan

- Si cerraste con un **STOP** deliberado, no se reanuda solo al abrir: los
  EMITIDO se conservan, pero el punto de reanudación se descarta (fue una
  decisión del operador, no un cierre).
- Si la playlist cambió entre sesiones (p. ej. el programador armó una lista
  nueva), el snapshot anterior se ignora automáticamente.
- El programador (SEMANA etc.) sigue funcionando igual: cuando dispara una
  programación nueva, arranca su lista desde cero; el mismo día, al reiniciar,
  conserva el avance.

## Verificación

- 45/45 tests de continuidad v24 (nuevo: cerrar a mitad del evento 2 →
  "reiniciar" 45 s después → eventos 1 y 2 EMITIDO, continúa en el evento 3
  con offset ~35 s; autoplay retoma en ese punto; estados persistidos para el
  siguiente arranque; STOP deliberado no se reanuda).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.43.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md; recuerda que puedes
  pasar tu mpv local como argumento).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Ajustes
recomendados en el VPS para continuidad 24/7 total:

- Ajustes → **«Restaurar la última playlist al abrir»** ✓ (activado)
- Ajustes → **«Poner AL AIRE automáticamente al abrir»** ✓
- Monitor de programa → **«Reloj del sistema»** (VPS)

Con esos tres, un reinicio del programa (o del Windows) vuelve al aire solo,
en el evento y minuto exactos que corresponde según la hora.
