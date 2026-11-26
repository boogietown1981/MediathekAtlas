"""filmfriend: the film library of German public libraries as a catalogue with links (0.6.52).

Björn (20.11.2026): fill the gaps of the video services. filmfriend (filmwerte GmbH) offers films, series and
documentaries free of charge to members of participating public libraries. Watching needs a library card login
on filmfriend.de; MediathekAtlas does not log in and has no player for it: every title opens on filmfriend.de
("Bei filmfriend ansehen"). Nothing is circumvented, no offline copies.

Interface (original answers saved on Björn's Mac on 20.11.2026, without login: filmfriend_samples.zip; the API
host is blocked in the build environment). Base ``https://api.tenant-group.frontend.vod.filmwerte.de/v12/``,
headers User-Agent, ``Origin``/``Referer`` https://www.filmfriend.de:

* ``GET www.filmfriend.de`` -> tenant ``id`` (fba2f8b5-…), ``landingPageId``.
* ``GET <tenant>/navigation`` -> ``primary[]`` with ``target {id, uriId, kind: "Page"}`` (Movies & Series, Kids,
  Documentaries, Collections).
* ``GET <tenant>/pages/<id>`` -> ``parts[]``; the part with ``displayMode: "FilterableThumbnails"`` ("All films and
  series") names the search behind the page: ``kinds``, ``categoryIds``, ``genreIds``, ``collectionId``.
* ``GET <tenant>/search?orderBy=Title&sortDirection=Ascending&kinds=Movie&kinds=Series&categoryIds=<id>&take=24
  &skip=N`` -> ``{results: [{kind, movie|series}], facets, totalCount}``. ``totalCount`` stays null, the end is a
  short page. The search rows carry title, synopsis, genres, categories, countries, runtime (seconds), uriId.
* ``GET <tenant>/movies/<id>`` and ``<tenant>/series/<id>`` -> additionally ``originalTitle``, ``releaseDate``,
  ``ageRatings [{name: "FSK 0", minimumAge: 0}]``, ``imdbUrl``, ``tmdbUrl``, ``artworkUris`` (CoverPortrait …).
  Fetched gently: new titles first, at most MAX_DETAILS per run, again after DETAIL_TTL.
* Episodes of a series: no endpoint found (``search?seriesId`` is ignored); series open on filmfriend.de.
* Website: ``https://www.filmfriend.de/de/movies/<uriId>``, ``/de/series/<uriId>``.
* Language: the tenant's default language is English (``defaultLanguageIsoCode``); the German website gets German
  texts. MediathekAtlas asks with ``Accept-Language: de`` (to be confirmed on Björn's Mac).

The imdbUrl gives the reference check a sure match; the age rating lets the shared rules (Kinderecke, FSK) work.
Titles and addresses never go to logs or the diagnosis.
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
ALL_CATEGORY = 'd36cbed2-7569-4b94-9080-03ce79c2ecee'   # "Movies & Series" (fallback when no page names a search)
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
MAX_ANSWER = 8 * 1024 * 1024
PAGE_SIZE = 24                # as the website asks
MAX_SEARCH_PAGES = 600        # per run, over all searches (14,400 titles)
MAX_DETAILS = 1200            # detail requests per run (0.6.54: was 400; at 1 s gap about 20 min in the background)
DETAIL_TTL = 30 * 86400
MAX_ITEMS = 20000
REQUEST_GAP = 1.0             # gentle: one request per second
RETRY_WAITS = (5, 20)         # seconds before the 2nd and 3rd try after 429/5xx
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
VALID_ID = re.compile(r'[ms]\.' + UUID.pattern)
URI_ID = re.compile(r'[a-z0-9][a-z0-9\-]{0,200}')
KINDS = {'movie': ('movie', 'm', 'movies'), 'series': ('series', 's', 'series')}
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
  drm INTEGER NOT NULL DEFAULT 1, web_url TEXT NOT NULL DEFAULT '', detail_at REAL NOT NULL DEFAULT 0,
  seen REAL NOT NULL, updated REAL NOT NULL);
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
    provider_base.ensure_schema(db, SCHEMA)        # once per process
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
    return {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',  # German texts
            'Origin': SITE, 'Referer': SITE + '/'}


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige filmfriend-Anfrage')
    req = urllib.request.Request(url, headers=headers)
    with provider_base.open_capped(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('filmfriend-Antwort zu groß')
        raw = provider_base.read_capped(response, limit)
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
    return tenant, landing if UUID.fullmatch(landing) else ''


def menu_pages(answer):
    """[(page id, title)] of the menu (``primary[].target`` with ``kind: "Page"``)."""
    out = []
    for group in ('primary', 'secondary'):
        for entry in answer.get(group) or [] if isinstance(answer, dict) else []:
            target = entry.get('target') if isinstance(entry, dict) and isinstance(entry.get('target'), dict) else {}
            ident = str(target.get('id') or '')
            if str(target.get('kind') or '') == 'Page' and UUID.fullmatch(ident) and ident not in [p for p, _ in out]:
                out.append((ident, _text(entry.get('title'), 60)))
    return out


def _ids(value):
    return tuple(str(v) for v in value if UUID.fullmatch(str(v))) if isinstance(value, list) else ()


def page_searches(answer):
    """The searches behind a page: parts with ``displayMode: "FilterableThumbnails"`` (the page's full list)."""
    out = []
    for part in answer.get('parts') or [] if isinstance(answer, dict) else []:
        if not isinstance(part, dict) or part.get('displayMode') != 'FilterableThumbnails':
            continue
        kinds = tuple(k for k in part.get('kinds') or [] if k in ('Movie', 'Series'))
        if not kinds:
            continue
        collection = str(part.get('collectionId') or '')
        search = (kinds, _ids(part.get('categoryIds')), _ids(part.get('genreIds')),
                  collection if UUID.fullmatch(collection) else '')
        if search not in out:
            out.append(search)
    return out


def search_path(tenant, search, skip):
    kinds, categories, genres, collection = search
    query = [('orderBy', 'Title'), ('sortDirection', 'Ascending')] + [('kinds', k) for k in kinds]
    query += [('categoryIds', c) for c in categories] + [('genreIds', g) for g in genres]
    if collection:
        query.append(('collectionId', collection))
    query += [('take', PAGE_SIZE), ('skip', skip)]
    return '%s/search?%s' % (tenant, urllib.parse.urlencode(query))


def search_entries(answer):
    """[(kind, object)] of a search answer, kind 'movie' or 'series'."""
    out = []
    for entry in answer.get('results') or [] if isinstance(answer, dict) else []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get('kind') or '').casefold()
        node = entry.get(kind)
        if kind in KINDS and isinstance(node, dict) and UUID.fullmatch(str(node.get('id') or '')):
            out.append((kind, node))
    return out


def _names(value, limit=6):
    out = []
    for entry in value if isinstance(value, list) else []:
        name = entry if isinstance(entry, str) else (entry.get('name') or entry.get('title')) if isinstance(entry, dict) else ''
        name = _text(name, 40)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _age(value):
    """FSK age from ``ageRatings`` ([{name: "FSK 12", minimumAge: 12}]); the highest German rating counts."""
    best = None
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('name') or '')
        if name and not re.match(r'(?i)fsk\b', name):
            continue                      # other systems (e.g. USK, JMK) are not FSK
        age = _int(entry.get('minimumAge'), 0, 21)
        if age is None:
            match = re.search(r'\d{1,2}', name)
            age = _int(match.group(0), 0, 21) if match else None
        if age in (0, 6, 12, 16, 18):
            best = age if best is None else max(best, age)
    return best


def _year(value):
    match = re.match(r'(\d{4})', str(value or ''))
    return _int(match.group(1), 1880, 2100) if match else None


def _poster(node):
    """Portrait cover (448×640), else a thumbnail, else the background in 720p."""
    artworks = [a for a in node.get('artworkUris') or [] if isinstance(a, dict)]
    for kind, fields in (('CoverPortrait', ('resolution1x', 'thumbnail', 'resolution2x')),
                         ('Thumbnail', ('resolution720', 'resolution1x', 'thumbnail')),
                         ('Background', ('resolution720', 'resolution1080'))):
        for art in artworks:
            if art.get('kind') != kind:
                continue
            for field in fields:
                url = str(art.get(field) or '')
                parts = urllib.parse.urlsplit(url)
                if parts.scheme == 'https' and parts.hostname and parts.hostname.endswith('b-cdn.net') \
                        and not parts.port and not parts.username and not re.search(r'[\s<>"\'{}]', url) and len(url) < 600:
                    return url
    return ''


def web_url(kind, uri_id, ident):
    section = KINDS[kind][2]
    return '%s/de/%s/%s' % (SITE, section, uri_id if URI_ID.fullmatch(uri_id or '') else ident)


def item_row(kind, node, detailed=False):
    """Catalogue row of a film or series from a search entry or a detail answer; None without a title."""
    title = _text(node.get('title'), 200)
    ident = str(node.get('id') or '')
    if not title or not UUID.fullmatch(ident):
        return None
    imdb = re.search(r'tt\d{5,10}', str(node.get('imdbUrl') or ''))
    tmdb = re.search(r'/(?:movie|tv)/(\d{1,9})', str(node.get('tmdbUrl') or ''))
    age = _age(node.get('ageRatings'))
    genres = _names(node.get('genres'))
    original = _text(node.get('originalTitle'), 200)
    runtime = _int(node.get('runtime'), 1, 100000) if kind == 'movie' else None   # seconds
    return {'id': '%s.%s' % (KINDS[kind][1], ident), 'kind': KINDS[kind][0], 'title': title, 'path': ident,
            'series_id': '', 'season': None, 'episode': None, 'year': _year(node.get('releaseDate')),
            'duration': runtime, 'rating': ('FSK %d' % age) if age is not None else '', 'genre': ', '.join(genres),
            'summary': _text(node.get('synopsis') or node.get('teaser'), 2000), 'poster': _poster(node),
            'imdb_id': imdb.group(0) if imdb else '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': 'Bibliothek', 'original_title': original if original.casefold() != title.casefold() else '',
            'country': ', '.join(_names(node.get('productionCountries'), 4)),
            'tmdb_id': tmdb.group(1) if tmdb else '', 'playable': 0, 'drm': 1,
            'web_url': web_url(kind, str(node.get('uriId') or ''), ident), 'detailed': detailed}


# Fields only the detail answer carries: kept from an earlier run when a title is not re-read in detail.
DETAIL_FIELDS = ('year', 'rating', 'poster', 'imdb_id', 'original_title', 'tmdb_id')


class Crawl:
    """The searches behind the menu pages (all films and series), then details for new titles."""

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
        # 0.6.143 (M1-Air-Diagnose 26.11.2026: 544 Fehler nach Netzverlust): wie dailyme nach NET_FAILURE_BUDGET
        # Verbindungsfehlern anhalten; der Lauf zählt als teilweise, der nächste Versuch folgt nach NET_RETRY.
        self.net_failures, self.stopped = 0, False
        self.search_pages, self.details, self.detail_404 = 0, 0, 0
        self.entries = {}                     # row id -> row (search data, then details)
        self.tenant = ''

    def get(self, path):
        if self.stopped:
            raise ConnectionError('filmfriend: Lauf nach Netzfehlern angehalten')
        try:
            raw = self.opener(API + path, _headers())
        except Exception as exc:
            if provider_base.network_failure(exc):
                self.net_failures += 1
                if self.net_failures >= provider_base.NET_FAILURE_BUDGET:
                    self.stopped = self.truncated = True
            raise
        answer = json.loads(raw.decode('utf-8'))
        self.requests += 1
        if self.requests % 100 == 0:
            _notify('filmfriend_sync_progress', requests=self.requests, titles=len(self.entries), errors=len(self.errors))
        if self.gap:
            time.sleep(self.gap)
        if not isinstance(answer, (dict, list)):
            raise ValueError('Unerwartete filmfriend-Antwort')
        return answer

    def searches(self):
        start = self.get(TENANT_HOST)
        self.tenant, _landing = tenant_of(start if isinstance(start, dict) else {})
        if not self.tenant:
            raise ValueError('filmfriend nennt keinen Mandanten')
        found = []
        try:
            pages = menu_pages(self.get(self.tenant + '/navigation'))
        except Exception as exc:
            self.errors.append('Menü: ' + _error(exc))
            pages = []
        for page, _title in pages:
            if self.stopped:
                break
            try:
                for search in page_searches(self.get('%s/pages/%s' % (self.tenant, page))):
                    if search not in found:
                        found.append(search)
            except Exception as exc:
                self.errors.append(_error(exc))
        return found or [(('Movie', 'Series'), (ALL_CATEGORY,), (), '')]

    def collect(self):
        for search in self.searches():
            skip = 0
            while not self.stopped:
                if self.search_pages >= MAX_SEARCH_PAGES or len(self.entries) >= MAX_ITEMS:
                    self.truncated = True
                    return
                try:
                    answer = self.get(search_path(self.tenant, search, skip))
                except Exception as exc:
                    self.errors.append(_error(exc))
                    break
                self.search_pages += 1
                entries = search_entries(answer)
                for kind, node in entries:
                    row = item_row(kind, node)
                    if row and row['id'] not in self.entries:
                        self.entries[row['id']] = row
                results = answer.get('results') if isinstance(answer, dict) else None
                if not isinstance(results, list) or len(results) < PAGE_SIZE:
                    break                     # totalCount stays null: a short page is the end
                skip += PAGE_SIZE

    def add_details(self, known, now):
        """Details for titles never read in detail (first) or not for DETAIL_TTL, at most MAX_DETAILS."""
        due = sorted((rid for rid in self.entries if now - known.get(rid, 0) >= DETAIL_TTL),
                     key=lambda rid: known.get(rid, 0))
        if len(due) > MAX_DETAILS:
            due = due[:MAX_DETAILS]
        for rid in due:
            if self.stopped:
                break
            row = self.entries[rid]
            kind = 'movie' if row['kind'] == 'movie' else 'series'
            try:
                answer = self.get('%s/%s/%s' % (self.tenant, KINDS[kind][2], row['path']))
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    self.detail_404 += 1          # no details: asked again only after DETAIL_TTL
                    self.entries[rid] = {**row, 'detail_checked': True}
                    continue
                self.errors.append(_error(exc))
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                continue
            detail = item_row(kind, answer if isinstance(answer, dict) else {}, detailed=True)
            if detail:
                self.details += 1
                self.entries[rid] = {**row, **{k: v for k, v in detail.items() if v not in (None, '') or k == 'detailed'}}


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'original_title',
          'country', 'tmdb_id', 'playable', 'drm', 'web_url')


def _store(db, items, now):
    """Search fields are always written; detail fields only from a detail answer (otherwise kept)."""
    for item in items:
        fields = [f for f in FIELDS if item.get('detailed') or f not in DETAIL_FIELDS
                  or not db.execute('SELECT 1 FROM filmfriend_items WHERE id=?', (item['id'],)).fetchone()]
        update = ','.join('%s=excluded.%s' % (f, f) for f in fields)
        detail_at = now if item.get('detailed') or item.get('detail_checked') else 0
        db.execute('''INSERT INTO filmfriend_items(id,%s,detail_at,seen,updated) VALUES(?,%s,?,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,detail_at=MAX(filmfriend_items.detail_at,excluded.detail_at),
            seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(fields), ','.join('?' * len(fields)), update),
                   (item['id'], *[item.get(f) for f in fields], detail_at, now, now))


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
        if not crawl.entries:
            raise ValueError(crawl.errors[0] if crawl.errors else 'filmfriend lieferte keine Filme')
        db = _connect(root)
        try:
            known = {r[0]: float(r[1] or 0) for r in db.execute('SELECT id, detail_at FROM filmfriend_items')}
        finally:
            db.close()
        crawl.add_details(known, now)
        rows = list(crawl.entries.values())
        waiting = sum(1 for r in rows if not (r.get('detailed') or r.get('detail_checked') or known.get(r['id'])))
        # a few failed pages leave the run complete; many make it partial (old titles stay visible)
        partial = crawl.truncated or len(crawl.errors) > max(3, 0.03 * crawl.requests)
        message = ('Katalog nur teilweise geladen: %s (%d Fehler)' % (crawl.errors[0], len(crawl.errors))
                   if crawl.errors and partial else 'Katalog nur teilweise geladen' if partial else '')
        counts = {'movies': sum(1 for r in rows if r['kind'] == 'movie'),
                  'series': sum(1 for r in rows if r['kind'] == 'series'), 'episodes': 0, 'channels': 0}
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'), ('last_error', message),
                                   ('last_http_status', 0), ('next_attempt', now + (provider_base.NET_RETRY if crawl.stopped else 24 * 3600)),
                                   ('requests', crawl.requests), ('pages', crawl.search_pages),
                                   ('details_waiting', waiting), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('filmfriend_sync_completed', partial=partial, requests=crawl.requests, pages=crawl.search_pages,
                errors=len(crawl.errors), truncated=crawl.truncated, details=crawl.details, detail_404=crawl.detail_404,
                details_waiting=waiting, net_failures=crawl.net_failures, stopped=crawl.stopped, imdb=sum(1 for r in rows if r['imdb_id']), **counts)
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
    """filmfriend names no episode list without login: the series page links to filmfriend.de."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige filmfriend-Serie')
    db = _connect(root)
    try:
        series = _row(db, series_id)
    finally:
        db.close()
    if not series:
        raise ValueError('filmfriend-Serie nicht im Katalog; bitte Katalog neu laden')
    return {'series': {'id': series_id, 'title': series['title'], **_summary(root, series)}, 'items': [], 'error': '',
            'note': 'Die Folgen stehen auf filmfriend.de (Anmeldung mit Bibliotheksausweis).'}


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    import filmfriend_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    kind = 'series' if view == 'series' else 'movie'
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = "FROM filmfriend_items WHERE kind=? AND seen>=?"
        args = [kind, last]
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
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
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
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'episodes': 0, 'channels': 0,
            'pages': _int(_get(db, 'pages', '0')) or 0, 'requests': _int(_get(db, 'requests', '0')) or 0,
            'details_waiting': _int(_get(db, 'details_waiting', '0')) or 0,
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
