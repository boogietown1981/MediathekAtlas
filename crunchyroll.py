"""Crunchyroll: anime series and films of crunchyroll.com as a catalogue with links (0.5.96).

Björn (13.11.2026): "crunchyroll mit dem free content anbinden". Findings before the build:

* Crunchyroll ended its free, ad-supported plan on 31.12.2025 (Cord Cutters News, Anime News
  Network). Since 1.1.2026 every title on crunchyroll.com needs a subscription. Free Crunchyroll
  episodes exist only on other services (official YouTube channel, FAST channels such as Pluto TV).
* Every stream of crunchyroll.com is protected with Widevine (cr-play-service); yt-dlp removed its
  Crunchyroll support for that reason in 2025.

So this module builds the catalogue (series with seasons and episodes, films, German texts and
categories), marks every title as "Nur mit Abo" unless Crunchyroll itself lists an episode as free
(``is_premium_only: false``; if free episodes ever come back they appear as "Kostenlos") and opens
crunchyroll.com ("Bei Crunchyroll ansehen", with the optional Chrome extension for the play click).
MediathekAtlas plays nothing from Crunchyroll, stores no offline copies and circumvents nothing.

API (public web API, formats from the yt-dlp extractor up to 2024.12 and the Crunchyroll website;
crunchyroll.com is blocked in the build environment, so this was NOT checked live):

* Anonymous token: ``POST https://www.crunchyroll.com/auth/v1/token`` with ``Authorization: Basic
  <client>``, ``ETP-Anonymous-ID: <uuid>``, body ``grant_type=client_id``. Several known clients are
  tried in turn; the one that worked is remembered.
* Catalogue: ``GET /content/v2/discover/browse?n=100&start=<n>&sort_by=alphabetical&locale=de-DE``
  -> ``{"total": …, "data": [{"id", "type": "series"|"movie_listing", "slug_title", "title",
  "description", "images": {"poster_tall": [[{source,width,height}]]}, "series_metadata"|
  "movie_listing_metadata": {…}}]}``.
* Seasons: ``GET /content/v2/cms/series/<id>/seasons``; episodes:
  ``GET /content/v2/cms/seasons/<id>/episodes``; films of a film entry:
  ``GET /content/v2/cms/movie_listings/<id>/movies``.
* Pages: ``https://www.crunchyroll.com/de/series/<id>/<slug>``, ``…/de/watch/<id>/<slug>``.

Crunchyroll protects its website with Cloudflare. If a request is blocked (HTTP 403 with a
challenge page), the message says so; titles, tokens and URLs never go to logs or the diagnosis.
"""
from __future__ import annotations

import base64
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

SITE = 'https://www.crunchyroll.com'
HOSTS = {'www.crunchyroll.com', 'beta-api.crunchyroll.com'}
LOCALE = 'de-DE'
PAGE = 100
MAX_PAGES = 60
MAX_ANSWER = 16 * 1024 * 1024
REQUEST_GAP = 0.4
SERIES_TTL = 6 * 3600
TOKEN_MARGIN = 30
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')
# Known public clients of Crunchyroll's own apps (web first). Crunchyroll changes them from time to
# time; a client the server rejects (400/401) is skipped and the next one is tried.
CLIENTS = (
    ('web', 'noaihdevm_6iyg0a8l0q', ''),
    ('console', 't-kdgp2h8c3jub8fn0fq', 'yfLDfMfrYvKXh4JXS1LEI2cCqu1v5Wan'),
)
VALID_ID = re.compile(r'[sme]\.[A-Z0-9]{6,16}')        # s.GY19NQ2QR, m.G1XHJV0M7, e.GRDQPM1ZY
ASSET_ID = re.compile(r'[A-Z0-9]{6,16}')
SLUG = re.compile(r'[a-z0-9][a-z0-9\-]{0,200}')
KIND_PREFIX = {'series': 's', 'movie': 'm', 'episode': 'e'}
GENRE = 'Animation, Anime'
PAID = 'Nur mit Abo'
FREE = 'Kostenlos'
DUB = 'Deutsche Synchronfassung'
SUB = 'Deutsche Untertitel'
IMAGE_HOSTS = ('.crunchyroll.com', '.vrv.co')
DRM_NOTE = ('Crunchyroll liefert alle Folgen und Filme nur mit Kopierschutz (Widevine) und seit dem 1.1.2026 '
            'nur noch mit Abo aus. MediathekAtlas umgeht nichts: bitte bei Crunchyroll ansehen.')
FREE_END_NOTE = ('Crunchyroll hat das kostenlose Angebot mit Werbung zum 31.12.2025 eingestellt. Gratis-Folgen '
                 'gibt es auf dem offiziellen YouTube-Kanal (Quelle „YouTube“) und bei Pluto TV.')

_SYNC_LOCK = threading.Lock()
_TOKEN_LOCK = threading.Lock()
_ACTIVE = False
_PROGRESS = ''
_TOKEN = {'value': '', 'expires': 0.0}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS crunchyroll_titles(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', offer TEXT NOT NULL DEFAULT 'plus',
  seasons INTEGER, episodes_total INTEGER, languages TEXT NOT NULL DEFAULT '', season_title TEXT NOT NULL DEFAULT '',
  watch_id TEXT NOT NULL DEFAULT '', web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS crunchyroll_titles_kind ON crunchyroll_titles(kind, seen);
CREATE INDEX IF NOT EXISTS crunchyroll_titles_series ON crunchyroll_titles(series_id, season, episode);
CREATE TABLE IF NOT EXISTS crunchyroll_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


class Blocked(Exception):
    """Cloudflare (or a region lock) refused the request."""

    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


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
    path = root / 'crunchyroll.sqlite3'
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
    row = db.execute('SELECT value FROM crunchyroll_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO crunchyroll_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def _check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port or parts.username or parts.password:
        raise ValueError('Ungültige Crunchyroll-Anfrage')
    return parts


def _cloudflare(code, head, body):
    """True for Cloudflare's bot check instead of an API answer."""
    text = body[:4000].decode('utf-8', 'replace').lower() if body else ''
    return bool(head.get('cf-mitigated')) or 'just a moment' in text or 'challenge-platform' in text \
        or ('cloudflare' in text and code == 403)


def _open(req):
    """bytes of one answer; Cloudflare's challenge becomes ``Blocked``."""
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != 'https' or final.hostname not in HOSTS:
                raise ValueError('Crunchyroll leitete auf eine unerwartete Adresse um')
            raw = response.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as exc:
        body = b''
        try:
            body = exc.read(8000)
        except OSError:
            pass
        head = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        if exc.code in (403, 429, 503) and _cloudflare(exc.code, head, body):
            raise Blocked(exc.code, 'cloudflare') from None
        if exc.code in (403, 451) and b'region' in body.lower():
            raise Blocked(exc.code, 'region') from None
        raise
    if len(raw) > MAX_ANSWER:
        raise ValueError('Crunchyroll-Antwort zu groß')
    return raw


def request_token(client, opener=None):
    """Anonymous access token of one public client (dict with access_token, expires_in)."""
    _name, ident, secret = client
    basic = base64.b64encode(('%s:%s' % (ident, secret)).encode('ascii')).decode('ascii')
    data = urllib.parse.urlencode({'grant_type': 'client_id'}).encode('ascii')
    req = urllib.request.Request(SITE + '/auth/v1/token', data=data, method='POST', headers={
        'Authorization': 'Basic ' + basic, 'ETP-Anonymous-ID': str(uuid.uuid4()), 'User-Agent': USER_AGENT,
        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
        'Origin': SITE, 'Referer': SITE + '/'})
    return _json((opener or _open)(req))


def _token(root=None, opener=None, now=None):
    """Valid bearer token; tries the remembered client first, then the others."""
    now = time.time() if now is None else now
    with _TOKEN_LOCK:
        if _TOKEN['value'] and _TOKEN['expires'] > now:
            return _TOKEN['value']
        preferred = ''
        if root:
            db = _connect(root)
            try:
                preferred = _get(db, 'client')
            finally:
                db.close()
        order = sorted(CLIENTS, key=lambda c: c[0] != preferred)
        last = None
        for client in order:
            try:
                answer = request_token(client, opener)
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 401):
                    last = exc
                    continue
                raise
            token = str(answer.get('access_token') or '') if isinstance(answer, dict) else ''
            if not token or len(token) > 8000:
                last = ValueError('Crunchyroll lieferte keinen Zugang')
                continue
            life = _int(answer.get('expires_in'), 30, 86400) or 300
            _TOKEN.update(value=token, expires=now + life - TOKEN_MARGIN)
            if root and client[0] != preferred:
                db = _connect(root)
                try:
                    with db:
                        _set(db, 'client', client[0])
                finally:
                    db.close()
            return token
        raise last or ValueError('Crunchyroll lieferte keinen Zugang')


def _fetch(path, query=None, root=None, opener=None):
    """GET of one API path on www.crunchyroll.com with the anonymous token. Returns parsed JSON."""
    query = dict(query or {})
    query.setdefault('locale', LOCALE)
    url = SITE + path + '?' + urllib.parse.urlencode(query)
    _check_url(url)
    for attempt in (0, 1):
        token = _token(root, opener)
        req = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + token, 'User-Agent': USER_AGENT, 'Accept': 'application/json',
            'Accept-Language': 'de-DE,de;q=0.9', 'Origin': SITE, 'Referer': SITE + '/'})
        try:
            return _json((opener or _open)(req))
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and not attempt:
                _TOKEN.update(value='', expires=0.0)      # token ran out early: one new one
                continue
            raise
    raise ValueError('Crunchyroll lieferte keinen Zugang')


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError, AttributeError):
        raise ValueError('Crunchyroll lieferte kein gültiges Ergebnis') from None


def _error(exc):
    if isinstance(exc, Blocked):
        if str(exc) == 'region':
            return 'Crunchyroll verweigert den Zugriff aus dieser Region (HTTP %d)' % exc.code
        return ('Crunchyroll blockiert den automatischen Abruf (Cloudflare-Schutz, HTTP %d). Bitte später erneut '
                'versuchen; bleibt es dabei, bitte die Diagnose schicken.' % exc.code)
    code = getattr(exc, 'code', None)
    if code in (400, 401):
        return 'Crunchyroll hat die bekannten App-Zugänge abgelehnt (HTTP %d); MediathekAtlas braucht ein Update' % code
    if code:
        return 'Crunchyroll antwortet mit HTTP %d' % code
    if isinstance(exc, ValueError):
        return str(exc)[:240]
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Crunchyroll ist nicht erreichbar', exc)
    return 'Crunchyroll-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _int(value, low=None, high=None):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def image(value):
    """Artwork on Crunchyroll's image hosts (imgsrv/static.crunchyroll.com), https only."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.port or parts.username or parts.password or len(value) > 800 \
            or not any(host.endswith(h) for h in IMAGE_HOSTS) or re.search(r'[\s<>"\'\\]', value):
        return ''
    return value


def pick_image(images, key, width=480):
    """The variant closest to ``width`` of ``images[key]`` (a list of lists of {source,width})."""
    groups = images.get(key) if isinstance(images, dict) else None
    best, best_gap = '', None
    for group in groups if isinstance(groups, list) else []:
        for v in group if isinstance(group, list) else [group]:
            if not isinstance(v, dict):
                continue
            url = image(v.get('source'))
            gap = abs((_int(v.get('width'), 1) or width) - width)
            if url and (best_gap is None or gap < best_gap):
                best, best_gap = url, gap
    return best


def _slug(value):
    value = str(value or '').lower()
    return value if SLUG.fullmatch(value) else ''


def web_url(kind, ident, slug=''):
    """Page of a title on crunchyroll.com (German interface)."""
    if not ASSET_ID.fullmatch(str(ident or '')):
        return ''
    if kind == 'series':
        return '%s/de/series/%s%s' % (SITE, ident, '/' + slug if slug else '')
    return '%s/de/watch/%s%s' % (SITE, ident, '/' + slug if slug else '')


def search_url(title):
    return '%s/de/search?q=%s' % (SITE, urllib.parse.quote(str(title or '')[:120]))


def _meta(node, *names):
    for name in names:
        value = node.get(name)
        if isinstance(value, dict):
            return value
    return node      # cms answers are flat (episode fields directly on the node)


def _rating(meta):
    ratings = meta.get('maturity_ratings') or []
    for r in reversed(ratings if isinstance(ratings, list) else []):
        age = _int(re.sub(r'\D', '', str(r)), 0, 21)
        if age is not None:
            return 'ab %d' % min(age, 18)
    return ''


def _genres(meta):
    out = []
    for g in meta.get('tenant_categories') or []:
        name = _text(g, 40)
        if name and name not in out:
            out.append(name)
    return ', '.join([GENRE] + out[:8])


def _languages(meta):
    """'dub' (German audio), 'sub' (German subtitles) as a comma list."""
    audio = {str(a) for a in meta.get('audio_locales') or [] if isinstance(a, str)}
    subs = {str(s) for s in meta.get('subtitle_locales') or [] if isinstance(s, str)}
    if isinstance(meta.get('audio_locale'), str):
        audio.add(meta['audio_locale'])
    out = []
    if LOCALE in audio:
        out.append('dub')
    if LOCALE in subs:
        out.append('sub')
    return ','.join(out)


def _year(meta, *names):
    for name in names:
        value = meta.get(name)
        year = _int(value, 1900, 2100) if not isinstance(value, str) else _int(value[:4], 1900, 2100)
        if year:
            return year
    return None


def _free(meta):
    """True only if Crunchyroll says explicitly that the title is not premium-only."""
    return meta.get('is_premium_only') is False


def item_from(node, series=None):
    """Series, film entry or episode of an API answer; None for anything else (music, clips)."""
    if not isinstance(node, dict):
        return None
    kind = str(node.get('type') or ('episode' if series is not None else ''))
    if kind == 'movie_listing':
        kind = 'movie'
    elif kind == 'movie' and series is not None:
        kind = 'episode'        # a film inside a film entry is handled like its episode
    ident = str(node.get('id') or '')
    title = _text(node.get('title'), 200)
    if kind not in KIND_PREFIX or not ASSET_ID.fullmatch(ident) or not title:
        return None
    if kind == 'episode' and not series:
        return None
    images = node.get('images') if isinstance(node.get('images'), dict) else {}
    slug = _slug(node.get('slug_title') or node.get('slug'))
    if kind == 'series':
        meta = _meta(node, 'series_metadata')
        free, poster = False, pick_image(images, 'poster_tall') or pick_image(images, 'poster_wide')
        duration, year = None, _year(meta, 'series_launch_year')
    elif kind == 'movie':
        meta = _meta(node, 'movie_listing_metadata')
        free = _free(meta)
        poster = pick_image(images, 'poster_tall') or pick_image(images, 'poster_wide') or pick_image(images, 'thumbnail')
        duration = (_int(meta.get('duration_ms'), 1000, 10 ** 8) or 0) // 1000 or None
        year = _year(meta, 'movie_release_year', 'premium_available_date')
    else:
        meta = _meta(node, 'episode_metadata', 'movie_metadata')
        if meta.get('is_clip') is True:
            return None
        free = _free(meta)
        poster = pick_image(images, 'thumbnail', 640)
        duration = (_int(meta.get('duration_ms'), 1000, 10 ** 8) or 0) // 1000 or None
        year = _year(meta, 'episode_air_date', 'premium_available_date')
    is_episode = kind == 'episode'
    season = _int(meta.get('season_number'), 0, 999) if is_episode else None
    number = meta.get('episode_number')
    number = _int(number, 0, 99999) if number is not None else _int(meta.get('sequence_number'), 0, 99999)
    out = {
        'id': KIND_PREFIX[kind] + '.' + ident, 'kind': kind, 'title': title, 'path': slug,
        'series_id': series['id'] if series else '', 'season': season, 'episode': number if is_episode else None,
        'year': year, 'duration': duration, 'rating': _rating(meta) or ((series or {}).get('rating') or ''),
        'genre': (series or {}).get('genre') or _genres(meta),
        'summary': _text(node.get('description') or node.get('promo_description'), 1600),
        'poster': poster, 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
        'category': FREE if free else PAID, 'offer': 'free' if free else 'plus',
        'seasons': _int(meta.get('season_count'), 0, 500) if kind == 'series' else None,
        'episodes_total': _int(meta.get('episode_count'), 0, 100000) if kind == 'series' else None,
        'languages': _languages(meta), 'season_title': _text(meta.get('season_title'), 200) if is_episode else '',
        'watch_id': ident if is_episode else '',
        'web_url': web_url('series' if kind == 'series' else 'watch', ident, slug) if kind != 'movie' else search_url(title)}
    return out


def browse_query(start):
    return {'n': PAGE, 'start': start, 'sort_by': 'alphabetical', 'ratings': 'true'}


def load_catalogue(fetch, gap, found, progress=None):
    """All series and film entries; False when the list stopped early."""
    seen, total = set(), None
    for page in range(MAX_PAGES):
        if gap and page:
            time.sleep(gap)
        try:
            answer = fetch('/content/v2/discover/browse', browse_query(len(seen)))
        except Exception:
            if page == 0:
                raise
            return False
        data = answer.get('data') if isinstance(answer, dict) else None
        data = data if isinstance(data, list) else []
        total = _int(answer.get('total'), 0) if isinstance(answer, dict) else None
        fresh = 0
        for node in data:
            ident = str(node.get('id') or '') if isinstance(node, dict) else ''
            if ident and ident not in seen:
                seen.add(ident)
                fresh += 1
                it = item_from(node)
                if it and it['kind'] in ('series', 'movie'):
                    found[it['id']] = it
        if progress:
            progress('%d von %s Titeln' % (len(seen), total if total is not None else '?'))
        if not fresh:
            return total is None or len(seen) >= total
        if total is None or len(seen) >= total:
            return True
    return False


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre', 'summary',
          'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'offer', 'seasons', 'episodes_total',
          'languages', 'season_title', 'watch_id', 'web_url')
KEEP_IF_EMPTY = ('watch_id',)      # a film's resolved watch page survives the next catalogue run


def _store(db, items, now):
    sets = ','.join(('%s=CASE WHEN excluded.%s<>\'\' THEN excluded.%s ELSE crunchyroll_titles.%s END' % (f, f, f, f))
                    if f in KEEP_IF_EMPTY else '%s=excluded.%s' % (f, f) for f in FIELDS)
    for item in items:
        db.execute('''INSERT INTO crunchyroll_titles(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), sets),
                   (item['id'], *[item[f] for f in FIELDS], now, now))
    # a film whose watch page is known links there instead of the search
    db.execute("""UPDATE crunchyroll_titles SET web_url='%s/de/watch/' || watch_id
                  WHERE kind='movie' AND watch_id<>'' AND web_url LIKE '%%/de/search?%%'""" % SITE)


def _counts(items):
    return {'movies': sum(1 for i in items if i['kind'] == 'movie'),
            'series': sum(1 for i in items if i['kind'] == 'series'),
            'free': sum(1 for i in items if i['offer'] == 'free')}


def _say(text):
    global _PROGRESS
    _PROGRESS = text


def sync(root, fetch=None, now=None, gap=None):
    """Load the whole catalogue (series and film entries). Episodes follow on demand."""
    now = time.time() if now is None else float(now)
    live = fetch is None
    fetch = fetch or (lambda path, query=None: _fetch(path, query, root))
    gap = (REQUEST_GAP if live else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('crunchyroll_sync_started')
    try:
        found = {}
        _say('Katalog wird geladen')
        complete = load_catalogue(fetch, gap, found, _say)
        if not any(i['kind'] == 'series' for i in found.values()):
            raise ValueError('Crunchyroll lieferte keine Serien')
        items = list(found.values())
        counts = _counts(items)
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if not complete and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', time.time()),
                                   ('last_result', 'complete' if complete else 'partial'),
                                   ('last_error', '' if complete else 'Katalog nur teilweise geladen'),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('crunchyroll_sync_completed', partial=not complete, **counts)
        return {'ok': True, 'partial': not complete, **counts}
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
        _notify('crunchyroll_sync_failed', http_status=getattr(exc, 'code', 0) or 0,
                blocked=str(exc) if isinstance(exc, Blocked) else '', error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}
    finally:
        _say('')


# ---------------------------------------------------------------- views

def _row(db, row_id):
    row = db.execute('SELECT * FROM crunchyroll_titles WHERE id=?', (row_id,)).fetchone()
    return dict(row) if row else None


def _series(db, series_id):
    row = db.execute("SELECT * FROM crunchyroll_titles WHERE id=? AND kind IN ('series','movie')", (series_id,)).fetchone()
    if not row:
        raise ValueError('Crunchyroll-Titel nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def load_episodes(root, series_id, fetch=None, now=None, gap=None):
    """All seasons and episodes of a series (or the films of a film entry)."""
    now = time.time() if now is None else now
    live = fetch is None
    fetch = fetch or (lambda path, query=None: _fetch(path, query, root))
    gap = (REQUEST_GAP if live else 0) if gap is None else gap
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    ident = series_id[2:]
    found = []
    if series['kind'] == 'movie':
        answer = fetch('/content/v2/cms/movie_listings/%s/movies' % ident)
        nodes = answer.get('data') if isinstance(answer, dict) else None
        for n in nodes if isinstance(nodes, list) else []:
            it = item_from(n, series)
            if it:
                found.append(it)
    else:
        answer = fetch('/content/v2/cms/series/%s/seasons' % ident)
        seasons = answer.get('data') if isinstance(answer, dict) else None
        for i, season in enumerate(seasons if isinstance(seasons, list) else []):
            sid = str(season.get('id') or '') if isinstance(season, dict) else ''
            if not ASSET_ID.fullmatch(sid):
                continue
            if gap and i:
                time.sleep(gap)
            answer = fetch('/content/v2/cms/seasons/%s/episodes' % sid)
            nodes = answer.get('data') if isinstance(answer, dict) else None
            number = _int(season.get('season_number'), 0, 999)
            for n in nodes if isinstance(nodes, list) else []:
                it = item_from(n, series)
                if it:
                    if it['season'] is None:
                        it['season'] = number
                    if not it['season_title']:
                        it['season_title'] = _text(season.get('title'), 200)
                    found.append(it)
    free = sum(1 for it in found if it['offer'] == 'free')
    db = _connect(root)
    try:
        with db:
            _store(db, found, now)
            _set(db, 'series_checked:' + series_id, now)
            if series['kind'] == 'movie' and found:
                db.execute("UPDATE crunchyroll_titles SET watch_id=?, web_url=?, duration=COALESCE(duration, ?) WHERE id=?",
                           (found[0]['watch_id'], found[0]['web_url'], found[0]['duration'], series_id))
            if free and series['offer'] != 'free':
                db.execute("UPDATE crunchyroll_titles SET offer='free', category=? WHERE id=?", (FREE, series_id))
            _set(db, 'free_episodes_seen', int(_get(db, 'free_episodes_seen', '0') or 0) + free)
    finally:
        db.close()
    _notify('crunchyroll_episodes_loaded', episodes=len(found), free=free)
    return found


def episodes(root, series_id, fetch=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')) or str(series_id)[0] not in 'sm':
        raise ValueError('Ungültige Crunchyroll-Serie')
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
            load_episodes(root, series_id, fetch, now)
        except Exception as exc:
            error = _error(exc)
    db = _connect(root)
    try:
        checked = float(_get(db, 'series_checked:' + series_id, '0') or 0)
        series = _series(db, series_id)
        rows = [dict(r) for r in db.execute(
            """SELECT * FROM crunchyroll_titles WHERE kind='episode' AND series_id=? AND seen>=?
               ORDER BY season IS NULL, season, episode IS NULL, episode, title COLLATE NOCASE""", (series_id, checked))]
    finally:
        db.close()
    extra = _summary(root, series)
    free = sum(1 for r in rows if r['offer'] == 'free')
    for row in rows:
        row.update({**extra, **_labels(row)})
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = 0
    note = ''
    if rows:
        note = ('%d von %d Folgen sind bei Crunchyroll kostenlos, die übrigen nur mit Abo.' % (free, len(rows))) if free \
            else 'Alle Folgen gibt es bei Crunchyroll nur mit Abo. ' + FREE_END_NOTE
    return {'series': {'id': series_id, 'title': series['title'], 'web_url': series['web_url'], **extra},
            'items': rows, 'error': error, 'note': note}


def _labels(row):
    """Offer and language as own filter values and the short line on the card."""
    plus = row.get('offer') != 'free'
    langs = str(row.get('languages') or '').split(',')
    lang = 'Deutsch' if 'dub' in langs else 'dt. UT' if 'sub' in langs else ''
    badge = PAID if plus else 'kostenlos'
    if lang:
        badge += ' · ' + lang
    return {'offer_label': PAID if plus else FREE, 'badge': badge,
            'language_labels': [l for c, l in (('dub', DUB), ('sub', SUB)) if c in langs]}


def _summary(root, row, reports=None):
    """Canonical categories and rating. Every Crunchyroll title is 'Animation' even before the check."""
    import categories as fixed
    import crunchyroll_enrichment
    report = (reports if reports is not None else crunchyroll_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre') or GENRE, report, age=portal_reference.age_of(row))
    out['categories'] = sorted({c for c in out['categories'] if not fixed.is_special(c)} | {'Animation'}, key=fixed.sort_key)
    return out


FILTERS = (FREE, PAID, DUB, SUB)


def _filter(row, value):
    if value in (FREE, PAID):
        return row.get('offer_label') == value
    return value in row.get('language_labels', [])


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films or series, with canonical categories, offer and language."""
    import crunchyroll_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    kind = {'movies': 'movie', 'series': 'series'}.get(view)
    if not kind:
        return {'items': [], 'total': 0, 'offset': offset, 'view': view, 'genre_counts': []}
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM crunchyroll_titles WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = crunchyroll_enrichment.all_cached(root)
    import ui_prefs
    mine = bool(ui_prefs.load(root).get('abo_crunchyroll'))   # 0.5.107: "Meine Abos"
    for row in rows:
        row.update(_summary(root, row, reports))
        row.update(_labels(row))
        if mine and row.get('offer') != 'free':
            row['badge'] = row['badge'].replace(PAID, 'In deinem Abo', 1)
        row['playable'] = 0
    counts = portal_reference.facets(rows)
    if genre in FILTERS:
        rows = [r for r in rows if _filter(r, genre) and portal_reference.in_collection(r, collection, kind)]
    else:
        rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    return []


def item(root, row_id, fetch=None):
    """Detail view of one series, film or episode. A film's watch page is looked up once."""
    import crunchyroll_enrichment
    if not VALID_ID.fullmatch(str(row_id or '')):
        raise ValueError('Ungültiger Crunchyroll-Titel')
    db = _connect(root)
    try:
        row = _row(db, row_id)
    finally:
        db.close()
    if not row:
        raise ValueError('Crunchyroll-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'movie' and not row.get('watch_id'):
        try:
            load_episodes(root, row_id, fetch)
        except Exception as exc:
            _notify('crunchyroll_movie_lookup_failed', http_status=getattr(exc, 'code', 0) or 0)
    db = _connect(root)
    try:
        row = _row(db, row_id)
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    base = parent if row['kind'] == 'episode' and parent else row
    report = crunchyroll_enrichment.cached(root, base['id'])
    summary = _summary(root, base, {base['id']: report})
    return {'item': {**row, **summary, **_labels(row), 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'playable': 0, 'protection': 'drm'},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        movies, series = _int(_get(db, 'movies', '0')) or 0, _int(_get(db, 'series', '0')) or 0
        free_seen = _int(_get(db, 'free_episodes_seen', '0')) or 0
        return {
            'running': _ACTIVE, 'progress': _PROGRESS, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'last_loaded': float(_get(db, 'last_loaded', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'client': _get(db, 'client'),
            'movies': movies, 'series': series, 'channels': 0, 'free': _int(_get(db, 'free', '0')) or 0,
            'free_episodes_seen': free_seen, 'plus': movies + series - (_int(_get(db, 'free', '0')) or 0),
            'protection': 'drm', 'protected': movies + series, 'playable': 0,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM crunchyroll_titles WHERE kind='episode'").fetchone()[0],
            'note': FREE_END_NOTE}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='crunchyroll_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:crunchyroll'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def play_source(root, row_id):
    """Crunchyroll streams are Widevine-protected: never a source, always the reason."""
    import hls_guard
    if not VALID_ID.fullmatch(str(row_id or '')):
        raise ValueError('Ungültiger Crunchyroll-Titel')
    _notify('crunchyroll_playback', result='protected')
    raise hls_guard.DrmProtected(DRM_NOTE)
