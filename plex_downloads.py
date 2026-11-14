"""Plex offline copies through the shared MediathekAtlas download queue (0.6.3).

Björn (14.11.2026): a free Plex film plays in MediathekAtlas, "aber ich kann nicht offline in den
30 tage sicherung aufnehmen". Like Pluto TV, JustWatch TV and Rakuten TV a Plex film or episode
becomes a regular job in the ``jobs`` table: same worker, folders and names (core.target), MKV,
NFO, metadata.json and ``.partial`` staging; life cycle (30 days, hourly expiry, delete now) in
netzkino_downloads.

* Only titles without copy protection: ``drm=1`` is refused with the usual note, an unchecked title
  (``drm=-1``) is checked through ``plex.play_source`` first, which marks it. Nothing is circumvented.
* Series are loaded episode by episode; live channels are not storable.
* The stream address carries a temporary Plex token; it is fetched fresh when the download starts
  (``resolve``) and never stored in the job.
"""
from __future__ import annotations

import secrets
import time

import netzkino_downloads as offline

OFFLINE_DAYS = 30
LICENSE = offline.PORTAL_LICENSES['plex']
NAME = 'Plex'


def metadata(row, series=None):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('Plex-Titel ohne Namen')
    source = series or row
    genres = [g.strip() for g in str(source.get('genre') or row.get('genre') or '').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or source.get('poster') or '', 'fanart': '',
            'provider': NAME, 'reference_id': None, 'state': 'manual',
            'reason': 'Plex-Katalogangaben; Offline-Nutzung zeitlich begrenzt.'}
    if row.get('imdb_id'):
        meta['imdb_id'] = row['imdb_id']
    if row.get('imdb_score') is not None:
        meta.update(rating=row['imdb_score'], votes=row.get('imdb_votes'), rating_source='IMDb')
    if row.get('kind') == 'episode':
        show = ' '.join(str((series or {}).get('title') or '').split())[:180]
        meta.pop('rating', None)
        if series and series.get('imdb_id'):
            meta['show_imdb_id'] = series['imdb_id']
        if show and row.get('season') is not None and row.get('episode'):
            meta.update(kind='series', title=show, season=int(row['season']), episode=int(row['episode']),
                        episode_title=title, year=None, show_description=series.get('summary') or '')
        elif show:
            meta['title'] = (show + ' - ' + title)[:180]
    return meta


def _load(root, item_id):
    import plex
    db = plex._connect(root)
    try:
        row = plex._row(db, item_id)
        parent = plex._row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    return row, parent


def build_job(root, download_dir, item_id, now=None, check=None):
    """``check(root, item_id)`` verifies an unchecked title; default ``plex.play_source``."""
    import core, hls_guard, plex, plex_enrichment, portal_reference
    if not plex.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Plex-Titel')
    row, parent = _load(root, item_id)
    if not row:
        raise ValueError('Plex-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Serien werden folgenweise geladen')
    if row['kind'] == 'channel':
        raise ValueError('Live-Sender lassen sich nicht offline speichern')
    if row['drm'] == 1:
        raise ValueError(plex.DRM_NOTE)
    if row['drm'] != 0:
        try:
            (check or plex.play_source)(root, item_id)
        except hls_guard.DrmProtected:
            raise ValueError(plex.DRM_NOTE) from None
    try:
        report = plex_enrichment.cached(root, item_id)
    except Exception:
        report = None
    meta = core.validate_meta(portal_reference.apply(metadata(row, parent), report, NAME, series_report=True))
    source_id = 'plex:' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'plex', '_plex_id': item_id, '_plex_home': str(root),
              'channel': NAME, 'title': row['title'], 'duration': row['duration']}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'plex', 'plex_id': item_id,
            'license': {'kind': LICENSE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'Plex (kostenlos): Offline-Nutzung %d Tage' % OFFLINE_DAYS}}


def enqueue(c, root, download_dir, item_id, now=None):
    job = build_job(root, download_dir, item_id, now)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def resolve(row):
    """Fresh, copy-protection-checked stream address (HLS or DASH) for downloads.run."""
    import plex
    return plex.play_source(row['_plex_home'], row['_plex_id'])['url']
