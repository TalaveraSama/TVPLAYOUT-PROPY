"""Diálogo de configuración del Procesador de Audio Profesional para emisión broadcast."""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audio_processor import AUDIO_PRESETS, build_audio_filters


def _prepare_resizable_dialog(dialog, width, height, min_width=520, min_height=420):
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


class AudioProcessorDialog(QDialog):
    """Diálogo completo para ajustar la cadena de audio profesional en tiempo de emisión."""

    def __init__(self, parent=None, settings: Dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Procesador de Audio Profesional — Nexora Air")
        self.settings = dict(settings or {})
        _prepare_resizable_dialog(self, 640, 680, 560, 460)
        self._init_ui()
        self._load_values()
        self._update_filter_preview()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # 1. Cabecera e Interruptor General
        top_box = QGroupBox("Estado del Procesador")
        top_layout = QVBoxLayout(top_box)
        self.enabled_chk = QCheckBox("Activar Procesador de Audio Profesional en Salidas IP (RTMP / SRT / UDP)")
        self.enabled_chk.setStyleSheet("font-weight:bold; font-size:13px; color:#00e5ff;")
        self.enabled_chk.toggled.connect(self._on_values_changed)
        top_layout.addWidget(self.enabled_chk)

        # Preset Selector
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset de Emisión:"))
        self.preset_combo = QComboBox()
        for key, pinfo in AUDIO_PRESETS.items():
            self.preset_combo.addItem(pinfo["name"], key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.preset_combo, 1)
        top_layout.addLayout(preset_row)

        self.preset_desc = QLabel()
        self.preset_desc.setWordWrap(True)
        self.preset_desc.setStyleSheet("color:#aaa; font-style:italic; padding-top:4px;")
        top_layout.addWidget(self.preset_desc)
        layout.addWidget(top_box)

        # 2. Pestañas de Ajustes Detallados
        tabs = QTabWidget()

        # Tab 1: Sonoridad (Loudness)
        tab_norm = QWidget()
        form_norm = QFormLayout(tab_norm)
        form_norm.setSpacing(8)

        self.norm_mode = QComboBox()
        self.norm_mode.addItem("Desactivado", "off")
        self.norm_mode.addItem("EBU R128 / ITU-R BS.1770 (loudnorm)", "loudnorm")
        self.norm_mode.addItem("AGC Dinámico Multi-Ventana (DynAudNorm)", "dynaudnorm")
        self.norm_mode.currentIndexChanged.connect(self._on_values_changed)
        form_norm.addRow("Algoritmo de Normalización:", self.norm_mode)

        self.target_lufs = QDoubleSpinBox()
        self.target_lufs.setRange(-35.0, -8.0)
        self.target_lufs.setSingleStep(0.5)
        self.target_lufs.setSuffix(" LUFS")
        self.target_lufs.valueChanged.connect(self._on_values_changed)
        form_norm.addRow("Sonoridad Integrada Objetivo:", self.target_lufs)

        self.true_peak = QDoubleSpinBox()
        self.true_peak.setRange(-8.0, 0.0)
        self.true_peak.setSingleStep(0.1)
        self.true_peak.setSuffix(" dBTP")
        self.true_peak.valueChanged.connect(self._on_values_changed)
        form_norm.addRow("Límite True Peak Máximo:", self.true_peak)

        self.lra = QDoubleSpinBox()
        self.lra.setRange(1.0, 20.0)
        self.lra.setSingleStep(0.5)
        self.lra.setSuffix(" LU")
        self.lra.valueChanged.connect(self._on_values_changed)
        form_norm.addRow("Rango de Sonoridad (LRA):", self.lra)

        tabs.addTab(tab_norm, "🔊 Sonoridad (LUFS)")

        # Tab 2: Dinámica y Compresión
        tab_dyn = QWidget()
        form_dyn = QFormLayout(tab_dyn)
        form_dyn.setSpacing(8)

        self.highpass = QComboBox()
        self.highpass.addItem("Desactivado", 0)
        self.highpass.addItem("30 Hz (Corte subsónico suave)", 30)
        self.highpass.addItem("35 Hz (Recomendado Broadcast)", 35)
        self.highpass.addItem("50 Hz (Eliminar rumble y golpes)", 50)
        self.highpass.addItem("80 Hz (Voz / Diálogos)", 80)
        self.highpass.currentIndexChanged.connect(self._on_values_changed)
        form_dyn.addRow("Filtro Pasa-Altos Subsónico:", self.highpass)

        self.compressor_chk = QCheckBox("Habilitar Compresor Dinámico Broadcast")
        self.compressor_chk.toggled.connect(self._on_values_changed)
        form_dyn.addRow("", self.compressor_chk)

        self.comp_thresh = QDoubleSpinBox()
        self.comp_thresh.setRange(-45.0, 0.0)
        self.comp_thresh.setSuffix(" dB")
        self.comp_thresh.valueChanged.connect(self._on_values_changed)
        form_dyn.addRow("Umbral (Threshold):", self.comp_thresh)

        self.comp_ratio = QDoubleSpinBox()
        self.comp_ratio.setRange(1.0, 15.0)
        self.comp_ratio.setSingleStep(0.5)
        self.comp_ratio.setSuffix(" : 1")
        self.comp_ratio.valueChanged.connect(self._on_values_changed)
        form_dyn.addRow("Ratio de Compresión:", self.comp_ratio)

        self.comp_attack = QDoubleSpinBox()
        self.comp_attack.setRange(1.0, 200.0)
        self.comp_attack.setSuffix(" ms")
        self.comp_attack.valueChanged.connect(self._on_values_changed)
        form_dyn.addRow("Tiempo de Ataque:", self.comp_attack)

        self.comp_release = QDoubleSpinBox()
        self.comp_release.setRange(10.0, 1000.0)
        self.comp_release.setSuffix(" ms")
        self.comp_release.valueChanged.connect(self._on_values_changed)
        form_dyn.addRow("Tiempo de Liberación:", self.comp_release)

        self.comp_makeup = QDoubleSpinBox()
        self.comp_makeup.setRange(0.0, 15.0)
        self.comp_makeup.setSuffix(" dB")
        self.comp_makeup.valueChanged.connect(self._on_values_changed)
        form_dyn.addRow("Ganancia Compensatoria (Makeup):", self.comp_makeup)

        tabs.addTab(tab_dyn, "🎛️ Dinámica & Compresión")

        # Tab 3: Ecualización y Realce
        tab_eq = QWidget()
        form_eq = QFormLayout(tab_eq)
        form_eq.setSpacing(8)

        self.eq_chk = QCheckBox("Habilitar Ecualizador Broadcast de 3 Bandas")
        self.eq_chk.toggled.connect(self._on_values_changed)
        form_eq.addRow("", self.eq_chk)

        self.eq_bass = QDoubleSpinBox()
        self.eq_bass.setRange(-10.0, 10.0)
        self.eq_bass.setSuffix(" dB (120 Hz)")
        self.eq_bass.valueChanged.connect(self._on_values_changed)
        form_eq.addRow("Graves:", self.eq_bass)

        self.eq_presence = QDoubleSpinBox()
        self.eq_presence.setRange(-10.0, 10.0)
        self.eq_presence.setSuffix(" dB (3.2 kHz)")
        self.eq_presence.valueChanged.connect(self._on_values_changed)
        form_eq.addRow("Presencia Vocal:", self.eq_presence)

        self.eq_treble = QDoubleSpinBox()
        self.eq_treble.setRange(-10.0, 10.0)
        self.eq_treble.setSuffix(" dB (12 kHz)")
        self.eq_treble.valueChanged.connect(self._on_values_changed)
        form_eq.addRow("Brillo / Agudos:", self.eq_treble)

        self.stereo_chk = QCheckBox("Realce de Imagen Estéreo (Stereo Widener)")
        self.stereo_chk.toggled.connect(self._on_values_changed)
        form_eq.addRow("", self.stereo_chk)

        self.limiter_chk = QCheckBox("Limitador True Peak de Seguridad (Anti-Clipping)")
        self.limiter_chk.toggled.connect(self._on_values_changed)
        form_eq.addRow("", self.limiter_chk)

        self.gain_db = QDoubleSpinBox()
        self.gain_db.setRange(-18.0, 18.0)
        self.gain_db.setSuffix(" dB")
        self.gain_db.valueChanged.connect(self._on_values_changed)
        form_eq.addRow("Ganancia Master Trim:", self.gain_db)

        tabs.addTab(tab_eq, "🎚️ Ecualización & Realce")
        layout.addWidget(tabs, 1)

        # 3. Vista previa de la cadena de filtros FFmpeg generada
        filter_box = QGroupBox("Cadena de Filtros FFmpeg (-af)")
        filter_layout = QVBoxLayout(filter_box)
        self.filter_preview = QPlainTextEdit()
        self.filter_preview.setReadOnly(True)
        self.filter_preview.setMaximumHeight(55)
        self.filter_preview.setStyleSheet("background:#111; color:#00e5ff; font-family:monospace; font-size:11px;")
        filter_layout.addWidget(self.filter_preview)
        layout.addWidget(filter_box)

        # 4. Botones de acción
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton("Valores por Defecto")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(btn_reset)
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
        self.enabled_chk.setChecked(bool(s.get("audio_proc_enabled", False)))

        preset = str(s.get("audio_proc_preset", "off"))
        idx = self.preset_combo.findData(preset)
        self.preset_combo.setCurrentIndex(max(0, idx))

        norm_mode = str(s.get("audio_proc_norm_mode", "loudnorm"))
        idx_n = self.norm_mode.findData(norm_mode)
        self.norm_mode.setCurrentIndex(max(0, idx_n))

        self.target_lufs.setValue(float(s.get("audio_proc_target_lufs", -23.0)))
        self.true_peak.setValue(float(s.get("audio_proc_true_peak", -1.5)))
        self.lra.setValue(float(s.get("audio_proc_lra", 7.0)))

        hp = int(s.get("audio_proc_highpass", 35))
        idx_hp = self.highpass.findData(hp)
        self.highpass.setCurrentIndex(max(0, idx_hp))

        self.compressor_chk.setChecked(bool(s.get("audio_proc_compressor", True)))
        self.comp_thresh.setValue(float(s.get("audio_proc_comp_threshold", -18.0)))
        self.comp_ratio.setValue(float(s.get("audio_proc_comp_ratio", 3.0)))
        self.comp_attack.setValue(float(s.get("audio_proc_comp_attack", 15.0)))
        self.comp_release.setValue(float(s.get("audio_proc_comp_release", 200.0)))
        self.comp_makeup.setValue(float(s.get("audio_proc_comp_makeup", 2.0)))

        self.eq_chk.setChecked(bool(s.get("audio_proc_equalizer", True)))
        self.eq_bass.setValue(float(s.get("audio_proc_eq_bass", 0.5)))
        self.eq_presence.setValue(float(s.get("audio_proc_eq_presence", 1.5)))
        self.eq_treble.setValue(float(s.get("audio_proc_eq_treble", 1.0)))

        self.stereo_chk.setChecked(bool(s.get("audio_proc_stereo_enhance", False)))
        self.limiter_chk.setChecked(bool(s.get("audio_proc_limiter", True)))
        self.gain_db.setValue(float(s.get("audio_proc_gain_db", 0.0)))

    def _on_preset_selected(self, _index):
        key = self.preset_combo.currentData()
        if not key or key not in AUDIO_PRESETS:
            return

        p = AUDIO_PRESETS[key]
        self.preset_desc.setText(p["desc"])

        if key == "off":
            self.enabled_chk.setChecked(False)
            self._update_filter_preview()
            return

        self.enabled_chk.setChecked(True)
        idx_n = self.norm_mode.findData(p["norm_mode"])
        self.norm_mode.setCurrentIndex(max(0, idx_n))

        self.target_lufs.setValue(p["target_lufs"])
        self.true_peak.setValue(p["true_peak"])
        self.lra.setValue(p["lra"])

        idx_hp = self.highpass.findData(p["highpass"])
        self.highpass.setCurrentIndex(max(0, idx_hp))

        self.compressor_chk.setChecked(p["compressor"])
        self.comp_thresh.setValue(p["comp_threshold"])
        self.comp_ratio.setValue(p["comp_ratio"])
        self.comp_attack.setValue(p["comp_attack"])
        self.comp_release.setValue(p["comp_release"])
        self.comp_makeup.setValue(p["comp_makeup"])

        self.eq_chk.setChecked(p["equalizer"])
        self.eq_bass.setValue(p["eq_bass"])
        self.eq_presence.setValue(p["eq_presence"])
        self.eq_treble.setValue(p["eq_treble"])

        self.stereo_chk.setChecked(p["stereo_enhance"])
        self.limiter_chk.setChecked(p["limiter"])
        self.gain_db.setValue(p["gain_db"])

        self._update_filter_preview()

    def _on_values_changed(self):
        self._update_filter_preview()

    def _update_filter_preview(self):
        cfg = self.values()
        filter_str = build_audio_filters(cfg)
        self.filter_preview.setPlainText(filter_str)

    def _reset_defaults(self):
        idx = self.preset_combo.findData("ebu_r128")
        self.preset_combo.setCurrentIndex(max(0, idx))

    def values(self) -> Dict[str, Any]:
        return {
            "audio_proc_enabled": self.enabled_chk.isChecked(),
            "audio_proc_preset": self.preset_combo.currentData() or "custom",
            "audio_proc_norm_mode": self.norm_mode.currentData() or "loudnorm",
            "audio_proc_target_lufs": self.target_lufs.value(),
            "audio_proc_true_peak": self.true_peak.value(),
            "audio_proc_lra": self.lra.value(),
            "audio_proc_highpass": int(self.highpass.currentData() or 0),
            "audio_proc_compressor": self.compressor_chk.isChecked(),
            "audio_proc_comp_threshold": self.comp_thresh.value(),
            "audio_proc_comp_ratio": self.comp_ratio.value(),
            "audio_proc_comp_attack": self.comp_attack.value(),
            "audio_proc_comp_release": self.comp_release.value(),
            "audio_proc_comp_makeup": self.comp_makeup.value(),
            "audio_proc_equalizer": self.eq_chk.isChecked(),
            "audio_proc_eq_bass": self.eq_bass.value(),
            "audio_proc_eq_presence": self.eq_presence.value(),
            "audio_proc_eq_treble": self.eq_treble.value(),
            "audio_proc_stereo_enhance": self.stereo_chk.isChecked(),
            "audio_proc_limiter": self.limiter_chk.isChecked(),
            "audio_proc_gain_db": self.gain_db.value(),
        }
