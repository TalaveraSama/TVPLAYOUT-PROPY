"""Diálogos adicionales: Logo/CG sobre la salida RTMP y Dispositivos (estado de binarios/encoders/GPU)."""
import os
import re
import shutil
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QLineEdit, QComboBox,
                               QSpinBox, QCheckBox, QFileDialog, QPlainTextEdit, QMessageBox)

from .config import MPV_PATH, FFMPEG_PATH, FFPROBE_PATH, ROOT, APP_VERSION, DEFAULT_LOGO_PATH

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LogoDialog(QDialog):
    """Configura la mosca/logo que FFmpeg superpone en la salida RTMP."""

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Logo / CG en salida RTMP")
        self.resize(520, 380)
        s = settings
        f = QFormLayout(self)
        self.enabled = QCheckBox("Superponer logo en la salida RTMP")
        self.enabled.setChecked(bool(s.get("logo_enabled", False)))
        row = QHBoxLayout()
        saved_logo = s.get("logo_path", "")
        default_logo = str(DEFAULT_LOGO_PATH) if DEFAULT_LOGO_PATH else ""
        self.path = QLineEdit(saved_logo or default_logo)
        self.path.setPlaceholderText("PNG con transparencia recomendado")
        row.addWidget(self.path, 1)
        b = QPushButton("…")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        self.position = QComboBox()
        self.position.addItems(["arriba-izquierda", "arriba-derecha", "abajo-izquierda", "abajo-derecha"])
        self.position.setCurrentText(s.get("logo_position", "arriba-derecha"))
        self.scale = QSpinBox()
        self.scale.setRange(2, 60)
        self.scale.setSuffix(" % del ancho")
        self.scale.setValue(int(s.get("logo_scale", 12)))
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(int(s.get("logo_opacity", 90)))
        self.margin = QSpinBox()
        self.margin.setRange(0, 400)
        self.margin.setSuffix(" px")
        self.margin.setValue(int(s.get("logo_margin", 24)))
        self.preview = QLabel()
        self.preview.setFixedHeight(90)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#000;border:1px solid #333;")
        f.addRow("", self.enabled)
        f.addRow("Archivo", row)
        f.addRow("Posición", self.position)
        f.addRow("Tamaño", self.scale)
        f.addRow("Opacidad", self.opacity)
        f.addRow("Margen", self.margin)
        f.addRow("Vista previa", self.preview)
        note = QLabel("El logo se aplica en el siguiente evento emitido por RTMP (FFmpeg se reinicia por clip). "
                      "No afecta al monitor local.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9a9a9a;")
        f.addRow(note)
        btns = QHBoxLayout()
        btns.addStretch()
        c = QPushButton("Cancelar")
        c.clicked.connect(self.reject)
        ok = QPushButton("Guardar")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(c)
        btns.addWidget(ok)
        f.addRow(btns)
        self.path.textChanged.connect(self._update_preview)
        self._update_preview()

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Logo", str(ROOT), "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif)")
        if p:
            self.path.setText(p)

    def _update_preview(self):
        p = self.path.text().strip()
        if p and os.path.isfile(p):
            pm = QPixmap(p)
            if not pm.isNull():
                self.preview.setPixmap(pm.scaled(240, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.preview.setPixmap(QPixmap())
        self.preview.setText("sin logo")

    def values(self):
        return {"logo_enabled": self.enabled.isChecked(), "logo_path": self.path.text().strip(),
                "logo_position": self.position.currentText(), "logo_scale": self.scale.value(),
                "logo_opacity": self.opacity.value(), "logo_margin": self.margin.value()}


class DevicesDialog(QDialog):
    """Estado del sistema: versiones de mpv/ffmpeg, encoders H.264 disponibles, GPU."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"Dispositivos y motores — TVPlayout PRO {APP_VERSION}")
        self.resize(760, 520)
        v = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 11px;")
        v.addWidget(self.text, 1)
        row = QHBoxLayout()
        b = QPushButton("↻ Volver a comprobar")
        b.clicked.connect(self.refresh)
        row.addWidget(b)
        b2 = QPushButton("🧪 Probar encoders (3 frames cada uno)")
        b2.clicked.connect(self.test_encoders)
        row.addWidget(b2)
        row.addStretch()
        c = QPushButton("Cerrar")
        c.clicked.connect(self.accept)
        row.addWidget(c)
        v.addLayout(row)
        self.refresh()

    @staticmethod
    def _run(cmd, timeout=15):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=CREATE_NO_WINDOW)
            return (p.stdout or "") + (p.stderr or "")
        except Exception as e:  # noqa: BLE001
            return f"(error: {e})"

    @staticmethod
    def _mpv_console():
        """mpv.exe (GUI) no escribe en consola; si existe mpv.com al lado, se usa para consultas."""
        if MPV_PATH and MPV_PATH.lower().endswith("mpv.exe"):
            com = MPV_PATH[:-4] + ".com"
            if os.path.isfile(com):
                return com
        return MPV_PATH

    def refresh(self):
        lines = []
        lines.append("=== BINARIOS ===")
        for name, path in (("mpv", MPV_PATH), ("ffmpeg", FFMPEG_PATH), ("ffprobe", FFPROBE_PATH)):
            lines.append(f"{name:8s} {path or 'NO ENCONTRADO'}")
        if MPV_PATH:
            out = self._run([self._mpv_console(), "--version"])
            lines.append("")
            lines.append("=== MPV ===")
            lines.append(out.strip().splitlines()[0] if out.strip() else out)
        if FFMPEG_PATH:
            out = self._run([FFMPEG_PATH, "-hide_banner", "-version"])
            lines.append("")
            lines.append("=== FFMPEG ===")
            lines.extend(out.strip().splitlines()[:2])
            enc = self._run([FFMPEG_PATH, "-hide_banner", "-encoders"])
            lines.append("")
            lines.append("=== ENCODERS H.264 DISPONIBLES ===")
            for codec, label in (("libx264", "CPU/x264"), ("h264_nvenc", "NVIDIA NVENC"), ("h264_qsv", "Intel QSV"),
                                 ("h264_amf", "AMD AMF")):
                ok = bool(re.search(rf"\b{codec}\b", enc))
                lines.append(f"[{'OK' if ok else '--'}] {label:14s} {codec}")
            lines.append("")
            lines.append("=== DISPOSITIVOS DE AUDIO (mpv) ===")
            if MPV_PATH:
                lines.append(self._run([self._mpv_console(), "--audio-device=help"]).strip())
        nv = shutil.which("nvidia-smi")
        lines.append("")
        lines.append("=== GPU ===")
        if nv:
            lines.append(self._run([nv, "-L"]).strip())
        else:
            lines.append("nvidia-smi no disponible (sin GPU NVIDIA o driver no instalado)")
        self.text.setPlainText("\n".join(lines))

    def test_encoders(self):
        if not FFMPEG_PATH:
            QMessageBox.warning(self, "FFmpeg", "FFmpeg no encontrado.")
            return
        results = ["=== PRUEBA DE ENCODERS ==="]
        for codec in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf"):
            cmd = [FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=25",
                   "-frames:v", "3", "-c:v", codec, "-f", "null", "-"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=25, creationflags=CREATE_NO_WINDOW)
                ok = p.returncode == 0
                err = (p.stderr or "").strip().splitlines()
                results.append(f"[{'OK' if ok else 'FALLA'}] {codec}" + ("" if ok else f" → {err[-1] if err else 'error'}"))
            except Exception as e:  # noqa: BLE001
                results.append(f"[FALLA] {codec} → {e}")
        self.text.appendPlainText("\n" + "\n".join(results))
