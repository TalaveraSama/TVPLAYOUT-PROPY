"""Ventana principal — consola de playout con distribución tipo XPlayout.

Columna izquierda: cabecera (título/reloj/fecha), transporte, contadores, modos, grid de playlist
(+ modo gráfico + biblioteca) y botonera. Columna derecha: VU + preview, funciones, salida RTMP,
reloj de estación y bloqueo.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QBrush, QPixmap, QKeySequence, QShortcut, QPalette, QPainter, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
                               QTabWidget, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QSlider,
                               QMessageBox, QFileDialog, QInputDialog, QMenu, QStackedWidget, QFrame, QSizePolicy,
                               QRadioButton, QButtonGroup,
                               QDialog)

from . import logger
from .config import (DB_PATH, MPV_PATH, FFMPEG_PATH, FFMPEG_NDI_PATH, FFPROBE_PATH, APP_NAME, APP_VERSION, APP_ICON_PATH, VIDEO_EXTS,
                     AUDIO_PREFS, category_color)
from .db import DB
from .scanner import Scanner
from .prober import ProbeWorker
from .pyav_player import PyAVPlayer
from .output import MultiOutputManager
from .tmdb import TMDBLookupWorker, build_movie_overlay
from .scheduler import SchedulerService
from .playout import (PlayoutController, make_item, ST_ONAIR, ST_READY, ST_AIRED, ST_CUT, ST_ERROR, ST_SKIPPED,
                      ST_PENDING, DONE_STATES)
from .widgets import StationClock, VUMeter, VideoSurface, LedLabel, ProgressBarThin, fmt_tc
from .dialogs import (PlaylistManagerDialog, SourcesDialog, SchedulerDialog, LogsDialog, SettingsDialog, EditClipDialog)
from .theme import QSS

log = logger.get("ui")

DAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

COLS = ["#", "Día", "Hora", "Hora real", "Duración", "Categoría", "Título", "Estado", "Fija", "Archivo", "Formato"]
C_NUM, C_DAY, C_TIME, C_REAL, C_DUR, C_CAT, C_TITLE, C_STATUS, C_FIXED, C_PATH, C_FMT = range(len(COLS))

STATUS_LABEL = {ST_PENDING: "", ST_READY: "LISTO", ST_ONAIR: "AL AIRE", ST_AIRED: "EMITIDO", ST_CUT: "CORTADO",
                ST_ERROR: "ERROR", ST_SKIPPED: "OMITIDO"}

DEFAULT_SETTINGS = {
    "rtmp_url": "", "outputs": [], "resolution": "1920x1080", "fps": "29.97", "encoder": "AUTO", "bitrate": 6000, "audio_bitrate": 192,
    "subtitle_burn": True, "ffmpeg_extra": "", "rtmp_autostart": False, "rtmp_mode": "local",
    "audio_pref": AUDIO_PREFS[0], "sub_pref": "OFF", "hwdec": "auto-safe", "audio_device": "",
    "autofill_category": "Todas", "autofill_count": 10, "tandas_category": "Publicidad", "tandas_count": 2,
    "midroll_enabled": False, "midroll_category": "Publicidad", "midroll_interval_minutes": 15,
    "identifiers_enabled": False, "identifier_in_path": "", "identifier_out_path": "",
    "tmdb_enabled": False, "tmdb_api_key": "", "tmdb_interval_minutes": 18, "tmdb_duration_seconds": 15,
    "restore_playlist": True, "autoplay": False, "probe_on_scan": True,
    "mode": "auto", "loop": True, "exact_time": True, "autofill": False, "tandas": False, "autoscroll": True,
    "volume": 100, "muted": False, "emergency_clip": "", "splitter": [1120, 430],
    "logo_enabled": False, "logo_path": "", "logo_position": "arriba-derecha", "logo_scale": 10, "logo_opacity": 90,
    "logo_margin": 48,
    # v23.3: filler automático. Cuando se acaba la lista, se carga el
    # clip de filler en loop infinito para que el monitor nunca quede
    # en negro. Si no hay filler configurado, se muestra un slate
    # estático generado con lavfi (texto "TVPlayout PRO — Próximamente").
    "filler_path": "", "filler_enabled": True,
}


def _btn(text, slot=None, name=None, tip=None, checkable=False):
    b = QPushButton(text)
    if slot:
        b.clicked.connect(slot)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    if checkable:
        b.setCheckable(True)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def _lbl(text="", name=None, align=None):
    l = QLabel(text)
    if name:
        l.setObjectName(name)
    if align is not None:
        l.setAlignment(align)
    return l


def _field(title, name="fieldValue", width=110):
    """Bloque «NOMBRE / valor» como los contadores de XPlayout."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(1)
    t = _lbl(title, "fieldName", Qt.AlignCenter)
    val = _lbl("--:--:--", name, Qt.AlignCenter)
    val.setMinimumWidth(width)
    v.addWidget(t)
    v.addWidget(val)
    return w, val


def _panel(name="panel"):
    w = QWidget()
    w.setObjectName(name)
    return w


def _section(title):
    return _lbl(title, "sectionTitle")


def _hline():
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.HLine)
    return f


class PlaylistGrid(QTableWidget):
    """Grid con soporte de arrastrar archivos desde el explorador."""

    def __init__(self, on_files, parent=None):
        super().__init__(0, len(COLS), parent)
        self._on_files = on_files
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            row = self.rowAt(int(e.position().y()))
            self._on_files(paths, row if row >= 0 else None)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        if APP_ICON_PATH:
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Broadcast Playout")
        self.resize(1600, 920)
        self.setMinimumSize(1280, 720)
        self.db = DB(DB_PATH)
        self.db.close_open_air_logs()
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update({k: v for k, v in self.db.all_settings().items() if k in DEFAULT_SETTINGS})
        self.scanner = None
        self.prober = None
        self.output = None
        self._locked = False
        self._last_rtmp_line = ""
        self._start_times = []
        self._lib_rows = []
        self._building = False
        self._current_thumb = ""
        self._dialogs = {}
        self._tmdb_worker = None
        self._tmdb_request_id = 0
        self._tmdb_overlay_path = ""

        self._build()
        self.player = PyAVPlayer(self.video, MPV_PATH, self)
        self.player.status.connect(self._status)
        self.player.levels.connect(self.vu.set_levels)
        self.ctrl = PlayoutController(self.db, self.player, self)
        self.ctrl.items_changed.connect(self.rebuild_grid)
        self.ctrl.item_changed.connect(self.update_row)
        self.ctrl.onair_changed.connect(self._onair_changed)
        self.ctrl.cue_changed.connect(lambda _i: self.update_next_label())
        self.ctrl.position.connect(self._position)
        self.ctrl.message.connect(self._status)
        self.ctrl.playlist_end.connect(self._playlist_end)
        self.ctrl.on_start_callbacks.append(self._rtmp_follow)
        self.ctrl.on_start_callbacks.append(self._tmdb_follow)
        self.ctrl.items_changed.connect(self._rtmp_sync_structure)
        # v22.1: sincronizar pausa y seek del playout con el RTMP.
        self.ctrl.paused_changed = getattr(self.ctrl, "paused_changed", None)
        # Crear la señal en el controlador si no existe (no se importa aquí para
        # no acoplar; el controlador emite message y position; el cambio de
        # pausa lo detectamos comparando estado).
        self._last_paused_state = False
        self._rtmp_sync_timer = QTimer(self)
        self._rtmp_sync_timer.setInterval(400)
        self._rtmp_sync_timer.timeout.connect(self._rtmp_tick_pause)
        self._rtmp_sync_timer.start()
        # v22.2.1: watcher de drift entre el playout local (mpv) y la salida
        # RTMP (FFmpeg). FFmpeg re-encodea y se desfasa progresivamente
        # respecto del mpv local; cada 2s comparamos y, si la diferencia
        # supera el umbral, realineamos reiniciando FFmpeg con el offset
        # correcto. El umbral default es 2.0s.
        # Tolerar el arranque/reconexión de FFmpeg: con NVENC y filtros
        # subtitles/logo la primera lectura puede tardar varios segundos.
        self._rtmp_drift_threshold = 6.0
        self._rtmp_drift_bad_count = 0
        self._rtmp_drift_last_restart = 0.0
        self._rtmp_drift_timer = QTimer(self)
        self._rtmp_drift_timer.setInterval(2000)
        self._rtmp_drift_timer.timeout.connect(self._rtmp_check_drift)
        self._rtmp_drift_timer.start()
        # Para evitar realineamientos espurios justo después de un seek/pause.
        self._rtmp_drift_suspend_until = 0.0
        self.scheduler = SchedulerService(self.db, self)
        self.scheduler.triggered.connect(self._scheduled_run)
        self.scheduler.status.connect(self._status)
        self.scheduler.start()

        self.apply_settings(first=True)
        self.refresh_categories()
        self.refresh_library()
        if self.settings.get("restore_playlist", True):
            n = self.ctrl.restore_current()
            if n:
                self._status(f"Playlist restaurada • {n} eventos")
        self.rebuild_grid()
        self._shortcuts()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._tick_ui)
        self.ui_timer.start(500)
        self._tick_ui()
        self._status(f"PyAV: {'OK' if self.player.available else 'NO INSTALADO'} • Preview mpv: {'OK' if MPV_PATH else 'NO'} • "
                     f"FFmpeg: {'OK' if FFMPEG_PATH else 'NO ENCONTRADO'} • ffprobe: {'OK' if FFPROBE_PATH else 'NO'} • "
                     f"Biblioteca: {self.db.count_media()} medios")
        log.info("%s %s iniciado con PyAV/libav", APP_NAME, APP_VERSION)
        QTimer.singleShot(800, self._autostart)

    # ================================================================== UI
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)
        self.splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(self.splitter)
        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        sizes = self.settings.get("splitter") or [1120, 430]
        try:
            self.splitter.setSizes([int(x) for x in sizes])
        except (TypeError, ValueError):
            self.splitter.setSizes([1120, 430])
        self.statusBar().showMessage("Listo")
        # v22.2.6: indicador permanente de errores/warnings recientes.
        # Se actualiza en _tick_ui. Click para abrir el dialog de logs.
        from PySide6.QtGui import QFont
        from . import logger as _logger
        self._logs_status = QLabel("Logs: 0")
        self._logs_status.setStyleSheet("padding: 0 8px; color: #b0bec5;")
        f = QFont()
        f.setBold(True)
        self._logs_status.setFont(f)
        self._logs_status.setCursor(Qt.PointingHandCursor)
        self._logs_status.mousePressEvent = lambda _e: self.open_logs()
        self.statusBar().addPermanentWidget(self._logs_status)

    # ---------------------------------------------------------------- left
    def _build_left(self):
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(5)

        # ---- cabecera
        head = _panel()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 4, 10, 4)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(_lbl(APP_NAME, "appTitle"))
        title_box.addWidget(_lbl(f"{APP_VERSION} • Broadcast Playout • Continuidad 24/7", "appSub"))
        hl.addLayout(title_box)
        hl.addStretch()
        self.fps_chip = _lbl("", "statusChip", Qt.AlignCenter)
        hl.addWidget(self.fps_chip)
        self.clock = _lbl("00:00:00", "fieldValue", Qt.AlignCenter)
        self.clock.setStyleSheet("font-size: 24px; padding: 2px 14px; min-width: 150px;")
        hl.addWidget(self.clock)
        hl.addStretch()
        self.date_lbl = _lbl("", "dateLabel", Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(self.date_lbl)
        lv.addWidget(head)

        # ---- transporte
        tr = _panel()
        tl = QHBoxLayout(tr)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(8)
        self.play_btn = _btn("▶", self.on_play, "transport", "PLAY (F1) — emitir siguiente / reanudar")
        self.play_btn.setCheckable(True)
        tl.addWidget(self.play_btn)
        self.thumb = _lbl("", "thumb", Qt.AlignCenter)
        self.thumb.setFixedSize(112, 63)
        self._set_thumb("")
        tl.addWidget(self.thumb)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.clip_title = _lbl("Sin evento al aire", "clipTitle")
        self.clip_title.setMinimumWidth(240)
        self.clip_path = _lbl("", "clipPath")
        self.clip_info = _lbl("", "clipInfo")
        for w in (self.clip_title, self.clip_path, self.clip_info):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.clip_title)
        info.addWidget(self.clip_path)
        info.addWidget(self.clip_info)
        self.progress = ProgressBarThin()
        self.progress.seek_requested.connect(self.ctrl_seek)
        info.addWidget(self.progress)
        tl.addLayout(info, 1)
        self.onair_led = LedLabel("ON-AIR")
        self.onair_led.setFixedWidth(84)
        tl.addWidget(self.onair_led)
        self.pause_btn = _btn("❚❚", self.on_pause, "transportPause", "PAUSA local (F2)")
        self.pause_btn.setCheckable(True)
        self.stop_btn = _btn("■", self.on_stop, "transport", "STOP (F3)")
        self.next_btn = _btn("▶▏", self.on_next, "transport", "SIGUIENTE (F4) — saltar al próximo evento")
        for b in (self.pause_btn, self.stop_btn, self.next_btn):
            tl.addWidget(b)
        lv.addWidget(tr)

        # ---- contadores
        cnt = _panel()
        cl = QHBoxLayout(cnt)
        cl.setContentsMargins(8, 4, 8, 6)
        cl.setSpacing(10)
        self.cue_btn = _btn("▲ Preparar\nsiguiente", self.on_cue, "gridBtn", "Marca la fila seleccionada como siguiente evento (F5)")
        cl.addWidget(self.cue_btn)
        w, self.f_cat = _field("CATEGORÍA", "fieldValue", 120)
        cl.addWidget(w)
        w, self.f_dur = _field("DURACIÓN")
        cl.addWidget(w)
        w, self.f_pos = _field("POSICIÓN")
        cl.addWidget(w)
        w, self.f_rem = _field("RESTANTE", "fieldValueAccent")
        cl.addWidget(w)
        w, self.f_plrem = _field("RESTA PLAYLIST")
        cl.addWidget(w)
        w, self.f_delay = _field("DESFASE", "fieldValue", 90)
        cl.addWidget(w)
        w, self.f_codec = _field("CODEC", "fieldValue", 90)
        cl.addWidget(w)
        cl.addStretch()
        nxt = QVBoxLayout()
        nxt.setSpacing(1)
        nxt.addWidget(_lbl("SIGUIENTE", "fieldName", Qt.AlignLeft))
        self.next_lbl = _lbl("—", "fieldValueGreen")
        self.next_lbl.setStyleSheet("font-size: 12px;")
        self.next_lbl.setMinimumWidth(220)
        nxt.addWidget(self.next_lbl)
        cl.addLayout(nxt)
        lv.addWidget(cnt)

        # ---- modos
        modes = _panel()
        ml = QHBoxLayout(modes)
        ml.setContentsMargins(8, 4, 8, 4)
        ml.setSpacing(6)
        self.autofill_btn = _btn("Autofill", self._modes_changed, "modeBtn", "Al terminar la playlist, rellena automáticamente con medios de la categoría configurada", True)
        self.tandas_btn = _btn("Tandas auto", self._modes_changed, "modeBtn", "Inserta anuncios (categoría Publicidad) después de cada evento", True)
        self.midroll_btn = _btn("Tanda intermedia", self._modes_changed, "IntermedioBtn", "Interrumpe Películas/Música según el intervalo configurado y reanuda desde el mismo segundo", True)
        self.exact_btn = _btn("Hora exacta", self._modes_changed, "modeBtn", "Los eventos con hora fija (⏰) cortan lo que esté al aire a su hora", True)
        self.loop_btn = _btn("Loop", self._modes_changed, "modeBtn", "Repetir la playlist al terminar", True)
        self.autoscroll_btn = _btn("Autoscroll", self._modes_changed, "modeBtn", "Seguir el evento al aire en la grid", True)
        for b in (self.autofill_btn, self.tandas_btn, self.midroll_btn, self.exact_btn, self.loop_btn, self.autoscroll_btn):
            ml.addWidget(b)
        ml.addStretch()
        ml.addWidget(_lbl("Modo:", "fieldName"))
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("modeCombo")
        self.mode_combo.addItem("Automático", "auto")
        self.mode_combo.addItem("Manual", "manual")
        self.mode_combo.currentIndexChanged.connect(self._modes_changed)
        ml.addWidget(self.mode_combo)
        self.pl_summary = _lbl("", "statusChip")
        ml.addWidget(self.pl_summary)
        lv.addWidget(modes)

        # ---- pestañas: grid / gráfico / biblioteca
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.grid = PlaylistGrid(self._files_dropped)
        self.grid.setHorizontalHeaderLabels(COLS)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setAlternatingRowColors(False)
        self.grid.verticalHeader().setVisible(False)
        self.grid.verticalHeader().setDefaultSectionSize(22)
        self.grid.setShowGrid(True)
        self.grid.setWordWrap(False)
        hh = self.grid.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(False)
        widths = {C_NUM: 34, C_DAY: 52, C_TIME: 70, C_REAL: 70, C_DUR: 74, C_CAT: 88, C_STATUS: 72, C_FIXED: 52, C_FMT: 110}
        for c, w in widths.items():
            self.grid.setColumnWidth(c, w)
        hh.setSectionResizeMode(C_TITLE, QHeaderView.Stretch)
        hh.setSectionResizeMode(C_PATH, QHeaderView.Interactive)
        self.grid.setColumnWidth(C_PATH, 220)
        self.grid.itemDoubleClicked.connect(lambda it: self.take_row(it.row()))
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.itemSelectionChanged.connect(self._grid_selection_changed)
        self.tabs.addTab(self.grid, "GRID MODE")

        self.graphic = QListWidget()
        self.graphic.setViewMode(QListWidget.IconMode)
        self.graphic.setIconSize(QSize(160, 90))
        self.graphic.setResizeMode(QListWidget.Adjust)
        self.graphic.setMovement(QListWidget.Static)
        self.graphic.setSpacing(8)
        self.graphic.setWordWrap(True)
        self.graphic.setUniformItemSizes(True)
        self.graphic.setGridSize(QSize(184, 150))
        self.graphic.itemDoubleClicked.connect(lambda it: self.take_row(self.graphic.row(it)))
        self.graphic.currentRowChanged.connect(self._graphic_selected)
        self.tabs.addTab(self.graphic, "GRAPHIC MODE")

        self.tabs.addTab(self._build_library(), "BIBLIOTECA")
        self.tabs.currentChanged.connect(self._tab_changed)
        lv.addWidget(self.tabs, 1)

        # ---- botoneras (stack: playlist / biblioteca)
        self.bottom = QStackedWidget()
        self.bottom.addWidget(self._build_playlist_buttons())
        self.bottom.addWidget(self._build_library_buttons())
        lv.addWidget(self.bottom)
        return left

    def _build_playlist_buttons(self):
        w = _panel()
        g = QGridLayout(w)
        g.setContentsMargins(6, 5, 6, 5)
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(4)
        row1 = [("📄 Insertar archivo…", self.insert_files, "Añade archivos de vídeo directamente (también puedes arrastrarlos a la grid)"),
                ("📚 Biblioteca", lambda: self.tabs.setCurrentIndex(2), "Abrir la biblioteca para añadir medios"),
                ("⏏ Preparar", self.on_cue, "Marcar como siguiente (F5)"),
                ("✎ Editar clip", self.edit_selected, "Título, categoría, hora fija, pistas"),
                ("▲ Subir", lambda: self.move_selected(-1), "Ctrl+↑"),
                ("🗑 Quitar", self.remove_selected, "Supr"),
                ("🧹 Limpiar emitidos", self.clear_aired, "Quita de la grid los eventos ya emitidos"),
                ("🎯 Ir al aire", self.scroll_to_onair, "Desplazar la grid hasta el evento al aire")]
        row2 = [("⏰ Hora fija…", self.set_fixed_time, "Fija la hora de inicio del evento seleccionado"),
                ("↺ Reiniciar estados", self.reset_statuses, "Marca todos los eventos como pendientes"),
                ("⧉ Duplicar", self.duplicate_selected, None),
                ("▼ Bajar", lambda: self.move_selected(1), "Ctrl+↓"),
                ("🗑 Vaciar playlist", self.clear_playlist, None),
                ("👁 Previsualizar", self.preview_selected, "Abre el clip en una ventana mpv aparte, sin afectar al aire"),
                ("🔀 Mezclar pendientes", self.shuffle_pending, "Orden aleatorio de los eventos pendientes"),
                ("💾 Playlist Manager", self.open_playlist_manager, None)]
        self._pl_buttons = []
        for r, row in enumerate((row1, row2)):
            for c, (text, slot, tip) in enumerate(row):
                b = _btn(text, slot, "gridBtn", tip)
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                g.addWidget(b, r, c)
                self._pl_buttons.append(b)
        return w

    def _build_library(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Buscar título, archivo o carpeta…")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_library)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        top.addWidget(self.search, 1)
        self.category = QComboBox()
        self.category.setMinimumWidth(150)
        self.category.currentIndexChanged.connect(lambda _i: self.refresh_library())
        top.addWidget(self.category)
        self.lib_status = _lbl("", "statusChip")
        top.addWidget(self.lib_status)
        v.addLayout(top)
        self.library = QTableWidget(0, 5)
        self.library.setHorizontalHeaderLabels(["Título", "Duración", "Categoría", "Formato", "Archivo"])
        self.library.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.library.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.library.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.library.verticalHeader().setVisible(False)
        self.library.verticalHeader().setDefaultSectionSize(22)
        self.library.setAlternatingRowColors(True)
        self.library.setWordWrap(False)
        lh = self.library.horizontalHeader()
        lh.setSectionResizeMode(0, QHeaderView.Stretch)
        lh.setSectionResizeMode(4, QHeaderView.Interactive)
        self.library.setColumnWidth(1, 80)
        self.library.setColumnWidth(2, 100)
        self.library.setColumnWidth(3, 130)
        self.library.setColumnWidth(4, 300)
        self.library.itemDoubleClicked.connect(lambda _it: self.add_library_selected("end"))
        self.library.setContextMenuPolicy(Qt.CustomContextMenu)
        self.library.customContextMenuRequested.connect(self._library_menu)
        v.addWidget(self.library, 1)
        return w

    def _build_library_buttons(self):
        w = _panel()
        g = QGridLayout(w)
        g.setContentsMargins(6, 5, 6, 5)
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(4)
        row1 = [("➕ Añadir al final", lambda: self.add_library_selected("end"), "Doble clic también añade al final"),
                ("⤵ Insertar tras el aire", lambda: self.add_library_selected("after_onair"), "Se emitirá a continuación del evento actual"),
                ("⤵ Insertar en selección", lambda: self.add_library_selected("at_selection"), "Antes de la fila seleccionada en la grid"),
                ("▶ Emitir ahora", lambda: self.add_library_selected("now"), "Corta lo que esté al aire y emite este medio"),
                ("👁 Previsualizar", self.preview_library, "Ventana mpv aparte"),
                ("↩ Volver a la playlist", lambda: self.tabs.setCurrentIndex(0), None)]
        row2 = [("🔄 Escanear fuentes", self.start_scan, "Escanea las carpetas configuradas en Fuentes"),
                ("🧪 Analizar metadatos", self.start_probe, "Duración, resolución, pistas y miniaturas con ffprobe"),
                ("🏷 Cambiar categoría", self.change_library_category, None),
                ("🎲 Añadir aleatorios…", self.add_random, "Añade N medios al azar de la categoría filtrada"),
                ("📁 Fuentes / Categorías", self.open_sources, None),
                ("🗑 Quitar de biblioteca", self.remove_from_library, "No borra el archivo del disco")]
        self._lib_buttons = []
        for r, row in enumerate((row1, row2)):
            for c, (text, slot, tip) in enumerate(row):
                b = _btn(text, slot, "gridBtn", tip)
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                g.addWidget(b, r, c)
                self._lib_buttons.append(b)
        return w

    # --------------------------------------------------------------- right
    def _build_right(self):
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(5)

        # ---- monitor
        mon = _panel("panelDark")
        mv = QVBoxLayout(mon)
        mv.setContentsMargins(6, 6, 6, 6)
        mv.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.vu = VUMeter()
        row.addWidget(self.vu)
        self.video = VideoSurface()
        self.video.setMinimumHeight(190)
        row.addWidget(self.video, 1)
        mv.addLayout(row, 1)
        ctr = QHBoxLayout()
        ctr.setSpacing(6)
        self.mute_btn = _btn("🔊 Audio local", self.toggle_mute, "modeBtn", "Silencia SOLO el monitor local; la salida RTMP conserva el audio", True)
        ctr.addWidget(self.mute_btn)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(self.settings.get("volume", 100)))
        self.vol.setToolTip("Volumen del monitor local")
        self.vol.valueChanged.connect(self._volume_changed)
        ctr.addWidget(self.vol, 1)
        ctr.addWidget(_lbl("Aspecto", "fieldName"))
        self.aspect = QComboBox()
        self.aspect.setObjectName("modeCombo")
        self.aspect.addItem("Auto", "-1")
        self.aspect.addItem("16:9", "16:9")
        self.aspect.addItem("4:3", "4:3")
        self.aspect.currentIndexChanged.connect(lambda _i: self.player.set_property("video-aspect-override", self.aspect.currentData()) if hasattr(self, "player") else None)
        ctr.addWidget(self.aspect)
        mv.addLayout(ctr)
        rv.addWidget(mon, 3)

        # ---- funciones
        fn = _panel()
        fv = QVBoxLayout(fn)
        fv.setContentsMargins(0, 0, 0, 6)
        fv.setSpacing(4)
        fv.addWidget(_section("FUNCIONES"))
        g = QGridLayout()
        g.setContentsMargins(6, 0, 6, 0)
        g.setSpacing(4)
        funcs = [("Playlist\nManager", self.open_playlist_manager), ("Biblioteca", lambda: self.tabs.setCurrentIndex(2)),
                 ("Programador", self.open_scheduler), ("Registros\nAs-Run", self.open_logs),
                 ("Fuentes /\nCategorías", self.open_sources), ("Ajustes del\nsistema", self.open_settings),
                 ("Salidas IP\nRTMP/SRT/NDI", self.open_outputs), ("Escanear\nbiblioteca", self.start_scan),
                 ("Logo / CG\n(RTMP)", self.open_logo), ("Dispositivos", self.open_devices)]
        self._fn_buttons = []
        for i, (text, slot) in enumerate(funcs):
            b = _btn(text, slot, "funcBtn")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            g.addWidget(b, i // 3, i % 3)
            self._fn_buttons.append(b)
        self.emergency_btn = _btn("🚨 EMERGENCIA", self.emergency, "danger", "Emite inmediatamente el clip de emergencia configurado")
        self.emergency_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        g.addWidget(self.emergency_btn, (len(funcs) + 2) // 3, 0, 1, 3)
        fv.addLayout(g)
        rv.addWidget(fn)

        # ---- RTMP
        out = _panel()
        ov = QVBoxLayout(out)
        ov.setContentsMargins(0, 0, 0, 6)
        ov.setSpacing(4)
        ov.addWidget(_section("SALIDAS IP · RTMP / SRT / NDI"))
        # La configuración de URLs/nombres y el activar/desactivar de cada
        # destino viven en OutputProfilesDialog. En la pantalla principal
        # dejamos únicamente un monitor de estado, para no editar destinos
        # accidentalmente durante el aire.
        self.rtmp_url = QLineEdit(self.settings.get("rtmp_url", ""))
        self.rtmp_url.setPlaceholderText("rtmp://servidor/app/clave")
        self.rtmp_url.editingFinished.connect(lambda: self._save_setting("rtmp_url", self.rtmp_url.text().strip()))
        self.rtmp_url.setVisible(False)

        # Se conservan como estado interno para compatibilidad y para que el
        # modo remoto se pueda guardar, pero ya no se muestran en el monitor.
        self.rtmp_mode_group = QButtonGroup(self)
        self.rtmp_mode_local = QRadioButton("Solo monitor local", self)
        self.rtmp_mode_remote = QRadioButton("Salidas IP activas", self)
        self.rtmp_mode_group.addButton(self.rtmp_mode_local)
        self.rtmp_mode_group.addButton(self.rtmp_mode_remote)
        initial_mode = self.settings.get("rtmp_mode", "local")
        (self.rtmp_mode_remote if initial_mode == "remote" else self.rtmp_mode_local).setChecked(True)
        self.rtmp_mode_group.buttonClicked.connect(self._rtmp_mode_changed)
        self.rtmp_mode_local.setVisible(False)
        self.rtmp_mode_remote.setVisible(False)

        r2 = QHBoxLayout()
        r2.setContentsMargins(6, 0, 6, 0)
        self.rtmp_chip = LedLabel("OFF", object_name="rtmpChip")
        self.rtmp_chip.setMinimumWidth(120)
        self.rtmp_chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        r2.addWidget(self.rtmp_chip, 1)
        # Referencia heredada: el control de activación está en cada perfil.
        self.rtmp_btn = _btn("", lambda: None, None, "")
        self.rtmp_btn.setVisible(False)
        ov.addLayout(r2)

        self.rtmp_destinations = _lbl("Abre Salidas IP para configurar destinos", "clipInfo")
        self.rtmp_destinations.setContentsMargins(6, 0, 6, 0)
        self.rtmp_destinations.setWordWrap(True)
        ov.addWidget(self.rtmp_destinations)
        self.rtmp_info = _lbl("", "clipInfo")
        self.rtmp_info.setContentsMargins(6, 0, 6, 0)
        self.rtmp_info.setWordWrap(True)
        ov.addWidget(self.rtmp_info)
        rv.addWidget(out)

        # ---- reloj + bloqueo
        clk = _panel("panelDark")
        cv = QVBoxLayout(clk)
        cv.setContentsMargins(6, 6, 6, 6)
        cv.setSpacing(4)
        self.station_clock = StationClock()
        cv.addWidget(self.station_clock, 1)
        br = QHBoxLayout()
        self.lock_btn = _btn("🔓 Bloquear consola", self.toggle_lock, "lockBtn", "Bloquea botones para evitar cambios accidentales (Ctrl+L)", True)
        br.addWidget(self.lock_btn)
        br.addStretch()
        br.addWidget(_btn("_", self.showMinimized, "winMin", "Minimizar"))
        br.addWidget(_btn("✕", self.close, "winClose", "Salir"))
        cv.addLayout(br)
        rv.addWidget(clk, 4)
        return right

    def _shortcuts(self):
        for key, slot in (("F1", self.on_play), ("F2", self.on_pause), ("F3", self.on_stop), ("F4", self.on_next),
                          ("F5", self.on_cue), ("Ctrl+L", self.lock_btn.click), ("Ctrl+F", self._focus_search),
                          ("Ctrl+Up", lambda: self.move_selected(-1)), ("Ctrl+Down", lambda: self.move_selected(1)),
                          ("F11", self.toggle_fullscreen)):
            QShortcut(QKeySequence(key), self, activated=slot)
        QShortcut(QKeySequence(Qt.Key_Delete), self.grid, activated=self.remove_selected)
        QShortcut(QKeySequence(Qt.Key_Return), self.library, activated=lambda: self.add_library_selected("end"))

    # ============================================================= settings
    def _save_setting(self, key, value):
        self.settings[key] = value
        self.db.set_setting(key, value)

    def apply_settings(self, first=False):
        s = self.settings
        self.ctrl.audio_pref = s.get("audio_pref", AUDIO_PREFS[0])
        self.ctrl.sub_pref = s.get("sub_pref", "OFF")
        self.ctrl.autofill_category = s.get("autofill_category", "Todas")
        self.ctrl.autofill_count = int(s.get("autofill_count", 10))
        self.ctrl.tandas_category = s.get("tandas_category", "Publicidad")
        self.ctrl.tandas_count = int(s.get("tandas_count", 2))
        self.ctrl.midroll_category = s.get("midroll_category", "Publicidad")
        self.ctrl.midroll_interval_minutes = max(1, int(s.get("midroll_interval_minutes", 15)))
        self.ctrl.identifiers_enabled = bool(s.get("identifiers_enabled", False))
        self.ctrl.identifier_in_path = str(s.get("identifier_in_path", "") or "")
        self.ctrl.identifier_out_path = str(s.get("identifier_out_path", "") or "")
        # v24: la activación de la tanda intermedia es independiente de la
        # tanda al finalizar el evento.
        # v23.3: filler automático. El operador configura el path a un
        # clip de filler en settings (filler_path). Si está vacío, se usa
        # el slate lavfi. Si filler_enabled es False, no se carga nada
        # y el playout queda con monitor en negro al acabar (legacy).
        self.ctrl.filler_path = str(s.get("filler_path", "") or "")
        # filler_enabled: si está en False, el playout NO carga filler
        # ni slate — comportamiento legacy (monitor en negro).
        self.player.hwdec = s.get("hwdec", "auto-safe")
        self.player.audio_device = s.get("audio_device", "")
        pref = s.get("audio_pref", "")
        alang = "es-MX,es-419,spa,es,esp" if pref.upper().startswith("AUTO") else ("" if pref == "Original" else pref)
        sub = s.get("sub_pref", "OFF")
        slang = "" if sub.upper() == "OFF" else ("es-MX,spa-MX,es-419,spa,es" if sub.upper().startswith("AUTO") else sub)
        self.player.set_track_langs(alang, slang)
        # Se puede activar desde Ajustes o desde el botón independiente de
        # modos; ambos controles deben reflejar el mismo valor persistido.
        self.midroll_btn.blockSignals(True)
        self.midroll_btn.setChecked(bool(s.get("midroll_enabled", False)))
        self.midroll_btn.blockSignals(False)
        if first:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(1 if s.get("mode") == "manual" else 0)
            self.mode_combo.blockSignals(False)
            for b, key in ((self.loop_btn, "loop"), (self.exact_btn, "exact_time"), (self.autofill_btn, "autofill"),
                           (self.tandas_btn, "tandas"), (self.midroll_btn, "midroll_enabled"), (self.autoscroll_btn, "autoscroll")):
                b.blockSignals(True)
                b.setChecked(bool(s.get(key)))
                b.blockSignals(False)
            # v22.1: aplicar volumen y mute al mpv real (no sólo al atributo Python).
            # Si mpv no está corriendo todavía, los valores se guardan en el atributo
            # y se aplican en el primer play() (ver MPVPlayer.play).
            vol = int(s.get("volume", 100))
            muted = bool(s.get("muted", False))
            self.player.volume = vol
            self.player.muted = muted
            self.vol.blockSignals(True)
            self.vol.setValue(vol)
            self.vol.blockSignals(False)
            self.mute_btn.setChecked(muted)
            self.mute_btn.setText("🔇 Local silenciado" if muted else "🔊 Audio local")
            if self.player.running:
                self.player.set_volume(vol)
                self.player.set_mute(muted)
            self._modes_changed()
        self.rtmp_url.setText(s.get("rtmp_url", ""))
        self._refresh_output_monitor()

    def _modes_changed(self, *_a):
        self.ctrl.mode = self.mode_combo.currentData() or "auto"
        self.ctrl.loop = self.loop_btn.isChecked()
        self.ctrl.exact_time = self.exact_btn.isChecked()
        self.ctrl.autofill = self.autofill_btn.isChecked()
        self.ctrl.tandas = self.tandas_btn.isChecked()
        self.ctrl.midroll_enabled = self.midroll_btn.isChecked()
        for key, val in (("mode", self.ctrl.mode), ("loop", self.ctrl.loop), ("exact_time", self.ctrl.exact_time),
                         ("autofill", self.ctrl.autofill), ("tandas", self.ctrl.tandas),
                         ("midroll_enabled", self.ctrl.midroll_enabled), ("autoscroll", self.autoscroll_btn.isChecked())):
            if self.settings.get(key) != val:
                self._save_setting(key, val)

    def _autostart(self):
        if self.settings.get("autoplay") and self.ctrl.items and not self.ctrl.is_on_air:
            self.ctrl.play_next("auto")
        if self.settings.get("rtmp_autostart") and self.ctrl.items and not self.output:
            self._rtmp_start()

    # ============================================================= library
    def refresh_categories(self):
        cur = self.category.currentText() if self.category.count() else "Todas"
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Todas")
        self.category.addItems(self.db.categories())
        idx = self.category.findText(cur)
        self.category.setCurrentIndex(idx if idx >= 0 else 0)
        self.category.blockSignals(False)

    def refresh_library(self):
        if not hasattr(self, "library"):
            return
        rows = self.db.search_media(self.search.text(), self.category.currentText() if self.category.count() else "Todas")
        self._lib_rows = rows
        self.library.setUpdatesEnabled(False)
        self.library.setRowCount(len(rows))
        for i, r in enumerate(rows):
            d = dict(r)
            fmt = f"{d.get('width') or ''}x{d.get('height') or ''} {d.get('video_codec') or ''}".strip(" x") if d.get("width") else (d.get("video_codec") or "")
            vals = [d["title"], fmt_tc(d.get("duration") or 0) if d.get("duration") else "", d["category"], fmt, d["path"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1:
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 2:
                    it.setForeground(QBrush(QColor(category_color(d["category"]))))
                if c == 0 and d.get("probe_error"):
                    it.setForeground(QBrush(QColor("#ff7070")))
                    it.setToolTip("ffprobe: " + d["probe_error"])
                self.library.setItem(i, c, it)
        self.library.setUpdatesEnabled(True)
        total, probed, failed = self.db.media_stats()
        self.lib_status.setText(f"{len(rows)} mostrados • {total} en biblioteca • {probed} analizados" + (f" • {failed} con error" if failed else ""))

    def _selected_library_items(self):
        rows = sorted({i.row() for i in self.library.selectedIndexes()})
        return [make_item(self._lib_rows[r]) for r in rows if r < len(self._lib_rows)]

    def add_library_selected(self, where="end"):
        if self._locked:
            return
        items = self._selected_library_items()
        if not items:
            self._status("Selecciona uno o más medios en la biblioteca")
            return
        self._insert_items(items, where)

    def _insert_items(self, items, where="end"):
        if where == "after_onair" and self.ctrl.is_on_air:
            n = self.ctrl.insert_items(self.ctrl.onair + 1, items)
        elif where == "at_selection":
            sel = self._selected_rows()
            n = self.ctrl.insert_items(sel[0] if sel else len(self.ctrl.items), items)
        elif where == "now":
            idx = self.ctrl.onair + 1 if self.ctrl.is_on_air else (self._selected_rows() or [len(self.ctrl.items)])[0]
            n = self.ctrl.insert_items(idx, items)
            if n:
                self.ctrl.play_index(idx, "manual")
        else:
            n = self.ctrl.append_items(items)
        self._status(f"{n} evento(s) añadido(s) a la playlist")
        return n

    def preview_library(self):
        items = self._selected_library_items()
        if items:
            self.player.open_external_preview(items[0]["path"])

    def change_library_category(self):
        items = self._selected_library_items()
        if not items:
            return
        cat, ok = QInputDialog.getItem(self, "Categoría", f"Nueva categoría para {len(items)} medio(s):", self.db.categories(), 0, False)
        if ok:
            for it in items:
                self.db.set_media_category(it["path"], cat)
            self.refresh_library()

    def remove_from_library(self):
        items = self._selected_library_items()
        if items and QMessageBox.question(self, "Biblioteca", f"¿Quitar {len(items)} medio(s) de la biblioteca? (no borra archivos)") == QMessageBox.Yes:
            for it in items:
                self.db.delete_media(it["path"])
            self.refresh_library()

    def add_random(self):
        n, ok = QInputDialog.getInt(self, "Añadir aleatorios", "Cantidad:", 10, 1, 500)
        if not ok:
            return
        cat = self.category.currentText() if self.category.count() else "Todas"
        rows = self.db.random_media(cat, n, exclude_paths=[i["path"] for i in self.ctrl.items])
        if not rows:
            self._status("No hay medios en esa categoría")
            return
        self.ctrl.append_items([make_item(r) for r in rows])
        self._status(f"{len(rows)} medios aleatorios añadidos ({cat})")
        self.tabs.setCurrentIndex(0)

    def _library_menu(self, pos):
        m = QMenu(self)
        m.addAction("➕ Añadir al final", lambda: self.add_library_selected("end"))
        m.addAction("⤵ Insertar tras el aire", lambda: self.add_library_selected("after_onair"))
        m.addAction("▶ Emitir ahora", lambda: self.add_library_selected("now"))
        m.addSeparator()
        m.addAction("👁 Previsualizar", self.preview_library)
        m.addAction("🏷 Cambiar categoría…", self.change_library_category)
        m.addAction("📂 Abrir carpeta", lambda: self._open_folder(self._selected_library_items()))
        m.addSeparator()
        m.addAction("🗑 Quitar de biblioteca", self.remove_from_library)
        m.exec(self.library.viewport().mapToGlobal(pos))

    def _open_folder(self, items):
        if not items:
            return
        p = items[0]["path"]
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", p])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(p)])
        except OSError as e:
            self._status(str(e))

    def _focus_search(self):
        self.tabs.setCurrentIndex(2)
        self.search.setFocus()
        self.search.selectAll()

    # --------------------------------------------------------------- scan
    def start_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self._status("Deteniendo escaneo…")
            return
        src = self.db.sources()
        if not src:
            if QMessageBox.question(self, "Fuentes", "No hay carpetas configuradas. ¿Abrir Fuentes / Categorías?") == QMessageBox.Yes:
                self.open_sources()
            return
        self.tabs.setCurrentIndex(2)
        self.lib_status.setText("ESCANEANDO…")
        self.scanner = Scanner(self.db, src)
        self.scanner.progress.connect(lambda f, files, media: self.lib_status.setText(f"Escaneando • carpetas {f} • archivos {files} • medios {media}"))
        self.scanner.error.connect(self._status)
        self.scanner.finished_count.connect(self._scan_done)
        self.scanner.start()
        log.info("Escaneo iniciado (%d fuentes)", len(src))

    def _scan_done(self, files, media):
        self.refresh_library()
        self._status(f"Escaneo finalizado • {files} archivos • {media} medios")
        log.info("Escaneo finalizado: %d archivos, %d medios", files, media)
        if self.settings.get("probe_on_scan", True) and FFPROBE_PATH:
            self.start_probe()

    def start_probe(self):
        if self.prober and self.prober.isRunning():
            self.prober.stop()
            self._status("Deteniendo análisis…")
            return
        if not FFPROBE_PATH:
            QMessageBox.warning(self, "ffprobe", "No se encontró ffprobe.exe. Colócalo junto a ffmpeg.exe en la raíz del proyecto.")
            return
        total, probed, failed = self.db.media_stats()
        pending = total - probed - failed
        if pending <= 0:
            if failed and QMessageBox.question(self, "Analizar", f"Todo analizado. {failed} con error: ¿reintentarlos?") == QMessageBox.Yes:
                self.db.reset_probe_errors()
            else:
                self._status("Biblioteca ya analizada")
                return
        self.prober = ProbeWorker(self.db, make_thumbs=bool(FFMPEG_PATH))
        self.prober.progress.connect(lambda done, left: self.lib_status.setText(f"Analizando metadatos • {done} listos • {left} pendientes"))
        self.prober.updated.connect(self.ctrl.refresh_meta_from_db)
        self.prober.finished_all.connect(lambda n: (self.refresh_library(), self._status(f"Análisis finalizado • {n} medios"), self.rebuild_grid()))
        self.prober.start()
        self._status("Analizando metadatos en segundo plano…")

    # ================================================================ grid
    def _selected_rows(self):
        return sorted({i.row() for i in self.grid.selectedIndexes()})

    def rebuild_grid(self):
        self._building = True
        sel = set(self._selected_rows())
        scroll = self.grid.verticalScrollBar().value()
        self.grid.setUpdatesEnabled(False)
        self._start_times = self.ctrl.compute_times()
        items = self.ctrl.items
        self.grid.setRowCount(len(items))
        for r, it in enumerate(items):
            self._fill_row(r, it, self._start_times[r] if r < len(self._start_times) else None)
        self.grid.setUpdatesEnabled(True)
        self.grid.verticalScrollBar().setValue(scroll)
        if sel:
            self.grid.blockSignals(True)
            for r in sel:
                if r < len(items):
                    for c in range(len(COLS)):
                        cell = self.grid.item(r, c)
                        if cell:
                            cell.setSelected(True)
            self.grid.blockSignals(False)
        self._rebuild_graphic()
        self._building = False
        self.update_next_label()
        self._update_summary()

    def _fill_row(self, r, it, start):
        onair = r == self.ctrl.onair
        status = it.get("status", "")
        if onair:
            bg, fg = QColor("#2f63c5"), QColor("#ffffff")
        elif status == ST_READY:
            bg, fg = QColor("#b39cf5"), QColor("#140a2a")
        elif status in DONE_STATES:
            bg, fg = QColor("#3a3a3a"), QColor("#9a9a9a")
        else:
            bg, fg = QColor(category_color(it.get("category", ""))), QColor("#111111")
        if it.get("late") and status not in DONE_STATES and not onair:
            fg = QColor("#7a0000")
        d = start
        vals = [str(r + 1),
                f"{d.day:02d}/{d.month:02d}" if d else "",
                d.strftime("%H:%M:%S") if d else "",
                it["aired_at"].strftime("%H:%M:%S") if it.get("aired_at") else "",
                fmt_tc(it.get("duration") or 0) if it.get("duration") else "--:--:--",
                it.get("category", ""),
                it.get("title", ""),
                STATUS_LABEL.get(status, status) + (f" • {it['note']}" if it.get("note") and status in (ST_ERROR,) else ""),
                (it.get("fixed_time") or "") + (" !" if it.get("late") and status not in DONE_STATES else ""),
                it.get("path", ""),
                (f"{it.get('width')}x{it.get('height')} {it.get('video_codec') or ''}".strip() if it.get("width") else (it.get("video_codec") or ""))]
        bold = onair or status == ST_READY
        for c, v in enumerate(vals):
            cell = self.grid.item(r, c)
            if cell is None:
                cell = QTableWidgetItem()
                self.grid.setItem(r, c, cell)
            if cell.text() != v:
                cell.setText(v)
            cell.setBackground(QBrush(bg))
            cell.setForeground(QBrush(fg))
            f = cell.font()
            if f.bold() != bold:
                f.setBold(bold)
                cell.setFont(f)
            if c in (C_NUM, C_TIME, C_REAL, C_DUR, C_STATUS, C_FIXED, C_DAY):
                cell.setTextAlignment(Qt.AlignCenter)
        tip = it.get("path", "")
        if it.get("note"):
            tip += f"\n{it['note']}"
        self.grid.item(r, C_TITLE).setToolTip(tip)

    def update_row(self, r):
        if 0 <= r < len(self.ctrl.items) and r < self.grid.rowCount():
            self._start_times = self.ctrl.compute_times()
            self._fill_row(r, self.ctrl.items[r], self._start_times[r] if r < len(self._start_times) else None)
            self._update_graphic_item(r)
        self.update_next_label()
        self._update_summary()

    def _update_times(self):
        items = self.ctrl.items
        if not items or self.grid.rowCount() != len(items):
            return
        self._start_times = self.ctrl.compute_times()
        for r, it in enumerate(items):
            d = self._start_times[r] if r < len(self._start_times) else None
            cell_t = self.grid.item(r, C_TIME)
            cell_d = self.grid.item(r, C_DAY)
            if cell_t is None or cell_d is None:
                continue
            t = d.strftime("%H:%M:%S") if d else ""
            dd = f"{d.day:02d}/{d.month:02d}" if d else ""
            if cell_t.text() != t:
                cell_t.setText(t)
            if cell_d.text() != dd:
                cell_d.setText(dd)
            late_mark = (it.get("fixed_time") or "") + (" !" if it.get("late") and it.get("status") not in DONE_STATES else "")
            cf = self.grid.item(r, C_FIXED)
            if cf is not None and cf.text() != late_mark:
                cf.setText(late_mark)

    def _update_summary(self):
        items = self.ctrl.items
        total = sum((i.get("duration") or 0) for i in items)
        pend = sum(1 for i in items if i.get("status") in (ST_PENDING, ST_READY))
        self.pl_summary.setText(f"{len(items)} eventos • {pend} pendientes • {fmt_tc(total)}")

    def _grid_selection_changed(self):
        if self._building:
            return
        rows = self._selected_rows()
        if rows and self.graphic.currentRow() != rows[0]:
            self.graphic.blockSignals(True)
            self.graphic.setCurrentRow(rows[0])
            self.graphic.blockSignals(False)

    def _graphic_selected(self, row):
        if self._building or row < 0:
            return
        self.grid.blockSignals(True)
        self.grid.selectRow(row)
        self.grid.blockSignals(False)

    def _rebuild_graphic(self):
        self.graphic.blockSignals(True)
        self.graphic.clear()
        for r, it in enumerate(self.ctrl.items):
            li = QListWidgetItem()
            self.graphic.addItem(li)
            self._update_graphic_item(r, li)
        self.graphic.blockSignals(False)

    def _update_graphic_item(self, r, li=None):
        li = li or self.graphic.item(r)
        if li is None or r >= len(self.ctrl.items):
            return
        it = self.ctrl.items[r]
        d = self._start_times[r] if r < len(self._start_times) else None
        li.setText(f"{r + 1}. {it.get('title', '')[:40]}\n{d.strftime('%H:%M:%S') if d else '--:--:--'} • {fmt_tc(it.get('duration') or 0)}")
        li.setIcon(self._thumb_icon(it))
        status = it.get("status")
        if r == self.ctrl.onair:
            li.setBackground(QBrush(QColor("#2f63c5")))
            li.setForeground(QBrush(QColor("#fff")))
        elif status == ST_READY:
            li.setBackground(QBrush(QColor("#5a4a8a")))
            li.setForeground(QBrush(QColor("#fff")))
        elif status in DONE_STATES:
            li.setBackground(QBrush(QColor("#2a2a2a")))
            li.setForeground(QBrush(QColor("#8a8a8a")))
        else:
            li.setBackground(QBrush(QColor("#181818")))
            li.setForeground(QBrush(QColor("#e6e6e6")))
        li.setToolTip(it.get("path", ""))

    def _thumb_icon(self, it):
        from PySide6.QtGui import QIcon
        pm = self._thumb_pixmap(it, 160, 90)
        return QIcon(pm)

    def _thumb_pixmap(self, it, w, h):
        pm = None
        thumb = it.get("thumb") or ""
        if thumb and os.path.isfile(thumb):
            pm = QPixmap(thumb)
            if not pm.isNull():
                return pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap(w, h)
        pm.fill(QColor("#000"))
        p = QPainter(pm)
        p.fillRect(0, 0, w, h, QColor(category_color(it.get("category", ""))).darker(260))
        p.setPen(QColor("#dcdcdc"))
        f = QFont()
        f.setPixelSize(max(9, h // 7))
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect().adjusted(4, 4, -4, -4), Qt.AlignCenter | Qt.TextWordWrap, (it.get("category") or "VIDEO").upper())
        p.end()
        return pm

    def _set_thumb(self, path, item=None):
        if item is None:
            pm = QPixmap(112, 63)
            pm.fill(QColor("#000"))
            self.thumb.setPixmap(pm)
            self._current_thumb = ""
            return
        key = item.get("thumb") or item.get("category", "")
        if key == self._current_thumb:
            return
        self._current_thumb = key
        self.thumb.setPixmap(self._thumb_pixmap(item, 112, 63))

    def _grid_menu(self, pos):
        row = self.grid.rowAt(pos.y())
        m = QMenu(self)
        if row >= 0:
            m.addAction("▶ Emitir ahora", lambda: self.take_row(row))
            m.addAction("⏏ Preparar como siguiente", self.on_cue)
            m.addSeparator()
            m.addAction("✎ Editar clip…", self.edit_selected)
            m.addAction("⏰ Hora fija…", self.set_fixed_time)
            m.addAction("⧉ Duplicar", self.duplicate_selected)
            m.addAction("👁 Previsualizar", self.preview_selected)
            m.addAction("📂 Abrir carpeta", lambda: self._open_folder([self.ctrl.items[row]]))
            m.addSeparator()
            m.addAction("🗑 Quitar", self.remove_selected)
        m.addAction("📄 Insertar archivo…", self.insert_files)
        m.addAction("🧹 Limpiar emitidos", self.clear_aired)
        m.addAction("🗑 Vaciar playlist", self.clear_playlist)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _files_dropped(self, paths, row):
        items = []
        for p in paths:
            if os.path.isdir(p):
                for base, _dirs, names in os.walk(p):
                    for n in sorted(names):
                        if Path(n).suffix.lower() in VIDEO_EXTS:
                            items.append(self._item_from_file(os.path.join(base, n)))
            elif Path(p).suffix.lower() in VIDEO_EXTS:
                items.append(self._item_from_file(p))
        if not items:
            self._status("No se soltaron archivos de vídeo válidos")
            return
        n = self.ctrl.insert_items(row if row is not None else len(self.ctrl.items), items)
        self._status(f"{n} archivo(s) añadidos")

    def _item_from_file(self, path):
        row = self.db.media_by_path(path)
        if row:
            return make_item(row)
        item = make_item({"path": path, "title": Path(path).stem, "category": "Otros"})
        if FFPROBE_PATH:
            try:
                from .prober import probe_file
                info = probe_file(path, timeout=10)
                item.update({k: info[k] for k in ("duration", "width", "height", "fps", "video_codec", "audio_codec", "tracks")})
                item["source_duration"] = item.get("duration") or 0
            except Exception as e:  # noqa: BLE001
                log.info("probe rápido falló para %s: %s", path, e)
        return item

    def insert_files(self):
        if self._locked:
            return
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Insertar archivos", "", f"Vídeo ({exts});;Todos (*.*)")
        if paths:
            sel = self._selected_rows()
            self._files_dropped(paths, sel[0] if sel else None)

    def _tab_changed(self, idx):
        self.bottom.setCurrentIndex(1 if idx == 2 else 0)

    # ---------------------------------------------------------- acciones grid
    def take_row(self, row):
        if self._locked:
            self._status("Consola bloqueada")
            return
        if 0 <= row < len(self.ctrl.items) and row != self.ctrl.onair:
            self.ctrl.play_index(row, "manual")

    def on_cue(self):
        if self._locked:
            return
        rows = self._selected_rows()
        if not rows:
            self._status("Selecciona una fila para prepararla")
            return
        if rows[0] == self.ctrl.cue:
            self.ctrl.set_cue(-1)
        else:
            self.ctrl.set_cue(rows[0])

    def edit_selected(self):
        if self._locked:
            return
        rows = self._selected_rows()
        if not rows:
            return
        it = self.ctrl.items[rows[0]]
        d = EditClipDialog(self, it, self.db.categories())
        if d.exec() == QDialog.Accepted:
            self.ctrl.update_item(rows[0], **d.values())

    def set_fixed_time(self):
        if self._locked:
            return
        rows = self._selected_rows()
        if not rows:
            return
        it = self.ctrl.items[rows[0]]
        text, ok = QInputDialog.getText(self, "Hora fija", "Hora de inicio (HH:MM o HH:MM:SS), vacío para quitar:", text=it.get("fixed_time", ""))
        if not ok:
            return
        text = text.strip()
        if text:
            from .playout import parse_fixed_time
            if parse_fixed_time(text, datetime.now()) is None:
                QMessageBox.warning(self, "Hora fija", "Formato inválido.")
                return
        self.ctrl.update_item(rows[0], fixed_time=text)

    def move_selected(self, delta):
        if self._locked:
            return
        rows = self._selected_rows()
        if not rows:
            return
        order = rows if delta < 0 else list(reversed(rows))
        new_rows = []
        for r in order:
            new_rows.append(self.ctrl.move(r, delta))
        self.grid.blockSignals(True)
        self.grid.clearSelection()
        for r in new_rows:
            for c in range(len(COLS)):
                cell = self.grid.item(r, c)
                if cell:
                    cell.setSelected(True)
        self.grid.setCurrentCell(new_rows[0], C_TITLE)
        self.grid.blockSignals(False)

    def remove_selected(self):
        if self._locked:
            return
        rows = self._selected_rows()
        if not rows:
            return
        if self.ctrl.onair in rows:
            self._status("No se puede quitar el evento AL AIRE")
        n = self.ctrl.remove_indices(rows)
        if n:
            self._status(f"{n} evento(s) quitados")
            nr = min(rows[0], self.grid.rowCount() - 1)
            if nr >= 0:
                self.grid.selectRow(nr)

    def duplicate_selected(self):
        if self._locked:
            return
        rows = self._selected_rows()
        if rows:
            self.ctrl.duplicate(rows[0])

    def clear_aired(self):
        if self._locked:
            return
        n = self.ctrl.clear_aired()
        self._status(f"{n} eventos emitidos eliminados de la grid")

    def clear_playlist(self):
        if self._locked:
            return
        if not self.ctrl.items:
            return
        if QMessageBox.question(self, "Vaciar", "¿Vaciar la playlist?" + (" El evento al aire se mantiene." if self.ctrl.is_on_air else "")) == QMessageBox.Yes:
            self.ctrl.clear()

    def reset_statuses(self):
        if self._locked:
            return
        self.ctrl.reset_statuses()

    def shuffle_pending(self):
        if self._locked:
            return
        import random
        items = self.ctrl.items
        start = (self.ctrl.onair + 1) if self.ctrl.is_on_air else 0
        pend_idx = [i for i in range(start, len(items)) if items[i]["status"] in (ST_PENDING, ST_READY)]
        if len(pend_idx) < 2:
            return
        chunk = [items[i] for i in pend_idx]
        random.shuffle(chunk)
        for i, it in zip(pend_idx, chunk):
            items[i] = it
        self.ctrl.set_cue(-1)
        self.ctrl.items_changed.emit()
        self.ctrl._mark_dirty()

    def preview_selected(self):
        rows = self._selected_rows()
        if rows:
            self.player.open_external_preview(self.ctrl.items[rows[0]]["path"])

    def scroll_to_onair(self):
        if self.ctrl.onair >= 0:
            self.grid.scrollToItem(self.grid.item(self.ctrl.onair, C_TITLE), QAbstractItemView.PositionAtCenter)
            self.tabs.setCurrentIndex(0)

    # ============================================================ transporte
    def on_play(self):
        if self._locked:
            self._status("Consola bloqueada")
            return
        if self.ctrl.is_on_air and self.ctrl.paused:
            self.ctrl.toggle_pause()
            self.pause_btn.setChecked(False)
            return
        if self.ctrl.is_on_air:
            self._status("Ya hay un evento AL AIRE • usa SIGUIENTE (F4) o doble clic sobre otro evento")
            return
        if not self.ctrl.items:
            self._status("Playlist vacía • añade medios desde la biblioteca")
            self.tabs.setCurrentIndex(2)
            return
        rows = self._selected_rows()
        if self.ctrl.cue < 0 and rows and self.ctrl.items[rows[0]]["status"] in (ST_PENDING, ST_READY):
            self.ctrl.play_index(rows[0], "manual")
        else:
            if not self.ctrl.play_next("manual"):
                self._status("No hay eventos pendientes • Reiniciar estados o añadir medios")

    def on_pause(self):
        if self._locked:
            return
        paused = self.ctrl.toggle_pause()
        self.pause_btn.setChecked(bool(paused))

    def on_stop(self):
        if self._locked:
            return
        self.ctrl.stop()
        self.pause_btn.setChecked(False)
        if self.output and self.output.isRunning():
            self.output.stop()
            self._status("STOP • salida RTMP detenida")

    def on_next(self):
        if self._locked:
            return
        if not self.ctrl.play_next("manual"):
            self._status("No hay siguiente evento")

    def ctrl_seek(self, frac):
        if self._locked:
            return
        self.ctrl.seek_fraction(frac)
        # v22.1: replicar el seek al RTMP (FFmpeg se reinicia con el offset
        # correspondiente). Sólo si el playout está al aire.
        if self.output and self.output.isRunning() and self.ctrl.is_on_air:
            self.output.seek_to(self.ctrl.onair, self.ctrl.elapsed)
            # v22.2.1: suspender el watcher de drift 3s para no realinear
            # mientras FFmpeg está reconectando.
            self._rtmp_drift_bad_count = 0
            self._rtmp_drift_suspend_until = time.time() + 8.0

    def toggle_mute(self):
        muted = self.mute_btn.isChecked()
        self.player.set_mute(muted)
        self.mute_btn.setText("🔇 Local silenciado" if muted else "🔊 Audio local")
        self._save_setting("muted", muted)
        if muted:
            self.vu.reset()

    def _volume_changed(self, v):
        # v22.1: debounce de 80ms — arrastrar el slider rápido ya no satura el
        # IPC ni compite con loadfile/seek en curso. El último valor gana.
        self.settings["volume"] = v
        self.player.volume = v   # sincroniza atributo para que play() lo re-aplique
        if self.player.running:
            if not hasattr(self, "_vol_debounce") or self._vol_debounce is None:
                self._vol_debounce = QTimer(self)
                self._vol_debounce.setSingleShot(True)
                self._vol_debounce.timeout.connect(self._apply_volume)
            self._vol_debounce.start(80)
        QTimer.singleShot(800, lambda: self.db.set_setting("volume", self.settings["volume"]))

    def _apply_volume(self):
        if self.player.running:
            self.player.set_volume(self.settings["volume"])

    def toggle_lock(self):
        self._locked = self.lock_btn.isChecked()
        self.lock_btn.setText("🔒 CONSOLA BLOQUEADA" if self._locked else "🔓 Bloquear consola")
        for b in (self.play_btn, self.pause_btn, self.stop_btn, self.next_btn, self.cue_btn, self.emergency_btn, self.rtmp_btn,
                  self.autofill_btn, self.tandas_btn, self.exact_btn, self.loop_btn, self.mode_combo, *self._pl_buttons, *self._lib_buttons):
            b.setEnabled(not self._locked)
        self._status("Consola bloqueada" if self._locked else "Consola desbloqueada")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def emergency(self):
        if self._locked:
            return
        clip = self.settings.get("emergency_clip", "")
        if not clip or not os.path.isfile(clip):
            exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))
            clip, _ = QFileDialog.getOpenFileName(self, "Clip de emergencia (se recordará)", "", f"Vídeo ({exts})")
            if not clip:
                return
            self._save_setting("emergency_clip", clip)
        item = self._item_from_file(clip)
        item["title"] = "🚨 " + item["title"]
        item["note"] = "emergencia"
        idx = self.ctrl.onair + 1 if self.ctrl.is_on_air else 0
        self.ctrl.insert_items(idx, [item])
        self.ctrl.play_index(idx, "emergency")
        log.warning("EMERGENCIA: %s", clip)

    # ------------------------------------------------------- señales playout
    def _onair_changed(self, idx):
        onair = idx >= 0
        is_slate = idx == -2
        self.onair_led.set_active(onair or is_slate)
        self.play_btn.setChecked(onair or is_slate)
        self.video.set_active(False if is_slate else onair,
                              "TVPlayout PRO\\nPROXIMAMENTE" if is_slate else ("" if onair else "SIN SEÑAL"))
        if not onair:
            self.pause_btn.setChecked(False)
            self.clip_title.setText("Sin evento al aire")
            self.clip_path.setText("")
            self.clip_info.setText("")
            self._set_thumb("")
            for f in (self.f_dur, self.f_pos, self.f_rem):
                f.setText("--:--:--")
            self.f_cat.setText("—")
            self.f_codec.setText("—")
            self.f_delay.setText("—")
            self.progress.set_progress(0, 0)
            self.vu.reset()
        else:
            it = self.ctrl.items[idx]
            self.clip_title.setText(it["title"])
            self.clip_path.setText(it["path"])
            tracks = it.get("tracks") or []
            na = sum(1 for t in tracks if t.get("type") == "a")
            ns = sum(1 for t in tracks if t.get("type") == "s")
            self.clip_info.setText(f"{it.get('video_codec') or '?'} {it.get('width') or '?'}x{it.get('height') or '?'} "
                                   f"{it.get('fps') or '?'} fps • {it.get('audio_codec') or '?'} • {na} audio / {ns} subs"
                                   + (f" • ⏰ {it['fixed_time']}" if it.get("fixed_time") else ""))
            self.f_cat.setText(it.get("category", "") or "—")
            self.f_codec.setText((it.get("video_codec") or "—").upper())
            self.f_dur.setText(fmt_tc(it.get("duration") or 0))
            self._set_thumb(it.get("thumb", ""), it)
            self._delay_field(it)
        self.rebuild_grid()
        if onair and self.autoscroll_btn.isChecked():
            QTimer.singleShot(50, self.scroll_to_onair)

    def _delay_field(self, it):
        """DESFASE: diferencia entre la hora real de inicio y la hora fija del evento (si la tiene)."""
        ft = it.get("fixed_time")
        aired = it.get("aired_at")
        if ft and aired:
            from .playout import parse_fixed_time
            target = parse_fixed_time(ft, aired)
            if target:
                diff = (aired - target).total_seconds()
                self.f_delay.setText(("+" if diff >= 0 else "-") + fmt_tc(abs(diff)))
                self.f_delay.setStyleSheet("color:#ff6060;" if diff > 60 else ("color:#4be36a;" if abs(diff) <= 60 else ""))
                return
        self.f_delay.setStyleSheet("")
        self.f_delay.setText("—")

    def _position(self, pos, dur):
        self.f_pos.setText(fmt_tc(pos))
        self.f_dur.setText(fmt_tc(dur) if dur else "--:--:--")
        rem = max(0.0, dur - pos) if dur else 0.0
        self.f_rem.setText(fmt_tc(rem) if dur else "--:--:--")
        if rem <= 10 and dur:
            self.f_rem.setStyleSheet("color:#ff4040; background:#2a0000;")
        elif self.f_rem.styleSheet():
            self.f_rem.setStyleSheet("")
        self.progress.set_progress(pos, dur)

    def update_next_label(self):
        nxt = self.ctrl.next_index()
        if nxt is None:
            self.next_lbl.setText("— (fin de playlist" + (" • loop" if self.ctrl.loop else "") + (" • autofill" if self.ctrl.autofill else "") + ")")
        else:
            it = self.ctrl.items[nxt]
            self.next_lbl.setText(f"{nxt + 1}. {it['title']}  [{fmt_tc(it.get('duration') or 0)}]" + ("  ⏏" if nxt == self.ctrl.cue else ""))

    def _playlist_end(self):
        if self.output and self.output.isRunning():
            self.output.stop()
            self._status("FIN DE PLAYLIST • salidas IP detenidas (activa Loop o Autofill para continuidad)")

    def _scheduled_run(self, schedule, rows):
        items = [make_item(r) for r in rows]
        if not items:
            self._status(f"PROGRAMADO • {schedule['name']} • sin medios")
            return
        self.ctrl.replace_playlist(items, start=True, reason=f"programador:{schedule['name']}")
        # v22.1: tras un replace_playlist, el RTMP debe saltar a la nueva lista
        # en el índice 0 (no al clip anterior). _rtmp_sync_structure sólo se
        # llama con items_changed antes de play_index(0), momento en el que
        # onair sigue siendo -1; por eso re-sincronizamos explícitamente aquí.
        if self.output and self.output.isRunning():
            self.output.sync_items(self.ctrl.export_items(), 0, force_jump=True)
        self._status(f"PROGRAMADO • {schedule['name']} • {len(items)} eventos • LOCAL + SALIDAS IP")
        log.info("Programación %s aplicada: %d eventos", schedule["name"], len(items))

    # ================================================================= RTMP
    def toggle_rtmp(self):
        """v22.2.2: compat — ya no se llama desde la UI, los radios
        (_rtmp_mode_changed) son la nueva forma de prender/apagar. Se
        conserva para no romper nada que aún lo invoque. Prende o apaga
        según el estado actual."""
        if self._locked:
            return
        if self.output and self.output.isRunning():
            self._rtmp_stop()
        else:
            mode = "remote" if self.rtmp_mode_remote.isChecked() else "local"
            if mode == "remote":
                self._rtmp_start()

    def _rtmp_mode_changed(self, _btn=None):
        """v22.2.2: el usuario cambió el modo RTMP. Persistir y actuar."""
        if self.rtmp_mode_remote.isChecked():
            new_mode = "remote"
        else:
            new_mode = "local"
        self._save_setting("rtmp_mode", new_mode)
        log.info("RTMP mode → %s", new_mode)
        # Si estamos pasando de "remote" a "local" con el RTMP activo, parar.
        if new_mode == "local" and self.output and self.output.isRunning():
            self._rtmp_stop()
        # Si estamos pasando a "remote" y no hay RTMP activo, arrancar.
        elif new_mode == "remote" and (not self.output or not self.output.isRunning()):
            self._rtmp_start()

    def _output_profiles(self):
        """Devuelve destinos nuevos y convierte la URL única antigua."""
        profiles = []
        for profile in self.settings.get("outputs") or []:
            if not isinstance(profile, dict) or not profile.get("enabled", True):
                continue
            target = str(profile.get("target") or profile.get("url") or "").strip()
            if target:
                profiles.append({"enabled": True, "name": str(profile.get("name") or profile.get("protocol", "RTMP")),
                                 "protocol": str(profile.get("protocol", "RTMP")).upper(), "target": target})
        if not profiles:
            legacy = self.rtmp_url.text().strip() or str(self.settings.get("rtmp_url", "")).strip()
            if legacy:
                protocol = "SRT" if legacy.lower().startswith("srt://") else "RTMP"
                profiles.append({"enabled": True, "name": f"{protocol} principal", "protocol": protocol, "target": legacy})
        return profiles

    def _rtmp_start(self):
        """Arranca todos los destinos IP habilitados en paralelo."""
        if self._locked:
            return
        profiles = self._output_profiles()
        if not profiles:
            QMessageBox.warning(self, "Salidas IP", "Configura al menos un destino RTMP, SRT o NDI en Salidas IP.")
            self.rtmp_mode_local.setChecked(True)
            return
        self._save_setting("outputs", profiles)
        needs_ffmpeg = any(str(p.get("protocol", "RTMP")).upper() != "NDI" for p in profiles)
        if needs_ffmpeg and not FFMPEG_PATH:
            QMessageBox.warning(self, "Salidas IP", "No se encontró ffmpeg.exe para RTMP/SRT. Colócalo en la raíz del proyecto.")
            self.rtmp_mode_local.setChecked(True)
            return
        if not self.ctrl.items:
            QMessageBox.warning(self, "Salidas IP", "La playlist está vacía.")
            self.rtmp_mode_local.setChecked(True)
            return
        if not self.ctrl.is_on_air:
            if not self.ctrl.play_next("manual"):
                QMessageBox.warning(self, "RTMP", "No hay eventos pendientes para emitir.")
                self.rtmp_mode_local.setChecked(True)
                return
        s = self.settings
        # v22.2.4: usar self.ctrl.elapsed que estima la posición del playout
        # local con el reloj de pared cuando mpv no reporta time-pos por IPC
        # (caso documentado en v22.2.3 con builds viejas de mpv). Antes leíamos
        # self.player._time directamente, que podía quedar en 0 si mpv no
        # emitía property-change, y generaba un loop de drift infinito.
        mpv_time = float(self.ctrl.elapsed or 0.0)
        self.output = MultiOutputManager(FFMPEG_PATH, profiles, self.ctrl.export_items(), s.get("resolution", "1920x1080"), s.get("fps", "29.97"),
                                          s.get("encoder", "AUTO"), int(s.get("bitrate", 6000)), s.get("audio_pref", AUDIO_PREFS[0]),
                                          s.get("sub_pref", "OFF"),
                                          bool(s.get("subtitle_burn", True) or str(s.get("sub_pref", "OFF")).upper() != "OFF"),
                                          int(s.get("audio_bitrate", 192)),
                                          loop=True, start_index=max(0, self.ctrl.onair), start_offset=mpv_time,
                                          extra_args=s.get("ffmpeg_extra", ""), logo=self._logo_config(),
                                          program_overlay=self._tmdb_overlay_path,
                                          program_interval=max(1, int(s.get("tmdb_interval_minutes", 18))) * 60.0,
                                          program_duration=max(1, int(s.get("tmdb_duration_seconds", 15))),
                                          ndi_ffmpeg=FFMPEG_NDI_PATH, ndi_source=self.player, parent=self)
        log.info("Salidas IP arrancadas (%d destinos) en offset %.2fs", len(profiles), mpv_time)
        self.output.state.connect(self._rtmp_state)
        self.output.log.connect(self._rtmp_log)
        self.output.ended.connect(self._rtmp_finished)
        self.output.start()
        self._set_rtmp_chip("CONECTANDO…")
        self.rtmp_chip.set_active(True)
        self._refresh_output_monitor()

    def _rtmp_stop(self):
        """v22.2.2: detiene el RTMP si está corriendo."""
        if self.output and self.output.isRunning():
            self.output.stop()

    def _logo_config(self):
        s = self.settings
        if not s.get("logo_enabled") or not s.get("logo_path") or not os.path.isfile(s.get("logo_path", "")):
            return None
        hidden_categories = {"Publicidad", str(s.get("tandas_category") or "Publicidad")}
        return {"path": s["logo_path"], "position": s.get("logo_position", "arriba-derecha"), "scale": int(s.get("logo_scale", 12)),
                "opacity": int(s.get("logo_opacity", 90)), "margin": int(s.get("logo_margin", 24)),
                "hide_categories": sorted(hidden_categories)}

    def _refresh_output_monitor(self):
        """Actualiza el monitor principal sin convertirlo en editor de destinos."""
        if not hasattr(self, "rtmp_destinations"):
            return
        profiles = []
        for profile in self.settings.get("outputs") or []:
            if not isinstance(profile, dict):
                continue
            target = str(profile.get("target") or profile.get("url") or "").strip()
            if target:
                profiles.append(profile)
        if not profiles:
            legacy = str(self.settings.get("rtmp_url", "") or self.rtmp_url.text()).strip()
            if legacy:
                profiles = [{"enabled": True, "protocol": "SRT" if legacy.lower().startswith("srt://") else "RTMP",
                             "name": "Destino principal", "target": legacy}]
        enabled = [p for p in profiles if p.get("enabled", True)]
        if not profiles:
            self.rtmp_destinations.setText("Sin destinos configurados • usa Salidas IP / RTMP / SRT / NDI")
            return
        labels = []
        for profile in profiles:
            protocol = str(profile.get("protocol", "RTMP")).upper()
            name = str(profile.get("name") or protocol)
            state = "ACTIVO" if profile.get("enabled", True) else "INACTIVO"
            labels.append(f"{name} [{protocol}] · {state}")
        running = bool(self.output and self.output.isRunning())
        self.rtmp_destinations.setText(
            f"Monitor de salidas · {len(enabled)}/{len(profiles)} activos · "
            f"{'EMITIENDO' if running else 'DETENIDO'}\n" + "  •  ".join(labels)
        )

    def _rtmp_state(self, ok, msg):
        self._refresh_output_monitor()
        self._status(msg)
        self.rtmp_chip.set_active(ok)
        self._set_rtmp_chip(msg.replace("RTMP ON AIR • ", "ON AIR • ") if ok else ("ERROR" if "ERROR" in msg else "OFF"))
        if ok:
            self.rtmp_info.setText(msg)
        elif "ERROR" in msg:
            self.rtmp_info.setText(msg)
            log.error(msg)
            # Una salida puede fallar sin tumbar las demás. Solo volvemos al
            # monitor local cuando ya no queda ningún destino activo.
            if not self.output or not self.output.isRunning():
                self.rtmp_mode_local.setChecked(True)

    def _set_rtmp_chip(self, text):
        self.rtmp_chip.setToolTip(text)
        fm = self.rtmp_chip.fontMetrics()
        self.rtmp_chip.setText(fm.elidedText(text, Qt.ElideRight, max(60, self.rtmp_chip.width() - 14)))

    def _rtmp_log(self, line):
        self._last_rtmp_line = line
        if line.startswith("FFmpeg •"):
            self.rtmp_info.setText(line[:180])
        else:
            self._status(line[:200])

    def _rtmp_finished(self):
        self.output = None
        self.rtmp_chip.set_active(False)
        self._set_rtmp_chip("OFF")
        self._refresh_output_monitor()
        # v22.2.2: si el modo sigue siendo "remote" pero el FFmpeg terminó
        # (por error o stop externo), no forzar cambio de radio — el usuario
        # puede reintentar. Pero si terminó por stop nuestro, dejamos el
        # modo como está.

    def _rtmp_follow(self, index, _item):
        """La salida IP sigue al evento; los perfiles activos arrancan
        automáticamente cuando ya existe un evento al aire. El offset se
        comparte con RTMP/SRT/NDI cuando una película vuelve de una tanda."""
        start_offset = max(0.0, float((_item or {}).get("_start_offset", 0.0) or 0.0))
        if self.output and self.output.isRunning():
            # No reutilizar la tarjeta de la película anterior mientras TMDB
            # resuelve la nueva; la respuesta llega de forma asíncrona.
            self.output.set_program_overlay("")
            self.output.sync_items(self.ctrl.export_items(), index, force_jump=True, start_offset=start_offset)
            # v22.2.1: al cambiar de clip el offset se resetea a 0 en el RTMP,
            # no tiene sentido que el watcher intente realinear durante 3s.
            self._rtmp_drift_bad_count = 0
            self._rtmp_drift_suspend_until = time.time() + 8.0
        elif self.settings.get("rtmp_mode") == "remote" and self._output_profiles():
            QTimer.singleShot(0, self._rtmp_start)

    def _tmdb_follow(self, index, item):
        """Busca la tarjeta sin bloquear la emisión y limpia la anterior."""
        self._tmdb_request_id += 1
        request_id = self._tmdb_request_id
        self._tmdb_overlay_path = ""
        self.player.set_program_overlay("")
        if self.output and self.output.isRunning():
            self.output.set_program_overlay("")
        settings = self.settings
        if (not settings.get("tmdb_enabled") or not settings.get("tmdb_api_key") or
                item.get("category") not in {"Películas", "Música"}):
            return
        worker = TMDBLookupWorker(settings.get("tmdb_api_key"), item.get("title", ""), parent=self)
        self._tmdb_worker = worker
        worker.result.connect(lambda title, data, rid=request_id, idx=index, it=item: self._tmdb_ready(rid, idx, it, data))
        worker.failed.connect(lambda title, error, rid=request_id: self._tmdb_failed(rid, error))
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.start()

    def _tmdb_failed(self, request_id, error):
        if request_id == self._tmdb_request_id:
            log.info("TMDB tarjeta no disponible: %s", error)

    def _tmdb_ready(self, request_id, index, item, metadata):
        if request_id != self._tmdb_request_id or self.ctrl.current is not item:
            return
        interval = max(1, int(self.settings.get("tmdb_interval_minutes", 18))) * 60.0
        duration = max(1, int(self.settings.get("tmdb_duration_seconds", 15)))
        image_path = str(metadata.get("backdrop_file") or metadata.get("poster_file") or "")
        if not image_path or not os.path.isfile(image_path):
            return
        out = Path(image_path)
        overlay = out.with_name(out.stem + f"_overlay_{self.settings.get('resolution', '1920x1080').replace('x', '_')}.png")
        if not build_movie_overlay(metadata, self.settings.get("resolution", "1920x1080"), overlay):
            return
        self._tmdb_overlay_path = str(overlay)
        self.player.set_program_overlay(str(overlay), interval, duration)
        if self.output and self.output.isRunning() and self.ctrl.is_on_air:
            self.output.set_program_overlay(str(overlay), interval, duration)
            self.output.sync_items(self.ctrl.export_items(), self.ctrl.onair, force_jump=True,
                                   start_offset=float(self.ctrl.elapsed or 0.0))
        self._status(f"TMDB • {metadata.get('title', item.get('title', 'Película'))}")

    def _rtmp_sync_structure(self):
        if self.output and self.output.isRunning():
            self.output.sync_items(self.ctrl.export_items(), self.ctrl.onair)

    def _rtmp_tick_pause(self):
        """v22.1: vigila el estado de pausa del playout y lo replica al RTMP.
        El RTMP no soporta pausa limpia (no es como mpv), así que al pausar
        dejamos el FFmpeg corriendo y al reanudar lo reiniciamos en el offset
        actual. El seek del playout también se refleja aquí."""
        if not self.output or not self.output.isRunning():
            self._last_paused_state = False
            return
        cur_paused = bool(self.ctrl.paused) if self.ctrl.is_on_air else False
        if cur_paused != self._last_paused_state:
            self._last_paused_state = cur_paused
            self.output.pause_here(cur_paused)
            self._status(f"RTMP {'pausado' if cur_paused else 'reanudado'} • sincronizado con playout local")
            # v22.2.1: suspender el watcher de drift 3s para no realinear
            # mientras el RTMP se está ajustando tras la pausa/reanudación.
            self._rtmp_drift_bad_count = 0
            self._rtmp_drift_suspend_until = time.time() + 8.0

    def _rtmp_check_drift(self):
        """v22.2.2: detecta desincronización entre el playout local y el RTMP
        y la corrige reiniciando FFmpeg con el offset correcto.

        Compara la posición DINÁMICA de mpv contra la posición estimada
        DINÁMICA del FFmpeg (current_offset + tiempo desde que arrancó).
        Esto es lo correcto: el offset estático solo no representa la
        posición actual del FFmpeg (que avanza con el reloj).

        El RTMP se desfasa progresivamente porque FFmpeg re-encodea
        (latencia acumulada). Si la diferencia supera el umbral, llamamos
        output.seek_to(onair, mpv_time) para realinear.

        Se suspende durante 3s después de cualquier seek/pause/realign para
        evitar realineamientos espurios mientras el RTMP se está reiniciando.
        """
        if not self.output or not self.output.isRunning():
            return
        # MultiOutputManager puede mantener su QThread vivo mientras el
        # proceso FFmpeg está entre reintentos. No convertir esa ventana en
        # un seek adicional: RTMP debe conservar el comportamiento estable de
        # v24.0.2.13 y ser el único componente que reconecta.
        if not getattr(self.output, "has_active_process", True):
            return
        if not self.ctrl.is_on_air or self.ctrl.paused:
            return
        if self._rtmp_drift_suspend_until and time.time() < self._rtmp_drift_suspend_until:
            return
        # v22.2.4: usar self.ctrl.elapsed en lugar de self.player._time.
        # Si mpv no está reportando time-pos por IPC (caso v22.2.3), _time
        # se queda en 0 y se genera un loop de drift infinito. elapsed
        # estima la posición con el reloj de pared como fallback.
        mpv_time = float(self.ctrl.elapsed or 0.0)
        # Posición estimada actual del FFmpeg (avanza con el reloj desde
        # que arrancó el clip). current_position se calcula internamente
        # como current_offset + (now - clip_emit_started).
        ffmpeg_pos = float(self.output.current_position or 0.0)
        # Dos lecturas consecutivas y enfriamiento: una reconexión normal de
        # 1–3 segundos no debe convertirse en un bucle que mate RTMP.
        drift = abs(mpv_time - ffmpeg_pos)
        now = time.time()
        if drift >= self._rtmp_drift_threshold:
            self._rtmp_drift_bad_count += 1
        else:
            self._rtmp_drift_bad_count = 0
        if self._rtmp_drift_bad_count < 2 or now - self._rtmp_drift_last_restart < 12.0:
            return
        log.info("RTMP drift %.2fs (mpv=%.2fs, ffmpeg_est=%.2fs) — realineando",
                 drift, mpv_time, ffmpeg_pos)
        self.output.seek_to(self.ctrl.onair, mpv_time)
        self._rtmp_drift_bad_count = 0
        self._rtmp_drift_last_restart = now
        # Suspender el watcher mientras FFmpeg reconecta.
        self._rtmp_drift_suspend_until = now + 8.0

    # ============================================================== diálogos
    def _show_dialog(self, key, factory):
        d = self._dialogs.get(key)
        if d is not None:
            try:
                if d.isVisible():
                    d.raise_()
                    d.activateWindow()
                    return d
            except RuntimeError:
                pass
        d = factory()
        self._dialogs[key] = d
        d.show()
        return d

    def open_playlist_manager(self):
        self._show_dialog("pm", lambda: PlaylistManagerDialog(self, self.ctrl, self.db))

    def open_sources(self):
        self._show_dialog("src", lambda: SourcesDialog(self, self.db))

    def open_scheduler(self):
        self._show_dialog("sch", lambda: SchedulerDialog(self, self.db, self.scheduler))

    def open_logs(self):
        self._show_dialog("logs", lambda: LogsDialog(self, self.db))

    def open_settings(self):
        d = SettingsDialog(self, self.settings)
        if d.exec() == QDialog.Accepted:
            vals = d.values()
            changed_output = any(self.settings.get(k) != vals[k] for k in ("resolution", "fps", "encoder", "bitrate", "audio_bitrate", "subtitle_burn", "ffmpeg_extra", "rtmp_url"))
            changed_player = any(self.settings.get(k) != vals[k] for k in ("hwdec", "audio_device"))
            changed_tracks = any(self.settings.get(k) != vals[k] for k in ("audio_pref", "sub_pref"))
            for k, v in vals.items():
                if self.settings.get(k) != v:
                    self._save_setting(k, v)
            self.apply_settings()
            if changed_tracks:
                # Cambia el evento actual inmediatamente. El reinicio breve
                # mantiene local, RTMP/SRT y la selección de pistas alineados.
                if self.output and self.output.isRunning():
                    self.output.set_track_preferences(vals.get("audio_pref"), vals.get("sub_pref"))
                self.ctrl.set_track_preferences(vals.get("audio_pref"), vals.get("sub_pref"))
            self._status("Ajustes guardados" + (" • idioma/subtítulo aplicado al aire" if changed_tracks else ""))
            if changed_player and self.player.running:
                self._status("Ajustes guardados • los cambios de mpv se aplican al siguiente evento tras STOP")
            if changed_output and self.output and self.output.isRunning():
                if QMessageBox.question(self, "RTMP", "La salida RTMP está activa. ¿Reiniciarla con los nuevos ajustes?") == QMessageBox.Yes:
                    self.output.stop()
                    QTimer.singleShot(1500, self._rtmp_start)

    def open_outputs(self):
        from .dialogs_extra import OutputProfilesDialog
        d = OutputProfilesDialog(self, self.settings)
        if d.exec() != QDialog.Accepted:
            return
        profiles = d.values()
        self._save_setting("outputs", profiles)
        # Mantener compatibilidad con la URL única de versiones anteriores.
        if profiles:
            self.rtmp_url.setText(str(profiles[0].get("target", "")))
            self._save_setting("rtmp_url", profiles[0].get("target", ""))
        self._refresh_output_monitor()
        enabled = any(bool(p.get("enabled", True)) for p in profiles)
        was_running = bool(self.output and self.output.isRunning())
        if was_running:
            self.output.stop()
            self.output.wait(4000)
            self.output = None
            self.rtmp_chip.set_active(False)
            self._set_rtmp_chip("OFF")
        if enabled:
            # La casilla Activo del diálogo es ahora la única decisión del
            # operador: al guardar, los perfiles activos pasan al aire.
            self.rtmp_mode_group.blockSignals(True)
            self.rtmp_mode_remote.setChecked(True)
            self.rtmp_mode_group.blockSignals(False)
            self._save_setting("rtmp_mode", "remote")
            QTimer.singleShot(250, self._rtmp_start)
        else:
            self.rtmp_mode_group.blockSignals(True)
            self.rtmp_mode_local.setChecked(True)
            self.rtmp_mode_group.blockSignals(False)
            self._save_setting("rtmp_mode", "local")
            self.rtmp_info.setText("Salidas detenidas • ningún destino está activo")
        self._refresh_output_monitor()
        self._status(f"Destinos guardados: {len(profiles)} • {'activando' if enabled else 'todos desactivados'}")

    def open_logo(self):
        from .dialogs_extra import LogoDialog
        d = LogoDialog(self, self.settings)
        if d.exec() == QDialog.Accepted:
            for k, v in d.values().items():
                if self.settings.get(k) != v:
                    self._save_setting(k, v)
            if self.output and self.output.isRunning():
                self.output.set_logo(self._logo_config())
                self._status("Logo actualizado • se aplica desde el siguiente evento RTMP")

    def open_devices(self):
        from .dialogs_extra import DevicesDialog
        self._show_dialog("dev", lambda: DevicesDialog(self))

    # ================================================================ varios
    def _status(self, msg):
        self.statusBar().showMessage(str(msg), 15000)

    def _tick_ui(self):
        now = datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S"))
        self.date_lbl.setText(f"{DAYS_ES[now.weekday()]} {now.day:02d} {MONTHS_ES[now.month - 1]} {now.year}")
        self.fps_chip.setText(f"{self.settings.get('resolution', '')}\n{self.settings.get('fps', '')} fps")
        self.f_plrem.setText(fmt_tc(self.ctrl.playlist_remaining()))
        # v22.2.6: indicador de logs (errores/warnings) en el statusBar.
        try:
            from . import logger as _logger
            counts = _logger.count_by_level(500)
            err = counts["ERROR"]
            warn = counts["WARNING"]
            if err > 0:
                txt = f"⛔ {err} error{'es' if err != 1 else ''}  ⚠ {warn}"
                color = "#ff5050"
            elif warn > 0:
                txt = f"⚠ {warn} warning{'s' if warn != 1 else ''}"
                color = "#ffb84d"
            else:
                txt = "✓ sin errores"
                color = "#81c784"
            self._logs_status.setText(txt)
            self._logs_status.setStyleSheet(f"padding: 0 8px; color: {color};")
        except Exception:
            pass
        if int(now.timestamp() * 2) % 2 == 0:
            self._update_times()
        # v22.2.5: la barra de progreso y POSICIÓN/RESTANTE dependían sólo
        # de la señal `position` de mpv (que necesita time-pos por IPC). Si
        # mpv no emite time-pos, _pos queda en 0 y la barra nunca avanza.
        # Como _tick_ui corre cada 500ms, refrescamos acá usando elapsed
        # (que tiene fallback al reloj de pared).
        if self.ctrl.is_on_air and not self.ctrl.paused:
            try:
                pos = float(self.ctrl.elapsed or 0.0)
                dur = float(self.ctrl.duration or 0.0)
                if dur > 0:
                    rem = max(0.0, dur - pos)
                    self.f_pos.setText(fmt_tc(pos))
                    self.f_dur.setText(fmt_tc(dur))
                    self.f_rem.setText(fmt_tc(rem))
                    self.progress.set_progress(pos, dur)
            except Exception:
                pass
        if self.ctrl.is_on_air and self.ctrl.paused:
            self.onair_led.setText("PAUSA" if int(now.timestamp()) % 2 else "ON-AIR")
        elif self.onair_led.text() != "ON-AIR":
            self.onair_led.setText("ON-AIR")

    def closeEvent(self, event):
        if self.ctrl.is_on_air or (self.output and self.output.isRunning()):
            if QMessageBox.question(self, "Salir", "Hay emisión AL AIRE. ¿Seguro que quieres salir?") != QMessageBox.Yes:
                event.ignore()
                return
        try:
            self._save_setting("splitter", self.splitter.sizes())
            self.ctrl._dirty = True
            self.ctrl.save_current()
            if self.output:
                self.output.stop()
                self.output.wait(4000)
            self.ctrl.stop()
            self.player.shutdown()
            if self.scanner and self.scanner.isRunning():
                self.scanner.stop()
                self.scanner.wait(2000)
            if self.prober and self.prober.isRunning():
                self.prober.stop()
                self.prober.wait(3000)
            self.db.close_open_air_logs()
        except Exception as e:  # noqa: BLE001
            log.error("cierre: %s", e)
        log.info("Aplicación cerrada")
        super().closeEvent(event)


def main():
    logger.setup()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor("#1b1b1b"))
    pal.setColor(QPalette.WindowText, QColor("#dcdcdc"))
    pal.setColor(QPalette.Base, QColor("#101010"))
    pal.setColor(QPalette.AlternateBase, QColor("#151515"))
    pal.setColor(QPalette.Text, QColor("#e6e6e6"))
    pal.setColor(QPalette.Button, QColor("#333333"))
    pal.setColor(QPalette.ButtonText, QColor("#ececec"))
    pal.setColor(QPalette.Highlight, QColor("#2f63c5"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#111111"))
    pal.setColor(QPalette.ToolTipText, QColor("#eeeeee"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
