"""Provider answers shared between the film platforms (0.5.49).

Björn (12.11.2026): "wenn wir auf einer Plattform schon Daten zu einem Film geladen bzw.
abgeglichen haben, dann brauchen wir diese nicht nochmal bei einer anderen Plattform abfragen" –
free films overlap between Netzkino, Pluto TV, JustWatch TV (and further sources). The IMDb/TVDB/
TMDB/OMDb/Wikidata answer for one work (kind, normalised title, year) is stored once in
``reference_share.sqlite3``; the next platform evaluates the stored answer with its own catalogue
fields (netzkino_enrichment.analyze) instead of asking the providers again.

Only complete answers are kept (no provider unavailable/deferred), only for titles with a year
(without it two different films of the same name would be mixed), for GOOD_TTL like the reports.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

TTL = 30 * 86400
MAX_PAYLOAD = 400_000


def _connect(root):
    db = sqlite3.connect(Path(root) / 'reference_share.sqlite3', timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS shared_lookups(key TEXT PRIMARY KEY, stored REAL NOT NULL, '
               'source TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


def key(meta):
    """'' when the title must not be shared (no year, no title, unknown kind)."""
    kind, year = (meta or {}).get('kind'), (meta or {}).get('year')
    raw = unicodedata.normalize('NFKD', str((meta or {}).get('title') or '').casefold())
    title = re.sub(r'[^a-z0-9]+', ' ', ''.join(ch for ch in raw if not unicodedata.combining(ch))).strip()
    if kind not in ('movie', 'series') or not title or not isinstance(year, int):
        return ''
    return '|'.join([kind, title, str(year), str(meta.get('season') or ''), str(meta.get('episode') or '')])


def _complete(result):
    return (isinstance(result, dict) and not result.get('deferred_providers')
            and 'provider_unavailable' not in (result.get('warnings') or []))


def get(root, meta, now=None):
    k = key(meta)
    if not k:
        return None
    now = time.time() if now is None else float(now)
    try:
        db = _connect(root)
        try:
            row = db.execute('SELECT stored,source,payload FROM shared_lookups WHERE key=?', (k,)).fetchone()
        finally:
            db.close()
        if not row or now - row[0] > TTL:
            return None
        result = json.loads(row[2])
    except (sqlite3.Error, ValueError, OSError):
        return None
    return {**result, 'shared_from': row[1]} if isinstance(result, dict) else None


def put(root, meta, result, source, now=None):
    k = key(meta)
    if not k or not _complete(result):
        return False
    try:
        payload = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    if len(payload) > MAX_PAYLOAD:
        return False
    try:
        db = _connect(root)
        try:
            with db:
                db.execute('INSERT OR REPLACE INTO shared_lookups VALUES(?,?,?,?)',
                           (k, time.time() if now is None else float(now), str(source)[:40], payload))
        finally:
            db.close()
    except (sqlite3.Error, OSError):
        return False
    return True


def wrap(root, lookup, source, *, now=None, fresh=False):
    """Provider lookup that answers from the shared store first. ``fresh`` (the user pressed
    "Jetzt abgleichen") always asks the providers and renews the stored answer."""
    def shared(row, meta, settings):
        if not fresh:
            hit = get(root, meta, now)
            if hit is not None:
                return hit
        result = lookup(row, meta, settings)
        put(root, meta, result, source, now)
        return result
    return shared


def stats(root):
    try:
        db = _connect(root)
        try:
            return {'stored': db.execute('SELECT COUNT(*) FROM shared_lookups').fetchone()[0],
                    'by_source': dict(db.execute('SELECT source,COUNT(*) FROM shared_lookups GROUP BY source'))}
        finally:
            db.close()
    except (sqlite3.Error, OSError):
        return {'stored': 0, 'by_source': {}}
