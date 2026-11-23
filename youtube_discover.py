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
FEATURED_PER_RUN = 16          # so viele Netzabrufe (Empfehlungen, Playlists, Suchen) je Lauf; der Rest aus dem Speicher
MAX_SUGGESTIONS = 40
PREVIEW_VIDEOS = 8
PREVIEW_TTL = 86400
LIST_TIMEOUT = 120
STATES = ('new', 'approved', 'rejected')
START_COUNT = 3                # 0.6.98 (Mac-Prüfung 0.6.90: 5 × 26 Min. ≈ 2 GB): freigegebener Kanal lädt zum Start 3 Videos
# Nachbesserung nach Mac-Prüfung 0.6.106 (23.11.2026): Vorschläge waren nur Handles ohne Namen, eine als Handle gelesene
# Kanal-Kennung, vorn englische Kanäle aus den Beschreibungen eines einzigen Abos, ohne Kindersignal.
RESOLVE_PER_RUN = 15           # so viele Vorschläge ohne Namen/Kanalbild werden je Lauf aufgelöst (je ein Listenabruf)
RESOLVE_VIDEOS = 12            # Videotitel je aufgelöstem Kanal (Kindersignal, Sprache)
MENTIONS_PER_ABO = 5           # aus den Beschreibungen eines Abos zählen höchstens so viele erwähnte Kanäle
SINGLE_SOURCE = 0.6            # nur von einem Abo erwähnt: weniger Gewicht
_LOST_ID = re.compile(r'@uc[0-9a-z_\-]{22}')   # vor der Korrektur kleingeschriebene Kanal-Kennung: nicht mehr auflösbar

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_mentions(video TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY(video, ref));
CREATE TABLE IF NOT EXISTS youtube_described(video TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_tagged(video TEXT PRIMARY KEY, tags TEXT NOT NULL DEFAULT '[]', at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_suggestions(
  ref TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0,
  why TEXT NOT NULL DEFAULT '[]', profile TEXT NOT NULL DEFAULT 'kinder', state TEXT NOT NULL DEFAULT 'new',
  decided_profile TEXT NOT NULL DEFAULT '', found REAL NOT NULL, updated REAL NOT NULL,
  sample TEXT NOT NULL DEFAULT '', sampled REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');
'''
# Aufgelöste Kanalangaben (Name, Kanal-ID, Videotitel, Sprache); nicht dasselbe wie die Vorschau (``sample``),
# die Björn selbst öffnet und die die Freigabe erst möglich macht.
_COLUMNS = (('info', "TEXT NOT NULL DEFAULT ''"),)

_LINK = re.compile(r'(?:https?://)?(?:www\.|m\.)?youtube\.com/(?:channel/(%s)|(%s)|user/([A-Za-z0-9_\-]{3,40}))(?![A-Za-z0-9_\-])'
                   % (youtube.CHANNEL_ID, youtube.HANDLE))
_LOCK = threading.Lock()
_RUNNING = {'active': False, 'progress': '', 'last_error': ''}


def _connect(root):
    db = youtube._connect(root)
    db.executescript(SCHEMA)
    have = {r[1] for r in db.execute('PRAGMA table_info(youtube_suggestions)')}
    for name, decl in _COLUMNS:
        if name not in have:
            db.execute('ALTER TABLE youtube_suggestions ADD COLUMN %s %s' % (name, decl))
    return db


def norm(ref):
    """Einheitliche Schreibweise: Kanal-ID unverändert, @Handle klein, user:Name."""
    ref = str(ref or '').strip()
    if re.fullmatch(youtube.CHANNEL_ID, ref):
        return ref
    if ref.startswith('@') and re.fullmatch(youtube.CHANNEL_ID, ref[1:]):
        return ref[1:]                        # „@UC…“ ist eine Kanal-Kennung, kein Handle (Groß/klein zählt)
    if re.fullmatch(youtube.HANDLE, ref):
        return ref.lower()
    if ref.startswith('user:') and re.fullmatch(r'[A-Za-z0-9_\-]{3,40}', ref[5:]):
        return 'user:' + ref[5:].lower()
    return ''


# ---------------------------------------------------------------- Erwähnungen in Beschreibungen

_HANDLE = re.compile(r'(?<![A-Za-z0-9._%+\-/])(@[A-Za-z0-9][A-Za-z0-9._\-]{2,29})(?![A-Za-z0-9._\-]*@)')
_OTHER_NETWORK = re.compile(r'instagram|insta\b|tiktok|twitter|facebook|threads|snapchat|twitch|x\.com|e-?mail|mail:', re.I)


def mentions(text, loose=True):
    """Kanäle, auf die eine Videobeschreibung verlinkt (geordnet, ohne Dubletten).

    0.6.98 ``loose``: auch blanke @Handles (YouTube verlinkt sie in Beschreibungen und Titeln selbst), außer in
    Zeilen, die ein anderes Netzwerk oder eine Mail-Adresse nennen."""
    text = str(text or '')[:20000]
    out = []
    for m in _LINK.finditer(text):
        ref = norm(m.group(1) or m.group(2) or ('user:' + m.group(3) if m.group(3) else ''))
        if ref and ref not in out:
            out.append(ref)
    if loose:
        for line in text.splitlines():
            if _OTHER_NETWORK.search(line):
                continue
            for m in _HANDLE.finditer(line):
                ref = norm(m.group(1).rstrip('.-_'))
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
BACKFILL_PER_RUN = 25          # Beschreibungen/Schlagwörter bereits geladener Videos, die ein Lauf nachholt
SEARCH_TAGS = 3                # 0.6.98: so viele Schlagwörter gesehener Videos je Profil werden bei YouTube gesucht
SEARCH_RESULTS = 20


def _cached(db, key, now, budget, fetch, fresh=False):
    """Höchstens wöchentlich neu lesen; ``budget`` = [noch erlaubte Netzabrufe in diesem Lauf]; ``fresh`` (Prüflauf)
    liest trotz Speicher neu."""
    try:
        cached = json.loads(youtube._get(db, key, '{}'))
    except ValueError:
        cached = {}
    if (cached.get('at', 0) > now - WEEK and not fresh) or budget[0] <= 0:
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


def _featured(root, db, abo, now, request, runner, budget, fresh=False):
    """Empfohlene Kanäle eines Abos. 0.6.98: nur noch mit API-Schlüssel (``channelSections``); den Reiter „Kanäle“
    liefert YouTube nicht mehr aus (Mac-Prüfung 0.6.90: yt-dlp „does not have a channels tab“ bei allen Kanälen)."""
    if request is None or not abo.get('channel_id'):
        return []
    return _cached(db, 'featured:%d' % abo['id'], now, budget, lambda: featured_with_api(request, abo['channel_id']), fresh)


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


def _playlists(root, db, abo, now, request, runner, budget, fresh=False):
    if abo['kind'] != 'channel':
        return []
    fetch = (lambda: playlist_channels_api(request, abo)) if request is not None else (lambda: playlist_channels_ytdlp(root, abo, runner))
    return _cached(db, 'playlists:%d' % abo['id'], now, budget, fetch, fresh)


def search_channels_ytdlp(root, term, runner=None):
    """0.6.98: [(ref, Kanalname, Treffer)] der Kanäle in einer YouTube-Suche (yt-dlp ``ytsearchN:``, nur Liste)."""
    data = _ytdlp_json(root, 'ytsearch%d:%s' % (SEARCH_RESULTS, term), SEARCH_RESULTS, runner)
    found = {}
    for entry in data.get('entries') or []:
        if isinstance(entry, dict):
            ref = _entry_channel(entry)
            if ref:
                item = found.setdefault(ref, [ref, ' '.join(str(entry.get('channel') or entry.get('uploader') or '').split())[:120], 0])
                item[2] += 1
    return [tuple(v) for v in found.values()]


def search_channels_api(request, term):
    rows = (request('search', {'part': 'snippet', 'q': term, 'type': 'video', 'maxResults': SEARCH_RESULTS,
                               'relevanceLanguage': 'de', 'safeSearch': 'strict'}) or {}).get('items') or []
    found = {}
    for r in rows:
        sn = (r or {}).get('snippet') or {}
        ref = norm(sn.get('channelId'))
        if ref:
            item = found.setdefault(ref, [ref, youtube._text(sn.get('channelTitle'), 120), 0])
            item[2] += 1
    return [tuple(v) for v in found.values()]


# 0.6.98 (Vorabprüfung am Mac: Tags von CHECKER WELT u. a.): zu allgemeine Wörter taugen nicht als Suchthema, wohl aber
# als Kindersignal; Personennamen (Moderation) und Plattformwörter werden nie gesucht.
GENERIC_TAGS = frozenset({'kinder', 'kids', 'video für kinder', 'videos für kinder', 'kinderfrage', 'lernen', 'schule', 'schulwissen',
                          'wissen', 'education', 'bildung', 'video', 'videos', 'deutsch', 'german', 'lustig', 'spaß', 'neu', 'folge',
                          'ganze folge', 'serie', 'kinderserie', 'kinderfernsehen', 'für kinder', 'familie', 'unterhaltung'})
_PLATFORM = re.compile(r'instagram|tiktok|youtube|shorts?\b|abonnier|kanal\b|channel|twitter|facebook|snapchat|twitch|podcast', re.I)
_PERSON = re.compile(r'[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)? [A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?')
# Kindersignale im Kanalnamen: öffentlich-rechtlich, Bildung, Museen, Verlage (Rang hoch) und typische Spielzeug-/Klick-
# Kanäle (Rang tief, Hinweis). Keine Bewertung von Inhalten, nur eine Reihenfolge; die Freigabe bleibt Björns Entscheidung.
_KIDS_GOOD = re.compile(r'\b(?:ard|zdf|kika|wdr|swr|br|ndr|mdr|hr|rbb|orf|srf|3sat|arte|checker|maus|planet schule|terra x|logo!?|'
                        r'museum|bibliothek|verlag|schule|wissen|forscher|experiment|lern|universität|stiftung|zoo)\b', re.I)
_KIDS_BAD = re.compile(r'toys?\b|spielzeug|unboxing|prank|challenge|gaming|minecraft|roblox|fortnite|diana|nastya|vania|'
                       r'geniale tricks|5-minute|magic|asmr|slime|surprise|überraschung', re.I)


_KIDS_WORDS = re.compile(r'\b(?:für kinder|kinder\w*|kindgerecht|erklärt|erklärvideo|sachgeschichten?|basteln|bastel\w*|malen|'
                         r'märchen|tierwissen|sendung mit der maus|sesamstraße|löwenzahn|wissen macht ah)\b', re.I)
_DE = re.compile(r'[äöüß]|\b(?:der|die|das|und|mit|für|ist|wie|was|ein|eine|nicht|wir|ich|auf|zum|vom|im)\b', re.I)
_EN = re.compile(r'\b(?:the|and|with|how|what|you|your|my|for|is|are|this|we|of|to|vs|best|ever|who|vs\.)\b', re.I)


def kids_signal(title, videos=()):
    """+1 (öffentlich-rechtlich/Bildung/Kinderwörter), -1 (Spielzeug-/Klick-Kanal) oder 0 nach Kanalname und
    (seit der Nachbesserung 0.6.106) den Titeln der neuesten Videos: zwei Treffer unter den Videotiteln zählen."""
    title = str(title or '')
    titles = [str(v or '') for v in videos or ()]
    if _KIDS_BAD.search(title) or sum(1 for v in titles if _KIDS_BAD.search(v)) >= 2:
        return -1
    if _KIDS_GOOD.search(title) or _KIDS_WORDS.search(title):
        return 1
    return 1 if sum(1 for v in titles if _KIDS_GOOD.search(v) or _KIDS_WORDS.search(v)) >= 2 else 0


def language(texts):
    """'de', 'en' oder '' (unklar) nach einfachen Wortzählungen in Kanalname und Videotiteln."""
    de = en = 0
    for text in texts or ():
        text = str(text or '')
        de += len(_DE.findall(text))
        en += len(_EN.findall(text))
    if de + en < 3:
        return ''
    return 'de' if de >= en else ('en' if en >= 2 * max(de, 1) else '')


def search_terms(db, watched, names, limit=SEARCH_TAGS):
    """Häufigste Schlagwörter der zu Ende gesehenen Videos (ohne Kanalnamen, Zahlen, Ein-Wort-Füller); ``discover``
    nimmt ohne gesehene Videos die Schlagwörter aller geladenen Abo-Videos."""
    if not watched:
        return []
    counts, shown = {}, {}
    names = {n.lower() for n in names if n}
    for start in range(0, len(watched), 400):
        chunk = watched[start:start + 400]
        for (tags,) in db.execute('SELECT tags FROM youtube_tagged WHERE video IN (%s)' % ','.join('?' * len(chunk)), chunk):
            try:
                tags = json.loads(tags)
            except ValueError:
                continue
            for t in {str(x).strip() for x in tags}:
                key = t.lower()
                if len(key) < 3 or key.isdigit() or key in names or key.startswith('#') or any(n and n in key for n in names) \
                        or key in GENERIC_TAGS or _PLATFORM.search(key) or _PERSON.fullmatch(t):
                    continue
                counts[key] = counts.get(key, 0) + 1
                shown.setdefault(key, t)
    need = 2 if len(watched) >= 3 else 1
    best = sorted((k for k in counts if counts[k] >= need), key=lambda k: (-counts[k], k))
    return [shown[k] for k in best[:limit]]


def backfill_descriptions(root, db, videos, runner=None, limit=BACKFILL_PER_RUN):
    """0.6.98: Beschreibungen bereits geladener Videos nachholen (vor 0.6.90 nicht gespeichert). Ein yt-dlp-Aufruf für
    bis zu ``limit`` Videos, ohne Download (``--skip-download``), mit Pause zwischen den Anfragen. Gesehene zuerst."""
    import youtube_downloads
    tried = {r[0] for r in db.execute('SELECT video FROM youtube_tagged')}
    todo = [v for v in videos if v not in tried and youtube.VALID_VIDEO.fullmatch(v)][:limit]
    if not todo:
        return 0
    tool = youtube_downloads.find_tool(root)
    if not tool:
        return 0
    args = [*tool[0], '--ignore-config', '--skip-download', '--no-playlist', '--no-warnings', '--no-cookies-from-browser',
            '--ignore-errors', '--ignore-no-formats-error', '--sleep-requests', '1', '--sleep-interval', '2',
            *youtube_downloads.js_args(root, tool), '--print', '%(id)s\t%(description)j\t%(tags)j', *[youtube.video_url(v) for v in todo]]
    result = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=LIST_TIMEOUT + 30 * len(todo),
                                        stdin=subprocess.DEVNULL, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    got = 0
    now = time.time()
    with db:
        for line in (result.stdout or '').splitlines():
            vid, _, rest = line.partition('\t')
            if vid not in todo:
                continue
            text, _, tags = rest.partition('\t')
            try:
                text = json.loads(text) if text else ''
            except ValueError:
                text = ''
            try:
                tags = json.loads(tags) if tags else []
            except ValueError:
                tags = []
            tags = [' '.join(str(t).split())[:40] for t in (tags if isinstance(tags, list) else []) if isinstance(t, str) and t.strip()][:30]
            db.execute('INSERT OR REPLACE INTO youtube_tagged(video,tags,at) VALUES(?,?,?)', (vid, json.dumps(tags, ensure_ascii=False), now))
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


# ---------------------------------------------------------------- Vorschläge auflösen (Name, Kanalbild, Videotitel)

_MISSING = re.compile(r'does not exist|not found|404|nicht gefunden|unavailable|terminated|has been removed', re.I)


def resolve(root, db, refs, now, request, runner, budget):
    """{ref: info} mit Name, Kanalbild, Kanal-ID, Titeln der neuesten Videos und Sprache. Je Kanal höchstens alle vier
    Wochen ein Listenabruf (``budget`` = [erlaubte Abrufe]); ``info['missing']``: Kanal gibt es nicht (Tippfehler,
    gelöscht), der Vorschlag entfällt. Andere Fehler (Netz, Bremse) werden beim nächsten Lauf neu versucht."""
    import youtube_abos
    import download_retry
    known = {r[0]: (r[1], r[2]) for r in db.execute('SELECT ref,title,avatar FROM youtube_suggestions')}
    out = {}
    for ref in refs:
        title, avatar = known.get(ref, ('', ''))
        try:                                      # eigener Speicher: auch weggefallene (fehlend, abonniert, doppelt)
            info = json.loads(youtube._get(db, 'resolve:' + ref, '{}'))
        except ValueError:
            info = {}
        if info.get('at', 0) > now - 4 * WEEK:
            out[ref] = info
            continue
        if budget[0] <= 0 or download_retry.blocked_until('youtube', time.time())[0]:
            if info:
                out[ref] = info
            continue
        budget[0] -= 1
        fake = {'id': 0, 'ref': ref, 'kind': 'channel', 'title': title, 'channel_id': ref if ref.startswith('UC') else '',
                'playlist': '', 'avatar': avatar}
        try:
            if request is not None:
                channel, videos = youtube_abos.list_with_api(root, fake, RESOLVE_VIDEOS, request)
            else:
                channel, videos = youtube_abos.list_with_ytdlp(fake, RESOLVE_VIDEOS, runner=runner, root=root)
        except Exception as exc:                  # noqa: BLE001 – ein unlesbarer Kanal hält die übrigen nicht auf
            message = str(exc) or type(exc).__name__
            if _MISSING.search(message):
                out[ref] = {'at': now, 'missing': True}
                with db:
                    youtube._set(db, 'resolve:' + ref, json.dumps(out[ref]))
            elif info:
                out[ref] = info
            continue
        titles = [v['title'] for v in videos if v.get('title')][:RESOLVE_VIDEOS]
        out[ref] = {'at': now, 'title': channel.get('title') or '', 'channel_id': channel.get('channel_id') or '',
                    'avatar': channel.get('avatar') or '', 'videos': titles,
                    'lang': language([channel.get('title') or '', *titles])}
        with db:
            youtube._set(db, 'resolve:' + ref, json.dumps(out[ref], ensure_ascii=False))
    return out


# ---------------------------------------------------------------- Vorschläge berechnen

def _weight(finished):
    return 1.0 + math.log2(1 + max(0, finished))


def discover(root, c=None, now=None, request=None, runner=None, seen=None, probe=False):
    """Vorschläge neu berechnen. Gibt die Zahl offener Vorschläge zurück.

    ``probe`` (Prüflauf, POST /api/youtube-discover {"action": "search", "probe": true}): auch pausierte Abos und
    ohne den Wochenspeicher, damit Playlist- und Suchquelle in einer Prüfinstanz mit abgeschalteten Abos laufen."""
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
        rows = [dict(r) for r in adb.execute("SELECT abo_id,video,job_id,state,title FROM youtube_abo_videos WHERE state IN ('done','archived')")]
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
        for r in rows:                       # 0.6.98: Zusammenarbeiten im Titel („mit @Kanal“)
            for ref in mentions(r.get('title') or ''):
                if ref not in mention_rows.setdefault(r['video'], []):
                    mention_rows[r['video']].append(ref)
        scores, why, profile_score, titles = {}, {}, {}, {}
        sources = {'featured': 0, 'playlists': 0, 'mentions': 0, 'search': 0, 'search_fallback': 0}
        mention_abos, other_source = {}, set()

        def add(ref, points, reason, profile, title='', source='mentions', abo=None):
            ref = norm(ref)
            if not ref or ref in subscribed or points <= 0 or _LOST_ID.fullmatch(ref):
                return
            sources[source] += 1
            if source == 'mentions':
                mention_abos.setdefault(ref, set()).add(abo)
            else:
                other_source.add(ref)
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
            if a['enabled'] or probe:
                for ref, title in (_featured(root, db, a, now, request, runner, budget if not paused else [0], probe) or []):
                    add(ref, 3 * w, 'von „%s“ empfohlen' % name, a['profile'], title, 'featured')
                for ref, title, count, playlist in (_playlists(root, db, a, now, request, runner, budget if not paused else [0], probe) or []):
                    add(ref, 2 * w + 0.5 * min(count - 1, 4),
                        'in der Playlist „%s“ von „%s“ (%s)' % (playlist, name, 'ein Video' if count == 1 else '%d Videos' % count),
                        a['profile'], title, 'playlists')
            counted = {}
            for vid, done in videos:
                for ref in mention_rows.get(vid, []):
                    n = counted.setdefault(ref, [0, 0])
                    n[0 if done else 1] += 1
            # Nachbesserung 0.6.106: ein Abo, das in jeder Beschreibung dieselben Partnerkanäle nennt, füllt die Liste nicht
            best = sorted(counted.items(), key=lambda kv: (-(min(kv[1][0], 5) + 0.3 * min(kv[1][1], 5)), kv[0]))[:MENTIONS_PER_ABO]
            for ref, (watched, unwatched) in best:
                points = min(watched, 5) + 0.3 * min(unwatched, 5)
                n = watched or unwatched
                text = ('in %s von „%s“ erwähnt' % ((('einem gesehenen Video' if n == 1 else '%d gesehenen Videos' % n) if watched else
                                                     ('einem Video' if n == 1 else '%d Videos' % n)), name))
                add(ref, points, text, a['profile'], source='mentions', abo=a['id'])
        # 0.6.98: YouTube-Suche nach den häufigsten Schlagwörtern der zu Ende gesehenen Videos je Profil
        _RUNNING['progress'] = 'Themen gesehener Videos werden gesucht …'
        profile_of = {a['id']: a['profile'] for a in abos}
        names = [a['label'] or a['title'] or '' for a in abos]
        for profile in sorted({a['profile'] for a in abos}):
            watched = [v for abo_id, items in by_abo.items() if profile_of.get(abo_id) == profile for v, d in items if d]
            terms, source, label = search_terms(db, watched, names), 'search', 'Thema gesehener Videos'
            if not terms:                    # Nachbesserung 0.6.106: noch nichts zu Ende gesehen → Themen aller Abo-Videos
                every = [v for abo_id, items in by_abo.items() if profile_of.get(abo_id) == profile for v, _d in items]
                terms, source, label = search_terms(db, every, names), 'search_fallback', 'Thema der Abo-Videos'
            for term in terms:
                query = term + (' für Kinder' if profile == 'kinder' and 'kind' not in term.lower() else '')
                fetch = (lambda t=query: search_channels_api(request, t)) if request is not None else \
                    (lambda t=query: search_channels_ytdlp(root, t, runner))
                for ref, title, hits in _cached(db, 'search:%s:%s' % (profile, term.lower()), now, budget if not paused else [0], fetch, probe):
                    add(ref, (1.0 if source == 'search' else 0.8) + 0.3 * min(hits - 1, 3), 'YouTube-Suche nach „%s“ (%s)' % (term, label),
                        profile, title, source)
        for ref, abos_seen in mention_abos.items():
            if ref in scores and ref not in other_source and len(abos_seen) == 1:
                scores[ref] *= SINGLE_SOURCE
        # Nachbesserung 0.6.106: die besten Vorschläge auflösen (Name, Kanalbild, Kanal-ID, Videotitel, Sprache)
        _RUNNING['progress'] = 'Vorgeschlagene Kanäle werden gelesen …'
        top = sorted(scores, key=lambda r: -scores[r])[:MAX_SUGGESTIONS + 10]
        infos = resolve(root, db, top, now, request, runner, [RESOLVE_PER_RUN] if not paused else [0])
        by_channel = {}
        for ref in top:
            info = infos.get(ref) or {}
            cid = norm(info.get('channel_id'))
            if info.get('missing') or (cid and cid in subscribed):
                scores.pop(ref, None)
                continue
            if info.get('title') and not titles.get(ref):
                titles[ref] = info['title']
            if cid:
                first = by_channel.setdefault(cid, ref)
                if first != ref:                 # derselbe Kanal unter Handle und Kennung: zusammenlegen
                    scores[first] += scores.pop(ref)
                    why[first].extend(w for w in why[ref] if w not in why[first])
                    for k, v in profile_score[ref].items():
                        profile_score[first][k] = profile_score[first].get(k, 0) + v
        with db:
            known = {r['ref']: dict(r) for r in db.execute('SELECT * FROM youtube_suggestions')}
            for ref, old in known.items():
                if old['state'] == 'new' and (ref not in scores or ref in subscribed):
                    db.execute('DELETE FROM youtube_suggestions WHERE ref=?', (ref,))
            for ref in scores:                   # Kinder-Vorschläge nach Kindersignalen und Sprache ordnen
                if max(profile_score[ref], key=profile_score[ref].get) != 'kinder':
                    continue
                info = infos.get(ref) or {}
                signal = kids_signal(titles.get(ref) or (known.get(ref) or {}).get('title') or ref, info.get('videos') or ())
                if signal > 0:
                    scores[ref] *= 1.5
                    why[ref].insert(0, 'Kindersignal in Name oder Videotiteln (öffentlich-rechtlich, Bildung, für Kinder)')
                elif signal < 0:
                    scores[ref] *= 0.3
                    why[ref].insert(0, 'Achtung: Name oder Videotitel deuten auf Spielzeug-/Klick-Kanal')
                else:
                    scores[ref] *= 0.5
                    why[ref].append('kein Kindersignal in Name und Videotiteln' if info.get('videos') else 'Kanal noch nicht gelesen')
                if info.get('lang') == 'en':
                    scores[ref] *= 0.3
                    why[ref].insert(0, 'englischsprachig')
            ranked = sorted(scores, key=lambda r: -scores[r])[:MAX_SUGGESTIONS]
            for ref in ranked:
                profile = max(profile_score[ref], key=profile_score[ref].get)
                old = known.get(ref)
                if old and old['state'] != 'new':
                    continue                             # entschieden: bleibt, wie Björn es entschieden hat
                info = infos.get(ref)
                if old:
                    db.execute('UPDATE youtube_suggestions SET score=?,why=?,profile=?,updated=?,title=CASE WHEN title=\'\' THEN ? ELSE title END,'
                               'avatar=CASE WHEN avatar=\'\' THEN ? ELSE avatar END,info=CASE WHEN ? THEN ? ELSE info END WHERE ref=?',
                               (round(scores[ref], 2), json.dumps(why[ref][:6]), profile, now, titles.get(ref, ''),
                                (info or {}).get('avatar') or '', bool(info), json.dumps(info or {}, ensure_ascii=False), ref))
                else:
                    db.execute('INSERT INTO youtube_suggestions(ref,title,avatar,score,why,profile,found,updated,info) VALUES(?,?,?,?,?,?,?,?,?)',
                               (ref, titles.get(ref, ''), (info or {}).get('avatar') or '', round(scores[ref], 2), json.dumps(why[ref][:6]),
                                profile, now, now, json.dumps(info, ensure_ascii=False) if info else ''))
            youtube._set(db, 'discover_last', str(now))
            count = db.execute("SELECT COUNT(*) FROM youtube_suggestions WHERE state='new'").fetchone()[0]
    finally:
        db.close()
    _notify('youtube_discover_done', open=count, network_reads=FEATURED_PER_RUN - budget[0], paused=paused,
            described=len(mention_rows), probe=bool(probe), resolved=sum(1 for i in infos.values() if i.get('title')), **sources)
    _RUNNING['sources'] = dict(sources)
    return count


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except Exception:
        pass


def start(root, force=False, now=None, probe=False):
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
            discover(root, probe=probe)
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
    return {'suggestions': states, 'videos_with_description': mentions_n, 'last': last, 'error': _RUNNING['last_error'][:120],
            'sources': _RUNNING.get('sources') or {}}
