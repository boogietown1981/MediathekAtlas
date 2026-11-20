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
- ``read_capped`` (0.6.52): reads an answer with a size cap and a total deadline. ``urlopen(timeout=30)``
  limits every single socket read only; on Björn's Mac a DMAX catalogue run hung for more than five
  minutes in a trickling SSL read. Every catalogue request of the platforms now ends after READ_DEADLINE.
- ``open_capped`` (0.6.54): the deadline also covers the time before the answer head. On Björn's Mac (check of
  0.6.52) a DMAX request hung in ``http.client._read_status``, where only the 30 s socket timeout per read applies
  (plus retries: 100 requests in about ten minutes). ``open_capped`` keeps the sockets it opens and shuts them
  down when OPEN_DEADLINE has passed, which ends a hanging read at once (TimeoutError).
- ``NET_FAILURE_BUDGET`` (0.6.54): a catalogue run stops after this many network failures (timeouts, refused or
  reset connections) and counts as partial; the next try follows after NET_RETRY (2 h, as YouTube).

What each platform fetches and how it maps titles stays in its own module. Standard library only.
"""
from __future__ import annotations

import contextlib
import http.client
import os
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import portal_reference

READ_DEADLINE = 120.0       # seconds for one answer (headers already received)
READ_CHUNK = 64 * 1024
OPEN_DEADLINE = 150.0       # seconds for one request from connecting to the last byte (0.6.54)
NET_FAILURE_BUDGET = 3      # network failures per catalogue run before it stops as partial (0.6.54)
NET_RETRY = 2 * 3600        # next try after a run stopped by the budget

_WAL = set()
_WAL_LOCK = threading.Lock()
_SCHEMA = set()
_SCHEMA_LOCK = threading.Lock()


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
    # 0.6.19 (Björns Diagnose 0.6.18): a run cut off by a restart or update ('interrupted') starts again
    # instead of waiting for the next 24-hour slot. ServusTV's crawl takes 30-40 minutes; the restart
    # into 0.6.18 cut it off and the new code (0.6.16) would only have run a day later.
    return bool(portal_reference.first_load_due(current)
                or current.get('last_result') == 'interrupted'
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


def read_capped(response, limit, deadline=None):
    """Up to ``limit + 1`` bytes of ``response`` (callers compare with ``limit`` as before), read in chunks;
    raises TimeoutError when the whole answer takes longer than ``deadline`` seconds (default READ_DEADLINE).
    One chunk can still wait for the socket timeout of the request, so the worst case is deadline + timeout."""
    deadline = READ_DEADLINE if deadline is None else float(deadline)
    ends = time.monotonic() + deadline
    parts, size = [], 0
    while size <= limit:
        chunk = response.read(min(READ_CHUNK, limit + 1 - size))
        if not chunk:
            break
        parts.append(chunk)
        size += len(chunk)
        if time.monotonic() > ends and size <= limit:
            raise TimeoutError('Antwort kam nicht innerhalb von %d Sekunden vollständig an' % deadline)
    return b''.join(parts)


class _Hold:
    """Sockets of one request; after the deadline every one is shut down (also ones connected later)."""

    def __init__(self):
        self.socks, self.expired, self.lock = [], False, threading.Lock()

    def add(self, sock):
        with self.lock:
            self.socks.append(sock)
            late = self.expired
        if late:
            _shut(sock)

    def expire(self):
        with self.lock:
            self.expired = True
            socks = list(self.socks)
        for sock in socks:
            _shut(sock)


def _shut(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _held(base, hold):
    class Held(base):
        def connect(self):
            super().connect()
            hold.add(self.sock)
    return Held


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, hold):
        super().__init__()
        self.hold = hold

    def http_open(self, req):
        return self.do_open(_held(http.client.HTTPConnection, self.hold), req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, hold):
        super().__init__()
        self.hold = hold

    def https_open(self, req):
        # the context is created per connection as before (netcheck may swap the trust store)
        return self.do_open(_held(http.client.HTTPSConnection, self.hold), req, context=self._context)


@contextlib.contextmanager
def open_capped(req, timeout=30, deadline=None):
    """``urllib.request.urlopen(req, timeout)`` with one deadline for the whole request, including the time
    before the answer head. Raises TimeoutError when the deadline ends the request; HTTP errors stay HTTPError."""
    deadline = OPEN_DEADLINE if deadline is None else float(deadline)
    hold = _Hold()
    timer = threading.Timer(deadline, hold.expire)
    timer.daemon = True
    timer.start()
    try:
        opener = urllib.request.build_opener(_HTTPHandler(hold), _HTTPSHandler(hold))
        try:
            with opener.open(req, timeout=timeout) as response:
                yield response
        except urllib.error.HTTPError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if hold.expired:
                raise TimeoutError('Keine vollständige Antwort innerhalb von %d Sekunden' % deadline) from exc
            raise
    finally:
        timer.cancel()


def network_failure(exc):
    """True for failures of the connection itself (no answer), not for HTTP answers or bad content."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    return isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, http.client.HTTPException)) \
        or (isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError))


def ensure_schema(db, script):
    """Run a ``CREATE … IF NOT EXISTS`` script once per process and database file (0.6.52). Running it on
    every connect made simultaneous status requests at start-up wait for each other's write lock
    (CI: 500 on /api/film-platforms). A file that is replaced later (new path) gets the script again."""
    row = db.execute('PRAGMA database_list').fetchone()
    key = (str(row[2] if row else ''), hash(script))
    if key[0] and key in _SCHEMA:
        return
    with _SCHEMA_LOCK:
        if key[0] and key in _SCHEMA:
            return
        db.executescript(script)
        if key[0]:
            _SCHEMA.add(key)
