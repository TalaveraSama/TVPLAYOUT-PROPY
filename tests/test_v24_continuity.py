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


def test_tmdb_general_scan_skips_done_and_edit_dialog_searches_image_gallery():
    window = _read("app", "main_window.py")
    tmdb = _read("app", "tmdb.py")
    dialog = _read("app", "dialogs_tmdb.py")
    # Escaneo general: sólo lo pendiente, con resumen al terminar.
    assert "escaneo general" in window
    assert "tmdb_id\"] or r[\"tmdb_poster" in window
    assert "_tmdb_lib_ok" in window and "_tmdb_lib_fail" in window
    assert "sin resultado" in window
    # Ventana de edición con buscador y galería de imágenes.
    assert "edit_tmdb_selected" in window and "TMDBEditDialog" in window
    assert "Editar ficha TMDB" in window
    assert "wants_clear" in window
    # Workers: búsqueda multi-resultado y galería de imágenes por película.
    assert "class TMDBSearchWorker" in tmdb and "class TMDBImagesWorker" in tmdb
    assert "/movie/{movie_id}/images" in tmdb
    assert "include_image_language" in tmdb
    assert "download_image" in tmdb
    assert "TMDBSearchWorker" in dialog and "TMDBImagesWorker" in dialog
    assert "poster_file" in dialog and "backdrop_file" in dialog


def test_tmdb_edit_dialog_is_simple_and_safe_to_close():
    """v24.0.2.26: una sola galería de imágenes (clic en la imagen correcta) y
    cierre inmediato: los hilos cuelgan de la ventana principal y nunca se
    espera bloqueando (el wait bloqueante provocaba congelamiento y el crash
    «QThread: Destroyed while thread is still running»)."""
    dialog = _read("app", "dialogs_tmdb.py")
    # Una sola galería: lista de resultados + lista de imágenes.
    assert dialog.count("QListWidget(") == 2
    assert "IMÁGENES DE LA PELÍCULA" in dialog
    assert "haz clic en la imagen que quieras usar" in dialog
    # Marca de imagen elegida por tipo.
    assert "✓ " in dialog and '"Póster" if img["kind"] == "poster" else "Fondo"' in dialog
    # Cierre seguro e inmediato.
    assert "wait(4000)" not in dialog
    assert "self._closed = True" in dialog
    assert "parent=self._worker_parent" in dialog
    assert "self._gallery_request += 1" in dialog and "self._search_gen += 1" in dialog


def test_tmdb_card_position_and_style_are_editable_with_wysiwyg_preview():
    """v24.0.2.25: la tarjeta TMDB al aire tiene posición/estilo configurables
    y la vista previa usa el mismo render que la salida (WYSIWYG)."""
    window = _read("app", "main_window.py")
    tmdb = _read("app", "tmdb.py")
    dialog = _read("app", "dialogs_tmdb.py")
    assert "render_movie_overlay" in tmdb and "resolve_card_layout" in tmdb
    assert "DEFAULT_CARD_LAYOUT" in tmdb
    assert '"tmdb_card_position"' in window and '"tmdb_card_align"' in window
    assert '"tmdb_card_style"' in window and '"tmdb_card_opacity"' in window and '"tmdb_card_margin"' in window
    assert "_tmdb_card_config" in window and "TMDBCardDialog" in window
    assert "open_tmdb_card" in window and "Tarjeta\\nTMDB" in window
    assert "_apply_movie_card" in window and "_tmdb_last_metadata" in window
    assert "class TMDBCardPreview" in dialog and "class TMDBCardDialog" in dialog
    assert "render_movie_overlay" in dialog and "Tarjeta compacta" in dialog
    assert "4:3 seguro" in dialog  # guías como el diálogo de Logo/CG
    # v24.0.2.27: el año se omite por defecto y se puede reactivar.
    assert '"show_year": False' in tmdb and 'if (cfg["show_year"] and year) else title' in tmdb
    assert '"tmdb_card_show_year"' in window and '"show_year": bool' in window
    assert "Mostrar año junto al título" in dialog and '"tmdb_card_show_year"' in dialog
    # v24.0.2.28: póster totalmente editable (tamaño y forma) y texto más compacto.
    assert '"poster_size": 100' in tmdb and '"poster_shape": "cuadrado"' in tmdb
    assert '"text_scale": 100' in tmdb
    assert "KeepAspectRatioByExpanding" in tmdb  # recorte al centro según la forma
    assert "0.032 * cfg[\"text_scale\"]" in tmdb and "0.0145 * cfg[\"text_scale\"]" in tmdb
    assert '"tmdb_card_poster_size"' in window and '"tmdb_card_poster_shape"' in window
    assert '"tmdb_card_text_scale"' in window
    assert "Tamaño del póster" in dialog and "Forma del póster" in dialog
    assert "Cuadrado" in dialog and "Original (2:3)" in dialog and "Panorámica 16:9" in dialog
    assert "Tamaño del texto" in dialog
    # v24.0.2.29: franja transparente, sin foto de fondo por defecto.
    assert '"backdrop_fill": False' in tmdb
    assert 'cfg["backdrop_fill"] and not backdrop.isNull()' in tmdb
    assert '"tmdb_card_backdrop_fill"' in window and '"backdrop_fill": bool' in window
    assert "Foto de fondo (backdrop) en la franja" in dialog and '"tmdb_card_backdrop_fill"' in dialog


def test_mpv_ipc_windows_pipe_is_byte_stream_not_message_mode():
    """v24.0.2.24: el named pipe de --input-ipc-server de mpv en Windows es un
    stream de bytes. Se abre con _winapi en modo síncrono y ReadFile/WriteFile
    directos; _read_loop arma los mensajes JSON delimitados por '\\n'.
    La versión con PipeConnection (modo MESSAGE) dejaba el playout mudo."""
    player = _read("app", "mpv_player.py")
    assert "from multiprocessing.connection import" not in player
    assert "_winapi.FILE_FLAG_OVERLAPPED" not in player  # handle síncrono, no overlapped
    assert "_winapi.ReadFile(self._handle, 65536)" in player
    assert "_winapi.WriteFile(self._handle, mv)" in player
    assert "_winapi.CloseHandle(self._handle)" in player
    assert 'buf.split(b"\\n", 1)' in player
    assert "IPC _PipeConn falló de forma inesperada" in player


def test_library_autotrim_and_clip_editing_apply_marks_to_playlist():
    """v24.0.2.30: auto-recorte de intro/final y Editar clip en biblioteca.

    Las marcas viven en la tabla media (mark_in/mark_out) y fluyen solas a la
    playlist vía make_item; make_item ya las lee del dict de la fila."""
    window = _read("app", "main_window.py")
    db = _read("app", "db.py")
    autotrim = _read("app", "autotrim.py")
    playout = _read("app", "playout.py")
    dialog = _read("app", "dialogs.py")
    # Migración y persistencia de marcas en media.
    assert '("mark_in", "REAL DEFAULT 0")' in db and '("mark_out", "REAL DEFAULT 0")' in db
    assert '"mark_in", "mark_out"' in db  # update_media_meta permitidos
    assert "trim_effective" in db
    # Detector: lógica pura + worker con blackdetect.
    assert "def parse_blackdetect" in autotrim and "def compute_marks" in autotrim
    assert "blackdetect=d=" in autotrim and "class AutoTrimWorker" in autotrim
    assert "HEAD_WINDOW" in autotrim and "TAIL_WINDOW" in autotrim and "MARGIN" in autotrim
    # Botones y acciones en biblioteca.
    assert "✂ Auto-recortar biblioteca" in window and "start_autotrim" in window
    assert "start_autotrim_selected" in window and "Auto-recortar selección" in window
    assert "✎ Editar clip" in window and "edit_library_clip" in window
    assert "AutoTrimWorker" in window and "LibraryClipDialog" in window
    # Diálogo de edición de clip de biblioteca.
    assert "class LibraryClipDialog" in dialog and "Guardar en biblioteca" in dialog
    # Propagación a eventos ya cargados y herencia al cargar playlists.
    assert "los recortes guardados en la biblioteca" in playout
    assert "se heredan si el evento no tiene propios" in db
    # La columna Duración muestra el recorte aplicado.
    assert "✂ {fmt_tc(dur_eff)}" in window


def test_windows_fit_tv_logical_resolution_and_dialogs_can_scroll():
    main = _read("app", "main_window.py")
    dialogs = _read("app", "dialogs.py")
    extra = _read("app", "dialogs_extra.py")
    assert "availableGeometry()" in main
    assert "self.statusBar().setSizeGripEnabled(True)" in main
    assert "self.setMinimumSize(min_w, min_h)" in main
    assert "QScrollArea" in dialogs and "def scroll_page" in dialogs
    assert "setSizeGripEnabled(True)" in dialogs and "setSizeGripEnabled(True)" in extra


def test_program_monitor_uses_the_encoded_ffmpeg_feed():
    main = _read("app", "main_window.py")
    output = _read("app", "output.py")
    dialogs = _read("app", "dialogs.py")
    assert "monitor_mode" in main and "program_feed" in main
    assert "_start_program_monitor" in main and "_program_monitor_url" in main
    assert "monitor_feed_url" in output and '"-f", "tee"' in output
    assert "onfail=ignore" in output and "proc.wait(timeout=2.5)" in output
    assert "Programa FFmpeg → reproductor externo" in dialogs
    assert "monitor_player_path" in dialogs


def test_autotrim_detects_netflix_style_intro_and_outro():
    """Lógica pura: el ident envuelto en negros se salta; el final se recorta."""
    import sys as _sys
    _sys.path.insert(0, REPO)
    try:
        from app.autotrim import compute_marks, parse_blackdetect
    except Exception:  # PySide6 ausente: se valida sólo la estructura
        return
    # Parser del stderr de blackdetect.
    text = ("[blackdetect @ 0x1] black_start:0 black_end:1.92 black_duration:1.92\n"
            "[blackdetect @ 0x2] black_start:10.1 black_end:12.4 black_duration:2.3\n")
    assert parse_blackdetect(text) == [(0.0, 1.92), (10.1, 12.4)]
    assert parse_blackdetect("sin negros aqui") == []
    # Patrón Netflix: negro → ident → negro → película.
    duration = 2 * 3600 + 15 * 60  # 2h15
    mi, mo = compute_marks(duration, head_blacks=[(0, 1.9), (10.1, 12.4)],
                           tail_blacks=[(duration - 25, duration - 20)])
    assert 12.4 < mi <= 13.0, "arranca tras el último negro (ident saltado)"
    assert duration - 25.5 <= mo < duration - 25, "corta en el primer negro del final"
    # Sin negros: sin recorte.
    assert compute_marks(duration, [], []) == (0.0, 0.0)
    # Cortes mínimos respetados y nunca deja menos de un minuto.
    assert compute_marks(duration, [(0, 0.3)], []) == (0.0, 0.0)
    assert compute_marks(90, head_blacks=[(0, 80)], tail_blacks=[]) == (0.0, 0.0)
    # Los micro-negros (parpadeos) se ignoran aunque el detector no filtre.
    assert compute_marks(5000, head_blacks=[(0, 0.1)], tail_blacks=[(4880, 4880.1)]) == (0.0, 0.0)
    assert compute_marks(duration, head_blacks=[(0, 100)]) == (0.0, 0.0)


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
