"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for Pluto TV titles (0.5.38).

Same provider chain and evaluation as Netzkino (netzkino_enrichment.analyze over
core.candidates): conservative, a unique eligible reference only, Pluto's own catalogue
fields keep priority. Reports live in pluto.sqlite3 (table pluto_reference_checks) and feed
categories, ratings, the detail view and download metadata (portal_reference).
Films and series are checked; an episode uses its series' report.
"""
from __future__ import annotations

import json
import time

import netzkino_enrichment as shared
import pluto
import portal_reference

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pluto_reference_checks(
  item_id TEXT PRIMARY KEY, checked REAL NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS pluto_ref_checked ON pluto_reference_checks(checked);
'''
GOOD_TTL = shared.GOOD_TTL
RETRY_TTL = shared.RETRY_TTL
UNCHECKED = {'status': 'unchecked', 'metadata': {}, 'references': [], 'cached': False}


def _conn(root):
    db = pluto._connect(root)
    db.executescript(SCHEMA)
    return db


def _row(db, item_id):
    if not pluto.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Pluto-Titel')
    row = db.execute('SELECT * FROM pluto_items WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise ValueError('Pluto-Titel nicht im Katalog; bitte Katalog neu laden')
    return dict(row)


def subject(db, item_id):
    """Title whose report applies: an episode uses its series."""
    row = _row(db, item_id)
    if row['kind'] == 'episode' and row.get('series_id'):
        parent = db.execute('SELECT * FROM pluto_items WHERE id=?', (row['series_id'],)).fetchone()
        if parent:
            return dict(parent)
    return row


def _identity(row):
    kind = 'series' if row['kind'] in ('series', 'episode') else 'movie'
    return {'kind': kind, 'title': shared._str(row.get('title'), 240),
            'year': shared._integer(row.get('year'), 1880, 2100) if kind == 'movie' else None,
            'season': None, 'episode': None, 'episode_title': ''}


def _editorial(row):
    return {'title': row.get('title') or '', 'year': row.get('year'), 'duration_seconds': row.get('duration'),
            'description': row.get('summary') or '', 'genres': portal_reference.split_labels(row.get('genre')),
            'poster': row.get('poster') or ''}


def _key(meta):
    return json.dumps([meta['kind'], meta['title'], meta['year']], ensure_ascii=False)


def cached(root, item_id):
    """Stored report for a title (episodes: their series), no provider traffic."""
    db = _conn(root)
    try:
        row = subject(db, item_id)
        found = db.execute('SELECT checked,identity,payload FROM pluto_reference_checks WHERE item_id=?',
                           (row['id'],)).fetchone()
    finally:
        db.close()
    if not found or found['identity'] != _key(_identity(row)):
        return dict(UNCHECKED)
    try:
        report = json.loads(found['payload'])
    except ValueError:
        return dict(UNCHECKED)
    return {**report, 'cached': True, 'checked_at': found['checked']} if isinstance(report, dict) else dict(UNCHECKED)


def all_cached(root):
    """{item_id: report} for every checked film/series (bulk read for catalogue views)."""
    db = _conn(root)
    try:
        out = {}
        for item_id, payload in db.execute('SELECT item_id,payload FROM pluto_reference_checks'):
            try:
                report = json.loads(payload)
            except ValueError:
                continue
            if isinstance(report, dict):
                out[item_id] = report
        return out
    finally:
        db.close()


def enrich(root, item_id, settings, *, lookup=None, now=None, force=False):
    now = time.time() if now is None else float(now)
    db = _conn(root)
    try:
        row = subject(db, item_id)
        if row['kind'] == 'channel':
            raise ValueError('Live-Sender haben keine Film- oder Seriendaten')
        meta = _identity(row)
        found = db.execute('SELECT checked,identity,payload FROM pluto_reference_checks WHERE item_id=?',
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
        raise ValueError('Pluto-Titel ohne Namen')
    if lookup is None:
        import core
        lookup = core.candidates
    editorial = _editorial(row)
    row_arg = {'title': row['title'], 'topic': meta['title'] if meta['kind'] == 'series' else '',
               'duration': row.get('duration'), 'channel': 'Pluto TV'}
    input_meta = {**meta, 'genres': editorial['genres'], 'description': editorial['description']}
    try:
        results = [lookup(row_arg, dict(input_meta), {**dict(settings), '_external_reference_validation': True})]
    except Exception:
        # Never log tokens, provider exceptions, titles or URLs.
        results = [{'candidates': [], 'warnings': ['provider_unavailable'], 'provider_checks': [],
                    'deferred_providers': ['provider_unavailable']}]
    report = shared.analyze(meta, editorial, results)
    # analyze() labels the portal's own fields 'Netzkino'; name the real source.
    report['field_sources'] = {k: ('Pluto TV' if v == 'Netzkino' else v) for k, v in report['field_sources'].items()}
    report.update(title=meta['title'], media_type=meta['kind'], checked_at=now,
                  status_source='local_optional_provider_check')
    db = _conn(root)
    try:
        with db:
            db.execute('''INSERT INTO pluto_reference_checks(item_id,checked,identity,payload) VALUES(?,?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET checked=excluded.checked,identity=excluded.identity,
                payload=excluded.payload''', (row['id'], now, _key(meta), json.dumps(report, ensure_ascii=False)))
    finally:
        db.close()
    return {**report, 'cached': False}


def pending(root, limit=10, now=None):
    """Current films and series never checked, then stale or partial checks."""
    now = time.time() if now is None else float(now)
    db = _conn(root)
    try:
        last = float(pluto._get(db, 'last_success', '0') or 0)
        rows = db.execute('''SELECT i.id, r.checked, r.payload FROM pluto_items i
            LEFT JOIN pluto_reference_checks r ON r.item_id=i.id
            WHERE i.kind IN ('movie','series') AND i.seen>=? AND (r.item_id IS NULL OR r.checked<?)
            ORDER BY (r.item_id IS NOT NULL), i.title LIMIT ?''', (last, now - RETRY_TTL, max(1, int(limit)) * 4)).fetchall()
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


def metrics(root):
    db = _conn(root)
    try:
        counts = {}
        for payload, in db.execute('SELECT payload FROM pluto_reference_checks'):
            try:
                status = json.loads(payload).get('status')
            except (ValueError, AttributeError):
                status = 'invalid'
            counts[status] = counts.get(status, 0) + 1
        return {'checked': sum(counts.values()), 'by_status': counts}
    finally:
        db.close()


def loop(root, settings, slots, stop, *, gap=6.0, idle=1800.0):
    """Background check, one title every `gap` seconds, shares the provider slots."""
    return shared.loop(root, settings, slots, stop, gap=gap, idle=idle, enrich_one=enrich,
                       pending_fn=pending, name='pluto')
