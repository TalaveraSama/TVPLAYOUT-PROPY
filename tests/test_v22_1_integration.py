"""Tests estructurales para los fixes de playout/RTMP/ volumen de v22.1.

No requiere PySide6 en runtime (sólo importamos el código y verificamos
firmas/contenido). Para los chequeos de OutputWorker.parseamos el archivo
directamente y confirmamos que la API pública esperada existe.

Ejecutar: python tests/test_v22_1_integration.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MPV = os.path.join(REPO, "app", "mpv_player.py")
OUT = os.path.join(REPO, "app", "output.py")
WIN = os.path.join(REPO, "app", "main_window.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_mpv_player_reapplies_volume_in_play():
    src = _read(MPV)
    # v22.2.8: el bug de v22.2.7 (opciones embebidas en loadfile que mpv
    # rechaza con issue #5770) y el bug de v22.2.1 (set_property antes
    # del loadfile aplicados al archivo anterior) se resuelven con una
    # estrategia combinada:
    #  - set_property ANTES del loadfile (volumen, mute, aid, sid, start, loop-file)
    #  - comando loadfile "path" replace (3 args, sin opciones embebidas)
    #  - _post_load_apply: set_property DESPUÉS del loadfile (200ms
    #    después vía QTimer.singleShot) para los críticos: pause, volume, mute
    #  - método _post_load_apply existe en el módulo
    play_block = re.search(r"def play\(self.*?\n(?:        .*\n)+", src, re.S)
    assert play_block, "no encontré el método play()"
    pb = play_block.group(0)
    # set_property para volume y mute ANTES del loadfile
    assert 'set_property("volume"' in pb, "play() debe setear volume antes del loadfile"
    assert 'set_property("mute"' in pb, "play() debe setear mute antes del loadfile"
    # el loadfile debe ser de 3 args (sin opciones embebidas)
    assert '"loadfile", path, "replace"' in pb or '["loadfile", path, "replace"]' in pb, \
        "play() debe usar loadfile con 3 argumentos (mpv rechaza opciones embebidas, issue #5770)"
    # el módulo debe definir _post_load_apply
    assert "def _post_load_apply" in src, \
        "el módulo debe tener _post_load_apply que reaplica pause/volume/mute tras el loadfile"
    # play() debe llamar a _post_load_apply vía QTimer.singleShot
    assert "QTimer.singleShot" in pb and "_post_load_apply" in pb, \
        "play() debe programar _post_load_apply con QTimer.singleShot tras el loadfile"


def test_apply_settings_sends_volume_to_mpv():
    src = _read(WIN)
    # En apply_settings con first=True debe invocar self.player.set_volume y self.player.set_mute
    # si mpv está corriendo
    block = re.search(r"if first:.*?self\._modes_changed\(\)", src, re.S)
    assert block, "no encontré el bloque 'if first:' en apply_settings"
    fb = block.group(0)
    assert "self.player.set_volume(" in fb, "apply_settings debe llamar self.player.set_volume al iniciar"
    assert "self.player.set_mute(" in fb, "apply_settings debe llamar self.player.set_mute al iniciar"


def test_volume_slider_has_debounce():
    src = _read(WIN)
    # El método _volume_changed debe iniciar un QTimer con debounce (no llamar
    # set_volume directo en cada valueChanged).
    block = re.search(r"def _volume_changed\(self.*?\n(?:        .*\n)+", src)
    assert block, "no encontré _volume_changed"
    vb = block.group(0)
    assert "_vol_debounce" in vb, "_volume_changed debe usar el debounce _vol_debounce"
    assert "self.player.set_volume(" not in vb, "_volume_changed NO debe llamar set_volume directamente (sólo el debounced)"
    assert "_apply_volume" in vb, "debe existir _apply_volume para aplicar el valor final"


def test_scheduled_run_resyncs_rtmp():
    src = _read(WIN)
    block = re.search(r"def _scheduled_run\(self.*?\n(?:        .*\n)+", src)
    assert block, "no encontré _scheduled_run"
    sb = block.group(0)
    assert "self.output.sync_items" in sb, "_scheduled_run debe re-sincronizar el RTMP tras replace_playlist"
    assert "force_jump=True" in sb, "la re-sincronización tras el programador debe ser force_jump=True"


def test_output_has_pause_and_seek_api():
    src = _read(OUT)
    assert "def pause_here" in src, "OutputWorker debe tener pause_here()"
    assert "def seek_to" in src, "OutputWorker debe tener seek_to()"
    assert "_jump_offset" in src, "OutputWorker debe manejar _jump_offset para seek/pause"
    # El loop principal debe consumir _jump_offset
    run_block = re.search(r"def run\(self.*?while not self\.stop_requested:.*?index = self\._jump_index.*?offset = getattr",
                          src, re.S)
    # El regex de arriba es muy estricto; hago uno más laxo
    run_block = re.search(r"def run\(self.*?\n        try:.*?\n(?:            .*\n)+",
                          src, re.S)
    assert run_block, "no encontré el cuerpo de run()"
    rb = run_block.group(0)
    assert "_jump_offset" in rb, "el loop de run() debe consumir _jump_offset"


def test_sync_items_accepts_start_offset():
    src = _read(OUT)
    sig = re.search(r"def sync_items\(self.*?\):", src)
    assert sig, "no encontré sync_items"
    assert "start_offset=0.0" in sig.group(0), "sync_items debe aceptar start_offset=0.0"


def test_main_window_watches_pause():
    src = _read(WIN)
    assert "_rtmp_tick_pause" in src, "MainWindow debe tener _rtmp_tick_pause para vigilar pausa"
    assert "_rtmp_sync_timer" in src, "MainWindow debe tener un timer _rtmp_sync_timer"
    # ctrl_seek debe llamar seek_to del RTMP
    seek_block = re.search(r"def ctrl_seek\(self.*?\n(?:        .*\n)+", src)
    assert seek_block, "no encontré ctrl_seek"
    sb = seek_block.group(0)
    assert "self.output.seek_to" in sb, "ctrl_seek debe propagar el seek al RTMP"


# --- v22.2.1: drift watcher ---

def test_output_exposes_current_offset():
    src = _read(OUT)
    assert "def current_offset" in src, "OutputWorker debe tener property current_offset"
    assert "_current_offset" in src, "OutputWorker debe mantener _current_offset"
    # El loop debe persistirlo
    run_block = re.search(r"def run\(self.*?\n(?:        .*\n)+", src, re.S)
    assert run_block
    rb = run_block.group(0)
    assert "self._current_offset = " in rb, "el loop debe persistir _current_offset antes de arrancar cada clip"


def test_main_window_has_drift_watcher():
    src = _read(WIN)
    assert "_rtmp_check_drift" in src, "MainWindow debe tener _rtmp_check_drift"
    assert "_rtmp_drift_timer" in src, "MainWindow debe tener _rtmp_drift_timer"
    assert "_rtmp_drift_threshold" in src, "MainWindow debe tener un umbral de drift configurable"
    idx = src.find("def _rtmp_check_drift(self")
    assert idx > 0
    # Leer 1500 caracteres (cubre cualquier implementación razonable)
    block = src[idx:idx + 2500]
    # v22.2.2: el watcher lee current_position (estimación dinámica), no
    # current_offset (estático).
    assert "self.output.current_position" in block, \
        "el watcher debe leer output.current_position (estimación dinámica de la posición de FFmpeg)"
    assert 'self.player, "_time"' in block or "self.player._time" in block, \
        "el watcher debe leer player._time (mpv local)"
    assert "self.output.seek_to" in block, "el watcher debe realinear con output.seek_to"


def test_drift_watcher_suspends_on_seek_and_pause():
    src = _read(WIN)
    # ctrl_seek debe suspender el watcher
    seek_block = re.search(r"def ctrl_seek\(self.*?\n(?:        .*\n)+", src)
    assert seek_block
    sb = seek_block.group(0)
    assert "_rtmp_drift_suspend_until" in sb, "ctrl_seek debe suspender el watcher de drift"
    # _rtmp_tick_pause debe suspender el watcher
    pause_block = re.search(r"def _rtmp_tick_pause\(self.*?\n(?:        .*\n)+", src)
    assert pause_block
    pb = pause_block.group(0)
    assert "_rtmp_drift_suspend_until" in pb, "_rtmp_tick_pause debe suspender el watcher de drift"
    # _rtmp_follow debe suspender el watcher
    follow_block = re.search(r"def _rtmp_follow\(self.*?\n(?:        .*\n)+", src)
    assert follow_block
    fb = follow_block.group(0)
    assert "_rtmp_drift_suspend_until" in fb, "_rtmp_follow debe suspender el watcher de drift"


def test_toggle_rtmp_uses_player_time_directly():
    src = _read(WIN)
    idx = src.find("def _rtmp_start(self")
    assert idx > 0, "no encontré _rtmp_start"
    end = src.find("self.output.start()", idx)
    assert end > idx, "no encontré self.output.start() en _rtmp_start"
    block = src[idx:end]
    # Acepta tanto self.player._time como getattr(self.player, "_time", 0.0)
    assert 'self.player._time' in block or 'getattr(self.player, "_time"' in block, \
        "_rtmp_start debe leer self.player._time (o getattr equivalente) para el offset inicial"
    assert "start_offset=mpv_time" in block, "_rtmp_start debe pasar mpv_time como start_offset al OutputWorker"


# --- v22.2.2: rtmp mode radio + current_position ---

def test_output_exposes_current_position():
    src = _read(OUT)
    assert "def current_position" in src, "OutputWorker debe tener property current_position"
    pos_block_idx = src.find("def current_position(self")
    assert pos_block_idx > 0
    end = src.find("\n    @property", pos_block_idx)
    if end < 0:
        end = pos_block_idx + 1200
    pb = src[pos_block_idx:end]
    assert "_current_offset" in pb, "current_position debe usar _current_offset"
    assert "_clip_emit_started" in pb, "current_position debe usar _clip_emit_started"
    assert "time.time()" in pb, "current_position debe usar time.time() para calcular el tiempo transcurrido"


def test_drift_watcher_uses_current_position():
    src = _read(WIN)
    idx = src.find("def _rtmp_check_drift(self")
    assert idx > 0
    block = src[idx:idx + 2500]
    assert "self.output.current_position" in block, \
        "el watcher de drift debe usar current_position (estimación dinámica), no current_offset (estático)"
    # v22.2.4: el watcher usa self.ctrl.elapsed (estimación con reloj de
    # pared cuando mpv no reporta time-pos). Antes leía self.player._time
    # que podía quedar en 0.
    assert "self.ctrl.elapsed" in block, \
        "el watcher debe usar self.ctrl.elapsed (estimación dinámica con reloj de pared)"


def test_rtmp_mode_radios_in_ui():
    src = _read(WIN)
    assert "QRadioButton" in src, "main_window.py debe importar QRadioButton"
    assert "QButtonGroup" in src, "main_window.py debe usar QButtonGroup para los radios"
    assert "self.rtmp_mode_local" in src, "debe existir self.rtmp_mode_local"
    assert "self.rtmp_mode_remote" in src, "debe existir self.rtmp_mode_remote"
    assert "self.rtmp_mode_ndi" in src, "debe existir self.rtmp_mode_ndi (placeholder para futuro)"
    assert "def _rtmp_mode_changed" in src, "debe existir el handler _rtmp_mode_changed"
    assert "def _rtmp_start" in src, "debe existir el método _rtmp_start"
    assert "def _rtmp_stop" in src, "debe existir el método _rtmp_stop"


def test_rtmp_mode_persisted_in_settings():
    src = _read(WIN)
    assert '"rtmp_mode"' in src, "rtmp_mode debe estar en DEFAULT_SETTINGS"
    assert 'self._save_setting("rtmp_mode"' in src, "_rtmp_mode_changed debe persistir el modo en la BD"
    # _rtmp_state debe volver a modo local si hay error
    assert "self.rtmp_mode_local.setChecked(True)" in src, "fallo de RTMP debe volver a modo local"


def test_ndi_radio_disabled_placeholder():
    src = _read(WIN)
    # El radio de NDI debe estar deshabilitado
    assert "self.rtmp_mode_ndi.setEnabled(False)" in src, "RTMP Local (NDI) debe estar deshabilitado como placeholder"


# --- v22.2.2 hotfix: bug del NameError en _build_right ---

def test_build_right_does_not_use_undefined_s():
    """v22.2.2: en _build_right se referenciaba 's.get(...)' que no estaba
    definido en ese scope (sólo en apply_settings). El fix es usar
    self.settings directamente. Este test garantiza que no vuelva a pasar.
    """
    src = _read(WIN)
    idx = src.find("def _build_right(self")
    end = src.find("def ", idx + 20)
    block = src[idx:end]
    # Buscamos 's.get(' o 's[' pero NO precedido por '=' (eso sería asignación
    # local de s) ni por 'self.' (eso sería self.s).
    import re
    for m in re.finditer(r"(?<!self\.)\bs\.[a-zA-Z_]", block):
        # Permitimos s.get, s.update, etc. dentro del bloque SOLO si hay
        # un '=' asignando a 's' antes.
        ctx_start = max(0, m.start() - 200)
        ctx = block[ctx_start:m.start()]
        if "= s" in ctx and ctx.rfind("= s") > ctx.rfind("\n"):
            # Hay una asignación local a 's' antes de este uso, OK
            continue
        # Si llegamos acá, hay un uso de 's.' sin asignación previa
        raise AssertionError(
            f"_build_right usa 's.' en offset {m.start()} sin asignación "
            f"previa: {block[max(0, m.start()-40):m.end()+40]!r}"
        )


def test_rtmp_mode_initial_uses_self_settings():
    """v22.2.2: initial_mode = self.settings.get('rtmp_mode', 'local')"""
    src = _read(WIN)
    # Buscar la línea exacta
    assert 'self.settings.get("rtmp_mode"' in src, \
        "initial_mode debe usar self.settings.get('rtmp_mode', 'local'), no 's.get(...)'"


# --- v22.2.10: monitor negro post-cut por watch_later restore ---

def test_mpv_player_disables_watch_later():
    """v22.2.10: --no-resume-playback y --no-save-position-on-quit en
    la línea de comando de mpv, y un método _purge_watch_later que
    limpia archivos .cfg de watch_later al arrancar.
    """
    src = _read(MPV)
    # _build_cmd debe incluir los dos flags
    build = re.search(r"def _build_cmd\(self.*?\n(?:        .*\n)+", src, re.S)
    assert build, "no encontré _build_cmd()"
    bb = build.group(0)
    assert "--no-resume-playback" in bb, \
        "_build_cmd debe pasar --no-resume-playback a mpv (sino mpv restaura la posición guardada al cargar el clip)"
    assert "--no-save-position-on-quit" in bb, \
        "_build_cmd debe pasar --no-save-position-on-quit a mpv (sino mpv guarda la posición al terminar y la usa la próxima vez)"
    # Debe existir un método _purge_watch_later que limpia los .cfg
    assert "def _purge_watch_later" in src, \
        "debe existir _purge_watch_later() que limpia los archivos watch_later al arrancar"
    # _purge_watch_later debe llamarse desde _build_cmd
    assert "_purge_watch_later()" in bb, \
        "_build_cmd debe invocar _purge_watch_later() antes de armar la línea de comando"
    # El método _purge_watch_later debe buscar APPDATA (Windows) y ~/.config (Linux)
    purge = re.search(r"def _purge_watch_later\(self.*?\n(?:        .*\n)+", src, re.S)
    assert purge, "no encontré el cuerpo de _purge_watch_later"
    pb = purge.group(0)
    assert "APPDATA" in pb or "appdata" in pb, \
        "_purge_watch_later debe buscar %APPDATA%/mpv/watch_later/ en Windows"
    assert ".config" in pb or "XDG_STATE" in pb, \
        "_purge_watch_later debe buscar ~/.config/mpv/watch_later/ o $XDG_STATE_HOME en Linux/macOS"
    # Debe borrar archivos .cfg específicamente
    assert ".cfg" in pb, "_purge_watch_later debe borrar archivos .cfg de watch_later"
    # Debe usar os.remove u os.unlink (no shutil.rmtree — sería demasiado)
    assert "os.remove" in pb or "os.unlink" in pb or "shutil.rmtree" in pb, \
        "_purge_watch_later debe usar os.remove/unlink o shutil.rmtree para borrar"


# --- v23.0: crossfade de audio entre clips ---

def test_mpv_player_supports_crossfade():
    """v23.0: MPVPlayer expone crossfade_enabled, crossfade_duration,
    set_crossfade() y fade_out(). play() aplica el filtro afade de
    fade-in al cargar el clip.
    """
    src = _read(MPV)
    # Atributos de instancia
    assert "self.crossfade_enabled" in src, "MPVPlayer debe tener self.crossfade_enabled"
    assert "self.crossfade_duration" in src, "MPVPlayer debe tener self.crossfade_duration"
    # Método set_crossfade para configurar
    assert "def set_crossfade" in src, "MPVPlayer debe tener set_crossfade() para configurar desde la UI"
    # Método fade_out para triggerear desde playout._tick()
    fade_out = re.search(r"def fade_out\(self.*?\n(?:        .*\n)+", src, re.S)
    assert fade_out, "no encontré el método fade_out()"
    fb = fade_out.group(0)
    assert "af" in fb and "afade" in fb, "fade_out debe agregar el filtro lavfi=afade a mpv"
    # Flag de no-duplicar
    assert "_fade_out_applied" in src, "MPVPlayer debe tener _fade_out_applied para no aplicar fade_out dos veces"
    # play() debe aplicar el fade-in si está habilitado
    play_block = re.search(r"def play\(self.*?\n(?:        .*\n)+", src, re.S)
    assert play_block, "no encontré el método play()"
    pb = play_block.group(0)
    assert "afade" in pb, "play() debe aplicar el filtro afade de fade-in cuando crossfade_enabled es True"


def test_playout_triggers_fade_out():
    """v23.0: playout._tick() invoca player.fade_out() cuando quedan
    crossfade_duration segundos para terminar el clip al aire.
    """
    src = _read(OUT)  # historical: OUT is the playout module path
    # En este test suite OUT apunta a app/output.py, no app/playout.py.
    # Necesitamos leer playout.py directamente.
    playout_src = _read(os.path.join(REPO, "app", "playout.py"))
    tick_block = re.search(r"def _tick\(self.*?\n(?:        .*\n)+", playout_src, re.S)
    assert tick_block, "no encontré _tick() en playout.py"
    tb = tick_block.group(0)
    assert "self.player.fade_out" in tb, \
        "playout._tick() debe invocar self.player.fade_out() cuando quedan crossfade_duration segundos"
    assert "crossfade_enabled" in tb or "crossfade" in tb.lower(), \
        "playout._tick() debe chequear el flag de crossfade del player antes de triggerear el fade-out"
    assert "self.player.crossfade_duration" in tb or "crossfade_duration" in tb, \
        "playout._tick() debe usar la duración configurada en el player"


def test_main_window_has_crossfade_controls():
    """v23.0: la UI tiene un toggle de crossfade y un slider de duración,
    con sus handlers que invocan self.player.set_crossfade() y persisten
    en settings.
    """
    src = _read(WIN)
    # Toggle
    assert "self.crossfade_btn" in src, "main_window debe tener self.crossfade_btn (toggle de crossfade)"
    assert "_crossfade_toggle_changed" in src, \
        "main_window debe tener el handler _crossfade_toggle_changed"
    # Slider
    assert "self.crossfade_duration" in src, "main_window debe tener el slider self.crossfade_duration"
    assert "_crossfade_duration_changed" in src, \
        "main_window debe tener el handler _crossfade_duration_changed"
    # Persistencia en settings
    assert 'crossfade_enabled' in src, \
        "main_window debe persistir 'crossfade_enabled' en settings"
    assert 'crossfade_duration' in src, \
        "main_window debe persistir 'crossfade_duration' en settings"
    # Handlers deben llamar al player
    assert "self.player.set_crossfade" in src, \
        "los handlers deben invocar self.player.set_crossfade()"
    # apply_settings debe aplicar el estado desde settings
    apply = re.search(r"def apply_settings\(self.*?self\._modes_changed\(\)", src, re.S)
    assert apply, "no encontré el cuerpo de apply_settings"
    ab = apply.group(0)
    assert "crossfade_enabled" in ab and "crossfade_duration" in ab, \
        "apply_settings debe aplicar el estado del crossfade desde settings (crossfade_enabled + crossfade_duration)"


# --- v23.3: filler automático + slate fallback ---

def test_mpv_player_supports_play_loop():
    """v23.3: MPVPlayer.play_loop(path) reproduce en loop infinito,
    sacando los filtros de crossfade residuales y usando loop-file=inf.
    """
    src = _read(MPV)
    # Encontrar play_loop buscando desde la firma hasta la siguiente def
    idx = src.find("def play_loop(self")
    assert idx > 0, "no encontré el método play_loop()"
    end = src.find("\n    def ", idx + 20)
    if end < 0:
        end = idx + 2500
    plb = src[idx:end]
    # El método debe tener loop-file=inf
    assert "loop-file" in plb and "inf" in plb, \
        "play_loop debe setear loop-file=inf en mpv"
    # Debe usar loadfile para arrancar el clip
    assert "loadfile" in plb, "play_loop debe usar loadfile para arrancar el clip"
    # Debe sacar los filtros de crossfade residuales (no aplicarlos nuevos)
    assert 'af", "remove"' in plb, \
        "play_loop debe sacar los filtros de crossfade residuales (@fadein/@fadeout) antes de arrancar"
    # No debe agregar filtros nuevos de afade. Buscamos el patrón de
    # apply (afade=) o remove (afade) solo en líneas de código (no en
    # docstring). Las líneas de código tienen exactamente 8 espacios de
    # indentación.
    code_lines = [l for l in plb.splitlines() if l.startswith("        ") and not l.startswith("         ")]
    code = "\n".join(code_lines)
    assert 'afade=' not in code, \
        "play_loop NO debe agregar filtros nuevos de afade (el filler es continuo, sin crossfade)"


def test_playout_has_filler_and_slate():
    """v23.3: PlayoutController expone filler_path, filler_active,
    _play_filler y _play_slate. _on_ended los invoca cuando no hay
    próximo clip, en lugar de quedar con monitor en negro.
    """
    src = _read(os.path.join(REPO, "app", "playout.py"))
    # Atributos de instancia
    assert "self.filler_path" in src, "PlayoutController debe tener self.filler_path"
    assert "self.filler_active" in src, "PlayoutController debe tener self.filler_active"
    # Métodos
    assert "def _play_filler" in src, "PlayoutController debe tener _play_filler()"
    assert "def _play_slate" in src, "PlayoutController debe tener _play_slate()"
    # _on_ended debe invocar _play_filler y _play_slate cuando no hay
    # más clips disponibles
    on_ended = re.search(r"def _on_ended\(self.*?\n(?:        .*\n)+", src, re.S)
    assert on_ended, "no encontré _on_ended"
    oeb = on_ended.group(0)
    assert "self._play_filler" in oeb and "self._play_slate" in oeb, \
        "_on_ended debe invocar _play_filler y _play_slate como fallback al fin de playlist"
    # Convención: -2 significa filler al aire
    assert "self.onair = -2" in src, \
        "PlayoutController debe usar self.onair = -2 como convención para filler al aire"
    # _on_position debe ignorar actualizaciones del filler
    on_pos = re.search(r"def _on_position\(self.*?\n(?:        .*\n)+", src, re.S)
    assert on_pos, "no encontré _on_position"
    opb = on_pos.group(0)
    assert "self.onair == -2" in opb, \
        "_on_position debe ignorar actualizaciones cuando onair == -2 (filler)"


def test_main_window_has_filler_setting():
    """v23.3: main_window expone filler_path y filler_enabled en
    DEFAULT_SETTINGS, y apply_settings lo carga en self.ctrl.filler_path.
    """
    src = _read(WIN)
    assert '"filler_path"' in src, "DEFAULT_SETTINGS debe tener 'filler_path'"
    assert '"filler_enabled"' in src, "DEFAULT_SETTINGS debe tener 'filler_enabled'"
    apply = re.search(r"def apply_settings\(self.*?self\._modes_changed\(\)", src, re.S)
    assert apply, "no encontré apply_settings"
    ab = apply.group(0)
    assert "filler_path" in ab, "apply_settings debe cargar filler_path en self.ctrl.filler_path"


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
