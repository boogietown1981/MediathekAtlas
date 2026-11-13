"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for Plex titles (0.5.98).

Same shared implementation as the other platforms (portal_enrichment): no Plex-specific matching
code, reports in plex.sqlite3 (table plex_reference_checks), titles already checked on another
platform are reused (reference_share).
"""
from __future__ import annotations

import portal_enrichment as engine
import plex

SPEC = engine.Spec(name='Plex', key='plex', items='plex_items', checks='plex_reference_checks',
                   connect=plex._connect, valid_id=lambda v: bool(plex.VALID_ID.fullmatch(v)),
                   last_success=lambda db: plex._get(db, 'last_success', '0'))
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
