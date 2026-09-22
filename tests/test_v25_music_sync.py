"""Pruebas para sincronización de vídeos musicales, importación de playlists M3U8,
continuidad sin cortes RTMP e identificadores de entrada/salida.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.db import DB
from app.playout import PlayoutController, make_item, ST_AIRED, ST_ONAIR, ST_PENDING
from app.main_window import MainWindow
from app.output import OutputWorker


class _DummyPlayer(QObject):
    ended = Signal(str)
    loaded = Signal()
    position = Signal(float, float)
    process_died = Signal()

    def play(self, *args, **kwargs):
        return True

    def stop(self):
        pass

    def set_pause(self, paused):
        pass


def _create_temp_video(directory: str, filename: str) -> str:
    path = os.path.join(directory, filename)
    with open(path, "wb") as f:
        f.write(b"dummy video content")
    return path


def test_identifier_eligibility_and_non_content_exclusion():
    """Valida que _identifier_eligible acepte música, películas y contenido general,
    pero excluya publicidad, tandas, filler, slate e identificadores transitorios."""
    with tempfile.TemporaryDirectory() as tmp:
        db = DB(os.path.join(tmp, "test.db"))
        player = _DummyPlayer()
        ctrl = PlayoutController(db, player)

        # Contenidos válidos
        assert ctrl._identifier_eligible({"category": "Música", "path": "/v1.mp4"}) is True
        assert ctrl._identifier_eligible({"category": "Películas", "path": "/v2.mp4"}) is True
        assert ctrl._identifier_eligible({"category": "Otros", "path": "/v3.mp4"}) is True
        assert ctrl._identifier_eligible({"category": "General", "path": "/v4.mp4"}) is True
        assert ctrl._identifier_eligible({"category": "Series", "path": "/v5.mp4"}) is True
        assert ctrl._identifier_eligible({"category": "musica", "path": "/v6.mp4"}) is True

        # No-contenidos excluidos
        assert ctrl._identifier_eligible({"category": "Publicidad", "path": "/ad1.mp4"}) is False
        assert ctrl._identifier_eligible({"category": "Tanda", "path": "/ad2.mp4"}) is False
        assert ctrl._identifier_eligible({"category": "Filler", "path": "/f.mp4"}) is False
        assert ctrl._identifier_eligible({"category": "Slate", "path": "/s.mp4"}) is False
        assert ctrl._identifier_eligible({"category": "Identificador", "path": "/id.mp4"}) is False
        assert ctrl._identifier_eligible({"_transient_identifier": True, "path": "/id.mp4"}) is False
        assert ctrl._identifier_eligible(None) is False


def test_identifiers_in_and_out_lifecycle():
    """Valida el ciclo completo de identificador de entrada y de salida."""
    with tempfile.TemporaryDirectory() as tmp:
        db = DB(os.path.join(tmp, "test.db"))
        player = _DummyPlayer()
        ctrl = PlayoutController(db, player)

        vid_in = _create_temp_video(tmp, "ident_in.mp4")
        vid_out = _create_temp_video(tmp, "ident_out.mp4")
        v1 = _create_temp_video(tmp, "music1.mp4")
        v2 = _create_temp_video(tmp, "music2.mp4")

        ctrl.identifiers_enabled = True
        ctrl.identifier_in_path = vid_in
        ctrl.identifier_out_path = vid_out

        ctrl.set_items([
            make_item({"path": v1, "title": "Track 1", "category": "Música", "duration": 200.0}),
            make_item({"path": v2, "title": "Track 2", "category": "Música", "duration": 180.0}),
        ])

        # 1. Iniciar evento 0 -> debe disparar identificador de entrada
        ctrl.play_index(0, "manual")
        assert ctrl.is_on_air
        # Al aire debe estar el bumper transitorio de entrada
        current = ctrl.current
        assert current["path"] == vid_in
        assert current.get("_transient_identifier") is True

        # 2. El bumper de entrada termina (EOF) -> debe remover el bumper e iniciar Track 1
        ctrl._on_ended("eof")
        current = ctrl.current
        assert current["path"] == v1
        assert current["title"] == "Track 1"

        # 3. Track 1 termina (EOF) -> debe disparar identificador de salida
        ctrl._on_ended("eof")
        current = ctrl.current
        assert current["path"] == vid_out
        assert current.get("_transient_identifier") is True

        # 4. El bumper de salida termina (EOF) -> debe iniciar Track 2 (y su identificador de entrada)
        ctrl._on_ended("eof")
        current = ctrl.current
        # Inicia con identificador de entrada para Track 2
        assert current["path"] == vid_in
        assert current.get("_transient_identifier") is True

        # 5. Bumper de entrada termina -> inicia Track 2
        ctrl._on_ended("eof")
        current = ctrl.current
        assert current["path"] == v2
        assert current["title"] == "Track 2"


def test_rtmp_drift_check_does_not_rewind_when_output_advances():
    """Valida que _rtmp_check_drift NO reinicie ni rebobine la salida cuando
    la salida avanza de clip (clip > onair) y el monitor local va a <1x."""
    class _MockCtrl:
        is_on_air = True
        paused = False
        elapsed = 130.0  # Playout local en segundo 130 de clip 1
        onair = 1

    class _MockOutput:
        def __init__(self):
            self.seeks = []
            self.current_index = 2  # Salida ya terminó clip 1 y arrancó clip 2
            self.has_active_process = True

        @property
        def current_position(self):
            return 2.5  # Segundo 2.5 de clip 2

        def isRunning(self):
            return True

        def seek_to(self, index, offset):
            self.seeks.append((index, offset))

    mw = MainWindow.__new__(MainWindow)
    mw.ctrl = _MockCtrl()
    mw.output = _MockOutput()
    mw._rtmp_drift_threshold = 6.0
    mw._rtmp_drift_bad_count = 0
    mw._rtmp_drift_last_restart = 0.0
    mw._rtmp_drift_baseline = None
    mw._rtmp_drift_clip = None
    mw._rtmp_drift_had_unknown = False
    mw._rtmp_drift_suspend_until = 0.0
    mw._rtmp_drift_local_lag_warned = False
    mw._rtmp_drift_ahead_warned = False
    mw._rtmp_drift_cap_realigned = 0
    mw._rtmp_drift_max_gap = 45.0
    mw._status = lambda *a, **k: None

    # Llamar al chequeo de drift
    mw._rtmp_check_drift()

    # NO debe haber llamado a seek_to (NO debe haber rebobinado al evento anterior)
    assert mw.output.seeks == [], f"Se ejecutó seek_to indebido: {mw.output.seeks}"
    assert mw._rtmp_drift_ahead_warned is True


def test_output_worker_sync_items_keeps_active_process():
    """Valida que sync_items con force_jump=True no mate el proceso si ya está
    emitiendo el mismo índice recientemente sin offset de seek."""
    worker = OutputWorker.__new__(OutputWorker)
    worker.seamless_concat = False   # camino legacy: un FFmpeg por clip
    worker._current_index = 1
    worker._clip_started = time.time() - 2.0  # arrancado hace 2s
    worker._jump = type("Event", (), {"set": lambda self: None})()
    worker._lock = type("Lock", (), {"__enter__": lambda s: None, "__exit__": lambda s, *a: None})()
    worker.protocol = "RTMP"
    worker.log = type("Sig", (), {"emit": lambda s, m: None})()
    worker.items = [{"path": "/a.mp4"}, {"path": "/b.mp4"}]

    class _Proc:
        def poll(self):
            return None  # proceso vivo

    worker.proc = _Proc()

    # Llamar sync_items para índice 1 con start_offset=0
    result = worker.sync_items([{"path": "/a.mp4"}, {"path": "/b.mp4"}], current_index=1, force_jump=True, start_offset=0.0)
    assert result is True
    # El proceso no debe haber sido terminado (sigue siendo _Proc)
    assert worker.proc is not None


def test_scan_done_refreshes_active_playlist_items():
    """Valida que _scan_done actualice los metadatos de los items en la playlist activa."""
    with tempfile.TemporaryDirectory() as tmp:
        db = DB(os.path.join(tmp, "test.db"))
        player = _DummyPlayer()
        ctrl = PlayoutController(db, player)

        vpath = _create_temp_video(tmp, "song.mp4")
        # Item en playlist antes de escanear (categoría Otros)
        ctrl.set_items([
            make_item({"path": vpath, "title": "Song", "category": "Otros", "duration": 0.0})
        ])

        # Se escanea e indexa en la BD con categoría Música y duración
        db.upsert_media(vpath, "Song", "Música")
        db.update_media_meta(vpath, duration=215.0, source_duration=215.0)

        mw = MainWindow.__new__(MainWindow)
        mw.ctrl = ctrl
        mw.db = db
        mw.settings = {"probe_on_scan": False}
        mw.refresh_library = lambda: None
        mw._status = lambda msg: None

        mw._scan_done(1, 1)

        # El item en la playlist activa debe haberse actualizado a Música y 215.0s
        assert ctrl.items[0]["category"] == "Música"
        assert ctrl.items[0]["duration"] == 215.0
