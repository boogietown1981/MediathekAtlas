"""0.5.61: Archive.org downloads like ArchiveMedia (Björn's decision 12.11.2026):
every listed video file, licence stored and shown, permanent, shared download queue."""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_downloads as ad  # noqa: E402
import netzkino_downloads as nd  # noqa: E402
import portal_sources as ps  # noqa: E402


def manifest():
    return {'metadata': {'identifier': 'old_movie_1950', 'title': 'Der alte Film', 'year': '1950',
                         'licenseurl': 'https://creativecommons.org/publicdomain/mark/1.0/',
                         'rights': 'Public Domain'},
            'files': [
                {'name': 'Der alte Film.mp4', 'format': 'MPEG4', 'size': '700000000', 'length': '01:30:00',
                 'source': 'original'},
                {'name': 'Der alte Film.de.srt', 'size': '3000', 'source': 'original'},
                {'name': 'Serie.S02E05.mkv', 'size': '300000000', 'length': '25:00', 'source': 'original'},
                {'name': 'Serie Folge ohne Nummer.mkv', 'size': '300000000', 'length': '25:00', 'source': 'original'},
            ]}


class ArchiveDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dl = Path(self.tmp.name) / 'Downloads'
        self.c = sqlite3.connect(':memory:')
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        ps.initialize(self.c)
        self.c.execute("INSERT INTO portal_items VALUES('ia1','internet_archive','old_movie_1950','Der alte Film','der alte film',1950,"
                       "'https://archive.org/details/old_movie_1950','{}',0,0)")
        self.detail = ps.archive_detail_document('old_movie_1950', manifest())
        ps.save_archive_detail(self.c, 'ia1', self.detail)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def variant(self, name):
        return next(v for v in self.detail['video_variants'] if v['filename'] == name)

    def test_movie_job_in_shared_queue_with_licence(self):
        r = ad.enqueue(self.c, str(self.dl), 'ia1', 'Der alte Film.mp4')
        self.assertTrue(r['created'])
        job = json.loads(self.c.execute('SELECT payload FROM jobs').fetchone()[0])
        self.assertEqual(job['origin'], 'internet_archive')
        self.assertEqual(job['source']['_download_url'], 'https://archive.org/download/old_movie_1950/Der%20alte%20Film.mp4')
        self.assertEqual(job['metadata']['kind'], 'movie')
        self.assertEqual(job['metadata']['year'], 1950)
        self.assertEqual(job['license']['kind'], 'archive_item')
        self.assertEqual(job['license']['rights'], 'Public Domain')
        self.assertIn('Filme', job['target'])
        # Permanent copy: no offline period; local only, never marks a Mediathek work.
        self.assertFalse(nd.is_offline(job))
        self.assertTrue(nd.is_portal(job))
        self.assertNotIn('offline_until', nd.stamp(dict(job)))
        self.assertEqual(job['sidecars'][0]['url'], 'https://archive.org/download/old_movie_1950/Der%20alte%20Film.de.srt')

    def test_download_url_used_by_worker(self):
        import downloads
        job = ad.build_job(self.c, str(self.dl), 'ia1', 'Der alte Film.mp4')
        self.assertEqual(downloads.source_url(job['source']), job['source']['_download_url'])

    def test_duplicate_not_queued_twice(self):
        ad.enqueue(self.c, str(self.dl), 'ia1', 'Der alte Film.mp4')
        again = ad.enqueue(self.c, str(self.dl), 'ia1', 'Der alte Film.mp4')
        self.assertFalse(again['created'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_episode_with_numbers(self):
        job = ad.build_job(self.c, str(self.dl), 'ia1', 'Serie.S02E05.mkv')
        self.assertEqual((job['metadata']['kind'], job['metadata']['season'], job['metadata']['episode']), ('series', 2, 5))
        self.assertIn('Season 02', job['target'])

    def test_unknown_episode_needs_user_input(self):
        v = self.variant('Serie Folge ohne Nummer.mkv')
        if v['kind'] == 'series':
            with self.assertRaises(ValueError):
                ad.build_job(self.c, str(self.dl), 'ia1', v['filename'])
        job = ad.build_job(self.c, str(self.dl), 'ia1', v['filename'], {'kind': 'series', 'title': 'Serie', 'season': 1, 'episode': 7})
        self.assertEqual((job['metadata']['season'], job['metadata']['episode']), (1, 7))
        movie = ad.build_job(self.c, str(self.dl), 'ia1', v['filename'], {'kind': 'movie', 'title': 'Einzelfilm'})
        self.assertEqual(movie['metadata']['kind'], 'movie')

    def test_only_manifest_files(self):
        for bad in ('../x.mp4', 'nicht/da.mp4', 'Der alte Film.de.srt'):
            with self.assertRaises(ValueError):
                ad.build_job(self.c, str(self.dl), 'ia1', bad)
        with self.assertRaises(ValueError):
            ad.build_job(self.c, str(self.dl), 'unbekannt', 'Der alte Film.mp4')

    def test_listing_by_item(self):
        ad.enqueue(self.c, str(self.dl), 'ia1', 'Der alte Film.mp4')
        out = ad.listing(self.c, item_id='ia1')
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(out['items'][0]['internet_archive_id'], 'ia1')
        self.assertIsNone(out['offline_days'])
        self.assertIn('Uploader', out['policy'])

    def test_sidecars_next_to_video(self):
        folder = self.dl / 'Filme' / 'Der alte Film (1950)'
        folder.mkdir(parents=True)
        video = folder / 'Der alte Film - (1950) - 576p.mkv'
        video.write_bytes(b'x')
        existing = folder / 'Der alte Film - (1950) - 576p.de.srt'
        job = {'path': str(video), 'sidecars': [{'name': 'Der alte Film.de.srt', 'url': 'https://archive.org/download/x/a.srt'},
                                                {'name': 'evil.exe', 'url': 'https://archive.org/download/x/evil.exe'}]}
        existing.write_text('alt')
        names = ad.fetch_sidecars(job, opener=lambda url: io.BytesIO(b'1\n00:00:01,000 --> 00:00:02,000\nHallo\n'))
        self.assertEqual(names, ['Der alte Film - (1950) - 576p.de.2.srt'])
        self.assertEqual(existing.read_text(), 'alt')   # never overwritten
        self.assertFalse(list(folder.glob('*.exe')))

    def test_server_and_ui_wiring(self):
        server = (ROOT / 'server.py').read_text()
        self.assertIn("path=='/api/archive-download'", server)
        self.assertIn("path=='/api/archive-downloads'", server)
        self.assertIn('archive_downloads.fetch_sidecars', server)
        app = (ROOT / 'web' / 'app.js').read_text()
        self.assertIn("api('archive-download'", app)
        self.assertIn('archive_downloads.py', (ROOT / 'build_macos.py').read_text())


if __name__ == '__main__':
    unittest.main()
