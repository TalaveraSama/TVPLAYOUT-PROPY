"""Consulta ligera de TMDB y composición del identificador visual de película."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QRect, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen, QPainterPath

from .config import CACHE_DIR

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p/"
TMDB_CACHE = CACHE_DIR / "tmdb"


def _request_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TVPlayout-PRO/24"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _download(url, path):
    if path.is_file() and path.stat().st_size > 0:
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "TVPlayout-PRO/24"})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = response.read()
    if not data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def download_image(url, path):
    """Descarga una imagen de TMDB a la caché (uso general de la biblioteca)."""
    return _download(str(url), Path(path))


class TMDBLookupWorker(QThread):
    """Busca la película sin bloquear el hilo de la interfaz ni el aire."""

    result = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, api_key, title, language="es-MX", parent=None):
        super().__init__(parent)
        self.api_key = str(api_key or "").strip()
        self.title = str(title or "").strip()
        self.language = language or "es-MX"

    @staticmethod
    def _safe_title(title):
        title = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", title)
        title = re.sub(r"[._]+", " ", title)
        return re.sub(r"\s+", " ", title).strip()

    def run(self):
        if not self.api_key or not self.title:
            self.failed.emit(self.title, "Falta TMDB_API_KEY o título")
            return
        try:
            query = self._safe_title(self.title)
            key = hashlib.sha1(f"{self.language}|{query}".encode("utf-8", "replace")).hexdigest()[:20]
            TMDB_CACHE.mkdir(parents=True, exist_ok=True)
            meta_path = TMDB_CACHE / f"{key}.json"
            metadata = None
            if meta_path.is_file():
                try:
                    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    metadata = None
            if not metadata:
                params = urllib.parse.urlencode({
                    "api_key": self.api_key,
                    "query": query,
                    "language": self.language,
                    "include_adult": "false",
                    "page": 1,
                })
                data = _request_json(f"{TMDB_API}/search/movie?{params}")
                result = (data.get("results") or [None])[0]
                if not result:
                    self.failed.emit(self.title, f"TMDB no encontró: {query}")
                    return
                metadata = {
                    "id": result.get("id"),
                    "title": result.get("title") or query,
                    "original_title": result.get("original_title") or "",
                    "year": str(result.get("release_date") or "")[:4],
                    "overview": result.get("overview") or "",
                    "poster_path": result.get("poster_path") or "",
                    "backdrop_path": result.get("backdrop_path") or "",
                }
                meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            for field, size in (("poster_path", "w342"), ("backdrop_path", "w780")):
                remote = metadata.get(field) or ""
                if not remote:
                    continue
                local = TMDB_CACHE / f"{key}_{field.replace('_path', '')}.jpg"
                if _download(f"{TMDB_IMAGES}{size}{remote}", local):
                    metadata[field.replace("_path", "_file")] = str(local)
            self.result.emit(self.title, metadata)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.title, str(exc)[:240])


class TMDBSearchWorker(QThread):
    """Buscador multi-resultado para la ventana de edición de la ficha TMDB.

    A diferencia de ``TMDBLookupWorker`` (que devuelve sólo el primer
    resultado para la tarjeta al aire), éste entrega hasta 20 candidatos con
    su miniatura descargada para elegir la película correcta.
    """

    results = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key, query, language="es-MX", parent=None):
        super().__init__(parent)
        self.api_key = str(api_key or "").strip()
        self.query = str(query or "").strip()
        self.language = language or "es-MX"

    def run(self):
        if not self.api_key or not self.query:
            self.failed.emit("Falta la API key o el texto de búsqueda")
            return
        try:
            params = urllib.parse.urlencode({
                "api_key": self.api_key,
                "query": self.query,
                "language": self.language,
                "include_adult": "false",
                "page": 1,
            })
            data = _request_json(f"{TMDB_API}/search/movie?{params}")
            out = []
            TMDB_CACHE.mkdir(parents=True, exist_ok=True)
            for r in (data.get("results") or [])[:20]:
                entry = {
                    "id": r.get("id"),
                    "title": r.get("title") or r.get("original_title") or "",
                    "original_title": r.get("original_title") or "",
                    "year": str(r.get("release_date") or "")[:4],
                    "overview": r.get("overview") or "",
                    "poster_path": r.get("poster_path") or "",
                    "backdrop_path": r.get("backdrop_path") or "",
                }
                if entry["poster_path"]:
                    local = TMDB_CACHE / (f"s_{entry['id']}_" +
                                          hashlib.sha1(entry["poster_path"].encode("utf-8")).hexdigest()[:10] + ".jpg")
                    try:
                        if _download(f"{TMDB_IMAGES}w185{entry['poster_path']}", local):
                            entry["poster_file"] = str(local)
                    except OSError:
                        pass  # una miniatura fallida no tumba la búsqueda
                out.append(entry)
            self.results.emit(out)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc)[:240])


class TMDBImagesWorker(QThread):
    """Descarga la galería de pósters y backdrops de una película concreta.

    Se trae la lista completa de imágenes del endpoint ``/movie/{id}/images``
    (español primero, luego inglés y sin idioma) y baja cada candidata en
    calidad final: pósters w342 y backdrops w780, los mismos tamaños que usa
    la tarjeta al aire, para que lo que se ve en la galería sea lo que se
    guarda.
    """

    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, api_key, movie, parent=None):
        super().__init__(parent)
        self.api_key = str(api_key or "").strip()
        self.movie = dict(movie or {})

    def run(self):
        movie_id = int(self.movie.get("id") or 0)
        if not self.api_key or not movie_id:
            self.failed.emit("Falta la API key o la película")
            return
        try:
            params = urllib.parse.urlencode({
                "api_key": self.api_key,
                "include_image_language": "es,en,null",
            })
            data = _request_json(f"{TMDB_API}/movie/{movie_id}/images?{params}")
            TMDB_CACHE.mkdir(parents=True, exist_ok=True)
            posters = [img for img in (self._grab(r, movie_id, "poster", "w342")
                                       for r in (data.get("posters") or [])[:12]) if img]
            backdrops = [img for img in (self._grab(r, movie_id, "backdrop", "w780")
                                         for r in (data.get("backdrops") or [])[:12]) if img]
            self.ready.emit({"movie": self.movie, "posters": posters, "backdrops": backdrops})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc)[:240])

    @staticmethod
    def _grab(img, movie_id, kind, size):
        remote = str(img.get("file_path") or "")
        if not remote:
            return None
        local = TMDB_CACHE / (f"m{movie_id}_{kind}_" +
                              hashlib.sha1(remote.encode("utf-8")).hexdigest()[:12] + ".jpg")
        try:
            if not _download(f"{TMDB_IMAGES}{size}{remote}", local):
                return None
        except OSError:
            return None  # una imagen fallida no tumba la galería completa
        return {"file": str(local), "path": remote,
                "lang": str(img.get("iso_639_1") or ""), "votes": int(img.get("vote_count") or 0)}


DEFAULT_CARD_LAYOUT = {
    "position": "arriba",   # arriba | abajo
    "align": "izquierda",   # izquierda | centro | derecha
    "style": "banda",       # banda completa | tarjeta compacta
    "opacity": 70,          # % de oscurecido del fondo
    "margin": 18,           # px de referencia a 1080p
}


def resolve_card_layout(layout=None):
    """Normaliza la configuración de la tarjeta (posición, alineación, estilo...)."""
    cfg = dict(DEFAULT_CARD_LAYOUT)
    for key in cfg:
        value = (layout or {}).get(key)
        if value is not None:
            cfg[key] = value
    position = str(cfg.get("position") or "").lower()
    cfg["position"] = "abajo" if "abajo" in position else "arriba"
    align = str(cfg.get("align") or "").lower()
    cfg["align"] = "centro" if "centro" in align else ("derecha" if "derech" in align else "izquierda")
    style = str(cfg.get("style") or "").lower()
    cfg["style"] = "tarjeta" if "tarjeta" in style else "banda"
    for key, top in (("opacity", 100), ("margin", 300)):
        try:
            cfg[key] = max(0, min(top, int(float(cfg.get(key) or 0))))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_CARD_LAYOUT[key]
    return cfg


def _overlay_image(value):
    """Imagen de la ficha: ruta en disco o QImage directo (vista previa)."""
    if isinstance(value, QImage):
        return value
    if value:
        img = QImage(str(value))
        if not img.isNull():
            return img
    return QImage()


def render_movie_overlay(metadata, resolution, layout=None):
    """Renderiza la tarjeta de película sobre un QImage RGBA transparente.

    Toda la geometría es proporcional a la altura del lienzo, así que la
    vista previa del diálogo «Tarjeta TMDB» se dibuja con exactamente la
    misma composición que la salida al aire (WYSIWYG a cualquier tamaño).
    """
    cfg = resolve_card_layout(layout)
    try:
        if isinstance(resolution, (tuple, list)):
            width, height = int(resolution[0]), int(resolution[1])
        else:
            width, height = (int(x) for x in str(resolution).lower().split("x", 1))
    except (TypeError, ValueError, IndexError):
        width, height = 1920, 1080
    if width <= 0 or height <= 0:
        return QImage()
    metadata = metadata or {}
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    scale = height / 1080.0
    band_h = max(40, int(height * 0.225))
    band_y = 0 if cfg["position"] == "arriba" else height - band_h
    margin = int(cfg["margin"] * scale)
    gap = max(4, int(16 * scale))
    dark = QColor(0, 0, 0, int(255 * cfg["opacity"] / 100.0))
    title = metadata.get("title") or "Película"
    year = metadata.get("year") or ""
    overview = metadata.get("overview") or "Ahora en emisión"
    overview = overview if len(overview) <= 210 else overview[:207].rstrip() + "…"
    title_font = QFont("Arial", max(9, int(height * 0.036)))
    title_font.setBold(True)
    label_font = QFont("Arial", max(7, int(height * 0.019)))
    label_metrics = QFontMetrics(label_font)
    title_font_metrics = QFontMetrics(title_font)
    title_text = f"{title}  {year}".strip()
    overview_text = overview

    poster = _overlay_image(metadata.get("poster_file"))
    poster_h = max(24, band_h - int(28 * scale))
    poster_w = 0
    if not poster.isNull():
        poster_w = int(poster.width() * poster_h / max(1, poster.height()))
        poster = poster.scaled(poster_w, poster_h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        poster_w = poster.width()
    poster_y = band_y + (band_h - poster_h) // 2
    backdrop = _overlay_image(metadata.get("backdrop_file"))
    max_text_w = max(120, int(width * 0.42))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def draw_text(x, w, align_right=False):
        flag = Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft
        painter.setPen(QColor(255, 255, 255, 255))
        painter.setFont(title_font)
        line = title_font_metrics.elidedText(title_text, Qt.TextElideMode.ElideRight, w)
        painter.drawText(QRect(x, band_y + int(band_h * 0.12), w, int(band_h * 0.30)),
                         flag | Qt.AlignmentFlag.AlignVCenter, line)
        painter.setFont(label_font)
        painter.setPen(QColor(230, 230, 230, 235))
        body = label_metrics.elidedText(overview_text, Qt.TextElideMode.ElideRight, w)
        painter.drawText(QRect(x, band_y + int(band_h * 0.48), w, int(band_h * 0.34)),
                         flag | Qt.AlignmentFlag.AlignTop, body)

    def draw_poster(x):
        if poster_w:
            painter.drawImage(x, poster_y, poster)

    if cfg["style"] == "tarjeta":
        text_w = min(max_text_w, width - 2 * margin - poster_w - gap if poster_w else width - 2 * margin)
        text_w = max(120, text_w)
        group_w = (poster_w + gap + text_w) if poster_w else text_w
        if cfg["align"] == "izquierda":
            x0 = margin
        elif cfg["align"] == "derecha":
            x0 = width - margin - group_w
        else:
            x0 = (width - group_w) // 2
        pad = max(6, int(14 * scale))
        card = QRect(x0 - pad, band_y + int(10 * scale), group_w + 2 * pad, band_h - int(20 * scale))
        radius = max(4.0, 10.0 * scale)
        path = QPainterPath()
        path.addRoundedRect(QRectF(card), radius, radius)
        painter.save()
        painter.setClipPath(path)
        if not backdrop.isNull():
            painter.drawImage(card, backdrop)
        painter.fillRect(card, dark)
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 40), max(1.0, 1.5 * scale)))
        painter.drawPath(path)
        draw_poster(x0)
        draw_text(x0 + (poster_w + gap if poster_w else 0), text_w)
    else:
        # Banda completa a lo ancho de la pantalla.
        if not backdrop.isNull():
            painter.drawImage(QRect(0, band_y, width, band_h), backdrop)
        painter.fillRect(QRect(0, band_y, width, band_h), dark)
        if cfg["align"] == "izquierda":
            draw_poster(margin)
            text_x = margin + (poster_w + gap if poster_w else 0)
            draw_text(text_x, max(120, width - margin - text_x))
        elif cfg["align"] == "derecha":
            poster_x = width - margin - poster_w if poster_w else width - margin
            draw_poster(poster_x)
            text_w = (poster_x - gap - margin) if poster_w else (width - 2 * margin)
            draw_text(margin, max(120, text_w), align_right=True)
        else:
            text_w = max_text_w
            group_w = (poster_w + gap + text_w) if poster_w else text_w
            x0 = (width - group_w) // 2
            draw_poster(x0)
            draw_text(x0 + (poster_w + gap if poster_w else 0), text_w)
    painter.end()
    return canvas


def build_movie_overlay(metadata, resolution, out_path, layout=None):
    """Crea una PNG RGBA de resolución completa con la tarjeta de película."""
    canvas = render_movie_overlay(metadata, resolution, layout)
    if canvas.isNull():
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return bool(canvas.save(str(out), "PNG"))
