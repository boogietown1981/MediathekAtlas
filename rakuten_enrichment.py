"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for Rakuten TV titles (0.5.51).

Same shared implementation as Pluto TV and JustWatch TV (portal_enrichment): no Rakuten-specific
matching code. Reports live in rakuten.sqlite3 (table rakuten_reference_checks). Björn
(12.11.2026): a film already checked on another platform must not be looked up again; that reuse
belongs into the shared engine, so Rakuten TV gets it automatically through this Spec.
"""
from __future__ import annotations

import portal_enrichment as engine
import rakuten

SPEC = engine.Spec(name='Rakuten TV', key='rakuten', items='rakuten_items', checks='rakuten_reference_checks',
                   connect=rakuten._connect, valid_id=lambda v: bool(rakuten.VALID_ID.fullmatch(v)),
                   last_success=lambda db: rakuten._get(db, 'last_success', '0'))
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
