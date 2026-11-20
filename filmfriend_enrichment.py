"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for filmfriend titles (0.6.52).

Same shared implementation as the other platforms (portal_enrichment): no provider-specific matching
code, reports in filmfriend.sqlite3 (table filmfriend_reference_checks), titles already checked on another
platform are reused (reference_share).
"""
from __future__ import annotations

import portal_enrichment as engine
import filmfriend

SPEC = engine.Spec(name='filmfriend', key='filmfriend', items='filmfriend_items', checks='filmfriend_reference_checks',
                   connect=filmfriend._connect, valid_id=lambda v: bool(filmfriend.VALID_ID.fullmatch(v)),
                   last_success=lambda db: filmfriend._get(db, 'last_success', '0'))
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
