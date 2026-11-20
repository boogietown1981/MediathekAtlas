"""Audio and subtitle languages per title, for every source (0.6.5).

Björn (14.11.2026): "was mir bisher auch fehlt sind die Sprachen, in denen der Film oder die
Serie verfügbar ist". This module collects what is known about the languages of a title and
turns it into one model for the title page, the tiles and the language filter.

Evidence, strongest first (the page always says where a statement comes from):

1. ``stream``: the provider's own HLS master playlist was read when the title was played
   (``#EXT-X-MEDIA`` with ``TYPE=AUDIO`` / ``SUBTITLES`` / ``CLOSED-CAPTIONS`` and ``LANGUAGE``),
   on the server (ffmpeg path) or in the browser (hls.js reports its tracks).
2. ``provider``: language lists the provider publishes in its catalogue (Crunchyroll audio and
   subtitle locales, YouTube's audio language, ``audio_languages``/``subtitle_languages`` and
   similar fields in catalogue answers).
3. ``title``: explicit marks in the title (OmU, OV, Originalfassung, „mit Untertiteln“,
   „(Englisch)“, Audiodeskription, Gebärdensprache …) and, for the Mediatheken, the channel of a
   version (ARTE.FR is the French version) and the subtitle file the broadcaster lists.
4. ``assumed``: German for German-language offers (ARD/ZDF & Co., Netzkino, Joyn, TOGGO, RTL+,
   ServusTV) when nothing else is known. Shown as „vermutlich“ and never as a check.

Nothing is guessed beyond that: without evidence the page says „unbekannt“. Speech is never
analysed; a language means the label a provider or a stream gives a track.

Observations live in ``languages.sqlite3`` in the data folder (WAL, see provider_base), one row
per source, title and kind of evidence. Standard library only.
"""
from __future__ import annotations

import json
import re
import threading
import time

FILENAME = 'languages.sqlite3'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS title_languages(
  source TEXT NOT NULL, id TEXT NOT NULL, origin TEXT NOT NULL,
  audio TEXT NOT NULL DEFAULT '', subtitles TEXT NOT NULL DEFAULT '', extras TEXT NOT NULL DEFAULT '',
  checked REAL NOT NULL, PRIMARY KEY(source, id, origin));
'''
SOURCES = ('mediathek', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll',
           'plex', 'servustv', 'redbulltv', 'dmax', 'filmfriend', 'rtlplus', 'samsung', 'sender', 'archive')
ORIGINS = ('stream', 'provider')
MAX_ID = 200
MAX_TRACKS = 16
ORIGINAL = 'orig'          # original audio whose language is not named ("OV", "OmU")

# German labels; codes are ISO 639-1 where one exists.
LABELS = {
    'de': 'Deutsch', 'en': 'Englisch', 'fr': 'Französisch', 'es': 'Spanisch', 'it': 'Italienisch',
    'pt': 'Portugiesisch', 'nl': 'Niederländisch', 'pl': 'Polnisch', 'cs': 'Tschechisch', 'da': 'Dänisch',
    'sv': 'Schwedisch', 'no': 'Norwegisch', 'fi': 'Finnisch', 'is': 'Isländisch', 'ru': 'Russisch',
    'uk': 'Ukrainisch', 'tr': 'Türkisch', 'el': 'Griechisch', 'hu': 'Ungarisch', 'ro': 'Rumänisch',
    'hr': 'Kroatisch', 'sr': 'Serbisch', 'bg': 'Bulgarisch', 'sk': 'Slowakisch', 'sl': 'Slowenisch',
    'ja': 'Japanisch', 'ko': 'Koreanisch', 'zh': 'Chinesisch', 'hi': 'Hindi', 'ar': 'Arabisch',
    'he': 'Hebräisch', 'fa': 'Persisch', 'th': 'Thailändisch', 'vi': 'Vietnamesisch', 'id': 'Indonesisch',
    'ga': 'Irisch', 'cy': 'Walisisch', 'lb': 'Luxemburgisch', 'rm': 'Rätoromanisch', 'la': 'Latein',
    'gsw': 'Schweizerdeutsch', 'bar': 'Bairisch', 'nds': 'Plattdeutsch', 'sgn': 'Gebärdensprache',
    ORIGINAL: 'Originalton',
}
SHORT = {ORIGINAL: 'OV', 'gsw': 'CH', 'nds': 'NDS', 'bar': 'BAR', 'sgn': 'DGS'}
# ISO 639-2 (B and T), English and German names -> code
_ALIASES = {
    'deu': 'de', 'ger': 'de', 'german': 'de', 'deutsch': 'de', 'dt': 'de',
    'eng': 'en', 'english': 'en', 'englisch': 'en', 'engl': 'en',
    'fra': 'fr', 'fre': 'fr', 'french': 'fr', 'francais': 'fr', 'français': 'fr', 'französisch': 'fr', 'franzosisch': 'fr',
    'spa': 'es', 'spanish': 'es', 'espanol': 'es', 'español': 'es', 'spanisch': 'es', 'castellano': 'es',
    'ita': 'it', 'italian': 'it', 'italiano': 'it', 'italienisch': 'it',
    'por': 'pt', 'portuguese': 'pt', 'portugiesisch': 'pt', 'português': 'pt',
    'nld': 'nl', 'dut': 'nl', 'dutch': 'nl', 'niederländisch': 'nl', 'niederlandisch': 'nl', 'nederlands': 'nl',
    'pol': 'pl', 'polish': 'pl', 'polnisch': 'pl', 'polski': 'pl',
    'ces': 'cs', 'cze': 'cs', 'czech': 'cs', 'tschechisch': 'cs',
    'dan': 'da', 'danish': 'da', 'dänisch': 'da', 'danisch': 'da',
    'swe': 'sv', 'swedish': 'sv', 'schwedisch': 'sv',
    'nor': 'no', 'nob': 'no', 'nno': 'no', 'nb': 'no', 'nn': 'no', 'norwegian': 'no', 'norwegisch': 'no',
    'fin': 'fi', 'finnish': 'fi', 'finnisch': 'fi', 'isl': 'is', 'ice': 'is', 'icelandic': 'is', 'isländisch': 'is',
    'rus': 'ru', 'russian': 'ru', 'russisch': 'ru', 'ukr': 'uk', 'ukrainian': 'uk', 'ukrainisch': 'uk',
    'tur': 'tr', 'turkish': 'tr', 'türkisch': 'tr', 'turkisch': 'tr',
    'ell': 'el', 'gre': 'el', 'greek': 'el', 'griechisch': 'el',
    'hun': 'hu', 'hungarian': 'hu', 'ungarisch': 'hu', 'ron': 'ro', 'rum': 'ro', 'romanian': 'ro', 'rumänisch': 'ro',
    'hrv': 'hr', 'croatian': 'hr', 'kroatisch': 'hr', 'srp': 'sr', 'serbian': 'sr', 'serbisch': 'sr',
    'bul': 'bg', 'bulgarian': 'bg', 'bulgarisch': 'bg', 'slk': 'sk', 'slo': 'sk', 'slovak': 'sk', 'slowakisch': 'sk',
    'slv': 'sl', 'slovenian': 'sl', 'slowenisch': 'sl',
    'jpn': 'ja', 'japanese': 'ja', 'japanisch': 'ja', 'kor': 'ko', 'korean': 'ko', 'koreanisch': 'ko',
    'zho': 'zh', 'chi': 'zh', 'chinese': 'zh', 'chinesisch': 'zh', 'mandarin': 'zh', 'cmn': 'zh', 'yue': 'zh', 'kantonesisch': 'zh',
    'hin': 'hi', 'hindi': 'hi', 'ara': 'ar', 'arabic': 'ar', 'arabisch': 'ar',
    'heb': 'he', 'iw': 'he', 'hebrew': 'he', 'hebräisch': 'he', 'fas': 'fa', 'per': 'fa', 'persian': 'fa', 'persisch': 'fa',
    'tha': 'th', 'thai': 'th', 'vie': 'vi', 'vietnamese': 'vi', 'ind': 'id', 'in': 'id', 'indonesian': 'id',
    'gle': 'ga', 'irish': 'ga', 'cym': 'cy', 'wel': 'cy', 'welsh': 'cy', 'ltz': 'lb', 'luxembourgish': 'lb',
    'roh': 'rm', 'lat': 'la', 'latin': 'la', 'schweizerdeutsch': 'gsw', 'swiss german': 'gsw',
    'plattdeutsch': 'nds', 'niederdeutsch': 'nds', 'bairisch': 'bar', 'bayerisch': 'bar',
    'dgs': 'sgn', 'gsg': 'sgn', 'gebärdensprache': 'sgn',
    'original': ORIGINAL, 'originalton': ORIGINAL, 'ov': ORIGINAL, 'orig': ORIGINAL,
}
# "no language", "several", "unknown": never shown as a language
_NONE = {'und', 'zxx', 'mis', 'mul', 'qaa', 'xx', 'none', 'unknown', 'unbekannt', 'n/a', ''}

# Languages of German-language offers; shown as "vermutlich", never as checked.
ASSUMED_GERMAN = {'mediathek', 'netzkino', 'joyn', 'toggo', 'rtlplus', 'servustv', 'sender'}
# MediathekView channel names of the language versions of ARTE.
CHANNEL_LANGUAGE = {'ARTE.FR': 'fr', 'ARTE.EN': 'en', 'ARTE.ES': 'es', 'ARTE.IT': 'it', 'ARTE.PL': 'pl',
                    'ARTE.DE': 'de'}

ACCESS_AD = 'Audiodeskription'
ACCESS_DGS = 'Gebärdensprache'
ACCESS_CLEAR = 'Klare Sprache'
ACCESS_EASY = 'Leichte Sprache'

FILTERS = (('', 'Alle Sprachen'), ('de', 'Deutsch'), ('en', 'Englisch'), ('fr', 'Französisch'),
           ('ov', 'Originalfassung (OV/OmU)'), ('ut', 'Mit Untertiteln'))


def code(value):
    """ISO code for a language label ('de-DE', 'DEU', 'German', 'Deutsch' -> 'de'); '' if unknown."""
    if isinstance(value, dict):
        for key in ('code', 'iso', 'iso_639_1', 'abbr', 'locale', 'language', 'lang', 'id', 'name', 'label'):
            found = code(value.get(key))
            if found:
                return found
        return ''
    text = ' '.join(str(value or '').split()).strip().casefold().rstrip('.')
    if not text or text in _NONE or len(text) > 40:
        return ''
    if text in _ALIASES:
        return _ALIASES[text]
    base = re.split(r'[-_]', text, maxsplit=1)[0]
    if base in _NONE:
        return ''
    if base in LABELS:
        return base
    if base in _ALIASES:
        return _ALIASES[base]
    return ''


def label(c):
    return LABELS.get(c, c.upper() if c else '')


def _codes(values, limit=MAX_TRACKS):
    out = []
    for v in values if isinstance(values, (list, tuple, set)) else [values]:
        if isinstance(v, str) and ',' in v:
            out += [x for x in _codes(v.split(','), limit) if x not in out]
            continue
        c = code(v)
        if c and c not in out:
            out.append(c)
    return out[:limit]


# --- provider catalogue answers ------------------------------------------------------------------

_AUDIO_KEYS = ('audio_languages', 'audioLanguages', 'audio_locales', 'audioLocales', 'audio_locale', 'audioLocale',
               'audio_language', 'audioLanguage', 'defaultAudioLanguage', 'audioTracks', 'audio_tracks', 'audioStreams',
               'spoken_languages')
_SUB_KEYS = ('subtitle_languages', 'subtitleLanguages', 'subtitle_locales', 'subtitleLocales', 'subtitles',
             'subtitleTracks', 'subtitle_tracks', 'closedCaptions', 'closed_captions')


def harvest(node, extra_audio=(), depth=8):
    """{'audio': [...], 'subtitles': [...]} from language fields of a catalogue answer.

    Only fields that name audio or subtitle languages are read, at most ``depth`` levels deep
    (lists of streams inside an entry; Plex: Media → Part → Stream). ``extra_audio`` names further keys that mean audio for one
    provider (Joyn: ``languages``). Returns {} when the answer names no language."""
    audio, subs = [], []

    def walk(obj, level):
        if level > depth or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, list):
            for x in obj[:64]:
                walk(x, level + 1)
            return
        # Plex: Media -> Part -> Stream with streamType 2 (audio) / 3 (subtitle) and languageCode
        if obj.get('streamType') in (2, 3, '2', '3'):
            c = code(obj.get('languageTag')) or code(obj.get('languageCode')) or code(obj.get('language'))
            target = audio if str(obj.get('streamType')) == '2' else subs
            if c and c not in target:
                target.append(c)
            return
        for key, value in obj.items():
            if key in _AUDIO_KEYS or key in extra_audio:
                audio.extend(c for c in _codes(value if isinstance(value, list) else [value]) if c not in audio)
            elif key in _SUB_KEYS:
                if isinstance(value, list) or isinstance(value, str):
                    subs.extend(c for c in _codes(value if isinstance(value, list) else [value]) if c not in subs)
            elif isinstance(value, (dict, list)):
                walk(value, level + 1)
    walk(node, 0)
    out = {}
    if audio:
        out['audio'] = audio[:MAX_TRACKS]
    if subs:
        out['subtitles'] = subs[:MAX_TRACKS]
    return out


# --- titles ---------------------------------------------------------------------------------------

_LANG_WORDS = ('englisch|english|engl\\.?|französisch|franzosisch|french|spanisch|spanish|italienisch|italian|'
               'polnisch|polish|türkisch|turkish|russisch|russian|japanisch|japanese|koreanisch|korean|'
               'niederländisch|dutch|dänisch|danish|schwedisch|swedish|norwegisch|norwegian|finnisch|'
               'portugiesisch|griechisch|ukrainisch|arabisch|chinesisch|plattdeutsch|schweizerdeutsch')
_RX = {
    'omu': re.compile(r'(?i)\bOmU\b|\bOmdU\b|\boriginal(?:fassung|version|ton)?\s+mit\s+(?:deutschen\s+)?untertitel'),
    'omeu': re.compile(r'(?i)\bOmeU\b|\boriginal(?:fassung|version)?\s+mit\s+englischen\s+untertitel'),
    'ov': re.compile(r'(?i)[(\[]\s*(?:OV|OF|O-Ton|VO|VOST(?:F)?|Originalfassung|Originalversion|Original)\s*[)\]]|'
                     r'\boriginal(?:fassung|version)\b|\boriginal version\b|\bim original\b|\bO-Ton\b'),
    'sub_de': re.compile(r'(?i)[(\[]\s*(?:UT|mit\s+UT)\s*[)\]]|\bmit\s+(?:deutschen\s+)?untertiteln?\b|'
                         r'\bdeutsche\s+untertitel\b|\bgerman\s+subtitles?\b|\bdt\.?\s+UT\b'),
    'sub_en': re.compile(r'(?i)\benglish\s+subtitles?\b|\bmit\s+englischen\s+untertiteln?\b'),
    'ad': re.compile(r'(?i)\baudiodeskription\b|\baudio[- ]?description\b|\bhörfassung\b|\bhörfilm\b|[(\[]\s*AD\s*[)\]]'),
    'dgs': re.compile(r'(?i)\bgebärdensprache\b|\bgebärdenfassung\b|[(\[]\s*DGS\s*[)\]]|\bmit\s+gebärden'),
    'clear': re.compile(r'(?i)\bklare\s+sprache\b'),
    'easy': re.compile(r'(?i)\bleichte\s+sprache\b'),
    # "(Englisch)", "- englische Fassung", "English version", "in English", "auf Englisch"
    'lang': re.compile(r'(?i)[(\[]\s*(?:in\s+|auf\s+)?(' + _LANG_WORDS + r')(?:e\s+(?:fassung|version|originalfassung))?\s*[)\]]|'
                       r'\b(' + _LANG_WORDS + r')e\s+(?:fassung|version|originalfassung)\b|'
                       r'\b(?:in|auf)\s+(' + _LANG_WORDS + r')\b|\b(english|french|spanish|italian)\s+version\b'),
    'de': re.compile(r'(?i)\b(?:auf\s+deutsch|deutsche\s+fassung|german\s+dub|deutsch\s+synchronisiert|'
                     r'ganzer\s+film\s+(?:auf\s+)?deutsch|in\s+german)\b|[(\[]\s*deutsch\s*[)\]]'),
}


def from_title(*texts):
    """What the title itself says: {'audio', 'subtitles', 'original', 'accessibility'}."""
    text = ' '.join(str(t or '') for t in texts)[:1200]
    out = {'audio': [], 'subtitles': [], 'original': False, 'accessibility': []}
    if not text.strip():
        return out
    if _RX['omu'].search(text):
        out['original'] = True
        out['subtitles'].append('de')
    if _RX['omeu'].search(text):
        out['original'] = True
        out['subtitles'].append('en')
    if _RX['ov'].search(text):
        out['original'] = True
    if _RX['sub_de'].search(text) and 'de' not in out['subtitles']:
        out['subtitles'].append('de')
    if _RX['sub_en'].search(text) and 'en' not in out['subtitles']:
        out['subtitles'].append('en')
    for m in _RX['lang'].finditer(text):
        word = next(g for g in m.groups() if g)
        c = code(word.rstrip('.'))
        if c and c != 'de' and c not in out['audio'] and c not in out['subtitles']:
            out['audio'].append(c)
    if _RX['de'].search(text) and 'de' not in out['audio']:
        out['audio'].append('de')
    for key, name in (('ad', ACCESS_AD), ('dgs', ACCESS_DGS), ('clear', ACCESS_CLEAR), ('easy', ACCESS_EASY)):
        if _RX[key].search(text):
            out['accessibility'].append(name)
    return out


# --- HLS ------------------------------------------------------------------------------------------

_ATTR = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')


def parse_hls(text):
    """Tracks named in a master playlist: {'audio', 'subtitles', 'accessibility'}; {} for none."""
    audio, subs, access = [], [], []
    for raw in str(text or '').splitlines()[:5000]:
        line = raw.strip()
        if not line.startswith('#EXT-X-MEDIA:'):
            continue
        a = {k: v.strip('"') for k, v in _ATTR.findall(line.split(':', 1)[1])}
        kind = a.get('TYPE', '').upper()
        c = code(a.get('LANGUAGE')) or code(a.get('NAME'))
        if kind == 'AUDIO':
            if 'describes-video' in a.get('CHARACTERISTICS', '') or _RX['ad'].search(a.get('NAME', '')):
                if ACCESS_AD not in access:
                    access.append(ACCESS_AD)
            if c and c not in audio:
                audio.append(c)
        elif kind in ('SUBTITLES', 'CLOSED-CAPTIONS') and c and c not in subs:
            subs.append(c)
    out = {}
    if audio:
        out['audio'] = audio[:MAX_TRACKS]
    if subs:
        out['subtitles'] = subs[:MAX_TRACKS]
    if access:
        out['accessibility'] = access
    return out


def tracks_from_player(audio, subtitles):
    """hls.js audioTracks/subtitleTracks ({lang, name, characteristics}) as the same shape."""
    out, access = {}, []
    a, s = [], []
    for t in (audio or [])[:MAX_TRACKS]:
        if not isinstance(t, dict):
            continue
        c = code(t.get('lang')) or code(t.get('name'))
        if 'describes-video' in str(t.get('characteristics') or '') or _RX['ad'].search(str(t.get('name') or '')):
            access.append(ACCESS_AD)
        if c and c not in a:
            a.append(c)
    for t in (subtitles or [])[:MAX_TRACKS]:
        if isinstance(t, dict):
            c = code(t.get('lang')) or code(t.get('name'))
            if c and c not in s:
                s.append(c)
    if a:
        out['audio'] = a
    if s:
        out['subtitles'] = s
    if access:
        out['accessibility'] = [ACCESS_AD]
    return out


# --- store ----------------------------------------------------------------------------------------

_LOCK = threading.Lock()
_READY = set()
DEFAULT_ROOT = None        # set by the server: data folder for callers without one (catalog.item)


def _root(root):
    return root if root is not None else DEFAULT_ROOT


def _connect(root):
    import provider_base
    root = _root(root)
    if root is None:
        raise ValueError('Kein Datenordner')
    db = provider_base.connect(root, FILENAME)
    key = str(root)
    if key not in _READY:
        db.executescript(SCHEMA)
        _READY.add(key)
    return db


def _valid(source, item_id):
    return source in SOURCES and isinstance(item_id, str) and 0 < len(item_id) <= MAX_ID and '\n' not in item_id


def remember(root, source, item_id, found, origin='stream', now=None):
    """Store one observation. ``found``: {'audio', 'subtitles', 'accessibility'} with codes.
    An empty observation stores nothing (no audio track named = unknown, not 'none')."""
    item_id = str(item_id or '')
    if not _valid(source, item_id) or origin not in ORIGINS or not isinstance(found, dict):
        return False
    audio = _codes(found.get('audio') or [])
    subs = _codes(found.get('subtitles') or [])
    extras = [x for x in found.get('accessibility') or [] if x in (ACCESS_AD, ACCESS_DGS, ACCESS_CLEAR, ACCESS_EASY)]
    if not audio and not subs and not extras:
        return False
    now = time.time() if now is None else float(now)
    with _LOCK:
        db = _connect(root)
        try:
            with db:
                db.execute('INSERT OR REPLACE INTO title_languages VALUES(?,?,?,?,?,?,?)',
                           (source, item_id, origin, ','.join(audio), ','.join(subs), ','.join(extras), now))
        finally:
            db.close()
        _forget(root, source)
    return True


def remember_from_db(db, source, items, now=None):
    """Hook for the platforms' ``_store``: the data folder is the folder of their database file.
    Never raises (a catalogue run must not fail because of language notes)."""
    try:
        if not any(isinstance(i, dict) and i.get('languages') for i in items or []):
            return 0
        from pathlib import Path
        path = next((r[2] for r in db.execute('PRAGMA database_list') if r[1] == 'main'), '')
        if not path:
            return 0
        return remember_items(Path(path).parent, source, items, now)
    except Exception:
        return 0


def remember_items(root, source, items, now=None):
    """Provider languages harvested during a catalogue run (items carry a 'languages' dict)."""
    rows = [(str(i.get('id') or ''), i.get('languages')) for i in items or [] if isinstance(i, dict)]
    rows = [(i, f) for i, f in rows if f and _valid(source, i)]
    if not rows:
        return 0
    now = time.time() if now is None else float(now)
    with _LOCK:
        db = _connect(root)
        try:
            with db:
                for item_id, found in rows:
                    db.execute('INSERT OR REPLACE INTO title_languages VALUES(?,?,?,?,?,?,?)',
                               (source, item_id, 'provider', ','.join(_codes(found.get('audio') or [])),
                                ','.join(_codes(found.get('subtitles') or [])), '', now))
        finally:
            db.close()
        _forget(root, source)
    return len(rows)


def lookup(root, source, ids):
    """{id: {origin: {'audio', 'subtitles', 'accessibility', 'checked'}}} for the given ids."""
    ids = [str(i) for i in ids or [] if i]
    out = {}
    if not ids or source not in SOURCES:
        return out
    try:
        db = _connect(root)
    except Exception:
        return out
    try:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            for r in db.execute('SELECT id,origin,audio,subtitles,extras,checked FROM title_languages WHERE source=? AND id IN (%s)'
                                % ','.join('?' * len(chunk)), (source, *chunk)):
                out.setdefault(r[0], {})[r[1]] = {'audio': [x for x in r[2].split(',') if x],
                                                  'subtitles': [x for x in r[3].split(',') if x],
                                                  'accessibility': [x for x in r[4].split(',') if x], 'checked': r[5]}
    except Exception:
        return {}
    finally:
        db.close()
    return out


_ALL = {}
_ALL_TTL = 60.0


def _rootkey(root):
    from pathlib import Path
    root = _root(root)
    return str(Path(root).resolve()) if root is not None else ''


def _forget(root, source):
    _ALL.pop((_rootkey(root), source), None)


def cached_all(root, source):
    """all_for() kept in memory for a minute; remember() renews it at once."""
    root = _root(root)
    if root is None:
        return {}
    key = (_rootkey(root), source)
    hit = _ALL.get(key)
    now = time.monotonic()
    if hit and now - hit[0] <= _ALL_TTL:
        return hit[1]
    value = all_for(root, source)
    _ALL[key] = (now, value)
    return value


def all_for(root, source):
    """Every observation of one source (small: only played or provider-labelled titles)."""
    try:
        db = _connect(root)
    except Exception:
        return {}
    out = {}
    try:
        for r in db.execute('SELECT id,origin,audio,subtitles,extras,checked FROM title_languages WHERE source=?', (source,)):
            out.setdefault(r[0], {})[r[1]] = {'audio': [x for x in r[2].split(',') if x],
                                              'subtitles': [x for x in r[3].split(',') if x],
                                              'accessibility': [x for x in r[4].split(',') if x], 'checked': r[5]}
    except Exception:
        return {}
    finally:
        db.close()
    return out


def counts(root):
    try:
        db = _connect(root)
    except Exception:
        return {}
    try:
        return {f'{s}/{o}': n for s, o, n in db.execute('SELECT source,origin,COUNT(*) FROM title_languages GROUP BY source,origin')}
    except Exception:
        return {}
    finally:
        db.close()


# --- player references ----------------------------------------------------------------------------

REF_SOURCE = {'offer': 'mediathek', 'netzkino': 'netzkino', 'pluto': 'pluto', 'justwatch': 'justwatch',
              'rakuten': 'rakuten', 'joyn': 'joyn', 'toggo': 'toggo', 'crunchyroll': 'crunchyroll',
              'samsung': 'samsung', 'plex': 'plex', 'servustv': 'servustv', 'rtlplus': 'rtlplus', 'youtube': 'youtube',
              'redbulltv': 'redbulltv', 'dmax': 'dmax', 'filmfriend': 'filmfriend', 'sender': 'sender'}


def ref_key(ref):
    """(source, id) of a player reference such as {'pluto': '…'}; None for local files and jobs."""
    for key, source in REF_SOURCE.items():
        value = str((ref or {}).get(key) or '')
        if value:
            return (source, value) if _valid(source, value) else None
    return None


def observe_hls(root, ref, url, fetch=None):
    """Read the (cached) master playlist of a stream that is being played and keep its tracks."""
    key = ref_key(ref)
    if not key or not url:
        return {}
    import hls_variants
    try:
        text = hls_variants.load(url, fetch)[0]
    except Exception:
        return {}
    found = parse_hls(text)
    if found:
        remember(root, key[0], key[1], found, 'stream')
    return found


# --- model ----------------------------------------------------------------------------------------

def _day(stamp):
    try:
        return time.strftime('%d.%m.%Y', time.localtime(float(stamp)))
    except (TypeError, ValueError, OverflowError):
        return ''


def _entries(codes):
    return [{'code': c, 'label': label(c)} for c in codes]


def build(source, *, observed=None, provider=None, titles=(), assumed=None, original_language='', provider_name='',
          extra=None):
    """One model for page, tile and filter.

    observed: {origin: {...}} from lookup() (stream/provider, possibly of several ids merged);
    provider: {'audio', 'subtitles'} known from the provider row itself (Crunchyroll, YouTube);
    titles: title texts to read OmU/OV/… from; extra: a pre-built from_title()-like dict
    (Mediatheken: channel and subtitle file); assumed: German if nothing else is known
    (default: source in ASSUMED_GERMAN)."""
    observed = observed or {}
    stream = observed.get('stream') or {}
    prov = {'audio': list((provider or {}).get('audio') or []), 'subtitles': list((provider or {}).get('subtitles') or [])}
    for c in (observed.get('provider') or {}).get('audio') or []:
        if c not in prov['audio']:
            prov['audio'].append(c)
    for c in (observed.get('provider') or {}).get('subtitles') or []:
        if c not in prov['subtitles']:
            prov['subtitles'].append(c)
    hint = from_title(*titles)
    if extra:
        for k in ('audio', 'subtitles', 'accessibility'):
            for c in extra.get(k) or []:
                if c not in hint[k]:
                    hint[k].append(c)
        hint['original'] = hint['original'] or bool(extra.get('original'))
    orig = code(original_language)
    evidence = []
    audio, subs = [], []

    def add(target, codes):
        for c in codes:
            if c and c not in target:
                target.append(c)
    if stream.get('audio') or stream.get('subtitles'):
        add(audio, stream.get('audio') or [])
        add(subs, stream.get('subtitles') or [])
        evidence.append({'kind': 'stream', 'label': 'im Stream geprüft' + (' am ' + _day(stream['checked']) if stream.get('checked') else '')})
    if prov['audio'] or prov['subtitles']:
        add(audio, prov['audio'])
        add(subs, prov['subtitles'])
        evidence.append({'kind': 'provider', 'label': 'laut ' + (provider_name or 'Anbieter')})
    # 0.6.6 (Björn, 14.11.2026: a Plex title named "OmU" played with German sound): sound measured in
    # the stream or named by the provider wins over the title. Only German there → no original version.
    measured = list(stream.get('audio') or prov['audio'])
    contradicted = bool(hint['original'] and measured and all(c == 'de' for c in measured))
    if contradicted:
        hint['original'] = False
    title_audio = list(hint['audio'])
    if hint['original'] and not title_audio:
        title_audio.append(orig if orig and orig != 'de' else ORIGINAL)
    if title_audio or hint['subtitles'] or contradicted:
        if not measured:
            add(audio, title_audio)
        add(subs, hint['subtitles'])
        evidence.append({'kind': 'title', 'label': 'laut Titel' + (' bzw. Sender' if extra else '')
                         + ('; der Titel nennt eine Originalfassung, der Ton ist aber Deutsch' if contradicted else '')})
    if ORIGINAL in audio and orig and orig not in audio:
        audio[audio.index(ORIGINAL)] = orig if orig != 'de' else ORIGINAL
    is_assumed = False
    if assumed is None:
        assumed = source in ASSUMED_GERMAN
    # German-language offers: the regular version is German unless the stream says otherwise.
    if assumed and not stream.get('audio') and 'de' not in audio and not (prov['audio']):
        if not audio or (extra or {}).get('regular'):
            audio.insert(0, 'de')
            is_assumed = True
    access = []
    for x in (stream.get('accessibility') or []) + hint['accessibility']:
        if x not in access:
            access.append(x)
    model = {'audio': _entries(audio), 'subtitles': _entries(subs), 'original': bool(hint['original'] or ORIGINAL in audio),
             'original_language': {'code': orig, 'label': label(orig)} if orig else None,
             'accessibility': access, 'assumed': is_assumed, 'assumed_codes': ['de'] if is_assumed else [],
             'evidence': evidence, 'known': bool(audio or subs)}
    if is_assumed:
        model['evidence'].append({'kind': 'assumed', 'label': 'vermutet: deutschsprachiges Angebot von ' + (provider_name or 'Anbieter') + ', nicht geprüft'})
    model['short'] = short(model)
    model['text'] = text(model)
    model['rows'] = facts(model)
    return model


def short(model):
    """Short label for a tile; '' when it would only repeat the obvious (German, assumed)."""
    audio = [a['code'] for a in model.get('audio') or []]
    subs = [s['code'] for s in model.get('subtitles') or []]
    parts = []
    if model.get('original') and subs and len(audio) <= 1:
        parts.append('OmU' if 'de' in subs else 'OV')
    else:
        shown = [SHORT.get(c, c.upper()) for c in audio]
        if model.get('assumed') and audio == ['de']:
            shown = []
        if shown and not (audio == ['de'] and not subs):
            parts.append(' · '.join(shown[:4]) + (' +' if len(shown) > 4 else ''))
        if subs:
            parts.append('UT ' + '/'.join(SHORT.get(c, c.upper()) for c in subs[:3]))
    if ACCESS_AD in (model.get('accessibility') or []):
        parts.append('AD')
    if ACCESS_DGS in (model.get('accessibility') or []):
        parts.append('DGS')
    return ' · '.join(p for p in parts if p)


def text(model):
    """One line for lists: 'Ton: Deutsch, Englisch · Untertitel: Deutsch'."""
    if not model.get('known') and not model.get('accessibility'):
        return 'unbekannt'
    parts = []
    if model.get('audio'):
        names = [a['label'] for a in model['audio']]
        if model.get('assumed'):
            names = [n + ' (vermutlich)' if a['code'] == 'de' else n for n, a in zip(names, model['audio'])]
        parts.append('Ton: ' + ', '.join(names))
    else:
        parts.append('Ton: unbekannt')
    if model.get('subtitles'):
        parts.append('Untertitel: ' + ', '.join(s['label'] for s in model['subtitles']))
    if model.get('accessibility'):
        parts.append(', '.join(model['accessibility']))
    return ' · '.join(parts)


def keys(model):
    """Values of the language filter that this model satisfies."""
    out = set()
    for a in model.get('audio') or []:
        out.add(a['code'])
    if model.get('original'):
        out.add('ov')
    if model.get('subtitles'):
        out.add('ut')
    return out


def matches(model, wanted):
    return not wanted or wanted in keys(model)


def facts(model):
    """Rows for the title page: [['Tonspuren', …], ['Untertitel', …], ['Barrierefreiheit', …], ['Sprachangaben', …]]."""
    rows = []
    audio = model.get('audio') or []
    if audio:
        rows.append(['Tonspuren', ', '.join(a['label'] + (' (vermutlich)' if model.get('assumed') and a['code'] in model.get('assumed_codes', []) else '')
                                            for a in audio)])
    else:
        rows.append(['Tonspuren', 'unbekannt'])
    if model.get('subtitles'):
        rows.append(['Untertitel', ', '.join(s['label'] for s in model['subtitles'])])
    elif model.get('known'):
        rows.append(['Untertitel', 'keine Angabe'])
    if model.get('accessibility'):
        rows.append(['Barrierefreiheit', ', '.join(model['accessibility'])])
    if model.get('original_language') and model['original_language']['code'] not in (ORIGINAL,):
        rows.append(['Originalsprache', model['original_language']['label']])
    rows.append(['Sprachangaben', '; '.join(e['label'] for e in model.get('evidence') or []) or
                 'keine – der Anbieter nennt keine Sprachen; beim Abspielen wird der Stream geprüft, sofern er Tonspuren benennt'])
    return rows


# --- Mediatheken ----------------------------------------------------------------------------------

def mediathek_row(row):
    """What one broadcaster offer says: channel version, title marks, subtitle file."""
    row = row or {}
    channel = str(row.get('channel') or '').strip().upper()
    hint = from_title(row.get('title'))
    out = {'audio': [], 'subtitles': list(hint['subtitles']), 'accessibility': list(hint['accessibility']),
           'original': hint['original'], 'regular': False}
    lang = CHANNEL_LANGUAGE.get(channel)
    if hint['audio']:
        out['audio'] = list(hint['audio'])
    elif lang and lang != 'de' and not hint['original']:
        out['audio'] = [lang]          # ARTE.FR: the French version
    elif not hint['original']:
        out['regular'] = True          # regular version of a German channel (German, not checked)
    if str(row.get('url_subtitle') or '').startswith(('http://', 'https://')):
        sub = lang or 'de'
        if sub not in out['subtitles']:
            out['subtitles'].append(sub)
    return out


def mediathek_rows(rows):
    """Union of several offers of one work (the regular version, OmU, AD …)."""
    out = {'audio': [], 'subtitles': [], 'accessibility': [], 'original': False, 'regular': False}
    for row in rows:
        one = mediathek_row(row)
        for k in ('audio', 'subtitles', 'accessibility'):
            for c in one[k]:
                if c not in out[k]:
                    out[k].append(c)
        out['original'] = out['original'] or one['original']
        out['regular'] = out['regular'] or one['regular']
    return out


def for_mediathek(root, offers, meta=None, observed=None):
    """Model of a Mediathek work from its offers [(offer_id, payload dict)]."""
    meta = meta or {}
    if observed is None:
        known = cached_all(root, 'mediathek')
        observed = merge_observed(known[o] for o, _ in offers if o in known)
    extra = mediathek_rows([p for _, p in offers])
    return build('mediathek', observed=observed, extra=extra, original_language=meta.get('original_language') or '',
                 provider_name='ARD, ZDF & Co.')


def merge_observed(values):
    """Several observation maps (episodes of a series, versions of a film) as one."""
    out = {}
    for one in values:
        for origin, v in (one or {}).items():
            slot = out.setdefault(origin, {'audio': [], 'subtitles': [], 'accessibility': [], 'checked': 0})
            for k in ('audio', 'subtitles', 'accessibility'):
                for c in v.get(k) or []:
                    if c not in slot[k]:
                        slot[k].append(c)
            slot['checked'] = max(slot['checked'] or 0, v.get('checked') or 0)
    return out


# --- platforms ------------------------------------------------------------------------------------

def provider_row(source, row):
    """Languages the stored row of a platform already carries."""
    row = row or {}
    if source == 'crunchyroll':
        langs = str(row.get('languages') or '').split(',')
        # 'dub' = German audio, 'sub' = German subtitles (crunchyroll._languages); Japanese original
        # is not stored, so only German is named.
        return {'audio': ['de'] if 'dub' in langs else [], 'subtitles': ['de'] if 'sub' in langs else []}
    if source == 'youtube':
        c = code(row.get('language'))
        return {'audio': [c] if c else [], 'subtitles': []}
    return {}


def for_portal(root, source, row, observed=None, extra_ids=(), name=''):
    """Model of a platform title from its stored row (+ observations of it and its episodes)."""
    row = row or {}
    item_id = str(row.get('id') or '')
    if observed is None:
        known = cached_all(root, source)
        observed = merge_observed(known[i] for i in (item_id, *extra_ids) if i in known)
    titles = [row.get('title'), row.get('raw_title')] if source == 'youtube' else [row.get('title')]
    return build(source, observed=observed, provider=provider_row(source, row), titles=titles, provider_name=name,
                 original_language=row.get('original_language') or '')


def to_json(model):
    return json.dumps(model, ensure_ascii=False, sort_keys=True)


def combine(models):
    """One model for a series from the models of its episodes (union of languages)."""
    models = [m for m in models or [] if m]
    if not models:
        return None
    audio, subs, access, evidence = [], [], [], []
    for m in models:
        for a in m.get('audio') or []:
            if a['code'] not in audio:
                audio.append(a['code'])
        for s in m.get('subtitles') or []:
            if s['code'] not in subs:
                subs.append(s['code'])
        for x in m.get('accessibility') or []:
            if x not in access:
                access.append(x)
        for e in m.get('evidence') or []:
            if e['label'] not in [x['label'] for x in evidence]:
                evidence.append(e)
    assumed = all(m.get('assumed') for m in models if m.get('audio'))
    if not assumed:
        evidence = [e for e in evidence if e['kind'] != 'assumed'] + [e for e in evidence if e['kind'] == 'assumed'][:1]
    out = {'audio': _entries(audio), 'subtitles': _entries(subs), 'original': any(m.get('original') for m in models),
           'original_language': next((m['original_language'] for m in models if m.get('original_language')), None),
           'accessibility': access, 'assumed': bool(assumed and audio == ['de']),
           'assumed_codes': ['de'] if assumed and audio == ['de'] else [], 'evidence': evidence[:6], 'known': bool(audio or subs)}
    out['short'] = short(out)
    out['text'] = text(out)
    out['rows'] = facts(out)
    return out


# --- filter for the Mediathek catalogue -----------------------------------------------------------

_LIKE_OV = ('%OmU%', '%OmdU%', '%OmeU%', '%(OV)%', '%[OV]%', '%Originalfassung%', '%Originalversion%',
            '%Original mit%', '%O-Ton%', '%original version%')
_LIKE_UT = ('%Untertitel%', '%(UT)%', '%subtitles%')
_LIKE_WORD = {'en': ('%Englisch%', '%English%', '%(engl%'), 'fr': ('%Französisch%', '%French%'),
              'es': ('%Spanisch%', '%Spanish%'), 'it': ('%Italienisch%', '%Italian%'), 'pl': ('%Polnisch%', '%Polish%')}
_FOREIGN_CHANNELS = tuple(ch for ch, lang in CHANNEL_LANGUAGE.items() if lang != 'de')


def _rows(c, where, args, scope=''):
    # each field is read from the JSON once per offer, then compared (t = title, ch = channel)
    # MATERIALIZED (SQLite 3.35+) reads each JSON field once; older SQLite (some NAS) gets the plain form
    sql = ("WITH o AS @MAT@ (SELECT work_id, json_extract(payload,'$.channel') AS ch, "
           "json_extract(payload,'$.title') AS t, json_extract(payload,'$.url_subtitle') AS sub FROM offers "
           "WHERE active=1" + scope + ") SELECT work_id, ch, t, sub FROM o WHERE " + where)
    import sqlite3
    try:
        cursor = c.execute(sql.replace('@MAT@', 'MATERIALIZED'), args)
    except sqlite3.OperationalError:
        cursor = c.execute(sql.replace('@MAT@', ''), args)
    for work, channel, title, sub in cursor:
        yield work, {'channel': channel or '', 'title': title or '', 'url_subtitle': sub or ''}


_FILTER_CACHE = {}
FILTER_TTL = 600.0         # the broadcaster list changes with the filmlist import (hours)


def mediathek_filter(c, wanted, now=None):
    """('include', work ids) or ('exclude', work ids) for the language filter of the Mediatheken.

    Regular versions of German channels count as German (assumed, as on the title page); only
    the candidates found by a cheap text search are read in full. Kept 10 minutes in memory."""
    now = time.monotonic() if now is None else now
    hit = _FILTER_CACHE.get(wanted)
    if hit and now - hit[0] <= FILTER_TTL:
        return hit[1]
    value = _mediathek_filter(c, wanted)
    _FILTER_CACHE.clear()          # one filter at a time: the sets can be large
    _FILTER_CACHE[wanted] = (now, value)
    return value


def forget_filters():
    _FILTER_CACHE.clear()


def _mediathek_filter(c, wanted):
    likes, args = [], []

    def like(patterns):
        for p in patterns:
            likes.append("t LIKE ?")
            args.append(p)
    sure = set()
    if wanted == 'ut':
        # a subtitle file of the broadcaster is enough; only title marks need a closer look
        sure = {r[0] for r in c.execute("SELECT DISTINCT work_id FROM offers WHERE active=1 AND "
                                        "json_extract(payload,'$.url_subtitle') LIKE 'http%'")}
        like(_LIKE_UT + _LIKE_OV)
    elif wanted == 'ov':
        like(_LIKE_OV)
    elif wanted in LABELS and wanted != 'de':
        like(_LIKE_WORD.get(wanted, ()))
        chans = [ch for ch, lang in CHANNEL_LANGUAGE.items() if lang == wanted]
        if chans:
            likes.append("ch IN (%s)" % ','.join('?' * len(chans)))
            args.extend(chans)
    elif wanted == 'de':
        like(_LIKE_OV + tuple(p for v in _LIKE_WORD.values() for p in v))
        likes.append("ch IN (%s)" % ','.join('?' * len(_FOREIGN_CHANNELS)))
        args.extend(_FOREIGN_CHANNELS)
    if not likes:
        return ('include', sure)
    found = {}
    for work, row in _rows(c, ' OR '.join(likes), args):
        if work not in sure:
            found.setdefault(work, []).append(row)
    if wanted == 'de':
        # candidates whose versions are all foreign or original: look at every version of them
        foreign = set()
        works = list(found)
        for start in range(0, len(works), 500):
            chunk = works[start:start + 500]
            versions = {}
            for work, row in _rows(c, '1', chunk, ' AND work_id IN (%s)' % ','.join('?' * len(chunk))):
                versions.setdefault(work, []).append(row)
            for work, rows in versions.items():
                m = build('mediathek', extra=mediathek_rows(rows))
                if 'de' not in keys(m):
                    foreign.add(work)
        return ('exclude', foreign)
    out = sure
    for work, rows in found.items():
        if wanted in keys(build('mediathek', extra=mediathek_rows(rows))):
            out.add(work)
    return ('include', out)


def valid_filter(value):
    value = str(value or '').strip().lower()[:8]
    return value if value in dict(FILTERS) or value in LABELS else ''
