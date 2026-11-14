"""Pluto TV: public catalogue (films, series with episodes, live channels) and playback.

Pluto TV is free and ad-supported. MediathekAtlas uses the same anonymous session the
website starts for every visitor (boot.pluto.tv, no account, no cookies) and plays the
official HLS streams in its own player, adverts included. Films and episodes may be kept
offline for 20 days (pluto_downloads, shared download queue); there is no ad removal and no geo workaround: Pluto decides by IP which country catalogue is served.

Endpoints are hard-coded and every answer is size-limited. Session tokens are kept in
memory only and never written to the database, logs or the diagnosis export.
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
import uuid
from pathlib import Path

import portal_reference

BOOT_URL = 'https://boot.pluto.tv/v4/start'
VOD_URL = 'https://service-vod.clusters.pluto.tv/v4/vod'
CHANNELS_URL = 'https://service-channels.clusters.pluto.tv/v2/guide/channels'
API_HOSTS = frozenset({'boot.pluto.tv', 'service-vod.clusters.pluto.tv', 'service-channels.clusters.pluto.tv'})
MAX_ANSWER = 48 * 1024 * 1024
MAX_ITEMS = 40000
SERIES_TTL = 6 * 3600
SOURCE_TTL = 600
REQUEST_GAP = 0.4
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
VALID_ID = re.compile(r'[A-Za-z0-9_\-]{6,64}')
KINDS = ('movie', 'series', 'episode', 'channel')

_SESSION = {'token': '', 'expires': 0.0, 'stitcher': '', 'params': ''}
_SESSION_LOCK = threading.Lock()
_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pluto_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, slug TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, number INTEGER,
  year INTEGER, duration INTEGER, rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '', poster TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS pluto_items_kind ON pluto_items(kind, seen);
CREATE INDEX IF NOT EXISTS pluto_items_series ON pluto_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS pluto_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
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
    path = root / 'pluto.sqlite3'
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
    row = db.execute('SELECT value FROM pluto_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO pluto_state(name,value) VALUES(?,?)', (key, str(value)))


def client_id(root):
    """Random installation id for the anonymous Pluto session (like a browser's device id)."""
    db = _connect(root)
    try:
        with db:
            value = _get(db, 'client_id')
            if not re.fullmatch(r'[0-9a-f\-]{36}', value):
                value = str(uuid.uuid4())
                _set(db, 'client_id', value)
        return value
    finally:
        db.close()


# ---------------------------------------------------------------- network

def _fetch_json(url, token=''):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS:
        raise ValueError('Unerwartete Pluto-Adresse')
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > MAX_ANSWER:
            raise ValueError('Pluto-Antwort zu groß')
        data = response.read(MAX_ANSWER + 1)
    if len(data) > MAX_ANSWER:
        raise ValueError('Pluto-Antwort zu groß')
    return json.loads(data.decode('utf-8'))


def _stitcher(value):
    parts = urllib.parse.urlsplit(str(value or ''))
    if parts.scheme != 'https' or not parts.hostname or not parts.hostname.endswith('.pluto.tv') \
            or parts.username or parts.password or parts.port:
        raise ValueError('Pluto lieferte keinen gültigen Wiedergabeserver')
    return 'https://' + parts.hostname


def session(root, fetch=None, now=None, force=False):
    """Anonymous website session (token, stitcher server, stitcher parameters)."""
    now = time.time() if now is None else now
    with _SESSION_LOCK:
        if not force and _SESSION['token'] and _SESSION['expires'] > now + 60:
            return dict(_SESSION)
        query = urllib.parse.urlencode({
            'appName': 'web', 'appVersion': '9.10.0', 'deviceVersion': '17.0', 'deviceModel': 'web',
            'deviceMake': 'safari', 'deviceType': 'web', 'clientID': client_id(root),
            'clientModelNumber': '1.0.0', 'serverSideAds': 'true'})
        data = (fetch or _fetch_json)(BOOT_URL + '?' + query)
        token = data.get('sessionToken') if isinstance(data, dict) else None
        if not isinstance(token, str) or not 20 <= len(token) <= 8000:
            raise ValueError('Pluto lieferte keine Sitzung')
        servers = data.get('servers') or {}
        params = data.get('stitcherParams') or ''
        if not isinstance(params, str) or len(params) > 4000:
            params = ''
        try:
            refresh = int(data.get('refreshInSec') or 3600)
        except (TypeError, ValueError):
            refresh = 3600
        _SESSION.update(token=token, expires=now + max(300, min(refresh, 6 * 3600)),
                        stitcher=_stitcher(servers.get('stitcher') if isinstance(servers, dict) else ''),
                        params=params)
        return dict(_SESSION)


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


def _seconds(value):
    """Pluto durations are milliseconds."""
    number = _int(value, 1)
    if number is None:
        return None
    seconds = number // 1000 if number > 100000 else number
    return seconds if 0 < seconds <= 172800 else None


def _image(node, prefer=('347:500', '2:3', '16:9', '4:3', '1:1')):
    covers = node.get('covers') if isinstance(node.get('covers'), list) else []
    images = node.get('images') if isinstance(node.get('images'), list) else []
    best = ''
    for want in prefer:
        for c in covers:
            if isinstance(c, dict) and c.get('aspectRatio') == want and isinstance(c.get('url'), str):
                best = c['url']
                break
        if best:
            break
    if not best:
        for c in covers + images:
            if isinstance(c, dict) and isinstance(c.get('url'), str):
                best = c['url']
                if c.get('type') in ('colorLogoPNG', 'poster', 'featuredImage'):
                    break
    for key in ('colorLogoPNG', 'logo', 'featuredImage', 'poster'):
        if not best and isinstance(node.get(key), dict) and isinstance(node[key].get('path'), str):
            best = node[key]['path']
    parts = urllib.parse.urlsplit(best)
    if parts.scheme != 'https' or not parts.hostname or len(best) > 800 or not (
            parts.hostname.endswith('.pluto.tv') or parts.hostname.endswith('.cloudfront.net')
            or parts.hostname.endswith('.plutotv.net')):
        return ''
    return best


def _path(node):
    """Stitcher path of a playable item, e.g. /stitch/hls/episode/<id>/master.m3u8."""
    stitched = node.get('stitched') if isinstance(node.get('stitched'), dict) else {}
    candidates = []
    if isinstance(stitched.get('path'), str):
        candidates.append(stitched['path'])
    for u in stitched.get('urls') or []:
        if isinstance(u, dict) and u.get('type') in (None, 'hls') and isinstance(u.get('url'), str):
            candidates.append(urllib.parse.urlsplit(u['url']).path)
    for value in candidates:
        value = re.sub(r'^/v2(?=/stitch/)', '', value)
        if re.fullmatch(r'/stitch/hls/(?:episode|channel)/[A-Za-z0-9_\-]{6,64}/master\.m3u8', value):
            return value
    return ''


def _year(node):
    for key in ('year', 'productionYear', 'releaseYear'):
        y = _int(node.get(key), 1880, 2100)
        if y:
            return y
    match = re.search(r'-((?:19|20)\d\d)-\d+-\d+(?:-[a-z0-9]+)?$', str(node.get('slug') or ''))
    return int(match.group(1)) if match else None


def item_from(node, kind, category='', series_id='', season=None):
    if not isinstance(node, dict):
        return None
    item_id = str(node.get('_id') or node.get('id') or '')
    title = _text(node.get('name') or node.get('title'), 200)
    if not VALID_ID.fullmatch(item_id) or len(title) < 1:
        return None
    if kind not in KINDS:
        return None
    path = _path(node)
    if not path and kind in ('movie', 'episode'):
        path = '/stitch/hls/episode/%s/master.m3u8' % item_id
    if not path and kind == 'channel':
        path = '/stitch/hls/channel/%s/master.m3u8' % item_id
    genre = node.get('genre')
    if isinstance(genre, list):
        genre = ', '.join(str(g) for g in genre[:6])
    return {
        'id': item_id, 'kind': kind, 'title': title, 'slug': _text(node.get('slug'), 200),
        'series_id': series_id, 'season': season if season is not None else _int(node.get('season'), 0, 999),
        'episode': _int(node.get('number') if kind == 'episode' else None, 0, 9999),
        'number': _int(node.get('number') if kind == 'channel' else None, 0, 100000),
        'year': _year(node), 'duration': _seconds(node.get('originalContentDuration') or node.get('duration')),  # without ad breaks (0.5.43)
        'rating': _text(node.get('rating'), 20), 'genre': _text(genre, 120),
        'summary': _text(node.get('description') or node.get('summary'), 1200),
        'poster': _image(node), 'path': path if kind != 'series' else '',
        'category': _text(category, 120)}


def parse_vod(data):
    """Films and series from /v4/vod/categories (items inside every category)."""
    cats = data.get('categories') if isinstance(data, dict) else data
    out = {}
    for cat in (cats or [])[:2000]:
        if not isinstance(cat, dict):
            continue
        name = cat.get('name') or ''
        for node in (cat.get('items') or [])[:MAX_ITEMS]:
            if not isinstance(node, dict):
                continue
            kind = 'series' if node.get('type') == 'series' else 'movie' if node.get('type') in ('movie', None) else ''
            item = item_from(node, kind, name) if kind else None
            if item and item['id'] not in out:
                out[item['id']] = item
        if len(out) > MAX_ITEMS:
            break
    return list(out.values())


def parse_channels(data):
    nodes = data.get('data') if isinstance(data, dict) else data
    out = {}
    for node in (nodes or [])[:5000]:
        if not isinstance(node, dict):
            continue
        cat = node.get('category') or ''
        if isinstance(node.get('categoryIDs'), list) and not cat:
            cat = ''
        item = item_from(node, 'channel', cat)
        if item:
            out[item['id']] = item
    return list(out.values())


def parse_seasons(data, series_id):
    seasons = data.get('seasons') if isinstance(data, dict) else None
    out = []
    for season in (seasons or [])[:200]:
        if not isinstance(season, dict):
            continue
        number = _int(season.get('number'), 0, 999)
        for node in (season.get('episodes') or [])[:2000]:
            item = item_from(node, 'episode', '', series_id, number)
            if item:
                if item['season'] is None:
                    item['season'] = _int(node.get('season'), 0, 999)
                out.append(item)
    return out


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'slug', 'series_id', 'season', 'episode', 'number', 'year', 'duration',
          'rating', 'genre', 'summary', 'poster', 'path', 'category')


def _store(db, items, now):
    for item in items:
        db.execute('''INSERT INTO pluto_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)),
                      ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def sync(root, fetch=None, now=None, gap=None):
    """Load films, series and live channels. Rows from earlier runs stay, but only titles
    seen in the latest successful run are listed (Pluto rotates its catalogue)."""
    now = time.time() if now is None else float(now)
    fetch = fetch or _fetch_json
    gap = (REQUEST_GAP if fetch is _fetch_json else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('pluto_sync_started')
    try:
        s = session(root, fetch, now, force=True)
        vod = parse_vod(fetch(VOD_URL + '/categories?' + urllib.parse.urlencode({
            'includeItems': 'true', 'includeCategoryFields': 'iconSvg', 'itemOffset': '10000',
            'offset': '1000', 'page': '1', 'sort': 'number:asc'}), s['token']))
        if gap:
            time.sleep(gap)
        channel_error = ''
        try:
            channels = parse_channels(fetch(CHANNELS_URL + '?' + urllib.parse.urlencode({
                'channelIds': '', 'offset': '0', 'limit': '1000', 'sort': 'number:asc'}), s['token']))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            channels, channel_error = [], _error(exc)
        if not vod and not channels:
            raise ValueError('Pluto lieferte keinen Katalog (Land nicht unterstützt?)')
        db = _connect(root)
        try:
            with db:
                _store(db, vod + channels, now)
                counts = {k: sum(1 for i in vod + channels if i['kind'] == k) for k in ('movie', 'series', 'channel')}
                # Live channels failed: keep the previous stock (incl. channels) visible.
                previous = float(_get(db, 'last_success', '0') or 0)
                for key, value in [('last_success', previous if channel_error and previous else now), ('last_loaded', now), ('last_result', 'partial' if channel_error else 'complete'),
                                   ('last_error', channel_error), ('movies', counts['movie']),
                                   ('series', counts['series']), ('channels', counts['channel']),
                                   ('next_attempt', now + 24 * 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('pluto_sync_completed', **counts, partial=bool(channel_error))
        return {'ok': True, **counts, 'partial': bool(channel_error)}
    except Exception as exc:  # network, JSON or format problems are reported, the stock stays
        message = _error(exc)
        db = _connect(root)
        try:
            with db:
                for key, value in [('last_result', 'failed'), ('last_error', message),
                                   ('last_http_status', getattr(exc, 'code', 0) or 0),
                                   ('next_attempt', now + 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        import netcheck
        _notify('pluto_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return 'Pluto TV verweigert den Zugriff (HTTP %d) – evtl. in diesem Land nicht verfügbar' % code
    if code:
        return 'Pluto TV antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Pluto TV ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Pluto-Katalog konnte nicht geladen werden'


def episodes(root, series_id, fetch=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')):
        raise ValueError('Ungültige Pluto-Serie')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        series = db.execute("SELECT title,genre FROM pluto_items WHERE id=? AND kind='series'", (series_id,)).fetchone()
        if not series:
            raise ValueError('Pluto-Serie nicht im Katalog; bitte Katalog neu laden')
        checked = float(_get(db, 'series_checked:' + series_id, '0') or 0)
        error = ''
        if not checked or now - checked > SERIES_TTL:
            try:
                s = session(root, fetch, now)
                found = parse_seasons((fetch or _fetch_json)(
                    VOD_URL + '/series/%s/seasons?offset=1000&page=1' % series_id, s['token']), series_id)
                with db:
                    _store(db, found, now)
                    _set(db, 'series_checked:' + series_id, now)
            except Exception as exc:
                error = _error(exc)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM pluto_items WHERE kind='episode' AND series_id=? ORDER BY season,episode,title",
            (series_id,))]
        import portal_reference, pluto_enrichment
        extra = portal_reference.summary(series['genre'],
                                         pluto_enrichment.all_cached(root).get(series_id))
        for row in rows:
            row.update(extra)
        return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': error}
    finally:
        db.close()


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films, series or live channels. Films and series carry the same canonical
    categories and reference ratings as the Mediathek catalogue (portal_reference)."""
    import portal_reference, pluto_enrichment
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    # 'all': the merged dashboard index (unified_index.py) reads every row once and pages itself.
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM pluto_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR category LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
    finally:
        db.close()
    if kind == 'channel':
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
                'genre_counts': []}
    reports = pluto_enrichment.all_cached(root)
    for row in rows:
        row.update(portal_reference.summary(row.get('genre'), reports.get(row['id']), age=portal_reference.age_of(row)))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre)
            and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    """All live channels of the latest successful catalogue run (for the Live-TV tab, 0.5.50)."""
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        return [dict(r) for r in db.execute(
            "SELECT id,title,number,genre,category,summary,poster FROM pluto_items "
            "WHERE kind='channel' AND seen>=? ORDER BY number,title", (last,))]
    finally:
        db.close()


def item(root, item_id):
    """Detail view of one film, series or episode: catalogue row, series, reference report."""
    import portal_reference, pluto_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Pluto-Titel')
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM pluto_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise ValueError('Pluto-Titel nicht im Katalog; bitte Katalog neu laden')
        row = dict(row)
        parent = db.execute('SELECT * FROM pluto_items WHERE id=?', (row['series_id'],)).fetchone() \
            if row.get('series_id') else None
        parent = dict(parent) if parent else None
    finally:
        db.close()
    report = pluto_enrichment.cached(root, item_id) if row['kind'] != 'channel' else dict(pluto_enrichment.UNCHECKED)
    genre = row.get('genre') or (parent or {}).get('genre')
    return {'item': {**row, **portal_reference.summary(genre, report, age=portal_reference.age_of(row)),
                     'poster': row.get('poster') or (parent or {}).get('poster') or ''},
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
            'channels': _int(_get(db, 'channels', '0')) or 0,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM pluto_items WHERE kind='episode'").fetchone()[0]}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='pluto_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:pluto'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or portal_reference.retry_after_update(root, sys.modules[__name__], current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def stream_url(s, path):
    """Official stitcher address (HLS master playlist incl. adverts) for one item."""
    if not re.fullmatch(r'/stitch/hls/(?:episode|channel)/[A-Za-z0-9_\-]{6,64}/master\.m3u8', path or ''):
        raise ValueError('Für diesen Pluto-Titel ist keine Wiedergabe hinterlegt')
    params = urllib.parse.parse_qsl(s.get('params') or '', keep_blank_values=True)
    params = [(k, v) for k, v in params if k not in ('jwt', 'masterJWTPassthrough')]
    params += [('jwt', s['token']), ('masterJWTPassthrough', 'true')]
    return _stitcher(s['stitcher']) + '/v2' + path + '?' + urllib.parse.urlencode(params)


def play_source(root, item_id, fetch=None, now=None):
    """Source for streaming.plan: always HLS, so the player uses native HLS or ffmpeg."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Pluto-Titel')
    now = time.time() if now is None else now
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM pluto_items WHERE id=?', (item_id,)).fetchone()
    finally:
        db.close()
    if not row:
        raise ValueError('Pluto-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    cached = _SOURCES.get(item_id)
    if cached and cached[0] > now:
        url = cached[1]
    else:
        try:
            url = stream_url(session(root, fetch, now), row['path'])
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(_error(exc)) from None
        _SOURCES[item_id] = (now + SOURCE_TTL, url)
    title = row['title']
    if row['kind'] == 'episode':
        series = ''
        db = _connect(root)
        try:
            parent = db.execute('SELECT title FROM pluto_items WHERE id=?', (row['series_id'],)).fetchone()
            series = parent['title'] if parent else ''
        finally:
            db.close()
        if row['season'] is not None and row['episode'] is not None:
            title = '%s · S%02dE%02d · %s' % (series or 'Serie', row['season'], row['episode'], row['title'])
    elif row['year']:
        title += ' (%s)' % row['year']
    return {'kind': 'url', 'url': url, 'hls': True, 'quality': 'Pluto TV (mit Werbung)', 'title': title,
            'duration': 0 if row['kind'] == 'channel' else row['duration'] or 0,
            'provider': 'pluto', 'live': row['kind'] == 'channel'}
