"""Pruebas unitarias y de integración para el Procesador de Audio Profesional y Titulación Musical en Vivo."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.audio_processor import AUDIO_PRESETS, build_audio_filters
from app.music_titling import (
    build_music_enable_expression,
    build_music_overlay,
    clean_music_title,
    extract_local_tags,
    identify_music_track,
    is_music_overlay_visible,
    parse_filename_music_info,
    render_music_overlay,
)


def test_audio_processor_disabled():
    """Cuando está desactivado, solo debe devolver el resampleo básico."""
    assert build_audio_filters({}) == "aresample=async=1:first_pts=0"
    assert build_audio_filters({"audio_proc_enabled": False}) == "aresample=async=1:first_pts=0"


def test_audio_processor_presets():
    """Verifica que los presets profesionales generen los filtros correctos."""
    # EBU R128
    ebu_cfg = dict(AUDIO_PRESETS["ebu_r128"])
    ebu_cfg["audio_proc_enabled"] = True
    ebu_cfg["audio_proc_norm_mode"] = ebu_cfg.get("norm_mode")
    ebu_cfg["audio_proc_target_lufs"] = ebu_cfg.get("target_lufs")
    ebu_cfg["audio_proc_true_peak"] = ebu_cfg.get("true_peak")
    ebu_cfg["audio_proc_lra"] = ebu_cfg.get("lra")
    ebu_cfg["audio_proc_highpass"] = ebu_cfg.get("highpass")
    ebu_cfg["audio_proc_compressor"] = ebu_cfg.get("compressor")
    ebu_cfg["audio_proc_equalizer"] = ebu_cfg.get("equalizer")
    ebu_cfg["audio_proc_limiter"] = ebu_cfg.get("limiter")
    filters = build_audio_filters(ebu_cfg)
    assert "highpass=f=35" in filters
    assert "loudnorm=I=-23.0:TP=-1.5:LRA=7.0:dual_mono=true" in filters
    assert "acompressor=" in filters
    assert "alimiter=" in filters
    assert "aresample=async=1:first_pts=0" in filters

    # Streaming Web (-14 LUFS)
    web_cfg = {
        "audio_proc_enabled": True,
        "audio_proc_norm_mode": "loudnorm",
        "audio_proc_target_lufs": -14.0,
        "audio_proc_true_peak": -1.0,
        "audio_proc_lra": 9.0,
        "audio_proc_highpass": 40,
        "audio_proc_stereo_enhance": True,
        "audio_proc_gain_db": 1.5,
    }
    web_filters = build_audio_filters(web_cfg)
    assert "loudnorm=I=-14.0:TP=-1.0:LRA=9.0:dual_mono=true" in web_filters
    assert "highpass=f=40" in web_filters
    assert "extrastereo=m=1.15" in web_filters
    assert "volume=+1.5dB" in web_filters

    # DynAudNorm AGC
    dyn_cfg = {
        "audio_proc_enabled": True,
        "audio_proc_norm_mode": "dynaudnorm",
        "audio_proc_highpass": 35,
    }
    dyn_filters = build_audio_filters(dyn_cfg)
    assert "dynaudnorm=f=150:g=15:p=0.95:m=10.0:r=0.9:b=1" in dyn_filters


def test_clean_music_title():
    """Comprueba la limpieza de etiquetas en nombres de archivo de música."""
    assert clean_music_title("Dua Lipa - Levitating (Official Music Video)") == "Dua Lipa - Levitating"
    assert clean_music_title("The Weeknd - Blinding Lights [Official Audio]") == "The Weeknd - Blinding Lights"
    assert clean_music_title("Miley Cyrus - Flowers (Video Oficial) [1080p].mp4") == "Miley Cyrus - Flowers"
    assert clean_music_title("Coldplay - Yellow (Remastered 4K).mkv") == "Coldplay - Yellow"


def test_parse_filename_music_info():
    """Comprueba la extracción de artista y título a partir del nombre de archivo."""
    info = parse_filename_music_info("/media/music/Dua Lipa - Levitating (Official Video).mp4")
    assert info["artist"] == "Dua Lipa"
    assert info["title"] == "Levitating"

    info2 = parse_filename_music_info("Queen — Bohemian Rhapsody.mp4")
    assert info2["artist"] == "Queen"
    assert info2["title"] == "Bohemian Rhapsody"

    info3 = parse_filename_music_info("SingleTitleSong.mkv")
    assert info3["title"] == "SingleTitleSong"
    assert info3["artist"] == ""


def test_music_timing_rules():
    """Verifica la visibilidad del zócalo musical tras 30s y en los últimos 10s."""
    duration = 200.0  # Canción de 3 minutos y 20 segundos

    # 1. Antes de los 30s: No debe ser visible
    assert not is_music_overlay_visible(0.0, duration)
    assert not is_music_overlay_visible(15.0, duration)
    assert not is_music_overlay_visible(29.9, duration)

    # 2. Entrada: Visible de 30.0s a 42.0s (30s tras inicio + 12s duración)
    assert is_music_overlay_visible(30.0, duration)
    assert is_music_overlay_visible(35.0, duration)
    assert is_music_overlay_visible(41.9, duration)

    # 3. Durante el cuerpo de la canción: No debe ser visible
    assert not is_music_overlay_visible(42.1, duration)
    assert not is_music_overlay_visible(100.0, duration)
    assert not is_music_overlay_visible(189.0, duration)

    # 4. Salida: Visible en los últimos 10 segundos (de 190.0s a 200.0s)
    assert is_music_overlay_visible(190.0, duration)
    assert is_music_overlay_visible(195.0, duration)
    assert is_music_overlay_visible(199.9, duration)


def test_build_music_enable_expression():
    """Verifica la expresión de FFmpeg generada para habilitar el zócalo musical."""
    duration = 180.0
    expr = build_music_enable_expression(0.0, duration, intro_start=30.0, intro_duration=12.0, outro_duration=10.0)
    assert "between(t,30.000,42.000)" in expr
    assert "between(t,170.000,180.000)" in expr

    # Con offset (ej. reanudación en el segundo 35)
    expr_offset = build_music_enable_expression(35.0, duration, intro_start=30.0, intro_duration=12.0, outro_duration=10.0)
    assert "between(t,0.000,7.000)" in expr_offset
    assert "between(t,135.000,145.000)" in expr_offset


def test_render_and_build_music_overlay():
    """Comprueba el renderizado del zócalo musical en imagen QImage y guardado en archivo PNG."""
    from PySide6.QtGui import QImage

    meta = {
        "artist": "ROSALÍA",
        "title": "DESPECHÁ",
        "album": "MOTOMAMI+",
        "year": "2022",
        "label": "Columbia Records",
    }
    img = render_music_overlay(meta, resolution=(1920, 1080), style_config={"style": "glass"})
    assert isinstance(img, QImage)
    assert not img.isNull()
    assert img.width() == 1920
    assert img.height() == 1080

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "test_music_overlay.png"
        ok = build_music_overlay(meta, (1280, 720), out_path)
        assert ok
        assert out_path.is_file()
        assert out_path.stat().st_size > 500


def test_output_worker_audio_and_music_overlays():
    """Verifica que OutputWorker integre filtros de audio y zócalos musicales."""
    from app.output import OutputWorker

    with tempfile.NamedTemporaryFile(suffix=".png") as tmp_logo, \
         tempfile.NamedTemporaryFile(suffix=".png") as tmp_music, \
         tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video:
        
        tmp_logo.write(b"x")
        tmp_logo.flush()
        tmp_music.write(b"x")
        tmp_music.flush()
        tmp_video.write(b"x")
        tmp_video.flush()

        item = {
            "path": tmp_video.name,
            "title": "Cancion Test",
            "category": "Música",
            "duration": 180.0,
            "source_duration": 180.0,
        }

        audio_cfg = {
            "audio_proc_enabled": True,
            "audio_proc_norm_mode": "loudnorm",
            "audio_proc_target_lufs": -23.0,
            "audio_proc_highpass": 35,
        }

        worker = OutputWorker(
            ffmpeg=sys.executable,
            items=[item],
            url="rtmp://localhost/live",
            resolution="1920x1080",
            fps="29.97",
            encoder="CPU/x264",
            bitrate=4000,
            audio_processor_config=audio_cfg,
            music_overlay=tmp_music.name,
            music_intro_start=30.0,
            music_intro_duration=12.0,
            music_outro_duration=10.0,
        )

        cmd, _label, _aid, _sid = worker._build_command(item, offset=0.0)
        cmd_str = " ".join(cmd)

        # Audio filter profesional
        assert "highpass=f=35" in cmd_str
        assert "loudnorm=I=-23.0" in cmd_str
        assert "aresample=async=1:first_pts=0" in cmd_str

        # Overlay musical de entrada a los 30s y salida a los últimos 10s
        assert "between(t,30.000,42.000)" in cmd_str
        assert "between(t,170.000,180.000)" in cmd_str
        assert "format=yuv420p" in cmd_str


def test_output_worker_live_stream_inputs():
    """Verifica que OutputWorker maneje entradas en vivo por RTMP, SRT y HLS/M3U8 con reconexión."""
    from app.output import OutputWorker

    live_item = {
        "path": "https://stream.server.com/live/channel.m3u8",
        "title": "Transmisión Secular en Vivo",
        "category": "En Vivo",
        "duration": 3600.0,
        "source_duration": 3600.0,
    }

    worker = OutputWorker(
        ffmpeg=sys.executable,
        items=[live_item],
        url="rtmp://localhost/live",
        resolution="1920x1080",
        fps="29.97",
        encoder="CPU/x264",
        bitrate=4000,
    )

    cmd, _label, _aid, _sid = worker._build_command(live_item, offset=0.0)
    cmd_str = " ".join(cmd)

    # Entradas HTTP/M3U8 no deben llevar -re y sí flags de reconexión
    assert "-reconnect 1" in cmd_str
    assert "-reconnect_at_eof 1" in cmd_str
    assert "https://stream.server.com/live/channel.m3u8" in cmd_str


def test_live_stream_dialog_and_wiring():
    """Comprueba el diálogo de inserción de transmisiones en vivo y su integración."""
    with open(REPO / "app" / "dialogs.py", encoding="utf-8") as f:
        dialogs_src = f.read()
    with open(REPO / "app" / "main_window.py", encoding="utf-8") as f:
        main_src = f.read()

    assert "class LiveStreamDialog(QDialog):" in dialogs_src
    assert "LiveStreamDialog" in main_src
    assert "insert_live_stream" in main_src
    assert "Stream en Vivo…" in main_src

