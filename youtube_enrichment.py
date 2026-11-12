"""IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for YouTube films and series (0.5.53).

Same shared engine as Pluto TV, JustWatch TV and Rakuten TV (portal_enrichment with
reference_share): a film already checked on another platform is not looked up again. Reports live
in youtube.sqlite3 (table youtube_reference_checks). The cleaned title and the year from the video
title (youtube.clean_title) are the identity; the channel's own words never replace a reference.
"""
from __future__ import annotations

import portal_enrichment as engine
import youtube

SPEC = engine.Spec(name='YouTube', key='youtube', items='youtube_items', checks='youtube_reference_checks',
                   connect=youtube._connect, valid_id=lambda v: bool(youtube.VALID_ID.fullmatch(v)),
                   last_success=lambda db: youtube._get(db, 'last_success', '0'))
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
