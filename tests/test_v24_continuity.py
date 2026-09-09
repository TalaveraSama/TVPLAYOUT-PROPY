"""Pruebas estructurales y puras de continuidad V24.

No levanta Qt ni requiere PySide6. La parte pura valida la regla de disparo
por intervalo; las pruebas estructurales protegen los puntos de integración
entre PyAV, playout y RTMP/SRT/NDI.

Ejecutar: python tests/test_v24_continuity.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


def midroll_due(position, next_at, eligible=True):
    """Regla pura del scheduler: el intervalo no depende del frame exacto."""
    return bool(eligible and next_at > 0 and position >= next_at)


def test_interval_scheduler_is_configurable_and_not_fixed_to_one_value():
    src = _read("app", "playout.py")
    assert "midroll_interval_minutes" in src
    assert "_midroll_interval_seconds" in src
    assert "self._midroll_next_at = self._pos + self._midroll_interval_seconds()" in src
    assert "self.midroll_interval_minutes" in src, "la fuente debe leer el valor configurable"
    assert not midroll_due(599.9, 600.0)
    assert midroll_due(600.0, 600.0)
    assert not midroll_due(600.0, 600.0, eligible=False)


def test_midroll_resumes_exact_local_and_ip_timeline():
    playout = _read("app", "playout.py")
    window = _read("app", "main_window.py")
    output = _read("app", "output.py")
    assert "resume_offset = max(0.0, float(self._pos or 0.0))" in playout
    assert 'self.play_index(target, "midroll-resume", start_offset=resume.get("offset", 0.0)' in playout
    assert "self._position_base = resume_offset" in playout
    assert "start_offset=start_offset" in window
    assert "_jump_offset" in output


def test_midroll_and_end_tanda_are_independent_controls():
    window = _read("app", "main_window.py")
    dialog = _read("app", "dialogs.py")
    playout = _read("app", "playout.py")
    assert "midroll_btn" in window and '"midroll_enabled"' in window
    assert "midroll_enabled" in dialog and "midroll_interval_minutes" in dialog
    assert "if (self.tandas and reason == \"eof\" and not self._midroll_resume" in playout


def test_identifiers_are_two_files_and_excluded_from_non_content():
    playout = _read("app", "playout.py")
    dialog = _read("app", "dialogs.py")
    assert "identifier_in_path" in playout and "identifier_out_path" in playout
    assert 'self.identifier_categories = {"Películas", "Música"}' in playout
    assert "Identificador de entrada" in dialog and "Identificador de salida" in dialog
    assert "Publicidad, filler ni slate" in dialog
    assert "_transient_identifier=True" in playout


def test_identifiers_follow_all_outputs_through_the_normal_on_start_callback():
    playout = _read("app", "playout.py")
    window = _read("app", "main_window.py")
    assert 'self.play_index(bumper_index, f"identifier-{phase}", _internal=True)' in playout
    assert "for cb in list(self.on_start_callbacks)" in playout
    assert "self.output.sync_items(self.ctrl.export_items(), index, force_jump=True, start_offset=start_offset)" in window


def test_pyav_receives_resume_source_offset_and_preserves_buffer_path():
    player = _read("app", "pyav_player.py")
    playout = _read("app", "playout.py")
    assert "start_at=self._trim_start" in player
    assert "self._job.seek(source_target)" in player
    assert "playback_start = trim_start + resume_offset" in playout
    assert "self.player.play(item[\"path\"]" in playout


def test_automatic_end_tanda_remains_in_the_controller():
    playout = _read("app", "playout.py")
    assert "def _insert_tanda(self, after_index):" in playout
    assert 'self._insert_tanda(idx)' in playout
    assert "self.tandas_category" in playout


def test_tmdb_card_is_periodic_and_shared_by_monitor_and_ip_outputs():
    window = _read("app", "main_window.py")
    player = _read("app", "pyav_player.py")
    output = _read("app", "output.py")
    tmdb = _read("app", "tmdb.py")
    dialog = _read("app", "dialogs.py")
    assert "tmdb_interval_minutes" in window and "tmdb_duration_seconds" in window
    assert "TMDBLookupWorker" in window and "build_movie_overlay" in window
    assert "set_program_overlay" in player and "_program_overlay_interval" in player
    assert "_program_enable_expression" in output and "program_overlay" in output
    assert "TMDB_API}/search/movie" in tmdb and "TMDB_IMAGES" in tmdb
    assert "Mostrar tarjeta TMDB periódica" in dialog


def test_context_menu_track_selection_uses_exact_stream_indices():
    dialog = _read("app", "dialogs.py")
    playout = _read("app", "playout.py")
    assert 'self.audio.addItem(label, f"#{t.get(\'idx\')}")' in dialog
    assert 'self.sub.addItem(label, f"#{t.get(\'idx\')}")' in dialog
    assert "pick_audio(item.get(\"tracks\"), self.audio_pref)" in playout
    assert "log.info(\"Cambio de pistas en vivo" in playout


def test_rtmp_drift_guard_does_not_restart_in_a_fast_loop():
    window = _read("app", "main_window.py")
    output = _read("app", "output.py")
    assert 'self._rtmp_drift_threshold = 6.0' in window
    assert "_rtmp_drift_bad_count < 2" in window
    assert "_rtmp_drift_last_restart < 12.0" in window
    assert "_rtmp_drift_suspend_until = now + 8.0" in window
    assert "has_active_process" in output
    assert "No convertir esa ventana" in window and "un seek adicional" in window


def test_subtitles_are_selected_and_logged_in_pyav():
    player = _read("app", "pyav_player.py")
    output = _read("app", "output.py")
    assert '"subtitle_id": self.subtitle_id' in player
    assert "PyAV subtitle event" in player
    assert 'subtitles=\'{_ffmpeg_filter_path(source)}\':si=' in output


def test_live_track_change_restarts_local_and_remote_at_same_offset():
    playout = _read("app", "playout.py")
    player = _read("app", "pyav_player.py")
    output = _read("app", "output.py")
    window = _read("app", "main_window.py")
    assert "def set_track_preferences" in playout
    assert "start=trim_start + offset" in playout
    assert "sub_id=sid" in playout
    assert "subtitle_id=sub_id" in player
    assert "_live_audio_preference" in output and "_live_subtitle_preference" in output
    assert "self.output.set_track_preferences" in window
    assert "self.ctrl.set_track_preferences" in window


def test_live_track_change_is_exposed_from_settings_and_supports_burned_subtitles():
    dialog = _read("app", "dialogs.py")
    output = _read("app", "output.py")
    config = _read("app", "config.py")
    assert "guardar estos valores cambia la pista en vivo" in dialog
    assert "subtitle_burn = self.subtitle_burn" in output
    assert "pick_subtitle(tracks, subtitle_preference)" in output
    assert '"en"' in config and '"eng"' in config and '"English"' in config


def test_library_can_probe_selection_and_store_tmdb_images():
    window = _read("app", "main_window.py")
    db = _read("app", "db.py")
    prober = _read("app", "prober.py")
    assert "Escanear TMDB biblioteca" in window
    assert "scan_tmdb_library" in window
    assert "scan_tmdb_manual" in window
    assert "Escanear esta película en TMDB" in window
    assert "scan_selected_metadata" in window
    assert "Escanear metadatos de selección" in window
    assert "tmdb_poster" in window and "tmdb_backdrop" in window
    assert "update_tmdb_metadata" in db
    assert "paths=None" in prober and "paths=self.paths" in prober


def test_windows_fit_tv_logical_resolution_and_dialogs_can_scroll():
    main = _read("app", "main_window.py")
    dialogs = _read("app", "dialogs.py")
    extra = _read("app", "dialogs_extra.py")
    assert "availableGeometry()" in main
    assert "self.statusBar().setSizeGripEnabled(True)" in main
    assert "self.setMinimumSize(min_w, min_h)" in main
    assert "QScrollArea" in dialogs and "def scroll_page" in dialogs
    assert "setSizeGripEnabled(True)" in dialogs and "setSizeGripEnabled(True)" in extra


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("OK", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, "—", exc)
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    sys.exit(0 if not failed else 1)
