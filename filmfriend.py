"""filmfriend: the film library of German public libraries as a catalogue with links (0.6.52).

Björn (20.11.2026): fill the gaps of the video services. filmfriend (filmwerte GmbH) offers several thousand
films, documentaries and children's films free of charge to members of participating public libraries. Watching
needs a library card login on filmfriend.de; MediathekAtlas does not log in and has no player for it: every
title opens on filmfriend.de ("Bei filmfriend ansehen"). Nothing is circumvented, no offline copies.

Interface (explored read-only and without login on Björn's Mac, 20.11.2026; the API host is blocked in the
build environment, so the field handling below is deliberately tolerant):

* ``GET https://api.tenant-group.frontend.vod.filmwerte.de/v12/www.filmfriend.de`` -> the tenant (``id``) and
  ``landingPageId``. Headers: User-Agent and ``Origin: https://www.filmfriend.de``.
* ``GET /v12/<tenant>/navigation`` -> menu with page references.
* ``GET /v12/<tenant>/pages/<page id>`` -> blocks (Banner, Collection, Genres, Heading, Movie, SearchResult,
  Video) with movie references ``{id, uriId, kind: "Movie"}`` and references to further pages.
* ``GET /v12/<tenant>/movies/<id>`` -> ``title``, ``originalTitle``, ``synopsis``, ``releaseDate``,
  ``ageRatings``, ``runtime``, ``genres``, ``categories``, ``productionCountries``, ``imdbUrl``, ``tmdbUrl``,
  ``filmportalUrl``, ``hasTrailer``, ``bonusVideos``.

The catalogue is collected from the pages reachable from the start page and the menu (breadth first, fixed
limits), then every film is read once. imdbUrl/tmdbUrl give the reference check a sure match; the age rating
lets the shared rules (Kinderecke, FSK) work. Titles and addresses never go to logs or the diagnosis.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import portal_reference
import provider_base

KEY = 'filmfriend'
NAME = 'filmfriend'
SITE = 'https://www.filmfriend.de'
API = 'https://api.tenant-group.frontend.vod.filmwerte.de/v12/'
API_HOSTS = frozenset({'api.tenant-group.frontend.vod.filmwerte.de'})
TENANT_HOST = 'www.filmfriend.de'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
MAX_ANSWER = 8 * 1024 * 1024
MAX_PAGES = 400               # pages of the website read per run
MAX_ITEMS = 15000
REQUEST_GAP = 0.3
RETRY_WAITS = (3, 10)         # seconds before the 2nd and 3rd try after 429/5xx
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
VALID_ID = re.compile(r'm\.' + UUID.pattern)
URI_ID = re.compile(r'[a-z0-9][a-z0-9\-]{0,200}')
PAGE_LINK = re.compile(r'/pages/(' + UUID.pattern + r')')
LIBRARY_NOTE = 'Ansehen mit Bibliotheksausweis einer teilnehmenden Bibliothek auf filmfriend.de'

_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS filmfriend_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', original_title TEXT NOT NULL DEFAULT '',
  country TEXT NOT NULL DEFAULT '', tmdb_id TEXT NOT NULL DEFAULT '', playable INTEGER NOT NULL DEFAULT 0,
  drm INTEGER NOT NULL DEFAULT 1, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS filmfriend_items_kind ON filmfriend_items(kind, seen);
CREATE TABLE IF NOT EXISTS filmfriend_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    db = provider_base.connect(root, 'filmfriend.sqlite3')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM filmfriend_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO filmfriend_state(name,value) VALUES(?,?)', (key, str(value)))


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


# ---------------------------------------------------------------- network

def _headers():
    return {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',
            'Origin': SITE, 'Referer': SITE + '/'}


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige filmfriend-Anfrage')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('filmfriend-Antwort zu groß')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('filmfriend-Antwort zu groß')
    return raw


def _error(exc):
    status = getattr(exc, 'code', None)
    if status in (401, 403):
        return 'filmfriend verweigert den Zugriff (HTTP %d)' % status
    if status == 429:
        return 'filmfriend bremst die Abrufe (HTTP 429), später erneut versuchen'
    if status:
        return 'filmfriend antwortet mit HTTP %d' % status
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('filmfriend ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'filmfriend-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def _walk(node, depth=0):
    """Every dict inside an answer (depth limited)."""
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node[:2000]:
            yield from _walk(value, depth + 1)


def tenant_of(answer):
    """(tenant id, landing page id) of the answer for www.filmfriend.de."""
    tenant = ''
    for key in ('id', 'tenantId', 'tenant'):
        value = answer.get(key)
        if isinstance(value, dict):
            value = value.get('id')
        if UUID.fullmatch(str(value or '')):
            tenant = str(value)
            break
    landing = str(answer.get('landingPageId') or '')
    if not UUID.fullmatch(landing):
        landing = next((str(d['landingPageId']) for d in _walk(answer)
                        if UUID.fullmatch(str(d.get('landingPageId') or ''))), '')
    return tenant, landing


def page_refs(answer):
    """Ids of pages an answer links to (``pageId``, ``kind: "Page"`` or ``…/pages/<id>`` links)."""
    out = []
    for node in _walk(answer):
        candidates = [node.get('pageId'), node.get('landingPageId')]
        if str(node.get('kind') or node.get('type') or '').casefold() == 'page':
            candidates.append(node.get('id'))
        for key in ('link', 'href', 'url', 'path', 'target'):
            value = node.get(key)
            if isinstance(value, str):
                match = PAGE_LINK.search(value)
                if match:
                    candidates.append(match.group(1))
        for value in candidates:
            value = str(value or '')
            if UUID.fullmatch(value) and value not in out:
                out.append(value)
    return out


def movie_refs(answer):
    """[(movie id, uriId)] referenced in a page answer (``kind: "Movie"``)."""
    out, seen = [], set()
    for node in _walk(answer):
        if str(node.get('kind') or '').casefold() != 'movie':
            continue
        ident = str(node.get('id') or '')
        if UUID.fullmatch(ident) and ident not in seen:
            seen.add(ident)
            uri = str(node.get('uriId') or '')
            out.append((ident, uri if URI_ID.fullmatch(uri) else ''))
    return out


def other_kinds(answer):
    """Kinds of referenced entries that are not films or pages (counted for the diagnosis only)."""
    kinds = {}
    for node in _walk(answer):
        kind = str(node.get('kind') or '')
        if kind and kind.casefold() not in ('movie', 'page') and UUID.fullmatch(str(node.get('id') or '')):
            kinds[kind[:30]] = kinds.get(kind[:30], 0) + 1
    return kinds


def _names(value, limit=6):
    out = []
    for entry in value if isinstance(value, list) else []:
        name = entry if isinstance(entry, str) else (entry.get('name') or entry.get('title') or entry.get('label')) \
            if isinstance(entry, dict) else ''
        name = _text(name, 40)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _age(value):
    """FSK age from ``ageRatings`` (list of {country/system, value/age} or plain numbers/texts)."""
    entries = value if isinstance(value, list) else [value]
    best = None
    for entry in entries:
        if isinstance(entry, dict):
            system = str(entry.get('country') or entry.get('system') or entry.get('type') or '').casefold()
            if system and not any(s in system for s in ('de', 'fsk', 'germany')):
                continue
            entry = next((entry.get(k) for k in ('value', 'age', 'minAge', 'rating', 'name') if entry.get(k) is not None), None)
        match = re.search(r'\d{1,2}', str(entry if entry is not None else ''))
        age = _int(match.group(0), 0, 21) if match else None
        if age is not None and age in (0, 6, 12, 16, 18):
            best = age if best is None else max(best, age)
    return best


def _year(value):
    match = re.match(r'(\d{4})', str(value or ''))
    year = _int(match.group(1), 1880, 2100) if match else None
    return year


def _runtime(value):
    """Seconds. ``runtime`` may come in minutes (small numbers), seconds or ISO 8601 (PT1H32M)."""
    if isinstance(value, str) and value.startswith('PT'):
        match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', value)
        if not match:
            return None
        h, m, s = (int(x or 0) for x in match.groups())
        return (h * 3600 + m * 60 + s) or None
    number = _int(value, 1, 10 ** 7)
    if number is None:
        return None
    return number * 60 if number < 600 else number          # 600+ can only be seconds for a film


def _image(answer):
    for node in _walk(answer):
        for key in ('poster', 'posterUrl', 'cover', 'image', 'imageUrl', 'thumbnail', 'url', 'src'):
            value = node.get(key)
            if isinstance(value, str):
                parts = urllib.parse.urlsplit(value)
                if parts.scheme == 'https' and parts.hostname and not parts.port and not parts.username \
                        and re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', parts.path + ('?' if parts.query else ''), re.I) \
                        and not re.search(r'[\s<>"\'{}]', value) and len(value) < 600:
                    return value
    return ''


def web_url(uri_id, movie_id):
    """Page of a film on filmfriend.de (the website addresses films by their uriId)."""
    if URI_ID.fullmatch(uri_id or ''):
        return '%s/de/movies/%s' % (SITE, uri_id)
    return '%s/de/movies/%s' % (SITE, movie_id)


def movie_row(answer, movie_id, uri_id=''):
    """Catalogue row of one film; None without a title."""
    title = _text(answer.get('title') or answer.get('name'), 200)
    if not title:
        return None
    imdb = re.search(r'tt\d{5,10}', str(answer.get('imdbUrl') or answer.get('imdbId') or ''))
    tmdb = re.search(r'/movie/(\d{1,9})', str(answer.get('tmdbUrl') or ''))
    uri = str(answer.get('uriId') or uri_id or '')
    age = _age(answer.get('ageRatings') if answer.get('ageRatings') is not None else answer.get('ageRating'))
    genres = _names(answer.get('genres'))
    for name in _names(answer.get('categories'), 4):
        if name not in genres:
            genres.append(name)
    original = _text(answer.get('originalTitle'), 200)
    return {'id': 'm.' + movie_id, 'kind': 'movie', 'title': title, 'path': movie_id, 'series_id': '',
            'season': None, 'episode': None, 'year': _year(answer.get('releaseDate') or answer.get('productionYear')),
            'duration': _runtime(answer.get('runtime') if answer.get('runtime') is not None else answer.get('duration')),
            'rating': ('FSK %d' % age) if age is not None else '', 'genre': ', '.join(genres[:8]),
            'summary': _text(answer.get('synopsis') or answer.get('description'), 2000), 'poster': _image(answer),
            'imdb_id': imdb.group(0) if imdb else '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': 'Bibliothek', 'original_title': original if original != title else '',
            'country': ', '.join(_names(answer.get('productionCountries'), 4)),
            'tmdb_id': tmdb.group(1) if tmdb else '', 'playable': 0, 'drm': 1,
            'web_url': web_url(uri if URI_ID.fullmatch(uri) else '', movie_id)}


class Crawl:
    """Pages reachable from the start page and the menu, then every film found on them."""

    def __init__(self, opener, gap, waits=()):
        self.gap, self.waits = gap, tuple(waits)
        raw = opener

        def patient(url, headers):
            for attempt in range(len(self.waits) + 1):
                try:
                    return raw(url, headers)
                except urllib.error.HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == len(self.waits):
                        raise
                    time.sleep(self.waits[attempt])
        self.opener = patient
        self.requests, self.errors, self.truncated = 0, [], False
        self.pages_read, self.movie_404, self.kinds = 0, 0, {}
        self.movies = {}                      # id -> uriId (order of discovery)

    def get(self, path):
        answer = json.loads(self.opener(API + path, _headers()).decode('utf-8'))
        self.requests += 1
        if self.requests % 200 == 0:
            _notify('filmfriend_sync_progress', requests=self.requests, movies=len(self.movies), errors=len(self.errors))
        if self.gap:
            time.sleep(self.gap)
        if not isinstance(answer, (dict, list)):
            raise ValueError('Unerwartete filmfriend-Antwort')
        return answer

    def collect(self):
        start = self.get(TENANT_HOST)
        tenant, landing = tenant_of(start if isinstance(start, dict) else {})
        if not tenant:
            raise ValueError('filmfriend nennt keinen Mandanten')
        self.tenant = tenant
        queue = [landing] if landing else []
        try:
            for ref in page_refs(self.get(tenant + '/navigation')):
                if ref not in queue:
                    queue.append(ref)
        except Exception as exc:
            self.errors.append('Menü: ' + _error(exc))
        if not queue:
            raise ValueError('filmfriend nennt keine Startseite')
        done = set()
        while queue:
            if len(done) >= MAX_PAGES or len(self.movies) >= MAX_ITEMS:
                self.truncated = True
                break
            page = queue.pop(0)
            if page in done:
                continue
            done.add(page)
            try:
                answer = self.get('%s/pages/%s' % (tenant, page))
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    continue
                self.errors.append(_error(exc))
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                continue
            self.pages_read += 1
            for ident, uri in movie_refs(answer):
                if ident not in self.movies:
                    self.movies[ident] = uri
            for kind, count in other_kinds(answer).items():
                self.kinds[kind] = self.kinds.get(kind, 0) + count
            queue += [ref for ref in page_refs(answer) if ref not in done and ref not in queue]

    def rows(self):
        out = []
        for ident, uri in list(self.movies.items())[:MAX_ITEMS]:
            try:
                answer = self.get('%s/movies/%s' % (self.tenant, ident))
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    self.movie_404 += 1
                    continue
                self.errors.append(_error(exc))
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                continue
            row = movie_row(answer if isinstance(answer, dict) else {}, ident, uri)
            if row:
                out.append(row)
        return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'original_title',
          'country', 'tmdb_id', 'playable', 'drm', 'web_url')


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)
    for item in items:
        db.execute('''INSERT INTO filmfriend_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item.get(f) for f in FIELDS], now, now))


def sync(root, opener=None, now=None, gap=None, waits=None):
    """Read the catalogue. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('filmfriend_sync_started')
    try:
        crawl = Crawl(opener or _open, gap, RETRY_WAITS if opener is None else (waits or ()))
        crawl.collect()
        rows = crawl.rows()
        if not rows:
            raise ValueError(crawl.errors[0] if crawl.errors else 'filmfriend lieferte keine Filme')
        # a few failed pages leave the run complete; many make it partial (old titles stay visible)
        partial = crawl.truncated or len(crawl.errors) > max(3, 0.03 * crawl.requests)
        message = ('Katalog nur teilweise geladen: %s (%d Fehler)' % (crawl.errors[0], len(crawl.errors))
                   if crawl.errors and partial else 'Katalog nur teilweise geladen' if partial else '')
        counts = {'movies': len(rows), 'series': 0, 'episodes': 0, 'channels': 0}
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'), ('last_error', message),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600),
                                   ('requests', crawl.requests), ('pages', crawl.pages_read), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('filmfriend_sync_completed', partial=partial, requests=crawl.requests, pages=crawl.pages_read,
                errors=len(crawl.errors), truncated=crawl.truncated, movie_404=crawl.movie_404,
                imdb=sum(1 for r in rows if r['imdb_id']), other_kinds=dict(sorted(crawl.kinds.items())[:10]), **counts)
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
        _notify('filmfriend_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute('SELECT * FROM filmfriend_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _summary(root, row, reports=None):
    import filmfriend_enrichment
    report = (reports if reports is not None else filmfriend_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))


def _labels(row):
    return {'offer_label': LIBRARY_NOTE, 'badge': 'Mit Bibliotheksausweis', 'playable': 0}


def episodes(root, series_id, now=None):
    raise ValueError('filmfriend führt hier nur Filme')


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    import filmfriend_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    if view != 'movies':
        return {'items': [], 'total': 0, 'offset': offset, 'view': view, 'genre_counts': []}
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = "FROM filmfriend_items WHERE kind='movie' AND seen>=?"
        args = [last]
        if query:
            sql += ' AND (title LIKE ? OR original_title LIKE ? OR genre LIKE ? OR summary LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = filmfriend_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
        row.update(_labels(row))
    facets = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, 'movie')]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': facets}


def item(root, item_id):
    import filmfriend_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger filmfriend-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row:
        raise ValueError('filmfriend-Titel nicht im Katalog; bitte Katalog neu laden')
    report = filmfriend_enrichment.cached(root, item_id)
    return {'item': {**row, **_summary(root, row, {row['id']: report}), **_labels(row)}, 'series': None,
            'reference': report}


def state(root):
    db = _connect(root)
    try:
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': 0, 'episodes': 0, 'channels': 0,
            'pages': _int(_get(db, 'pages', '0')) or 0, 'requests': _int(_get(db, 'requests', '0')) or 0,
            'note': LIBRARY_NOTE}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='filmfriend_catalog_sync').start()
    return True


def should_sync(root, now=None):
    return provider_base.catalog_due(root, sys.modules[__name__], state(root), now)


def loop(root, stop):
    provider_base.loop(root, stop, KEY, sys.modules[__name__])


def play_source(root, item_id):
    """filmfriend plays only after a library login on filmfriend.de: never a source here."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger filmfriend-Titel')
    raise ValueError('filmfriend-Filme laufen nur nach Anmeldung mit Bibliotheksausweis auf filmfriend.de; '
                     'bitte „Bei filmfriend ansehen“ wählen.')
