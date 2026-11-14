"""Joyn: films, series and live channels of joyn.de (0.5.65).

Björn (12.11.2026): "in der nächsten Version die Free-Version von Joyn mit Live-TV und
Mediatheken anbinden"; later the same evening: "ich habe auch einen Account … neben dem
Free-Angebot kann ich auch Pay-Angebote dort nutzen". So the catalogue holds the free offer
(licence type AVOD) and, clearly marked, the Joyn+ titles and channels (SVOD / marking PLUS).
MediathekAtlas does not log in to Joyn and stores no Joyn account data.

Formats as recorded in Björn's HAR (12.11.2026 23:09, www.joyn.de in Chrome, not signed in):

* One GraphQL host, ``https://api.joyn.de/graphql``, called with GET and Apollo persisted queries
  (``operationName``, ``variables``, ``extensions={"persistedQuery":{"version":1,"sha256Hash":…}}``)
  and the website's headers (``x-api-key``, ``Joyn-Platform: web``, ``Joyn-Country: DE`` …). The
  hashes come from the website's JavaScript of the same day. If Joyn deploys new query texts, the
  answer is ``PersistedQueryNotFound``; the catalogue run then stops with a clear message.
* ``Navigation`` (no variables): the live channels (``liveTv``: brand with ``livestream`` id,
  quality, ``liveStreamGroups`` such as PUBLIC_VALUE/SPORTS and ``markings`` PLUS), the brands of
  the "Mediatheken" and the genre lanes of /filme and /serien.
* ``GenresPaths`` (no variables): genre paths of /filme, /serien, /plus/filme and /plus/serien.
* ``PageOverviewGenre`` (path, first, offset): one genre page (grid of Movie/Series cards with
  id, title, description, path, licenseTypes, markings, genres, brands, ageRating, images).

NOT in the recording and therefore not implemented: episode lists (query ``Season``, variables
unknown), the pages of the single Mediatheken (SAT.1, ProSieben …) and every playback request
(entitlement, playlist, licence). Joyn is known to deliver with Widevine in the browser; until a
recording of a playback shows an unprotected stream, every title and channel opens the official
page ("Bei Joyn ansehen"). Nothing is circumvented.

Reference checks (IMDb/TVDB/TMDB/OMDb/Wikidata) use the shared portal_enrichment engine.
Titles, tokens and URLs never go to logs or the diagnosis export.
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
from pathlib import Path

import portal_reference

API = 'https://api.joyn.de/graphql'
SITE = 'https://www.joyn.de'
API_KEY = '4f0fd9f18abbe3cf0e87fdb556bc39c8'   # public key of the website (HAR), no account data
CLIENT_VERSION = '5.1593.0'
HASHES = {   # persisted queries of the website (JavaScript bundle of 12.11.2026)
    'Navigation': '818622ff5afe143664241034ba0c537650ec9a2eeae4d568830b47d8de605b7e',
    'GenresPaths': '435ae0c38956a45a4a451b4cb694c9b90913e873e64f9b18e84b107369385701',
    'PageOverviewGenre': '37ba6d0dde470df3f8999d49bcd24bc5c72b8e7192768026d82447c664c6ab7f',
}
FEATURE_FLAGS = {'enable_user_location': 'true', 'watch_assistant_variant': 'true'}
PAGE_SIZE = 32                     # as the website
MAX_PAGES = 60                     # per genre path
MAX_ITEMS = 20000
MAX_ANSWER = 16 * 1024 * 1024
REQUEST_GAP = 0.4                  # 0.5.68: 1 s made the first run take many minutes
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
ASSET_ID = r'[a-z0-9][a-z0-9_\-]{0,80}'
VALID_ID = re.compile(r'[msc]\.' + ASSET_ID)       # m.<film>, s.<series>, c.<live stream>
VALID_ASSET = re.compile(ASSET_ID)
GENRE_PATH = re.compile(r'/(?:plus/)?(?:filme|serien)/genre/[a-z0-9\-]{1,80}')
VALID_BRAND = re.compile(r'[A-Za-z0-9][A-Za-z0-9_\-]{0,80}')   # Brand.id: "165", "bbc-earth"
LIVE_PATH = '/play/live-tv'
TITLE_PATH = re.compile(r'/(?:filme|serien|compilation|channels|mediatheken)/[a-z0-9\-]{1,160}(?:/[a-z0-9\-]{1,160}){0,2}')
KIND_PREFIX = {'movie': 'm', 'series': 's', 'channel': 'c'}
TYPE_KIND = {'Movie': 'movie', 'Series': 'series'}
FREE, PLUS = 'Joyn (kostenlos)', 'Joyn+'
# 0.5.93: Sender, die Joyns Navigation als frei führt (PUBLIC_VALUE, ohne PLUS-Markierung), die joyn.de
# aber nur mit Joyn+ abspielt. Beobachtet von Björn am 13.11.2026 (SAT.1). Nur der genaue Sendername,
# nicht SAT.1 GOLD, SAT.1 emotions oder die Regionalfenster.
PLUS_CHANNELS = {'sat.1'}


def plus_channel(title):
    return str(title or '').strip().lower() in PLUS_CHANNELS
FREE_LICENSES = {'AVOD', 'FREE'}
PAID_LICENSES = {'SVOD', 'TVOD', 'PREMIUM', 'PLUS', 'HD'}
GROUP_NAMES = {'PUBLIC_VALUE': 'Öffentlich-rechtlich & Regional', 'SPORTS': 'Sport'}
NOTE = ('Joyn spielt Filme, Folgen und Live-Sender im eigenen Player ab, in der Regel mit Kopierschutz '
        '(Widevine). MediathekAtlas umgeht ihn nicht: bitte bei Joyn ansehen.')

_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS joyn_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', brand TEXT NOT NULL DEFAULT '',
  offer TEXT NOT NULL DEFAULT 'free', seasons INTEGER, quality TEXT NOT NULL DEFAULT '',
  playable INTEGER NOT NULL DEFAULT 0, drm INTEGER NOT NULL DEFAULT 1, web_url TEXT NOT NULL DEFAULT '',
  seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS joyn_items_kind ON joyn_items(kind, seen);
CREATE TABLE IF NOT EXISTS joyn_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
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
    path = root / 'joyn.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM joyn_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO joyn_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def headers():
    return {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Content-Type': 'application/json',
            'x-api-key': API_KEY, 'Joyn-Platform': 'web', 'Joyn-Client-Version': CLIENT_VERSION,
            'Joyn-Distribution-Tenant': 'JOYN', 'Joyn-Country': 'DE', 'Joyn-User-State': 'code=A_A',
            'Origin': SITE, 'Referer': SITE + '/'}


def query_url(operation, variables=None):
    """GET address of one persisted query, built exactly like the website does."""
    if operation not in HASHES:
        raise ValueError('Unbekannte Joyn-Abfrage')
    params = {'operationName': operation, **FEATURE_FLAGS}
    if variables is not None:
        params['variables'] = json.dumps(variables, separators=(',', ':'))
    params['extensions'] = json.dumps({'persistedQuery': {'version': 1, 'sha256Hash': HASHES[operation]}},
                                      separators=(',', ':'))
    return API + '?' + urllib.parse.urlencode(params)


def _request(operation, variables=None):
    req = urllib.request.Request(query_url(operation, variables), headers=headers())
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > MAX_ANSWER:
            raise ValueError('Joyn-Antwort zu groß')
        raw = response.read(MAX_ANSWER + 1)
    if len(raw) > MAX_ANSWER:
        raise ValueError('Joyn-Antwort zu groß')
    return json.loads(raw.decode('utf-8'))


def _data(answer):
    """``data`` of a GraphQL answer; errors such as PersistedQueryNotFound become a clear message."""
    if not isinstance(answer, dict):
        raise ValueError('Joyn lieferte kein gültiges Ergebnis')
    errors = answer.get('errors')
    if errors and not answer.get('data'):
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        text = str(first.get('message') or (first.get('extensions') or {}).get('code') or 'Fehler')
        if 'persistedquery' in text.replace(' ', '').lower():
            raise ValueError('Joyn hat seine Website-Abfragen geändert (PersistedQueryNotFound) – '
                             'MediathekAtlas braucht ein Update; bitte einen neuen HAR-Mitschnitt schicken')
        raise ValueError('Joyn lehnte die Abfrage ab: ' + _text(text, 160))
    data = answer.get('data')
    if not isinstance(data, dict):
        raise ValueError('Joyn lieferte kein gültiges Ergebnis')
    return data


def _error(exc):
    code = getattr(exc, 'code', None)
    if code == 451 or code == 403:
        return 'Joyn verweigert den Zugriff (HTTP %d, evtl. nur aus Deutschland abrufbar)' % code
    if code:
        return 'Joyn antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Joyn ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:240]
    return 'Joyn-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

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


def image(value):
    """Artwork on Joyn's image host (img.joyn.de, https only)."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.port or parts.username or len(value) > 600 \
            or not (host == 'img.joyn.de' or host.endswith('.joyn.de')) or re.search(r'[\s<>"\']', value):
        return ''
    return value


def _image(node, *keys):
    for key in keys:
        value = node.get(key)
        url = image(value.get('url')) if isinstance(value, dict) else ''
        if url:
            return url
    return ''


def web_url(path):
    path = str(path or '')
    return SITE + path if TITLE_PATH.fullmatch(path) else ''


def live_url(brand_id):
    """Player page of one live channel, built as the website builds it (0.5.90).

    The website links each entry of the Navigation's liveTv list as
    ``/play/live-tv?channel_id=<id of the brand>`` (JavaScript bundle of 12.11.2026). Before 0.5.90
    MediathekAtlas linked the brand page (/channels/…) or, for the 114 of 128 channels without one,
    the bare /play/live-tv: Joyn then opened its default channel (Björn, 13.11.2026: "Joyn zeigt
    immer noch auf arte"). Without a valid brand id there is no channel link at all."""
    brand_id = str(brand_id or '')
    return SITE + LIVE_PATH + '?' + urllib.parse.urlencode({'channel_id': brand_id}) if VALID_BRAND.fullmatch(brand_id) else ''


def live_link_current(url):
    """True for a channel link that names its channel (stored by 0.5.90 or later)."""
    return str(url or '').startswith(SITE + LIVE_PATH + '?channel_id=')


def _names(values, key='name', limit=12):
    out = []
    for v in values if isinstance(values, list) else []:
        name = _text(v.get(key) if isinstance(v, dict) else v, 60)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def offer(node):
    """'free' (AVOD), 'plus' (Joyn+ / paid) or '' (unknown licence, not listed)."""
    licences = {str(v).upper() for v in node.get('licenseTypes') or [] if isinstance(v, str)}
    markings = {str(v).upper() for v in node.get('markings') or [] if isinstance(v, str)}
    if licences & FREE_LICENSES:
        return 'free'
    if licences & PAID_LICENSES or 'PLUS' in markings:
        return 'plus'
    return ''


def item_from(node, plus_page=False):
    """Film or series card of a genre page; None for anything else (compilations, unknown licences)."""
    if not isinstance(node, dict):
        return None
    kind = TYPE_KIND.get(str(node.get('__typename') or ''))
    ident = str(node.get('id') or '')
    title = _text(node.get('title'), 200)
    kind_offer = offer(node) or ('plus' if plus_page else '')
    if not kind or not title or not VALID_ASSET.fullmatch(ident) or not kind_offer:
        return None
    age = _int((node.get('ageRating') or {}).get('minAge') if isinstance(node.get('ageRating'), dict) else None, 0, 21)
    brands = _names(node.get('brands'), 'title', 4)
    return {
        'id': KIND_PREFIX[kind] + '.' + ident, 'kind': kind, 'title': title, 'path': _text(node.get('path'), 200),
        'series_id': '', 'season': None, 'episode': None, 'year': None, 'duration': None,
        'rating': ('FSK %d' % age) if age is not None else '', 'genre': ', '.join(_names(node.get('genres'))),
        'summary': _text(node.get('description'), 1600),
        'poster': _image(node, 'heroPortrait', 'primaryImage', 'iconicImage'),
        'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
        'category': PLUS if kind_offer == 'plus' else FREE, 'brand': ', '.join(brands), 'offer': kind_offer,
        'seasons': _int(node.get('numberOfSeasons'), 0, 200), 'quality': '',
        'playable': 0, 'drm': 1, 'web_url': web_url(node.get('path'))}


def channel_from(node, number=None):
    """Live channel of the navigation (Brand with livestream); radio and empty brands are skipped."""
    if not isinstance(node, dict) or node.get('isRadio'):
        return None
    live = node.get('livestream') if isinstance(node.get('livestream'), dict) else None
    ident = str((live or {}).get('id') or '')
    title = _text((live or {}).get('title') or node.get('title'), 200)
    if not live or not title or not VALID_ASSET.fullmatch(ident):
        return None
    groups = [str(g) for g in live.get('liveStreamGroups') or [] if isinstance(g, str)]
    markings = {str(m).upper() for m in live.get('markings') or [] if isinstance(m, str)}
    plus = 'PLUS' in markings or plus_channel(title) or plus_channel(node.get('title'))
    group = next((GROUP_NAMES[g] for g in groups if g in GROUP_NAMES), '')
    return {
        'id': 'c.' + ident, 'kind': 'channel', 'title': title, 'path': ident, 'series_id': '', 'season': None,
        'episode': None, 'year': None, 'duration': None, 'rating': '', 'genre': group,
        'summary': '', 'poster': image(((node.get('logo') or {}) if isinstance(node.get('logo'), dict) else {}).get('url')),
        'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': number,
        'category': PLUS if plus else (group or 'Joyn'), 'brand': _text(node.get('title'), 80),
        'offer': 'plus' if plus else 'free', 'seasons': None, 'quality': _text(live.get('quality'), 8),
        'playable': 0, 'drm': 1,
        # 0.5.90: the player page of exactly this channel (see live_url).
        'web_url': live_url(node.get('id'))}


def genre_paths(navigation, paths_answer=None):
    """(path, plus) of all genre pages: navigation lanes plus GenresPaths (incl. /plus/…)."""
    out = []

    def add(blocks, plus=False):
        for block in blocks if isinstance(blocks, list) else []:
            for asset in (block or {}).get('assets') or [] if isinstance(block, dict) else []:
                path = str((asset or {}).get('path') or '') if isinstance(asset, dict) else ''
                if GENRE_PATH.fullmatch(path) and (path, plus or path.startswith('/plus/')) not in out:
                    out.append((path, plus or path.startswith('/plus/')))

    for key in ('movieGenre', 'seriesGenre'):
        add(((navigation or {}).get(key) or {}).get('blocks'))
    for key, plus in (('movies', False), ('series', False), ('plusMovies', True), ('plusSeries', True)):
        add(((paths_answer or {}).get(key) or {}).get('blocks'), plus)
    return out


def genre_assets(data):
    page = data.get('page') if isinstance(data.get('page'), dict) else {}
    out = []
    for block in page.get('blocks') or []:
        if isinstance(block, dict):
            out += [a for a in block.get('assets') or [] if isinstance(a, dict)]
    return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'brand', 'offer',
          'seasons', 'quality', 'playable', 'drm', 'web_url')


def _store(db, items, now):
    for item in items:
        db.execute('''INSERT INTO joyn_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def _merge(found, item):
    """A title appears on several genre pages: keep one row and collect Joyn's genres."""
    old = found.get(item['id'])
    if not old:
        found[item['id']] = item
        return
    genres = [g for g in (old['genre'].split(', ') + item['genre'].split(', ')) if g]
    old['genre'] = ', '.join(dict.fromkeys(genres))[:400]
    if item['offer'] == 'free':          # free wins over a Joyn+ listing of the same title
        old['offer'], old['category'] = 'free', FREE


def _page(request, path, page, retry_wait):
    """One genre page. A failed request is asked once more after a pause (0.5.85: Björn's run of
    12.11.2026 lost a film genre to a single slow answer and the whole catalogue counted as partial)."""
    variables = {'first': PAGE_SIZE, 'path': path, 'offset': page * PAGE_SIZE}
    try:
        return genre_assets(_data(request('PageOverviewGenre', variables)))
    except Exception:
        if retry_wait:
            time.sleep(retry_wait)
        return genre_assets(_data(request('PageOverviewGenre', variables)))


def _load_genre(request, path, plus, gap, found, retry_wait=0.0):
    """All pages of one genre path. Returns '' when complete, otherwise why it stopped early.
    A page that brings no title not already seen on this path ends the path (0.5.68: protects
    against an ignored offset, which would otherwise repeat the same 32 titles up to MAX_PAGES times)."""
    seen = set()
    for page in range(MAX_PAGES):
        if gap and page:
            time.sleep(gap)
        try:
            assets = _page(request, path, page, retry_wait)
        except Exception as exc:
            return 'Seite %d: %s' % (page + 1, _error(exc))
        ids = {str(node.get('id') or '') for node in assets}
        fresh = ids - seen
        seen |= ids
        for node in assets:
            it = item_from(node, plus)
            if it:
                _merge(found, it)
        if len(assets) < PAGE_SIZE or not fresh or len(found) >= MAX_ITEMS:
            return ''
    return 'mehr als %d Seiten' % MAX_PAGES


def _counts(items):
    return {'movies': sum(1 for i in items if i['kind'] == 'movie'),
            'series': sum(1 for i in items if i['kind'] == 'series'),
            'channels': sum(1 for i in items if i['kind'] == 'channel'),
            'plus': sum(1 for i in items if i['offer'] == 'plus')}


def _save_progress(root, found, now, progress):
    """0.5.68: store what is loaded so far, so channels and titles appear during the run
    (Björn: "Joyn bleibt bei Sendern und Filmen bzw. Serien komplett leer" while the first run
    was still loading). last_loaded changes, so the stored platform view is rebuilt."""
    items = list(found.values())
    db = _connect(root)
    try:
        with db:
            _store(db, items, now)
            for key, value in [('last_loaded', time.time()), ('progress', progress), *_counts(items).items()]:
                _set(db, key, value)
    finally:
        db.close()


def sync(root, request=None, now=None, gap=None):
    """Load live channels and all films/series of the genre pages. Rows stay, but only titles
    seen in the latest successful run are listed (the catalogue rotates)."""
    now = time.time() if now is None else float(now)
    request = request or _request
    gap = (REQUEST_GAP if request is _request else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('joyn_sync_started')
    try:
        navigation = _data(request('Navigation'))
        found, partial, notes = {}, False, []
        for pos, node in enumerate(navigation.get('liveTv') or []):
            ch = channel_from(node, pos + 1)
            if ch:
                found.setdefault(ch['id'], ch)
        _save_progress(root, found, now, 'Live-Sender geladen, Genre-Seiten folgen')
        try:
            extra = _data(request('GenresPaths'))
        except Exception as exc:
            extra, partial = {}, True
            notes.append('Genre-Übersicht: ' + _error(exc))
        paths = genre_paths(navigation, extra)
        if not paths:
            raise ValueError('Joyn nannte keine Genre-Seiten')
        retry_wait = 5.0 if gap else 0.0
        failed = {}      # step number -> reason
        for number, (path, plus) in enumerate(paths, 1):
            reason = _load_genre(request, path, plus, gap, found, retry_wait)
            if reason:
                failed[number] = reason
            _save_progress(root, found, now, 'Genre-Seite %d von %d' % (number, len(paths)))
            _notify('joyn_sync_progress', step=number, steps=len(paths), partial=partial or bool(failed), failed=len(failed),
                    **_counts(list(found.values())))
            if gap:
                time.sleep(gap)
        # 0.5.85: genre pages that stopped early get a second run at the end, when a short
        # disturbance at Joyn is usually over; only what still fails makes the catalogue partial.
        for number in list(failed):
            path, plus = paths[number - 1]
            _save_progress(root, found, now, 'Genre-Seite %d von %d noch einmal' % (number, len(paths)))
            reason = _load_genre(request, path, plus, gap, found, retry_wait)
            _notify('joyn_sync_retry', step=number, steps=len(paths), ok=not reason, **_counts(list(found.values())))
            if reason:
                failed[number] = reason
            else:
                del failed[number]
        for number, reason in failed.items():
            partial = True
            notes.append('Genre-Seite %d von %d (%s)' % (number, len(paths), reason))
        if not any(i['kind'] in ('movie', 'series') for i in found.values()):
            raise ValueError(notes[0] if notes else 'Joyn lieferte keine Filme oder Serien')
        items = list(found.values())
        counts = _counts(items)
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', time.time()), ('progress', ''),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('next_attempt', now + (3600 if partial else 24 * 3600)), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('joyn_sync_completed', partial=partial, failed_steps=sorted(failed), reasons=[_text(r, 120) for r in list(failed.values())[:5]], **counts)
        return {'ok': True, 'partial': partial, **counts}
    except Exception as exc:
        message = _error(exc)
        db = _connect(root)
        try:
            with db:
                for key, value in [('last_result', 'failed'), ('last_error', message), ('progress', ''),
                                   ('last_http_status', getattr(exc, 'code', 0) or 0), ('next_attempt', now + 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        import netcheck
        _notify('joyn_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- views

def _row(db, item_id):
    row = db.execute('SELECT * FROM joyn_items WHERE id=?', (item_id,)).fetchone()
    return _plus_fix(dict(row)) if row else None


def _plus_fix(row):
    """0.5.93: a channel of PLUS_CHANNELS is Joyn+ also in catalogues stored before the list."""
    if row.get('kind') == 'channel' and plus_channel(row.get('title')):
        row['offer'], row['category'] = 'plus', PLUS
    return row


def episodes(root, series_id):
    """Episode lists are not recorded yet (query 'Season'): the series page links to Joyn."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige Joyn-Serie')
    db = _connect(root)
    try:
        series = _row(db, series_id)
    finally:
        db.close()
    if not series or series['kind'] != 'series':
        raise ValueError('Joyn-Serie nicht im Katalog; bitte Katalog neu laden')
    extra = _summary(root, series)
    return {'series': {'id': series_id, 'title': series['title'], 'web_url': series['web_url'], **extra},
            'items': [], 'error': '',
            'note': 'Die Folgen dieser Serie zeigt MediathekAtlas noch nicht an – bitte bei Joyn ansehen.'}


def _summary(root, row, reports=None):
    import joyn_enrichment
    report = (reports if reports is not None else joyn_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))
    # 0.5.83: Joyn+ / kostenlos is the offer, not a category; it stays on the card (row['category'])
    # and as filter value (listing genre=FREE/PLUS), but no longer among the shared category chips.
    out['offer_label'] = PLUS if row.get('offer') == 'plus' else FREE
    # 0.5.90: a channel link of an earlier catalogue opens Joyn's default channel, not this one.
    if row.get('kind') == 'channel' and not live_link_current(row.get('web_url')):
        out['web_url'] = ''
    return out


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films, series or live channels; films and series with canonical categories and ratings."""
    import joyn_enrichment
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM joyn_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR brand LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
    finally:
        db.close()
    if kind == 'channel':
        for row in rows:      # 0.5.90: no link of an earlier catalogue that opens the wrong channel
            _plus_fix(row)
            if not live_link_current(row.get('web_url')):
                row['web_url'] = ''
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
                'genre_counts': []}
    reports = joyn_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
    counts = portal_reference.facets(rows)
    if genre in (FREE, PLUS):
        rows = [r for r in rows if r.get('offer_label') == genre and portal_reference.in_collection(r, collection, kind)]
    else:
        rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    """Live channels of the latest successful catalogue run (Live-TV tab, live_tv)."""
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT id,title,number,genre,category,summary,poster,offer,quality,web_url,playable FROM joyn_items "
            "WHERE kind='channel' AND seen>=? ORDER BY number,title", (last,))]
    finally:
        db.close()
    # 0.5.93: also for catalogues stored before the list (no new request needed)
    return [_plus_fix({**row, 'kind': 'channel'}) for row in rows]


def item(root, item_id):
    """Detail view of one film, series or channel: catalogue row and reference report."""
    import joyn_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Joyn-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row:
        raise ValueError('Joyn-Titel nicht im Katalog; bitte Katalog neu laden')
    report = joyn_enrichment.cached(root, item_id) if row['kind'] != 'channel' else dict(joyn_enrichment.UNCHECKED)
    return {'item': {**row, **_summary(root, row, {row['id']: report})}, 'series': None, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        movies, series = _int(_get(db, 'movies', '0')) or 0, _int(_get(db, 'series', '0')) or 0
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': movies, 'series': series, 'channels': _int(_get(db, 'channels', '0')) or 0,
            'plus': _int(_get(db, 'plus', '0')) or 0, 'protected': movies + series, 'playable': 0,
            'progress': _get(db, 'progress') if _ACTIVE else ''}
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


def live_links_outdated(root):
    """Number of listed live channels whose stored link does not name its channel (catalogues
    loaded before 0.5.90 linked the bare live page, which plays Joyn's default channel)."""
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        if not last:
            return 0
        rows = db.execute("SELECT web_url FROM joyn_items WHERE kind='channel' AND seen>=?", (last,)).fetchall()
        return sum(1 for (url,) in rows if not live_link_current(url))
    finally:
        db.close()


LINK_RETRY = 3600     # seconds between two attempts of the link refresh after a failure


def refresh_live_links(root, request=None, now=None):
    """0.5.90: rebuild the links of the live channels with one Navigation request, so a catalogue
    of an earlier version opens the right channel without waiting for the next full run.
    Only web_url of channels already in the catalogue changes; films and series stay untouched."""
    now = time.time() if now is None else float(now)
    request = request or _request
    db = _connect(root)
    try:
        with db:
            _set(db, 'links_attempt', now)
    finally:
        db.close()
    try:
        navigation = _data(request('Navigation'))
    except Exception as exc:
        _notify('joyn_links_failed', reason=_text(_error(exc), 120))
        return {'ok': False, 'error': _error(exc), 'updated': 0}
    links = {}
    for pos, node in enumerate(navigation.get('liveTv') or []):
        ch = channel_from(node, pos + 1)
        if ch and ch['web_url']:
            links.setdefault(ch['id'], ch['web_url'])
    db = _connect(root)
    try:
        with db:
            updated = 0
            for ident, url in links.items():
                updated += db.execute("UPDATE joyn_items SET web_url=? WHERE id=? AND kind='channel' AND web_url<>?",
                                      (url, ident, url)).rowcount
    finally:
        db.close()
    _notify('joyn_links_refreshed', channels=len(links), updated=updated)
    return {'ok': True, 'updated': updated, 'channels': len(links)}


def _links_due(root, current, now=None):
    now = time.time() if now is None else now
    if current.get('running') or not current.get('last_success'):
        return False
    db = _connect(root)
    try:
        attempt = float(_get(db, 'links_attempt', '0') or 0)
    finally:
        db.close()
    return now - attempt >= LINK_RETRY and live_links_outdated(root) > 0


def start_sync(root):
    global _ACTIVE
    with _SYNC_LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True
    threading.Thread(target=_run, args=(root,), daemon=True, name='joyn_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:joyn'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)
        elif _links_due(root, current):
            try:
                refresh_live_links(root)
            except Exception:  # a local database problem must not end the loop
                pass


def play_source(root, item_id, **_):
    """Source for streaming.resolve: Joyn playback is not released (see module text)."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Joyn-Titel')
    raise hls_guard.DrmProtected(NOTE)
