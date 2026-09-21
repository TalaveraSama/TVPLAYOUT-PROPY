"""Identificación y titulación gráfica en vivo para videos musicales (Lower-Third / Zócalo).

Soporta reconocimiento automático mediante:
  1. AudD Music Recognition API (https://audd.io)
  2. AcoustID & Chromaprint / MusicBrainz (https://acoustid.org)
  3. ACRCloud Broadcast API (https://acrcloud.com)
  4. Extracción inteligente de metadatos locales (ID3 / ffprobe / Heurística de nombre de archivo)

Reglas de tiempo de emisión al aire:
  - Entrada: Aparece después de 30 segundos de iniciada la canción (configurable, ~12s de duración).
  - Salida: Aparece en los últimos 10 segundos de la canción hasta finalizar el clip.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QCoreApplication, QObject, QRect, QRectF, QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from .config import CACHE_DIR, FFMPEG_PATH, FFPROBE_PATH

log = logging.getLogger("nexora.music")

MUSIC_CACHE = CACHE_DIR / "music_titling"
MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

_qt_app = None


def _ensure_app():
    global _qt_app
    if QGuiApplication.instance() is None and QCoreApplication.instance() is None:
        try:
            _qt_app = QGuiApplication([])
        except Exception:
            _qt_app = QCoreApplication([])

# Limpieza de sufijos y etiquetas típicas en títulos de videos musicales
_MUSIC_TAG_PATTERNS = [
    re.compile(r"[\(\[\{][^\)\]\}]*(?:official|video\s*oficial|audio\s*oficial|visualizer|lyric|remaster|hd|4k|1080p|720p|explicit|clean|live|en\s*vivo|videoclip)[^\)\]\}]*[\)\]\}]", re.IGNORECASE),
    re.compile(r"(?:official\s*(?:music\s*)?video|video\s*oficial|official\s*audio|visualizer|lyric\s*video)[\s\.]*$", re.IGNORECASE),
    re.compile(r"\.(?:mp4|mkv|mov|avi|ts|m4v|webm|mpg|mpeg|mp3|flac|wav|m4a|aac)$", re.IGNORECASE),
]


def clean_music_title(raw_text: str) -> str:
    """Limpia etiquetas promocionales o técnicas de un título musical."""
    text = str(raw_text or "").strip()
    for pat in _MUSIC_TAG_PATTERNS:
        text = pat.sub("", text)
    # Limpiar espacios y guiones sobrantes
    text = re.sub(r"\s+", " ", text).strip(" -_")
    return text


def parse_filename_music_info(raw_name: str) -> Dict[str, str]:
    """Extrae artista, título y posibles colaboradores del nombre de archivo."""
    stem = Path(raw_name).stem
    cleaned = clean_music_title(stem)

    # Patrón común: "Artista - Canción" o "Artista — Canción" o "Artista ~ Canción"
    parts = re.split(r"\s*[-–—~]\s*", cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artist = parts[0].strip()
        title = parts[1].strip()
    else:
        artist = ""
        title = cleaned or stem

    return {
        "artist": artist,
        "title": title,
        "album": "",
        "year": "",
        "genre": "",
        "label": "",
        "source": "local_filename",
    }


def extract_local_tags(path: str) -> Dict[str, str]:
    """Extrae etiquetas ID3 / Vorbis / MP4 / ffprobe de metadatos integrados en el archivo."""
    info = parse_filename_music_info(path)
    ffprobe = FFPROBE_PATH or "ffprobe"
    if not os.path.isfile(path):
        return info

    try:
        cmd = [
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ]
        out = subprocess.check_output(cmd, timeout=8, stderr=subprocess.DEVNULL)
        data = json.loads(out.decode("utf-8", "replace"))
        fmt_tags = (data.get("format") or {}).get("tags") or {}

        # Normalizar claves a minúsculas
        tags = {k.lower(): str(v) for k, v in fmt_tags.items()}

        artist = tags.get("artist") or tags.get("album_artist") or tags.get("author") or tags.get("performer") or ""
        title = tags.get("title") or tags.get("track") or ""
        album = tags.get("album") or ""
        year = tags.get("date") or tags.get("year") or tags.get("creation_time") or ""
        genre = tags.get("genre") or ""
        label = tags.get("publisher") or tags.get("copyright") or tags.get("label") or ""

        if year and len(year) >= 4:
            m = re.search(r"\b(19\d{2}|20\d{2})\b", year)
            if m:
                year = m.group(1)

        if artist:
            info["artist"] = clean_music_title(artist)
        if title:
            info["title"] = clean_music_title(title)
        if album:
            info["album"] = clean_music_title(album)
        if year:
            info["year"] = year
        if genre:
            info["genre"] = genre
        if label:
            info["label"] = label
        info["source"] = "local_tags" if (artist or title) else info["source"]
    except Exception as exc:
        log.debug("extract_local_tags %s: %s", path, exc)

    return info


def recognize_audd(audio_path: str, api_token: str) -> Optional[Dict[str, str]]:
    """Consulta la API de AudD Music Recognition con una muestra de audio."""
    if not api_token or not os.path.isfile(audio_path):
        return None

    try:
        # Extraer muestra de 15 segundos en MP3 ligero a /tmp
        sample_path = str(MUSIC_CACHE / f"sample_{hashlib.md5(audio_path.encode()).hexdigest()[:10]}.mp3")
        ffmpeg = FFMPEG_PATH or "ffmpeg"
        subprocess.run(
            [ffmpeg, "-y", "-ss", "10", "-t", "15", "-i", audio_path, "-ac", "1", "-ar", "22050", "-b:a", "64k", sample_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )

        with open(sample_path, "rb") as f:
            audio_data = f.read()

        boundary = "----WebKitFormBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()
        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"api_token\"\r\n\r\n{api_token}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sample.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode())
        body.extend(audio_data)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            "https://api.audd.io/",
            data=bytes(body),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Nexora-Air-Playout/25",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))

        result = data.get("result")
        if result and isinstance(result, dict):
            return {
                "artist": clean_music_title(result.get("artist") or ""),
                "title": clean_music_title(result.get("title") or ""),
                "album": clean_music_title(result.get("album") or ""),
                "year": str(result.get("release_date") or "")[:4],
                "label": str(result.get("label") or ""),
                "source": "audd_api",
            }
    except Exception as exc:
        log.warning("AudD recognition falló para %s: %s", audio_path, exc)
    return None


def recognize_acoustid(audio_path: str, client_key: str) -> Optional[Dict[str, str]]:
    """Consulta la API de AcoustID / Chromaprint."""
    if not client_key or not os.path.isfile(audio_path):
        return None

    try:
        # Intentar fpcalc si está en el sistema
        cmd = ["fpcalc", "-json", audio_path]
        out = subprocess.check_output(cmd, timeout=10, stderr=subprocess.DEVNULL)
        data = json.loads(out.decode("utf-8", "replace"))
        duration = int(data.get("duration", 0))
        fingerprint = data.get("fingerprint", "")

        if not fingerprint:
            return None

        url = (
            f"https://api.acoustid.org/v2/lookup?client={urllib.parse.quote(client_key)}"
            f"&meta=recordings+releasegroups+compress&duration={duration}&fingerprint={urllib.parse.quote(fingerprint)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Nexora-Air-Playout/25"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8", "replace"))

        results = res_data.get("results") or []
        for r in results:
            recordings = r.get("recordings") or []
            if recordings:
                rec = recordings[0]
                artists = rec.get("artists") or []
                artist = artists[0].get("name") if artists else ""
                title = rec.get("title") or ""
                release_groups = rec.get("releasegroups") or []
                album = release_groups[0].get("title") if release_groups else ""
                return {
                    "artist": clean_music_title(artist),
                    "title": clean_music_title(title),
                    "album": clean_music_title(album),
                    "year": "",
                    "label": "",
                    "source": "acoustid",
                }
    except Exception as exc:
        log.warning("AcoustID falló para %s: %s", audio_path, exc)
    return None


def recognize_acrcloud(audio_path: str, host: str, key: str, secret: str) -> Optional[Dict[str, str]]:
    """Consulta la API de reconocimiento de ACRCloud."""
    if not host or not key or not secret or not os.path.isfile(audio_path):
        return None

    try:
        sample_path = str(MUSIC_CACHE / f"acr_{hashlib.md5(audio_path.encode()).hexdigest()[:10]}.wav")
        ffmpeg = FFMPEG_PATH or "ffmpeg"
        subprocess.run(
            [ffmpeg, "-y", "-ss", "10", "-t", "12", "-i", audio_path, "-ac", "1", "-ar", "8000", sample_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )

        with open(sample_path, "rb") as f:
            sample_bytes = f.read()

        http_method = "POST"
        http_uri = "/v1/identify"
        data_type = "audio"
        signature_version = "1"
        timestamp = str(int(time.time()))

        string_to_sign = f"{http_method}\n{http_uri}\n{key}\n{data_type}\n{signature_version}\n{timestamp}"
        sign = base64.b64encode(
            hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha1).digest()
        ).decode("utf-8")

        boundary = "----WebKitFormBoundary" + hashlib.md5(timestamp.encode()).hexdigest()
        body = bytearray()
        fields = {
            "access_key": key,
            "sample_bytes": str(len(sample_bytes)),
            "timestamp": timestamp,
            "signature": sign,
            "data_type": data_type,
            "signature_version": signature_version,
        }
        for k, v in fields.items():
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"sample\"; filename=\"sample.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
        body.extend(sample_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        url = f"https://{host}{http_uri}" if not host.startswith("http") else f"{host}{http_uri}"
        req = urllib.request.Request(url, data=bytes(body), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Nexora-Air-Playout/25",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))

        music = (data.get("metadata") or {}).get("music") or []
        if music:
            m = music[0]
            artists = m.get("artists") or []
            artist = artists[0].get("name") if artists else ""
            title = m.get("title") or ""
            album = (m.get("album") or {}).get("name") or ""
            year = str(m.get("release_date") or "")[:4]
            label = str(m.get("label") or "")
            return {
                "artist": clean_music_title(artist),
                "title": clean_music_title(title),
                "album": clean_music_title(album),
                "year": year,
                "label": label,
                "source": "acrcloud",
            }
    except Exception as exc:
        log.warning("ACRCloud falló para %s: %s", audio_path, exc)
    return None


def identify_music_track(path: str, settings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Identifica un video musical usando la mejor fuente configurada o metadatos locales."""
    settings = settings or {}
    service = str(settings.get("music_titling_service", "auto") or "auto").lower()

    # Comprobar caché local de identificación
    cache_key = hashlib.sha256(path.encode("utf-8")).hexdigest()
    cache_file = MUSIC_CACHE / f"track_{cache_key}.json"
    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("title") or cached.get("artist"):
                return cached
        except Exception:
            pass

    meta = None

    # Intentar servicios en línea si están configurados
    if service in {"auto", "audd"}:
        token = str(settings.get("music_audd_api_token", "")).strip()
        if token:
            meta = recognize_audd(path, token)

    if not meta and service in {"auto", "acoustid"}:
        key = str(settings.get("music_acoustid_api_key", "")).strip()
        if key:
            meta = recognize_acoustid(path, key)

    if not meta and service in {"auto", "acrcloud"}:
        host = str(settings.get("music_acrcloud_host", "")).strip()
        k = str(settings.get("music_acrcloud_key", "")).strip()
        s = str(settings.get("music_acrcloud_secret", "")).strip()
        if host and k and s:
            meta = recognize_acrcloud(path, host, k, s)

    # Si los servicios fallan o no hay conexión, extraer etiquetas y nombre
    if not meta or not meta.get("title"):
        meta = extract_local_tags(path)

    # Si el título está vacío, usar el nombre base
    if not meta.get("title"):
        meta["title"] = Path(path).stem

    # Guardar en caché
    try:
        cache_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    return meta


# ============================================================================
# Renderizado de Zócalo / Lower-Third Gráfico de Música
# ============================================================================

def _parse_res(resolution: Any) -> Tuple[int, int]:
    if isinstance(resolution, (tuple, list)) and len(resolution) == 2:
        return int(resolution[0]), int(resolution[1])
    try:
        w, h = str(resolution).lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def render_music_overlay(track_meta: Dict[str, str], resolution: Any = (1920, 1080),
                         style_config: Optional[Dict[str, Any]] = None) -> QImage:
    """Renderiza el zócalo musical (Lower-Third broadcast) en una imagen QImage con transparencia."""
    _ensure_app()
    w, h = _parse_res(resolution)
    canvas = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)

    artist = str(track_meta.get("artist") or "").strip()
    title = str(track_meta.get("title") or "").strip()
    album = str(track_meta.get("album") or "").strip()
    year = str(track_meta.get("year") or "").strip()
    label = str(track_meta.get("label") or "").strip()

    if not title and not artist:
        return canvas

    cfg = style_config or {}
    style = str(cfg.get("style") or "glass").lower()
    position = str(cfg.get("position") or "inferior-izquierda").lower()
    opacity = max(10, min(100, int(cfg.get("opacity", 90) or 90))) / 100.0
    scale = max(50, min(200, int(cfg.get("text_scale", 100) or 100))) / 100.0
    accent_hex = str(cfg.get("accent_color") or "#00e5ff")

    # Geometría del zócalo proporcional a la resolución (base 1080p)
    factor = h / 1080.0
    card_w = int(min(w * 0.52, 780 * factor * scale))
    card_h = int(140 * factor * scale)
    margin_x = int(64 * factor)
    margin_y = int(64 * factor)

    if position == "inferior-derecha":
        box_x = w - card_w - margin_x
        box_y = h - card_h - margin_y
    elif position == "superior-izquierda":
        box_x = margin_x
        box_y = margin_y
    elif position == "inferior-completo":
        card_w = w - (margin_x * 2)
        box_x = margin_x
        box_y = h - card_h - margin_y
    else:  # inferior-izquierda (predeterminado estilo MTV)
        box_x = margin_x
        box_y = h - card_h - margin_y

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    rect = QRectF(box_x, box_y, card_w, card_h)

    # 1. Fondo de la tarjeta según estilo
    radius = 16.0 * factor if "compact" not in style else 4.0
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    if style == "neon":
        bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg_grad.setColorAt(0.0, QColor(10, 15, 30, int(230 * opacity)))
        bg_grad.setColorAt(1.0, QColor(25, 10, 40, int(240 * opacity)))
        p.fillPath(path, QBrush(bg_grad))
        p.setPen(QPen(QColor(accent_hex), 2.5 * factor))
        p.drawPath(path)
    elif style == "classic_mtv":
        p.fillRect(rect, QColor(0, 0, 0, int(240 * opacity)))
        # Borde izquierdo grueso de color
        bar_w = 12 * factor
        p.fillRect(QRectF(box_x, box_y, bar_w, card_h), QColor(accent_hex))
    elif style == "compact":
        p.fillRect(rect, QColor(15, 15, 15, int(210 * opacity)))
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.0))
        p.drawPath(path)
    else:  # Modern Glass (predeterminado)
        bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg_grad.setColorAt(0.0, QColor(20, 24, 35, int(225 * opacity)))
        bg_grad.setColorAt(1.0, QColor(12, 14, 22, int(240 * opacity)))
        p.fillPath(path, QBrush(bg_grad))
        # Borde sutil traslúcido
        p.setPen(QPen(QColor(255, 255, 255, int(70 * opacity)), 1.5 * factor))
        p.drawPath(path)

    # 2. Icono / Barra de ecualizador gráfico musical a la izquierda
    badge_w = int(72 * factor * scale)
    badge_rect = QRectF(box_x + (16 * factor), box_y + (16 * factor), badge_w, card_h - (32 * factor))
    badge_path = QPainterPath()
    badge_path.addRoundedRect(badge_rect, 10.0 * factor, 10.0 * factor)
    
    # Fondo del badge
    badge_grad = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
    badge_grad.setColorAt(0.0, QColor(accent_hex).lighter(120))
    badge_grad.setColorAt(1.0, QColor(accent_hex).darker(150))
    p.fillPath(badge_path, QBrush(badge_grad))

    # Dibujar barras de ecualizador simuladas dentro del badge
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 230))
    bar_spacing = badge_w / 5.0
    bar_heights = [0.45, 0.85, 0.65, 0.95]
    for i, bh in enumerate(bar_heights):
        bx = badge_rect.left() + (i + 1) * bar_spacing - (3 * factor)
        bw = max(3.0 * factor, 4.0 * factor)
        total_h = badge_rect.height() - (16 * factor)
        by = badge_rect.bottom() - (8 * factor) - (total_h * bh)
        p.drawRoundedRect(QRectF(bx, by, bw, total_h * bh), 2.0, 2.0)

    # 3. Textos (Canción, Artista, Álbum/Año)
    text_x = box_x + badge_w + (32 * factor)
    max_text_w = card_w - badge_w - (48 * factor)

    # Línea 1: CANCIÓN (Grande, bold, blanco)
    title_font_size = max(14, int(26 * factor * scale))
    title_font = QFont("Segoe UI", title_font_size, QFont.Weight.Bold)
    title_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    p.setFont(title_font)
    p.setPen(QColor(255, 255, 255))
    fm_title = QFontMetrics(title_font)
    elided_title = fm_title.elidedText(title.upper() if title else "MÚSICA", Qt.TextElideMode.ElideRight, int(max_text_w))
    title_y = box_y + (38 * factor * scale)
    p.drawText(int(text_x), int(title_y), elided_title)

    # Línea 2: ARTISTA (Mediano, color de acento / cyan)
    artist_font_size = max(12, int(20 * factor * scale))
    artist_font = QFont("Segoe UI", artist_font_size, QFont.Weight.DemiBold)
    artist_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    p.setFont(artist_font)
    p.setPen(QColor(accent_hex))
    fm_artist = QFontMetrics(artist_font)
    artist_display = artist or "Artista Desconocido"
    elided_artist = fm_artist.elidedText(artist_display, Qt.TextElideMode.ElideRight, int(max_text_w))
    artist_y = title_y + (28 * factor * scale)
    p.drawText(int(text_x), int(artist_y), elided_artist)

    # Línea 3: Álbum / Año / Discográfica (Pequeño, gris claro)
    sub_parts = []
    if album:
        sub_parts.append(f"Álbum: {album}")
    if year:
        sub_parts.append(year)
    if label and len(sub_parts) < 2:
        sub_parts.append(label)
    sub_text = " • ".join(sub_parts)

    if sub_text:
        sub_font_size = max(10, int(14 * factor * scale))
        sub_font = QFont("Segoe UI", sub_font_size, QFont.Weight.Normal)
        sub_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(sub_font)
        p.setPen(QColor(190, 200, 215, 220))
        fm_sub = QFontMetrics(sub_font)
        elided_sub = fm_sub.elidedText(sub_text, Qt.TextElideMode.ElideRight, int(max_text_w))
        sub_y = artist_y + (22 * factor * scale)
        p.drawText(int(text_x), int(sub_y), elided_sub)

    p.end()
    return canvas


def build_music_overlay(track_meta: Dict[str, str], resolution: Any, out_path: Path | str,
                        style_config: Optional[Dict[str, Any]] = None) -> bool:
    """Genera y guarda el archivo PNG del zócalo musical con canal alfa."""
    img = render_music_overlay(track_meta, resolution, style_config)
    if img.isNull():
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return img.save(str(out), "PNG")


def is_music_overlay_visible(position: float, duration: float,
                             intro_start: float = 30.0, intro_duration: float = 12.0,
                             outro_duration: float = 10.0) -> bool:
    """Determina si el zócalo musical debe estar visible en el segundo actual de reproducción."""
    pos = max(0.0, float(position or 0.0))
    dur = max(0.0, float(duration or 0.0))

    # Ventana de Entrada: Inicia a los 30 segundos y permanece por intro_duration
    in_intro = (intro_start <= pos < intro_start + intro_duration)

    # Ventana de Salida: En los últimos 10 segundos de la canción
    in_outro = False
    if dur > (intro_start + intro_duration):
        in_outro = (pos >= max(0.0, dur - outro_duration))
    elif dur > outro_duration:
        in_outro = (pos >= dur - outro_duration)

    return in_intro or in_outro


def build_music_enable_expression(offset: float, duration: float,
                                  intro_start: float = 30.0, intro_duration: float = 12.0,
                                  outro_duration: float = 10.0) -> str:
    """Construye la expresión FFmpeg 'enable' para superponer el zócalo en RTMP/SRT/UDP."""
    origin = max(0.0, float(offset or 0.0))
    total = max(0.0, float(duration or 0.0))

    windows = []

    # Ventana de entrada (30s)
    intro_in = max(0.0, intro_start - origin)
    intro_out = max(0.0, (intro_start + intro_duration) - origin)
    if intro_out > 0 and (total <= 0 or intro_in < total):
        if origin < (intro_start + intro_duration):
            windows.append(f"between(t,{intro_in:.3f},{intro_out:.3f})")

    # Ventana de salida (últimos 10s)
    if total > (intro_start + intro_duration):
        outro_start = max(0.0, total - outro_duration)
        outro_in = max(0.0, outro_start - origin)
        outro_out = max(0.0, total - origin)
        if outro_out > 0:
            windows.append(f"between(t,{outro_in:.3f},{outro_out:.3f})")

    return "+".join(windows)


# ============================================================================
# Worker asíncrono para identificación en segundo plano
# ============================================================================

class MusicLookupWorker(QThread):
    """Consulta metadatos de música en segundo plano sin congelar la interfaz ni la emisión."""
    result = Signal(str, dict, str)   # path, metadata, overlay_path
    failed = Signal(str, str)        # path, error_msg

    def __init__(self, path: str, resolution: str = "1920x1080", settings: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.resolution = resolution
        self.settings = dict(settings or {})

    def run(self):
        try:
            meta = identify_music_track(self.path, self.settings)
            res_str = self.resolution.replace("x", "_")
            hash_key = hashlib.md5(f"{self.path}_{self.resolution}_{json.dumps(meta, sort_keys=True)}".encode()).hexdigest()[:12]
            overlay_file = MUSIC_CACHE / f"music_overlay_{hash_key}_{res_str}.png"

            style_cfg = {
                "style": self.settings.get("music_titling_style", "glass"),
                "position": self.settings.get("music_titling_position", "inferior-izquierda"),
                "opacity": self.settings.get("music_titling_opacity", 90),
                "text_scale": self.settings.get("music_titling_text_scale", 100),
                "accent_color": self.settings.get("music_titling_accent_color", "#00e5ff"),
            }

            if not overlay_file.is_file():
                build_music_overlay(meta, self.resolution, overlay_file, style_cfg)

            self.result.emit(self.path, meta, str(overlay_file))
        except Exception as exc:
            log.error("Error identificando música %s: %s", self.path, exc)
            self.failed.emit(self.path, str(exc))
