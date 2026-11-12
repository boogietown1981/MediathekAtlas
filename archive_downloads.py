"""Internet Archive (archive.org) downloads through the shared download queue (0.5.61).

Björn's decision (12.11.2026, decision card): downloads "wie in ArchiveMedia" –
every listed video file can be downloaded; the upload's licence statement
(``rights``/``licenseurl``) is stored with the job and shown, not enforced.

Like Netzkino/Pluto offline copies, an Archive.org file becomes a regular job in
``jobs`` and runs through downloads.run (same folder layout, MKV tagging, NFO,
metadata.json, ``.partial`` staging). Differences:
* no expiry: ``license.kind='archive_item'`` is not an offline kind;
* never announced to the Verbund and never marks a Mediathek work as downloaded
  (``netzkino_downloads.is_portal``);
* subtitle sidecars listed in the item manifest (.srt/.vtt/.ass) are fetched
  next to the video after completion, as ArchiveMedia's ``download_sidecars``.

Only files from the saved, filtered item manifest (``portal_sources``) are
accepted; addresses are built from identifier and file name, never taken from
the browser.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path, PurePosixPath

ORIGIN = 'internet_archive'
LICENSE_KIND = 'archive_item'
SIDECAR_EXT = {'.srt', '.vtt', '.ass', '.ssa', '.sub'}
SIDECAR_MAX = 8 * 1024 * 1024
POLICY = ('Archive.org-Dateien werden dauerhaft gespeichert (wie in ArchiveMedia). '
          'Die Lizenzangabe stammt vom Uploader und wird nicht geprüft.')


def _variant(detail, filename):
    for v in detail.get('video_variants') or []:
        if v.get('filename') == filename:
            return v
    raise ValueError('Datei gehört nicht zu den angezeigten Videodateien dieses Eintrags')


def _int(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError('Staffel/Folge/Jahr müssen Zahlen sein') from None


def metadata(detail, variant, override=None):
    """Metadata for the job; ``override`` = user's corrections (title, year, kind, season, episode)."""
    import core
    o = override if isinstance(override, dict) else {}
    kind = o.get('kind') or variant.get('kind')
    if kind not in ('movie', 'series'):
        kind = 'series' if variant.get('episode') is not None else 'movie'
    title = str(o.get('title') or '').strip()
    if not title:
        title = (detail.get('normalized_title') or detail.get('title') or '') if kind == 'series' or len(detail.get('video_variants') or []) <= 1 \
            else (variant.get('title') or detail.get('normalized_title') or detail.get('title') or '')
    meta = {'kind': kind, 'title': str(title)[:240],
            'year': _int(o.get('year')) if o.get('year') not in (None, '') else detail.get('year'),
            'season': _int(o.get('season')) if o.get('season') not in (None, '') else variant.get('season'),
            'episode': _int(o.get('episode')) if o.get('episode') not in (None, '') else variant.get('episode'),
            'description': str(detail.get('description') or '')[:2000],
            'provider': 'Internet Archive', 'reference_id': None,
            'source_channel': 'Internet Archive'}
    if kind == 'series':
        meta['episode_title'] = str(variant.get('title') or '')[:240] if variant.get('title') != title else ''
    try:
        return core.validate_meta(meta)
    except ValueError as e:
        if kind == 'series' and (meta['season'] is None or meta['episode'] is None):
            raise ValueError('Staffel und Folge dieser Datei sind unbekannt. Bitte beim Herunterladen angeben '
                             '(oder als Film laden).') from None
        raise e


def sidecars(identifier, variant):
    import portal_sources
    out = []
    for s in variant.get('sidecar_subtitles') or []:
        name = s.get('name') if isinstance(s, dict) else None
        try:
            name = portal_sources._safe_archive_filename(name)
        except ValueError:
            continue
        if PurePosixPath(name).suffix.lower() not in SIDECAR_EXT:
            continue
        out.append({'name': name, 'url': portal_sources._archive_video_url(identifier, name)})
    return out[:12]


def build_job(c, download_dir, item_id, filename, override=None, now=None):
    import core, portal_sources
    saved = portal_sources.archive_saved_detail(c, item_id).get('detail')
    if not saved or saved.get('source') != ORIGIN:
        raise ValueError('Bitte erst den Archiv-Dateibestand prüfen')
    identifier = portal_sources.internet_archive_id(saved.get('external_id'))
    filename = portal_sources._safe_archive_filename(filename)
    variant = _variant(saved, filename)
    meta = metadata(saved, variant, override)
    url = portal_sources._archive_video_url(identifier, filename)
    source_id = 'archive:' + identifier + ':' + hashlib.sha1(filename.encode()).hexdigest()[:12]
    target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_download_url': url, 'channel': 'Internet Archive',
              'title': variant.get('title') or saved.get('title'), 'topic': saved.get('title'),
              'duration': variant.get('duration_seconds'), 'size': variant.get('size_bytes'),
              'url_website': saved.get('page_url')}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': ORIGIN, ORIGIN + '_id': item_id,
            'archive_identifier': identifier, 'archive_file': filename,
            'sidecars': sidecars(identifier, variant),
            'license': {'kind': LICENSE_KIND,
                        'rights': str(saved.get('rights') or '')[:500],
                        'license_url': str(saved.get('license_url') or '')[:500],
                        'granted': time.time() if now is None else float(now),
                        'note': 'Lizenzangabe des Uploaders, nicht geprüft (Downloads wie in ArchiveMedia)'}}


def enqueue(c, download_dir, item_id, filename, override=None):
    import netzkino_downloads
    job = build_job(c, download_dir, item_id, filename, override)
    for payload, state in c.execute("SELECT payload,state FROM jobs WHERE state IN ('queued','downloading','tagging','done')"):
        other = json.loads(payload)
        if other.get('origin') == ORIGIN and other.get('archive_identifier') == job['archive_identifier'] \
                and other.get('archive_file') == job['archive_file']:
            return {'id': other.get('id'), 'created': False, 'state': state}
    return netzkino_downloads.insert(c, job)


def fetch_sidecars(job, opener=None):
    """Download listed subtitle files next to the finished video. Never overwrites."""
    import core
    path = Path(job.get('path') or job.get('target') or '')
    if not path.name or not path.parent.is_dir():
        return []
    opener = opener or core.open_url
    saved = []
    for s in job.get('sidecars') or []:
        suffix = PurePosixPath(s.get('name') or '').suffix.lower()
        if suffix not in SIDECAR_EXT:
            continue
        # '<Video>.<Sprache>.srt' if the archive name carries a language tag, else '<Video>.srt'.
        stem = PurePosixPath(s['name']).stem
        lang = stem.rsplit('.', 1)[-1].lower() if '.' in stem else ''
        lang = lang if lang.isalpha() and 2 <= len(lang) <= 3 else ''
        dest = path.with_name(path.stem + ('.' + lang if lang else '') + suffix)
        n = 2
        while dest.exists():
            dest = path.with_name(path.stem + ('.' + lang if lang else '') + '.' + str(n) + suffix)
            n += 1
            if n > 20:
                break
        if dest.exists():
            continue
        try:
            with opener(s['url']) as response:
                data = response.read(SIDECAR_MAX + 1)
            if len(data) > SIDECAR_MAX or b'<html' in data[:300].lower():
                continue
            part = dest.with_name(dest.name + '.partial')
            part.write_bytes(data)
            part.replace(dest)
            saved.append(dest.name)
        except Exception:
            continue
    return saved


def listing(c, item_id=None, limit=50):
    import netzkino_downloads
    out = netzkino_downloads.listing(c, item_id=item_id, limit=limit, origin=ORIGIN)
    out['policy'] = POLICY
    out['offline_days'] = None
    return out
