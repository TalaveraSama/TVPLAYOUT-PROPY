"""Pruebas del motor continuo «dos mundos» (productor de spools + consumidor persistente).

Se usa un FFmpeg falso (script) para validar la orquestación sin depender de
un binario real: el falso productor escribe un «spool TS» con marcadores de
timestamp global y el falso consumidor lee stdin y reporta ``time=``.

Ejecutar:  python -m pytest tests/test_feed_engine.py -q
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# --------------------------------------------------------------------- fakes
FAKE_FFMPEG = r'''#!/usr/bin/env python3
import os, re, sys, time

args = sys.argv[1:]

def has(flag):
    return flag in args

def opt(flag, default=None):
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default

def ts_str(t):
    return "%02d:%02d:%06.3f" % (int(t // 3600), int(t % 3600 // 60), t % 60)

# ---- MODO PRODUCTOR: escribe un spool TS "global" a ritmo acelerado ----
out = opt("-f")
ts_offset = float(opt("-output_ts_offset", "0") or 0)
if out == "mpegts" and not has("pipe:0"):
    path = args[-1]
    dur = float(opt("-t", "6") or 6)
    chunk = 0.5
    with open(path, "wb") as f:
        t = ts_offset
        written = 0.0
        while written < dur:
            f.write(("TS @%.3f\n" % t).encode())
            f.flush()
            t += chunk
            written += chunk
            time.sleep(0.02)      # acelerado (no realtime) para el test
    sys.exit(0)

# ---- MODO CONSUMIDOR: lee stdin, imprime time= (formato -stats) ----
# Con un pequeño ritmo por paquete emula el pacing de -re (más lento que la
# producción del falso productor, como en la realidad).
if has("pipe:0"):
    t = -1.0
    buf = b""
    try:
        while True:
            data = os.read(0, 65536)
            if not data:
                break
            buf += data
            new_t = t
            for m in re.finditer(rb"TS @([0-9.]+)", buf):
                new_t = max(new_t, float(m.group(1)))
            if new_t > t:
                t = new_t
                sys.stderr.write("frame=  1 fps=0.0 q=-1.0 size=       1kB time=%s speed=1.00x\r" % ts_str(t))
                sys.stderr.flush()
                time.sleep(0.05)
            if len(buf) > (1 << 20):
                buf = buf[-65536:]
    except OSError:
        pass
    sys.exit(0)

sys.exit(0)
'''


def _make_fake_ffmpeg(tmpdir):
    path = os.path.join(tmpdir, "fake_ffmpeg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_FFMPEG)
    os.chmod(path, 0o755)
    slate = os.path.join(tmpdir, "slate.mp4")
    with open(slate, "wb") as f:
        f.write(b"slate")
    return path, slate


def _media_file(tmpdir, name):
    p = os.path.join(tmpdir, name)
    with open(p, "wb") as f:
        f.write(b"media")
    return p


def _engine(ffmpeg, items, tmpdir, **kw):
    from app.feed_engine import ContinuousOutputEngine
    return ContinuousOutputEngine(
        ffmpeg=ffmpeg,
        items=items,
        url="rtmp://fake.server/live",
        resolution="1920x1080",
        fps="25",
        encoder="CPU/x264",
        bitrate=4000,
        audio_preference="AUTO",
        subtitle_preference="OFF",
        subtitle_burn=False,
        audio_bitrate=192,
        loop=True,
        start_index=kw.pop("start_index", 0),
        start_offset=kw.pop("start_offset", 0.0),
        fallback_mode="bars",
        seamless_concat=True,
        **kw,
    )


# ------------------------------------------------------------------- tests
def test_producer_command_has_global_offset_and_ts(tmp_path):
    """El comando productor lleva -re, -ss/-t, aresample y el offset global."""
    ffmpeg, _ = _make_fake_ffmpeg(str(tmp_path))
    from app.feed_engine import ContinuousOutputEngine
    media = _media_file(str(tmp_path), "peli.mp4")
    eng = ContinuousOutputEngine(
        ffmpeg=ffmpeg, items=[{"path": media}], url="rtmp://x/live",
        resolution="1280x720", fps="25", encoder="CPU/x264", bitrate=4000,
        subtitle_preference="OFF", fallback_mode="bars")
    item = {"path": media, "mark_in": 10.0, "mark_out": 40.0,
            "source_duration": 120.0, "duration": 30.0}
    cmd, label, aid, dur = eng._build_producer_command(item, 5.0, 123.5, "/tmp/out.ts")
    s = " ".join(cmd)
    assert label == "CPU/x264"
    assert "-ss 15.000" in s            # mark_in 10 + offset 5
    assert "-t 25.000" in s             # trim 30 (40-10) - offset 5 restantes
    assert "-output_ts_offset 123.500" in s
    assert "-f mpegts" in s and s.endswith("/tmp/out.ts")
    assert "-re" in s
    assert "aresample=async=1:first_pts=0" in s
    assert "setsar=1" in s
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in s
    assert "libx264" in s
    assert abs(dur - 25.0) < 0.01


def test_producer_duration_without_marks(tmp_path):
    """Sin marcas, el segmento usa la duración conocida del clip (EOF natural)."""
    ffmpeg, _ = _make_fake_ffmpeg(str(tmp_path))
    from app.feed_engine import ContinuousOutputEngine
    eng = ContinuousOutputEngine(
        ffmpeg=ffmpeg, items=[{"path": "/media/peli.mp4"}], url="rtmp://x/live",
        resolution="1280x720", fps="25", encoder="CPU/x264", bitrate=4000,
        subtitle_preference="OFF", fallback_mode="bars")
    media = _media_file(str(tmp_path), "peli.mp4")
    item = {"path": media, "source_duration": 90.0, "duration": 90.0}
    cmd, _label, _aid, dur = eng._build_producer_command(item, 0.0, 0.0, "/tmp/o.ts")
    s = " ".join(cmd)
    assert " -t " not in s              # hasta EOF natural, como el camino legacy
    assert abs(dur - 90.0) < 0.01       # pero la línea de tiempo conoce la duración


def test_slate_command_maintains_flow(tmp_path):
    ffmpeg, _ = _make_fake_ffmpeg(str(tmp_path))
    from app.feed_engine import ContinuousOutputEngine
    eng = ContinuousOutputEngine(
        ffmpeg=ffmpeg, items=[], url="rtmp://x/live",
        resolution="1280x720", fps="25", encoder="CPU/x264", bitrate=4000,
        subtitle_preference="OFF", fallback_mode="bars")
    eng.SLATE_CHUNK = 120.0
    cmd, _label = eng._build_slate_command(77.0, "/tmp/slate.ts")
    s = " ".join(cmd)
    assert "-output_ts_offset 77.000" in s
    assert "-stream_loop" in s and "-re" in s
    assert "-t 120.000" in s
    assert "-f mpegts" in s


def test_engine_end_to_end_feed_and_signals(tmp_path):
    """Ciclo completo: produce dos clips, empalma, emite progreso y fin, y el
    consumidor NUNCA se reinicia (un único proceso durante toda la sesión)."""
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    a = _media_file(str(tmp_path), "a.mp4")
    b = _media_file(str(tmp_path), "b.mp4")
    items = [{"path": a, "source_duration": 6.0, "duration": 6.0},
             {"path": b, "source_duration": 6.0, "duration": 6.0}]
    eng = _engine(ffmpeg, items, str(tmp_path))
    signals = {"log": [], "state": [], "now": [], "progress": [], "finished": [], "ended": 0}
    # DirectConnection: el test no tiene event loop; la entrega en cola del
    # hilo UI nunca llegaría. En la app real (con loop) la conexión por
    # defecto entrega en el hilo de interfaz como corresponde.
    from PySide6.QtCore import Qt
    eng.log.connect(lambda m: signals["log"].append(m), Qt.DirectConnection)
    eng.state.connect(lambda ok, m: signals["state"].append((ok, m)), Qt.DirectConnection)
    eng.now_playing.connect(lambda i, p: signals["now"].append((i, p)), Qt.DirectConnection)
    eng.progress.connect(lambda i, p: signals["progress"].append((i, p)), Qt.DirectConnection)
    eng.clip_finished.connect(lambda i, ok: signals["finished"].append((i, ok)), Qt.DirectConnection)
    eng.ended.connect(lambda: signals.__setitem__("ended", signals["ended"] + 1), Qt.DirectConnection)

    eng.start()
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if any(i == 1 for i, _ok in signals["finished"]):
                break
            time.sleep(0.1)
    finally:
        eng.stop()
        eng.wait(10000)

    finished_idx = [i for i, _ok in signals["finished"]]
    assert 0 in finished_idx, f"clip 0 no terminó: {signals['log'][-8:]}"
    # el consumidor persistente debió arrancar (ON AIR) sin reconexiones
    starts = [m for _ok, m in signals["state"] if "ON AIR" in m]
    assert starts, f"sin ON AIR: {signals['state']}"
    reconnects = [m for m in signals["log"] if "reconectando" in m]
    assert not reconnects, f"el consumidor se reinició: {reconnects}"
    # progreso con índices de playlist y posiciones crecientes
    idxs = {i for i, _p in signals["progress"]}
    assert 0 in idxs, f"sin progreso del clip 0: {signals['progress'][:5]}"
    assert signals["ended"] == 1


def test_switch_without_touching_consumer(tmp_path):
    """Un salto manual (force_jump) conmuta segmentos sin reiniciar el consumidor."""
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    a = _media_file(str(tmp_path), "a.mp4")
    b = _media_file(str(tmp_path), "b.mp4")
    items = [{"path": a, "source_duration": 30.0, "duration": 30.0},
             {"path": b, "source_duration": 30.0, "duration": 30.0}]
    eng = _engine(ffmpeg, items, str(tmp_path))
    logs = []
    eng.log.connect(logs.append)
    eng.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if eng._pumps and eng._pumps[0].cur_seq >= 0:
                break
            time.sleep(0.05)
        assert eng._pumps, "no arrancó la bomba"
        pump = eng._pumps[0]
        first_consumer = pump.consumer
        # esperar a que el primer segmento tenga bytes y se alimente
        deadline = time.time() + 15
        while time.time() < deadline and pump._offset == 0:
            time.sleep(0.05)
        assert pump._offset > 0, "la bomba no alimentó al consumidor"
        # salto manual al evento 2
        assert eng.sync_items(items, 1, force_jump=True) is True
        deadline = time.time() + 25
        while time.time() < deadline:
            cur = eng._current_master_segment()
            if cur is not None and not cur.is_slate and cur.index == 1 and cur.seq != 0:
                break
            time.sleep(0.1)
        cur = eng._current_master_segment()
        assert cur is not None and cur.index == 1, f"no conmutó al evento 2 (cur={cur and cur.index})"
        # el proceso consumidor debe ser EL MISMO (nunca se reinició)
        assert pump.consumer is first_consumer, "el consumidor persistente se reinició"
        assert first_consumer.poll() is None
    finally:
        eng.stop()
        eng.wait(10000)
    assert any("conmutación" in m for m in logs)


def test_standalone_slate_when_playlist_empty(tmp_path):
    """Sin playlist, el motor produce slate para mantener la conexión viva."""
    ffmpeg, slate = _make_fake_ffmpeg(str(tmp_path))
    import app.feed_engine as fe
    orig = fe.get_or_create_fallback_slate
    fe.get_or_create_fallback_slate = lambda *a, **k: slate
    try:
        eng = _engine(ffmpeg, [], str(tmp_path))
        eng.SLATE_CHUNK = 2.0            # slate corto para el test
        eng.start()
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                if eng._segments and eng._segments[0].proc is not None:
                    break
                time.sleep(0.05)
            assert eng._segments, "no creó segmento de slate"
            seg = eng._segments[0]
            assert seg.is_slate
            deadline = time.time() + 15
            while time.time() < deadline and not seg.done:
                time.sleep(0.05)
            assert seg.done, "el productor de slate no terminó"
        finally:
            eng.stop()
            eng.wait(10000)
    finally:
        fe.get_or_create_fallback_slate = orig


def test_speculation_matches_provider(tmp_path):
    """El proveedor del controlador decide el siguiente evento pre-producido."""
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    a = _media_file(str(tmp_path), "a.mp4")
    b = _media_file(str(tmp_path), "b.mp4")
    c = _media_file(str(tmp_path), "c.mp4")
    items = [{"path": a, "duration": 30.0}, {"path": b, "duration": 30.0},
             {"path": c, "duration": 30.0}]
    eng = _engine(ffmpeg, items, str(tmp_path))
    # el controlador "decide" que tras el evento 0 va el 2
    eng.set_next_provider(lambda cur: (2, items[2]))
    got = eng._speculate_next(0)
    assert got is not None and got[0] == 2 and got[1]["path"] == c
    # sin proveedor: avance lineal
    eng.set_next_provider(None)
    got = eng._speculate_next(0)
    assert got is not None and got[0] == 1 and got[1]["path"] == b
    # sin loop y sin nada después: None (slate)
    eng.loop = False
    assert eng._speculate_next(2) is None


def test_orphan_cleanup_on_python_exit(tmp_path):
    """proc_tools registra los hijos y kill_all_live los termina."""
    from app import proc_tools
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    proc = proc_tools.popen([ffmpeg, "-f", "mpegts", str(tmp_path / "x.ts")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert proc.poll() is None
    proc_tools.kill_all_live()
    try:
        proc.wait(timeout=3)
        cleaned = True
    except Exception:  # noqa: BLE001
        cleaned = False
    assert cleaned and proc.poll() is not None


def test_pause_freezes_flow_without_killing_consumer(tmp_path):
    """Pausar congela la alimentación; el consumidor persistente sigue vivo."""
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    a = _media_file(str(tmp_path), "a.mp4")
    items = [{"path": a, "source_duration": 60.0, "duration": 60.0}]
    eng = _engine(ffmpeg, items, str(tmp_path))
    eng.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if eng._pumps and eng._pumps[0]._offset > 0:
                break
            time.sleep(0.05)
        pump = eng._pumps[0]
        assert pump._offset > 0, "la bomba no alimentó"
        consumer = pump.consumer
        eng.pause_here(True)
        time.sleep(0.6)
        frozen = pump._offset
        time.sleep(0.4)
        assert pump._offset == frozen, "la pausa no congeló la alimentación"
        assert pump.consumer is consumer and consumer.poll() is None, \
            "la pausa mató al consumidor persistente"
        eng.pause_here(False)
        deadline = time.time() + 15
        while time.time() < deadline and pump._offset <= frozen:
            time.sleep(0.05)
        assert pump._offset > frozen, "no se reanudó la alimentación"
        assert pump.consumer is consumer, "la reanudación reinició el consumidor"
    finally:
        eng.stop()
        eng.wait(10000)


def test_consumer_reconnect_resumes_from_spool(tmp_path):
    """Si el consumidor muere (red), la bomba lo relanza y retoma el spool."""
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    a = _media_file(str(tmp_path), "a.mp4")
    items = [{"path": a, "source_duration": 120.0, "duration": 120.0}]
    eng = _engine(ffmpeg, items, str(tmp_path))
    logs = []
    from PySide6.QtCore import Qt
    eng.log.connect(logs.append, Qt.DirectConnection)
    eng.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if eng._pumps and eng._pumps[0]._offset > 0:
                break
            time.sleep(0.05)
        pump = eng._pumps[0]
        assert pump._offset > 0
        dead_consumer = pump.consumer
        dead_consumer.kill()          # simula la caída de la conexión
        deadline = time.time() + 20
        while time.time() < deadline:
            if pump.consumer is not dead_consumer and pump._offset > 0:
                break
            time.sleep(0.1)
        assert pump.consumer is not dead_consumer, "no se relanzó el consumidor"
        assert pump._offset > 0, "no se reanudó la alimentación tras reconectar"
        assert any("reconectando" in m for m in logs)
    finally:
        eng.stop()
        eng.wait(10000)


def test_output_manager_routes_to_continuous_engine(tmp_path):
    """MultiOutputManager usa el motor continuo cuando seamless_concat=True."""
    from app.output import MultiOutputManager
    from app.feed_engine import ContinuousOutputEngine
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    profiles = [{"name": "Canal RTMP", "protocol": "RTMP", "target": "rtmp://x/live", "enabled": True}]
    mgr = MultiOutputManager(ffmpeg, profiles, [{"path": "/media/a.mp4"}],
                             "1920x1080", "25", "CPU/x264", 4000)
    worker = mgr._make_worker(profiles[0])
    assert isinstance(worker, ContinuousOutputEngine)
    # legacy cuando seamless_concat=False
    mgr.common["seamless_concat"] = False
    worker2 = mgr._make_worker(profiles[0])
    assert type(worker2).__name__ == "BroadcastEngine"
    assert not isinstance(worker2, ContinuousOutputEngine)


def test_provider_survives_manager_start(tmp_path):
    """set_next_provider ANTES de start() debe llegar al motor continuo:
    start() recrea los workers, el manager debe reenviar el provider."""
    from app.output import MultiOutputManager
    from app.feed_engine import ContinuousOutputEngine
    ffmpeg, _slate = _make_fake_ffmpeg(str(tmp_path))
    profiles = [{"name": "Canal RTMP", "protocol": "RTMP", "target": "rtmp://x/live", "enabled": True}]
    mgr = MultiOutputManager(ffmpeg, profiles, [{"path": "/media/a.mp4"}],
                             "1920x1080", "25", "CPU/x264", 4000,
                             seamless_concat=True)
    calls = []
    mgr.set_next_provider(lambda idx: calls.append(idx) or None)
    try:
        mgr.start()
        assert mgr.workers, "no se creó ningún worker"
        engine = mgr.workers[0]
        assert isinstance(engine, ContinuousOutputEngine)
        assert engine._next_provider is not None, \
            "el provider se perdió al recrearse los workers en start()"
        engine._next_provider(0)          # debe ser el callable instalado
        assert calls == [0]
    finally:
        mgr.stop()
        for w in mgr.workers:
            w.wait(10000)
