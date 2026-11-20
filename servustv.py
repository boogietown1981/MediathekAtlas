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

0.6.47: the same engine serves Red Bull TV (``redbulltv.py``): Red Bull TV runs on the same Red Bull Media
House platform (tv-api.redbull.com, api-player.redbull.com) under its own tenant. Everything that differs
between the two (names, site, scope, seeds, player tenant, database, live fallback) is a ``Tenant``; the
module-level functions below keep their signatures and use the ServusTV tenant unless ``t`` is given.

Clips and trailers are left out (Björn: no "Sonstiges"); films, episodes and live channels are kept.
0.6.54 (Björn 20.11.2026: "ja bitte einbauen"): films and episodes can be kept offline for 30 days for personal
viewing, like Pluto TV, Netzkino and Plex (servustv_downloads.py; until 0.6.53: no offline copies, because
ServusTV offers downloads only inside its own app). Only titles the player interface releases right now as plain
HLS without a key; youth protection hours, geo blocks and live channels are never stored. If the player names an
end of availability (``availability_end``), the copy is removed then at the latest. Titles and URLs never go to
logs or the diagnosis export.
"""
from __future__ import annotations

import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import portal_reference
import provider_base

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
REQUEST_GAP = 0.5           # 0.5.106: 0.25 s drew HTTP 403 from the Red Bull edge (Björn, 13.11.2026)
RETRY_WAITS = (4, 15)       # seconds before the 2nd and 3rd try after 403/429/503
SOURCE_TTL = 120
MIN_FILM = 20 * 60           # seconds; shorter videos without a show are clips
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
# 0.6.48 (Björn's Mac, live network, 20.11.2026): Red Bull TV names its content with resource names
# ("rrn:content:films:<uuid>", "rrn:content:shows:<uuid>", "rrn:content:event-profiles:<uuid>"), cards may carry
# a "page:" prefix, collections are "<uuid>", "playlists::<uuid>" or "rrn:content:collections:<uuid>".
# 0.6.47 accepted only the ServusTV forms, so every Red Bull TV card was dropped ("lieferte keine Videos").
_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
RRN = r'rrn:content:[a-z][a-z\-]{1,40}:' + _UUID + r'(?::[A-Za-z]{2}(?:-[A-Za-z]{2,3})?)?'
RRN_ID = re.compile(RRN)
RB_ID = re.compile(r'(?:AA-?|AP-?|PN)[A-Z0-9]{8,30}|[a-z][a-z0-9\-]{2,40}|' + RRN)
COLLECTION_ID = re.compile(_UUID + r'|playlists::' + _UUID + r'|rrn:content:collections:' + _UUID + r'|[a-z][a-z0-9\-]{2,40}')
# 0.6.47: Red Bull TV ids also start with AP- (yt-dlp redbulltv tests: AP-1Q6XCDTAN1W11); 0.6.48: rrn ids
VALID_ID = re.compile(r'(?:[vc]\.(?:AA-?|AP-?|PN)[A-Z0-9]{8,30}|s\.(?:(?:AA|AP)-?[A-Z0-9]{8,30}|n-[a-z0-9\-]{1,80})|[vcs]\.' + RRN + ')')
SKIP_TYPES = {'clip', 'trailer', 'stop', 'live_program', 'person', 'promo', 'external'}
# 0.6.16: sport and event pages (MotoGP, Superbike, DTM …) carry full replays and documentaries.
PAGE_TYPES = {'subchannel', 'page', 'system', 'topic', 'channel', 'event'}
# 0.6.16 (Björn, 16.11.2026: "ServusTV hat weiterhin nur sehr wenige Treffer"): ServusTV marks many
# full-length videos as ``clip`` (whole debates, vodcasts, docu series, race replays; in the HAR of
# 13.11.2026 185 of 787 clips ran 20 minutes or longer, spread over 23 formats). Clips of at least
# MIN_FILM count as episodes of their format; shorter clips stay out (no "Sonstiges").
NAV_PAGE = re.compile(r'https://www\.servustv\.com/[a-z]{2}/page/((?:AA-?|AP-?|PN)[A-Z0-9]{8,30})(?:[/?#].*)?')
# 0.6.16: a single page that keeps answering 403/404/410/451 after the retries is left out (in the
# diagnosis of 16.11.2026 always the same 10 of 2,361 requests, never recovered: not a rate limit).
# Only when more than this share of the requests is refused does the run count as partial.
REFUSED_SHARE = 0.03
SKIPPABLE = (403, 404, 410, 451)
# 0.6.45: in every run of 16.–20.11.2026 the very same 15 pages answered 403 ("refused": 15, "recovered": 0),
# each after three tries with 4 s and 15 s pauses (~5 minutes per run and 45 refused requests at the Red Bull
# edge). A page refused after all tries is remembered (address only) and skipped without a request for
# REFUSED_RECHECK; after that it is tried once more, without the pauses. Pages that answer again are forgotten.
REFUSED_RECHECK = 7 * 86400
# 0.6.50 (Björn's Mac, 20.11.2026): those 15 pages are all /collections/v5.3/stv/de/de/<uuid> and answer 403 with
# the body {"err":"geo blocked"}; the same ids under /stv/de/at/ answer 200. They are lists for Austria only.
# A 403 with that body is final at once: no retries, not counted as refused, not a partial run; the page is
# remembered as "nur in Österreich" and asked again only after GEO_RECHECK (one try). Nothing is taken from the
# Austrian scope.
GEO_RECHECK = 30 * 86400
GEO_MARK = re.compile(rb'geo[ _-]?block', re.I)
MAX_REFUSED_KEPT = 500
# ServusTV live channels if the catalogue cannot be read (ids from the HAR of 13.11.2026).
LIVE_FALLBACK = (('c.PN0B1EC15B2FE10', 'ServusTV', 1),)



@dataclass(frozen=True)
class Tenant:
    """What differs between the services of the Red Bull Media House platform (0.6.47)."""
    key: str                       # provider key (routes, diagnosis events, play parameter)
    name: str                      # shown name, also in messages
    site: str                      # web site for links and Referer
    scopes: tuple                  # catalogue scopes, tried in this order until one answers
    seeds: tuple                   # pages the crawl starts at
    player_tenants: tuple          # tenant parameter of the player interface, tried in this order
    table: str                     # table prefix in the own database file
    dbfile: str
    live_fallback: tuple = ()      # (id, title, number) of channels shown when the catalogue lists none
    live_summary: str = ''
    web_pattern: str = ''          # share_url accepted as link (full match)
    web_item: str = ''             # link for an id: '%(site)s/…/%(id)s'
    web_home: str = ''
    web_shows: str = ''
    locale: str = 'de'
    assumed_scope: bool = False    # True: the scopes are not confirmed by a recording (diagnosis says so)


STV = Tenant(
    key=KEY, name=NAME, site=SITE, scopes=(SCOPE,), seeds=SEEDS, player_tenants=('stv',), table='servustv',
    dbfile='servustv.sqlite3', live_fallback=LIVE_FALLBACK, live_summary='Das laufende Programm von ServusTV.',
    web_pattern=r'https://www\.servustv\.com/[a-z]{2}/(?:page|video)/[A-Za-z0-9:\-]{4,60}(?:/[a-z0-9\-]{1,160})?',
    web_item='%(site)s/de/page/%(id)s', web_home=SITE + '/de', web_shows=SITE + '/de/sendungen')

_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_RUNNING = {}                      # tenant key -> catalogue run active (ServusTV keeps _ACTIVE as well)


def _active(t):
    return _ACTIVE if t.key == KEY else bool(_RUNNING.get(t.key))


def _sql(t, text):
    return text.replace('servustv_', t.table + '_') if t.table != 'servustv' else text

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


def _connect(root, t=STV):
    db = provider_base.connect(root, t.dbfile)   # 0.6.0: WAL, busy timeout (provider_base)
    db.executescript(_sql(t, SCHEMA))
    # sqlite3 connections take neither attributes nor weak references: remember the tenant by object id.
    # Every connection handed to _get/_set/_store comes from here, so a reused id is always overwritten.
    _DB_TENANT[id(db)] = t
    return db


_DB_TENANT = {}


def _tenant_of(db):
    return _DB_TENANT.get(id(db)) or STV


def _get(db, key, default=''):
    row = db.execute(_sql(_tenant_of(db), 'SELECT value FROM servustv_state WHERE name=?'), (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute(_sql(_tenant_of(db), 'INSERT OR REPLACE INTO servustv_state(name,value) VALUES(?,?)'), (key, str(value)))


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

def _headers(t=STV):
    return {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',
            'Origin': t.site, 'Referer': t.site + '/'}


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige Anfrage an die Red-Bull-Plattform')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('Antwort der Red-Bull-Plattform zu groß')
        raw = provider_base.read_capped(response, limit)
    if len(raw) > limit:
        raise ValueError('Antwort der Red-Bull-Plattform zu groß')
    return raw


def _json(opener, url, t=STV):
    answer = json.loads(opener(url, _headers(t)).decode('utf-8'))
    if not isinstance(answer, dict):
        raise ValueError('Unerwartete %s-Antwort' % t.name)
    return answer


def product(opener, ident, t=STV, scope=None):
    if not RB_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültige %s-Seite' % t.name)
    return _json(opener, TV_API + '/products/v5.3' + (scope or t.scopes[0]) + ident, t)


def collection(opener, ident, offset=0, t=STV, scope=None):
    if not COLLECTION_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültige %s-Liste' % t.name)
    return _json(opener, TV_API + '/collections/v5.3' + (scope or t.scopes[0]) + ident + '?'
                 + urllib.parse.urlencode({'offset': int(offset)}), t)


def _error(exc, t=STV):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return '%s verweigert den Zugriff (HTTP %d)' % (t.name, code)
    if code == 451:
        return '%s bietet seine Videos in diesem Land nicht an (HTTP 451)' % t.name
    if code:
        return '%s antwortet mit HTTP %d' % (t.name, code)
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('%s ist nicht erreichbar' % t.name, exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return '%s-Katalog konnte nicht geladen werden' % t.name


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


def _web(card, t=STV):
    url = str(card.get('share_url') or '')
    if t.web_pattern and re.fullmatch(t.web_pattern, url):
        return url.replace('/page/page:', '/page/')
    ident = str(card.get('id') or '')
    return t.web_item % {'site': t.site, 'id': ident} if RB_ID.fullmatch(ident) else t.web_home


def _summary_of(card):
    for key in ('long_description', 'short_description', 'description'):
        text = _text(card.get(key), 1600)
        if text:
            return text
    return ''


def _base(card, kind, t=STV):
    return {'kind': kind, 'title': _text(card.get('title'), 200), 'path': str(card.get('id')), 'series_id': '',
            'season': None, 'episode': None, 'year': None, 'duration': _ms(card.get('duration')),
            'rating': '', 'genre': ', '.join(_genres(card)), 'summary': _summary_of(card), 'poster': image(card),
            'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': (_genres(card) or [''])[0], 'published': None,
            'playable': 1 if card.get('playable') is not False else 0, 'drm': -1, 'web_url': _web(card, t)}


def _page_key(url):
    """Address of a request without host (stable across runs)."""
    parts = urllib.parse.urlsplit(str(url))
    return (parts.path + ('?' + parts.query if parts.query else ''))[:300]


class GeoBlocked(urllib.error.HTTPError):
    """0.6.50: a page the platform offers only in Austria (403 with body "geo blocked")."""


def _geo_blocked(exc):
    """True for a 403 whose body says "geo blocked" (reads at most 4 KB of the error body)."""
    if isinstance(exc, GeoBlocked):
        return True
    if getattr(exc, 'code', None) != 403:
        return False
    try:
        body = exc.read(4096) if getattr(exc, 'fp', None) is not None else b''
    except (OSError, ValueError, AttributeError):
        return False
    return bool(GEO_MARK.search(body or b''))


def _known_geo(db):
    try:
        data = json.loads(_get(db, 'geo_pages', '{}') or '{}')
    except ValueError:
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float)) and v > 0} \
        if isinstance(data, dict) else {}


def _known_refused(db):
    try:
        data = json.loads(_get(db, 'refused_pages', '{}') or '{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class Crawl:
    """Breadth-first walk over pages, shows and rails, with fixed request limits."""

    def __init__(self, opener, gap, waits=(), known_refused=None, now=None, t=STV, scope=None, known_geo=None):
        self.gap, self.waits = gap, tuple(waits)
        self.t, self.scope = t, scope or t.scopes[0]
        self.refused = self.recovered = self.known_skipped = 0
        self.now = time.time() if now is None else float(now)
        # 0.6.45: address -> time of the last refusal (see REFUSED_RECHECK)
        self.known_refused = {str(k): float(v) for k, v in (known_refused or {}).items()
                              if isinstance(v, (int, float)) and v > 0}
        self.refused_pages = {}
        self.known_geo = dict(known_geo or {})
        self.geo_pages = {}                   # 0.6.50: address -> time it was found geo blocked
        raw = opener

        def patient(url, headers, *args, **kwargs):
            """0.5.106: the edge answers bursts with 403 – wait and try again before giving up."""
            key = _page_key(url)
            seen_geo = self.known_geo.get(key)
            if seen_geo and self.now - seen_geo < GEO_RECHECK:
                self.geo_pages[key] = seen_geo
                raise GeoBlocked(url, 403, 'nur in Oesterreich', None, None)
            last = self.known_refused.get(key)
            if last and self.now - last < REFUSED_RECHECK:
                self.known_skipped += 1
                self.refused_pages[key] = last
                raise urllib.error.HTTPError(url, 403, 'zuletzt verweigert, wird spaeter erneut geprueft', None, None)
            waits = () if last else self.waits      # due for a re-check: one try, no pauses
            for attempt in range(len(waits) + 1):
                try:
                    answer = raw(url, headers, *args, **kwargs)
                    if attempt:
                        self.recovered += 1
                    return answer
                except urllib.error.HTTPError as exc:
                    if _geo_blocked(exc):
                        self.geo_pages[key] = self.now
                        self.known_refused.pop(key, None)
                        raise GeoBlocked(url, 403, 'nur in Oesterreich', None, None) from None
                    if exc.code not in (403, 429, 503) or attempt == len(waits):
                        if exc.code in (403, 429, 503):
                            self.refused += 1
                        if exc.code == 403:
                            self.refused_pages[key] = self.now
                        raise
                    time.sleep(waits[attempt])
        self.opener = patient
        self.items, self.shows, self.show_names = {}, {}, {}
        self.pending_products, self.done_products = [], set()
        self.pending_collections, self.done_collections = [], set()
        self.requests, self.errors, self.truncated = 0, [], False
        self.unavailable = {}                 # HTTP status -> pages left out (0.6.16)
        self.long_clips = self.events = 0

    def _failed(self, exc, seed=False):
        """0.6.16: a single refused or vanished page is skipped; everything else is an error."""
        code = getattr(exc, 'code', None)
        if isinstance(exc, GeoBlocked):
            return                            # 0.6.50: counted in geo_pages, not as refused
        if isinstance(exc, urllib.error.HTTPError) and code in SKIPPABLE and not seed:
            self.unavailable[code] = self.unavailable.get(code, 0) + 1
            return
        if isinstance(exc, urllib.error.HTTPError) and code == 404 and seed:
            return
        self.errors.append(_error(exc, self.t))

    def refused_too_often(self):
        refused = sum(n for code, n in self.unavailable.items() if code != 404)
        return refused > max(3, REFUSED_SHARE * max(self.requests, 1))

    def _pause(self):
        self.requests += 1
        if self.requests % 200 == 0:
            # 0.5.104: progress in the diagnosis (counts only, no titles or addresses)
            _notify(self.t.key + '_sync_progress', requests=self.requests, items=len(self.items),
                    shows=len(self.shows), errors=len(self.errors), refused=self.refused, recovered=self.recovered)
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
        if ident.startswith('page:') and RRN_ID.fullmatch(ident[5:]):
            ident = ident[5:]                            # 0.6.48: Red Bull TV tile of a film page
            card = {**card, 'id': ident}                 # the player and the stored path need the bare name
        if ctype == 'any':
            # 0.6.16: teaser tiles ("Alle Folgen: Jetzt streamen!") that point to a ServusTV page
            match = NAV_PAGE.fullmatch(str(card.get('nav_url') or ''))
            if match:
                self.want_product(match.group(1))
            return
        if not RB_ID.fullmatch(ident) or (ident.islower() and not RRN_ID.fullmatch(ident)):
            return
        if ctype in ('event_profile', 'event-profile', 'event_profiles'):
            ctype = 'event'                              # 0.6.48: Red Bull TV event pages (replays, upcoming events)
        if not ctype and RRN_ID.fullmatch(ident):
            # 0.6.48: the content type is part of a Red Bull TV resource name
            ctype = {'films': 'film', 'shows': 'show', 'episodes': 'episode', 'videos': 'video',
                     'event-profiles': 'event', 'live-videos': 'video_channel'}.get(ident.split(':')[2], '')
        if ctype in PAGE_TYPES:
            if ctype == 'event' and ident not in self.done_products and ident not in self.pending_products:
                self.events += 1
            self.want_product(ident)
            return
        if ctype == 'show':
            if ident not in self.shows:
                self.shows[ident] = {**_base(card, 'series', self.t), 'id': 's.' + ident, 'duration': None}
                self.show_names.setdefault(_text(card.get('title'), 200).casefold(), ident)
            self.want_product(ident)
            return
        if ctype == 'video_channel':
            self.items.setdefault('c.' + ident, {**_base(card, 'channel', self.t), 'id': 'c.' + ident, 'genre': 'Live',
                                                 'category': 'Live', 'duration': None})
            return
        long_clip = ctype == 'clip' and (_ms(card.get('duration')) or 0) >= MIN_FILM
        if (ctype in SKIP_TYPES and not long_clip) \
                or card.get('type') not in ((None, 'video', 'page') if ctype == 'film' else (None, 'video')):
            return
        row = _base(card, 'movie', self.t)
        if not row['title']:
            return
        show_name = _text(card.get('show_name') or (card.get('subheading') if ctype in ('episode', 'clip') else ''), 200)
        if long_clip:
            if 'v.' + ident not in self.items:
                self.long_clips += 1
            if show_name.casefold() == row['title'].casefold():
                show_name = ''                          # a stand-alone documentary, not a format
        if ctype == 'episode' or show is not None or (long_clip and show_name):
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
            answer = collection(self.opener, ident, offset, self.t, self.scope)
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
        answer = product(self.opener, ident, self.t, self.scope)
        self._pause()
        show = ident if str(answer.get('content_type') or '') == 'show' else None
        if show and ident not in self.shows and _text(answer.get('title'), 200):
            # 0.6.16: a show reached through a teaser tile has no card of its own: use the product
            self.card({**answer, 'id': ident, 'content_type': 'show'})
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
                        self._failed(exc)
            else:
                self.want_collection(cid)

    def run(self):
        for seed in self.t.seeds:
            self.want_product(seed)
        while (self.pending_products or self.pending_collections) and len(self.items) < MAX_ITEMS:
            if self.pending_collections and len(self.done_collections) < MAX_COLLECTIONS:
                cid = self.pending_collections.pop(0)
                self.done_collections.add(cid)
                try:
                    self.run_collection(cid)
                except Exception as exc:
                    self._failed(exc)
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
            except Exception as exc:
                self._failed(exc, seed=pid in self.t.seeds)
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
                sid = 's.n-' + (slug(name) or self.t.key)
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
                            'published': None, 'playable': 1, 'drm': -1, 'web_url': self.t.web_shows})
        return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'published',
          'playable', 'drm', 'web_url')
_KEEP = ('drm',)


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS if f not in _KEEP)
    for item in items:
        db.execute(_sql(_tenant_of(db), '''INSERT INTO servustv_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update)),
                   (item['id'], *[item.get(f) for f in FIELDS], now, now))


def live_rows(t=STV):
    return [{'id': cid, 'kind': 'channel', 'title': title, 'path': cid[2:], 'series_id': '', 'season': None,
             'episode': None, 'year': None, 'duration': None, 'rating': '', 'genre': 'Live',
             'summary': t.live_summary, 'poster': '', 'imdb_id': '', 'imdb_score': None,
             'imdb_votes': None, 'number': number, 'category': 'Live', 'published': None, 'playable': 1, 'drm': -1,
             'web_url': t.site + '/de/video/' + cid[2:]} for cid, title, number in t.live_fallback]


def find_scope(t, opener, stored=''):
    """0.6.47: catalogue scope of a tenant whose scope is not confirmed by a recording (Red Bull TV).

    The stored scope of the last successful run is tried first, then the candidates in order; the first
    one whose start page answers wins. Returns (scope, first page answer or None, error of the last try)."""
    candidates = [stored] if stored in t.scopes else []
    candidates += [x for x in t.scopes if x not in candidates]
    last = None
    for scope in candidates:
        try:
            return scope, product(opener, t.seeds[0], t, scope), None
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (400, 403, 404, 410):
                break                          # throttling or server trouble: not a question of the scope
        except (ValueError, OSError) as exc:
            last = exc
            break
    return '', None, last


def sync(root, opener=None, now=None, gap=None, waits=None, t=STV):
    """Read the library of a tenant. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root, t)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
            # 0.5.104: errors of the WordPress/sitemap reader of 0.5.101 no longer apply (Björn's diagnosis).
            if re.match(r'(WordPress|Sitemap)', _get(db, 'last_error')):
                _set(db, 'last_error', '')
    finally:
        db.close()
    _notify(t.key + '_sync_started')
    try:
        db = _connect(root, t)
        try:
            known = _known_refused(db)
            known_geo = _known_geo(db)
            stored_scope = _get(db, 'scope')
        finally:
            db.close()
        scope = t.scopes[0]
        if len(t.scopes) > 1:
            scope, _, problem = find_scope(t, opener or _open, stored_scope)
            if not scope:
                _notify(t.key + '_scope_missing', tried=len(t.scopes), http_status=getattr(problem, 'code', 0) or 0)
                raise problem if problem is not None else ValueError('%s lieferte keine Startseite' % t.name)
        crawl = Crawl(opener or _open, gap, RETRY_WAITS if opener is None else (waits or ()), known_refused=known,
                      now=now, t=t, scope=scope, known_geo=known_geo)
        crawl.run()
        rows = crawl.rows()
        if not any(r['kind'] in ('movie', 'episode') for r in rows):
            raise ValueError(crawl.errors[0] if crawl.errors else '%s lieferte keine Videos' % t.name)
        channels = [r for r in rows if r['kind'] == 'channel']
        first = t.live_fallback[0][0] if t.live_fallback else ''
        for number, row in enumerate(sorted(channels, key=lambda r: (r['id'] != first, r['title'])), 1):
            row['number'] = number
        if not channels:
            rows += live_rows(t)
        refused = sum(n for code, n in crawl.unavailable.items() if code != 404)
        too_many = crawl.refused_too_often()
        partial = crawl.truncated or bool(crawl.errors) or too_many
        if crawl.errors:
            message = 'Katalog nur teilweise geladen: %s (%d von %d Abrufen)' % (crawl.errors[0], len(crawl.errors), crawl.requests)
        elif too_many:
            message = ('Katalog nur teilweise geladen: %s verweigert den Zugriff (HTTP 403) (%d von %d Abrufen)'
                       % (t.name, refused, crawl.requests))
        elif partial:
            message = 'Katalog nur teilweise geladen'
        else:
            message = ''
        skipped = sum(crawl.unavailable.values())
        note = ('%d %s-Seite%s nicht freigegeben und übersprungen' % (skipped, t.name, '' if skipped == 1 else 'n')
                if skipped and not partial else '')
        geo = len(crawl.geo_pages)
        if geo:
            geo_note = '%d Liste%s nur in Österreich verfügbar (Geosperre)' % (geo, '' if geo == 1 else 'n')
            note = note + ' · ' + geo_note if note else geo_note
        counts = {'movies': sum(1 for r in rows if r['kind'] == 'movie'),
                  'series': sum(1 for r in rows if r['kind'] == 'series'),
                  'episodes': sum(1 for r in rows if r['kind'] == 'episode'),
                  'channels': sum(1 for r in rows if r['kind'] == 'channel')}
        db = _connect(root, t)
        try:
            with db:
                _store(db, rows, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', message), ('note', note), ('unavailable', skipped),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600),
                                   ('requests', crawl.requests), ('scope', scope), *counts.items()]:
                    _set(db, key, value)
                kept = dict(sorted(((k, v) for k, v in crawl.refused_pages.items() if k not in crawl.geo_pages),
                                   key=lambda kv: -kv[1])[:MAX_REFUSED_KEPT])
                _set(db, 'refused_pages', json.dumps(kept, separators=(',', ':')))
                geo_kept = dict(sorted(crawl.geo_pages.items(), key=lambda kv: -kv[1])[:MAX_REFUSED_KEPT])
                _set(db, 'geo_pages', json.dumps(geo_kept, separators=(',', ':')))
                _set(db, 'geo_blocked', geo)
        finally:
            db.close()
        _notify(t.key + '_sync_completed', partial=partial, requests=crawl.requests, refused=crawl.refused,
                recovered=crawl.recovered, errors=len(crawl.errors), truncated=crawl.truncated,
                known_skipped=crawl.known_skipped, remembered=len(crawl.refused_pages), geo_blocked=len(crawl.geo_pages),
                # 0.6.45: the error texts (no addresses), so a partial run can be explained
                error_texts=sorted(set(crawl.errors))[:3],
                unavailable={str(k): v for k, v in sorted(crawl.unavailable.items())},
                long_clips=crawl.long_clips, events=crawl.events, shows=len(crawl.shows), **counts)
        return {'ok': True, 'partial': partial, **counts}
    except Exception as exc:
        message = _error(exc, t)
        db = _connect(root, t)
        try:
            with db:
                for key, value in [('last_result', 'failed'), ('last_error', message),
                                   ('last_http_status', getattr(exc, 'code', 0) or 0), ('next_attempt', now + 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        import netcheck
        _notify(t.key + '_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute(_sql(_tenant_of(db), 'SELECT * FROM servustv_items WHERE id=?'), (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _enrichment(t):
    import importlib
    return importlib.import_module(t.key + '_enrichment')


def _summary(root, row, reports=None, t=STV):
    report = (reports if reports is not None else _enrichment(t).all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))


def episodes(root, series_id, now=None, t=STV):
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige %s-Sendung' % t.name)
    db = _connect(root, t)
    try:
        series = _row(db, series_id)
        if not series or series['kind'] != 'series':
            raise ValueError('%s-Sendung nicht im Katalog; bitte Katalog neu laden' % t.name)
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(_sql(t,
            "SELECT * FROM servustv_items WHERE kind='episode' AND series_id=? AND seen>=? "
            "ORDER BY season IS NULL, season, episode IS NULL, episode, published DESC, title"), (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series, t=t)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = 0 if row['drm'] == 1 else 1
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': ''}


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection='', t=STV):
    """One page of films, formats (series) or the live channels, with canonical categories."""
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root, t)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = _sql(t, 'FROM servustv_items WHERE kind=? AND seen>=?')
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR summary LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
        if kind == 'series':
            counts = dict(db.execute(_sql(t, "SELECT series_id,COUNT(*) FROM servustv_items WHERE kind='episode' AND seen>=? "
                                     "GROUP BY series_id"), (last,)).fetchall())
            for row in rows:
                row['episodes'] = counts.get(row['id'], 0)
    finally:
        db.close()
    for row in rows:
        row['playable'] = 0 if row['drm'] == 1 else 1
    if kind == 'channel':
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': []}
    reports = _enrichment(t).all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports, t))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('published') or (r.get('year') or 0) * 31557600), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': counts}


def channels(root, t=STV):
    """Live channels of the latest run (ServusTV, Red Bull TV, Wetterpanorama …); the tenant's own stream as a
    fallback once a catalogue run was attempted, even if it failed."""
    db = _connect(root, t)
    try:
        tried = float(_get(db, 'last_attempt', '0') or 0)
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(_sql(t,
            "SELECT id,title,number,genre,category,summary,poster,web_url,drm FROM servustv_items "
            "WHERE kind='channel' AND seen>=? ORDER BY number,title"), (last,))] if last else []
    finally:
        db.close()
    if rows or not tried:
        return rows
    return [{k: r[k] for k in ('id', 'title', 'number', 'genre', 'category', 'summary', 'poster', 'web_url', 'drm')}
            for r in live_rows(t)]


def item(root, item_id, t=STV):
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger %s-Titel' % t.name)
    db = _connect(root, t)
    try:
        row = _row(db, item_id) or (next((r for r in live_rows(t) if r['id'] == item_id), None) if item_id.startswith('c.') else None)
        if not row:
            raise ValueError('%s-Titel nicht im Katalog; bitte Katalog neu laden' % t.name)
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    row['playable'] = 0 if row['drm'] == 1 or row['kind'] == 'series' else 1
    report = _enrichment(t).cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report}, t)
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or ''},
            'series': parent, 'reference': report}


def state(root, t=STV):
    db = _connect(root, t)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protected = db.execute(_sql(t, "SELECT COUNT(*) FROM servustv_items WHERE drm=1 AND kind IN ('movie','episode') AND seen>=?"),
                               (last,)).fetchone()[0]
        return {
            'running': _active(t), 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0), 'last_success': last,
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _active(t)),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'channels': _int(_get(db, 'channels', '0')) or 0, 'protected': protected,
            'requests': _int(_get(db, 'requests', '0')) or 0,
            'unavailable': _int(_get(db, 'unavailable', '0')) or 0, 'note': _get(db, 'note'),
            'geo_blocked': _int(_get(db, 'geo_blocked', '0')) or 0,
            'scope_assumed': t.assumed_scope}
    finally:
        db.close()


def set_auto(root, enabled, t=STV):
    if type(enabled) is not bool:
        raise ValueError('Automatik muss ausdrücklich ein- oder ausgeschaltet werden')
    db = _connect(root, t)
    try:
        with db:
            _set(db, 'auto', int(enabled))
    finally:
        db.close()
    return state(root, t)


def _mark_running(t, value):
    global _ACTIVE
    if t.key == KEY:
        _ACTIVE = value
    else:
        _RUNNING[t.key] = value


def _run(root, t=STV):
    try:
        sync(root, t=t)
    finally:
        with _SYNC_LOCK:
            _mark_running(t, False)


def start_sync(root, t=STV):
    with _SYNC_LOCK:
        if _active(t):
            return False
        _mark_running(t, True)
    threading.Thread(target=_run, args=(root, t), daemon=True, name=t.key + '_catalog_sync').start()
    return True


def should_sync(root, now=None):
    """Whether the catalogue run should start now (0.6.0: the shared rule in provider_base)."""
    return provider_base.catalog_due(root, sys.modules[__name__], state(root), now)


def loop(root, stop):
    """Former own loop thread; the server uses the shared planner (planner.py) instead."""
    provider_base.loop(root, stop, 'servustv', sys.modules[__name__])



# ---------------------------------------------------------------- playback

# ---------------------------------------------------------------- playback

def player_info(ident, opener=None, t=STV, tenant=None):
    """Answer of the Red Bull player interface for one video or live channel."""
    if not RB_ID.fullmatch(str(ident or '')):
        raise ValueError('Ungültiges %s-Video' % t.name)
    return _json(opener or _open, PLAYER + '?' + urllib.parse.urlencode(
        {'videoId': ident, 'deviceGroup': 'group_5', 'locale': t.locale, 'tenant': tenant or t.player_tenants[0]}), t)


def _player_answer(ident, opener, t):
    """0.6.47: the first player tenant that names a stream; otherwise the answer (or error) of the first one.
    Red Bull TV's own tenant is not confirmed by a recording, so the ServusTV tenant is the second try
    (both share one video store; the ServusTV player serves the Red Bull TV live channel)."""
    first = first_error = None
    for number, tenant in enumerate(t.player_tenants):
        try:
            answer = player_info(ident, opener, t, tenant)
        except urllib.error.HTTPError as exc:
            if first_error is None and first is None:
                first_error = exc
            if exc.code not in (400, 403, 404):
                break
            continue
        if _stream_url(answer.get('videoUrl')) and not answer.get('playabilityErrors'):
            if number:
                _notify(t.key + '_player_fallback', tenant_position=number)
            return answer
        if first is None:
            first = answer
    if first is not None:
        return first
    raise first_error if first_error is not None else ValueError('%s nennt für dieses Video keinen Stream.' % t.name)


def _mark_drm(root, item_id, value, t=STV):
    db = _connect(root, t)
    try:
        with db:
            db.execute(_sql(t, 'UPDATE servustv_items SET drm=? WHERE id=?'), (int(value), item_id))
    finally:
        db.close()


def playability(answer, t=STV):
    """Plain-language reason why the player interface gives no stream."""
    errors = answer.get('playabilityErrors') if isinstance(answer, dict) else None
    errors = [str(e) for e in errors] if isinstance(errors, list) else []
    details = answer.get('playabilityErrorDetails') if isinstance(answer.get('playabilityErrorDetails'), dict) else {}
    if 'FSK_BLOCKED' in errors:
        d = details.get('FSK_BLOCKED') if isinstance(details.get('FSK_BLOCKED'), dict) else {}
        start, end, age = _int(d.get('minEveningHour'), 0, 23), _int(d.get('maxMorningHour'), 0, 23), _int(d.get('minAge'), 0, 21)
        window = ' von %02d:00 bis %02d:00 Uhr' % (start, end) if start is not None and end is not None else ''
        return ('Jugendschutz: %s zeigt dieses Video nur%s%s.' % (t.name, window, ' (ab %d Jahren)' % age if age else '')).replace('nur.', 'zu bestimmten Uhrzeiten.')
    if 'NOT_YET_AVAILABLE' in errors:
        d = details.get('NOT_YET_AVAILABLE') if isinstance(details.get('NOT_YET_AVAILABLE'), dict) else {}
        when = _text(d.get('availableFrom') or answer.get('currentSunrise'), 40)
        return 'Dieses Video ist bei %s noch nicht freigegeben' % t.name + (' (ab %s).' % when if when else '.')
    if any('GEO' in e.upper() for e in errors):
        return '%s zeigt dieses Video in deinem Land nicht (Geosperre).' % t.name
    if any('EXPIRED' in e.upper() or 'SUNSET' in e.upper() for e in errors):
        return 'Dieses Video ist bei %s nicht mehr verfügbar.' % t.name
    if errors:
        return '%s gibt dieses Video nicht frei (%s).' % (t.name, ', '.join(_text(e, 40) for e in errors[:3]))
    return '%s nennt für dieses Video keinen Stream.' % t.name


def _stream_url(value):
    parts = urllib.parse.urlsplit(str(value or ''))
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.port not in (None, 443):
        return ''
    return str(value)


# 0.6.54: explicit end of availability in the player answer (names as on other Red Bull Media House players and
# the broadcaster interfaces). Nothing is guessed: an unknown or unreadable value means "no end known".
END_KEYS = ('availableUntil', 'availableTo', 'availabilityEnd', 'availabilityUntil', 'expirationDate', 'expiryDate',
            'currentSunset', 'sunset', 'sunsetDate', 'validUntil')


def _when(value):
    """Seconds since 1970 for an epoch (s or ms) or an ISO time with zone; None otherwise."""
    import datetime
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value) / (1000 if value > 1e11 else 1)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if re.fullmatch(r'\d{9,13}', text):
            return _when(int(text))
        try:
            dt = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return None   # unknown time zone: never invent a deadline
        number = dt.timestamp()
    else:
        return None
    return number if 946684800 <= number <= 4102444800 else None   # 2000 … 2100


def availability_end(answer):
    """End of availability named by the player interface (seconds), or None."""
    if not isinstance(answer, dict):
        return None
    for source in (answer, answer.get('availability'), answer.get('meta')):
        if not isinstance(source, dict):
            continue
        for key in END_KEYS:
            when = _when(source.get(key))
            if when:
                return when
    return None


def _player_title(row, parent, t=STV):
    title = row['title']
    if row['kind'] == 'episode':
        series = (parent or {}).get('title') or t.name
        if row['season'] is not None and row['episode'] is not None:
            return '%s · S%02dE%02d · %s' % (series, row['season'], row['episode'], title)
        return '%s · %s' % (series, title)
    if row['kind'] == 'channel':
        return title
    return title + (' (%s)' % row['year'] if row.get('year') else '')


def play_source(root, item_id, opener=None, check=None, now=None, t=STV):
    """Source for streaming.plan: HLS checked by hls_guard, played with hls.js or ffmpeg."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger %s-Titel' % t.name)
    now = time.time() if now is None else now
    db = _connect(root, t)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row and item_id.startswith('c.'):
        row = next((r for r in live_rows(t) if r['id'] == item_id), None)
    if not row:
        raise ValueError('%s-Titel nicht im Katalog; bitte Katalog neu laden' % t.name)
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Sendung auswählen')
    if row['drm'] == 1:
        raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
    live = row['kind'] == 'channel'
    cache_key = item_id if t.key == KEY else (t.key, item_id)
    cached = _SOURCES.get(cache_key)
    if cached and cached[0] > now:
        url, duration, until = (tuple(cached[1]) + (None,))[:3]
    else:
        try:
            answer = _player_answer(row['path'], opener, t)
        except urllib.error.HTTPError as exc:
            raise ValueError(_error(exc, t)) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(_error(exc, t)) from None
        url = _stream_url(answer.get('videoUrl'))
        if not url or answer.get('playabilityErrors'):
            raise ValueError(playability(answer, t))
        try:
            (check or hls_guard.check)(url)
        except hls_guard.DrmProtected:
            _mark_drm(root, item_id, 1, t)
            raise
        if row['drm'] != 0 and not live:
            _mark_drm(root, item_id, 0, t)
        duration = 0 if live else (_int(answer.get('duration'), 1, 24 * 3600) or row['duration'] or 0)
        until = None if live else availability_end(answer)
        _SOURCES[cache_key] = (now + SOURCE_TTL, (url, duration, until))
    return {'kind': 'url', 'url': url, 'hls': True, 'title': _player_title(row, parent, t), 'provider': t.key,
            'quality': '%s live (kostenlos)' % t.name if live else '%s (kostenlos)' % t.name,
            'duration': duration or 0, 'live': live, 'available_until': until}
