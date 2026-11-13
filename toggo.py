"""TOGGO: the children's series of toggo.de (Super RTL), incl. TOGGOLINO (0.5.79).

Björn (12.11.2026): "integriere mir als nächstes TOGGO für meine Tochter".

toggo.de was not reachable from the development environment and no recording (HAR) existed
when this was written, so everything here rests on publicly documented formats only and is
NOT confirmed live:

* Addresses of episodes and clips (documented by yt-dlp's Toggo extractor):
  ``https://www.toggo.de/[toggolino/]<serie>/folge/<folge>`` and ``…/video/<clip>``.
  The catalogue is built from the website's own sitemap (robots.txt -> ``Sitemap:`` lines,
  sitemap index, ``<loc>`` entries; the standard sitemap format): every address of that shape
  is an episode or clip of the series named in it.
* Details of one episode (yt-dlp): ``https://production-n.toggo.de/api/assetstore/vod/asset/<folge>``
  -> ``data`` with ``title``, ``description``, ``images``, ``series_title``, ``season_no``,
  ``episode_no`` and ``custom_fields`` (``video-cloud-id`` = Brightcove video id).
* Streams: Brightcove Playback API (public, documented): the player's policy key from
  ``players.brightcove.net/<account>/default_default/config.json``, then
  ``edge.api.brightcove.com/playback/v1/accounts/<account>/videos/<id>`` -> ``sources``.

Copy protection: according to yt-dlp, TOGGO lists its streams as Widevine (DASH ``/cenc/``) and
FairPlay (HLS ``/fairplay/``). MediathekAtlas never rewrites addresses to reach an unlisted
variant and circumvents nothing. Only a source the Playback API itself lists WITHOUT a key
system (plain HLS or MP4) is played, and hls_guard checks the playlist once more. If there is
none, the episode opens toggo.de ("Bei TOGGO ansehen"). The outcome of the first check is
remembered, so the tiles show the right button. No offline copies in this version.

The sitemap run records only technical counters in the diagnosis (number of sitemaps, addresses
and path shapes), never titles, tokens or addresses.
"""
from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
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
from pathlib import Path

import portal_reference

SITE = 'https://www.toggo.de'
ASSET_API = 'https://production-n.toggo.de/api/assetstore/vod/asset/'
BRIGHTCOVE_ACCOUNT = '6057955896001'
PLAYER_CONFIG = 'https://players.brightcove.net/%s/default_default/config.json' % BRIGHTCOVE_ACCOUNT
PLAYER_SCRIPT = 'https://players.brightcove.net/%s/default_default/index.min.js' % BRIGHTCOVE_ACCOUNT
PLAYBACK_API = 'https://edge.api.brightcove.com/playback/v1/accounts/%s/videos/' % BRIGHTCOVE_ACCOUNT
HOSTS = {'www.toggo.de', 'production-n.toggo.de', 'players.brightcove.net', 'edge.api.brightcove.com'}
SITEMAP_CANDIDATES = ('/sitemap.xml', '/sitemap_index.xml', '/sitemap-index.xml', '/sitemaps/sitemap.xml')
MAX_SITEMAPS = 60
MAX_ANSWER = 24 * 1024 * 1024
MAX_SERIES = 1500
MAX_ITEMS = 60000
REQUEST_GAP = 0.25
SERIES_DETAIL_TTL = 7 * 24 * 3600
EPISODE_BUDGET = 10.0              # seconds a series page may spend completing episode details
EPISODE_WORKERS = 4
POLICY_TTL = 12 * 3600
SOURCE_TTL = 300
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
VALID_ID = re.compile(r'[se]\.[0-9a-f]{16}')
SLUG = r"[^/?#\s<>\"\\]{1,200}"
EPISODE_URL = re.compile(r'https://www\.toggo\.de/(toggolino/)?(' + SLUG + r')/(folge|video)/(' + SLUG + r')/?')
VIDEO_ID = re.compile(r'\d{6,20}|ref:[A-Za-z0-9_.:\-]{1,80}')
POLICY_KEY = re.compile(r'BCpk[A-Za-z0-9_\-.~]{20,400}')
BRANDS = {'': 'TOGGO', 'toggolino/': 'TOGGOLINO'}
GENRE = 'Kinder'
HLS_TYPES = {'application/x-mpegurl', 'application/vnd.apple.mpegurl'}
DRM_NOTE = ('TOGGO liefert diese Folge nur mit Kopierschutz (Widevine/FairPlay). MediathekAtlas umgeht ihn '
            'nicht: bitte bei TOGGO ansehen.')
NO_SITEMAP = ('TOGGO nennt in seiner Seitenübersicht (Sitemap) keine Folgen. MediathekAtlas braucht dafür ein '
              'Update; bitte die Diagnose oder einen HAR-Mitschnitt von toggo.de schicken')

_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_POLICY = {}        # {'key': (expires, value)} – in memory only
_SOURCES = {}       # item id -> (expires, source dict)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS toggo_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', brand TEXT NOT NULL DEFAULT '', slug TEXT NOT NULL DEFAULT '',
  clip INTEGER NOT NULL DEFAULT 0, video_id TEXT NOT NULL DEFAULT '', detailed REAL NOT NULL DEFAULT 0,
  drm INTEGER, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS toggo_items_kind ON toggo_items(kind, seen);
CREATE INDEX IF NOT EXISTS toggo_items_series ON toggo_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS toggo_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, level=None, **details):
    """Technical counters only; never URLs, tokens or titles."""
    try:
        import diagnostics
        if level:
            diagnostics.event(event, level, **details)
        else:
            diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'toggo.sqlite3'
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
    row = db.execute('SELECT value FROM toggo_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO toggo_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def _fetch(url, headers=None):
    """GET one address on a fixed TOGGO/Brightcove host; size-limited, gzip sitemaps unpacked."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port or parts.username or parts.password:
        raise ValueError('Ungültige TOGGO-Anfrage')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json, text/xml, */*',
                                               'Accept-Language': 'de-DE,de;q=0.9', 'Origin': SITE,
                                               'Referer': SITE + '/', **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in HOSTS:
            raise ValueError('TOGGO leitete auf eine unerwartete Adresse um')
        raw = response.read(MAX_ANSWER + 1)
    if len(raw) > MAX_ANSWER:
        raise ValueError('TOGGO-Antwort zu groß')
    if raw[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=__import__('io').BytesIO(raw)) as packed:
            raw = packed.read(MAX_ANSWER + 1)
        if len(raw) > MAX_ANSWER:
            raise ValueError('TOGGO-Antwort zu groß')
    return raw


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('TOGGO lieferte kein gültiges Ergebnis') from None


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (403, 451):
        return 'TOGGO verweigert den Zugriff (HTTP %d, evtl. nur aus Deutschland abrufbar)' % code
    if code:
        return 'TOGGO antwortet mit HTTP %d' % code
    if isinstance(exc, ValueError):
        return str(exc)[:240]
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('TOGGO ist nicht erreichbar', exc)
    return 'TOGGO-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _int(value, low=None, high=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool) or (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def item_id(kind, key):
    return ('s.' if kind == 'series' else 'e.') + hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]


def image(value):
    """Artwork address from TOGGO's own API: https, no credentials, no odd characters."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.port or parts.username or parts.password \
            or len(value) > 800 or re.search(r'[\s<>"\'\\]', value):
        return ''
    return value


def pretty(slug):
    """Readable title from an address part until the real title is known: 'paw-patrol' -> 'Paw Patrol'."""
    words = [w for w in re.split(r'-+', urllib.parse.unquote(str(slug or ''))) if w]
    return _text(' '.join(w[:1].upper() + w[1:] for w in words), 200) or 'Ohne Titel'


def locs(text):
    """All <loc> addresses of a sitemap or sitemap index (plain text scan: no XML entity expansion)."""
    return [html.unescape(m).strip() for m in re.findall(r'<loc>\s*([^<]{1,2000}?)\s*</loc>', str(text or ''))]


def is_index(text):
    return '<sitemapindex' in str(text or '')[:4000]


def robots_sitemaps(text):
    out = []
    for line in str(text or '').splitlines():
        m = re.match(r'(?i)\s*sitemap\s*:\s*(\S+)', line)
        if m and _own(m.group(1)) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _own(url):
    parts = urllib.parse.urlsplit(str(url or ''))
    return parts.scheme == 'https' and parts.hostname == 'www.toggo.de' and not parts.port and not parts.username


def classify(url):
    """{'brand','series','clip','slug'} for an episode/clip address, else None."""
    m = EPISODE_URL.fullmatch(str(url or '').strip())
    if not m:
        return None
    series, slug = urllib.parse.unquote(m.group(2)), urllib.parse.unquote(m.group(4))
    if not series or not slug or series in ('toggolino', 'folge', 'video') or re.search(r'[/?#\s<>"\\]', series + slug):
        return None
    return {'prefix': m.group(1) or '', 'series': series, 'clip': m.group(3) == 'video', 'slug': slug}


def _q(part):
    return urllib.parse.quote(part, safe='-._~')


def episode_url(entry):
    return '%s/%s%s/%s/%s' % (SITE, entry['prefix'], _q(entry['series']), 'video' if entry['clip'] else 'folge', _q(entry['slug']))


def shapes(urls):
    """Counters of path shapes for the diagnosis: depth and the fixed words only, no titles."""
    counts = {}
    for url in urls:
        parts = [p for p in urllib.parse.urlsplit(url).path.split('/') if p]
        key = '/'.join(p if p in ('toggolino', 'folge', 'video', 'serien', 'serie', 'videos', 'spiele', 'live-tv', 'tv') else '*'
                       for p in parts[:5]) or '/'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12])


def read_sitemaps(fetch, gap=0.0):
    """All page addresses of the website's sitemaps -> (addresses, number of sitemaps read, first error)."""
    queue, first_error = [], None
    try:
        queue = robots_sitemaps(fetch(SITE + '/robots.txt').decode('utf-8', 'replace'))
    except Exception as exc:
        first_error = exc
    if not queue:      # robots.txt names none (or was not readable): the usual places
        queue = [SITE + path for path in SITEMAP_CANDIDATES]
    seen, pages, read = set(), [], 0
    while queue and len(seen) < MAX_SITEMAPS and len(pages) < 400000:
        url = queue.pop(0)
        if url in seen or not _own(url):
            continue
        seen.add(url)
        if gap and read:
            time.sleep(gap)
        try:
            text = fetch(url).decode('utf-8', 'replace')
        except Exception as exc:
            first_error = first_error or exc
            continue
        found = locs(text)
        if not found:
            continue
        read += 1
        if is_index(text):
            queue += [u for u in found if u not in seen]
        else:
            pages += found
            # Sitemaps nested without an index element: follow addresses that are sitemaps themselves.
            queue += [u for u in found if re.search(r'sitemap[^/]*\.xml(?:\.gz)?$', u) and u not in seen]
    return pages, read, first_error


def catalogue(pages):
    """Series and their episodes from page addresses: {series key: {...,'entries': {key: entry}}}."""
    series, plain = {}, {}
    for url in pages:
        entry = classify(url)
        if not entry:
            if _own(url):
                parts = [p for p in urllib.parse.urlsplit(url).path.split('/') if p]
                if parts:
                    plain.setdefault(urllib.parse.unquote(parts[-1]), url)
            continue
        key = entry['prefix'] + entry['series']
        group = series.setdefault(key, {'prefix': entry['prefix'], 'series': entry['series'], 'entries': {}})
        group['entries'].setdefault(('video/' if entry['clip'] else 'folge/') + entry['slug'], entry)
    for group in series.values():
        # Page of the series itself, if the sitemap lists one whose last part is the series name.
        page = plain.get(group['series'], '')
        first = next(iter(group['entries'].values()))
        group['web_url'] = page if page and not re.search(r'[\s<>"\'\\]', page) else episode_url(first)
    return series


def asset_fields(answer):
    """Fields of one asset answer (``data``); {} when it is not usable."""
    data = answer.get('data') if isinstance(answer, dict) else None
    if not isinstance(data, dict):
        return {}
    video = ''
    for field in data.get('custom_fields') or []:
        if isinstance(field, dict) and field.get('key') == 'video-cloud-id' and VIDEO_ID.fullmatch(str(field.get('value') or '')):
            video = str(field['value'])
    images = data.get('images') if isinstance(data.get('images'), dict) else {}
    ordered = sorted(images.items(), key=lambda kv: next((i for i, word in enumerate(('teaser', 'thumb', 'landscape', '16', 'poster'))
                                                          if word in str(kv[0]).lower()), 9))
    poster = next((image(v) for _, v in ordered if image(v)), '')
    duration = _int(data.get('duration'), 1, 10 ** 9)
    if duration and duration > 6 * 3600:          # milliseconds
        duration = duration // 1000
    age = _int(data.get('fsk') if data.get('fsk') is not None else data.get('age_rating'), 0, 18)
    return {'title': _text(data.get('title'), 200), 'summary': _text(data.get('description'), 1600),
            'series_title': _text(data.get('series_title'), 200), 'season': _int(data.get('season_no'), 0, 999),
            'episode': _int(data.get('episode_no'), 0, 9999), 'video_id': video, 'poster': poster,
            'duration': duration, 'rating': ('FSK %d' % age) if age is not None else ''}


def load_asset(fetch, slug):
    return asset_fields(_json(fetch(ASSET_API + urllib.parse.quote(slug, safe=''))))


# ---------------------------------------------------------------- storage

def _rows_from(series):
    rows = []
    for key, group in series.items():
        sid = item_id('series', key)
        brand = BRANDS[group['prefix']]
        rows.append({'id': sid, 'kind': 'series', 'title': pretty(group['series']), 'path': key, 'series_id': '',
                     'brand': brand, 'slug': group['series'], 'clip': 0, 'web_url': group['web_url'],
                     'number': len(group['entries'])})
        for ekey, entry in group['entries'].items():
            rows.append({'id': item_id('episode', key + '/' + ekey), 'kind': 'episode', 'title': pretty(entry['slug']),
                         'path': key + '/' + ekey, 'series_id': sid, 'brand': brand, 'slug': entry['slug'],
                         'clip': int(entry['clip']), 'web_url': episode_url(entry), 'number': None})
    return rows


def _store(db, rows, now):
    """New rows are inserted with the title derived from the address; known rows keep their loaded
    details (title, picture, numbers, video id) and only get the fresh address data."""
    for r in rows:
        db.execute('''INSERT INTO toggo_items(id,kind,title,path,series_id,genre,category,brand,slug,clip,web_url,number,seen,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET path=excluded.path,series_id=excluded.series_id,category=excluded.category,
              brand=excluded.brand,slug=excluded.slug,clip=excluded.clip,web_url=excluded.web_url,number=excluded.number,
              seen=excluded.seen''',
                   (r['id'], r['kind'], r['title'], r['path'], r['series_id'], GENRE, r['brand'], r['brand'], r['slug'],
                    r['clip'], r['web_url'], r['number'], now, now))


def _apply_episode(db, row_id, fields, now):
    db.execute('''UPDATE toggo_items SET title=CASE WHEN ?<>'' THEN ? ELSE title END, summary=?, season=?, episode=?,
        duration=COALESCE(?,duration), rating=?, poster=CASE WHEN ?<>'' THEN ? ELSE poster END, video_id=?, detailed=?, updated=?
        WHERE id=?''', (fields.get('title', ''), fields.get('title', ''), fields.get('summary', ''), fields.get('season'),
                        fields.get('episode'), fields.get('duration'), fields.get('rating', ''), fields.get('poster', ''),
                        fields.get('poster', ''), fields.get('video_id', ''), now, now, row_id))


def _apply_series(db, series_id, fields, now):
    if fields.get('series_title'):
        db.execute('UPDATE toggo_items SET title=? WHERE id=?', (fields['series_title'], series_id))
    if fields.get('poster'):
        db.execute("UPDATE toggo_items SET poster=? WHERE id=? AND poster=''", (fields['poster'], series_id))
    if fields.get('rating'):
        db.execute("UPDATE toggo_items SET rating=? WHERE id=? AND rating=''", (fields['rating'], series_id))
    db.execute('UPDATE toggo_items SET detailed=?, updated=? WHERE id=?', (now, now, series_id))


def _counts(db, since):
    row = db.execute("""SELECT SUM(kind='series'), SUM(kind='episode' AND clip=0), SUM(kind='episode' AND clip=1)
                        FROM toggo_items WHERE seen>=?""", (since,)).fetchone()
    return {'movies': 0, 'series': row[0] or 0, 'episodes': row[1] or 0, 'clips': row[2] or 0}


def _first_episodes(db, now, since):
    """(series id, episode id, slug) of the series whose title/picture still has to be loaded."""
    out = []
    for s in db.execute("SELECT id FROM toggo_items WHERE kind='series' AND seen>=? AND (detailed=0 OR detailed<?) ORDER BY title",
                        (since, now - SERIES_DETAIL_TTL)).fetchall():
        e = db.execute("SELECT id,slug FROM toggo_items WHERE series_id=? AND seen>=? ORDER BY clip,rowid LIMIT 1",
                       (s[0], since)).fetchone()
        if e:
            out.append((s[0], e[0], e[1]))
    return out[:MAX_SERIES]


def sync(root, fetch=None, now=None, gap=None, check=None):
    """Read the sitemaps, store all series and episodes, then load title and picture of each series
    from its first episode. What is already found is stored at once, so the catalogue fills up
    during the run. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    fetch = fetch or _fetch
    gap = (REQUEST_GAP if fetch is _fetch else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
            _set(db, 'progress', 'Seitenübersicht von toggo.de wird gelesen')
    finally:
        db.close()
    _notify('toggo_sync_started')
    try:
        pages, read, first_error = read_sitemaps(fetch, gap)
        series = catalogue(pages)
        _notify('toggo_sitemap', sitemaps=read, addresses=len(pages), series=len(series),
                episodes=sum(len(g['entries']) for g in series.values()), shapes=shapes(pages))
        if not read and first_error is not None:
            raise first_error
        if not series:
            raise ValueError(NO_SITEMAP + ' (%d Sitemaps, %d Adressen gelesen)' % (read, len(pages)))
        rows = _rows_from(series)[:MAX_ITEMS]
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                # Visible at once: this run's rows count as the current catalogue.
                for key, value in [('last_success', now), ('last_loaded', time.time()),
                                   ('progress', 'Serien gefunden, Titel und Bilder folgen'), *_counts(db, now).items()]:
                    _set(db, key, value)
            todo = _first_episodes(db, now, now)
        finally:
            db.close()
        failed, notes = 0, []
        for number, (sid, eid, slug) in enumerate(todo, 1):
            if gap:
                time.sleep(gap)
            try:
                fields = load_asset(fetch, slug)
                if not fields:
                    raise ValueError('TOGGO lieferte keine Folgendaten')
            except Exception as exc:
                failed += 1
                if not notes:
                    notes.append(_error(exc))
                if failed >= 8 and failed == number:     # nothing works: do not hammer the server
                    break
                continue
            db = _connect(root)
            try:
                with db:
                    _apply_episode(db, eid, fields, now)
                    _apply_series(db, sid, fields, now)
                    if number % 10 == 0 or number == len(todo):
                        _set(db, 'last_loaded', time.time())
                        _set(db, 'progress', 'Serie %d von %d' % (number, len(todo)))
            finally:
                db.close()
        partial = failed > 0
        protection = ''
        try:
            protection = probe(root, fetch, check=check)
        except Exception:
            pass
        db = _connect(root)
        try:
            with db:
                counts = _counts(db, now)
                for key, value in [('last_loaded', time.time()), ('progress', ''),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Titel und Bilder von %d Serien fehlen noch%s' % (failed, ': ' + notes[0] if notes else ''))
                                    if partial else ''),
                                   ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('toggo_sync_completed', partial=partial, details_failed=failed, protection=protection or 'unknown', **counts)
        return {'ok': True, 'partial': partial, **counts}
    except Exception as exc:
        message = _error(exc)
        db = _connect(root)
        try:
            with db:
                for key, value in [('last_result', 'failed'), ('last_error', message), ('progress', ''),
                                   ('last_http_status', getattr(exc, 'code', 0) or 0), ('next_attempt', now + 3600)]:
                    _set(db, key, value)
        finally:
            db.close()
        import netcheck
        _notify('toggo_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- views

def _row(db, row_id):
    row = db.execute('SELECT * FROM toggo_items WHERE id=?', (row_id,)).fetchone()
    return dict(row) if row else None


def _series(db, series_id):
    row = db.execute("SELECT * FROM toggo_items WHERE id=? AND kind='series'", (series_id,)).fetchone()
    if not row:
        raise ValueError('TOGGO-Serie nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def _playable(row, protection):
    """Verified plain stream, or not checked yet while TOGGO is not known to protect its streams."""
    if row.get('kind') != 'episode':
        return 0
    if row.get('drm') == 0:
        return 1
    return 0 if row.get('drm') == 1 or protection == 'drm' else 1


def complete_episodes(root, series_id, fetch=None, now=None, budget=None):
    """Load the details (title, numbers, picture, video id) of episodes that only have their
    address so far; stops after ``budget`` seconds, the rest follows on the next call."""
    now = time.time() if now is None else now
    fetch = fetch or _fetch
    budget = EPISODE_BUDGET if budget is None else budget
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        todo = [(r[0], r[1]) for r in db.execute(
            "SELECT id,slug FROM toggo_items WHERE kind='episode' AND series_id=? AND seen>=? AND detailed=0 ORDER BY clip,rowid",
            (series_id, last))]
    finally:
        db.close()
    if not todo:
        return {'loaded': 0, 'left': 0, 'error': ''}
    deadline, done, first_error = time.monotonic() + budget, [], ''
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=EPISODE_WORKERS, thread_name_prefix='toggo_episode')
    try:
        futures = {pool.submit(load_asset, fetch, slug): eid for eid, slug in todo}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=max(0.1, budget)):
                try:
                    fields = future.result()
                    if fields:
                        done.append((futures[future], fields))
                    elif not first_error:
                        first_error = 'TOGGO lieferte keine Folgendaten'
                except Exception as exc:
                    first_error = first_error or _error(exc)
                if time.monotonic() > deadline:
                    break
        except concurrent.futures.TimeoutError:
            pass
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:      # Python 3.8
            pool.shutdown(wait=False)
    db = _connect(root)
    try:
        with db:
            for eid, fields in done:
                _apply_episode(db, eid, fields, now)
    finally:
        db.close()
    return {'loaded': len(done), 'left': len(todo) - len(done), 'error': first_error}


def episodes(root, series_id, fetch=None, now=None, budget=None):
    """Episodes of a series; missing details are loaded on demand (see complete_episodes)."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige TOGGO-Serie')
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    result = complete_episodes(root, series_id, fetch, now, budget)
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protection = _get(db, 'protection')
        rows = [dict(r) for r in db.execute(
            """SELECT * FROM toggo_items WHERE kind='episode' AND series_id=? AND seen>=?
               ORDER BY clip, season IS NULL, season, episode IS NULL, episode, title COLLATE NOCASE""", (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = _playable(row, protection)
        if row['clip']:
            row['title'] = 'Clip · ' + row['title']
    note = ''
    if result['left']:
        note = ('Bei %d Folgen fehlen noch Titel und Nummer; sie werden beim nächsten Öffnen der Serie ergänzt.' % result['left'])
    return {'series': {'id': series_id, 'title': series['title'], 'web_url': series['web_url'], **extra},
            'items': rows, 'error': result['error'] if result['left'] else '', 'note': note}


def _summary(root, row, reports=None):
    import toggo_enrichment
    report = (reports if reports is not None else toggo_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre') or GENRE, report)
    # TOGGO and TOGGOLINO (pre-school) are categories of their own, so parents can filter by age group.
    brand = row.get('brand') or 'TOGGO'
    out['categories'] = [c for c in out['categories'] if c != portal_reference.UNKNOWN] + [brand]
    return out


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of series (TOGGO has no single films and no live channels here)."""
    import toggo_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    if view != 'series':
        return {'items': [], 'total': 0, 'offset': offset, 'view': view, 'genre_counts': []}
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = "FROM toggo_items WHERE kind='series' AND seen>=?"
        args = [last]
        if query:
            sql += ' AND (title LIKE ? OR brand LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = toggo_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
        row['playable'] = 0
        row['seasons'] = None
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, 'series')]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    return []


def item(root, row_id):
    """Detail view of one series or episode: catalogue row, series, reference report."""
    import toggo_enrichment
    if not VALID_ID.fullmatch(str(row_id or '')):
        raise ValueError('Ungültiger TOGGO-Titel')
    db = _connect(root)
    try:
        row = _row(db, row_id)
        if not row:
            raise ValueError('TOGGO-Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
        protection = _get(db, 'protection')
    finally:
        db.close()
    base = parent if row['kind'] == 'episode' and parent else row
    report = toggo_enrichment.cached(root, base['id'])
    summary = _summary(root, base, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'playable': _playable(row, protection), 'protection': protection},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        protection = _get(db, 'protection')
        series = _int(_get(db, 'series', '0')) or 0
        out = {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'last_loaded': float(_get(db, 'last_loaded', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': 0, 'series': series, 'channels': 0,
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'clips': _int(_get(db, 'clips', '0')) or 0,
            'protection': protection or 'unknown', 'protected': series if protection == 'drm' else 0,
            'progress': _get(db, 'progress') if _ACTIVE else ''}
        if protection == 'drm':
            out['playable'] = 0
        return out
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='toggo_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:toggo'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def policy_key(fetch=None, now=None):
    """Public policy key of TOGGO's Brightcove player (config.json, else the player script)."""
    now = time.time() if now is None else now
    hit = _POLICY.get('key')
    if hit and hit[0] > now:
        return hit[1]
    fetch = fetch or _fetch
    key = ''
    try:
        config = _json(fetch(PLAYER_CONFIG))
        key = str(((config.get('video_cloud') or {}) if isinstance(config, dict) else {}).get('policy_key') or '')
    except Exception:
        key = ''
    if not POLICY_KEY.fullmatch(key):
        found = POLICY_KEY.search(fetch(PLAYER_SCRIPT).decode('utf-8', 'replace'))
        key = found.group(0) if found else ''
    if not POLICY_KEY.fullmatch(key):
        raise ValueError('Der TOGGO-Player nannte keinen Zugangsschlüssel für die Wiedergabe')
    _POLICY['key'] = (now + POLICY_TTL, key)
    return key


def _protected(source):
    src = str(source.get('src') or '')
    return bool(source.get('key_systems')) or '/fairplay/' in src or '/cenc/' in src or '/playready/' in src \
        or '/widevine/' in src


def _stream_url(value):
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.port or parts.username or parts.password \
            or len(value) > 4000 or re.search(r'[\s<>"\'\\]', value):
        return ''
    return value


def pick_source(sources):
    """(source, protected count): the best source listed WITHOUT copy protection – HLS first, then
    the largest MP4 up to 1080p. None when every listed source needs a DRM licence."""
    plain, protected = [], 0
    for s in sources if isinstance(sources, list) else []:
        if not isinstance(s, dict):
            continue
        if _protected(s):
            protected += 1
            continue
        url = _stream_url(s.get('src'))
        kind = str(s.get('type') or '').lower()
        if not url:
            continue
        if kind in HLS_TYPES or urllib.parse.urlsplit(url).path.endswith('.m3u8'):
            plain.append((2, 0, {'url': url, 'hls': True}))
        elif kind == 'video/mp4' or str(s.get('container') or '').upper() == 'MP4':
            height = _int(s.get('height'), 1, 4320) or 0
            plain.append((1, height if height <= 1080 else -height, {'url': url, 'hls': False, 'height': height}))
    if not plain:
        return None, protected
    plain.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return plain[0][2], protected


def playback(video_id, fetch=None, now=None):
    """Answer of the Brightcove Playback API for one video."""
    if not VIDEO_ID.fullmatch(str(video_id or '')):
        raise ValueError('TOGGO nannte für diese Folge kein Video')
    fetch = fetch or _fetch
    url = PLAYBACK_API + urllib.parse.quote(video_id, safe=':')
    for attempt in (0, 1):
        try:
            return _json(fetch(url, {'Accept': 'application/json;pk=' + policy_key(fetch, now)}))
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                body = json.loads(exc.read(20000).decode('utf-8', 'replace'))
                first = body[0] if isinstance(body, list) and body and isinstance(body[0], dict) else {}
                detail = str(first.get('error_subcode') or first.get('error_code') or '')
            except Exception:
                pass
            if detail == 'INVALID_POLICY_KEY' and attempt == 0:
                _POLICY.clear()
                continue
            if 'GEO' in detail:
                raise ValueError('TOGGO gibt diese Folge nur in Deutschland frei (Standortsperre)') from None
            if exc.code == 404:
                raise ValueError('TOGGO hat diese Folge nicht mehr im Angebot') from None
            raise ValueError('TOGGO lehnte die Wiedergabe ab (HTTP %d%s)' % (exc.code, ', ' + _text(detail, 40) if detail else '')) from None
    raise ValueError('TOGGO lehnte die Wiedergabe ab')


def _remember(root, row_id, drm, duration=None):
    """Result of one episode's check (0 = plain stream, 1 = copy protected)."""
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE toggo_items SET drm=?, duration=COALESCE(?,duration) WHERE id=?', (drm, duration, row_id))
    finally:
        db.close()


def resolve(root, row, fetch=None, check=None, now=None):
    """Playable source of one episode, or hls_guard.DrmProtected. The result is remembered."""
    import hls_guard
    now = time.time() if now is None else now
    cached = _SOURCES.get(row['id'])
    if cached and cached[0] > now:
        return cached[1]
    fetch = fetch or _fetch
    video = row.get('video_id') or ''
    if not video:
        fields = load_asset(fetch, row['slug'])
        if not fields:
            raise ValueError('TOGGO lieferte keine Folgendaten')
        db = _connect(root)
        try:
            with db:
                _apply_episode(db, row['id'], fields, now)
        finally:
            db.close()
        video = fields.get('video_id') or ''
        row = {**row, 'title': fields.get('title') or row['title']}
    answer = playback(video, fetch, now)
    source, protected = pick_source(answer.get('sources') if isinstance(answer, dict) else None)
    duration = _int((answer or {}).get('duration'), 1, 10 ** 9) if isinstance(answer, dict) else None
    duration = duration // 1000 if duration else None
    if source and source['hls']:
        try:
            (check or hls_guard.check)(source['url'])
        except hls_guard.DrmProtected:
            source = None
            protected += 1
    if not source:
        _notify('toggo_playback', result='protected' if protected else 'no_source', protected_sources=protected)
        if protected:
            _remember(root, row['id'], 1, duration)
            raise hls_guard.DrmProtected(DRM_NOTE)
        raise ValueError('TOGGO lieferte für diese Folge keinen Stream')
    _remember(root, row['id'], 0, duration)
    _notify('toggo_playback', result='clear', hls=source['hls'])
    out = {'kind': 'url', 'url': source['url'], 'hls': source['hls'],
           'quality': 'TOGGO' + (' %dp' % source['height'] if source.get('height') else ''),
           'title': row['title'], 'duration': duration or row.get('duration') or 0, 'provider': 'toggo'}
    _SOURCES[row['id']] = (now + SOURCE_TTL, out)
    return out


def probe(root, fetch=None, now=None, check=None, samples=3):
    """Check one episode each of up to ``samples`` series to learn whether TOGGO protects its
    streams: 'clear' if one plays without copy protection, 'drm' if all checked ones are
    protected, '' if nothing could be checked. The answer decides which button episodes show
    that were not played yet."""
    import hls_guard
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            """SELECT * FROM toggo_items WHERE kind='episode' AND clip=0 AND video_id<>'' AND seen>=?
               GROUP BY series_id ORDER BY rowid LIMIT ?""", (last, samples))]
    finally:
        db.close()
    protected, result = 0, ''
    for row in rows:
        try:
            resolve(root, row, fetch, check, now)
            result = 'clear'
            break
        except hls_guard.DrmProtected:
            protected += 1
        except Exception:
            continue
    if not result and protected:
        result = 'drm'
    if result:
        db = _connect(root)
        try:
            with db:
                if _get(db, 'protection') != result:
                    _set(db, 'protection', result)
                    _set(db, 'last_loaded', time.time())      # stored catalogue views are rebuilt
        finally:
            db.close()
    return result


def play_source(root, row_id, fetch=None, check=None, now=None):
    """Source for streaming.resolve: the episode's stream if TOGGO lists one without copy protection."""
    if not VALID_ID.fullmatch(str(row_id or '')):
        raise ValueError('Ungültiger TOGGO-Titel')
    db = _connect(root)
    try:
        row = _row(db, row_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row:
        raise ValueError('TOGGO-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    try:
        source = resolve(root, row, fetch, check, now)
    except urllib.error.HTTPError as exc:
        raise ValueError(_error(exc)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(_error(exc)) from None
    if parent and parent.get('title') and parent['title'] not in source['title']:
        source = {**source, 'title': '%s · %s' % (parent['title'], source['title'])}
    return source
