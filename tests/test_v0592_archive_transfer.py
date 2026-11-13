"""0.5.92: Archive.org-Liste zwischen Installationen austauschen (ArchiveMedia catalog_transfer)."""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_transfer as transfer  # noqa: E402
import portal_sources  # noqa: E402
from tests._wiring import wired  # noqa: E402


def database():
    c = sqlite3.connect(':memory:')
    portal_sources.initialize(c)
    return c


def write_list(path, items, files, manifest=None, extra=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('items.jsonl', ''.join(json.dumps(i) + '\n' if isinstance(i, dict) else i for i in items))
        z.writestr('files.jsonl', ''.join(json.dumps(f) + '\n' for f in files))
        z.writestr('manifest.json', json.dumps(manifest or {'format': transfer.FORMAT, 'schema_version': 1, 'items': len(items), 'files': len(files)}))
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return path


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.a = database()
        self.addCleanup(self.a.close)
        rows = [portal_sources.entry('internet_archive', 'nosferatu_1922', 'Nosferatu', 'https://archive.org/details/nosferatu_1922', 1922, 'Stummfilm'),
                portal_sources.entry('internet_archive', 'lone_ranger_s1', 'The Lone Ranger – Staffel 1', 'https://archive.org/details/lone_ranger_s1')]
        rows[0]['language_claim'] = 'German'
        portal_sources.save(self.a, rows)
        doc = {'metadata': {'identifier': 'lone_ranger_s1', 'title': 'The Lone Ranger', 'mediatype': 'movies', 'uploader': 'someone@example.org'},
               'files': [{'name': 'Lone Ranger S01E01.mkv', 'source': 'original', 'format': 'Matroska', 'size': '700000000', 'length': '1500'},
                         {'name': 'Lone Ranger S01E01.mp4', 'source': 'derivative', 'original': 'Lone Ranger S01E01.mkv', 'format': 'h.264', 'size': '250000000', 'length': '1500'}]}
        portal_sources.save_archive_detail(self.a, rows[1]['id'], portal_sources.archive_detail_document('lone_ranger_s1', doc))

    def test_export_is_the_archivemedia_format_and_data_only(self):
        facts = transfer.export(self.a, self.dir / 'liste.zip', now=0)
        self.assertEqual((facts['items'], facts['files']), (2, 2))
        with zipfile.ZipFile(self.dir / 'liste.zip') as z:
            self.assertEqual(set(z.namelist()), {'manifest.json', 'items.jsonl', 'files.jsonl'})
            manifest = json.loads(z.read('manifest.json'))
            items = [json.loads(line) for line in z.read('items.jsonl').splitlines()]
            files = [json.loads(line) for line in z.read('files.jsonl').splitlines()]
            everything = z.read('items.jsonl') + z.read('files.jsonl') + z.read('manifest.json')
        self.assertEqual((manifest['format'], manifest['schema_version'], manifest['items'], manifest['files']), ('archivemedia-file-list', 1, 2, 2))
        self.assertEqual(items[1], {'id': 'nosferatu_1922', 'title': 'Nosferatu', 'year': 1922, 'language': 'German', 'date': ''})
        self.assertEqual([set(f) for f in files], [{'item_id', 'filename', 'category', 'file_role', 'source', 'original', 'format', 'bytes', 'duration', 'md5', 'sha1'}] * 2)
        self.assertEqual(sorted((f['filename'], f['file_role'], f['bytes']) for f in files),
                         [('Lone Ranger S01E01.mkv', 'content', 700000000), ('Lone Ranger S01E01.mp4', 'derivative', 250000000)])
        for secret in (b'example.org', b'/home', b'download_dir', b'Stummfilm'):
            self.assertNotIn(secret, everything)

    def test_import_adds_only_unknown_uploads_and_changes_nothing(self):
        transfer.export(self.a, self.dir / 'liste.zip')
        b = database()
        self.addCleanup(b.close)
        portal_sources.save(b, [portal_sources.entry('internet_archive', 'nosferatu_1922', 'Nosferatu (eigener Titel)', 'https://archive.org/details/nosferatu_1922', 1922)])
        result = transfer.load(b, self.dir / 'liste.zip', now=5)
        self.assertEqual((result['items'], result['files'], result['added'], result['known'], result['written_by']), (2, 2, 1, 1, 'MediathekAtlas'))
        rows = {r[0]: (r[1], json.loads(r[2])) for r in b.execute('SELECT external_id,title,metadata FROM portal_items')}
        self.assertEqual(rows['nosferatu_1922'][0], 'Nosferatu (eigener Titel)')
        new = rows['lone_ranger_s1'][1]
        self.assertEqual((new['transferred'], new['transferred_video_files'], new['evidence'], new['download_allowed'], new['page_url']),
                         (True, 2, 'transferred_archive_list', False, 'https://archive.org/details/lone_ranger_s1'))
        self.assertEqual(b.execute('SELECT COUNT(*) FROM portal_archive_details').fetchone()[0], 0)
        self.assertEqual(transfer.load(b, self.dir / 'liste.zip')['added'], 0)
        self.assertEqual(len(portal_sources.listing(b, source='internet_archive')['items']), 2)

    def test_a_list_from_archivemedia_is_read(self):
        path = write_list(self.dir / 'am.zip', [{'id': 'metropolis_1927', 'title': 'Metropolis', 'year': '1927', 'language': 'ger', 'date': '2008-01-01'},
                                               {'id': 'ohne.titel', 'title': '', 'year': 'n/a'}],
                          [{'item_id': 'metropolis_1927', 'filename': 'Metropolis.mkv', 'category': 'video', 'file_role': 'content'},
                           {'item_id': 'metropolis_1927', 'filename': 'cover.jpg', 'category': 'images', 'file_role': 'auxiliary'}])
        b = database()
        self.addCleanup(b.close)
        result = transfer.load(b, path)
        self.assertEqual((result['added'], result['written_by']), (2, 'ArchiveMedia'))
        rows = {r[0]: (r[1], r[2], json.loads(r[3])['transferred_video_files']) for r in b.execute('SELECT external_id,title,year,metadata FROM portal_items')}
        self.assertEqual(rows, {'metropolis_1927': ('Metropolis', 1927, 1), 'ohne.titel': ('ohne.titel', None, 0)})

    def test_a_bad_list_changes_nothing(self):
        good_item, good_file = {'id': 'gut', 'title': 'Gut'}, {'item_id': 'gut', 'filename': 'a.mkv', 'category': 'video', 'file_role': 'content'}
        cases = {
            'kein ZIP': lambda p: p.write_bytes(b'kein zip'),
            'Listenformat': lambda p: write_list(p, [good_item], [good_file], extra={'extra.txt': 'x'}),
            'Format oder Version': lambda p: write_list(p, [good_item], [good_file], {'format': 'anderes', 'schema_version': 1, 'items': 1, 'files': 1}),
            'Zeilenanzahl im Manifest': lambda p: write_list(p, [good_item], [good_file], {'format': transfer.FORMAT, 'schema_version': 1, 'items': -1, 'files': 1}),
            'unvollständig': lambda p: write_list(p, [good_item], [good_file], {'format': transfer.FORMAT, 'schema_version': 1, 'items': 2, 'files': 1}),
            'Ungültige Archive-ID': lambda p: write_list(p, [good_item, {'id': '../etc/passwd', 'title': 'x'}], [good_file]),
            'ungültige Zeile': lambda p: write_list(p, [good_item, 'kein json\n'], [good_file]),
            'Ungültiger Dateiname': lambda p: write_list(p, [good_item], [dict(good_file, filename='../../x.mkv')]),
            'Dateikategorie': lambda p: write_list(p, [good_item], [dict(good_file, category='virus')]),
        }
        b = database()
        self.addCleanup(b.close)
        for number, (message, make) in enumerate(cases.items()):
            path = self.dir / ('schlecht%d.zip' % number)
            make(path)
            with self.assertRaisesRegex(ValueError, message):
                transfer.load(b, path)
            self.assertEqual(b.execute('SELECT COUNT(*) FROM portal_items').fetchone()[0], 0, message)

    def test_wiring(self):
        self.assertTrue(wired("'/api/archive-list-export'"))
        self.assertTrue(wired("'/api/archive-list-import'"))
        self.assertIn("'archive_transfer.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn('archive-list-file', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
