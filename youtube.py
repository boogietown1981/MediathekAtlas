"""YouTube: complete free films and series that rights holders upload to their own channels (0.5.53).

Björn (12.11.2026): "eine YouTube-Schnittstelle … auch hier gibt es immer wieder kostenlose Filme in
Channels, die man sich anschauen kann, da sie direkt von den Rechteinhabern wie Sony etc.
hochgeladen werden". Shown in the established format: catalogue and platform tab, tiles, the shared
title and series page, overview card and the shared IMDb/TVDB/TMDB check (reference_share, no
double look-ups).

* Curated, not a search: only channels and playlists listed under "YouTube-Kanäle" are read
  (official channels of studios and distributors; Björn can add and remove them). From a channel
  only complete films are taken: minimum length (default 60 minutes), no trailers, clips, making-of,
  live streams; a playlist can be added as a series (each video one episode).
* Catalogue through the official YouTube Data API v3 with Björn's own free API key
  (Google Cloud, quota 10,000 units a day). A run costs about two units per 50 videos; video facts
  are cached for a week, so daily refreshes stay far below the quota. No scraping of youtube.com.
* Availability: videos blocked in Germany (regionRestriction), private, not yet processed, live
  and upcoming streams are left out. Not embeddable or age-restricted videos stay in the catalogue
  but only link to youtube.com (the embedded player refuses them).
* Playback: the official embedded YouTube player (youtube-nocookie.com) inside the MediathekAtlas
  player window, with the adverts YouTube shows. This is the playback YouTube's terms allow.
* Offline copies: YouTube's terms forbid downloading except through a download function YouTube
  itself provides (YouTube Premium, in YouTube's apps) or with prior written permission of YouTube
  and the rights holder. Björn decided (12.11.2026): opt-in switch, off by default, 30 days on his
  own responsibility (youtube_downloads). The stored ``offline`` column stays 0; the views compute
  it from the switch (offline_flag).

The API key never goes to logs, the diagnosis export or the browser; titles and URLs are not logged.
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

API = 'https://www.googleapis.com/youtube/v3/'
SITE = 'https://www.youtube.com'
EMBED = 'https://www.youtube-nocookie.com/embed/'
REGION = 'DE'
MAX_ANSWER = 8 * 1024 * 1024
MAX_PER_SOURCE = 5000             # videos read from one channel/playlist
MAX_SOURCES = 60
VIDEO_TTL = 7 * 86400             # video facts are re-read weekly
REQUEST_GAP = 0.2
MOVIE_MINUTES = 60
EPISODE_MINUTES = 10
VIDEO_ID = r'[A-Za-z0-9_-]{11}'
PLAYLIST_ID = r'[A-Za-z0-9_-]{12,64}'
CHANNEL_ID = r'UC[A-Za-z0-9_-]{22}'
HANDLE = r'@[A-Za-z0-9._\-]{3,30}'
VALID_ID = re.compile(r'(?:[ve]\.%s|s\.%s)' % (VIDEO_ID, PLAYLIST_ID))
VALID_VIDEO = re.compile(VIDEO_ID)
ENDPOINTS = ('channels', 'playlists', 'playlistItems', 'videos')
IMAGE_HOST = 'i.ytimg.com'
NO_OFFLINE = ('YouTube erlaubt das Herunterladen nur über eigene Funktionen (YouTube Premium in den '
              'YouTube-Apps) oder mit schriftlicher Erlaubnis von YouTube und Rechteinhaber. MediathekAtlas '
              'speichert YouTube-Filme deshalb nicht offline.')
NO_KEY = ('Kein YouTube-API-Schlüssel hinterlegt. Unter „YouTube-Kanäle & API-Schlüssel“ einen kostenlosen '
          'Schlüssel für die YouTube Data API v3 eintragen.')

# Suggestions shown on first start (Björn can remove them). Handles were not reachable from the
# build environment (youtube.com blocked there): a handle YouTube does not know is reported per
# source as "nicht gefunden" and changes nothing else.
DEFAULT_SOURCES = (
    ('@FilmRiseMovies', 'movies', 'FilmRise Movies (Verleih, englisch)'),
    ('@ParamountVault', 'movies', 'Paramount Vault (Studio, englisch)'),
    ('@Popcornflix', 'movies', 'Popcornflix (Verleih, englisch)'),
)

_KEY = lambda: ''                 # set by server.configure(): returns the stored API key
_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', raw_title TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '', source_id INTEGER,
  playable INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL DEFAULT '', offline INTEGER NOT NULL DEFAULT 0,
  drm INTEGER NOT NULL DEFAULT 0, web_url TEXT NOT NULL DEFAULT '', seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS youtube_items_kind ON youtube_items(kind, seen);
CREATE INDEX IF NOT EXISTS youtube_items_series ON youtube_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS youtube_videos(id TEXT PRIMARY KEY, payload TEXT NOT NULL, checked REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'movies',
  label TEXT NOT NULL DEFAULT '', min_minutes INTEGER NOT NULL DEFAULT 60, enabled INTEGER NOT NULL DEFAULT 1,
  suggested INTEGER NOT NULL DEFAULT 0, channel_id TEXT NOT NULL DEFAULT '', playlist TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', videos INTEGER NOT NULL DEFAULT 0, films INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '', checked REAL NOT NULL DEFAULT 0, added REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def configure(key_source):
    """Server hook: callable returning the stored API key (settings 'youtube')."""
    global _KEY
    _KEY = key_source


def _notify(event, **details):
    """Technical counters only; never URLs, keys or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'youtube.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(SCHEMA)
    if 'skipped' not in {r[1] for r in db.execute('PRAGMA table_info(youtube_sources)')}:
        db.execute("ALTER TABLE youtube_sources ADD COLUMN skipped TEXT NOT NULL DEFAULT '{}'")   # 0.5.54
    if _get(db, 'seeded') != '1':
        with db:
            for ref, kind, label in DEFAULT_SOURCES:
                db.execute('INSERT OR IGNORE INTO youtube_sources(ref,kind,label,min_minutes,suggested,added) '
                           'VALUES(?,?,?,?,1,?)', (ref, kind, label, MOVIE_MINUTES, time.time()))
            _set(db, 'seeded', '1')
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM youtube_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO youtube_state(name,value) VALUES(?,?)', (key, str(value)))


# ---------------------------------------------------------------- helpers

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


def duration_seconds(value):
    """ISO 8601 duration of the API (PT1H32M10S, P1DT2H) -> seconds."""
    m = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', str(value or ''))
    if not m or not any(m.groups()):
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def image(value):
    value = str(value or '')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != 'https' or (parts.hostname or '').lower() != IMAGE_HOST or parts.port or parts.username \
            or len(value) > 400 or re.search(r'[\s<>"\']', value):
        return ''
    return value


def _thumb(snippet):
    thumbs = snippet.get('thumbnails') if isinstance(snippet.get('thumbnails'), dict) else {}
    for size in ('maxres', 'standard', 'high', 'medium', 'default'):
        url = image((thumbs.get(size) or {}).get('url') if isinstance(thumbs.get(size), dict) else '')
        if url:
            return url
    return ''


def video_url(video_id):
    return '%s/watch?v=%s' % (SITE, video_id) if VALID_VIDEO.fullmatch(str(video_id or '')) else ''


def playlist_url(playlist_id):
    return '%s/playlist?list=%s' % (SITE, playlist_id) if re.fullmatch(PLAYLIST_ID, str(playlist_id or '')) else ''


def parse_ref(text):
    """User input -> canonical reference: '@handle', 'UC…' (channel) or 'PL…' (playlist)."""
    value = str(text or '').strip()
    if len(value) > 300:
        raise ValueError('Adresse zu lang')
    if re.fullmatch(HANDLE, value) or re.fullmatch(CHANNEL_ID, value):
        return value
    if re.fullmatch(r'(?:PL|OL|FL|UU)[A-Za-z0-9_-]{10,62}', value):
        return value
    if not re.match(r'https?://', value):
        value = 'https://' + value
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or '').lower()
    if host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        raise ValueError('Bitte eine Adresse von youtube.com angeben (Kanal, @Handle oder Playlist)')
    playlist = urllib.parse.parse_qs(parts.query).get('list', [''])[0]
    if playlist and re.fullmatch(PLAYLIST_ID, playlist):
        return playlist
    segments = [s for s in parts.path.split('/') if s]
    if segments and re.fullmatch(HANDLE, urllib.parse.unquote(segments[0])):
        return urllib.parse.unquote(segments[0])
    if len(segments) >= 2 and segments[0] == 'channel' and re.fullmatch(CHANNEL_ID, segments[1]):
        return segments[1]
    if len(segments) >= 2 and segments[0] == 'user' and re.fullmatch(r'[A-Za-z0-9]{3,40}', segments[1]):
        return 'user:' + segments[1]
    raise ValueError('Adresse nicht erkannt. Möglich: youtube.com/@Kanal, youtube.com/channel/UC…, '
                     'youtube.com/playlist?list=…')


# Title cleaning: "Der Pate (Ganzer Film Deutsch, HD) | Krimi | 1972" -> "Der Pate", 1972, Krimi.
_NOISE = re.compile(r'\b(?:ganze[rn]?\s+(?:spiel)?film(?:e)?|spielfilm|kompletter\s+film|in\s+voller\s+länge|'
                    r'full\s+(?:length\s+)?(?:movie|film)|free\s+(?:full\s+)?movie|kostenlos(?:\s+(?:anschauen|schauen|sehen))?|'
                    r'(?:auf\s+)?deutsch|german|english|englisch|(?:full\s+)?hd|4k|uhd|1080p|720p|in\s+hd|'
                    r'film\s+(?:auf\s+)?deutsch|ganzer\s+film\s+auf\s+deutsch|online\s+(?:schauen|sehen|anschauen)|gratis|'
                    r'synchronfassung|ov|omu|uncut|remastered|restauriert|mit\s+untertiteln|untertitel|subtitles?|'
                    r'ganzer\s+western|ganzer\s+krimi|ganzer\s+thriller|ganzer\s+horrorfilm)\b', re.I)
_EXCLUDE = re.compile(r'\b(?:trailer|teaser|making[\s-]?of|behind\s+the\s+scenes|featurette|clip|ausschnitt|'
                      r'interview|best\s+of|compilation|zusammenschnitt|hörbuch|audiobook|podcast|livestream|'
                      r'live\s+stream|24/7|reaction|review|kritik|recap|soundtrack|full\s+album|shorts?)\b', re.I)
GENRES = {
    'action': 'Action', 'actionfilm': 'Action', 'abenteuer': 'Abenteuer', 'adventure': 'Abenteuer',
    'animation': 'Animation', 'anime': 'Animation', 'biografie': 'Biografie', 'biopic': 'Biografie',
    'biography': 'Biografie', 'comedy': 'Komödie', 'komödie': 'Komödie', 'crime': 'Krimi', 'krimi': 'Krimi',
    'doku': 'Dokumentation', 'dokumentation': 'Dokumentation', 'documentary': 'Dokumentation',
    'drama': 'Drama', 'familie': 'Familie', 'familienfilm': 'Familie', 'family': 'Familie', 'fantasy': 'Fantasy',
    'historie': 'Historie', 'history': 'Historie', 'horror': 'Horror', 'horrorfilm': 'Horror',
    'kinderfilm': 'Kinder', 'kinder': 'Kinder', 'kids': 'Kinder', 'kriegsfilm': 'Kriegsfilm', 'war': 'Kriegsfilm',
    'liebesfilm': 'Romantik', 'romance': 'Romantik', 'romantik': 'Romantik', 'romanze': 'Romantik',
    'musik': 'Musik', 'musical': 'Musik', 'mystery': 'Mystery', 'sci-fi': 'Science-Fiction', 'scifi': 'Science-Fiction',
    'science fiction': 'Science-Fiction', 'science-fiction': 'Science-Fiction', 'sport': 'Sport',
    'thriller': 'Thriller', 'western': 'Western', 'erotik': 'Erotik', 'martial arts': 'Action', 'kung fu': 'Action',
}
def genres_in(text):
    """Known genre words in a text part ("Thriller", "Action & Abenteuer", "Sci-Fi")."""
    low = str(text or '').lower()
    out = []
    for word, name in GENRES.items():
        if re.search(r'(?<![\w-])' + re.escape(word) + r'(?![\w-])', low) and name not in out:
            out.append(name)
    return out


_SEP = re.compile(r'\s+[|–—/]+\s+|\s+-\s+|\s*\|\s*|\s*//\s*')


def clean_title(raw, channel=''):
    """(title, year, genres, language) from a YouTube video title."""
    text = _text(raw, 300)
    year = None
    language = ''
    low = text.lower()
    if re.search(r'\b(?:deutsch|german|synchronfassung)\b', low):
        language = 'Deutsch'
    elif re.search(r'\b(?:english|englisch|full\s+movie)\b', low):
        language = 'Englisch'
    genres = []
    # Bracketed parts: keep a year, drop noise ("(1972)", "[Ganzer Film, HD]").
    def bracket(m):
        nonlocal year
        inner = m.group(1)
        found = re.fullmatch(r'\s*((?:19|20)\d\d)\s*', inner)
        if found:
            year = year or int(found.group(1))
            return ' '
        for word in re.split(r'[,;/|]', inner):
            g = GENRES.get(word.strip().lower())
            if g and g not in genres:
                genres.append(g)
        rest = _NOISE.sub('', inner)
        rest = re.sub(r'(?:19|20)\d\d', '', rest)
        if not year:
            y = re.search(r'\b((?:19|20)\d\d)\b', inner)
            if y:
                year = int(y.group(1))
        stripped = re.sub(r'[\s,;:./|&+\-]+', '', rest)
        if not stripped or genres_in(inner):
            return ' '
        return m.group(0)
    text = re.sub(r'[\(\[\{]([^\)\]\}]{0,80})[\)\]\}]', bracket, text)
    parts = [p.strip(' -–—:|') for p in _SEP.split(text) if p and p.strip(' -–—:|')]
    title = ''
    for part in parts:
        low = part.lower()
        y = re.fullmatch(r'((?:19|20)\d\d)', part)
        if y:
            year = year or int(y.group(1))
            continue
        if low in GENRES:
            if GENRES[low] not in genres:
                genres.append(GENRES[low])
            continue
        if channel and low == channel.lower():
            continue
        cleaned = _NOISE.sub(' ', part)
        cleaned = re.sub(r'\b(?:film|filme)\b\s*$', '', cleaned, flags=re.I)
        cleaned = ' '.join(cleaned.split()).strip(' -–—:,|')
        if not title and re.sub(r'\W', '', cleaned):
            title = cleaned
        elif title:
            for g in genres_in(low):
                if g not in genres:
                    genres.append(g)
            y = re.search(r'\b((?:19|20)\d\d)\b', part)
            if y and not year:
                year = int(y.group(1))
    if not title:
        title = _text(raw, 200)
    trailing = re.search(r'\s+\(?((?:19|20)\d\d)\)?$', title)
    if trailing and len(title) > len(trailing.group(0)) + 1:
        year = year or int(trailing.group(1))
        title = title[:trailing.start()].strip()
    if len(title) > 3 and title.isupper():
        title = ' '.join(w.capitalize() if w.isalpha() else w for w in title.split())
    return title[:200], year, genres, language


def episode_numbers(raw, position=None):
    """(season, episode) from "S01E02", "Staffel 2 Folge 5", "Folge 3", "Episode 4"; else playlist order."""
    text = str(raw or '')
    m = re.search(r'\bS(\d{1,2})\s*[ .]?E(\d{1,3})\b', text, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'\b(?:Staffel|Season)\s*(\d{1,2})\D{0,12}?(?:Folge|Episode|Ep\.?|Teil)\s*(\d{1,3})\b', text, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'\b(?:Folge|Episode|Ep\.?|Teil|Part)\s*(\d{1,3})\b', text, re.I)
    if m:
        return 1, int(m.group(1))
    return (1, position + 1) if isinstance(position, int) and position >= 0 else (None, None)


def episode_title(raw, series_title):
    text = _text(raw, 200)
    if series_title and text.lower().startswith(series_title.lower()):
        text = text[len(series_title):]
    text = re.sub(r'\b(?:S\d{1,2}\s*E\d{1,3}|(?:Staffel|Season)\s*\d+|(?:Folge|Episode|Ep\.?|Teil|Part)\s*\d+)\b', ' ', text, flags=re.I)
    text = _NOISE.sub(' ', text)
    text = ' '.join(text.split()).strip(' -–—:|,.')
    return text[:200]


def summary_text(description):
    """First lines of a description without links, hashtags and channel advertising."""
    lines = []
    for line in str(description or '').splitlines():
        line = line.strip()
        low = line.lower()
        if not line:
            if lines:
                lines.append('')
            continue
        if re.search(r'https?://|www\.|#\w|abonnier|subscribe|instagram|facebook|tiktok|twitter|newsletter|©', low):
            continue
        lines.append(line)
        if sum(len(x) for x in lines) > 1400:
            break
    return _text(' '.join(lines), 1600)


def video_facts(node, region=REGION):
    """Facts of one videos.list entry, or None for anything not listable (private, live, blocked here)."""
    if not isinstance(node, dict) or not VALID_VIDEO.fullmatch(str(node.get('id') or '')):
        return None
    snippet = node.get('snippet') if isinstance(node.get('snippet'), dict) else {}
    details = node.get('contentDetails') if isinstance(node.get('contentDetails'), dict) else {}
    status = node.get('status') if isinstance(node.get('status'), dict) else {}
    if status.get('privacyStatus') not in (None, 'public', 'unlisted') or status.get('uploadStatus') not in (None, 'processed'):
        return None
    if snippet.get('liveBroadcastContent') not in (None, 'none'):
        return None
    restriction = details.get('regionRestriction') if isinstance(details.get('regionRestriction'), dict) else {}
    allowed, blocked = restriction.get('allowed'), restriction.get('blocked')
    if (isinstance(allowed, list) and region not in allowed) or (isinstance(blocked, list) and region in blocked):
        return None
    rating = details.get('contentRating') if isinstance(details.get('contentRating'), dict) else {}
    age = rating.get('ytRating') == 'ytAgeRestricted'
    fsk = {'fskUnrated': '', 'fsk0': 'FSK 0', 'fsk6': 'FSK 6', 'fsk12': 'FSK 12', 'fsk16': 'FSK 16', 'fsk18': 'FSK 18'}.get(rating.get('fskRating'), '')
    embeddable = status.get('embeddable') is not False
    reason = ''
    if age:
        reason = 'Altersbeschränkt: YouTube zeigt das Video nur angemeldet auf youtube.com'
    elif not embeddable:
        reason = 'Der Kanal erlaubt keine Einbettung; nur auf youtube.com abspielbar'
    return {'id': node['id'], 'title': _text(snippet.get('title'), 300),
            'description': str(snippet.get('description') or '')[:5000],
            'channel': _text(snippet.get('channelTitle'), 120), 'published': _text(snippet.get('publishedAt'), 30),
            'language': _text(snippet.get('defaultAudioLanguage') or snippet.get('defaultLanguage'), 12),
            'duration': duration_seconds(details.get('duration')), 'poster': _thumb(snippet),
            'playable': not age and embeddable, 'reason': reason, 'rating': 'FSK 18' if age and not fsk else fsk,
            'kids': status.get('madeForKids') is True}


# 0.5.54 (Björn, 12.11.2026): channels also upload promo videos that reach the minimum length.
# The format check is ArchiveMedia's video_triage (vendor/archive_portals, imported, not copied, so
# updates of the ArchiveMedia modules apply here too), plus the video description: release
# advertising ("jetzt im Kino", "ab … auf Blu-ray", "offizieller Trailer") marks a promo unless the
# title or description itself says it is the complete film.
PROMO = re.compile(r'(?:\b(?:jetzt|ab\s+sofort|ab\s+\d{1,2}\.\s*\w*|ab\s+dem\s+\d{1,2}\.)\s+(?:\w+\s+){0,2}(?:im\s+kino|in\s+den\s+kinos|'
                   r'auf\s+(?:dvd|blu-?ray|4k|uhd)|digital\s+(?:erhältlich|verfügbar|kaufen|leihen)|als\s+download|vorbestellen)|'
                   r'offizielle[rs]?\s+(?:trailer|teaser)|official\s+(?:trailer|teaser|clip)|in\s+theaters|'
                   r'now\s+(?:on|available\s+on)\s+(?:digital|blu-?ray|dvd)|pre-?order|vorbestellen|'
                   r'making[\s-]?of|behind\s+the\s+scenes|featurette|interview\s+mit|exklusiver?\s+ausschnitt)', re.I)
COMPLETE = re.compile(r'\b(?:ganzer\s+(?:spiel)?film|ganze\s+folge|kompletter\s+film|in\s+voller\s+länge|spielfilm|'
                      r'full\s+(?:length\s+)?(?:movie|film|episode)|feature[ -]?(?:film|length)|komplette\s+folge)\b', re.I)


def screen(facts, minimum):
    """'' when the video may be a complete film/episode, else the German reason it is left out."""
    if facts['duration'] < minimum:
        return 'zu kurz'
    try:
        from vendor.archive_portals import video_triage
        category, _ = video_triage.classify(facts['title'])
    except ImportError:   # bundle without the ArchiveMedia modules: own vocabulary only
        category = 'main'
    if category != 'main':
        return {'clip': 'Trailer/Clip', 'podcast': 'Podcast', 'religious': 'Gottesdienst/Predigt'}.get(category, category)
    if _EXCLUDE.search(facts['title']):
        return 'Trailer/Clip'
    head = str(facts.get('description') or '')[:800]
    if PROMO.search(head) and not (COMPLETE.search(facts['title']) or COMPLETE.search(head)):
        return 'Werbung für Kino/DVD (Beschreibung)'
    return ''


def doubtful(report):
    """Reason when every reference found contradicts the runtime (promo cut, compilation …)."""
    refs = (report or {}).get('references') or []
    if not refs or any(r.get('eligible') for r in refs):
        return ''
    if all('Laufzeit widersprüchlich' in (r.get('issues') or []) for r in refs):
        return 'Laufzeit passt zu keinem gefundenen Werk'
    return ''


LANGUAGE_NAMES = {'de': 'Deutsch', 'en': 'Englisch', 'fr': 'Französisch', 'it': 'Italienisch', 'es': 'Spanisch'}


def movie_item(facts, source):
    """Complete film from a channel/playlist of kind 'movies', or None (too short, trailer …)."""
    minimum = max(1, _int(source.get('min_minutes'), 1, 600) or MOVIE_MINUTES) * 60
    if screen(facts, minimum):
        return None
    title, year, genres, language = clean_title(facts['title'], facts['channel'])
    lang = language or LANGUAGE_NAMES.get(facts['language'].split('-')[0].lower(), '')
    return {'id': 'v.' + facts['id'], 'kind': 'movie', 'title': title, 'path': facts['id'], 'series_id': '',
            'season': None, 'episode': None, 'year': year, 'duration': facts['duration'], 'rating': facts['rating'],
            'genre': ', '.join(genres), 'summary': summary_text(facts['description']), 'poster': facts['poster'],
            'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': None,
            'category': facts['channel'] or source.get('title') or '', 'raw_title': facts['title'], 'language': lang,
            'published': facts['published'], 'source_id': source.get('id'), 'playable': int(facts['playable']),
            'reason': facts['reason'], 'offline': 0, 'drm': 0, 'web_url': video_url(facts['id'])}


def series_items(source, entries, facts_by_id):
    """Series (one playlist) with its episodes; entries = [(video_id, position)]."""
    playlist = source.get('playlist') or ''
    if not re.fullmatch(PLAYLIST_ID, playlist):
        return []
    minimum = max(1, _int(source.get('min_minutes'), 1, 600) or EPISODE_MINUTES) * 60
    name = _text(source.get('label') or source.get('title'), 200)
    title, year, genres, language = clean_title(name or 'Serie')
    series_id = 's.' + playlist
    out, poster, channel, rating = [], '', '', ''
    for video_id, position in entries:
        f = facts_by_id.get(video_id)
        if not f or screen(f, minimum):
            continue
        season, number = episode_numbers(f['title'], position)
        poster = poster or f['poster']
        channel = channel or f['channel']
        rating = rating or f['rating']
        language = language or LANGUAGE_NAMES.get(f['language'].split('-')[0].lower(), '')
        out.append({'id': 'e.' + video_id, 'kind': 'episode', 'title': episode_title(f['title'], title) or 'Folge %s' % (number or ''),
                    'path': video_id, 'series_id': series_id, 'season': season, 'episode': number, 'year': None,
                    'duration': f['duration'], 'rating': f['rating'], 'genre': '', 'summary': summary_text(f['description']),
                    'poster': f['poster'], 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None, 'number': position,
                    'category': f['channel'], 'raw_title': f['title'], 'language': language, 'published': f['published'],
                    'source_id': source.get('id'), 'playable': int(f['playable']), 'reason': f['reason'], 'offline': 0,
                    'drm': 0, 'web_url': video_url(video_id)})
    if not out:
        return []
    series = {'id': series_id, 'kind': 'series', 'title': title, 'path': playlist, 'series_id': '', 'season': None,
              'episode': None, 'year': year, 'duration': None, 'rating': rating, 'genre': ', '.join(genres),
              'summary': '', 'poster': poster, 'imdb_id': '', 'imdb_score': None, 'imdb_votes': None,
              'number': len(out), 'category': channel or source.get('title') or '', 'raw_title': name,
              'language': language, 'published': '', 'source_id': source.get('id'), 'playable': 1, 'reason': '',
              'offline': 0, 'drm': 0, 'web_url': playlist_url(playlist)}
    return [series] + out


# ---------------------------------------------------------------- network

def _request(endpoint, query, key):
    """One request to the fixed YouTube Data API host; only the four read endpoints are used."""
    if endpoint not in ENDPOINTS:
        raise ValueError('Ungültige YouTube-Anfrage')
    url = API + endpoint + '?' + urllib.parse.urlencode({**query, 'key': key})
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'MediathekAtlas'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(65536).decode('utf-8'))
        except (ValueError, OSError, UnicodeDecodeError):
            body = {}
        raise ApiError(exc.code, body) from None
    if len(raw) > MAX_ANSWER:
        raise ValueError('YouTube-Antwort zu groß')
    return json.loads(raw.decode('utf-8'))


class ApiError(Exception):
    """HTTP error of the Data API with its reason (keyInvalid, quotaExceeded …)."""

    def __init__(self, code, body):
        error = (body or {}).get('error') if isinstance(body, dict) else {}
        errors = (error or {}).get('errors') if isinstance(error, dict) else []
        self.code = code
        self.reason = str((errors[0] or {}).get('reason') if isinstance(errors, list) and errors and isinstance(errors[0], dict) else '')[:60]
        super().__init__('YouTube API HTTP %s %s' % (code, self.reason))


def _error(exc):
    if isinstance(exc, ApiError):
        if exc.reason in ('quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded'):
            return 'Tageskontingent der YouTube-API aufgebraucht; neuer Versuch morgen'
        if exc.reason in ('keyInvalid', 'badRequest') or exc.code == 400:
            return 'YouTube-API-Schlüssel ungültig oder Anfrage abgelehnt (HTTP %d)' % exc.code
        if exc.reason in ('accessNotConfigured', 'forbidden', 'ipRefererBlocked', 'keyExpired') or exc.code == 403:
            return ('YouTube verweigert den Zugriff (%s). Ist die „YouTube Data API v3“ für den Schlüssel '
                    'freigeschaltet?' % (exc.reason or 'HTTP 403'))
        if exc.code == 404:
            return 'Kanal oder Playlist nicht gefunden'
        return 'YouTube antwortet mit HTTP %d' % exc.code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('YouTube-API ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'YouTube-Katalog konnte nicht geladen werden'


def resolve_source(request, src):
    """Fill channel_id/playlist/title of a source (channels.list or playlists.list)."""
    ref = src['ref']
    if ref.startswith('@') or ref.startswith('UC') or ref.startswith('user:'):
        query = {'part': 'snippet,contentDetails', 'maxResults': 1}
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
        if not re.fullmatch(PLAYLIST_ID, uploads):
            raise ValueError('Kanal ohne öffentliche Uploads')
        return {'channel_id': str(node.get('id') or '')[:40], 'playlist': uploads,
                'title': _text((node.get('snippet') or {}).get('title'), 120)}
    items = (request('playlists', {'part': 'snippet', 'id': ref, 'maxResults': 1}) or {}).get('items') or []
    node = items[0] if items and isinstance(items[0], dict) else None
    if not node:
        raise ValueError('Playlist nicht gefunden')
    snippet = node.get('snippet') or {}
    return {'channel_id': _text(snippet.get('channelId'), 40), 'playlist': ref,
            'title': _text(snippet.get('title'), 120)}


def playlist_entries(request, playlist, gap=0, limit=MAX_PER_SOURCE):
    """[(video_id, position)] of a playlist, all pages (50 per request, 1 quota unit each)."""
    out, token, seen = [], '', set()
    while len(out) < limit:
        query = {'part': 'snippet,contentDetails', 'playlistId': playlist, 'maxResults': 50}
        if token:
            query['pageToken'] = token
        answer = request('playlistItems', query) or {}
        for node in answer.get('items') or []:
            if not isinstance(node, dict):
                continue
            vid = str((node.get('contentDetails') or {}).get('videoId') or '')
            pos = _int((node.get('snippet') or {}).get('position'), 0, 100000)
            if VALID_VIDEO.fullmatch(vid) and vid not in seen:
                seen.add(vid)
                out.append((vid, pos if pos is not None else len(out)))
        token = str(answer.get('nextPageToken') or '')
        if not token or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', token):
            break
        if gap:
            time.sleep(gap)
    return out[:limit]


def load_facts(request, db, ids, now, gap=0):
    """Video facts for ids: cached for a week, the rest through videos.list (50 per unit)."""
    found, missing = {}, []
    for vid in ids:
        row = db.execute('SELECT payload,checked FROM youtube_videos WHERE id=?', (vid,)).fetchone()
        if row and now - row['checked'] < VIDEO_TTL:
            try:
                payload = json.loads(row['payload'])
            except ValueError:
                payload = None
            if payload != 'gone':
                if isinstance(payload, dict):
                    found[vid] = payload
                continue
            continue
        missing.append(vid)
    for start in range(0, len(missing), 50):
        chunk = missing[start:start + 50]
        answer = request('videos', {'part': 'snippet,contentDetails,status', 'id': ','.join(chunk),
                                    'maxResults': 50}) or {}
        got = {}
        for node in answer.get('items') or []:
            facts = video_facts(node)
            if facts:
                got[facts['id']] = facts
            elif isinstance(node, dict) and VALID_VIDEO.fullmatch(str(node.get('id') or '')):
                got.setdefault(node['id'], None)
        with db:
            for vid in chunk:
                facts = got.get(vid)
                db.execute('INSERT OR REPLACE INTO youtube_videos(id,payload,checked) VALUES(?,?,?)',
                           (vid, json.dumps(facts if facts else 'gone', ensure_ascii=False), now))
                if facts:
                    found[vid] = facts
        if gap and start + 50 < len(missing):
            time.sleep(gap)
    return found


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'raw_title',
          'language', 'published', 'source_id', 'playable', 'reason', 'offline', 'drm', 'web_url')


def _store(db, items, now):
    for item in items:
        db.execute('''INSERT INTO youtube_items(id,%s,seen,updated) VALUES(?,%s,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(FIELDS), ','.join('?' * len(FIELDS)), ','.join('%s=excluded.%s' % (f, f) for f in FIELDS)),
                   (item['id'], *[item[f] for f in FIELDS], now, now))


def sources(root):
    db = _connect(root)
    try:
        return [dict(r) for r in db.execute('SELECT * FROM youtube_sources ORDER BY suggested, added')]
    finally:
        db.close()


def add_source(root, text, kind='movies', label='', min_minutes=None):
    ref = parse_ref(text)
    if kind not in ('movies', 'series'):
        raise ValueError('Art muss „Filme“ oder „Serie“ sein')
    if kind == 'series' and (ref.startswith('@') or ref.startswith('UC') or ref.startswith('user:')):
        raise ValueError('Eine Serie bitte als Playlist-Adresse angeben (youtube.com/playlist?list=…)')
    minutes = _int(min_minutes, 1, 600) if min_minutes not in (None, '') else None
    if min_minutes not in (None, '') and minutes is None:
        raise ValueError('Mindestlänge: 1 bis 600 Minuten')
    minutes = minutes or (MOVIE_MINUTES if kind == 'movies' else EPISODE_MINUTES)
    db = _connect(root)
    try:
        if db.execute('SELECT COUNT(*) FROM youtube_sources').fetchone()[0] >= MAX_SOURCES:
            raise ValueError('Höchstens %d Kanäle/Playlists' % MAX_SOURCES)
        with db:
            db.execute('''INSERT INTO youtube_sources(ref,kind,label,min_minutes,enabled,suggested,added) VALUES(?,?,?,?,1,0,?)
                ON CONFLICT(ref) DO UPDATE SET kind=excluded.kind,label=excluded.label,min_minutes=excluded.min_minutes,
                enabled=1,suggested=0''', (ref, kind, _text(label, 120), minutes, time.time()))
    finally:
        db.close()
    return sources(root)


def update_source(root, source_id, action):
    sid = _int(source_id, 1)
    if not sid or action not in ('remove', 'enable', 'disable'):
        raise ValueError('Ungültige Aktion')
    db = _connect(root)
    try:
        with db:
            if action == 'remove':
                db.execute('DELETE FROM youtube_sources WHERE id=?', (sid,))
            else:
                db.execute('UPDATE youtube_sources SET enabled=? WHERE id=?', (int(action == 'enable'), sid))
    finally:
        db.close()
    return sources(root)


def sync(root, request=None, now=None, gap=None, key=None):
    """Read all enabled sources. Rows stay; listed are the titles seen in the latest successful run."""
    now = time.time() if now is None else float(now)
    if request is None:
        key = (key if key is not None else _KEY()) or ''
        key = str(key).strip()
        if key:
            request = lambda endpoint, query: _request(endpoint, query, key)
    gap = (REQUEST_GAP if request is not None and key else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            if request is None:
                _set(db, 'last_result', 'failed')
                _set(db, 'last_error', NO_KEY)
                _set(db, 'next_attempt', now + 3600)
                return {'ok': False, 'error': NO_KEY}
            _set(db, 'last_result', 'running')
        active = [dict(r) for r in db.execute('SELECT * FROM youtube_sources WHERE enabled=1 ORDER BY id')]
    finally:
        db.close()
    _notify('youtube_sync_started', sources=len(active))
    found, failures, quota_hit = {}, [], False
    episodes_of = set()
    try:
        if not active:
            raise ValueError('Keine YouTube-Kanäle eingetragen')
        for src in active:
            db = _connect(root)
            try:
                try:
                    if not src['playlist'] or now - (src['checked'] or 0) > 30 * 86400:
                        src.update(resolve_source(request, src))
                    entries = playlist_entries(request, src['playlist'], gap)
                    facts = load_facts(request, db, [v for v, _ in entries], now, gap)
                    minimum = max(1, _int(src.get('min_minutes'), 1, 600) or (EPISODE_MINUTES if src['kind'] == 'series' else MOVIE_MINUTES)) * 60
                    skipped = {}
                    for v, _ in entries:
                        why = screen(facts[v], minimum) if v in facts else 'nicht verfügbar (gesperrt, privat, live)'
                        if why:
                            skipped[why] = skipped.get(why, 0) + 1
                    if src['kind'] == 'series':
                        items = series_items(src, entries, facts)
                        episodes_of.update(i['path'] for i in items if i['kind'] == 'episode')
                    else:
                        items = [it for it in (movie_item(facts[v], src) for v, _ in entries if v in facts) if it]
                    for it in items:
                        found.setdefault(it['id'], it)
                    films = sum(1 for i in items if i['kind'] in ('movie', 'episode'))
                    with db:
                        db.execute('''UPDATE youtube_sources SET channel_id=?,playlist=?,title=?,videos=?,films=?,
                            last_error='',checked=?,skipped=? WHERE id=?''', (src['channel_id'], src['playlist'], src['title'],
                                                                   len(entries), films, now, json.dumps(skipped, ensure_ascii=False), src['id']))
                except Exception as exc:
                    message = _error(exc)
                    quota_hit |= isinstance(exc, ApiError) and exc.reason in ('quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded')
                    failures.append(message)
                    with db:
                        db.execute('UPDATE youtube_sources SET last_error=?,checked=? WHERE id=?',
                                   (message, now if not isinstance(exc, (urllib.error.URLError, OSError)) else src['checked'], src['id']))
                    if isinstance(exc, ApiError) and exc.code in (400, 403):
                        break   # key or quota problem: the other sources fail the same way
            finally:
                db.close()
        # A video both in a film channel and in a series playlist is listed as episode only.
        for vid in episodes_of:
            found.pop('v.' + vid, None)
        if not found:
            raise ValueError(failures[0] if failures else 'Keine vollständigen Filme gefunden (Mindestlänge prüfen)')
        items = list(found.values())
        partial = bool(failures)
        counts = {'movies': sum(1 for i in items if i['kind'] == 'movie'),
                  'series': sum(1 for i in items if i['kind'] == 'series'),
                  'episodes': sum(1 for i in items if i['kind'] == 'episode'),
                  'playable': sum(1 for i in items if i['kind'] != 'series' and i['playable'])}
        db = _connect(root)
        try:
            with db:
                _store(db, items, now)
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                for k, value in [('last_success', visible_since), ('last_loaded', now),
                                 ('last_result', 'partial' if partial else 'complete'),
                                 ('last_error', ('%d von %d Quellen mit Fehler: %s' % (len(failures), len(active), failures[0])) if partial else ''),
                                 ('next_attempt', now + 24 * 3600), *counts.items()]:
                    _set(db, k, value)
        finally:
            db.close()
        _notify('youtube_sync_completed', partial=partial, failed_sources=len(failures), **counts)
        return {'ok': True, 'partial': partial, **counts}
    except Exception as exc:
        message = _error(exc)
        db = _connect(root)
        try:
            with db:
                for k, value in [('last_result', 'failed'), ('last_error', message),
                                 ('last_http_status', getattr(exc, 'code', 0) or 0),
                                 ('next_attempt', now + (12 * 3600 if quota_hit else 3600))]:
                    _set(db, k, value)
        finally:
            db.close()
        _notify('youtube_sync_failed', http_status=getattr(exc, 'code', 0) or 0, reason=getattr(exc, 'reason', '') or type(exc).__name__)
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- views

def _row(db, item_id):
    row = db.execute('SELECT * FROM youtube_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def offline_flag(root, row, enabled=None):
    """1 when the opt-in switch is on and the title is a single, not age-restricted video."""
    if enabled is None:
        import youtube_downloads
        enabled = youtube_downloads.enabled(root)
    return int(bool(enabled) and row.get('kind') in ('movie', 'episode')
               and not str(row.get('reason') or '').startswith('Altersbeschränkt'))


def _summary(root, row, reports=None):
    import youtube_enrichment
    report = (reports if reports is not None else youtube_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report)


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection='', show_doubtful=False):
    """One page of films or series with canonical categories and ratings (same as the other portals).
    Titles whose every reference contradicts the runtime are hidden (counted in ``hidden``)."""
    import youtube_enrichment
    kind = {'movies': 'movie', 'series': 'series'}.get(view, 'movie')
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = max(1, min(_int(limit, 1) or 60, 200))
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM youtube_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR category LIKE ? OR raw_title LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like] * 4
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
    finally:
        db.close()
    reports = youtube_enrichment.all_cached(root)
    import youtube_downloads
    switch = youtube_downloads.enabled(root)
    hidden = 0
    kept = []
    for row in rows:
        row['doubt'] = doubtful(reports.get(row['id']))
        if row['doubt'] and not show_doubtful:
            hidden += 1
            continue
        row.update(_summary(root, row, reports))
        row['offline'] = offline_flag(root, row, switch)
        kept.append(row)
    rows = kept
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view,
            'genre_counts': counts, 'hidden': hidden}


def episodes(root, series_id, request=None, now=None):
    """Episodes of a series playlist (loaded with the catalogue run, no extra traffic)."""
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige YouTube-Serie')
    db = _connect(root)
    try:
        series = _row(db, series_id)
        if not series or series['kind'] != 'series':
            raise ValueError('YouTube-Serie nicht im Katalog; bitte Katalog neu laden')
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM youtube_items WHERE kind='episode' AND series_id=? AND seen>=? ORDER BY season,episode,number,title",
            (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series)
    import youtube_downloads
    switch = youtube_downloads.enabled(root)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row['offline'] = offline_flag(root, row, switch)
    return {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': ''}


def item(root, item_id):
    import youtube_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger YouTube-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        if not row:
            raise ValueError('YouTube-Titel nicht im Katalog; bitte Katalog neu laden')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    report = youtube_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or '',
                     'offline': offline_flag(root, row)},
            'series': parent, 'reference': report}


def state(root):
    db = _connect(root)
    try:
        srcs = [dict(r) for r in db.execute('SELECT enabled,last_error FROM youtube_sources')]
        return {
            'running': _ACTIVE, 'auto': _get(db, 'auto', '1') == '1', 'key_set': bool(str(_KEY() or '').strip()),
            'last_attempt': float(_get(db, 'last_attempt', '0') or 0),
            'last_success': float(_get(db, 'last_success', '0') or 0),
            'next_attempt': float(_get(db, 'next_attempt', '0') or 0),
            'last_result': portal_reference.stored_result(_get(db, 'last_result', 'never'), _ACTIVE),
            'last_error': _get(db, 'last_error'),
            'last_http_status': _int(_get(db, 'last_http_status', '0')) or 0,
            'movies': _int(_get(db, 'movies', '0')) or 0, 'series': _int(_get(db, 'series', '0')) or 0,
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'playable': _int(_get(db, 'playable', '0')) or 0,
            'sources': sum(1 for s in srcs if s['enabled']),
            'sources_failed': sum(1 for s in srcs if s['enabled'] and s['last_error']),
            'offline_enabled': _get(db, 'offline_enabled', '0') == '1',
            'offline_note': '' if _get(db, 'offline_enabled', '0') == '1' else NO_OFFLINE}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='youtube_catalog_sync').start()
    return True


def loop(root, stop):
    """Daily refresh (on by default: the API is quota-limited, not the user's bandwidth). Without a
    key nothing is requested."""
    while not stop.wait(60):
        current = state(root)
        if not current['key_set'] or current['running']:
            continue
        if portal_reference.first_load_due(current) or (current['auto'] and time.time() >= current['next_attempt']):
            start_sync(root)


# ---------------------------------------------------------------- playback

def play_info(root, item_id):
    """What the player window needs for the official embedded YouTube player (no stream address,
    no download: YouTube plays the video itself, with its adverts)."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger YouTube-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row:
        raise ValueError('YouTube-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine Folge der Serie auswählen')
    if not row['playable']:
        raise ValueError((row['reason'] or 'Nur auf youtube.com abspielbar') + '.')
    return {'mode': 'embed', 'provider': 'youtube', 'video_id': row['path'], 'embed': EMBED + row['path'],
            'title': row['title'], 'duration': row['duration'] or 0, 'web_url': row['web_url'],
            'quality': 'offizieller YouTube-Player, mit Werbung', 'channel': row['category']}
