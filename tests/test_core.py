"""Pruebas rápidas de la lógica sin interfaz gráfica (DB, selección de pistas, tiempos, scheduler).

Ejecutar:  python -m pytest tests -q      (o)      python tests/test_core.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.db import DB, CURRENT_PLAYLIST  # noqa: E402
from app.prober import pick_audio, pick_subtitle  # noqa: E402
from app.playout import parse_fixed_time, make_item  # noqa: E402
from app.scheduler import SchedulerService  # noqa: E402
from app.widgets import fmt_tc  # noqa: E402


def _db():
    d = tempfile.mkdtemp()
    return DB(os.path.join(d, "t.db"))


def test_fmt_tc():
    assert fmt_tc(0) == "00:00:00"
    assert fmt_tc(3661.4) == "01:01:01"
    assert fmt_tc(-5) == "-00:00:05"
    assert fmt_tc(None) == "00:00:00"
    assert fmt_tc(65, show_hours=False) == "01:05"
    assert fmt_tc(3661, show_hours=False) == "01:01:01"  # las horas se muestran si h>0
    assert fmt_tc(1.5, frames=True, fps=10.0) == "00:00:01.05"


def test_pick_tracks_prefers_latino():
    tracks = [
        {"type": "a", "idx": 0, "lang": "eng", "title": "English"},
        {"type": "a", "idx": 1, "lang": "spa", "title": "Castellano"},
        {"type": "a", "idx": 2, "lang": "spa", "title": "Latino"},
        {"type": "s", "idx": 0, "lang": "eng", "title": ""},
        {"type": "s", "idx": 1, "lang": "spa", "title": "Forzados"},
    ]
    assert pick_audio(tracks, "AUTO / Español latino preferido") == 2
    assert pick_audio(tracks, "Original") is None
    assert pick_audio(tracks, "#1") == 1
    assert pick_subtitle(tracks, "OFF") == -1
    assert pick_subtitle(tracks, "AUTO / Español MX preferido") == 1
    assert pick_audio([], "AUTO") is None


def test_parse_fixed_time():
    ref = datetime(2026, 9, 7, 10, 0, 0)
    assert parse_fixed_time("20:30", ref) == datetime(2026, 9, 7, 20, 30)
    assert parse_fixed_time("08:00:15", ref) == datetime(2026, 9, 7, 8, 0, 15)
    # hace más de 12 h → se interpreta como mañana
    assert parse_fixed_time("01:00", datetime(2026, 9, 7, 23, 0)) == datetime(2026, 9, 8, 1, 0)
    assert parse_fixed_time("99:00", ref) is None
    assert parse_fixed_time("", ref) is None


def test_db_media_playlist_settings_airlog():
    db = _db()
    db.add_source("/tmp/x", "Películas", True)
    assert len(db.sources()) == 1
    db.upsert_media("/tmp/x/a.mkv", "A", "Películas")
    db.upsert_media("/tmp/x/b.mp4", "B", "Publicidad")
    assert db.count_media() == 2
    db.update_media_meta("/tmp/x/a.mkv", duration=120.5, width=1920, height=1080, fps=25.0, video_codec="h264",
                         tracks=[{"type": "a", "idx": 0, "lang": "spa"}], metadata_ok=1)
    row = db.media_by_path("/tmp/x/a.mkv")
    assert row["metadata_ok"] == 1 and row["width"] == 1920
    item = make_item(row)
    assert item["tracks"][0]["lang"] == "spa" and item["duration"] == 120.5
    # playlist con nombre + actual
    items = [make_item(r) for r in db.search_media()]
    items[0]["fixed_time"] = "20:00"
    db.save_playlist("Noche", items)
    loaded = db.load_playlist("Noche")
    assert len(loaded) == 2 and loaded[0]["fixed_time"] == "20:00"
    assert "Noche" in db.playlist_names()
    db.save_playlist(CURRENT_PLAYLIST, items)
    assert CURRENT_PLAYLIST not in db.playlist_names()
    n, dur, _ = db.playlist_summary("Noche")
    assert n == 2 and dur == 120.5
    db.rename_playlist("Noche", "Tarde")
    assert "Tarde" in db.playlist_names() and "Noche" not in db.playlist_names()
    # ajustes
    db.set_setting("bitrate", 4500)
    db.set_setting("rtmp_url", "rtmp://a/b")
    assert db.get_setting("bitrate") == 4500 and db.all_settings()["rtmp_url"] == "rtmp://a/b"
    # as-run
    lid = db.air_log_start("A", "/tmp/x/a.mkv", "Películas", 120.5, "manual")
    db.air_log_end(lid, "EMITIDO")
    logs = db.air_logs(datetime.now().strftime("%Y-%m-%d"))
    assert logs and logs[-1]["status"] == "EMITIDO"
    # random / categorías
    assert len(db.random_media("Publicidad", 5)) == 1
    db.add_category("Promos")
    assert "Promos" in db.categories()
    db.delete_category("Promos")
    assert "Promos" not in db.categories()


def test_scheduler_next_run():
    db = _db()
    db.add_schedule("diario", "daily", "07:00", category="Todas", item_count=3)
    db.add_schedule("finde", "weekly", "20:30", days="5,6", category="Todas", item_count=3)
    db.add_schedule("mensual", "monthly", "00:05", day_of_month=1, category="Todas", item_count=3)
    db.add_schedule("trim", "quarterly", "12:00", day_of_month=15, month_of_quarter=2, category="Todas", item_count=3)
    sch = SchedulerService(db)
    now = datetime(2026, 9, 7, 10, 0)  # lunes
    rows = {r["name"]: r for r in db.schedules()}
    assert sch.next_run(rows["diario"], now) == datetime(2026, 9, 7, 7, 0) + timedelta(days=1)
    assert sch.next_run(rows["finde"], now) == datetime(2026, 9, 12, 20, 30)
    assert sch.next_run(rows["mensual"], now) == datetime(2026, 10, 1, 0, 5)
    assert sch.next_run(rows["trim"], now) == datetime(2026, 11, 15, 12, 0)
    assert sch._match(rows["diario"], datetime(2026, 9, 7, 7, 0, 30))
    assert not sch._match(rows["finde"], datetime(2026, 9, 7, 20, 30))
    assert sch._match(rows["finde"], datetime(2026, 9, 12, 20, 30))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("Todas las pruebas pasaron")
