"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for Pluto TV titles (0.5.38).

Since 0.5.40 the implementation is the shared portal_enrichment (also used by JustWatch TV);
this module keeps Pluto's public functions. Reports live in pluto.sqlite3 (table
pluto_reference_checks) and feed categories, ratings, the detail view and download metadata
(portal_reference). Films and series are checked; an episode uses its series' report.
"""
from __future__ import annotations

import portal_enrichment as engine
import pluto

SPEC = engine.Spec(name='Pluto TV', key='pluto', items='pluto_items', checks='pluto_reference_checks',
                   connect=pluto._connect, valid_id=lambda v: bool(pluto.VALID_ID.fullmatch(v)),
                   last_success=lambda db: pluto._get(db, 'last_success', '0'))
SCHEMA = SPEC.schema()
GOOD_TTL = engine.GOOD_TTL
RETRY_TTL = engine.RETRY_TTL
UNCHECKED = engine.UNCHECKED


def _conn(root):
    return engine._conn(SPEC, root)


def subject(db, item_id):
    return engine.subject(SPEC, db, item_id)


def cached(root, item_id):
    return engine.cached(SPEC, root, item_id)


def all_cached(root):
    return engine.all_cached(SPEC, root)


def enrich(root, item_id, settings, *, lookup=None, now=None, force=False):
    return engine.enrich(SPEC, root, item_id, settings, lookup=lookup, now=now, force=force)


def pending(root, limit=10, now=None):
    return engine.pending(SPEC, root, limit, now)


def metrics(root):
    return engine.metrics(SPEC, root)


def loop(root, settings, slots, stop, *, gap=6.0, idle=1800.0):
    return engine.loop(SPEC, root, settings, slots, stop, gap=gap, idle=idle)
