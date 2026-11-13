"""Was ein Archive.org-Upload außer Videos enthält (0.5.92), aus Archive Media.

Carried over from ArchiveMedia:

* ``bluray_playlist``: a Blu-ray image consists of numbered clips (``BDMV/STREAM/00001.m2ts``) and
  playlists (``BDMV/PLAYLIST/00800.mpls``) that say which clips make up a title, in which order.
  The clips are hidden as technical files; the playlist tells which of them are the main film.
  A playlist proves an order and a running time, not a film title, an episode or a language.
* ``multi_catalog`` with ``catalog_taxonomy``: the audio files, documents and programs of an upload
  with a careful kind (music, audio book, book, comic, Windows program ...) and the reason for it.
* ``catalog_enrichment``: a look-up only by a number the uploader stated (ISBN at Open Library,
  release id at MusicBrainz), on request - never a guess by title.

Nothing here downloads media. ``collect`` works on the manifest alone; the two look-ups fetch a
playlist of at most 256 KiB or one small JSON answer, only when the user asks.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import PurePosixPath

from vendor.archive_portals import bluray_playlist, catalog_enrichment, catalog_taxonomy
from vendor.archive_portals import unified_inventory as inventory

CATEGORIES = ('audio', 'documents', 'software')
LABELS = {'audio': 'Audio', 'documents': 'Dokumente', 'software': 'Programme'}
SUBTYPES = {'music': 'Musik', 'audiobook': 'Hörbuch', 'podcast': 'Podcast', 'radio': 'Radio', 'speech': 'Vortrag', 'unknown': 'nicht zugeordnet',
            'windows': 'Windows', 'macos': 'macOS', 'linux': 'Linux', 'android': 'Android', 'ios': 'iOS', 'multi': 'mehrere Systeme',
            'book': 'Buch', 'pdf': 'PDF', 'ebook': 'E-Book', 'word': 'Textdokument', 'spreadsheet': 'Tabelle', 'presentation': 'Präsentation',
            'text': 'Text', 'comic': 'Comic', 'other': 'gemischte Formate'}
MAX_EXAMPLES = 12
MAX_PLAYLISTS = 60
MAX_CLIPS = 3000
MAX_LOOKUP_BYTES = 384 * 1024
LOOKUP_HOSTS = ('openlibrary.org', 'musicbrainz.org')
PLAYLIST = re.compile(r'(?i)(?:^|/)BDMV/PLAYLIST/(\d{5})\.mpls$')
CLIP = re.compile(r'(?i)(?:^|/)BDMV/STREAM/(\d{5})\.m2ts$')


def _size(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n < 10 ** 15 else None


def _url(identifier, name):
    return 'https://archive.org/download/' + urllib.parse.quote(identifier, safe='') + '/' + '/'.join(
        urllib.parse.quote(part, safe='') for part in name.split('/'))


def collect(identifier, meta, raw_files):
    """Other media, Blu-ray structure and stated numbers of one upload, from its manifest."""
    meta = meta if isinstance(meta, dict) else {}
    groups = {category: [] for category in CATEGORIES}
    playlists, clips = [], {}
    for raw in raw_files:
        if not isinstance(raw, dict) or not isinstance(raw.get('name'), str):
            continue
        name = raw['name'].replace('\\', '/')
        if not name or name.startswith('/') or '\x00' in name or '..' in PurePosixPath(name).parts:
            continue
        hit = PLAYLIST.search(name)
        if hit:
            size = _size(raw.get('size'))
            if size is not None and size <= bluray_playlist.MAX_PLAYLIST_BYTES and len(playlists) < MAX_PLAYLISTS:
                playlists.append({'filename': name, 'number': hit.group(1), 'size_bytes': size, 'folder': name[:hit.start()].strip('/')})
            continue
        hit = CLIP.search(name)
        if hit:
            if len(clips) < MAX_CLIPS:
                clips[name[:hit.start()].strip('/') + '|' + hit.group(1)] = _size(raw.get('size')) or 0
            continue
        category, role, _ = inventory.classify(name, raw)
        if category in groups and role == 'content':
            groups[category].append(raw)
    other = []
    for category in CATEGORIES:
        files = groups[category]
        if not files:
            continue
        subtype, reason = catalog_taxonomy.classify_entry(category, meta, files)
        files.sort(key=lambda f: f['name'].casefold())
        other.append({'category': category, 'label': LABELS[category], 'subtype': subtype, 'subtype_label': SUBTYPES.get(subtype, subtype),
                      'reason': reason, 'files': len(files), 'bytes': sum(_size(f.get('size')) or 0 for f in files),
                      'examples': [{'name': f['name'], 'size_bytes': _size(f.get('size')), 'format': str(f.get('format') or '')[:80],
                                    'url': _url(identifier, f['name'])} for f in files[:MAX_EXAMPLES]]})
    numbers = []
    for category in ('documents', 'audio'):
        provider, value = catalog_enrichment.identifier(meta, category)
        if provider:
            numbers.append({'provider': provider, 'id': value,
                            'label': 'ISBN ' + value if provider == 'openlibrary' else 'MusicBrainz-Veröffentlichung ' + value})
    bluray = None
    if playlists:
        playlists.sort(key=lambda p: (p['folder'], p['number']))
        bluray = {'playlists': playlists, 'clips': len(clips), 'clip_sizes': clips, 'parsed': {},
                  'note': 'Eine Blu-ray-Playlist belegt Reihenfolge und Laufzeit der Clips, nicht Titel, Folge oder Sprache.'}
    return {'other_media': other, 'bluray': bluray, 'external_ids': numbers}


def _read(url, limit, opener=None):
    import core
    with (opener or core.open_url)(url, timeout=18) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Antwort zu groß')
    return raw


def read_playlist(detail, filename, opener=None):
    """Fetch and read one playlist of the stored manifest. Returns its summary; ``detail`` gets it under bluray.parsed."""
    bluray = (detail or {}).get('bluray') or {}
    entry = next((p for p in bluray.get('playlists') or [] if p.get('filename') == filename), None)
    if not entry:
        raise ValueError('Diese Playlist gehört nicht zum gespeicherten Dateibestand')
    try:
        parsed = bluray_playlist.parse_mpls(_read(_url(detail['external_id'], filename), bluray_playlist.MAX_PLAYLIST_BYTES, opener))
    except bluray_playlist.PlaylistError as error:
        raise ValueError('Playlist nicht lesbar: ' + str(error)) from None
    sizes = bluray.get('clip_sizes') or {}
    names = [clip['clip_id'] for clip in parsed['clips']]
    present = [n for n in names if entry['folder'] + '|' + n in sizes]
    summary = {'filename': filename, 'number': entry['number'], 'play_items': parsed['play_items'],
               'duration_seconds': parsed['duration_seconds'], 'distinct_clips': len(set(names)),
               'clips_present': len(set(present)), 'clips_missing': sorted(set(names) - set(present))[:20],
               'bytes': sum(sizes[entry['folder'] + '|' + n] for n in set(present)),
               'clips': [{'clip': c['clip_id'], 'duration_seconds': c['duration_seconds']} for c in parsed['clips'][:40]],
               'warning': parsed['warning']}
    bluray.setdefault('parsed', {})[filename] = summary
    return summary


def main_playlist(detail):
    """The longest playlist read so far whose clips are all in the upload, or None. A hint, not a proof."""
    parsed = ((detail or {}).get('bluray') or {}).get('parsed') or {}
    complete = [p for p in parsed.values() if p['distinct_clips'] and p['clips_present'] == p['distinct_clips']]
    return max(complete, key=lambda p: (p['duration_seconds'], p['filename']))['filename'] if complete else None


def lookup(detail, provider, opener=None):
    """Ask Open Library or MusicBrainz for the number the uploader stated. Never searches by title."""
    entry = next((n for n in (detail or {}).get('external_ids') or [] if n.get('provider') == provider), None)
    if not entry:
        raise ValueError('Dieser Upload nennt keine solche Kennung')

    def fetch(url):
        if urllib.parse.urlsplit(url).hostname not in LOOKUP_HOSTS:
            raise ValueError('Unerwartete Adresse')
        return json.loads(_read(url, MAX_LOOKUP_BYTES, opener))
    found = catalog_enrichment.lookup(provider, entry['id'], fetch=fetch)
    if not found:
        return {'found': False, 'provider': provider, 'id': entry['id']}
    out = {'found': True, 'provider': found['provider'], 'id': entry['id'], 'title': str(found.get('title') or '')[:300]}
    if provider == 'openlibrary':
        out.update(published=str(found.get('publish_date') or '')[:40], pages=found.get('number_of_pages') if isinstance(found.get('number_of_pages'), int) else None,
                   publishers=[str(p)[:120] for p in found.get('publishers') or []][:4])
    else:
        credit = found.get('artist_credit') if isinstance(found.get('artist_credit'), list) else []
        out.update(published=str(found.get('date') or '')[:40], country=str(found.get('country') or '')[:8],
                   artists=[str(a.get('name') or '')[:120] for a in credit if isinstance(a, dict)][:6])
    return out
