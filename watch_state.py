"""Merkliste, Anheften und Abspielstand je Titel, auf dem Server gespeichert (0.5.81).

Taken over from HomeTube (hometube/catalog.py: favorite, pinned, last watched). Until now the
playback position lived only in the browser's localStorage, so another browser or device started
every title from the beginning, and nothing on the server knew what had been watched. The storage
overview (storage_policy.py) needs exactly that to protect titles.

One small SQLite file ``watch.sqlite3`` next to the other databases. A row is addressed by the
player's key: ``<plattform>:<id>`` for the film platforms, ``job:<id>`` for a finished download
and the work id for ARD, ZDF & Co. Live channels have no position and are not stored.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DB_NAME = 'watch.sqlite3'
KEY = re.compile(r'^[A-Za-z0-9_.:\-]{1,200}$')
# What the player may be asked to open again: the same references /api/play accepts.
REF_KEYS = ('offer', 'job', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'joyn', 'youtube')
SOURCES = ('mediatheken', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'joyn', 'youtube', 'download')
KINDS = ('movie', 'series', 'episode', 'music')
MIN_POSITION = 20      # seconds; below that a title does not count as started (as in the player)
END_MARGIN = 45        # seconds before the end that count as "watched to the end"
MAX_CONTINUE = 24
MAX_MARKED = 500
MAX_PROGRESS = 3000    # newest positions handed to a browser for "Fortsetzen"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
 key TEXT PRIMARY KEY,
 title TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT '',
 year INTEGER,
 poster TEXT NOT NULL DEFAULT '',
 ref TEXT NOT NULL DEFAULT '{}',
 open TEXT NOT NULL DEFAULT '{}',
 pos REAL NOT NULL DEFAULT 0,
 duration REAL NOT NULL DEFAULT 0,
 done INTEGER NOT NULL DEFAULT 0,
 watched_at REAL NOT NULL DEFAULT 0,
 favorite INTEGER NOT NULL DEFAULT 0,
 pinned INTEGER NOT NULL DEFAULT 0,
 marked_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS entries_watched ON entries(watched_at);
CREATE INDEX IF NOT EXISTS entries_marked ON entries(favorite, marked_at);
"""

_LOCK = threading.Lock()
_READY: set[str] = set()


@contextmanager
def _db(root):
    path = Path(root) / DB_NAME
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with _LOCK:
            if str(path) not in _READY:
                c.execute('PRAGMA journal_mode=WAL')
                c.executescript(SCHEMA)
                _READY.add(str(path))
        with c:
            yield c
    finally:
        c.close()


def valid_key(key):
    key = str(key or '')
    if not KEY.fullmatch(key) or key.startswith('live:'):
        raise ValueError('Ungültiger Titelschlüssel')
    return key


def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _number(value, top=10 ** 7):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if 0 <= number <= top else 0.0   # NaN fails both comparisons


def _poster(value):
    value = str(value or '')
    return value if len(value) <= 600 and re.fullmatch(r'https://[A-Za-z0-9.\-]+/[^\s<>"\']*', value) else ''


def clean_ref(ref):
    """Only the reference fields the player knows, as short strings."""
    out = {}
    if isinstance(ref, dict):
        for name in REF_KEYS:
            value = ref.get(name)
            if isinstance(value, (str, int)) and str(value) and len(str(value)) <= 200:
                out[name] = str(value)
    return out


def clean_open(value):
    """How the title page is opened again from the Merkliste (ids only, no addresses)."""
    out = {}
    if isinstance(value, dict):
        for name in ('id', 'series_key', 'show_key', 'work_id'):
            item = value.get(name)
            if isinstance(item, (str, int)) and str(item) and len(str(item)) <= 300:
                out[name] = str(item)
        if value.get('series_parent') is True:
            out['series_parent'] = True
    return out


def _describe(info):
    info = info if isinstance(info, dict) else {}
    try:
        year = int(info.get('year'))
        year = year if 1880 <= year <= 2100 else None
    except (TypeError, ValueError):
        year = None
    return {'title': _text(info.get('title'), 300),
            'source': info.get('source') if info.get('source') in SOURCES else '',
            'kind': info.get('kind') if info.get('kind') in KINDS else '',
            'year': year, 'poster': _poster(info.get('poster')),
            'ref': clean_ref(info.get('ref')), 'open': clean_open(info.get('open'))}


def _upsert_description(c, key, d):
    """Fill or refresh the describing fields; an empty value never overwrites a known one."""
    c.execute('INSERT OR IGNORE INTO entries(key) VALUES(?)', (key,))
    c.execute("""UPDATE entries SET
        title=CASE WHEN ?<>'' THEN ? ELSE title END,
        source=CASE WHEN ?<>'' THEN ? ELSE source END,
        kind=CASE WHEN ?<>'' THEN ? ELSE kind END,
        year=COALESCE(?,year),
        poster=CASE WHEN ?<>'' THEN ? ELSE poster END,
        ref=CASE WHEN ?<>'{}' THEN ? ELSE ref END,
        open=CASE WHEN ?<>'{}' THEN ? ELSE open END
        WHERE key=?""",
              (d['title'], d['title'], d['source'], d['source'], d['kind'], d['kind'], d['year'],
               d['poster'], d['poster'], json.dumps(d['ref']), json.dumps(d['ref']),
               json.dumps(d['open']), json.dumps(d['open']), key))


def progress(root, key, pos=0, duration=0, done=False, info=None, now=None):
    """The player reports where a title stands. ``done`` or the last 45 seconds finish it."""
    key = valid_key(key)
    pos, duration = _number(pos), _number(duration)
    finished = bool(done) or bool(duration and pos > duration - END_MARGIN)
    if not finished and pos <= MIN_POSITION:
        return {'ok': True, 'stored': False}
    now = time.time() if now is None else float(now)
    with _db(root) as c:
        _upsert_description(c, key, _describe(info))
        c.execute('UPDATE entries SET pos=?,duration=CASE WHEN ?>0 THEN ? ELSE duration END,done=?,watched_at=? WHERE key=?',
                  (0 if finished else pos, duration, duration, int(finished), now, key))
    return {'ok': True, 'stored': True, 'done': finished}


def mark(root, key, favorite=None, pinned=None, info=None, now=None):
    """Merkliste (favorite) and Anheften (pinned: never suggested for deletion)."""
    key = valid_key(key)
    now = time.time() if now is None else float(now)
    with _db(root) as c:
        _upsert_description(c, key, _describe(info))
        if favorite is not None:
            c.execute('UPDATE entries SET favorite=?,marked_at=? WHERE key=?', (int(bool(favorite)), now, key))
        if pinned is not None:
            c.execute('UPDATE entries SET pinned=? WHERE key=?', (int(bool(pinned)), key))
        row = c.execute('SELECT favorite,pinned FROM entries WHERE key=?', (key,)).fetchone()
        _prune(c, key)
    return {'ok': True, 'favorite': bool(row['favorite']), 'pinned': bool(row['pinned'])}


def forget(root, key):
    """Remove the playback position ("Von vorn", "Aus Weiterschauen entfernen"); marks stay."""
    key = valid_key(key)
    with _db(root) as c:
        c.execute('UPDATE entries SET pos=0,done=0,watched_at=0 WHERE key=?', (key,))
        _prune(c, key)
    return {'ok': True}


def _prune(c, key):
    c.execute('DELETE FROM entries WHERE key=? AND favorite=0 AND pinned=0 AND watched_at=0', (key,))


def _public(row):
    return {'key': row['key'], 'title': row['title'] or 'Ohne Titel', 'source': row['source'], 'kind': row['kind'],
            'year': row['year'], 'poster': row['poster'], 'ref': json.loads(row['ref'] or '{}'),
            'open': json.loads(row['open'] or '{}'), 'pos': round(row['pos'], 1), 'duration': round(row['duration'], 1),
            'done': bool(row['done']), 'watched_at': row['watched_at'], 'favorite': bool(row['favorite']),
            'pinned': bool(row['pinned']), 'marked_at': row['marked_at']}


def overview(root):
    """Everything a page needs at its start: Weiterschauen, Merkliste, positions and marks by key."""
    with _db(root) as c:
        started = c.execute('SELECT * FROM entries WHERE done=0 AND pos>? ORDER BY watched_at DESC LIMIT ?',
                            (MIN_POSITION, MAX_CONTINUE)).fetchall()
        marked = c.execute('SELECT * FROM entries WHERE favorite=1 ORDER BY marked_at DESC LIMIT ?', (MAX_MARKED,)).fetchall()
        recent = c.execute('SELECT key,pos,done,watched_at FROM entries WHERE watched_at>0 ORDER BY watched_at DESC LIMIT ?',
                           (MAX_PROGRESS,)).fetchall()
        flags = c.execute('SELECT key,favorite,pinned FROM entries WHERE favorite=1 OR pinned=1').fetchall()
    return {'continue': [_public(r) for r in started], 'marked': [_public(r) for r in marked],
            'progress': {r['key']: {'pos': round(r['pos'], 1), 'done': bool(r['done']), 'at': int(r['watched_at'] * 1000)} for r in recent},
            'marks': {r['key']: {'favorite': bool(r['favorite']), 'pinned': bool(r['pinned'])} for r in flags}}


def states(root):
    """key -> {favorite, pinned, done, watched_at} for the storage overview."""
    with _db(root) as c:
        rows = c.execute('SELECT key,favorite,pinned,done,watched_at FROM entries').fetchall()
    return {r['key']: {'favorite': bool(r['favorite']), 'pinned': bool(r['pinned']), 'done': bool(r['done']),
                       'watched_at': r['watched_at']} for r in rows}


def summary(root):
    """Counts for the diagnosis export (no titles)."""
    with _db(root) as c:
        r = c.execute('SELECT COUNT(*),SUM(favorite),SUM(pinned),SUM(done),SUM(CASE WHEN done=0 AND pos>? THEN 1 ELSE 0 END) FROM entries',
                      (MIN_POSITION,)).fetchone()
    return {'entries': r[0] or 0, 'favorites': r[1] or 0, 'pinned': r[2] or 0, 'finished': r[3] or 0, 'started': r[4] or 0}
