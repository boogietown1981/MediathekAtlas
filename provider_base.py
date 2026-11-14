"""Common ground of the catalogue platforms (0.6.0, Phase B of the review of 14.11.2026).

Until 0.5.108 eleven platform modules (Netzkino, Pluto TV, JustWatch, Rakuten TV, Joyn, TOGGO,
Crunchyroll, Plex, ServusTV, RTL+, YouTube) each carried their own copy of the same frame: open the
database, decide whether the catalogue is due, and a loop thread that asked that question every
minute. The copies had drifted apart (only three platforms reloaded a partial catalogue after an
update until 0.5.108). This module holds that frame once:

- ``connect``: the platform's own SQLite file, now in WAL mode (readers no longer wait for the
  catalogue run that writes), ``busy_timeout`` 5 s, optionally readable only by the owner.
- ``catalog_due``: one rule for "start a catalogue run now" (first start, once after an update when
  the last run was partial or failed, the daily automatic run).
- ``loop``: the old per-platform loop, kept for callers and tests; the server itself uses the
  single planner in ``planner.py`` instead of one thread per platform.

What each platform fetches and how it maps titles stays in its own module. Standard library only.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import portal_reference

_WAL = set()
_WAL_LOCK = threading.Lock()


def connect(root, filename, *, private=False, timeout=5):
    """Connection to ``root/filename`` with rows by name, a 5 s busy timeout and WAL journal."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    db = sqlite3.connect(str(path), timeout=timeout)
    if private and os.name != 'nt':
        try:
            os.chmod(path, 0o600)       # tokens or account choices inside
        except OSError:
            pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    _wal(db, str(path))
    return db


def _wal(db, key):
    """Switch a database file to WAL once per process. WAL keeps readers (the web page) and the one
    writer (the catalogue run) apart, which matters on slow NAS disks. The mode is stored in the file;
    if the switch is not possible right now (another connection holds a lock), the next connect
    tries again. ``synchronous=NORMAL`` is the recommended pairing: at worst the last transaction
    before a power cut is lost, never the file."""
    if os.environ.get('MEDIATHEKATLAS_NO_WAL') == '1':
        return                       # data folder on a network share: WAL needs local shared memory
    if key in _WAL:
        db.execute('PRAGMA synchronous=NORMAL')
        return
    with _WAL_LOCK:
        try:
            mode = db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        except sqlite3.OperationalError:
            return
        if str(mode).lower() == 'wal':
            _WAL.add(key)
            db.execute('PRAGMA synchronous=NORMAL')


def catalog_due(root, module, current, now=None):
    """True when the platform's catalogue run should start now (the rule all platforms share)."""
    if current.get('running'):
        return False
    now = time.time() if now is None else now
    return bool(portal_reference.first_load_due(current)
                or portal_reference.retry_after_update(root, module, current)
                or (current.get('auto') and now >= float(current.get('next_attempt') or 0)))


def running(module):
    """Whether the platform's catalogue run is active (every platform keeps the flag ``_ACTIVE``)."""
    return bool(getattr(module, '_ACTIVE', False))


def loop(root, stop, key, module, interval=60):
    """The former per-platform loop: every minute, start the catalogue run when it is due."""
    import task_control
    while not stop.wait(interval):
        if task_control.paused('catalog:' + key):
            continue
        if module.should_sync(root):
            module.start_sync(root)
