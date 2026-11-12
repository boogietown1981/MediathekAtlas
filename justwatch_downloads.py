"""JustWatch TV offline copies through the shared MediathekAtlas download queue (0.5.40).

Björn (12.11.2026): JustWatch TV's own titles may be kept offline for 30 days. Exactly as for
Pluto TV (pluto_downloads) a film or episode becomes a regular job in the ``jobs`` table: same
worker, folders and names (core.target), MKV, NFO, metadata.json and ``.partial`` staging;
life cycle (offline period, hourly expiry, delete now, no Verbund sharing) in netzkino_downloads.

* Only titles for which JustWatch publishes a stream for external players can be stored.
* ``source._resolver='justwatch'``: the signed address is fetched right before the download,
  checked for copy protection (hls_guard; DRM streams are refused) and never stored.
* The file contains what JustWatch streams, adverts included; nothing is cut out.
"""
from __future__ import annotations

import secrets
import time

import netzkino_downloads as offline

OFFLINE_DAYS = 30
LICENSE = offline.PORTAL_LICENSES['justwatch']
NAME = 'JustWatch TV'


def metadata(row, series=None):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('JustWatch-Titel ohne Namen')
    source = series or row
    genres = [g.strip() for g in str(source.get('genre') or '').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or source.get('poster') or '', 'fanart': '',
            'provider': NAME, 'reference_id': None, 'state': 'manual',
            'reason': 'JustWatch-TV-Katalogangaben; Offline-Nutzung zeitlich begrenzt.'}
    if row.get('imdb_id'):
        meta['imdb_id'] = row['imdb_id']
    if row.get('imdb_score') is not None:
        meta.update(rating=row['imdb_score'], votes=row.get('imdb_votes'), rating_source='IMDb')
    if row.get('kind') == 'episode':
        show = ' '.join(str((series or {}).get('title') or '').split())[:180]
        meta.pop('rating', None)   # the catalogue rating belongs to the series
        if series and series.get('imdb_id'):
            meta['show_imdb_id'] = series['imdb_id']
        # Same rule as Mediathek, Netzkino and Pluto: series layout only with season AND episode.
        if show and row.get('season') is not None and row.get('episode'):
            meta.update(kind='series', title=show, season=int(row['season']), episode=int(row['episode']),
                        episode_title=title, year=None, show_description=series.get('summary') or '')
        elif show:
            meta['title'] = (show + ' - ' + title)[:180]
    return meta


def build_job(root, download_dir, item_id, now=None):
    import core, justwatch, justwatch_enrichment, portal_reference
    if not justwatch.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger JustWatch-Titel')
    db = justwatch._connect(root)
    try:
        row = db.execute('SELECT * FROM justwatch_items WHERE id=?', (item_id,)).fetchone()
        row = dict(row) if row else None
        parent = db.execute('SELECT * FROM justwatch_items WHERE id=?', (row['series_id'],)).fetchone() \
            if row and row['series_id'] else None
        parent = dict(parent) if parent else None
    finally:
        db.close()
    if not row:
        raise ValueError('JustWatch-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Serien werden folgenweise geladen')
    if not row['playable']:
        raise ValueError(justwatch.NOT_PLAYABLE)
    try:
        report = justwatch_enrichment.cached(root, item_id)
    except Exception:
        report = None
    # Classification and metadata like an ARD/ZDF download; JustWatch's own fields keep priority.
    meta = core.validate_meta(portal_reference.apply(metadata(row, parent), report, NAME, series_report=True))
    source_id = 'justwatch:' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'justwatch', '_justwatch_id': item_id, '_justwatch_home': str(root),
              'channel': NAME, 'title': row['title'], 'duration': row['duration']}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'justwatch', 'justwatch_id': item_id,
            'license': {'kind': LICENSE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'JustWatch TV: Download erlaubt, Offline-Nutzung %d Tage' % OFFLINE_DAYS}}


def enqueue(c, root, download_dir, item_id, now=None):
    job = build_job(root, download_dir, item_id, now)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def resolve(row):
    """Fresh, DRM-checked HLS address for downloads.run."""
    import justwatch
    return justwatch.play_source(row['_justwatch_home'], row['_justwatch_id'])['url']
