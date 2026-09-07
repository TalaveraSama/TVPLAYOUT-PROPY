"""Análisis de medios con ffprobe/ffmpeg: duración, resolución, fps, códecs, pistas y miniaturas."""
import hashlib
import json
import os
import subprocess

from PySide6.QtCore import QThread, Signal

from .config import FFMPEG_PATH, FFPROBE_PATH, THUMB_DIR, LANG_PRIORITY, SUB_PRIORITY

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _fraction(text):
    try:
        if "/" in str(text):
            a, b = str(text).split("/", 1)
            a, b = float(a), float(b)
            return a / b if b else 0.0
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_file(path, ffprobe=None, timeout=25):
    """Devuelve dict con duration,width,height,fps,video_codec,audio_codec,tracks o lanza excepción."""
    ffprobe = ffprobe or FFPROBE_PATH
    if not ffprobe:
        raise RuntimeError("ffprobe no encontrado")
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "ffprobe error").strip()[:300])
    data = json.loads(p.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "video_codec": "", "audio_codec": "", "tracks": []}
    try:
        info["duration"] = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        pass
    a_idx = s_idx = 0
    for s in streams:
        kind = s.get("codec_type")
        tags = s.get("tags", {}) or {}
        if kind == "video" and not info["video_codec"]:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            info["width"] = int(s.get("width") or 0)
            info["height"] = int(s.get("height") or 0)
            info["fps"] = round(_fraction(s.get("avg_frame_rate") or s.get("r_frame_rate") or 0), 3)
            info["video_codec"] = s.get("codec_name", "")
            if not info["duration"]:
                info["duration"] = float(s.get("duration") or 0)
        elif kind == "audio":
            if not info["audio_codec"]:
                info["audio_codec"] = s.get("codec_name", "")
            info["tracks"].append({"type": "a", "idx": a_idx, "lang": tags.get("language", ""),
                                   "title": tags.get("title", ""), "codec": s.get("codec_name", ""),
                                   "channels": s.get("channels", 0)})
            a_idx += 1
        elif kind == "subtitle":
            info["tracks"].append({"type": "s", "idx": s_idx, "lang": tags.get("language", ""),
                                   "title": tags.get("title", ""), "codec": s.get("codec_name", "")})
            s_idx += 1
    return info


def thumb_path_for(path):
    h = hashlib.sha1(str(path).encode("utf-8", "replace")).hexdigest()[:20]
    return THUMB_DIR / f"{h}.jpg"


def make_thumbnail(path, duration=0.0, ffmpeg=None, timeout=30):
    """Genera miniatura JPG (160x90) del clip. Devuelve la ruta o ''."""
    ffmpeg = ffmpeg or FFMPEG_PATH
    if not ffmpeg:
        return ""
    out = thumb_path_for(path)
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    pos = 0
    if duration and duration > 20:
        pos = min(duration * 0.12, 600)
    elif duration and duration > 2:
        pos = duration / 3
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{pos:.2f}", "-i", str(path),
           "-frames:v", "1", "-vf", "scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2",
           "-q:v", "4", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except Exception:
        return ""
    return str(out) if out.is_file() and out.stat().st_size > 0 else ""


def pick_track(tracks, kind, preference, priority):
    """Elige índice de pista (0-based por tipo) según preferencia; None = default/ninguna."""
    cands = [t for t in (tracks or []) if t.get("type") == kind]
    if not cands:
        return None
    pref = (preference or "").strip()
    if pref.upper() == "OFF":
        return -1
    if pref.lower() == "original":
        return None
    wanted = priority if pref.upper().startswith("AUTO") else [pref] + priority

    def norm(x):
        return (x or "").lower().replace("_", "-")

    for w in wanted:
        w = norm(w)
        if w.startswith("#") and w[1:].isdigit():          # selección explícita por índice
            n = int(w[1:])
            if any(t["idx"] == n for t in cands):
                return n
            continue
        for t in cands:
            lang = norm(t.get("lang"))
            title = norm(t.get("title"))
            if lang == w or (len(w) > 2 and w in title) or (w in ("es", "spa") and lang in ("es", "spa", "esp", "es-mx", "es-419", "spa-mx")):
                return t["idx"]
    return None


def pick_audio(tracks, preference):
    return pick_track(tracks, "a", preference, LANG_PRIORITY)


def pick_subtitle(tracks, preference):
    return pick_track(tracks, "s", preference, SUB_PRIORITY)


class ProbeWorker(QThread):
    """Analiza en segundo plano los medios sin metadatos."""
    progress = Signal(int, int)        # hechos, pendientes
    updated = Signal(str)              # path actualizado
    finished_all = Signal(int)         # total analizados

    def __init__(self, db, make_thumbs=True, batch=100):
        super().__init__()
        self.db = db
        self.make_thumbs = make_thumbs
        self.batch = batch
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def run(self):
        done = 0
        if not FFPROBE_PATH:
            self.finished_all.emit(0)
            return
        while not self.stop_requested:
            rows = self.db.unprobed_media(self.batch)
            if not rows:
                break
            for r in rows:
                if self.stop_requested:
                    break
                path = r["path"]
                if not os.path.isfile(path):
                    self.db.update_media_meta(path, probe_error="no existe")
                    continue
                try:
                    info = probe_file(path)
                    thumb = make_thumbnail(path, info["duration"]) if self.make_thumbs else ""
                    self.db.update_media_meta(path, duration=info["duration"], width=info["width"], height=info["height"],
                                              fps=info["fps"], video_codec=info["video_codec"], audio_codec=info["audio_codec"],
                                              tracks=info["tracks"], thumb=thumb, metadata_ok=1, probe_error="")
                    self.updated.emit(path)
                except Exception as e:  # noqa: BLE001
                    self.db.update_media_meta(path, probe_error=str(e)[:200] or "error")
                done += 1
                if done % 5 == 0:
                    total, probed, failed = self.db.media_stats()
                    self.progress.emit(done, max(0, total - probed - failed))
        self.finished_all.emit(done)
