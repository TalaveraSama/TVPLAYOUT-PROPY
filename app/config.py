from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "tvplayout.db"

VIDEO_EXTS = {
    ".mkv",".mp4",".mov",".avi",".ts",".m2ts",".mts",".m4v",".webm",
    ".mpg",".mpeg",".vob",".wmv",".flv",".3gp",".ogv",".mxf"
}

LANG_PRIORITY = ["es-MX","es-419","spa","es","Spanish","Español"]
SUB_PRIORITY = ["es-MX","spa-MX","es-419","spa","es","Spanish","Español"]

def find_binary(name, env_name):
    env = os.environ.get(env_name, "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates += [
        ROOT / name,
        ROOT / "bin" / name,
        ROOT / "mpv-x86_64" / name,
    ]
    for p in candidates:
        if p.exists():
            return str(p.resolve())
    return ""

MPV_PATH = find_binary("mpv.exe", "MPV_PATH")
FFMPEG_PATH = find_binary("ffmpeg.exe", "FFMPEG_PATH")
