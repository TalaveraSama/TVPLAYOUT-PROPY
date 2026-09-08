"""Programador: dispara playlists automáticas por reglas diarias/semanales/mensuales/trimestrales.

V22.1: sincronización al arrancar (catch-up), deduplicación por período y
validación de día del mes (incluye soporte para 29/30/31 en meses cortos).
"""
from datetime import datetime, timedelta
import calendar

from PySide6.QtCore import QObject, QTimer, Signal

from . import logger

log = logger.get("scheduler")

MODE_LABELS = {"daily": "Diario", "weekly": "Semanal", "monthly": "Mensual", "quarterly": "Trimestral"}
DAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _period_key(mode, when):
    """Granularidad correcta para evitar re-disparos:
       daily→YYYY-MM-DD, weekly→YYYY-Www, monthly→YYYY-MM, quarterly→YYYY-Qq.
       Cualquier otra cosa cae a YYYY-MM-DD HH:MM (granularidad anterior)."""
    if mode == "daily":
        return when.strftime("%Y-%m-%d")
    if mode == "weekly":
        iso = when.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if mode == "monthly":
        return when.strftime("%Y-%m")
    if mode == "quarterly":
        q = (when.month - 1) // 3 + 1
        return f"{when.year}-Q{q}"
    return when.strftime("%Y-%m-%d %H:%M")


def _last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


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
            # V22.1: catch-up de reglas cuya hora ya pasó en el día actual.
            # Se ejecuta una sola vez al arrancar (no en cada tick) para no spamear.
            QTimer.singleShot(500, self._run_pending_today)

    def stop(self):
        self.running = False
        self.timer.stop()

    # ----------------------------------------------------------- matching
    @staticmethod
    def matches_day(s, day):
        mode = (s["mode"] or "daily").lower()
        if mode == "daily":
            return True
        if mode == "weekly":
            days = {int(x) for x in (s["days"] or "").split(",") if x.strip().isdigit()}
            return day.weekday() in days
        if mode == "monthly":
            # V22.1: aceptar el último día del mes cuando day_of_month no existe
            # (p.ej. regla "día 31" debe disparar el 28/29 en febrero).
            dom = int(s["day_of_month"] or 0)
            if dom <= 0:
                return False
            return day.day == min(dom, _last_day_of_month(day.year, day.month))
        if mode == "quarterly":
            moq = int(s["month_of_quarter"] or 1)
            if not (1 <= moq <= 3):
                return False
            if ((day.month - 1) % 3) + 1 != moq:
                return False
            dom = int(s["day_of_month"] or 1)
            if dom <= 0:
                return False
            return day.day == min(dom, _last_day_of_month(day.year, day.month))
        return False

    def _match(self, s, now):
        if not s["enabled"]:
            return False
        if (s["start_time"] or "")[:5] != now.strftime("%H:%M"):
            return False
        return self.matches_day(s, now)

    # ----------------------------------------------------------- catch-up
    def _run_pending_today(self):
        """Dispara las reglas habilitadas cuya hora ya pasó en el día actual y
        cuyo last_run_key indica que aún no se ejecutaron en este período."""
        if not self.running:
            return
        now = datetime.now()
        # Si la hora actual no matchea con ninguna regla, no hay nada que hacer.
        current_hhmm = now.strftime("%H:%M")
        for s in self.db.schedules(True):
            if (s["start_time"] or "")[:5] != current_hhmm:
                continue
            if not self.matches_day(s, now):
                continue
            key = _period_key((s["mode"] or "daily").lower(), now)
            if s["last_run_key"] == key:
                continue
            items = self.db.schedule_media(s["category"], s["item_count"], s["order_mode"])
            self.db.mark_schedule_run(s["id"], key)
            if items:
                self.status.emit(f"PROGRAMADO (catch-up) • {s['name']} • {len(items)} medios")
                log.info("Catch-up: programación %s disparada al arrancar (%d medios)", s["name"], len(items))
                self.triggered.emit(s, items)
            else:
                self.status.emit(f"SIN MEDIOS (catch-up) • {s['name']} • {s['category']}")
                log.warning("Catch-up: programación %s sin medios en %s", s["name"], s["category"])

    # ----------------------------------------------------------- planning
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

    # ----------------------------------------------------------- control
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
        for s in self.db.schedules(True):
            if not self._match(s, now):
                continue
            s_key = _period_key((s["mode"] or "daily").lower(), now)
            if s["last_run_key"] == s_key:
                continue
            items = self.db.schedule_media(s["category"], s["item_count"], s["order_mode"])
            self.db.mark_schedule_run(s["id"], s_key)
            if items:
                self.status.emit(f"PROGRAMADO • {s['name']} • {len(items)} medios")
                log.info("Programación %s disparada (%d medios)", s["name"], len(items))
                self.triggered.emit(s, items)
            else:
                self.status.emit(f"SIN MEDIOS • {s['name']} • {s['category']}")
                log.warning("Programación %s sin medios en %s", s["name"], s["category"])
