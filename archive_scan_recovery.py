"""Sicherer, wiederanlaufender Archive.org-Scan (0.5.92), aus Archive Media.

ArchiveMedia ``clean_scan`` and ``scan_recovery``, carried over to the scan sources of
``portal_control`` (collections and public uploaders):

* A page is only counted when Archive.org proves it is the page that was asked for: the results
  are sorted by identifier, the answer names its start position, and a page must begin behind the
  last identifier already seen. A silent repeat of page one used to be counted as progress.
* Archive.org's search answers at most 10 000 results per question. A larger collection is split
  by publication date into time windows; a window that is still too large is halved again.
* A failure is told apart: a passing network problem is tried again with a growing pause and
  given up after a bounded number of attempts; a search that makes no provable progress stops as
  ``stalled``; a refused request stops as ``error``. The position is kept in every case.
* "Neu durchsuchen" starts a source again from the beginning. Nothing that was found is deleted;
  the counters of the previous run are kept in a history table.
* The total Archive.org names for a source is stored next to what was read, as an estimate of the
  coverage - not as a proof.

Pure functions and SQL over ``portal_scopes``; the HTTP request itself stays in ``portal_control``.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error

SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_scope_windows(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 start_utc TEXT NOT NULL,
 end_utc TEXT NOT NULL,
 page INTEGER NOT NULL DEFAULT 1,
 state TEXT NOT NULL DEFAULT 'queued',
 found INTEGER NOT NULL DEFAULT 0,
 total INTEGER,
 last_identifier TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 updated REAL NOT NULL DEFAULT 0,
 UNIQUE(scope_id,start_utc,end_utc));
CREATE INDEX IF NOT EXISTS ix_portal_scope_windows_next ON portal_scope_windows(scope_id,state,start_utc);
CREATE TABLE IF NOT EXISTS portal_scope_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 saved REAL NOT NULL,
 snapshot TEXT NOT NULL);
"""
COLUMNS = (('provider_total', 'INTEGER'), ('mode', 'INTEGER NOT NULL DEFAULT 2'),
           ('last_identifier', "TEXT NOT NULL DEFAULT ''"), ('generation', 'INTEGER NOT NULL DEFAULT 0'))
LEGACY, VERIFIED = 1, 2              # mode: 1 = a scan begun before 0.5.92 (unsorted pages), 2 = sorted and verified
RESULT_LIMIT = 9500                  # Archive.org answers 10 000 results per question at most
FIRST_YEAR = 1996                    # nothing was published on Archive.org before
STAMP = '%Y-%m-%dT%H:%M:%SZ'
MAX_TRANSIENT = 8                    # consecutive passing failures before a source stops
MAX_STALLS = 3
HISTORY_KEPT = 20
TRANSIENT_TERMS = ('timed out', 'timeout', 'temporary', 'connection reset', 'connection aborted', 'remote end closed',
                   'broken pipe', 'database is locked', 'no route to host', 'name or service not known',
                   'nodename nor servname', 'network is unreachable', 'server disconnected', 'unexpected eof',
                   'eof occurred', 'urlopen error', 'http error 429', 'http error 500', 'http error 502',
                   'http error 503', 'http error 504')
TRANSIENT_CODES = (408, 425, 429, 500, 502, 503, 504)


class Stalled(ValueError):
    """Archive.org gave no provable progress. The stored position stays as it is."""


def migrate(c):
    c.executescript(SCHEMA)
    have = {r[1] for r in c.execute('PRAGMA table_info(portal_scopes)')}
    fresh = 'mode' not in have
    for name, definition in COLUMNS:
        if name not in have:
            c.execute('ALTER TABLE portal_scopes ADD COLUMN %s %s' % (name, definition))
    if fresh:
        # A scan that is in the middle of unsorted pages finishes the way it began; changing the
        # order under a stored page number would skip uploads.
        c.execute("UPDATE portal_scopes SET mode=? WHERE cursor>1 AND state!='complete'", (LEGACY,))


# ---- the question -------------------------------------------------------------------------

def full_window(now=None):
    """The time span that holds every upload: 1996 until the first day of the next month."""
    today = dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc)
    end = dt.datetime(today.year + (today.month == 12), today.month % 12 + 1, 1)
    return dt.datetime(FIRST_YEAR, 1, 1).strftime(STAMP), end.strftime(STAMP)


def window_clause(window):
    """Search clause of a window. The end is exclusive, written as the second before it."""
    start = dt.datetime.strptime(window['start_utc'], STAMP)
    end = dt.datetime.strptime(window['end_utc'], STAMP)
    if start >= end:
        raise ValueError('Ungültiges Zeitfenster')
    return ' AND publicdate:[%s TO %s]' % (window['start_utc'], (end - dt.timedelta(seconds=1)).strftime(STAMP))


def position(scope):
    """(page, last identifier) of the next request of a verified scan."""
    window = scope.get('window')
    if window:
        return int(window['page']), window.get('last_identifier') or ''
    return int(scope['cursor']), scope.get('last_identifier') or ''


# ---- the answer ---------------------------------------------------------------------------

def check(document, page, per_page, last_identifier=''):
    """Facts of a search answer, or an error when it is not the page that was asked for."""
    response = document.get('response') if isinstance(document, dict) else None
    if not isinstance(response, dict):
        raise ValueError('Archive.org: ungültige Suchantwort')
    docs, total = response.get('docs'), response.get('numFound')
    if not isinstance(docs, list) or isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError('Archive.org: ungültige Trefferliste')
    if total > RESULT_LIMIT:
        # Nothing of this answer is used; the question is asked again in smaller parts.
        return {'total': total, 'count': 0, 'first': '', 'last': '', 'more': False, 'too_large': True}
    offset = (int(page) - 1) * per_page
    start = response.get('start')
    if start is not None and (isinstance(start, bool) or not str(start).isdigit() or int(start) != offset):
        raise Stalled('Archive.org lieferte eine andere Seite als angefragt (Position %s statt %d)' % (start, offset))
    names = [d.get('identifier') for d in docs if isinstance(d, dict) and isinstance(d.get('identifier'), str)]
    if not docs and offset < total:
        raise Stalled('Leere Suchseite, obwohl weitere Treffer gemeldet sind')
    if page > 1 and last_identifier and names and names[0] <= last_identifier:
        raise Stalled('Suchseite wiederholt oder unsortiert (beginnt bei „%s“)' % names[0][:60])
    return {'total': total, 'count': len(docs), 'first': names[0] if names else '', 'last': names[-1] if names else '',
            'more': offset + len(docs) < total and len(docs) == per_page, 'too_large': False}


# ---- time windows -------------------------------------------------------------------------

def _add_window(c, scope_id, start, end, now):
    return c.execute('INSERT OR IGNORE INTO portal_scope_windows(scope_id,start_utc,end_utc,updated) VALUES(?,?,?,?)',
                     (scope_id, start, end, now)).rowcount


def split(c, scope_id, start_utc, end_utc, now=None):
    """Two halves of a time span as new windows. False when a second cannot be halved."""
    now = time.time() if now is None else now
    start, end = dt.datetime.strptime(start_utc, STAMP), dt.datetime.strptime(end_utc, STAMP)
    seconds = int((end - start).total_seconds())
    if seconds <= 1:
        return False
    middle = (start + dt.timedelta(seconds=seconds // 2)).strftime(STAMP)
    _add_window(c, scope_id, start_utc, middle, now)
    _add_window(c, scope_id, middle, end_utc, now)
    return True


def next_window(c, scope_id):
    """The newest window still to read (new uploads first), or None."""
    row = c.execute("""SELECT id,start_utc,end_utc,page,last_identifier FROM portal_scope_windows
        WHERE scope_id=? AND state='queued' ORDER BY start_utc DESC,id LIMIT 1""", (scope_id,)).fetchone()
    return dict(zip(('id', 'start_utc', 'end_utc', 'page', 'last_identifier'), row)) if row else None


def windows_left(c, scope_id):
    return c.execute("SELECT COUNT(*) FROM portal_scope_windows WHERE scope_id=? AND state='queued'", (scope_id,)).fetchone()[0]


def apply(c, scope, facts, now=None):
    """Store what a verified page proved. Returns True while the source has more to read."""
    now = time.time() if now is None else now
    scope_id, window = scope['id'], scope.get('window')
    if window:
        if facts['too_large']:
            done = split(c, scope_id, window['start_utc'], window['end_utc'], now)
            c.execute('UPDATE portal_scope_windows SET state=?,total=?,note=?,updated=? WHERE id=?',
                      ('split' if done else 'error', facts['total'],
                       '' if done else 'Mehr als %d Uploads in einer Sekunde; nicht weiter teilbar' % RESULT_LIMIT, now, window['id']))
        else:
            c.execute("""UPDATE portal_scope_windows SET page=page+?,state=?,found=found+?,total=?,last_identifier=?,updated=?
                WHERE id=?""", (int(facts['more']), 'queued' if facts['more'] else 'complete', facts['count'], facts['total'],
                                facts['last'] or window.get('last_identifier') or '', now, window['id']))
        return windows_left(c, scope_id) > 0
    if facts['too_large']:
        # The whole source is too large for one question: from now on it is read in windows.
        start, end = full_window(now)
        c.execute('UPDATE portal_scopes SET provider_total=? WHERE id=?', (facts['total'], scope_id))
        split(c, scope_id, start, end, now)
        return windows_left(c, scope_id) > 0
    c.execute('UPDATE portal_scopes SET provider_total=?,last_identifier=? WHERE id=?',
              (facts['total'], facts['last'] or scope.get('last_identifier') or '', scope_id))
    return facts['more']


# ---- failures -----------------------------------------------------------------------------

def kind_of(error):
    """'stalled', 'transient' or 'permanent'."""
    if isinstance(error, Stalled):
        return 'stalled'
    if isinstance(error, urllib.error.HTTPError):
        return 'transient' if error.code in TRANSIENT_CODES else 'permanent'
    if isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return 'transient'
    text = str(error).lower()
    if 'ungültig' in text:
        return 'permanent'
    if any(term in text for term in TRANSIENT_TERMS) or isinstance(error, OSError):
        return 'transient'
    return 'permanent'


def plan(error, failures, enabled=True):
    """(state, pause in seconds) after the ``failures``-th consecutive failure of a source."""
    kind = kind_of(error)
    pause = min(3600, 30 * 2 ** min(failures, 7))
    if not enabled:
        return 'paused', pause
    if kind == 'stalled':
        return ('retry', pause) if failures < MAX_STALLS else ('stalled', 0)
    if kind == 'transient':
        return ('retry', pause) if failures < MAX_TRANSIENT else ('error', 0)
    return 'error', 0


# ---- a new run ----------------------------------------------------------------------------

def rescan(c, scope_id, now=None):
    """Read a source again from the start. Found uploads stay; the old counters go to the history."""
    now = time.time() if now is None else now
    row = c.execute("""SELECT kind,scope,state,cursor,pages_done,imported,failures,last_error,last_success,provider_total,mode,generation
        FROM portal_scopes WHERE id=?""", (scope_id,)).fetchone()
    if not row:
        raise ValueError('Scanquelle nicht gefunden')
    if row[2] == 'running':
        raise ValueError('Laufenden Scan zunächst pausieren')
    if row[0] == 'item':
        raise ValueError('Ein einzelner Upload wird über „Start“ erneut gelesen')
    names = ('kind', 'scope', 'state', 'cursor', 'pages_done', 'imported', 'failures', 'last_error', 'last_success', 'provider_total', 'mode', 'generation')
    windows = [list(r) for r in c.execute('SELECT state,COUNT(*),COALESCE(SUM(found),0) FROM portal_scope_windows WHERE scope_id=? GROUP BY state', (scope_id,))]
    c.execute('INSERT INTO portal_scope_history(scope_id,saved,snapshot) VALUES(?,?,?)',
              (scope_id, now, json.dumps({'previous': dict(zip(names, row)), 'windows': windows}, ensure_ascii=False)))
    c.execute('DELETE FROM portal_scope_history WHERE scope_id=? AND id NOT IN (SELECT id FROM portal_scope_history WHERE scope_id=? ORDER BY id DESC LIMIT ?)',
              (scope_id, scope_id, HISTORY_KEPT))
    # Only the positions of the search are cleared, never an upload that was found.
    c.execute('DELETE FROM portal_scope_windows WHERE scope_id=?', (scope_id,))
    c.execute("""UPDATE portal_scopes SET cursor=1,pages_done=0,run_pages=0,imported=0,failures=0,last_error='',last_identifier='',
        provider_total=NULL,mode=?,generation=generation+1,state='queued',enabled=1,next_try=0,updated=? WHERE id=?""", (VERIFIED, now, scope_id))
    return c.execute('SELECT generation FROM portal_scopes WHERE id=?', (scope_id,)).fetchone()[0]


def coverage(c):
    """Per source: what Archive.org names and what was read. An estimate, not a proof. scope id -> facts."""
    out = {}
    windows = {}
    for scope_id, state, count, found in c.execute('SELECT scope_id,state,COUNT(*),COALESCE(SUM(found),0) FROM portal_scope_windows GROUP BY scope_id,state'):
        windows.setdefault(scope_id, {})[state] = (count, found)
    for scope_id, kind, state, imported, total, mode, generation in c.execute(
            "SELECT id,kind,state,imported,provider_total,mode,generation FROM portal_scopes WHERE source='internet_archive'"):
        w = windows.get(scope_id, {})
        parts = sum(n for s, (n, _) in w.items() if s != 'split')
        done = w.get('complete', (0, 0))[0]
        broken = w.get('error', (0, 0))[0]
        if total is None:
            verdict = 'unknown'
        elif state != 'complete':
            verdict = 'in_progress'
        elif broken or imported < total:
            verdict = 'needs_review'
        else:
            verdict = 'count_plausible'
        out[scope_id] = {'provider_total': total, 'read': imported, 'windows': parts, 'windows_done': done, 'windows_failed': broken,
                         'verified': mode == VERIFIED, 'generation': generation, 'coverage': verdict,
                         'gap': max(0, total - imported) if total is not None and state == 'complete' else None}
    return out
