"""Auto-recorte de biblioteca: detecta intro y final de cada película.

El ident del inicio (p. ej. el «Netflix» de las capturas) y el remate final
quedan envueltos en tramos de negro: se analiza el principio y el final del
archivo con el filtro ``blackdetect`` de FFmpeg y se recorta…

- al inicio: desde el final del ÚLTIMO tramo negro de la cabecera (así se
  salta también el logotipo que queda entre negros), y
- al final: hasta el primer tramo negro de la cola.

Las marcas se guardan en la biblioteca (media.mark_in / media.mark_out) y se
aplican solas cuando el medio se añade a la playlist. El archivo original
nunca se modifica.
"""
import re
import subprocess

from PySide6.QtCore import QThread, Signal

# Ventanas de análisis y umbrales del recorte automático.
HEAD_WINDOW = 90.0     # segundos analizados al inicio
TAIL_WINDOW = 120.0    # segundos analizados al final
MIN_BLACK = 0.6        # duración mínima de un tramo negro para contar
MARGIN = 0.25          # colchón para no morder el primer/último fotograma
MIN_CUT_IN = 0.5       # no cortar arranques menores a esto
MIN_CUT_OUT = 1.0      # no cortar finales menores a esto
MIN_KEEP = 60.0        # conservar al menos un minuto de película

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_BLACK_RE = re.compile(
    r"black_start:\s*(\d+(?:\.\d+)?)\s+black_end:\s*(\d+(?:\.\d+)?)\s+black_duration:\s*(\d+(?:\.\d+)?)"
)


def parse_blackdetect(text):
    """Extrae los tramos negros del stderr de ffmpeg blackdetect → [(ini, fin)]."""
    out = []
    for match in _BLACK_RE.finditer(text or ""):
        start, end = float(match.group(1)), float(match.group(2))
        if end > start:
            out.append((start, end))
    return out


def compute_marks(duration, head_blacks=(), tail_blacks=(),
                  head_window=None, tail_window=None,
                  margin=None, min_cut_in=None, min_cut_out=None, min_keep=None):
    """Lógica pura del recorte: devuelve (mark_in, mark_out) en segundos.

    ``mark_in`` = final del último negro de la cabecera + margen.
    ``mark_out`` = inicio del primer negro de la cola − margen (0 = sin corte).
    Sólo se corta si queda al menos ``min_keep`` de película y el corte supera
    el mínimo correspondiente.
    """
    head_window = HEAD_WINDOW if head_window is None else head_window
    tail_window = TAIL_WINDOW if tail_window is None else tail_window
    margin = MARGIN if margin is None else margin
    min_cut_in = MIN_CUT_IN if min_cut_in is None else min_cut_in
    min_cut_out = MIN_CUT_OUT if min_cut_out is None else min_cut_out
    min_keep = MIN_KEEP if min_keep is None else min_keep
    try:
        duration = max(0.0, float(duration or 0))
    except (TypeError, ValueError):
        duration = 0.0

    # Defensa en profundidad: ignorar micro-negros aunque el detector no
    # hubiera filtrado por duración mínima.
    head_blacks = [(s, e) for s, e in (head_blacks or ()) if (e - s) >= MIN_BLACK]
    tail_blacks = [(s, e) for s, e in (tail_blacks or ()) if (e - s) >= MIN_BLACK]

    mark_in = 0.0
    ends = [e for s, e in head_blacks if e <= head_window + 1.0]
    if ends:
        candidate = max(ends) + margin
        if candidate >= min_cut_in and (duration <= 0 or duration - candidate >= min_keep):
            mark_in = round(candidate, 3)

    mark_out = 0.0
    if duration > 0:
        allowed_from = max(0.0, duration - tail_window - 1.0)
        starts = [s for s, e in tail_blacks if s >= allowed_from and e <= duration + 1.0]
        if starts:
            cut = min(starts) - margin
            if (duration - cut) >= min_cut_out and (cut - mark_in) >= min_keep:
                mark_out = round(cut, 3)
    return mark_in, mark_out


class AutoTrimWorker(QThread):
    """Recorre la biblioteca en segundo plano aplicando el auto-recorte."""

    progress = Signal(int, int, str)          # procesadas, total, título actual
    item_done = Signal(str, float, float, bool)  # path, mark_in, mark_out, cambió
    finished_all = Signal(int, int)           # procesadas, recortadas

    def __init__(self, db, ffmpeg_path, rows, force=False, parent=None):
        super().__init__(parent)
        self.db = db
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.rows = list(rows or [])
        self.force = bool(force)
        self._stop = False

    def stop(self):
        self._stop = True

    # ------------------------------------------------------------- detección
    def _detect(self, path, seek, window):
        cmd = [self.ffmpeg_path, "-hide_banner", "-nostats", "-loglevel", "info",
               "-ss", f"{max(0.0, seek):.3f}"]
        if window:
            cmd += ["-t", f"{float(window):.3f}"]
        cmd += ["-i", path, "-vf", f"blackdetect=d={MIN_BLACK}:pic_th=0.97:pix_th=0.10",
                "-an", "-sn", "-dn", "-f", "null", "-"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=180, creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            return []
        return parse_blackdetect(proc.stderr or "")

    # ------------------------------------------------------------------ run
    def run(self):
        processed = trimmed = 0
        total = len(self.rows)
        for row in self.rows:
            if self._stop:
                break
            path = str(row["path"] or "")
            try:
                duration = float(row["duration"] or 0)
            except (TypeError, ValueError):
                duration = 0.0
            if not path or duration <= 0:
                continue
            existing_in = float(row["mark_in"] or 0) if "mark_in" in row.keys() else 0.0
            existing_out = float(row["mark_out"] or 0) if "mark_out" in row.keys() else 0.0
            if not self.force and (existing_in > 0 or existing_out > 0):
                processed += 1  # ya tiene recortes: no se re-analiza
                self.progress.emit(processed, total, str(row["title"] or path))
                continue
            head_blacks = self._detect(path, 0.0, HEAD_WINDOW)
            tail_seek = max(0.0, duration - TAIL_WINDOW)
            tail_blacks = [(s + tail_seek, e + tail_seek) for s, e in self._detect(path, tail_seek, 0)]
            mark_in, mark_out = compute_marks(duration, head_blacks, tail_blacks)
            changed = (abs(mark_in - existing_in) > 0.001) or (abs(mark_out - existing_out) > 0.001)
            if changed:
                self.db.update_media_meta(path, mark_in=mark_in, mark_out=mark_out)
                trimmed += 1
            processed += 1
            self.item_done.emit(path, mark_in, mark_out, changed)
            self.progress.emit(processed, total, str(row["title"] or path))
        self.finished_all.emit(processed, trimmed)
