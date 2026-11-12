"""0.5.56: ArchiveMedia stage 1 – Fanart.tv artwork for identified works and verified
catalog.db snapshots (backup_manager from ArchiveMedia v0.10.53)."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import artwork  # noqa: E402
import db_backup  # noqa: E402
import task_control  # noqa: E402
from vendor.archive_portals import backup_manager  # noqa: E402

FANART_MOVIE = {'name': 'Film', 'imdb_id': 'tt0111161', 'tmdb_id': '278',
                'movieposter': [{'url': 'https://assets.fanart.tv/fanart/movies/278/movieposter/a.jpg', 'lang': 'de', 'likes': '4'}],
                'moviebackground': [{'url': 'https://assets.fanart.tv/fanart/movies/278/moviebackground/b.jpg', 'lang': '00', 'likes': '2'}],
                'hdmovielogo': [{'url': 'https://assets.fanart.tv/fanart/movies/278/hdmovielogo/c.png', 'lang': 'en', 'likes': '9'}]}


class FanartTests(unittest.TestCase):
    def test_provenance_matches_vendored_files(self):
        for entry in json.loads((ROOT / 'PROVENANCE.json').read_text()):
            data = (ROOT / entry['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], entry['path'])

    def test_no_key_no_request(self):
        m = {'title': 'Film', 'kind': 'movie', 'year': 1994, 'imdb_id': 'tt0111161'}
        with mock.patch('core.open_url', side_effect=AssertionError('network')):
            found, errors = artwork.lookup(m, {})
        self.assertFalse(errors)
        self.assertNotIn('logo', found)

    def test_movie_logo_poster_background_by_imdb_id(self):
        m = {'title': 'Film', 'kind': 'movie', 'year': 1994, 'provider': 'IMDb Offline', 'reference_id': 'tt0111161'}
        seen = []

        def fetch(request):
            seen.append((request.full_url, request.get_header('Api-key')))
            return FANART_MOVIE
        with mock.patch.object(artwork, '_fanart_fetch', side_effect=fetch):
            found, errors = artwork.lookup(m, {'fanart': 'secret-key'})
        self.assertFalse(errors)
        self.assertEqual(found['logo'], FANART_MOVIE['hdmovielogo'][0]['url'])
        self.assertEqual(found['poster'], FANART_MOVIE['movieposter'][0]['url'])
        self.assertEqual(found['fanart'], FANART_MOVIE['moviebackground'][0]['url'])
        self.assertIn('Fanart.tv', found['artwork_provider'])
        self.assertTrue(found['fanart_checked'])
        url, key = seen[0]
        self.assertIn('/movies/tt0111161', url)
        self.assertNotIn('secret-key', url)   # credentials only in headers
        self.assertEqual(key, 'secret-key')

    def test_existing_tmdb_images_are_kept_logo_added(self):
        m = {'title': 'Film', 'kind': 'movie', 'year': 1994, 'imdb_id': 'tt0111161',
             'poster': 'https://image.tmdb.org/t/p/w500/x.jpg', 'fanart': 'https://image.tmdb.org/t/p/w1280/y.jpg'}
        with mock.patch.object(artwork, '_fanart_fetch', return_value=FANART_MOVIE):
            found, _ = artwork.lookup(m, {'fanart': 'k'})
        artwork.apply(m, found)
        self.assertTrue(m['poster'].startswith('https://image.tmdb.org/'))
        self.assertTrue(m['logo'].startswith('https://assets.fanart.tv/'))

    def test_conflicting_id_blocks_images(self):
        m = {'title': 'Film', 'kind': 'movie', 'year': 1994, 'imdb_id': 'tt0111161'}
        wrong = dict(FANART_MOVIE, imdb_id='tt9999999')
        with mock.patch.object(artwork, '_fanart_fetch', return_value=wrong):
            found, _ = artwork.lookup(m, {'fanart': 'k'})
        self.assertNotIn('logo', found)
        self.assertNotIn('poster', found)
        self.assertIn('fanart_conflict', found)

    def test_series_prefers_tvdb_id(self):
        m = {'title': 'Serie', 'kind': 'series', 'year': 2015, 'provider': 'TVDB', 'reference_id': '289590'}
        seen = []

        def fetch(request):
            seen.append(request.full_url)
            return {'thetvdb_id': '289590', 'hdtvlogo': [{'url': 'https://assets.fanart.tv/fanart/tv/289590/hdtvlogo/l.png', 'lang': 'de'}]}
        with mock.patch.object(artwork, '_fanart_fetch', side_effect=fetch):
            found = {}
            artwork.fanart_lookup(m, {'fanart_personal': 'p'}, found)
        self.assertTrue(found['logo'].endswith('l.png'))
        self.assertIn('/tv/289590?source=tvdb', seen[0])

    def test_foreign_image_host_rejected(self):
        m = {'title': 'Film', 'kind': 'movie', 'imdb_id': 'tt0111161'}
        evil = {'imdb_id': 'tt0111161', 'hdmovielogo': [{'url': 'https://evil.example/logo.png'}]}
        with mock.patch.object(artwork, '_fanart_fetch', return_value=evil):
            found, _ = artwork.lookup(m, {'fanart': 'k'})
        self.assertNotIn('logo', found)
        self.assertTrue(artwork.valid('https://assets.fanart.tv/fanart/x.png'))

    def test_download_exports_clearlogo(self):
        source = (ROOT / 'downloads.py').read_text()
        self.assertIn("('logo',dest.parent.parent/'clearlogo')", source)
        self.assertIn("('logo',dest.with_name(dest.stem+'-clearlogo'))", source)

    def test_settings_and_ui_wiring(self):
        server = (ROOT / 'server.py').read_text()
        self.assertIn("'fanart','fanart_personal'", server)
        self.assertIn("stored.get('fanart')", server)   # redacted from diagnostics
        app = (ROOT / 'web' / 'app.js').read_text()
        self.assertIn("'assets.fanart.tv'", app)
        self.assertIn('clear_fanart:true', app)
        self.assertIn('id="fanart"', (ROOT / 'web' / 'index.html').read_text())


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        c = sqlite3.connect(self.root / 'catalog.db')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE works(id TEXT PRIMARY KEY, meta TEXT)')
        c.executemany('INSERT INTO works VALUES(?,?)', [(str(i), 'x' * 200) for i in range(3000)])
        c.commit()
        self.conn = c   # stays open: the snapshot must work while the app writes (WAL)
        db_backup._STATE.update(phase='idle', error='', last=None, progress=0.0)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_snapshot_is_consistent_and_listed(self):
        self.conn.execute("INSERT INTO works VALUES('wal-only','y')")
        self.conn.commit()
        made = db_backup.create(self.root)
        name = made['backup']['name']
        copy = sqlite3.connect(self.root / 'Backups' / name)
        self.assertEqual(copy.execute('SELECT COUNT(*) FROM works').fetchone()[0], 3001)
        copy.close()
        listing = db_backup.listing(self.root)
        self.assertEqual(listing['count'], 1)
        self.assertFalse(listing['backups'][0]['automatic'])
        self.assertFalse(list((self.root / 'Backups').glob('*.part')))

    def test_rotation_keeps_manual_and_newest_automatic(self):
        manual = db_backup.create(self.root, now=1_700_000_000)['backup']['name']
        names = []
        for i in range(6):
            names.append(db_backup.create(self.root, automatic=True, now=1_700_000_100 + i * 10)['backup']['name'])
            # distinct mtimes for a deterministic order
            p = self.root / 'Backups' / names[-1]
            import os
            os.utime(p, (1_700_000_100 + i * 10, 1_700_000_100 + i * 10))
        removed = db_backup.rotate(self.root)
        self.assertEqual(sorted(removed), sorted(names[:2]))
        left = {x['name'] for x in db_backup.listing(self.root)['backups']}
        self.assertIn(manual, left)
        self.assertEqual(left - {manual}, set(names[2:]))
        # A deleted name is never recreated.
        self.assertTrue(backup_manager.was_deleted(self.root, names[0]))

    def test_auto_due_once_per_interval(self):
        self.assertTrue(db_backup.auto_due(self.root))
        db_backup.create(self.root, automatic=True)
        self.assertFalse(db_backup.auto_due(self.root))
        self.assertTrue(db_backup.auto_due(self.root, now=time.time() + db_backup.AUTO_INTERVAL + 5))

    def test_delete_needs_confirmation_and_fingerprint(self):
        entry = db_backup.create(self.root)['backup']
        with self.assertRaises(ValueError):
            db_backup.delete(self.root, [{'name': entry['name'], 'fingerprint': entry['fingerprint']}], 'ja')
        with self.assertRaises(ValueError):
            db_backup.delete(self.root, [{'name': entry['name'], 'fingerprint': 'falsch'}], 'BACKUP LÖSCHEN')
        with self.assertRaises(ValueError):
            db_backup.delete(self.root, [{'name': 'catalog.db'}], 'BACKUP LÖSCHEN')
        done = db_backup.delete(self.root, [{'name': entry['name'], 'fingerprint': entry['fingerprint']}], 'BACKUP LÖSCHEN')
        self.assertEqual(done['deleted_count'], 1)
        self.assertTrue((self.root / 'catalog.db').exists())

    def test_low_disk_space_refused(self):
        with mock.patch('shutil.disk_usage', return_value=mock.Mock(free=1024)):
            with self.assertRaises(ValueError):
                db_backup.create(self.root)
        self.assertFalse(list((self.root / 'Backups').glob('*')))

    def test_task_is_controllable(self):
        self.assertIn('backup', task_control.TASKS)
        self.assertIn('start', task_control.TASKS['backup']['can'])

    def test_loop_runs_on_request_and_stops(self):
        stop = threading.Event()
        with mock.patch.object(task_control, 'take_request', side_effect=[True, False, False, False]), \
             mock.patch.object(task_control, 'wait_if_paused', return_value=True):
            t = threading.Thread(target=db_backup.loop, args=(self.root, stop), kwargs={'first_delay': 3600})
            t.start()
            for _ in range(100):
                if list((self.root / 'Backups').glob('catalog-auto-*.db')):
                    break
                time.sleep(0.05)
            stop.set()
            t.join(10)
        self.assertTrue(list((self.root / 'Backups').glob('catalog-auto-*.db')))


if __name__ == '__main__':
    unittest.main()
