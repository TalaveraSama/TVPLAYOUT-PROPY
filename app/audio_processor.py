"""Procesador de audio profesional para emisión broadcast y streaming.

Incluye normalización de sonoridad (EBU R128, ITU-R BS.1770, Streaming Web),
compresor dinámico, limitador True Peak, ecualizador broadcast, filtro pasa-altos
subsónico y realce de imagen estéreo.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger("nexora.audio")

# Presets profesionales de audio para televisión y streaming
AUDIO_PRESETS = {
    "off": {
        "name": "Desactivado (Directo)",
        "desc": "Pasa el audio sin procesamiento adicional, solo resampleo a 48 kHz estéreo.",
        "norm_mode": "off",
        "target_lufs": -23.0,
        "true_peak": -1.5,
        "lra": 7.0,
        "highpass": 0,
        "compressor": False,
        "comp_threshold": -18.0,
        "comp_ratio": 3.0,
        "comp_attack": 15.0,
        "comp_release": 200.0,
        "comp_makeup": 2.5,
        "equalizer": False,
        "eq_bass": 0.0,
        "eq_presence": 0.0,
        "eq_treble": 0.0,
        "stereo_enhance": False,
        "limiter": False,
        "gain_db": 0.0,
    },
    "ebu_r128": {
        "name": "EBU R128 Broadcast (-23 LUFS)",
        "desc": "Estándar internacional de televisión digital (EBU R128 / ITU-R BS.1770). Sonoridad integrada de -23 LUFS y límite True Peak de -1.5 dBTP.",
        "norm_mode": "loudnorm",
        "target_lufs": -23.0,
        "true_peak": -1.5,
        "lra": 7.0,
        "highpass": 35,
        "compressor": True,
        "comp_threshold": -20.0,
        "comp_ratio": 2.5,
        "comp_attack": 20.0,
        "comp_release": 250.0,
        "comp_makeup": 2.0,
        "equalizer": True,
        "eq_bass": 0.5,
        "eq_presence": 1.5,
        "eq_treble": 1.0,
        "stereo_enhance": False,
        "limiter": True,
        "gain_db": 0.0,
    },
    "streaming_web": {
        "name": "Streaming Web (-14 LUFS)",
        "desc": "Estándar moderno para YouTube Live, Twitch y Facebook (-14 LUFS, -1.0 dBTP). Gran presencia, pegada y claridad vocal.",
        "norm_mode": "loudnorm",
        "target_lufs": -14.0,
        "true_peak": -1.0,
        "lra": 9.0,
        "highpass": 40,
        "compressor": True,
        "comp_threshold": -16.0,
        "comp_ratio": 3.5,
        "comp_attack": 10.0,
        "comp_release": 150.0,
        "comp_makeup": 3.0,
        "equalizer": True,
        "eq_bass": 1.0,
        "eq_presence": 2.0,
        "eq_treble": 2.0,
        "stereo_enhance": True,
        "limiter": True,
        "gain_db": 0.0,
    },
    "dynaudnorm": {
        "name": "AGC Dinámico Multi-Ventana (DynAudNorm)",
        "desc": "Nivelación dinámica continua e inteligente. Iguala automáticamente diálogos bajos y películas sin bombeo de volumen.",
        "norm_mode": "dynaudnorm",
        "target_lufs": -20.0,
        "true_peak": -1.5,
        "lra": 7.0,
        "highpass": 35,
        "compressor": False,
        "comp_threshold": -18.0,
        "comp_ratio": 3.0,
        "comp_attack": 15.0,
        "comp_release": 200.0,
        "comp_makeup": 2.0,
        "equalizer": True,
        "eq_bass": 0.5,
        "eq_presence": 1.5,
        "eq_treble": 1.0,
        "stereo_enhance": False,
        "limiter": True,
        "gain_db": 0.0,
    },
    "broadcast_pro": {
        "name": "Procesador Master TV & Radio PRO",
        "desc": "Cadena completa broadcast: corte subsónico 35Hz + ecualizador de 3 bandas + compresor multibanda + normalizador + limitador True Peak.",
        "norm_mode": "loudnorm",
        "target_lufs": -22.0,
        "true_peak": -1.0,
        "lra": 8.0,
        "highpass": 35,
        "compressor": True,
        "comp_threshold": -18.0,
        "comp_ratio": 3.0,
        "comp_attack": 15.0,
        "comp_release": 200.0,
        "comp_makeup": 2.5,
        "equalizer": True,
        "eq_bass": 1.2,
        "eq_presence": 2.2,
        "eq_treble": 2.0,
        "stereo_enhance": True,
        "limiter": True,
        "gain_db": 0.0,
    },
    "radio_fm": {
        "name": "Estilo Radio FM / Música",
        "desc": "Optimizado para canales musicales y radios: realce estéreo, compresión densa y ecualización con pegada.",
        "norm_mode": "dynaudnorm",
        "target_lufs": -16.0,
        "true_peak": -0.8,
        "lra": 6.0,
        "highpass": 45,
        "compressor": True,
        "comp_threshold": -15.0,
        "comp_ratio": 4.0,
        "comp_attack": 8.0,
        "comp_release": 120.0,
        "comp_makeup": 3.5,
        "equalizer": True,
        "eq_bass": 2.0,
        "eq_presence": 2.0,
        "eq_treble": 2.5,
        "stereo_enhance": True,
        "limiter": True,
        "gain_db": 0.0,
    },
}


def build_audio_filters(config: Dict[str, Any] | None = None) -> str:
    """Construye la cadena de filtros de audio FFmpeg (-af) según los ajustes configurados."""
    if not config or not config.get("audio_proc_enabled", False):
        return "aresample=async=1:first_pts=0"

    filters = []

    # 1. Filtro pasa-altos subsónico (elimina ruidos por debajo de 35Hz/50Hz)
    hp = int(config.get("audio_proc_highpass", 0) or 0)
    if hp > 0:
        filters.append(f"highpass=f={hp}")

    # 2. Ecualizador paramétrico de 3 bandas (graves, presencia vocal, brillo)
    if config.get("audio_proc_equalizer", False):
        bass = float(config.get("audio_proc_eq_bass", 0.0) or 0.0)
        presence = float(config.get("audio_proc_eq_presence", 0.0) or 0.0)
        treble = float(config.get("audio_proc_eq_treble", 0.0) or 0.0)
        if abs(bass) > 0.1:
            filters.append(f"equalizer=f=120:t=q:w=1.0:g={bass:.1f}")
        if abs(presence) > 0.1:
            filters.append(f"equalizer=f=3200:t=q:w=1.2:g={presence:.1f}")
        if abs(treble) > 0.1:
            filters.append(f"equalizer=f=12000:t=q:w=0.8:g={treble:.1f}")

    # 3. Compresor dinámico broadcast
    if config.get("audio_proc_compressor", False):
        thresh = float(config.get("audio_proc_comp_threshold", -18.0) or -18.0)
        ratio = float(config.get("audio_proc_comp_ratio", 3.0) or 3.0)
        attack = float(config.get("audio_proc_comp_attack", 15.0) or 15.0)
        release = float(config.get("audio_proc_comp_release", 200.0) or 200.0)
        makeup = float(config.get("audio_proc_comp_makeup", 2.0) or 2.0)
        filters.append(
            f"acompressor=threshold={thresh:.1f}dB:ratio={ratio:.1f}:attack={attack:.1f}:release={release:.1f}:makeup={makeup:.1f}dB"
        )

    # 4. Modo de normalización de sonoridad
    norm_mode = str(config.get("audio_proc_norm_mode", "off") or "off").lower()
    if norm_mode == "loudnorm":
        target = float(config.get("audio_proc_target_lufs", -23.0) or -23.0)
        tp = float(config.get("audio_proc_true_peak", -1.5) or -1.5)
        lra = float(config.get("audio_proc_lra", 7.0) or 7.0)
        filters.append(f"loudnorm=I={target:.1f}:TP={tp:.1f}:LRA={lra:.1f}:dual_mono=true")
    elif norm_mode == "dynaudnorm":
        filters.append("dynaudnorm=f=150:g=15:p=0.95:m=10.0:r=0.9:b=1")

    # 5. Realce de imagen estéreo
    if config.get("audio_proc_stereo_enhance", False):
        filters.append("extrastereo=m=1.15")

    # 6. Limitador True Peak de seguridad (evita distorsión digital)
    if config.get("audio_proc_limiter", False):
        tp = float(config.get("audio_proc_true_peak", -1.0) or -1.0)
        filters.append(f"alimiter=limit={tp:.1f}dB:attack=5:release=50:asc=1")

    # 7. Ganancia master manual (si es distinta de 0 dB)
    gain = float(config.get("audio_proc_gain_db", 0.0) or 0.0)
    if abs(gain) > 0.1:
        filters.append(f"volume={gain:+.1f}dB")

    # 8. Resampleo final estable
    filters.append("aresample=async=1:first_pts=0")

    return ",".join(filters)
