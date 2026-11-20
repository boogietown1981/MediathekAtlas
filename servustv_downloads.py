"""ServusTV offline copies through the shared MediathekAtlas download queue (0.6.54).

Björn (20.11.2026): "bei redbull und servus tv gibts keine download option, warum?" – until 0.6.53 both had
none, because ServusTV and Red Bull TV offer downloads only inside their own apps. Asked whether a time-limited
copy for private viewing like Pluto TV, Netzkino and Plex should be built, he answered "ja bitte einbauen".

As with Plex (plex_downloads) a film or an episode becomes a regular job in the ``jobs`` table: same worker,
folders and names (core.target), MKV, NFO, metadata.json and ``.partial`` staging; the life cycle (offline
period, hourly expiry, delete now, never shared in the Verbund) is the shared one in netzkino_downloads.
This module serves every tenant of the Red Bull Media House engine (servustv.py); redbulltv_downloads.py
only names the Red Bull TV tenant.

Rules:

* only films and episodes; live channels and whole shows are refused;
* only what the player interface releases at this moment as plain HLS without a key: the title is asked
  fresh (``servustv.play_source``: hls_guard, youth protection hours, geo block, "not yet available");
  a refusal is shown as it is, nothing is circumvented. The Austria-only lists are not in the catalogue;
* the offline period is OFFLINE_DAYS (30, like Pluto TV, Netzkino and Plex). If the player names an end of
  availability, the copy is removed then at the latest (``license.until``, netzkino_downloads.stamp);
* "best" loads up to 1080p H.264 (plays on older Macs and NAS players too); 4K (HEVC) only on request.
* The stream address is fetched fresh when the download starts (``resolve``) and never stored.

NOT confirmed by a recording (the cloud build cannot reach the Red Bull hosts): field names of an availability
end in the player answer (``servustv.END_KEYS``) and the codec ladder of ServusTV; checked on Björn's Mac.
"""
from __future__ import annotations

import secrets
import time

import netzkino_downloads as offline
import servustv as engine

OFFLINE_DAYS = 30
MIN_LEFT = 3600            # a title that ends within the hour is not worth starting
DEFAULT_QUALITY = '1080'   # "best" means up to 1080p H.264 (download_quality / hls_variants.choose prefer)
PREFER_CODEC = 'avc1'
LICENSE = 'servustv_offline'


def license_kind(t):
    return offline.PORTAL_LICENSES[t.key]


def metadata(row, series=None, t=engine.STV):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('%s-Titel ohne Namen' % t.name)
    source = series or row
    genres = [g.strip() for g in str(row.get('genre') or source.get('genre') or '').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or source.get('poster') or '', 'fanart': '',
            'provider': t.name, 'reference_id': None, 'state': 'manual',
            'reason': '%s-Katalogangaben; Offline-Nutzung zeitlich begrenzt.' % t.name}
    if row.get('kind') == 'episode':
        show = ' '.join(str((series or {}).get('title') or '').split())[:180]
        # Same rule as for Mediathek, Netzkino and Plex: series layout only with season AND episode.
        if show and row.get('season') is not None and row.get('episode'):
            meta.update(kind='series', title=show, season=int(row['season']), episode=int(row['episode']),
                        episode_title=title, year=None, show_description=(series or {}).get('summary') or '')
        elif show:
            meta['title'] = (show + ' - ' + title)[:180]
    return meta


def _load(root, item_id, t):
    db = engine._connect(root, t)
    try:
        row = engine._row(db, item_id)
        parent = engine._row(db, row['series_id']) if row and row.get('series_id') else None
    finally:
        db.close()
    return row, parent


def build_job(root, download_dir, item_id, now=None, check=None, t=engine.STV):
    """``check(root, item_id)`` asks the player; default ``servustv.play_source`` for the tenant."""
    import core, hls_guard, portal_reference
    if not engine.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger %s-Titel' % t.name)
    row, parent = _load(root, item_id, t)
    if not row:
        raise ValueError('%s-Titel nicht im Katalog; bitte Katalog neu laden' % t.name)
    if row['kind'] == 'channel' or item_id.startswith('c.'):
        raise ValueError('Live-Sender lassen sich nicht offline speichern')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Sendungen werden folgenweise geladen')
    if row['kind'] not in ('movie', 'episode'):
        raise ValueError('Nur Filme und Folgen lassen sich offline speichern')
    if row['drm'] == 1:
        raise ValueError('%s liefert diesen Titel nur mit Kopierschutz aus; keine Offline-Kopie möglich.' % t.name)
    now = time.time() if now is None else float(now)
    try:
        found = (check or (lambda r, i: engine.play_source(r, i, t=t)))(root, item_id)
    except hls_guard.DrmProtected:
        raise ValueError('%s liefert diesen Titel nur mit Kopierschutz aus; keine Offline-Kopie möglich.' % t.name) from None
    if not isinstance(found, dict) or found.get('live'):
        raise ValueError('Live-Sender lassen sich nicht offline speichern')
    until = found.get('available_until')
    until = float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else None
    if until is not None and until - now < MIN_LEFT:
        raise ValueError('Dieser Titel ist bei %s nur noch kurz verfügbar; eine Offline-Kopie lohnt nicht mehr.' % t.name)
    try:
        report = engine._enrichment(t).cached(root, item_id)
    except Exception:
        report = None
    meta = core.validate_meta(portal_reference.apply(metadata(row, parent, t), report, t.name, series_report=True))
    source_id = t.key + ':' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': t.key, '_rb_id': item_id, '_rb_home': str(root),
              '_prefer_codec': PREFER_CODEC, 'channel': t.name, 'title': row['title'],
              'duration': found.get('duration') or row['duration']}
    lic = {'kind': license_kind(t), 'days': OFFLINE_DAYS, 'granted': now,
           'note': '%s (kostenlos): private Offline-Kopie, %d Tage' % (t.name, OFFLINE_DAYS)}
    if until is not None:
        lic['until'] = until
        lic['note'] += ', höchstens bis zum Verfügbarkeitsende beim Sender'
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': DEFAULT_QUALITY, 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': t.key, t.key + '_id': item_id, 'license': lic}


def enqueue(c, root, download_dir, item_id, now=None, check=None, t=engine.STV):
    job = build_job(root, download_dir, item_id, now, check, t)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def resolve(row, t=engine.STV):
    """Fresh, copy-protection-checked HLS address for downloads.run (never stored in the job)."""
    found = engine.play_source(row['_rb_home'], row['_rb_id'], t=t)
    if found.get('live'):
        raise ValueError('Live-Sender lassen sich nicht offline speichern')
    return found['url']

