"""Build/validate the unsigned MediathekAtlas macOS .app ZIP without macOS APIs.

The bundle is Python source, static resources, a plist and a shell launcher:
no compiled native binary is built here. This is a *portable, unverified*
release fallback when GitHub-hosted macOS runners have no available capacity.
It does not substitute native macOS integration tests.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import plistlib
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "MediathekAtlas.app"
LAUNCHER = f"{APP_NAME}/Contents/MacOS/MediathekAtlas"
PLIST = f"{APP_NAME}/Contents/Info.plist"
RESOURCES = f"{APP_NAME}/Contents/Resources/app/"


def build_zip(app: Path, destination: Path) -> Path:
    """Zip an existing macOS bundle, retaining the executable POSIX mode."""
    if not (app / "Contents" / "Info.plist").is_file():
        raise ValueError("Info.plist fehlt")
    launcher = app / "Contents" / "MacOS" / "MediathekAtlas"
    if not launcher.is_file() or not (launcher.stat().st_mode & 0o111):
        raise ValueError("Startprogramm fehlt oder ist nicht ausführbar")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=7, allowZip64=True) as archive:
        for entry in sorted(app.rglob("*")):
            if entry.is_symlink():
                raise ValueError(f"Nicht erlaubter Symlink im Paket: {entry}")
            if entry.is_file():
                archive.write(entry, f"{APP_NAME}/{entry.relative_to(app).as_posix()}")
    return destination


def verify_zip(destination: Path, version: str | None = None) -> dict:
    """Reject corrupted, incomplete or non-executable bundles."""
    required = (LAUNCHER, PLIST, RESOURCES + "server.py",
                RESOURCES + "catalog.py", RESOURCES + "version.py",
                RESOURCES + "video_causality.py",
                RESOURCES + "web/index.html", RESOURCES + "web/app.js")
    with zipfile.ZipFile(destination, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Beschädigte ZIP-Datei: {bad}")
        entries = {item.filename: item for item in archive.infolist()}
        absent = [name for name in required if name not in entries]
        if absent:
            raise ValueError("Dateien fehlen im App-Paket: " + ", ".join(absent))
        if not (entries[LAUNCHER].external_attr >> 16) & 0o111:
            raise ValueError("Startprogramm ist im ZIP nicht ausführbar")
        if stat.S_IFMT(entries[LAUNCHER].external_attr >> 16) == stat.S_IFLNK:
            raise ValueError("Startprogramm ist ein Symlink")
        info = plistlib.loads(archive.read(PLIST))
        if info.get("CFBundleExecutable") != "MediathekAtlas":
            raise ValueError("Bundle-Startprogramm stimmt nicht überein")
        if version and info.get("CFBundleShortVersionString") != version:
            raise ValueError("Falsche App-Version im Info.plist")
        if not archive.read(RESOURCES + "web/index.html"):
            raise ValueError("Weboberfläche fehlt")
        return {"version": info.get("CFBundleShortVersionString"),
                "files": len(entries), "bytes": destination.stat().st_size}


def main() -> None:
    # When run as python packaging/macos_zip.py, Python starts with the
    # packaging subdirectory on sys.path rather than the repository root.
    sys.path.insert(0, str(ROOT))
    from version import VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true",
                        help="Validate an existing artifact")
    args = parser.parse_args()
    destination = ROOT / "dist" / f"MediathekAtlas_v{VERSION}_macOS.zip"
    if not args.verify:
        build_zip(ROOT / "build" / APP_NAME, destination)
    print(f"{destination}: {verify_zip(destination, VERSION)}")


if __name__ == "__main__":
    main()
