"""Diálogos de funciones: Playlist Manager, Fuentes/Categorías, Programador, Registros, Ajustes, Editar clip."""
import json
import os
from datetime import datetime

from PySide6.QtCore import Qt, QTime, QDate, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QLineEdit, QComboBox,
                               QSpinBox, QDoubleSpinBox, QCheckBox, QTimeEdit, QDateEdit, QMessageBox, QFileDialog, QInputDialog,
                               QPlainTextEdit, QTabWidget, QWidget, QListWidget, QListWidgetItem, QGroupBox, QScrollArea, QFrame)

from . import logger
from .config import (MPV_PATH, VLC_PATH, FFMPEG_PATH, FFPROBE_PATH, ROOT, RESOLUTIONS, FPS_LIST, ENCODERS, AUDIO_PREFS, SUB_PREFS,
                     category_color, DB_PATH, APP_VERSION)
from .scheduler import MODE_LABELS, DAY_LABELS
from .widgets import fmt_tc


def _btn(text, slot=None, name=None, tip=None):
    b = QPushButton(text)
    if slot:
        b.clicked.connect(slot)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    return b


def _note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    return label


class BaseDialog(QDialog):
    def __init__(self, parent, title, w=900, h=600):
        super().__init__(parent)
        self.setWindowTitle(f"{title} — TVPlayout PRO {APP_VERSION}")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            # Respeta la resolución lógica de Windows/TV y nunca nace más
            # grande que el área visible detrás de la barra de tareas.
            w = min(int(w), max(480, available.width() - 32))
            h = min(int(h), max(360, available.height() - 56))
        self.resize(max(480, int(w)), max(360, int(h)))
        self.setMinimumSize(480, 360)
        self.setSizeGripEnabled(True)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

    @staticmethod
    def scroll_page(widget):
        """Envuelve páginas altas para que funcionen en TV/escala DPI grande."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(widget)
        return scroll


# ============================================================ PLAYLIST MANAGER
class PlaylistManagerDialog(BaseDialog):
    """Guardar/cargar playlists con nombre, exportar/importar M3U/JSON."""

    def __init__(self, parent, controller, db):
        super().__init__(parent, "Playlist Manager", 760, 520)
        self.ctrl = controller
        self.db = db
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Playlists guardadas en la base de datos. Cargar reemplaza la playlist actual; "
                           "Añadir la agrega al final."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nombre", "Eventos", "Duración total", "Creada"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _i: self.load(replace=True))
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(_btn("💾 Guardar actual como…", self.save_as, "primary"))
        row.addWidget(_btn("📂 Cargar (reemplazar)", lambda: self.load(True)))
        row.addWidget(_btn("➕ Añadir al final", lambda: self.load(False)))
        row.addWidget(_btn("✎ Renombrar", self.rename))
        row.addWidget(_btn("🗑 Eliminar", self.delete, "danger"))
        row.addStretch()
        v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(_btn("⬇ Exportar M3U/JSON…", self.export_file))
        row2.addWidget(_btn("⬆ Importar M3U/JSON…", self.import_file))
        row2.addStretch()
        row2.addWidget(_btn("Cerrar", self.accept))
        v.addLayout(row2)
        self.reload()

    def reload(self):
        self.table.setRowCount(0)
        for name in self.db.playlist_names():
            n, dur, created = self.db.playlist_summary(name)
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate([name, str(n), fmt_tc(dur), created]):
                it = QTableWidgetItem(val)
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)

    def _selected_name(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).text() if r >= 0 else None

    def save_as(self):
        if not self.ctrl.items:
            QMessageBox.information(self, "Playlist", "La playlist actual está vacía.")
            return
        name, ok = QInputDialog.getText(self, "Guardar playlist", "Nombre:", text=datetime.now().strftime("Playlist %Y-%m-%d %H%M"))
        name = (name or "").strip()
        if not ok or not name or name == "__current__":
            return
        if name in self.db.playlist_names():
            if QMessageBox.question(self, "Playlist", f"«{name}» ya existe. ¿Sobrescribir?") != QMessageBox.Yes:
                return
        self.db.save_playlist(name, self.ctrl.export_items())
        self.reload()

    def load(self, replace):
        name = self._selected_name()
        if not name:
            return
        from .playout import make_item
        rows = self.db.load_playlist(name)
        items = [make_item(r) for r in rows]
        if not items:
            QMessageBox.information(self, "Playlist", "La playlist está vacía o sus archivos ya no existen en la biblioteca.")
            return
        if replace:
            if self.ctrl.is_on_air and QMessageBox.question(
                    self, "Playlist", "Hay un evento AL AIRE. ¿Reemplazar la playlist? El evento actual seguirá hasta terminar.") != QMessageBox.Yes:
                return
            if self.ctrl.is_on_air:
                self.ctrl.clear()
                self.ctrl.append_items(items)
            else:
                self.ctrl.set_items(items)
        else:
            self.ctrl.append_items(items)
        self.parent().statusBar().showMessage(f"Playlist «{name}» • {len(items)} eventos")

    def rename(self):
        name = self._selected_name()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=name)
        new = (new or "").strip()
        if ok and new and new != name:
            self.db.rename_playlist(name, new)
            self.reload()

    def delete(self):
        name = self._selected_name()
        if name and QMessageBox.question(self, "Eliminar", f"¿Eliminar la playlist «{name}»?") == QMessageBox.Yes:
            self.db.delete_playlist(name)
            self.reload()

    def export_file(self):
        if not self.ctrl.items:
            QMessageBox.information(self, "Exportar", "La playlist actual está vacía.")
            return
        path, flt = QFileDialog.getSaveFileName(self, "Exportar playlist", str(ROOT / "playlist.m3u8"),
                                                "M3U (*.m3u *.m3u8);;JSON (*.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                data = [{k: v for k, v in it.items() if k not in ("aired_at", "late")} for it in self.ctrl.export_items()]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for it in self.ctrl.items:
                        f.write(f"#EXTINF:{int(it['duration'] or -1)},{it['title']}\n")
                        if it.get("fixed_time"):
                            f.write(f"#EXT-X-TVPLAYOUT-FIXED:{it['fixed_time']}\n")
                        if float(it.get("mark_in") or 0) > 0:
                            f.write(f"#EXT-X-TVPLAYOUT-MARKIN:{float(it['mark_in']):.3f}\n")
                        if float(it.get("mark_out") or 0) > 0:
                            f.write(f"#EXT-X-TVPLAYOUT-MARKOUT:{float(it['mark_out']):.3f}\n")
                        f.write(it["path"] + "\n")
            self.parent().statusBar().showMessage("Playlist exportada: " + path)
        except OSError as e:
            QMessageBox.critical(self, "Exportar", str(e))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar playlist", str(ROOT), "Playlists (*.m3u *.m3u8 *.json *.txt)")
        if not path:
            return
        from .playout import make_item
        items = []
        try:
            if path.lower().endswith(".json"):
                with open(path, encoding="utf-8") as f:
                    for d in json.load(f):
                        if isinstance(d, dict) and d.get("path"):
                            row = self.db.media_by_path(d["path"])
                            base = make_item(row) if row else make_item(d)
                            base["fixed_time"] = d.get("fixed_time", "") or ""
                            base["mark_in"] = max(0.0, float(d.get("mark_in") or 0))
                            base["mark_out"] = max(0.0, float(d.get("mark_out") or 0))
                            if base.get("source_duration"):
                                from .playout import trim_bounds
                                start, end, effective = trim_bounds(base)
                                base["mark_in"], base["mark_out"], base["duration"] = start, (end if end < base["source_duration"] else 0.0), effective
                            items.append(base)
            else:
                title = ""
                fixed = ""
                m3u_duration = 0.0
                mark_in = 0.0
                mark_out = 0.0
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("#EXTINF"):
                            head, title = (line.split(",", 1) + [""])[:2] if "," in line else (line, "")
                            try:
                                m3u_duration = max(0.0, float(head.split(":", 1)[1]))
                            except (ValueError, IndexError):
                                m3u_duration = 0.0
                        elif line.startswith("#EXT-X-TVPLAYOUT-FIXED:"):
                            fixed = line.split(":", 1)[1]
                        elif line.startswith("#EXT-X-TVPLAYOUT-MARKIN:"):
                            try:
                                mark_in = max(0.0, float(line.split(":", 1)[1]))
                            except ValueError:
                                mark_in = 0.0
                        elif line.startswith("#EXT-X-TVPLAYOUT-MARKOUT:"):
                            try:
                                mark_out = max(0.0, float(line.split(":", 1)[1]))
                            except ValueError:
                                mark_out = 0.0
                        elif line.startswith("#"):
                            continue
                        else:
                            row = self.db.media_by_path(line)
                            it = make_item(row) if row else make_item({
                                "path": line,
                                "title": title or os.path.splitext(os.path.basename(line))[0],
                                "duration": m3u_duration,
                                "source_duration": m3u_duration,
                            })
                            it["fixed_time"] = fixed
                            it["mark_in"] = mark_in
                            it["mark_out"] = mark_out
                            if it.get("source_duration"):
                                from .playout import trim_bounds
                                start, end, effective = trim_bounds(it)
                                it["mark_in"], it["mark_out"], it["duration"] = start, (end if end < it["source_duration"] else 0.0), effective
                            items.append(it)
                            title, fixed, m3u_duration, mark_in, mark_out = "", "", 0.0, 0.0, 0.0
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Importar", str(e))
            return
        if not items:
            QMessageBox.information(self, "Importar", "No se encontraron entradas válidas.")
            return
        self.ctrl.append_items(items)
        self.parent().statusBar().showMessage(f"Importados {len(items)} eventos")


# ============================================================ FUENTES / CATEGORÍAS
class SourcesDialog(BaseDialog):
    def __init__(self, parent, db):
        super().__init__(parent, "Fuentes y categorías", 900, 560)
        self.db = db
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # --- fuentes
        w = QWidget()
        sl = QVBoxLayout(w)
        sl.addWidget(QLabel("Carpetas locales o UNC (\\\\servidor\\carpeta) que se escanean hacia la biblioteca. "
                            "Cada fuente asigna una categoría a sus archivos."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Carpeta / Fuente", "Categoría", "Recursivo"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        sl.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(_btn("📁 Añadir carpeta…", self.add_folder, "primary"))
        row.addWidget(_btn("⌨ Añadir ruta manual/UNC…", self.add_manual))
        row.addWidget(_btn("🗑 Quitar", self.remove_selected, "danger"))
        row.addStretch()
        row.addWidget(_btn("💾 Guardar", self.save))
        sl.addLayout(row)
        tabs.addTab(w, "FUENTES")

        # --- categorías
        w2 = QWidget()
        cl = QVBoxLayout(w2)
        cl.addWidget(QLabel("Categorías disponibles para fuentes, programador, autofill y tandas. "
                            "El color se usa en la grid de la playlist."))
        self.cat_list = QListWidget()
        cl.addWidget(self.cat_list, 1)
        row2 = QHBoxLayout()
        row2.addWidget(_btn("＋ Nueva categoría…", self.add_category, "primary"))
        row2.addWidget(_btn("🗑 Eliminar categoría", self.delete_category, "danger"))
        row2.addStretch()
        cl.addLayout(row2)
        tabs.addTab(w2, "CATEGORÍAS")

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(_btn("Cerrar", self.accept))
        v.addLayout(bottom)
        self.reload()

    def reload(self):
        self.table.setRowCount(0)
        cats = self.db.categories()
        for s in self.db.sources(False):
            self._add_row(s["path"], s["category"], bool(s["recursive"]), cats)
        self.cat_list.clear()
        for c in cats:
            it = QListWidgetItem(c)
            it.setBackground(QBrush(QColor(category_color(c))))
            it.setForeground(QBrush(QColor("#111")))
            self.cat_list.addItem(it)

    def _add_row(self, path, category, recursive, cats=None):
        cats = cats or self.db.categories()
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(path))
        combo = QComboBox()
        combo.addItems(cats)
        if category in cats:
            combo.setCurrentText(category)
        self.table.setCellWidget(r, 1, combo)
        cb = QCheckBox("Sí")
        cb.setChecked(recursive)
        self.table.setCellWidget(r, 2, cb)

    def add_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if p:
            self._ask_category_and_add(p)

    def add_manual(self):
        p, ok = QInputDialog.getText(self, "Ruta", "Carpeta local o UNC:")
        if ok and p.strip():
            self._ask_category_and_add(p.strip())

    def _ask_category_and_add(self, p):
        cats = self.db.categories()
        cat, ok = QInputDialog.getItem(self, "Categoría", "Categoría para esta fuente:", cats, 0, False)
        if ok:
            self._add_row(p, cat, True, cats)

    def remove_selected(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def save(self):
        rows = []
        for r in range(self.table.rowCount()):
            p = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
            c = self.table.cellWidget(r, 1).currentText()
            rec = self.table.cellWidget(r, 2).isChecked()
            if p:
                rows.append((p, c, rec))
        self.db.replace_sources(rows)
        self.parent().statusBar().showMessage(f"Fuentes guardadas ({len(rows)})")
        self.parent().refresh_categories()

    def add_category(self):
        name, ok = QInputDialog.getText(self, "Nueva categoría", "Nombre:")
        if ok and name.strip():
            self.db.add_category(name.strip())
            self.reload()
            self.parent().refresh_categories()

    def delete_category(self):
        it = self.cat_list.currentItem()
        if not it:
            return
        if QMessageBox.question(self, "Categoría", f"¿Eliminar «{it.text()}»? Los medios conservan el nombre de categoría.") == QMessageBox.Yes:
            self.db.delete_category(it.text())
            self.reload()
            self.parent().refresh_categories()


# ============================================================ PROGRAMADOR
class SchedulerDialog(BaseDialog):
    def __init__(self, parent, db, scheduler):
        super().__init__(parent, "Programador — Diario / Semanal / Mensual / Trimestral", 1150, 680)
        self.db = db
        self.scheduler = scheduler
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Cada regla genera una playlist automática desde una categoría y la pone AL AIRE a la hora indicada "
                              "(también actualiza las salidas RTMP/SRT/NDI si están activas). Una regla Diario genera una lista por fecha; "
                              "activa Loop para repetirla al terminar y Autofill para añadir medios cuando se agote, hasta que la próxima "
                              "generación diaria reemplace la lista."))
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["Activo", "Nombre", "Modo", "Hora", "Días", "Día mes", "Mes Q", "Categoría",
                                              "Cantidad", "Orden", "Próxima ejecución"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._load_selected_into_form)
        root.addWidget(self.table, 1)

        box = QGroupBox("Regla")
        form = QGridLayout(box)
        self.name = QLineEdit()
        self.mode = QComboBox()
        for k, v in MODE_LABELS.items():
            self.mode.addItem(v, k)
        self.tm = QTimeEdit()
        self.tm.setDisplayFormat("HH:mm")
        self.tm.setTime(QTime.currentTime())
        self.cat = QComboBox()
        self.cat.addItem("Todas")
        self.cat.addItems(db.categories())
        self.count = QSpinBox()
        self.count.setRange(1, 10000)
        self.count.setValue(20)
        self.order = QComboBox()
        for k, v in (("sequential", "Secuencial"), ("random", "Aleatorio"), ("recent", "Recientes")):
            self.order.addItem(v, k)
        self.dom = QSpinBox()
        self.dom.setRange(1, 31)
        self.moq = QSpinBox()
        self.moq.setRange(1, 3)
        form.addWidget(QLabel("Nombre"), 0, 0)
        form.addWidget(self.name, 0, 1, 1, 3)
        form.addWidget(QLabel("Modo"), 0, 4)
        form.addWidget(self.mode, 0, 5)
        form.addWidget(QLabel("Hora"), 0, 6)
        form.addWidget(self.tm, 0, 7)
        form.addWidget(QLabel("Día del mes"), 1, 0)
        form.addWidget(self.dom, 1, 1)
        form.addWidget(QLabel("Mes del trimestre"), 1, 2)
        form.addWidget(self.moq, 1, 3)
        form.addWidget(QLabel("Categoría"), 1, 4)
        form.addWidget(self.cat, 1, 5)
        form.addWidget(QLabel("Cantidad"), 1, 6)
        form.addWidget(self.count, 1, 7)
        form.addWidget(QLabel("Orden"), 1, 8)
        form.addWidget(self.order, 1, 9)
        form.addWidget(QLabel("Días semana"), 2, 0)
        self.days = []
        for n, t in enumerate(DAY_LABELS):
            cb = QCheckBox(t)
            cb.setChecked(True)
            self.days.append(cb)
            form.addWidget(cb, 2, n + 1)
        root.addWidget(box)
        self.mode.currentIndexChanged.connect(self._mode_state)
        self._mode_state()

        buttons = QHBoxLayout()
        buttons.addWidget(_btn("💾 Guardar regla", self.save, "primary"))
        buttons.addWidget(_btn("✚ Nueva (limpiar formulario)", self.clear_form))
        buttons.addWidget(_btn("▶ Ejecutar ahora", self.run_now))
        buttons.addWidget(_btn("⏻ Activar / Desactivar", self.toggle))
        buttons.addWidget(_btn("🗑 Eliminar", self.delete, "danger"))
        buttons.addStretch()
        buttons.addWidget(_btn("Cerrar", self.accept))
        root.addLayout(buttons)
        self.reload()

    def _mode_state(self):
        m = self.mode.currentData()
        for cb in self.days:
            cb.setEnabled(m == "weekly")
        self.dom.setEnabled(m in ("monthly", "quarterly"))
        self.moq.setEnabled(m == "quarterly")

    def reload(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for r in self.db.schedules():
            i = self.table.rowCount()
            self.table.insertRow(i)
            days = ",".join(DAY_LABELS[int(x)] for x in (r["days"] or "").split(",") if x.strip().isdigit()) if r["mode"] == "weekly" else ""
            nr = self.scheduler.next_run(r)
            vals = ["ON" if r["enabled"] else "OFF", r["name"], MODE_LABELS.get(r["mode"], r["mode"]), r["start_time"], days,
                    str(r["day_of_month"] or "") if r["mode"] in ("monthly", "quarterly") else "",
                    str(r["month_of_quarter"] or "") if r["mode"] == "quarterly" else "",
                    r["category"], str(r["item_count"]), {"sequential": "Secuencial", "random": "Aleatorio", "recent": "Recientes"}.get(r["order_mode"], r["order_mode"]),
                    f"{DAY_LABELS[nr.weekday()]} {nr:%d/%m %H:%M}" if (nr and r["enabled"]) else "—"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, r["id"])
                if c == 0:
                    it.setForeground(QBrush(QColor("#4be36a" if r["enabled"] else "#888")))
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, c, it)
        self.table.blockSignals(False)

    def _selected_row(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        sid = self.table.item(r, 0).data(Qt.UserRole)
        return next((x for x in self.db.schedules() if x["id"] == sid), None)

    def _load_selected_into_form(self):
        s = self._selected_row()
        if not s:
            return
        self.name.setText(s["name"])
        idx = self.mode.findData(s["mode"])
        self.mode.setCurrentIndex(max(0, idx))
        self.tm.setTime(QTime.fromString((s["start_time"] or "00:00")[:5], "HH:mm"))
        self.cat.setCurrentText(s["category"] or "Todas")
        self.count.setValue(int(s["item_count"] or 1))
        self.order.setCurrentIndex(max(0, self.order.findData(s["order_mode"])))
        self.dom.setValue(int(s["day_of_month"] or 1))
        self.moq.setValue(int(s["month_of_quarter"] or 1))
        days = {int(x) for x in (s["days"] or "").split(",") if x.strip().isdigit()}
        for i, cb in enumerate(self.days):
            cb.setChecked(i in days if s["mode"] == "weekly" else True)

    def clear_form(self):
        self.table.clearSelection()
        self.name.clear()
        self.name.setFocus()

    def save(self):
        n = self.name.text().strip()
        if not n:
            QMessageBox.warning(self, "Programador", "Escribe un nombre.")
            return
        m = self.mode.currentData()
        ds = ",".join(str(i) for i, cb in enumerate(self.days) if cb.isChecked()) if m == "weekly" else ""
        if m == "weekly" and not ds:
            QMessageBox.warning(self, "Programador", "Selecciona al menos un día.")
            return
        self.db.add_schedule(n, m, self.tm.time().toString("HH:mm"), ds, self.dom.value(), self.moq.value(),
                             self.cat.currentText(), self.count.value(), self.order.currentData())
        self.reload()
        self.parent().statusBar().showMessage(f"Programación «{n}» guardada")

    def run_now(self):
        s = self._selected_row()
        if not s:
            QMessageBox.warning(self, "Programador", "Selecciona una regla guardada.")
            return
        self.scheduler.run_schedule_now(s["id"])

    def toggle(self):
        s = self._selected_row()
        if s:
            self.db.set_schedule_enabled(s["id"], not bool(s["enabled"]))
            self.reload()

    def delete(self):
        s = self._selected_row()
        if s and QMessageBox.question(self, "Eliminar", f"¿Eliminar la regla «{s['name']}»?") == QMessageBox.Yes:
            self.db.delete_schedule(s["id"])
            self.reload()


# ============================================================ REGISTROS (AS-RUN + SISTEMA)
class LogsDialog(BaseDialog):
    line_received = Signal(str)   # los logs pueden llegar desde hilos de trabajo → señal (cola) hacia el hilo GUI

    def __init__(self, parent, db):
        super().__init__(parent, "Registros — As-Run y sistema", 1000, 620)
        self.db = db
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        w = QWidget()
        al = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel("Día:"))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.dateChanged.connect(self.reload_air)
        top.addWidget(self.date)
        top.addWidget(_btn("↻ Actualizar", self.reload_air))
        top.addWidget(_btn("⬇ Exportar CSV…", self.export_csv))
        top.addStretch()
        self.air_summary = QLabel("")
        top.addWidget(self.air_summary)
        al.addLayout(top)
        self.air_table = QTableWidget(0, 7)
        self.air_table.setHorizontalHeaderLabels(["Inicio", "Fin", "Título", "Categoría", "Duración", "Estado", "Nota"])
        self.air_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.air_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.air_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.air_table.verticalHeader().setVisible(False)
        al.addWidget(self.air_table, 1)
        tabs.addTab(w, "AS-RUN LOG (emitido)")

        w2 = QWidget()
        sl = QVBoxLayout(w2)
        # v22.2.6: filtros por nivel + colorear líneas para ver errores
        # de un vistazo. Antes el QPlainTextEdit mostraba todo en un solo
        # color y era difícil detectar ERROR/WARNING entre la maraña de INFO.
        filt = QHBoxLayout()
        filt.addWidget(QLabel("Nivel:"))
        self.filter_level = QComboBox()
        self.filter_level.addItems(["TODO", "INFO+", "WARNING+", "SOLO ERROR"])
        self.filter_level.currentIndexChanged.connect(self._refilter)
        filt.addWidget(self.filter_level)
        filt.addStretch()
        filt.addWidget(QLabel(f"Archivo: {logger.LOG_FILE}"))
        filt.addWidget(_btn("📂 Abrir carpeta", self._open_log_dir))
        filt.addWidget(_btn("Limpiar vista", self._clear_sys))
        sl.addLayout(filt)
        self.sys_text = QPlainTextEdit()
        self.sys_text.setReadOnly(True)
        self.sys_text.setMaximumBlockCount(3000)
        self.sys_text.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 11px;")
        sl.addWidget(self.sys_text, 1)
        # Buffer de líneas recientes (con su nivel). El listener de logger
        # las guarda acá; el filtro decide cuáles pintar.
        self._sys_buf = []
        tabs.addTab(w2, "SISTEMA")

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(_btn("Cerrar", self.accept))
        v.addLayout(bottom)
        # Cargar últimas líneas con su nivel
        for line in logger.recent_lines(1000):
            self._sys_buf.append(self._classify(line))
        self._refilter()
        self.line_received.connect(self._on_log_line)
        self._listener = self.line_received.emit
        logger.add_listener(self._listener)
        self.reload_air()

    def _classify(self, line):
        """Devuelve (line, level) donde level in {INFO, WARNING, ERROR, DEBUG}."""
        up = line.upper()
        if "ERROR" in up:
            return (line, "ERROR")
        if "WARNING" in up:
            return (line, "WARNING")
        if "DEBUG" in up:
            return (line, "DEBUG")
        return (line, "INFO")

    def _color_for(self, level):
        return {
            "ERROR":   QColor("#ff5050"),
            "WARNING": QColor("#ffb84d"),
            "DEBUG":   QColor("#808080"),
            "INFO":    QColor("#cfd8dc"),
        }.get(level, QColor("#cfd8dc"))

    def _passes_filter(self, level):
        idx = self.filter_level.currentIndex()
        order = ["INFO", "DEBUG", "WARNING", "ERROR"]
        # TODO:0, INFO+:1 (todo), WARNING+:2, SOLO ERROR:3
        if idx == 0:
            return True
        if idx == 1:
            return level in ("INFO", "DEBUG", "WARNING", "ERROR")
        if idx == 2:
            return level in ("WARNING", "ERROR")
        if idx == 3:
            return level == "ERROR"
        return True

    def _refilter(self):
        self.sys_text.clear()
        for line, level in self._sys_buf:
            if self._passes_filter(level):
                self.sys_text.setTextColor(self._color_for(level))
                self.sys_text.appendPlainText(line)
        self.sys_text.setTextColor(self._color_for("INFO"))
        sb = self.sys_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_log_line(self, line):
        classified = self._classify(line)
        self._sys_buf.append(classified)
        if len(self._sys_buf) > 3000:
            self._sys_buf = self._sys_buf[-3000:]
        if self._passes_filter(classified[1]):
            self.sys_text.setTextColor(self._color_for(classified[1]))
            self.sys_text.appendPlainText(line)
            self.sys_text.setTextColor(self._color_for("INFO"))
            sb = self.sys_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _open_log_dir(self):
        try:
            import os, subprocess
            p = os.path.dirname(str(logger.LOG_FILE))
            if os.name == "nt":
                os.startfile(p)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Logs", f"No se pudo abrir la carpeta: {e}")

    def _clear_sys(self):
        # Limpia la vista Y el buffer local (no toca el archivo de log).
        self._sys_buf.clear()
        self.sys_text.clear()

    def closeEvent(self, event):
        logger.remove_listener(self._listener)
        super().closeEvent(event)

    def reload_air(self):
        day = self.date.date().toString("yyyy-MM-dd")
        rows = self.db.air_logs(day)
        self.air_table.setRowCount(0)
        total = 0.0
        for r in rows:
            i = self.air_table.rowCount()
            self.air_table.insertRow(i)
            started = (r["started_at"] or "")[11:19]
            ended = (r["ended_at"] or "")[11:19]
            real = ""
            try:
                if r["ended_at"]:
                    real = fmt_tc((datetime.fromisoformat(r["ended_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds())
            except ValueError:
                pass
            vals = [started, ended, r["title"], r["category"], real or fmt_tc(r["duration"]), r["status"], r["note"] or ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 5:
                    color = {"EMITIDO": "#4be36a", "ON AIR": "#ff5050", "CORTADO": "#ffd21f", "ERROR": "#ff5050"}.get(v, "#ccc")
                    it.setForeground(QBrush(QColor(color)))
                self.air_table.setItem(i, c, it)
            total += r["duration"] or 0
        self.air_summary.setText(f"{len(rows)} eventos • {fmt_tc(total)}")

    def export_csv(self):
        day = self.date.date().toString("yyyy-MM-dd")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar as-run", str(ROOT / f"asrun_{day}.csv"), "CSV (*.csv)")
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["inicio", "fin", "titulo", "ruta", "categoria", "duracion_s", "estado", "nota"])
                for r in self.db.air_logs(day):
                    w.writerow([r["started_at"], r["ended_at"], r["title"], r["path"], r["category"], f"{r['duration']:.1f}", r["status"], r["note"]])
            self.parent().statusBar().showMessage("As-run exportado: " + path)
        except OSError as e:
            QMessageBox.critical(self, "Exportar", str(e))


# ============================================================ AJUSTES DEL SISTEMA
class SettingsDialog(BaseDialog):
    """Ajustes: salida RTMP/encoder, audio/subtítulos, automatización, rutas de binarios."""

    def __init__(self, parent, settings: dict):
        super().__init__(parent, "Ajustes del sistema", 720, 620)
        self.settings = dict(settings)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # --- salida
        w = QWidget()
        f = QFormLayout(w)
        self.rtmp = QLineEdit(self.settings.get("rtmp_url", ""))
        self.rtmp.setPlaceholderText("rtmp://servidor/app/clave  •  rtmps://…  •  srt://host:puerto")
        self.res = QComboBox()
        self.res.setEditable(True)
        self.res.addItems(RESOLUTIONS)
        self.res.setCurrentText(self.settings.get("resolution", "1920x1080"))
        self.fps = QComboBox()
        self.fps.addItems(FPS_LIST)
        self.fps.setCurrentText(str(self.settings.get("fps", "29.97")))
        self.encoder = QComboBox()
        self.encoder.addItems(ENCODERS)
        self.encoder.setCurrentText(self.settings.get("encoder", "AUTO"))
        self.bitrate = QSpinBox()
        self.bitrate.setRange(300, 60000)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setValue(int(self.settings.get("bitrate", 6000)))
        self.abitrate = QComboBox()
        self.abitrate.addItems(["96", "128", "160", "192", "256", "320"])
        self.abitrate.setCurrentText(str(self.settings.get("audio_bitrate", 192)))
        self.burn = QCheckBox("Quemar subtítulos preferidos en la salida RTMP (más CPU)")
        self.burn.setChecked(bool(self.settings.get("subtitle_burn", False)))
        self.extra = QLineEdit(self.settings.get("ffmpeg_extra", ""))
        self.extra.setPlaceholderText("argumentos extra de FFmpeg (avanzado)")
        self.autostart_rtmp = QCheckBox("Iniciar salidas IP automáticamente al abrir la aplicación si hay playlist")
        self.autostart_rtmp.setChecked(bool(self.settings.get("rtmp_autostart", False)))
        self.outputs_btn = QPushButton("Configurar destinos RTMP / SRT / NDI…")
        self.outputs_btn.clicked.connect(parent.open_outputs)
        f.addRow("Destinos", self.outputs_btn)
        f.addRow("URL de salida", self.rtmp)
        f.addRow("Resolución", self.res)
        f.addRow("FPS", self.fps)
        f.addRow("Encoder", self.encoder)
        f.addRow("Bitrate vídeo", self.bitrate)
        f.addRow("Bitrate audio (kbps)", self.abitrate)
        f.addRow("", self.burn)
        f.addRow("FFmpeg extra", self.extra)
        f.addRow("", self.autostart_rtmp)
        tabs.addTab(self.scroll_page(w), "SALIDA RTMP")

        # --- audio / subs / automatización
        w2 = QWidget()
        f2 = QFormLayout(w2)
        self.audio = QComboBox()
        self.audio.addItems(AUDIO_PREFS)
        self.audio.setCurrentText(self.settings.get("audio_pref", AUDIO_PREFS[0]))
        self.sub = QComboBox()
        self.sub.addItems(SUB_PREFS)
        self.sub.setCurrentText(self.settings.get("sub_pref", "OFF"))
        self.hwdec = QComboBox()
        self.hwdec.addItems(["auto-safe", "auto", "no", "d3d11va", "dxva2", "nvdec", "cuda", "qsv"])
        self.hwdec.setCurrentText(self.settings.get("hwdec", "auto-safe"))
        self.audio_device = QLineEdit(self.settings.get("audio_device", ""))
        self.audio_device.setPlaceholderText("vacío = predeterminado (ej. wasapi/{guid})")
        self.monitor_mode = QComboBox()
        self.monitor_mode.addItem("PyAV/libav (predeterminado)", "pyav")
        self.monitor_mode.addItem("Programa FFmpeg → reproductor externo", "program_feed")
        # v24.0.2.37: para VPS sin monitor ni CPU de sobra: el playout avanza
        # con el reloj de pared y sólo FFmpeg decodifica (las salidas IP).
        self.monitor_mode.addItem("Reloj del sistema (sin decodificar — ideal VPS)", "clock")
        self.monitor_mode.setCurrentIndex(max(0, self.monitor_mode.findData(self.settings.get("monitor_mode", "pyav"))))
        self.monitor_player = QComboBox()
        self.monitor_player.addItems(["VLC", "mpv", "ffplay"])
        self.monitor_player.setCurrentText(str(self.settings.get("monitor_player", "VLC")))
        self.monitor_player_path = QLineEdit(self.settings.get("monitor_player_path", ""))
        self.monitor_player_path.setPlaceholderText("vlc.exe, mpv.exe o ffplay.exe")
        self.monitor_player_browse = QPushButton("Buscar…")
        self.monitor_player_browse.clicked.connect(self._choose_monitor_player)
        monitor_path_row = QHBoxLayout()
        monitor_path_row.addWidget(self.monitor_player_path, 1)
        monitor_path_row.addWidget(self.monitor_player_browse)
        self.monitor_feed_port = QSpinBox()
        self.monitor_feed_port.setRange(1024, 65535)
        self.monitor_feed_port.setValue(int(self.settings.get("monitor_feed_port", 39000)))
        self.autofill_cat = QComboBox()
        self.autofill_cat.addItem("Todas")
        self.autofill_cat.addItems(parent.db.categories())
        self.autofill_cat.setCurrentText(self.settings.get("autofill_category", "Todas"))
        self.autofill_n = QSpinBox()
        self.autofill_n.setRange(1, 500)
        self.autofill_n.setValue(int(self.settings.get("autofill_count", 10)))
        self.tanda_cat = QComboBox()
        self.tanda_cat.addItems(parent.db.categories())
        self.tanda_cat.setCurrentText(self.settings.get("tandas_category", "Publicidad"))
        self.tanda_n = QSpinBox()
        self.tanda_n.setRange(1, 20)
        self.tanda_n.setValue(int(self.settings.get("tandas_count", 2)))
        self.midroll_enabled = QCheckBox("Activar tanda intermedia (control separado de la tanda al final)")
        self.midroll_enabled.setChecked(bool(self.settings.get("midroll_enabled", False)))
        self.midroll_cat = QComboBox()
        self.midroll_cat.addItems(parent.db.categories())
        self.midroll_cat.setCurrentText(self.settings.get("midroll_category", "Publicidad"))
        self.midroll_interval = QSpinBox()
        self.midroll_interval.setRange(1, 240)
        self.midroll_interval.setSuffix(" min")
        self.midroll_interval.setValue(max(1, int(self.settings.get("midroll_interval_minutes", 15))))
        self.identifiers_enabled = QCheckBox("Activar identificadores en Películas y Música")
        self.identifiers_enabled.setChecked(bool(self.settings.get("identifiers_enabled", False)))
        self.identifier_in = QLineEdit(self.settings.get("identifier_in_path", ""))
        self.identifier_in.setPlaceholderText("Vídeo de entrada • aproximadamente 8 segundos")
        self.identifier_in_browse = QPushButton("Buscar…")
        self.identifier_in_browse.clicked.connect(lambda: self._choose_identifier(self.identifier_in))
        in_row = QHBoxLayout()
        in_row.addWidget(self.identifier_in, 1)
        in_row.addWidget(self.identifier_in_browse)
        self.identifier_out = QLineEdit(self.settings.get("identifier_out_path", ""))
        self.identifier_out.setPlaceholderText("Vídeo de salida • aproximadamente 8 segundos")
        self.identifier_out_browse = QPushButton("Buscar…")
        self.identifier_out_browse.clicked.connect(lambda: self._choose_identifier(self.identifier_out))
        out_row = QHBoxLayout()
        out_row.addWidget(self.identifier_out, 1)
        out_row.addWidget(self.identifier_out_browse)
        self.tmdb_enabled = QCheckBox("Mostrar tarjeta TMDB periódica para Películas")
        self.tmdb_enabled.setChecked(bool(self.settings.get("tmdb_enabled", False)))
        self.tmdb_key = QLineEdit(self.settings.get("tmdb_api_key", ""))
        self.tmdb_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_key.setPlaceholderText("API key de TMDB")
        self.tmdb_interval = QSpinBox()
        self.tmdb_interval.setRange(1, 240)
        self.tmdb_interval.setSuffix(" min")
        self.tmdb_interval.setValue(max(1, int(self.settings.get("tmdb_interval_minutes", 18))))
        self.tmdb_duration = QSpinBox()
        self.tmdb_duration.setRange(1, 60)
        self.tmdb_duration.setSuffix(" s")
        self.tmdb_duration.setValue(max(1, int(self.settings.get("tmdb_duration_seconds", 15))))
        self.restore_pl = QCheckBox("Restaurar la última playlist al abrir")
        self.restore_pl.setChecked(bool(self.settings.get("restore_playlist", True)))
        self.autoplay = QCheckBox("Poner AL AIRE automáticamente al abrir (continuidad 24/7)")
        self.autoplay.setChecked(bool(self.settings.get("autoplay", False)))
        self.probe_on_scan = QCheckBox("Analizar metadatos/miniaturas tras escanear (requiere ffprobe)")
        self.probe_on_scan.setChecked(bool(self.settings.get("probe_on_scan", True)))
        self.autotrim_on_scan = QCheckBox("Recortar intro/final de películas automáticamente tras escanear (saltar logos de Netflix/HBO/Amazon)")
        self.autotrim_on_scan.setChecked(bool(self.settings.get("autotrim_on_scan", True)))
        self.ndi_disabled = QCheckBox("Deshabilitar salidas NDI temporalmente (dejar solo RTMP y SRT)")
        self.ndi_disabled.setChecked(bool(self.settings.get("ndi_disabled", True)))
        f2.addRow("Audio preferido", self.audio)
        f2.addRow("Subtítulos preferidos", self.sub)
        f2.addRow("", _note("Si hay un evento al aire, guardar estos valores cambia la pista en vivo; puede haber un corte IP breve."))
        f2.addRow("Decodificación HW (mpv)", self.hwdec)
        f2.addRow("Dispositivo de audio (mpv)", self.audio_device)
        f2.addRow("Monitor de programa", self.monitor_mode)
        f2.addRow("Reproductor monitor", self.monitor_player)
        f2.addRow("Ejecutable monitor", monitor_path_row)
        f2.addRow("Puerto feed local", self.monitor_feed_port)
        f2.addRow("", _note("El modo Programa FFmpeg muestra en VLC/mpv/ffplay la misma señal codificada que sale por RTMP/SRT, incluyendo subtítulos y audio. PyAV sigue siendo el modo predeterminado."))
        f2.addRow("Autofill: categoría", self.autofill_cat)
        f2.addRow("Autofill: cantidad", self.autofill_n)
        f2.addRow("Tandas: categoría", self.tanda_cat)
        f2.addRow("Tandas: anuncios por corte", self.tanda_n)
        f2.addRow("", self.midroll_enabled)
        f2.addRow("Tanda intermedia: categoría", self.midroll_cat)
        f2.addRow("Tanda intermedia: intervalo", self.midroll_interval)
        f2.addRow("", self.identifiers_enabled)
        f2.addRow("Identificador de entrada", in_row)
        f2.addRow("Identificador de salida", out_row)
        f2.addRow("", _note("Los identificadores se usan sólo en Películas y Música; no se insertan en Publicidad, filler ni slate."))
        f2.addRow("", self.tmdb_enabled)
        f2.addRow("TMDB API key", self.tmdb_key)
        f2.addRow("TMDB: intervalo", self.tmdb_interval)
        f2.addRow("TMDB: duración visible", self.tmdb_duration)
        f2.addRow("", _note("La tarjeta combina backdrop, póster, título y año; su posición, alineación y estilo se ajustan con vista previa en Tarjeta TMDB (panel FUNCIONES). Requiere una API key de TMDB."))
        f2.addRow("", self.restore_pl)
        f2.addRow("", self.autoplay)
        f2.addRow("", self.probe_on_scan)
        f2.addRow("", self.autotrim_on_scan)
        f2.addRow("", self.ndi_disabled)
        tabs.addTab(self.scroll_page(w2), "REPRODUCCIÓN / AUTOMATIZACIÓN")

        # --- sistema
        w3 = QWidget()
        f3 = QFormLayout(w3)
        def chip(path):
            l = QLabel(path or "NO ENCONTRADO")
            l.setStyleSheet(f"color:{'#4be36a' if path else '#ff5050'};")
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return l
        f3.addRow("mpv", chip(MPV_PATH))
        f3.addRow("VLC (opcional)", chip(VLC_PATH))
        f3.addRow("ffmpeg", chip(FFMPEG_PATH))
        f3.addRow("ffprobe", chip(FFPROBE_PATH))
        f3.addRow("Base de datos", chip(str(DB_PATH)))
        f3.addRow("Carpeta del proyecto", chip(str(ROOT)))
        note = QLabel("Coloca mpv.exe en mpv-x86_64\\ y ffmpeg.exe + ffprobe.exe en la raíz del proyecto (o carpeta ffmpeg\\bin). "
                      "VLC es opcional: se usa como reproductor alternativo de vistas previas y del monitor de programa. "
                      "También puedes definir MPV_PATH / FFMPEG_PATH / VLC_PATH en un archivo .env. Reinicia tras cambiar rutas.")
        note.setWordWrap(True)
        f3.addRow(note)
        tabs.addTab(self.scroll_page(w3), "SISTEMA")

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(_btn("Cancelar", self.reject))
        bottom.addWidget(_btn("💾 Guardar", self.accept, "primary"))
        v.addLayout(bottom)
        self.setModal(True)

    def _choose_monitor_player(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar reproductor del monitor", "",
            "Ejecutables (*.exe);;Todos los archivos (*.*)",
        )
        if path:
            self.monitor_player_path.setText(path)

    def _choose_identifier(self, field):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar identificador de aproximadamente 8 segundos", "",
            "Vídeo (*.mp4 *.mov *.mkv *.avi *.webm *.ts);;Todos los archivos (*.*)",
        )
        if path:
            field.setText(path)

    def values(self):
        return {
            "rtmp_url": self.rtmp.text().strip(),
            "resolution": self.res.currentText().strip(),
            "fps": self.fps.currentText(),
            "encoder": self.encoder.currentText(),
            "bitrate": self.bitrate.value(),
            "audio_bitrate": int(self.abitrate.currentText()),
            "subtitle_burn": self.burn.isChecked(),
            "ffmpeg_extra": self.extra.text().strip(),
            "rtmp_autostart": self.autostart_rtmp.isChecked(),
            "audio_pref": self.audio.currentText(),
            "sub_pref": self.sub.currentText(),
            "hwdec": self.hwdec.currentText(),
            "audio_device": self.audio_device.text().strip(),
            "monitor_mode": self.monitor_mode.currentData() or "pyav",
            "monitor_player": self.monitor_player.currentText(),
            "monitor_player_path": self.monitor_player_path.text().strip(),
            "monitor_feed_port": self.monitor_feed_port.value(),
            "autofill_category": self.autofill_cat.currentText(),
            "autofill_count": self.autofill_n.value(),
            "tandas_category": self.tanda_cat.currentText(),
            "tandas_count": self.tanda_n.value(),
            "midroll_enabled": self.midroll_enabled.isChecked(),
            "midroll_category": self.midroll_cat.currentText(),
            "midroll_interval_minutes": self.midroll_interval.value(),
            "identifiers_enabled": self.identifiers_enabled.isChecked(),
            "identifier_in_path": self.identifier_in.text().strip(),
            "identifier_out_path": self.identifier_out.text().strip(),
            "tmdb_enabled": self.tmdb_enabled.isChecked(),
            "tmdb_api_key": self.tmdb_key.text().strip(),
            "tmdb_interval_minutes": self.tmdb_interval.value(),
            "tmdb_duration_seconds": self.tmdb_duration.value(),
            "restore_playlist": self.restore_pl.isChecked(),
            "autoplay": self.autoplay.isChecked(),
            "probe_on_scan": self.probe_on_scan.isChecked(),
            "autotrim_on_scan": self.autotrim_on_scan.isChecked(),
            "ndi_disabled": self.ndi_disabled.isChecked(),
        }


# ============================================================ EDITAR CLIP
class EditClipDialog(QDialog):
    def __init__(self, parent, item, categories):
        super().__init__(parent)
        self.setWindowTitle("Editar evento")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 560, 430
        if available is not None:
            width = min(width, max(480, available.width() - 32))
            height = min(height, max(340, available.height() - 56))
        self.resize(width, height)
        self.setMinimumSize(480, 340)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self.item = item
        self.source_duration = max(0.0, float(item.get("source_duration") or item.get("duration") or 0))
        f = QFormLayout(self)
        self.title = QLineEdit(item.get("title", ""))
        self.cat = QComboBox()
        self.cat.addItems(categories)
        if item.get("category") in categories:
            self.cat.setCurrentText(item["category"])
        self.fixed = QLineEdit(item.get("fixed_time", ""))
        self.fixed.setPlaceholderText("HH:MM o HH:MM:SS — vacío = secuencial")
        trim_max = max(86400.0, self.source_duration)
        self.trim_start = QDoubleSpinBox()
        self.trim_start.setDecimals(3)
        self.trim_start.setRange(0.0, trim_max)
        self.trim_start.setSingleStep(0.5)
        self.trim_start.setSuffix(" s")
        self.trim_start.setToolTip("Segundos que se quitarán al principio del video")
        self.trim_start.setValue(max(0.0, min(self.source_duration, float(item.get("mark_in") or 0))))
        self.trim_end = QDoubleSpinBox()
        self.trim_end.setDecimals(3)
        self.trim_end.setRange(0.0, trim_max)
        self.trim_end.setSingleStep(0.5)
        self.trim_end.setSuffix(" s")
        self.trim_end.setToolTip("Segundos que se quitarán al final del video; no necesitas calcular la duración total")
        mark_out = float(item.get("mark_out") or 0)
        end_to_remove = max(0.0, self.source_duration - mark_out) if mark_out > 0 and self.source_duration > 0 else 0.0
        self.trim_end.setValue(min(self.source_duration, end_to_remove))
        self.trim_preview = QLabel()
        self.trim_preview.setStyleSheet("color:#8fd6a3;")
        self.trim_start.valueChanged.connect(self._update_trim_preview)
        self.trim_end.valueChanged.connect(self._update_trim_preview)
        reset = _btn("Restablecer corte", self._reset_trim)
        trim_box = QHBoxLayout()
        trim_box.addWidget(self.trim_start)
        trim_box.addWidget(QLabel("inicio"))
        trim_box.addWidget(self.trim_end)
        trim_box.addWidget(QLabel("final"))
        trim_box.addWidget(reset)
        self._update_trim_preview()
        self.audio = QComboBox()
        self.audio.addItem("Por defecto", "")
        self.sub = QComboBox()
        self.sub.addItem("Por defecto", "")
        self.sub.addItem("OFF", "OFF")
        for t in item.get("tracks") or []:
            label = f"#{t.get('idx', 0) + 1} {t.get('lang') or '?'} {t.get('title') or ''} ({t.get('codec', '')})".strip()
            if t.get("type") == "a":
                # Guardar el índice real evita depender de que el archivo
                # tenga correctamente etiquetado el idioma (eng/es).
                self.audio.addItem(label, f"#{t.get('idx')}")
            elif t.get("type") == "s":
                self.sub.addItem(label, f"#{t.get('idx')}")
        cur_a = self.audio.findData(item.get("audio_lang", ""))
        if cur_a < 0:
            for track in item.get("tracks") or []:
                if (track.get("type") == "a" and item.get("audio_lang") and
                        item.get("audio_lang").lower() in {str(track.get("lang") or "").lower(), str(track.get("title") or "").lower()}):
                    cur_a = self.audio.findData(f"#{track.get('idx')}")
                    break
        self.audio.setCurrentIndex(max(0, cur_a))
        cur_s = self.sub.findData(item.get("subtitle_lang", ""))
        if cur_s < 0:
            for track in item.get("tracks") or []:
                if (track.get("type") == "s" and item.get("subtitle_lang") and
                        item.get("subtitle_lang").lower() in {str(track.get("lang") or "").lower(), str(track.get("title") or "").lower()}):
                    cur_s = self.sub.findData(f"#{track.get('idx')}")
                    break
        self.sub.setCurrentIndex(max(0, cur_s))
        path = QLabel(item.get("path", ""))
        path.setWordWrap(True)
        path.setStyleSheet("color:#9a9a9a;")
        info = QLabel(f"{fmt_tc(item.get('duration') or 0)} • {item.get('width') or '?'}x{item.get('height') or '?'} • "
                      f"{item.get('fps') or '?'} fps • {item.get('video_codec') or '?'} / {item.get('audio_codec') or '?'}")
        info.setStyleSheet("color:#9a9a9a;")
        f.addRow("Título", self.title)
        f.addRow("Categoría", self.cat)
        f.addRow("Recortar (segundos)", trim_box)
        f.addRow("Resultado", self.trim_preview)
        f.addRow("Hora fija", self.fixed)
        f.addRow("Pista de audio", self.audio)
        f.addRow("Subtítulos", self.sub)
        f.addRow("Archivo", path)
        f.addRow("Info", info)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(_btn("Cancelar", self.reject))
        row.addWidget(_btn("Aceptar", self._accept, "primary"))
        f.addRow(row)

    def _reset_trim(self):
        self.trim_start.setValue(0.0)
        self.trim_end.setValue(0.0)

    def _update_trim_preview(self):
        start = float(self.trim_start.value())
        end = float(self.trim_end.value())
        if self.source_duration > 0:
            result = max(0.0, self.source_duration - start - end)
            self.trim_preview.setText(
                f"Original: {fmt_tc(self.source_duration)} • Resultado: {fmt_tc(result)}"
            )
        else:
            self.trim_preview.setText("Duración original no disponible; escanea el archivo para validar el corte.")

    def _accept(self):
        start = float(self.trim_start.value())
        end = float(self.trim_end.value())
        if self.source_duration > 0 and start + end >= self.source_duration:
            QMessageBox.warning(
                self, "Corte",
                "Los segundos quitados al principio y al final deben dejar al menos una fracción de video."
            )
            return
        self.accept()

    def values(self):
        ft = self.fixed.text().strip()
        if ft:
            parts = ft.split(":")
            try:
                h = int(parts[0]); m = int(parts[1]) if len(parts) > 1 else 0; s = int(parts[2]) if len(parts) > 2 else 0
                ft = f"{h:02d}:{m:02d}" + (f":{s:02d}" if s else "")
            except (ValueError, IndexError):
                ft = ""
        trim_start = float(self.trim_start.value())
        trim_end = float(self.trim_end.value())
        # El modelo interno conserva mark-out como posición absoluta, pero la
        # interfaz permite al operador pensar en segundos a recortar desde el
        # final, sin calcular la duración total del video.
        mark_out = max(0.0, self.source_duration - trim_end) if trim_end > 0 else 0.0
        return {"title": self.title.text().strip() or self.item.get("title", ""), "category": self.cat.currentText(),
                "fixed_time": ft, "audio_lang": self.audio.currentData() or "", "subtitle_lang": self.sub.currentData() or "",
                "mark_in": trim_start, "mark_out": mark_out,
                "source_duration": self.source_duration}


class LibraryClipDialog(QDialog):
    """Editar un medio de la biblioteca: título, categoría y recortes.

    Los recortes (mark in / mark out) se guardan en la biblioteca y se aplican
    automáticamente cuando el medio se añade a la playlist; el archivo original
    nunca se modifica. La interfaz usa la misma metáfora que Editar evento:
    segundos quitados al principio y al final.
    """

    def __init__(self, parent, media, categories):
        super().__init__(parent)
        self.setWindowTitle("Editar clip (biblioteca)")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 540, 400
        if available is not None:
            width = min(int(width), max(480, available.width() - 32))
            height = min(int(height), max(340, available.height() - 56))
        self.resize(max(480, int(width)), max(340, int(height)))
        self.setMinimumSize(480, 340)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)

        m = dict(media or {})
        self.source_duration = max(0.0, float(m.get("duration") or 0))
        self.path = str(m.get("path") or "")

        f = QFormLayout(self)
        self.title = QLineEdit(str(m.get("title") or ""))
        self.cat = QComboBox()
        self.cat.setEditable(True)
        self.cat.addItems(categories)
        if m.get("category") in categories:
            self.cat.setCurrentText(str(m["category"]))
        trim_max = max(86400.0, self.source_duration)
        mark_in = max(0.0, float(m.get("mark_in") or 0))
        mark_out = max(0.0, float(m.get("mark_out") or 0))
        end_removed = max(0.0, self.source_duration - mark_out) if mark_out > 0 and self.source_duration > 0 else 0.0
        self.trim_start = QDoubleSpinBox()
        self.trim_start.setDecimals(3)
        self.trim_start.setRange(0.0, trim_max)
        self.trim_start.setSingleStep(0.5)
        self.trim_start.setSuffix(" s")
        self.trim_start.setToolTip("Segundos que se quitarán al principio (intro, logotipos…)")
        self.trim_start.setValue(min(self.source_duration, mark_in) if self.source_duration else mark_in)
        self.trim_end = QDoubleSpinBox()
        self.trim_end.setDecimals(3)
        self.trim_end.setRange(0.0, trim_max)
        self.trim_end.setSingleStep(0.5)
        self.trim_end.setSuffix(" s")
        self.trim_end.setToolTip("Segundos que se quitarán del final (créditos, cierre…)")
        self.trim_end.setValue(min(self.source_duration, end_removed))
        self.trim_preview = QLabel()
        self.trim_preview.setStyleSheet("color:#8fd6a3;")
        self.trim_start.valueChanged.connect(self._update_trim_preview)
        self.trim_end.valueChanged.connect(self._update_trim_preview)
        reset = _btn("Restablecer corte", self._reset_trim)
        trim_box = QHBoxLayout()
        trim_box.addWidget(self.trim_start)
        trim_box.addWidget(QLabel("quitar del inicio"))
        trim_box.addWidget(self.trim_end)
        trim_box.addWidget(QLabel("quitar del final"))
        trim_box.addWidget(reset)
        path_lbl = QLabel(self.path)
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet("color:#9a9a9a;")
        dur_lbl = QLabel(f"Duración total: {fmt_tc(self.source_duration)}" +
                         (f" • resolución {m.get('width') or '?'}x{m.get('height') or '?'}" if m.get("width") else ""))
        dur_lbl.setStyleSheet("color:#9a9a9a;")
        f.addRow("Título", self.title)
        f.addRow("Categoría", self.cat)
        f.addRow("Recorte", trim_box)
        f.addRow("", self.trim_preview)
        f.addRow("", dur_lbl)
        f.addRow("Archivo", path_lbl)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("💾 Guardar en biblioteca")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        self._update_trim_preview()

    def _reset_trim(self):
        self.trim_start.setValue(0.0)
        self.trim_end.setValue(0.0)

    def _update_trim_preview(self):
        start = float(self.trim_start.value())
        end = float(self.trim_end.value())
        if self.source_duration > 0:
            effective = max(0.0, self.source_duration - start - end)
            self.trim_preview.setText(
                f"Duración al aire: {fmt_tc(effective)}  •  empieza en {fmt_tc(start)}  •  termina en {fmt_tc(max(start, self.source_duration - end))}")
        else:
            self.trim_preview.setText("Duración desconocida: analiza los metadatos para ver la vista previa del corte.")

    def _accept(self):
        start = float(self.trim_start.value())
        end = float(self.trim_end.value())
        if self.source_duration > 0 and start + end >= self.source_duration:
            QMessageBox.warning(self, "Corte",
                                "Los segundos quitados al principio y al final deben dejar al menos una fracción de video.")
            return
        self.accept()

    def values(self):
        trim_start = float(self.trim_start.value())
        trim_end = float(self.trim_end.value())
        mark_out = max(0.0, self.source_duration - trim_end) if trim_end > 0 else 0.0
        return {"title": self.title.text().strip() or "",
                "category": self.cat.currentText().strip() or "Otros",
                "mark_in": trim_start,
                "mark_out": mark_out}
