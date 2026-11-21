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
* ``budget_gb`` (0.6.45): höchstens so viel Speicher belegen die Videos dieses Abos (Standard 10 GB,
  0 = ohne Grenze). Ist es erreicht, macht wie bei ``keep`` das älteste gesehene Video Platz; sonst warten
  neue Videos. Dazu gilt für alle Abos eine **Reserve**: unterschreitet der freie Speicher am Abo-Ziel
  ``abo_reserve_gb`` (Standard 5 GB), startet kein Abo-Download, bis wieder Platz ist.

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

import storage_locations
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
# 0.6.44 (Björn, 20.11.2026: „die Abos starten auch immer zur selben Zeit … bei mehreren aktuellen YouTube-Videos
# für Versatz sorgen“): Abos, die zusammen angelegt wurden, blieben mit gleichem Intervall für immer im Gleichtakt
# und wurden direkt nacheinander geprüft. Jetzt liegen zwischen zwei Abo-Prüfungen mindestens STAGGER Sekunden.
STAGGER = 5 * 60

# 0.6.45 (Björn, 20.11.2026: Speicherbudget für Abos, damit die Platte nicht vollläuft; sein Mac hatte zeitweise nur
# ~2 GB frei): Budget je Abo und eine gemeinsame Reserve an freiem Speicher am Abo-Ziel.
BUDGET_DEFAULT_GB = 10
MAX_BUDGET_GB = 2000
RESERVE_CHOICES = (1, 2, 5, 10, 20, 50)
RESERVE_DEFAULT_GB = 5
RESERVE_RECHECK = 30 * 60      # wartet ein Abo-Download auf Platz, prüft er alle 30 Minuten erneut
# Geschätzte Größe eines noch nicht geladenen Videos (Byte je Sekunde, MP4 H.264/AAC bei YouTube üblich)
RATE = {'480': 110_000, '720': 250_000, '1080': 500_000}
GB = 1000 ** 3                 # Anzeige wie im Finder (Dezimal-GB)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_abos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL, profile TEXT NOT NULL DEFAULT 'kinder', kind TEXT NOT NULL DEFAULT 'channel',
  label TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', channel_id TEXT NOT NULL DEFAULT '',
  playlist TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'new',
  start_count INTEGER NOT NULL DEFAULT 5, keep INTEGER NOT NULL DEFAULT 30, include TEXT NOT NULL DEFAULT '',
  exclude TEXT NOT NULL DEFAULT '', min_seconds INTEGER NOT NULL DEFAULT 61, max_seconds INTEGER NOT NULL DEFAULT 0,
  quality TEXT NOT NULL DEFAULT '720', kids INTEGER NOT NULL DEFAULT 1, interval_hours INTEGER NOT NULL DEFAULT 3,
  enabled INTEGER NOT NULL DEFAULT 1, added REAL NOT NULL, checked REAL NOT NULL DEFAULT 0,
  next_check REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', last_new INTEGER NOT NULL DEFAULT 0,
  via TEXT NOT NULL DEFAULT '', budget_gb REAL NOT NULL DEFAULT 10, UNIQUE(ref, profile));
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


# 0.6.11 (Björn, 16.11.2026): Abos gehören einem Profil. „kinder“ erscheint nur in der Kinderecke,
# „erwachsene“ nur im Ansehen-Modus; derselbe Kanal darf in beiden Profilen abonniert sein.
PROFILES = {'kinder': 'Kinderecke', 'erwachsene': 'Für mich (Ansehen-Modus)'}

_COLUMNS = ('id', 'ref', 'kind', 'label', 'title', 'channel_id', 'playlist', 'avatar', 'mode', 'start_count', 'keep',
            'include', 'exclude', 'min_seconds', 'max_seconds', 'quality', 'kids', 'interval_hours', 'enabled', 'added',
            'checked', 'next_check', 'last_error', 'last_new', 'via', 'budget_gb')


def _migrate(db):
    """Bis 0.6.10: ``ref`` war eindeutig, ``kids`` schaltete die Kinderecke zu (Erwachsene sahen alles).
    Jetzt Profil je Abo; kids=1 -> 'kinder', kids=0 -> 'erwachsene'. IDs bleiben (Videos hängen daran)."""
    columns = {r[1] for r in db.execute('PRAGMA table_info(youtube_abos)')}
    if 'profile' in columns:
        if 'budget_gb' not in columns:
            # 0.6.45: Speicherbudget je Abo. ADD COLUMN ändert nur das Schema (kein Tabellendurchlauf).
            with db:
                db.execute('ALTER TABLE youtube_abos ADD COLUMN budget_gb REAL NOT NULL DEFAULT %s' % BUDGET_DEFAULT_GB)
            return True
        return False
    keep = [c for c in _COLUMNS if c in columns]
    with db:
        db.execute('ALTER TABLE youtube_abos RENAME TO youtube_abos_bis_0610')
        db.executescript(SCHEMA)
        db.execute('INSERT INTO youtube_abos(%s,profile) SELECT %s,CASE WHEN kids=1 THEN \'kinder\' ELSE \'erwachsene\' END '
                   'FROM youtube_abos_bis_0610' % (','.join(keep), ','.join(keep)))
        db.execute('DROP TABLE youtube_abos_bis_0610')
    return True


def _connect(root):
    db = youtube._connect(root)            # dieselbe Datei youtube.sqlite3 (WAL)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='youtube_abos'").fetchone():
        _migrate(db)
    db.executescript(SCHEMA)
    return db


def profile_of(data, current=None):
    value = str((data or {}).get('profile') or '')
    if not value and 'kids' in (data or {}):     # ältere Aufrufer (bis 0.6.10) schicken nur kids
        value = 'kinder' if data.get('kids') not in (False, 0, '0', 'false', '') else 'erwachsene'
    value = value or (current or {}).get('profile') or 'kinder'
    if value not in PROFILES:
        raise ValueError('Unbekanntes Profil')
    return value


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
    if 'budget_gb' in data or not current:
        try:
            budget = float(str(data.get('budget_gb', BUDGET_DEFAULT_GB)).replace(',', '.'))
        except ValueError:
            raise ValueError('Speicherbudget: bitte eine Zahl in GB (0 = ohne Grenze)') from None
        if budget != budget or budget < 0:
            raise ValueError('Speicherbudget: bitte eine Zahl in GB (0 = ohne Grenze)')
        out['budget_gb'] = round(min(budget, MAX_BUDGET_GB), 1)
    for key in ('include', 'exclude'):
        if key in data or not current:
            out[key] = ', '.join(_words(data.get(key)))[:300]
    if 'label' in data or not current:
        out['label'] = ' '.join(str(data.get('label') or '').split())[:80]
    if 'enabled' in data or not current:
        out['enabled'] = int(data.get('enabled', True) not in (False, 0, '0', 'false', ''))
    if 'profile' in data or 'kids' in data or not current:
        out['profile'] = profile_of(data, cur)
        out['kids'] = int(out['profile'] == 'kinder')       # Spalte bleibt für ältere Auswertungen
    return out


def add(root, data, now=None):
    now = time.time() if now is None else float(now)
    ref, kind = parse(data.get('url'))
    fields = _clean(data)
    db = _connect(root)
    try:
        if db.execute('SELECT COUNT(*) FROM youtube_abos').fetchone()[0] >= MAX_ABOS:
            raise ValueError('Höchstens %d Abos' % MAX_ABOS)
        if db.execute('SELECT 1 FROM youtube_abos WHERE ref=? AND profile=?', (ref, fields['profile'])).fetchone():
            raise ValueError('Dieser Kanal bzw. diese Playlist ist im Profil „%s“ schon abonniert' % PROFILES[fields['profile']])
        with db:
            cur = db.execute('INSERT INTO youtube_abos(ref,kind,added,next_check,%s) VALUES(?,?,?,?,%s)'
                             % (','.join(fields), ','.join('?' * len(fields))), (ref, kind, now, now, *fields.values()))
        abo_id = cur.lastrowid
    finally:
        db.close()
    _notify('youtube_abo_added', kind=kind, mode=fields['mode'], profile=fields['profile'])
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
            if fields.get('profile', row['profile']) != row['profile'] and db.execute(
                    'SELECT 1 FROM youtube_abos WHERE ref=? AND profile=? AND id!=?', (row['ref'], fields['profile'], abo_id)).fetchone():
                raise ValueError('Dieser Kanal ist im Profil „%s“ schon abonniert' % PROFILES[fields['profile']])
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
        message, _retry, block = youtube_downloads._failure(result.stderr[-3000:])
        if block:                        # 0.6.13: Bot-Prüfung auch beim Lesen der Liste: YouTube eine Weile schonen
            import download_retry
            download_retry.block('youtube', time.time() + download_retry.BACKOFF[0], message)
        raise ValueError('YouTube-Liste nicht lesbar: ' + message)
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
    # 0.6.44: names without emojis, hashtags and special characters (core.tidy_name). A channel folder that
    # already exists under its old name stays in use, so one channel never ends up in two folders.
    name = clean_path_part(('%s - ' % date if date else '') + core.tidy_name(title))[:150].rstrip(' .-') or 'Video'
    folder = Path(download_dir) / FOLDER
    old_channel = clean_path_part(channel)[:80] or 'YouTube'
    channel_dir = old_channel if (folder / old_channel).is_dir() else (clean_path_part(core.tidy_name(channel))[:80].rstrip(' .-') or 'YouTube')
    target = folder / channel_dir / ('%s [%s].mp4' % (name, video['video']))
    item_id = 'v.' + video['video']
    source = {'_id': 'youtube:' + item_id, '_resolver': 'youtube', '_youtube_id': item_id, '_youtube_home': str(root),
              '_video_id': video['video'], '_target': str(target), '_container': 'mp4', '_abo': int(abo['id']),
              'channel': channel, 'title': title, 'duration': video.get('duration'), 'url': youtube.video_url(video['video'])}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta, 'root': str(download_dir),
            'quality': abo.get('quality') or '720', 'target': str(target), 'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'youtube', 'youtube_id': item_id, 'youtube_abo': int(abo['id']),
            'license': {'kind': youtube_downloads.LICENSE, 'days': youtube_downloads.OFFLINE_DAYS, 'granted': now,
                        'note': 'YouTube-Abo: Offline-Kopie auf eigene Verantwortung (Schalter), %d Tage'
                                % youtube_downloads.OFFLINE_DAYS}}


# ---------------------------------------------------------------- Speicherbudget (0.6.45)

def estimate(video, quality='720'):
    """Geschätzte Größe eines noch nicht geladenen Videos in Byte (ohne Dauer: 10 Minuten)."""
    try:
        seconds = float(video.get('duration') or 0)
    except (TypeError, ValueError):
        seconds = 0
    return int((seconds if seconds > 0 else 600) * RATE.get(str(quality), RATE['720']))


def _file_size(payload):
    try:
        job = json.loads(payload)
    except (TypeError, ValueError):
        return 0
    path = str(job.get('path') or job.get('target') or '')
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return int(job.get('total') or job.get('received') or 0)


def held(c, db, abo):
    """(Byte fertiger Videos, geschätzte Byte wartender Aufträge) dieses Abos."""
    rows = db.execute("SELECT video,state,job_id,duration FROM youtube_abo_videos WHERE abo_id=? AND state IN ('queued','done')",
                      (abo['id'],)).fetchall()
    states = _job_states(c, [r['job_id'] for r in rows if r['state'] == 'done']) if c is not None else {}
    done = queued = 0
    sizes = []
    for r in rows:
        if r['state'] == 'done':
            size = _file_size(states.get(r['job_id'], (None, None))[1])
            done += size
            sizes.append((size, r['duration']))
    rate = _learned_rate(sizes)
    for r in rows:
        if r['state'] != 'done':
            queued += sized({'duration': r['duration']}, abo.get('quality'), rate)
    return done, queued


def _learned_rate(sizes):
    """0.6.58: Byte je Sekunde, die die fertigen Videos dieses Abos wirklich belegen (None ohne Vergleich).

    Björns Diagnose vom 20.11. nachts: ein Abo belegte 18,7 GB bei 10 GB Budget. Die Schätzung mit der festen
    Rate (720p: 250 kB/s) lag für Kinderkanäle zu niedrig; mit der gemessenen Rate rechnet das Budget ehrlich.
    """
    total = seconds = 0
    for size, duration in sizes:
        try:
            duration = float(duration or 0)
        except (TypeError, ValueError):
            duration = 0
        if size > 0 and duration > 0:
            total += size
            seconds += duration
    return total / seconds if seconds >= 60 else None


def sized(video, quality='720', rate=None):
    """Geschätzte Größe; mit gemessener Rate des Abos nie kleiner als diese (höchstens das Vierfache der festen)."""
    base = estimate(video, quality)
    if not rate:
        return base
    try:
        seconds = float(video.get('duration') or 0)
    except (TypeError, ValueError):
        seconds = 0
    fixed = RATE.get(str(quality), RATE['720'])
    learned = int((seconds if seconds > 0 else 600) * min(float(rate), fixed * 4))
    return max(base, learned)


def abo_rate(c, db, abo):
    """Gemessene Rate der fertigen Videos eines Abos (für neue Aufträge)."""
    if c is None:
        return None
    rows = db.execute("SELECT job_id,duration FROM youtube_abo_videos WHERE abo_id=? AND state='done'", (abo['id'],)).fetchall()
    states = _job_states(c, [r['job_id'] for r in rows])
    return _learned_rate([(_file_size(states.get(r['job_id'], (None, None))[1]), r['duration']) for r in rows])


def trim_queued(c, db, abo, budget):
    """0.6.58: Liegt ein Abo über seinem Budget, gehen noch nicht gestartete Aufträge zurück auf „gewünscht“.

    Aufträge aus der Zeit vor dem Budget (0.6.43 und älter) oder mit zu kleiner Schätzung liefen sonst einfach
    weiter. Die neuesten Videos behalten ihren Platz, die ältesten Wünsche warten. Gibt die Zahl zurück.
    """
    if not budget or c is None:
        return 0
    done, queued_before = held(c, db, abo)
    rows = [dict(r) for r in db.execute("SELECT * FROM youtube_abo_videos WHERE abo_id=? AND state='queued'", (abo['id'],))]
    if not rows:
        return 0
    states = _job_states(c, [r['job_id'] for r in rows])
    rows.sort(key=lambda v: _order_key(v, abo['kind']), reverse=True)
    rate = abo_rate(c, db, abo)
    used = done
    released = 0
    for r in rows:
        job_state = states.get(r['job_id'], (None, None))[0]
        size = sized(r, abo.get('quality'), rate)
        if job_state != 'queued':                      # läuft schon oder ist fertig: zählt, bleibt
            used += size if job_state != 'done' else 0
            continue
        if used + size <= budget or not used:
            used += size
            continue
        if c.execute("DELETE FROM jobs WHERE id=? AND state='queued'", (r['job_id'],)).rowcount:
            db.execute("UPDATE youtube_abo_videos SET state='wanted',job_id='',reason=? WHERE abo_id=? AND video=?",
                       (BUDGET_REASON, abo['id'], r['video']))
            released += 1
    if released:
        db.commit()
        # 0.6.71 (Mac-Prüfung 0.6.68): used_gb 0.0 las sich wie ein Fehler – die Planung lag über dem Budget
        _notify('youtube_abo_budget_trimmed', released=released, used_gb=round(done / GB, 1),
                planned_gb=round(queued_before / GB, 1), budget_gb=abo.get('budget_gb'))
    return released


BUDGET_REASON = 'wartet: Speicherbudget des Abos erreicht'


def budget_bytes(abo):
    try:
        value = float(abo.get('budget_gb') or 0)
    except (TypeError, ValueError):
        value = 0
    return int(value * GB) if value > 0 else 0


def reserve_gb(root):
    db = youtube._connect(root)
    try:
        value = youtube._get(db, 'abo_reserve_gb', str(RESERVE_DEFAULT_GB))
    finally:
        db.close()
    try:
        value = int(float(value))
    except ValueError:
        return RESERVE_DEFAULT_GB
    return value if value in RESERVE_CHOICES else RESERVE_DEFAULT_GB


def set_reserve(root, value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError('Bitte eine Reserve in GB wählen') from None
    if value not in RESERVE_CHOICES:
        raise ValueError('Erlaubt sind %s GB Reserve' % ', '.join(map(str, RESERVE_CHOICES)))
    db = youtube._connect(root)
    try:
        with db:
            youtube._set(db, 'abo_reserve_gb', value)
    finally:
        db.close()
    return value


def free_bytes(path):
    """Freier Speicher am Ziel; ein noch nicht angelegter Ordner zählt über seinen nächsten vorhandenen Elternordner."""
    if not path:
        return None
    p = Path(path)
    for candidate in (p, *p.parents):
        try:
            if candidate.exists():
                import shutil
                return shutil.disk_usage(candidate).free
        except OSError:
            return None
    return None


def no_room(root, target_dir, extra=0):
    """Hinweis, wenn nach ``extra`` Byte weniger als die Reserve frei bliebe, sonst ''."""
    free = free_bytes(target_dir)
    reserve = reserve_gb(root) * GB
    if free is None or free - extra >= reserve:
        return ''
    return ('Weniger als %d GB frei am Abo-Speicherort (%.1f GB frei): Abo-Downloads warten, bis wieder Platz ist'
            % (reserve // GB, free / GB))


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
            # 0.6.11: hält ein anderes Abo (anderes Profil, gleicher Kanal) dieselbe Datei, bleibt sie liegen;
            # nur dieses Abo gibt seinen Platz frei.
            shared = db.execute("SELECT 1 FROM youtube_abo_videos WHERE job_id=? AND abo_id!=? AND state='done'",
                                (row['job_id'], abo['id'])).fetchone()
            if shared:
                db.execute("UPDATE youtube_abo_videos SET state='expired',reason='gesehen, Platz für Neues' WHERE abo_id=? AND video=?",
                           (abo['id'], row['video']))
                return True
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
    rows = db.execute('SELECT abo_id,video,state,job_id,reason FROM youtube_abo_videos ' + where, args).fetchall()
    states = _job_states(c, [r['job_id'] for r in rows])
    changed = 0
    with db:
        for r in rows:
            job_state, payload = states.get(r['job_id'], (None, None))
            if job_state in ('queued', 'downloading', 'tagging'):
                new = 'queued'
                # 0.6.13: wartet der Auftrag nach einem vorübergehenden Fehler, steht der Grund am Video.
                try:
                    job = json.loads(payload)
                    waiting = str(job.get('last_error') or '')[:200] if job_state == 'queued' and job.get('retries') else ''
                except (TypeError, ValueError):
                    waiting = ''
                if new == r['state'] and waiting != (r['reason'] or ''):
                    db.execute('UPDATE youtube_abo_videos SET reason=? WHERE abo_id=? AND video=?', (waiting, r['abo_id'], r['video']))
                    changed += 1
                    continue
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
        if request is None:
            # 0.6.13: Pausiert YouTube uns gerade (Bot-Prüfung), wartet auch die Liste über yt-dlp.
            import download_retry
            until, why = download_retry.blocked_until('youtube', now)
            if until:
                message = 'YouTube pausiert bis %s Uhr (%s); die Prüfung folgt danach' % (time.strftime('%H:%M', time.localtime(until)), why)
                with db:
                    db.execute('UPDATE youtube_abos SET last_error=?,next_check=? WHERE id=?', (message, until + 60, abo_id))
                return {'ok': False, 'error': message, 'paused': True}
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
                       (now, _staggered(db, abo_id, now + later), added, note, abo_id))
        _notify('youtube_abo_checked', via=via, listed=len(videos), new=added, queued=queued, pending=pending)
        return {'ok': True, 'listed': len(videos), 'new': added, 'queued': queued, 'pending': pending, 'note': note}
    finally:
        db.close()


def _enqueue(root, db, abo, now, c=None, download_dir=None):
    """Gewünschte Videos (neueste zuerst) in die Warteschlange, höchstens MAX_QUEUE und ``keep``."""
    import netzkino_downloads as offline
    def work(c):
        sync_states(c, db, abo['id'])
        # 0.6.20: eigener Zwischenspeicher (Einstellungen → Speicherorte), sonst der Downloadordner
        target_dir = download_dir or storage_locations.abo_base(_SETTINGS() or {})
        if not target_dir:
            return 0, 0
        wanted = [dict(r) for r in db.execute("SELECT * FROM youtube_abo_videos WHERE abo_id=? AND state='wanted'", (abo['id'],))]
        wanted.sort(key=lambda v: _order_key(v, abo['kind']), reverse=True)
        queued = waiting = 0
        budget = budget_bytes(abo)
        if budget:
            trim_queued(c, db, abo, budget)
            wanted = [dict(r) for r in db.execute("SELECT * FROM youtube_abo_videos WHERE abo_id=? AND state='wanted'", (abo['id'],))]
            wanted.sort(key=lambda v: _order_key(v, abo['kind']), reverse=True)
        rate = abo_rate(c, db, abo) if budget else None
        for v in wanted[:MAX_QUEUE]:
            count = db.execute("SELECT COUNT(*) FROM youtube_abo_videos WHERE abo_id=? AND state IN ('queued','done')",
                               (abo['id'],)).fetchone()[0]
            if count >= abo['keep'] and not _make_room(c, db, abo, now):
                waiting += 1
                break
            size = sized(v, abo.get('quality'), rate)
            if budget:
                # 0.6.45: Speicherbudget je Abo. Gesehene Videos machen Platz (wie bei ``keep``), gemerkte,
                # angeheftete und ungesehene bleiben; reicht das nicht, wartet das Video. Ein einzelnes Video,
                # das allein größer ist als das Budget, darf geladen werden, wenn sonst nichts liegt.
                used = sum(held(c, db, abo))
                while used and used + size > budget and _make_room(c, db, abo, now):
                    used = sum(held(c, db, abo))
                if used and used + size > budget:
                    waiting += 1
                    _notify('youtube_abo_budget_full', used_gb=round(used / GB, 1), budget_gb=abo.get('budget_gb'))
                    break
            if no_room(root, target_dir, size):
                waiting += 1
                _notify('youtube_abo_reserve_reached', reserve_gb=reserve_gb(root))
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


def _staggered(db, abo_id, when):
    """Nächster Prüfzeitpunkt, der von jedem anderen aktiven Abo mindestens STAGGER Sekunden entfernt liegt."""
    others = sorted(r[0] for r in db.execute('SELECT next_check FROM youtube_abos WHERE enabled=1 AND id!=? AND next_check>0',
                                             (abo_id,)))
    for other in others:                      # aufsteigend: höchstens ein Durchgang nötig
        if abs(other - when) < STAGGER:
            when = other + STAGGER
    return when


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
    # 0.6.44: je Lauf nur ein Abo prüfen; die übrigen fälligen folgen im Abstand von STAGGER Sekunden, damit nicht
    # mehrere Kanäle gleichzeitig gelesen werden und ihre neuen Videos nicht im selben Moment in die Warteschlange gehen.
    if len(ids) > 1:
        start = time.time() if now is None else float(now)
        db = _connect(root)
        try:
            with db:
                for number, later_id in enumerate(ids[1:], 1):
                    db.execute('UPDATE youtube_abos SET next_check=? WHERE id=?', (start + number * STAGGER, later_id))
        finally:
            db.close()
        ids = ids[:1]
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


# 0.6.14 (Björn, 16.11.2026: „lieber nur wenige Videos die Stunde laden“, damit die Bot-Sperre gar nicht
# erst auslöst): automatische Abo-Downloads starten höchstens PER_HOUR-mal pro Stunde, gleichmäßig verteilt
# (bei 4 alle 15 Minuten). Der Zeitpunkt des letzten Starts steht in youtube.sqlite3, damit ein Neustart
# keinen Schub auslöst. Einzelne Klicks auf „Offline speichern“ sind keine Abo-Aufträge und starten sofort.
PER_HOUR_CHOICES = (1, 2, 3, 4, 6, 10, 20)
PER_HOUR_DEFAULT = 4


def per_hour(root):
    db = youtube._connect(root)
    try:
        value = youtube._get(db, 'abo_per_hour', str(PER_HOUR_DEFAULT))
    finally:
        db.close()
    try:
        value = int(value)
    except ValueError:
        return PER_HOUR_DEFAULT
    return value if value in PER_HOUR_CHOICES else PER_HOUR_DEFAULT


def set_per_hour(root, value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError('Bitte eine Zahl pro Stunde wählen') from None
    if value not in PER_HOUR_CHOICES:
        raise ValueError('Erlaubt sind %s Videos pro Stunde' % ', '.join(map(str, PER_HOUR_CHOICES)))
    db = youtube._connect(root)
    try:
        with db:
            youtube._set(db, 'abo_per_hour', value)
    finally:
        db.close()
    return value


def _last_start(db, now):
    try:
        last = float(youtube._get(db, 'abo_last_start', '0') or 0)
    except ValueError:
        last = 0.0
    return 0.0 if last > now + 60 else last          # Uhr zurückgestellt: nicht ewig warten


def next_slot(root, now=None):
    """Frühester Start des nächsten Abo-Videos (0 = sofort)."""
    now = time.time() if now is None else float(now)
    db = youtube._connect(root)
    try:
        slot = _last_start(db, now) + 3600.0 / per_hour(root)
    finally:
        db.close()
    return slot if slot > now else 0.0


def pace(root, job, now=None, force=False, c=None):
    """Vor dem Start eines Abo-Auftrags: ist der nächste Platz noch nicht frei, wartet der Auftrag bis
    dahin (``not_before``, Hinweis) und die Funktion gibt True zurück. Sonst wird der Start vermerkt."""
    if not job.get('youtube_abo'):
        return False
    now = time.time() if now is None else float(now)
    # 0.6.60: das Budget des Abos gilt auch für Aufträge, die schon in der Warteschlange stehen (aus der Zeit
    # vor dem Budget oder mit zu kleiner Schätzung). „Jetzt versuchen“ startet trotzdem.
    if c is not None and not force:
        over = over_budget(root, c, job, now)
        if over:
            job.update(not_before=now + RESERVE_RECHECK, note=over)
            return True
    # 0.6.45: auch schon eingereihte Abo-Aufträge starten nicht, solange die Reserve unterschritten wäre.
    room = no_room(root, job.get('root') or str(Path(str(job.get('target') or '')).parent),
                   estimate({'duration': (job.get('source') or {}).get('duration')}, job.get('quality')))
    if room and not force:
        job.update(not_before=now + RESERVE_RECHECK, note=room)
        return True
    limit = per_hour(root)
    db = youtube._connect(root)
    try:
        slot = _last_start(db, now) + 3600.0 / limit
        if slot > now and not force:          # „Jetzt versuchen“ startet sofort, zählt aber mit
            job.update(not_before=slot, note='Höchstens %d Abo-Videos pro Stunde: nächstes startet um %s Uhr'
                       % (limit, time.strftime('%H:%M', time.localtime(slot))))
            return True
        with db:
            youtube._set(db, 'abo_last_start', now)
    finally:
        db.close()
    return False


def over_budget(root, c, job, now=None):
    """Hinweis, wenn der Start dieses Abo-Auftrags das Speicherbudget seines Abos überschritte, sonst ''."""
    db = _connect(root)
    try:
        row = db.execute('SELECT * FROM youtube_abos WHERE id=?', (int(job.get('youtube_abo') or 0),)).fetchone()
        if not row:
            return ''
        abo = dict(row, _root=str(root))
        budget = budget_bytes(abo)
        if not budget:
            return ''
        sync_states(c, db, abo['id'])                # fertige Aufträge zählen mit ihrer echten Größe
        done, _queued = held(c, db, abo)
        size = sized({'duration': (job.get('source') or {}).get('duration')}, job.get('quality'), abo_rate(c, db, abo))
        while done and done + size > budget and _make_room(c, db, abo, time.time() if now is None else now):
            db.commit()
            done, _queued = held(c, db, abo)
        if done and done + size > budget:
            return ('Speicherbudget des Abos erreicht (%.1f von %s GB): wartet, bis gesehene Videos Platz machen'
                    % (done / GB, gb_text(abo.get('budget_gb'))))
        return ''
    finally:
        db.close()


def gb_text(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return str(value)
    return ('%.1f' % value).rstrip('0').rstrip('.').replace('.', ',')


TEMPORARY_ERRORS = ('kein Bot', 'zu viele Anfragen', 'keine Daten', 'antwortet nicht rechtzeitig', 'Zeitüberschreitung')
# 0.6.19 (Björns Diagnose 0.6.18): these ended as permanent errors before 0.6.19; requeued once after the update.
REQUEUE_ONCE = ('This video is not available', 'Zu wenig freier Speicher')
# 0.6.28 (Diagnose 19.11.): exFAT/SMB-Ziele ohne Hardlinks scheiterten beim Veröffentlichen mit
# „[Errno 45] Operation not supported“. core.publish_exclusive weicht jetzt aus; einmal neu einreihen.
REQUEUE_NO_HARDLINK = ('[Errno 45]', 'Operation not supported', '[Errno 95]')


# 0.6.36: "This video is not available" bei Kindervideos ("Made for Kids") lag an der fehlenden
# JavaScript-Laufzeit für yt-dlp. Sobald eine da ist, diese Aufträge einmal neu einreihen.
NOT_AVAILABLE = 'This video is not available'


def requeue_not_available(c, now=None):
    """Aufgegebene YouTube-Aufträge mit „This video is not available“ einmal neu einreihen (gestaffelt)."""
    now = time.time() if now is None else float(now)
    moved = 0
    for job_id, payload in c.execute("SELECT id,payload FROM jobs WHERE state='error' "
                                     "AND json_extract(payload,'$.origin')='youtube'").fetchall():
        try:
            job = json.loads(payload)
        except (TypeError, ValueError):
            continue
        error = str(job.get('error') or '')
        if job.get('requeued_0636') or NOT_AVAILABLE not in error:
            continue
        job.update(state='queued', not_before=now + 60 + moved * 120, received=0, total=0, speed=0, eta=None,
                   error='', retries=0, last_error=error[:200], requeued_0636=True,
                   note='Wird mit JavaScript-Laufzeit (Deno) erneut versucht')
        c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'queued', job_id))
        moved += 1
    return moved


def requeue_on_start(c, now=None, js_ready=False):
    """0.6.13, einmal beim Start: YouTube-Aufträge, die vor 0.6.13 an einem vorübergehenden Fehler
    (Bot-Prüfung) gescheitert sind, und Abo-Downloads, die ein Neustart unterbrochen hat, wieder
    einreihen. Gestaffelt, damit YouTube nicht alle auf einmal sieht. Gibt die Zahl zurück."""
    import download_retry
    now = time.time() if now is None else float(now)
    rows = c.execute("SELECT id,payload,state FROM jobs WHERE state IN ('error','interrupted') "
                     "AND json_extract(payload,'$.origin')='youtube'").fetchall()
    moved = 0
    for job_id, payload, state in rows:
        try:
            job = json.loads(payload)
        except (TypeError, ValueError):
            continue
        error = str(job.get('error') or '')
        if state == 'interrupted' and job.get('youtube_abo'):
            wait = 60
        elif state == 'error' and not job.get('retries') and any(x in error for x in TEMPORARY_ERRORS):
            wait = download_retry.BACKOFF[0]
        elif state == 'error' and not job.get('requeued_0619') and any(x in error for x in REQUEUE_ONCE):
            wait = download_retry.BACKOFF[0]
            job['requeued_0619'] = True
        elif state == 'error' and not job.get('requeued_0628') and any(x in error for x in REQUEUE_NO_HARDLINK):
            wait = 60
            job['requeued_0628'] = True
        else:
            continue
        job.update(state='queued', not_before=now + wait + moved * 120, received=0, total=0, speed=0, eta=None,
                   error='', retries=1 if state == 'error' else int(job.get('retries') or 0),
                   last_error=error[:200] if state == 'error' else '',
                   note='Wird nach dem Update automatisch erneut versucht')
        c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'queued', job_id))
        moved += 1
    if js_ready:
        moved += requeue_not_available(c, now + moved * 120)
    return moved


def tick(root):
    """Jede Minute ohne fällige Prüfung: fertige Downloads übernehmen (für „Neu“ in der Kinderansicht)."""
    if _DB is None:
        return
    global _TRIMMED_AT
    db = _connect(root)
    try:
        with _DB() as c:
            sync_states(c, db)
            # 0.6.68: Aufträge über dem Budget nicht erst bei der nächsten Kanalprüfung (bis 24 h) zurücknehmen
            # (Mac-Prüfung 0.6.67: 1,0 GB belegt, 76,9 GB „in Arbeit“ bei 10 GB Budget)
            if time.time() - _TRIMMED_AT >= TRIM_INTERVAL:
                _TRIMMED_AT = time.time()
                for abo in [dict(r) for r in db.execute('SELECT * FROM youtube_abos WHERE enabled=1')]:
                    budget = budget_bytes(abo)
                    if budget:
                        trim_queued(c, db, abo, budget)
    finally:
        db.close()


TRIM_INTERVAL = 600
_TRIMMED_AT = 0.0


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
        # 0.6.13: Aufträge, die nach einem vorübergehenden Fehler auf ihren nächsten Versuch warten
        for r in db.execute("SELECT abo_id,COUNT(*) FROM youtube_abo_videos WHERE state='queued' AND reason!='' GROUP BY abo_id"):
            mine = counts.setdefault(r[0], {})
            mine['retry'] = r[1]
            mine['queued'] = max(0, (mine.get('queued') or 0) - r[1])
        reasons = {}
        for r in db.execute("SELECT abo_id,reason,COUNT(*) FROM youtube_abo_videos WHERE state IN ('skipped','failed','queued') AND reason!='' "
                            "GROUP BY abo_id,reason ORDER BY 3 DESC"):
            reasons.setdefault(r[0], []).append({'reason': r[1], 'count': r[2]})
        # 0.6.68 (Mac-Prüfung 0.6.67): Videos, die nur wegen des Budgets warten, auch in der Verwaltung zählen
        budget_wait = dict(db.execute("SELECT abo_id,COUNT(*) FROM youtube_abo_videos WHERE state='wanted' AND reason=? GROUP BY abo_id",
                                      (BUDGET_REASON,)).fetchall())
    finally:
        db.close()
    usage = {}
    if c is not None:
        db = _connect(root)
        try:
            for a in abos:
                usage[a['id']] = held(c, db, a)
        finally:
            db.close()
    for a in abos:
        done_bytes, queued_bytes = usage.get(a['id'], (0, 0))
        budget = budget_bytes(a)
        a['used_gb'] = round(done_bytes / GB, 2)
        a['planned_gb'] = round(queued_bytes / GB, 2)
        # Budget (fast) erreicht und noch Videos, die warten
        a['budget_full'] = bool(budget and done_bytes + queued_bytes >= budget * 0.95
                                and (counts.get(a['id'], {}).get('wanted') or 0))
        # 0.6.60: schon geladene Videos liegen über dem Budget (z. B. aus der Zeit vor dem Budget)
        a['over_budget'] = bool(budget and done_bytes > budget)
        # 0.6.68: „voll“ heißt bei used 1,0 GB von 10 GB nur „mit den laufenden Downloads verplant“ – getrennt benennen
        a['budget_planned_full'] = bool(a['budget_full'] and not a['over_budget'] and done_bytes < budget * 0.95)
        a['budget_full'] = a['budget_full'] or a['over_budget']
        a['waiting_for_budget'] = budget_wait.get(a['id'], 0)
        a['counts'] = counts.get(a['id'], {})
        a['reasons'] = reasons.get(a['id'], [])[:5]
        a['name'] = a['label'] or a['title'] or a['ref']
        a['url'] = _channel_url(a['ref']).replace('/videos', '')
        a['avatar_local'] = bool(avatar_file(root, a['id']))
    offline = youtube_downloads.status(root)
    profiles = [{'key': k, 'label': v, 'abos': sum(1 for a in abos if a['profile'] == k),
                 'done': sum((a['counts'].get('done') or 0) for a in abos if a['profile'] == k)} for k, v in PROFILES.items()]
    return {'abos': abos, 'profiles': profiles, 'offline': {'enabled': offline.get('enabled'), 'tool': bool(offline.get('tool'))},
            'key_set': bool(str((_SETTINGS() or {}).get('youtube') or '').strip()), 'running': _ACTIVE,
            'progress': _PROGRESS, 'days': youtube_downloads.OFFLINE_DAYS, 'pause': _pause(),
            'per_hour': per_hour(root), 'per_hour_choices': list(PER_HOUR_CHOICES), 'next_slot': next_slot(root),
            'storage': _storage(root), 'waiting_for_budget': sum(a['waiting_for_budget'] for a in abos)}


def _storage(root):
    """0.6.45: Reserve und freier Speicher am Abo-Ziel für die Verwaltung."""
    target = storage_locations.abo_base(_SETTINGS() or {})
    free = free_bytes(target)
    reserve = reserve_gb(root)
    return {'reserve_gb': reserve, 'reserve_choices': list(RESERVE_CHOICES),
            'free_gb': round(free / GB, 1) if free is not None else None,
            'low': bool(free is not None and free < reserve * GB), 'budget_default_gb': BUDGET_DEFAULT_GB}


def _pause(now=None):
    import download_retry
    until, reason = download_retry.blocked_until('youtube', now)
    return {'until': until, 'reason': reason} if until else {}


def kids(root, c, watch=None, profile='kinder'):
    """Fertig geladene Videos eines Profils mit seinen Kanälen, neue zuerst. Kinderecke: 'kinder',
    Ansehen-Modus (watch_home.py): 'erwachsene' (0.6.11: keine Vermischung mehr)."""
    import watch_state
    if profile is not None and profile not in PROFILES:
        raise ValueError('Unbekanntes Profil')
    db = _connect(root)
    try:
        sync_states(c, db)
        # 0.6.27: profile=None liefert alle Abos (Dashboard, library()).
        abos = [dict(r) for r in (db.execute('SELECT id,label,title,ref,kids,profile FROM youtube_abos') if profile is None else
                                  db.execute('SELECT id,label,title,ref,kids,profile FROM youtube_abos WHERE profile=?', (profile,)))]
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
        channels.append({'id': a['id'], 'name': a['label'] or a['title'] or a['ref'], 'videos': len(own), 'kids': a['profile'] == 'kinder', 'profile': a['profile'],
                         'new': sum(1 for v in own if v['new']), 'avatar': bool(avatar_file(root, a['id']))})
    channels.sort(key=lambda ch: (-ch['new'], ch['name'].lower()))
    return {'channels': channels, 'videos': videos}


def library(root, c, watch=None):
    """0.6.27 (Björn, 19.11.2026): die abonnierten Videos im normalen Dashboard, gegliedert je Kanal.
    Alle Profile; je Kanal zusätzlich, was noch in der Warteschlange steckt und wann zuletzt geprüft wurde."""
    data = kids(root, c, watch=watch, profile=None)
    db = _connect(root)
    try:
        meta = {r['id']: dict(r) for r in db.execute(
            'SELECT id,ref,enabled,checked,next_check,last_error,interval_hours FROM youtube_abos')}
        counts = {}
        for r in db.execute("SELECT abo_id,state,COUNT(*),SUM(state='queued' AND reason!='') FROM youtube_abo_videos GROUP BY abo_id,state"):
            mine = counts.setdefault(r[0], {})
            mine[r[1]] = r[2]
            if r[1] == 'queued' and r[3]:
                mine['retry'] = r[3]
    finally:
        db.close()
    for ch in data['channels']:
        m, n = meta.get(ch['id'], {}), counts.get(ch['id'], {})
        ch.update({'profile_label': PROFILES.get(ch['profile'], ch['profile']), 'enabled': bool(m.get('enabled')),
                   'checked': m.get('checked') or 0, 'next_check': m.get('next_check') or 0,
                   'error': m.get('last_error') or '', 'queued': n.get('queued') or 0, 'retry': n.get('retry') or 0,
                   'failed': n.get('failed') or 0, 'url': _channel_url(m.get('ref') or '').replace('/videos', '') if m.get('ref') else ''})
    # Kanäle mit neuen Videos zuerst, dann mit Videos, dann der Rest (z. B. noch nichts geladen)
    data['channels'].sort(key=lambda ch: (-ch['new'], -ch['videos'], ch['name'].lower()))
    data['pause'] = _pause()
    data['next_slot'] = next_slot(root)
    return data


def summary(root):
    """Zahlen für den Diagnoseexport (ohne Namen und Adressen)."""
    db = _connect(root)
    try:
        abos = db.execute("SELECT COUNT(*),SUM(enabled),SUM(profile='kinder') FROM youtube_abos").fetchone()
        states = dict(db.execute('SELECT state,COUNT(*) FROM youtube_abo_videos GROUP BY state').fetchall())
        errors = db.execute("SELECT COUNT(*) FROM youtube_abos WHERE last_error!=''").fetchone()[0]
        waiting_budget = db.execute("SELECT COUNT(*) FROM youtube_abo_videos WHERE state='wanted' AND reason=?",
                                    (BUDGET_REASON,)).fetchone()[0]
    finally:
        db.close()
    return {'abos': abos[0] or 0, 'enabled': abos[1] or 0, 'kids': abos[2] or 0, 'videos': states,
            'with_note': errors, 'running': _ACTIVE, 'waiting_for_budget': waiting_budget}
