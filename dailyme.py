"""dailyme TV: free, ad-funded films, series and documentaries as a catalogue with links (0.6.62).

Björn (20.11.2026): "nimm bitte auch die anbindung von dailyme tv mit auf". dailyme TV (www.dailyme.de, Daygent
GmbH) shows films, series, documentaries, anime and live channels without an account. The website is a
JavaScript application; the catalogue (programmes, episodes, covers, FSK, running times) is in the page HTML
the server sends, playback is not:

* Playback: the website player opens a session and fetches an access key per clip before a stream starts
  (third-party analysis of the public player, 2026; adverts through Google IMA). That is access control of the
  provider's player. MediathekAtlas does not rebuild it: every title opens on dailyme.de ("Bei dailyme
  ansehen"). No own player, no offline copies; the offline mode exists only in the dailyme apps.
* Catalogue (hosts blocked in the build environment; structure from the public pages, 20.11.2026, to be
  confirmed on Björn's Mac):
  - Lists: ``/``, ``/content/theme/<slug>`` (filme, serien-shows-magazine, dokus, family-kids …),
    ``/content/channel/<slug>`` (serien, anime-serien, schauriger-horror …), ``/content/provider/<slug>``,
    ``/content/neu``. Each names programmes as ``/content/show/<id>-<slug>/`` (5-digit ids).
  - Programme page ``/content/show/<id>-<slug>/`` lists its episodes as
    ``/content/show/<id>-<slug>/<episode id>-<slug>`` (7-digit ids) with running time ("23:46"), sometimes
    "STAFFEL 1 • FOLGE 1"; badges "DRAMA · 2018 · FSK 0"; schema.org JSON-LD is read when present.
  - Pictures: ``https://www.dailyme.de/fast/cover/<b|l|c><id>.jpg|png``, ``mini-cms.daygent.de``, ``*.selocon.com``.
  - Sitemaps named in robots.txt: ``/fast/video-sitemap.xml`` (episodes with title, description, duration,
    thumbnail) and ``/fast/inhalte-sitemap.xml``; read first, list and programme pages add FSK, genres, kind.
  - Film page: <title> "… – ganzer Film kostenlos ansehen | dailyme TV", "Kompletter Film · 2015", "FSK 12",
    "Abspielen 1:44:54"; series page: "26 Folgen", episode links "… kostenlos streamen | dailyme 24:12 Staffel 1,
    Folge N: <Beschreibung>".
* Films are programmes marked "ganzer Film"/"Kompletter Film", with one long video (from 45 minutes) or from the
  film lists.
* robots.txt (20.11.2026: ``Allow: /``, ``Disallow: /content/player/`` and ``/microsites_static/``) is honoured
  for every request; requests are spaced (1 s) and identify MediathekAtlas honestly. The player addresses are
  never requested. A page the server sends only as a JavaScript shell is reported as such, nothing is executed.
* Terms (AGB, "Stand: Mai 2018"): private, non-commercial use; no rights in the content; offline viewing is a
  function of the apps. Hence: links only, no copies, no access to the videos outside dailyme's own player.

The DDR series section (``/content/ddr``) uses another address scheme and is left out for now; live channels
are not part of this module. Titles and addresses never go to logs or the diagnosis.
"""
from __future__ import annotations

import html
import html.parser
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import portal_reference
import provider_base

KEY = 'dailyme'
NAME = 'dailyme TV'
SITE = 'https://www.dailyme.de'
HOSTS = frozenset({'www.dailyme.de', 'dailyme.de', 'www1.dailyme.de'})
try:
    from version import VERSION as _VERSION
except ImportError:                       # pragma: no cover
    _VERSION = '0'
USER_AGENT = 'Mozilla/5.0 (compatible; MediathekAtlas/%s; private catalogue with links)' % _VERSION
MAX_ANSWER = 6 * 1024 * 1024
START_LISTS = ('/', '/content/theme/filme', '/content/theme/serien-shows-magazine', '/content/theme/dokus',
               '/content/theme/family-kids', '/content/channel/serien', '/content/channel/anime-serien', '/content/neu')
MAX_LISTS = 160              # list pages per run
MAX_SHOWS = 6000
MAX_DETAILS = 1500           # programme pages per run (new ones first); the rest the next day
DETAIL_TTL = 7 * 86400       # a programme page is read again after a week
MAX_ITEMS = 120000
REQUEST_GAP = 1.0
RETRY_WAITS = (5, 20)
FILM_SECONDS = 45 * 60
PLAYBACK_NOTE = 'Ansehen auf dailyme.de mit Werbung, ohne Anmeldung'
OFFLINE_NOTE = 'Offline-Kopien nur in der dailyme-App (Offline-Modus)'
NOT_PLAYABLE = ('dailyme TV spielt seine Videos nur im eigenen Player (Sitzung und Zugriffsschlüssel je Video); '
                'bitte „Bei dailyme ansehen“ wählen.')
VALID_ID = re.compile(r'[mse]\.\d{1,9}')
SHOW_PATH = re.compile(r'/content/show/(\d{3,9})-([a-z0-9][a-z0-9\-]{0,200})/?$')
EPISODE_PATH = re.compile(r'/content/show/(\d{3,9})-([a-z0-9][a-z0-9\-]{0,200})/(\d{3,9})-([a-z0-9][a-z0-9\-]{0,200})/?$')
LIST_PATH = re.compile(r'/content/(?:theme|channel|provider|kategorie)/[a-z0-9][a-z0-9\-]{0,120}/?$'
                       r'|/content/(?:neu|western|film-finder|deutsche-filme|halloween)/?$')
SITEMAPS = ('/fast/video-sitemap.xml', '/fast/inhalte-sitemap.xml')
MAX_SITEMAP = 48 * 1024 * 1024
MAX_SITEMAP_FILES = 40
# Lists whose slug says something about the content: genre added to every programme found there.
LIST_GENRE = {'family-kids': 'Familie', 'dokus': 'Dokumentation', 'anime-serien': 'Anime',
              'schauriger-horror': 'Horror', 'western': 'Western', 'english': 'Englisch', 'autos-sport': 'Sport',
              'digital-games': 'Gaming', 'actionfilme': 'Action', 'komoedien': 'Komödie', 'drama-movies': 'Drama',
              'crime-movies': 'Krimi', 'science-fiction-movies': 'Science-Fiction', 'cartoons': 'Zeichentrick',
              'zeichentrickfilme': 'Zeichentrick', 'filme-und-serien-fuer-vorschul-kids': 'Kinder',
              'tierfilme-kinder': 'Kinder', 'naturdokus-kinder': 'Kinder', 'nanoki-filme': 'Kinder',
              'familienfilme': 'Familie', 'family': 'Familie', 'pferdefilme': 'Familie'}
FILM_LISTS = frozenset({'filme', 'western', 'film-finder', 'deutsche-filme', 'neue-filme', 'actionfilme', 'top-filme',
                        'komoedien', 'drama-movies', 'crime-movies', 'science-fiction-movies', 'familienfilme',
                        'zeichentrickfilme', 'pferdefilme', 'tierfilme-kinder', 'nanoki-filme'})
SERIES_LISTS = frozenset({'serien', 'serien-shows-magazine', 'anime-serien'})
FSK = re.compile(r'\bFSK\s?(0|6|12|16|18)\b')
CLOCK = re.compile(r'(?<![\d:])(\d{1,3}):([0-5]\d)(?::([0-5]\d))?(?![\d:])')
MINUTES = re.compile(r'\b(\d{1,3})\s?Min\b')
SEASON_EPISODE = re.compile(r'(?i)\bSTAFFEL\s*(\d{1,3})\s*[•·,|/-]?\s*FOLGE\s*(\d{1,4})\b|\bS(\d{1,2})\s?E(\d{1,4})\b')
FILM_LABEL = re.compile(r'(?i)\bkompletter film\b|\bganzer film\b')
SEASON_SLUG = re.compile(r'(?:^|-)staffel-(\d{1,3})(?:-|$)')
EPISODE_SLUG = re.compile(r'(?:^|-)folge-(\d{1,4})(?:-|$)')
YEAR = re.compile(r'(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)')
IMAGE_HOST = re.compile(r'(?:^|\.)(?:dailyme\.de|selocon\.com|daygent\.de)$')

_SYNC_LOCK = threading.Lock()
_ACTIVE = False

SCHEMA = '''
CREATE TABLE IF NOT EXISTS dailyme_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
  series_id TEXT NOT NULL DEFAULT '', season INTEGER, episode INTEGER, year INTEGER, duration INTEGER,
  rating TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  poster TEXT NOT NULL DEFAULT '', imdb_id TEXT NOT NULL DEFAULT '', imdb_score REAL, imdb_votes INTEGER,
  number INTEGER, category TEXT NOT NULL DEFAULT '', playable INTEGER NOT NULL DEFAULT 0,
  drm INTEGER NOT NULL DEFAULT -1, web_url TEXT NOT NULL DEFAULT '', detail_at REAL NOT NULL DEFAULT 0,
  seen REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS dailyme_items_kind ON dailyme_items(kind, seen);
CREATE INDEX IF NOT EXISTS dailyme_items_series ON dailyme_items(series_id, season, episode);
CREATE TABLE IF NOT EXISTS dailyme_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _notify(event, **details):
    """Technical counters only; never URLs or titles."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _connect(root):
    db = provider_base.connect(root, 'dailyme.sqlite3')
    provider_base.ensure_schema(db, SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM dailyme_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO dailyme_state(name,value) VALUES(?,?)', (key, str(value)))


def _text(value, limit):
    value = html.unescape(re.sub(r'<[^>]{0,400}>', ' ', str(value or '')))
    return ' '.join(value.split())[:limit]


def _int(value, low=None, high=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


# ---------------------------------------------------------------- network

def _headers():
    return {'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.5',
            'Accept-Language': 'de-DE,de;q=0.9'}


def _url(path):
    return SITE + path


def _open(url, headers, limit=MAX_ANSWER):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port or parts.username:
        raise ValueError('Ungültige dailyme-Anfrage')
    req = urllib.request.Request(url, headers=headers)
    with provider_base.open_capped(req, timeout=30) as response:
        if int(response.headers.get('Content-Length', '0') or 0) > limit:
            raise ValueError('dailyme-Antwort zu groß')
        raw = provider_base.read_capped(response, limit)
    if len(raw) > limit:
        raise ValueError('dailyme-Antwort zu groß')
    return raw.decode('utf-8', 'replace')


def _error(exc):
    status = getattr(exc, 'code', None)
    if status == 451:
        return 'dailyme TV ist von hier aus nicht verfügbar (HTTP 451, Geosperre)'
    if status in (401, 403):
        return 'dailyme TV verweigert den Zugriff (HTTP %d)' % status
    if status == 429:
        return 'dailyme TV bremst die Abrufe (HTTP 429), später erneut versuchen'
    if status:
        return 'dailyme TV antwortet mit HTTP %d' % status
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        import netcheck
        return netcheck.with_cause('dailyme TV ist nicht erreichbar', exc)
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Katalog von dailyme TV konnte nicht geladen werden'


# ---------------------------------------------------------------- robots.txt

def robots_rules(text):
    """``Disallow``/``Allow`` prefixes for every client (``User-agent: *`` or MediathekAtlas)."""
    rules, active, saw_agent = [], False, False
    for raw in str(text or '').splitlines()[:2000]:
        line = raw.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        name, value = (part.strip() for part in line.split(':', 1))
        name = name.casefold()
        if name == 'user-agent':
            if not saw_agent:
                active = False
            saw_agent = True
            if value == '*' or value.casefold() == 'mediathekatlas':
                active = True
            continue
        saw_agent = False
        if active and name in ('disallow', 'allow') and (value or name == 'allow'):
            rules.append((name == 'allow', value[:300]))
    return rules


def robots_allows(rules, path):
    """Longest matching prefix wins (``*`` and ``$`` as in RFC 9309); allowed when nothing matches."""
    best, allowed = -1, True
    for allow, pattern in rules:
        regex = '^' + re.escape(pattern).replace(r'\*', '.*')
        if regex.endswith(r'\$'):
            regex = regex[:-2] + '$'
        if re.match(regex, path) and len(pattern) > best:
            best, allowed = len(pattern), allow
    return allowed


# ---------------------------------------------------------------- parsing

def _image(value):
    url = html.unescape(str(value or '').strip())
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = SITE + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == 'https' and parts.hostname and IMAGE_HOST.search(parts.hostname) and not parts.port \
            and not parts.username and not re.search(r'[\s<>"\'{}]', url) and len(url) < 600:
        return url
    return ''


def _seconds(text):
    """'23:46' -> 1426, '1:23:46' -> 5026, '262 Min.' -> 15720; None when no running time is named."""
    match = CLOCK.search(text or '')
    if match:
        a, b, c = match.group(1), match.group(2), match.group(3)
        seconds = (int(a) * 3600 + int(b) * 60 + int(c)) if c else (int(a) * 60 + int(b))
        return seconds if 30 <= seconds <= 12 * 3600 else None
    match = MINUTES.search(text or '')
    if match:
        return int(match.group(1)) * 60 if 1 <= int(match.group(1)) <= 720 else None
    return None


def _iso_seconds(value):
    match = re.fullmatch(r'P(?:T)?(?:(\d{1,2})H)?(?:(\d{1,4})M)?(?:(\d{1,5})S)?', str(value or '').strip())
    if not match or not any(match.groups()):
        return None
    h, m, s = (int(x or 0) for x in match.groups())
    seconds = h * 3600 + m * 60 + s
    return seconds if 30 <= seconds <= 12 * 3600 else None


def _badges(text):
    """'DRAMA · 2018 · FSK 0' -> ({'genres': ['Drama'], 'year': 2018, 'fsk': 0})."""
    out = {'genres': [], 'year': None, 'fsk': None}
    fsk = FSK.search(text or '')
    if fsk:
        out['fsk'] = int(fsk.group(1))
    for chunk in re.split(r'\s[·•|]\s', text or ''):
        chunk = chunk.strip()
        if YEAR.fullmatch(chunk) and out['year'] is None:
            out['year'] = int(chunk)
        elif re.fullmatch(r'[A-ZÄÖÜ][A-ZÄÖÜ/&\- ]{2,30}', chunk) and not FSK.fullmatch(chunk) \
                and not re.match(r'(?:STAFFEL|FOLGE)\b', chunk):
            name = '/'.join(part.capitalize() for part in chunk.split('/'))
            if name not in out['genres']:
                out['genres'].append(name)
    return out


class _Page(html.parser.HTMLParser):
    """Anchors (href, text, picture, title attributes), headings, meta tags and JSON-LD of one page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.meta, self.ld, self.h1 = [], {}, [], ''
        self.title = ''
        self._anchor = None
        self._depth = 0
        self._in = None            # 'title', 'h1', 'ld'
        self._buffer = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or '') for k, v in attrs}
        if tag == 'a' and a.get('href'):
            if self._anchor is None:
                self._anchor = {'href': a['href'], 'text': [], 'img': '', 'alt': '', 'label': a.get('aria-label') or a.get('title') or ''}
                self._depth = 0
            else:
                self._depth += 1
        elif tag == 'img' and self._anchor is not None and not self._anchor['img']:
            self._anchor['img'] = a.get('src') or a.get('data-src') or (a.get('srcset') or '').split(' ')[0]
            self._anchor['alt'] = a.get('alt') or ''
        elif tag == 'meta':
            name = (a.get('property') or a.get('name') or '').casefold()
            if name in ('description', 'og:title', 'og:description', 'og:image', 'og:type', 'video:duration',
                        'video:release_date') and name not in self.meta:
                self.meta[name] = a.get('content') or ''
        elif tag == 'script' and 'ld+json' in a.get('type', ''):
            self._in, self._buffer = 'ld', []
        elif tag in ('title', 'h1') and self._in is None:
            self._in, self._buffer = tag, []

    def handle_endtag(self, tag):
        if tag == 'a' and self._anchor is not None:
            if self._depth:
                self._depth -= 1
            else:
                anchor, self._anchor = self._anchor, None
                anchor['text'] = ' · '.join(t for t in anchor['text'] if t)
                self.links.append(anchor)
        elif (tag == 'script' and self._in == 'ld') or (tag == self._in):
            body = ''.join(self._buffer)
            if self._in == 'ld':
                try:
                    self.ld.append(json.loads(body))
                except ValueError:
                    pass
            elif self._in == 'title':
                self.title = _text(body, 300)
            elif self._in == 'h1' and not self.h1:
                self.h1 = _text(body, 300)
            self._in = None

    def handle_data(self, data):
        if self._in:
            self._buffer.append(data)
        text = ' '.join(data.split())
        if text and self._in != 'ld':
            if self._anchor is not None:
                self._anchor['text'].append(text)
            if len(self.text) < 4000:
                self.text.append(text)


def parse_page(markup):
    page = _Page()
    try:
        page.feed(str(markup or '')[:MAX_ANSWER])
        page.close()
    except (ValueError, AssertionError):
        pass
    return page


def _path(href):
    """Site path of a link to dailyme.de ('' for other hosts)."""
    parts = urllib.parse.urlsplit(html.unescape(str(href or '')).strip())
    if parts.scheme and (parts.scheme != 'https' or parts.hostname not in HOSTS):
        return ''
    if not parts.scheme and parts.netloc:
        return ''
    return parts.path or '/'


def clean_title(value):
    """'X kostenlos streamen | dailyme' -> 'X'; 'Ip Man 3 – ganzer Film kostenlos ansehen | dailyme TV' -> 'Ip Man 3'."""
    value = _text(value, 600)
    value = re.split(r'(?i)\s*(?:[–|-]\s*)?(?:ganzer film |anime-serie |serie )?kostenlos (?:ansehen|streamen|anschauen|schauen)\b'
                     r'|\s*\|\s*dailyme\b', value)[0]
    value = re.sub(r'\s*(?:\d{1,3}:[0-5]\d(?::[0-5]\d)?)?\s*Staffel\s*\d{1,3},?\s*Folge\s*\d{1,4}:?.*$', '', value, flags=re.I)
    return value.strip(' –-|:')[:200]


def _anchor_title(anchor, slug=''):
    for value in (anchor.get('label'), anchor.get('alt')):
        value = clean_title(value)
        if value and not FSK.search(value):
            return value
    for chunk in str(anchor.get('text') or '').split(' · '):
        chunk = chunk.strip()
        if len(chunk) < 2 or CLOCK.fullmatch(chunk) or MINUTES.search(chunk) or FSK.search(chunk) \
                or YEAR.fullmatch(chunk) or re.fullmatch(r'[A-ZÄÖÜ /&•·\-\d]{2,40}', chunk) \
                or chunk.casefold() in ('jetzt ansehen', 'ansehen', 'abspielen', 'mehr', 'mehr >', 'neu', 'film', 'serie'):
            continue
        chunk = clean_title(chunk)
        if chunk:
            return chunk
    return slug.replace('-', ' ').strip().title()[:200] if slug else ''


def list_page(markup):
    """Programmes and further lists of a list page: ({show id: tile}, [list paths])."""
    page = parse_page(markup)
    shows, lists = {}, []
    for anchor in page.links:
        path = _path(anchor['href'])
        if not path:
            continue
        show = SHOW_PATH.fullmatch(path)
        episode = EPISODE_PATH.fullmatch(path)
        if show or episode:
            match = show or episode
            sid, slug = match.group(1), match.group(2)
            tile = shows.setdefault(sid, {'id': sid, 'slug': slug, 'title': '', 'poster': '', 'duration': None,
                                          'year': None, 'fsk': None, 'genres': []})
            text = anchor.get('text') or ''
            if show:
                tile['title'] = tile['title'] or _anchor_title(anchor, slug)
                tile['duration'] = tile['duration'] or _seconds(text)
            badges = _badges(text)
            tile['year'] = tile['year'] or badges['year']
            tile['fsk'] = tile['fsk'] if tile['fsk'] is not None else badges['fsk']
            tile['genres'] = tile['genres'] or badges['genres']
            tile['poster'] = tile['poster'] or _image(anchor.get('img'))
        elif LIST_PATH.fullmatch(path):
            path = path.rstrip('/')
            if path not in lists:
                lists.append(path)
    return shows, lists


def _ld_nodes(page):
    out = []
    for node in page.ld:
        stack = [node]
        while stack and len(out) < 2000:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item[:500])
            elif isinstance(item, dict):
                out.append(item)
                for key in ('@graph', 'episode', 'episodes', 'containsSeason', 'hasPart', 'itemListElement', 'item'):
                    if key in item:
                        stack.append(item[key])
    return out


def _ld_type(node):
    kind = node.get('@type')
    return {str(k) for k in kind} if isinstance(kind, list) else {str(kind or '')}


def show_page(markup, sid, slug):
    """Facts and episodes of a programme page. ``stub`` is True for a bare JavaScript shell."""
    page = parse_page(markup)
    facts = {'title': '', 'summary': '', 'poster': '', 'year': None, 'fsk': None, 'genres': [], 'type': '',
             'duration': None}
    episodes = {}
    for node in _ld_nodes(page):
        types = _ld_type(node)
        if types & {'Movie', 'TVSeries', 'CreativeWorkSeries', 'VideoObject'} and not facts['title']:
            facts['title'] = _text(node.get('name'), 200)
            facts['summary'] = _text(node.get('description'), 2000)
            image = node.get('image')
            facts['poster'] = _image(image.get('url') if isinstance(image, dict) else (image[0] if isinstance(image, list) and image else image))
            year = YEAR.search(str(node.get('datePublished') or node.get('startDate') or node.get('dateCreated') or ''))
            facts['year'] = int(year.group(1)) if year else None
            fsk = FSK.search(str(node.get('contentRating') or ''))
            facts['fsk'] = int(fsk.group(1)) if fsk else None
            genre = node.get('genre')
            facts['genres'] = [_text(g, 40) for g in (genre if isinstance(genre, list) else [genre]) if _text(g, 40)][:6]
            facts['type'] = 'movie' if 'Movie' in types else 'series' if types & {'TVSeries', 'CreativeWorkSeries'} else ''
            facts['duration'] = _iso_seconds(node.get('duration'))
        if 'TVEpisode' in types or 'Episode' in types:
            match = EPISODE_PATH.search(_path(node.get('url') or node.get('@id') or ''))
            if match and match.group(1) == sid:
                season = node.get('partOfSeason') if isinstance(node.get('partOfSeason'), dict) else {}
                episodes[match.group(3)] = {'id': match.group(3), 'slug': match.group(4),
                                            'title': _text(node.get('name'), 200),
                                            'summary': _text(node.get('description'), 1600),
                                            'duration': _iso_seconds(node.get('duration')),
                                            'season': _int(season.get('seasonNumber'), 0, 999),
                                            'episode': _int(node.get('episodeNumber'), 0, 9999),
                                            'poster': _image(node.get('thumbnailUrl') or node.get('image'))}
    for anchor in page.links:
        match = EPISODE_PATH.fullmatch(_path(anchor['href']))
        if not match or match.group(1) != sid:
            continue
        eid, eslug = match.group(3), match.group(4)
        text = anchor.get('text') or ''
        entry = episodes.setdefault(eid, {'id': eid, 'slug': eslug, 'title': '', 'summary': '', 'duration': None,
                                          'season': None, 'episode': None, 'poster': ''})
        entry['title'] = entry['title'] or _anchor_title(anchor, eslug)
        entry['duration'] = entry['duration'] or _seconds(text)
        entry['poster'] = entry['poster'] or _image(anchor.get('img'))
        described = re.search(r'(?i)\bFolge\s*\d{1,4}\s*:\s*(.{8,})$', text)
        if described and not entry['summary']:
            entry['summary'] = _text(described.group(1).replace(' · ', ' '), 1600)
        numbers = SEASON_EPISODE.search(text)
        if numbers and entry['episode'] is None:
            season, episode = (numbers.group(1), numbers.group(2)) if numbers.group(1) else (numbers.group(3), numbers.group(4))
            entry['season'], entry['episode'] = int(season), int(episode)
    whole = ' · '.join(page.text)
    facts['title'] = clean_title(facts['title'] or page.meta.get('og:title') or page.h1 or page.title)
    facts['summary'] = facts['summary'] or _text(page.meta.get('og:description') or page.meta.get('description'), 2000)
    facts['poster'] = facts['poster'] or _image(page.meta.get('og:image'))
    badges = _badges(whole)
    facts['year'] = facts['year'] or badges['year']
    facts['fsk'] = facts['fsk'] if facts['fsk'] is not None else badges['fsk']
    facts['genres'] = facts['genres'] or badges['genres']
    if not facts['type'] and ('video.movie' in (page.meta.get('og:type') or '')
                              or (FILM_LABEL.search(page.title) and len(episodes) <= 1)
                              or (not episodes and re.search(r'(?i)\bkompletter film\b', whole))):
        facts['type'] = 'movie'
    if facts['type'] == 'movie' and not facts['duration']:
        facts['duration'] = _seconds(' '.join(t for t in page.text if 'Abspielen' in t or CLOCK.fullmatch(t))[:400])
    facts['duration'] = facts['duration'] or _iso_seconds(page.meta.get('video:duration')) \
        or _int(page.meta.get('video:duration'), 30, 12 * 3600)
    # Season numbers from the programme slug ("…-staffel-2") and episode numbers from episode slugs ("…-folge-05")
    slug_season = SEASON_SLUG.search(slug or '')
    for entry in episodes.values():
        if entry['season'] is None and slug_season:
            entry['season'] = int(slug_season.group(1))
        if entry['episode'] is None:
            number = EPISODE_SLUG.search(entry['slug'])
            if number:
                entry['episode'] = int(number.group(1))
    stub = not episodes and not page.ld and not page.h1 and not page.meta.get('og:title') \
        and 'enable javascript' in whole.casefold()
    return facts, list(episodes.values()), stub


# ---------------------------------------------------------------- sitemaps

def _xml_text(block, tag):
    match = re.search(r'<%s(?:\s[^>]{0,200})?>(.*?)</%s>' % (tag, tag), block, re.S)
    if not match:
        return ''
    value = match.group(1).strip()
    if value.startswith('<![CDATA[') and value.endswith(']]>'):
        value = value[9:-3]
    return html.unescape(value)


def sitemap_entries(text):
    """('index', [sitemap paths]) or ('urls', [{path, title, summary, duration, poster, year, family}]).
    Read with plain patterns (no XML entities are expanded); only addresses on www.dailyme.de count."""
    text = str(text or '')
    if re.search(r'<sitemapindex\b', text[:4000]):
        paths = []
        for block in re.findall(r'<sitemap\b.*?</sitemap>', text, re.S)[:MAX_SITEMAP_FILES * 4]:
            path = _path(_xml_text(block, 'loc'))
            if path.startswith('/') and path.endswith('.xml') and path not in paths:
                paths.append(path)
        return 'index', paths
    out = []
    for block in re.findall(r'<url\b.*?</url>', text, re.S):
        if len(out) >= MAX_ITEMS:
            break
        path = _path(_xml_text(block, 'loc'))
        if not (SHOW_PATH.fullmatch(path) or EPISODE_PATH.fullmatch(path)):
            continue
        published = YEAR.search(_xml_text(block, 'video:publication_date'))
        out.append({'path': path, 'title': clean_title(_xml_text(block, 'video:title')),
                    'summary': _text(_xml_text(block, 'video:description'), 1600),
                    'duration': _int(_xml_text(block, 'video:duration'), 30, 12 * 3600),
                    'poster': _image(_xml_text(block, 'video:thumbnail_loc')),
                    'year': int(published.group(1)) if published else None,
                    'family': _xml_text(block, 'video:family_friendly').strip().casefold() == 'yes'})
    return 'urls', out


# ---------------------------------------------------------------- crawl

def _list_slug(path):
    return path.rstrip('/').rsplit('/', 1)[-1]


def _kind(tile, facts, episodes):
    if facts.get('type'):
        return facts['type']
    lists = tile.get('lists') or set()
    long_videos = [e for e in episodes if (e.get('duration') or 0) >= FILM_SECONDS]
    if len(episodes) == 1 and (long_videos or lists & FILM_LISTS):
        return 'movie'
    if not episodes and ((tile.get('duration') or 0) >= FILM_SECONDS or (facts.get('duration') or 0) >= FILM_SECONDS
                         or (lists & FILM_LISTS and not lists & SERIES_LISTS)):
        return 'movie'
    return 'series'


class Crawl:
    """List pages (programmes), then the programme pages (episodes) with fixed limits."""

    def __init__(self, opener, gap, waits=(), now=None):
        self.gap, self.waits = gap, tuple(waits)
        self.now = time.time() if now is None else float(now)
        raw = opener

        def patient(url, headers, **kw):
            for attempt in range(len(self.waits) + 1):
                try:
                    return raw(url, headers, **kw)
                except urllib.error.HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == len(self.waits):
                        raise
                    time.sleep(self.waits[attempt])
        self.opener = patient
        self.tiles = {}
        self.rows = {}
        self.kept = []               # programmes not re-read this run (read within DETAIL_TTL)
        self.requests, self.errors, self.truncated = 0, [], False
        self.lists_read = self.details = self.stubs = self.blocked = 0
        self.net_failures, self.stopped = 0, False
        self.rules = []
        self.videos = {}             # show id -> {episode id: entry} from the video sitemap
        self.sitemap_urls = 0

    def _failed(self, exc):
        if provider_base.network_failure(exc):
            self.net_failures += 1
            if self.net_failures >= provider_base.NET_FAILURE_BUDGET:
                self.stopped = self.truncated = True
        return self.stopped

    def get(self, path, **kw):
        self.requests += 1
        if self.requests % 100 == 0:
            _notify('dailyme_sync_progress', requests=self.requests, shows=len(self.tiles), items=len(self.rows),
                    errors=len(self.errors))
        try:
            return self.opener(_url(path), _headers(), **kw)
        finally:
            if self.gap:
                time.sleep(self.gap)

    def robots(self):
        try:
            self.rules = robots_rules(self.get('/robots.txt'))
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                raise                     # RFC 9309: server error -> assume everything is disallowed
            self.rules = []               # 4xx: no robots.txt, everything allowed
        except Exception as exc:
            self._failed(exc)
            raise                         # no connection: the run fails with the network message

    def allowed(self, path):
        if robots_allows(self.rules, path):
            return True
        self.blocked += 1
        return False

    def _tile(self, sid, slug):
        tile = self.tiles.get(sid)
        if tile is None and len(self.tiles) < MAX_SHOWS:
            tile = self.tiles[sid] = {'id': sid, 'slug': slug, 'title': '', 'poster': '', 'duration': None,
                                      'year': None, 'fsk': None, 'genres': [], 'lists': set()}
        elif tile is None:
            self.truncated = True
        return tile

    def sitemaps(self):
        """The sitemaps named in robots.txt (video and content); a missing sitemap is no error."""
        queue, done = list(SITEMAPS), set()
        while queue and not self.stopped and len(done) < MAX_SITEMAP_FILES:
            path = queue.pop(0)
            if path in done or not self.allowed(path):
                continue
            done.add(path)
            try:
                kind, entries = sitemap_entries(self.get(path, limit=MAX_SITEMAP))
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 410):
                    self.errors.append(_error(exc))
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                self._failed(exc)
                continue
            if kind == 'index':
                queue.extend(p for p in entries if p not in done and p not in queue)
                continue
            for entry in entries:
                self.sitemap_urls += 1
                episode = EPISODE_PATH.fullmatch(entry['path'])
                show = episode or SHOW_PATH.fullmatch(entry['path'])
                tile = self._tile(show.group(1), show.group(2))
                if tile is None:
                    continue
                if episode:
                    self.videos.setdefault(tile['id'], {})[episode.group(3)] = {
                        'id': episode.group(3), 'slug': episode.group(4), 'title': entry['title'],
                        'summary': entry['summary'], 'duration': entry['duration'], 'season': None,
                        'episode': None, 'poster': entry['poster'], 'year': entry['year']}
                else:
                    tile['poster'] = tile['poster'] or entry['poster']
                    tile['duration'] = tile['duration'] or entry['duration']

    def _merged(self, sid, episodes):
        """Episodes of the programme page plus those only the video sitemap names."""
        known = {e['id']: e for e in episodes}
        for eid, video in (self.videos.get(sid) or {}).items():
            entry = known.get(eid)
            if entry is None:
                known[eid] = dict(video)
                number = EPISODE_SLUG.search(video['slug'])
                if number:
                    known[eid]['episode'] = int(number.group(1))
            else:
                for key in ('title', 'summary', 'duration', 'poster'):
                    entry[key] = entry.get(key) or video.get(key)
        return list(known.values())

    def collect(self):
        queue, done = list(START_LISTS), set()
        while queue and not self.stopped:
            path = queue.pop(0)
            if path in done:
                continue
            if len(done) >= MAX_LISTS:
                self.truncated = True
                break
            done.add(path)
            if not self.allowed(path):
                continue
            try:
                shows, lists = list_page(self.get(path))
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 410):
                    self.errors.append(_error(exc))
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                self._failed(exc)
                continue
            self.lists_read += 1
            slug = _list_slug(path)
            for sid, tile in shows.items():
                known = self._tile(sid, tile['slug'])
                if known is None:
                    continue
                for key in ('title', 'poster', 'duration', 'year', 'genres'):
                    known[key] = known[key] or tile[key]
                if known['fsk'] is None:
                    known['fsk'] = tile['fsk']
                if path != '/':
                    known['lists'].add(slug)
            for found in lists:
                if found not in done and found not in queue:
                    queue.append(found)

    def read_shows(self, known):
        """Programme pages: new programmes first, then the oldest; at most MAX_DETAILS per run."""
        order = sorted(self.tiles.values(), key=lambda t: (known.get('s.' + t['id']) or known.get('m.' + t['id']) or 0))
        for tile in order:
            sid = tile['id']
            last = known.get('s.' + sid) or known.get('m.' + sid) or 0
            if self.stopped or len(self.rows) >= MAX_ITEMS:
                self.truncated = True
                break
            if last and last > self.now - DETAIL_TTL:
                self.kept.append(sid)
                continue
            if self.details >= MAX_DETAILS:
                self.kept.append(sid)
                continue
            path = '/content/show/%s-%s/' % (sid, tile['slug'])
            if not self.allowed(path):
                self._add(tile, {}, self._merged(sid, []), detailed=False)
                continue
            try:
                facts, episodes, stub = show_page(self.get(path), sid, tile['slug'])
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    continue              # programme withdrawn
                self.errors.append(_error(exc))
                self._add(tile, {}, self._merged(sid, []), detailed=False)
                continue
            except Exception as exc:
                self.errors.append(_error(exc))
                self._add(tile, {}, self._merged(sid, []), detailed=False)
                if self._failed(exc):
                    break
                continue
            self.details += 1
            self.stubs += 1 if stub else 0
            self._add(tile, facts, self._merged(sid, episodes), detailed=not stub)

    def _add(self, tile, facts, episodes, detailed):
        sid = tile['id']
        kind = _kind(tile, facts, episodes)
        genres = []
        for name in list(facts.get('genres') or []) + list(tile.get('genres') or []) + \
                [LIST_GENRE[s] for s in sorted(tile.get('lists') or ()) if s in LIST_GENRE]:
            if name and name not in genres and not (kind == 'movie' and name == 'Serie'):
                genres.append(name)
        fsk = facts.get('fsk') if facts.get('fsk') is not None else tile.get('fsk')
        show_url = '%s/content/show/%s-%s/' % (SITE, sid, tile['slug'])
        title = tile.get('title') or facts.get('title') or tile['slug'].replace('-', ' ').title()
        base = {'title': _text(title, 200), 'path': sid, 'series_id': '', 'season': None, 'episode': None,
                'year': facts.get('year') or tile.get('year'), 'rating': ('FSK %d' % fsk) if fsk is not None else '',
                'genre': ', '.join(genres[:6]), 'summary': facts.get('summary') or '',
                'poster': tile.get('poster') or facts.get('poster') or '', 'imdb_id': '', 'imdb_score': None,
                'imdb_votes': None, 'number': None, 'category': 'dailyme TV', 'playable': 0, 'drm': -1,
                'detailed': detailed}
        if kind == 'movie':
            video = episodes[0] if len(episodes) == 1 else None
            web = '%s/content/show/%s-%s/%s-%s' % (SITE, sid, tile['slug'], video['id'], video['slug']) if video else show_url
            self.rows['m.' + sid] = {**base, 'id': 'm.' + sid, 'kind': 'movie',
                                     'duration': (video or {}).get('duration') or facts.get('duration') or tile.get('duration'),
                                     'web_url': web}
            return
        self.rows['s.' + sid] = {**base, 'id': 's.' + sid, 'kind': 'series', 'duration': None, 'web_url': show_url}
        for entry in episodes:
            if len(self.rows) >= MAX_ITEMS:
                self.truncated = True
                break
            self.rows['e.' + entry['id']] = {
                **base, 'id': 'e.' + entry['id'], 'kind': 'episode', 'title': entry['title'] or base['title'],
                'path': entry['id'], 'series_id': 's.' + sid, 'season': entry['season'], 'episode': entry['episode'],
                'duration': entry['duration'], 'summary': entry['summary'] or '',
                'poster': entry['poster'] or base['poster'],
                'web_url': '%s/content/show/%s-%s/%s-%s' % (SITE, sid, tile['slug'], entry['id'], entry['slug'])}


# ---------------------------------------------------------------- storage

FIELDS = ('kind', 'title', 'path', 'series_id', 'season', 'episode', 'year', 'duration', 'rating', 'genre',
          'summary', 'poster', 'imdb_id', 'imdb_score', 'imdb_votes', 'number', 'category', 'playable', 'drm', 'web_url')
# Filled only from a programme page: kept from an earlier run when the page was a bare shell or not read.
DETAIL_FIELDS = ('summary', 'year', 'rating')


def _store(db, items, now):
    for item in items:
        # without a programme page an empty detail field keeps what an earlier reading found
        fields = [f for f in FIELDS if item.get('detailed') or f not in DETAIL_FIELDS or item.get(f)
                  or not db.execute('SELECT 1 FROM dailyme_items WHERE id=?', (item['id'],)).fetchone()]
        update = ','.join('%s=excluded.%s' % (f, f) for f in fields)
        detail_at = now if item.get('detailed') else 0
        db.execute('''INSERT INTO dailyme_items(id,%s,detail_at,seen,updated) VALUES(?,%s,?,?,?)
            ON CONFLICT(id) DO UPDATE SET %s,detail_at=MAX(dailyme_items.detail_at,excluded.detail_at),
            seen=excluded.seen,updated=excluded.updated'''
                   % (','.join(fields), ','.join('?' * len(fields)), update),
                   (item['id'], *[item.get(f) for f in fields], detail_at, now, now))


def _keep(db, show_ids, now):
    """Programmes not re-read this run stay listed with their episodes from the last reading."""
    for sid in show_ids:
        db.execute("UPDATE dailyme_items SET seen=? WHERE id IN (?,?) OR series_id=?", (now, 's.' + sid, 'm.' + sid, 's.' + sid))


def sync(root, opener=None, now=None, gap=None, waits=None):
    """Read the catalogue. Rows stay, but only titles seen in the latest successful run are listed."""
    now = time.time() if now is None else float(now)
    gap = (REQUEST_GAP if opener is None else 0) if gap is None else gap
    db = _connect(root)
    try:
        with db:
            _set(db, 'last_attempt', now)
            _set(db, 'last_result', 'running')
    finally:
        db.close()
    _notify('dailyme_sync_started')
    try:
        crawl = Crawl(opener or _open, gap, RETRY_WAITS if opener is None else (waits or ()), now=now)
        crawl.robots()
        crawl.sitemaps()
        crawl.collect()
        if not crawl.tiles:
            if crawl.blocked:
                raise ValueError('robots.txt von dailyme.de erlaubt das Lesen der Katalogseiten nicht')
            if crawl.errors:
                raise ValueError(crawl.errors[0])
            raise ValueError('dailyme.de liefert die Katalogseiten nur als JavaScript-Anwendung; '
                             'ohne eigenen Browser ist der Katalog nicht lesbar')
        db = _connect(root)
        try:
            known = {r[0]: float(r[1] or 0) for r in db.execute(
                "SELECT id, detail_at FROM dailyme_items WHERE kind IN ('series','movie')")}
        finally:
            db.close()
        crawl.read_shows(known)
        rows = list(crawl.rows.values())
        partial = crawl.truncated or len(crawl.errors) > max(3, 0.03 * crawl.requests)
        message = ('Katalog nur teilweise geladen: %s (%d Fehler)' % (crawl.errors[0], len(crawl.errors))
                   if crawl.errors and partial else 'Katalog nur teilweise geladen' if partial else '')
        db = _connect(root)
        try:
            with db:
                _store(db, rows, now)
                _keep(db, crawl.kept, now)
                counts = {kind + 's' if kind != 'series' else 'series': n for kind, n in db.execute(
                    "SELECT kind, COUNT(*) FROM dailyme_items WHERE seen>=? GROUP BY kind", (now,))}
                counts = {'movies': counts.get('movies', 0), 'series': counts.get('series', 0),
                          'episodes': counts.get('episodes', 0), 'channels': 0}
                previous = float(_get(db, 'last_success', '0') or 0)
                visible_since = previous if partial and previous else now
                waiting = max(0, len(crawl.tiles) - crawl.details - sum(
                    1 for sid in crawl.kept if known.get('s.' + sid) or known.get('m.' + sid)))
                for key, value in [('last_success', visible_since), ('last_loaded', now),
                                   ('last_result', 'partial' if partial else 'complete'), ('last_error', message),
                                   ('last_http_status', 0),
                                   ('next_attempt', now + (provider_base.NET_RETRY if crawl.stopped else 24 * 3600)),
                                   ('requests', crawl.requests), ('lists', crawl.lists_read),
                                   ('stubs', crawl.stubs), ('robots_blocked', crawl.blocked), ('sitemap_urls', crawl.sitemap_urls),
                                   ('details_waiting', waiting), *counts.items()]:
                    _set(db, key, value)
        finally:
            db.close()
        _notify('dailyme_sync_completed', partial=partial, requests=crawl.requests, lists=crawl.lists_read,
                details=crawl.details, stubs=crawl.stubs, robots_blocked=crawl.blocked, sitemap_urls=crawl.sitemap_urls, errors=len(crawl.errors),
                net_failures=crawl.net_failures, stopped=crawl.stopped, truncated=crawl.truncated,
                details_waiting=waiting, **counts)
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
        _notify('dailyme_sync_failed', http_status=getattr(exc, 'code', 0) or 0, error_type=netcheck.kind(exc))
        return {'ok': False, 'error': message}


# ---------------------------------------------------------------- reading

def _row(db, item_id):
    row = db.execute('SELECT * FROM dailyme_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def own_score(row):
    return None


def _summary(root, row, reports=None):
    import dailyme_enrichment
    report = (reports if reports is not None else dailyme_enrichment.all_cached(root)).get(row['id'])
    return portal_reference.summary(row.get('genre'), report, age=portal_reference.age_of(row))


def _labels(row):
    return {'offer_label': PLAYBACK_NOTE, 'badge': 'Kostenlos mit Werbung', 'playable': 0}


def episodes(root, series_id, now=None):
    if not VALID_ID.fullmatch(str(series_id or '')) or not str(series_id).startswith('s.'):
        raise ValueError('Ungültige dailyme-Serie')
    db = _connect(root)
    try:
        series = _row(db, series_id)
        if not series or series['kind'] != 'series':
            raise ValueError('Serie nicht im Katalog; bitte Katalog neu laden')
        last = float(_get(db, 'last_success', '0') or 0)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM dailyme_items WHERE kind='episode' AND series_id=? AND seen>=? "
            "ORDER BY season IS NULL, season, episode IS NULL, episode, CAST(path AS INTEGER), title", (series_id, last))]
    finally:
        db.close()
    extra = _summary(root, series)
    for row in rows:
        row.update(extra)
        row['poster'] = row['poster'] or series['poster']
        row.update(_labels(row))
    result = {'series': {'id': series_id, 'title': series['title'], **extra}, 'items': rows, 'error': ''}
    if not rows:
        result['note'] = 'Die Folgen dieser Serie stehen auf dailyme.de.'
    return result


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    import dailyme_enrichment
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 1) or 60, 200))
    kind = 'series' if view == 'series' else 'movie'
    db = _connect(root)
    try:
        last = float(_get(db, 'last_success', '0') or 0)
        sql = 'FROM dailyme_items WHERE kind=? AND seen>=?'
        args = [kind, last]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ? OR summary LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like, like]
        rows = [dict(r) for r in db.execute('SELECT * ' + sql + ' ORDER BY title COLLATE NOCASE', args)]
        counts = dict(db.execute("SELECT series_id,COUNT(*) FROM dailyme_items WHERE kind='episode' AND seen>=? "
                                 "GROUP BY series_id", (last,)).fetchall()) if kind == 'series' else {}
    finally:
        db.close()
    reports = dailyme_enrichment.all_cached(root)
    for row in rows:
        if kind == 'series':
            row['episodes'] = counts.get(row['id'], 0)
        row.update(_summary(root, row, reports))
        row.update(_labels(row))
    facets = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'rating':
        rows.sort(key=lambda r: (-(r['score'] or {}).get('value', -1), r['title'].casefold()))
    elif sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': facets}


def item(root, item_id):
    import dailyme_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger dailyme-Titel')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        parent = _row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    if not row:
        raise ValueError('dailyme-Titel nicht im Katalog; bitte Katalog neu laden')
    report = dailyme_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, {**base, 'genre': row.get('genre') or base.get('genre')}, {base['id']: report})
    return {'item': {**row, **summary, **_labels(row), 'poster': row.get('poster') or (parent or {}).get('poster') or ''},
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
            'episodes': _int(_get(db, 'episodes', '0')) or 0, 'channels': 0,
            'lists': _int(_get(db, 'lists', '0')) or 0, 'requests': _int(_get(db, 'requests', '0')) or 0,
            'sitemap_urls': _int(_get(db, 'sitemap_urls', '0')) or 0,
            'stubs': _int(_get(db, 'stubs', '0')) or 0, 'robots_blocked': _int(_get(db, 'robots_blocked', '0')) or 0,
            'details_waiting': _int(_get(db, 'details_waiting', '0')) or 0,
            'note': PLAYBACK_NOTE + '. ' + OFFLINE_NOTE}
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
    threading.Thread(target=_run, args=(root,), daemon=True, name='dailyme_catalog_sync').start()
    return True


def should_sync(root, now=None):
    return provider_base.catalog_due(root, sys.modules[__name__], state(root), now)


def loop(root, stop):
    provider_base.loop(root, stop, KEY, sys.modules[__name__])


def play_source(root, item_id):
    """dailyme plays only in its own player (session and access key per clip): never a source here."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger dailyme-Titel')
    raise ValueError(NOT_PLAYABLE)
