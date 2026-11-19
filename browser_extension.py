"""0.5.91: optionale Chrome-Erweiterung „MediathekAtlas Videostart“ als ZIP für die Weboberfläche.

Die Dateien liegen in web/browser-extension/chrome (kommen so in jedes Paket mit). Das ZIP enthält einen
Ordner „MediathekAtlas-Videostart“, den Chrome unter chrome://extensions → „Entpackte Erweiterung laden“
übernimmt. Die Versionsnummer der Erweiterung folgt der App-Version.

0.6.38 (Björn: „Installieren der Chrome-Erweiterung einfacher machen“): Im Desktopbetrieb legt die App die
Erweiterung selbst entpackt in einen festen Ordner im Startordner (provide) und schreibt ihn bei jedem Start
mit der aktuellen Fassung neu. Kein Download, kein Entpacken mehr; der Assistent zeigt den Ordner im
Finder/Explorer (reveal), von dort zieht man ihn auf chrome://extensions. Eine Webseite oder ein
Startbefehl darf chrome://extensions nicht öffnen (Chrome lässt chrome://-Adressen von außen nicht zu),
deshalb kopiert der Assistent die Adresse. Die geladene
Erweiterung meldet sich auf der MediathekAtlas-Seite (atlas_bridge.js) und lädt sich nach einem Update selbst
neu (background.js). Ohne Entwicklermodus geht es nur über den Chrome Web Store (Entwicklerkonto nötig).
"""
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

FOLDER = Path(__file__).parent / 'web' / 'browser-extension' / 'chrome'
TOP = 'MediathekAtlas-Videostart'
FILES = ('manifest.json', 'autostart.js', 'atlas_bridge.js', 'background.js', 'popup.html', 'popup.js', 'icons/icon16.png', 'icons/icon48.png', 'icons/icon128.png')
FIXED_TIME = (2026, 11, 13, 0, 0, 0)


def chrome_version(version):
    """Chrome accepts one to four dot-separated numbers (0..65535); '0.5.91-beta' -> '0.5.91'."""
    parts = re.findall(r'\d+', str(version or ''))[:4]
    return '.'.join(str(min(int(p), 65535)) for p in parts) or '0.0.0'


def _contents(version, folder=FOLDER):
    """(Name, Bytes) jeder Datei der Erweiterung, manifest.json mit der App-Version."""
    for name in FILES:
        data = (folder / name).read_bytes()
        if name == 'manifest.json':
            manifest = json.loads(data.decode('utf-8'))
            manifest['version'] = chrome_version(version)
            data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        yield name, data


def package(version, folder=FOLDER):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in _contents(version, folder):
            info = zipfile.ZipInfo('%s/%s' % (TOP, name), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buffer.getvalue()


# --- 0.6.38: entpackter Ordner für „Entpackte Erweiterung laden“ -------------------------------------------

def install_dir(home):
    """Fester Ort der entpackten Erweiterung: <Startordner>/Chrome-Erweiterung/MediathekAtlas-Videostart.

    Der Startordner (nicht der Datenordner) bleibt auch nach einem Umzug der Daten an seinem Platz, Chrome
    findet die Erweiterung also immer am selben Pfad."""
    return Path(home) / 'Chrome-Erweiterung' / TOP


def provide(version, home, folder=FOLDER):
    """Schreibt die Erweiterung entpackt nach install_dir(home). Nur geänderte Dateien werden ersetzt
    (über eine .partial-Datei, damit Chrome nie eine halbe Datei liest). Rückgabe: Pfad, Version, geändert."""
    target = install_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, data in _contents(version, folder):
        path = target / name
        try:
            if path.read_bytes() == data:
                continue
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + '.partial')
        part.write_bytes(data)
        os.replace(part, path)
        changed.append(name)
    # Dateien früherer Fassungen, die es nicht mehr gibt, entfernen (nur bekannte Endungen, nie Fremdes).
    keep = set(FILES)
    for path in sorted(target.rglob('*')):
        rel = path.relative_to(target).as_posix()
        if path.is_file() and rel not in keep and path.suffix in ('.js', '.json', '.html', '.png', '.partial'):
            try:
                path.unlink()
                changed.append('-' + rel)
            except OSError:
                pass
    return {'path': str(target), 'version': chrome_version(version), 'changed': changed}


def status(version, home, network=False):
    """Stand für den Einrichtungsassistenten."""
    out = {'version': chrome_version(version), 'local': not network, 'platform': sys.platform,
           'path': '', 'ready': False}
    if network:
        return out
    target = install_dir(home)
    out['path'] = str(target)
    try:
        manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
        out['ready'] = manifest.get('version') == out['version'] and all((target / f).is_file() for f in FILES)
    except (OSError, ValueError):
        pass
    return out


def reveal(path, runner=subprocess.Popen, platform=None):
    """Zeigt den Ordner im Finder/Explorer, markiert (zum Ziehen auf chrome://extensions). True = angezeigt."""
    platform = platform or sys.platform
    path = str(path)
    try:
        if platform == 'darwin':
            runner(['/usr/bin/open', '-R', path])
        elif platform.startswith('win'):
            runner(['explorer', '/select,', path])
        else:
            runner(['xdg-open', str(Path(path).parent)])
    except OSError:
        return False   # kein Dateimanager (z. B. Linux ohne Desktop): der Assistent zeigt den Pfad
    return True

