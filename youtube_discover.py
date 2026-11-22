"""Neue YouTube-Kanäle aus dem eigenen Sehverhalten vorschlagen (0.6.90).

Björn (22.11.2026): „ob wir anhand von Verläufen von Videos, die geschaut werden, auch neue Kanäle auf YouTube
entdecken können … ja, aber wie können wir diese dann anzeigen, validieren und dann ggf. für meine Tochter
verfügbar machen“.

YouTubes eigene Empfehlungen gibt es ohne Anmeldung nicht (und Anmeldung/Cookies sind ausgeschlossen, Björns
Entscheidung vom 12.11.2026). Ebenso keine KI in der App (Björn 20.11.2026). Vorgeschlagen wird deshalb nur, was
sich aus öffentlichen Angaben der abonnierten Kanäle nachvollziehbar ergibt:

* **Empfohlene Kanäle** eines Abos (Reiter „Kanäle“ auf YouTube): mit API-Schlüssel ``channelSections``
  (Abschnitte vom Typ ``multipleChannels``), sonst yt-dlp ``<Kanal>/channels`` (``--flat-playlist``).
  Je Abo höchstens einmal pro Woche gelesen.
* **Erwähnungen** in den Beschreibungen geladener Videos (Links ``youtube.com/@…``, ``/channel/UC…``,
  ``/user/…``): Beschreibung aus dem Data-API-Speicher oder, seit 0.6.90, von yt-dlp beim Abo-Download
  (``--write-description``).

Gewicht: was zu Ende gesehen wurde, zählt mehr. Ein Abo mit vielen gesehenen Videos gibt seinen Empfehlungen
mehr Gewicht; eine Erwähnung in einem gesehenen Video zählt voll, in einem ungesehenen wenig.

Prüfen und Freigeben (nur Erwachsene, YouTube → Abos): Vorschau der neuesten Videos (Abspielen im offiziellen
YouTube-Player), dann „Für die Kinderecke freigeben“ (Abo im Profil ``kinder``), „Für mich abonnieren“ oder
„Nicht vorschlagen“. Die Kinderecke selbst zeigt nie Vorschläge, nur freigegebene Abos.

Daten in youtube.sqlite3 (Tabellen ``youtube_suggestions``, ``youtube_mentions``). Nur Standardbibliothek.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.parse

import youtube

WEEK = 7 * 86400
AUTO_EVERY = 86400             # automatische Suche höchstens einmal am Tag (aus youtube_abos.tick)
FEATURED_PER_RUN = 10          # so viele Abos lesen ihren Reiter „Kanäle“ je Lauf neu (Rest aus dem Speicher)
MAX_SUGGESTIONS = 40
PREVIEW_VIDEOS = 8
PREVIEW_TTL = 86400
LIST_TIMEOUT = 120
STATES = ('new', 'approved', 'rejected')
START_COUNT = 3                # 0.6.98 (Mac-Prüfung 0.6.90: 5 × 26 Min. ≈ 2 GB): freigegebener Kanal lädt zum Start 3 Videos

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_mentions(video TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY(video, ref));
CREATE TABLE IF NOT EXISTS youtube_described(video TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_suggestions(
  ref TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0,
  why TEXT NOT NULL DEFAULT '[]', profile TEXT NOT NULL DEFAULT 'kinder', state TEXT NOT NULL DEFAULT 'new',
  decided_profile TEXT NOT NULL DEFAULT '', found REAL NOT NULL, updated REAL NOT NULL,
  sample TEXT NOT NULL DEFAULT '', sampled REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');
'''

_LINK = re.compile(r'(?:https?://)?(?:www\.|m\.)?youtube\.com/(?:channel/(%s)|(%s)|user/([A-Za-z0-9_\-]{3,40}))(?![A-Za-z0-9_\-])'
                   % (youtube.CHANNEL_ID, youtube.HANDLE))
_LOCK = threading.Lock()
_RUNNING = {'active': False, 'progress': '', 'last_error': ''}


def _connect(root):
    db = youtube._connect(root)
    db.executescript(SCHEMA)
    return db


def norm(ref):
    """Einheitliche Schreibweise: Kanal-ID unverändert, @Handle klein, user:Name."""
    ref = str(ref or '').strip()
    if re.fullmatch(youtube.CHANNEL_ID, ref):
        return ref
    if re.fullmatch(youtube.HANDLE, ref):
        return ref.lower()
    if ref.startswith('user:') and re.fullmatch(r'[A-Za-z0-9_\-]{3,40}', ref[5:]):
        return 'user:' + ref[5:].lower()
    return ''


# ---------------------------------------------------------------- Erwähnungen in Beschreibungen

def mentions(text):
    """Kanäle, auf die eine Videobeschreibung verlinkt (geordnet, ohne Dubletten)."""
    out = []
    for m in _LINK.finditer(str(text or '')[:20000]):
        ref = norm(m.group(1) or m.group(2) or ('user:' + m.group(3) if m.group(3) else ''))
        if ref and ref not in out:
            out.append(ref)
    return out[:30]


def record_mentions(root, video, text):
    """Vom Abo-Download (youtube_downloads.fetch) aufgerufen: Erwähnungen eines Videos merken."""
    if not youtube.VALID_VIDEO.fullmatch(str(video or '')):
        return 0
    refs = mentions(text)
    db = _connect(root)
    try:
        with db:
            db.execute('DELETE FROM youtube_mentions WHERE video=?', (video,))
            db.executemany('INSERT OR IGNORE INTO youtube_mentions(video,ref) VALUES(?,?)', [(video, r) for r in refs])
            db.execute('INSERT OR REPLACE INTO youtube_described(video,at) VALUES(?,?)', (video, time.time()))
    finally:
        db.close()
    return len(refs)


def _api_mentions(db, videos):
    """Beschreibungen aus dem Data-API-Speicher (youtube_videos) für noch nicht erfasste Videos übernehmen."""
    known = {r[0] for r in db.execute('SELECT video FROM youtube_described')}
    missing = [v for v in videos if v not in known]
    for start in range(0, len(missing), 400):
        chunk = missing[start:start + 400]
        for vid, payload in db.execute('SELECT id,payload FROM youtube_videos WHERE id IN (%s)' % ','.join('?' * len(chunk)), chunk):
            try:
                text = json.loads(payload).get('description') or ''
            except (TypeError, ValueError, AttributeError):
                continue
            db.executemany('INSERT OR IGNORE INTO youtube_mentions(video,ref) VALUES(?,?)', [(vid, r) for r in mentions(text)])
            db.execute('INSERT OR REPLACE INTO youtube_described(video,at) VALUES(?,?)', (vid, time.time()))


# ---------------------------------------------------------------- Empfohlene Kanäle eines Abos

def _channel_base(ref):
    if ref.startswith('@'):
        return 'https://www.youtube.com/%s' % ref
    if ref.startswith('user:'):
        return 'https://www.youtube.com/user/%s' % ref[5:]
    return 'https://www.youtube.com/channel/%s' % ref


def featured_with_ytdlp(root, ref, runner=None):
    """[(ref, Titel)] aus dem Reiter „Kanäle“ über yt-dlp (kein Schlüssel nötig)."""
    import youtube_downloads
    tool = youtube_downloads.find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    args = [*tool[0], '--ignore-config', '--flat-playlist', '-J', '--no-warnings', '--no-cookies-from-browser',
            '--playlist-end', '60', _channel_base(ref) + '/channels']
    result = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL,
                                        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode != 0:
        message, _retry, block = youtube_downloads._failure(result.stderr[-3000:])
        if block:
            import download_retry
            download_retry.block('youtube', time.time() + download_retry.BACKOFF[0], message)
        if 'does not have a channels tab' in (result.stderr or '').lower() or 'channels tab' in (result.stderr or '').lower():
            return []                                    # Kanal zeigt keine empfohlenen Kanäle
        raise ValueError(message)
    try:
        data = json.loads(result.stdout or '{}')
    except ValueError:
        raise ValueError('yt-dlp lieferte keine lesbare Liste') from None
    own = {norm(data.get('channel_id')), norm(data.get('uploader_id')), norm(ref)}
    out = []
    for entry in data.get('entries') or []:
        if not isinstance(entry, dict):
            continue
        found = ''
        for value in (entry.get('channel_id'), entry.get('id'), entry.get('uploader_id')):
            found = norm(value)
            if found:
                break
        if not found:
            found = (mentions(entry.get('url') or '') or [''])[0]
        if found and found not in own and found not in [f for f, _ in out]:
            out.append((found, ' '.join(str(entry.get('channel') or entry.get('title') or entry.get('uploader') or '').split())[:120]))
    return out


def featured_with_api(request, channel_id):
    """[(ref, Titel)] aus den Kanalabschnitten (``channelSections``, Typ ``multipleChannels``); 1 Einheit + 1 je 50."""
    if not re.fullmatch(youtube.CHANNEL_ID, str(channel_id or '')):
        return []
    ids = []
    for item in (request('channelSections', {'part': 'snippet,contentDetails', 'channelId': channel_id}) or {}).get('items') or []:
        if not isinstance(item, dict) or (item.get('snippet') or {}).get('type') != 'multipleChannels':
            continue
        for cid in (item.get('contentDetails') or {}).get('channels') or []:
            if re.fullmatch(youtube.CHANNEL_ID, str(cid)) and cid != channel_id and cid not in ids:
                ids.append(cid)
    titles = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        for node in (request('channels', {'part': 'snippet', 'id': ','.join(chunk), 'maxResults': 50}) or {}).get('items') or []:
            if isinstance(node, dict):
                titles[node.get('id')] = youtube._text((node.get('snippet') or {}).get('title'), 120)
    return [(cid, titles.get(cid, '')) for cid in ids]


PLAYLISTS_PER_ABO = 4          # so viele Playlists eines Abos werden je Woche gelesen
PLAYLIST_VIDEOS = 50
BACKFILL_PER_RUN = 15          # Beschreibungen bereits geladener Videos, die ein Lauf nachholt


def _cached(db, key, now, budget, fetch):
    """Höchstens wöchentlich neu lesen; ``budget`` = [noch erlaubte Netzabrufe in diesem Lauf]."""
    try:
        cached = json.loads(youtube._get(db, key, '{}'))
    except ValueError:
        cached = {}
    if cached.get('at', 0) > now - WEEK or budget[0] <= 0:
        return [tuple(x) for x in cached.get('refs') or []]
    budget[0] -= 1
    try:
        refs = fetch()
    except Exception as exc:                  # eine unlesbare Quelle hält die übrigen nicht auf
        _RUNNING['last_error'] = (str(exc) or type(exc).__name__)[:200]
        return [tuple(x) for x in cached.get('refs') or []]
    with db:
        youtube._set(db, key, json.dumps({'at': now, 'refs': refs}))
    return refs


def _featured(root, db, abo, now, request, runner, budget):
    """Empfohlene Kanäle eines Abos. 0.6.98: nur noch mit API-Schlüssel (``channelSections``); den Reiter „Kanäle“
    liefert YouTube nicht mehr aus (Mac-Prüfung 0.6.90: yt-dlp „does not have a channels tab“ bei allen Kanälen)."""
    if request is None or not abo.get('channel_id'):
        return []
    return _cached(db, 'featured:%d' % abo['id'], now, budget, lambda: featured_with_api(request, abo['channel_id']))


def _ytdlp_json(root, url, end, runner=None):
    import youtube_downloads
    tool = youtube_downloads.find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    args = [*tool[0], '--ignore-config', '--flat-playlist', '-J', '--no-warnings', '--no-cookies-from-browser',
            '--playlist-end', str(end), url]
    result = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL,
                                        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode != 0:
        message, _retry, block = youtube_downloads._failure(result.stderr[-3000:])
        if block:
            import download_retry
            download_retry.block('youtube', time.time() + download_retry.BACKOFF[0], message)
        if 'does not have a' in (result.stderr or '').lower() and 'tab' in (result.stderr or '').lower():
            return {}
        raise ValueError(message)
    try:
        return json.loads(result.stdout or '{}')
    except ValueError:
        raise ValueError('yt-dlp lieferte keine lesbare Liste') from None


def _entry_channel(entry):
    for value in (entry.get('channel_id'), entry.get('uploader_id'), entry.get('channel_url'), entry.get('uploader_url')):
        found = norm(value) or (mentions(value)[0] if isinstance(value, str) and mentions(value) else '')
        if found:
            return found
    return ''


def playlist_channels_ytdlp(root, abo, runner=None):
    """0.6.98: [(ref, Kanalname, Anzahl Videos, Playlist)] fremder Kanäle in den Playlists eines Abos (Sammlungen,
    Zusammenarbeiten). Ohne Schlüssel über yt-dlp: ``<Kanal>/playlists``, dann je Playlist die Einträge."""
    data = _ytdlp_json(root, _channel_base(abo['ref']) + '/playlists', PLAYLISTS_PER_ABO * 2, runner)
    own = {norm(abo['ref']), norm(abo.get('channel_id')), norm(data.get('channel_id')), norm(data.get('uploader_id'))}
    lists = []
    for entry in data.get('entries') or []:
        pid = str((entry or {}).get('id') or '')
        if re.fullmatch(youtube.PLAYLIST_ID, pid) and pid not in [l for l, _ in lists]:
            lists.append((pid, ' '.join(str(entry.get('title') or '').split())[:80]))
    return _count_foreign(own, [(title, _ytdlp_json(root, youtube.playlist_url(pid), PLAYLIST_VIDEOS, runner).get('entries') or [])
                                for pid, title in lists[:PLAYLISTS_PER_ABO]])


def playlist_channels_api(request, abo):
    """Dasselbe mit API-Schlüssel: playlists.list (1 Einheit) und playlistItems.list je Playlist (1 Einheit)."""
    if not abo.get('channel_id'):
        return []
    items = (request('playlists', {'part': 'snippet', 'channelId': abo['channel_id'], 'maxResults': PLAYLISTS_PER_ABO * 2}) or {}).get('items') or []
    groups = []
    for item in items[:PLAYLISTS_PER_ABO]:
        pid = str((item or {}).get('id') or '')
        if not re.fullmatch(youtube.PLAYLIST_ID, pid):
            continue
        rows = (request('playlistItems', {'part': 'snippet', 'playlistId': pid, 'maxResults': PLAYLIST_VIDEOS}) or {}).get('items') or []
        groups.append((youtube._text((item.get('snippet') or {}).get('title'), 80),
                       [{'channel_id': (r.get('snippet') or {}).get('videoOwnerChannelId'),
                         'channel': (r.get('snippet') or {}).get('videoOwnerChannelTitle')} for r in rows if isinstance(r, dict)]))
    return _count_foreign({norm(abo['ref']), norm(abo['channel_id'])}, groups)


def _count_foreign(own, groups):
    found = {}
    for title, entries in groups:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ref = _entry_channel(entry)
            if not ref or ref in own:
                continue
            item = found.setdefault(ref, [ref, ' '.join(str(entry.get('channel') or entry.get('uploader') or '').split())[:120], 0, title])
            item[2] += 1
    return [tuple(v) for v in sorted(found.values(), key=lambda v: -v[2])][:30]


def _playlists(root, db, abo, now, request, runner, budget):
    if abo['kind'] != 'channel':
        return []
    fetch = (lambda: playlist_channels_api(request, abo)) if request is not None else (lambda: playlist_channels_ytdlp(root, abo, runner))
    return _cached(db, 'playlists:%d' % abo['id'], now, budget, fetch)


def backfill_descriptions(root, db, videos, runner=None, limit=BACKFILL_PER_RUN):
    """0.6.98: Beschreibungen bereits geladener Videos nachholen (vor 0.6.90 nicht gespeichert). Ein yt-dlp-Aufruf für
    bis zu ``limit`` Videos, ohne Download (``--skip-download``), mit Pause zwischen den Anfragen. Gesehene zuerst."""
    import youtube_downloads
    tried = {r[0] for r in db.execute('SELECT video FROM youtube_described')}
    todo = [v for v in videos if v not in tried and youtube.VALID_VIDEO.fullmatch(v)][:limit]
    if not todo:
        return 0
    tool = youtube_downloads.find_tool(root)
    if not tool:
        return 0
    args = [*tool[0], '--ignore-config', '--skip-download', '--no-playlist', '--no-warnings', '--no-cookies-from-browser',
            '--ignore-errors', '--ignore-no-formats-error', '--sleep-requests', '1', '--sleep-interval', '2',
            *youtube_downloads.js_args(root, tool), '--print', '%(id)s\t%(description)j', *[youtube.video_url(v) for v in todo]]
    result = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=LIST_TIMEOUT + 30 * len(todo),
                                        stdin=subprocess.DEVNULL, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    got = 0
    now = time.time()
    with db:
        for line in (result.stdout or '').splitlines():
            vid, _, text = line.partition('\t')
            if vid not in todo:
                continue
            try:
                text = json.loads(text) if text else ''
            except ValueError:
                text = ''
            refs = mentions(text if isinstance(text, str) else '')
            db.execute('DELETE FROM youtube_mentions WHERE video=?', (vid,))
            db.executemany('INSERT OR IGNORE INTO youtube_mentions(video,ref) VALUES(?,?)', [(vid, r) for r in refs])
            db.execute('INSERT OR REPLACE INTO youtube_described(video,at) VALUES(?,?)', (vid, now))
            got += 1
    if not got and result.returncode != 0:
        message, _retry, block = youtube_downloads._failure((result.stderr or '')[-3000:])
        if block:
            import download_retry
            download_retry.block('youtube', time.time() + download_retry.BACKOFF[0], message)
        _RUNNING['last_error'] = ('Beschreibungen nicht lesbar: ' + message)[:200]
    return got


# ---------------------------------------------------------------- Vorschläge berechnen

def _weight(finished):
    return 1.0 + math.log2(1 + max(0, finished))


def discover(root, c=None, now=None, request=None, runner=None, seen=None):
    """Vorschläge neu berechnen. Gibt die Zahl offener Vorschläge zurück."""
    import youtube_abos
    now = time.time() if now is None else float(now)
    if request is None:
        request = youtube_abos._request_for_key()
    if seen is None:
        import watch_state
        seen = watch_state.states(root)
    adb = youtube_abos._connect(root)
    try:
        abos = [dict(r) for r in adb.execute('SELECT * FROM youtube_abos')]
        rows = [dict(r) for r in adb.execute("SELECT abo_id,video,job_id,state FROM youtube_abo_videos WHERE state IN ('done','archived')")]
    finally:
        adb.close()
    subscribed = set()
    for a in abos:
        subscribed.update(x for x in (norm(a['ref']), norm(a['channel_id'])) if x)
    by_abo = {}
    for r in rows:
        mark = seen.get('job:' + (r['job_id'] or '')) or {}
        by_abo.setdefault(r['abo_id'], []).append((r['video'], bool(mark.get('done'))))
    db = _connect(root)
    try:
        import download_retry
        paused = bool(download_retry.blocked_until('youtube', now)[0]) and request is None
        order = sorted(rows, key=lambda r: not (seen.get('job:' + (r['job_id'] or '')) or {}).get('done'))
        if request is not None:
            _api_mentions(db, [r['video'] for r in rows])
            db.commit()
        if not paused:
            # 0.6.98: Beschreibungen schon geladener Videos nachholen (gesehene zuerst); mit Schlüssel nur, was die API nicht hatte
            _RUNNING['progress'] = 'Videobeschreibungen werden gelesen …'
            try:
                backfill_descriptions(root, db, [r['video'] for r in order], runner=runner)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                _RUNNING['last_error'] = str(exc)[:200]
        mention_rows = {}
        for vid, ref in db.execute('SELECT video,ref FROM youtube_mentions'):
            mention_rows.setdefault(vid, []).append(ref)
        scores, why, profile_score, titles = {}, {}, {}, {}

        def add(ref, points, reason, profile, title=''):
            ref = norm(ref)
            if not ref or ref in subscribed or points <= 0:
                return
            scores[ref] = scores.get(ref, 0) + points
            if reason not in why.setdefault(ref, []):
                why[ref].append(reason)
            ps = profile_score.setdefault(ref, {})
            ps[profile] = ps.get(profile, 0) + points
            if title and not titles.get(ref):
                titles[ref] = title

        budget = [FEATURED_PER_RUN]
        _RUNNING['progress'] = 'Playlists der Abos werden gelesen …'
        for a in sorted(abos, key=lambda a: -sum(1 for _, d in by_abo.get(a['id'], []) if d)):
            name = a['label'] or a['title'] or a['ref']
            videos = by_abo.get(a['id'], [])
            finished = sum(1 for _, d in videos if d)
            w = _weight(finished)
            if a['enabled']:
                for ref, title in (_featured(root, db, a, now, request, runner, budget if not paused else [0]) or []):
                    add(ref, 3 * w, 'von „%s“ empfohlen' % name, a['profile'], title)
                for ref, title, count, playlist in (_playlists(root, db, a, now, request, runner, budget if not paused else [0]) or []):
                    add(ref, 2 * w + 0.5 * min(count - 1, 4),
                        'in der Playlist „%s“ von „%s“ (%s)' % (playlist, name, 'ein Video' if count == 1 else '%d Videos' % count),
                        a['profile'], title)
            counted = {}
            for vid, done in videos:
                for ref in mention_rows.get(vid, []):
                    n = counted.setdefault(ref, [0, 0])
                    n[0 if done else 1] += 1
            for ref, (watched, unwatched) in counted.items():
                points = min(watched, 5) + 0.3 * min(unwatched, 5)
                n = watched or unwatched
                text = ('in %s von „%s“ erwähnt' % ((('einem gesehenen Video' if n == 1 else '%d gesehenen Videos' % n) if watched else
                                                     ('einem Video' if n == 1 else '%d Videos' % n)), name))
                add(ref, points, text, a['profile'])
        with db:
            known = {r['ref']: dict(r) for r in db.execute('SELECT * FROM youtube_suggestions')}
            for ref, old in known.items():
                if old['state'] == 'new' and (ref not in scores or ref in subscribed):
                    db.execute('DELETE FROM youtube_suggestions WHERE ref=?', (ref,))
            ranked = sorted(scores, key=lambda r: -scores[r])[:MAX_SUGGESTIONS]
            for ref in ranked:
                profile = max(profile_score[ref], key=profile_score[ref].get)
                old = known.get(ref)
                if old and old['state'] != 'new':
                    continue                             # entschieden: bleibt, wie Björn es entschieden hat
                if old:
                    db.execute('UPDATE youtube_suggestions SET score=?,why=?,profile=?,updated=?,title=CASE WHEN title=\'\' THEN ? ELSE title END '
                               'WHERE ref=?', (round(scores[ref], 2), json.dumps(why[ref][:6]), profile, now, titles.get(ref, ''), ref))
                else:
                    db.execute('INSERT INTO youtube_suggestions(ref,title,score,why,profile,found,updated) VALUES(?,?,?,?,?,?,?)',
                               (ref, titles.get(ref, ''), round(scores[ref], 2), json.dumps(why[ref][:6]), profile, now, now))
            youtube._set(db, 'discover_last', str(now))
            count = db.execute("SELECT COUNT(*) FROM youtube_suggestions WHERE state='new'").fetchone()[0]
    finally:
        db.close()
    _notify('youtube_discover_done', open=count, network_reads=FEATURED_PER_RUN - budget[0], paused=paused,
            described=len(mention_rows))
    return count


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except Exception:
        pass


def start(root, force=False, now=None):
    """Im Hintergrund suchen (Knopf „Vorschläge suchen“ oder täglich aus youtube_abos.tick)."""
    now = time.time() if now is None else float(now)
    if not force:
        db = _connect(root)
        try:
            last = float(youtube._get(db, 'discover_last', '0') or 0)
        finally:
            db.close()
        if last > now - AUTO_EVERY:
            return False
    with _LOCK:
        if _RUNNING['active']:
            return False
        _RUNNING.update(active=True, progress='Vorschläge werden gesucht …', last_error='')

    def body():
        try:
            discover(root)
        except Exception as exc:                          # nie den Planer stören
            _RUNNING['last_error'] = str(exc)[:200]
            _notify('youtube_discover_failed', reason=type(exc).__name__)
        finally:
            _RUNNING.update(active=False, progress='')
    threading.Thread(target=body, name='youtube-discover', daemon=True).start()
    return True


# ---------------------------------------------------------------- Prüfen und Entscheiden

def _row(db, ref):
    row = db.execute('SELECT * FROM youtube_suggestions WHERE ref=?', (ref,)).fetchone()
    if not row:
        raise ValueError('Vorschlag nicht gefunden')
    return dict(row)


def preview(root, ref, now=None, request=None, runner=None, refresh=False):
    """Kanalangaben und die neuesten Videos eines Vorschlags (für das Probeschauen)."""
    import youtube_abos
    now = time.time() if now is None else float(now)
    ref = norm(ref)
    db = _connect(root)
    try:
        row = _row(db, ref)
    finally:
        db.close()
    if row['sample'] and row['sampled'] > now - PREVIEW_TTL and not refresh:
        return {**_public(row), 'videos': json.loads(row['sample']).get('videos', [])}
    if request is None:
        request = youtube_abos._request_for_key()
    fake = {'id': 0, 'ref': ref, 'kind': 'channel', 'title': row['title'],
            'channel_id': ref if ref.startswith('UC') else '', 'playlist': '', 'avatar': row['avatar']}
    try:
        if request is not None:
            info, videos = youtube_abos.list_with_api(root, fake, PREVIEW_VIDEOS * 2, request)
        else:
            info, videos = youtube_abos.list_with_ytdlp(fake, PREVIEW_VIDEOS * 2, runner=runner, root=root)
    except Exception as exc:
        raise ValueError('Kanal nicht lesbar: %s' % (str(exc)[:200] or type(exc).__name__)) from None
    videos = sorted(videos, key=lambda v: (v.get('published') or '', -v['position']), reverse=True)
    sample = [{'video': v['video'], 'title': v['title'], 'duration': v.get('duration'), 'published': v.get('published') or '',
               'poster': v.get('poster') or youtube_abos._poster(v['video']), 'age': bool(v.get('age')),
               'short': bool(v.get('duration') and v['duration'] < youtube_abos.SHORTS_SECONDS)}
              for v in videos[:PREVIEW_VIDEOS]]
    note = ''
    if any(v['age'] for v in sample):
        note = 'YouTube kennzeichnet Videos dieses Kanals als altersbeschränkt.'
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE youtube_suggestions SET title=?,avatar=?,sample=?,sampled=?,note=? WHERE ref=?',
                       (info.get('title') or row['title'], info.get('avatar') or row['avatar'],
                        json.dumps({'videos': sample, 'channel_id': info.get('channel_id') or ''}), now, note, ref))
        row = _row(db, ref)
    finally:
        db.close()
    return {**_public(row), 'videos': sample}


def decide(root, ref, action, now=None):
    """``kids`` (Abo für die Kinderecke), ``me`` (Abo im Ansehen-Modus), ``reject`` (nie wieder vorschlagen),
    ``reset`` (wieder offen)."""
    import youtube_abos
    ref = norm(ref)
    db = _connect(root)
    try:
        row = _row(db, ref)
    finally:
        db.close()
    abo_id = None
    if action in ('kids', 'me'):
        profile = 'kinder' if action == 'kids' else 'erwachsene'
        sample = json.loads(row['sample'] or '{}') if row['sample'] else {}
        url = sample.get('channel_id') or ref
        abo_id = youtube_abos.add(root, {'url': url, 'profile': profile, 'mode': 'new', 'start_count': START_COUNT,
                                         'label': row['title'][:80]}, now=now)
        state, decided = 'approved', profile
    elif action == 'reject':
        state, decided = 'rejected', ''
    elif action == 'reset':
        state, decided = 'new', ''
    else:
        raise ValueError('Unbekannte Entscheidung')
    db = _connect(root)
    try:
        with db:
            db.execute('UPDATE youtube_suggestions SET state=?,decided_profile=?,updated=? WHERE ref=?',
                       (state, decided, time.time() if now is None else float(now), ref))
    finally:
        db.close()
    _notify('youtube_discover_decided', action=action)
    return {'ok': True, 'abo': abo_id}


def _public(row):
    try:
        why = json.loads(row.get('why') or '[]')
    except ValueError:
        why = []
    host = (urllib.parse.urlsplit(row.get('avatar') or '').hostname or '').lower()
    import youtube_abos
    return {'ref': row['ref'], 'title': row['title'] or row['ref'], 'score': row['score'], 'why': why,
            'profile': row['profile'], 'state': row['state'], 'decided_profile': row['decided_profile'],
            'avatar': row['avatar'] if row.get('avatar', '').startswith('https://') and youtube_abos.AVATAR_HOSTS.fullmatch(host) else '',
            'url': _channel_base(row['ref']), 'checked': bool(row.get('sampled')), 'note': row.get('note') or ''}


def overview(root):
    db = _connect(root)
    try:
        rows = [dict(r) for r in db.execute("SELECT * FROM youtube_suggestions ORDER BY state='new' DESC, score DESC LIMIT 200")]
        last = float(youtube._get(db, 'discover_last', '0') or 0)
    finally:
        db.close()
    return {'suggestions': [_public(r) for r in rows if r['state'] == 'new'],
            'decided': [_public(r) for r in rows if r['state'] != 'new'][:50],
            'last': last, 'running': _RUNNING['active'], 'progress': _RUNNING['progress'], 'error': _RUNNING['last_error']}


def summary(root):
    """Zahlen für den Diagnoseexport (ohne Namen)."""
    db = _connect(root)
    try:
        states = dict(db.execute('SELECT state,COUNT(*) FROM youtube_suggestions GROUP BY state').fetchall())
        mentions_n = db.execute('SELECT COUNT(DISTINCT video) FROM youtube_mentions').fetchone()[0]
        last = float(youtube._get(db, 'discover_last', '0') or 0)
    finally:
        db.close()
    return {'suggestions': states, 'videos_with_description': mentions_n, 'last': last, 'error': _RUNNING['last_error'][:120]}
