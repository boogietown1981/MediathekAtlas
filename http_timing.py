"""Request timing for diagnostics (0.5.41).

Björn saw the platform panels stay at "Katalogstatus wird geladen …" without any error. To find
out which requests keep the local service (or the browser's few connections per host) busy, every
API request is timed: requests still running appear in the diagnostics export with their age, and
slow ones are counted per endpoint and logged at most once a minute per endpoint. Only the path is
kept, never query strings (they can hold search terms).
"""
from __future__ import annotations

import itertools
import threading
import time

SLOW_SECONDS = 5.0
LOG_INTERVAL = 60.0
# Long by nature: video and file transfers.
STREAMING = ('/api/stream', '/api/download-file')

_LOCK = threading.Lock()
_ACTIVE: dict[int, tuple[str, str, float]] = {}
_SLOW: dict[str, dict] = {}
_LOGGED: dict[str, float] = {}
_IDS = itertools.count(1)


def endpoint(raw_path):
    path = str(raw_path or '').split('?', 1)[0].split('#', 1)[0]
    return path[:80] or '/'


def start(method, raw_path, now=None):
    key = next(_IDS)
    with _LOCK:
        _ACTIVE[key] = (str(method), endpoint(raw_path), time.monotonic() if now is None else now)
    return key


def finish(key, log=None, now=None):
    """Close a request; returns its duration. ``log(endpoint, seconds, method)`` for slow ones."""
    now = time.monotonic() if now is None else now
    with _LOCK:
        entry = _ACTIVE.pop(key, None)
        if not entry:
            return 0.0
        method, path, began = entry
        seconds = max(0.0, now - began)
        if seconds < SLOW_SECONDS or path in STREAMING:
            return seconds
        slot = _SLOW.setdefault(path, {'count': 0, 'max_seconds': 0.0, 'last_seconds': 0.0})
        slot['count'] += 1
        slot['max_seconds'] = round(max(slot['max_seconds'], seconds), 2)
        slot['last_seconds'] = round(seconds, 2)
        due = now - _LOGGED.get(path, float('-inf')) >= LOG_INTERVAL
        if due:
            _LOGGED[path] = now
    if due and log:
        try:
            log(path, round(seconds, 2), method)
        except Exception:
            pass
    return seconds


def snapshot(now=None):
    now = time.monotonic() if now is None else now
    with _LOCK:
        active = sorted(({'method': m, 'endpoint': p, 'seconds': round(now - t, 1)} for m, p, t in _ACTIVE.values()),
                        key=lambda x: -x['seconds'])
        slow = {k: dict(v) for k, v in sorted(_SLOW.items(), key=lambda kv: -kv[1]['max_seconds'])[:25]}
    return {'active': active[:40], 'active_count': len(active), 'slow_threshold_seconds': SLOW_SECONDS, 'slow': slow}
