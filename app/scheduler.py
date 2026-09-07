from datetime import datetime
from PySide6.QtCore import QObject, QTimer, Signal


class SchedulerService(QObject):
    triggered = Signal(object, object)
    status = Signal(str)

    def __init__(self, db):
        super().__init__()
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

    def _match(self, s, now):
        if not s["enabled"]:
            return False
        if (s["start_time"] or "")[:5] != now.strftime("%H:%M"):
            return False
        mode = (s["mode"] or "daily").lower()
        if mode == "daily":
            return True
        if mode == "weekly":
            days = {int(x) for x in (s["days"] or "").split(",") if x.strip().isdigit()}
            return now.weekday() in days
        if mode == "monthly":
            return now.day == int(s["day_of_month"] or 0)
        if mode == "quarterly":
            moq = int(s["month_of_quarter"] or 1)
            return ((now.month - 1) % 3) + 1 == moq and now.day == int(s["day_of_month"] or 1)
        return False

    def run_schedule_now(self, schedule_id):
        rows = self.db.schedules(False)
        s = next((x for x in rows if int(x["id"]) == int(schedule_id)), None)
        if not s:
            return False
        items = self.db.schedule_media(s["category"], s["item_count"], s["order_mode"])
        if items:
            self.status.emit(f"PRUEBA PROGRAMADOR • {s['name']} • {len(items)} medios")
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
            # Mark the minute even when there are no files, preventing a 1-second loop.
            self.db.mark_schedule_run(s["id"], key)
            if items:
                self.status.emit(f"PROGRAMADO • {s['name']} • {len(items)} medios")
                self.triggered.emit(s, items)
            else:
                self.status.emit(f"SIN MEDIOS • {s['name']} • {s['category']}")
