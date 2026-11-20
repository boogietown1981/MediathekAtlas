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
* web links: 0.6.47 guessed ``https://www.redbull.com/de-de/tv/video/<id>``.

0.6.48, checked on Björn's Mac on the live network (20.11.2026): all three scopes answer; ``discover`` names
collections as ``playlists::<uuid>``, ``<uuid>`` or ``rrn:content:collections:<uuid>``; a collection page
(``?offset=0``) carries ``cards`` with ids ``page:rrn:content:films:<uuid>``, ``rrn:content:shows:<uuid>``,
``rrn:content:event-profiles:<uuid>``; ``/products/v5.3/rbtv/de/int/rrn:content:films:<uuid>`` describes a film
(duration in ms, share_url ``https://www.redbull.tv/de/video/<id>/<slug>``); the player answers with
``tenant=rbtv`` (plain HLS on play.redbull.com, no key), ``tenant=stv`` gives 404. The engine (servustv.py)
now accepts these resource names; ServusTV ids are unchanged.

If none of the scopes answers, the run fails with a plain message and a ``redbulltv_scope_missing`` entry in
the diagnosis (counts and HTTP status only). The Red Bull TV live channel stays playable through ServusTV in
the Live-TV tab in any case. No account, no DRM bypass: streams with a key are refused by hls_guard.

0.6.54 (Björn 20.11.2026): Red Bull TV offers no downloads itself; films and episodes without copy protection can be
kept as a private copy for 30 days (redbulltv_downloads.py, same rules as ServusTV), never live channels.
"""
from __future__ import annotations

import sys

import provider_base
import servustv as engine

KEY = 'redbulltv'
NAME = 'Red Bull TV'
SITE = 'https://www.redbull.tv'   # 0.6.48: share_url https://www.redbull.tv/de/video/<rrn id>/<slug> (Björn's Mac)
SCOPES = ('/rbtv/de/int/', '/rbtv/de/de/', '/rbtv/en/int/')
SEEDS = ('discover',)
VALID_ID = engine.VALID_ID

TENANT = engine.Tenant(
    key=KEY, name=NAME, site=SITE, scopes=SCOPES, seeds=SEEDS, player_tenants=('rbtv', 'stv'),
    table='redbulltv', dbfile='redbulltv.sqlite3', live_fallback=(),
    live_summary='Das laufende Programm von Red Bull TV.',
    web_pattern=(r'https://www\.redbull\.(?:tv/[a-z]{2}|com/[a-z]{2,3}-[a-z]{2}/(?:tv/)?)/?(?:video|videos|episodes|episode|films|film|'
                 r'shows|show|live|page)/[A-Za-z0-9:\-]{4,120}(?:/[a-z0-9\-]{1,160})?'),
    web_item='%(site)s/de/video/%(id)s', web_home=SITE + '/de', web_shows=SITE + '/de',
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
