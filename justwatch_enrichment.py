"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for JustWatch TV titles (0.5.40).

Same shared implementation as Pluto TV (portal_enrichment). Reports live in
justwatch.sqlite3 (table justwatch_reference_checks). JustWatch's own IMDb id and rating are
kept from the catalogue (justwatch.own_score, justwatch_downloads); the check adds the
canonical genres, cast, directors and artwork like for every other source.
"""
from __future__ import annotations

import portal_enrichment as engine
import justwatch

SPEC = engine.Spec(name='JustWatch TV', key='justwatch', items='justwatch_items', checks='justwatch_reference_checks',
                   connect=justwatch._connect, valid_id=lambda v: bool(justwatch.VALID_ID.fullmatch(v)),
                   last_success=lambda db: justwatch._get(db, 'last_success', '0'))
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
