"""Programador: dispara playlists automáticas por reglas diarias/semanales/mensuales/trimestrales."""
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from . import logger

log = logger.get("scheduler")

MODE_LABELS = {"daily": "Diario", "weekly": "Semanal", "monthly": "Mensual", "quarterly": "Trimestral"}
DAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


class SchedulerService(QObject):
    triggered = Signal(object, object)   # schedule(row), items(list[Row])
    status = Signal(str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.running = False

    def start(self):
        if not self.running:
            self.running = True
            self.timer.start()
            self.status.emit("PROGRAMADOR ACTIVO")

    def stop(self):
        self.running = False
        self.timer.stop()

    @staticmethod
    def matches_day(s, day):
        mode = (s["mode"] or "daily").lower()
        if mode == "daily":
            return True
        if mode == "weekly":
            days = {int(x) for x in (s["days"] or "").split(",") if x.strip().isdigit()}
            return day.weekday() in days
        if mode == "monthly":
            return day.day == int(s["day_of_month"] or 0)
        if mode == "quarterly":
            moq = int(s["month_of_quarter"] or 1)
            return ((day.month - 1) % 3) + 1 == moq and day.day == int(s["day_of_month"] or 1)
        return False

    def _match(self, s, now):
        if not s["enabled"]:
            return False
        if (s["start_time"] or "")[:5] != now.strftime("%H:%M"):
            return False
        return self.matches_day(s, now)

    def next_run(self, s, now=None):
        """Próxima ejecución (datetime) de una regla o None."""
        now = now or datetime.now()
        try:
            h, m = [int(x) for x in (s["start_time"] or "00:00")[:5].split(":")]
        except ValueError:
            return None
        for d in range(0, 370):
            day = (now + timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)
            if day <= now:
                continue
            if self.matches_day(s, day):
                return day
        return None

    def upcoming(self, limit=10):
        now = datetime.now()
        out = []
        for s in self.db.schedules(True):
            nr = self.next_run(s, now)
            if nr:
                out.append((nr, s))
        out.sort(key=lambda x: x[0])
        return out[:limit]

    def run_schedule_now(self, schedule_id):
        rows = self.db.schedules(False)
        s = next((x for x in rows if int(x["id"]) == int(schedule_id)), None)
        if not s:
            return False
        items = self.db.schedule_media(s["category"], s["item_count"], s["order_mode"])
        if items:
            self.status.emit(f"PRUEBA PROGRAMADOR • {s['name']} • {len(items)} medios")
            log.info("Ejecución manual de la programación %s (%d medios)", s["name"], len(items))
            self.triggered.emit(s, items)
            return True
        self.status.emit(f"SIN MEDIOS • {s['name']} • {s['category']}")
        return False

    def tick(self):
        if not self.running:
            return
        now = datetime.now()
        key = now.strftime("%Y-%m-%d %H:%M")
        for s in self.db.schedules(True):
            if not self._match(s, now) or s["last_run_key"] == key:
                continue
            items = self.db.schedule_media(s["category"], s["item_count"], s["order_mode"])
            self.db.mark_schedule_run(s["id"], key)
            if items:
                self.status.emit(f"PROGRAMADO • {s['name']} • {len(items)} medios")
                log.info("Programación %s disparada (%d medios)", s["name"], len(items))
                self.triggered.emit(s, items)
            else:
                self.status.emit(f"SIN MEDIOS • {s['name']} • {s['category']}")
                log.warning("Programación %s sin medios en %s", s["name"], s["category"])
