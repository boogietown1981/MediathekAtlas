"""ServusTV On: the free video library and the live channels of ServusTV (0.5.101, rebuilt on the real interfaces in 0.5.102).

Björn (13.11.2026, decision card "Beides"): connect ServusTV On with playback in the own player, and
RTL+ as a catalogue with links. ServusTV is free, needs no account and streams plain HLS without copy
protection; every stream is still checked with hls_guard.

Interfaces, taken from Björn's HAR recording of servustv.com (13.11.2026). ServusTV runs on the
Red Bull Media House platform; no login, no token, only the usual Referer:

* Catalogue: ``https://tv-api.redbull.com/products/v5.3/stv/de/de/<id>`` describes a page, show or
  video; a page or show names its rails in ``collections`` (ids). ``/collections/v5.3/stv/de/de/
  <id>?offset=<n>`` returns ``cards`` (20 per page, ``meta.total``, ``meta.next``). Cards carry
  ``id``, ``title``, ``content_type`` (``show``, ``episode``, ``film``, ``clip``, ``subchannel``,
  ``video_channel``, ``stop`` …), ``show_name``/``subheading``, ``season_number``,
  ``episode_number``, ``duration`` (ms), descriptions, ``content_color`` and images under
  ``resources.redbull.tv/<id>/<type>/{im}``. The crawl starts at the page ``sendungen`` (all
  formats) and the home page ``discover`` and follows sub-pages (categories) and shows.
* Playback: ``https://api-player.redbull.com/tv?videoId=<id>&deviceGroup=group_5&locale=de&tenant=stv``
  -> ``videoUrl`` (``play.redbull.com/main/v1/…m3u8``: fMP4 HLS up to 1080p, audio as a separate
  rendition, no EXT-X-KEY) or ``playabilityErrors`` (youth protection with hours, not yet
  available, geo block). Live channels (``video_channel``: ServusTV, Red Bull TV, Wetterpanorama)
  answer the same way (ServusTV live: ``freqsyndlin.servustv.com``).

Clips and trailers are left out (Björn: no "Sonstiges"); films, episodes and live channels are kept.
No offline copies: ServusTV allows downloads only inside its own app. Titles and URLs never go to
logs or the diagnosis export.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import portal_reference

KEY = 'servustv'
NAME = 'ServusTV'
SITE = 'https://www.servustv.com'
TV_API = 'https://tv-api.redbull.com'
PLAYER = 'https://api-player.redbull.com/tv'
SCOPE = '/stv/de/de/'
SEEDS = ('sendungen', 'discover')
API_HOSTS = frozenset({'tv-api.redbull.com', 'api-player.redbull.com'})
IMAGE = 'im:i:w_480,q_70'
MAX_ANSWER = 8 * 1024 * 1024
MAX_ITEMS = 30000
MAX_PRODUCTS = 600           # pages and shows read per run
MAX_COLLECTIONS = 1500
MAX_COLLECTION_PAGES = 60    # 20 cards each
REQUEST_GAP = 0.25
SOURCE_TTL = 120
MIN_FILM = 20 * 60           # seconds; shorter videos without a show are clips
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
RB_ID = re.compile(r'(?:AA-?|PN|AP)[A-Z0-9]{8,30}|[a-z][a-z0-9\-]{2,40}')
COLLECTION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[a-z][a-z0-9\-]{2,40}')
VALID_ID = re.compile(r'(?:[vc]\.(?:AA-?|PN)[A-Z0-9]{8,30}|s\.(?:AA-?[A-Z0-9]{8,30}|n-[a-z0-9\-]{1,80}))')
SKIP_TYPES = {'clip', 'trailer', 'stop', 'live_program', 'event', 'person', 'promo', 'external'}
PAGE_TYPES = {'subchannel', 'page', 'system', 'topic', 'channel'}
# ServusTV live channels if the catalogue cannot be read (ids from the HAR of 13.11.2026).
LIVE_FALLBACK = (('c.PN0B1EC15B2FE10', 'ServusTV', 1),)

_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS servustv_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', published REAL,
  playable INTEGER NOT NULL DEFAULT 1, drm INTEGER NOT NULL DEFAULT -1, web_url TEXT NOT NULL DEFAULT '',
  seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS servustv_items_kind ON servustv_items(kind, seen);
CREATE INDEX IF NOT EXISTS servustv_items_series ON servustv_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS servustv_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    """Technical counters only; never URLs or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(root / 'servustv.sqlite3'), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM servustv_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO servustv_state(name,value) VALUES(?,?)', (key, str(value)))


def _text(value, limit):
    """Plain text: HTML entities resolved, tags removed, whitespace folded."""
    value = html.unescape(re.sub(r'<[^>]{0,400}>', ' ', html.unescape(str(value or ''))))
    return ' '.join(value.split())[:limit]


def _int(value, low=None, high=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def slug(value):
    value = _text(value, 120).casefold()
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
        value = value.replace(a, b)
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:80]




# ---------------------------------------------------------------- network

def _headers():
    return {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',
            'Origin': SITE, 'Referer': SITE + '/'}


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige ServusTV-Anfrage')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('ServusTV-Antwort zu groß')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('ServusTV-Antwort zu groß')
    return raw


def _json(opener, url):
    answer = json.loads(opener(url, _headers()).decode('utf-8'))
    if not isinstance(answer, dict):
        raise ValueError('Unerwartete ServusTV-Antwort')
    return answer


def product(opener, ident):
    if not RB_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültige ServusTV-Seite')
    return _json(opener, TV_API + '/products/v5.3' + SCOPE + ident)


def collection(opener, ident, offset=0):
    if not COLLECTION_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültige ServusTV-Liste')
    return _json(opener, TV_API + '/collections/v5.3' + SCOPE + ident + '?' + urllib.parse.urlencode({'offset': int(offset)}))


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return 'ServusTV verweigert den Zugriff (HTTP %d)' % code
    if code == 451:
        return 'ServusTV bietet seine Videos in diesem Land nicht an (HTTP 451)'
    if code:
        return 'ServusTV antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('ServusTV ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'ServusTV-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def image(card, kinds=('rbtv_display_art_portrait', 'rbtv_display_art_landscape', 'rbtv_background_landscape')):
    """Image address from the ``{im}`` template of resources.redbull.tv (https only)."""
    res = card.get('media_resources') if isinstance(card.get('media_resources'), dict) else {}
    for kind in kinds:
        url = str((res.get(kind) or {}).get('url') or '') if isinstance(res.get(kind), dict) else ''
        url = url.replace('{im}', IMAGE)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == 'https' and parts.hostname == 'resources.redbull.tv' and not parts.port \
                and not re.search(r'[\s<>"\'{}]', url) and len(url) < 400:
            return url
    return ''


def _ms(value):
    seconds = _int(value, 1000, 24 * 3600 * 1000)
    return seconds // 1000 if seconds else None


def _genres(card):
    out = []
    for value in (card.get('content_color') or []) + (card.get('tags') or []):
        name = _text(value, 40)
        if name and name not in out:
            out.append(name)
    return out[:6]


def _web(card):
    url = str(card.get('share_url') or '')
    if re.fullmatch(r'https://www\.servustv\.com/[a-z]{2}/(?:page|video)/[A-Za-z0-9:\-]{4,60}(?:/[a-z0-9\-]{1,160})?', url):
        return url.replace('/page/page:', '/page/')
    ident = str(card.get('id') or '')
    return '%s/de/page/%s' % (SITE, ident) if RB_ID.fullmatch(ident) else SITE + '/de'


def _summary_of(card):
    for key in ('long_description', 'short_description', 'description'):
        text = _text(card.get(key), 1600)
        if text:
            return text
    return ''


def _base(card, kind):
    return {'kind': kind, 'title': _text(card.get('title'), 200), 'path': str(card.get('id')), 'series_id': '',
            'season': None, 'episode': None, 'year': None, 'duration': _ms(card.get('duration')),
            'rating': '', 'genre': ', '.join(_genres(card)), 'summary': _summary_of(card), 'poster': image(card),
            'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': (_genres(card) or [''])[0], 'published': None,
            'playable': 1 if card.get('playable') is not False else 0, 'drm': -1, 'web_url': _web(card)}


class Crawl:
    """Breadth-first walk over pages, shows and rails, with fixed request limits."""

    def __init__(self, opener, gap):
        self.opener, self.gap = opener, gap
        self.items, self.shows, self.show_names = {}, {}, {}
        self.pending_products, self.done_products = [], set()
        self.pending_collections, self.done_collections = [], set()
        self.requests, self.errors, self.truncated = 0, [], False

    def _pause(self):
        self.requests += 1
        if self.requests % 200 == 0:
            # 0.5.104: progress in the diagnosis (counts only, no titles or addresses)
            _notify('servustv_sync_progress', requests=self.requests, items=len(self.items),
                    shows=len(self.shows), errors=len(self.errors))
        if self.gap:
            time.sleep(self.gap)

    def want_product(self, ident, front=False):
        if ident and ident not in self.done_products and ident not in self.pending_products and RB_ID.fullmatch(ident):
            (self.pending_products.insert(0, ident) if front else self.pending_products.append(ident))

    def want_collection(self, ident):
        if ident and ident not in self.done_collections and ident not in self.pending_collections \
                and COLLECTION_ID.fullmatch(ident):
            self.pending_collections.append(ident)

    def card(self, card, show=None):
        if not isinstance(card, dict):
            return
        ident, ctype = str(card.get('id') or ''), str(card.get('content_type') or '')
        if not RB_ID.fullmatch(ident) or ident.islower():
            return
        if ctype in PAGE_TYPES:
            self.want_product(ident)
            return
        if ctype == 'show':
            if ident not in self.shows:
                self.shows[ident] = {**_base(card, 'series'), 'id': 's.' + ident, 'duration': None}
                self.show_names.setdefault(_text(card.get('title'), 200).casefold(), ident)
            self.want_product(ident)
            return
        if ctype == 'video_channel':
            self.items.setdefault('c.' + ident, {**_base(card, 'channel'), 'id': 'c.' + ident, 'genre': 'Live',
                                                 'category': 'Live', 'duration': None})
            return
        if ctype in SKIP_TYPES or card.get('type') not in (None, 'video'):
            return
        row = _base(card, 'movie')
        if not row['title']:
            return
        show_name = _text(card.get('show_name') or (card.get('subheading') if ctype == 'episode' else ''), 200)
        if ctype == 'episode' or show is not None:
            row.update(kind='episode', season=_int(card.get('season_number'), 0, 999),
                       episode=_int(card.get('episode_number'), 0, 9999))
            row['_show'] = show or ''
            row['_show_name'] = show_name or (self.shows.get(show) or {}).get('title', '')
        elif ctype != 'film' and (row['duration'] or 0) < MIN_FILM:
            return                                      # short video without a show: a clip
        self.items.setdefault('v.' + ident, {**row, 'id': 'v.' + ident})
        if show and self.items['v.' + ident].get('_show') == '':
            self.items['v.' + ident]['_show'] = show

    def run_collection(self, ident, show=None):
        offset, pages = 0, 0
        while pages < MAX_COLLECTION_PAGES and len(self.items) < MAX_ITEMS:
            answer = collection(self.opener, ident, offset)
            self._pause()
            cards = answer.get('cards') if isinstance(answer.get('cards'), list) else []
            for card in cards:
                self.card(card, show)
            meta = answer.get('meta') if isinstance(answer.get('meta'), dict) else {}
            total = _int(meta.get('total'), 0) or 0
            offset += len(cards)
            pages += 1
            if not cards or not meta.get('next') or (total and offset >= total):
                return
        self.truncated = True

    def run_product(self, ident):
        answer = product(self.opener, ident)
        self._pause()
        show = ident if str(answer.get('content_type') or '') == 'show' else None
        for entry in answer.get('collections') or []:
            cid = str((entry or {}).get('id') or '') if isinstance(entry, dict) else str(entry or '')
            if isinstance(entry, dict) and entry.get('list_type') == 'reference':
                continue                                  # personal lists (favourites, continue watching)
            if show:
                if cid not in self.done_collections and COLLECTION_ID.fullmatch(cid):
                    self.done_collections.add(cid)
                    try:
                        self.run_collection(cid, show)
                    except Exception as exc:
                        self.errors.append(_error(exc))
            else:
                self.want_collection(cid)

    def run(self):
        for seed in SEEDS:
            self.want_product(seed)
        while (self.pending_products or self.pending_collections) and len(self.items) < MAX_ITEMS:
            if self.pending_collections and len(self.done_collections) < MAX_COLLECTIONS:
                cid = self.pending_collections.pop(0)
                self.done_collections.add(cid)
                try:
                    self.run_collection(cid)
                except Exception as exc:
                    self.errors.append(_error(exc))
                continue
            self.pending_collections = []
            if not self.pending_products:
                break
            if len(self.done_products) >= MAX_PRODUCTS:
                self.truncated = True
                break
            pid = self.pending_products.pop(0)
            self.done_products.add(pid)
            try:
                self.run_product(pid)
            except urllib.error.HTTPError as exc:
                if exc.code != 404 or pid not in SEEDS:
                    self.errors.append(_error(exc))
            except Exception as exc:
                self.errors.append(_error(exc))
        if self.pending_products or self.pending_collections:
            self.truncated = True

    def rows(self):
        """Catalogue rows: films, shows with their episodes, live channels."""
        out, used = [], set()
        named = {}
        for row in self.items.values():
            if row['kind'] != 'episode':
                continue
            show = row.pop('_show', '') or self.show_names.get(row.get('_show_name', '').casefold(), '')
            name = row.pop('_show_name', '')
            if show:
                sid = 's.' + show
            elif name:
                sid = 's.n-' + (slug(name) or 'servustv')
                named.setdefault(sid, {'title': name, 'poster': row['poster'], 'genre': row['genre'],
                                       'category': row['category']})
            else:
                row['kind'] = 'movie'
                out.append(row)
                continue
            row['series_id'] = sid
            used.add(sid)
            out.append(row)
        for row in self.items.values():
            if row['kind'] in ('movie', 'channel') and row not in out:
                row.pop('_show', None)
                row.pop('_show_name', None)
                out.append(row)
        for ident, show in self.shows.items():
            if show['id'] in used:
                out.append(show)
        for sid, info in named.items():
            if sid in used:
                out.append({'id': sid, 'kind': 'series', 'title': info['title'], 'path': '', 'series_id': '',
                            'season': None, 'episode': None, 'year': None, 'duration': None, 'rating': '',
                            'genre': info['genre'], 'summary': '', 'poster': info['poster'], 'imdb_id': '',
                            'imdb_score': None, 'imdb_votes': None, 'number': None, 'category': info['category'],
                            'published': None, 'playable': 1, 'drm': -1, 'web_url': SITE + '/de/sendungen'})
        return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'published',
          'playable', 'drm', 'web_url')
_KEEP = ('drm',)


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS if f not in _KEEP)
    for item in items:
        db.execute('''INSERT INTO servustv_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item.get(f) for f in FIELDS], now, now))


def live_rows():
    return [{'id': cid, 'kind': 'channel', 'title': title, 'path': cid[2:], 'series_id': '', 'season': None,
             'episode': None, 'year': None, 'duration': None, 'rating': '', 'genre': 'Live',
             'summary': 'Das laufende Programm von ServusTV.', 'poster': '', 'imdb_id': '', 'imdb_score': None,
             'imdb_votes': None, 'number': number, 'category': 'Live', 'published': None, 'playable': 1, 'drm': -1,
             'web_url': SITE + '/de/video/' + cid[2:]} for cid, title, number in LIVE_FALLBACK]


def sync(root, opener=None, now=None, gap=None):
    """Read the ServusTV library. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
            # 0.5.104: errors of the WordPress/sitemap reader of 0.5.101 no longer apply (Björn's diagnosis).
            if re.match(r'(WordPress|Sitemap)', _get(db, 'last_error')):
                _set(db, 'last_error', '')
    finally:
        db.close()
    _notify('servustv_sync_started')
    try:
        crawl = Crawl(opener or _open, gap)
        crawl.run()
        rows = crawl.rows()
        if not any(r['kind'] in ('movie', 'episode') for r in rows):
            raise ValueError(crawl.errors[0] if crawl.errors else 'ServusTV lieferte keine Videos')
        channels = [r for r in rows if r['kind'] == 'channel']
        for number, row in enumerate(sorted(channels, key=lambda r: (r['id'] != LIVE_FALLBACK[0][0], r['title'])), 1):
            row['number'] = number
        if not channels:
            rows += live_rows()
        partial = crawl.truncated or bool(crawl.errors)
        counts = {'movies': sum(1 for r in rows if r['kind'] == 'movie'),
                  'series': sum(1 for r in rows if r['kind'] == 'series'),
                  'episodes': sum(1 for r in rows if r['kind'] == 'episode'),
                  'channels': sum(1 for r in rows if r['kind'] == 'channel')}
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + crawl.errors[0] if crawl.errors else '')) if partial else ''),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600),
                                   ('requests', crawl.requests), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('servustv_sync_completed', partial=partial, requests=crawl.requests, **counts)
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
        _notify('servustv_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute('SELECT * FROM servustv_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _summary(root, row, reports=None):
    import servustv_enrichment
    report = (reports if reports is not None else servustv_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report)


def episodes(root, series_id, now=None):
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige ServusTV-Sendung')
    db = _connect(root)
    try:
        series = _row(db, series_id)
        if not series or series['kind'] != 'series':
            raise ValueError('ServusTV-Sendung nicht im Katalog; bitte Katalog neu laden')
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM servustv_items WHERE kind='episode' AND series_id=? AND seen>=? "
            "ORDER BY season IS NULL, season, episode IS NULL, episode, published DESC, title", (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = 0 if row['drm'] == 1 else 1
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': ''}


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films, formats (series) or the live channels, with canonical categories."""
    import servustv_enrichment
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM servustv_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR summary LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
        if kind == 'series':
            counts = dict(db.execute("SELECT series_id,COUNT(*) FROM servustv_items WHERE kind='episode' AND seen>=? "
                                     "GROUP BY series_id", (last,)).fetchall())
            for row in rows:
                row['episodes'] = counts.get(row['id'], 0)
    finally:
        db.close()
    for row in rows:
        row['playable'] = 0 if row['drm'] == 1 else 1
    if kind == 'channel':
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': []}
    reports = servustv_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('published') or (r.get('year') or 0) * 31557600), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': counts}


def channels(root):
    """Live channels of the latest run (ServusTV, Red Bull TV, Wetterpanorama …); the ServusTV stream as a
    fallback once a catalogue run was attempted, even if it failed."""
    db = _connect(root)
    try:
        tried = float(_get(db, 'last_attempt', '0') or 0)
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT id,title,number,genre,category,summary,poster,web_url,drm FROM servustv_items "
            "WHERE kind='channel' AND seen>=? ORDER BY number,title", (last,))] if last else []
    finally:
        db.close()
    if rows or not tried:
        return rows
    return [{k: r[k] for k in ('id', 'title', 'number', 'genre', 'category', 'summary', 'poster', 'web_url', 'drm')}
            for r in live_rows()]


def item(root, item_id):
    import servustv_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger ServusTV-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id) or (next((r for r in live_rows() if r['id'] == item_id), None) if item_id.startswith('c.') else None)
        if not row:
            raise ValueError('ServusTV-Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    row['playable'] = 0 if row['drm'] == 1 or row['kind'] == 'series' else 1
    report = servustv_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or ''},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protected = db.execute("SELECT COUNT(*) FROM servustv_items WHERE drm=1 AND kind IN ('movie','episode') AND seen>=?",
                               (last,)).fetchone()[0]
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0), 'last_success': last,
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'channels': _int(_get(db, 'channels', '0')) or 0, 'protected': protected,
            'requests': _int(_get(db, 'requests', '0')) or 0}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='servustv_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:servustv'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

# ---------------------------------------------------------------- playback

def player_info(ident, opener=None):
    """Answer of the Red Bull player interface for one video or live channel."""
    if not RB_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültiges ServusTV-Video')
    return _json(opener or _open, PLAYER + '?' + urllib.parse.urlencode(
        {'videoId': ident, 'deviceGroup': 'group_5', 'locale': 'de', 'tenant': 'stv'}))


def _mark_drm(root, item_id, value):
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE servustv_items SET drm=? WHERE id=?', (int(value), item_id))
    finally:
        db.close()


def playability(answer):
    """Plain-language reason why the player interface gives no stream."""
    errors = answer.get('playabilityErrors') if isinstance(answer, dict) else None
    errors = [str(e) for e in errors] if isinstance(errors, list) else []
    details = answer.get('playabilityErrorDetails') if isinstance(answer.get('playabilityErrorDetails'), dict) else {}
    if 'FSK_BLOCKED' in errors:
        d = details.get('FSK_BLOCKED') if isinstance(details.get('FSK_BLOCKED'), dict) else {}
        start, end, age = _int(d.get('minEveningHour'), 0, 23), _int(d.get('maxMorningHour'), 0, 23), _int(d.get('minAge'), 0, 21)
        window = ' von %02d:00 bis %02d:00 Uhr' % (start, end) if start is not None and end is not None else ''
        return ('Jugendschutz: ServusTV zeigt dieses Video nur%s%s.' % (window, ' (ab %d Jahren)' % age if age else '')).replace('nur.', 'zu bestimmten Uhrzeiten.')
    if 'NOT_YET_AVAILABLE' in errors:
        d = details.get('NOT_YET_AVAILABLE') if isinstance(details.get('NOT_YET_AVAILABLE'), dict) else {}
        when = _text(d.get('availableFrom') or answer.get('currentSunrise'), 40)
        return 'Dieses Video ist bei ServusTV noch nicht freigegeben' + (' (ab %s).' % when if when else '.')
    if any('GEO' in e.upper() for e in errors):
        return 'ServusTV zeigt dieses Video in deinem Land nicht (Geosperre).'
    if any('EXPIRED' in e.upper() or 'SUNSET' in e.upper() for e in errors):
        return 'Dieses Video ist bei ServusTV nicht mehr verfügbar.'
    if errors:
        return 'ServusTV gibt dieses Video nicht frei (%s).' % ', '.join(_text(e, 40) for e in errors[:3])
    return 'ServusTV nennt für dieses Video keinen Stream.'


def _stream_url(value):
    parts = urllib.parse.urlsplit(str(value or ''))
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.port not in (None, 443):
        return ''
    return str(value)


def _player_title(row, parent):
    title = row['title']
    if row['kind'] == 'episode':
        series = (parent or {}).get('title') or 'ServusTV'
        if row['season'] is not None and row['episode'] is not None:
            return '%s · S%02dE%02d · %s' % (series, row['season'], row['episode'], title)
        return '%s · %s' % (series, title)
    if row['kind'] == 'channel':
        return title
    return title + (' (%s)' % row['year'] if row.get('year') else '')


def play_source(root, item_id, opener=None, check=None, now=None):
    """Source for streaming.plan: HLS checked by hls_guard, played with hls.js or ffmpeg."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger ServusTV-Titel')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row and item_id.startswith('c.'):
        row = next((r for r in live_rows() if r['id'] == item_id), None)
    if not row:
        raise ValueError('ServusTV-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Sendung auswählen')
    if row['drm'] == 1:
        raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
    live = row['kind'] == 'channel'
    cached = _SOURCES.get(item_id)
    if cached and cached[0] > now:
        url, duration = cached[1]
    else:
        try:
            answer = player_info(row['path'], opener)
        except urllib.error.HTTPError as exc:
            raise ValueError(_error(exc)) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(_error(exc)) from None
        url = _stream_url(answer.get('videoUrl'))
        if not url or answer.get('playabilityErrors'):
            raise ValueError(playability(answer))
        try:
            (check or hls_guard.check)(url)
        except hls_guard.DrmProtected:
            _mark_drm(root, item_id, 1)
            raise
        if row['drm'] != 0 and not live:
            _mark_drm(root, item_id, 0)
        duration = 0 if live else (_int(answer.get('duration'), 1, 24 * 3600) or row['duration'] or 0)
        _SOURCES[item_id] = (now + SOURCE_TTL, (url, duration))
    return {'kind': 'url', 'url': url, 'hls': True, 'title': _player_title(row, parent), 'provider': KEY,
            'quality': 'ServusTV live (kostenlos)' if live else 'ServusTV (kostenlos)',
            'duration': duration or 0, 'live': live}
