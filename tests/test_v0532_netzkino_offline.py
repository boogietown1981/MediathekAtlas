"""0.5.32: Netzkino offline downloads via ytdl-nightly and the shared queue."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import core, downloads, netzkino, netzkino_downloads as nd, ytdl_bridge  # noqa: E402

ITEM = 'ab' * 16


def next_page(node):
    data = {'props': {'__dehydratedState': {'queries': [
        {'state': {'data': {'data': {'other': {'__typename': 'Category'}}}}},
        {'state': {'data': {'data': {'movie': node}}}}]}}}
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + '</script></html>')


MOVIE = {'__typename': 'CmsMovie', 'title': 'Hin und Weg', 'originalTitle': 'Hin und Weg',
         'productionYear': 2014, 'runtimeInSeconds': 5700, 'fskRating': 12,
         'licenses': {'nodes': [{'properties': 'AVOD'}]},
         'videoSource': {'pmdUrl': 'hin-und-weg.mp4'}}


class BridgeTests(unittest.TestCase):
    def test_vendored_ytdl_nightly_is_loadable(self):
        st = ytdl_bridge.status()
        self.assertTrue(st['ok'], st)
        self.assertTrue(st['version'])
        meta = json.loads((ROOT / 'vendor' / 'ytdl_nightly' / 'VENDOR.json').read_text())
        self.assertEqual(meta['repository'], 'https://github.com/boogietown1981/ytdl-nightly')
        # Lazy extractor index keeps the import cheap on old NAS hardware.
        self.assertTrue((ROOT / 'vendor' / 'ytdl_nightly' / 'youtube_dl' / 'extractor' / 'lazy_extractors.py').is_file())
        self.assertNotIn('shahid.py', os.listdir(ROOT / 'vendor' / 'ytdl_nightly' / 'youtube_dl' / 'extractor'))

    def test_only_netzkino_detail_pages(self):
        self.assertEqual(ytdl_bridge.page_url('https://netzkino.de/details/hin-und-weg'),
                         'https://www.netzkino.de/details/hin-und-weg')
        for bad in ('https://www.netzkino.de/#!/kino/x', 'http://www.netzkino.de/details/x1',
                    'https://evil.example/details/abc', 'https://www.netzkino.de/details/a/../b'):
            with self.assertRaises(ytdl_bridge.ResolveError):
                ytdl_bridge.page_url(bad)

    def resolve(self, node):
        ie_class = ytdl_bridge._extractor_class(ytdl_bridge.load())
        with mock.patch.object(ie_class, '_download_webpage', return_value=next_page(node)):
            return ytdl_bridge.resolve('https://www.netzkino.de/details/hin-und-weg')

    def test_resolves_progressive_mp4_through_ytdl(self):
        info = self.resolve(MOVIE)
        self.assertEqual(info['url'], 'https://pmd.netzkino-seite.netzkino.de/hin-und-weg.mp4')
        self.assertEqual(info['duration'], 5700)
        self.assertEqual(info['extractor'], 'netzkino:mediathekatlas')

    def test_refuses_drm_and_missing_file(self):
        drm = {**MOVIE, 'licenses': {'nodes': [{'properties': 'DRM'}]}}
        with self.assertRaisesRegex(ytdl_bridge.ResolveError, 'DRM'):
            self.resolve(drm)
        hls_only = {**MOVIE, 'videoSource': {'hlsUrl': 'x.m3u8'}}
        with self.assertRaisesRegex(ytdl_bridge.ResolveError, 'MP4'):
            self.resolve(hls_only)
        with self.assertRaisesRegex(ytdl_bridge.ResolveError, 'Filmdaten'):
            self.resolve({'__typename': 'Category'})


class QueueFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        self.media = Path(self.tmp.name) / 'media'
        self.media.mkdir()
        db = netzkino._connect(self.state)
        now = time.time()
        with db:
            db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,year,content_id,genres)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (ITEM, 'Hin und Weg', 'https://www.netzkino.de/details/hin-und-weg',
                'graphql', 'unverified', now, now, 'movie', 2014, 'a0U01000004epM6', 'Comedy,Drama'))
            db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,year)
                VALUES(?,?,?,?,?,?,?,?,?)''', ('cd' * 16, 'Die Serie - S02E05 - Finale',
                'https://www.netzkino.de/details/die-serie-s2e5', 'graphql', 'unverified', now, now, 'movie', None))
        db.close()
        self.c = sqlite3.connect(':memory:')
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        self.details = lambda root, item: {'details': {'description': 'Roadmovie', 'cast': ['Florian David Fitz'],
                                                     'poster': 'https://img.example/p.jpg'}}

    def job(self, item=ITEM):
        r = nd.enqueue(self.c, self.state, self.media, item, details_get=self.details)
        row = self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()
        return r, json.loads(row[0])

    def publish(self, job):
        target = Path(job['target'])
        target.parent.mkdir(parents=True)
        for p in (target, target.with_suffix('.nfo'), target.with_suffix('.metadata.json'),
                  target.parent / 'poster.jpg', target.parent / 'fanart.jpg'):
            p.write_bytes(b'x')
        job.update(state='done', path=str(target))
        nd.stamp(job, now=1000)
        self.c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'done', job['id']))
        return target


class QueueTests(QueueFixture):
    def test_same_naming_scheme_as_mediathek_videos(self):
        r, job = self.job()
        self.assertTrue(r['created'])
        expected = core.target(self.media, job['metadata'], 'netzkino:' + ITEM)
        self.assertEqual(job['target'], str(expected))
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(),
                         'Filme/Hin und Weg (2014)/Hin und Weg (2014).mkv')
        self.assertEqual(job['source']['_resolver'], 'netzkino')
        self.assertNotIn('_download_url', job['source'])
        self.assertEqual(job['license']['kind'], 'netzkino_offline')
        self.assertEqual(job['metadata']['cast'], [{'name': 'Florian David Fitz'}])

    def test_episode_naming_and_no_invented_season(self):
        _, job = self.job('cd' * 16)
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(),
                         'Serien/Die Serie/Season 02/Die Serie - S02E05.mkv')
        meta = nd.metadata({'title': 'Krimi - Folge 3', 'kind': 'movie'}, {})
        self.assertEqual(meta['kind'], 'movie')  # no season -> no invented "Staffel 1"

    def test_no_duplicates(self):
        first, _ = self.job()
        second = nd.enqueue(self.c, self.state, self.media, ITEM, details_get=self.details)
        self.assertFalse(second['created'])
        self.assertEqual(second['id'], first['id'])

    def test_shared_pipeline_resolves_right_before_download(self):
        _, job = self.job()
        with mock.patch.object(ytdl_bridge, 'resolve', return_value={'url': 'https://pmd.netzkino-seite.netzkino.de/f.mp4'}) as res:
            self.assertEqual(downloads.source_url(job['source']), 'https://pmd.netzkino-seite.netzkino.de/f.mp4')
        res.assert_called_once_with('https://www.netzkino.de/details/hin-und-weg')
        # Mediathek rows keep their quality order
        self.assertEqual(downloads.source_url({'url_video': 'a', 'url_video_hd': 'b'}, 'standard'), 'a')
        with self.assertRaises(ValueError):
            downloads.source_url({'_resolver': 'unbekannt'})

    def test_thirty_day_expiry_removes_only_own_files(self):
        _, job = self.job()
        target = self.publish(job)
        self.assertEqual(job['offline_until'], 1000 + 30 * 86400)
        other = self.media / 'Filme' / 'Anderer Film (2000)' / 'Anderer Film (2000).mkv'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'keep')
        self.assertEqual(nd.expire(self.c, now=1000 + 29 * 86400), [])
        self.assertTrue(target.exists())
        listing = nd.listing(self.c, ITEM, now=1000 + 29 * 86400)['items'][0]
        self.assertEqual(listing['days_left'], 1)
        self.assertEqual(nd.expire(self.c, now=1000 + 30 * 86400 + 1), [job['id']])
        self.assertFalse(target.parent.exists())
        self.assertTrue(other.exists())
        state = self.c.execute('SELECT state FROM jobs WHERE id=?', (job['id'],)).fetchone()[0]
        self.assertEqual(state, 'expired')
        # After expiry the title may be downloaded again for another 30 days.
        self.assertTrue(nd.enqueue(self.c, self.state, self.media, ITEM, details_get=self.details)['created'])

    def test_folder_with_other_video_keeps_artwork(self):
        _, job = self.job()
        target = self.publish(job)
        (target.parent / 'Hin und Weg (2014) - 1080p.mkv').write_bytes(b'mediathek')
        nd.delete_now(self.c, job['id'])
        self.assertFalse(target.exists())
        self.assertTrue((target.parent / 'poster.jpg').exists())

    def test_never_deletes_outside_download_root(self):
        _, job = self.job()
        outside = Path(self.tmp.name) / 'elsewhere.mkv'
        outside.write_bytes(b'x')
        job.update(path=str(outside))
        self.assertEqual(nd.remove_files(job), [])
        self.assertTrue(outside.exists())

    def test_licensed_file_keeps_old_function_without_expiry(self):
        r = nd.enqueue_file(self.c, self.state, self.media, ITEM, 'https://files.rightsholder.example/film.mp4',
                            'written_permission', 'Schriftliche Freigabe des Rechteinhabers vom 1.11.2026',
                            True, details_get=self.details)
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        self.assertEqual(job['source']['_download_url'], 'https://files.rightsholder.example/film.mp4')
        self.assertNotIn('_resolver', job['source'])
        nd.stamp(job, now=0)
        self.assertNotIn('offline_until', job)
        with self.assertRaises(ValueError):
            nd.direct_url('https://pmd.netzkino-seite.netzkino.de/film.mp4')

    def test_legacy_queue_is_migrated_once(self):
        legacy = sqlite3.connect(str(self.state / nd.LEGACY_DB))
        legacy.execute('''CREATE TABLE licensed_netzkino_downloads (id TEXT PRIMARY KEY, netzkino_id TEXT,
            title TEXT, source_url TEXT, rights_basis TEXT, rights_note TEXT, target_name TEXT, state TEXT)''')
        legacy.execute('INSERT INTO licensed_netzkino_downloads VALUES(?,?,?,?,?,?,?,?)',
                       ('1' * 32, ITEM, 'Hin und Weg', 'https://files.rightsholder.example/film.mp4',
                        'rights_holder', 'Eigene Rechte am Film laut Vertrag 2026', 'x.mp4', 'paused'))
        legacy.commit()
        legacy.close()
        self.assertEqual(nd.migrate_legacy(self.state, self.c, self.media), 1)
        self.assertEqual(nd.migrate_legacy(self.state, self.c, self.media), 0)
        self.assertEqual(nd.summary(self.c)['queued'], 1)


@unittest.skipUnless(downloads.tool('ffmpeg') and downloads.tool('ffprobe'), 'ffmpeg/ffprobe fehlen')
class EndToEndTests(QueueFixture):
    """Full shared pipeline: resolver -> HTTP download -> MKV + NFO + metadata.json."""
    def test_download_produces_mediathek_layout(self):
        import io, subprocess
        _, job = self.job()
        clip = Path(self.tmp.name) / 'clip.mp4'
        subprocess.run([downloads.tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=5',
                        '-t', '2', '-pix_fmt', 'yuv420p', str(clip)], check=True)
        data = clip.read_bytes()

        class Reply(io.BytesIO):
            headers = {'Content-Type': 'video/mp4', 'Content-Length': str(len(data))}
            def __enter__(self): return self
            def __exit__(self, *a): self.close()
        opened = []
        def fake_open(url, *a, **k):
            opened.append(url)
            return Reply(data)
        states = []
        with mock.patch.object(ytdl_bridge, 'resolve', return_value={'url': 'https://pmd.netzkino-seite.netzkino.de/f.mp4'}), \
             mock.patch.object(core, 'open_url', side_effect=fake_open), \
             mock.patch('artwork.save_image', return_value=True):
            downloads.run(job['source'], job['metadata'], job['root'], job['quality'],
                          lambda state, *a, **k: states.append((state, k)), lambda: False)
        self.assertEqual(opened, ['https://pmd.netzkino-seite.netzkino.de/f.mp4'])
        target = Path(job['target'])
        self.assertTrue(target.is_file())
        self.assertTrue(target.with_suffix('.nfo').is_file())
        meta = json.loads(target.with_suffix('.metadata.json').read_text())
        self.assertEqual(meta['metadata']['provider'], 'Netzkino')
        self.assertEqual(states[-1][0], 'done')
        self.assertFalse(list(target.parent.glob('*.partial')))


class ServerWiringTests(unittest.TestCase):
    def test_server_uses_shared_queue_and_expiry(self):
        s = (ROOT / 'server.py').read_text()
        self.assertIn('netzkino_downloads.enqueue(c,ROOT,root,item_id)', s)
        self.assertIn("name='netzkino_offline_expiry'", s)
        self.assertNotIn('netzkino_licensed_file_worker', s)
        self.assertIn('if j[\'state\']==\'done\':netzkino_downloads.stamp(j)', s)
        self.assertIn("'ytdl_bridge.py'", (ROOT / 'build_macos.py').read_text())

    def test_nas_package_files_are_world_readable(self):
        import build_nas
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'app'
            build_nas.copy_app(dest)
            self.assertTrue((dest / 'ytdl_bridge.py').is_file())
            self.assertTrue((dest / 'vendor' / 'ytdl_nightly' / 'youtube_dl' / '__init__.py').is_file())
            bad = [p for p in dest.rglob('*') if p.is_file() and not os.stat(p).st_mode & 0o004]
            self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
