"""DMAX, TLC & HGTV: the free on-demand libraries of Warner Bros. Discovery Germany (0.6.48).

Björn (20.11.2026): "welche dienste fehlen … hier kannst du auch alles angehen". dmax.de, tlc.de and
de.hgtv.com show their programmes (documentaries, reality, home and garden) with adverts, without an
account. All three run on the same Discovery platform, so one module serves them; each title carries
its channel (DMAX, TLC, HGTV) as category.

Interfaces (from public open-source clients: the yt-dlp extractors ``DiscoveryNetworksDeIE`` /
``HGTVDeIE`` (dplay.py, 2026.10) and Brawl345/Get-DMAX-Links; the hosts are blocked in the build
environment, so nothing here was checked live – the first catalogue run on Björn's computer decides):

* Token: ``GET https://eu1-prod.disco-api.com/token?realm=<realm>&deviceId=<hex>`` ->
  ``data.attributes.token`` (anonymous, kept in memory only). Realms ``dmaxde``, ``tlcde``, ``hgtv``.
* 0.6.52 (checked on Björn's Mac, 20.11.2026): de-api.loma-cms.com no longer exists (NXDOMAIN, "Name nicht
  auflösbar"). The websites read ``https://public.aurora.enhanced.live/site/`` without login:
  - Programmes: ``GET /site/page/sendungen/?include=default&filter[environment]=dmaxde&v=2`` ->
    ``blocks[0].items[]`` with ``title``, ``slug``, ``attributes.showId``, ``metaMedia`` (DMAX 74, TLC 65 with
    environment ``tlcde``; ``hgtv`` answered 500, the right name is unknown, so ``hgtvde`` is tried first).
  - Programme: ``GET /site/shows/<slug>/?include=default&filter[environment]=<env>&v=2`` -> ``showHeaderBlock``
    (``show.seasons``, pictures) and ``seoSonicShowBlock.items[]`` = episodes (``id``, ``alternateId``,
    ``videoType`` EPISODE, ``videoDuration`` ms, ``seasonNumber``, ``episodeNumber``, ``publishStart``/``End``,
    ``package.type`` free, ``meta.name``/``description``/``thumbnailUrl``/``embedUrl``). A programme without that
    block has no episodes online (19 of 20 checked had some).
  - Playback is NOT confirmed: the token host answered 504/502 on the Mac and the website puts a consent
    banner in front of its player. Until a recording shows how the free player gets its stream, every episode
    opens on the channel's website (``PLAYBACK_CONFIRMED``); the code below for the own player stays, unused.
* Episodes until 0.6.48 (disco-api, unconfirmed): ``GET …/content/videos/?filter[show.id]=<id>…``.
* Playback: ``POST …/playback/v3/videoPlaybackInfo`` with ``deviceInfo.drmSupported=false`` ->
  ``data.attributes.streaming[]`` (HLS address). Some programmes are delivered only with FairPlay or
  Widevine (yt-dlp issue reports: ``hls_fairPlay_ts``); such titles are recognised (``drmEnabled``,
  ``protection``, hls_guard) and only open the channel's website. Nothing is circumvented.
* Pages: ``https://dmax.de/sendungen/<show>/<episode>`` (TLC: tlc.de, HGTV: de.hgtv.com).

No offline copies (the channels allow none outside their own apps). Titles, tokens and addresses never go
to logs or the diagnosis export.
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
import uuid

import portal_reference
import provider_base

KEY = 'dmax'
NAME = 'DMAX, TLC & HGTV'
DISCO = 'https://eu1-prod.disco-api.com/'
AURORA = 'https://public.aurora.enhanced.live/site/'
API_HOSTS = frozenset({'eu1-prod.disco-api.com', 'public.aurora.enhanced.live'})
# 0.6.52: the own player is used only once a recording confirms how the free player gets its stream.
PLAYBACK_CONFIRMED = False
# key, channel name, realm, CMS environment, website
# (key, channel, realm, website environments to try in order, website). 0.6.52: environments of the website API
# (dmaxde and tlcde confirmed on Björn's Mac; for HGTV "hgtv" answered 500, "hgtvde" is a guess).
SITES = (('dmax', 'DMAX', 'dmaxde', ('dmaxde',), 'https://dmax.de'),
         ('tlc', 'TLC', 'tlcde', ('tlcde',), 'https://tlc.de'),
         ('hgtv', 'HGTV', 'hgtv', ('hgtvde', 'hgtv'), 'https://de.hgtv.com'))
REALMS = {s[2]: s for s in SITES}
# Category the channel stands for, added after the episode's own genres (the shared categories.py rules map it):
# DMAX documentary formats, TLC reality, HGTV home and garden. An assumption per channel, not a statement of
# the broadcaster; titles with own genres (True Crime, Paranormal …) get those as well.
CHANNEL_GENRE = {'dmaxde': 'Dokumentation', 'tlcde': 'Reality-TV', 'hgtv': 'Ratgeber & Lifestyle'}
DISCO_CLIENT = 'Alps:HyogaPlayer:0.0.0'
DEVICE_INFO = 'STONEJS/1 (Unknown/Unknown; Unknown/Unknown; Unknown)'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
MAX_ANSWER = 8 * 1024 * 1024
MAX_SHOWS = 1500             # per channel
MAX_ITEMS = 60000
REQUEST_GAP = 0.3
RETRY_WAITS = (3, 10)        # seconds before the 2nd and 3rd try after 429/5xx
SOURCE_TTL = 120
TOKEN_TTL = 6 * 3600
FREE_PACKAGES = {'free', 'registered', 'anonymous', 'avod'}
VALID_ID = re.compile(r'(?:s\.(?:dmaxde|tlcde|hgtv)\.\d{1,12}|e\.\d{1,14})')
NUMBER = re.compile(r'\d{1,14}')
SLUG = re.compile(r'[a-z0-9][a-z0-9\-]{0,160}')

_TOKENS = {}                 # realm -> (expires, token); memory only
_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS dmax_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', published REAL, realm TEXT NOT NULL DEFAULT '',
  offer TEXT NOT NULL DEFAULT 'free', playable INTEGER NOT NULL DEFAULT 1, drm INTEGER NOT NULL DEFAULT -1,
  web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS dmax_items_kind ON dmax_items(kind, seen);
CREATE INDEX IF NOT EXISTS dmax_items_series ON dmax_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS dmax_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    """Technical counters only; never URLs, tokens or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    db = provider_base.connect(root, 'dmax.sqlite3')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM dmax_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO dmax_state(name,value) VALUES(?,?)', (key, str(value)))


def _text(value, limit):
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


def _stamp(value):
    """ISO time ('2025-10-16T20:05:00Z') -> seconds since 1970, or None."""
    text = str(value or '')
    match = re.match(r'(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?', text)
    if not match:
        return None
    import calendar
    parts = [int(p or 0) for p in match.groups()]
    try:
        return float(calendar.timegm((parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], 0, 0, 0)))
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------- network

def _headers(site, token=None, realm=''):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'de-DE,de;q=0.9',
               'Origin': site, 'Referer': site + '/', 'X-Device-Info': DEVICE_INFO, 'X-Disco-Client': DISCO_CLIENT}
    if realm:
        headers['X-Disco-Params'] = 'realm=' + realm
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def _open(url, headers, data=None, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige DMAX-Anfrage')
    if data is not None:
        headers = {**headers, 'Content-Type': 'application/json'}
    req = urllib.request.Request(url, headers=headers, data=data, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('DMAX-Antwort zu groß')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('DMAX-Antwort zu groß')
    return raw


def _json(opener, url, headers, data=None):
    answer = json.loads(opener(url, headers, data).decode('utf-8'))
    if not isinstance(answer, dict):
        raise ValueError('Unerwartete DMAX-Antwort')
    return answer


def _api_error(exc):
    """Discovery answers errors as JSON:API ``errors[0].code``; returns the code or ''."""
    try:
        body = exc.read(65536) if hasattr(exc, 'read') else b''
        info = json.loads(body.decode('utf-8', 'replace') or '{}')
        return str(((info.get('errors') or [{}])[0] or {}).get('code') or '')[:80]
    except (ValueError, AttributeError, OSError, TypeError, IndexError):
        return ''


def _error(exc, code=''):
    status = getattr(exc, 'code', None)
    if code == 'access.denied.geoblocked' or status == 451:
        return 'DMAX, TLC und HGTV zeigen ihre Videos nur in Deutschland (Geosperre)'
    if status in (401, 403):
        return 'DMAX/TLC/HGTV verweigert den Zugriff (HTTP %d)' % status
    if status == 429:
        return 'DMAX/TLC/HGTV bremst die Abrufe (HTTP 429), später erneut versuchen'
    if status:
        return 'DMAX/TLC/HGTV antwortet mit HTTP %d' % status
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('DMAX/TLC/HGTV ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Katalog von DMAX, TLC und HGTV konnte nicht geladen werden'


def token(realm, opener=None, now=None, fresh=False):
    """Anonymous bearer token of one realm (memory only, never stored or logged)."""
    if realm not in REALMS:
        raise ValueError('Unbekannter Discovery-Bereich')
    now = time.time() if now is None else now
    cached = _TOKENS.get(realm)
    if cached and cached[0] > now and not fresh:
        return cached[1]
    site = REALMS[realm][4]
    query = urllib.parse.urlencode({'realm': realm, 'deviceId': uuid.uuid4().hex})
    answer = _json(opener or _open, DISCO + 'token?' + query, _headers(site, realm=realm))
    value = str((((answer.get('data') or {}).get('attributes') or {}).get('token')) or '')
    if not value or len(value) > 4096 or re.search(r'\s', value):
        raise ValueError('DMAX/TLC/HGTV gibt kein Zugangstoken aus')
    _TOKENS[realm] = (now + TOKEN_TTL, value)
    return value


# ---------------------------------------------------------------- parsing

def _https_image(value):
    url = str(value or '')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == 'https' and parts.hostname and not parts.port and not parts.username \
            and re.search(r'(?:^|\.)(?:disco-api\.com|enhanced\.live|dmax\.de|tlc\.de|hgtv\.com|discovery\.com|'
                          r'dnitv\.com|akamaized\.net|imgix\.net|cloudfront\.net)$', parts.hostname) \
            and not re.search(r'[\s<>"\'{}]', url) and len(url) < 600:
        return url
    return ''


def _find_image(node, depth=0):
    """First usable picture address in a CMS tile (field names differ between tile types)."""
    if depth > 5:
        return ''
    if isinstance(node, str):
        return _https_image(node) if re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', node, re.I) or 'images' in node else ''
    if isinstance(node, dict):
        for key in ('poster', 'image', 'images', 'metaMedia', 'media', 'thumbnailUrl', 'src', 'url', 'thumbnail',
                    'teaserImage', 'logo'):
            if key in node:
                found = _find_image(node[key], depth + 1)
                if found:
                    return found
        return ''
    if isinstance(node, list):
        for entry in node[:4]:
            found = _find_image(entry, depth + 1)
            if found:
                return found
    return ''


def programmes(answer):
    """Programmes of the CMS page "Sendungen": [(show id, title, picture, slug)]."""
    out, seen = [], set()
    blocks = answer.get('blocks') if isinstance(answer.get('blocks'), list) else []
    for block in blocks:
        items = block.get('items') if isinstance(block, dict) and isinstance(block.get('items'), list) else []
        for tile in items:
            if not isinstance(tile, dict):
                continue
            attrs = tile.get('attributes') if isinstance(tile.get('attributes'), dict) else {}
            show = str(attrs.get('showId') or tile.get('showId') or '')
            if not NUMBER.fullmatch(show) or show in seen:
                continue
            seen.add(show)
            slug = str(tile.get('slug') or attrs.get('slug') or '')
            if not SLUG.fullmatch(slug):
                link = str(tile.get('url') or tile.get('link') or tile.get('path') or '')
                match = re.search(r'/sendungen/([a-z0-9][a-z0-9\-]{0,160})', link)
                slug = match.group(1) if match else ''
            out.append((show, _text(tile.get('title') or attrs.get('title'), 200), _find_image(tile), slug))
    return out


def _blocks(answer):
    blocks = answer.get('blocks') if isinstance(answer.get('blocks'), list) else []
    return [b for b in blocks if isinstance(b, dict)]


def _offer_of_package(entry):
    package = entry.get('package')
    kind = str((package.get('type') if isinstance(package, dict) else package) or '').casefold()
    return 'free' if not kind or kind in FREE_PACKAGES else 'premium'


def show_page(answer, site, show_id, slug, now):
    """0.6.52: episodes of one programme from the website API (``seoSonicShowBlock.items``) and the programme's
    facts from ``showHeaderBlock``. Episodes outside their publishing window are left out."""
    key, channel, realm, _envs, base = site
    facts, rows = {}, []
    for block in _blocks(answer):
        name = str(block.get('type') or block.get('name') or block.get('blockType') or '')
        show = block.get('show') if isinstance(block.get('show'), dict) else None
        if show and not facts:
            facts = {'title': _text(show.get('title') or show.get('name'), 200),
                     'summary': _text(show.get('description') or show.get('teaser'), 1600),
                     'poster': _find_image(show) or _find_image(block), 'seasons': _int(show.get('seasons'), 0, 200)}
        items = block.get('items') if isinstance(block.get('items'), list) else []
        if 'showheader' in name.casefold() or not items:
            continue
        for entry in items:
            if not isinstance(entry, dict) or not NUMBER.fullmatch(str(entry.get('id') or '')):
                continue
            if str(entry.get('videoType') or 'EPISODE').upper() != 'EPISODE':
                continue
            if 'alternateId' not in entry and 'seasonNumber' not in entry and 'videoDuration' not in entry:
                continue                                  # a teaser of another block, not an episode
            meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
            title = _text(meta.get('name') or entry.get('title') or entry.get('name'), 200)
            if not title:
                continue
            start, end = _stamp(entry.get('publishStart')), _stamp(entry.get('publishEnd'))
            if (start is not None and start > now) or (end is not None and end <= now):
                continue
            alternate = str(entry.get('alternateId') or '')
            embed = str(meta.get('embedUrl') or '')
            match = re.fullmatch(r'(?:\{domain\}|https://(?:www\.)?(?:dmax\.de|tlc\.de|de\.hgtv\.com))'
                                 r'(/sendungen/[a-z0-9][a-z0-9\-]{0,160}/[a-z0-9][a-z0-9\-]{0,160})/?', embed)
            if match:
                web = base + match.group(1)
            elif SLUG.fullmatch(slug or '') and SLUG.fullmatch(alternate):
                web = '%s/sendungen/%s/%s' % (base, slug, alternate)
            else:
                web = '%s/sendungen/%s' % (base, slug) if SLUG.fullmatch(slug or '') else base + '/sendungen'
            published = start or _stamp(entry.get('airDate'))
            offer = _offer_of_package(entry)
            drm = 1 if entry.get('drmEnabled') is True else -1
            rows.append({'id': 'e.' + str(entry['id']), 'kind': 'episode', 'title': title, 'path': str(entry['id']),
                         'series_id': 's.%s.%s' % (realm, show_id), 'season': _int(entry.get('seasonNumber'), 0, 999),
                         'episode': _int(entry.get('episodeNumber'), 0, 9999),
                         'year': int(time.gmtime(published).tm_year) if published else None,
                         'duration': (_int(entry.get('videoDuration'), 1000, 24 * 3600 * 1000) or 0) // 1000 or None,
                         'rating': '', 'genre': ', '.join(g for g in (channel, CHANNEL_GENRE.get(realm, '')) if g),
                         'summary': _text(meta.get('description') or entry.get('description'), 1600),
                         'poster': _https_image(meta.get('thumbnailUrl')) or _find_image(entry), 'imdb_id': '',
                         'imdb_score': None, 'imdb_votes': None, 'number': None, 'category': channel,
                         'published': published, 'realm': realm, 'offer': offer,
                         'playable': 1 if PLAYBACK_CONFIRMED and offer == 'free' and drm != 1 else 0, 'drm': drm,
                         'web_url': web})
    return rows, facts


class Crawl:
    """Programmes of the three channels with all their episodes, with fixed request limits."""

    def __init__(self, opener, gap, waits=(), now=None):
        self.gap, self.waits = gap, tuple(waits)
        self.now = time.time() if now is None else float(now)
        raw = opener

        def patient(url, headers, data=None):
            for attempt in range(len(self.waits) + 1):
                try:
                    return raw(url, headers, data)
                except urllib.error.HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == len(self.waits):
                        raise
                    time.sleep(self.waits[attempt])
        self.opener = patient
        self.rows, self.series = {}, {}
        self.requests, self.errors, self.truncated = 0, [], False
        self.per_channel = {}
        self.unavailable = []             # channels whose catalogue the website API does not know (0.6.52)

    def _pause(self):
        self.requests += 1
        if self.requests % 100 == 0:
            _notify('dmax_sync_progress', requests=self.requests, episodes=len(self.rows), series=len(self.series),
                    errors=len(self.errors))
        if self.gap:
            time.sleep(self.gap)

    def _site_json(self, path, env, base):
        query = urllib.parse.urlencode({'include': 'default', 'filter[environment]': env, 'v': '2'})
        answer = _json(self.opener, AURORA + path + '?' + query, _headers(base))
        self._pause()
        return answer

    def channel(self, site):
        key, channel, realm, envs, base = site
        shows, env, failure = [], '', None
        for candidate in envs:
            try:
                shows = programmes(self._site_json('page/sendungen/', candidate, base))
            except urllib.error.HTTPError as exc:
                failure = exc
                if exc.code in (400, 404, 500):
                    continue                      # unknown environment name: try the next one
                break
            except Exception as exc:
                failure = exc
                break
            if shows:
                env, failure = candidate, None
                break
        if not env:
            unknown = failure is None or isinstance(failure, urllib.error.HTTPError) and failure.code in (400, 404, 500)
            if unknown and len(envs) > 1:
                # the website API knows no catalogue under the names tried: a note, not a failed run
                self.unavailable.append(channel)
                self.per_channel[key] = None
                return
            self.errors.append('%s: %s' % (channel, _error(failure) if failure else '%s nennt keine Sendungen' % channel))
            return
        if len(shows) > MAX_SHOWS:
            shows, self.truncated = shows[:MAX_SHOWS], True
        found = 0
        for show_id, title, picture, slug in shows:
            if len(self.rows) >= MAX_ITEMS:
                self.truncated = True
                break
            if not SLUG.fullmatch(slug or ''):
                continue                          # the programme page is addressed by its slug
            sid = 's.%s.%s' % (realm, show_id)
            try:
                rows, info = show_page(self._site_json('shows/%s/' % slug, env, base), site, show_id, slug, self.now)
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 404, 410):
                    continue                      # programme withdrawn
                self.errors.append('%s: %s' % (channel, _error(exc)))
                continue
            except Exception as exc:
                self.errors.append('%s: %s' % (channel, _error(exc)))
                continue
            for row in rows:
                self.rows.setdefault(row['id'], row)
            found += len(rows)
            self.series[sid] = {'id': sid, 'kind': 'series', 'title': title or info.get('title') or 'Ohne Titel', 'path': show_id,
                                'series_id': '', 'season': None, 'episode': None, 'year': None, 'duration': None,
                                'rating': '', 'genre': channel, 'summary': info.get('summary', ''),
                                'poster': picture or info.get('poster', ''),
                                'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
                                'category': channel, 'published': None, 'realm': realm, 'offer': 'free',
                                'playable': 1, 'drm': -1, 'web_url': '%s/sendungen/%s' % (base, slug)}
        self.per_channel[key] = found

    def run(self, sites=SITES):
        for site in sites:
            self.channel(site)

    def result(self):
        """Series rows (only programmes with episodes) and their episodes; a programme whose episodes are
        all paid or protected is marked like that, its genre names the channel plus the episodes' genres."""
        out, by_series = [], {}
        for row in self.rows.values():
            by_series.setdefault(row['series_id'], []).append(row)
        for sid, series in self.series.items():
            episodes = by_series.get(sid) or []
            if not episodes:
                continue
            genres = []
            for row in episodes:
                for name in row['genre'].split(', '):
                    if name and name not in genres:
                        genres.append(name)
            series['genre'] = ', '.join(genres[:6])
            if not any(r['offer'] == 'free' for r in episodes):
                series['offer'] = 'premium'
            if not any(r['playable'] for r in episodes):
                series['playable'] = 0
            if all(r['drm'] == 1 for r in episodes):
                series['drm'] = 1                  # every episode is copy protected: badge on the tile
            series['poster'] = series['poster'] or next((r['poster'] for r in episodes if r['poster']), '')
            years = [r['year'] for r in episodes if r['year']]
            series['year'] = min(years) if years else None
            out.append(series)
            out.extend(episodes)
        return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'published', 'realm',
          'offer', 'playable', 'drm', 'web_url')
_KEEP = ('drm',)


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS if f not in _KEEP)
    for item in items:
        db.execute('''INSERT INTO dmax_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,drm=MAX(dmax_items.drm,excluded.drm),seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item.get(f) for f in FIELDS], now, now))


def sync(root, opener=None, now=None, gap=None, waits=None, sites=SITES):
    """Read the three libraries. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('dmax_sync_started')
    try:
        crawl = Crawl(opener or _open, gap, RETRY_WAITS if opener is None else (waits or ()), now=now)
        crawl.run(sites)
        rows = crawl.result()
        if not any(r['kind'] == 'episode' for r in rows):
            raise ValueError(crawl.errors[0] if crawl.errors else 'DMAX, TLC und HGTV lieferten keine Videos')
        partial = crawl.truncated or bool(crawl.errors)
        message = ('Katalog nur teilweise geladen: %s (%d Fehler)' % (crawl.errors[0], len(crawl.errors)) if crawl.errors
                   else 'Katalog nur teilweise geladen' if partial else '')
        counts = {'movies': 0, 'series': sum(1 for r in rows if r['kind'] == 'series'),
                  'episodes': sum(1 for r in rows if r['kind'] == 'episode'), 'channels': 0}
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'), ('last_error', message),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600),
                                   ('requests', crawl.requests), ('per_channel', json.dumps(crawl.per_channel)),
                                   ('unavailable', json.dumps(crawl.unavailable)),
                                   *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('dmax_sync_completed', partial=partial, requests=crawl.requests, errors=len(crawl.errors),
                truncated=crawl.truncated, per_channel=crawl.per_channel, unavailable=crawl.unavailable,
                premium=sum(1 for r in rows if r['kind'] == 'episode' and r['offer'] != 'free'),
                protected=sum(1 for r in rows if r['kind'] == 'episode' and r['drm'] == 1), **counts)
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
        _notify('dmax_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute('SELECT * FROM dmax_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _badge(row):
    if row.get('offer') == 'premium':
        return 'Nur mit discovery+'
    if row.get('drm') == 1:
        return 'Kopiergeschützt'
    return ''


def _playable(row):
    if not PLAYBACK_CONFIRMED:
        return 0                                   # 0.6.52: opens on the channel's website, see the module text
    return 0 if row['kind'] == 'series' or row.get('drm') == 1 or row.get('offer') == 'premium' else 1


def _summary(root, row, reports=None):
    import dmax_enrichment
    report = (reports if reports is not None else dmax_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))


def episodes(root, series_id, now=None):
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige DMAX-Sendung')
    db = _connect(root)
    try:
        series = _row(db, series_id)
        if not series or series['kind'] != 'series':
            raise ValueError('Sendung nicht im Katalog; bitte Katalog neu laden')
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM dmax_items WHERE kind='episode' AND series_id=? AND seen>=? "
            "ORDER BY season IS NULL, season, episode IS NULL, episode, published, title", (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = _playable(row)
        row['badge'] = _badge(row)
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': ''}


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of programmes (series). The three channels have no films of their own."""
    import dmax_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    if view != 'series':
        return {'items': [], 'total': 0, 'offset': offset, 'view': view, 'genre_counts': []}
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = "FROM dmax_items WHERE kind='series' AND seen>=?"
        args = [last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR summary LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
        counts = dict(db.execute("SELECT series_id,COUNT(*) FROM dmax_items WHERE kind='episode' AND seen>=? "
                                 "GROUP BY series_id", (last,)).fetchall())
    finally:
        db.close()
    reports = dmax_enrichment.all_cached(root)
    for row in rows:
        row['episodes'] = counts.get(row['id'], 0)
        row['playable'] = 0
        row['badge'] = _badge(row)
        row.update(_summary(root, row, reports))
    facets = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, 'series')]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': facets}


def item(root, item_id):
    import dmax_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger DMAX-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        if not row:
            raise ValueError('Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    row['playable'] = _playable(row)
    row['badge'] = _badge(row)
    report = dmax_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or ''},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protected = db.execute("SELECT COUNT(*) FROM dmax_items WHERE kind='episode' AND seen>=? AND (drm=1 OR offer!='free')",
                               (last,)).fetchone()[0]
        try:
            per_channel = json.loads(_get(db, 'per_channel', '{}') or '{}')
        except ValueError:
            per_channel = {}
        try:
            unavailable = [str(c)[:20] for c in json.loads(_get(db, 'unavailable', '[]') or '[]')][:3]
        except (ValueError, TypeError):
            unavailable = []
        note = ('%s: Katalog über die Website derzeit nicht abrufbar' % ' und '.join(unavailable)) if unavailable else ''
        note = (note + '. ' if note else '') + 'Folgen öffnen vorerst beim Sender' if not PLAYBACK_CONFIRMED else note
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0), 'last_success': last,
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'channels': 0, 'protected': protected,
            'requests': _int(_get(db, 'requests', '0')) or 0,
            'per_channel': per_channel if isinstance(per_channel, dict) else {}, 'unavailable': unavailable,
            'note': note}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='dmax_catalog_sync').start()
    return True


def should_sync(root, now=None):
    return provider_base.catalog_due(root, sys.modules[__name__], state(root), now)


def loop(root, stop):
    provider_base.loop(root, stop, KEY, sys.modules[__name__])


# ---------------------------------------------------------------- playback

def _mark_drm(root, item_id, value):
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE dmax_items SET drm=? WHERE id=?', (int(value), item_id))
    finally:
        db.close()


def streams(answer):
    """[(type, url, protected)] from ``data.attributes.streaming`` (list in v3, dict in older answers)."""
    raw = (((answer.get('data') or {}).get('attributes') or {}).get('streaming')) if isinstance(answer, dict) else None
    entries = []
    if isinstance(raw, dict):
        entries = [{'type': k, **(v if isinstance(v, dict) else {})} for k, v in raw.items()]
    elif isinstance(raw, list):
        entries = [e for e in raw if isinstance(e, dict)]
    out = []
    for entry in entries:
        url = str(entry.get('url') or '')
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.port not in (None, 443):
            continue
        protection = entry.get('protection') if isinstance(entry.get('protection'), dict) else {}
        protected = bool(protection.get('drmEnabled') or protection.get('schemes')) \
            or bool(re.search(r'(?i)fairplay|widevine|playready|cenc', url))
        out.append((str(entry.get('type') or ''), url, protected))
    # HLS first (hls.js in the browser, ffmpeg otherwise), DASH last
    return sorted(out, key=lambda s: (s[2], 0 if s[0] == 'hls' or '.m3u8' in s[1] else 1))


def playback(realm, video_id, opener=None, now=None):
    if realm not in REALMS or not NUMBER.fullmatch(str(video_id or '')):
        raise ValueError('Ungültiges DMAX-Video')
    opener = opener or _open
    site = REALMS[realm][4]
    body = json.dumps({'deviceInfo': {'adBlocker': False, 'drmSupported': False, 'hdrCapabilities': ['SDR'],
                                      'hwDecodingCapabilities': [], 'soundCapabilities': ['STEREO']},
                       'videoId': str(video_id), 'wisteriaProperties': {}}).encode()
    for attempt in (0, 1):
        bearer = token(realm, opener, now, fresh=bool(attempt))
        try:
            return _json(opener, DISCO + 'playback/v3/videoPlaybackInfo', _headers(site, bearer, realm), body)
        except urllib.error.HTTPError as exc:
            code = _api_error(exc)
            if code == 'invalid.token' and not attempt:
                continue
            if code == 'access.denied.missingpackage':
                raise ValueError('Diese Folge gibt es nur mit discovery+; bitte beim Sender ansehen.') from None
            raise ValueError(_error(exc, code)) from None
    raise ValueError('DMAX/TLC/HGTV gibt kein Zugangstoken aus')


def _player_title(row, parent):
    series = (parent or {}).get('title') or REALMS.get(row.get('realm') or '', ('', 'DMAX'))[1]
    if row['season'] is not None and row['episode'] is not None:
        return '%s · S%02dE%02d · %s' % (series, row['season'], row['episode'], row['title'])
    return '%s · %s' % (series, row['title'])


def play_source(root, item_id, opener=None, check=None, now=None):
    """Source for streaming.plan: HLS checked by hls_guard, played with hls.js or ffmpeg."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger DMAX-Titel')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row:
        raise ValueError('Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Sendung auswählen')
    if not PLAYBACK_CONFIRMED:
        raise ValueError('%s-Folgen laufen vorerst nur auf der Website des Senders; bitte „Beim Sender ansehen“ wählen.'
                         % REALMS.get(row['realm'], ('', 'DMAX'))[1])
    if row['offer'] == 'premium':
        raise ValueError('Diese Folge gibt es nur mit discovery+; bitte beim Sender ansehen.')
    if row['drm'] == 1:
        raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
    channel = REALMS.get(row['realm'], ('', 'DMAX'))[1]
    cached = _SOURCES.get(item_id)
    if cached and cached[0] > now:
        url = cached[1]
    else:
        try:
            answer = playback(row['realm'], row['path'], opener, now)
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(_error(exc)) from None
        found = streams(answer)
        if not found:
            raise ValueError('%s nennt für diese Folge keinen Stream.' % channel)
        kind, url, protected = found[0]
        if protected:
            _mark_drm(root, item_id, 1)
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        if kind == 'hls' or '.m3u8' in url:
            try:
                (check or hls_guard.check)(url)
            except hls_guard.DrmProtected:
                _mark_drm(root, item_id, 1)
                raise
        if row['drm'] != 0:
            _mark_drm(root, item_id, 0)
        _SOURCES[item_id] = (now + SOURCE_TTL, url)
    return {'kind': 'url', 'url': url, 'hls': '.m3u8' in url or not url.endswith('.mpd'), 'title': _player_title(row, parent),
            'provider': KEY, 'quality': '%s (kostenlos mit Werbung)' % channel, 'duration': row['duration'] or 0, 'live': False}
