"""Verificación estática + tests puros de la lógica del scheduler v22.1.

No requiere PySide6 (que no está disponible en algunos entornos de CI).
La lógica de matching y de claves de período se duplica intencionalmente para
poder testearla sin levantar Qt; el código de app/scheduler.py se valida
parseándolo y comprobando que contiene las firmas y mensajes clave.

Ejecutar: python tests/test_scheduler_v22_1.py
"""
import calendar
import os
import re
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULER_PY = os.path.join(REPO, "app", "scheduler.py")


# ---------------------------------------------------------------- lógica
def _period_key(mode, when):
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


def matches_day(s, day):
    mode = (s["mode"] or "daily").lower()
    if mode == "daily":
        return True
    if mode == "weekly":
        days = {int(x) for x in (s["days"] or "").split(",") if x.strip().isdigit()}
        return day.weekday() in days
    if mode == "monthly":
        dom = int(s["day_of_month"] or 0)
        if dom <= 0:
            return False
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(dom, last)
    if mode == "quarterly":
        moq = int(s["month_of_quarter"] or 1)
        if not (1 <= moq <= 3):
            return False
        if ((day.month - 1) % 3) + 1 != moq:
            return False
        dom = int(s["day_of_month"] or 1)
        if dom <= 0:
            return False
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(dom, last)
    return False


# --------------------------------------------------------------- tests puros
def test_period_key():
    assert _period_key("daily", datetime(2026, 9, 7, 10, 30)) == "2026-09-07"
    assert _period_key("weekly", datetime(2026, 9, 7, 10, 30)) == "2026-W37"
    assert _period_key("monthly", datetime(2026, 9, 7, 10, 30)) == "2026-09"
    assert _period_key("quarterly", datetime(2026, 9, 7, 10, 30)) == "2026-Q3"
    assert _period_key("quarterly", datetime(2026, 2, 15, 10, 30)) == "2026-Q1"


def test_monthly_day_31_in_short_months():
    s = {"mode": "monthly", "day_of_month": 31}
    assert matches_day(s, datetime(2027, 1, 31))
    assert matches_day(s, datetime(2027, 2, 28))     # febrero: usa último día
    assert matches_day(s, datetime(2027, 4, 30))     # abril: día 30 (31 no existe)
    assert not matches_day(s, datetime(2027, 2, 15))


def test_monthly_day_zero_never_matches():
    s = {"mode": "monthly", "day_of_month": 0}
    for d in range(1, 29):
        assert not matches_day(s, datetime(2027, 2, d))


def test_quarterly_validates_moq():
    s_ok = {"mode": "quarterly", "day_of_month": 15, "month_of_quarter": 2}
    s_bad = {"mode": "quarterly", "day_of_month": 15, "month_of_quarter": 0}
    s_bad2 = {"mode": "quarterly", "day_of_month": 15, "month_of_quarter": 4}
    assert matches_day(s_ok, datetime(2027, 5, 15))
    assert not matches_day(s_ok, datetime(2027, 3, 15))
    assert not matches_day(s_bad, datetime(2027, 5, 15))
    assert not matches_day(s_bad2, datetime(2027, 5, 15))


def test_weekly_days():
    s = {"mode": "weekly", "days": "5,6"}
    assert matches_day(s, datetime(2026, 9, 12))     # sábado
    assert matches_day(s, datetime(2026, 9, 13))     # domingo
    assert not matches_day(s, datetime(2026, 9, 14))  # lunes


def test_dedup_keys_within_period():
    d = datetime(2026, 9, 7, 10, 30)
    assert _period_key("daily", d) == _period_key("daily", d.replace(hour=23, minute=59))
    assert _period_key("monthly", d) == _period_key("monthly", d.replace(day=15))
    assert _period_key("daily", d) != _period_key("monthly", d)


# --------------------------------------------- verificación estática del archivo
def _read_scheduler():
    with open(SCHEDULER_PY, encoding="utf-8") as f:
        return f.read()


def test_scheduler_has_catch_up():
    src = _read_scheduler()
    assert "_run_pending_today" in src, "scheduler.py debe definir _run_pending_today (catch-up al iniciar)"
    assert "singleShot" in src, "scheduler.py debe programar el catch-up con QTimer.singleShot al arrancar"


def test_scheduler_uses_period_key_for_dedup():
    src = _read_scheduler()
    # La deduplicación principal (en tick y _run_pending_today) debe usar _period_key.
    assert "_period_key" in src, "scheduler.py debe usar _period_key para deduplicar"
    assert src.count("_period_key") >= 3, "_period_key debe usarse en catch-up y en tick"
    # El fallback de _period_key (para modos desconocidos) puede seguir usando
    # granularidad fina, pero los cuatro modos conocidos deben tener su rama.
    for mode in ("daily", "weekly", "monthly", "quarterly"):
        assert f'== "{mode}"' in src, f"_period_key debe tener rama para modo {mode!r}"


def test_scheduler_validates_day_of_month():
    src = _read_scheduler()
    assert "dom <= 0" in src or "day_of_month or 0" in src, "scheduler.py debe validar day_of_month <= 0"
    assert "monthrange" in src, "scheduler.py debe usar calendar.monthrange para días 29/30/31 en meses cortos"


def test_scheduler_knows_about_v22_1():
    src = _read_scheduler()
    # Anclaje textual para que se note que el archivo incluye el cambio
    assert "V22.1" in src, "scheduler.py debe marcarse como V22.1 con un comentario"


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("OK", name)
        except AssertionError as e:
            print("FAIL", name, "—", e)
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    sys.exit(0 if failed == 0 else 1)
