"""Ventanas TMDB: edición sencilla de la ficha (buscador + una galería de
imágenes) y configuración de la tarjeta al aire con vista previa."""
import os

from PySide6.QtCore import Qt, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from .config import APP_VERSION
from .tmdb import TMDBImagesWorker, TMDBSearchWorker, render_movie_overlay


class TMDBEditDialog(QDialog):
    """Edición sencilla de la ficha TMDB: buscar la película y hacer clic en
    la imagen correcta.

    Una sola galería mezcla los pósters y los fondos de la película; al hacer
    clic en una imagen queda elegida como póster o como fondo según su tipo
    (marcada con ✓). Cerrar la ventana es inmediato: los hilos de descarga
    cuelgan de la ventana principal, nunca del diálogo.
    """

    def __init__(self, parent, media, api_key):
        super().__init__(parent)
        self.setWindowTitle(f"Editar imágenes TMDB — TVPlayout PRO {APP_VERSION}")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 940, 600
        if available is not None:
            width = min(int(width), max(700, available.width() - 32))
            height = min(int(height), max(460, available.height() - 56))
        self.resize(max(700, int(width)), max(460, int(height)))
        self.setMinimumSize(700, 460)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        self.media = dict(media or {})
        self.api_key = str(api_key or "").strip()
        self._search_worker = None
        self._images_worker = None
        self._results = []
        self._movie = None
        self._images = []            # [{"kind": "poster"|"backdrop", "file": str, "lang": str}]
        self._chosen_poster = ""
        self._chosen_backdrop = ""
        self._gallery_request = 0
        self._search_gen = 0
        self._meta = {}
        self._clear = False
        self._closed = False
        # Los workers cuelgan de la ventana principal: cerrar el diálogo nunca
        # destruye un hilo en marcha (eso es un crash de Qt). Los resultados
        # tardíos se ignoran con los contadores de generación.
        self._worker_parent = self.parent() if isinstance(self.parent(), QWidget) else None

        root = QVBoxLayout(self)
        info = QLabel(f"<b>{self.media.get('title') or 'Medio sin título'}</b><br>"
                      f"<span style='color:#9a9a9a;'>{self.media.get('path') or ''}</span>")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(info)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Título de la película…")
        self.query.returnPressed.connect(self._search)
        self.query.setText(str(self.media.get("tmdb_title") or self.media.get("title") or ""))
        search_row.addWidget(self.query, 1)
        self.search_btn = QPushButton("🔎 Buscar")
        self.search_btn.clicked.connect(self._search)
        search_row.addWidget(self.search_btn)
        root.addLayout(search_row)

        self.status = QLabel(" ")
        self.status.setStyleSheet("color:#9a9a9a;")
        root.addWidget(self.status)

        body = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self._section("RESULTADOS"))
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.IconMode)
        self.results.setIconSize(QSize(66, 99))
        self.results.setGridSize(QSize(84, 130))
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
        rv.addWidget(self._section("IMÁGENES DE LA PELÍCULA"))
        self.movie_lbl = QLabel("Elige una película de la izquierda para ver sus imágenes.")
        self.movie_lbl.setStyleSheet("color:#79d6ff;")
        self.movie_lbl.setWordWrap(True)
        rv.addWidget(self.movie_lbl)
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.IconMode)
        self.images.setIconSize(QSize(110, 110))
        self.images.setGridSize(QSize(126, 152))
        self.images.setResizeMode(QListWidget.Adjust)
        self.images.setMovement(QListWidget.Static)
        self.images.setSelectionMode(QListWidget.SingleSelection)
        self.images.setWordWrap(True)
        self.images.currentRowChanged.connect(self._pick_image)
        rv.addWidget(self.images, 1)
        body.addWidget(right)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([280, 640])
        root.addWidget(body, 1)

        chosen = QHBoxLayout()
        chosen.setSpacing(12)
        chosen.addWidget(self._chosen_group("Póster", "poster"))
        chosen.addWidget(self._chosen_group("Fondo", "backdrop"))
        chosen.addStretch()
        root.addLayout(chosen)

        buttons = QHBoxLayout()
        clear_btn = QPushButton("🗑 Quitar ficha TMDB")
        clear_btn.clicked.connect(self._clear_ficha)
        buttons.addWidget(clear_btn)
        buttons.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        self.save_btn = QPushButton("💾 Guardar ficha")
        self.save_btn.setObjectName("primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        buttons.addWidget(self.save_btn)
        root.addLayout(buttons)

        if self.query.text().strip():
            self.status.setText("Buscando en TMDB…")
            QTimer.singleShot(250, self._search)
        else:
            self.status.setText("Escribe un título y pulsa Buscar.")

    # ------------------------------------------------------------------- UI
    @staticmethod
    def _section(title):
        lbl = QLabel(title)
        lbl.setObjectName("sectionTitle")
        return lbl

    def _chosen_group(self, title, kind):
        """Miniatura de la imagen elegida (póster o fondo) con su botón ✕."""
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(QLabel(f"<b>{title}</b>"))
        x = QPushButton("✕")
        x.setFixedSize(22, 22)
        x.setToolTip(f"Guardar sin {title.lower()}")
        if kind == "poster":
            x.clicked.connect(self._clear_poster)
            self.poster_x = x
        else:
            x.clicked.connect(self._clear_backdrop)
            self.backdrop_x = x
        head.addWidget(x)
        head.addStretch()
        v.addLayout(head)
        thumb = QLabel("—")
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("border:1px solid #333; color:#666; background:#0c0c0c;")
        if kind == "poster":
            thumb.setFixedSize(74, 104)
            self.poster_thumb = thumb
        else:
            thumb.setFixedSize(160, 90)
            self.backdrop_thumb = thumb
        v.addWidget(thumb)
        return panel

    # --------------------------------------------------------------- workers
    @staticmethod
    def _worker_running(worker):
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            return False  # ya liberado con deleteLater

    def _worker_done(self, worker, button):
        worker.deleteLater()
        if button is not None:
            button.setEnabled(True)

    # --------------------------------------------------------------- búsqueda
    def _search(self):
        if self._closed:
            return
        text = self.query.text().strip()
        if not text:
            self.status.setText("Escribe un título para buscar")
            return
        if not self.api_key:
            self.status.setText("Falta la API key de TMDB (configúrala en Ajustes)")
            return
        if self._worker_running(self._search_worker):
            self.status.setText("Espera: la búsqueda anterior sigue en curso…")
            return
        self._search_gen += 1
        gen = self._search_gen
        self.search_btn.setEnabled(False)
        self.status.setText(f"Buscando «{text}»…")
        worker = TMDBSearchWorker(self.api_key, text, parent=self._worker_parent)
        self._search_worker = worker
        worker.results.connect(lambda rows, g=gen: self._search_ready(g, rows))
        worker.failed.connect(lambda err, g=gen: self._search_failed(g, err))
        worker.finished.connect(lambda w=worker: self._worker_done(w, self.search_btn))
        worker.start()

    def _search_ready(self, gen, rows):
        if self._closed or gen != self._search_gen:
            return
        self._results = list(rows or [])
        self.results.clear()
        for r in self._results:
            label = r.get("title") or r.get("original_title") or "Sin título"
            year = r.get("year") or ""
            it = QListWidgetItem(f"{label}\n{year}" if year else label)
            poster_file = str(r.get("poster_file") or "")
            if poster_file and os.path.isfile(poster_file):
                pm = QPixmap(poster_file)
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(66, 99, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.results.addItem(it)
        count = len(self._results)
        self.status.setText(f"{count} resultado(s)" if count else "Sin resultados; prueba con otro título")
        if count:
            self.results.setCurrentRow(0)

    def _search_failed(self, gen, error):
        if self._closed or gen != self._search_gen:
            return
        self.status.setText(f"TMDB no disponible: {error}")

    def _pick_result(self, row):
        if self._closed or row < 0 or row >= len(self._results):
            return
        self._movie = self._results[row]
        title = self._movie.get("title") or self._movie.get("original_title") or ""
        year = self._movie.get("year") or ""
        self.movie_lbl.setText(f"<b>{title}</b> {year}".strip())
        self._load_gallery(self._movie)

    # --------------------------------------------------------------- galería
    def _load_gallery(self, movie):
        self._gallery_request += 1
        request = self._gallery_request
        self._images = []
        self._chosen_poster = ""
        self._chosen_backdrop = ""
        self.results.selectionModel().blockSignals(True)  # no reentrar al limpiar
        self.images.clear()
        self.images.selectionModel().blockSignals(False)
        self._refresh_marks()
        self._update_chosen()
        self.save_btn.setEnabled(False)
        self.status.setText(f"Descargando imágenes de «{movie.get('title') or ''}»…")
        worker = TMDBImagesWorker(self.api_key, movie, parent=self._worker_parent)
        self._images_worker = worker
        worker.ready.connect(lambda data, r=request: self._gallery_ready(r, data))
        worker.failed.connect(lambda err, r=request: self._gallery_failed(r, err))
        worker.finished.connect(lambda w=worker: self._worker_done(w, None))
        worker.start()

    def _gallery_ready(self, request, data):
        if self._closed or request != self._gallery_request:
            return
        posters = list(data.get("posters") or [])
        backdrops = list(data.get("backdrops") or [])
        self._images = ([{"kind": "poster", "file": str(p.get("file") or ""), "lang": str(p.get("lang") or "")}
                         for p in posters] +
                        [{"kind": "backdrop", "file": str(b.get("file") or ""), "lang": str(b.get("lang") or "")}
                         for b in backdrops])
        self.images.clear()
        for img in self._images:
            it = QListWidgetItem()
            local = img["file"]
            if local and os.path.isfile(local):
                pm = QPixmap(local)
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.images.addItem(it)
        # Por defecto: primera imagen de cada tipo.
        self._chosen_poster = next((i["file"] for i in self._images if i["kind"] == "poster"), "")
        self._chosen_backdrop = next((i["file"] for i in self._images if i["kind"] == "backdrop"), "")
        self._refresh_marks()
        self._update_chosen()
        self.save_btn.setEnabled(True)
        self.status.setText(f"{len(posters)} pósters • {len(backdrops)} fondos — haz clic en la imagen que quieras usar")

    def _gallery_failed(self, request, error):
        if self._closed or request != self._gallery_request:
            return
        self.save_btn.setEnabled(False)
        self.status.setText(f"No se pudieron descargar las imágenes: {error}. "
                            "Vuelve a hacer clic en la película para reintentar.")

    def _pick_image(self, row):
        if self._closed or row < 0 or row >= len(self._images):
            return
        img = self._images[row]
        if img["kind"] == "poster":
            self._chosen_poster = img["file"]
        else:
            self._chosen_backdrop = img["file"]
        self._refresh_marks()
        self._update_chosen()

    def _refresh_marks(self):
        """Marca con ✓ la imagen elegida de cada tipo."""
        for i, img in enumerate(self._images):
            it = self.images.item(i)
            if it is None:
                continue
            base = "Póster" if img["kind"] == "poster" else "Fondo"
            chosen = self._chosen_poster if img["kind"] == "poster" else self._chosen_backdrop
            it.setText(("✓ " if chosen and img["file"] == chosen else "") + base)

    def _update_chosen(self):
        self._set_thumb(self.poster_thumb, self._chosen_poster, 74, 104)
        self._set_thumb(self.backdrop_thumb, self._chosen_backdrop, 160, 90)

    @staticmethod
    def _set_thumb(label, path, w, h):
        pm = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pm.isNull():
            label.setPixmap(QPixmap())
            label.setText("—")
        else:
            label.setText("")
            label.setPixmap(pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _clear_poster(self):
        self._chosen_poster = ""
        self._refresh_marks()
        self._update_chosen()

    def _clear_backdrop(self):
        self._chosen_backdrop = ""
        self._refresh_marks()
        self._update_chosen()

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
            "poster_file": self._chosen_poster,
            "backdrop_file": self._chosen_backdrop,
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
        # Cierre inmediato y seguro: los hilos siguen su curso colgados de la
        # ventana principal y sus resultados tardíos se ignoran (_closed y los
        # contadores de generación). Nunca se espera bloqueando la interfaz.
        self._closed = True
        self._gallery_request += 1
        self._search_gen += 1
        super().done(result)


class TMDBCardPreview(QWidget):
    """Vista previa de la tarjeta TMDB con guías 16:9 y área segura 4:3.

    La tarjeta se renderiza con ``render_movie_overlay`` — exactamente el
    mismo código que usa la salida al aire — a las proporciones del lienzo
    visible, así que lo que se ve aquí es lo que sale por RTMP/SRT/NDI.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 250)
        self.setStyleSheet("background:#050505;border:1px solid #333;")
        self._metadata = {}
        self._layout = {}

    def set_sample(self, metadata, layout):
        self._metadata = metadata or {}
        self._layout = layout or {}
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#050505"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        frame_w = min(self.width() - 28, (self.height() - 46) * 16 / 9)
        frame_h = frame_w * 9 / 16
        frame = QRectF((self.width() - frame_w) / 2, 22, frame_w, frame_h)
        p.fillRect(frame, QColor("#111820"))
        # Tarjeta real, misma geometría del aire.
        card = render_movie_overlay(self._metadata, (int(frame_w), int(frame_h)), self._layout)
        if not card.isNull():
            p.drawImage(frame, card, QRectF(card.rect()))
        # Guías: marco 16:9 y área central 4:3 (12.5% — 87.5%).
        p.setPen(QPen(QColor("#72c7ff"), 1.5))
        p.drawRect(frame)
        safe_left = frame.left() + frame.width() * 0.125
        safe_right = frame.right() - frame.width() * 0.125
        p.setPen(QPen(QColor(242, 201, 76, 170), 1, Qt.DashLine))
        p.drawLine(safe_left, frame.top(), safe_left, frame.bottom())
        p.drawLine(safe_right, frame.top(), safe_right, frame.bottom())
        p.setPen(QColor("#f2c94c"))
        guide_font = QFont("Segoe UI", 8)
        p.setFont(guide_font)
        p.drawText(int(safe_left + 4), int(frame.bottom() + 15), "4:3 seguro · 12.5%")
        p.drawText(int(safe_right - 64), int(frame.bottom() + 15), "87.5%")
        p.setPen(QColor("#72c7ff"))
        p.drawText(int(frame.left()), 15, "16:9 · vista previa exacta de la tarjeta al aire")
        p.end()


class TMDBCardDialog(QDialog):
    """Posición y estilo de la tarjeta TMDB con vista previa en vivo."""

    def __init__(self, parent, settings, db=None):
        super().__init__(parent)
        self.setWindowTitle(f"Tarjeta TMDB al aire — TVPlayout PRO {APP_VERSION}")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 880, 600
        if available is not None:
            width = min(int(width), max(680, available.width() - 32))
            height = min(int(height), max(460, available.height() - 56))
        self.resize(max(680, int(width)), max(460, int(height)))
        self.setMinimumSize(680, 460)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        s = settings or {}
        self._samples = []
        self._sample_index = 0

        root = QVBoxLayout(self)
        self.preview = TMDBCardPreview()
        self.preview.setMinimumHeight(260)
        root.addWidget(self.preview, 1)

        form = QFormLayout()
        self.position = QComboBox()
        self.position.addItem("Arriba", "arriba")
        self.position.addItem("Abajo", "abajo")
        self.position.setCurrentIndex(1 if s.get("tmdb_card_position") == "abajo" else 0)
        self.align = QComboBox()
        self.align.addItem("Izquierda", "izquierda")
        self.align.addItem("Centro", "centro")
        self.align.addItem("Derecha", "derecha")
        saved_align = str(s.get("tmdb_card_align") or "izquierda")
        self.align.setCurrentIndex(2 if "derech" in saved_align else (1 if "centro" in saved_align else 0))
        self.style = QComboBox()
        self.style.addItem("Banda completa", "banda")
        self.style.addItem("Tarjeta compacta", "tarjeta")
        self.style.setCurrentIndex(1 if "tarjeta" in str(s.get("tmdb_card_style") or "") else 0)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setToolTip("Oscurecido del fondo de la tarjeta para que el texto siempre se lea")
        self.opacity.setValue(int(s.get("tmdb_card_opacity", 70) or 70))
        self.margin = QSpinBox()
        self.margin.setRange(0, 300)
        self.margin.setSuffix(" px")
        self.margin.setToolTip("Margen de referencia a 1080p; se escala solo a cualquier resolución")
        self.margin.setValue(int(s.get("tmdb_card_margin", 18) or 18))
        form.addRow("Posición", self.position)
        form.addRow("Alineación", self.align)
        form.addRow("Estilo", self.style)
        self.poster_size = QSpinBox()
        self.poster_size.setRange(40, 160)
        self.poster_size.setSuffix(" % banda")
        self.poster_size.setToolTip("Altura del póster como % de la franja; más de 100% sobresale de la franja")
        self.poster_size.setValue(int(s.get("tmdb_card_poster_size", 100) or 100))
        form.addRow("Tamaño del póster", self.poster_size)
        self.poster_shape = QComboBox()
        self.poster_shape.addItem("Cuadrado", "cuadrado")
        self.poster_shape.addItem("Original (2:3)", "original")
        self.poster_shape.addItem("Panorámica 16:9", "ancho")
        saved_shape = str(s.get("tmdb_card_poster_shape") or "cuadrado")
        self.poster_shape.setCurrentIndex({"original": 1, "ancho": 2}.get(saved_shape, 0))
        form.addRow("Forma del póster", self.poster_shape)
        self.text_scale = QSpinBox()
        self.text_scale.setRange(60, 150)
        self.text_scale.setSuffix(" %")
        self.text_scale.setToolTip("Escala del título y la descripción; la base ya es compacta")
        self.text_scale.setValue(int(s.get("tmdb_card_text_scale", 100) or 100))
        form.addRow("Tamaño del texto", self.text_scale)
        self.show_year = QCheckBox("Mostrar año junto al título")
        self.show_year.setChecked(bool(s.get("tmdb_card_show_year", False)))
        form.addRow("", self.show_year)
        form.addRow("Opacidad del fondo", self.opacity)
        form.addRow("Margen", self.margin)
        root.addLayout(form)

        sample_row = QHBoxLayout()
        self.sample_lbl = QLabel()
        self.sample_lbl.setStyleSheet("color:#9a9a9a;")
        sample_row.addWidget(self.sample_lbl, 1)
        cycle_btn = QPushButton("↻ Otra muestra")
        cycle_btn.setToolTip("Rota por las películas de la biblioteca que ya tienen imágenes TMDB")
        cycle_btn.clicked.connect(self._cycle_sample)
        sample_row.addWidget(cycle_btn)
        root.addLayout(sample_row)

        note = QLabel("La vista previa usa exactamente el mismo render que la salida al aire (RTMP/SRT/NDI y monitor). "
                      "La tarjeta aparece periódicamente durante Películas y Música según el intervalo de Ajustes.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9a9a9a;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("💾 Guardar")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        for combo in (self.position, self.align, self.style, self.poster_shape):
            combo.currentIndexChanged.connect(self._update_preview)
        self.show_year.stateChanged.connect(self._update_preview)
        self.opacity.valueChanged.connect(self._update_preview)
        self.margin.valueChanged.connect(self._update_preview)
        self.poster_size.valueChanged.connect(self._update_preview)
        self.text_scale.valueChanged.connect(self._update_preview)
        self._load_samples(db)
        self._update_preview()

    # --------------------------------------------------------------- muestras
    def _load_samples(self, db):
        """Muestra real: las películas de la biblioteca con ficha TMDB."""
        self._samples = []
        if db is not None:
            try:
                for row in db.search_media("", "Todas", limit=5000):
                    meta = {
                        "title": row["tmdb_title"] or row["title"],
                        "year": row["tmdb_year"] or "",
                        "overview": row["tmdb_overview"] or "",
                        "poster_file": row["tmdb_poster"] or "",
                        "backdrop_file": row["tmdb_backdrop"] or "",
                    }
                    if meta["poster_file"] or meta["backdrop_file"]:
                        self._samples.append(meta)
            except Exception:  # noqa: BLE001
                self._samples = []
        if not self._samples:
            self._samples = [self._synthetic_sample()]
        self._sample_index = 0
        self._refresh_sample_label()

    @staticmethod
    def _synthetic_sample():
        """Muestra sintética (imágenes dibujadas) cuando no hay fichas en la biblioteca."""
        poster = QImage(200, 300, QImage.Format.Format_RGB32)
        poster.fill(QColor("#35507a"))
        p = QPainter(poster)
        p.setPen(QColor("#ffffff"))
        f = QFont("Arial", 22)
        f.setBold(True)
        p.setFont(f)
        p.drawText(poster.rect(), Qt.AlignCenter, "PÓSTER")
        p.end()
        backdrop = QImage(640, 360, QImage.Format.Format_RGB32)
        backdrop.fill(QColor("#1c2a3f"))
        p = QPainter(backdrop)
        p.setPen(QColor("#9fb6d4"))
        f = QFont("Arial", 28)
        p.setFont(f)
        p.drawText(backdrop.rect(), Qt.AlignCenter, "BACKDROP")
        p.end()
        return {"title": "Película de ejemplo", "year": "2026",
                "overview": "Sinopsis de ejemplo para comprobar cómo se lee el texto de la tarjeta sobre el vídeo.",
                "poster_file": poster, "backdrop_file": backdrop}

    def _current_sample(self):
        if not self._samples:
            return {}
        return self._samples[self._sample_index % len(self._samples)]

    def _cycle_sample(self):
        self._sample_index = (self._sample_index + 1) % max(1, len(self._samples))
        self._refresh_sample_label()
        self._update_preview()

    def _refresh_sample_label(self):
        meta = self._current_sample()
        backdrop = meta.get("backdrop_file")
        if backdrop and not isinstance(backdrop, QImage):
            self.sample_lbl.setText(f"Muestra: {meta.get('title') or ''} {meta.get('year') or ''}".strip())
        else:
            self.sample_lbl.setText("Muestra: ejemplo sintético (la biblioteca aún no tiene fichas TMDB)")

    # ---------------------------------------------------------------- preview
    def _layout_values(self):
        return {"position": self.position.currentData(),
                "align": self.align.currentData(),
                "style": self.style.currentData(),
                "opacity": self.opacity.value(),
                "margin": self.margin.value(),
                "show_year": self.show_year.isChecked(),
                "poster_size": self.poster_size.value(),
                "poster_shape": self.poster_shape.currentData(),
                "text_scale": self.text_scale.value()}

    def _update_preview(self):
        self.preview.set_sample(self._current_sample(), self._layout_values())

    def values(self):
        return {"tmdb_card_position": self.position.currentData() or "arriba",
                "tmdb_card_align": self.align.currentData() or "izquierda",
                "tmdb_card_style": self.style.currentData() or "banda",
                "tmdb_card_opacity": self.opacity.value(),
                "tmdb_card_margin": self.margin.value(),
                "tmdb_card_show_year": self.show_year.isChecked(),
                "tmdb_card_poster_size": self.poster_size.value(),
                "tmdb_card_poster_shape": self.poster_shape.currentData() or "cuadrado",
                "tmdb_card_text_scale": self.text_scale.value()}
