"""Rakuten TV offline copies through the shared MediathekAtlas download queue (0.5.51).

Björn (12.11.2026): free Rakuten TV films and series "bei Bedarf offline schauen" (bad internet),
30 days like Netzkino, Pluto TV and JustWatch TV. A film or episode becomes a regular job in the
``jobs`` table: same worker, folders and names (core.target), MKV, NFO, metadata.json and
``.partial`` staging; life cycle (offline period, hourly expiry, delete now) in netzkino_downloads.

* As recorded in Björn's HAR (12.11.2026) Rakuten delivers free films and episodes only with
  Widevine/PlayReady: every such title carries ``drm=1`` and ``build_job`` refuses it with a clear
  reason; nothing is circumvented. Live channels are not storable. The module keeps Rakuten in the
  shared offline life cycle (listing, policy, days) and takes over as soon as Rakuten publishes an
  unprotected stream for a title (``drm=0``).
"""
from __future__ import annotations

import secrets
import time

import netzkino_downloads as offline

OFFLINE_DAYS = 30
LICENSE = offline.PORTAL_LICENSES['rakuten']
NAME = 'Rakuten TV'


def metadata(row, series=None):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('Rakuten-Titel ohne Namen')
    source = series or row
    genres = [g.strip() for g in str(source.get('genre') or '').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or source.get('poster') or '', 'fanart': '',
            'provider': NAME, 'reference_id': None, 'state': 'manual',
            'reason': 'Rakuten-TV-Katalogangaben; Offline-Nutzung zeitlich begrenzt.'}
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


def build_job(root, download_dir, item_id, now=None):
    import core, rakuten, rakuten_enrichment, portal_reference
    if not rakuten.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger Rakuten-Titel')
    db = rakuten._connect(root)
    try:
        row = rakuten._row(db, item_id)
        parent = rakuten._row(db, row['series_id']) if row and row['series_id'] else None
    finally:
        db.close()
    if not row:
        raise ValueError('Rakuten-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Serien werden folgenweise geladen')
    if row['kind'] == 'channel':
        raise ValueError('Live-Sender lassen sich nicht offline speichern')
    if row['drm']:
        raise ValueError(rakuten.DRM_NOTE)
    try:
        report = rakuten_enrichment.cached(root, item_id)
    except Exception:
        report = None
    meta = core.validate_meta(portal_reference.apply(metadata(row, parent), report, NAME, series_report=True))
    source_id = 'rakuten:' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'rakuten', '_rakuten_id': item_id, '_rakuten_home': str(root),
              'channel': NAME, 'title': row['title'], 'duration': row['duration']}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'rakuten', 'rakuten_id': item_id,
            'license': {'kind': LICENSE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'Rakuten TV (kostenlos): Offline-Nutzung %d Tage' % OFFLINE_DAYS}}


def enqueue(c, root, download_dir, item_id, now=None):
    job = build_job(root, download_dir, item_id, now)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def resolve(row):
    """Fresh, copy-protection-checked stream address for downloads.run."""
    import rakuten
    return rakuten.play_source(row['_rakuten_home'], row['_rakuten_id'])['url']
