"""Device keys and stream tickets for API v1 (0.6.2, Phase C of the review of 14.11.2026).

The web page proves itself with the login cookie (network mode) and a page token that changes with
every start. A client outside the browser (an Apple TV player, a phone app, a script) has neither.
For such clients the user creates a **device key** in Verwaltung → System:

- the key is shown once; the file ``api_keys.json`` (readable by the owner only) keeps a SHA-256
  hash, the name, the day it was created and when it was last used;
- a key opens the addresses below ``/api/v1/`` and nothing else (no settings, no catalogue runs,
  no key management);
- deleting the entry withdraws the key at once. Without any key the server answers no ``/api/v1``
  request from outside the page, so nothing new is open by default.

A **ticket** is a short-lived value for addresses a video player calls itself (it often cannot
send headers): ``<expiry>.<HMAC-SHA256>``, signed with a secret of the running server, valid for
twelve hours and only until the next restart.

Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

FILE = 'api_keys.json'
PREFIX = 'atlas_'
MAX_KEYS = 50
TICKET_SECONDS = 12 * 3600
_LOCK = threading.Lock()
_CACHE = {}          # path -> ((mtime_ns, size, inode), items)
_USED = {}           # key id -> time of the last write of 'last_used'


def _path(root):
    return Path(root) / FILE


def _load(root):
    path = _path(root)
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)     # the time alone is too coarse on some file systems
    except OSError:
        return []
    hit = _CACHE.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        items = json.loads(path.read_text(encoding='utf-8')).get('keys') or []
    except (OSError, ValueError, AttributeError):
        items = []
    items = [i for i in items if isinstance(i, dict) and i.get('id') and i.get('hash')]
    _CACHE[str(path)] = (stamp, items)
    return items


def _store(root, items):
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'keys': items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    _CACHE.pop(str(path), None)


def _digest(key):
    return hashlib.sha256(key.encode('utf-8', 'replace')).hexdigest()


def _public(item):
    return {k: item.get(k) for k in ('id', 'name', 'created', 'last_used')}


def listing(root):
    """The keys without their hashes, newest first."""
    with _LOCK:
        return sorted((_public(i) for i in _load(root)), key=lambda i: -(i.get('created') or 0))


def create(root, name, now=None):
    """A new key; the clear text is in the result under 'key' and is stored nowhere."""
    name = ' '.join(str(name or '').split())[:60]
    if not name:
        raise ValueError('Bitte einen Namen für das Gerät angeben')
    with _LOCK:
        items = list(_load(root))
        if len(items) >= MAX_KEYS:
            raise ValueError('Höchstens %d Geräteschlüssel. Bitte zuerst einen löschen.' % MAX_KEYS)
        if any(i.get('name', '').lower() == name.lower() for i in items):
            raise ValueError('Diesen Namen gibt es schon')
        key = PREFIX + secrets.token_urlsafe(32)
        item = {'id': secrets.token_hex(6), 'name': name, 'created': int(time.time() if now is None else now),
                'last_used': 0, 'hash': _digest(key)}
        _store(root, items + [item])
    return dict(_public(item), key=key)


def revoke(root, key_id):
    """Delete a key; True when it existed."""
    with _LOCK:
        items = list(_load(root))
        left = [i for i in items if i['id'] != str(key_id)]
        if len(left) == len(items):
            return False
        _store(root, left)
        _USED.pop(str(key_id), None)
    return True


def verify(root, key, now=None):
    """The key's entry (without hash) when ``key`` is valid, else None."""
    if not isinstance(key, str) or not key.startswith(PREFIX) or not 20 <= len(key) <= 200:
        return None
    digest = _digest(key)
    now = time.time() if now is None else now
    with _LOCK:
        items = _load(root)
        found = None
        for item in items:        # every entry is compared, in constant time each
            if hmac.compare_digest(str(item['hash']), digest):
                found = item
        if not found:
            return None
        if now - _USED.get(found['id'], 0) >= 300:     # at most one write in five minutes (NAS disks)
            _USED[found['id']] = now
            try:
                _store(root, [dict(i, last_used=int(now)) if i['id'] == found['id'] else i for i in items])
            except OSError:
                pass
        return _public(found)


def ticket(secret, seconds=TICKET_SECONDS, now=None):
    expiry = int((time.time() if now is None else now) + seconds)
    return '%d.%s' % (expiry, _sign(secret, expiry))


def ticket_valid(secret, value, now=None):
    try:
        expiry, mac = str(value or '').split('.', 1)
        expiry = int(expiry)
    except ValueError:
        return False
    if expiry < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(mac, _sign(secret, expiry))


def _sign(secret, expiry):
    return hmac.new(str(secret).encode(), b'atlas-v1-ticket:%d' % expiry, hashlib.sha256).hexdigest()
