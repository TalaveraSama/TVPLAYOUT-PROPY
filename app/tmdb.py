"""Consulta ligera de TMDB y composición del identificador visual de película."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics

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


def build_movie_overlay(metadata, resolution, out_path):
    """Crea una PNG RGBA de resolución completa con backdrop, póster y texto."""
    try:
        width, height = (int(x) for x in str(resolution).lower().split("x", 1))
    except (TypeError, ValueError):
        width, height = 1920, 1080
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    band_h = max(150, int(height * 0.225))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    backdrop = QImage(metadata.get("backdrop_file", ""))
    if not backdrop.isNull():
        painter.drawImage(QRect(0, 0, width, band_h), backdrop)
    painter.fillRect(QRect(0, 0, width, band_h), QColor(0, 0, 0, 178))
    poster = QImage(metadata.get("poster_file", ""))
    poster_h = max(100, band_h - 28)
    poster_w = int(poster.width() * poster_h / max(1, poster.height())) if not poster.isNull() else 0
    if not poster.isNull():
        poster = poster.scaled(poster_w, poster_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(18, 14, poster)
    text_x = 34 + poster_w
    text_w = max(320, width - text_x - 36)
    title = metadata.get("title") or "Película"
    year = metadata.get("year") or ""
    painter.setPen(QColor(255, 255, 255, 255))
    title_font = QFont("Arial", max(24, int(height * 0.036)))
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(QRect(text_x, 28, text_w, 58), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     f"{title}  {year}".strip())
    label_font = QFont("Arial", max(14, int(height * 0.019)))
    label_font.setBold(False)
    painter.setFont(label_font)
    painter.setPen(QColor(230, 230, 230, 235))
    overview = metadata.get("overview") or "Ahora en emisión"
    overview = overview if len(overview) <= 210 else overview[:207].rstrip() + "…"
    metrics = QFontMetrics(label_font)
    overview = metrics.elidedText(overview, Qt.TextElideMode.ElideRight, text_w)
    painter.drawText(QRect(text_x, 90, text_w, 54), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, overview)
    painter.end()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return bool(canvas.save(str(out), "PNG"))
