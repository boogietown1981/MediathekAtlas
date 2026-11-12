"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for film portals with own catalogue (0.5.40).

One implementation for Pluto TV (pluto_enrichment) and JustWatch TV (justwatch_enrichment):
same provider chain and evaluation as Netzkino (netzkino_enrichment.analyze over
core.candidates), conservative, a unique eligible reference only, the portal's own catalogue
fields keep priority. Each portal describes itself with a ``Spec``; reports live in the
portal's own SQLite file and feed categories, ratings, details and download metadata
(portal_reference). Films and series are checked; an episode uses its series' report.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

import netzkino_enrichment as shared
import portal_reference

GOOD_TTL = shared.GOOD_TTL
RETRY_TTL = shared.RETRY_TTL
UNCHECKED = {'status': 'unchecked', 'metadata': {}, 'references': [], 'cached': False}


@dataclass(frozen=True)
class Spec:
    name: str                # label shown as field source, e.g. 'Pluto TV'
    key: str                 # short name for logs/threads, e.g. 'pluto'
    items: str               # catalogue table, columns id, kind, title, year, duration, genre, summary, poster, series_id, seen
    checks: str              # report table
    connect: Callable        # root -> sqlite3 connection (row_factory Row)
    valid_id: Callable       # str -> bool
    last_success: Callable   # db -> float (only titles seen in the latest catalogue run are pending)

    def schema(self):
        return ('CREATE TABLE IF NOT EXISTS %s(item_id TEXT PRIMARY KEY, checked REAL NOT NULL, '
                'identity TEXT NOT NULL, payload TEXT NOT NULL);'
                'CREATE INDEX IF NOT EXISTS %s_checked ON %s(checked);' % (self.checks, self.checks, self.checks))


def _conn(spec, root):
    db = spec.connect(root)
    db.executescript(spec.schema())
    return db


def _row(spec, db, item_id):
    if not spec.valid_id(str(item_id or '')):
        raise ValueError('Ungültiger %s-Titel' % spec.name)
    row = db.execute('SELECT * FROM %s WHERE id=?' % spec.items, (item_id,)).fetchone()
    if not row:
        raise ValueError('%s-Titel nicht im Katalog; bitte Katalog neu laden' % spec.name)
    return dict(row)


def subject(spec, db, item_id):
    """Title whose report applies: an episode uses its series."""
    row = _row(spec, db, item_id)
    if row['kind'] == 'episode' and row.get('series_id'):
        parent = db.execute('SELECT * FROM %s WHERE id=?' % spec.items, (row['series_id'],)).fetchone()
        if parent:
            return dict(parent)
    return row


def identity(row):
    kind = 'series' if row['kind'] in ('series', 'episode') else 'movie'
    return {'kind': kind, 'title': shared._str(row.get('title'), 240),
            'year': shared._integer(row.get('year'), 1880, 2100) if kind == 'movie' else None,
            'season': None, 'episode': None, 'episode_title': ''}


def editorial(row):
    return {'title': row.get('title') or '', 'year': row.get('year'), 'duration_seconds': row.get('duration'),
            'description': row.get('summary') or '', 'genres': portal_reference.split_labels(row.get('genre')),
            'poster': row.get('poster') or ''}


def _key(meta):
    return json.dumps([meta['kind'], meta['title'], meta['year']], ensure_ascii=False)


def cached(spec, root, item_id):
    """Stored report for a title (episodes: their series), no provider traffic."""
    db = _conn(spec, root)
    try:
        row = subject(spec, db, item_id)
        found = db.execute('SELECT checked,identity,payload FROM %s WHERE item_id=?' % spec.checks,
                           (row['id'],)).fetchone()
    finally:
        db.close()
    if not found or found['identity'] != _key(identity(row)):
        return dict(UNCHECKED)
    try:
        report = json.loads(found['payload'])
    except ValueError:
        return dict(UNCHECKED)
    return {**report, 'cached': True, 'checked_at': found['checked']} if isinstance(report, dict) else dict(UNCHECKED)


def all_cached(spec, root):
    """{item_id: report} for every checked film/series (bulk read for catalogue views)."""
    db = _conn(spec, root)
    try:
        out = {}
        for item_id, payload in db.execute('SELECT item_id,payload FROM %s' % spec.checks):
            try:
                report = json.loads(payload)
            except ValueError:
                continue
            if isinstance(report, dict):
                out[item_id] = report
        return out
    finally:
        db.close()


def enrich(spec, root, item_id, settings, *, lookup=None, now=None, force=False):
    now = time.time() if now is None else float(now)
    db = _conn(spec, root)
    try:
        row = subject(spec, db, item_id)
        if row['kind'] == 'channel':
            raise ValueError('Live-Sender haben keine Film- oder Seriendaten')
        meta = identity(row)
        found = db.execute('SELECT checked,identity,payload FROM %s WHERE item_id=?' % spec.checks,
                           (row['id'],)).fetchone()
    finally:
        db.close()   # provider traffic never holds a SQLite connection
    if found and not force and found['identity'] == _key(meta):
        try:
            prev = json.loads(found['payload'])
        except ValueError:
            prev = {}
        if isinstance(prev, dict) and now - found['checked'] < (RETRY_TTL if prev.get('status') == 'partial' else GOOD_TTL):
            return {**prev, 'cached': True, 'checked_at': found['checked']}
    if not meta['title']:
        raise ValueError('%s-Titel ohne Namen' % spec.name)
    if lookup is None:
        import core
        lookup = core.candidates
    info = editorial(row)
    row_arg = {'title': row['title'], 'topic': meta['title'] if meta['kind'] == 'series' else '',
               'duration': row.get('duration'), 'channel': spec.name}
    input_meta = {**meta, 'genres': info['genres'], 'description': info['description']}
    try:
        results = [lookup(row_arg, dict(input_meta), {**dict(settings), '_external_reference_validation': True})]
    except Exception:
        # Never log tokens, provider exceptions, titles or URLs.
        results = [{'candidates': [], 'warnings': ['provider_unavailable'], 'provider_checks': [],
                    'deferred_providers': ['provider_unavailable']}]
    report = shared.analyze(meta, info, results)
    # analyze() labels the portal's own fields 'Netzkino'; name the real source.
    report['field_sources'] = {k: (spec.name if v == 'Netzkino' else v) for k, v in report['field_sources'].items()}
    report.update(title=meta['title'], media_type=meta['kind'], checked_at=now,
                  status_source='local_optional_provider_check')
    db = _conn(spec, root)
    try:
        with db:
            db.execute('''INSERT INTO %s(item_id,checked,identity,payload) VALUES(?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET checked=excluded.checked,identity=excluded.identity,
                payload=excluded.payload''' % spec.checks, (row['id'], now, _key(meta), json.dumps(report, ensure_ascii=False)))
    finally:
        db.close()
    return {**report, 'cached': False}


def pending(spec, root, limit=10, now=None):
    """Current films and series never checked, then stale or partial checks."""
    now = time.time() if now is None else float(now)
    db = _conn(spec, root)
    try:
        last = float(spec.last_success(db) or 0)
        rows = db.execute('''SELECT i.id, r.checked, r.payload FROM %s i
            LEFT JOIN %s r ON r.item_id=i.id
            WHERE i.kind IN ('movie','series') AND i.seen>=? AND (r.item_id IS NULL OR r.checked<?)
            ORDER BY (r.item_id IS NOT NULL), i.title LIMIT ?''' % (spec.items, spec.checks),
                          (last, now - RETRY_TTL, max(1, int(limit)) * 4)).fetchall()
    finally:
        db.close()
    out = []
    for item_id, checked, payload in rows:
        if checked is not None:
            try:
                status = json.loads(payload).get('status')
            except (ValueError, AttributeError):
                status = None
            if status != 'partial' and now - checked < GOOD_TTL:
                continue
        out.append(item_id)
        if len(out) >= limit:
            break
    return out


def metrics(spec, root):
    db = _conn(spec, root)
    try:
        counts = {}
        for payload, in db.execute('SELECT payload FROM %s' % spec.checks):
            try:
                status = json.loads(payload).get('status')
            except (ValueError, AttributeError):
                status = 'invalid'
            counts[status] = counts.get(status, 0) + 1
        return {'checked': sum(counts.values()), 'by_status': counts}
    finally:
        db.close()


def loop(spec, root, settings, slots, stop, *, gap=6.0, idle=1800.0):
    """Background check, one title every `gap` seconds, shares the provider slots."""
    return shared.loop(root, settings, slots, stop, gap=gap, idle=idle,
                       enrich_one=lambda r, i, s, **kw: enrich(spec, r, i, s, **kw),
                       pending_fn=lambda r, *a, **kw: pending(spec, r, *a, **kw), name=spec.key)
