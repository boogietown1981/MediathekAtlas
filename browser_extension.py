"""0.5.91: optionale Chrome-Erweiterung „MediathekAtlas Videostart“ als ZIP für die Weboberfläche.

Die Dateien liegen in web/browser-extension/chrome (kommen so in jedes Paket mit). Das ZIP enthält einen
Ordner „MediathekAtlas-Videostart“, den Chrome unter chrome://extensions → „Entpackte Erweiterung laden“
übernimmt. Die Versionsnummer der Erweiterung folgt der App-Version.
"""
import io
import json
import re
import zipfile
from pathlib import Path

FOLDER = Path(__file__).parent / 'web' / 'browser-extension' / 'chrome'
TOP = 'MediathekAtlas-Videostart'
FILES = ('manifest.json', 'autostart.js', 'popup.html', 'popup.js', 'icons/icon16.png', 'icons/icon48.png', 'icons/icon128.png')
FIXED_TIME = (2026, 11, 13, 0, 0, 0)


def chrome_version(version):
    """Chrome accepts one to four dot-separated numbers (0..65535); '0.5.91-beta' -> '0.5.91'."""
    parts = re.findall(r'\d+', str(version or ''))[:4]
    return '.'.join(str(min(int(p), 65535)) for p in parts) or '0.0.0'


def package(version, folder=FOLDER):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            data = (folder / name).read_bytes()
            if name == 'manifest.json':
                manifest = json.loads(data.decode('utf-8'))
                manifest['version'] = chrome_version(version)
                data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            info = zipfile.ZipInfo('%s/%s' % (TOP, name), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buffer.getvalue()
