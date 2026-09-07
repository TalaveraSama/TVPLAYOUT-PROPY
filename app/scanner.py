"""Escaneo recursivo de carpetas locales y UNC hacia la biblioteca SQLite."""
import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .config import VIDEO_EXTS


class Scanner(QThread):
    found = Signal(str)
    progress = Signal(int, int, int)      # carpetas, archivos, medios
    finished_count = Signal(int, int)     # archivos, medios
    error = Signal(str)

    def __init__(self, db, sources, purge_missing=True):
        super().__init__()
        self.db = db
        self.sources = sources
        self.purge_missing = purge_missing
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def _handle(self, path, name, category):
        if Path(name).suffix.lower() in VIDEO_EXTS and not name.startswith("._"):
            title = Path(name).stem
            self.db.upsert_media(path, title, category)
            self.found.emit(title)
            return True
        return False

    def run(self):
        files = media = folders = 0
        seen_roots = []
        try:
            for src in self.sources:
                if self.stop_requested:
                    break
                root = src["path"]
                category = src["category"]
                recursive = bool(src["recursive"])
                if not os.path.isdir(root):
                    self.error.emit(f"No accesible: {root}")
                    continue
                seen_roots.append(os.path.normcase(os.path.abspath(root)))
                if recursive:
                    for base, dirs, names in os.walk(root):
                        if self.stop_requested:
                            break
                        dirs[:] = [d for d in dirs if not d.startswith((".", "$", "@"))]
                        folders += 1
                        for name in names:
                            if self.stop_requested:
                                break
                            files += 1
                            if self._handle(os.path.join(base, name), name, category):
                                media += 1
                        if folders % 5 == 0:
                            self.progress.emit(folders, files, media)
                else:
                    folders += 1
                    with os.scandir(root) as it:
                        for e in it:
                            if self.stop_requested:
                                break
                            if e.is_file():
                                files += 1
                                if self._handle(e.path, e.name, category):
                                    media += 1
                    self.progress.emit(folders, files, media)
            if self.purge_missing and not self.stop_requested and seen_roots:
                removed = self._purge_missing(seen_roots)
                if removed:
                    self.error.emit(f"Eliminados de la biblioteca {removed} archivos que ya no existen")
            self.progress.emit(folders, files, media)
            self.finished_count.emit(files, media)
        except Exception as e:  # noqa: BLE001
            self.error.emit(repr(e))
            self.finished_count.emit(files, media)

    def _purge_missing(self, roots):
        """Quita de la biblioteca archivos dentro de las fuentes escaneadas que ya no existen."""
        removed = 0
        for r in self.db.search_media("", "Todas", limit=10 ** 7):
            if self.stop_requested:
                break
            p = r["path"]
            np_ = os.path.normcase(os.path.abspath(p))
            if any(np_.startswith(root) for root in roots) and not os.path.isfile(p):
                self.db.delete_media(p)
                removed += 1
        return removed
