"""Capa de persistencia SQLite (biblioteca, playlists, programaciones, ajustes, as-run log)."""
import json
import random
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sources(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL DEFAULT 'Películas',
    recursive INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS media(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Películas',
    size INTEGER DEFAULT 0,
    mtime REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    fps REAL DEFAULT 0,
    video_codec TEXT DEFAULT '',
    metadata_ok INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playlists(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS schedules(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    mode TEXT NOT NULL,
    start_time TEXT NOT NULL,
    days TEXT DEFAULT '',
    day_of_month INTEGER DEFAULT 0,
    month_of_quarter INTEGER DEFAULT 0,
    category TEXT DEFAULT 'Todas',
    item_count INTEGER DEFAULT 1,
    order_mode TEXT DEFAULT 'sequential',
    enabled INTEGER DEFAULT 1,
    last_run_key TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS playlist_items(
    id INTEGER PRIMARY KEY,
    playlist_id INTEGER NOT NULL,
    media_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    audio_lang TEXT DEFAULT '',
    subtitle_lang TEXT DEFAULT '',
    mark_in REAL DEFAULT 0,
    mark_out REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS air_log(
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT DEFAULT '',
    title TEXT DEFAULT '',
    path TEXT DEFAULT '',
    category TEXT DEFAULT '',
    duration REAL DEFAULT 0,
    status TEXT DEFAULT 'ON AIR',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_media_category ON media(category);
CREATE INDEX IF NOT EXISTS idx_media_title ON media(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_air_log_started ON air_log(started_at);
"""

DEFAULT_CATEGORIES = ["Películas", "Series", "Infantil", "Documentales", "Música",
                      "Deportes", "Noticias", "Publicidad", "Otros"]

CURRENT_PLAYLIST = "__current__"


class DB:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self._init()

    # ------------------------------------------------------------------ init
    def _init(self):
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            for c in DEFAULT_CATEGORIES:
                self.conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (c,))
            self.conn.commit()

    def _columns(self, table):
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        """Añade columnas nuevas a bases de datos de versiones anteriores."""
        pi = self._columns("playlist_items")
        for name, ddl in [
            ("path", "TEXT DEFAULT ''"),
            ("title", "TEXT DEFAULT ''"),
            ("category", "TEXT DEFAULT ''"),
            ("fixed_time", "TEXT DEFAULT ''"),
            ("duration", "REAL DEFAULT 0"),
        ]:
            if name not in pi:
                self.conn.execute(f"ALTER TABLE playlist_items ADD COLUMN {name} {ddl}")
        m = self._columns("media")
        for name, ddl in [
            ("audio_codec", "TEXT DEFAULT ''"),
            ("tracks", "TEXT DEFAULT ''"),
            ("thumb", "TEXT DEFAULT ''"),
            ("probe_error", "TEXT DEFAULT ''"),
        ]:
            if name not in m:
                self.conn.execute(f"ALTER TABLE media ADD COLUMN {name} {ddl}")

    # -------------------------------------------------------------- settings
    def get_setting(self, key, default=None):
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return row["value"]

    def set_setting(self, key, value):
        with self._lock:
            self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, json.dumps(value)))
            self.conn.commit()

    def all_settings(self):
        with self._lock:
            out = {}
            for r in self.conn.execute("SELECT key,value FROM settings"):
                try:
                    out[r["key"]] = json.loads(r["value"])
                except (TypeError, ValueError):
                    out[r["key"]] = r["value"]
            return out

    # --------------------------------------------------------------- sources
    def sources(self, enabled_only=True):
        with self._lock:
            sql = "SELECT * FROM sources" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
            return self.conn.execute(sql).fetchall()

    def add_source(self, path, category="Películas", recursive=True):
        with self._lock:
            self.conn.execute(
                """INSERT INTO sources(path,category,recursive,enabled) VALUES(?,?,?,1)
                   ON CONFLICT(path) DO UPDATE SET category=excluded.category, recursive=excluded.recursive, enabled=1""",
                (str(path), category, int(recursive)))
            self.conn.commit()

    def remove_source(self, path):
        with self._lock:
            self.conn.execute("DELETE FROM sources WHERE path=?", (str(path),))
            self.conn.commit()

    def replace_sources(self, rows):
        """rows: lista de (path, category, recursive)."""
        with self._lock:
            self.conn.execute("DELETE FROM sources")
            for path, category, recursive in rows:
                if path:
                    self.conn.execute("INSERT OR REPLACE INTO sources(path,category,recursive,enabled) VALUES(?,?,?,1)",
                                      (str(path), category or "Películas", int(bool(recursive))))
            self.conn.commit()

    # ------------------------------------------------------------ categories
    def categories(self):
        with self._lock:
            return [r["name"] for r in self.conn.execute("SELECT name FROM categories ORDER BY name COLLATE NOCASE")]

    def add_category(self, name):
        name = (name or "").strip()
        if not name:
            return False
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
            self.conn.commit()
        return True

    def delete_category(self, name):
        with self._lock:
            self.conn.execute("DELETE FROM categories WHERE name=?", (name,))
            self.conn.commit()

    # ----------------------------------------------------------------- media
    def upsert_media(self, path, title, category):
        try:
            st = Path(path).stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = 0, 0
        with self._lock:
            self.conn.execute("""
            INSERT INTO media(path,title,category,size,mtime)
            VALUES(?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
              title=excluded.title, category=excluded.category,
              size=excluded.size,
              metadata_ok=CASE WHEN media.mtime=excluded.mtime THEN media.metadata_ok ELSE 0 END,
              mtime=excluded.mtime
            """, (str(path), title, category, size, mtime))
            self.conn.commit()

    def count_media(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    def search_media(self, term="", category="Todas", limit=5000):
        with self._lock:
            term = (term or "").strip()
            args = []
            where = []
            if term:
                like = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                where.append("(title LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')")
                args += [like, like]
            if category and category != "Todas":
                where.append("category=?")
                args.append(category)
            sql = "SELECT * FROM media"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY title COLLATE NOCASE LIMIT ?"
            args.append(int(limit))
            return self.conn.execute(sql, args).fetchall()

    def media_by_ids(self, ids):
        ids = [int(i) for i in ids if i is not None]
        if not ids:
            return []
        with self._lock:
            out = {}
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                for r in self.conn.execute(f"SELECT * FROM media WHERE id IN ({q})", chunk):
                    out[r["id"]] = r
            return [out[i] for i in ids if i in out]

    def media_by_path(self, path):
        with self._lock:
            return self.conn.execute("SELECT * FROM media WHERE path=?", (str(path),)).fetchone()

    def unprobed_media(self, limit=200):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM media WHERE metadata_ok=0 AND (probe_error='' OR probe_error IS NULL) ORDER BY id LIMIT ?",
                (int(limit),)).fetchall()

    def update_media_meta(self, path, **fields):
        allowed = {"duration", "width", "height", "fps", "video_codec", "audio_codec", "tracks",
                   "thumb", "metadata_ok", "probe_error", "title", "category"}
        cols = [(k, v) for k, v in fields.items() if k in allowed]
        if not cols:
            return
        with self._lock:
            sql = "UPDATE media SET " + ", ".join(f"{k}=?" for k, _ in cols) + " WHERE path=?"
            self.conn.execute(sql, [json.dumps(v) if isinstance(v, (list, dict)) else v for _, v in cols] + [str(path)])
            self.conn.commit()

    def set_media_category(self, path, category):
        with self._lock:
            self.conn.execute("UPDATE media SET category=? WHERE path=?", (category, str(path)))
            self.conn.commit()

    def delete_media(self, path):
        with self._lock:
            self.conn.execute("DELETE FROM media WHERE path=?", (str(path),))
            self.conn.commit()

    def random_media(self, category="Todas", count=10, exclude_paths=(), max_duration=None, min_duration=0):
        with self._lock:
            args = []
            sql = "SELECT * FROM media"
            where = []
            if category and category != "Todas":
                where.append("category=?")
                args.append(category)
            if max_duration is not None:
                where.append("duration>0 AND duration<=?")
                args.append(float(max_duration))
            if min_duration:
                where.append("duration>=?")
                args.append(float(min_duration))
            if where:
                sql += " WHERE " + " AND ".join(where)
            rows = [r for r in self.conn.execute(sql, args).fetchall() if r["path"] not in set(exclude_paths)]
        random.shuffle(rows)
        return rows[:max(0, int(count))]

    def media_stats(self):
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            probed = self.conn.execute("SELECT COUNT(*) FROM media WHERE metadata_ok=1").fetchone()[0]
            failed = self.conn.execute("SELECT COUNT(*) FROM media WHERE probe_error<>''").fetchone()[0]
            return total, probed, failed

    def reset_probe_errors(self):
        with self._lock:
            self.conn.execute("UPDATE media SET probe_error='' WHERE probe_error<>''")
            self.conn.commit()

    # ------------------------------------------------------------- playlists
    def playlist_names(self):
        with self._lock:
            return [r["name"] for r in self.conn.execute(
                "SELECT name FROM playlists WHERE name<>? ORDER BY name COLLATE NOCASE", (CURRENT_PLAYLIST,))]

    def save_playlist(self, name, items):
        """items: lista de dicts con path,title,category,duration,media_id,audio_lang,subtitle_lang,fixed_time."""
        with self._lock:
            self.conn.execute("INSERT INTO playlists(name) VALUES(?) ON CONFLICT(name) DO UPDATE SET name=excluded.name", (name,))
            pid = self.conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()[0]
            self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            self.conn.executemany(
                """INSERT INTO playlist_items(playlist_id,media_id,position,audio_lang,subtitle_lang,path,title,category,fixed_time,duration)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [(pid, int(it.get("media_id") or 0), pos, it.get("audio_lang", "") or "", it.get("subtitle_lang", "") or "",
                  it.get("path", ""), it.get("title", ""), it.get("category", ""), it.get("fixed_time", "") or "",
                  float(it.get("duration") or 0)) for pos, it in enumerate(items, 1)])
            self.conn.commit()
            return pid

    def load_playlist(self, name):
        with self._lock:
            pl = self.conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if not pl:
                return []
            rows = self.conn.execute("SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position", (pl["id"],)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                media = None
                if d.get("media_id"):
                    media = self.conn.execute("SELECT * FROM media WHERE id=?", (d["media_id"],)).fetchone()
                if media is None and d.get("path"):
                    media = self.conn.execute("SELECT * FROM media WHERE path=?", (d["path"],)).fetchone()
                item = {
                    "media_id": media["id"] if media else d.get("media_id"),
                    "path": (media["path"] if media else d.get("path")) or "",
                    "title": d.get("title") or (media["title"] if media else "") or Path(d.get("path") or "").stem,
                    "category": d.get("category") or (media["category"] if media else "") or "Otros",
                    "duration": (media["duration"] if media and media["duration"] else d.get("duration")) or 0,
                    "audio_lang": d.get("audio_lang") or "",
                    "subtitle_lang": d.get("subtitle_lang") or "",
                    "fixed_time": d.get("fixed_time") or "",
                }
                if media:
                    for k in ("width", "height", "fps", "video_codec", "audio_codec", "tracks", "thumb"):
                        item[k] = media[k] if k in media.keys() else ""
                if item["path"]:
                    out.append(item)
            return out

    def delete_playlist(self, name):
        with self._lock:
            pl = self.conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if pl:
                self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pl["id"],))
                self.conn.execute("DELETE FROM playlists WHERE id=?", (pl["id"],))
                self.conn.commit()

    def rename_playlist(self, old, new):
        with self._lock:
            self.conn.execute("UPDATE playlists SET name=? WHERE name=?", (new, old))
            self.conn.commit()

    def playlist_summary(self, name):
        with self._lock:
            pl = self.conn.execute("SELECT id, created_at FROM playlists WHERE name=?", (name,)).fetchone()
            if not pl:
                return 0, 0.0, ""
            row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(duration),0) FROM playlist_items WHERE playlist_id=?",
                                    (pl["id"],)).fetchone()
            return int(row[0]), float(row[1] or 0), pl["created_at"] or ""

    # ------------------------------------------------------------- schedules
    def schedules(self, enabled_only=False):
        with self._lock:
            sql = "SELECT * FROM schedules" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY start_time,name"
            return self.conn.execute(sql).fetchall()

    def add_schedule(self, name, mode, start_time, days='', day_of_month=0, month_of_quarter=0,
                     category='Todas', item_count=1, order_mode='sequential'):
        with self._lock:
            self.conn.execute("""INSERT INTO schedules(name,mode,start_time,days,day_of_month,month_of_quarter,category,item_count,order_mode,enabled)
                VALUES(?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(name) DO UPDATE SET mode=excluded.mode,start_time=excluded.start_time,days=excluded.days,
                day_of_month=excluded.day_of_month,month_of_quarter=excluded.month_of_quarter,category=excluded.category,
                item_count=excluded.item_count,order_mode=excluded.order_mode,enabled=1""",
                              (name, mode, start_time, days, int(day_of_month or 0), int(month_of_quarter or 0),
                               category, int(item_count), order_mode))
            self.conn.commit()

    def delete_schedule(self, sid):
        with self._lock:
            self.conn.execute("DELETE FROM schedules WHERE id=?", (sid,))
            self.conn.commit()

    def set_schedule_enabled(self, sid, enabled):
        with self._lock:
            self.conn.execute("UPDATE schedules SET enabled=?, last_run_key='' WHERE id=?", (int(enabled), sid))
            self.conn.commit()

    def mark_schedule_run(self, sid, key):
        with self._lock:
            self.conn.execute("UPDATE schedules SET last_run_key=? WHERE id=?", (key, sid))
            self.conn.commit()

    def schedule_media(self, category, count, order_mode='sequential'):
        with self._lock:
            args = []
            sql = "SELECT * FROM media"
            if category and category != 'Todas':
                sql += " WHERE category=?"
                args.append(category)
            sql += " ORDER BY title COLLATE NOCASE"
            rows = list(self.conn.execute(sql, args).fetchall())
        if order_mode == 'random':
            random.shuffle(rows)
        elif order_mode == 'recent':
            rows.sort(key=lambda r: (r['mtime'] or 0), reverse=True)
        return rows[:max(1, int(count))]

    # --------------------------------------------------------------- air log
    def air_log_start(self, title, path, category, duration, note=""):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO air_log(started_at,title,path,category,duration,status,note) VALUES(?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), title, path, category, float(duration or 0), "ON AIR", note))
            self.conn.commit()
            return cur.lastrowid

    def air_log_end(self, log_id, status="EMITIDO", note=None):
        if not log_id:
            return
        with self._lock:
            if note is None:
                self.conn.execute("UPDATE air_log SET ended_at=?, status=? WHERE id=?",
                                  (datetime.now().isoformat(timespec="seconds"), status, log_id))
            else:
                self.conn.execute("UPDATE air_log SET ended_at=?, status=?, note=? WHERE id=?",
                                  (datetime.now().isoformat(timespec="seconds"), status, note, log_id))
            self.conn.commit()

    def air_logs(self, day):
        """day: 'YYYY-MM-DD'."""
        with self._lock:
            return self.conn.execute("SELECT * FROM air_log WHERE started_at LIKE ? ORDER BY started_at", (day + "%",)).fetchall()

    def close_open_air_logs(self):
        with self._lock:
            self.conn.execute("UPDATE air_log SET status='INTERRUMPIDO', ended_at=? WHERE ended_at='' OR ended_at IS NULL",
                              (datetime.now().isoformat(timespec="seconds"),))
            self.conn.commit()
