import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .config import VIDEO_EXTS

class Scanner(QThread):
    found = Signal(str)
    progress = Signal(int, int, int)
    finished_count = Signal(int, int)
    error = Signal(str)

    def __init__(self, db, sources):
        super().__init__()
        self.db=db
        self.sources=sources
        self.stop_requested=False

    def stop(self):
        self.stop_requested=True

    def run(self):
        files=0
        media=0
        folders=0
        try:
            for src in self.sources:
                if self.stop_requested: break
                root=src["path"]
                category=src["category"]
                recursive=bool(src["recursive"])
                if not os.path.isdir(root):
                    self.error.emit(f"No accesible: {root}")
                    continue
                if recursive:
                    walker=os.walk(root)
                    for base, dirs, names in walker:
                        if self.stop_requested: break
                        folders += 1
                        for name in names:
                            if self.stop_requested: break
                            files += 1
                            p=os.path.join(base,name)
                            if Path(name).suffix.lower() in VIDEO_EXTS:
                                title=Path(name).stem
                                self.db.upsert_media(p,title,category)
                                media += 1
                                self.found.emit(title)
                        if folders % 5 == 0:
                            self.progress.emit(folders,files,media)
                else:
                    with os.scandir(root) as it:
                        for e in it:
                            if self.stop_requested: break
                            if e.is_file():
                                files += 1
                                if Path(e.name).suffix.lower() in VIDEO_EXTS:
                                    self.db.upsert_media(e.path,Path(e.name).stem,category)
                                    media += 1
                                    self.found.emit(Path(e.name).stem)
            self.progress.emit(folders,files,media)
            self.finished_count.emit(files,media)
        except Exception as e:
            self.error.emit(repr(e))
            self.finished_count.emit(files,media)
