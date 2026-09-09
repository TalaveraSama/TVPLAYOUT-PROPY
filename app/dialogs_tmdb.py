"""Ventana de edición de la ficha TMDB: buscador por título y galería de imágenes.

Permite corregir la ficha de cualquier medio de la biblioteca: buscar el
título en TMDB, elegir el resultado correcto entre varios candidatos y
seleccionar el póster y el backdrop que se guardarán de la galería completa
de la película (no sólo la imagen principal que devuelve la búsqueda).
"""
import os

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .config import APP_VERSION
from .tmdb import TMDBImagesWorker, TMDBSearchWorker


class TMDBEditDialog(QDialog):
    """Busca una película en TMDB y deja elegir póster/backdrop de su galería."""

    def __init__(self, parent, media, api_key):
        super().__init__(parent)
        self.setWindowTitle(f"Editar ficha TMDB — TVPlayout PRO {APP_VERSION}")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 1080, 640
        if available is not None:
            width = min(int(width), max(760, available.width() - 32))
            height = min(int(height), max(480, available.height() - 56))
        self.resize(max(760, int(width)), max(480, int(height)))
        self.setMinimumSize(760, 480)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        self.media = dict(media or {})
        self.api_key = str(api_key or "").strip()
        self._search_worker = None
        self._images_worker = None
        self._results = []
        self._movie = None
        self._posters = []
        self._backdrops = []
        self._chosen = {"poster": "", "backdrop": ""}
        self._gallery_request = 0
        self._meta = {}
        self._clear = False

        root = QVBoxLayout(self)
        info = QLabel(f"<b>{self.media.get('title') or 'Medio sin título'}</b><br>"
                      f"<span style='color:#9a9a9a;'>{self.media.get('path') or ''}</span>")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(info)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Título exacto para buscar en TMDB…")
        self.query.returnPressed.connect(self._search)
        self.query.setText(str(self.media.get("tmdb_title") or self.media.get("title") or ""))
        search_row.addWidget(self.query, 1)
        self.search_btn = QPushButton("🔎 Buscar en TMDB")
        self.search_btn.clicked.connect(self._search)
        search_row.addWidget(self.search_btn)
        root.addLayout(search_row)

        self.status = QLabel("Escribe un título y pulsa Buscar, o elige un resultado.")
        self.status.setStyleSheet("color:#9a9a9a;")
        root.addWidget(self.status)

        body = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self._section("RESULTADOS"))
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setIconSize(QSize(72, 108))
        self.results.setGridSize(QSize(92, 148))
        self.results.setResizeMode(QListWidget.Adjust)
        self.results.setMovement(QListWidget.Static)
        self.results.setSelectionMode(QListWidget.SingleSelection)
        self.results.setWordWrap(True)
        self.results.currentRowChanged.connect(self._pick_result)
        lv.addWidget(self.results, 1)
        body.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.movie_lbl = QLabel("Sin película seleccionada")
        self.movie_lbl.setWordWrap(True)
        self.movie_lbl.setStyleSheet("color:#79d6ff;")
        self.movie_lbl.setMinimumHeight(64)
        rv.addWidget(self.movie_lbl)

        gal = QHBoxLayout()
        gal.setSpacing(8)
        gal.addWidget(self._gallery_panel("PÓSTER", "poster", 96, 144, 116, 172))
        gal.addWidget(self._gallery_panel("BACKDROP", "backdrop", 208, 117, 232, 152))
        rv.addLayout(gal, 1)
        body.addWidget(right)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([300, 720])
        root.addWidget(body, 1)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("💾 Guardar ficha e imágenes")
        self.save_btn.setObjectName("primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        buttons.addWidget(self.save_btn)
        clear_btn = QPushButton("🗑 Quitar ficha TMDB")
        clear_btn.clicked.connect(self._clear_ficha)
        buttons.addWidget(clear_btn)
        buttons.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        if self.query.text().strip():
            QTimer.singleShot(200, self._search)

    # ------------------------------------------------------------------- UI
    @staticmethod
    def _section(title):
        lbl = QLabel(title)
        lbl.setObjectName("sectionTitle")
        return lbl

    def _make_gallery(self, icon_w, icon_h, grid_w, grid_h):
        """Lista tipo galería (IconMode) para pósters o backdrops."""
        lst = QListWidget()
        lst.setViewMode(QListWidget.IconMode)
        lst.setIconSize(QSize(icon_w, icon_h))
        lst.setGridSize(QSize(grid_w, grid_h))
        lst.setResizeMode(QListWidget.Adjust)
        lst.setMovement(QListWidget.Static)
        lst.setSelectionMode(QListWidget.SingleSelection)
        lst.setWordWrap(True)
        return lst

    def _gallery_panel(self, title, kind, icon_w, icon_h, grid_w, grid_h):
        """Panel «título + galería» para pósters o backdrops."""
        lst = self._make_gallery(icon_w, icon_h, grid_w, grid_h)
        if kind == "poster":
            self.posters = lst
        else:
            self.backdrops = lst
        lst.currentRowChanged.connect(lambda row, k=kind: self._pick_image(k, row))
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._section(title))
        v.addWidget(lst, 1)
        return panel

    # --------------------------------------------------------------- búsqueda
    def _search(self):
        text = self.query.text().strip()
        if not text:
            self.status.setText("Escribe un título para buscar")
            return
        if not self.api_key:
            self.status.setText("Falta la API key de TMDB (configúrala en Ajustes)")
            return
        self.search_btn.setEnabled(False)
        self.status.setText(f"Buscando «{text}» en TMDB…")
        worker = TMDBSearchWorker(self.api_key, text, parent=self)
        self._search_worker = worker
        worker.results.connect(self._search_ready)
        worker.failed.connect(self._search_failed)
        worker.finished.connect(lambda w=worker: self._worker_finished(w, self.search_btn))
        worker.start()

    def _worker_finished(self, worker, button):
        worker.deleteLater()
        if button is not None:
            button.setEnabled(True)

    def _search_ready(self, results):
        self._results = list(results or [])
        self.results.clear()
        for r in self._results:
            label = r.get("title") or r.get("original_title") or "Sin título"
            year = r.get("year") or ""
            it = QListWidgetItem(f"{label}\n{year}" if year else label)
            poster_file = str(r.get("poster_file") or "")
            if poster_file and os.path.isfile(poster_file):
                pm = QPixmap(poster_file)
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(72, 108, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            it.setToolTip((r.get("overview") or "")[:400])
            self.results.addItem(it)
        count = len(self._results)
        self.status.setText(f"{count} resultado(s)" if count else "TMDB no encontró ese título; prueba con otro texto")
        if count:
            self.results.setCurrentRow(0)

    def _search_failed(self, error):
        self.status.setText(f"TMDB no disponible: {error}")

    def _pick_result(self, row):
        if row < 0 or row >= len(self._results):
            return
        self._movie = self._results[row]
        title = self._movie.get("title") or self._movie.get("original_title") or ""
        year = self._movie.get("year") or ""
        overview = self._movie.get("overview") or ""
        self.movie_lbl.setText(f"<b>{title}</b> {year}<br>"
                               f"<span style='color:#b0bec5;'>{overview[:280]}</span>")
        self._load_gallery(self._movie)

    # --------------------------------------------------------------- galería
    def _load_gallery(self, movie):
        self._gallery_request += 1
        request = self._gallery_request
        self._posters, self._backdrops = [], []
        self._chosen = {"poster": "", "backdrop": ""}
        self.posters.clear()
        self.backdrops.clear()
        self.save_btn.setEnabled(False)
        self.status.setText(f"Descargando galería de «{movie.get('title') or ''}»…")
        worker = TMDBImagesWorker(self.api_key, movie, parent=self)
        self._images_worker = worker
        worker.ready.connect(lambda data, r=request: self._gallery_ready(r, data))
        worker.failed.connect(lambda error, r=request: self._gallery_failed(r, error))
        worker.finished.connect(lambda w=worker: self._worker_finished(w, None))
        worker.start()

    def _gallery_ready(self, request, data):
        if request != self._gallery_request:
            return  # llegó una galería de una selección anterior
        self._posters = list(data.get("posters") or [])
        self._backdrops = list(data.get("backdrops") or [])
        self._fill_gallery(self.posters, self._posters, "✕ Sin póster", 96, 144)
        self._fill_gallery(self.backdrops, self._backdrops, "✕ Sin backdrop", 208, 117)
        self.save_btn.setEnabled(True)
        self.status.setText(f"Galería lista • {len(self._posters)} pósters • {len(self._backdrops)} backdrops")

    def _fill_gallery(self, lst, images, empty_label, icon_w, icon_h):
        lst.clear()
        lst.addItem(QListWidgetItem(empty_label))
        for img in images:
            it = QListWidgetItem()
            local = str(img.get("file") or "")
            if local and os.path.isfile(local):
                pm = QPixmap(local)
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(icon_w, icon_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            lang = str(img.get("lang") or "").upper()
            it.setToolTip(f"Idioma: {lang or 'sin texto'}")
            lst.addItem(it)
        # Por defecto queda elegida la primera imagen real de cada galería.
        lst.setCurrentRow(1 if images else 0)

    def _gallery_failed(self, request, error):
        if request != self._gallery_request:
            return
        self.save_btn.setEnabled(False)
        self.status.setText(f"No se pudo descargar la galería: {error}. "
                            "Vuelve a seleccionar la película para reintentar.")

    def _pick_image(self, kind, row):
        images = self._posters if kind == "poster" else self._backdrops
        if row <= 0 or row > len(images):
            self._chosen[kind] = ""
        else:
            self._chosen[kind] = str(images[row - 1].get("file") or "")

    # ---------------------------------------------------------------- acciones
    def _save(self):
        if not self._movie:
            QMessageBox.warning(self, "Ficha TMDB", "Busca y selecciona una película primero.")
            return
        self._meta = {
            "id": self._movie.get("id"),
            "title": self._movie.get("title") or self._movie.get("original_title") or "",
            "year": self._movie.get("year") or "",
            "overview": self._movie.get("overview") or "",
            "poster_file": self._chosen.get("poster") or "",
            "backdrop_file": self._chosen.get("backdrop") or "",
        }
        self.accept()

    def _clear_ficha(self):
        question = "¿Quitar la ficha TMDB (título, sinopsis e imágenes) de este medio?"
        if QMessageBox.question(self, "Ficha TMDB", question) == QMessageBox.Yes:
            self._clear = True
            self.accept()

    # ------------------------------------------------------------------ salida
    def values(self):
        """Ficha elegida: id, título, año, sinopsis y archivos de imagen."""
        return dict(self._meta)

    def wants_clear(self):
        return bool(self._clear)

    def done(self, result):
        # Esperar a los workers antes de cerrar: sus hilos usan urllib y no
        # pueden abortarse a mitad de descarga; el diálogo sigue vivo como
        # hijo de la ventana principal, así que es seguro dejarlos terminar.
        for worker in (self._search_worker, self._images_worker):
            if worker is not None and worker.isRunning():
                worker.wait(4000)
        super().done(result)
