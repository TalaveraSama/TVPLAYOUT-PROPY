from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QTime, QTimer
from .config import DB_PATH, MPV_PATH, FFMPEG_PATH
from .db import DB
from .scanner import Scanner
from .mpv_player import MPVPlayer
from .output import OutputWorker
from .scheduler import SchedulerService

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TVPlayout PRO V21 — Broadcast Playout")
        self.resize(1550, 900)
        self.setMinimumSize(1200, 650)
        self.db = DB(DB_PATH)
        self.scanner = None
        self.output = None
        self.scheduler = None
        self._paused = False
        self._muted = False
        self._build()
        self.refresh_categories()
        self.refresh_library()

    def _build(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        buttons = [
            ("📚 Fuentes / Categorías", self.sources_dialog),
            ("🔄 Escanear", self.start_scan),
            ("＋ Playlist", self.add_selected),
            ("🗓 Programador", self.scheduler_dialog),
            ("📢 Anuncios", self.ads_dialog),
        ]
        for text, slot in buttons:
            b = QPushButton(text); b.clicked.connect(slot); top.addWidget(b)
        top.addStretch(); self.clock = QLabel(); top.addWidget(self.clock); root.addLayout(top)
        self.clock_timer = QTimer(self); self.clock_timer.timeout.connect(lambda: self.clock.setText(QTime.currentTime().toString("HH:mm:ss"))); self.clock_timer.start(500)

        splitter = QSplitter(Qt.Horizontal); root.addWidget(splitter, 1)

        # Biblioteca
        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("BIBLIOTECA"))
        self.search = QLineEdit(); self.search.setPlaceholderText("🔎 Buscar película, archivo o carpeta..."); self.search.textChanged.connect(self.refresh_library); ll.addWidget(self.search)
        self.category = QComboBox(); self.category.currentTextChanged.connect(self.refresh_library); ll.addWidget(self.category)
        self.library = QListWidget(); self.library.setSelectionMode(QAbstractItemView.ExtendedSelection); self.library.itemDoubleClicked.connect(self.preview_item); ll.addWidget(self.library, 1)
        self.lib_status = QLabel("Biblioteca lista"); ll.addWidget(self.lib_status)
        splitter.addWidget(left)

        # Preview / local playout
        center = QWidget(); cl = QVBoxLayout(center)
        self.onair = QLabel("ON AIR / PREVIEW"); self.onair.setAlignment(Qt.AlignCenter); self.onair.setMinimumHeight(400); self.onair.setStyleSheet("background:#050505;color:#777;font-size:22px;"); cl.addWidget(self.onair, 1)
        self.now = QLabel("Sin reproducción"); cl.addWidget(self.now)
        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶ PLAY"); self.play_btn.clicked.connect(self.play_selected)
        self.pause_btn = QPushButton("Ⅱ PAUSE"); self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn = QPushButton("■ STOP"); self.stop_btn.clicked.connect(self.stop_player)
        self.mute_btn = QPushButton("🔊 AUDIO LOCAL"); self.mute_btn.clicked.connect(self.toggle_mute)
        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0, 100); self.vol.setValue(100); self.vol.setMaximumWidth(160); self.vol.valueChanged.connect(self.set_volume)
        for b in (self.play_btn, self.pause_btn, self.stop_btn, self.mute_btn): controls.addWidget(b)
        controls.addWidget(QLabel("Vol.")); controls.addWidget(self.vol); cl.addLayout(controls)
        self.local_note = QLabel("🔊 Audio/Mutear afecta SOLO el preview local • RTMP conserva su audio"); self.local_note.setStyleSheet("color:#8fd18f;"); cl.addWidget(self.local_note)
        splitter.addWidget(center)

        # Playlist + output
        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("PLAYLIST / ON AIR"))
        self.playlist = QListWidget(); self.playlist.setSelectionMode(QAbstractItemView.SingleSelection); self.playlist.setContextMenuPolicy(Qt.CustomContextMenu); self.playlist.customContextMenuRequested.connect(self.playlist_menu); rl.addWidget(self.playlist, 1)
        pbtn = QHBoxLayout();
        rem = QPushButton("🗑 Eliminar"); rem.clicked.connect(self.remove_playlist_selected)
        clear = QPushButton("🗑 Vaciar"); clear.clicked.connect(self.clear_playlist)
        pbtn.addWidget(rem); pbtn.addWidget(clear); rl.addLayout(pbtn)

        rl.addWidget(QLabel("Audio por defecto")); self.audio = QComboBox(); self.audio.addItems(["AUTO / Español preferido","es-MX","es-419","spa","es","Original"]); rl.addWidget(self.audio)
        rl.addWidget(QLabel("Subtítulos por defecto")); self.sub = QComboBox(); self.sub.addItems(["AUTO / Español MX preferido","es-MX","spa-MX","es-419","spa","es","OFF"]); rl.addWidget(self.sub)

        out = QGroupBox("SALIDA / VIDEO OUTPUT"); ol = QFormLayout(out)
        self.res = QComboBox(); self.res.addItems(["1920x1080","1280x720","720x576","3840x2160"]); ol.addRow("Resolución", self.res)
        self.fps = QComboBox(); self.fps.addItems(["23.976","24","25","29.97","30","50","59.94","60"]); self.fps.setCurrentText("29.97"); ol.addRow("FPS", self.fps)
        self.encoder = QComboBox(); self.encoder.addItems(["AUTO","CPU/x264","NVIDIA NVENC","Intel QSV","AMD AMF"]); ol.addRow("Encoder", self.encoder)
        self.bitrate = QSpinBox(); self.bitrate.setRange(500, 50000); self.bitrate.setValue(6000); self.bitrate.setSuffix(" kbps"); ol.addRow("Bitrate", self.bitrate)
        self.rtmp = QLineEdit(); self.rtmp.setPlaceholderText("rtmp://servidor/app/stream"); ol.addRow("RTMP", self.rtmp)
        self.rtmp_btn = QPushButton("🔴 INICIAR RTMP"); self.rtmp_btn.clicked.connect(self.toggle_rtmp); ol.addRow(self.rtmp_btn)
        rl.addWidget(out)
        splitter.addWidget(right); splitter.setSizes([390, 760, 400])

        self.statusBar().showMessage(f"MPV: {'OK' if MPV_PATH else 'NO'} | FFmpeg: {'OK' if FFMPEG_PATH else 'NO'}")
        self.player = MPVPlayer(self.onair, MPV_PATH); self.player.status.connect(self.statusBar().showMessage)
        self.scheduler = SchedulerService(self.db); self.scheduler.triggered.connect(self._scheduled_run); self.scheduler.status.connect(self.statusBar().showMessage); self.scheduler.start()

    def refresh_categories(self):
        self.category.blockSignals(True); self.category.clear(); self.category.addItem("Todas"); self.category.addItems(self.db.categories()); self.category.blockSignals(False)

    def refresh_library(self):
        if not hasattr(self, 'library'): return
        self.library.clear(); rows = self.db.search_media(self.search.text(), self.category.currentText() if self.category.count() else "Todas")
        for r in rows:
            it = QListWidgetItem(r["title"]); it.setData(Qt.UserRole, dict(r)); self.library.addItem(it)
        self.lib_status.setText(f"Medios: {len(rows)} / Total: {self.db.count_media()}")

    def start_scan(self):
        if self.scanner and self.scanner.isRunning(): self.scanner.stop(); return
        src = self.db.sources()
        if not src:
            QMessageBox.warning(self, "Fuentes", "Primero agrega una carpeta en Fuentes / Categorías."); return
        self.lib_status.setText("ESCANEANDO..."); self.scanner = Scanner(self.db, src)
        self.scanner.progress.connect(lambda f, files, media: self.lib_status.setText(f"Escaneando • carpetas {f} • archivos {files} • medios {media}"))
        self.scanner.found.connect(lambda t: self.lib_status.setText(f"Encontrado: {t}"))
        self.scanner.error.connect(lambda e: self.statusBar().showMessage(e))
        self.scanner.finished_count.connect(lambda files, media: (self.refresh_library(), self.lib_status.setText(f"Finalizado • archivos {files} • medios {media}")))
        self.scanner.start()

    def add_selected(self):
        for it in self.library.selectedItems():
            r = it.data(Qt.UserRole); item = QListWidgetItem(r["title"]); item.setData(Qt.UserRole, r); self.playlist.addItem(item)
        if self.playlist.count() and self.playlist.currentRow() < 0: self.playlist.setCurrentRow(0)
        self.sync_rtmp_playlist()

    def _playlist_sources(self):
        out = []
        for i in range(self.playlist.count()):
            r = self.playlist.item(i).data(Qt.UserRole)
            if r and r.get("path"): out.append(r["path"])
        return out

    def sync_rtmp_playlist(self):
        if self.output and self.output.isRunning():
            sources = self._playlist_sources()
            if sources: self.output.replace_sources(sources)

    def remove_playlist_selected(self):
        row = self.playlist.currentRow()
        if row >= 0:
            self.playlist.takeItem(row)
            if self.playlist.count(): self.playlist.setCurrentRow(min(row, self.playlist.count() - 1))
            self.sync_rtmp_playlist()

    def clear_playlist(self):
        self.playlist.clear(); self.sync_rtmp_playlist()

    def playlist_menu(self, pos):
        menu = QMenu(self); menu.addAction("🗑 Eliminar seleccionado", self.remove_playlist_selected); menu.addAction("🗑 Vaciar playlist", self.clear_playlist); menu.exec(self.playlist.mapToGlobal(pos))

    def preview_item(self, it):
        r = it.data(Qt.UserRole); self.now.setText("PREVIEW • " + r["title"]); self.player.play(r["path"])

    def play_selected(self):
        it = self.playlist.currentItem() or (self.playlist.item(0) if self.playlist.count() else None)
        if not it: return
        r = it.data(Qt.UserRole); self.now.setText("ON AIR • " + r["title"]); self.player.play(r["path"])

    def toggle_pause(self):
        self._paused = not self._paused; self.player.pause(); self.pause_btn.setText("▶ RESUME" if self._paused else "Ⅱ PAUSE")

    def toggle_mute(self):
        self._muted = not self._muted; self.player.set_mute(self._muted); self.mute_btn.setText("🔇 MUTED LOCAL" if self._muted else "🔊 AUDIO LOCAL")

    def set_volume(self, value):
        self.player.set_volume(value)

    def stop_player(self):
        self.player.stop(); self.now.setText("Sin reproducción"); self._paused = False; self.pause_btn.setText("Ⅱ PAUSE")

    def toggle_rtmp(self):
        if self.output and self.output.isRunning():
            self.output.stop(); self.rtmp_btn.setText("🔴 INICIAR RTMP"); return
        url = self.rtmp.text().strip()
        if not url: QMessageBox.warning(self, "RTMP", "Escribe la URL RTMP."); return
        sources = self._playlist_sources()
        if not sources: QMessageBox.warning(self, "RTMP", "Agrega al menos un elemento a la playlist."); return
        enc = self.encoder.currentText()
        if enc == "AUTO": enc = "NVIDIA NVENC" if "NVIDIA" in self._gpu_hint() else "CPU/x264"
        self.output = OutputWorker(FFMPEG_PATH, sources, url, self.res.currentText(), self.fps.currentText(), enc, self.bitrate.value(), self.audio.currentText(), self.sub.currentText(), False)
        self.output.state.connect(self._rtmp_state); self.output.log.connect(lambda s: self.statusBar().showMessage("FFmpeg • " + s[:200])); self.output.finished.connect(self._rtmp_finished)
        self.output.start(); self.rtmp_btn.setText("■ DETENER RTMP")

    def _rtmp_state(self, ok, msg):
        self.statusBar().showMessage(msg); self.rtmp_btn.setText("■ DETENER RTMP" if ok else "🔴 INICIAR RTMP")

    def _rtmp_finished(self):
        self.output = None; self.rtmp_btn.setText("🔴 INICIAR RTMP")

    def _gpu_hint(self):
        import shutil, subprocess
        exe = shutil.which("nvidia-smi")
        if not exe: return ""
        try: return subprocess.check_output([exe, "-L"], stderr=subprocess.DEVNULL, text=True, timeout=2)
        except Exception: return ""

    def sources_dialog(self):
        d = QDialog(self); d.setWindowTitle("Fuentes y categorías — Biblioteca permanente"); d.resize(950, 620); v = QVBoxLayout(d)
        v.addWidget(QLabel("Las fuentes y categorías quedan guardadas en SQLite y pueden reutilizarse en el programador."))
        table = QTableWidget(0, 3); table.setHorizontalHeaderLabels(["Carpeta / Fuente", "Categoría", "Recursivo"]); table.horizontalHeader().setStretchLastSection(True); v.addWidget(table, 1)
        for s in self.db.sources():
            row = table.rowCount(); table.insertRow(row); table.setItem(row, 0, QTableWidgetItem(s["path"])); table.setItem(row, 1, QTableWidgetItem(s["category"])); table.setItem(row, 2, QTableWidgetItem("Sí" if s["recursive"] else "No"))
        btn = QHBoxLayout(); add = QPushButton("Añadir carpeta"); add.clicked.connect(lambda: self._add_source(table)); btn.addWidget(add); save = QPushButton("Guardar"); save.clicked.connect(lambda: self._save_sources(table, d)); btn.addWidget(save); close = QPushButton("Cerrar"); close.clicked.connect(d.accept); btn.addWidget(close); v.addLayout(btn); d.exec()

    def _add_source(self, table):
        p = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if not p: return
        cat, ok = QInputDialog.getItem(self, "Categoría", "Categoría:", self.db.categories(), 0, False)
        if not ok: return
        row = table.rowCount(); table.insertRow(row); table.setItem(row, 0, QTableWidgetItem(p)); table.setItem(row, 1, QTableWidgetItem(cat)); table.setItem(row, 2, QTableWidgetItem("Sí"))

    def _save_sources(self, table, d):
        for row in range(table.rowCount()):
            p = table.item(row, 0).text().strip() if table.item(row, 0) else ""
            c = table.item(row, 1).text().strip() if table.item(row, 1) else "Películas"
            if p: self.db.add_source(p, c or "Películas", True)
        d.accept(); self.statusBar().showMessage("Fuentes guardadas")

    def scheduler_dialog(self):
        d = QDialog(self); d.setWindowTitle("Programador TV — Diario / Semanal / Mensual / Trimestral"); d.resize(1180, 720); root = QVBoxLayout(d)
        root.addWidget(QLabel("Scheduler tipo XPlayout: crea automáticamente una playlist desde una categoría guardada y la pone ON AIR a la hora indicada."))
        table = QTableWidget(0, 10); table.setHorizontalHeaderLabels(["Activo","Nombre","Modo","Hora","Días","Día mes","Mes Q","Categoría","Cantidad","Orden"]); table.setSelectionBehavior(QAbstractItemView.SelectRows); table.horizontalHeader().setStretchLastSection(True); root.addWidget(table, 1)

        form = QGridLayout(); name = QLineEdit(); mode = QComboBox(); mode.addItems(["daily","weekly","monthly","quarterly"]); tm = QTimeEdit(); tm.setDisplayFormat("HH:mm"); tm.setTime(QTime.currentTime())
        cat = QComboBox(); cat.addItem("Todas"); cat.addItems(self.db.categories()); count = QSpinBox(); count.setRange(1, 10000); count.setValue(20); order = QComboBox(); order.addItems(["sequential","random","recent"]); dom = QSpinBox(); dom.setRange(1, 31); dom.setValue(1); moq = QSpinBox(); moq.setRange(1, 3); moq.setValue(1)
        form.addWidget(QLabel("Nombre"),0,0); form.addWidget(name,0,1,1,3); form.addWidget(QLabel("Modo"),0,4); form.addWidget(mode,0,5); form.addWidget(QLabel("Hora"),0,6); form.addWidget(tm,0,7)
        form.addWidget(QLabel("Día mes"),1,0); form.addWidget(dom,1,1); form.addWidget(QLabel("Mes trimestre"),1,2); form.addWidget(moq,1,3); form.addWidget(QLabel("Categoría"),1,4); form.addWidget(cat,1,5); form.addWidget(QLabel("Cantidad"),1,6); form.addWidget(count,1,7); form.addWidget(QLabel("Orden"),1,8); form.addWidget(order,1,9)
        days=[]
        for n,t in enumerate(["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]):
            cb=QCheckBox(t); cb.setChecked(True); days.append(cb); form.addWidget(cb,2,n+1)
        form.addWidget(QLabel("Días semana"),2,0); root.addLayout(form)

        def load():
            table.setRowCount(0)
            for r in self.db.schedules():
                i=table.rowCount(); table.insertRow(i); vals=["ON" if r['enabled'] else "OFF",r['name'],r['mode'],r['start_time'],r['days'],str(r['day_of_month'] or ''),str(r['month_of_quarter'] or ''),r['category'],str(r['item_count']),r['order_mode']]
                for c,v in enumerate(vals): table.setItem(i,c,QTableWidgetItem(v))
        load()

        def state_for_mode(m):
            weekly = m == 'weekly'; monthly = m in ('monthly','quarterly'); quarter = m == 'quarterly'
            for cb in days: cb.setEnabled(weekly)
            dom.setEnabled(monthly); moq.setEnabled(quarter)
        mode.currentTextChanged.connect(state_for_mode); state_for_mode(mode.currentText())

        buttons=QHBoxLayout(); add=QPushButton('＋ Guardar programación'); test=QPushButton('▶ Ejecutar ahora'); delete=QPushButton('🗑 Eliminar'); toggle=QPushButton('⏻ Activar / Desactivar'); close=QPushButton('Cerrar')
        for x in (add,test,delete,toggle,close): buttons.addWidget(x)
        root.addLayout(buttons)

        def selected_id():
            row=table.currentRow()
            if row<0:return None
            namev=table.item(row,1).text(); return next((x['id'] for x in self.db.schedules() if x['name']==namev),None)
        def save():
            n=name.text().strip()
            if not n: QMessageBox.warning(d,'Programador','Escribe un nombre.'); return
            m=mode.currentText(); ds=','.join(str(i) for i,cb in enumerate(days) if cb.isChecked()) if m=='weekly' else ''
            if m=='weekly' and not ds: QMessageBox.warning(d,'Programador','Selecciona al menos un día.'); return
            self.db.add_schedule(n,m,tm.time().toString('HH:mm'),ds,dom.value(),moq.value(),cat.currentText(),count.value(),order.currentText()); load(); self.statusBar().showMessage('Programación guardada')
        add.clicked.connect(save)
        def test_now():
            sid=selected_id()
            if sid is None: QMessageBox.warning(d,'Programador','Selecciona una programación guardada.'); return
            self.scheduler.run_schedule_now(sid)
        test.clicked.connect(test_now)
        delete.clicked.connect(lambda: (self.db.delete_schedule(selected_id()), load()) if selected_id() else None)
        def tog():
            sid=selected_id()
            if sid is None:return
            r=next(x for x in self.db.schedules() if x['id']==sid); self.db.set_schedule_enabled(sid,not bool(r['enabled'])); load()
        toggle.clicked.connect(tog); close.clicked.connect(d.accept); d.exec()

    def _scheduled_run(self, schedule, items):
        self.playlist.clear()
        for r in items:
            it=QListWidgetItem(r['title']); it.setData(Qt.UserRole,dict(r)); self.playlist.addItem(it)
        if not self.playlist.count():
            self.statusBar().showMessage(f"PROGRAMADO • {schedule['name']} • sin medios"); return
        self.playlist.setCurrentRow(0); self.play_selected()
        # Esta era la falla de V20: el scheduler cambiaba MPV pero FFmpeg seguía
        # usando el concat creado al iniciar RTMP. V21 cambia el programa RTMP en caliente.
        self.sync_rtmp_playlist()
        self.statusBar().showMessage(f"PROGRAMADO • {schedule['name']} • {len(items)} medios • LOCAL + RTMP sincronizados")

    def ads_dialog(self): QMessageBox.information(self,"Anuncios","Módulo reservado para tandas. La inserción automática de comerciales se integrará sobre el scheduler sin cortar el audio local ni la salida RTMP.")

def main():
    app=QApplication([]); app.setStyle("Fusion"); w=MainWindow(); w.show(); app.exec()
