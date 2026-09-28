#!/usr/bin/env python3
"""Prepare and validate a Nexora Air release.

The application version lives in ``app/config.py``.  This helper keeps the
version copied into the build documentation and Windows launchers in sync,
without rewriting historical release notes.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "app" / "config.py"
# These files contain the current release number, rather than historical data.
CURRENT_RELEASE_FILES = (
    Path("app/config.py"),
    Path("README.md"),
    Path("BUILD.md"),
    Path("build_exe.bat"),
    Path("installer/BUILD_INSTALLER.bat"),
)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def version_parts(version: str) -> tuple[str, str]:
    """Return the display form (Vx.y.z) and tag form (vx.y.z)."""
    version = version.removeprefix("V").removeprefix("v")
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"versión inválida: {version!r}; usa X.Y.Z")
    return f"V{version}", f"v{version}"


def current_version() -> str:
    text = CONFIG.read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"(V[\d.]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("app/config.py no contiene APP_VERSION")
    return match.group(1)


def replace_version(old: str, display: str) -> list[Path]:
    changed: list[Path] = []
    for relative in CURRENT_RELEASE_FILES:
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        updated = text.replace(old, display)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
            changed.append(relative)
    return changed


def check(display: str) -> int:
    errors: list[str] = []
    expected_note = ROOT / "RELEASE_NOTES" / f"{display.lower()}.md"
    if not CONFIG.is_file():
        errors.append("falta app/config.py")
    else:
        try:
            actual = current_version()
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            if actual != display:
                errors.append(f"APP_VERSION es {actual}, se esperaba {display}")

    for relative in CURRENT_RELEASE_FILES[1:]:
        path = ROOT / relative
        if display not in path.read_text(encoding="utf-8"):
            errors.append(f"{relative} no contiene {display}")
    if not expected_note.is_file():
        errors.append(f"falta {expected_note.relative_to(ROOT)}")
    elif not expected_note.read_text(encoding="utf-8").strip():
        errors.append(f"{expected_note.relative_to(ROOT)} está vacío")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: release {display} sincronizada")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="versión destino, por ejemplo 25.6.0")
    parser.add_argument("--check", action="store_true", help="solo valida la release actual")
    args = parser.parse_args()

    if args.check:
        display = current_version()
        return check(display)
    if not args.version:
        parser.error("indica una versión o usa --check")
    try:
        display, _tag = version_parts(args.version)
        old = current_version()
    except ValueError as exc:
        parser.error(str(exc))
    if display == old:
        print(f"La release ya está en {display}; no hay cambios")
    else:
        changed = replace_version(old, display)
        print(f"Release {old} -> {display}")
        for path in changed:
            print(f"  actualizado {path}")
    return check(display)


if __name__ == "__main__":
    raise SystemExit(main())
