"""Widgets personalizados: reloj estación, VU meter, superficie de video, indicadores."""
import math
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath, QImage
from PySide6.QtWidgets import QWidget, QLabel, QSizePolicy


def fmt_tc(seconds, show_hours=True, frames=False, fps=25.0):
    """Formatea segundos como HH:MM:SS (o HH:MM:SS.ff)."""
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        seconds = 0
    neg = seconds < 0
    seconds = abs(float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    out = f"{h:02d}:{m:02d}:{s:02d}" if (show_hours or h) else f"{m:02d}:{s:02d}"
    if frames:
        f = int(round((seconds - int(seconds)) * fps)) % max(1, int(round(fps)))
        out += f".{f:02d}"
    return ("-" if neg else "") + out


class StationClock(QWidget):
    """Reloj de estación: anillo de 60 puntos (segundos) + dígitos grandes HH:MM y SS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(200)
        self._accent = QColor("#e5871e")

    def sizeHint(self):
        return QSize(260, 260)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        r = side / 2 - 8
        p.fillRect(self.rect(), QColor("#161616"))
        grad = QRadialGradient(QPointF(cx, cy), r)
        grad.setColorAt(0.0, QColor("#202020"))
        grad.setColorAt(1.0, QColor("#141414"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#0a0a0a"), 2))
        p.drawEllipse(QPointF(cx, cy), r, r)

        now = time.time()
        lt = time.localtime(now)
        sec = lt.tm_sec + (now - int(now))
        # 60 puntos: los ya transcurridos brillan
        for i in range(60):
            ang = math.radians(i * 6 - 90)
            px = cx + math.cos(ang) * (r - 12)
            py = cy + math.sin(ang) * (r - 12)
            lit = i <= int(sec)
            if i % 5 == 0:
                rad = 3.4
                col = QColor("#ffffff") if lit else QColor("#4a4a4a")
            else:
                rad = 2.0
                col = QColor("#d8d8d8") if lit else QColor("#3a3a3a")
            if i == int(sec):
                col = self._accent
                rad += 1.2
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px, py), rad, rad)

        # icono estilo "play" arriba
        p.setPen(QPen(self._accent, 2))
        p.setBrush(Qt.NoBrush)
        icon_r = r * 0.09
        icon_c = QPointF(cx, cy - r * 0.45)
        p.drawEllipse(icon_c, icon_r, icon_r)
        tri = QPainterPath()
        tri.moveTo(icon_c.x() - icon_r * 0.35, icon_c.y() - icon_r * 0.5)
        tri.lineTo(icon_c.x() + icon_r * 0.55, icon_c.y())
        tri.lineTo(icon_c.x() - icon_r * 0.35, icon_c.y() + icon_r * 0.5)
        tri.closeSubpath()
        p.fillPath(tri, self._accent)

        # dígitos
        big = QFont("Consolas")
        big.setStyleHint(QFont.Monospace)
        big.setPixelSize(int(r * 0.42))
        big.setBold(True)
        p.setFont(big)
        p.setPen(QColor("#f5f5f5"))
        rect_big = QRectF(cx - r, cy - r * 0.32, 2 * r, r * 0.5)
        p.drawText(rect_big, Qt.AlignCenter, f"{lt.tm_hour:02d}:{lt.tm_min:02d}")
        small = QFont(big)
        small.setPixelSize(int(r * 0.26))
        p.setFont(small)
        p.setPen(QColor("#dddddd"))
        rect_small = QRectF(cx - r, cy + r * 0.16, 2 * r, r * 0.34)
        p.drawText(rect_small, Qt.AlignCenter, f"{lt.tm_sec:02d}")
        p.end()


class VUMeter(QWidget):
    """VU meter estéreo vertical con escala dBFS, segmentos verde/amarillo/rojo y hold de picos."""

    def __init__(self, parent=None, channels=2):
        super().__init__(parent)
        self.channels = channels
        self._levels = [-90.0] * channels
        self._peaks = [-90.0] * channels
        self._peak_time = [0.0] * channels
        self.setMinimumWidth(34)
        self.setMaximumWidth(48)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._decay = QTimer(self)
        self._decay.timeout.connect(self._tick)
        self._decay.start(50)
        self.setToolTip("Nivel de audio (dBFS) del reproductor local")

    def set_levels(self, *levels):
        now = time.time()
        for i, lv in enumerate(levels[: self.channels]):
            lv = max(-90.0, min(6.0, float(lv)))
            if lv >= self._levels[i]:
                self._levels[i] = lv
            else:
                self._levels[i] = max(lv, self._levels[i] - 2.5)
            if lv >= self._peaks[i]:
                self._peaks[i] = lv
                self._peak_time[i] = now
        self.update()

    def reset(self):
        self._levels = [-90.0] * self.channels
        self._peaks = [-90.0] * self.channels
        self.update()

    def _tick(self):
        now = time.time()
        changed = False
        for i in range(self.channels):
            if self._levels[i] > -90:
                self._levels[i] = max(-90.0, self._levels[i] - 1.2)
                changed = True
            if self._peaks[i] > -90 and now - self._peak_time[i] > 1.2:
                self._peaks[i] = max(-90.0, self._peaks[i] - 0.8)
                changed = True
        if changed:
            self.update()

    @staticmethod
    def _norm(db):
        # -60 dB .. 0 dB → 0..1 (escala cuasi-lineal en dB)
        return max(0.0, min(1.0, (db + 60.0) / 60.0))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0c0c0c"))
        w, h = self.width(), self.height()
        margin_top, margin_bottom = 4, 14
        usable = h - margin_top - margin_bottom
        bar_w = (w - 10) / self.channels
        seg_h = 4
        gap = 1
        n_seg = max(1, int(usable // (seg_h + gap)))
        for ch in range(self.channels):
            x = 5 + ch * bar_w
            lvl = self._norm(self._levels[ch])
            peak = self._norm(self._peaks[ch])
            lit = int(round(lvl * n_seg))
            peak_seg = int(round(peak * n_seg))
            for s in range(n_seg):
                y = margin_top + usable - (s + 1) * (seg_h + gap)
                frac = s / n_seg
                if frac > 0.9:
                    col = QColor("#ff2a2a")
                elif frac > 0.72:
                    col = QColor("#ffd21f")
                else:
                    col = QColor("#35e05a")
                if s >= lit and s != peak_seg - 1:
                    col = QColor(col.red() // 5, col.green() // 5, col.blue() // 5)
                p.fillRect(QRectF(x, y, bar_w - 3, seg_h), col)
        p.setPen(QColor("#9a9a9a"))
        f = QFont()
        f.setPixelSize(8)
        p.setFont(f)
        p.drawText(QRectF(0, h - 12, w / 2, 12), Qt.AlignCenter, "L")
        p.drawText(QRectF(w / 2, h - 12, w / 2, 12), Qt.AlignCenter, "R")
        p.end()


class VideoSurface(QWidget):
    """Superficie de vídeo pintada por frames RGB entregados por PyAV.

    No depende de una ventana hija, IPC, named pipe ni de un ejecutable
    reproductor externo. El frame se recibe mediante una señal Qt y se pinta
    en el hilo de la interfaz, que es el único hilo permitido para tocar
    widgets.
    """

    double_clicked = Signal()
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text = "SIN SEÑAL"
        self._active = False
        self._frame = QImage()
        self._aspect_mode = "auto"

    def set_active(self, active, text=None):
        self._active = bool(active)
        if text is not None:
            self._text = text
        self.update()

    def set_frame(self, frame):
        """Recibe un QImage ya desacoplado de la memoria de PyAV."""
        if frame is None or frame.isNull():
            return
        self._frame = frame
        self._active = True
        self.update()

    def clear_frame(self):
        self._frame = QImage()
        self._active = False
        self.update()

    def set_aspect_mode(self, mode):
        self._aspect_mode = str(mode or "auto")
        self.update()

    def mouseDoubleClickEvent(self, _event):
        self.double_clicked.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._active and not self._frame.isNull():
            mode = Qt.IgnoreAspectRatio if self._aspect_mode == "stretch" else Qt.KeepAspectRatio
            scaled = self._frame.scaled(self.size(), mode, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawImage(x, y, scaled)
            p.end()
            return
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#0b0b0b"))
        g.setColorAt(1, QColor("#050505"))
        p.fillRect(self.rect(), g)
        p.setPen(QColor("#4a4a4a"))
        f = QFont()
        f.setPixelSize(max(12, min(22, self.height() // 10)))
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class LedLabel(QLabel):
    """Etiqueta con propiedad `active` para estilos ON/OFF vía QSS."""

    def __init__(self, text="", parent=None, object_name="onAir"):
        super().__init__(text, parent)
        self.setObjectName(object_name)
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("active", False)

    def set_active(self, active):
        if self.property("active") == bool(active):
            return
        self.setProperty("active", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ProgressBarThin(QWidget):
    """Barra de progreso fina (posición del clip) con marca de remain en rojo al final."""

    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self._value = 0.0
        self._warn_frac = 1.0
        self.setCursor(Qt.PointingHandCursor)

    def set_progress(self, pos, dur):
        self._value = max(0.0, min(1.0, pos / dur)) if dur and dur > 0 else 0.0
        self._warn_frac = max(0.0, 1.0 - (10.0 / dur)) if dur and dur > 10 else 1.0
        self.update()

    def mousePressEvent(self, event):
        if self.width() > 0:
            self.seek_requested.emit(max(0.0, min(1.0, event.position().x() / self.width())))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0a0a"))
        w = self.width()
        fill = int(w * self._value)
        p.fillRect(0, 2, fill, self.height() - 4, QColor("#e5871e"))
        wx = int(w * self._warn_frac)
        p.fillRect(wx, 2, w - wx, self.height() - 4, QColor(200, 30, 30, 120))
        p.setPen(QColor("#000"))
        p.drawRect(0, 0, w - 1, self.height() - 1)
        p.end()
