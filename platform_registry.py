"""One description per film platform instead of copied routes (0.5.84).

Until 0.5.82 ``server.py`` repeated the same block for every platform: catalogue page, details,
offline list, catalogue run, daily switch, reference check, offline download and two background
threads. A fix had to be made six times and a new platform meant copying forty lines. Here every
platform says once what it consists of; the routes and the threads follow from that.

Addresses, answers and event names are unchanged (``/api/<key>``, ``/api/<key>-details``,
``/api/<key>-downloads``, ``/api/<key>-sync``, ``/api/<key>-auto``, ``/api/<key>-enrich``,
``/api/<key>-download-add``). What only one platform has (YouTube sources and key, Netzkino's own
routes) stays in ``server.py``; such a route is switched off here with its flag.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from types import ModuleType
from typing import Callable, Optional

import diagnostics
import download_quality
import downloads
import netzkino_downloads
import portal_snapshot
import task_control

import netzkino, netzkino_enrichment
import pluto, pluto_downloads, pluto_enrichment
import justwatch, justwatch_downloads, justwatch_enrichment
import rakuten, rakuten_downloads, rakuten_enrichment
import joyn, joyn_enrichment
import toggo, toggo_enrichment
import crunchyroll, crunchyroll_enrichment
import youtube, youtube_downloads, youtube_enrichment


@dataclass(frozen=True)
class Platform:
    key: str
    module: ModuleType                    # state, listing, episodes, item, start_sync, set_auto, loop
    enrichment: ModuleType                # enrich, metrics, loop
    offline: Optional[ModuleType] = None  # enqueue(c, root, download_dir, item_id); None = no offline copies
    page: bool = True                     # GET /api/<key>
    details: bool = True                  # GET /api/<key>-details
    jobs: bool = True                     # GET /api/<key>-downloads
    control: bool = True                  # POST -sync, -auto
    enrich: bool = True                   # POST -enrich
    add: bool = True                      # POST -download-add (needs ``offline``)
    jobs_extra: Optional[Callable] = None  # (root, result) -> None, platform-specific fields of the offline list

    @property
    def name(self):
        return dict(task_control.PORTALS)[self.key]


def _youtube_jobs(root, result):
    switch = youtube_downloads.status(root)
    result['enabled'] = switch['enabled']
    result['tool_hint'] = switch['tool_hint'] if switch['enabled'] else ''


PLATFORMS = (
    # Netzkino came first and keeps its own routes (manual links, recording, grouped view).
    Platform('netzkino', netzkino, netzkino_enrichment, page=False, details=False, jobs=False, control=False, enrich=False, add=False),
    Platform('pluto', pluto, pluto_enrichment, pluto_downloads),
    Platform('justwatch', justwatch, justwatch_enrichment, justwatch_downloads),
    Platform('rakuten', rakuten, rakuten_enrichment, rakuten_downloads),
    # YouTube: the page has extra views (tracks, doubtful) and the download has playlists; both stay in server.py.
    Platform('youtube', youtube, youtube_enrichment, youtube_downloads, page=False, add=False, jobs_extra=_youtube_jobs),
    Platform('joyn', joyn, joyn_enrichment),
    Platform('toggo', toggo, toggo_enrichment),
    # 0.5.96: catalogue with links only (Widevine, subscription since 1.1.2026).
    Platform('crunchyroll', crunchyroll, crunchyroll_enrichment),
)
BY_KEY = {p.key: p for p in PLATFORMS}
KEYS = tuple(p.key for p in PLATFORMS)
MODULES = {p.key: (p.module, p.enrichment) for p in PLATFORMS}


def _split(path):
    """'/api/pluto-details' -> (platform, 'details'); '/api/pluto' -> (platform, '')."""
    if not path.startswith('/api/'):
        return None, ''
    key, _, action = path[5:].partition('-')
    return BY_KEY.get(key), action


def routes():
    """Every address answered here, as (method, path); for tests and the overview in the docs."""
    out = []
    for p in PLATFORMS:
        base = '/api/' + p.key
        if p.page:
            out.append(('GET', base))
        if p.details:
            out.append(('GET', base + '-details'))
        if p.jobs:
            out.append(('GET', base + '-downloads'))
        if p.control:
            out += [('POST', base + '-sync'), ('POST', base + '-auto')]
        if p.enrich:
            out.append(('POST', base + '-enrich'))
        if p.add and p.offline:
            out.append(('POST', base + '-download-add'))
    return out


def serves(method, path):
    return (method, path) in routes()


def handle_get(ctx, path, q):
    """Answer of a platform's read route as (payload, status), or None when the route is not ours."""
    p, action = _split(path)
    if not p:
        return None
    first = lambda name, default='': q.get(name, [default])[0]
    if action == '' and p.page:
        try:
            if first('view') == 'episodes':
                data = p.module.episodes(ctx.root, first('series'))
            else:
                return ctx.portal_page(p.key, p.module, q), 200
        except ValueError as e:
            return {'error': str(e)}, 404
        data['status'] = portal_snapshot.status(p.key, lambda: p.module.state(ctx.root))
        return data, 200
    if action == 'details' and p.details:
        try:
            return p.module.item(ctx.root, first('id')), 200
        except ValueError as e:
            return {'error': str(e)}, 404
    if action == 'downloads' and p.jobs:
        # Platforms without offline copies (Joyn, TOGGO, Crunchyroll) answer with the shared, empty list.
        with ctx.db() as c:
            result = netzkino_downloads.listing(c, item_id=ctx.job_ids(q), origin=p.key)
        result['ffmpeg'] = bool(downloads.tool('ffmpeg'))
        if p.jobs_extra:
            p.jobs_extra(ctx.root, result)
        return result, 200
    return None


def handle_post(ctx, path, d):
    """Answer of a platform's action route as payload, or None when the route is not ours."""
    p, action = _split(path)
    if not p:
        return None
    if action == 'sync' and p.control:
        return {'started': p.module.start_sync(ctx.root)}
    if action == 'auto' and p.control:
        return {'status': p.module.set_auto(ctx.root, d.get('enabled'))}
    if action == 'enrich' and p.enrich:
        with ctx.slots:
            result = p.enrichment.enrich(ctx.root, str(d.get('id', '')), ctx.settings(), force=d.get('force') is True)
        diagnostics.event(p.key + '_reference_check', status=result['status'], candidates=len(result.get('references', [])))
        return result
    if action == 'download-add' and p.add and p.offline:
        item_id = str(d.get('id', ''))
        # Classification and metadata like an ARD/ZDF download: IMDb/TVDB/TMDB check first
        # (cached when fresh). A provider failure never blocks the download.
        try:
            with ctx.slots:
                p.enrichment.enrich(ctx.root, item_id, ctx.settings())
        except Exception as e:
            diagnostics.error(p.key + '_download_enrich_failed', e)
        with ctx.db() as c:
            result = p.offline.enqueue(c, ctx.root, ctx.settings()['download_dir'], item_id)
            download_quality.set_job(c, result, d.get('quality'))
        diagnostics.event(p.key + '_download_enqueued', created=result['created'])
        return result
    return None


def thread_names():
    return [p.key + '_auto_enrichment' for p in PLATFORMS] + [p.key + '_catalog_scheduler' for p in PLATFORMS]


def start_background(ctx, stop):
    """Reference check and daily catalogue run of every platform (two threads each, as before)."""
    started = []
    for p in PLATFORMS:
        # IMDb/TVDB/TMDB/OMDb/Wikidata for every title, automatically and gently.
        t = threading.Thread(target=p.enrichment.loop, args=(ctx.root, ctx.settings, ctx.slots, stop),
                             daemon=True, name=p.key + '_auto_enrichment')
        t.start()
        started.append(t)
    for p in PLATFORMS:
        t = threading.Thread(target=p.module.loop, args=(ctx.root, stop), daemon=True, name=p.key + '_catalog_scheduler')
        t.start()
        started.append(t)
    return started
