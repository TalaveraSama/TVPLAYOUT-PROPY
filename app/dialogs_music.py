"""Diálogo de configuración de Reconocimiento y Titulación Gráfica en Vivo para Videos Musicales."""
from __future__ import annotations

import os
from typing import Any, Dict

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .music_titling import (
    clean_music_title,
    extract_local_tags,
    identify_music_track,
    render_music_overlay,
)


def _prepare_resizable_dialog(dialog, width, height, min_width=540, min_height=450):
    screen = (dialog.parent().screen() if dialog.parent() is not None else None) or QApplication.primaryScreen()
    available = screen.availableGeometry() if screen is not None else None
    if available is not None:
        width = min(int(width), max(min_width, available.width() - 32))
        height = min(int(height), max(min_height, available.height() - 56))
    dialog.resize(max(min_width, int(width)), max(min_height, int(height)))
    dialog.setMinimumSize(min_width, min_height)
    dialog.setSizeGripEnabled(True)
    dialog.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint, True)


class MusicOverlayPreviewWidget(QWidget):
    """Vista previa profesional del zócalo musical renderizado sobre un fotograma simulado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 260)
        self.setStyleSheet("background:#05070a; border:1px solid #222; border-radius:6px;")
        self._sample_meta = {
            "artist": "DUA LIPA",
            "title": "Levitating",
            "album": "Future Nostalgia",
            "year": "2020",
            "label": "Warner Records",
        }
        self._style_config = {
            "style": "glass",
            "position": "inferior-izquierda",
            "opacity": 90,
            "text_scale": 100,
            "accent_color": "#00e5ff",
        }

    def set_sample(self, meta: Dict[str, str], style_config: Dict[str, Any]):
        self._sample_meta = dict(meta or self._sample_meta)
        self._style_config = dict(style_config or self._style_config)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fondo con gradiente oscuro simulando video broadcast
        rect = self.rect()
        p.fillRect(rect, QColor("#080c14"))

        # Dibujar líneas de guía sutiles
        p.setPen(QPen(QColor(40, 50, 70), 1, Qt.PenStyle.DashLine))
        p.drawRect(int(rect.width() * 0.05), int(rect.height() * 0.05),
                   int(rect.width() * 0.9), int(rect.height() * 0.9))

        # Renderizar el zócalo a la resolución de este widget
        img = render_music_overlay(self._sample_meta, (rect.width(), rect.height()), self._style_config)
        if not img.isNull():
            p.drawImage(0, 0, img)

        p.end()


class MusicTitlingDialog(QDialog):
    """Diálogo de configuración para el servicio de identificación musical y titulación al aire."""

    def __init__(self, parent=None, settings: Dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Titulación de Videos Musicales en Vivo — Nexora Air")
        self.settings = dict(settings or {})
        _prepare_resizable_dialog(self, 680, 720, 580, 500)
        self._init_ui()
        self._load_values()
        self._update_preview()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # 1. Vista Previa en Vivo del Zócalo
        self.preview = MusicOverlayPreviewWidget(self)
        layout.addWidget(self.preview)

        # 2. Interruptor General
        self.enabled_chk = QCheckBox("Activar Titulación Automática en Clips de Música")
        self.enabled_chk.setStyleSheet("font-weight:bold; font-size:13px; color:#00e5ff;")
        self.enabled_chk.toggled.connect(self._on_values_changed)
        layout.addWidget(self.enabled_chk)

        # 3. Pestañas de Configuración
        tabs = QTabWidget()

        # Tab 1: Reglas de Tiempo (Timing)
        tab_timing = QWidget()
        form_time = QFormLayout(tab_timing)
        form_time.setSpacing(10)

        self.intro_start = QDoubleSpinBox()
        self.intro_start.setRange(0.0, 180.0)
        self.intro_start.setSingleStep(1.0)
        self.intro_start.setSuffix(" s tras el inicio")
        self.intro_start.setValue(30.0)
        self.intro_start.valueChanged.connect(self._on_values_changed)
        form_time.addRow("Entrada del Título (Inicio):", self.intro_start)

        self.intro_dur = QDoubleSpinBox()
        self.intro_dur.setRange(3.0, 60.0)
        self.intro_dur.setSingleStep(1.0)
        self.intro_dur.setSuffix(" s de duración")
        self.intro_dur.setValue(12.0)
        self.intro_dur.valueChanged.connect(self._on_values_changed)
        form_time.addRow("Duración de Entrada:", self.intro_dur)

        self.outro_dur = QDoubleSpinBox()
        self.outro_dur.setRange(2.0, 60.0)
        self.outro_dur.setSingleStep(1.0)
        self.outro_dur.setSuffix(" s antes del final")
        self.outro_dur.setValue(10.0)
        self.outro_dur.valueChanged.connect(self._on_values_changed)
        form_time.addRow("Salida del Título (Final):", self.outro_dur)

        note_time = QLabel("ℹ️ <b>Regla Broadcast:</b> El título aparece automáticamente <b>después de 30 segundos</b> de iniciada la canción y reaparece durante los <b>últimos 10 segundos</b> antes de terminar.")
        note_time.setWordWrap(True)
        note_time.setStyleSheet("color:#aaa; font-size:11px; padding:6px; background:#111; border-radius:4px;")
        form_time.addRow("", note_time)

        tabs.addTab(tab_timing, "⏱️ Tiempos de Emisión")

        # Tab 2: Servicio de Identificación / APIs
        tab_service = QWidget()
        form_srv = QFormLayout(tab_service)
        form_srv.setSpacing(8)

        self.service_combo = QComboBox()
        self.service_combo.addItem("Automático (Etiquetas locales + APIs en línea)", "auto")
        self.service_combo.addItem("AudD Music Recognition API (Reconocimiento acústico)", "audd")
        self.service_combo.addItem("AcoustID / Chromaprint (Base MusicBrainz)", "acoustid")
        self.service_combo.addItem("ACRCloud Broadcast API", "acrcloud")
        self.service_combo.addItem("Solo metadatos locales (ID3 / ffprobe / Nombre)", "local")
        self.service_combo.currentIndexChanged.connect(self._on_values_changed)
        form_srv.addRow("Servicio de Reconocimiento:", self.service_combo)

        self.audd_token = QLineEdit()
        self.audd_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.audd_token.setPlaceholderText("API token de AudD (https://audd.io)")
        self.audd_token.textChanged.connect(self._on_values_changed)
        form_srv.addRow("AudD API Token:", self.audd_token)

        self.acoustid_key = QLineEdit()
        self.acoustid_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.acoustid_key.setPlaceholderText("Client API key de AcoustID")
        self.acoustid_key.textChanged.connect(self._on_values_changed)
        form_srv.addRow("AcoustID Client Key:", self.acoustid_key)

        self.acr_host = QLineEdit()
        self.acr_host.setPlaceholderText("ej. identify-us-west-2.acrcloud.com")
        self.acr_host.textChanged.connect(self._on_values_changed)
        form_srv.addRow("ACRCloud Host:", self.acr_host)

        self.acr_key = QLineEdit()
        self.acr_key.setPlaceholderText("Access Key")
        self.acr_key.textChanged.connect(self._on_values_changed)
        form_srv.addRow("ACRCloud Key:", self.acr_key)

        self.acr_secret = QLineEdit()
        self.acr_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.acr_secret.setPlaceholderText("Access Secret")
        self.acr_secret.textChanged.connect(self._on_values_changed)
        form_srv.addRow("ACRCloud Secret:", self.acr_secret)

        tabs.addTab(tab_service, "🔍 Servicio de Reconocimiento")

        # Tab 3: Diseño y Grafismo (Look & Feel)
        tab_style = QWidget()
        form_style = QFormLayout(tab_style)
        form_style.setSpacing(8)

        self.style_combo = QComboBox()
        self.style_combo.addItem("Modern Glassmorphism (Translúcido)", "glass")
        self.style_combo.addItem("MTV / Telehit Clásico (Borde de color)", "classic_mtv")
        self.style_combo.addItem("Neon Cyber (Acentos Nexora Air)", "neon")
        self.style_combo.addItem("Compact Minimal (Minimalista)", "compact")
        self.style_combo.currentIndexChanged.connect(self._on_values_changed)
        form_style.addRow("Estilo Visual:", self.style_combo)

        self.position_combo = QComboBox()
        self.position_combo.addItem("Inferior Izquierda (Estándar TV)", "inferior-izquierda")
        self.position_combo.addItem("Inferior Derecha", "inferior-derecha")
        self.position_combo.addItem("Superior Izquierda", "superior-izquierda")
        self.position_combo.addItem("Inferior Ancho Completo", "inferior-completo")
        self.position_combo.currentIndexChanged.connect(self._on_values_changed)
        form_style.addRow("Posición en Pantalla:", self.position_combo)

        self.color_combo = QComboBox()
        self.color_combo.addItem("Cian Eléctrico (#00e5ff)", "#00e5ff")
        self.color_combo.addItem("Amarillo Oro (#ffd54f)", "#ffd54f")
        self.color_combo.addItem("Violeta Neón (#e040fb)", "#e040fb")
        self.color_combo.addItem("Verde Esmeralda (#00e676)", "#00e676")
        self.color_combo.addItem("Rojo Fuego (#ff5252)", "#ff5252")
        self.color_combo.addItem("Blanco Puro (#ffffff)", "#ffffff")
        self.color_combo.currentIndexChanged.connect(self._on_values_changed)
        form_style.addRow("Color de Acento:", self.color_combo)

        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(40, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(90)
        self.opacity_spin.valueChanged.connect(self._on_values_changed)
        form_style.addRow("Opacidad del Fondo:", self.opacity_spin)

        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(60, 160)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(100)
        self.scale_spin.valueChanged.connect(self._on_values_changed)
        form_style.addRow("Escala de Texto y Gráficos:", self.scale_spin)

        tabs.addTab(tab_style, "🎨 Estilo & Gráficos")
        layout.addWidget(tabs, 1)

        # 4. Botonera
        btn_layout = QHBoxLayout()
        btn_test = QPushButton("Probar Archivo Local…")
        btn_test.clicked.connect(self._test_local_file)
        btn_layout.addWidget(btn_test)

        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("Guardar y Aplicar")
        btn_save.setStyleSheet("background:#00bcd4; color:#000; font-weight:bold; padding:6px 16px;")
        btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _load_values(self):
        s = self.settings
        self.enabled_chk.setChecked(bool(s.get("music_titling_enabled", True)))

        self.intro_start.setValue(float(s.get("music_titling_intro_start", 30.0)))
        self.intro_dur.setValue(float(s.get("music_titling_intro_duration", 12.0)))
        self.outro_dur.setValue(float(s.get("music_titling_outro_duration", 10.0)))

        srv = str(s.get("music_titling_service", "auto"))
        idx_s = self.service_combo.findData(srv)
        self.service_combo.setCurrentIndex(max(0, idx_s))

        self.audd_token.setText(str(s.get("music_audd_api_token", "")))
        self.acoustid_key.setText(str(s.get("music_acoustid_api_key", "")))
        self.acr_host.setText(str(s.get("music_acrcloud_host", "")))
        self.acr_key.setText(str(s.get("music_acrcloud_key", "")))
        self.acr_secret.setText(str(s.get("music_acrcloud_secret", "")))

        st = str(s.get("music_titling_style", "glass"))
        idx_st = self.style_combo.findData(st)
        self.style_combo.setCurrentIndex(max(0, idx_st))

        pos = str(s.get("music_titling_position", "inferior-izquierda"))
        idx_p = self.position_combo.findData(pos)
        self.position_combo.setCurrentIndex(max(0, idx_p))

        col = str(s.get("music_titling_accent_color", "#00e5ff"))
        idx_c = self.color_combo.findData(col)
        self.color_combo.setCurrentIndex(max(0, idx_c))

        self.opacity_spin.setValue(int(s.get("music_titling_opacity", 90)))
        self.scale_spin.setValue(int(s.get("music_titling_text_scale", 100)))

    def _on_values_changed(self):
        self._update_preview()

    def _update_preview(self):
        style_cfg = {
            "style": self.style_combo.currentData() or "glass",
            "position": self.position_combo.currentData() or "inferior-izquierda",
            "accent_color": self.color_combo.currentData() or "#00e5ff",
            "opacity": self.opacity_spin.value(),
            "text_scale": self.scale_spin.value(),
        }
        self.preview.set_sample(self.preview._sample_meta, style_cfg)

    def _test_local_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar video musical", "", "Videos/Audio (*.mp4 *.mkv *.avi *.mp3 *.flac *.wav)")
        if not path:
            return
        meta = identify_music_track(path, self.values())
        if meta.get("title") or meta.get("artist"):
            self.preview._sample_meta = meta
            self._update_preview()
            QMessageBox.information(
                self,
                "Identificación Exitosa",
                f"<b>Canción:</b> {meta.get('title')}<br>"
                f"<b>Artista:</b> {meta.get('artist')}<br>"
                f"<b>Álbum:</b> {meta.get('album') or 'N/A'}<br>"
                f"<b>Fuente:</b> {meta.get('source')}",
            )
        else:
            QMessageBox.warning(self, "Sin Resultados", "No se pudieron extraer metadatos del archivo seleccionado.")

    def values(self) -> Dict[str, Any]:
        return {
            "music_titling_enabled": self.enabled_chk.isChecked(),
            "music_titling_intro_start": self.intro_start.value(),
            "music_titling_intro_duration": self.intro_dur.value(),
            "music_titling_outro_duration": self.outro_dur.value(),
            "music_titling_service": self.service_combo.currentData() or "auto",
            "music_audd_api_token": self.audd_token.text().strip(),
            "music_acoustid_api_key": self.acoustid_key.text().strip(),
            "music_acrcloud_host": self.acr_host.text().strip(),
            "music_acrcloud_key": self.acr_key.text().strip(),
            "music_acrcloud_secret": self.acr_secret.text().strip(),
            "music_titling_style": self.style_combo.currentData() or "glass",
            "music_titling_position": self.position_combo.currentData() or "inferior-izquierda",
            "music_titling_accent_color": self.color_combo.currentData() or "#00e5ff",
            "music_titling_opacity": self.opacity_spin.value(),
            "music_titling_text_scale": self.scale_spin.value(),
        }
