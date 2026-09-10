"""Configuración global: rutas, binarios y constantes."""
from pathlib import Path
import os
import shutil
import sys


def _runtime_root():
    """Carpeta persistente de la aplicación, también dentro de PyInstaller.

    En modo desarrollo ``__file__`` apunta al checkout. En un ejecutable
    congelado no se debe usar ``sys._MEIPASS``: en onefile es temporal y se
    borra al cerrar, lo que perdería la base, logs y cache. La carpeta del
    ejecutable es la raíz portable estable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _runtime_root()
APP_NAME = "TVPlayout PRO"
APP_VERSION = "V24.0.2.36"
IS_WINDOWS = os.name == "nt"


def _first_asset(*paths):
    for path in paths:
        path = Path(path)
        if path.is_file():
            return path
    return None


# El usuario puede colocar su identidad visual sin modificar el código.
# logo.ico se usa como icono del EXE cuando existe; logo.png como icono de la
# ventana y como ruta sugerida para el logo de salida RTMP.
APP_ICON_PATH = _first_asset(ROOT / "assets" / "logo.png", ROOT / "logo.png",
                             ROOT / "assets" / "logo.ico", ROOT / "logo.ico")
APP_EXE_ICON_PATH = _first_asset(ROOT / "assets" / "logo.ico", ROOT / "logo.ico")
DEFAULT_LOGO_PATH = _first_asset(ROOT / "assets" / "logo.png", ROOT / "logo.png")


def _load_env_file():
    """Carga un .env sencillo (CLAVE=valor) desde la raíz del proyecto."""
    p = ROOT / ".env"
    if not p.is_file():
        return
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


_load_env_file()

DB_PATH = Path(os.environ.get("TVPLAYOUT_DB") or (ROOT / "tvplayout.db"))
CACHE_DIR = ROOT / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
LOG_DIR = ROOT / "logs"
for _d in (CACHE_DIR, THUMB_DIR, LOG_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

VIDEO_EXTS = {
    ".mkv", ".mp4", ".mov", ".avi", ".ts", ".m2ts", ".mts", ".m4v", ".webm",
    ".mpg", ".mpeg", ".vob", ".wmv", ".flv", ".3gp", ".ogv", ".mxf",
}

LANG_PRIORITY = ["es-MX", "es-419", "Latino", "Latin", "LAT", "spa", "es", "esp", "Spanish", "Español", "Castellano"]
SUB_PRIORITY = ["es-MX", "spa-MX", "es-419", "Latino", "Latin", "spa", "es", "esp", "Spanish", "Español", "Castellano"]

AUDIO_PREFS = ["AUTO / Español latino preferido", "es-MX", "es-419", "spa", "es", "en", "eng", "English", "Original"]
SUB_PREFS = ["AUTO / Español MX preferido", "es-MX", "spa-MX", "es-419", "spa", "es", "en", "eng", "English", "OFF"]

RESOLUTIONS = ["1920x1080", "1280x720", "720x576", "720x480", "3840x2160"]
FPS_LIST = ["23.976", "24", "25", "29.97", "30", "50", "59.94", "60"]
ENCODERS = ["AUTO", "CPU/x264", "NVIDIA NVENC", "Intel QSV", "AMD AMF"]

# Colores por categoría (estilo grid XPlayout: filas pastel con texto oscuro)
CATEGORY_COLORS = {
    "Películas": "#f4a45a",
    "Series": "#8fdc8f",
    "Infantil": "#c9a4ff",
    "Documentales": "#f2d16b",
    "Música": "#7fd6f2",
    "Deportes": "#f28c8c",
    "Noticias": "#d4d4d4",
    "Publicidad": "#f3f38a",
    "Otros": "#e2cba9",
}
FALLBACK_COLORS = ["#f7b58a", "#a8e3c8", "#b9c8ff", "#ffd3e0", "#d9e6a2", "#b7e6ec"]


def category_color(name: str) -> str:
    if name in CATEGORY_COLORS:
        return CATEGORY_COLORS[name]
    return FALLBACK_COLORS[sum(ord(c) for c in (name or "")) % len(FALLBACK_COLORS)]


def find_binary(name: str, env_name: str = "") -> str:
    """Busca un ejecutable: variable de entorno, raíz del proyecto, bin/, mpv-x86_64/, ffmpeg/ y PATH."""
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        names = [name + ".exe", name]
    else:
        names = [name]
    candidates = []
    env = os.environ.get(env_name, "").strip() if env_name else ""
    if env:
        candidates.append(Path(env))
        for n in names:
            candidates.append(Path(env) / n)
    for n in names:
        candidates += [
            ROOT / n,
            ROOT / "bin" / n,
            ROOT / "mpv-x86_64" / n,
            ROOT / "ffmpeg" / n,
            ROOT / "ffmpeg" / "bin" / n,
        ]
    for p in candidates:
        try:
            if p.is_file():
                return str(p.resolve())
        except OSError:
            continue
    for n in names:
        w = shutil.which(n)
        if w:
            return w
    return ""


MPV_PATH = find_binary("mpv", "MPV_PATH")
FFMPEG_PATH = find_binary("ffmpeg", "FFMPEG_PATH")
# NDI no viene habilitado en la mayoría de builds genéricas de FFmpeg.
# Permite colocar una build separada como ffmpeg-ndi.exe sin cambiar la
# salida RTMP/SRT estable.
FFMPEG_NDI_PATH = find_binary("ffmpeg-ndi", "FFMPEG_NDI_PATH")
FFPROBE_PATH = ""
if FFMPEG_PATH:
    _probe = Path(FFMPEG_PATH).with_name("ffprobe.exe" if IS_WINDOWS else "ffprobe")
    if _probe.is_file():
        FFPROBE_PATH = str(_probe)
if not FFPROBE_PATH:
    FFPROBE_PATH = find_binary("ffprobe", "FFPROBE_PATH")


# v24.0.2.32: VLC es el reproductor alternativo para las vistas previas de
# biblioteca/playlist y para el monitor de programa FFmpeg. El instalador
# oficial lo deja en Program Files\VideoLAN\VLC (no siempre está en el PATH).
def find_vlc() -> str:
    found = find_binary("vlc", "VLC_PATH")
    if found:
        return found
    if IS_WINDOWS:
        bases = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramW6432", ""),
                 os.environ.get("ProgramFiles(x86)", "")]
        for base in (b for b in bases if b):
            exe = Path(base) / "VideoLAN" / "VLC" / "vlc.exe"
            try:
                if exe.is_file():
                    return str(exe.resolve())
            except OSError:
                continue
    return ""


VLC_PATH = find_vlc()
