import sqlite3
import threading
from pathlib import Path

class DB:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        with self._lock:
            self.conn.executescript("""
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
            """)
            defaults = ["Películas","Series","Infantil","Documentales","Música","Deportes","Noticias","Publicidad","Otros"]
            for c in defaults:
                self.conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)",(c,))
            self.conn.commit()

    def sources(self):
        with self._lock:
            return self.conn.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY id").fetchall()

    def add_source(self, path, category="Películas", recursive=True):
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO sources(path,category,recursive) VALUES(?,?,?)",
                (str(path), category, int(recursive))
            )
            self.conn.commit()

    def categories(self):
        with self._lock:
            return [r["name"] for r in self.conn.execute("SELECT name FROM categories ORDER BY name")]

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
              size=excluded.size, mtime=excluded.mtime
            """,(str(path),title,category,size,mtime))
            self.conn.commit()

    def count_media(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    def search_media(self, term="", category="Todas"):
        with self._lock:
            term = term.strip()
            args=[]
            where=[]
            if term:
                like='%' + term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
                where.append("(title LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')")
                args += [like,like]
            if category and category != "Todas":
                where.append("category=?")
                args.append(category)
            sql="SELECT * FROM media"
            if where: sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY title COLLATE NOCASE"
            return self.conn.execute(sql,args).fetchall()

    def save_playlist(self, name, media_ids):
        with self._lock:
            cur=self.conn.execute("INSERT INTO playlists(name) VALUES(?) ON CONFLICT(name) DO UPDATE SET name=excluded.name",(name,))
            pid=self.conn.execute("SELECT id FROM playlists WHERE name=?",(name,)).fetchone()[0]
            self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?",(pid,))
            for pos,mid in enumerate(media_ids,1):
                self.conn.execute("INSERT INTO playlist_items(playlist_id,media_id,position) VALUES(?,?,?)",(pid,mid,pos))
            self.conn.commit()
            return pid

    def schedules(self, enabled_only=False):
        with self._lock:
            sql="SELECT * FROM schedules" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY start_time,name"
            return self.conn.execute(sql).fetchall()

    def add_schedule(self, name, mode, start_time, days='', day_of_month=0, month_of_quarter=0, category='Todas', item_count=1, order_mode='sequential'):
        with self._lock:
            self.conn.execute("""INSERT INTO schedules(name,mode,start_time,days,day_of_month,month_of_quarter,category,item_count,order_mode,enabled)
                VALUES(?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(name) DO UPDATE SET mode=excluded.mode,start_time=excluded.start_time,days=excluded.days,day_of_month=excluded.day_of_month,month_of_quarter=excluded.month_of_quarter,category=excluded.category,item_count=excluded.item_count,order_mode=excluded.order_mode,enabled=1""",
                (name,mode,start_time,days,int(day_of_month or 0),int(month_of_quarter or 0),category,int(item_count),order_mode))
            self.conn.commit()

    def delete_schedule(self, sid):
        with self._lock:
            self.conn.execute("DELETE FROM schedules WHERE id=?",(sid,)); self.conn.commit()

    def set_schedule_enabled(self, sid, enabled):
        with self._lock:
            self.conn.execute("UPDATE schedules SET enabled=?, last_run_key=? WHERE id=?",(int(enabled), "" if enabled else "", sid)); self.conn.commit()

    def mark_schedule_run(self, sid, key):
        with self._lock:
            self.conn.execute("UPDATE schedules SET last_run_key=? WHERE id=?",(key,sid)); self.conn.commit()

    def schedule_media(self, category, count, order_mode='sequential'):
        with self._lock:
            args=[]; sql="SELECT * FROM media"
            if category and category != 'Todas': sql += " WHERE category=?"; args.append(category)
            sql += " ORDER BY title COLLATE NOCASE"
            rows=list(self.conn.execute(sql,args).fetchall())
            if order_mode == 'random':
                import random; random.shuffle(rows)
            elif order_mode == 'recent':
                rows.sort(key=lambda r: (r['mtime'] or 0), reverse=True)
            return rows[:max(1,int(count))]
