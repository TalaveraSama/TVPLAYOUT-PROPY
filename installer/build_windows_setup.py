#!/usr/bin/env python3
"""Builder reproducible del instalador offline de Nexora Air para Windows x64.

Puede ejecutarse desde Linux o Windows. Descarga artefactos públicos oficiales,
arma un runtime Python embebido (sin instalar Python en el equipo destino) y
compila un único Setup con NSIS.

Uso:
    python installer/build_windows_setup.py check
    python installer/build_windows_setup.py prepare
    python installer/build_windows_setup.py setup
    python installer/build_windows_setup.py all
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".installer-build"
DOWNLOADS = WORK / "downloads"
PAYLOAD = WORK / "payload"
DIST = ROOT / "dist"
PYTHON_VERSION = "3.13.2"
PYTHON_EMBED_PACKAGE = "3.13.0"
PYTHON_ARCHIVE_SHA256 = "6e57af03c2cb64dd5191f76274b97fc630b3001bde59f82cf1e252e7e02d6754"
PYSIDE_VERSION = "6.8.3"
PYAV_VERSION = "16.1.0"
APP_NAME = "Nexora Air"
APP_SLUG = "NexoraAir"
APP_VERSION = "V25.3.0"
SETUP_NAME = f"Setup_{APP_SLUG}_{APP_VERSION}.exe"
USER_AGENT = f"{APP_SLUG}-builder/{APP_VERSION}"

# PyPI redistribuye sin cambios el embeddable oficial de python.org. La URL y
# el SHA quedan fijados para que el build sea repetible incluso si aparece una
# versión posterior del paquete.
PYTHON_URL = (
    "https://files.pythonhosted.org/packages/d5/63/"
    "4c82f72006f06a26b05d2f9b0fa082281c3fc4c63df8c03fbf9c0a47bd64/"
    "python_embed-3.13.0.tar.gz"
)
FFMPEG_PACKAGE_VERSION = "1.1.0"  # wheel Windows firmado/publicado en PyPI
WHEEL_PACKAGES = {
    "shiboken6": PYSIDE_VERSION,
    "PySide6_Essentials": PYSIDE_VERSION,
    "PySide6_Addons": PYSIDE_VERSION,
    "av": PYAV_VERSION,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size:
        print(f"[cache] {target.name}")
        return target
    partial = target.with_suffix(target.suffix + ".part")
    print(f"[descarga] {url}")
    curl = shutil.which("curl")
    if curl:
        # curl reanuda descargas grandes y tolera cierres TLS transitorios de
        # python.org/PyPI mucho mejor que una única petición urllib.
        cmd = [curl, "-L", "--fail", "--retry", "5", "--retry-all-errors",
               "--connect-timeout", "30", "-A", USER_AGENT]
        if partial.is_file() and partial.stat().st_size:
            cmd += ["-C", "-"]
        cmd += ["-o", str(partial), url]
        subprocess.run(cmd, check=True)
    else:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, 1024 * 1024)
    partial.replace(target)
    return target


def pypi_wheel(package: str, version: str) -> Path:
    api = f"https://pypi.org/pypi/{package}/{version}/json"
    request = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        metadata = json.load(response)
    candidates = []
    for item in metadata.get("urls", []):
        filename = str(item.get("filename") or "")
        if not filename.endswith(".whl"):
            continue
        if "win_amd64" in filename:
            # CPython 3.13 exacto primero; los wheels abi3 de Qt son válidos.
            score = 0 if "cp313" in filename else 1 if "abi3" in filename else 2
            candidates.append((score, filename, item["url"]))
        elif filename.endswith("py3-none-any.whl"):
            candidates.append((3, filename, item["url"]))
    if not candidates:
        raise RuntimeError(f"PyPI no ofrece wheel Windows x64 para {package}=={version}")
    _score, filename, url = sorted(candidates)[0]
    return download(url, DOWNLOADS / filename)


def extract_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        archive.extractall(target)


def copy_application() -> None:
    shutil.copy2(ROOT / "main.py", PAYLOAD / "main.py")
    shutil.copytree(ROOT / "app", PAYLOAD / "app", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "assets", PAYLOAD / "assets", dirs_exist_ok=True)
    for name in ("README.md", "requirements.txt"):
        shutil.copy2(ROOT / name, PAYLOAD / name)


def prepare() -> None:
    print(f"== {APP_NAME} {APP_VERSION}: preparando runtime Windows x64 ==")
    shutil.rmtree(PAYLOAD, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)

    python_archive = download(PYTHON_URL, DOWNLOADS / f"python-embed-{PYTHON_EMBED_PACKAGE}.tar.gz")
    if sha256(python_archive) != PYTHON_ARCHIVE_SHA256:
        raise RuntimeError("SHA256 inesperado para el runtime Python embebido")
    python_stage = WORK / "python-stage"
    shutil.rmtree(python_stage, ignore_errors=True)
    python_stage.mkdir(parents=True)
    with tarfile.open(python_archive, "r:gz") as archive:
        archive.extractall(python_stage)
    data_zips = list(python_stage.rglob("python_embed/data.zip"))
    if len(data_zips) != 1:
        raise RuntimeError("El paquete python-embed no contiene un único data.zip")
    embed_stage = python_stage / "embed"
    extract_zip(data_zips[0], embed_stage)
    install_root = embed_stage / "cp313"
    if not (install_root / "python.exe").is_file():
        raise RuntimeError("El runtime Python embebido no contiene cp313/python.exe")
    shutil.copytree(install_root, PAYLOAD, dirs_exist_ok=True)
    shutil.rmtree(python_stage, ignore_errors=True)

    site_packages = PAYLOAD / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    wheels = []
    for package, version in WHEEL_PACKAGES.items():
        wheel = pypi_wheel(package, version)
        wheels.append(wheel)
        extract_zip(wheel, site_packages)

    ffmpeg_wheel = pypi_wheel("ffmpeg-binaries", FFMPEG_PACKAGE_VERSION)
    with zipfile.ZipFile(ffmpeg_wheel) as archive:
        members = {Path(name).name.lower(): name for name in archive.namelist()}
        for executable in ("ffmpeg.exe", "ffprobe.exe"):
            member = members.get(executable)
            if not member:
                raise RuntimeError(f"{executable} no está en {ffmpeg_wheel.name}")
            with archive.open(member) as src, (PAYLOAD / executable).open("wb") as dst:
                shutil.copyfileobj(src, dst)

    copy_application()

    # El runtime embebido no busca site-packages salvo que su _pth lo indique.
    pth = "python313.zip\n.\nLib\\site-packages\nimport site\n"
    (PAYLOAD / "python313._pth").write_text(pth, encoding="ascii")
    # Ejecutables con identidad propia; CPython admite un _pth con el nombre
    # del exe, por eso la copia sigue siendo un launcher autónomo.
    shutil.copy2(PAYLOAD / "pythonw.exe", PAYLOAD / f"{APP_SLUG}.exe")
    shutil.copy2(PAYLOAD / "python.exe", PAYLOAD / f"{APP_SLUG}-Console.exe")
    (PAYLOAD / f"{APP_SLUG}._pth").write_text(pth, encoding="ascii")
    (PAYLOAD / f"{APP_SLUG}-Console._pth").write_text(pth, encoding="ascii")
    # Las copias de pythonw/python conservan toda la compatibilidad del runtime
    # embebido. ``sitecustomize`` hace que también funcionen al abrir el EXE
    # directamente (los accesos directos pueden seguir pasando main.py).
    launcher_bootstrap = f'''# Generado por el builder de {APP_NAME} {APP_VERSION}.\nimport os\nimport runpy\nimport sys\n\n_launchers = {{"{APP_SLUG.lower()}.exe", "{APP_SLUG.lower()}-console.exe"}}\nif len(sys.argv) == 1 and not sys.argv[0] and os.path.basename(sys.executable).lower() in _launchers:\n    _main = os.path.join(os.path.dirname(sys.executable), "main.py")\n    sys.argv = [_main]\n    runpy.run_path(_main, run_name="__main__")\n'''
    (site_packages / "sitecustomize.py").write_text(launcher_bootstrap, encoding="utf-8")

    manifest = {
        "product": APP_NAME,
        "version": APP_VERSION,
        "python": PYTHON_VERSION,
        "pyside6": PYSIDE_VERSION,
        "pyav": PYAV_VERSION,
        "architecture": "windows-x86_64",
        "files": {},
        "inputs": {p.name: sha256(p) for p in [python_archive, ffmpeg_wheel, *wheels]},
    }
    for path in sorted(PAYLOAD.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(PAYLOAD).as_posix()] = {
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
    (PAYLOAD / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    size = sum(p.stat().st_size for p in PAYLOAD.rglob("*") if p.is_file())
    print(f"[OK] payload: {len(manifest['files'])} archivos, {size / 1024 / 1024:.1f} MiB")


def nsis_escape(path: Path) -> str:
    return str(path).replace("/", "\\")


def write_nsis() -> Path:
    if not (PAYLOAD / f"{APP_SLUG}.exe").is_file():
        raise RuntimeError("Falta el payload. Ejecuta primero: prepare")
    DIST.mkdir(parents=True, exist_ok=True)
    script = WORK / "NexoraAir.nsi"
    payload = nsis_escape(PAYLOAD)
    out = nsis_escape(DIST / SETUP_NAME)
    icon = nsis_escape(ROOT / "assets" / "logo.ico")
    content = rf'''Unicode True
LoadLanguageFile "${{NSISDIR}}\Contrib\Language files\Spanish.nlf"
Name "{APP_NAME} {APP_VERSION}"
Caption "Instalar {APP_NAME} {APP_VERSION}"
OutFile "{out}"
InstallDir "$LOCALAPPDATA\Programs\{APP_SLUG}"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
Icon "{icon}"
UninstallIcon "{icon}"

; Páginas NSIS nativas: también compilan desde hosts no Windows sin depender
; de ejecutables auxiliares de Modern UI.
Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Nexora Air" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "{payload}\*.*"

  ; Migración in-place y desde el directorio usado por TVPlayout PRO.
  IfFileExists "$INSTDIR\nexora-air.db" db_done
  IfFileExists "$INSTDIR\tvplayout.db" 0 old_dir_db
  CopyFiles /SILENT "$INSTDIR\tvplayout.db" "$INSTDIR\nexora-air.db"
  Goto db_done
old_dir_db:
  IfFileExists "$LOCALAPPDATA\Programs\TVPlayoutPRO\tvplayout.db" 0 db_done
  CopyFiles /SILENT "$LOCALAPPDATA\Programs\TVPlayoutPRO\tvplayout.db" "$INSTDIR\nexora-air.db"
db_done:
  IfFileExists "$INSTDIR\.env" env_done
  IfFileExists "$LOCALAPPDATA\Programs\TVPlayoutPRO\.env" 0 env_done
  CopyFiles /SILENT "$LOCALAPPDATA\Programs\TVPlayoutPRO\.env" "$INSTDIR\.env"
env_done:
  IfFileExists "$INSTDIR\cache\*.*" cache_done
  IfFileExists "$LOCALAPPDATA\Programs\TVPlayoutPRO\cache\*.*" 0 cache_done
  ; Copiar el directorio completo conserva thumbs/ y demás subdirectorios.
  CopyFiles /SILENT "$LOCALAPPDATA\Programs\TVPlayoutPRO\cache" "$INSTDIR"
cache_done:
  IfFileExists "$INSTDIR\logs\*.*" logs_done
  IfFileExists "$LOCALAPPDATA\Programs\TVPlayoutPRO\logs\*.*" 0 logs_done
  CopyFiles /SILENT "$LOCALAPPDATA\Programs\TVPlayoutPRO\logs" "$INSTDIR"
logs_done:

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\{APP_NAME}"
  CreateShortcut "$SMPROGRAMS\{APP_NAME}\{APP_NAME}.lnk" "$INSTDIR\{APP_SLUG}.exe" '"$INSTDIR\main.py"' "$INSTDIR\assets\logo.ico"
  CreateShortcut "$SMPROGRAMS\{APP_NAME}\Consola de diagnóstico.lnk" "$INSTDIR\{APP_SLUG}-Console.exe" '"$INSTDIR\main.py"' "$INSTDIR\assets\logo.ico"
  CreateShortcut "$DESKTOP\{APP_NAME}.lnk" "$INSTDIR\{APP_SLUG}.exe" '"$INSTDIR\main.py"' "$INSTDIR\assets\logo.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}" "DisplayName" "{APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}" "DisplayVersion" "{APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}" "Publisher" "{APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}" "DisplayIcon" "$INSTDIR\assets\logo.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  CreateDirectory "$DESKTOP\NexoraAir-Backup"
  CopyFiles /SILENT "$INSTDIR\nexora-air.db" "$DESKTOP\NexoraAir-Backup"
  CopyFiles /SILENT "$INSTDIR\tvplayout.db" "$DESKTOP\NexoraAir-Backup"
  CopyFiles /SILENT "$INSTDIR\.env" "$DESKTOP\NexoraAir-Backup"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\Lib"
  RMDir /r "$INSTDIR\assets"
  Delete "$INSTDIR\*.exe"
  Delete "$INSTDIR\*.dll"
  Delete "$INSTDIR\*.zip"
  Delete "$INSTDIR\*.pyd"
  Delete "$INSTDIR\*._pth"
  Delete "$INSTDIR\main.py"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\release-manifest.json"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\{APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\{APP_NAME}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}"
SectionEnd
'''
    script.write_text(content, encoding="utf-8")
    return script


def find_makensis() -> str:
    explicit = os.environ.get("MAKENSIS")
    candidates = [
        explicit,
        shutil.which("makensis"),
        shutil.which("makensis.exe"),
        r"C:\Program Files (x86)\NSIS\makensis.exe",
        r"C:\Program Files\NSIS\makensis.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("No se encontró makensis (NSIS 3). Instálalo o define MAKENSIS.")


def build_setup() -> Path:
    script = write_nsis()
    makensis = find_makensis()
    print(f"[NSIS] {makensis} {script}")
    subprocess.run([makensis, str(script)], check=True, cwd=ROOT)
    result = DIST / SETUP_NAME
    if not result.is_file():
        raise RuntimeError(f"NSIS no creó {result}")
    checksum = sha256(result)
    (DIST / f"{SETUP_NAME}.sha256").write_text(f"{checksum}  {SETUP_NAME}\n", encoding="ascii")
    print(f"[OK] {result} ({result.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"[SHA256] {checksum}")
    return result


def check() -> None:
    cfg = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    spec = (ROOT / "tvplayout.spec").read_text(encoding="utf-8")
    assert f'APP_NAME = "{APP_NAME}"' in cfg
    assert f'APP_VERSION = "{APP_VERSION}"' in cfg
    assert f'name="{APP_SLUG}"' in spec
    assert (ROOT / "assets" / "logo.png").is_file()
    assert (ROOT / "assets" / "logo.ico").is_file()
    print(f"[OK] identidad y versión sincronizadas: {APP_NAME} {APP_VERSION}")


def main(argv: list[str]) -> int:
    action = argv[1].lower() if len(argv) > 1 else "all"
    check()
    if action == "check":
        return 0
    if action in {"prepare", "all"}:
        prepare()
    if action in {"setup", "all"}:
        build_setup()
    if action not in {"check", "prepare", "setup", "all"}:
        raise SystemExit("Uso: build_windows_setup.py [check|prepare|setup|all]")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except (AssertionError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
