"""Lokale Filmarchive auf eigenen Ordnern und Netzwerkfreigaben (0.6.151).

Björn (26.11.2026): „Erkennung bzw. Einbinden von lokalen Filmarchiven auf Shares ermöglichen; wenn dort schon
NFO-Dateien sind, können diese gleich genutzt werden, wenn hier noch keine sind, werden sie eben gescannt und
zugeordnet.“

* Ordner (auch eingehängte SMB-/NFS-Freigaben, NAS-Pfade) stehen in ``lokal.sqlite3`` (Einstellungen → „Lokale
  Filmarchive“). Gelesen wird nur: nichts umbenennen, verschieben, löschen und keine NFO schreiben.
* Kodi-/Jellyfin-NFO (``<Datei>.nfo``, ``movie.nfo``, ``tvshow.nfo``, Folgen ``<episodedetails>``) liefern Titel, Jahr,
  IMDb-/TMDB-Kennung, Staffel/Folge, Handlung, Genres, Laufzeit und ein https-Bild. Ohne NFO: Datei- und Ordnername
  („Titel (2010)“, „Titel.2010.1080p…“, „Serie S01E02“, „Serie/Staffel 1/…“).
* Zugeordnet wird wie bei den Film-Plattformen (lokal_enrichment → portal_enrichment: IMDb offline, TVDB, TMDB …);
  der Katalog führt die Titel als eigene Quelle „Lokales Archiv“, zusammengeführt mit gleichen Titeln anderer Anbieter
  und als geladen vorn (local_titles).
* Inkrementell: unveränderte Dateien (Größe, Änderungszeit) werden nicht neu gelesen. Ist eine Freigabe nicht
  erreichbar, bleiben ihre Titel erhalten und gelten als „offline“; nur in einem erreichbaren Ordner fehlende Dateien
  gelten als entfernt (ausgeblendet, nicht gelöscht).
* Abspielen über den eigenen Player (streaming.resolve, MKV und Co. per ffmpeg umgewandelt), nur Dateien innerhalb
  der eingetragenen Ordner.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import portal_reference
import provider_base

NAME = 'Lokales Archiv'
VIDEO = frozenset({'.mkv', '.mp4', '.m4v', '.webm', '.mov', '.avi', '.ts', '.m2ts', '.mpg', '.mpeg', '.wmv', '.flv', '.divx'})
SKIP_DIR = re.compile(r'(?i)^(?:\..*|@eadir|#recycle|#snapshot|\$recycle\.bin|system volume information|lost\+found|'
                      r'extras?|featurettes?|behind the scenes|deleted scenes|trailers?|samples?)$')
# 0.6.153 (Mac-Prüfung 0.6.151: „Metropolis (1927)/sample.mkv“ als zweiter Film): auch am Namensanfang
# (nur der ganze Name „sample.mkv“, „trailer-2.mp4“ – „Trailer Park Boys S01E01“ bleibt)
SKIP_FILE = re.compile(r'(?i)(?:^\._|[-._ ](?:sample|trailer)(?:[-._ ]|$)|^(?:sample|trailer)s?(?:[-._ ]?\d+)?\.[a-z0-9]+$)')
MIN_SIZE = 20 * 1000 * 1000            # kleinere Dateien sind Vorschauen/Beispiele
NFO_MAX = 1024 * 1024
VALID_ID = re.compile(r'^[fes][0-9a-f]{20}$')
RESCAN = 6 * 3600                       # Freigaben alle 6 Stunden auf Änderungen prüfen
MAX_DIRS = 20
SCHEMA = '''
CREATE TABLE IF NOT EXISTS lokal_items(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, year INTEGER, duration INTEGER,
  genre TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', poster TEXT NOT NULL DEFAULT '',
  series_id TEXT, season INTEGER, episode INTEGER, imdb_id TEXT NOT NULL DEFAULT '', tmdb_id TEXT NOT NULL DEFAULT '',
  nfo INTEGER NOT NULL DEFAULT 0, path TEXT, folder TEXT NOT NULL DEFAULT '', size INTEGER, mtime REAL,
  state TEXT NOT NULL DEFAULT 'ok', seen REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS lokal_items_kind ON lokal_items(kind, state);
CREATE INDEX IF NOT EXISTS lokal_items_series ON lokal_items(series_id);
CREATE INDEX IF NOT EXISTS lokal_items_folder ON lokal_items(folder);
CREATE TABLE IF NOT EXISTS lokal_state(name TEXT PRIMARY KEY, value TEXT);
'''
_ACTIVE = False
_SYNC_LOCK = threading.Lock()


def _connect(root):
    db = provider_base.connect(root, 'lokal.sqlite3', private=True)
    db.executescript(SCHEMA)
    return db


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM lokal_state WHERE name=?', (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute('INSERT INTO lokal_state(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (key, str(value)))


def _hash(prefix, text):
    return prefix + hashlib.sha1(text.encode('utf-8', 'surrogateescape')).hexdigest()[:20]


# ------------------------------------------------------------------ Ordner

def clean_dirs(values):
    """Absolute Ordner, ohne Laufwerkswurzel, ohne Doppelte; Text (eine Zeile je Ordner) oder Liste."""
    if isinstance(values, str):
        values = values.splitlines()
    out = []
    for value in list(values or [])[:MAX_DIRS * 2]:
        text = str(value or '').strip()
        if not text:
            continue
        p = Path(text).expanduser()
        if not p.is_absolute():
            raise ValueError('Bitte absolute Pfade angeben (z. B. /Volumes/Filme)')
        if p == Path(p.anchor):
            raise ValueError('Ein ganzes Laufwerk („%s“) bitte nicht – den Ordner mit den Filmen angeben' % text)
        text = str(p)
        if text not in out:
            out.append(text)
    return out[:MAX_DIRS]


def dirs(root):
    db = _connect(root)
    try:
        try:
            value = json.loads(_get(db, 'dirs', '[]'))
        except ValueError:
            value = []
        return [str(v) for v in value if isinstance(v, str)]
    finally:
        db.close()


def set_dirs(root, values):
    """Ordner speichern; ein entfernter Ordner nimmt seine Titel aus dem Katalog (Dateien bleiben unberührt)."""
    new = clean_dirs(values)
    db = _connect(root)
    try:
        with db:
            _set(db, 'dirs', json.dumps(new))
            gone = [r[0] for r in db.execute('SELECT DISTINCT folder FROM lokal_items') if r[0] not in new]
            for folder in gone:
                db.execute('DELETE FROM lokal_items WHERE folder=?', (folder,))
            _set(db, 'next_attempt', 0)
    finally:
        db.close()
    return new


def allowed(path, folders):
    """Liegt die Datei (aufgelöst) in einem der Ordner? Symbolische Verweise nach draußen zählen nicht."""
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    for folder in folders:
        try:
            base = os.path.realpath(folder)
            if os.path.commonpath((real, base)) == base:
                return True
        except (OSError, ValueError):
            continue
    return False


# ------------------------------------------------------------------ Namen und NFO

TAGS = re.compile(r'(?i)[ ._\-\[\(](?:2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr|hdr10|dv|bluray|blu-ray|bdrip|brrip|'
                  r'web-?dl|web-?rip|webrip|hdtv|dvdrip|dvd|remux|x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|'
                  r'truehd|atmos|german|deutsch|dl|ml|multi|subbed|uncut|extended|directors\.?cut|proper|repack|'
                  r'internal|complete)(?=$|[ ._\-\]\)])')
YEAR = re.compile(r'(?:^|[ ._\-\(\[])((?:19[2-9]|20[0-4])\d)(?=$|[ ._\-\)\]])')
EPISODE = re.compile(r'(?i)(?:^|[ ._\-])s(\d{1,2})[ ._\-]?e(\d{1,3})|(?:^|[ ._\-])(\d{1,2})x(\d{2,3})(?=$|[ ._\-])')
SEASON_DIR = re.compile(r'(?i)^(?:season|staffel|series|serie)[ ._\-]*(\d{1,2})$|^s(\d{1,2})$')
IMDB = re.compile(r'\b(tt\d{7,10})\b')


def _words(text):
    text = re.sub(r'[._]+', ' ', str(text or ''))
    return re.sub(r'\s+', ' ', text).strip(' -–[]()')


def parse_name(path):
    """Titel, Jahr und (Folge) aus Datei- und Ordnernamen, ohne Netz."""
    p = Path(path)
    stem = p.stem
    ep = EPISODE.search(stem)
    if ep:
        season = int(ep.group(1) or ep.group(3))
        episode = int(ep.group(2) or ep.group(4))
        show = _words(stem[:ep.start()])
        rest = _words(TAGS.split(stem[ep.end():])[0])
        parent = p.parent
        if not show or SEASON_DIR.match(parent.name):
            if SEASON_DIR.match(parent.name):
                parent = parent.parent
            show = show or _words(parent.name)
        year = YEAR.search(show)
        if year:
            show = _words(show[:year.start()]) or show
        return {'kind': 'episode', 'show': show, 'season': season, 'episode': episode, 'title': rest,
                'year': int(year.group(1)) if year else None}
    for name in (stem, p.parent.name):
        cut = TAGS.search(name)
        head = name[:cut.start()] if cut else name
        year = None
        for y in YEAR.finditer(head):
            year = y
        if year and year.start() > 0:
            return {'kind': 'movie', 'title': _words(head[:year.start()]), 'year': int(year.group(1))}
    cut = TAGS.search(stem)
    return {'kind': 'movie', 'title': _words(stem[:cut.start()] if cut else stem), 'year': None}


def _text(node, tag):
    found = node.find(tag)
    return (found.text or '').strip() if found is not None and found.text else ''


def read_nfo(path):
    """Kodi-/Jellyfin-NFO lesen; {} bei Fehler. Reiner URL-Text: nur die IMDb-Kennung."""
    try:
        if os.path.getsize(path) > NFO_MAX:
            return {}
        raw = Path(path).read_bytes()
    except OSError:
        return {}
    text = raw.decode('utf-8', 'replace')
    start = text.find('<')
    if start < 0 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        m = IMDB.search(text)
        return {'imdb_id': m.group(1)} if m else {}
    try:
        node = ET.fromstring(text[start:].strip())
    except ET.ParseError:
        m = IMDB.search(text)
        return {'imdb_id': m.group(1)} if m else {}
    out = {'tag': node.tag.lower()}
    for key in ('title', 'originaltitle', 'showtitle', 'plot', 'outline'):
        if _text(node, key):
            out[key] = _text(node, key)
    for key in ('year', 'season', 'episode', 'runtime'):
        value = _text(node, key)
        if value.isdigit():
            out[key] = int(value)
    if 'year' not in out:
        m = re.match(r'((?:19|20)\d\d)', _text(node, 'premiered') or _text(node, 'aired'))
        if m:
            out['year'] = int(m.group(1))
    genres = [(g.text or '').strip() for g in node.findall('genre') if g.text and g.text.strip()]
    if genres:
        out['genres'] = genres[:10]
    for uid in node.findall('uniqueid'):
        kind = (uid.get('type') or '').lower()
        value = (uid.text or '').strip()
        if kind == 'imdb' and IMDB.fullmatch(value):
            out['imdb_id'] = value
        elif kind in ('tmdb', 'themoviedb') and value.isdigit():
            out['tmdb_id'] = value
    for key in ('imdbid', 'imdb_id', 'id'):
        value = _text(node, key)
        if 'imdb_id' not in out and IMDB.fullmatch(value):
            out['imdb_id'] = value
    if 'tmdb_id' not in out and _text(node, 'tmdbid').isdigit():
        out['tmdb_id'] = _text(node, 'tmdbid')
    for thumb in node.findall('thumb'):
        url = (thumb.text or '').strip()
        if url.startswith('https://') and (thumb.get('aspect') in (None, '', 'poster')):
            out['poster'] = url[:600]
            break
    seconds = node.find('fileinfo/streamdetails/video/durationinseconds')
    if seconds is not None and (seconds.text or '').strip().isdigit():
        out['seconds'] = int(seconds.text.strip())
    return out


def _nfo_for(path, names):
    p = Path(path)
    for candidate in [p.with_suffix('.nfo')] + [p.parent / n for n in names]:
        if candidate.is_file():
            return candidate
    return None


def _show_nfo(path):
    p = Path(path).parent
    for folder in (p, p.parent):
        candidate = folder / 'tvshow.nfo'
        if candidate.is_file():
            return candidate
    return None


def describe(path, single_in_folder=True):
    """Alles Bekannte zu einer Videodatei: NFO zuerst, sonst der Name."""
    guess = parse_name(path)
    nfo_path = _nfo_for(path, ('movie.nfo',) if single_in_folder else ())
    nfo = read_nfo(nfo_path) if nfo_path else {}
    if nfo.get('tag') == 'episodedetails' or (guess['kind'] == 'episode' and nfo.get('tag') != 'movie'):
        show_nfo = _show_nfo(path)
        show = read_nfo(show_nfo) if show_nfo else {}
        out = {'kind': 'episode', 'show': show.get('title') or nfo.get('showtitle') or guess.get('show') or _words(Path(path).parent.name),
               'show_year': show.get('year') or guess.get('year'), 'show_imdb': show.get('imdb_id', ''),
               'show_genres': show.get('genres') or [], 'show_plot': show.get('plot', ''), 'show_poster': show.get('poster', ''),
               'season': nfo.get('season', guess.get('season')), 'episode': nfo.get('episode', guess.get('episode')),
               'title': nfo.get('title') or guess.get('title') or '', 'summary': nfo.get('plot', ''),
               'duration': nfo.get('seconds') or (nfo.get('runtime', 0) * 60) or None, 'nfo': bool(nfo or show)}
        return out
    return {'kind': 'movie', 'title': nfo.get('title') or guess['title'] or Path(path).stem,
            'year': nfo.get('year') or guess.get('year'), 'imdb_id': nfo.get('imdb_id', ''), 'tmdb_id': nfo.get('tmdb_id', ''),
            'genres': nfo.get('genres') or [], 'summary': nfo.get('plot') or nfo.get('outline', ''),
            'poster': nfo.get('poster', ''), 'duration': nfo.get('seconds') or (nfo.get('runtime', 0) * 60) or None,
            'nfo': bool(nfo)}


# ------------------------------------------------------------------ Einlesen

def walk(folder, deadline=None, stats=None):
    """Videodateien unterhalb des Ordners: [(Pfad, Größe, Änderungszeit, Videos im selben Ordner)].
    Folgt keinen symbolisch verknüpften Ordnern, überspringt Papierkörbe, Extras und Beispiele.
    ``stats['small']``: übergangene Videos unter MIN_SIZE (0.6.153: in der Oberfläche genannt)."""
    out, stack = [], [folder]
    while stack:
        if deadline and time.monotonic() > deadline:
            raise TimeoutError('Zeitbudget')
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        videos = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not SKIP_DIR.match(entry.name):
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False) and os.path.splitext(entry.name)[1].lower() in VIDEO \
                        and not SKIP_FILE.search(entry.name):
                    st = entry.stat(follow_symlinks=False)
                    if st.st_size >= MIN_SIZE:
                        videos.append((entry.path, st.st_size, st.st_mtime))
                    elif stats is not None:
                        stats['small'] = stats.get('small', 0) + 1
            except OSError:
                continue
        out += [(p, s, m, len(videos)) for p, s, m in videos]
    return out


def _reachable(folder):
    """Ordner da und lesbar (eine abgemeldete Freigabe: Einhängepunkt fehlt oder ist leer und nicht lesbar)."""
    try:
        os.listdir(folder)
        return os.path.isdir(folder)
    except OSError:
        return False


def scan(root, now=None, seconds=1800.0, describe_fn=None):
    """Alle Ordner einlesen (inkrementell). Gibt eine Zusammenfassung je Ordner zurück."""
    now = time.time() if now is None else now
    describe_fn = describe_fn or describe
    started = time.monotonic()
    deadline = started + seconds
    summary = []
    for folder in dirs(root):
        entry = {'folder': folder, 'reachable': _reachable(folder), 'new': 0, 'changed': 0, 'gone': 0, 'files': 0}
        db = _connect(root)
        try:
            if not entry['reachable']:
                with db:
                    entry['offline'] = db.execute("UPDATE lokal_items SET state='offline' WHERE folder=? AND state='ok'",
                                                  (folder,)).rowcount
                summary.append(entry)
                continue
            try:
                small = {}
                files = walk(folder, deadline, small)
                entry['small'] = small.get('small', 0)
            except TimeoutError:
                entry['incomplete'] = True
                summary.append(entry)
                continue
            known = {r['path']: dict(r) for r in db.execute(
                "SELECT id,path,size,mtime,state FROM lokal_items WHERE folder=? AND kind IN ('movie','episode')", (folder,))}
            if not files and any(r['state'] != 'gone' for r in known.values()):
                # Leerer Einhängepunkt (Freigabe auf Linux/NAS nicht eingehängt): nichts als gelöscht werten, nur offline
                entry['reachable'] = False
                with db:
                    entry['offline'] = db.execute("UPDATE lokal_items SET state='offline' WHERE folder=? AND state='ok'",
                                                  (folder,)).rowcount
                summary.append(entry)
                continue
        finally:
            db.close()
        rows, touched = [], []
        for path, size, mtime, siblings in files:
            entry['files'] += 1
            old = known.pop(path, None)
            if old and old['size'] == size and abs((old['mtime'] or 0) - mtime) < 1:
                touched.append(old['id'])
                continue
            try:
                info = describe_fn(path, siblings == 1)
            except Exception:
                continue
            rows.append((path, size, mtime, info))
            entry['changed' if old else 'new'] += 1
        db = _connect(root)
        try:
            with db:
                for i in range(0, len(touched), 500):
                    part = touched[i:i + 500]
                    db.execute("UPDATE lokal_items SET seen=?, state='ok' WHERE id IN (%s)" % ','.join('?' * len(part)), [now] + part)
                for path, size, mtime, info in rows:
                    _store(db, folder, path, size, mtime, info, now)
                for old in known.values():
                    if old['state'] != 'gone':
                        db.execute("UPDATE lokal_items SET state='gone' WHERE id=?", (old['id'],))
                        entry['gone'] += 1
                _series(db, folder, now)
        finally:
            db.close()
        summary.append(entry)
    db = _connect(root)
    try:
        with db:
            if all(e['reachable'] and not e.get('incomplete') for e in summary):
                _set(db, 'last_success', now)
            _set(db, 'last_attempt', now)
            _set(db, 'next_attempt', now + RESCAN)
            _set(db, 'last_result', 'ok' if summary and all(e['reachable'] for e in summary) else ('partial' if summary else 'empty'))
            _set(db, 'last_summary', json.dumps(summary))
    finally:
        db.close()
    try:
        import diagnostics
        diagnostics.event('lokal_scan', folders=len(summary), files=sum(e['files'] for e in summary),
                          new=sum(e['new'] for e in summary), changed=sum(e['changed'] for e in summary),
                          gone=sum(e['gone'] for e in summary), offline=sum(1 for e in summary if not e['reachable']),
                          incomplete=sum(1 for e in summary if e.get('incomplete')),
                          small=sum(e.get('small', 0) for e in summary), seconds=round(time.monotonic() - started, 2))
    except Exception:
        pass
    return summary


def _store(db, folder, path, size, mtime, info, now):
    if info['kind'] == 'episode':
        show = info['show'] or 'Unbekannte Serie'
        series_id = _hash('s', folder + '\x00' + show.casefold())
        title = info['title'] or ('Folge %s' % info['episode'] if info.get('episode') is not None else Path(path).stem)
        db.execute('''INSERT INTO lokal_items(id,kind,title,year,duration,genre,summary,poster,series_id,season,episode,imdb_id,
            tmdb_id,nfo,path,folder,size,mtime,state,seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ok',?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,title=excluded.title,duration=excluded.duration,summary=excluded.summary,
            series_id=excluded.series_id,season=excluded.season,episode=excluded.episode,nfo=excluded.nfo,size=excluded.size,
            mtime=excluded.mtime,state='ok',seen=excluded.seen''',
                   (_hash('e', path), 'episode', title[:240], None, info.get('duration'), '', info.get('summary', '')[:4000], '',
                    series_id, info.get('season'), info.get('episode'), '', '', int(info.get('nfo', False)), path, folder,
                    size, mtime, now))
        # Angaben der Serie (tvshow.nfo) merken; _series legt die Serienzeile an
        db.execute('''INSERT INTO lokal_items(id,kind,title,year,genre,summary,poster,imdb_id,nfo,folder,state,seen)
            VALUES(?,'series',?,?,?,?,?,?,?,?,'ok',?) ON CONFLICT(id) DO UPDATE SET
            year=COALESCE(excluded.year,lokal_items.year),
            genre=CASE WHEN excluded.genre!='' THEN excluded.genre ELSE lokal_items.genre END,
            summary=CASE WHEN excluded.summary!='' THEN excluded.summary ELSE lokal_items.summary END,
            poster=CASE WHEN excluded.poster!='' THEN excluded.poster ELSE lokal_items.poster END,
            imdb_id=CASE WHEN excluded.imdb_id!='' THEN excluded.imdb_id ELSE lokal_items.imdb_id END,
            nfo=MAX(excluded.nfo,lokal_items.nfo),seen=excluded.seen''',
                   (series_id, show[:240], info.get('show_year'), ', '.join(info.get('show_genres') or []),
                    info.get('show_plot', '')[:4000], info.get('show_poster', ''), info.get('show_imdb', ''),
                    int(bool(info.get('show_imdb') or info.get('show_genres'))), folder, now))
        return
    db.execute('''INSERT INTO lokal_items(id,kind,title,year,duration,genre,summary,poster,imdb_id,tmdb_id,nfo,path,folder,size,
        mtime,state,seen) VALUES(?,'movie',?,?,?,?,?,?,?,?,?,?,?,?,?,'ok',?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
        year=excluded.year,duration=excluded.duration,genre=excluded.genre,summary=excluded.summary,poster=excluded.poster,
        imdb_id=excluded.imdb_id,tmdb_id=excluded.tmdb_id,nfo=excluded.nfo,size=excluded.size,mtime=excluded.mtime,
        state='ok',seen=excluded.seen''',
               (_hash('f', path), info['title'][:240], info.get('year'), info.get('duration'), ', '.join(info.get('genres') or []),
                info.get('summary', '')[:4000], info.get('poster', ''), info.get('imdb_id', ''), info.get('tmdb_id', ''),
                int(info.get('nfo', False)), path, folder, size, mtime, now))


def _series(db, folder, now):
    """Serienzeilen: erreichbar, solange eine Folge da ist; ohne Folge ausgeblendet."""
    db.execute("""UPDATE lokal_items SET state=CASE WHEN EXISTS(SELECT 1 FROM lokal_items e WHERE e.series_id=lokal_items.id
        AND e.state='ok') THEN 'ok' WHEN EXISTS(SELECT 1 FROM lokal_items e WHERE e.series_id=lokal_items.id AND e.state='offline')
        THEN 'offline' ELSE 'gone' END, seen=CASE WHEN EXISTS(SELECT 1 FROM lokal_items e WHERE e.series_id=lokal_items.id
        AND e.state='ok') THEN ? ELSE seen END WHERE kind='series' AND folder=?""", (now, folder))


# ------------------------------------------------------------------ Katalog (Schnittstelle wie die Film-Plattformen)

def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _summary(root, row, reports=None):
    import lokal_enrichment
    report = (reports if reports is not None else lokal_enrichment.all_cached(root)).get(row['id'])
    # NFO mit IMDb-Nummer (Kodi/Jellyfin-Scraper): ihre Genres gelten wie bei JustWatch als eingeordnet
    return portal_reference.summary(row.get('genre'), report, identified=bool(row.get('imdb_id')), age=None)


def _public(row):
    row = dict(row)
    row['playable'] = 1 if row['kind'] in ('movie', 'episode') and row['state'] == 'ok' else 0
    row['offline_share'] = row['state'] == 'offline'
    row['local'] = True
    row.pop('path', None)
    if row.get('imdb_id') and not IMDB.fullmatch(row['imdb_id']):
        row['imdb_id'] = ''
    return row


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    kind = 'series' if view == 'series' else 'movie'
    offset = max(0, min(_int(offset, 0) or 0, 1000000))
    limit = 1000000 if limit == 'all' else max(1, min(_int(limit, 60) or 60, 200))
    db = _connect(root)
    try:
        sql = "SELECT * FROM lokal_items WHERE kind=? AND state IN ('ok','offline')"
        args = [kind]
        if query:
            sql += ' AND (title LIKE ? OR genre LIKE ?)'
            like = '%' + str(query)[:100] + '%'
            args += [like, like]
        rows = [_public(r) for r in db.execute(sql + ' ORDER BY title COLLATE NOCASE', args)]
        if kind == 'series' and rows:
            counts = dict(db.execute("SELECT series_id, COUNT(*) FROM lokal_items WHERE kind='episode' AND state IN ('ok','offline') "
                                     "GROUP BY series_id"))
            for r in rows:
                r['episode_count'] = counts.get(r['id'], 0)
            rows = [r for r in rows if r['episode_count']]
    finally:
        db.close()
    import lokal_enrichment
    reports = lokal_enrichment.all_cached(root)
    for row in rows:
        row.update(_summary(root, row, reports))
    counts = portal_reference.facets(rows)
    rows = [r for r in rows if portal_reference.matches(r, genre) and portal_reference.in_collection(r, collection, kind)]
    if sort == 'year':
        rows.sort(key=lambda r: (-(r.get('year') or 0), r['title'].casefold()))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'view': view, 'genre_counts': counts}


def _row(db, item_id):
    row = db.execute('SELECT * FROM lokal_items WHERE id=?', (item_id,)).fetchone()
    return dict(row) if row else None


def item(root, item_id):
    import lokal_enrichment
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Titel im lokalen Archiv')
    db = _connect(root)
    try:
        row = _row(db, item_id)
        if not row or row['state'] == 'gone':
            raise ValueError('Titel nicht (mehr) im lokalen Archiv; Ordner neu einlesen')
        parent = _row(db, row['series_id']) if row.get('series_id') else None
    finally:
        db.close()
    report = lokal_enrichment.cached(root, item_id)
    base = parent if row['kind'] == 'episode' and parent else row
    summary = _summary(root, base, {base['id']: report})
    public = _public(row)
    if row['state'] == 'offline':
        public['notes'] = ['Freigabe gerade nicht erreichbar: %s' % row['folder']]
    return {'item': {**public, **summary, 'poster': row.get('poster') or (parent or {}).get('poster') or ''},
            'series': _public(parent) if parent else None, 'reference': report}


def episodes(root, series_id):
    if not VALID_ID.fullmatch(str(series_id or '')):
        raise ValueError('Ungültige Serie im lokalen Archiv')
    db = _connect(root)
    try:
        rows = [_public(r) for r in db.execute(
            "SELECT * FROM lokal_items WHERE series_id=? AND kind='episode' AND state IN ('ok','offline') "
            "ORDER BY season, episode, title", (series_id,))]
    finally:
        db.close()
    return {'items': rows}


def play_source(root, item_id):
    """Datei zum Abspielen (streaming.resolve); nur innerhalb der eingetragenen Ordner und erreichbar."""
    if not VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Titel im lokalen Archiv')
    db = _connect(root)
    try:
        row = _row(db, item_id)
    finally:
        db.close()
    if not row or row['kind'] not in ('movie', 'episode') or row['state'] == 'gone':
        raise ValueError('Titel nicht im lokalen Archiv')
    path = row['path'] or ''
    if not allowed(path, dirs(root)):
        raise ValueError('Datei liegt nicht in einem eingetragenen Archivordner')
    if not os.path.isfile(path):
        raise ValueError('Freigabe nicht erreichbar oder Datei verschoben: %s' % row['folder'])
    title = row['title'] + (' (%s)' % row['year'] if row.get('year') else '')
    return {'kind': 'file', 'path': path, 'title': title, 'duration': row.get('duration') or 0, 'provider': 'lokal'}


def ids(root):
    """Kennungen aller abspielbaren Titel (Filme, Folgen, Serien mit Folgen) – für „geladen zuerst“."""
    db = _connect(root)
    try:
        return {r[0] for r in db.execute("SELECT id FROM lokal_items WHERE state IN ('ok','offline')")}
    finally:
        db.close()


# ------------------------------------------------------------------ Planer (wie die Plattform-Kataloge)

def state(root):
    db = _connect(root)
    try:
        try:
            summary = json.loads(_get(db, 'last_summary', '[]'))
        except ValueError:
            summary = []
        counts = dict(db.execute("SELECT kind, COUNT(*) FROM lokal_items WHERE state IN ('ok','offline') GROUP BY kind"))
        nfo = db.execute("SELECT COUNT(*) FROM lokal_items WHERE kind IN ('movie','episode') AND nfo=1 AND state IN ('ok','offline')").fetchone()[0]
        offline = db.execute("SELECT COUNT(*) FROM lokal_items WHERE kind IN ('movie','episode') AND state='offline'").fetchone()[0]
        return {'running': _ACTIVE, 'auto': True, 'dirs': dirs(root),
                'last_attempt': float(_get(db, 'last_attempt', '0') or 0), 'last_success': float(_get(db, 'last_success', '0') or 0),
                'next_attempt': float(_get(db, 'next_attempt', '0') or 0), 'last_result': _get(db, 'last_result', 'never'),
                'last_error': _get(db, 'last_error'), 'folders': summary,
                'movies': counts.get('movie', 0), 'series': counts.get('series', 0), 'episodes': counts.get('episode', 0),
                'with_nfo': nfo, 'offline': offline}
    finally:
        db.close()


def should_sync(root, now=None):
    now = time.time() if now is None else now
    if _ACTIVE:
        return False
    s = state(root)
    return bool(s['dirs']) and now >= s['next_attempt']


def _run(root):
    global _ACTIVE
    try:
        scan(root)
    except Exception as exc:
        db = _connect(root)
        try:
            with db:
                _set(db, 'last_error', str(exc)[:200]);_set(db, 'next_attempt', time.time() + 600)
        finally:
            db.close()
    finally:
        with _SYNC_LOCK:
            _ACTIVE = False
        try:
            import unified_index
            import local_titles
            local_titles.invalidate();unified_index.invalidate(soft=True)
        except Exception:
            pass


def start_sync(root):
    global _ACTIVE
    with _SYNC_LOCK:
        if _ACTIVE:
            return False
        _ACTIVE = True
    threading.Thread(target=_run, args=(root,), daemon=True, name='lokal_scan').start()
    return True


MODULE = sys.modules[__name__]
