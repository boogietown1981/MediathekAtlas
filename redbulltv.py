"""Red Bull TV: free films, series and live channels of Red Bull TV (0.6.47).

Björn (20.11.2026, standing order "work until I stop you"): Red Bull TV as a new video source (sports and
adventure documentaries, series, films). Red Bull TV runs on the same Red Bull Media House platform as
ServusTV (``tv-api.redbull.com`` for the catalogue, ``api-player.redbull.com`` for playback, images on
``resources.redbull.tv``), so this module only describes the Red Bull TV tenant and reuses the ServusTV
engine (``servustv.py``): crawl, storage, listing, reference checks, playback with hls_guard.

NOT confirmed by a recording (the cloud build cannot reach redbull.com; checked on Björn's Mac later):

* catalogue scope: ``/rbtv/de/int/`` is tried first, then ``/rbtv/de/de/`` and ``/rbtv/en/int/``; the first
  one whose start page ``discover`` answers is remembered for the next runs (``scope`` in the state);
* player tenant ``rbtv``; if it names no stream the ServusTV tenant ``stv`` is asked as well (both serve
  one video store; the ServusTV player already plays the Red Bull TV live channel);
* web links ``https://www.redbull.com/de-de/tv/video/<id>`` (pattern of the yt-dlp extractor).

If none of the scopes answers, the run fails with a plain message and a ``redbulltv_scope_missing`` entry in
the diagnosis (counts and HTTP status only). The Red Bull TV live channel stays playable through ServusTV in
the Live-TV tab in any case. No offline copies (Red Bull TV offers no downloads), no account, no DRM bypass:
streams with a key are refused by hls_guard.
"""
from __future__ import annotations

import sys

import provider_base
import servustv as engine

KEY = 'redbulltv'
NAME = 'Red Bull TV'
SITE = 'https://www.redbull.com'
SCOPES = ('/rbtv/de/int/', '/rbtv/de/de/', '/rbtv/en/int/')
SEEDS = ('discover',)
VALID_ID = engine.VALID_ID

TENANT = engine.Tenant(
    key=KEY, name=NAME, site=SITE, scopes=SCOPES, seeds=SEEDS, player_tenants=('rbtv', 'stv'),
    table='redbulltv', dbfile='redbulltv.sqlite3', live_fallback=(),
    live_summary='Das laufende Programm von Red Bull TV.',
    web_pattern=(r'https://www\.redbull\.com/[a-z]{2,3}-[a-z]{2}/(?:tv/)?(?:video|videos|episodes|films|live|page)/'
                 r'[A-Za-z0-9:\-]{4,120}(?:/[a-z0-9\-]{1,160})?'),
    web_item='%(site)s/de-de/tv/video/%(id)s', web_home=SITE + '/de-de/tv', web_shows=SITE + '/de-de/tv',
    assumed_scope=True)
T = TENANT


def _connect(root):
    # the engine opens provider_base.connect(root, 'redbulltv.sqlite3') with the Red Bull TV tables
    return engine._connect(root, T)


def _get(db, key, default=''):
    return engine._get(db, key, default)


def _set(db, key, value):
    engine._set(db, key, value)


def sync(root, opener=None, now=None, gap=None, waits=None):
    return engine.sync(root, opener, now, gap, waits, t=T)


def episodes(root, series_id, now=None):
    return engine.episodes(root, series_id, now, t=T)


def listing(root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
    return engine.listing(root, view, query, offset, limit, genre, sort, collection, t=T)


def channels(root):
    return engine.channels(root, t=T)


def item(root, item_id):
    return engine.item(root, item_id, t=T)


def state(root):
    return engine.state(root, t=T)


def set_auto(root, enabled):
    return engine.set_auto(root, enabled, t=T)


def start_sync(root):
    return engine.start_sync(root, t=T)


def should_sync(root, now=None):
    return provider_base.catalog_due(root, sys.modules[__name__], state(root), now)


def loop(root, stop):
    provider_base.loop(root, stop, KEY, sys.modules[__name__])


def own_score(row):
    return None


def play_source(root, item_id, opener=None, check=None, now=None):
    return engine.play_source(root, item_id, opener, check, now, t=T)


def __getattr__(name):
    """``_ACTIVE`` like every platform module (provider_base.running, planner); the flag lives in the engine."""
    if name == '_ACTIVE':
        return engine._active(T)
    raise AttributeError(name)
