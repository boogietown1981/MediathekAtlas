"""Archive.org-Liste zwischen Installationen austauschen (0.5.92), aus Archive Media.

ArchiveMedia ``catalog_transfer``: what one installation has found on Archive.org can be handed
to another as one file, so the second one does not have to search everything again. The file is
the format ArchiveMedia itself writes and reads (``archivemedia-file-list``, version 1: a ZIP with
``manifest.json``, ``items.jsonl`` and ``files.jsonl``), so lists go both ways between
MediathekAtlas and ArchiveMedia.

Data only: Archive.org identifiers, titles and the publicly listed file names. No videos, no local
paths, no download jobs, no settings, no keys, no work assignments. An import only adds uploads
that are not known yet; nothing existing is changed. Imported uploads are marked as transferred
and unconfirmed until their own data is read from Archive.org.
"""
from __future__ import annotations

import datetime
import json
import re
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath

import portal_sources

FORMAT = 'archivemedia-file-list'
VERSION = 1
ID = re.compile(r'[A-Za-z0-9_.-]{1,130}')
NAMES = {'manifest.json', 'items.jsonl', 'files.jsonl'}
CATEGORIES = {'video', 'audio', 'software', 'documents', 'images', 'other'}
ROLES = {'content', 'derivative', 'technical', 'sidecar', 'auxiliary', 'unknown'}
MAX_UPLOAD = 256 * 1024 * 1024            # one request body; ArchiveMedia allows more, a browser upload here does not
MAX_UNCOMPRESSED = 4 * 1024 ** 3
MAX_LINE = 65536
MAX_ROWS = 50_000_000
EVIDENCE = 'transferred_archive_list'
NOTE = ('Nur Archive-IDs und öffentlich verfügbare Dateimetadaten; keine Downloads, Pfade, Tokens, '
        'Nutzereinstellungen oder Werkzuordnungen.')


def _line(record):
    return (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def _role(variant):
    role = variant.get('technical_role') or 'primary_video'
    if role == 'archive_derivative' or (role == 'primary_video' and str(variant.get('source') or '').lower() != 'original'):
        return 'derivative'
    return 'content' if role == 'primary_video' else 'technical'


def export(c, target, now=None):
    """Write every known Archive.org upload and the video files of the stored manifests to ``target``."""
    target = Path(target)
    items = files = 0
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
        with archive.open('items.jsonl', 'w', force_zip64=True) as stream:
            for external_id, title, year, payload in c.execute(
                    "SELECT external_id,title,year,metadata FROM portal_items WHERE source='internet_archive' ORDER BY external_id"):
                if not ID.fullmatch(str(external_id)):
                    continue
                try:
                    language = str(json.loads(payload).get('language_claim') or '')[:120]
                except (ValueError, AttributeError):
                    language = ''
                stream.write(_line({'id': external_id, 'title': title, 'year': year, 'language': language, 'date': ''}))
                items += 1
        with archive.open('files.jsonl', 'w', force_zip64=True) as stream:
            for external_id, payload in c.execute(
                    """SELECT i.external_id,d.payload FROM portal_archive_details d JOIN portal_items i ON i.id=d.item_id
                       WHERE i.source='internet_archive' ORDER BY i.external_id"""):
                if not ID.fullmatch(str(external_id)):
                    continue
                try:
                    variants = json.loads(payload).get('video_variants') or []
                except (ValueError, AttributeError):
                    continue
                for v in sorted((v for v in variants if isinstance(v, dict) and v.get('filename')), key=lambda v: v['filename']):
                    stream.write(_line({'item_id': external_id, 'filename': v['filename'], 'category': 'video', 'file_role': _role(v),
                                        'source': str(v.get('source') or '')[:120], 'original': str(v.get('original') or '')[:1200],
                                        'format': str(v.get('format') or '')[:160], 'bytes': v.get('size_bytes'),
                                        'duration': v.get('duration_seconds'), 'md5': '', 'sha1': ''}))
                    files += 1
        stamp = datetime.datetime.fromtimestamp(time.time() if now is None else now, datetime.timezone.utc).isoformat()
        archive.writestr('manifest.json', json.dumps({'format': FORMAT, 'schema_version': VERSION, 'created_utc': stamp, 'items': items,
                                                      'files': files, 'notes': NOTE, 'written_by': 'MediathekAtlas'}, ensure_ascii=False, indent=2))
    return {'items': items, 'files': files, 'size_bytes': target.stat().st_size}


def export_bytes(c, now=None):
    with tempfile.TemporaryDirectory(prefix='atlas-list-') as folder:
        target = Path(folder) / 'liste.zip'
        facts = export(c, target, now)
        return target.read_bytes(), facts


def _lines(archive, name):
    with archive.open(name) as entry:
        while True:
            raw = entry.readline(MAX_LINE + 1)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                raise ValueError('Ein Datensatz der Liste ist zu groß')
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError('Die Liste ist beschädigt (ungültige Zeile in %s)' % name) from None
            if not isinstance(record, dict):
                raise ValueError('Die Liste ist beschädigt (ungültiger Datensatz)')
            yield record


def _year(value):
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if 1870 <= n <= 2100 else None


def _item(record):
    ident = record.get('id')
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise ValueError('Ungültige Archive-ID in der Liste')
    title = ' '.join(str(record.get('title') or ident).split())[:240]
    return ident, title if len(title) >= 2 else ident, _year(record.get('year')), ' '.join(str(record.get('language') or '').split())[:120]


def _file(record):
    ident, name = record.get('item_id'), record.get('filename')
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise ValueError('Ungültige Archive-ID bei einer Datei der Liste')
    if not isinstance(name, str) or not name or len(name) > 1200 or '\x00' in name or name.startswith('/') or '..' in PurePosixPath(name).parts:
        raise ValueError('Ungültiger Dateiname in der Liste')
    if record.get('category') not in CATEGORIES or record.get('file_role') not in ROLES:
        raise ValueError('Ungültige Dateikategorie in der Liste')
    return ident


def inspect(archive):
    """Manifest of a list after every safety check that needs no row."""
    infos = archive.infolist()
    if {i.filename for i in infos} != NAMES or len(infos) != 3:
        raise ValueError('Unbekanntes Listenformat: erwartet werden genau manifest.json, items.jsonl und files.jsonl')
    if any(i.flag_bits & 1 for i in infos):
        raise ValueError('Verschlüsselte Listen werden nicht unterstützt')
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise ValueError('Die Liste ist entpackt zu groß')
    if archive.getinfo('manifest.json').file_size > 65536:
        raise ValueError('Das Manifest der Liste ist zu groß')
    try:
        manifest = json.loads(archive.read('manifest.json'))
    except (ValueError, UnicodeError):
        raise ValueError('Das Manifest der Liste ist beschädigt') from None
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('schema_version') != VERSION:
        raise ValueError('Keine Liste aus MediathekAtlas oder ArchiveMedia (Format oder Version unbekannt)')
    for key in ('items', 'files'):
        if type(manifest.get(key)) is not int or not 0 <= manifest[key] <= MAX_ROWS:
            raise ValueError('Ungültige Zeilenanzahl im Manifest der Liste')
    return manifest


def load(c, source, now=None):
    """Add the uploads of a list that are not known yet. The whole list is checked before the first change."""
    source = Path(source)
    if source.stat().st_size > MAX_UPLOAD:
        raise ValueError('Die Liste ist zu groß (höchstens %d MB)' % (MAX_UPLOAD // 1048576))
    now = time.time() if now is None else now
    try:
        archive = zipfile.ZipFile(source, 'r', allowZip64=True)
    except (zipfile.BadZipFile, OSError):
        raise ValueError('Die Datei ist keine Liste (kein ZIP-Archiv)') from None
    with archive:
        manifest = inspect(archive)
        try:
            counted = sum(1 for record in _lines(archive, 'items.jsonl') if _item(record))
            with_files = {}
            listed = 0
            for record in _lines(archive, 'files.jsonl'):
                ident = _file(record)
                listed += 1
                if record['category'] == 'video' and record['file_role'] in ('content', 'derivative'):
                    with_files[ident] = with_files.get(ident, 0) + 1
        except (zipfile.BadZipFile, EOFError, OSError):
            raise ValueError('Die Liste ist beschädigt oder unvollständig') from None
        if counted != manifest['items'] or listed != manifest['files']:
            raise ValueError('Die Liste ist unvollständig (Zeilenanzahl weicht vom Manifest ab)')
        added = 0
        for record in _lines(archive, 'items.jsonl'):
            ident, title, year, language = _item(record)
            row = portal_sources.entry('internet_archive', ident, title, 'https://archive.org/details/' + urllib.parse.quote(ident, safe=''),
                                       year, evidence=EVIDENCE)
            row['language_claim'] = language
            row['language_evidence'] = 'transferred_list' if language else 'unavailable'
            row['transferred'] = True
            row['transferred_video_files'] = with_files.get(ident, 0)
            added += c.execute("""INSERT OR IGNORE INTO portal_items(id,source,external_id,title,title_key,year,page_url,metadata,discovered,updated)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (row['id'], row['source'], row['external_id'], row['title'], portal_sources.title_key(row['title']),
                                                  row.get('year'), row['page_url'], json.dumps(row, ensure_ascii=False), now, now)).rowcount
    return {'ok': True, 'items': manifest['items'], 'files': manifest['files'], 'added': added, 'known': manifest['items'] - added,
            'written_by': str(manifest.get('written_by') or 'ArchiveMedia')[:40],
            'note': 'Übernommene Uploads sind unbestätigt, bis „Fassungen, Folgen und Sprachen prüfen“ ihre Daten von Archive.org liest.'}
