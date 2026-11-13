"""TOGGO: series and films of toggo.de (Super RTL), incl. the pre-school offer TOGGOLINO.

Björn (12.11.2026): "integriere mir als nächstes TOGGO für meine Tochter". 0.5.79 was built
without access to toggo.de from publicly documented formats (sitemap, yt-dlp, Brightcove). Björn's
HAR (13.11.2026, www.toggo.de in Chrome, not signed in) shows the real formats; since 0.5.87
this module follows the recording and the guesses are gone:

* Catalogue: ``POST https://production-n.toggo.de/api/assetstore/vod/asset?expand=false`` with a
  JSON filter, e.g. ``{"filter":{"and":[{"type":["movie"]}]},"sort":"title[asc]","size":20}``;
  answer ``{"success":true,"data":{"size","offset","total_items","items":[…]}}``. Recorded sizes:
  10, 20 and 500. No account, no key; the website sends ``x-authorized-user: false``,
  ``x-paid-user: false``, ``x-platform-type: Web``, ``x-preview-mode: false``.
  NOT recorded: a second page. If ``total_items`` exceeds one answer, ``offset`` is tried (the
  answer names that field) and the run stops as soon as a page brings nothing new.
* One series with all seasons and episodes:
  ``GET …/vod/asset/<u_name>?filter=rootParentTypes[not|hidden]`` -> ``data.episodes`` (204 for
  PAW Patrol in one answer).
* Fields: ``id`` (VSE302, VEP17623, MOV116), ``u_name``, ``title``, ``description``, ``summary``,
  ``images`` (SeriesCover, MovieCover, Thumbnail on ameepublic.imgix.net), ``genres``,
  ``target_age_group`` (school / preschool), ``age_range_start``, ``season_no``, ``episode_no``,
  ``run_length`` (seconds), ``release_year``, ``available_packages`` (fvod = free, catchup = free
  for some days after the broadcast, svod = subscription), ``latest_end_date``,
  ``video_audio_amee_asset_id`` (ASV18480).
* Pages: ``/videos/serien/<serie>``, ``/videos/serien/<serie>/folge/<folge>``,
  ``/sammlung/alle-filme/filme/<film>/video/<film>``.
* Streams: ``GET https://stus.player.streamingtech.de/movie-playout-variants/superrtl/<ASV>?platform=web``
  -> variants dashsd/dashhd (licences WIDEVINE + PLAYREADY) and hlsfairplayhd/hlsfairplaysd
  (FAIRPLAY); the player fetched a Widevine licence. Recorded for a free episode (catchup) and
  a free film (fvod): every variant is copy protected.

So TOGGO titles get catalogue, title and series pages and open toggo.de ("Bei TOGGO ansehen");
MediathekAtlas circumvents nothing, plays nothing protected and stores no offline copies. After
each catalogue run up to three free titles are checked: only if TOGGO ever lists a variant
without a licence (plain HLS, confirmed by hls_guard) do titles get the player button.

Titles, tokens and URLs never go to logs or the diagnosis export.
"""
from __future__ import annotations

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
API = 'https://production-n.toggo.de/api/assetstore/vod/asset'
VARIANTS = 'https://stus.player.streamingtech.de/movie-playout-variants/superrtl/%s?platform=web'
HOSTS = {'production-n.toggo.de', 'stus.player.streamingtech.de'}
PAGE = 500                         # largest size the website itself uses
MAX_PAGES = 20
MAX_ANSWER = 32 * 1024 * 1024
REQUEST_GAP = 0.5
SERIES_TTL = 6 * 3600
SOURCE_TTL = 300
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
VALID_ID = re.compile(r'[sme]\.[A-Z]{2,5}\d{1,9}')        # s.VSE302, m.MOV116, e.VEP17623
ASSET_ID = re.compile(r'[A-Z]{2,5}\d{1,9}')
U_NAME = re.compile(r"[a-z0-9][a-z0-9\-_.']{0,200}")
KIND_PREFIX = {'series': 's', 'movie': 'm', 'episode': 'e'}
FREE_PACKAGES = {'fvod', 'catchup'}
GENRE = 'Kinder'
IGNORED_GENRES = {'allgemein', 'preschool', 'school', 'kino'}
AGE_GROUPS = {'preschool': 'TOGGOLINO (Vorschule)', 'school': 'TOGGO (Schulkinder)'}
PAID = 'Nur mit Abo'
FREE = 'Kostenlos'
CHILDREN = 'Kinder & Familie'
IMAGE_HOSTS = ('.imgix.net', '.toggo.de', '.superrtl.de')
DRM_NOTE = ('TOGGO liefert Folgen und Filme nur mit Kopierschutz (Widevine/PlayReady/FairPlay) aus. '
            'MediathekAtlas umgeht ihn nicht: bitte bei TOGGO ansehen.')

_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_SOURCES = {}       # item id -> (expires, source dict)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS toggo_assets(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', ages TEXT NOT NULL DEFAULT '', offer TEXT NOT NULL DEFAULT 'free',
  seasons INTEGER, until REAL, video_id TEXT NOT NULL DEFAULT '', original_title TEXT NOT NULL DEFAULT '',
  drm INTEGER, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS toggo_assets_kind ON toggo_assets(kind, seen);
CREATE INDEX IF NOT EXISTS toggo_assets_series ON toggo_assets(series_id, season, episode);
CREATE TABLE IF NOT EXISTS toggo_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
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
    path = root / 'toggo.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='toggo_items'").fetchone():
        # 0.5.79-0.5.85 stored guessed sitemap entries under other ids: catalogue, state and checks start anew.
        db.executescript('DROP TABLE IF EXISTS toggo_items; DROP TABLE IF EXISTS toggo_reference_checks; '
                         'DROP TABLE IF EXISTS toggo_state;')
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM toggo_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO toggo_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- network

def headers(body=False):
    """The website's own request headers (HAR); no account and no device data."""
    out = {'User-Agent': USER_AGENT, 'Accept': '*/*', 'Accept-Language': 'de-DE,de;q=0.9', 'Origin': SITE,
           'Referer': SITE + '/', 'x-authorized-user': 'false', 'x-paid-user': 'false', 'x-platform-type': 'Web',
           'x-preview-mode': 'false'}
    if body:
        out['Content-Type'] = 'application/json'
    return out


def _fetch(url, body=None):
    """One request to a fixed TOGGO host: POST with a JSON body, otherwise GET. Returns bytes."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port or parts.username or parts.password:
        raise ValueError('Ungültige TOGGO-Anfrage')
    data = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8') if body is not None else None
    if parts.hostname == 'production-n.toggo.de':
        head = headers(body is not None)
    else:
        head = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Origin': SITE, 'Referer': SITE + '/'}
    req = urllib.request.Request(url, data=data, headers=head, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=40) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in HOSTS:
            raise ValueError('TOGGO leitete auf eine unerwartete Adresse um')
        raw = response.read(MAX_ANSWER + 1)
    if len(raw) > MAX_ANSWER:
        raise ValueError('TOGGO-Antwort zu groß')
    return raw


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError, AttributeError):
        raise ValueError('TOGGO lieferte kein gültiges Ergebnis') from None


def _data(answer):
    """``data`` of an API answer; ``success: false`` becomes a clear message."""
    if not isinstance(answer, dict):
        raise ValueError('TOGGO lieferte kein gültiges Ergebnis')
    if answer.get('success') is False or answer.get('data') is None:
        err = answer.get('err')
        text = err.get('message') or err.get('code') if isinstance(err, dict) else err
        raise ValueError('TOGGO lehnte die Abfrage ab' + (': ' + _text(text, 160) if text else ''))
    return answer['data']


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
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def image(value):
    """Artwork on TOGGO's image hosts (ameepublic.imgix.net), https only."""
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.port or parts.username or parts.password or len(value) > 800 \
            or not any(host.endswith(h) for h in IMAGE_HOSTS) or re.search(r'[\s<>"\'\\]', value):
        return ''
    return value


def _image(node, *keys):
    images = node.get('images') if isinstance(node.get('images'), dict) else {}
    for key in keys:
        url = image(images.get(key))
        if url:
            return url
    return ''


def _u_name(value):
    value = str(value or '')
    return value if U_NAME.fullmatch(value) else ''


def _q(part):
    return urllib.parse.quote(part, safe='-._~')


def web_url(kind, u_name, series_u_name=''):
    """Page of a title on toggo.de, as the website builds it (HAR)."""
    if not u_name:
        return ''
    if kind == 'series':
        return '%s/videos/serien/%s' % (SITE, _q(u_name))
    if kind == 'movie':
        return '%s/sammlung/alle-filme/filme/%s/video/%s' % (SITE, _q(u_name), _q(u_name))
    if kind == 'episode' and series_u_name:
        return '%s/videos/serien/%s/folge/%s' % (SITE, _q(series_u_name), _q(u_name))
    return ''


def offer(node):
    """'free' (fvod or catchup), 'plus' (subscription only) or '' (no package: not listed)."""
    packages = {str(p).lower() for p in node.get('available_packages') or [] if isinstance(p, str)}
    if packages & FREE_PACKAGES:
        return 'free'
    return 'plus' if packages else ''


def _genres(node):
    out = []
    for g in node.get('genres') or []:
        name = _text(g, 40)
        if name and name.casefold() not in IGNORED_GENRES and name not in out:
            out.append(name)
    return ', '.join([GENRE] + out[:8])


def _ages(node):
    groups = [g for g in node.get('target_age_group') or [] if g in AGE_GROUPS]
    return ','.join(sorted(set(groups)))


def _until(node, kind_offer):
    """End of the free availability (catch-up episodes vanish after some days), else None."""
    if kind_offer != 'free':
        return None
    ends = [node.get(k) for k in ('fvod_latest_end_date', 'catchup_latest_end_date')]
    ends = [e for e in ends if isinstance(e, (int, float)) and not isinstance(e, bool) and e > 0]
    return float(max(ends)) if ends else None


def item_from(node, series=None):
    """Series, film or episode of an API answer; None for anything else (audio, games, live events)."""
    if not isinstance(node, dict):
        return None
    kind = str(node.get('type') or '')
    ident = str(node.get('id') or '')
    title = _text(node.get('title'), 200)
    u_name = _u_name(node.get('u_name'))
    kind_offer = offer(node)
    if kind not in KIND_PREFIX or not ASSET_ID.fullmatch(ident) or not title or not kind_offer:
        return None
    if kind == 'episode' and not series:
        return None
    age = _int(node.get('age_recommendation') if node.get('age_recommendation') is not None else node.get('age_range_start'), 0, 18)
    video = str(node.get('video_audio_amee_asset_id') or '')
    year = _int(node.get('release_year'), 1900, 2100)
    if kind == 'series':
        poster = _image(node, 'SeriesCover', 'SeriesDetailPageMobile', 'Thumbnail')
        link = web_url('series', u_name)
    elif kind == 'movie':
        poster = _image(node, 'MovieCover', 'Thumbnail', 'StageThumbnail', 'MovieDetailPageMobile')
        link = web_url('movie', u_name)
    else:
        poster = _image(node, 'Thumbnail', 'StageThumbnail')
        link = web_url('episode', u_name, series['path'])
    return {
        'id': KIND_PREFIX[kind] + '.' + ident, 'kind': kind, 'title': title, 'path': u_name,
        'series_id': series['id'] if series else '', 'season': _int(node.get('season_no'), 0, 999) if kind == 'episode' else None,
        'episode': _int(node.get('episode_no'), 0, 9999) if kind == 'episode' else None, 'year': year,
        'duration': _int(node.get('run_length'), 1, 100000) if kind != 'series' else None,
        'rating': ('ab %d' % age) if age is not None else '', 'genre': _genres(node),
        'summary': _text(node.get('summary') or node.get('description') or node.get('short_summary'), 1600),
        'poster': poster, 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
        'category': PAID if kind_offer == 'plus' else FREE, 'ages': _ages(node), 'offer': kind_offer,
        'seasons': _int(node.get('season_count'), 0, 200) if kind == 'series' else None,
        'until': _until(node, kind_offer), 'video_id': video if ASSET_ID.fullmatch(video) else '',
        'original_title': _text(node.get('original_title'), 200), 'web_url': link}


def list_body(kind, offset=0):
    """Filter of the website's own list request; ``offset`` only from the second page on."""
    body = {'filter': {'and': [{'type': [kind]}]}, 'sort': 'title[asc]', 'size': PAGE}
    if offset:
        body['offset'] = offset
    return body


def load_list(fetch, kind, gap, found):
    """All titles of one type; False when the list stopped early (paging not answered as expected)."""
    seen, total = set(), None
    for page in range(MAX_PAGES):
        if gap and page:
            time.sleep(gap)
        try:
            data = _data(_json(fetch(API + '?expand=false', list_body(kind, len(seen)))))
        except Exception:
            if page == 0:
                raise
            return False
        items = data.get('items') if isinstance(data, dict) else None
        items = items if isinstance(items, list) else []
        total = _int(data.get('total_items'), 0) if isinstance(data, dict) else None
        fresh = 0
        for node in items:
            ident = str(node.get('id') or '') if isinstance(node, dict) else ''
            if ident and ident not in seen:
                seen.add(ident)
                fresh += 1
                it = item_from(node)
                if it and it['kind'] == kind:
                    found[it['id']] = it
        if not fresh:
            return total is None or len(seen) >= total
        if total is None or len(seen) >= total:
            return True
    return False


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre', 'summary',
          'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'ages', 'offer', 'seasons', 'until',
          'video_id', 'original_title', 'web_url')


def _store(db, items, now):
    """Insert or refresh rows; the remembered copy-protection result (drm) of a title stays."""
    for item in items:
        db.execute('''INSERT INTO toggo_assets(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def _counts(items):
    return {'movies': sum(1 for i in items if i['kind'] == 'movie'),
            'series': sum(1 for i in items if i['kind'] == 'series'),
            'plus': sum(1 for i in items if i['offer'] == 'plus')}


def sync(root, fetch=None, now=None, gap=None, check=None):
    """Load all series and films. Rows stay, but only titles seen in the latest successful run
    are listed (catch-up episodes and licences rotate)."""
    now = time.time() if now is None else float(now)
    fetch = fetch or _fetch
    gap = (REQUEST_GAP if fetch is _fetch else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('toggo_sync_started')
    try:
        found, partial, notes = {}, False, []
        for kind in ('series', 'movie'):
            try:
                partial |= not load_list(fetch, kind, gap, found)
            except Exception as exc:
                if kind == 'series':
                    raise
                partial = True
                notes.append('Filme: ' + _error(exc))
            if gap:
                time.sleep(gap)
        if not any(i['kind'] == 'series' for i in found.values()):
            raise ValueError('TOGGO lieferte keine Serien')
        items = list(found.values())
        counts = _counts(items)
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for key, value in [('last_success', visible_since), ('last_loaded', time.time()),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        protection = ''
        try:
            protection = probe(root, fetch, check=check)
        except Exception:
            pass
        _notify('toggo_sync_completed', partial=partial, protection=protection or 'unknown', **counts)
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
        _notify('toggo_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- views

def _row(db, row_id):
    row = db.execute('SELECT * FROM toggo_assets WHERE id=?', (row_id,)).fetchone()
    return dict(row) if row else None


def _series(db, series_id):
    row = db.execute("SELECT * FROM toggo_assets WHERE id=? AND kind='series'", (series_id,)).fetchone()
    if not row:
        raise ValueError('TOGGO-Serie nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def _playable(row, protection):
    """Only a title whose own check found a plain stream, or an unchecked free title while the
    probe of the latest run found plain streams. TOGGO protects everything as recorded."""
    if row.get('kind') not in ('episode', 'movie') or row.get('offer') != 'free':
        return 0
    if row.get('drm') == 0:
        return 1
    return 1 if row.get('drm') is None and protection == 'clear' else 0


def load_episodes(root, series_id, fetch=None, now=None):
    """All seasons and episodes of a series: one request, as the series page of the website."""
    now = time.time() if now is None else now
    fetch = fetch or _fetch
    db = _connect(root)
    try:
        series = _series(db, series_id)
    finally:
        db.close()
    if not series['path']:
        raise ValueError('TOGGO nannte für diese Serie keine Seite')
    data = _data(_json(fetch('%s/%s?filter=rootParentTypes[not|hidden]' % (API, _q(series['path'])))))
    nodes = data.get('episodes') if isinstance(data, dict) else None
    found = [it for it in (item_from(n, series) for n in nodes if isinstance(nodes, list)) if it and it['kind'] == 'episode'] \
        if isinstance(nodes, list) else []
    db = _connect(root)
    try:
        with db:
            _store(db, found, now)
            _set(db, 'series_checked:' + series_id, now)
    finally:
        db.close()
    return found


def episodes(root, series_id, fetch=None, now=None):
    """Episodes of a series, loaded on demand and cached for six hours."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige TOGGO-Serie')
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
            load_episodes(root, series_id, fetch, now)
        except Exception as exc:
            error = _error(exc)
    db = _connect(root)
    try:
        checked = float(_get(db, 'series_checked:' + series_id, '0') or 0)
        protection = _get(db, 'protection')
        rows = [dict(r) for r in db.execute(
            """SELECT * FROM toggo_assets WHERE kind='episode' AND series_id=? AND seen>=?
               ORDER BY season IS NULL, season, episode IS NULL, episode, title COLLATE NOCASE""", (series_id, checked))]
    finally:
        db.close()
    extra = _summary(root, series)
    free = sum(1 for r in rows if r['offer'] == 'free')
    for row in rows:
        row.update({**extra, **_labels(row)})
        row['poster'] = row['poster'] or series['poster']
        row['playable'] = _playable(row, protection)
    note = ''
    if rows:
        note = '%d von %d Folgen sind bei TOGGO kostenlos, die übrigen nur mit Abo.' % (free, len(rows)) if free < len(rows) else ''
    return {'series': {'id': series_id, 'title': series['title'], 'web_url': series['web_url'], **extra},
            'items': rows, 'error': error, 'note': note}


def _labels(row):
    """TOGGO's own filter values (0.5.83: offer and age group are no categories): offer, age groups
    and the short line on the card ('kostenlos bis 20.11.' / 'Nur mit Abo')."""
    plus = row.get('offer') == 'plus'
    badge = PAID if plus else 'kostenlos'
    until = row.get('until')
    if not plus and until and row.get('kind') != 'series' and until - time.time() < 60 * 86400:
        badge += ' bis ' + time.strftime('%d.%m.', time.localtime(until))
    return {'offer_label': PAID if plus else FREE, 'badge': badge,
            'age_labels': [AGE_GROUPS[g] for g in str(row.get('ages') or '').split(',') if g in AGE_GROUPS]}


def _summary(root, row, reports=None):
    """Canonical categories and rating. TOGGO is a children's platform: every title is
    'Kinder & Familie' even before the reference check."""
    import categories as fixed
    import toggo_enrichment
    report = (reports if reports is not None else toggo_enrichment.all_cached(root)).get(row['id'])
    out = portal_reference.summary(row.get('genre') or GENRE, report)
    out['categories'] = sorted({c for c in out['categories'] if not fixed.is_special(c)} | {CHILDREN}, key=fixed.sort_key)
    return out


FILTERS = (FREE, PAID, 'TOGGO', 'TOGGOLINO')


def _filter(row, value):
    """Own filter values of the TOGGO tab (sent like a category)."""
    if value in (FREE, PAID):
        return row.get('offer_label') == value
    group = 'preschool' if value == 'TOGGOLINO' else 'school'
    return group in str(row.get('ages') or '').split(',')


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    """One page of films or series, with canonical categories, age groups and ratings."""
    import toggo_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    kind = {'movies': 'movie', 'series': 'series'}.get(view)
    if not kind:
        return {'items': [], 'total': 0, 'offset': offset, 'view': view, 'genre_counts': []}
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        protection = _get(db, 'protection')
        sql = 'FROM toggo_assets WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR original_title LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = toggo_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
        row.update(_labels(row))
        row['playable'] = _playable(row, protection)
    counts = portal_reference.facets(rows)
    if genre in FILTERS:
        rows = [r for r in rows if _filter(r, genre) and portal_reference.in_collection(r, collection, kind)]
    else:
        rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts}


def channels(root):
    return []


def item(root, row_id):
    """Detail view of one series, film or episode: catalogue row, series, reference report."""
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
    return {'item': {**row, **summary, **_labels(row), 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'playable': _playable(row, protection), 'protection': protection},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        protection = _get(db, 'protection')
        movies, series = _int(_get(db, 'movies', '0')) or 0, _int(_get(db, 'series', '0')) or 0
        out = {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '0') == '1',
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'last_loaded': float(_get(db, 'last_loaded', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': movies, 'series': series, 'channels': 0, 'plus': _int(_get(db, 'plus', '0')) or 0,
            'protection': protection or 'unknown',
            'protected': 0 if protection == 'clear' else movies + series,
            'episodes_cached': db.execute("SELECT COUNT(*) FROM toggo_assets WHERE kind='episode'").fetchone()[0]}
        if protection != 'clear':
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

def _stream_url(value):
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.port or parts.username or parts.password \
            or len(value) > 4000 or re.search(r'[\s<>"\'\\]', value):
        return ''
    return value


def pick_variant(variants):
    """(HLS address, number of protected variants): only a variant the service lists WITHOUT any
    licence and whose address is an HLS playlist. As recorded every variant carries Widevine,
    PlayReady or FairPlay, so this returns ('', 4)."""
    protected, plain = 0, ''
    for v in variants if isinstance(variants, list) else []:
        if not isinstance(v, dict):
            continue
        if v.get('licenses') or 'fairplay' in str(v.get('name') or '').lower():
            protected += 1
            continue
        for s in v.get('sources') or []:
            url = _stream_url(s.get('url')) if isinstance(s, dict) else ''
            if url and urllib.parse.urlsplit(url).path.endswith('.m3u8') and not plain:
                plain = url
    return plain, protected


def _remember(root, row_id, drm):
    """Result of one title's check (0 = plain stream, 1 = copy protected)."""
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE toggo_assets SET drm=? WHERE id=?', (drm, row_id))
    finally:
        db.close()


def resolve(root, row, fetch=None, check=None, now=None):
    """Playable source of one episode or film, or hls_guard.DrmProtected. The result is remembered."""
    import hls_guard
    now = time.time() if now is None else now
    cached = _SOURCES.get(row['id'])
    if cached and cached[0] > now:
        return cached[1]
    if not ASSET_ID.fullmatch(str(row.get('video_id') or '')):
        raise ValueError('TOGGO nannte für diesen Titel kein Video')
    url, protected = pick_variant(_json((fetch or _fetch)(VARIANTS % row['video_id'])))
    if url:
        try:
            (check or hls_guard.check)(url)
        except hls_guard.DrmProtected:
            url = ''
            protected += 1
    if not url:
        _notify('toggo_playback', result='protected' if protected else 'no_source', protected_variants=protected)
        if protected:
            _remember(root, row['id'], 1)
            raise hls_guard.DrmProtected(DRM_NOTE)
        raise ValueError('TOGGO lieferte für diesen Titel keinen Stream')
    _remember(root, row['id'], 0)
    _notify('toggo_playback', result='clear')
    out = {'kind': 'url', 'url': url, 'hls': True, 'quality': 'TOGGO', 'title': row['title'],
           'duration': row.get('duration') or 0, 'provider': 'toggo'}
    _SOURCES[row['id']] = (now + SOURCE_TTL, out)
    return out


def probe(root, fetch=None, now=None, check=None, samples=3):
    """Check up to ``samples`` free films to learn whether TOGGO protects its streams: 'clear' if
    one is listed without copy protection, 'drm' if all checked ones are protected, '' if
    nothing could be checked. Unchecked titles get the player button only after 'clear'."""
    import hls_guard
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            """SELECT * FROM toggo_assets WHERE kind='movie' AND offer='free' AND video_id<>'' AND seen>=?
               ORDER BY title LIMIT ?""", (last, samples))]
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
    """Source for streaming.resolve: a stream only if TOGGO lists one without copy protection."""
    import hls_guard
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
    if row['offer'] != 'free':
        raise hls_guard.DrmProtected('Diesen Titel gibt es bei TOGGO nur mit Abo; bitte bei TOGGO ansehen.')
    try:
        source = resolve(root, row, fetch, check, now)
    except urllib.error.HTTPError as exc:
        raise ValueError(_error(exc)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(_error(exc)) from None
    if parent and parent.get('title') and parent['title'] not in source['title']:
        source = {**source, 'title': '%s · %s' % (parent['title'], source['title'])}
    return source
