"""Rakuten TV: the free films, series and live channels of rakuten.tv (0.5.51).

Björn (12.11.2026): connect rakuten.tv "auch hier möchte ich auf die free filme und serien
zugreifen, diese bei bedarf offline schauen können … angepasste ansicht im format, welches sich
etabliert hat". Only the free offer is read ("Kostenlos mit Anzeigen", purchase type AVOD, and the
free live channels); rentals, purchases and subscriptions are ignored.

Formats as recorded in Björn's HAR (12.11.2026, rakuten.tv/de in Chrome):

* Catalogue: public JSON API of the website, gizmo.rakuten.tv/v3, no account, no cookies, with
  ``classification_id=307&device_identifier=web&locale=de&market_code=de``. All free films are the
  list ``free-all-movies`` (1,899 titles), all free series ``free-all-tv-shows`` (120). Page 1:
  ``lists/<id>?contents[per_page]=24`` (list head + ``contents.data``), further pages
  ``lists/<id>/contents?page=N&per_page=24`` (``data`` + ``meta.pagination.total_pages``).
* Series: ``tv_shows/<id>/current_season`` -> season id, ``seasons/<id>`` -> ``episodes`` and
  ``other_seasons``.
* Live: ``live_channels?page=N&per_page=25`` with the programme of the coming hours (160 channels).
* Streams: ``POST avod/streamings``. Free films and episodes are delivered ONLY as
  ``web:DASH-CENC:WVM`` with a Widevine licence (prod-widevine.rakuten.tv; the title pages list
  only DASH-CENC and PlayReady). MediathekAtlas does not circumvent copy protection, so films and
  episodes get catalogue, title page and "Bei Rakuten TV ansehen", but no player and no offline
  copy. Live channels are ``web:HLS-NONE:NONE``: ordinary HLS with AES-128 (key format identity,
  as Pluto TV); they play in the MediathekAtlas player, live only (not storable).

Reference checks (IMDb/TVDB/TMDB/OMDb/Wikidata) use the shared portal_enrichment engine with
reference_share, so films already checked on another platform are not looked up again. Titles,
tokens and URLs never go to logs or the diagnosis export.
"""
from __future__ import annotations
import sys

import datetime
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

API = 'https://gizmo.rakuten.tv/v3/'
SITE = 'https://www.rakuten.tv'
MARKET, LOCALE = 'de', 'de'
CLASSIFICATION_ID = '307'          # Germany, as sent by the website
DEVICE = 'web'
FREE_LISTS = (('free-all-movies', 'movie'), ('free-all-tv-shows', 'series'))
LIVE_PLAYER = 'web:HLS-NONE:NONE'  # the website's own profile for live channels
MAX_ANSWER = 16 * 1024 * 1024
MAX_STREAM_URL = 16000             # advert parameters make live addresses ~2,000 characters long
MAX_ITEMS = 20000
PER_PAGE = 24                      # as the website
LIVE_PER_PAGE = 25
MAX_PAGES = 200
REQUEST_GAP = 1.0
SERIES_TTL = 6 * 3600
SOURCE_TTL = 120
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
SLUG = r'[a-z0-9][a-z0-9\-]{0,150}'
VALID_ID = re.compile(r'[msec]\.' + SLUG)     # m.<film>, s.<series>, e.<episode>, c.<live channel>
VALID_SLUG = re.compile(SLUG)
KIND_PREFIX = {'movie': 'm', 'series': 's', 'episode': 'e', 'channel': 'c'}
TYPE_KIND = {'movies': 'movie', 'tv_shows': 'series', 'episodes': 'episode', 'live_channels': 'channel'}
IMAGE_HOSTS = ('.rakuten.tv', '.wuaki.tv')
DRM_NOTE = ('Rakuten TV liefert kostenlose Filme und Folgen nur mit Kopierschutz (Widevine/PlayReady) aus. '
            'MediathekAtlas umgeht ihn nicht: Abspielen und Offline-Speichern sind dafür nicht möglich, '
            'bitte bei Rakuten TV ansehen.')

_SOURCES = {}
_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_DEVICE_UID = str(uuid.uuid4())    # per app start, in memory only (the website sends one too)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS rakuten_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '',
  playable INTEGER NOT NULL DEFAULT 0, drm INTEGER NOT NULL DEFAULT 1, web_url TEXT NOT NULL DEFAULT '',
  seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS rakuten_items_kind ON rakuten_items(kind, seen);
CREATE INDEX IF NOT EXISTS rakuten_items_series ON rakuten_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS rakuten_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
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
    path = root / 'rakuten.sqlite3'
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
    row = db.execute('SELECT value FROM rakuten_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO rakuten_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def params():
    return {'classification_id': CLASSIFICATION_ID, 'device_identifier': DEVICE, 'locale': LOCALE,
            'market_code': MARKET}


def _request(path, query=None, body=None):
    """One request to the fixed Rakuten API host; only known relative API paths are accepted."""
    if not re.fullmatch(r'[a-z_]+(?:/[a-z0-9_\-]{1,160}){0,3}', path):
        raise ValueError('Ungültige Rakuten-Anfrage')
    url = API + path + '?' + urllib.parse.urlencode({**params(), **(query or {})})
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method='POST' if data is not None else 'GET', headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Content-Type': 'application/json',
        'Origin': SITE, 'Referer': SITE + '/'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > MAX_ANSWER:
            raise ValueError('Rakuten-Antwort zu groß')
        raw = response.read(MAX_ANSWER + 1)
    if len(raw) > MAX_ANSWER:
        raise ValueError('Rakuten-Antwort zu groß')
    return json.loads(raw.decode('utf-8'))


def _data(answer):
    """``data`` of an answer; Rakuten errors look like {"errors":[{"code":…,"message":…}]}."""
    if not isinstance(answer, dict):
        raise ValueError('Rakuten TV lieferte kein gültiges Ergebnis')
    errors = answer.get('errors')
    if errors and not answer.get('data'):
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        raise ValueError('Rakuten TV lehnte die Abfrage ab: ' + _text(first.get('message') or first.get('code') or 'Fehler', 160))
    return answer.get('data')


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403):
        return 'Rakuten TV verweigert den Zugriff (HTTP %d)' % code
    if code:
        return 'Rakuten TV antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('Rakuten TV ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Rakuten-TV-Katalog konnte nicht geladen werden'


def _http_detail(exc):
    """_error plus Rakuten's own error text from the answer body, if it sends one (0.5.59)."""
    text = _error(exc)
    try:
        answer = json.loads(exc.read(65536).decode('utf-8', 'replace'))
        errors = answer.get('errors') if isinstance(answer, dict) else None
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        detail = first.get('message') or first.get('code')
        if detail:
            text += ': ' + _text(detail, 160)
    except Exception:
        pass
    return text


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


def image(value):
    """Artwork address on Rakuten's own image hosts (images-N.rakuten.tv, https only)."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.port or parts.username or len(value) > 600 \
            or not any(host.endswith(h) for h in IMAGE_HOSTS) or re.search(r'[\s<>"\']', value):
        return ''
    return value


def _images(node, *keys):
    images = node.get('images') if isinstance(node.get('images'), dict) else {}
    return next((image(images.get(k)) for k in keys if image(images.get(k))), '')


def web_url(kind, slug):
    if not VALID_SLUG.fullmatch(str(slug or '')):
        return ''
    section = {'movie': 'movies', 'series': 'tv_shows', 'episode': 'tv_shows', 'channel': 'player/live_channels'}[kind]
    return '%s/%s/%s/%s' % (SITE, MARKET, section, slug)


def _names(values, limit=12):
    out = []
    for v in values if isinstance(values, list) else []:
        name = _text(v.get('name') if isinstance(v, dict) else v, 60)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _imdb(node):
    """IMDb score Rakuten itself shows (highlighted_score/scores with site IMDb) and the id from its link."""
    scores = [node.get('highlighted_score')] + list(node.get('scores') or [])
    for s in scores:
        if isinstance(s, dict) and str((s.get('site') or {}).get('name') or '').lower() == 'imdb':
            match = re.search(r'imdb\.com/title/(tt\d{5,10})', str(s.get('href') or ''))
            return (_float(s.get('score'), 0, 10), _int(s.get('amount_of_votes'), 0), match.group(1) if match else '')
    return None, None, ''


def _free(node):
    labels = node.get('labels') if isinstance(node.get('labels'), dict) else {}
    kinds = {str((p or {}).get('kind') or '').lower() for p in labels.get('purchase_types') or [] if isinstance(p, dict)}
    return not kinds or 'avod' in kinds


def _rating(node):
    c = node.get('classification')
    return _text(c.get('name'), 20) if isinstance(c, dict) else ''


def item_from(node):
    """Free film or series from a list entry; None for anything else."""
    if not isinstance(node, dict):
        return None
    kind = TYPE_KIND.get(str(node.get('type') or ''))
    slug = str(node.get('id') or '')
    title = _text(node.get('title'), 200)
    if kind not in ('movie', 'series') or not title or not VALID_SLUG.fullmatch(slug) or not _free(node):
        return None
    score, votes, imdb_id = _imdb(node)
    duration = _int(node.get('duration'), 1, 1440)
    return {
        'id': KIND_PREFIX[kind] + '.' + slug, 'kind': kind, 'title': title, 'path': slug, 'series_id': '',
        'season': None, 'episode': None, 'year': _int(node.get('year'), 1880, 2100),
        'duration': duration * 60 if duration and kind == 'movie' else None, 'rating': _rating(node),
        'genre': ', '.join(_names(node.get('genres'))),
        'summary': _text(node.get('short_plot') or node.get('plot'), 1600),
        'poster': _images(node, 'artwork', 'standard_artwork', 'snapshot'),
        'imdb_id': imdb_id, 'imdb_score': score, 'imdb_votes': votes, 'number': None, 'category': '',
        'playable': 0, 'drm': 1, 'web_url': web_url(kind, slug)}


def channel_from(node, now=None):
    """Free live channel with the programme running now."""
    if not isinstance(node, dict) or node.get('type') != 'live_channels':
        return None
    slug = str(node.get('id') or '')
    title = _text(node.get('title'), 200)
    if not title or not VALID_SLUG.fullmatch(slug):
        return None
    labels = node.get('labels') if isinstance(node.get('labels'), dict) else {}
    tags = _names(labels.get('tags'))
    current = ''
    stamp = time.time() if now is None else now
    for p in node.get('live_programs') or []:
        if not isinstance(p, dict):
            continue
        try:
            start = datetime.datetime.fromisoformat(str(p.get('starts_at'))).timestamp()
            end = datetime.datetime.fromisoformat(str(p.get('ends_at'))).timestamp()
        except ValueError:
            continue
        if start <= stamp < end:
            current = _text(p.get('title'), 200)
            break
    return {
        'id': 'c.' + slug, 'kind': 'channel', 'title': title, 'path': slug, 'series_id': '', 'season': None,
        'episode': None, 'year': None, 'duration': None, 'rating': _rating(node),
        'genre': ', '.join(tags), 'summary': ('Jetzt: ' + current) if current else '',
        'poster': _images(node, 'artwork', 'snapshot'), 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None,
        'number': _int(node.get('channel_number'), 0, 100000), 'category': tags[0] if tags else '',
        'playable': 1, 'drm': 0, 'web_url': web_url('channel', slug)}


def list_page(answer):
    """(entries, total_pages) for the first list page (data.contents) and further pages (data + meta)."""
    data = _data(answer)
    if isinstance(data, dict) and isinstance(data.get('contents'), dict):
        holder = data['contents']
        entries, meta = holder.get('data'), holder.get('meta')
    else:
        entries, meta = data, answer.get('meta')
    pages = _int(((meta or {}).get('pagination') or {}).get('total_pages'), 1, 10000) if isinstance(meta, dict) else None
    return (entries if isinstance(entries, list) else []), pages or 1


def parse_season(data, series):
    """Episodes of one season answer (seasons/<id>)."""
    data = data if isinstance(data, dict) else {}
    number = _int(data.get('number'), 0, 999)
    out = []
    for ep in (data.get('episodes') or [])[:1000]:
        if not isinstance(ep, dict) or not VALID_SLUG.fullmatch(str(ep.get('id') or '')):
            continue
        duration = _int(ep.get('duration'), 1, 1440)
        season = _int(ep.get('season_number'), 0, 999)
        out.append({'id': 'e.' + ep['id'], 'kind': 'episode', 'title': _text(ep.get('title'), 200) or 'Folge',
                    'path': ep['id'], 'series_id': series['id'], 'season': season if season is not None else number,
                    'episode': _int(ep.get('number'), 0, 9999), 'year': _int(ep.get('year'), 1880, 2100),
                    'duration': duration * 60 if duration else None, 'rating': '', 'genre': '',
                    'summary': _text(ep.get('short_plot') or ep.get('plot'), 1600),
                    'poster': _images(ep, 'snapshot', 'artwork'), 'imdb_id': '', 'imdb_score': None,
                    'imdb_votes': None, 'number': None, 'category': '', 'playable': 0, 'drm': 1,
                    'web_url': series.get('web_url') or ''})
    return out


def other_seasons(data):
    out = []
    for s in (data or {}).get('other_seasons') or [] if isinstance(data, dict) else []:
        if isinstance(s, dict) and VALID_SLUG.fullmatch(str(s.get('id') or '')):
            out.append(s['id'])
    return out[:100]


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'playable', 'drm',
          'web_url')


def _store(db, items, now):
    for item in items:
        db.execute('''INSERT INTO rakuten_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def _load_list(request, ident, gap, found):
    """All pages of one free list; returns False when it stopped early."""
    entries, pages = list_page(request('lists/' + ident, {'contents[page]': 1, 'contents[per_page]': PER_PAGE}))
    page = 1
    while True:
        for node in entries:
            it = item_from(node)
            if it:
                found.setdefault(it['id'], it)
        page += 1
        if page > min(pages, MAX_PAGES) or len(found) >= MAX_ITEMS:
            return True
        if gap:
            time.sleep(gap)
        try:
            entries, pages = list_page(request('lists/%s/contents' % ident, {'page': page, 'per_page': PER_PAGE}))
        except Exception:
            return False


def _load_live(request, gap, now):
    start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(hours=3)
    window = {'epg_duration_minutes': 180, 'epg_starts_at': start.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
              'epg_ends_at': end.strftime('%Y-%m-%dT%H:%M:%S.000Z'), 'per_page': LIVE_PER_PAGE}
    found, page, pages = {}, 1, 1
    while page <= min(pages, 40):
        answer = request('live_channels', {**window, 'page': page})
        entries = _data(answer)
        pages = _int((((answer.get('meta') or {}).get('pagination') or {}).get('total_pages')), 1, 1000) or 1
        for node in entries if isinstance(entries, list) else []:
            ch = channel_from(node, now)
            if ch:
                found.setdefault(ch['id'], ch)
        page += 1
        if gap and page <= pages:
            time.sleep(gap)
    return found


def sync(root, request=None, now=None, gap=None):
    """Load all free films, series and live channels. Rows stay, but only titles seen in the
    latest successful run are listed (the free catalogue rotates)."""
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
    _notify('rakuten_sync_started')
    try:
        found, partial, notes = {}, False, []
        for ident, _ in FREE_LISTS:
            try:
                partial |= not _load_list(request, ident, gap, found)
            except Exception as exc:
                if not found:
                    raise
                partial = True
                notes.append(_error(exc))
        try:
            found.update(_load_live(request, gap, now))
        except Exception as exc:
            partial = True
            notes.append('Live-Sender: ' + _error(exc))
        if not any(i['kind'] in ('movie', 'series') for i in found.values()):
            raise ValueError('Rakuten TV lieferte keine kostenlosen Titel')
        items = list(found.values())
        counts = {'movies': sum(1 for i in items if i['kind'] == 'movie'),
                  'series': sum(1 for i in items if i['kind'] == 'series'),
                  'channels': sum(1 for i in items if i['kind'] == 'channel')}
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('rakuten_sync_completed', partial=partial, **counts)
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
        _notify('rakuten_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


def _row(db, item_id):
    row = db.execute('SELECT * FROM rakuten_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def _series(db, series_id):
    row = db.execute("SELECT * FROM rakuten_items WHERE id=? AND kind='series'", (series_id,)).fetchone()
    if not row:
        raise ValueError('Rakuten-Serie nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def load_episodes(root, series_id, request=None, now=None):
    """All seasons of a series: current season first, then the ones it lists as other_seasons."""
    now = time.time() if now is None else now
    request = request or _request
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    current = _data(request('tv_shows/%s/current_season' % series['path']))
    first = str((current or {}).get('id') or '')
    if not VALID_SLUG.fullmatch(first):
        raise ValueError('Rakuten TV nannte keine Staffel')
    season = _data(request('seasons/' + first))
    found = parse_season(season, series)
    for ident in other_seasons(season):
        found += parse_season(_data(request('seasons/' + ident)), series)
    db = _connect(root)
    try:
        with db:
            _store(db, found, now)
            _set(db, 'series_checked:' + series_id, now)
    finally:
        db.close()
    return found


def episodes(root, series_id, request=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige Rakuten-Serie')
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
            load_episodes(root, series_id, request, now)
        except Exception as exc:
            error = _error(exc)
    db = _connect(root)
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM rakuten_items WHERE kind='episode' AND series_id=? ORDER BY season,episode,title",
            (series_id,))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': error}


def own_score(row):
    value = row.get('imdb_score')
    if not isinstance(value, (int, float)) or not 0 <= value <= 10:
        return None
    return {'value': round(float(value), 1), 'source': 'IMDb', 'votes': row.get('imdb_votes')}


def _summary(root, row, reports=None):
    import rakuten_enrichment
    report = (reports if reports is not None else rakuten_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))
    if not out['score']:
        out['score'] = own_score(row)
    return out


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films, series or live channels; films and series with canonical categories and ratings."""
    import rakuten_enrichment
    kind = {'movies': 'movie', 'series': 'series', 'live': 'channel'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    # 'all': the merged dashboard index (unified_index.py) reads every row once and pages itself.
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM rakuten_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        order = 'number,title' if kind == 'channel' else 'title COLLATE NOCASE'
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY ' + order, args)]
    finally:
        db.close()
    if kind == 'channel':
        return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
                'genre_counts': []}
    reports = rakuten_enrichment.all_cached(root)
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


def channels(root):
    """Live channels of the latest successful catalogue run (for the Live-TV tab, live_tv)."""
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        return [dict(r) for r in db.execute(
            "SELECT id,title,number,genre,category,summary,poster FROM rakuten_items "
            "WHERE kind='channel' AND drm=0 AND seen>=? ORDER BY number,title", (last,))]
    finally:
        db.close()


def item(root, item_id):
    """Detail view of one film, series, episode or channel: catalogue row, series, reference report."""
    import rakuten_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Rakuten-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        if not row:
            raise ValueError('Rakuten-Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    report = rakuten_enrichment.cached(root, item_id) if row['kind'] != 'channel' else dict(rakuten_enrichment.UNCHECKED)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'web_url': row.get('web_url') or (parent or {}).get('web_url') or ''},
            'series': parent, 'reference': report}


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
            'protected': movies + series,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM rakuten_items WHERE kind='episode'").fetchone()[0]}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='rakuten_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:rakuten'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or portal_reference.retry_after_update(root, sys.modules[__name__], current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def stream_info(answer):
    """(url, licence) from an avod/streamings answer: data.stream_infos[0].

    0.5.59: any https address without credentials is accepted (live channels are served by
    advert-inserting CDNs whose host is not always *.rakuten.tv, and the advert parameters make
    the address long); hls_guard.check still inspects every playlist before playback."""
    data = _data(answer)
    infos = data.get('stream_infos') if isinstance(data, dict) else None
    first = infos[0] if isinstance(infos, list) and infos and isinstance(infos[0], dict) else {}
    url = str(first.get('url') or '')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password \
            or len(url) > MAX_STREAM_URL:
        url = ''
    return url, str(first.get('license_url') or '')


def _no_stream_reason(answer):
    """Short, token-free description of an avod/streamings answer without a usable address."""
    if not isinstance(answer, dict):
        return 'keine Antwortdaten'
    errors = answer.get('errors')
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return _text(errors[0].get('message') or errors[0].get('code') or 'Fehler', 160)
    data = answer.get('data') if isinstance(answer.get('data'), dict) else {}
    infos = data.get('stream_infos')
    if not isinstance(infos, list) or not infos:
        return 'Antwort ohne Streamliste (Felder: %s)' % ', '.join(sorted(map(str, data))[:12])
    first = infos[0] if isinstance(infos[0], dict) else {}
    url = str(first.get('url') or '')
    if not url:
        return 'Streamliste ohne Adresse (Profil %s)' % _text(first.get('player') or '?', 40)
    parts = urllib.parse.urlsplit(url)
    return 'Adresse abgelehnt (%s, %d Zeichen)' % (parts.scheme or 'ohne Schema', len(url))


def _live_body(row, session):
    """Request body for a live channel, built like the website's own (0.5.59).

    Sent: the technical player fields of the website. Not sent: IP address, browser string,
    advertising IDs or a consent string. Consent is declared as refused (opt-out); adverts stay
    in the stream (Rakuten inserts them server-side)."""
    return {'unique_session_id': session, 'audio_language': 'DEU', 'audio_quality': '2.0',
            'classification_id': CLASSIFICATION_ID, 'content_id': row['path'], 'content_type': 'live_channels',
            'custom_device_type': DEVICE, 'device_make': 'chrome', 'device_model': 'GENERIC',
            'device_serial': 'not implemented', 'device_stream_video_quality': 'HD', 'device_uid': _DEVICE_UID,
            'device_year': 1970, 'gdpr_consent_opt_out': '1', 'gdpr_consent': '', 'hdr_type': 'NONE',
            'ifa_subscriber_id': None, 'ifa_type': 'ppid', 'player_height': 1080, 'player_width': 1920,
            'player': LIVE_PLAYER, 'strict_video_quality': False, 'subtitle_formats': ['vtt'],
            'subtitle_language': 'MIS', 'support_closed_captions': True, 'video_type': 'stream',
            'support_thumbnails': True, 'app_bundle': 'com.rakutentv.web', 'app_name': 'RakutenTV',
            'url': 'rakuten.tv'}


def _live_query(session):
    return {'device_stream_audio_quality': '2.0', 'device_stream_hdr_type': 'NONE',
            'device_stream_video_quality': 'FHD', 'device_uid': _DEVICE_UID,
            'disable_dash_legacy_packages': 'false', 'unique_session_id': session}


def live_stream(row, request=None, now=None):
    """Fresh HLS address of a live channel, requested with the website's live profile."""
    import hls_guard
    now = time.time() if now is None else now
    cached = _SOURCES.get(row['id'])
    if cached and cached[0] > now:
        return cached[1]
    session = str(uuid.uuid4())
    answer = (request or _request)('avod/streamings', _live_query(session), _live_body(row, session))
    url, licence = stream_info(answer)
    if licence:
        raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
    if not url:
        reason = _no_stream_reason(answer)
        try:
            import diagnostics
            diagnostics.event('rakuten_live_no_stream', 'WARNING', channel=row['path'], reason=reason)
        except Exception:
            pass
        raise ValueError('Rakuten TV lieferte für diesen Sender keinen Stream (%s)' % reason)
    _SOURCES[row['id']] = (now + SOURCE_TTL, url)
    return url


def play_source(root, item_id, request=None, check=None, now=None):
    """Source for streaming.plan. Live channels: HLS, checked for copy protection. Films and
    episodes: refused, Rakuten delivers them only with Widevine/PlayReady (see module text)."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Rakuten-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row:
        raise ValueError('Rakuten-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    if row['kind'] != 'channel' or row['drm']:
        raise hls_guard.DrmProtected(DRM_NOTE)
    try:
        url = live_stream(row, request, now)
        (check or hls_guard.check)(url)
    except urllib.error.HTTPError as exc:
        raise ValueError(_http_detail(exc)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(_error(exc)) from None
    title = ('%s · %s' % (row['number'], row['title'])) if row['number'] else row['title']
    return {'kind': 'url', 'url': url, 'hls': True, 'quality': 'Rakuten TV live (kostenlos, mit Werbung)',
            'title': title, 'duration': 0, 'provider': 'rakuten', 'live': True}
