"""Samsung TV Plus: free live channels (FAST) for Germany (0.5.97).

Samsung TV Plus offers in Germany only live channels (no films or series on demand), about 216
stations with adverts in groups such as Filme, Serien, Dokus & Wissen, Kids, News, Sport.

Source of the channel list
    Samsung publishes no open API. The channel list comes from the public, daily updated
    collection at i.mjh.nz (``SamsungTVPlus/.channels.json.gz``), which Kodi add-ons and IPTV
    players use as well: per region name, number, group, logo, description and the programme of
    the next hours, plus ``license_url`` for channels that Samsung only delivers with Widevine.
    Playback goes through the redirect service named in that list (``jmp2.uk/stvp-<id>``), which
    answers with the official HLS address of the channel. Both services are small community
    projects; if they disappear the tab says so and the other providers keep working.

Copy protection
    Channels with ``license_url`` are Widevine protected. MediathekAtlas never circumvents copy
    protection: such channels are not listed, only counted ("16 Sender nur mit Kopierschutz").
    Every other stream is checked with hls_guard before playback (no DRM key in the playlist).

Nothing is stored offline (live streams). The list is kept in ``samsung_tvplus.json`` in the
data folder and refreshed every 12 hours by default (it is small: about 0.5 MB packed).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KEY = 'samsung'
NAME = 'Samsung TV Plus'
DATA_URL = 'https://i.mjh.nz/SamsungTVPlus/.channels.json.gz'
PLAY_URL = 'https://jmp2.uk/{slug}'
REGION = 'de'
REGIONS = ('de', 'at', 'ch')
FILE = 'samsung_tvplus.json'
MAX_ANSWER = 16 * 1024 * 1024      # packed and unpacked
MAX_CHANNELS = 2000
MAX_PROGRAMS = 16                  # programme entries kept per channel (the next hours)
REFRESH = 12 * 3600                # the programme only covers about one day
RETRY = 30 * 60
SOURCE_TTL = 120
USER_AGENT = 'okhttp/4.12.0'       # as named by the list for playback ("headers")
VALID_ID = re.compile(r'[A-Za-z0-9]{4,40}')
VALID_SLUG = re.compile(r'[a-z0-9\-]{0,40}\{id\}[a-z0-9\-.]{0,20}')
SITE = 'https://www.samsungtvplus.com/'
DRM_NOTE = ('Samsung TV Plus liefert diesen Sender nur mit Kopierschutz (Widevine) aus. '
            'MediathekAtlas umgeht ihn nicht; bitte in der Samsung-TV-Plus-App ansehen.')

_LOCK = threading.Lock()           # file access
_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_SOURCES = {}                      # channel id -> (valid until, resolved HLS address)


def _notify(event, **details):
    """Technical counters only; never URLs or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _int(value, low=None, high=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def _https(value):
    value = str(value or '').strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or re.search(r'[\s<>"\']', value):
        return ''
    return value[:600]


# ---------------------------------------------------------------- storage

def _path(root):
    return Path(root) / FILE


def _empty():
    return {'auto': True, 'region': REGION, 'channels': [], 'protected': 0, 'slug': 'stvp-{id}',
            'last_attempt': 0.0, 'last_success': 0.0, 'next_attempt': 0.0, 'last_result': 'never',
            'last_error': '', 'last_http_status': 0}


def _load(root):
    with _LOCK:
        try:
            data = json.loads(_path(root).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    out.update({k: data[k] for k in out if k in data})
    if not isinstance(out['channels'], list):
        out['channels'] = []
    return out


def _save(root, data):
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with _LOCK:
        fd, tmp = tempfile.mkstemp(prefix='.samsung_tvplus.', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            if os.name != 'nt':
                os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _update(root, **values):
    data = _load(root)
    data.update(values)
    _save(root, data)
    return data


# ---------------------------------------------------------------- network

def _fetch(url=DATA_URL):
    """The packed channel list (fixed address, size limited)."""
    req = urllib.request.Request(url, headers={'User-Agent': 'MediathekAtlas', 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=40) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > MAX_ANSWER:
            raise ValueError('Senderliste zu groß')
        raw = response.read(MAX_ANSWER + 1)
    if len(raw) > MAX_ANSWER:
        raise ValueError('Senderliste zu groß')
    if raw[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=__import__('io').BytesIO(raw)) as packed:
            raw = packed.read(MAX_ANSWER + 1)
        if len(raw) > MAX_ANSWER:
            raise ValueError('Senderliste zu groß')
    return json.loads(raw.decode('utf-8'))


def _error(exc):
    code = getattr(exc, 'code', None)
    if code:
        return 'Senderliste von Samsung TV Plus antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Senderliste von Samsung TV Plus (i.mjh.nz) ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Senderliste von Samsung TV Plus konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def _programs(rows, now):
    """[[start, title], …] -> the entry running now and the following ones."""
    out = []
    if not isinstance(rows, list):
        return out
    clean = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        start = _int(row[0], 0, 4102444800)
        title = _text(row[1], 160)
        if start is not None and title:
            clean.append((start, title))
    clean.sort()
    for i, (start, title) in enumerate(clean):
        end = clean[i + 1][0] if i + 1 < len(clean) else start + 3600
        if end <= now:
            continue
        out.append([start, title])
        if len(out) >= MAX_PROGRAMS:
            break
    return out


def parse(data, region=REGION, now=None):
    """Channel list of one region -> (channels, protected count, slug pattern)."""
    now = time.time() if now is None else now
    if not isinstance(data, dict) or not isinstance(data.get('regions'), dict):
        raise ValueError('Samsung TV Plus: unerwartetes Format der Senderliste')
    node = data['regions'].get(region)
    if not isinstance(node, dict) or not isinstance(node.get('channels'), dict):
        raise ValueError('Samsung TV Plus: keine Sender für die Region %s' % region.upper())
    slug = str(data.get('slug') or 'stvp-{id}')
    if not VALID_SLUG.fullmatch(slug):
        raise ValueError('Samsung TV Plus: unerwartetes Adressmuster in der Senderliste')
    channels, protected = [], 0
    for ident, row in node['channels'].items():
        if len(channels) >= MAX_CHANNELS:
            break
        if not VALID_ID.fullmatch(str(ident)) or not isinstance(row, dict):
            continue
        title = _text(row.get('name'), 160)
        if not title:
            continue
        if row.get('license_url'):
            protected += 1      # Widevine: not listed, never circumvented
            continue
        channels.append({'id': str(ident), 'title': title, 'number': _int(row.get('chno'), 0, 999999),
                         'group': _text(row.get('group'), 60) or NAME, 'logo': _https(row.get('logo')),
                         'summary': _text(row.get('description'), 600),
                         'programs': _programs(row.get('programs'), now)})
    channels.sort(key=lambda c: (c['number'] if c['number'] is not None else 1e9, c['title'].casefold()))
    return channels, protected, slug


def sync(root, fetch=None, now=None):
    """Load the channel list once; the stored list stays when the run fails."""
    now = time.time() if now is None else now
    current = _load(root)
    region = current['region'] if current['region'] in REGIONS else REGION
    _update(root, last_attempt=now, last_result='running')
    try:
        channels, protected, slug = parse((fetch or _fetch)(), region, now)
        if not channels:
            raise ValueError('Samsung TV Plus lieferte keine Sender ohne Kopierschutz')
    except Exception as exc:
        message = _error(exc)
        _update(root, last_result='error', last_error=message, last_http_status=getattr(exc, 'code', 0) or 0,
                next_attempt=now + RETRY)
        _notify('samsung_catalog_failed', level='WARNING', http=getattr(exc, 'code', 0) or 0)
        return {'ok': False, 'error': message}
    _SOURCES.clear()
    _update(root, channels=channels, protected=protected, slug=slug, last_success=now, last_result='ok',
            last_error='', last_http_status=0, next_attempt=now + REFRESH)
    _notify('samsung_catalog_loaded', channels=len(channels), protected=protected)
    return {'ok': True, 'channels': len(channels), 'protected': protected}


# ---------------------------------------------------------------- reading

def now_next(programs, now=None):
    """('Jetzt: …', 'Danach: …') text of the stored programme, '' when nothing is known."""
    now = time.time() if now is None else now
    rows = [p for p in programs or [] if isinstance(p, list) and len(p) == 2]
    for i, (start, title) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else start + 3600
        if start <= now < end:
            text = 'Jetzt: ' + title
            if i + 1 < len(rows):
                text += ' · danach %s %s' % (time.strftime('%H:%M', time.localtime(rows[i + 1][0])), rows[i + 1][1])
            return text
    if rows and rows[0][0] > now:
        return 'Ab %s: %s' % (time.strftime('%H:%M', time.localtime(rows[0][0])), rows[0][1])
    return ''


def channels(root, now=None):
    """Stored channels for the Live-TV tab (live_tv.samsung_channels); no network."""
    out = []
    for row in _load(root)['channels']:
        if not isinstance(row, dict) or not VALID_ID.fullmatch(str(row.get('id', ''))):
            continue
        current = now_next(row.get('programs'), now)
        summary = row.get('summary') or ''
        out.append({'id': row['id'], 'title': row.get('title') or 'Sender', 'number': row.get('number'),
                    'category': row.get('group') or NAME, 'poster': row.get('logo') or '',
                    'summary': (current + (' — ' if current and summary else '') + summary) if current else summary})
    return out


def state(root):
    data = _load(root)
    return {'running': _ACTIVE, 'auto': bool(data['auto']), 'region': data['region'],
            'last_attempt': float(data['last_attempt'] or 0), 'last_success': float(data['last_success'] or 0),
            'next_attempt': float(data['next_attempt'] or 0),
            'last_result': 'interrupted' if data['last_result'] == 'running' and not _ACTIVE else data['last_result'],
            'last_error': data['last_error'], 'last_http_status': int(data['last_http_status'] or 0),
            'channels': len(data['channels']), 'protected': int(data['protected'] or 0)}


def set_auto(root, enabled):
    if type(enabled) is not bool:
        raise ValueError('Automatik muss ausdrücklich ein- oder ausgeschaltet werden')
    _update(root, auto=enabled)
    return state(root)


def set_region(root, region):
    region = str(region or '').lower()
    if region not in REGIONS:
        raise ValueError('Unbekannte Region; erlaubt sind ' + ', '.join(r.upper() for r in REGIONS))
    _update(root, region=region, next_attempt=0.0)
    return state(root)


def _run(root):
    global _ACTIVE
    try:
        sync(root)
    except Exception as exc:          # never leave the switch on
        _update(root, last_result='error', last_error=_error(exc))
    finally:
        with _SYNC_LOCK:
            _ACTIVE = False


def start_sync(root):
    global _ACTIVE
    with _SYNC_LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True
    threading.Thread(target=_run, args=(root,), daemon=True, name='samsung_catalog_sync').start()
    return True


def due(current, now=None):
    """Load on the first start, then every 12 hours while the automatic switch is on."""
    now = time.time() if now is None else now
    if current['running']:
        return False
    if not current['last_success'] and not current['last_attempt']:
        return True
    return bool(current['auto']) and now >= current['next_attempt']


def loop(root, stop):
    import task_control
    if not stop.wait(20) and due(state(root)):
        start_sync(root)
    while not stop.wait(60):
        if task_control.paused('catalog:' + KEY):
            continue
        if due(state(root)):
            start_sync(root)


# ---------------------------------------------------------------- playback

def _resolve(url):
    """Follow the redirect service to the channel's HLS address (HTTPS only, nothing read beyond the header)."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=20) as response:
        final = response.geturl()
    if not _https(final):
        raise ValueError('Samsung TV Plus lieferte keine sichere Stream-Adresse')
    return final


def play_source(root, item_id, resolver=None, check=None, now=None):
    """Source for streaming.plan: HLS, checked for copy protection, adverts included."""
    import hls_guard
    item_id = str(item_id or '')
    if not VALID_ID.fullmatch(item_id):
        raise ValueError('Ungültiger Samsung-TV-Plus-Sender')
    now = time.time() if now is None else now
    data = _load(root)
    row = next((r for r in data['channels'] if isinstance(r, dict) and r.get('id') == item_id), None)
    if not row:
        raise ValueError('Sender nicht in der Samsung-TV-Plus-Liste; bitte Senderliste neu laden')
    slug = data['slug'] if VALID_SLUG.fullmatch(str(data['slug'])) else 'stvp-{id}'
    cached = _SOURCES.get(item_id)
    if cached and cached[0] > now:
        url = cached[1]
    else:
        try:
            url = (resolver or _resolve)(PLAY_URL.format(slug=slug.format(id=item_id)))
            (check or hls_guard.check)(url)
        except hls_guard.DrmProtected:
            raise hls_guard.DrmProtected(DRM_NOTE) from None
        except urllib.error.HTTPError as exc:
            raise ValueError('Samsung TV Plus: Sender gerade nicht abrufbar (HTTP %d)' % exc.code) from None
        except (urllib.error.URLError, OSError) as exc:
            import netcheck
            raise ValueError(netcheck.with_cause('Samsung TV Plus ist nicht erreichbar', exc)) from None
        _SOURCES[item_id] = (now + SOURCE_TTL, url)
    title = ('%s · %s' % (row['number'], row['title'])) if row.get('number') else row['title']
    return {'kind': 'url', 'url': url, 'hls': True, 'quality': 'Samsung TV Plus live (kostenlos, mit Werbung)',
            'title': title, 'duration': 0, 'provider': KEY, 'live': True}


def summary(root):
    """Counters for the diagnosis export; no titles or addresses."""
    current = state(root)
    return {k: current[k] for k in ('running', 'auto', 'region', 'last_success', 'last_result', 'last_error',
                                    'last_http_status', 'channels', 'protected')}
