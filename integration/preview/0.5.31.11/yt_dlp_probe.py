"""Optional, explicitly user-initiated yt-dlp metadata-only Netzkino validation.

Never fetch, export, log, or persist streaming URLs/format manifests, cookies,
DRM secrets, provider tokens or downloadable formats. Not a download capability.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from urllib.parse import urlsplit

MAX_OUTPUT_BYTES = 3 * 1024 * 1024
MAX_TEXT = 1600
MAX_PEOPLE = 16
TIMEOUT = 32


def safe_netmovie(url):
    if not isinstance(url, str) or len(url) > 900:
        raise ValueError('Netzkino-Adresse ungültig')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in ('netzkino.de', 'www.netzkino.de')
            or p.username or p.password or p.port not in (None, 443)
            or not re.fullmatch(r'/details/[A-Za-z0-9._~-]{2,150}', p.path)
            or p.query or p.fragment):
        raise ValueError('Nur öffentliche Netzkino-Filmseiten sind zulässig')
    return 'https://www.netzkino.de' + p.path


def _text(v, limit=MAX_TEXT):
    return ' '.join(v.split())[:limit] if isinstance(v, str) else ''


def _int(v, low, high):
    try:
        i = int(v)
        return i if low <= i <= high else None
    except (TypeError, ValueError):
        return None


def _strings(values):
    if not isinstance(values, list):
        return []
    result = []
    for v in values[:60]:
        s = _text(v, 120)
        if s and s not in result:
            result.append(s)
        if len(result) >= MAX_PEOPLE:
            break
    return result


def sanitize(data):
    if not isinstance(data, dict):
        raise ValueError('Antwort enthält kein Metadatenobjekt')
    # STRICT whitelist. Do not add 'formats', 'url', 'manifest_url', 'http_headers',
    # 'subtitles', cookies or arbitrary nested extractor objects.
    raw_date = data.get('release_date')
    guessed_year = str(raw_date)[:4] if raw_date else None
    return {
        'provider': 'yt-dlp:netzkino',
        'title': _text(data.get('title'), 220),
        'original_title': _text(data.get('alt_title'), 220),
        'year': _int(data.get('release_year') or guessed_year, 1800, 2100),
        'duration_seconds': _int(data.get('duration'), 1, 86400),
        'fsk': _int(data.get('age_limit'), 0, 18),
        'description': _text(data.get('description'), 2200),
        'country': _text(data.get('location'), 80),
        'cast': _strings(data.get('cast')),
        'creators': _strings(data.get('creators')),
        'categories': _strings(data.get('categories')),
        'series': _text(data.get('series'), 220),
        'season_number': _int(data.get('season_number'), 0, 99),
        'episode_number': _int(data.get('episode_number'), 1, 10000),
        'identity_verified': False,
        'rights_verified': False,
        'format_verified': False,
    }


def compare(editorial, observed):
    """Only report discrepancies; do not override stored metadata or work identities."""
    warnings = []
    def norm(s):
        return re.sub(r'\W+', '', str(s or '').casefold())
    a, b = editorial or {}, observed or {}
    if a.get('original_title') and b.get('original_title') and norm(a['original_title']) != norm(b['original_title']):
        warnings.append('Originaltitel weichen ab')
    if a.get('year') and b.get('year') and int(a['year']) != int(b['year']):
        warnings.append('Produktionsjahre weichen ab')
    if a.get('duration_seconds') and b.get('duration_seconds'):
        left, right = int(a['duration_seconds']), int(b['duration_seconds'])
        if abs(left - right) >= max(180, left * .20):
            warnings.append('Signifikant unterschiedliche Laufzeiten')
    return warnings


def probe(url, editor=None, *, runner=None, executable=None):
    """Simulated extraction; optional installed CLI. Never download a media file.

    The CLI may access provider websites for metadata; call only after user click.
    Its untrusted raw JSON stays in memory and is never returned or logged.
    """
    safe_url = safe_netmovie(url)
    exe = executable if executable is not None else shutil.which('yt-dlp')
    if not exe:
        return {'status':'not_installed','error':'yt-dlp nicht installiert', 'metadata':None, 'warnings':[]}
    cmd = [exe, '--ignore-config', '--no-playlist', '--no-cache-dir',
           '--skip-download', '--no-check-formats', '--dump-single-json', safe_url]
    try:
        proc = (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                check=False, env={**os.environ, 'PYTHONIOENCODING':'utf-8'})
    except subprocess.TimeoutExpired:
        return {'status':'timeout','error':'Metadatenprüfung überschritt das Zeitlimit', 'metadata':None, 'warnings':[]}
    except (OSError, ValueError):
        return {'status':'unavailable','error':'yt-dlp konnte nicht gestartet werden','metadata':None,'warnings':[]}
    if proc.returncode != 0:
        # STDERR may contain full signed URLs; never expose it to the UI/logs.
        return {'status':'provider_error','error':'Netzkino-Extractor meldet einen Fehler','metadata':None,'warnings':[]}
    output = proc.stdout
    if not isinstance(output, str) or len(output.encode('utf-8')) > MAX_OUTPUT_BYTES:
        return {'status':'invalid_response','error':'Antwort zu groß oder unlesbar','metadata':None,'warnings':[]}
    try:
        result = sanitize(json.loads(output))
    except (ValueError, TypeError):
        return {'status':'invalid_response','error':'Unbekanntes Metadatenformat','metadata':None,'warnings':[]}
    if not result['title']:
        return {'status':'invalid_response','error':'Metadatentitel fehlt','metadata':None,'warnings':[]}
    return {'status':'ok','error':'','metadata':result,
            'warnings':compare(editor or {},result),
            'note':'Technische Extraktion und Metadatenzugriff sind kein Nachweis von Download- oder Wiedergaberechten.'}
