"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for TOGGO titles (0.5.79, table toggo_assets since 0.5.87).

Same shared implementation as Pluto TV, JustWatch TV and Rakuten TV (portal_enrichment): no TOGGO-specific
matching code. Reports live in toggo.sqlite3 (table toggo_reference_checks). Björn
(12.11.2026): a film already checked on another platform must not be looked up again; that reuse
belongs into the shared engine, so TOGGO gets it automatically through this Spec.
"""
from __future__ import annotations

import portal_enrichment as engine
import toggo

SPEC = engine.Spec(name='TOGGO', key='toggo', items='toggo_assets', checks='toggo_reference_checks',
                   connect=toggo._connect, valid_id=lambda v: bool(toggo.VALID_ID.fullmatch(v)),
                   last_success=lambda db: toggo._get(db, 'last_success', '0'))
UNCHECKED = engine.UNCHECKED


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
