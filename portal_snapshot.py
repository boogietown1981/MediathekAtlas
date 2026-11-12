"""Stored catalogue views of the platforms (0.5.60).

Björn (12.11.2026): under "Plattformen" the catalogue is sometimes not there or takes long to
appear; once everything has been scanned, a view can stay stored until the next scan.

Until now every page of a platform read all rows of its database, parsed the reference report of
every title and sorted and filtered the list again. While the catalogue run or the work matching
was writing to the same database, a page could wait for the lock or fail.

This module keeps the complete prepared list per platform and view:

* in memory for every filter that was asked for,
* on disk (``snapshots/<platform>-<view>-<sort>.json``) for the unfiltered views, so they are there
  immediately after a restart,
* a stored list is answered at once; when it is older than ``TTL`` it is renewed in the background
  (the work matching adds ratings and categories all the time),
* a finished catalogue run (other ``stamp``) or a change by the user (``invalidate``) builds the
  list anew before it is shown; if that fails, the stored list is shown instead of an error.

Nothing here decides what belongs to a catalogue: the list is exactly what ``listing(limit='all')``
of the platform returned.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

TTL = 60.0
_MAX = 40
_MEM = {}            # key -> {'data': dict, 'stamp': str, 'built': monotonic, 'used': monotonic}
_LOCK = threading.Lock()
_BUILD = {}          # source -> Lock, one build per platform at a time
_BUSY = set()
_GEN = {}            # source -> int, raised by invalidate()
_STATUS = {}         # source -> last status that could be read
_DIR = None
STATS = {'hits': 0, 'builds': 0, 'background': 0, 'restored': 0, 'fallbacks': 0}


def configure(directory):
    """Folder for the stored views; without it everything stays in memory."""
    global _DIR
    _DIR = Path(directory) if directory else None
    with _LOCK:
        _MEM.clear()
        _BUSY.clear()
        _GEN.clear()
        _STATUS.clear()


def _file(key):
    source, view, query, genre, sort, collection = key
    if _DIR is None or query or genre or collection:
        return None
    name = '-'.join(re.sub(r'[^a-z0-9]+', '', str(part).lower())[:24] or 'x' for part in (source, view, sort))
    return _DIR / (name + '.json')


def _write(key, data, stamp):
    path = _file(key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version': 1, 'key': list(key), 'stamp': stamp, 'saved': time.time(), 'data': data},
                                  separators=(',', ':')), encoding='utf-8')
        tmp.replace(path)
    except (OSError, TypeError, ValueError):
        pass   # the view is still served from memory


def _read(key):
    path = _file(key)
    if path is None:
        return None
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
        if stored.get('version') != 1 or stored.get('key') != list(key) or not isinstance(stored['data'].get('items'), list):
            return None
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    STATS['restored'] += 1
    # built = -inf: shown at once, renewed on first use.
    return {'data': stored['data'], 'stamp': str(stored.get('stamp') or ''), 'built': float('-inf'),
            'used': time.monotonic(), 'saved': float(stored.get('saved') or 0)}


def _store(key, data, stamp):
    now = time.monotonic()
    with _LOCK:
        _MEM[key] = {'data': data, 'stamp': stamp, 'built': now, 'used': now, 'saved': time.time()}
        while len(_MEM) > _MAX:
            _MEM.pop(min(_MEM, key=lambda k: _MEM[k]['used']))
    _write(key, data, stamp)


def _build(key, loader, stamp):
    with _LOCK:
        lock = _BUILD.setdefault(key[0], threading.Lock())
    with lock:
        with _LOCK:
            entry = _MEM.get(key)
            if entry and entry['stamp'] == stamp and time.monotonic() - entry['built'] <= TTL:
                return entry['data']      # built while waiting
        data = loader()
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise ValueError('Katalogansicht ohne Einträge')
        STATS['builds'] += 1
        _store(key, data, stamp)
        return data


def _renew(key, loader, stamp):
    try:
        _build(key, loader, stamp)
        STATS['background'] += 1
    except Exception:
        pass   # the stored view stays; the next request tries again
    finally:
        with _LOCK:
            _BUSY.discard(key)


def invalidate(source):
    """The user changed something of this platform: the next view is built anew."""
    with _LOCK:
        _GEN[source] = _GEN.get(source, 0) + 1


def status(source, loader):
    """Status of the platform; when its database is busy, the last one that could be read."""
    try:
        value = loader()
        with _LOCK:
            _STATUS[source] = value
        return value
    except Exception:
        with _LOCK:
            known = _STATUS.get(source)
        if known is None:
            raise
        return known


def full(source, view, loader, stamp='', query='', genre='', sort='title', collection=''):
    """Complete prepared list for one filter. ``loader()`` returns the dict of
    ``listing(limit='all')``; ``stamp`` changes when a catalogue run has finished."""
    key = (str(source), str(view)[:20], str(query or '').strip().casefold()[:180], str(genre or '').strip().casefold()[:80],
           str(sort)[:20], str(collection)[:20])
    now = time.monotonic()
    with _LOCK:
        stamp = '%s|%d' % (stamp, _GEN.get(key[0], 0))
        entry = _MEM.get(key)
    if entry is None:
        entry = _read(key)
        if entry is not None:
            # The file knows the run it belongs to, but not the changes of this session.
            entry['stamp'] = '%s|%d' % (entry['stamp'].rsplit('|', 1)[0], 0)
            with _LOCK:
                entry = _MEM.setdefault(key, entry)
    if entry is not None:
        with _LOCK:
            entry['used'] = now
        if entry['stamp'] == stamp:
            if now - entry['built'] > TTL:
                with _LOCK:
                    start = key not in _BUSY
                    if start:
                        _BUSY.add(key)
                if start:
                    threading.Thread(target=_renew, args=(key, loader, stamp), daemon=True,
                                     name='portal_snapshot_renew').start()
            STATS['hits'] += 1
            return entry['data']
        try:
            return _build(key, loader, stamp)
        except Exception:
            STATS['fallbacks'] += 1
            return entry['data']       # better the stored view than an empty tab
    return _build(key, loader, stamp)


def page(source, view, loader, stamp='', query='', genre='', sort='title', collection='', offset=0, limit=60):
    """One page out of the stored list, in the shape ``listing`` returns."""
    data = full(source, view, loader, stamp, query, genre, sort, collection)
    try:
        offset = max(0, min(int(offset), 1000000))
    except (TypeError, ValueError):
        offset = 0
    if limit == 'all':
        size = len(data['items'])
    else:
        try:
            size = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            size = 60
    out = {k: v for k, v in data.items() if k != 'items'}
    out.update(items=data['items'][offset:offset + size], total=len(data['items']), offset=offset)
    return out
