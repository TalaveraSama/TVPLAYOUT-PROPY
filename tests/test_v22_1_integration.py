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
