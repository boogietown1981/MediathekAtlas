"""ServusTV On: the free video library and the two live channels of ServusTV (0.5.101).

Björn (13.11.2026, decision card "Beides"): connect ServusTV On with playback in the own player, and
RTL+ as a catalogue with links. ServusTV is free, needs no account and streams plain HLS without copy
protection (as yt-dlp's ``ServusIE`` shows); every stream is still checked with hls_guard.

Interfaces (servustv.com is blocked in the build environment, nothing here is recorded live):

* Playback (documented by yt-dlp): ``GET https://api-player.redbull.com/stv/servus-tv-playnet?videoId=AA-…``
  -> ``videoUrl`` (HLS) plus ``title``, ``description``, ``poster``, ``duration``, ``label`` (format),
  ``season`` ("Season 11"), ``chapter`` ("Episode 8 - …"). Without ``videoUrl`` the answer names
  ``playabilityErrors`` (``FSK_BLOCKED`` with hours, ``NOT_YET_AVAILABLE``, geo blocks); they are
  shown in plain words. Older address ``/stv/servus-tv?timeZone=Europe/Berlin`` as fallback.
* Video pages are WordPress (``backend.servustv.com``, namespace ``rbmh/v2``; the page data has
  ``title.rendered``, ``stv_date.raw``, ``stv_duration``, ``category_names``,
  ``stv_short_description``). The catalogue is read from the WordPress REST index: the first
  listable route for media assets found there is paged with ``per_page``/``page``. Fields are read
  tolerantly because their exact names are not known yet.
* Fallback catalogue: the sitemaps named in ``www.servustv.com/robots.txt`` (video URLs
  ``/<bereich>/v/aa-…/``, with ``video:`` tags where present). Entries without a title get it from
  the player interface, a limited number per run.
* Live: ServusTV Deutschland and Österreich, public HLS addresses (as listed by iptv-org and Kodi
  add-ons), several candidates each, the first one that answers as clear HLS wins.

No offline copies: ServusTV allows downloads only inside its own app. Titles, URLs and errors in
detail never go to logs or the diagnosis export.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import portal_reference

KEY = 'servustv'
NAME = 'ServusTV'
SITE = 'https://www.servustv.com'
BACKEND = 'https://backend.servustv.com'
PLAYER = 'https://api-player.redbull.com'
PLAYER_PATHS = ('/stv/servus-tv-playnet', '/stv/servus-tv')
API_HOSTS = frozenset({'www.servustv.com', 'servustv.com', 'backend.servustv.com', 'api-player.redbull.com'})
LIVE_HOSTS = frozenset({'rbmn-live.akamaized.net', 'stv-live.akamaized.net'})
# Candidate list routes for media assets, in this order, if the REST index does not name one.
ROUTES = ('/wp/v2/media_asset', '/rbmh/v2/media_asset', '/wp/v2/video', '/wp/v2/videos', '/wp/v2/stv_video')
LIVE = (
    ('c.de', 'ServusTV Deutschland', 1, ('https://rbmn-live.akamaized.net/hls/live/2002830/geoSTVDEweb/master.m3u8',
                                         'https://rbmn-live.akamaized.net/hls/live/2002830/geoSTVDEweb/master_6692.m3u8')),
    ('c.at', 'ServusTV Österreich', 2, ('https://stv-live.akamaized.net/hls/live/2031011/lingeoSTVATwebPri/master.m3u8',
                                        'https://rbmn-live.akamaized.net/hls/live/2002825/geoSTVATweb/master.m3u8')),
)
MAX_ANSWER = 16 * 1024 * 1024
MAX_ITEMS = 30000
PAGE = 100
MAX_PAGES = 300
MAX_SITEMAPS = 150
FILL_PER_RUN = 400          # titles completed through the player interface per catalogue run
REQUEST_GAP = 0.3
SOURCE_TTL = 120
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
AA = re.compile(r'AA-?[A-Z0-9]{8,30}')
VALID_ID = re.compile(r'(?:v\.AA-?[A-Z0-9]{8,30}|s\.[a-z0-9][a-z0-9\-]{0,80}|c\.(?:de|at))')
VIDEO_URL = re.compile(r'https://(?:www\.)?servustv\.com/(?:[a-z0-9\-]+/)*v(?:ideos)?/(aa-?[a-z0-9]{8,30})/?', re.I)
# The section in the address (/natur/v/…) as provider genre.
SECTIONS = {'natur': 'Natur', 'wissen': 'Wissen', 'sport': 'Sport', 'unterhaltung': 'Unterhaltung',
            'kultur': 'Kultur', 'aktuelles': 'Nachrichten', 'news': 'Nachrichten', 'volkskultur': 'Volkskultur',
            'spielfilme': 'Spielfilm', 'filme': 'Spielfilm', 'serien': 'Serie', 'krimi': 'Krimi',
            'doku': 'Dokumentation', 'dokumentationen': 'Dokumentation', 'reisen': 'Reise', 'musik': 'Musik',
            'kinder': 'Kinder', 'talk': 'Talk', 'motorsport': 'Motorsport', 'fussball': 'Fußball',
            'wintersport': 'Wintersport', 'eishockey': 'Eishockey', 'religion': 'Religion', 'heimat': 'Heimat'}
FILM_WORDS = ('spielfilm', 'film', 'krimi', 'thriller', 'komödie', 'drama', 'western', 'heimatfilm')

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


def video_id(value):
    """'aa-28bycqnh92111' or a URL with it -> 'AA-28BYCQNH92111'; '' when there is none."""
    found = AA.search(str(value or '').upper())
    return found.group(0) if found else ''


# ---------------------------------------------------------------- network

def _headers(accept='application/json'):
    return {'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Language': 'de-DE,de;q=0.9',
            'Origin': SITE, 'Referer': SITE + '/'}


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS | LIVE_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige ServusTV-Anfrage')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('ServusTV-Antwort zu groß')
        raw = response.read(limit + 1)
        final = response.geturl()
    if len(raw) > limit:
        raise ValueError('ServusTV-Antwort zu groß')
    return raw, final


def _json(opener, url):
    raw, _ = opener(url, _headers())
    return json.loads(raw.decode('utf-8'))


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

def image(value):
    """Absolute https image address (no credentials, no port), else ''."""
    if isinstance(value, dict):
        value = value.get('url') or value.get('src') or value.get('source_url') or ''
    if isinstance(value, list):
        value = value[0] if value else ''
        return image(value)
    value = str(value or '').strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.port or parts.username or len(value) > 600 \
            or re.search(r'[\s<>"\']', value):
        return ''
    return value


def _rendered(value):
    return value.get('rendered') if isinstance(value, dict) else value


def _first(node, *keys):
    for key in keys:
        value = node.get(key) if isinstance(node, dict) else None
        value = _rendered(value)
        if isinstance(value, dict):
            value = value.get('raw') or value.get('name') or value.get('title') or value.get('value')
        if value not in (None, '', [], {}):
            return value
    return None


def _number(value, word):
    """'Season 11' / 'Staffel 11' / 11 -> 11; 'Episode 8 - Titel' -> 8."""
    if isinstance(value, (int, float)):
        return _int(value, 0, 9999)
    found = re.search(r'(?i)(?:%s)\s*(\d{1,4})' % word, str(value or ''))
    return _int(found.group(1), 0, 9999) if found else None


def _episode_title(chapter):
    """'Episode 8 - Vie Ferrate – Klettersteige' -> 'Vie Ferrate – Klettersteige'."""
    return _text(re.sub(r'(?i)^\s*(?:episode|folge)\s*\d{1,4}\s*[-–:·]?\s*', '', str(chapter or '')), 200)


def _web(value):
    value = str(value or '')
    return value if VIDEO_URL.fullmatch(value) or re.fullmatch(r'https://www\.servustv\.com/[A-Za-z0-9\-_/]{1,300}', value) else ''


def _genres(node, url=''):
    names = node.get('category_names') if isinstance(node, dict) else None
    out = []
    if isinstance(names, list):
        out = [_text(n.get('name') if isinstance(n, dict) else n, 60) for n in names]
    elif isinstance(names, str):
        out = [_text(n, 60) for n in names.split(',')]
    section = re.match(r'https://(?:www\.)?servustv\.com/([a-z0-9\-]+)/v/', str(url or ''))
    if section and section.group(1) in SECTIONS:
        out.append(SECTIONS[section.group(1)])
    seen = []
    for g in out:
        if g and g not in seen:
            seen.append(g)
    return seen[:8]


def video_from(node):
    """Normalised video from a WordPress media asset (or a player answer); None without id or title."""
    if not isinstance(node, dict):
        return None
    vid = ''
    for key in ('aa_id', 'stv_aa_id', 'stv_video_id', 'video_id', 'videoId', 'asset_id', 'stv_asset_id', 'id'):
        vid = video_id(_first(node, key))
        if vid:
            break
    link = str(_first(node, 'link', 'url', 'permalink') or '')
    if not vid:
        vid = video_id(link) or video_id(_first(node, 'slug'))
    title = _text(_first(node, 'title', 'stv_title', 'name'), 200)
    if not vid or not title:
        return None
    published = _int(_first(node, 'stv_date', 'currentSunrise', 'date_gmt', 'date'), 0)
    if published is None:
        raw = str(_first(node, 'date_gmt', 'date', 'currentSunrise') or '')
        try:
            import datetime
            published = int(datetime.datetime.fromisoformat(raw.replace('Z', '+00:00')[:25]).timestamp()) if raw else None
        except ValueError:
            published = None
    duration = _int(_first(node, 'stv_duration', 'duration'), 1, 24 * 3600)
    series = _text(_first(node, 'stv_format', 'stv_format_name', 'format_name', 'format', 'label', 'stv_label',
                          'series', 'stv_series', 'show'), 160)
    season = _number(_first(node, 'stv_season', 'season', 'season_number'), 'season|staffel')
    chapter = _first(node, 'stv_episode', 'episode', 'chapter', 'episode_number')
    episode = _number(chapter, 'episode|folge')
    summary = ''
    for key in ('stv_short_description', 'stv_long_description', 'description', 'excerpt', 'content'):
        summary = _text(_first(node, key), 1600)
        if summary:
            break
    poster = ''
    for key in ('stv_image', 'stv_teaser_image', 'poster', 'image', 'featured_image', 'jetpack_featured_media_url',
                'thumbnail', 'yoast_head_json'):
        value = node.get(key)
        if key == 'yoast_head_json' and isinstance(value, dict):
            value = value.get('og_image')
        poster = image(value)
        if poster:
            break
    age = _text(_first(node, 'stv_fsk', 'fsk', 'age_rating'), 12)
    return {'vid': vid, 'title': title, 'series': series if series and series.casefold() != title.casefold() else '',
            'season': season, 'episode': episode, 'episode_title': _episode_title(chapter) if isinstance(chapter, str) else '',
            'duration': duration, 'summary': summary, 'poster': poster, 'published': published,
            'rating': ('FSK ' + age) if re.fullmatch(r'\d{1,2}', age) else age,
            'genres': _genres(node, link), 'web_url': _web(link)}


def _sitemap_entry(url_node, ns):
    loc = (url_node.findtext('sm:loc', '', ns) or '').strip()
    match = VIDEO_URL.fullmatch(loc)
    if not match:
        return None
    video = url_node.find('video:video', ns)
    title = summary = poster = ''
    duration = published = None
    if video is not None:
        title = _text(video.findtext('video:title', '', ns), 200)
        summary = _text(video.findtext('video:description', '', ns), 1600)
        poster = image(video.findtext('video:thumbnail_loc', '', ns))
        duration = _int(video.findtext('video:duration', '', ns), 1, 24 * 3600)
        raw = video.findtext('video:publication_date', '', ns)
        if raw:
            try:
                import datetime
                published = int(datetime.datetime.fromisoformat(raw.strip().replace('Z', '+00:00')[:25]).timestamp())
            except ValueError:
                published = None
    if not poster:
        poster = image(url_node.findtext('image:image/image:loc', '', ns))
    return {'vid': video_id(match.group(1)), 'title': title, 'series': '', 'season': None, 'episode': None,
            'episode_title': '', 'duration': duration, 'summary': summary, 'poster': poster, 'published': published,
            'rating': '', 'genres': _genres({}, loc), 'web_url': loc}


SITEMAP_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'video': 'http://www.google.com/schemas/sitemap-video/1.1',
              'image': 'http://www.google.com/schemas/sitemap-image/1.1'}


def parse_sitemap(raw):
    """(child sitemaps, video entries) of one sitemap file. External entities are never resolved."""
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
    if '<!DOCTYPE' in text[:2000] or '<!ENTITY' in text[:4000]:
        raise ValueError('Ungültige Sitemap')
    root = ET.fromstring(text)
    children = [s.strip() for s in (n.findtext('sm:loc', '', SITEMAP_NS) for n in root.findall('sm:sitemap', SITEMAP_NS)) if s]
    entries = [e for e in (_sitemap_entry(n, SITEMAP_NS) for n in root.findall('sm:url', SITEMAP_NS)) if e]
    return children, entries


# ---------------------------------------------------------------- catalogue sources

def rest_routes(index):
    """List routes for media assets named in a WordPress REST index, best first."""
    routes = index.get('routes') if isinstance(index, dict) else None
    if not isinstance(routes, dict):
        return list(ROUTES)
    named = [r for r in routes if isinstance(r, str) and '(?P' not in r and re.fullmatch(r'/[a-z0-9_\-/]{3,80}', r)
             and re.search(r'media_asset|video', r) and not r.endswith(('/schema', '/search'))]
    named.sort(key=lambda r: (ROUTES.index(r) if r in ROUTES else len(ROUTES), len(r)))
    return named + [r for r in ROUTES if r not in named]


def load_rest(opener, gap, found):
    """Media assets from the WordPress REST interface; (complete, note)."""
    try:
        index = _json(opener, BACKEND + '/wp-json/')
    except (urllib.error.HTTPError, ValueError):
        index = None
    for route in rest_routes(index)[:6]:
        page, got = 1, 0
        while page <= MAX_PAGES and len(found) < MAX_ITEMS:
            url = BACKEND + '/wp-json' + route + '?' + urllib.parse.urlencode(
                {'per_page': PAGE, 'page': page, 'orderby': 'date', 'order': 'desc'})
            try:
                answer = _json(opener, url)
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 404) and page > 1:   # WordPress: page number past the end
                    return True, ''
                if exc.code in (400, 401, 403, 404):
                    break
                raise
            entries = answer if isinstance(answer, list) else (answer.get('items') or answer.get('data') or []) \
                if isinstance(answer, dict) else []
            if not isinstance(entries, list):
                entries = []
            for node in entries:
                video = video_from(node)
                if video:
                    found.setdefault(video['vid'], video)
                    got += 1
            if len(entries) < PAGE:
                break
            page += 1
            if gap:
                time.sleep(gap)
        if got:
            return page <= MAX_PAGES, ''
    return False, 'WordPress-Schnittstelle ohne Videoliste'


def load_sitemaps(opener, gap, found):
    """Video pages from the sitemaps named in robots.txt; (complete, note)."""
    queue = []
    try:
        raw, _ = opener(SITE + '/robots.txt', _headers('text/plain'), limit=512 * 1024)
        queue = [m.strip() for m in re.findall(r'(?im)^\s*sitemap:\s*(\S+)', raw.decode('utf-8', 'replace'))]
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        pass
    queue += [SITE + '/sitemap_index.xml', SITE + '/sitemap.xml']
    done, read, complete = set(), 0, True
    while queue and read < MAX_SITEMAPS and len(found) < MAX_ITEMS:
        url = queue.pop(0)
        parts = urllib.parse.urlsplit(url)
        if url in done or parts.scheme != 'https' or parts.hostname not in API_HOSTS:
            continue
        done.add(url)
        try:
            raw, _ = opener(url, _headers('application/xml'))
            children, entries = parse_sitemap(raw)
        except (urllib.error.HTTPError, ValueError, ET.ParseError):
            continue
        read += 1
        # Video sitemaps first; news, tags and plain pages last.
        children.sort(key=lambda u: (0 if re.search(r'(?i)video|media|asset', u) else 1))
        queue = children + queue
        for entry in entries:
            found.setdefault(entry['vid'], entry)
        if gap:
            time.sleep(gap)
    if queue and read >= MAX_SITEMAPS:
        complete = False
    return complete and read > 0, '' if read else 'keine Sitemap erreichbar'


def player_info(vid, opener=None):
    """Answer of the player interface for one video (first address that answers)."""
    opener = opener or _open
    last = None
    for path in PLAYER_PATHS:
        query = {'videoId': vid}
        if path.endswith('servus-tv'):
            query['timeZone'] = 'Europe/Berlin'
        try:
            answer = _json(opener, PLAYER + path + '?' + urllib.parse.urlencode(query))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (404, 410):
                continue
            raise
        if isinstance(answer, dict):
            return answer
    if last:
        raise last
    raise ValueError('ServusTV nennt zu diesem Video nichts')


def _fill(opener, videos, gap, limit=FILL_PER_RUN):
    """Titles from the player interface for sitemap entries without one (limited per run)."""
    done = 0
    for video in videos[:limit]:
        try:
            info = player_info(video['vid'], opener)
        except Exception:
            continue
        done += 1
        better = video_from({**info, 'videoId': video['vid']})
        if better:
            for key, value in better.items():
                if value and not video.get(key):
                    video[key] = value
        if gap:
            time.sleep(gap)
    return done


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'published',
          'playable', 'drm', 'web_url')
_KEEP = ('drm', 'playable')


def _row_of(video, now):
    """Catalogue rows (film, or series + episode) for one normalised video."""
    # The publication date is not the production year: leave the year open for the reference checks.
    year = None
    genre = ', '.join(video['genres'])
    filmish = any(w in genre.casefold() for w in FILM_WORDS)
    base = {'path': video['vid'], 'season': None, 'episode': None, 'year': year, 'duration': video['duration'],
            'rating': video['rating'], 'genre': genre, 'summary': video['summary'], 'poster': video['poster'],
            'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': video['genres'][0] if video['genres'] else '', 'published': video['published'],
            'playable': 1, 'drm': -1, 'web_url': video['web_url'] or ''}
    if video['series'] and not (filmish and video['season'] is None and video['episode'] is None):
        sid = 's.' + (slug(video['series']) or 'servustv')
        series = {**base, 'id': sid, 'kind': 'series', 'title': video['series'], 'path': '', 'series_id': '',
                  'duration': None, 'web_url': '', 'summary': '', 'year': None}
        episode = {**base, 'id': 'v.' + video['vid'], 'kind': 'episode', 'series_id': sid,
                   'title': video['episode_title'] or video['title'], 'season': video['season'], 'episode': video['episode']}
        return [series, episode]
    return [{**base, 'id': 'v.' + video['vid'], 'kind': 'movie', 'title': video['title'], 'series_id': ''}]


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS if f not in _KEEP)
    for item in items:
        db.execute('''INSERT INTO servustv_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item.get(f) for f in FIELDS], now, now))


def _merge_series(rows):
    """One series row per format: newest poster, all genres, summary of the first episode with one."""
    series, out = {}, []
    for row in rows:
        if row['kind'] != 'series':
            out.append(row)
            continue
        have = series.get(row['id'])
        if not have:
            series[row['id']] = dict(row)
            continue
        have['poster'] = have['poster'] or row['poster']
        genres = [g for g in (have['genre'] + ', ' + row['genre']).split(', ') if g]
        have['genre'] = ', '.join(dict.fromkeys(genres))[:300]
        have['category'] = have['category'] or row['category']
    return out + list(series.values())


def live_rows():
    return [{'id': cid, 'kind': 'channel', 'title': title, 'path': cid[2:], 'series_id': '', 'season': None,
             'episode': None, 'year': None, 'duration': None, 'rating': '', 'genre': 'Vollprogramm',
             'summary': 'Das laufende Programm von ServusTV (%s).' % ('Deutschland' if cid == 'c.de' else 'Österreich'),
             'poster': '', 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': number,
             'category': 'Vollprogramm', 'published': None, 'playable': 1, 'drm': -1,
             'web_url': SITE + '/de/live-tv/' if cid == 'c.de' else SITE + '/at/live-tv/'}
            for cid, title, number, _ in LIVE]


def sync(root, opener=None, now=None, gap=None):
    """Load the video library. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    opener = opener or _open
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('servustv_sync_started')
    try:
        found, notes, source = {}, [], ''
        try:
            complete, note = load_rest(opener, gap, found)
            source = 'rest' if found else ''
            if note:
                notes.append(note)
        except Exception as exc:
            complete = False
            notes.append('WordPress: ' + _error(exc))
        if not found:
            try:
                complete, note = load_sitemaps(opener, gap, found)
                source = 'sitemap' if found else ''
                if note:
                    notes.append(note)
            except Exception as exc:
                complete = False
                notes.append('Sitemap: ' + _error(exc))
        filled = _fill(opener, [v for v in found.values() if not v['title']], gap)
        videos = [v for v in found.values() if v['title']]
        if not videos:
            raise ValueError(notes[0] if notes else 'ServusTV lieferte keine Videos')
        rows = _merge_series([r for v in videos for r in _row_of(v, now)]) + live_rows()
        partial = not complete or len(videos) < len(found)
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
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600), ('source', source),
                                   ('filled', filled), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('servustv_sync_completed', partial=partial, source=source, **counts)
        return {'ok': True, 'partial': partial, 'source': source, **counts}
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
    """The two live channels. They do not depend on the catalogue, so they are listed as soon as the
    first catalogue run was attempted (about a minute after the first start), even if it failed."""
    db = _connect(root)
    try:
        tried = float(_get(db, 'last_attempt', '0') or 0)
    finally:
        db.close()
    if not tried:
        return []
    return [{k: r[k] for k in ('id', 'title', 'number', 'genre', 'category', 'summary', 'poster', 'web_url', 'drm')}
            for r in live_rows()]


def item(root, item_id):
    import servustv_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger ServusTV-Titel')
    if item_id.startswith('c.'):
        row = next(r for r in live_rows() if r['id'] == item_id)
        return {'item': {**row, **portal_reference.summary(row['genre'], None)}, 'series': None,
                'reference': dict(servustv_enrichment.UNCHECKED)}
    db = _connect(root)
    try:
        row = _row(db, item_id)
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
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'channels': len(LIVE), 'protected': protected,
            'source': _get(db, 'source')}
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
    check = check or hls_guard.check
    if item_id.startswith('c.'):
        row = next(r for r in live_rows() if r['id'] == item_id)
        cached = _SOURCES.get(item_id)
        if cached and cached[0] > now:
            url = cached[1]
        else:
            url, last = '', None
            for candidate in next(c for c in LIVE if c[0] == item_id)[3]:
                try:
                    check(candidate)
                    url = candidate
                    break
                except hls_guard.DrmProtected:
                    raise
                except Exception as exc:
                    last = exc
            if not url:
                raise ValueError(_error(last) if last else 'ServusTV live ist nicht erreichbar')
            _SOURCES[item_id] = (now + SOURCE_TTL, url)
        return {'kind': 'url', 'url': url, 'hls': True, 'title': row['title'], 'provider': KEY,
                'quality': 'ServusTV live (kostenlos)', 'duration': 0, 'live': True}
    db = _connect(root)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row:
        raise ValueError('ServusTV-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Sendung auswählen')
    if row['drm'] == 1:
        raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
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
        if not url:
            raise ValueError(playability(answer))
        try:
            check(url)
        except hls_guard.DrmProtected:
            _mark_drm(root, item_id, 1)
            raise
        if row['drm'] != 0:
            _mark_drm(root, item_id, 0)
        duration = _int(answer.get('duration'), 1, 24 * 3600) or row['duration'] or 0
        _SOURCES[item_id] = (now + SOURCE_TTL, (url, duration))
    return {'kind': 'url', 'url': url, 'hls': True, 'title': _player_title(row, parent), 'provider': KEY,
            'quality': 'ServusTV (kostenlos)', 'duration': duration or 0, 'live': False}
