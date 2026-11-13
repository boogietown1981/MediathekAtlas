"""RTL+: the free part of RTL+ ("RTL+ Free") as a catalogue with links (0.5.102).

Björn (13.11.2026, decision card "Beides"): RTL+ as a catalogue with links. Every RTL+ stream is
protected with Widevine (VOD ``dashcenc``/FairPlay, live as well), so MediathekAtlas never plays
RTL+ itself: each title opens plus.rtl.de ("Bei RTL+ ansehen", optional Chrome extension for the
play click). Nothing is circumvented, no offline copies.

Interfaces (from public open-source clients, e.g. the Kodi add-on "script.service.ultimate" and an
MIT-licensed RTL+ EPG client; plus.rtl.de is blocked in the build environment, nothing recorded live):

* Anonymous access: ``POST auth.rtl.de/…/openid-connect/token`` with the public client
  ``anonymous-user`` (client credentials) -> bearer; ``GET front-auth.rtlde.bedrock.tech/v2/rtlde/
  platforms/m6group_web/token`` with it -> Bedrock token. Both live only in memory for one run.
* Catalogue (Bedrock layout API): ``layout.rtlde.bedrock.tech/front/v1/rtlde/m6group_web/main/
  token-web-31/folder/<id>/layout`` for the folders Filme (4), Serien (3), Reality & Shows (1) and
  Kids (148). Blocks of type ``bffPaginated`` hold ``classic`` items; further pages come from
  ``/service/rtlplus_root/block/<blockId>?page=<nextPage>``. An item whose action target is of type
  ``lock`` needs RTL+ Premium: such titles are only counted, the catalogue lists RTL+ Free.
* Images: signed Bedrock image addresses (``images-fio.rtlde.bedrock.tech``), as the official site
  builds them.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import portal_reference

KEY = 'rtlplus'
NAME = 'RTL+'
SITE = 'https://plus.rtl.de'
TOKEN_URL = 'https://auth.rtl.de/auth/realms/rtlplus/protocol/openid-connect/token'
CLIENT_ID = 'anonymous-user'
CLIENT_SECRET = '4bfeb73f-1c4a-4e9f-a7fa-96aa1ad3d94c'   # public client of the RTL+ website
BEDROCK_AUTH = 'https://front-auth.rtlde.bedrock.tech/v2/rtlde/platforms/m6group_web/token'
LAYOUT = 'https://layout.rtlde.bedrock.tech/front/v1/rtlde/m6group_web/main/token-web-31'
IMAGE_BASE = 'https://images-fio.rtlde.bedrock.tech/v2/images'
IMAGE_PARAMS = 'auto=webp&blur=0&fit=scale_crop&height=480&interlace=1&optimize=high&width=320'
IMAGE_KEY = 'x9vGg4RNeNBqV2nBfhqLV6cN4n'
CLIENT_RELEASE = '6.44.1'
API_HOSTS = frozenset({'auth.rtl.de', 'front-auth.rtlde.bedrock.tech', 'layout.rtlde.bedrock.tech'})
# folder id -> (catalogue kind, path segment on plus.rtl.de, provider genre)
FOLDERS = (('4', 'movie', 'filme', ''), ('3', 'series', 'serien', ''), ('1', 'series', 'shows', 'Show'),
           ('148', 'series', 'serien', 'Kinder'))
FOLDER_NAMES = {'4': 'Filme', '3': 'Serien', '1': 'Shows', '148': 'Kids'}
# 0.5.107: the guest area "Kostenlose Inhalte" (folder 193) holds what RTL+ shows without an
# subscription; everything else in the main folders needs RTL+ (Björn: "+" titles do not play).
# Source: the RTL+ Free scraper of moviescout-modules (folder id, X-Location, block paging).
FREE_FOLDER = '193'
FREE_LOCATION = SITE + '/rtlplus-root/kostenlose-inhalte-main-root-service-f_' + FREE_FOLDER
MAX_ANSWER = 16 * 1024 * 1024
MAX_ITEMS = 20000
MAX_BLOCK_PAGES = 40
MAX_FOLDERS = 60            # main folders plus the genre folders they link to
REQUEST_GAP = 0.4
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'
VALID_ID = re.compile(r'[ms]\.\d{1,12}')
SEO = re.compile(r'[a-z0-9][a-z0-9\-]{0,160}')
BLOCK_ID = re.compile(r'[A-Za-z0-9_.\-]{4,200}')
DRM_NOTE = ('RTL+ liefert alle Videos nur mit Kopierschutz (Widevine) aus. MediathekAtlas umgeht ihn nicht: '
            'bitte bei RTL+ ansehen.')

_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS rtlplus_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', playable INTEGER NOT NULL DEFAULT 0,
  drm INTEGER NOT NULL DEFAULT 1, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL,
  offer TEXT NOT NULL DEFAULT 'free');
CREATE INDEX IF NOT EXISTS rtlplus_items_kind ON rtlplus_items(kind, seen);
CREATE TABLE IF NOT EXISTS rtlplus_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(root / 'rtlplus.sqlite3'), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    if 'offer' not in {r[1] for r in db.execute('PRAGMA table_info(rtlplus_items)')}:
        db.execute("ALTER TABLE rtlplus_items ADD COLUMN offer TEXT NOT NULL DEFAULT 'free'")   # 0.5.107
    _migrate_links(db)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM rtlplus_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO rtlplus_state(name,value) VALUES(?,?)', (key, str(value)))


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

def _open(url, headers, data=None, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in API_HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige RTL+-Anfrage')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('RTL+-Antwort zu groß')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('RTL+-Antwort zu groß')
    return raw


class Api:
    """Anonymous RTL+ session: OIDC bearer plus Bedrock token, renewed once when refused."""

    def __init__(self, opener=None):
        self.opener = opener or _open
        self.device = '_luid_' + str(uuid.uuid4())
        self.bearer = self.bedrock = ''

    def _json(self, url, headers, data=None):
        return json.loads(self.opener(url, headers, data).decode('utf-8'))

    def login(self):
        body = urllib.parse.urlencode({'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
                                       'grant_type': 'client_credentials'}).encode()
        answer = self._json(TOKEN_URL, {'User-Agent': USER_AGENT, 'Accept': 'application/json',
                                        'Content-Type': 'application/x-www-form-urlencoded',
                                        'Origin': SITE, 'Referer': SITE + '/'}, body)
        self.bearer = str((answer or {}).get('access_token') or '')
        if not re.fullmatch(r'[A-Za-z0-9_\-.]{20,6000}', self.bearer):
            raise ValueError('RTL+ gab keinen Gast-Zugang aus')
        answer = self._json(BEDROCK_AUTH, {'User-Agent': USER_AGENT, 'Accept': 'application/json',
                                           'Authorization': 'Bearer ' + self.bearer, 'X-Customer-Name': 'rtlde',
                                           'X-Client-Release': CLIENT_RELEASE, 'x-auth-device-name': 'Windows - Firefox',
                                           'x-auth-device-player-size-width': '1920',
                                           'x-auth-device-player-size-height': '1080', 'x-auth-device-id': self.device,
                                           'Origin': SITE, 'Referer': SITE + '/'})
        self.bedrock = str((answer or {}).get('token') or '')
        if not re.fullmatch(r'[A-Za-z0-9_\-.]{20,6000}', self.bedrock):
            raise ValueError('RTL+ gab kein Plattform-Token aus')

    def layout(self, path, query, location=SITE + '/'):
        if not re.fullmatch(r'/[A-Za-z0-9_.\-/]{1,300}', path) or '..' in path:
            raise ValueError('Ungültige RTL+-Anfrage')
        if not self.bearer:
            self.login()
        for attempt in (0, 1):
            headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Authorization': 'Bearer ' + self.bearer,
                       'X-Bedrock-Token': self.bedrock, 'X-Customer-Name': 'rtlde', 'X-Client-Release': CLIENT_RELEASE,
                       'X-Location': location, 'Origin': SITE, 'Referer': SITE + '/'}
            try:
                return self._json(LAYOUT + path + '?' + urllib.parse.urlencode(query), headers)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 498) and attempt == 0:
                    self.login()
                    continue
                raise


def _error(exc):
    code = getattr(exc, 'code', None)
    if code in (401, 403, 498):
        return 'RTL+ verweigert den Gast-Zugang (HTTP %d)' % code
    if code == 451:
        return 'RTL+ bietet seine Inhalte in diesem Land nicht an (HTTP 451)'
    if code:
        return 'RTL+ antwortet mit HTTP %d' % code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('RTL+ ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'RTL+-Katalog konnte nicht geladen werden'


# ---------------------------------------------------------------- parsing

def image_url(image_id):
    """Signed Bedrock image address, as plus.rtl.de builds it."""
    image_id = str(image_id or '')
    if not re.fullmatch(r'[A-Za-z0-9_\-]{4,120}', image_id):
        return ''
    suffix = '/%s/raw?%s' % (image_id, IMAGE_PARAMS)
    digest = hashlib.sha1(('/v2/images' + suffix + IMAGE_KEY).encode()).hexdigest()
    return IMAGE_BASE + suffix + '&hash=' + digest


def _image(content):
    image = content.get('image') if isinstance(content.get('image'), dict) else {}
    ratios = image.get('idsByRatio') if isinstance(image.get('idsByRatio'), dict) else {}
    for ratio in ('2:3', '16:9', '3:1', '1:1'):
        if ratios.get(ratio):
            return image_url(ratios[ratio])
    return image_url(image.get('id'))


def _target(content):
    action = content.get('action') if isinstance(content.get('action'), dict) else {}
    target = action.get('target') if isinstance(action.get('target'), dict) else {}
    locked = target.get('type') == 'lock'
    if locked:
        lock = target.get('value_lock') if isinstance(target.get('value_lock'), dict) else {}
        target = lock.get('originalTarget') if isinstance(lock.get('originalTarget'), dict) else {}
    layout = target.get('value_layout') if isinstance(target.get('value_layout'), dict) else {}
    return layout, locked


def web_url(section, seo, ident):
    """Page of a programme or film on plus.rtl.de: ``/<seo>-p_<id>``.

    Confirmed by Björn on 13.11.2026 (``plus.rtl.de/kurbis-chaos-in-der-heimat-p_1068``); the earlier
    ``/video-tv/<bereich>/<seo>-<id>`` ended on "Diese Seite existiert nicht". ``section`` stays for callers."""
    if not SEO.fullmatch(str(seo or '')) or not re.fullmatch(r'\d{1,12}', str(ident or '')):
        return SITE + '/'
    return '%s/%s-p_%s' % (SITE, seo, ident)


OLD_LINK = re.compile(r'https://plus\.rtl\.de/video-tv/[a-z]+/([a-z0-9][a-z0-9\-]{0,160})-(\d{1,12})')


def _migrate_links(db):
    """0.5.106: rewrite links stored by 0.5.102–0.5.105 to the confirmed scheme, once."""
    if _get(db, 'links_v2') == '1':
        return
    with db:
        for row in db.execute("SELECT id, web_url FROM rtlplus_items WHERE web_url LIKE 'https://plus.rtl.de/video-tv/%'").fetchall():
            match = OLD_LINK.fullmatch(row[1] or '')
            db.execute('UPDATE rtlplus_items SET web_url=? WHERE id=?',
                       (web_url('', match.group(1), match.group(2)) if match else SITE + '/', row[0]))
        _set(db, 'links_v2', 1)


def item_from(entry, kind, section, genre=''):
    """(item, locked) from a ``classic`` block item that leads to a programme or film; None otherwise.

    ``kind`` None (free area, 0.5.107): a film when ``extraDetails`` starts with "Film", else a series."""
    if not isinstance(entry, dict) or entry.get('itemType') != 'classic':
        return None
    content = entry.get('itemContent') if isinstance(entry.get('itemContent'), dict) else {}
    layout, locked = _target(content)
    if layout.get('type') not in ('program', 'video'):
        return None
    ident, seo = str(layout.get('id') or ''), str(layout.get('seo') or '')
    parent = layout.get('parent') if isinstance(layout.get('parent'), dict) else {}
    if layout.get('type') == 'video':
        # 0.5.104 (Björn: film links ended on "Diese Seite existiert nicht"): a tile that leads to a
        # video names the video, but plus.rtl.de pages belong to the programme (``parent``).
        if not re.fullmatch(r'\d{1,12}', str(parent.get('id') or '')):
            return None
        ident, seo = str(parent['id']), str(parent.get('seo') or '')
    title = _text(content.get('title') or content.get('extraTitle') or '', 200)
    if not re.fullmatch(r'\d{1,12}', ident) or not title:
        return None
    if kind is None:
        kind = 'movie' if str(content.get('extraDetails') or '').strip().lower().startswith('film') else 'series'
        section = 'filme' if kind == 'movie' else 'serien'
    highlight = _text(content.get('highlight'), 200)
    genres = [g.strip() for g in highlight.split('•') if g.strip() and not re.search(r'\d', g)][:4]
    if genre and genre not in genres:
        genres.append(genre)
    return {'id': ('m.' if kind == 'movie' else 's.') + ident, 'kind': kind, 'title': title, 'path': ident,
            'series_id': '', 'season': None, 'episode': None, 'year': None, 'duration': None, 'rating': '',
            'genre': ', '.join(genres), 'summary': _text(content.get('description') or content.get('subtitle'), 1600),
            'poster': _image(content), 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': genres[0] if genres else '', 'playable': 0, 'drm': 1,
            'web_url': web_url(section, seo, ident), 'offer': 'free'}, locked


def _blocks(answer):
    blocks = answer.get('blocks') if isinstance(answer, dict) else None
    if isinstance(blocks, list):
        return [b for b in blocks if isinstance(b, dict)]
    return [answer] if isinstance(answer, dict) and isinstance(answer.get('content'), dict) else []


def _items(block):
    content = block.get('content') if isinstance(block.get('content'), dict) else {}
    items = content.get('items')
    return items if isinstance(items, list) else []


def _next_page(block):
    content = block.get('content') if isinstance(block.get('content'), dict) else {}
    pagination = content.get('pagination') if isinstance(content.get('pagination'), dict) else {}
    return _int(pagination.get('nextPage'), 1, 100000)


def folder_target(entry):
    """Id of a sub-folder (e.g. a genre) an item leads to, or ''."""
    if not isinstance(entry, dict) or entry.get('itemType') != 'classic':
        return ''
    content = entry.get('itemContent') if isinstance(entry.get('itemContent'), dict) else {}
    layout, _ = _target(content)
    ident = str(layout.get('id') or '')
    if layout.get('type') == 'folder' and re.fullmatch(r'\d{1,9}', ident):
        return ident
    return ''


def load_folder(api, folder, kind, section, genre, gap, found, locked_ids, subfolders=None, stats=None, location=None,
                locked_items=None):
    """All titles of one folder, block by block; False when it stopped early.

    Further layout pages come with ``blockPage``, further pages of a block from
    ``/folder/<id>/block/<blockId>`` (0.5.107; the ``service/rtlplus_root`` path of 0.5.102 answered
    404 in Björn's diagnosis). A 404 there ends only that block. Sub-folders go to ``subfolders``."""
    complete = True
    stats = stats if stats is not None else {}
    location = location or SITE + '/video-tv/' + section
    path = '/folder/%s' % folder
    answer = api.layout(path + '/layout', {'blockPage': 1, 'nbPages': 2}, location)
    blocks, layout_page, layout_pages = _blocks(answer), _top_next(answer), 0
    while layout_page and layout_pages < 10:
        if gap:
            time.sleep(gap)
        more = api.layout(path + '/layout', {'blockPage': layout_page, 'nbPages': 2}, location)
        blocks += _blocks(more)
        layout_page, layout_pages = _top_next(more), layout_pages + 1
    for block in blocks:
        if block.get('type') not in (None, 'bffPaginated'):
            continue
        entries, page, pages = _items(block), _next_page(block), 0
        block_id = str(block.get('id') or block.get('blockId') or '')
        while True:
            for entry in entries:
                sub = folder_target(entry)
                if sub and subfolders is not None:
                    subfolders.append(sub)
                    continue
                got = item_from(entry, kind, section, genre)
                if not got:
                    continue
                it, locked = got
                if locked:
                    locked_ids.add(it['id'])
                    if locked_items is not None:
                        locked_items.setdefault(it['id'], it)
                else:
                    found.setdefault(it['id'], it)
            if not page or not BLOCK_ID.fullmatch(block_id) or len(found) >= MAX_ITEMS:
                break
            if pages >= MAX_BLOCK_PAGES:
                complete = False
                break
            if gap:
                time.sleep(gap)
            try:
                more = api.layout('%s/block/%s' % (path, block_id), {'nbPages': 3, 'page': page}, location)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                stats['block_404'] = stats.get('block_404', 0) + 1
                break
            pages += 1
            inner = _blocks(more)
            entries = [e for b in inner for e in _items(b)]
            page = _next_page(inner[0]) if inner else None
    return complete


def _top_next(answer):
    pagination = answer.get('pagination') if isinstance(answer, dict) and isinstance(answer.get('pagination'), dict) else {}
    return _int(pagination.get('nextPage'), 2, 1000)


FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'playable', 'drm', 'web_url',
          'offer')
ABO = 'Nur mit RTL+ Abo'
FREE = 'Kostenlos'


def _store(db, items, now):
    update = ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)
    for item in items:
        db.execute('''INSERT INTO rtlplus_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), update),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def sync(root, opener=None, now=None, gap=None):
    """Load the free RTL+ titles (guest area); titles that need RTL+ are only counted."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('rtlplus_sync_started')
    try:
        api = Api(opener)
        api.login()
        found, locked, partial, notes, stats = {}, set(), False, [], {}
        # 1) the free guest area with its sub-folders: this is the catalogue.
        queue, visited = [(FREE_FOLDER, 'Kostenlose Inhalte')], set()
        while queue and len(visited) < MAX_FOLDERS and len(found) < MAX_ITEMS:
            folder, name = queue.pop(0)
            if folder in visited:
                continue
            visited.add(folder)
            subfolders = []
            try:
                partial |= not load_folder(api, folder, None, '', '', gap, found, locked, subfolders, stats,
                                           location=FREE_LOCATION)
            except Exception as exc:
                if folder == FREE_FOLDER:
                    raise
                if getattr(exc, 'code', None) == 404:
                    stats['folder_404'] = stats.get('folder_404', 0) + 1   # a linked folder that is gone
                    continue
                partial = True
                notes.append('%s: %s' % (name, _error(exc)))
                continue
            queue += [(sub, 'Kostenlose Inhalte (Unterordner %s)' % sub) for sub in subfolders if sub not in visited]
        if not found:
            raise ValueError('RTL+ lieferte keine kostenlosen Titel')
        # 2) the main folders only to count what needs RTL+ (never listed, Björn: "+" titles do not play).
        paid, free_paths = {}, {i['path'] for i in found.values()}
        for folder, kind, section, genre in FOLDERS:
            try:
                load_folder(api, folder, kind, section, genre, gap, paid, locked, None, stats, locked_items=paid)
            except Exception as exc:
                stats['premium_folder_errors'] = stats.get('premium_folder_errors', 0) + 1
                _notify('rtlplus_premium_count_failed', folder=folder, http_status=getattr(exc, 'code', 0) or 0)
        # Kept as "Nur mit RTL+ Abo"; listed only when "Meine Abos → RTL+" is ticked (0.5.107).
        abo = {}
        for it in paid.values():
            if it['path'] not in free_paths and it['id'] not in found:
                abo.setdefault(it['id'], {**it, 'offer': 'abo'})
        items = list(found.values()) + list(abo.values())
        counts = {'movies': sum(1 for i in found.values() if i['kind'] == 'movie'),
                  'series': sum(1 for i in found.values() if i['kind'] == 'series'),
                  'premium': len({i['path'] for i in abo.values()})}
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                # The first run on the free area hides the subscription titles of 0.5.102–0.5.106 at once.
                first_free = _get(db, 'free_v1') != '1'
                visible_since = previous if partial and previous and not first_free else now
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'),
                                   ('last_error', ('Katalog nur teilweise geladen' + (': ' + notes[0] if notes else '')) if partial else ''),
                                   ('last_http_status', 0), ('next_attempt', now + 24 * 3600), ('free_v1', 1), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('rtlplus_sync_completed', partial=partial, folders=len(visited), **stats, **counts)
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
        _notify('rtlplus_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute('SELECT * FROM rtlplus_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _summary(root, row, reports=None):
    import rtlplus_enrichment
    report = (reports if reports is not None else rtlplus_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))


def episodes(root, series_id, now=None):
    """RTL+ episodes are not loaded: the series page links to plus.rtl.de."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige RTL+-Serie')
    db = _connect(root)
    try:
        series = _row(db, series_id)
    finally:
        db.close()
    if not series:
        raise ValueError('RTL+-Serie nicht im Katalog; bitte Katalog neu laden')
    return {'series': {'id': series_id, 'title': series['title'], **_summary(root, series)}, 'items': [], 'error': '',
            'note': 'Die Folgen stehen bei RTL+ (kostenlos mit Werbung, je nach Folge auch nur mit RTL+ Premium).'}


def has_abo(root):
    import ui_prefs
    return bool(ui_prefs.load(root).get('abo_rtlplus'))


def _labels(row, abo):
    paid = row.get('offer') == 'abo'
    return {'offer_label': ABO if paid else FREE,
            'badge': ('In deinem RTL+ Abo' if abo else ABO) if paid else 'kostenlos'}


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    import rtlplus_enrichment
    kind = {'movies': 'movie', 'series': 'series'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM rtlplus_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if not has_abo(root):
            sql += " AND offer='free'"   # 0.5.107: subscription titles only with "Meine Abos → RTL+"
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = rtlplus_enrichment.all_cached(root)
    abo = has_abo(root)
    for row in rows:
        row.update(_summary(root, row, reports))
        row.update(_labels(row, abo))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': counts}


def item(root, item_id):
    import rtlplus_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger RTL+-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row:
        raise ValueError('RTL+-Titel nicht im Katalog; bitte Katalog neu laden')
    report = rtlplus_enrichment.cached(root, item_id)
    return {'item': {**row, **_summary(root, row, {row['id']: report}), **_labels(row, has_abo(root)), 'playable': 0},
            'series': None, 'reference': report}


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
            'premium': _int(_get(db, 'premium', '0')) or 0, 'channels': 0,
            'free_catalog': _get(db, 'free_v1') == '1'}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='rtlplus_catalog_sync').start()
    return True


def loop(root, stop):
    import task_control
    while not stop.wait(60):
        if task_control.paused('catalog:rtlplus'):
            continue
        current = state(root)
        if portal_reference.first_load_due(current) or portal_reference.retry_after_update(root, sys.modules[__name__], current) or (
                current['last_success'] and not current['running'] and not current.get('free_catalog')
                and time.time() - current['last_attempt'] > 600) or (
                current['auto'] and not current['running'] and time.time() >= current['next_attempt']):
            start_sync(root)


def play_source(root, item_id):
    """RTL+ streams are Widevine-protected: never a source, always the reason."""
    import hls_guard
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger RTL+-Titel')
    _notify('rtlplus_playback', result='protected')
    raise hls_guard.DrmProtected(DRM_NOTE)
