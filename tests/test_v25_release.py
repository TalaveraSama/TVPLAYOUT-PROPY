"""Pruebas de release de Nexora Air V25.0.1."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def read(*parts):
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def test_identity_and_version_are_centralized():
    config = read("app", "config.py")
    main = read("app", "main_window.py")
    spec = read("tvplayout.spec")
    assert 'APP_NAME = "Nexora Air"' in config
    assert 'APP_VERSION = "V25.0.1"' in config
    assert 'APP_SLUG = "NexoraAir"' in config
    assert "setWindowTitle(f\"{APP_NAME} {APP_VERSION}" in main
    assert 'name="NexoraAir"' in spec
    assert (REPO / "assets" / "logo.png").is_file()
    assert (REPO / "assets" / "logo.ico").is_file()


def test_output_worker_exposes_real_master_clock():
    output = read("app", "output.py")
    assert "progress = Signal(int, float)" in output
    assert "clip_finished = Signal(int, bool)" in output
    assert "self.progress.emit(int(clip_index), max(0.0, position))" in output
    assert "proc is not self.proc or clip_index != self._current_index" in output
    assert "def _await_controller" in output
    assert "if self.externally_controlled" in output
    assert "self.master_worker = worker" in output
    assert "worker.progress.connect(self.master_progress.emit)" in output
    assert "worker.clip_finished.connect(self.master_finished.emit)" in output


def test_main_window_wires_ffmpeg_master_only_in_clock_mode():
    main = read("app", "main_window.py")
    assert "externally_controlled=bool(self.ctrl.clock_only and needs_ffmpeg)" in main
    assert "self.output.master_progress.connect(self.ctrl.follow_output_position)" in main
    assert "self.output.master_finished.connect(self.ctrl.output_master_finished)" in main
    assert "if self.ctrl.clock_only and self.ctrl.output_master_active:" in main


def test_installer_builder_is_offline_and_migrates_previous_data():
    builder = read("installer", "build_windows_setup.py")
    assert 'PYTHON_VERSION = "3.13.2"' in builder
    assert 'PYSIDE_VERSION = "6.8.3"' in builder
    assert "pythonw.exe" in builder and "ffmpeg.exe" in builder and "ffprobe.exe" in builder
    assert "PySide6_Essentials" in builder and "PySide6_Addons" in builder
    assert 'FFMPEG_PACKAGE_VERSION = "1.1.0"' in builder
    assert 'site_packages / "sitecustomize.py"' in builder
    assert "runpy.run_path(_main" in builder
    assert "TVPlayoutPRO\\tvplayout.db" in builder
    assert "nexora-air.db" in builder
    assert "SetCompressor /SOLID lzma" in builder
    subprocess.run(
        [sys.executable, str(REPO / "installer" / "build_windows_setup.py"), "check"],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )


def test_ffmpeg_progress_freezes_and_finishes_controller_timeline():
    try:
        from PySide6.QtCore import QCoreApplication, QObject, Signal
    except Exception:
        return
    from app.playout import PlayoutController, make_item, ST_AIRED, ST_ONAIR

    app = QCoreApplication.instance() or QCoreApplication([])

    class Player(QObject):
        ended = Signal(str)
        loaded = Signal()
        position = Signal(float, float)
        process_died = Signal()

        def play(self, *_args, **_kwargs):
            return True

        def stop(self):
            pass

        def set_pause(self, _paused):
            pass

    class DB:
        def __init__(self):
            self.settings = {}
            self.log_id = 0

        def set_setting(self, key, value):
            self.settings[key] = value

        def get_setting(self, key, default=None):
            return self.settings.get(key, default)

        def air_log_start(self, *_args):
            self.log_id += 1
            return self.log_id

        def air_log_end(self, *_args):
            pass

        def save_playlist(self, *_args):
            pass

    with tempfile.TemporaryDirectory(prefix="nexora-v25-") as tmp:
        paths = []
        for name in ("A.mkv", "B.mkv"):
            path = os.path.join(tmp, name)
            Path(path).write_bytes(b"x")
            paths.append(path)
        ctrl = PlayoutController(DB(), Player())
        ctrl.clock_only = True
        ctrl.items = [
            make_item({"path": paths[0], "title": "A", "duration": 10.0}),
            make_item({"path": paths[1], "title": "B", "duration": 10.0}),
        ]
        ctrl.set_output_master(True)
        assert ctrl.play_index(0, "test")
        assert ctrl.items[0]["status"] == ST_ONAIR

        assert ctrl.follow_output_position(0, 4.25)
        time.sleep(0.05)
        # Una salida congelada congela también la playlist; no suma pared.
        assert abs(ctrl.elapsed - 4.25) < 0.01, ctrl.elapsed
        ctrl.clock_tick()
        assert ctrl.onair == 0

        # Una medición tardía del evento equivocado se ignora.
        assert not ctrl.follow_output_position(1, 9.0)
        assert abs(ctrl.elapsed - 4.25) < 0.01

        # Sólo el EOF del master finaliza A y arranca B en modo automático.
        assert ctrl.output_master_finished(0, True)
        assert ctrl.items[0]["status"] == ST_AIRED
        assert ctrl.onair == 1
        assert ctrl.items[1]["status"] == ST_ONAIR
        ctrl._tick_timer.stop()
        ctrl._save_timer.stop()
    del app


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("OK", name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL", name, "—", exc)
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    raise SystemExit(1 if failed else 0)
