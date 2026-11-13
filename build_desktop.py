"""Build desktop packages for Windows and Linux (0.5.80).

  python3 build_desktop.py [out_dir]

Produces, all architecture-independent (pure Python, system Python 3.9+):
* ``MediathekAtlas_v<V>-Windows-Setup.exe``  NSIS installer, per user, no admin rights
  (needs ``makensis``; skipped with a warning when it is missing),
* ``MediathekAtlas_v<V>-Windows.zip``         portable folder (start.ps1 / Start.bat),
* ``mediathekatlas_<V>_all.deb``              Debian/Ubuntu/Mint/Raspberry Pi OS (needs ``dpkg-deb``),
* ``MediathekAtlas_v<V>-Linux.tar.gz``        every other distribution, ``./install.sh`` per user.

Data folders: Windows ``%LOCALAPPDATA%\\MediathekAtlas``, Linux ``~/.mediathekatlas`` (as before).
Build-only dependency: Pillow (icons).
"""
import shutil, subprocess, sys, tarfile, zipfile
from pathlib import Path

from version import VERSION
import build_nas

ROOT = Path(__file__).resolve().parent
PACK = ROOT / 'packaging'
NAME = 'MediathekAtlas'


def render(text, **extra):
    text = text.replace('@VERSION@', VERSION)
    for key, value in extra.items():
        text = text.replace('@%s@' % key, str(value))
    return text


def png(size):
    return build_nas.icon(size)


def ico(path):
    from PIL import Image
    im = Image.open(ROOT / 'assets' / 'icon.png').convert('RGBA')
    im.save(path, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def _write(path, text, mode=0o644, crlf=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace('\r\n', '\n')
    if crlf:
        data = data.replace('\n', '\r\n')
    path.write_bytes(data.encode('utf-8-sig' if path.suffix == '.ps1' else 'utf-8'))
    path.chmod(mode)


README_WIN = """MediathekAtlas {v} für Windows
=============================

Start: Startmenü → MediathekAtlas (der Browser öffnet sich von selbst).
Voraussetzung: Python 3.9 oder neuer. Fehlt es, bietet der Start die Installation über
winget an (oder öffnet python.org). Für Downloads wird ffmpeg empfohlen:
  winget install Gyan.FFmpeg

Daten (Katalog, Einstellungen, Protokolle): %LOCALAPPDATA%\\MediathekAtlas
Downloads (Standard): Benutzerordner\\Videos\\MediathekAtlas
Diagnose: Startmenü → MediathekAtlas → Diagnose erstellen (ZIP auf dem Desktop).
Deinstallation: Einstellungen → Apps, oder Startmenü → MediathekAtlas entfernen.
Die Daten bleiben bei Update und Deinstallation erhalten.

Portable Fassung (ZIP): Ordner entpacken und "MediathekAtlas starten.bat" doppelklicken.
"""

README_LINUX = """MediathekAtlas {v} für Linux
===========================

Debian, Ubuntu, Mint, Raspberry Pi OS:  sudo apt install ./mediathekatlas_{v}_all.deb
Andere Distributionen:  tar xzf MediathekAtlas_v{v}-Linux.tar.gz && ./MediathekAtlas_v{v}-Linux/install.sh
(ohne Root-Rechte, nur für den aktuellen Benutzer; Entfernen mit uninstall.sh)

Start über das Anwendungsmenü oder im Terminal: mediathekatlas
Ohne Fenster als Dienst des Benutzers: systemctl --user enable --now mediathekatlas
Diagnose: mediathekatlas --diagnose (ZIP auf dem Desktop bzw. im Home-Ordner)
Voraussetzung: python3 ab 3.9; empfohlen ffmpeg. Daten: ~/.mediathekatlas
"""


def stage_app(dest):
    build_nas.copy_app(dest)
    return dest


# ------------------------------------------------------------------ Windows

def build_windows(out_dir):
    stage = ROOT / 'build' / 'windows'
    if stage.exists():
        shutil.rmtree(stage)
    stage_app(stage / 'app')
    _write(stage / 'start.ps1', render((PACK / 'windows' / 'start.ps1').read_text('utf-8')), crlf=True)
    _write(stage / 'LIESMICH.txt', README_WIN.format(v=VERSION), crlf=True)
    ico(stage / 'mediathekatlas.ico')
    results = []
    # Portable ZIP: the same folder plus a double-click starter.
    bat = ('@echo off\r\ncd /d "%~dp0"\r\nstart "" powershell.exe -NoProfile -ExecutionPolicy Bypass '
           '-WindowStyle Hidden -File "%~dp0start.ps1"\r\n')
    zpath = out_dir / ('%s_v%s-Windows.zip' % (NAME, VERSION))
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        top = '%s_v%s' % (NAME, VERSION)
        for p in sorted(stage.rglob('*')):
            if p.is_file():
                z.write(p, top + '/' + p.relative_to(stage).as_posix())
        z.writestr(top + '/MediathekAtlas starten.bat', bat)
        z.writestr(top + '/Diagnose erstellen.bat', bat.replace('start.ps1"', 'start.ps1" -Diagnose'))
    results.append(zpath)
    makensis = shutil.which('makensis')
    if not makensis:
        print('WARNUNG: makensis fehlt – Windows-Setup.exe nicht gebaut (apt install nsis).')
        return results
    exe = out_dir / ('%s_v%s-Windows-Setup.exe' % (NAME, VERSION))
    parts = [int(x) for x in VERSION.split('.')[:3]] + [0]
    nsi = ROOT / 'build' / 'windows-installer.nsi'
    _write(nsi, render((PACK / 'windows' / 'installer.nsi').read_text('utf-8'), OUTFILE=exe, STAGE=stage,
                       ICON=stage / 'mediathekatlas.ico', VIVERSION='.'.join(map(str, parts[:4]))))
    subprocess.run([makensis, '-V2', str(nsi)], check=True)
    results.append(exe)
    return results


# ------------------------------------------------------------------ Linux

def _tar_add(tar, path, arcname):
    def reset(info):
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.mode = 0o755 if info.isdir() or info.name.endswith('.sh') else 0o644
        return info
    tar.add(path, arcname=arcname, filter=reset)


def build_deb(out_dir):
    stage = ROOT / 'build' / 'deb'
    if stage.exists():
        shutil.rmtree(stage)
    app = '/usr/lib/mediathekatlas'
    stage_app(stage / app.lstrip('/'))
    linux = PACK / 'linux'
    _write(stage / 'usr/bin/mediathekatlas', render((linux / 'mediathekatlas.sh').read_text('utf-8'), APP_DIR=app), 0o755)
    _write(stage / 'usr/share/applications/mediathekatlas.desktop',
           render((linux / 'mediathekatlas.desktop').read_text('utf-8'), EXEC='/usr/bin/mediathekatlas'))
    _write(stage / 'usr/lib/systemd/user/mediathekatlas.service',
           render((linux / 'mediathekatlas.service').read_text('utf-8'), EXEC='/usr/bin/mediathekatlas'))
    for size in (48, 128, 256):
        p = stage / ('usr/share/icons/hicolor/%dx%d/apps/mediathekatlas.png' % (size, size))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png(size))
    _write(stage / 'usr/share/doc/mediathekatlas/README', README_LINUX.format(v=VERSION))
    shutil.copy2(ROOT / 'LICENSE', stage / 'usr/share/doc/mediathekatlas/copyright')
    size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024 + 1
    control = ('Package: mediathekatlas\nVersion: %s\nArchitecture: all\nMaintainer: MediathekAtlas <noreply@mediathekatlas.invalid>\n'
               'Installed-Size: %d\nDepends: python3 (>= 3.9)\nRecommends: ffmpeg, xdg-utils\nSection: video\nPriority: optional\n'
               'Description: Katalog der Mediatheken und freien Film-Plattformen\n'
               ' Lokaler Server mit Web-Oberfläche: ARD, ZDF & Co., Netzkino, Pluto TV, Rakuten TV, Joyn,\n'
               ' YouTube und Archive.org durchsuchen, abspielen und geordnet herunterladen.\n') % (VERSION, size)
    _write(stage / 'DEBIAN/control', control)
    # Byte code of an older version is never left behind (the launcher copies a runtime anyway).
    _write(stage / 'DEBIAN/prerm', '#!/bin/sh\nset -e\nfind /usr/lib/mediathekatlas -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true\n', 0o755)
    for p in [stage, *stage.rglob('*')]:
        if p.is_dir():
            p.chmod(0o755)
    deb = out_dir / ('mediathekatlas_%s_all.deb' % VERSION)
    dpkg = shutil.which('dpkg-deb')
    if not dpkg:
        print('WARNUNG: dpkg-deb fehlt – .deb nicht gebaut.')
        return []
    subprocess.run([dpkg, '--root-owner-group', '-Zxz', '--build', str(stage), str(deb)], check=True,
                   stdout=subprocess.DEVNULL)
    return [deb]


def build_tarball(out_dir):
    top = '%s_v%s-Linux' % (NAME, VERSION)
    stage = ROOT / 'build' / 'linux' / top
    if stage.parent.exists():
        shutil.rmtree(stage.parent)
    stage_app(stage / 'app')
    linux = PACK / 'linux'
    for name in ('mediathekatlas.sh', 'mediathekatlas.desktop', 'mediathekatlas.service', 'install.sh', 'uninstall.sh'):
        _write(stage / name, render((linux / name).read_text('utf-8')), 0o755 if name.endswith('.sh') else 0o644)
    (stage / 'mediathekatlas.png').write_bytes(png(256))
    _write(stage / 'LIESMICH.txt', README_LINUX.format(v=VERSION))
    path = out_dir / (top + '.tar.gz')
    with tarfile.open(path, 'w:gz') as tar:
        _tar_add(tar, stage, top)
    return [path]


def main(out_dir=None):
    out_dir = Path(out_dir or ROOT / 'dist').resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    built = build_windows(out_dir) + build_deb(out_dir) + build_tarball(out_dir)
    for p in built:
        print(p)
    return built


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
