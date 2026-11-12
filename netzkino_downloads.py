"""Netzkino offline downloads through the shared MediathekAtlas download queue.

Since 0.5.32 there is exactly one download implementation: a Netzkino title
becomes a regular job in the ``jobs`` table and is processed by the same worker
as Mediathek videos (downloads.run). Therefore Netzkino files get the same
folder layout and names (core.target: ``Filme/<Titel> (<Jahr>)/…mkv`` or
``Serien/<Serie>/Season NN/<Serie> - SxxEyy.mkv``), the same MKV tagging, NFO and
metadata.json sidecars and the same ``.partial`` staging.

Differences to Mediathek jobs, all stored in the job payload:
* ``source._resolver='netzkino'``: the progressive MP4 address is resolved with
  ytdl-nightly (ytdl_bridge) right before the download, never stored in advance;
* ``license.kind='netzkino_offline'``: offline use is limited to OFFLINE_DAYS
  after completion. ``expire()`` then removes the video, its sidecars and
  artwork that only belonged to it, and marks the job ``expired``;
* such jobs are not announced to other Verbund systems and do not mark
  Mediathek works as downloaded.

The 0.5.31.9 "licensed direct file" queue (separate SQLite + worker) is
migrated into the shared queue; explicit user-licensed direct files remain
possible through ``enqueue_file``.
"""
from __future__ import annotations

import ipaddress
import json
import re
import secrets
import sqlite3
import time
import urllib.parse
from pathlib import Path

OFFLINE_DAYS = 30
OFFLINE_SECONDS = OFFLINE_DAYS * 86400
LICENSE_OFFLINE = 'netzkino_offline'
# Streaming portals with time-limited offline copies in the shared queue (0.5.37: Pluto TV).
PORTAL_LICENSES = {'netzkino': LICENSE_OFFLINE, 'pluto': 'pluto_offline', 'justwatch': 'justwatch_offline',
                   'rakuten': 'rakuten_offline'}
# Display name and offline period module per portal (listing policy text).
PORTAL_NAMES = {'netzkino': 'Netzkino', 'pluto': 'Pluto-TV', 'justwatch': 'JustWatch-TV', 'rakuten': 'Rakuten-TV'}
OFFLINE_KINDS = frozenset(PORTAL_LICENSES.values())
LICENSE_FILE = 'licensed_file'
ACTIVE = ('queued', 'downloading', 'tagging')
ID_RE = re.compile(r'^[0-9a-f]{32}$')
EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov'}
RIGHTS = {'rights_holder', 'written_permission', 'public_domain'}
LEGACY_DB = 'netzkino_licensed_downloads.sqlite3'
IMAGE_STEMS = ('poster', 'fanart')
IMAGE_EXT = ('.jpg', '.png')


# ---------------------------------------------------------------- job model
def is_netzkino(job):
    return (job or {}).get('origin') == 'netzkino'


def is_portal(job):
    """Netzkino or Pluto job: per-device copy, never shared in the Verbund, no Mediathek work."""
    return (job or {}).get('origin') in PORTAL_LICENSES


def is_offline(job):
    return ((job or {}).get('license') or {}).get('kind') in OFFLINE_KINDS


def offline_seconds(job):
    try:
        days = int(((job or {}).get('license') or {}).get('days') or OFFLINE_DAYS)
    except (TypeError, ValueError):
        days = OFFLINE_DAYS
    return max(1, min(days, 366)) * 86400


def _people(values):
    out = []
    for v in values or []:
        name = v.get('name') if isinstance(v, dict) else v
        if isinstance(name, str) and name.strip():
            out.append(' '.join(name.split())[:120])
    return out[:20]


def metadata(row, details):
    """Map Netzkino catalogue + public details to the shared metadata schema."""
    import netzkino
    d = {**(details or {})}
    title = ' '.join(str(d.get('title') or row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('Netzkino-Titel ohne Namen')
    media = netzkino.classify_media({'title': title, 'kind': row.get('kind') or 'movie'})
    year = d.get('year') if d.get('year') is not None else row.get('year')
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': year,
            'season': None, 'episode': None,
            'description': d.get('description') or row.get('summary') or '',
            'genres': list(d.get('genres') or [g.strip() for g in (row.get('genres') or '').split(',') if g.strip()])[:12],
            'poster': d.get('poster') or row.get('poster') or '', 'fanart': d.get('backdrop') or '',
            'cast': [{'name': n} for n in _people(d.get('cast'))],
            'directors': _people(d.get('directors')), 'writers': _people(d.get('writers')),
            'provider': 'Netzkino', 'reference_id': d.get('content_id') or row.get('content_id') or None,
            'state': 'manual', 'reason': 'Netzkino-Katalogangaben; Offline-Nutzung zeitlich begrenzt.'}
    # Same rule as for Mediathek videos: series names only with season AND
    # episode. "Folge 3" without a season stays a film-style title instead of
    # inventing "Staffel 1".
    if media['media_type'] == 'episode' and media['season'] and media['episode']:
        meta.update(kind='series', title=media['series_title'], season=media['season'],
                    episode=media['episode'], episode_title=media['episode_title'] or title)
    elif media['media_type'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; ganze Serien werden folgenweise geladen')
    return meta


def build_job(root, download_dir, item_id, *, details_get=None, now=None):
    """Create (but do not store) the shared-queue job for one Netzkino title."""
    import core, netzkino_details, ytdl_bridge
    if not ID_RE.fullmatch(str(item_id or '')):
        raise ValueError('Ungültige Netzkino-Katalogkennung')
    db = netzkino_details._connect(root)
    try:
        row = netzkino_details._find(db, item_id)
    finally:
        db.close()
    page = ytdl_bridge.page_url(row['url'])
    details = (details_get or netzkino_details.get)(root, item_id).get('details') or {}
    report = _report(root, item_id) if details_get is None else None
    # IMDb/TVDB/TMDB/OMDb/Wikidata check (netzkino_enrichment, run right before enqueueing):
    # same classification and metadata as an ARD/ZDF download (canonical genres, cast,
    # poster, NFO ids, rating); Netzkino's own editorial fields keep priority.
    import portal_reference
    meta = portal_reference.apply(metadata(row, details), report, 'Netzkino')
    meta = core.validate_meta(meta)
    source_id = 'netzkino:' + item_id
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'netzkino', '_page_url': page,
              'channel': 'Netzkino', 'title': row['title'],
              'duration': details.get('duration_seconds') or row.get('duration')}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'netzkino', 'netzkino_id': item_id,
            'license': {'kind': LICENSE_OFFLINE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'Netzkino: Download erlaubt, Offline-Nutzung %d Tage' % OFFLINE_DAYS}}


def _report(root, item_id):
    """Cached reference report, or None."""
    try:
        import netzkino_enrichment
        report = netzkino_enrichment.cached(root, item_id)
    except Exception:
        return None
    return report if report.get('status') in ('candidate', 'review', 'no_match', 'partial') else None


def _duplicate(c, job):
    for payload, state in c.execute("SELECT payload,state FROM jobs WHERE state IN ('queued','downloading','tagging','done')"):
        other = json.loads(payload)
        if other.get('target') == job['target']:
            return other.get('id'), state
        if is_netzkino(other) and job.get('netzkino_id') and other.get('netzkino_id') == job['netzkino_id'] \
                and (other.get('license') or {}).get('kind') == job['license']['kind']:
            return other.get('id'), state
    return None


def insert(c, job):
    """Store a job in the shared queue unless the title/file is already there."""
    found = _duplicate(c, job)
    if found:
        return {'id': found[0], 'created': False, 'state': found[1]}
    if __import__('core').existing_download(job['target']):
        raise FileExistsError('Zieldatei existiert bereits – nichts überschrieben')
    c.execute('INSERT INTO jobs VALUES(?,?,?)', (job['id'], json.dumps(job), job['state']))
    __import__('job_queue').supersede(c, job)   # 0.5.43: one card per file
    return {'id': job['id'], 'created': True, 'state': job['state'], 'target': job['target']}


def enqueue(c, root, download_dir, item_id, **kw):
    return insert(c, build_job(root, download_dir, item_id, **kw))


# ------------------------------------------- explicitly licensed direct files
def _safe_host(host):
    h = (host or '').lower().rstrip('.')
    if not h or len(h) > 240 or '.' not in h or h.endswith(('.local', '.internal', '.test', '.localhost')):
        raise ValueError('Nur öffentliche HTTPS-Downloadserver sind erlaubt')
    if any(h == n or h.endswith('.' + n) for n in ('netzkino.de', 'pluto.tv', 'tubitv.com', 'justwatch.com', 'dailymotion.com', 'rakuten.tv')):
        raise ValueError('Für Netzkino-Titel „Offline herunterladen“ verwenden; dieses Feld ist für fremde Lizenzdateien')
    try:
        ipaddress.ip_address(h.strip('[]'))
    except ValueError:
        pass
    else:
        raise ValueError('Direkte IP-Adressen sind nicht gestattet')
    if not re.fullmatch(r'[a-z0-9.-]+', h) or '..' in h:
        raise ValueError('Ungültiger Downloadserver')
    return h


def direct_url(value):
    if not isinstance(value, str) or not (15 <= len(value) <= 1200):
        raise ValueError('Berechtigten direkten Datei-Link angeben')
    try:
        p = urllib.parse.urlsplit(value)
    except ValueError:
        raise ValueError('Ungültige Datei-Adresse') from None
    if (p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password
            or p.query or p.fragment or '\\' in p.path or '%' in p.path):
        raise ValueError('Nur HTTPS-Dateilinks ohne Zugangstoken, Parameter oder Umleitungen')
    _safe_host(p.hostname)
    if Path(p.path).suffix.lower() not in EXTENSIONS or not p.path.startswith('/'):
        raise ValueError('Nur explizite MP4/MKV/WebM/MOV-Dateien; keine Streaming-Playlists')
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, '', ''))


def enqueue_file(c, root, download_dir, item_id, file_url, rights_basis, rights_note,
                 confirmed=False, **kw):
    """User-licensed direct file for a Netzkino title: no expiry, same naming."""
    if confirmed is not True:
        raise ValueError('Ausdrückliche Bestätigung der gesonderten Downloadberechtigung erforderlich')
    if rights_basis not in RIGHTS:
        raise ValueError('Art der separaten Downloadberechtigung fehlt')
    note = ' '.join(str(rights_note or '').split())
    if not 24 <= len(note) <= 600:
        raise ValueError('Konkrete Rechtequelle/Freigabe dokumentieren (mindestens 24 Zeichen)')
    url = direct_url(file_url)
    job = build_job(root, download_dir, item_id, **kw)
    job['source'].pop('_resolver', None)
    job['source']['_download_url'] = url
    job['license'] = {'kind': LICENSE_FILE, 'rights_basis': rights_basis, 'note': note,
                      'granted': job['license']['granted']}
    return insert(c, job)


def migrate_legacy(root, c, download_dir):
    """Move open 0.5.31.9 licensed-file jobs into the shared queue (once, idempotent)."""
    path = Path(root) / LEGACY_DB
    if not path.is_file():
        return 0
    moved = 0
    legacy = sqlite3.connect(str(path), timeout=8)
    legacy.row_factory = sqlite3.Row
    try:
        names = {r[0] for r in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'licensed_netzkino_downloads' not in names:
            return 0
        rows = legacy.execute("""SELECT * FROM licensed_netzkino_downloads
            WHERE state IN ('queued','running','paused','error')""").fetchall()
        for r in rows:
            try:
                enqueue_file(c, root, download_dir, r['netzkino_id'], r['source_url'],
                             r['rights_basis'], r['rights_note'], True,
                             details_get=lambda _r, _i: {'details': {}})
                moved += 1
            except (ValueError, OSError):
                pass  # stays visible in the legacy table; nothing is deleted
            with legacy:
                legacy.execute("UPDATE licensed_netzkino_downloads SET state='migrated' WHERE id=?", (r['id'],))
    finally:
        legacy.close()
    return moved


# ------------------------------------------------------- offline life cycle
def stamp(job, now=None):
    """Called when a job reaches 'done': start the offline period."""
    if is_offline(job) and not job.get('offline_until'):
        now = time.time() if now is None else float(now)
        job['downloaded_at'] = now
        job['offline_until'] = now + offline_seconds(job)
    return job


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except (ValueError, OSError):
        return False


def _has_video(folder):
    return any(p.is_file() and p.suffix.lower() in ('.mkv', '.mp4', '.m4v', '.avi', '.mov', '.webm', '.ts')
               for p in folder.iterdir())


def _drop_artwork(folder, extra=()):
    for stem in IMAGE_STEMS:
        for ext in IMAGE_EXT:
            p = folder / (stem + ext)
            if p.is_file() and not p.is_symlink():
                p.unlink()
    for name in extra:
        p = folder / name
        if p.is_file() and not p.is_symlink():
            p.unlink()


def _rmdir(folder):
    try:
        folder.rmdir()
        return True
    except OSError:
        return False


def remove_files(job):
    """Delete exactly the files this job published; never touch unrelated media."""
    target = Path(job.get('path') or job.get('target') or '')
    root = job.get('root') or ''
    if not target.name or not root or not _inside(target, root):
        return []
    removed = []
    # 0.5.42: films also carry '<Datei>-poster' / '<Datei>-backdrop' next to the video.
    images = [target.with_name(target.stem + tag + ext) for tag in ('-poster', '-backdrop') for ext in IMAGE_EXT]
    for p in (target, target.with_suffix('.nfo'), target.with_suffix('.metadata.json'), *images):
        if p.is_file() and not p.is_symlink():
            p.unlink()
            removed.append(str(p))
    folder = target.parent
    if not folder.is_dir():
        return removed
    if (job.get('metadata') or {}).get('kind') == 'series':
        _rmdir(folder)  # empty season folder
        show = folder.parent
        if show.is_dir() and not any(p.is_dir() for p in show.iterdir()) and not _has_video(show):
            _drop_artwork(show, ('tvshow.nfo',))
            _rmdir(show)
    elif not _has_video(folder):
        _drop_artwork(folder)
        _rmdir(folder)
    return removed


def _finish(c, job, state, now):
    job.update(state=state, expired_at=now, file_state='removed')
    c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), state, job['id']))


def expire(c, now=None):
    """Remove offline copies whose period has ended. Returns the expired job ids."""
    now = time.time() if now is None else float(now)
    done = []
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='done'").fetchall():
        job = json.loads(payload)
        if not is_offline(job):
            continue
        if not job.get('offline_until'):
            stamp(job, now)  # finished without bookkeeping: start now, never early
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job['id']))
            continue
        if job['offline_until'] > now:
            continue
        remove_files(job)
        _finish(c, job, 'expired', now)
        done.append(job['id'])
    return done


def delete_now(c, job_id, now=None):
    """User removes an offline copy before the period ends."""
    r = c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'", (str(job_id),)).fetchone()
    if not r:
        raise ValueError('Nur fertige Offline-Downloads können gelöscht werden')
    job = json.loads(r[0])
    if not is_portal(job):
        raise ValueError('Kein Netzkino- oder Pluto-Download')
    remove_files(job)
    _finish(c, job, 'removed', time.time() if now is None else float(now))
    return {'ok': True, 'state': 'removed'}


def loop(db, stop, interval=3600):
    """Hourly expiry check; also runs right after start."""
    import diagnostics
    while True:
        try:
            with db() as c:
                expired = expire(c)
            if expired:
                diagnostics.event('netzkino_offline_expired', count=len(expired))
        except Exception as exc:  # never stop the service because of cleanup
            diagnostics.error('netzkino_offline_expiry_failed', exc)
        if stop.wait(interval):
            return


# ------------------------------------------------------------- read models
def _public(job, now):
    until = job.get('offline_until')
    return {'id': job['id'], 'netzkino_id': job.get('netzkino_id'), 'pluto_id': job.get('pluto_id'),
            'justwatch_id': job.get('justwatch_id'), 'rakuten_id': job.get('rakuten_id'),
            'origin': job.get('origin'), 'state': job.get('state'),
            'title': (job.get('metadata') or {}).get('title'),
            'target_name': Path(job.get('path') or job.get('target') or '').name,
            'received': job.get('received', 0), 'total': job.get('total', 0),
            'error': '' if job.get('state') == 'done' else job.get('error', ''), 'license': (job.get('license') or {}).get('kind'),
            'offline_until': until,
            'not_before': job.get('not_before') if job.get('state') == 'queued' and float(job.get('not_before') or 0) > now else None,
            'days_left': None if not until else max(0, int((until - now + 86399) // 86400))}


def listing(c, item_id=None, limit=50, now=None, origin='netzkino'):
    now = time.time() if now is None else float(now)
    items = []
    key = origin + '_id'
    # 0.5.45: a series page asks for all its episodes at once (item_id is then a list of ids).
    wanted = set(item_id) if isinstance(item_id, (list, tuple, set)) else ({item_id} if item_id else None)
    if wanted is not None and len(wanted) > 1:
        limit = max(limit, min(len(wanted) * 3, 3000))
    for payload, state in c.execute('SELECT payload,state FROM jobs ORDER BY rowid DESC'):
        job = json.loads(payload)
        if job.get('origin') != origin or (wanted is not None and job.get(key) not in wanted):
            continue
        job['state'] = state
        items.append(_public(job, now))
        if len(items) >= limit:
            break
    days, name = portal_days(origin), PORTAL_NAMES.get(origin, origin)
    return {'items': items, 'offline_days': days,
            'policy': '%s-Titel dürfen heruntergeladen und %d Tage offline genutzt werden; '
                      'danach entfernt MediathekAtlas die Datei automatisch.' % (name, days)}


def portal_days(origin):
    if origin == 'pluto':
        import pluto_downloads
        return pluto_downloads.OFFLINE_DAYS
    if origin == 'justwatch':
        import justwatch_downloads
        return justwatch_downloads.OFFLINE_DAYS
    if origin == 'rakuten':
        import rakuten_downloads
        return rakuten_downloads.OFFLINE_DAYS
    return OFFLINE_DAYS


def portal_duplicate(c, job):
    """Running or finished job for the same file or the same portal title (Pluto, JustWatch …)."""
    key = job['origin'] + '_id'
    for payload, state in c.execute("SELECT payload,state FROM jobs WHERE state IN ('queued','downloading','tagging','done')"):
        other = json.loads(payload)
        if other.get('target') == job['target'] or (other.get('origin') == job['origin'] and other.get(key) == job[key]):
            return {'id': other.get('id'), 'created': False, 'state': state}
    return None


def summary(c, origin='netzkino'):
    counts = {}
    for payload, state in c.execute('SELECT payload,state FROM jobs'):
        if json.loads(payload).get('origin') == origin:
            counts[state] = counts.get(state, 0) + 1
    return {k: counts.get(k, 0) for k in ('queued', 'downloading', 'tagging', 'done', 'error',
                                         'cancelled', 'expired', 'removed')}
