"""YouTube-Kanal-Abos mit automatischem Offline-Speichern und Kinderansicht (0.6.7).

Björn (14.11.2026): Seine Tochter schaut viele Kindervideos, das Internet ist schlecht und das
Streaming hängt. Ihre Lieblingskanäle sollen abonniert werden; neue Videos werden selbsttätig
heruntergeladen, als „neu“ gekennzeichnet und in einer eigenen, kindgerechten Oberfläche
(/kinder, web/kids.*) im Vollbild abgespielt. Die Idee stammt aus HomeTube (Abos + Abspieler).

Je Abo einstellbar:

* **Was** geladen wird: ``new`` (nur neue Videos ab dem Abo, dazu die ``start_count`` neuesten zum
  Start) oder ``all`` (alle Videos, neueste zuerst). Eine **Reihe** ist eine Playlist-Adresse oder
  ein Titelfilter („Peppa, Folge“); ``exclude`` schließt Wörter aus.
* Länge: ``min_seconds`` (Standard 61 s, damit Shorts draußen bleiben), ``max_seconds`` (0 = egal).
* ``keep``: höchstens so viele Videos dieses Abos liegen gleichzeitig offline. Kommt ein neues
  dazu, wird dafür das älteste **bereits gesehene** entfernt; ungesehene bleiben immer.
* ``quality``: 480/720/1080 (Standard 720, spart Platz und Leitung), ``kids``: in der Kinderansicht.

Rahmen, unverändert seit 0.5.53 (Björns Entscheidung 12.11.2026): Laden nur mit eingeschaltetem
YouTube-Offline-Schalter (Zustimmung mit Zeitpunkt), keine Cookies, keine Anmeldung, nichts
umgangen; jede Kopie ist ein gewöhnlicher Auftrag der gemeinsamen Warteschlange mit derselben
Frist (youtube_downloads.OFFLINE_DAYS). Abgelaufene Videos werden nicht erneut geladen.

Liste der Videos: mit API-Schlüssel über die YouTube Data API (1 Einheit je 50 Videos), sonst über
yt-dlp (``--flat-playlist``, kein Schlüssel nötig). Abo-Downloads werden als MP4 (H.264/AAC
bevorzugt) gespeichert, damit Safari, iPad und schwache NAS sie ohne Umwandlung abspielen;
Ablage ``<Download>/YouTube-Abos/<Kanal>/<Datum> - <Titel> [<ID>].mp4``.

Hintergrund: ein Eintrag im Planer (planner.CatalogJob 'youtube_abos'), geprüft wird ein Abo nach
dem anderen, je Prüfung höchstens ``MAX_QUEUE`` neue Aufträge. Nur Standardbibliothek.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

import youtube

MODES = ('new', 'all')
QUALITIES = ('480', '720', '1080')
FOLDER = 'YouTube-Abos'
MAX_ABOS = 80
MAX_LIST = 500                 # Videos, die eine Prüfung höchstens liest
NEW_LIST = 50                  # bei späteren Prüfungen von „nur neue“ reicht die erste Seite
MAX_QUEUE = 8                  # neue Aufträge je Abo und Prüfung (der Rest folgt bei der nächsten)
INTERVALS = (1, 3, 6, 12, 24)  # Stunden
BACKLOG_RECHECK = 20 * 60      # stehen noch Videos aus, kommt das Abo bald wieder dran
LIST_TIMEOUT = 180
SHORTS_SECONDS = 61
AVATAR_HOSTS = re.compile(r'^(?:[a-z0-9-]+\.)*(?:ytimg\.com|ggpht\.com|googleusercontent\.com)$')
LIVE_STATES = ('queued', 'downloading', 'tagging', 'done')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_abos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'channel',
  label TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', channel_id TEXT NOT NULL DEFAULT '',
  playlist TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'new',
  start_count INTEGER NOT NULL DEFAULT 5, keep INTEGER NOT NULL DEFAULT 30, include TEXT NOT NULL DEFAULT '',
  exclude TEXT NOT NULL DEFAULT '', min_seconds INTEGER NOT NULL DEFAULT 61, max_seconds INTEGER NOT NULL DEFAULT 0,
  quality TEXT NOT NULL DEFAULT '720', kids INTEGER NOT NULL DEFAULT 1, interval_hours INTEGER NOT NULL DEFAULT 3,
  enabled INTEGER NOT NULL DEFAULT 1, added REAL NOT NULL, checked REAL NOT NULL DEFAULT 0,
  next_check REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', last_new INTEGER NOT NULL DEFAULT 0,
  via TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS youtube_abo_videos(
  abo_id INTEGER NOT NULL, video TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '',
  duration INTEGER, poster TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'wanted', reason TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL DEFAULT '',
  found REAL NOT NULL, done_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(abo_id, video));
CREATE INDEX IF NOT EXISTS youtube_abo_videos_state ON youtube_abo_videos(abo_id, state);
'''
# Zustände eines Videos: old (vor dem Abo, „nur neue“), wanted (soll geladen werden), skipped (Filter),
# queued/done/failed (Auftrag), expired (Frist abgelaufen oder entfernt: nie erneut laden).

_DB = None                     # server.configure: Fabrik für catalog.db (Warteschlange „jobs“)
_SETTINGS = lambda: {}
_LOCK = threading.Lock()
_ACTIVE = False
_PROGRESS = ''


def configure(db=None, settings=None):
    global _DB, _SETTINGS
    if db is not None:
        _DB = db
    if settings is not None:
        _SETTINGS = settings


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    db = youtube._connect(root)            # dieselbe Datei youtube.sqlite3 (WAL)
    db.executescript(SCHEMA)
    return db


def _int(value, low, high, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _words(text):
    return [w.strip().lower() for w in re.split(r'[,;\n]', str(text or '')) if w.strip()][:20]


# ---------------------------------------------------------------- Abos verwalten

def parse(text):
    """Adresse -> (ref, kind). Kanal (@Handle, UC…, user:) oder Playlist; einzelne Videos nicht."""
    ref = youtube.parse_ref(text)
    if ref == 'store:free' or ref.startswith('v:'):
        raise ValueError('Bitte einen Kanal (youtube.com/@Kanal) oder eine Playlist abonnieren, kein einzelnes Video')
    return ref, ('channel' if ref.startswith(('@', 'UC', 'user:')) else 'playlist')


def _clean(data, current=None):
    cur = dict(current or {})
    out = {}
    if 'mode' in data or not current:
        mode = str(data.get('mode') or cur.get('mode') or 'new')
        if mode not in MODES:
            raise ValueError('Modus muss „nur neue“ oder „alle“ sein')
        out['mode'] = mode
    if 'quality' in data or not current:
        quality = str(data.get('quality') or cur.get('quality') or '720')
        if quality not in QUALITIES:
            raise ValueError('Qualität: 480, 720 oder 1080')
        out['quality'] = quality
    if 'interval_hours' in data or not current:
        hours = _int(data.get('interval_hours', 3), 1, 24, 3)
        out['interval_hours'] = min(INTERVALS, key=lambda h: abs(h - hours))
    for key, low, high, default in (('start_count', 0, 50, 5), ('keep', 1, 500, 30),
                                    ('min_seconds', 0, 6 * 3600, SHORTS_SECONDS), ('max_seconds', 0, 12 * 3600, 0)):
        if key in data or not current:
            out[key] = _int(data.get(key, default), low, high, default)
    for key in ('include', 'exclude'):
        if key in data or not current:
            out[key] = ', '.join(_words(data.get(key)))[:300]
    if 'label' in data or not current:
        out['label'] = ' '.join(str(data.get('label') or '').split())[:80]
    for key in ('kids', 'enabled'):
        if key in data or not current:
            out[key] = int(data.get(key, True) not in (False, 0, '0', 'false', ''))
    return out


def add(root, data, now=None):
    now = time.time() if now is None else float(now)
    ref, kind = parse(data.get('url'))
    fields = _clean(data)
    db = _connect(root)
    try:
        if db.execute('SELECT COUNT(*) FROM youtube_abos').fetchone()[0] >= MAX_ABOS:
            raise ValueError('Höchstens %d Abos' % MAX_ABOS)
        if db.execute('SELECT 1 FROM youtube_abos WHERE ref=?', (ref,)).fetchone():
            raise ValueError('Dieser Kanal bzw. diese Playlist ist schon abonniert')
        with db:
            cur = db.execute('INSERT INTO youtube_abos(ref,kind,added,next_check,%s) VALUES(?,?,?,?,%s)'
                             % (','.join(fields), ','.join('?' * len(fields))), (ref, kind, now, now, *fields.values()))
        abo_id = cur.lastrowid
    finally:
        db.close()
    _notify('youtube_abo_added', kind=kind, mode=fields['mode'], kids=bool(fields['kids']))
    return abo_id


def change(root, abo_id, data, now=None):
    """Einstellungen ändern, pausieren (enabled), „jetzt prüfen“ (check) oder entfernen (remove)."""
    abo_id = _int(abo_id, 1, 10 ** 9, 0)
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM youtube_abos WHERE id=?', (abo_id,)).fetchone()
        if not row:
            raise ValueError('Abo nicht gefunden')
        action = str(data.get('action') or 'update')
        with db:
            if action == 'remove':
                # Die geladenen Videos bleiben als gewöhnliche Downloads (mit ihrer Frist) erhalten.
                db.execute('DELETE FROM youtube_abo_videos WHERE abo_id=?', (abo_id,))
                db.execute('DELETE FROM youtube_abos WHERE id=?', (abo_id,))
                return {'removed': True}
            if action == 'check':
                db.execute('UPDATE youtube_abos SET next_check=0,enabled=1 WHERE id=?', (abo_id,))
                return {'ok': True}
            fields = _clean(data, dict(row))
            if not fields:
                return {'ok': True}
            if fields.get('mode') == 'all' and row['mode'] == 'new':
                # „alle“ holt jetzt auch die älteren Videos nach
                db.execute("UPDATE youtube_abo_videos SET state='wanted' WHERE abo_id=? AND state='old'", (abo_id,))
            if any(k in fields for k in ('include', 'exclude', 'min_seconds', 'max_seconds')):
                db.execute("UPDATE youtube_abo_videos SET state='wanted',reason='' WHERE abo_id=? AND state='skipped'", (abo_id,))
            fields['next_check'] = 0
            db.execute('UPDATE youtube_abos SET %s WHERE id=?' % ','.join('%s=?' % k for k in fields),
                       (*fields.values(), abo_id))
        return {'ok': True}
    finally:
        db.close()


# ---------------------------------------------------------------- Videos eines Abos lesen

def _channel_url(ref):
    if ref.startswith('@'):
        return 'https://www.youtube.com/%s/videos' % ref
    if ref.startswith('UC'):
        return 'https://www.youtube.com/channel/%s/videos' % ref
    if ref.startswith('user:'):
        return 'https://www.youtube.com/user/%s/videos' % ref[5:]
    return youtube.playlist_url(ref)


def _poster(video):
    return 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % video


def _published(entry):
    for key in ('timestamp', 'release_timestamp'):
        value = entry.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(value))
    date = str(entry.get('upload_date') or '')
    if re.fullmatch(r'\d{8}', date):
        return '%s-%s-%sT00:00:00Z' % (date[:4], date[4:6], date[6:])
    return ''


def _avatar(thumbs):
    """Kanalbild aus yt-dlp-Vorschaubildern: quadratisch (avatar), sonst das kleinste."""
    best = ''
    for t in thumbs if isinstance(thumbs, list) else []:
        if not isinstance(t, dict):
            continue
        url = str(t.get('url') or '')
        host = (urllib.parse.urlsplit(url).hostname or '').lower()
        if not url.startswith('https://') or not AVATAR_HOSTS.fullmatch(host):
            continue
        if 'avatar' in str(t.get('id') or ''):
            return url
        w, h = t.get('width'), t.get('height')
        if w and h and w == h and not best:
            best = url
    return best


def list_with_ytdlp(abo, limit, runner=None, root=None):
    """(Kanalangaben, Videos) über yt-dlp, ohne API-Schlüssel."""
    import youtube_downloads
    tool = youtube_downloads.find_tool(root) if root is not None else None
    if not tool:
        raise ValueError('Ohne YouTube-API-Schlüssel braucht das Abo yt-dlp; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    args = [*tool[0], '--ignore-config', '--flat-playlist', '-J', '--no-warnings', '--no-cookies-from-browser',
            '--playlist-end', str(limit), _channel_url(abo['ref'])]
    run = runner or subprocess.run
    result = run(args, capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL,
                 env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode != 0:
        raise ValueError('YouTube-Liste nicht lesbar: ' + youtube_downloads._reason(result.stderr[-3000:]))
    try:
        data = json.loads(result.stdout or '{}')
    except ValueError:
        raise ValueError('yt-dlp lieferte keine lesbare Liste') from None
    title = str(data.get('channel') or data.get('uploader') or data.get('title') or '')
    title = re.sub(r'\s+-\s+(?:Videos|Uploads from .*)$', '', title)[:120]
    info = {'title': title, 'channel_id': str(data.get('channel_id') or '')[:40] if re.fullmatch(youtube.CHANNEL_ID, str(data.get('channel_id') or '')) else '',
            'playlist': abo['ref'] if abo['kind'] == 'playlist' else '', 'avatar': _avatar(data.get('thumbnails'))}
    videos, seen = [], set()
    for number, entry in enumerate(data.get('entries') or []):
        if not isinstance(entry, dict):
            continue
        vid = str(entry.get('id') or '')
        if not youtube.VALID_VIDEO.fullmatch(vid) or vid in seen:
            continue
        if str(entry.get('live_status') or '') in ('is_live', 'is_upcoming', 'post_live'):
            continue
        seen.add(vid)
        duration = entry.get('duration')
        videos.append({'video': vid, 'title': ' '.join(str(entry.get('title') or '').split())[:200],
                       'published': _published(entry), 'position': number,
                       'duration': int(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
                       'poster': _poster(vid)})
    return info, videos[:limit]


def list_with_api(root, abo, limit, request):
    """(Kanalangaben, Videos) über die Data API: Uploads-Playlist bzw. die Playlist, dann videos.list."""
    info = {'title': abo.get('title') or '', 'channel_id': abo.get('channel_id') or '',
            'playlist': abo.get('playlist') or '', 'avatar': abo.get('avatar') or ''}
    if not info['playlist'] or not info['avatar']:
        if abo['kind'] == 'channel':
            query = {'part': 'snippet,contentDetails', 'maxResults': 1}
            ref = abo['ref']
            if ref.startswith('@'):
                query['forHandle'] = ref
            elif ref.startswith('user:'):
                query['forUsername'] = ref[5:]
            else:
                query['id'] = ref
            items = (request('channels', query) or {}).get('items') or []
            node = items[0] if items and isinstance(items[0], dict) else None
            if not node:
                raise ValueError('Kanal nicht gefunden')
            uploads = str(((node.get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads') or '')
            if not re.fullmatch(youtube.PLAYLIST_ID, uploads):
                raise ValueError('Kanal ohne öffentliche Uploads')
            snippet = node.get('snippet') or {}
            thumbs = snippet.get('thumbnails') if isinstance(snippet.get('thumbnails'), dict) else {}
            avatar = ''
            for size in ('high', 'medium', 'default'):
                url = str((thumbs.get(size) or {}).get('url') or '') if isinstance(thumbs.get(size), dict) else ''
                host = (urllib.parse.urlsplit(url).hostname or '').lower()
                if url.startswith('https://') and AVATAR_HOSTS.fullmatch(host):
                    avatar = url
                    break
            info.update(title=youtube._text(snippet.get('title'), 120), channel_id=str(node.get('id') or '')[:40],
                        playlist=uploads, avatar=avatar)
        else:
            resolved = youtube.resolve_source(request, {'ref': abo['ref']})
            info.update(title=resolved['title'], channel_id=resolved['channel_id'], playlist=resolved['playlist'])
    entries = youtube.playlist_entries(request, info['playlist'], limit=limit)
    ydb = youtube._connect(root)
    try:
        facts = youtube.load_facts(request, ydb, [v for v, _ in entries], time.time())
    finally:
        ydb.close()
    videos = []
    for number, (vid, position) in enumerate(entries):
        f = facts.get(vid)
        if not f:
            continue                         # privat, gesperrt, live
        videos.append({'video': vid, 'title': ' '.join(str(f.get('title') or '').split())[:200],
                       'published': f.get('published') or '', 'duration': f.get('duration'),
                       'poster': f.get('poster') or _poster(vid),
                       'position': number if abo['kind'] == 'channel' else position,
                       'age': str(f.get('reason') or '').startswith('Altersbeschränkt')})
    return info, videos


def screen(abo, video):
    """Grund, warum ein Video nicht geladen wird, oder ''."""
    title = video.get('title', '').lower()
    duration = video.get('duration')
    if video.get('age'):
        return 'altersbeschränkt'
    if duration and abo['min_seconds'] and duration < abo['min_seconds']:
        return 'kürzer als %s' % _span(abo['min_seconds'])
    if duration and abo['max_seconds'] and duration > abo['max_seconds']:
        return 'länger als %s' % _span(abo['max_seconds'])
    include, exclude = _words(abo['include']), _words(abo['exclude'])
    if include and not any(w in title for w in include):
        return 'passt nicht zur Reihe'
    if any(w in title for w in exclude):
        return 'ausgeschlossen'
    return ''


def _span(seconds):
    return '%d Min.' % round(seconds / 60) if seconds >= 120 else '%d s' % seconds


def _order_key(video, kind):
    # Neueste zuerst: Datum, sonst Reihenfolge (Kanäle liefern neueste zuerst, Playlists älteste zuerst).
    return (video.get('published') or '', -video['position'] if kind == 'channel' else video['position'])


# ---------------------------------------------------------------- Aufträge

def _job_states(c, job_ids):
    ids = [j for j in job_ids if j]
    out = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        for row in c.execute('SELECT id,state,payload FROM jobs WHERE id IN (%s)' % ','.join('?' * len(chunk)), chunk):
            out[row[0]] = (row[1], row[2])
    return out


def build_job(root, download_dir, abo, video, now=None):
    import core, youtube_downloads
    from package_media import clean_path_part
    now = time.time() if now is None else float(now)
    channel = abo.get('label') or abo.get('title') or 'YouTube'
    title = video.get('title') or video['video']
    date = (video.get('published') or '')[:10]
    year = int(date[:4]) if re.fullmatch(r'\d{4}-\d\d-\d\d', date) else None
    meta = core.validate_meta({
        'kind': 'movie', 'title': title[:180], 'episode_title': '', 'year': year, 'season': None, 'episode': None,
        'description': '', 'genres': ['YouTube-Abo'] + (['Kinder'] if abo.get('kids') else []),
        'poster': video.get('poster') or _poster(video['video']), 'fanart': '', 'provider': youtube_downloads.NAME,
        'reference_id': None, 'state': 'manual',
        'reason': 'YouTube-Abo %s; Offline-Kopie auf eigene Verantwortung, zeitlich begrenzt.' % channel})
    name = clean_path_part(('%s - ' % date if date else '') + title)[:150] or 'Video'
    target = Path(download_dir) / FOLDER / (clean_path_part(channel)[:80] or 'YouTube') / ('%s [%s].mp4' % (name, video['video']))
    item_id = 'v.' + video['video']
    source = {'_id': 'youtube:' + item_id, '_resolver': 'youtube', '_youtube_id': item_id, '_youtube_home': str(root),
              '_video_id': video['video'], '_target': str(target), '_container': 'mp4',
              'channel': channel, 'title': title, 'duration': video.get('duration'), 'url': youtube.video_url(video['video'])}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta, 'root': str(download_dir),
            'quality': abo.get('quality') or '720', 'target': str(target), 'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'youtube', 'youtube_id': item_id, 'youtube_abo': int(abo['id']),
            'license': {'kind': youtube_downloads.LICENSE, 'days': youtube_downloads.OFFLINE_DAYS, 'granted': now,
                        'note': 'YouTube-Abo: Offline-Kopie auf eigene Verantwortung (Schalter), %d Tage'
                                % youtube_downloads.OFFLINE_DAYS}}


def _make_room(c, db, abo, now):
    """Platz für ein neues Video: das älteste schon gesehene Video dieses Abos entfernen."""
    import netzkino_downloads, watch_state
    try:
        seen = watch_state.states(Path(abo['_root']))
    except Exception:
        seen = {}
    rows = db.execute("SELECT video,job_id FROM youtube_abo_videos WHERE abo_id=? AND state='done' ORDER BY done_at",
                      (abo['id'],)).fetchall()
    for row in rows:
        mark = seen.get('job:' + row['job_id']) or {}
        if mark.get('done') and not mark.get('pinned') and not mark.get('favorite'):
            try:
                netzkino_downloads.delete_now(c, row['job_id'], now)
            except ValueError:
                pass
            db.execute("UPDATE youtube_abo_videos SET state='expired',reason='gesehen, Platz für Neues' WHERE abo_id=? AND video=?",
                       (abo['id'], row['video']))
            return True
    return False


def sync_states(c, db, abo_id=None):
    """Zustände aus der Warteschlange übernehmen (fertig, Fehler, abgelaufen)."""
    where, args = ("WHERE state IN ('queued','done','failed')", ()) if abo_id is None else \
        ("WHERE abo_id=? AND state IN ('queued','done','failed')", (abo_id,))
    rows = db.execute('SELECT abo_id,video,state,job_id FROM youtube_abo_videos ' + where, args).fetchall()
    states = _job_states(c, [r['job_id'] for r in rows])
    changed = 0
    with db:
        for r in rows:
            job_state, payload = states.get(r['job_id'], (None, None))
            if job_state in ('queued', 'downloading', 'tagging'):
                new = 'queued'
            elif job_state == 'done':
                new = 'done'
            elif job_state == 'error':
                new = 'failed'
            else:                       # abgelaufen, entfernt oder Auftrag gelöscht
                new = 'expired'
            if new != r['state']:
                reason = ''
                if new == 'failed':
                    try:
                        reason = str(json.loads(payload).get('error') or '')[:200]
                    except (TypeError, ValueError):
                        reason = ''
                db.execute('UPDATE youtube_abo_videos SET state=?,reason=?,done_at=CASE WHEN ?=\'done\' THEN ? ELSE done_at END '
                           'WHERE abo_id=? AND video=?', (new, reason, new, time.time(), r['abo_id'], r['video']))
                changed += 1
    return changed


# ---------------------------------------------------------------- Prüfung

def _request_for_key():
    key = str((_SETTINGS() or {}).get('youtube') or '').strip()
    if not key:
        return None
    return lambda endpoint, query: youtube._request(endpoint, query, key)


def check(root, abo_id, now=None, request=None, runner=None, c=None, download_dir=None):
    """Ein Abo prüfen: Videos lesen, neue merken, Aufträge anlegen. Gibt Zahlen zurück."""
    import youtube_downloads
    now = time.time() if now is None else float(now)
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM youtube_abos WHERE id=?', (abo_id,)).fetchone()
        if not row:
            raise ValueError('Abo nicht gefunden')
        abo = dict(row)
        abo['_root'] = str(root)
        first = not abo['checked']
        limit = MAX_LIST if (first or abo['mode'] == 'all') else NEW_LIST
        request = request if request is not None else _request_for_key()
        try:
            if request is not None:
                info, videos = list_with_api(root, abo, limit, request)
                via = 'api'
            else:
                info, videos = list_with_ytdlp(abo, limit, runner=runner, root=root)
                via = 'yt-dlp'
        except Exception as exc:
            message = youtube._error(exc) if not isinstance(exc, ValueError) else str(exc)[:240]
            with db:
                db.execute('UPDATE youtube_abos SET last_error=?,checked=?,next_check=? WHERE id=?',
                           (message, now, now + 3600, abo_id))
            _notify('youtube_abo_check_failed', reason=type(exc).__name__)
            return {'ok': False, 'error': message}
        known = {r['video']: r['state'] for r in db.execute('SELECT video,state FROM youtube_abo_videos WHERE abo_id=?', (abo_id,))}
        ordered = sorted(videos, key=lambda v: _order_key(v, abo['kind']), reverse=True)
        newest = {v['video'] for v in ordered[:abo['start_count']]}
        added = 0
        with db:
            for v in videos:
                if v['video'] in known:
                    db.execute('UPDATE youtube_abo_videos SET title=?,published=CASE WHEN ?!=\'\' THEN ? ELSE published END,'
                               'duration=COALESCE(?,duration),poster=? WHERE abo_id=? AND video=?',
                               (v['title'], v['published'], v['published'], v['duration'], v['poster'], abo_id, v['video']))
                    continue
                state = 'old' if (first and abo['mode'] == 'new' and v['video'] not in newest) else 'wanted'
                reason = screen(abo, v) if state == 'wanted' else ''
                if reason:
                    state = 'skipped'
                db.execute('INSERT INTO youtube_abo_videos(abo_id,video,title,published,duration,poster,position,state,reason,found) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?)', (abo_id, v['video'], v['title'], v['published'], v['duration'],
                                                          v['poster'], v['position'], state, reason, now))
                if state == 'wanted' and not first:
                    added += 1
            db.execute('UPDATE youtube_abos SET title=?,channel_id=?,playlist=?,avatar=?,via=?,last_error=\'\' WHERE id=?',
                       (info['title'] or abo['title'], info['channel_id'] or abo['channel_id'],
                        info['playlist'] or abo['playlist'], info['avatar'] or abo['avatar'], via, abo_id))
        abo.update(title=info['title'] or abo['title'], avatar=info['avatar'] or abo['avatar'])
        _cache_avatar(root, abo)
        queued, waiting, note = 0, 0, ''
        if c is None and _DB is None:
            note = 'Warteschlange nicht verfügbar'
        elif not youtube_downloads.enabled(root):
            note = 'YouTube-Offline-Speichern ist ausgeschaltet; neue Videos warten'
        else:
            queued, waiting = _enqueue(root, db, abo, now, c, download_dir)
        with db:
            pending = db.execute("SELECT COUNT(*) FROM youtube_abo_videos WHERE abo_id=? AND state='wanted'", (abo_id,)).fetchone()[0]
            later = BACKLOG_RECHECK if pending and not note and not waiting else abo['interval_hours'] * 3600
            db.execute('UPDATE youtube_abos SET checked=?,next_check=?,last_new=?,last_error=? WHERE id=?',
                       (now, now + later, added, note, abo_id))
        _notify('youtube_abo_checked', via=via, listed=len(videos), new=added, queued=queued, pending=pending)
        return {'ok': True, 'listed': len(videos), 'new': added, 'queued': queued, 'pending': pending, 'note': note}
    finally:
        db.close()


def _enqueue(root, db, abo, now, c=None, download_dir=None):
    """Gewünschte Videos (neueste zuerst) in die Warteschlange, höchstens MAX_QUEUE und ``keep``."""
    import netzkino_downloads as offline
    def work(c):
        sync_states(c, db, abo['id'])
        target_dir = download_dir or (_SETTINGS() or {}).get('download_dir')
        if not target_dir:
            return 0, 0
        wanted = [dict(r) for r in db.execute("SELECT * FROM youtube_abo_videos WHERE abo_id=? AND state='wanted'", (abo['id'],))]
        wanted.sort(key=lambda v: _order_key(v, abo['kind']), reverse=True)
        queued = waiting = 0
        for v in wanted[:MAX_QUEUE]:
            held = db.execute("SELECT COUNT(*) FROM youtube_abo_videos WHERE abo_id=? AND state IN ('queued','done')",
                              (abo['id'],)).fetchone()[0]
            if held >= abo['keep'] and not _make_room(c, db, abo, now):
                waiting += 1
                break
            try:
                job = build_job(root, target_dir, abo, v, now)
                result = offline.portal_duplicate(c, job) or offline.insert(c, job)
            except FileExistsError:
                db.execute("UPDATE youtube_abo_videos SET state='skipped',reason='Datei liegt schon vor' WHERE abo_id=? AND video=?",
                           (abo['id'], v['video']))
                continue
            except (ValueError, OSError) as exc:
                db.execute("UPDATE youtube_abo_videos SET state='failed',reason=? WHERE abo_id=? AND video=?",
                           (str(exc)[:200], abo['id'], v['video']))
                continue
            state = 'done' if result.get('state') == 'done' else 'queued'
            db.execute('UPDATE youtube_abo_videos SET state=?,job_id=?,done_at=? WHERE abo_id=? AND video=?',
                       (state, result['id'], now if state == 'done' else 0, abo['id'], v['video']))
            queued += int(bool(result.get('created')))
        db.commit()
        return queued, waiting
    if c is not None:
        return work(c)
    with _DB() as conn:
        return work(conn)


def due(root, now=None):
    now = time.time() if now is None else float(now)
    db = _connect(root)
    try:
        return [r[0] for r in db.execute('SELECT id FROM youtube_abos WHERE enabled=1 AND next_check<=? ORDER BY next_check',
                                         (now,))]
    finally:
        db.close()


def run_due(root, now=None):
    global _PROGRESS
    results = []
    ids = due(root, now)
    for number, abo_id in enumerate(ids, 1):
        _PROGRESS = 'Abo %d von %d' % (number, len(ids))
        try:
            results.append(check(root, abo_id, now))
        except Exception as exc:          # ein kaputtes Abo hält die anderen nicht auf
            _notify('youtube_abo_check_error', reason=type(exc).__name__)
    _PROGRESS = ''
    return results


# Planer-Schnittstelle (planner.CatalogJob): should_sync / start_sync / _ACTIVE
def should_sync(root, now=None):
    if _ACTIVE or _DB is None:
        return False
    try:
        return bool(due(root, now))
    except Exception:
        return False


def start_sync(root, queue=False):
    global _ACTIVE
    with _LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True

    def body():
        global _ACTIVE
        try:
            run_due(root)
        finally:
            _ACTIVE = False
    threading.Thread(target=body, name='youtube_abos', daemon=True).start()
    return True


def tick(root):
    """Jede Minute ohne fällige Prüfung: fertige Downloads übernehmen (für „Neu“ in der Kinderansicht)."""
    if _DB is None:
        return
    db = _connect(root)
    try:
        with _DB() as c:
            sync_states(c, db)
    finally:
        db.close()


# ---------------------------------------------------------------- Bilder (offline verfügbar)

def _image_dir(root):
    path = Path(root) / 'youtube_abos'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_avatar(root, abo, fetch=None):
    url = str(abo.get('avatar') or '')
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if not url.startswith('https://') or not AVATAR_HOSTS.fullmatch(host):
        return False
    dest = _image_dir(root) / ('avatar-%d.jpg' % int(abo['id']))
    if dest.exists() and time.time() - dest.stat().st_mtime < 30 * 86400:
        return True
    try:
        if fetch is None:
            import core
            with core.open_url(url, timeout=20) as response:
                data = response.read(2 * 1024 * 1024 + 1)
        else:
            data = fetch(url)
    except (OSError, ValueError):
        return False
    if len(data) > 2 * 1024 * 1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG') or data[8:12] == b'WEBP'):
        return False
    tmp = dest.with_suffix('.part')
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return True


def avatar_file(root, abo_id):
    path = Path(root) / 'youtube_abos' / ('avatar-%d.jpg' % _int(abo_id, 0, 10 ** 9, 0))
    return path if path.is_file() else None


def poster_file(job):
    """Das Vorschaubild, das der Download neben die Datei gelegt hat (<Datei>-poster.jpg)."""
    path = Path(str((job or {}).get('path') or ''))
    if not path.name:
        return None
    for ext in ('.jpg', '.png'):
        candidate = path.with_name(path.stem + '-poster' + ext)
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------- Ansichten

def overview(root, c=None):
    """Alle Abos mit Zahlen für die Verwaltung (YouTube → Abos)."""
    import youtube_downloads
    db = _connect(root)
    try:
        if c is not None:
            sync_states(c, db)
        abos = [dict(r) for r in db.execute('SELECT * FROM youtube_abos ORDER BY COALESCE(NULLIF(label,\'\'),title,ref) COLLATE NOCASE')]
        counts = {}
        for r in db.execute('SELECT abo_id,state,COUNT(*) FROM youtube_abo_videos GROUP BY abo_id,state'):
            counts.setdefault(r[0], {})[r[1]] = r[2]
        reasons = {}
        for r in db.execute("SELECT abo_id,reason,COUNT(*) FROM youtube_abo_videos WHERE state IN ('skipped','failed') AND reason!='' "
                            "GROUP BY abo_id,reason ORDER BY 3 DESC"):
            reasons.setdefault(r[0], []).append({'reason': r[1], 'count': r[2]})
    finally:
        db.close()
    for a in abos:
        a['counts'] = counts.get(a['id'], {})
        a['reasons'] = reasons.get(a['id'], [])[:5]
        a['name'] = a['label'] or a['title'] or a['ref']
        a['url'] = _channel_url(a['ref']).replace('/videos', '')
    offline = youtube_downloads.status(root)
    return {'abos': abos, 'offline': {'enabled': offline.get('enabled'), 'tool': bool(offline.get('tool'))},
            'key_set': bool(str((_SETTINGS() or {}).get('youtube') or '').strip()), 'running': _ACTIVE,
            'progress': _PROGRESS, 'days': youtube_downloads.OFFLINE_DAYS}


def kids(root, c, watch=None, only_kids=True):
    """Was die Kinderansicht zeigt: Kanäle und fertig geladene Videos, neue zuerst.
    0.6.8: only_kids=False liefert alle Abos (Ansehen-Modus für Erwachsene, watch_home.py)."""
    import watch_state
    db = _connect(root)
    try:
        sync_states(c, db)
        abos = [dict(r) for r in db.execute('SELECT id,label,title,ref,kids FROM youtube_abos' + (' WHERE kids=1' if only_kids else ''))]
        ids = [a['id'] for a in abos]
        rows = [dict(r) for r in db.execute(
            "SELECT abo_id,video,title,published,duration,job_id,done_at FROM youtube_abo_videos WHERE state='done' AND abo_id IN (%s)"
            % ','.join('?' * len(ids)), ids)] if ids else []
    finally:
        db.close()
    jobs = _job_states(c, [r['job_id'] for r in rows])
    marks = watch if watch is not None else watch_state.overview(root).get('progress', {})
    videos = []
    for r in rows:
        state, payload = jobs.get(r['job_id'], (None, None))
        if state != 'done':
            continue
        try:
            job = json.loads(payload)
        except (TypeError, ValueError):
            continue
        mark = marks.get('job:' + r['job_id']) or {}
        duration = r['duration'] or 0
        videos.append({'job': r['job_id'], 'video': r['video'], 'abo': r['abo_id'], 'title': r['title'],
                       'published': r['published'], 'duration': duration, 'added': r['done_at'],
                       'new': not mark, 'done': bool(mark.get('done')),
                       'progress': round(min(1, (mark.get('pos') or 0) / duration), 3) if duration and not mark.get('done') else 0,
                       'pos': mark.get('pos') or 0, 'poster': bool(poster_file(job)),
                       'until': job.get('offline_until')})
    videos.sort(key=lambda v: (v['published'] or '', v['added']), reverse=True)
    channels = []
    for a in abos:
        own = [v for v in videos if v['abo'] == a['id']]
        channels.append({'id': a['id'], 'name': a['label'] or a['title'] or a['ref'], 'videos': len(own), 'kids': bool(a['kids']),
                         'new': sum(1 for v in own if v['new']), 'avatar': bool(avatar_file(root, a['id']))})
    channels.sort(key=lambda ch: (-ch['new'], ch['name'].lower()))
    return {'channels': channels, 'videos': videos}


def summary(root):
    """Zahlen für den Diagnoseexport (ohne Namen und Adressen)."""
    db = _connect(root)
    try:
        abos = db.execute('SELECT COUNT(*),SUM(enabled),SUM(kids) FROM youtube_abos').fetchone()
        states = dict(db.execute('SELECT state,COUNT(*) FROM youtube_abo_videos GROUP BY state').fetchall())
        errors = db.execute("SELECT COUNT(*) FROM youtube_abos WHERE last_error!=''").fetchone()[0]
    finally:
        db.close()
    return {'abos': abos[0] or 0, 'enabled': abos[1] or 0, 'kids': abos[2] or 0, 'videos': states,
            'with_note': errors, 'running': _ACTIVE}
