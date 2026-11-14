"""JustWatch TV: JustWatch's own free films and series (package ``jwt``), catalogue and playback (0.5.40).

Björn (12.11.2026): connect JustWatch TV "only for its own films and series", 30 days offline.
Only the free, ad-supported package ``jwt`` ("JustWatch TV Free") is read; Plus (``jut``, a
subscription), Store (``jst``, rentals) and offers of other streaming services are ignored.

* Catalogue: the public GraphQL API the website uses (apis.justwatch.com/graphql, no account,
  no cookies), ``popularTitles`` filtered to the package, paged by cursor, country DE.
  Formats as recorded in Björn's HAR (12.11.2026).
* Playback: JustWatch publishes, for part of its own titles, a stream for external players
  (``streamUrlExternalPlayer``, an HLS playlist on apis.justwatch.com). That address is signed
  and expires, so it is fetched fresh right before playing or downloading and never stored.
  Before use hls_guard refuses copy-protected (DRM) streams; nothing is circumvented.
  Titles without such a stream only get the official JustWatch page.

Endpoints are hard-coded and every answer is size-limited. Titles, tokens and URLs never go to
logs or the diagnosis export.
"""
from __future__ import annotations
import sys

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

API_URL = 'https://apis.justwatch.com/graphql'
SITE = 'https://www.justwatch.com'
IMAGES = 'https://images.justwatch.com'
PACKAGE = 'jwt'
COUNTRY, LANGUAGE = 'DE', 'de'
MAX_ANSWER = 16 * 1024 * 1024
MAX_ITEMS = 20000
PAGE = 40
MAX_PAGES = 200
REQUEST_GAP = 1.0
SERIES_TTL = 6 * 3600
SOURCE_TTL = 300
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
VALID_ID = re.compile(r't(?:m|s|se|ss|e)\d{1,12}')
VALID_PATH = re.compile(r'/de/(?:Film|Serie)/[A-Za-z0-9%_.~\-]{1,200}(?:/Staffel-\d{1,4})?')
STREAM_PATH = re.compile(r'/jwtv/manifest/external/[A-Za-z0-9_\-=]{8,3000}(?:\.[A-Za-z0-9_\-=]{1,200})?\.m3u8')
IGNORED_GENRES = {'eur', 'Produziert in Europa', 'Made in Europe'}

_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS justwatch_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  playable INTEGER NOT NULL DEFAULT 0, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL,
  night INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS justwatch_items_kind ON justwatch_items(kind, seen);
CREATE INDEX IF NOT EXISTS justwatch_items_series ON justwatch_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS justwatch_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''

# Only fields MediathekAtlas uses; same types and arguments as the website's GetPopularTitles.
CATALOG_QUERY = '''query MediathekAtlasJustWatchTv($country: Country!, $language: Language!, $first: Int!,
  $after: String, $filter: TitleFilter, $watchNowFilter: WatchNowOfferFilter!) {
  popularTitles(country: $country, filter: $filter, first: $first, sortBy: POPULAR, sortRandomSeed: 0, after: $after) {
    edges { node { id objectType
      content(country: $country, language: $language) {
        title fullPath originalReleaseYear shortDescription runtime ageCertification%s
        posterUrl(profile: S718, format: JPG)
        genres { shortName translation(language: $language) }
        externalIds { imdbId }
        scoring { imdbScore imdbVotes } }
      watchNowOffer(country: $country, platform: WEB, filter: $watchNowFilter) {
        standardWebURL streamUrlExternalPlayer monetizationType package { shortName } } } }
    pageInfo { endCursor hasNextPage }
    totalCount } }'''
# 0.5.52: JustWatch itself says when a title has a youth-protection time window (FSK 16: 22-6 h,
# FSK 18: 23-6 h; empty list = no window). The basic query is the fallback if the field is refused.
CATALOG_QUERY_BASIC = CATALOG_QUERY % ''
CATALOG_QUERY = CATALOG_QUERY % ('\n        ageCertificationDetails(country: $country) '
                                 '{ ageValue availableHours { fromMinute toMinute } }')

SEASONS_QUERY = '''query MediathekAtlasJustWatchTvSeasons($fullPath: String!, $country: Country!, $language: Language!) {
  urlV2(fullPath: $fullPath) { node { id
    ... on Show { seasons { id content(country: $country, language: $language) { seasonNumber }
      episodes(limit: 300) { id
        content(country: $country, language: $language) { title shortDescription episodeNumber seasonNumber runtime }
        offers(country: $country, platform: WEB, filter: {packages: ["jwt"]}) {
          standardWebURL streamUrlExternalPlayer package { shortName } } } } } } } }'''

# 0.5.49: the shape justwatch.com itself uses (Björn's HAR, 12.11.2026): the series lists its seasons
# with their own paths, each season page lists its episodes. Used when the combined query above
# returns nothing (Björn: "Andromeda", 5 seasons x 22 episodes, showed no episodes).
SEASON_LIST_QUERY = '''query MediathekAtlasJustWatchTvSeasonList($fullPath: String!, $country: Country!, $language: Language!) {
  urlV2(fullPath: $fullPath) { node { id
    ... on Show { seasons { id totalEpisodeCount content(country: $country, language: $language) { seasonNumber fullPath } } } } } }'''

SEASON_QUERY = '''query MediathekAtlasJustWatchTvSeason($fullPath: String!, $country: Country!, $language: Language!, $limit: Int!) {
  urlV2(fullPath: $fullPath) { node { id
    ... on Season { episodes(limit: $limit) { id
      content(country: $country, language: $language) { title shortDescription episodeNumber seasonNumber runtime }
      offers(country: $country, platform: WEB, filter: {packages: ["jwt"]}) {
        standardWebURL streamUrlExternalPlayer package { shortName } } } } } } }'''

STREAM_QUERY = '''query MediathekAtlasJustWatchTvStream($fullPath: String!, $country: Country!) {
  urlV2(fullPath: $fullPath) { node { id
    ... on MovieOrShow { watchNowOffer(country: $country, platform: WEB, filter: {packages: ["jwt"], monetizationTypes: []}) {
      standardWebURL streamUrlExternalPlayer package { shortName } } }
    ... on Movie { offers(country: $country, platform: WEB, filter: {packages: ["jwt"]}) {
      standardWebURL streamUrlExternalPlayer package { shortName } } } } } }'''


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
    path = root / 'justwatch.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    if 'night' not in {r[1] for r in db.execute('PRAGMA table_info(justwatch_items)')}:
        # 0.5.52: older stock; until the next catalogue run the age rating decides (16/18 = time window).
        with db:
            db.execute('ALTER TABLE justwatch_items ADD COLUMN night INTEGER NOT NULL DEFAULT 0')
            db.execute("UPDATE justwatch_items SET night=1 WHERE CAST(rating AS INTEGER)>=16")
            db.execute("UPDATE justwatch_items SET night=1 WHERE kind='episode' AND series_id IN "
                       "(SELECT id FROM justwatch_items WHERE kind='series' AND night=1)")
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM justwatch_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO justwatch_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def _post(query, variables):
    """One GraphQL request to the fixed JustWatch endpoint; GraphQL errors become ValueError."""
    body = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    req = urllib.request.Request(API_URL, data=body, method='POST', headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Content-Type': 'application/json',
        'Origin': SITE, 'Referer': SITE + '/'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > MAX_ANSWER:
            raise ValueError('JustWatch-Antwort zu groß')
        data = response.read(MAX_ANSWER + 1)
    if len(data) > MAX_ANSWER:
        raise ValueError('JustWatch-Antwort zu groß')
    return json.loads(data.decode('utf-8'))


def _data(answer):
    if not isinstance(answer, dict):
        raise ValueError('JustWatch lieferte kein gültiges Ergebnis')
    if answer.get('errors') and not answer.get('data'):
        # Only the first message, shortened; it never contains personal data.
        first = answer['errors'][0] if isinstance(answer['errors'], list) and answer['errors'] else {}
        raise ValueError('JustWatch lehnte die Abfrage ab: ' + _text((first or {}).get('message'), 160))
    return answer.get('data') or {}


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return 'JustWatch verweigert den Zugriff (HTTP %d)' % code
    if code:
        return 'JustWatch antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('JustWatch ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'JustWatch-Katalog konnte nicht geladen werden'


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


def _float(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def poster(value):
    """'/poster/123/{profile}/slug.{format}' or a full images.justwatch.com address -> https URL."""
    value = str(value or '')
    if value.startswith('/poster/'):
        value = IMAGES + value.replace('{profile}', 's718').replace('{format}', 'jpg')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or parts.hostname != 'images.justwatch.com' or parts.port or parts.username \
            or len(value) > 600 or not re.fullmatch(r'/poster/\d{1,15}/s\d{2,4}/[A-Za-z0-9_.\-]{1,200}', parts.path):
        return ''
    return value


def web_url(value, path=''):
    """Official title page (only www.justwatch.com/de/…)."""
    for candidate in (value, SITE + path if path else ''):
        parts = urllib.parse.urlsplit(str(candidate or ''))
        if parts.scheme == 'https' and parts.hostname == 'www.justwatch.com' and not parts.port \
                and not parts.username and VALID_PATH.fullmatch(parts.path):
            return SITE + parts.path + ('?package=' + PACKAGE)
    return ''


def stream_url(value):
    """External-player HLS address; only JustWatch's own manifest endpoint is accepted."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or parts.hostname != 'apis.justwatch.com' or parts.port or parts.username \
            or parts.password or len(value) > 4000 or not STREAM_PATH.fullmatch(parts.path):
        return ''
    return value


def genres(content):
    out = []
    for g in (content.get('genres') or [])[:12] if isinstance(content, dict) else []:
        if not isinstance(g, dict):
            continue
        name = _text(g.get('translation'), 60)
        if name and name not in IGNORED_GENRES and g.get('shortName') not in IGNORED_GENRES and name not in out:
            out.append(name)
    return ', '.join(out)


def _offer(offers):
    """First offer of JustWatch TV Free from an offer or a list of offers."""
    for o in offers if isinstance(offers, list) else [offers]:
        if isinstance(o, dict) and ((o.get('package') or {}).get('shortName') in (None, PACKAGE)):
            return o
    return None


def night_only(content):
    """True if JustWatch releases the title only inside a youth-protection time window."""
    details = content.get('ageCertificationDetails') if isinstance(content, dict) else None
    if isinstance(details, dict) and isinstance(details.get('availableHours'), list):
        return bool(details['availableHours'])
    age = _int((details or {}).get('ageValue') if isinstance(details, dict) else None, 0, 21)
    if age is None:
        found = re.search(r'\d{1,2}', str((content or {}).get('ageCertification') or ''))
        age = int(found.group()) if found else 0
    return age >= 16


def item_from(node):
    """Film or series from a popularTitles node; None if it is not a JustWatch TV Free title."""
    if not isinstance(node, dict):
        return None
    item_id = str(node.get('id') or '')
    kind = {'MOVIE': 'movie', 'SHOW': 'series'}.get(node.get('objectType'))
    content = node.get('content') if isinstance(node.get('content'), dict) else {}
    title = _text(content.get('title'), 200)
    path = str(content.get('fullPath') or '')
    if not VALID_ID.fullmatch(item_id) or not kind or not title or not VALID_PATH.fullmatch(path):
        return None
    offer = _offer(node.get('watchNowOffer'))
    if node.get('watchNowOffer') and offer is None:
        return None   # best offer belongs to another package
    scoring = content.get('scoring') if isinstance(content.get('scoring'), dict) else {}
    imdb = ((content.get('externalIds') or {}).get('imdbId') or '') if isinstance(content.get('externalIds'), dict) else ''
    runtime = _int(content.get('runtime'), 1, 1440)
    return {
        'id': item_id, 'kind': kind, 'title': title, 'path': path, 'series_id': '', 'season': None, 'episode': None,
        'year': _int(content.get('originalReleaseYear'), 1880, 2100),
        'duration': runtime * 60 if runtime and kind == 'movie' else None,
        'rating': _text(content.get('ageCertification'), 20), 'genre': genres(content),
        'summary': _text(content.get('shortDescription'), 1600), 'poster': poster(content.get('posterUrl')),
        'imdb_id': imdb if re.fullmatch(r'tt\d{5,10}', imdb) else '',
        'imdb_score': _float(scoring.get('imdbScore'), 0, 10), 'imdb_votes': _int(scoring.get('imdbVotes'), 0),
        'playable': 1 if offer and stream_url(offer.get('streamUrlExternalPlayer')) else 0,
        'web_url': web_url((offer or {}).get('standardWebURL'), path), 'night': 1 if night_only(content) else 0}


def parse_page(data):
    pt = (data or {}).get('popularTitles') or {}
    items = [i for i in (item_from((e or {}).get('node')) for e in (pt.get('edges') or [])[:500]) if i]
    info = pt.get('pageInfo') or {}
    cursor = info.get('endCursor') if isinstance(info.get('endCursor'), str) and len(info['endCursor']) < 200 else ''
    return items, cursor, bool(info.get('hasNextPage')) and bool(cursor), _int(pt.get('totalCount'), 0)


def parse_seasons(data, series):
    node = ((data or {}).get('urlV2') or {}).get('node') or {}
    out, streams = [], {}
    for season in (node.get('seasons') or [])[:100]:
        if not isinstance(season, dict):
            continue
        number = _int(((season.get('content') or {}).get('seasonNumber')), 0, 999)
        for ep in (season.get('episodes') or [])[:1000]:
            if not isinstance(ep, dict) or not VALID_ID.fullmatch(str(ep.get('id') or '')):
                continue
            offer = _offer(ep.get('offers') or [])
            if offer is None:
                continue   # not on JustWatch TV Free
            c = ep.get('content') if isinstance(ep.get('content'), dict) else {}
            runtime = _int(c.get('runtime'), 1, 1440)
            url = stream_url(offer.get('streamUrlExternalPlayer'))
            if url:
                streams[ep['id']] = url
            out.append({'id': ep['id'], 'kind': 'episode', 'title': _text(c.get('title'), 200) or 'Folge',
                        'path': '', 'series_id': series['id'],
                        'season': _int(c.get('seasonNumber'), 0, 999) if c.get('seasonNumber') is not None else number,
                        'episode': _int(c.get('episodeNumber'), 0, 9999), 'year': None,
                        'duration': runtime * 60 if runtime else None, 'rating': '', 'genre': '',
                        'summary': _text(c.get('shortDescription'), 1600), 'poster': '', 'imdb_id': '',
                        'imdb_score': None, 'imdb_votes': None, 'playable': 1 if url else 0,
                        'web_url': web_url(offer.get('standardWebURL'), series.get('path') or ''),
                        'night': 1 if series.get('night') else 0})   # episodes follow their series
    return out, streams


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'playable', 'web_url', 'night')


def _store(db, items, now):
    for item in items:
        db.execute('''INSERT INTO justwatch_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)),
                      ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item.get(f, 0) if f == 'night' else item[f] for f in FIELDS], now, now))


def sync(root, post=None, now=None, gap=None):
    """Load all JustWatch TV Free films and series. Rows stay, but only titles seen in the
    latest successful run are listed (the free catalogue rotates)."""
    now = time.time() if now is None else float(now)
    post = post or _post
    gap = (REQUEST_GAP if post is _post else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('justwatch_sync_started')
    found, cursor, pages, total, partial, query = {}, '', 0, 0, False, CATALOG_QUERY
    try:
        while pages < MAX_PAGES and len(found) < MAX_ITEMS:
            variables = {'country': COUNTRY, 'language': LANGUAGE, 'first': PAGE, 'after': cursor,
                         'filter': {'packages': [PACKAGE], 'objectTypes': [], 'monetizationTypes': [], 'genres': [],
                                    'excludeGenres': [], 'searchQuery': ''},
                         'watchNowFilter': {'packages': [PACKAGE], 'monetizationTypes': []}}
            try:
                try:
                    items, cursor, more, total = parse_page(_data(post(query, variables)))
                except Exception as exc:
                    if found or query is CATALOG_QUERY_BASIC or _offline(exc):
                        raise
                    query = CATALOG_QUERY_BASIC   # time-window field refused: age rating decides instead
                    _notify('justwatch_query_fallback')
                    items, cursor, more, total = parse_page(_data(post(query, variables)))
            except Exception:
                if not found:
                    raise
                partial = True   # keep what was loaded; next run completes it
                break
            pages += 1
            for item in items:
                found.setdefault(item['id'], item)
            if not more:
                break
            if gap:
                time.sleep(gap)
        if not found:
            raise ValueError('JustWatch lieferte keine Titel von JustWatch TV')
        items = list(found.values())
        counts = {'movies': sum(1 for i in items if i['kind'] == 'movie'),
                  'series': sum(1 for i in items if i['kind'] == 'series'),
                  'playable': sum(1 for i in items if i['playable']),
                  'night_only': sum(1 for i in items if i['night'] and not i['playable']),
                  'protected': sum(1 for i in items if i['kind'] == 'movie' and not i['playable'] and not i['night'])}
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                # A partial run keeps the previous stock visible (only a complete run retires titles).
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now), ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', 'Katalog nur teilweise geladen' if partial else ''),
                                   ('total_reported', total or 0), ('next_attempt', now + 24 * 3600),
                                   *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('justwatch_sync_completed', pages=pages, partial=partial, **counts)
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
        _notify('justwatch_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


def _series(db, series_id):
    row = db.execute("SELECT * FROM justwatch_items WHERE id=? AND kind='series'", (series_id,)).fetchone()
    if not row:
        raise ValueError('JustWatch-Serie nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def load_episodes(root, series_id, post=None, now=None):
    """Fetch seasons/episodes of a series (only those on JustWatch TV Free); returns fresh streams."""
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    call, first_error, mode = post or _post, None, 'combined'
    try:
        found, streams = parse_seasons(_data(call(SEASONS_QUERY, {
            'fullPath': series['path'], 'country': COUNTRY, 'language': LANGUAGE})), series)
    except Exception as exc:
        if _offline(exc):
            raise                  # network down: the per-season requests would fail the same way
        found, streams, first_error = [], {}, exc   # query refused (also HTTP 4xx) or answer not usable
    if not found:
        mode = 'per_season'
        try:
            found, streams = _episodes_by_season(call, series, pause=post is None)
        except Exception as exc:
            raise first_error or exc
        if not found and first_error:
            raise first_error
    _notify('justwatch_episodes_loaded', mode=mode, episodes=len(found), playable=len(streams))
    db = _connect(root)
    try:
        with db:
            _store(db, found, now)
            _set(db, 'series_checked:' + series_id, now)
    finally:
        db.close()
    for item_id, url in streams.items():
        _SOURCES[item_id] = (now + SOURCE_TTL, url)
    return found


def _offline(exc):
    """Network failure (not an HTTP answer of the server)."""
    return isinstance(exc, (urllib.error.URLError, OSError)) and not isinstance(exc, urllib.error.HTTPError)


def _episodes_by_season(call, series, pause=True):
    """Seasons first, then every season page on its own (as the website does)."""
    node = ((_data(call(SEASON_LIST_QUERY, {'fullPath': series['path'], 'country': COUNTRY, 'language': LANGUAGE}))
             .get('urlV2') or {}).get('node') or {})
    found, streams = [], {}
    for season in (node.get('seasons') or [])[:60]:
        content = season.get('content') if isinstance(season, dict) and isinstance(season.get('content'), dict) else {}
        path = str(content.get('fullPath') or '')
        if not re.fullmatch(r'/de/Serie/[A-Za-z0-9_\-]{1,160}/[A-Za-z0-9_\-]{1,60}', path):
            continue
        total = _int(season.get('totalEpisodeCount'), 1, 500) or 20
        data = None
        for limit in dict.fromkeys((min(total, 300), 20)):   # 20 is what the website asks for
            try:
                data = _data(call(SEASON_QUERY, {'fullPath': path, 'country': COUNTRY, 'language': LANGUAGE, 'limit': limit}))
                break
            except Exception as exc:
                if _offline(exc):
                    raise
                continue
        if data is None:
            continue
        episodes_ = ((data.get('urlV2') or {}).get('node') or {}).get('episodes') or []
        rows, urls = parse_seasons({'urlV2': {'node': {'seasons': [{'content': {'seasonNumber': content.get('seasonNumber')},
                                                                   'episodes': episodes_}]}}}, series)
        found += rows
        streams.update(urls)
        if pause:
            time.sleep(0.3)
    return found, streams


def episodes(root, series_id, post=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')):
        raise ValueError('Ungültige JustWatch-Serie')
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
            load_episodes(root, series_id, post, now)
        except Exception as exc:
            error = _error(exc)
    db = _connect(root)
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM justwatch_items WHERE kind='episode' AND series_id=? ORDER BY season,episode,title",
            (series_id,))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': error}


def own_score(row):
    """IMDb rating that JustWatch itself publishes (same shape as portal_reference.rating)."""
    value = row.get('imdb_score')
    if not isinstance(value, (int, float)) or not 0 <= value <= 10:
        return None
    return {'value': round(float(value), 1), 'source': 'IMDb', 'votes': row.get('imdb_votes')}


def _summary(root, row, reports=None):
    import portal_reference, justwatch_enrichment
    report = (reports if reports is not None else justwatch_enrichment.all_cached(root)).get(row['id'])
    # JustWatch is itself a metadata service: its IMDb ID identifies the title (0.5.83).
    out = portal_reference.summary(row.get('genre'), report, identified=bool(row.get('imdb_id')), age=portal_reference.age_of(row))
    if not out['score']:
        out['score'] = own_score(row)
    return out


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films or series with canonical categories and ratings (as the Mediathek catalogue)."""
    import portal_reference, justwatch_enrichment
    kind = {'movies': 'movie', 'series': 'series'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    # 'all': the merged dashboard index (unified_index.py) reads every row once and pages itself.
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM justwatch_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = justwatch_enrichment.all_cached(root)
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


def item(root, item_id):
    """Detail view of one film, series or episode: catalogue row, series, reference report."""
    import justwatch_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger JustWatch-Titel')
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM justwatch_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise ValueError('JustWatch-Titel nicht im Katalog; bitte Katalog neu laden')
        row = dict(row)
        parent = db.execute('SELECT * FROM justwatch_items WHERE id=?', (row['series_id'],)).fetchone() \
            if row.get('series_id') else None
        parent = dict(parent) if parent else None
    finally:
        db.close()
    report = justwatch_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'web_url': row.get('web_url') or (parent or {}).get('web_url') or ''},
            'series': parent, 'reference': report}


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
            'playable': _int(_get(db, 'playable', '0')) or 0,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM justwatch_items WHERE kind='episode'").fetchone()[0]}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='justwatch_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:justwatch'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or portal_reference.retry_after_update(root, sys.modules[__name__], current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

# Youth protection (Björn, 12.11.2026, text on justwatch.com: "Ab 00:00 Uhr verfügbar (Jugendschutz)
# … von 00:00 Uhr bis 06:00 Uhr"): by day JustWatch publishes no stream for such titles. Nothing is
# circumvented; a download can be reserved and starts inside the window, when JustWatch releases it.
NIGHT_START = (0, 10)     # local time Europe/Berlin, a little after midnight
NIGHT_END = (5, 0)        # latest start, so the download ends before 06:00
NIGHT_NOTE = 'Jugendschutz: JustWatch gibt diesen Titel nur von 0 bis 6 Uhr frei'


def night_start(now=None):
    """Unix time at which a night-only title may be fetched: now inside the window, else next 00:10."""
    import datetime
    now = time.time() if now is None else float(now)
    try:
        import zoneinfo
        zone = zoneinfo.ZoneInfo('Europe/Berlin')
    except Exception:
        zone = None   # system without time zone data: local time of the device
    local = datetime.datetime.fromtimestamp(now, zone)
    start = local.replace(hour=NIGHT_START[0], minute=NIGHT_START[1], second=0, microsecond=0)
    end = local.replace(hour=NIGHT_END[0], minute=NIGHT_END[1], second=0, microsecond=0)
    if start <= local <= end:
        return now
    if local > end:
        start += datetime.timedelta(days=1)
    return start.timestamp()


# 0.5.52 (Björn's HAR of "Andromeda", FSK 12, 12.11.2026): titles without an address for external
# players run in JustWatch's own player only, Widevine/PlayReady/FairPlay protected (licence server,
# SAMPLE-AES). That is copy protection, not a time window: no player here and no offline copy.
PROTECTED = ('JustWatch spielt diesen Titel nur im eigenen, kopiergeschützten Player (DRM) ab. '
             'Wiedergabe und Offline-Kopie in MediathekAtlas sind dafür nicht möglich; „Bei JustWatch ansehen“ verwenden.')
NOT_PLAYABLE = PROTECTED
NIGHT_NOT_PLAYABLE = ('JustWatch hat auch im Jugendschutz-Zeitfenster keinen Stream für externe Player freigegeben; '
                      'der Titel läuft nur im kopiergeschützten JustWatch-Player.')


def fresh_stream(root, row, post=None, now=None):
    """Signed external-player address, fetched right now (cached five minutes in memory only)."""
    now = time.time() if now is None else now
    cached = _SOURCES.get(row['id'])
    if cached and cached[0] > now:
        return cached[1]
    url = ''
    if row['kind'] == 'episode':
        load_episodes(root, row['series_id'], post, now)
        cached = _SOURCES.get(row['id'])
        url = cached[1] if cached else ''
    else:
        node = ((_data((post or _post)(STREAM_QUERY, {'fullPath': row['path'], 'country': COUNTRY}))
                 .get('urlV2') or {}).get('node') or {})
        for offer in [node.get('watchNowOffer')] + list(node.get('offers') or []):
            o = _offer(offer)
            url = stream_url((o or {}).get('streamUrlExternalPlayer'))
            if url:
                break
    if not url:
        raise ValueError(NIGHT_NOT_PLAYABLE if row.get('night') else PROTECTED)
    _SOURCES[row['id']] = (now + SOURCE_TTL, url)
    return url


def released_now(root, row, post=None, now=None):
    """0.5.76: does JustWatch release a stream for external players at this moment? Asked live,
    because the real youth-protection window (FSK 16: 22-6 h, FSK 18: 23-6 h) is wider than the
    fixed night start and the stored catalogue flag can be hours old. Never raises."""
    try:
        return bool(fresh_stream(root, row, post, now))
    except Exception:
        return False


def play_source(root, item_id, post=None, check=None, now=None):
    """Source for streaming.plan: HLS, checked for copy protection before use."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger JustWatch-Titel')
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM justwatch_items WHERE id=?', (item_id,)).fetchone()
        row = dict(row) if row else None
        series = db.execute('SELECT title FROM justwatch_items WHERE id=?', (row['series_id'],)).fetchone() \
            if row and row['series_id'] else None
    finally:
        db.close()
    if not row:
        raise ValueError('JustWatch-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    try:
        url = fresh_stream(root, row, post, now)
        import hls_guard
        (check or hls_guard.check)(url)
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(_error(exc)) from None
    title = row['title']
    if row['kind'] == 'episode' and row['season'] is not None and row['episode'] is not None:
        title = '%s · S%02dE%02d · %s' % (series['title'] if series else 'Serie', row['season'], row['episode'], row['title'])
    elif row['year']:
        title += ' (%s)' % row['year']
    return {'kind': 'url', 'url': url, 'hls': True, 'quality': 'JustWatch TV (mit Werbung)', 'title': title,
            'duration': row['duration'] or 0, 'provider': 'justwatch', 'live': False}
