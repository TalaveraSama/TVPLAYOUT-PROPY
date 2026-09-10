# V24.0.2.41 — TMDB: adiós a los cientos de «no encontró» (consultas limpias)

## Qué pasaba

Desde los primeros logs del VPS vimos cientos de líneas así:

```
TMDB no encontró: 13 dias en el lago de la muerte 2025
TMDB no encontró: American Fiction 2023 1080p WEBRip x264 AAC5 1-[YTS MX]
TMDB no encontró: Heart Eyes 2025 1080p WEBRip x264 AAC5 1-[YTS MX]
```

Las búsquedas a TMDB llevaban **todo el nombre del archivo**: año, resolución,
códecs, audio y el grupo de release. Con esa basura dentro, TMDB no encontraba
nada y la ficha quedaba sin póster, ni descripción, ni año.

## Qué cambia en esta versión

1. **Consulta limpia.** Antes de buscar se filtra todo lo técnico:
   - Etiquetas de release: `1080p`, `4K`, `UHD`, `HDR`, `WEBRip`, `WEB-DL`,
     `BluRay`, `BRRip`, `DVDRip`, `x264/x265/H265`, `HEVC`, `AAC5 1`, `DDP5 1`,
     `DTS`, `Atmos`, `DUAL`, `LATINO`, `SUBTITULADO`, `REPACK`, `REMUX`…
   - Bloques `[YTS MX]`, `(2023)` y variantes con guiones (`H265-DUAL`).
2. **El año viaja aparte** (`year=2023`), que es como TMDB realmente filtra —
   mejora la precisión en vez de estorbar la búsqueda.
3. **Reintento sin año**: si el año del nombre de archivo está mal (re-edición,
   error de quien subió el archivo), se reintenta la búsqueda sin él antes de
   rendirse.
4. **Los títulos legítimos no se tocan**: «Destino Final 3» conserva su
   «Final», «Spider-Man» su guion, «1917» y «2012» su año-nombre (el año al
   inicio del título forma parte del título).

**Ejemplos reales de tu biblioteca:**

| Nombre de archivo | Consulta enviada | Año |
|---|---|---|
| American Fiction 2023 1080p WEBRip x264 AAC5 1-[YTS MX] | American Fiction | 2023 |
| 13 dias en el lago de la muerte 2025 | 13 dias en el lago de la muerte | 2025 |
| Kraven 2024 2160p WEB-DL DDP5 1 Atmos HDR H265-DUAL | Kraven | 2024 |
| La Huérfana 2009 1080p BluRay DD5 1 Latino [YTS] | La Huérfana | 2009 |

El buscador manual del editor TMDB también se beneficia: si escribes «Coco
2017», busca «Coco» con año 2017.

## Verificación

- 43/43 tests de continuidad v24 (nuevo: limpieza con los títulos reales que
  fallaban, año como parámetro, reintento sin año, títulos legítimos intactos;
  runtime con red simulada verificando la URL exacta que se envía).
- 41/41 tests de integración v22.1, 10/10 del programador, tests core OK.
- Instalador: `Setup_TVPlayoutPRO_V24.0.2.41.exe` (compilar con
  `installer\BUILD_INSTALLER.bat` — guía en BUILD.md).

## Cómo actualizar

Reemplaza la carpeta del programa (o compila el instalador). Para re-intentar
las fichas que quedaron sin datos: panel FUNCIONES → **TMDB: escanear
biblioteca** (con «forzar») o clic derecho → re-scan TMDB en los medios que
quieras.
