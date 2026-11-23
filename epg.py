"""Programme guide (EPG) of the public broadcasters, from their own programme services.

Björn (23.11.2026): a programme guide for the TV stations of the Live-TV tab, and the programme data as
evidence for the recognition of Mediathek offers (show, date, episode title/number, genre: news or film).

Sources (all public, used by the broadcasters' own websites and apps, no account, no key):
- SRF (SRF 1, SRF zwei, SRF info): SRG SSR Integration Layer
  ``il.srgssr.ch/integrationlayer/2.0/srf/programGuide/tv/byDate/<YYYY-MM-DD>?reduced=false``.
  Checked live on 23.11.2026: about 14–20 days back and five weeks ahead; genre, production year and
  country, season/episode/episodes total, repeat flag and ``mediaUrn`` (the Play SRF video id).
- ARD (Das Erste, the regional stations, ONE, ARD alpha, tagesschau24 …): ARD programme API
  ``programm-api.ard.de/program/api/program?day=<YYYY-MM-DD>`` (all ARD stations in one answer; the same
  source as programm.ard.de and the Zapp app). Checked live: a few days back fine, 30 days back answers 404.
- ZDF family (ZDF, ZDFneo, ZDFinfo, 3sat, KiKA, phoenix): ``api.zdf.de/cmdm/epg/broadcasts`` with the
  guest token of the ZDF website (reference: mediathekview/zapp-backend, MIT). NOT checked live yet.

Nothing here touches copy protection or a commercial programme guide (TV Spielfilm, HÖRZU, fernsehserien.de,
wunschliste.de: their terms forbid automatic reading; wunschliste.de is only linked, see epg_links in the UI).

Storage: ``epg.sqlite3`` in the data folder (not catalog.db): one row per broadcast, texts shortened. About
1,500 broadcasts per day, roughly 0.5 MB per day; broadcasts older than KEEP_DAYS are removed. A run every
6 hours fetches the days that are not final yet (yesterday … AHEAD_DAYS ahead); past days are fetched once,
on the first run as far back as each source answers (BACKFILL_DAYS). About 30 requests per run.
"""
from __future__ import annotations

import datetime
import json
import re
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path

KEY = 'epg'
NAME = 'Programmführer'
FILE = 'epg.sqlite3'
REFRESH = 6 * 3600
RETRY = 45 * 60
AHEAD_DAYS = 7               # live view and next broadcasts
BACKFILL_DAYS = 14           # first run: as far back as the sources answer (evidence for the recognition)
KEEP_DAYS = 400              # evidence stays a year; the Mediathek keeps many offers that long
MAX_ANSWER = 8 * 1024 * 1024
MIN_INTERVAL = 0.7           # seconds between two requests (polite client of a public service)
TEXT = 400                   # stored description length
TZ = datetime.timezone(datetime.timedelta(hours=1))   # only for naming days; times are stored as epoch seconds

SRF_URL = 'https://il.srgssr.ch/integrationlayer/2.0/{vendor}/programGuide/tv/byDate/{day}?reduced=false'
SRG_VENDORS = ('srf',)       # rts/rsi answer as well; French/Italian stations are not in the Live-TV tab
ARD_URL = 'https://programm-api.ard.de/program/api/program?day={day}'
ZDF_URL = 'https://api.zdf.de/cmdm/epg/broadcasts?from={start}&to={end}&limit=200&page={page}&order=asc&tvServices={service}'
ZDF_TOKEN = 'https://zdf-prod-futura.zdf.de/mediathekV2/token'
ZDF_PAGE = 'https://www.zdf.de/live-tv'
ZDF_SERVICES = ('zdf', 'ZDFneo', 'zdfinfo', '3sat', 'ki.ka', 'phoenix')
SOURCES = ('srf', 'ard', 'zdf')
SOURCE_NAMES = {'srf': 'SRF', 'ard': 'ARD', 'zdf': 'ZDF'}

# Genre words that make a broadcast a feature film or a news/magazine programme (recognition evidence).
FILM_GENRES = re.compile(r'(?i)\b(?:spielfilm|fernsehfilm|tv-?film|kinofilm|film|drama|komödie|thriller|krimi(?:nalfilm)?|western|'
                         r'abenteuer(?:film)?|liebesfilm|actionfilm|horrorfilm|science[- ]fiction|fantasy|animationsfilm|zeichentrickfilm)\b')
SHOW_GENRES = re.compile(r'(?i)\b(?:news|nachrichten|magazin|info|dok|doku\w*|reportage|talk|unterhaltung|show|sport|'
                         r'ratgeber|service|kultur|wissen|quiz|musik|religion|politik|wetter|kinder|jugend)\b')

_LOCK = threading.Lock()
_SYNC_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]
_ACTIVE = False
_ZDF_TOKEN = {}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS broadcasts(
  station TEXT NOT NULL, start INTEGER NOT NULL, stop INTEGER NOT NULL, source TEXT NOT NULL,
  title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '',
  season INTEGER, episode INTEGER, episodes INTEGER, year INTEGER, country TEXT NOT NULL DEFAULT '',
  repeat INTEGER NOT NULL DEFAULT 0, live INTEGER NOT NULL DEFAULT 0, media TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '', fetched REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(station, start));
CREATE INDEX IF NOT EXISTS broadcasts_start ON broadcasts(start);
CREATE INDEX IF NOT EXISTS broadcasts_media ON broadcasts(media) WHERE media<>'';
CREATE TABLE IF NOT EXISTS days(source TEXT NOT NULL, day TEXT NOT NULL, fetched REAL NOT NULL, entries INTEGER NOT NULL,
  result TEXT NOT NULL, PRIMARY KEY(source, day));
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


class Unavailable(Exception):
    """The source did not answer usefully (network, HTTP error, unknown format)."""


def _notify(event, **details):
    """Technical counters only; never titles or addresses."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def _text(value, limit=200):
    value = re.sub(r'<[^>]{0,200}>', ' ', str(value or ''))
    return ' '.join(value.split())[:limit]


def _int(value, low=0, high=100000):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _stamp(value):
    """ISO time with offset -> epoch seconds (None when missing or without zone)."""
    try:
        moment = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return None
    return int(moment.timestamp())


def station_key(name):
    import live_tv
    return live_tv.station_key(live_tv.station_name(name))


# ---------------------------------------------------------------- storage

def connect(root):
    import provider_base
    db = provider_base.connect(root, FILE)
    provider_base.ensure_schema(db, SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, **values):
    db.executemany('INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   [(k, json.dumps(v)) for k, v in values.items()])


def _value(db, key, default):
    try:
        return json.loads(_get(db, key, json.dumps(default)))
    except ValueError:
        return default


def store(db, rows, now=None):
    """Write normalised broadcasts; a newer answer replaces the same station and start time."""
    now = time.time() if now is None else now
    fields = ('station', 'start', 'stop', 'source', 'title', 'subtitle', 'genre', 'season', 'episode', 'episodes', 'year',
              'country', 'repeat', 'live', 'media', 'description', 'channel')
    db.executemany('INSERT OR REPLACE INTO broadcasts(%s,fetched) VALUES(%s,?)' % (','.join(fields), ','.join('?' * len(fields))),
                   [tuple(r.get(f) for f in fields) + (now,) for r in rows])
    return len(rows)


def _row(source, channel, start, stop, title, **extra):
    if not title or start is None:
        return None
    stop = stop if isinstance(stop, int) and stop > start else start + 1800
    row = {'station': station_key(channel), 'start': start, 'stop': min(stop, start + 24 * 3600), 'source': source,
           'title': _text(title), 'subtitle': '', 'genre': '', 'season': None, 'episode': None, 'episodes': None,
           'year': None, 'country': '', 'repeat': 0, 'live': 0, 'media': '', 'description': '', 'channel': _text(channel, 80)}
    row.update({k: v for k, v in extra.items() if v not in (None, '')})
    if not row['station'] or row['station'] == 'sender':
        return None
    return row


# ---------------------------------------------------------------- parsers (every field optional)

def parse_srf(data):
    out = []
    guide = data.get('programGuide') if isinstance(data, dict) else None
    for block in guide if isinstance(guide, list) else []:
        channel = _text(((block or {}).get('channel') or {}).get('title'), 80) if isinstance(block, dict) else ''
        for p in (block.get('programList') or []) if isinstance(block, dict) else []:
            if not isinstance(p, dict) or not channel:
                continue
            media = str(p.get('mediaUrn') or '')
            row = _row('srf', channel, _stamp(p.get('startTime')), _stamp(p.get('endTime')), p.get('title'),
                       subtitle=_text(p.get('subtitle')), genre=_text(p.get('genre'), 60),
                       season=_int(p.get('seasonNumber'), 0, 500), episode=_int(p.get('episodeNumber'), 0, 100000),
                       episodes=_int(p.get('episodesTotal'), 0, 100000), year=_int(p.get('productionYear'), 1890, 2100),
                       country=_text(p.get('productionCountry'), 80), repeat=1 if p.get('isRepetition') is True else 0,
                       live=1 if p.get('isLive') is True else 0,
                       media=media if re.fullmatch(r'urn:srf:video:[0-9a-f\-]{36}', media) else '',
                       description=_text(p.get('lead') or p.get('description'), TEXT))
            if row:
                out.append(row)
    return out


def parse_ard(data):
    out = []
    channels = data.get('channels') if isinstance(data, dict) else None
    for ch in channels if isinstance(channels, list) else []:
        if not isinstance(ch, dict):
            continue
        slots = ch.get('timeSlots') or []
        items = [x for slot in slots if isinstance(slot, list) for x in slot] + [x for x in slots if isinstance(x, dict)]
        for p in items:
            if not isinstance(p, dict) or p.get('type') not in (None, 'epg'):
                continue
            info = p.get('channel') if isinstance(p.get('channel'), dict) else {}
            channel = _text(info.get('name') or ch.get('name') or ch.get('id'), 80)
            start = _stamp(p.get('broadcastedOn'))
            stop = _stamp(p.get('broadcastEnd'))
            if stop is None and start is not None and _int(p.get('duration'), 1, 86400):
                stop = start + int(p['duration'])
            show, full = _text(p.get('coreTitle') or p.get('title')), _text(p.get('title'))
            subtitle = _text(p.get('subline') or p.get('coreSubline'))
            if re.match(r'(?i)(?:moderation|mit|zu gast|gäste)\b', subtitle):
                subtitle = ''
            if show and full.lower().startswith(show.lower()) and len(full) > len(show):
                subtitle = full[len(show):].strip(' -–:(),') or subtitle      # „Tatort: Tod im Park“ -> edition title
            row = _row('ard', channel, start, stop, show, subtitle=subtitle,
                       genre=_text(p.get('genre'), 60),
                       season=_int(p.get('seasonNumber'), 0, 500), episode=_int(p.get('episodeNumber'), 0, 100000),
                       live=1 if p.get('isLive') is True else 0, repeat=1 if p.get('isRepeat') is True else 0,
                       description=_text(p.get('synopsis'), TEXT))
            if row:
                out.append(row)
    return out


def parse_zdf(data):
    out = []
    items = data.get('http://zdf.de/rels/cmdm/broadcasts') if isinstance(data, dict) else None
    for p in items if isinstance(items, list) else []:
        if not isinstance(p, dict):
            continue
        service = p.get('http://zdf.de/rels/tvservice') if isinstance(p.get('http://zdf.de/rels/tvservice'), dict) else {}
        channel = _text(service.get('tvServiceTitle') or p.get('tvService'), 80)
        start = _stamp(p.get('effectiveAirtimeBegin') or p.get('airtimeBegin'))
        stop = _stamp(p.get('effectiveAirtimeEnd') or p.get('airtimeEnd'))
        brand = _text(p.get('primaryBrand'))
        title = _text(p.get('title'))
        # „Volle Kanne - Service täglich“ with brand „Volle Kanne“: the show is the brand, the rest the edition.
        subtitle = _text(p.get('subtitle') or p.get('subheadline'))
        if brand and title.lower().startswith(brand.lower()) and title.lower() != brand.lower():
            subtitle = subtitle or title[len(brand):].strip(' -–:')
            title = brand
        row = _row('zdf', channel, start, stop, title, subtitle=subtitle, live=1 if p.get('live') is True else 0,
                   description=_text(p.get('text'), TEXT))
        if row:
            out.append(row)
    return out


# ---------------------------------------------------------------- network

def _request(url, headers=None, fetch=None):
    if fetch:
        return fetch(url, headers or {})
    import core
    with _REQUEST_LOCK:
        wait = _LAST_REQUEST[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.monotonic()
        try:
            with core.open_url(url, None, {'Accept': 'application/json', **(headers or {})}, timeout=30) as r:
                raw = r.read(MAX_ANSWER + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (400, 404):
                return None          # day outside the window of the source
            raise Unavailable('HTTP %d' % exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Unavailable('Netzwerkfehler') from None
    if len(raw) > MAX_ANSWER:
        raise Unavailable('Antwort zu groß')
    if headers and headers.get('Accept') == 'text/html':
        return raw.decode('utf-8', 'replace')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Unavailable('keine gültige Antwort') from None


def _zdf_token(fetch=None, force=False):
    """Guest token: the app token service first, the live-TV page of zdf.de as fallback (as Zapp does)."""
    with _LOCK:
        token = dict(_ZDF_TOKEN)
    if token and not force and token.get('expires', 0) > time.time() + 60:
        return token['value']
    value = ''
    try:
        data = _request(ZDF_TOKEN, fetch=fetch) or {}
        if isinstance(data, dict) and isinstance(data.get('token'), str):
            value = str(data.get('type') or 'Bearer') + ' ' + data['token']
    except Unavailable:
        value = ''
    if not value or force:
        page = _request(ZDF_PAGE, {'Accept': 'text/html'}, fetch=fetch) or ''
        m = re.search(r'apiToken["\'\s:{\\]*["\']([\w\-.]{30,})', str(page))
        if m:
            value = 'Bearer ' + m[1]
    if not value:
        raise Unavailable('ZDF: kein Gast-Token')
    try:
        import diagnostics
        diagnostics.register_secrets(value.split(' ', 1)[-1])
    except (ImportError, OSError, RuntimeError, AttributeError):
        pass
    with _LOCK:
        _ZDF_TOKEN.clear()
        _ZDF_TOKEN.update(value=value, expires=time.time() + 3600)
    return value


def fetch_day(source, day, fetch=None):
    """Broadcasts of one source and day; None when the source has no data for that day."""
    if source == 'srf':
        rows, seen = [], False
        for vendor in SRG_VENDORS:
            data = _request(SRF_URL.format(vendor=vendor, day=day), fetch=fetch)
            if data is not None:
                seen = True
                rows.extend(parse_srf(data))
        return rows if seen and rows else None
    if source == 'ard':
        data = _request(ARD_URL.format(day=day), fetch=fetch)
        return (parse_ard(data) or None) if data is not None else None
    if source == 'zdf':
        start = datetime.datetime.fromisoformat(day).replace(tzinfo=TZ)
        span = {'start': urllib.parse.quote(start.isoformat()), 'end': urllib.parse.quote((start + datetime.timedelta(days=1)).isoformat())}
        rows = []
        for service in ZDF_SERVICES:
            for page in range(1, 4):
                url = ZDF_URL.format(service=urllib.parse.quote(service), page=page, **span)
                headers = {'Accept': 'application/vnd.de.zdf.v1.0+json', 'Api-Auth': _zdf_token(fetch)}
                try:
                    data = _request(url, headers, fetch=fetch)
                except Unavailable as exc:
                    if 'HTTP 401' not in str(exc) and 'HTTP 403' not in str(exc):
                        raise
                    headers['Api-Auth'] = _zdf_token(fetch, force=True)
                    data = _request(url, headers, fetch=fetch)
                found = parse_zdf(data) if data else []
                rows.extend(found)
                if len(found) < 200:
                    break
        return rows or None
    raise ValueError('Unbekannte Quelle')


# ---------------------------------------------------------------- runs

def _day(moment):
    return datetime.datetime.fromtimestamp(moment, TZ).date()


def due_days(db, source, now):
    """Days to fetch now: yesterday … AHEAD_DAYS ahead every run (the plan changes), older days once."""
    today = _day(now)
    known = {r[0]: r[1] for r in db.execute('SELECT day,result FROM days WHERE source=?', (source,))}
    out = []
    for offset in range(-BACKFILL_DAYS, AHEAD_DAYS + 1):
        day = (today + datetime.timedelta(days=offset)).isoformat()
        if offset < -1 and day in known:
            continue                   # past day already final (or not offered by the source)
        out.append(day)
    return out


def sync(root, fetch=None, now=None):
    """One run over all sources; a broken source never stops the others."""
    now = time.time() if now is None else now
    db = connect(root)
    try:
        with db:
            _set(db, last_attempt=now, last_result='running')
        report, total, failures = {}, 0, 0
        for source in SOURCES:
            got, empty, error = 0, 0, ''
            for day in due_days(db, source, now):
                try:
                    rows = fetch_day(source, day, fetch)
                except Unavailable as exc:
                    error = str(exc)[:120]
                    break              # the source is not reachable now; next run tries again
                except Exception as exc:   # unknown answer format of one day
                    error = (exc.__class__.__name__ + ': ' + str(exc))[:120]
                    continue
                with db:
                    if rows:
                        got += store(db, rows, now)
                    else:
                        empty += 1
                    db.execute('INSERT OR REPLACE INTO days(source,day,fetched,entries,result) VALUES(?,?,?,?,?)',
                               (source, day, now, len(rows or ()), 'ok' if rows else 'empty'))
            report[source] = {'broadcasts': got, 'empty_days': empty, 'error': error}
            total += got
            failures += 1 if error else 0
        with db:
            db.execute('DELETE FROM broadcasts WHERE stop<?', (int(now - KEEP_DAYS * 86400),))
            db.execute('DELETE FROM days WHERE day<?', ((_day(now) - datetime.timedelta(days=KEEP_DAYS)).isoformat(),))
            result = 'ok' if not failures else ('partial' if failures < len(SOURCES) else 'error')
            _set(db, last_result=result, last_error='; '.join('%s: %s' % (SOURCE_NAMES[k], v['error']) for k, v in report.items() if v['error']),
                 sources=report, next_attempt=now + (REFRESH if result != 'error' else RETRY),
                 **({'last_success': now} if result != 'error' else {}))
        _notify('epg_loaded', result=result, broadcasts=total,
                **{k + '_broadcasts': v['broadcasts'] for k, v in report.items()},
                **{k + '_error': v['error'] for k, v in report.items() if v['error']})
        return {'ok': result != 'error', 'result': result, 'broadcasts': total, 'sources': report}
    finally:
        db.close()


def state(root):
    db = connect(root)
    try:
        values = {k: _value(db, k, d) for k, d in (('auto', True), ('last_attempt', 0.0), ('last_success', 0.0),
                                                   ('next_attempt', 0.0), ('last_result', 'never'), ('last_error', ''),
                                                   ('sources', {}))}
        row = db.execute('SELECT COUNT(*),MIN(start),MAX(start) FROM broadcasts').fetchone()
    finally:
        db.close()
    if values['last_result'] == 'running' and not _ACTIVE:
        values['last_result'] = 'interrupted'
    values.update(running=_ACTIVE, broadcasts=row[0] or 0, first=row[1] or 0, last=row[2] or 0)
    return values


def set_auto(root, enabled):
    if type(enabled) is not bool:
        raise ValueError('Automatik muss ausdrücklich ein- oder ausgeschaltet werden')
    db = connect(root)
    try:
        with db:
            _set(db, auto=enabled, **({'next_attempt': time.time()} if enabled else {}))
    finally:
        db.close()
    return state(root)


def should_sync(root, now=None):
    """The planner's question: first start at once, then every 6 hours while the automatic switch is on."""
    now = time.time() if now is None else now
    current = state(root)
    if current['running'] or not current['auto']:
        return False
    if current['last_result'] in ('never', 'interrupted'):
        return True
    return now >= float(current['next_attempt'] or 0)


def _run(root):
    global _ACTIVE
    try:
        sync(root)
    except Exception as exc:          # never leave the switch on
        try:
            db = connect(root)
            with db:
                _set(db, last_result='error', last_error=str(exc)[:200], next_attempt=time.time() + RETRY)
            db.close()
        except Exception:
            pass
    finally:
        with _SYNC_LOCK:
            _ACTIVE = False


def start_sync(root):
    global _ACTIVE
    with _SYNC_LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True
    threading.Thread(target=_run, args=(root,), daemon=True, name='epg_sync').start()
    return True


# ---------------------------------------------------------------- reading

def _public(row):
    keys = ('station', 'start', 'stop', 'title', 'subtitle', 'genre', 'season', 'episode', 'episodes', 'year', 'country',
            'repeat', 'live', 'source')
    return {k: row[k] for k in keys}


def now_next(root, stations=None, now=None):
    """{station key: {'now': broadcast or None, 'next': broadcast or None}} for the Live-TV tab; no network."""
    now = int(time.time() if now is None else now)
    path = Path(root) / FILE
    if not path.exists():
        return {}
    db = connect(root)
    try:
        rows = db.execute('SELECT * FROM broadcasts WHERE stop>? AND start<? ORDER BY station,start',
                          (now, now + 12 * 3600)).fetchall()
    finally:
        db.close()
    wanted = set(stations) if stations else None
    out = {}
    for row in rows:
        if wanted is not None and row['station'] not in wanted:
            continue
        slot = out.setdefault(row['station'], {'now': None, 'next': None})
        if row['start'] <= now < row['stop'] and slot['now'] is None:
            slot['now'] = _public(row)
        elif row['start'] > now and slot['next'] is None:
            slot['next'] = _public(row)
    return out


def line(entry):
    """'Jetzt: Tagesschau · danach 20:15 Tatort' for the station summary ('' when nothing is known)."""
    if not entry:
        return ''
    parts = []
    cur, nxt = entry.get('now'), entry.get('next')
    if cur:
        parts.append('Jetzt: ' + cur['title'] + (' – ' + cur['subtitle'] if cur.get('subtitle') else ''))
    if nxt:
        clock = datetime.datetime.fromtimestamp(nxt['start']).strftime('%H:%M')
        parts.append(('danach ' if cur else 'Ab ') + clock + ' ' + nxt['title'])
    return ' · '.join(parts)


def schedule(root, station, day=None, now=None):
    """Broadcasts of one station for one day (local time), for a programme view; no network."""
    now = time.time() if now is None else now
    try:
        date = datetime.date.fromisoformat(day) if day else datetime.date.fromtimestamp(now)
    except ValueError:
        raise ValueError('Ungültiges Datum') from None
    start = int(datetime.datetime.combine(date, datetime.time(5, 0)).timestamp())   # TV day starts at 5:00
    if not (Path(root) / FILE).exists():
        return []
    db = connect(root)
    try:
        rows = db.execute('SELECT * FROM broadcasts WHERE station=? AND start>=? AND start<? ORDER BY start',
                          (str(station)[:60], start, start + 86400)).fetchall()
    finally:
        db.close()
    return [_public(r) for r in rows]


def summary(root):
    """Counters for the diagnosis export; no titles."""
    current = state(root)
    return {k: current[k] for k in ('auto', 'last_result', 'last_success', 'next_attempt', 'broadcasts', 'first', 'last', 'sources')}


# ---------------------------------------------------------------- recognition evidence (Stufe 2, not wired yet)

URN = re.compile(r'urn:srf:video:[0-9a-f\-]{36}')


def kind_hint(broadcast):
    """'movie', 'show' or '' from the guide's genre; a series episode number is no film."""
    genre = str((broadcast or {}).get('genre') or '')
    if (broadcast or {}).get('episode') or (broadcast or {}).get('season'):
        return 'show'
    if SHOW_GENRES.search(genre):
        return 'show'
    if FILM_GENRES.search(genre):
        return 'movie'
    return ''


def match(db, offer, tolerance=300):
    """The broadcast a Mediathek offer belongs to, or None.

    Exact for SRF when the offer's page carries the Play SRF video id (``mediaUrn``). Otherwise the station, the start
    time (film list ``timestamp`` = Sendezeit, ± ``tolerance`` seconds) and, when both are known, a duration that fits
    (±20 %, at least 5 min) must agree; an offer that falls inside a broadcast is not enough (clips of a magazine have
    their own times). Returns {'broadcast': …, 'how': 'media'|'time'}."""
    url = ' '.join(str(offer.get(k) or '') for k in ('url_website', 'url_video'))
    found = URN.search(url)
    if found:
        row = db.execute('SELECT * FROM broadcasts WHERE media=? ORDER BY repeat,start LIMIT 1', (found[0],)).fetchone()
        if row:
            return {'broadcast': {**_public(row), 'media': row['media']}, 'how': 'media'}
    stamp = _int(offer.get('timestamp'), 1, 10 ** 11)
    station = station_key(offer.get('channel') or '')
    if not stamp or not station:
        return None
    rows = db.execute('SELECT * FROM broadcasts WHERE station=? AND start BETWEEN ? AND ? ORDER BY abs(start-?)',
                      (station, stamp - tolerance, stamp + tolerance, stamp)).fetchall()
    duration = _int(offer.get('duration'), 1, 86400)
    for row in rows:
        length = row['stop'] - row['start']
        if duration and abs(length - duration) > max(300, 0.2 * length):
            continue
        return {'broadcast': {**_public(row), 'media': row['media']}, 'how': 'time'}
    return None
