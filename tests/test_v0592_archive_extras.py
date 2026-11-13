"""0.5.92: Blu-ray-Playlists, weitere Inhalte und Kennungen eines Archive.org-Uploads
(ArchiveMedia bluray_playlist, multi_catalog, catalog_taxonomy, catalog_enrichment)."""
import io
import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_extras as extras  # noqa: E402
import portal_sources  # noqa: E402
from tests._wiring import wired  # noqa: E402


def mpls(clips):
    """A minimal playlist: (clip number, seconds) per play item."""
    items = b''
    for clip, seconds in clips:
        block = ('%05d' % clip).encode() + b'M2TS' + b'\x00' * 3 + struct.pack('>II', 45000 * 10, 45000 * (10 + seconds))
        items += struct.pack('>H', len(block)) + block
    body = b'\x00\x00' + struct.pack('>H', len(clips)) + b'\x00\x00' + items
    return b'MPLS0200' + struct.pack('>I', 40) + b'\x00' * 28 + struct.pack('>I', len(body)) + body


def upload(extra_meta=None, extra_files=()):
    doc = {'metadata': {'identifier': 'bd_film', 'title': 'Ein Film (Blu-ray)', 'mediatype': 'movies', 'uploader': 'x@example.org', **(extra_meta or {})},
           'files': [{'name': 'DISC1/BDMV/PLAYLIST/00800.mpls', 'size': '300'}, {'name': 'DISC1/BDMV/PLAYLIST/00001.mpls', 'size': '200'},
                     {'name': 'DISC1/BDMV/PLAYLIST/99999.mpls', 'size': '99999999'},
                     {'name': 'DISC1/BDMV/STREAM/00001.m2ts', 'size': '20000000000', 'length': '5000'},
                     {'name': 'DISC1/BDMV/STREAM/00002.m2ts', 'size': '9000000000', 'length': '2000'},
                     {'name': 'DISC1/BDMV/STREAM/00003.m2ts', 'size': '9000000', 'length': '40'},
                     {'name': 'film.mkv', 'size': '900000000', 'length': '6000', 'source': 'original'}, *extra_files]}
    return portal_sources.archive_detail_document('bd_film', doc)


class Opener:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def __call__(self, url, timeout=0):
        self.asked.append(url)
        answer = self.answers[url.rsplit('/', 1)[-1]]
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer)


class BlurayTests(unittest.TestCase):
    def test_structure_from_the_manifest(self):
        detail = upload()
        b = detail['bluray']
        self.assertEqual([(p['number'], p['folder']) for p in b['playlists']], [('00001', 'DISC1'), ('00800', 'DISC1')])  # the oversized one is left out
        self.assertEqual((b['clips'], b['clip_sizes']['DISC1|00002'], b['parsed']), (3, 9000000000, {}))
        self.assertEqual([v['filename'] for v in detail['video_variants']], ['film.mkv'])
        self.assertIsNone(portal_sources.archive_detail_document('ohne', {'metadata': {'title': 'Ohne Blu-ray'}, 'files': [{'name': 'a.mkv', 'size': '900000000', 'length': '6000'}]})['bluray'])

    def test_reading_playlists_and_the_main_title(self):
        detail = upload()
        opener = Opener({'00800.mpls': mpls([(1, 5000), (2, 2000)]), '00001.mpls': mpls([(3, 40)])})
        first = extras.read_playlist(detail, 'DISC1/BDMV/PLAYLIST/00001.mpls', opener)
        self.assertEqual((first['play_items'], first['duration_seconds'], first['clips_present'], first['bytes']), (1, 40.0, 1, 9000000))
        self.assertEqual(extras.main_playlist(detail), 'DISC1/BDMV/PLAYLIST/00001.mpls')
        main = extras.read_playlist(detail, 'DISC1/BDMV/PLAYLIST/00800.mpls', opener)
        self.assertEqual((main['play_items'], main['duration_seconds'], main['distinct_clips'], main['clips_present'], main['clips_missing'], main['bytes']),
                         (2, 7000.0, 2, 2, [], 29000000000))
        self.assertEqual([c['clip'] for c in main['clips']], ['00001', '00002'])
        self.assertEqual(extras.main_playlist(detail), 'DISC1/BDMV/PLAYLIST/00800.mpls')
        self.assertEqual(opener.asked[0], 'https://archive.org/download/bd_film/DISC1/BDMV/PLAYLIST/00001.mpls')
        json.dumps(detail)   # stays storable

    def test_missing_clips_and_refusals(self):
        detail = upload()
        opener = Opener({'00800.mpls': mpls([(1, 5000), (7, 9000)]), '00001.mpls': b'kein mpls' * 10})
        partial = extras.read_playlist(detail, 'DISC1/BDMV/PLAYLIST/00800.mpls', opener)
        self.assertEqual((partial['clips_present'], partial['clips_missing']), (1, ['00007']))
        self.assertIsNone(extras.main_playlist(detail))   # a title with missing clips is no candidate
        with self.assertRaisesRegex(ValueError, 'nicht lesbar'):
            extras.read_playlist(detail, 'DISC1/BDMV/PLAYLIST/00001.mpls', opener)
        for name in ('DISC1/BDMV/PLAYLIST/99999.mpls', '../../etc/passwd', 'film.mkv', ''):
            with self.assertRaisesRegex(ValueError, 'gehört nicht'):
                extras.read_playlist(detail, name, opener)
        self.assertEqual(len(opener.asked), 2)
        big = Opener({'00800.mpls': b'M' * (extras.bluray_playlist.MAX_PLAYLIST_BYTES + 5)})
        with self.assertRaisesRegex(ValueError, 'zu groß'):
            extras.read_playlist(detail, 'DISC1/BDMV/PLAYLIST/00800.mpls', big)


class OtherMediaTests(unittest.TestCase):
    def test_kinds_with_reasons(self):
        detail = upload({'artist': 'Orchester', 'isbn': '978-3-16-148410-0'},
                        [{'name': 'ost/02 Finale.flac', 'size': '40000000', 'format': 'Flac'}, {'name': 'ost/01 Thema.flac', 'size': '30000000'},
                         {'name': 'Begleitbuch.pdf', 'size': '500000'}, {'name': 'Begleitbuch.epub', 'size': '300000'},
                         {'name': 'setup.exe', 'size': '1000'}, {'name': 'app.dmg', 'size': '2000'},
                         {'name': 'bd_film_meta.xml', 'size': '10'}, {'name': 'cover.jpg', 'size': '10'}, {'name': 'film.srt', 'size': '10'},
                         {'name': '../boese.pdf', 'size': '10'}])
        groups = {g['category']: g for g in detail['other_media']}
        self.assertEqual({k: (g['subtype'], g['subtype_label'], g['files']) for k, g in groups.items()},
                         {'audio': ('music', 'Musik', 2), 'documents': ('book', 'Buch', 2), 'software': ('multi', 'mehrere Systeme', 2)})
        self.assertEqual((groups['audio']['bytes'], [e['name'] for e in groups['audio']['examples']]), (70000000, ['ost/01 Thema.flac', 'ost/02 Finale.flac']))
        self.assertEqual(groups['audio']['examples'][0]['url'], 'https://archive.org/download/bd_film/ost/01%20Thema.flac')
        self.assertIn('Künstler', groups['audio']['reason'])
        self.assertEqual(detail['external_ids'], [{'provider': 'openlibrary', 'id': '9783161484100', 'label': 'ISBN 9783161484100'}])
        self.assertNotIn('example.org', json.dumps(detail))
        plain = upload()
        self.assertEqual((plain['other_media'], plain['external_ids']), ([], []))

    def test_many_files_are_counted_not_listed(self):
        detail = upload(None, [{'name': 'cd/%03d.mp3' % n, 'size': '1000'} for n in range(40)])
        group = detail['other_media'][0]
        self.assertEqual((group['files'], len(group['examples']), group['subtype']), (40, extras.MAX_EXAMPLES, 'unknown'))

    def test_lookup_only_by_the_stated_number(self):
        detail = upload({'isbn': '9783161484100', 'musicbrainz_releaseid': '0A1B2C3D-0000-4000-8000-000000000001'},
                        [{'name': 'Buch.pdf', 'size': '5'}, {'name': 'a.flac', 'size': '5'}])
        self.assertEqual([n['provider'] for n in detail['external_ids']], ['openlibrary', 'musicbrainz'])
        mbid = '0a1b2c3d-0000-4000-8000-000000000001'
        opener = Opener({'9783161484100.json': json.dumps({'title': 'Ein Buch', 'publish_date': '1999', 'number_of_pages': 320, 'publishers': ['Verlag']}).encode(),
                         mbid + '?fmt=json': json.dumps({'id': mbid, 'title': 'Ein Album', 'date': '2001', 'country': 'DE', 'artist-credit': [{'name': 'Band'}]}).encode()})
        book = extras.lookup(detail, 'openlibrary', opener)
        self.assertEqual((book['found'], book['provider'], book['title'], book['pages'], book['publishers']), (True, 'Open Library', 'Ein Buch', 320, ['Verlag']))
        album = extras.lookup(detail, 'musicbrainz', opener)
        self.assertEqual((album['title'], album['artists'], album['country']), ('Ein Album', ['Band'], 'DE'))
        self.assertEqual(opener.asked, ['https://openlibrary.org/isbn/9783161484100.json', 'https://musicbrainz.org/ws/2/release/' + mbid + '?fmt=json'])
        unknown = Opener({'9783161484100.json': b'{}'})
        self.assertEqual(extras.lookup(detail, 'openlibrary', unknown), {'found': False, 'provider': 'openlibrary', 'id': '9783161484100'})
        with self.assertRaisesRegex(ValueError, 'keine solche Kennung'):
            extras.lookup(upload(), 'openlibrary', opener)
        with self.assertRaisesRegex(ValueError, 'keine solche Kennung'):
            extras.lookup(detail, 'https://evil.example', opener)

    def test_wiring(self):
        self.assertTrue(wired("'/api/archive-bluray-playlist'"))
        self.assertTrue(wired("'/api/archive-external-id'"))
        self.assertIn("'archive_extras.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("api('archive-bluray-playlist'", app)
        self.assertIn("api('archive-external-id'", app)
        for name in ('bluray_playlist.py', 'catalog_taxonomy.py', 'catalog_enrichment.py'):
            self.assertTrue((ROOT / 'vendor' / 'archive_portals' / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
