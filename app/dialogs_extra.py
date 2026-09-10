"""Diálogos adicionales: Logo/CG sobre la salida RTMP y Dispositivos (estado de binarios/encoders/GPU)."""
import os
import re
import shutil
import subprocess

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QLineEdit, QComboBox,
                               QSpinBox, QCheckBox, QFileDialog, QPlainTextEdit, QMessageBox, QWidget,
                               QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView)

from .config import MPV_PATH, VLC_PATH, FFMPEG_PATH, FFMPEG_NDI_PATH, FFPROBE_PATH, ROOT, APP_VERSION, DEFAULT_LOGO_PATH
from .ndi_sender import NDISender

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _prepare_resizable_dialog(dialog, width, height, min_width=480, min_height=340):
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


class LogoSafeAreaPreview(QWidget):
    """Vista previa profesional con guías 16:9 y área central 4:3.

    Las líneas amarillas en 12.5% y 87.5% marcan los límites horizontales
    del área 4:3 dentro de un lienzo 16:9. La misma geometría se aplica en
    ``OutputWorker`` para que la posición real de FFmpeg coincida con esta
    previsualización.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 230)
        self.setStyleSheet("background:#050505;border:1px solid #333;")
        self._pixmap = QPixmap()
        self._position = "arriba-derecha"
        self._scale = 10
        self._margin = 48

    def set_values(self, path, position, scale, margin):
        self._pixmap = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        self._position = position or "arriba-derecha"
        self._scale = max(2, int(scale or 10))
        self._margin = max(0, int(margin or 0))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#050505"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # El lienzo de referencia siempre es 16:9, aunque el widget sea más
        # alto o más ancho para conservar la proporción del monitor.
        frame_w = min(self.width() - 28, (self.height() - 42) * 16 / 9)
        frame_h = frame_w * 9 / 16
        frame = QRectF((self.width() - frame_w) / 2, 22, frame_w, frame_h)
        p.fillRect(frame, QColor("#111820"))
        p.setPen(QPen(QColor("#72c7ff"), 1.5))
        p.drawRect(frame)

        # Guías porcentuales 16:9: centro y extremos del lienzo.
        p.setPen(QPen(QColor(114, 199, 255, 130), 1, Qt.DashLine))
        for pct in (0.0, 0.5, 1.0):
            x = frame.left() + frame.width() * pct
            p.drawLine(x, frame.top(), x, frame.bottom())
            label = "0%" if pct == 0 else ("50%" if pct == 0.5 else "100%")
            p.drawText(int(x - 14), int(frame.bottom() + 16), label)

        # Área 4:3 centrada: 75% del ancho de un canvas 16:9, límites 12.5/87.5.
        safe_left = frame.left() + frame.width() * 0.125
        safe_right = frame.right() - frame.width() * 0.125
        p.setPen(QPen(QColor("#f2c94c"), 1.5, Qt.DashLine))
        p.drawRect(QRectF(safe_left, frame.top(), safe_right - safe_left, frame.height()))
        p.drawLine(safe_left, frame.top(), safe_left, frame.bottom())
        p.drawLine(safe_right, frame.top(), safe_right, frame.bottom())
        p.setPen(QColor("#f2c94c"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(int(safe_left - 18), int(frame.top() - 5), "12.5%")
        p.drawText(int(safe_right - 18), int(frame.top() - 5), "87.5%")
        p.setPen(QColor("#72c7ff"))
        p.drawText(int(frame.left()), 15, "16:9 · 0% — 100%")
        p.setPen(QColor("#f2c94c"))
        p.drawText(int(safe_left + 5), int(frame.bottom() + 16), "4:3 seguro · 12.5% — 87.5%")

        if not self._pixmap.isNull():
            logo_w = max(8.0, frame.width() * self._scale / 100.0)
            logo_h = logo_w * self._pixmap.height() / max(1, self._pixmap.width())
            margin_x = frame.width() * self._margin / 1920.0
            margin_y = frame.height() * self._margin / 1080.0
            x = safe_left + margin_x if "izquierda" in self._position else safe_right - logo_w - margin_x
            y = frame.top() + margin_y if "arriba" in self._position else frame.bottom() - logo_h - margin_y
            logo_rect = QRectF(x, y, logo_w, logo_h)
            p.drawPixmap(logo_rect, self._pixmap, self._pixmap.rect())
        p.end()


class LogoDialog(QDialog):
    """Configura la mosca/logo que FFmpeg superpone en la salida RTMP."""

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Logo / CG en salida RTMP")
        _prepare_resizable_dialog(self, 520, 380, 480, 340)
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
        self.scale.setRange(2, 30)
        self.scale.setSuffix(" % del ancho")
        self.scale.setToolTip("Tamaño profesional recomendado: 8–12 % del ancho de salida")
        self.scale.setValue(int(s.get("logo_scale", 10)))
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(int(s.get("logo_opacity", 90)))
        self.margin = QSpinBox()
        self.margin.setRange(0, 400)
        self.margin.setSuffix(" px")
        self.margin.setToolTip("Margen dentro del área segura 4:3; recomendado: 48 px en 1920x1080")
        self.margin.setValue(int(s.get("logo_margin", 48)))
        self.preview = LogoSafeAreaPreview()
        self.preview.setMinimumHeight(230)
        f.addRow("", self.enabled)
        f.addRow("Archivo", row)
        f.addRow("Posición", self.position)
        f.addRow("Tamaño", self.scale)
        f.addRow("Opacidad", self.opacity)
        f.addRow("Margen", self.margin)
        f.addRow("Vista previa", self.preview)
        note = QLabel("Las guías muestran el lienzo 16:9 y el margen central 4:3 (12.5%–87.5%). "
                      "La posición real queda dentro del área 4:3. Tamaño recomendado para una mosca profesional: 8–12%. "
                      "Se aplica en el siguiente evento RTMP y no afecta al monitor local.")
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
        self.position.currentTextChanged.connect(self._update_preview)
        self.scale.valueChanged.connect(self._update_preview)
        self.margin.valueChanged.connect(self._update_preview)
        self._update_preview()

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Logo", str(ROOT), "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif)")
        if p:
            self.path.setText(p)

    def _update_preview(self):
        self.preview.set_values(self.path.text().strip(), self.position.currentText(),
                                self.scale.value(), self.margin.value())

    def values(self):
        return {"logo_enabled": self.enabled.isChecked(), "logo_path": self.path.text().strip(),
                "logo_position": self.position.currentText(), "logo_scale": self.scale.value(),
                "logo_opacity": self.opacity.value(), "logo_margin": self.margin.value()}


class OutputProfilesDialog(QDialog):
    """Configuración de destinos de distribución RTMP, SRT y NDI."""

    HEADERS = ["Activo", "Nombre", "Protocolo", "Destino"]

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Salidas IP — RTMP / SRT / NDI")
        _prepare_resizable_dialog(self, 820, 560, 560, 380)
        self._profiles = [dict(p) for p in (settings.get("outputs") or [])]
        legacy = str(settings.get("rtmp_url", "") or "").strip()
        if not self._profiles and legacy:
            self._profiles = [{"enabled": True, "name": "RTMP principal", "protocol": "RTMP", "target": legacy}]
        self._edit_row = -1

        root = QVBoxLayout(self)
        # v24.0.2.37: con NDI deshabilitado no se prueba la DLL (evita el
        # reintento ruidoso en equipos sin el Runtime instalado).
        if bool(settings.get("ndi_disabled", True)):
            ndi_ok, ndi_detail, ndi_path = False, "deshabilitado temporalmente en Ajustes", ""
        else:
            ndi_ok, ndi_detail, ndi_path = NDISender.probe()
        ndi_state = (f"NDI directo: DISPONIBLE ({ndi_path})" if ndi_ok
                     else f"NDI directo: NO DISPONIBLE ({ndi_detail})")
        note = QLabel(
            "Cada destino RTMP/SRT usa un proceso FFmpeg independiente y sigue al mismo playout local. "
            "RTMP y SRT son compatibles con OBS y vMix. NDI se publica directamente con el NDI Runtime x64 "
            "instalado en Windows; no requiere ffmpeg-ndi.exe ni el muxer libndi_newtek.\n" + ndi_state
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9a9a9a;")
        root.addWidget(note)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._load_selected)
        root.addWidget(self.table, 1)

        form = QFormLayout()
        self.enabled = QCheckBox("Destino activo")
        self.enabled.setChecked(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("OBS local, vMix estudio, CDN principal…")
        self.protocol = QComboBox()
        self.protocol.addItems(["RTMP", "SRT", "NDI"])
        self.target = QLineEdit()
        self.target.setPlaceholderText("rtmp://host/app/clave")
        self.protocol.currentTextChanged.connect(self._target_hint)
        form.addRow("", self.enabled)
        form.addRow("Nombre", self.name)
        form.addRow("Protocolo", self.protocol)
        form.addRow("URL / nombre NDI", self.target)
        root.addLayout(form)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Añadir destino")
        self.add_btn.clicked.connect(self._add_or_update)
        remove = QPushButton("Eliminar seleccionado")
        remove.clicked.connect(self._remove_selected)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(remove)
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Guardar destinos")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self._refresh_table()
        self._target_hint(self.protocol.currentText())

    def _target_hint(self, protocol):
        hints = {
            "RTMP": "rtmp://host/app/clave  o  rtmps://host/app/clave",
            "SRT": "srt://host:9000?mode=caller&latency=200000",
            "NDI": "Nombre NDI visible en la red, por ejemplo TVPlayout PRO",
        }
        self.target.setPlaceholderText(hints.get(protocol, "Destino"))

    def _refresh_table(self):
        self.table.setRowCount(0)
        for profile in self._profiles:
            row = self.table.rowCount()
            self.table.insertRow(row)
            enabled = QTableWidgetItem("Sí" if profile.get("enabled", True) else "No")
            enabled.setData(Qt.UserRole, bool(profile.get("enabled", True)))
            self.table.setItem(row, 0, enabled)
            self.table.setItem(row, 1, QTableWidgetItem(str(profile.get("name") or "Destino")))
            self.table.setItem(row, 2, QTableWidgetItem(str(profile.get("protocol", "RTMP")).upper()))
            self.table.setItem(row, 3, QTableWidgetItem(str(profile.get("target") or profile.get("url") or "")))

    def _load_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        self._edit_row = row
        profile = self._profiles[row]
        self.enabled.setChecked(bool(profile.get("enabled", True)))
        self.name.setText(str(profile.get("name") or "Destino"))
        self.protocol.setCurrentText(str(profile.get("protocol", "RTMP")).upper())
        self.target.setText(str(profile.get("target") or profile.get("url") or ""))
        self.add_btn.setText("Actualizar destino")

    def _add_or_update(self):
        target = self.target.text().strip()
        name = self.name.text().strip() or self.protocol.currentText()
        if not target:
            QMessageBox.warning(self, "Destino", "Escribe una URL RTMP/SRT o un nombre NDI.")
            return
        profile = {"enabled": self.enabled.isChecked(), "name": name,
                   "protocol": self.protocol.currentText().upper(), "target": target}
        if self._edit_row >= 0 and self._edit_row < len(self._profiles):
            self._profiles[self._edit_row] = profile
        else:
            self._profiles.append(profile)
        self._edit_row = -1
        self._refresh_table()
        self.table.clearSelection()
        self.add_btn.setText("Añadir destino")
        self.name.clear()
        self.target.clear()

    def _remove_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        self._profiles.pop(row)
        self._edit_row = -1
        self._refresh_table()
        self.add_btn.setText("Añadir destino")

    def values(self):
        return [{"enabled": bool(p.get("enabled", True)), "name": str(p.get("name") or "Destino"),
                 "protocol": str(p.get("protocol", "RTMP")).upper(),
                 "target": str(p.get("target") or p.get("url") or "").strip()}
                for p in self._profiles if str(p.get("target") or p.get("url") or "").strip()]

class DevicesDialog(QDialog):
    """Estado del sistema: versiones de mpv/ffmpeg, encoders H.264 disponibles, GPU."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"Dispositivos y motores — TVPlayout PRO {APP_VERSION}")
        _prepare_resizable_dialog(self, 760, 520, 560, 380)
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
        for name, path in (("ffmpeg", FFMPEG_PATH), ("ffmpeg-ndi heredado", FFMPEG_NDI_PATH),
                           ("ffprobe", FFPROBE_PATH), ("mpv (preview)", MPV_PATH),
                           ("vlc (preview alternativo)", VLC_PATH)):
            lines.append(f"{name:18s} {path or 'NO ENCONTRADO'}")
        if bool(getattr(parent, "settings", {}).get("ndi_disabled", True)):
            ndi_ok, ndi_detail, ndi_path = False, "deshabilitado temporalmente en Ajustes", ""
        else:
            ndi_ok, ndi_detail, ndi_path = NDISender.probe()
        lines.append("")
        lines.append("=== NDI DIRECTO (RUNTIME x64) ===")
        lines.append(f"[{'OK' if ndi_ok else '--'}] {ndi_detail}")
        lines.append(f"DLL: {ndi_path or 'NO ENCONTRADA'}")
        lines.append("Ruta NDI: ctypes → Processing.NDI.Lib.x64.dll (sin FFmpeg)")
        lines.append("")
        lines.append("=== CÓMO VERIFICAR LA SALIDA NDI ===")
        lines.append("1) Salidas IP → activa un destino NDI; el estado debe decir «NDI directo activo».")
        lines.append("2) Sin playout local se envía una TARJETA DE PRUEBA con reloj en vivo")
        lines.append("   (si no la ves en el receptor, el problema es Runtime/red, no del playout).")
        lines.append("3) NDI Tools → Studio Monitor: selecciona la fuente (gratis en ndi.video/tools).")
        lines.append("4) OBS necesita el plugin DistroAV (antes obs-ndi); vMix trae NDI integrado")
        lines.append("   (Add Input → NDI). Sin el plugin, OBS NO muestra fuentes NDI.")
        lines.append("5) Si la fuente no aparece: misma red/subred, permitir la app y mDNS (UDP 5353)")
        lines.append("   en el firewall de Windows, y desactivar VPN/adaptadores virtuales.")
        if FFMPEG_NDI_PATH:
            ndi_muxers = self._run([FFMPEG_NDI_PATH, "-hide_banner", "-muxers"])
            lines.append(f"Muxer libndi_newtek heredado: {'OK' if 'libndi_newtek' in ndi_muxers else 'NO'}")
        if MPV_PATH:
            out = self._run([self._mpv_console(), "--version"])
            lines.append("")
            lines.append("=== MPV ===")
            lines.append(out.strip().splitlines()[0] if out.strip() else out)
        if VLC_PATH:
            out = self._run([VLC_PATH, "--version"])
            lines.append("")
            lines.append("=== VLC ===")
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
