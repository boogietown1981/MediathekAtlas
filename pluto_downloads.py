"""Pluto TV offline copies through the shared MediathekAtlas download queue (0.5.37).

Björn (12.11.2026): Pluto titles may be stored offline for 30 days (first stated as 20, corrected the same day). As with Netzkino
(netzkino_downloads) a Pluto film or episode becomes a regular job in the ``jobs`` table:
same worker, same folders and names (core.target), MKV tagging, NFO, metadata.json and
``.partial`` staging. The life cycle (offline period, hourly expiry, delete now, no
Verbund sharing) is the shared one in netzkino_downloads.

* ``source._resolver='pluto'``: the official HLS address (with session) is resolved right
  before the download and fetched with ffmpeg; it is never stored, only its path.
* The file contains what Pluto streams, adverts included; nothing is cut out.
* Live channels cannot be downloaded.
"""
from __future__ import annotations

import secrets
import time

import netzkino_downloads as offline

OFFLINE_DAYS = 30
LICENSE = offline.PORTAL_LICENSES['pluto']


def metadata(row, series_title=''):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('Pluto-Titel ohne Namen')
    genres = [g.strip() for g in str(row.get('genre') or '').replace('&', ',').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or '', 'fanart': '',
            'provider': 'Pluto TV', 'reference_id': None, 'state': 'manual',
            'reason': 'Pluto-TV-Katalogangaben; Offline-Nutzung zeitlich begrenzt.'}
    if row.get('kind') == 'episode':
        show = ' '.join(str(series_title or '').split())[:180]
        # Same rule as for Mediathek and Netzkino: series layout only with season AND episode.
        if show and row.get('season') is not None and row.get('episode'):
            meta.update(kind='series', title=show, season=int(row['season']), episode=int(row['episode']),
                        episode_title=title, year=None)
        elif show:
            meta['title'] = (show + ' - ' + title)[:180]
    return meta


def build_job(root, download_dir, item_id, now=None):
    import core, pluto
    if not pluto.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Pluto-Titel')
    db = pluto._connect(root)
    try:
        row = db.execute('SELECT * FROM pluto_items WHERE id=?', (item_id,)).fetchone()
        row = dict(row) if row else None
        parent = db.execute('SELECT title,poster,genre FROM pluto_items WHERE id=?',
                            (row['series_id'],)).fetchone() if row and row['series_id'] else None
    finally:
        db.close()
    if not row:
        raise ValueError('Pluto-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'channel':
        raise ValueError('Live-Sender können nicht heruntergeladen werden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Serien werden folgenweise geladen')
    if not row['path']:
        raise ValueError('Für diesen Pluto-Titel ist keine Wiedergabe hinterlegt')
    if parent and not row['poster']:
        row['poster'] = parent['poster']
    if parent and not row['genre']:
        row['genre'] = parent['genre']
    import pluto_enrichment, portal_reference
    try:
        report = pluto_enrichment.cached(root, item_id)
    except Exception:
        report = None
    # Same classification and metadata as an ARD/ZDF download (canonical genres, cast, poster,
    # NFO ids, rating) from the IMDb/TVDB/TMDB check; Pluto's own fields keep priority.
    meta = core.validate_meta(portal_reference.apply(metadata(row, parent['title'] if parent else ''),
                                                     report, 'Pluto TV', series_report=True))
    source_id = 'pluto:' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'pluto', '_pluto_id': item_id, '_pluto_home': str(root),
              'channel': 'Pluto TV', 'title': row['title'], 'duration': row['duration']}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'pluto', 'pluto_id': item_id,
            'license': {'kind': LICENSE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'Pluto TV: Download erlaubt, Offline-Nutzung %d Tage' % OFFLINE_DAYS}}


def enqueue(c, root, download_dir, item_id, now=None):
    job = build_job(root, download_dir, item_id, now)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def resolve(row):
    """HLS address for downloads.run (session is fetched/renewed as needed)."""
    import pluto
    return pluto.play_source(row['_pluto_home'], row['_pluto_id'])['url']
