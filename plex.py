"""Plex: the free films, series and live channels of Plex ("Kostenlos auf Plex") (0.5.98).

Björn (13.11.2026): connect further free streaming services, Plex second after Samsung TV Plus.
No Plex account and no Plex Media Server are needed: the website watch.plex.tv works with an
anonymous token, and so does MediathekAtlas.

Interfaces (from public open-source clients, e.g. the Kodi add-ons of SlyGuy and MovieScout, the
FastChannels scraper and Plex's own python-plexapi; not recorded live, Plex is blocked in the build
environment):

* Token: ``POST https://plex.tv/api/v2/users/anonymous`` with ``X-Plex-Product`` and a fixed
  ``X-Plex-Client-Identifier`` -> ``authToken``. Kept in plex.sqlite3 (never logged, never shown).
* Films and series: ``https://vod.provider.plex.tv`` answers like a Plex Media Server.
  ``/library/sections`` lists the sections (``Directory`` with ``key`` and ``type`` movie/show);
  ``/library/sections/<key>/all`` pages through a section with ``X-Plex-Container-Start/Size``.
  If a section does not answer ``/all``, its hubs (``/hubs/sections/<key>``) are read instead.
  Episodes: ``/library/metadata/<ratingKey>/allLeaves``. Streams: ``/library/metadata/<ratingKey>``
  -> ``Media[].Part[].key`` (mostly DASH, ``container`` mpd). A part with a ``license`` (Widevine)
  or ``drm`` is protected: no player, no offline copy, only "Bei Plex ansehen". Every other stream
  is checked before playback (DASH: ``ContentProtection``; HLS: hls_guard) and runs through ffmpeg.
* Live: ``https://epg.provider.plex.tv/lineups/plex/channels`` (``Channel`` with ``id``, ``title``,
  ``thumb``, ``summary``); stream ``/library/parts/<id>.m3u8`` -> redirect to an HLS address.

The catalogue offered depends on the country of the internet connection (Plex decides). Reference
checks (IMDb/TVDB/TMDB/OMDb/Wikidata) use the shared portal_enrichment engine. Titles, tokens and
URLs never go to logs or the diagnosis export.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import portal_reference

KEY = 'plex'
NAME = 'Plex'
AUTH_URL = 'https://plex.tv/api/v2/users/anonymous'
VOD = 'https://vod.provider.plex.tv'
EPG = 'https://epg.provider.plex.tv'
SITE = 'https://watch.plex.tv'
PRODUCT = 'Plex Mediaverse'
API_HOSTS = frozenset({'plex.tv', 'vod.provider.plex.tv', 'epg.provider.plex.tv'})
MAX_ANSWER = 32 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_ITEMS = 40000
PAGE = 100
MAX_PAGES = 400
REQUEST_GAP = 0.4
SERIES_TTL = 6 * 3600
SOURCE_TTL = 120
TOKEN_TTL = 7 * 24 * 3600
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
VALID_ID = re.compile(r'[msec]\.[A-Za-z0-9][A-Za-z0-9\-_]{2,90}')
VALID_KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-_]{2,90}')
PART_PATH = re.compile(r'/library/parts/[A-Za-z0-9\-_./]{1,300}')
SLUG = re.compile(r'[a-z0-9][a-z0-9\-]{0,200}')
KIND_PREFIX = {'movie': 'm', 'series': 's', 'episode': 'e', 'channel': 'c'}
DRM_NOTE = ('Plex liefert diesen Titel nur mit Kopierschutz (Widevine) aus. MediathekAtlas umgeht ihn nicht: '
            'bitte bei Plex ansehen.')
_CENC = re.compile(r'<(?:\w+:)?ContentProtection\b', re.I)

_SOURCES = {}
_TOKEN_LOCK = threading.Lock()
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS plex_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '',
  playable INTEGER NOT NULL DEFAULT 1, drm INTEGER NOT NULL DEFAULT -1, web_url TEXT NOT NULL DEFAULT '',
  seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS plex_items_kind ON plex_items(kind, seen);
CREATE INDEX IF NOT EXISTS plex_items_series ON plex_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS plex_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    """Technical counters only; never URLs, tokens or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'plex.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)       # holds the anonymous token
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM plex_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO plex_state(name,value) VALUES(?,?)', (key, str(value)))


def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _int(value, low=None, high=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def _float(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


# ---------------------------------------------------------------- network

def client_id(root):
    """One fixed client identifier per installation (Plex ties the anonymous token to it)."""
    db = _connect(root)
    try:
        value = _get(db, 'client_id')
        if not re.fullmatch(r'[a-f0-9\-]{36}', value):
            value = str(uuid.uuid4())
            with db:
                _set(db, 'client_id', value)
        return value
    finally:
        db.close()


def _headers(cid, token=''):
    out = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',
           'X-Plex-Product': PRODUCT, 'X-Plex-Client-Identifier': cid, 'X-Plex-Language': 'de',
           'X-Plex-Platform': 'Chrome', 'X-Plex-Device': 'MediathekAtlas',
           'Origin': SITE, 'Referer': SITE + '/'}
    if token:
        out['X-Plex-Token'] = token
    return out


def _open(url, headers, data=None, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS:
        raise ValueError('Ungültige Plex-Anfrage')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('Plex-Antwort zu groß')
        raw = response.read(limit + 1)
        final = response.geturl()
    if len(raw) > limit:
        raise ValueError('Plex-Antwort zu groß')
    return raw, final


def _new_token(cid):
    raw, _ = _open(AUTH_URL, _headers(cid), data=b'')
    answer = json.loads(raw.decode('utf-8'))
    token = str((answer or {}).get('authToken') or '') if isinstance(answer, dict) else ''
    if not re.fullmatch(r'[A-Za-z0-9_\-.]{8,400}', token):
        raise ValueError('Plex gab keinen Gast-Zugang aus')
    return token


def session(root, fetch_token=None, now=None, force=False):
    """(client id, anonymous token); renewed after a week or when Plex refuses it."""
    now = time.time() if now is None else now
    cid = client_id(root)
    with _TOKEN_LOCK:
        db = _connect(root)
        try:
            token, made = _get(db, 'token'), float(_get(db, 'token_made', '0') or 0)
        finally:
            db.close()
        if force or not token or now - made > TOKEN_TTL:
            token = (fetch_token or _new_token)(cid)
            db = _connect(root)
            try:
                with db:
                    _set(db, 'token', token)
                    _set(db, 'token_made', now)
            finally:
                db.close()
    return cid, token


class Api:
    """JSON requests to the fixed Plex hosts with the anonymous token (one renewal on 401)."""

    def __init__(self, root, opener=None, fetch_token=None):
        self.root, self.opener, self.fetch_token = root, opener or _open, fetch_token
        self.cid, self.token = session(root, fetch_token)

    def url(self, base, path, query=None):
        if not re.fullmatch(r'/[A-Za-z0-9\-_./]{1,300}', path) or '..' in path:
            raise ValueError('Ungültige Plex-Anfrage')
        return base + path + ('?' + urllib.parse.urlencode(query) if query else '')

    def get(self, base, path, query=None):
        for attempt in (0, 1):
            try:
                raw, _ = self.opener(self.url(base, path, query), _headers(self.cid, self.token))
                return json.loads(raw.decode('utf-8'))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403) and attempt == 0:
                    self.cid, self.token = session(self.root, self.fetch_token, force=True)
                    continue
                raise


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return 'Plex verweigert den Zugriff (HTTP %d)' % code
    if code == 451:
        return 'Plex bietet seine Gratis-Inhalte in diesem Land nicht an (HTTP 451)'
    if code:
        return 'Plex antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Plex ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Plex-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def _list(node, key):
    value = node.get(key) if isinstance(node, dict) else None
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def _container(answer):
    return answer.get('MediaContainer') if isinstance(answer, dict) and isinstance(answer.get('MediaContainer'), dict) else {}


def image(value):
    """Artwork with an absolute https address (Plex's metadata/image CDN). Relative paths need the
    token and are left out so that no token ever reaches the page."""
    value = str(value or '').strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.port or parts.username or len(value) > 600 \
            or re.search(r'[\s<>"\']', value) or re.search(r'(?i)token', parts.query):
        return ''
    return value


def _tags(node, key, limit=12):
    out = []
    for g in _list(node, key):
        name = _text(g.get('tag') if isinstance(g, dict) else g, 60)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _imdb(node):
    for g in _list(node, 'Guid'):
        match = re.fullmatch(r'imdb://(tt\d{5,10})', str((g or {}).get('id') or ''))
        if match:
            return match.group(1)
    match = re.search(r'imdb://(tt\d{5,10})', str(node.get('guid') or ''))
    return match.group(1) if match else ''


def _score(node):
    """Plex shows the audience or critics rating of IMDb/TMDb/Rotten Tomatoes (0-10)."""
    for r in _list(node, 'Rating'):
        if isinstance(r, dict) and 'imdb' in str(r.get('image') or '').lower():
            return _float(r.get('value'), 0, 10)
    return _float(node.get('audienceRating'), 0, 10) if 'imdb' in str(node.get('audienceRatingImage') or '').lower() else None


def _age(value):
    """Plex writes 'de/12' or 'TV-14': German ratings become 'FSK 12'."""
    value = _text(value, 20)
    match = re.fullmatch(r'(?i)de/(?:fsk[- ]?)?(\d{1,2})', value)
    return 'FSK ' + match.group(1) if match else re.sub(r'^[a-z]{2}/', '', value)


def _slug(node):
    slug = str(node.get('slug') or '')
    return slug if SLUG.fullmatch(slug) else ''


def web_url(kind, slug):
    if not SLUG.fullmatch(str(slug or '')):
        return ''
    return '%s/de/%s/%s' % (SITE, 'movie' if kind == 'movie' else 'show', slug)


def _key(node):
    key = str(node.get('ratingKey') or '')
    if not key:
        key = str(node.get('key') or '').rstrip('/').split('/')[-1]
        key = key if key != 'children' else ''
    return key if VALID_KEY.fullmatch(key) else ''


def item_from(node):
    """Film or series from a section or hub entry; None for anything else."""
    if not isinstance(node, dict):
        return None
    kind = {'movie': 'movie', 'show': 'series'}.get(str(node.get('type') or ''))
    key, title = _key(node), _text(node.get('title'), 200)
    if not kind or not key or not title:
        return None
    duration = _int(node.get('duration'), 1000, 24 * 3600 * 1000)
    genres = _tags(node, 'Genre')
    slug = _slug(node)
    return {'id': KIND_PREFIX[kind] + '.' + key, 'kind': kind, 'title': title, 'path': key, 'series_id': '',
            'season': None, 'episode': None, 'year': _int(node.get('year'), 1880, 2100),
            'duration': duration // 1000 if duration and kind == 'movie' else None,
            'rating': _age(node.get('contentRating')), 'genre': ', '.join(genres),
            'summary': _text(node.get('summary') or node.get('tagline'), 1600),
            'poster': image(node.get('thumb')) or image(node.get('art')), 'imdb_id': _imdb(node),
            'imdb_score': _score(node), 'imdb_votes': None, 'number': None, 'category': genres[0] if genres else '',
            'playable': 1, 'drm': -1, 'web_url': web_url(kind, slug)}


def episode_from(node, series):
    if not isinstance(node, dict) or str(node.get('type') or '') != 'episode':
        return None
    key = _key(node)
    if not key:
        return None
    duration = _int(node.get('duration'), 1000, 24 * 3600 * 1000)
    return {'id': 'e.' + key, 'kind': 'episode', 'title': _text(node.get('title'), 200) or 'Folge', 'path': key,
            'series_id': series['id'], 'season': _int(node.get('parentIndex'), 0, 999),
            'episode': _int(node.get('index'), 0, 9999), 'year': _int(node.get('year'), 1880, 2100),
            'duration': duration // 1000 if duration else None, 'rating': _age(node.get('contentRating')),
            'genre': '', 'summary': _text(node.get('summary'), 1600),
            'poster': image(node.get('thumb')) or image(node.get('grandparentThumb')), 'imdb_id': '',
            'imdb_score': None, 'imdb_votes': None, 'number': None, 'category': '', 'playable': 1, 'drm': -1,
            'web_url': series.get('web_url') or ''}


def channel_from(node):
    if not isinstance(node, dict):
        return None
    ident = str(node.get('id') or node.get('gridKey') or '')
    title = _text(node.get('title') or node.get('callSign'), 200)
    if not title or not VALID_KEY.fullmatch(ident):
        return None
    genres = _tags(node, 'Genre') or ([_text(node.get('genre'), 60)] if node.get('genre') else [])
    return {'id': 'c.' + ident, 'kind': 'channel', 'title': title, 'path': ident, 'series_id': '', 'season': None,
            'episode': None, 'year': None, 'duration': None, 'rating': '', 'genre': ', '.join(genres),
            'summary': _text(node.get('summary'), 600), 'poster': image(node.get('thumb') or node.get('logo')),
            'imdb_id': '', 'imdb_score': None, 'imdb_votes': None,
            'number': _int(node.get('vcn') or node.get('channelVcn'), 0, 100000), 'category': genres[0] if genres else '',
            'playable': 1, 'drm': 1 if node.get('drm') in (True, 1, '1', 'true') else -1,
            'web_url': '%s/de/live-tv/channel/%s' % (SITE, _slug(node)) if _slug(node) else SITE + '/de/live-tv'}


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'playable', 'drm',
          'web_url')
# What a catalogue run must not reset: copy protection learnt at playback.
_KEEP = ('drm', 'playable')


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS if f not in _KEEP)
    for item in items:
        db.execute('''INSERT INTO plex_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def sections(api):
    out = []
    for d in _list(_container(api.get(VOD, '/library/sections')), 'Directory'):
        if isinstance(d, dict) and d.get('type') in ('movie', 'show'):
            key = str(d.get('key') or '').rstrip('/').split('/')[-1]
            if VALID_KEY.fullmatch(key):
                out.append((key, d['type']))
    return out


def _page_all(api, key, gap, found):
    """All entries of one section through /all; False when it stopped early."""
    start, pages = 0, 0
    while pages < MAX_PAGES and len(found) < MAX_ITEMS:
        box = _container(api.get(VOD, '/library/sections/%s/all' % key,
                                 {'X-Plex-Container-Start': start, 'X-Plex-Container-Size': PAGE, 'includeGuids': 1}))
        entries = _list(box, 'Metadata')
        for node in entries:
            it = item_from(node)
            if it:
                found.setdefault(it['id'], it)
        total = _int(box.get('totalSize'), 0) or 0
        start += len(entries)
        pages += 1
        if not entries or (total and start >= total) or (not total and len(entries) < PAGE):
            return True
        if gap:
            time.sleep(gap)
    return False


def _page_hubs(api, key, gap, found):
    """Fallback: every hub of a section, each paged."""
    hubs = _list(_container(api.get(VOD, '/hubs/sections/%s' % key, {'count': PAGE})), 'Hub')
    for hub in hubs[:60]:
        for node in _list(hub, 'Metadata'):
            it = item_from(node)
            if it:
                found.setdefault(it['id'], it)
        path = str(hub.get('key') or '').split('?')[0]
        if not re.fullmatch(r'/[A-Za-z0-9\-_./]{1,200}', path) or not hub.get('more'):
            continue
        start = len(_list(hub, 'Metadata'))
        for _ in range(40):
            if gap:
                time.sleep(gap)
            entries = _list(_container(api.get(VOD, path, {'X-Plex-Container-Start': start,
                                                            'X-Plex-Container-Size': PAGE})), 'Metadata')
            for node in entries:
                it = item_from(node)
                if it:
                    found.setdefault(it['id'], it)
            start += len(entries)
            if len(entries) < PAGE or len(found) >= MAX_ITEMS:
                break
    return True


def _load_live(api):
    found = {}
    for node in _list(_container(api.get(EPG, '/lineups/plex/channels')), 'Channel')[:3000]:
        ch = channel_from(node)
        if ch:
            found.setdefault(ch['id'], ch)
    return found


def sync(root, opener=None, fetch_token=None, now=None, gap=None):
    """Load all free films, series and live channels. Rows stay, but only titles seen in the
    latest successful run are listed (the free catalogue rotates)."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('plex_sync_started')
    try:
        api = Api(root, opener, fetch_token)
        found, partial, notes = {}, False, []
        try:
            for key, _ in sections(api):
                try:
                    try:
                        complete = _page_all(api, key, gap, found)
                    except urllib.error.HTTPError as exc:
                        if exc.code not in (400, 404):
                            raise
                        complete = _page_hubs(api, key, gap, found)
                    partial |= not complete
                except Exception as exc:
                    partial = True
                    notes.append(_error(exc))
        except Exception as exc:
            partial = True
            notes.append('Filme/Serien: ' + _error(exc))
        try:
            found.update(_load_live(api))
        except Exception as exc:
            partial = True
            notes.append('Live-Sender: ' + _error(exc))
        if not found:
            raise ValueError(notes[0] if notes else 'Plex lieferte keine kostenlosen Titel')
        items = list(found.values())
        counts = {'movies': sum(1 for i in items if i['kind'] == 'movie'),
                  'series': sum(1 for i in items if i['kind'] == 'series'),
                  'channels': sum(1 for i in items if i['kind'] == 'channel')}
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('plex_sync_completed', partial=partial, **counts)
        return {'ok': True, 'partial': partial, **counts}
    except Exception as exc:
        message = _error(exc)
        db = _connect(root)
        try:
            with db:
                for key, value in [('last_result', 'failed'), ('last_error', message),
                                   ('last_http_status', getattr(exc, 'code', 0) or 0), ('next_attempt', now + 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        import netcheck
        _notify('plex_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


def _row(db, item_id):
    row = db.execute('SELECT * FROM plex_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def _series(db, series_id):
    row = db.execute("SELECT * FROM plex_items WHERE id=? AND kind='series'", (series_id,)).fetchone()
    if not row:
        raise ValueError('Plex-Serie nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def load_episodes(root, series_id, opener=None, fetch_token=None, now=None):
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    api = Api(root, opener, fetch_token)
    found = []
    for node in _list(_container(api.get(VOD, '/library/metadata/%s/allLeaves' % series['path'])), 'Metadata')[:3000]:
        ep = episode_from(node, series)
        if ep:
            found.append(ep)
    db = _connect(root)
    try:
        with db:
            _store(db, found, now)
            _set(db, 'series_checked:' + series_id, now)
    finally:
        db.close()
    return found


def episodes(root, series_id, opener=None, fetch_token=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige Plex-Serie')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        series = _series(db, series_id)
        checked = float(_get(db, 'series_checked:' + series_id, '0') or 0)
    finally:
        db.close()
    error = ''
    if not checked or now - checked > SERIES_TTL:
        try:
            load_episodes(root, series_id, opener, fetch_token, now)
        except Exception as exc:
            error = _error(exc)
    db = _connect(root)
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM plex_items WHERE kind='episode' AND series_id=? ORDER BY season,episode,title", (series_id,))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = 0 if row['drm'] == 1 else 1
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': error}


def own_score(row):
    value = row.get('imdb_score')
    if not isinstance(value, (int, float)) or not 0 <= value <= 10:
        return None
    return {'value': round(float(value), 1), 'source': 'IMDb', 'votes': row.get('imdb_votes')}


def _summary(root, row, reports=None):
    import plex_enrichment
    report = (reports if reports is not None else plex_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre'), report)
    if not out['score']:
        out['score'] = own_score(row)
    return out


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films, series or live channels; films and series with canonical categories and ratings."""
    import plex_enrichment
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM plex_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
    finally:
        db.close()
    for row in rows:
        row['playable'] = 0 if row['drm'] == 1 else 1
    if kind == 'channel':
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
                'genre_counts': []}
    reports = plex_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    """Live channels of the latest successful catalogue run (for the Live-TV tab)."""
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        return [dict(r) for r in db.execute(
            "SELECT id,title,number,genre,category,summary,poster,web_url,drm FROM plex_items "
            "WHERE kind='channel' AND seen>=? ORDER BY number,title", (last,))]
    finally:
        db.close()


def item(root, item_id):
    import plex_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Plex-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        if not row:
            raise ValueError('Plex-Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    row['playable'] = 0 if row['drm'] == 1 or row['kind'] == 'series' else 1
    report = plex_enrichment.cached(root, item_id) if row['kind'] != 'channel' else dict(plex_enrichment.UNCHECKED)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'web_url': row.get('web_url') or (parent or {}).get('web_url') or ''},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protected = db.execute("SELECT COUNT(*) FROM plex_items WHERE drm=1 AND kind IN ('movie','episode') AND seen>=?",
                               (last,)).fetchone()[0]
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0), 'last_success': last,
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'channels': _int(_get(db, 'channels', '0')) or 0, 'protected': protected,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM plex_items WHERE kind='episode'").fetchone()[0]}
    finally:
        db.close()


def set_auto(root, enabled):
    if type(enabled) is not bool:
        raise ValueError('Automatik muss ausdrücklich ein- oder ausgeschaltet werden')
    db = _connect(root)
    try:
        with db:
            _set(db, 'auto', int(enabled))
    finally:
        db.close()
    return state(root)


def _run(root):
    global _ACTIVE
    try:
        sync(root)
    finally:
        with _SYNC_LOCK:
            _ACTIVE = False


def start_sync(root):
    global _ACTIVE
    with _SYNC_LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True
    threading.Thread(target=_run, args=(root,), daemon=True, name='plex_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:plex'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def _mark_drm(root, item_id, value):
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE plex_items SET drm=? WHERE id=?', (int(value), item_id))
    finally:
        db.close()


def part_of(answer):
    """(part path, container, protected) of the first playable part of a metadata answer."""
    for meta in _list(_container(answer), 'Metadata'):
        for media in _list(meta, 'Media'):
            protected = bool(media.get('drm')) if isinstance(media, dict) else False
            for part in _list(media, 'Part'):
                if not isinstance(part, dict):
                    continue
                path = str(part.get('key') or '').split('?')[0]
                if not PART_PATH.fullmatch(path) or '..' in path:
                    continue
                container = str(part.get('container') or media.get('container') or '').lower()
                if path.endswith('.mpd'):
                    container = 'mpd'
                elif path.endswith('.m3u8'):
                    container = 'm3u8'
                return path, container, protected or bool(part.get('license') or part.get('License') or part.get('drm'))
    return None


def dash_protected(text):
    """True when an MPD announces copy protection (ContentProtection, e.g. Widevine/PlayReady/CENC)."""
    return bool(_CENC.search(str(text or '')))


def _stream_query(cid, token):
    return urllib.parse.urlencode({'includeAllStreams': 1, 'X-Plex-Product': PRODUCT, 'X-Plex-Client-Identifier': cid,
                                   'X-Plex-Platform': 'Chrome', 'X-Plex-Session-Id': str(uuid.uuid4()),
                                   'X-Plex-Token': token})


def stream(root, row, opener=None, fetch_token=None, check=None):
    """Checked stream address of a film, episode or channel: (url, hls)."""
    import hls_guard
    opener = opener or _open
    api = Api(root, opener, fetch_token)
    if row['kind'] == 'channel':
        url = EPG + '/library/parts/%s.m3u8?%s' % (urllib.parse.quote(row['path'], safe='-_'), _stream_query(api.cid, api.token))
        (check or hls_guard.check)(url)
        return url, True
    found = part_of(api.get(VOD, '/library/metadata/%s' % row['path'], {'includeGuids': 1}))
    if not found:
        raise ValueError('Plex nennt für diesen Titel keinen Stream')
    path, container, protected = found
    if protected:
        raise hls_guard.DrmProtected(DRM_NOTE)
    url = VOD + path + '?' + _stream_query(api.cid, api.token)
    if container == 'mpd':
        raw, _ = opener(url, _headers(api.cid), limit=MAX_MANIFEST)
        if dash_protected(raw.decode('utf-8', 'replace')):
            raise hls_guard.DrmProtected(DRM_NOTE)
        return url, False
    (check or hls_guard.check)(url)
    return url, True


def play_source(root, item_id, opener=None, fetch_token=None, check=None, now=None):
    """Source for streaming.plan. Clear streams play through ffmpeg (DASH) or hls.js (HLS);
    protected ones are refused with a note and remembered, so the catalogue shows the link instead."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Plex-Titel')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row:
        raise ValueError('Plex-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    if row['drm'] == 1:
        raise hls_guard.DrmProtected(DRM_NOTE)
    cached = _SOURCES.get(item_id)
    if cached and cached[0] > now:
        url, hls = cached[1]
    else:
        try:
            url, hls = stream(root, row, opener, fetch_token, check)
        except hls_guard.DrmProtected:
            _mark_drm(root, item_id, 1)
            raise hls_guard.DrmProtected(DRM_NOTE) from None
        except urllib.error.HTTPError as exc:
            raise ValueError(_error(exc)) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(_error(exc)) from None
        if row['drm'] != 0:
            _mark_drm(root, item_id, 0)
        _SOURCES[item_id] = (now + SOURCE_TTL, (url, hls))
    title = row['title']
    if row['kind'] == 'episode':
        series = (parent or {}).get('title') or 'Serie'
        title = ('%s · S%02dE%02d · %s' % (series, row['season'], row['episode'], row['title'])
                 if row['season'] is not None and row['episode'] is not None else '%s · %s' % (series, row['title']))
    elif row['kind'] == 'movie' and row['year']:
        title += ' (%s)' % row['year']
    elif row['kind'] == 'channel' and row['number']:
        title = '%s · %s' % (row['number'], row['title'])
    source = {'kind': 'url', 'url': url, 'hls': hls, 'title': title, 'provider': KEY,
              'quality': 'Plex live (kostenlos, mit Werbung)' if row['kind'] == 'channel' else 'Plex (kostenlos, mit Werbung)',
              'duration': 0 if row['kind'] == 'channel' else row['duration'] or 0, 'live': row['kind'] == 'channel'}
    if not hls:
        source.update(remux=True, server_only=True)   # DASH: ffmpeg on the server joins picture and sound
    return source
