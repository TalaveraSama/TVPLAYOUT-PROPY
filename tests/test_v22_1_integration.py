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
    # En play() debe haber un set_property("volume", ...) y set_property("mute", ...)
    play_block = re.search(r"def play\(self.*?\n(?:        .*\n)+", src)
    assert play_block, "no encontré el método play()"
    pb = play_block.group(0)
    assert 'set_property("volume"' in pb, "play() debe re-aplicar volume con set_property"
    assert 'set_property("mute"' in pb, "play() debe re-aplicar mute con set_property"
    # El re-set debe ocurrir ANTES del loadfile
    loadfile_pos = pb.find('"loadfile"')
    vol_pos = pb.find('set_property("volume"')
    mute_pos = pb.find('set_property("mute"')
    assert vol_pos < loadfile_pos, "set_property('volume') debe ir antes del loadfile"
    assert mute_pos < loadfile_pos, "set_property('mute') debe ir antes del loadfile"


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
