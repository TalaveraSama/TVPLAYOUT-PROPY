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


def test_autotrim_worker_marks_done_and_runs_automatically_after_scan():
    """v24.0.2.36: el worker marca autotrim_done (no re-analiza) y el pase
    automático post-escaneo sólo toma películas sin analizar."""
    import os as _os, tempfile as _tf, shutil as _sh
    if _qt_app() is None:
        return
    from app.autotrim import AutoTrimWorker
    from app.db import DB as Database

    tmp = _tf.mkdtemp(prefix="autotrim36_")
    try:
        fake = _os.path.join(tmp, "ffmpeg_fake.sh")
        counter = _os.path.join(tmp, "count")
        with open(fake, "w") as f:
            f.write("#!/bin/bash\n"
                    "echo x >> " + counter + "\n"
                    "echo '[blackdetect @ 0x1] black_start:0 black_end:4.5 black_duration:4.5' >&2\n"
                    "exit 0\n")
        _os.chmod(fake, 0o755)

        database = Database(_os.path.join(tmp, "t.db"))
        nueva = _os.path.join(tmp, "peli_nueva.mkv")
        vista = _os.path.join(tmp, "peli_vista.mkv")
        database.upsert_media(nueva, "Peli Nueva", "Películas")
        database.update_media_meta(nueva, duration=3600.0)
        database.upsert_media(vista, "Peli Vista", "Películas")
        database.update_media_meta(vista, duration=3600.0, autotrim_done=1)

        rows = database.search_media("", "Películas", limit=100)
        assert len(rows) == 2, [r["title"] for r in rows]
        AutoTrimWorker(database, fake, rows, force=False).run()  # síncrono

        by_title = {r["title"]: r for r in database.search_media("", "Películas", limit=100)}
        # La nueva quedó recortada (intro saltada, final cortado) y marcada.
        assert abs(by_title["Peli Nueva"]["mark_in"] - 4.75) < 0.01
        assert abs(by_title["Peli Nueva"]["mark_out"] - 3479.75) < 0.01
        assert by_title["Peli Nueva"]["autotrim_done"] == 1
        # La ya analizada no se tocó y el ffmpeg falso se invocó SOLO para la
        # nueva (2 pasadas: cabecera y cola).
        assert by_title["Peli Vista"]["mark_in"] == 0
        with open(counter) as f:
            assert len(f.read().split()) == 2, "debió analizar sólo la película nueva"

        # Segundo pase (p. ej. siguiente escaneo): nada pendiente, 0 invocaciones.
        AutoTrimWorker(database, fake, database.search_media("", "Películas", limit=100),
                       force=False).run()
        with open(counter) as f:
            assert len(f.read().split()) == 2, "no debe re-analizar lo ya procesado"

        # Forzado (menú contextual): re-analiza aunque esté marcada.
        AutoTrimWorker(database, fake, database.search_media("", "Películas", limit=100),
                       force=True).run()
        with open(counter) as f:
            assert len(f.read().split()) == 6, "forzado re-analiza las dos (2+2+2)"
    finally:
        _sh.rmtree(tmp, ignore_errors=True)

    # Cableado del pase automático post-escaneo.
    window = _read("app", "main_window.py")
    dialogs = _read("app", "dialogs.py")
    autotrim = _read("app", "autotrim.py")
    assert "autotrim_on_scan" in window and '"autotrim_on_scan": True' in window
    assert "finished_all.connect(self._probe_done)" in window
    assert "def _probe_done(self, n):" in window and "_autotrim_new_movies()" in window
    assert "def _autotrim_new_movies(self):" in window
    assert "autotrim_done" in autotrim and autotrim.count("update_media_meta") >= 2
    assert '"autotrim_on_scan": self.autotrim_on_scan.isChecked(),' in dialogs


def _qt_app():
    """QApplication compartida para las pruebas de runtime (o None sin PySide6)."""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance() or QApplication([])


def test_rtmp_manager_accepts_monitor_feed_kwarg():
    """v24.0.2.31: _rtmp_start pasa monitor_feed_url y el gestor debe aceptarlo.

    Sin este parámetro en la firma, arrancar cualquier salida RTMP/SRT/NDI
    lanza TypeError y la salida queda DETENIDA para siempre.
    """
    main = _read("app", "main_window.py")
    output = _read("app", "output.py")
    assert "monitor_feed_url=monitor_feed_url)" in main
    block = output.split("class MultiOutputManager", 1)[1]
    block = block.split("def __init__", 1)[1].split("):", 1)[0]
    assert "monitor_feed_url" in block, "MultiOutputManager.__init__ debe aceptar monitor_feed_url"


def test_multi_output_manager_constructor_matches_rtmp_start_call():
    """El constructor acepta exactamente los kwargs que usa _rtmp_start."""
    if _qt_app() is None:
        return
    from app.output import MultiOutputManager
    manager = MultiOutputManager(
        "ffmpeg", [{"enabled": True, "name": "Principal", "protocol": "RTMP",
                    "target": "rtmp://servidor/live"}],
        [{"path": "/p/peli.mkv", "duration": 60.0}], "1920x1080", "29.97", "AUTO", 6000,
        "AUTO / Español latino preferido", "OFF", True, 192,
        loop=True, start_index=0, start_offset=12.5, extra_args="",
        logo=None, program_overlay=None, program_interval=1080.0,
        program_duration=15.0, ndi_ffmpeg=None, ndi_source=None, parent=None,
        monitor_feed_url="udp://127.0.0.1:39000")
    assert manager.monitor_feed_url == "udp://127.0.0.1:39000"
    w = manager._make_worker({"protocol": "RTMP", "target": "rtmp://servidor/live", "name": "P"},
                             "udp://127.0.0.1:39000")
    assert w.monitor_feed_url == "udp://127.0.0.1:39000"
    w2 = manager._make_worker({"protocol": "RTMP", "target": "rtmp://otro/live", "name": "Q"}, "")
    assert w2.monitor_feed_url == ""


def test_ndi_sender_fails_gracefully_without_runtime():
    """Sin NDI Runtime (Linux/desarrollo) el emisor informa la causa y no revienta."""
    if os.name == "nt":
        return
    from app.ndi_sender import NDISender
    sender = NDISender("Prueba NDI")
    assert sender.start() is False and sender.error
    ok, detail, path = NDISender.probe()
    assert ok is False and detail


def test_multi_output_manager_reports_ndi_unavailable():
    """Un perfil NDI sin Runtime emite estado claro y deja el gestor estable."""
    if os.name == "nt" or _qt_app() is None:
        return
    from app.output import MultiOutputManager
    manager = MultiOutputManager("ffmpeg", [{"enabled": True, "name": "NDI local",
                                             "protocol": "NDI", "target": "Studio Monitor"}],
                                 [], "1920x1080", "29.97", "AUTO", 6000)
    states = []
    manager.state.connect(lambda ok, msg: states.append((bool(ok), str(msg))))
    manager.start()
    assert states and not any(ok for ok, _ in states)
    assert any("NDI no disponible" in msg for _, msg in states)
    assert manager.isRunning() is False
    manager.stop()


def test_library_preview_prefers_mpv_with_vlc_fallback_and_clear_feedback():
    """v24.0.2.32: la vista previa de biblioteca usa mpv o VLC y avisa si no hay ninguno."""
    config = _read("app", "config.py")
    player = _read("app", "pyav_player.py")
    main = _read("app", "main_window.py")
    dialogs = _read("app", "dialogs.py")
    extra = _read("app", "dialogs_extra.py")
    assert "def find_vlc()" in config and "VLC_PATH = find_vlc()" in config
    assert 'vlc_path=""' in player and "--no-one-instance" in player
    assert "Preview abierto en" in player and "no se encontró mpv.exe ni VLC" in player
    assert 'vlc_path=VLC_PATH' in main
    assert 'open_external_preview(items[0]["path"], "BIBLIOTECA")' in main
    assert 'open_external_preview(self.ctrl.items[rows[0]]["path"], "PREVIEW")' in main
    assert "No se encontró mpv.exe ni VLC" in main
    assert "VLC (opcional)" in dialogs and "vlc (preview alternativo)" in extra


def test_open_external_preview_runtime_prefers_mpv_then_vlc():
    """Runtime: mpv primero, VLC de reserva y aviso claro sin ninguno."""
    if _qt_app() is None or os.name != "posix":
        return
    import stat
    import tempfile
    import time
    from app.pyav_player import PyAVPlayer
    witness = tempfile.mktemp(suffix=".txt")
    fake_mpv = tempfile.mktemp(suffix=".sh")
    fake_vlc = tempfile.mktemp(suffix=".sh")
    with open(fake_mpv, "w") as fh:
        fh.write(f'#!/bin/bash\necho mpv >> "{witness}"\n')
    with open(fake_vlc, "w") as fh:
        fh.write(f'#!/bin/bash\necho vlc >> "{witness}"\n')
    for exe in (fake_mpv, fake_vlc):
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)

    def statuses_of(player):
        msgs = []
        player.status.connect(msgs.append)
        return msgs

    # 1) Con ambos: mpv gana.
    p1 = PyAVPlayer(None, mpv_path=fake_mpv, vlc_path=fake_vlc)
    m1 = statuses_of(p1)
    assert p1.open_external_preview("/tmp/media/peli.mkv", "TEST") is True
    assert any("Preview abierto en mpv" in m for m in m1), m1
    # 2) Sin mpv: VLC de reserva.
    p2 = PyAVPlayer(None, mpv_path="", vlc_path=fake_vlc)
    m2 = statuses_of(p2)
    assert p2.open_external_preview("/tmp/media/peli.mkv", "TEST") is True
    assert any("Preview abierto en VLC" in m for m in m2), m2
    # 3) Sin ninguno: False + mensaje claro.
    p3 = PyAVPlayer(None, mpv_path="", vlc_path="")
    m3 = statuses_of(p3)
    assert p3.open_external_preview("/tmp/media/peli.mkv", "TEST") is False
    assert any("no se encontró mpv.exe ni VLC" in m for m in m3), m3
    # Los procesos de prueba realmente arrancaron.
    deadline = time.time() + 5
    while time.time() < deadline:
        if os.path.exists(witness):
            break
        time.sleep(0.1)
    content = open(witness).read() if os.path.exists(witness) else ""
    assert "mpv" in content and "vlc" in content, content


def test_ndi_test_pattern_and_live_counters_are_wired():
    """v24.0.2.33: tarjeta de prueba sin playout + contadores visibles en la app."""
    sender = _read("app", "ndi_sender.py")
    output = _read("app", "output.py")
    main = _read("app", "main_window.py")
    extra = _read("app", "dialogs_extra.py")
    assert "TEST_PATTERN_INTERVAL" in sender and "def _maybe_test_pattern" in sender
    assert "def _build_test_frame" in sender and "FUENTE DE PRUEBA NDI" in sender
    assert "self.frames_sent += 1" in sender and "self.audio_samples += sample_count" in sender
    assert "self.test_active = False" in sender and "self.test_active = True" in sender
    assert "def ndi_stats(self)" in output
    assert "ndi_stats() if self.output else []" in main
    assert 'getattr(self.output, "ndi_senders", None)' in main
    assert "tarjeta de prueba" in main
    # Guía de verificación en Dispositivos.
    assert "CÓMO VERIFICAR LA SALIDA NDI" in extra
    assert "Studio Monitor" in extra and "DistroAV" in extra and "UDP 5353" in extra


def test_ndi_test_pattern_frame_builds_and_stats_report_live_state():
    """Runtime: la tarjeta de prueba se genera con reloj y ndi_stats reporta."""
    if _qt_app() is None:
        return
    from app.ndi_sender import NDISender, TEST_PATTERN_WIDTH, TEST_PATTERN_HEIGHT
    from app.output import MultiOutputManager
    s = NDISender("Verificacion NDI")
    frame = s._build_test_frame()
    assert frame is not None and not frame.isNull()
    assert frame.width() == TEST_PATTERN_WIDTH and frame.height() == TEST_PATTERN_HEIGHT
    assert s.frames_sent == 0 and s.test_pattern is True
    # Gestor sin emisores: estadísticas vacías y sin errores.
    mgr = MultiOutputManager("ffmpeg", [], [], "1920x1080", "29.97", "AUTO", 6000)
    assert mgr.ndi_stats() == []


def test_ndi_stats_shows_in_output_monitor_label():
    """El monitor de salidas de la ventana muestra los frames NDI en vivo."""
    if _qt_app() is None:
        return
    from app.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)  # no arrancar hilos/timers
    import app.main_window as MW

    class _FakeMgr:
        ndi_senders = [object()]
        def isRunning(self):
            return True
        def ndi_stats(self):
            return [("Estudio", 3210, 96000, 0.1, False)]

    mw.settings = {"outputs": [{"enabled": True, "name": "Estudio", "protocol": "NDI",
                                "target": "Estudio"}], "rtmp_url": ""}
    mw.rtmp_url = type("L", (), {"text": ""})()
    mw.output = _FakeMgr()

    class _Lbl:
        text = ""
        def setText(self, value):
            self.text = value
    mw.rtmp_destinations = _Lbl()
    mw._refresh_output_monitor()
    assert "Estudio [NDI] · 3210 frames · señal en vivo" in mw.rtmp_destinations.text, mw.rtmp_destinations.text


def test_full_windows_installer_bundles_app_ffmpeg_mpv_and_optional_runtimes():
    """v24.0.2.34: el instalador único empaqueta todo y usa la versión actual."""
    import re
    cfg = _read("app", "config.py")
    iss = _read("installer", "TVPLAYOUT-PROPY.iss")
    build_installer = _read("installer", "BUILD_INSTALLER.bat")
    build_portable = _read("build_exe.bat")
    gitignore = _read(".gitignore")
    docs = _read("BUILD.md")
    version = re.search(r'APP_VERSION = "([^"]+)"', cfg).group(1)
    # Versión sincronizada en todos los artefactos del instalador.
    assert f'#define MyAppVersion "{version}"' in iss
    assert f"set \"APP_VERSION={version}\"" in build_installer
    assert f"set \"APP_VERSION={version}\"" in build_portable
    assert f"Setup_TVPlayoutPRO_{{#MyAppVersion}}" in iss
    # Instalación por usuario (carpeta con permisos de escritura para la BD).
    assert "PrivilegesRequired=lowest" in iss and "DefaultDirName={autopf}\TVPlayoutPRO" in iss
    # Empaqueta la app completa y los binarios en la raíz del programa.
    assert "dist\\TVPlayoutPRO\\*" in iss and "recursesubdirs" in iss
    assert "TVPlayoutPRO.exe" in iss
    # Opcionales: NDI Runtime, VLC y regla de firewall mDNS.
    assert 'Name: "ndi"' in iss and 'Name: "vlc"' in iss and 'Name: "firewall"' in iss
    assert "UDP localport=5353" in iss and "Spanish.isl" in iss
    # El orquestador descarga/vendoriza y compila con Inno Setup.
    assert "vendor" in build_installer and "ISCC" in build_installer
    assert "build_exe.bat --no-pause" in build_installer
    assert "gyan.dev" in build_installer and "mpv" in build_installer
    # El build portable ahora también empaqueta mpv.exe en la raíz.
    assert "MPV_SRC" in build_portable and "mpv-x86_64\\mpv.exe" in build_portable
    assert "vendor/" in gitignore
    assert "BUILD_INSTALLER.bat" in docs


def test_runtime_root_points_to_exe_dir_when_frozen():
    """Pureza de la raíz portable: congelada, ROOT es la carpeta del EXE.

    Así el instalador puede poner la app (con la BD junto al EXE) en
    %LOCALAPPDATA%\Programs y todo sigue funcionando igual que en modo
    portable.
    """
    import importlib
    import sys as _sys
    _sys.path.insert(0, REPO)
    saved_frozen = getattr(_sys, "frozen", None)
    saved_exe = getattr(_sys, "executable", "")
    fake_exe = os.path.join(REPO, "Programs", "TVPlayoutPRO.exe")
    try:
        _sys.frozen = True
        _sys.executable = fake_exe
        import app.config as cfg
        importlib.reload(cfg)
        assert str(cfg.ROOT) == os.path.dirname(os.path.abspath(fake_exe)), cfg.ROOT
    finally:
        if saved_frozen is None:
            del _sys.frozen
        else:
            _sys.frozen = saved_frozen
        _sys.executable = saved_exe
        import app.config as cfg
        importlib.reload(cfg)
        assert str(cfg.ROOT) == REPO


def test_rtmp_drift_uses_real_ffmpeg_position_not_wall_clock():
    """v24.0.2.35: la posición de FFmpeg se mide con -stats, no se estima.

    La estimación por reloj de pared contaba la latencia de arranque (abrir
    el archivo por red + conectar al RTMP: 7-9 s en un VPS lento) como
    contenido emitido y el watcher reiniciaba FFmpeg en bucle cada ~13 s.
    """
    output = _read("app", "output.py")
    main = _read("app", "main_window.py")
    assert '"-stats"' in output and "_PROGRESS_RE" in output
    assert "time=(\\d+):(\\d+):(\\d+(?:\\.\\d+)?)" in output
    assert "return -1.0  # calentando: sin medición real todavía" in output
    assert "return -1.0 if self.workers else 0.0" in output
    # El watcher no compara a ciegas durante el arranque y descuenta el gap.
    assert "if ffmpeg_pos < 0:" in main
    assert "self._rtmp_drift_baseline = mpv_time - ffmpeg_pos" in main
    # v24.0.2.37: drift con SIGNO — la salida adelantada (monitor local lento)
    # jamás se reinicia; sólo se corrige la salida que va detrás.
    assert "signed = (mpv_time - ffmpeg_pos) - self._rtmp_drift_baseline" in main
    assert "if signed < 0:" in main and "_rtmp_drift_local_lag_warned" in main
    # sc_threshold solo aporta algo a x264; en AMF/NVENC sólo generaba ruido.
    assert output.count('"-sc_threshold", "0"') == 1


def test_progress_line_parsing_and_current_position():
    """Runtime: _drain_stderr captura time= y current_position lo refleja."""
    if _qt_app() is None:
        return
    from app.output import OutputWorker

    class _FakeStderr:
        lines = [
            "frame=  100 fps= 25 q=28.0 size=    512kB time=00:00:04.00 bitrate=1049.6kbits/s speed=1x\r",
            "frame=  150 fps= 25 q=28.0 size=    768kB time=00:00:06.00 bitrate=1049.6kbits/s speed=1x\r",
            "[out#0/flv @ 0x1] Codec AVOption sc_threshold has not been used\n",
        ]
        def __iter__(self):
            return iter(self.lines)

    class _FakeProc:
        stderr = _FakeStderr()
        def poll(self):
            return None

    worker = OutputWorker("ffmpeg", [], "rtmp://x/live", "1920x1080", "29.97", "AUTO", 6000)
    worker._current_offset = 12.0
    worker.proc = _FakeProc()
    worker._drain_stderr(worker.proc, [])
    assert abs(worker._out_time - 6.0) < 0.001, worker._out_time
    assert abs(worker.current_position - 18.0) < 0.001  # 12.0 + 6.0 reales
    # Sin medición todavía (calentando): -1, nunca una estimación inflada.
    worker._out_time = -1.0
    worker._out_time_at = 0.0
    assert worker.current_position == -1.0


def test_drift_watcher_tolerates_startup_gap_and_catches_real_stall():
    """Runtime: el gap de arranque no es drift; un gap que crece sí lo es."""
    if _qt_app() is None:
        return
    from app.main_window import MainWindow

    class _Ctrl:
        is_on_air = True
        paused = False
        elapsed = 0.0
        onair = 0

    class _Out:
        def __init__(self):
            self.seeks = []
            self._position = -1.0
            self.index = 0
        @property
        def current_position(self):
            return self._position
        @current_position.setter
        def current_position(self, value):
            self._position = float(value)
        def isRunning(self):
            return True
        has_active_process = True
        def seek_to(self, index, offset):
            self.seeks.append((index, offset))

    mw = MainWindow.__new__(MainWindow)
    mw.output = _Out()
    mw.ctrl = _Ctrl()
    mw._rtmp_drift_threshold = 6.0
    mw._rtmp_drift_bad_count = 0
    mw._rtmp_drift_last_restart = 0.0
    mw._rtmp_drift_baseline = None
    mw._rtmp_drift_clip = None
    mw._rtmp_drift_had_unknown = False
    mw._rtmp_drift_suspend_until = 0.0
    mw._rtmp_drift_local_lag_warned = False
    mw._status = lambda *a, **k: None      # el aviso de monitor lento no toca la UI real

    # A) Calentando (VPS abriendo el archivo por red): no compara ni realinea.
    mw.ctrl.elapsed = 8.0
    mw.output.current_position = -1.0
    for _ in range(5):
        mw._rtmp_check_drift()
    assert mw.output.seeks == []

    # B) Primer frame medido: fija el gap de arranque como línea base.
    mw.ctrl.elapsed = 10.0
    mw.output.current_position = 2.0   # 8 s detrás del monitor local (arranque lento)
    mw._rtmp_check_drift()
    assert mw._rtmp_drift_baseline == 8.0
    assert mw.output.seeks == []

    # C) Gap constante = salida estable retrasada: NUNCA realinea
    #    (la versión anterior reiniciaba FFmpeg cada ~13 s en este punto).
    for t in range(12, 40, 2):
        mw.ctrl.elapsed = float(t)
        mw.output.current_position = float(t - 8)
        mw._rtmp_check_drift()
    assert mw.output.seeks == [], "un gap de arranque constante no es drift"

    # D) El gap CRECE (entrada que no da abasto): realigna una sola vez.
    mw.ctrl.elapsed = 60.0
    mw.output.current_position = 30.0   # el gap pasó de 8 a 30 s
    mw._rtmp_check_drift()
    mw._rtmp_check_drift()
    assert len(mw.output.seeks) == 1, mw.output.seeks
    # Tras realinear queda suspendido: no bucle inmediato.
    mw._rtmp_check_drift()
    assert len(mw.output.seeks) == 1

    # E) v24.0.2.37: la SALIDA va ADELANTADA y el gap crece (monitor local
    #    decodificando a <1x, caso del VPS con CPU justa): la señal RTMP está
    #    sana a 1x y NO se toca — antes esto reiniciaba cada ~25 s.
    mw.output.seeks.clear()
    mw._rtmp_drift_clip = None          # forzar nueva línea base
    mw._rtmp_drift_suspend_until = 0.0  # levantar la suspensión del realineo D
    mw._rtmp_drift_last_restart = 0.0
    mw.ctrl.elapsed = 20.0
    mw.output.current_position = 21.0   # salida 1 s por delante
    mw._rtmp_check_drift()
    assert mw._rtmp_drift_baseline == -1.0
    for t in range(22, 60, 2):
        mw.ctrl.elapsed = float(t)          # monitor a ~0.66x
        mw.output.current_position = float(t) * 1.0 + 1.0 - (20.0 - 21.0) - (-1.0)  # ~1x real
        mw.output.current_position = float(t) + (t - 22) * 0.34      # se adelanta progresivamente
        mw._rtmp_check_drift()
    assert mw.output.seeks == [], "la salida adelantada (monitor lento) no se reinicia"
    assert mw._rtmp_drift_local_lag_warned is True, "debió avisar una vez del monitor lento"


def test_clock_mode_advances_without_local_decode_and_ndi_is_disabled():
    """v24.0.2.37: modo Reloj (VPS sin decodificación local) + NDI off."""
    import time as _time
    # --- Estructural: cableado del modo Reloj y del NDI deshabilitado.
    playout = _read("app", "playout.py")
    window = _read("app", "main_window.py")
    dialogs = _read("app", "dialogs.py")
    dialogs_extra = _read("app", "dialogs_extra.py")
    assert "self.clock_only = False" in playout
    assert "def clock_tick(self):" in playout and '_on_ended("eof")' in playout
    assert "if self.clock_only and self._started_at > 0 and not self.paused:" in playout
    assert "if self.clock_only:\n            # v24.0.2.37: modo Reloj — sin decodificación local" in playout
    assert '"clock")' in dialogs and "ideal VPS" in dialogs
    assert "self.ctrl.clock_tick()" in window
    assert "RELOJ DEL SISTEMA" in window
    assert '"ndi_disabled": True' in window
    assert 'str(profile.get("protocol", "RTMP")).upper() == "NDI"' in window
    assert '"ndi_disabled": self.ndi_disabled.isChecked(),' in dialogs
    assert "deshabilitado temporalmente en Ajustes" in dialogs_extra

    # --- Runtime: el reloj de pared dirige el playout sin reproductor.
    if _qt_app() is None:
        return
    from app.playout import PlayoutController

    ctrl = PlayoutController.__new__(PlayoutController)
    ctrl.clock_only = True
    ctrl.paused = False
    ctrl.onair = 0
    ctrl.items = [{"path": "/tmp/media/peli.mkv", "title": "Peli", "duration": 2.0,
                   "source_duration": 2.0, "category": "Películas"}]
    ctrl._pos = 0.0
    ctrl._dur = 2.0
    ctrl._started_at = _time.time()
    ctrl._position_base = 0.0
    ctrl._midroll_next_at = 0.0
    ctrl.midroll_enabled = False
    ended = []
    ctrl._on_ended = lambda reason: ended.append(reason)
    ctrl._identifier_eligible = lambda item: False
    assert ctrl.is_on_air

    t0 = ctrl.elapsed
    assert t0 < 0.5, "el reloj debe partir de ~0"
    assert ctrl.clock_tick() is False       # todavía no termina (dur=2s)
    _time.sleep(1.2)
    assert 1.0 <= ctrl.elapsed - t0 <= 1.5, "avanza con el reloj de pared a 1x"
    _time.sleep(1.1)
    assert ctrl.clock_tick() is True        # llegó al final → avanza de evento
    assert ended == ["eof"]

    # Pausa: congela el reloj sin reproductor local.
    ctrl._started_at = _time.time()
    ctrl._pos = 0.0
    ctrl.paused = True
    frozen = ctrl.elapsed
    _time.sleep(0.3)
    assert abs(ctrl.elapsed - frozen) < 0.05, "en pausa el reloj no avanza"


def test_output_profiles_skip_ndi_when_disabled():
    """v24.0.2.37: con ndi_disabled los destinos NDI no arrancan (solo RTMP/SRT)."""
    if _qt_app() is None:
        return
    from app.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)
    mw.settings = {"outputs": [
        {"enabled": True, "name": "Principal", "protocol": "RTMP", "target": "rtmp://x/live"},
        {"enabled": True, "name": "NDI local", "protocol": "NDI", "target": "CANAL1"},
        {"enabled": True, "name": "SRT", "protocol": "SRT", "target": "srt://x:9000"},
    ]}
    mw._status = lambda *a, **k: None
    mw.rtmp_url = type("U", (), {"text": ""})()
    profiles = mw._output_profiles()
    assert [p["protocol"] for p in profiles] == ["RTMP", "SRT"], profiles
    mw.settings["ndi_disabled"] = False
    profiles = mw._output_profiles()
    assert [p["protocol"] for p in profiles] == ["RTMP", "NDI", "SRT"], profiles


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
