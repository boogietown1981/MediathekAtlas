"""0.5.37: Pluto TV offline copies (20 days) through the shared download queue."""
import functools
import http.server
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core, downloads, pluto, pluto_downloads as pd, netzkino_downloads as nd  # noqa: E402
from test_v0536_pluto import Fixture, MOVIE, SERIES, TOKEN  # noqa: E402

EPISODE = '61aabbccddeeff0011220001'
CHANNEL = '5ce4475cd43850831ca91ce7'


class OfflineFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()
        pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=2000)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def job(self, item=MOVIE['_id'], now=1000):
        r = pd.enqueue(self.c, self.root, self.media, item, now=now)
        row = self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()
        return r, json.loads(row[0])

    def publish(self, job, now=1000):
        target = Path(job['target'])
        target.parent.mkdir(parents=True, exist_ok=True)
        for p in (target, target.with_suffix('.nfo'), target.with_suffix('.metadata.json')):
            p.write_bytes(b'x')
        job.update(state='done', path=str(target))
        nd.stamp(job, now=now)
        self.c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'done', job['id']))
        return target


class QueueTests(OfflineFixture):
    def test_film_uses_mediathek_naming_and_thirty_day_licence(self):
        r, job = self.job()
        self.assertTrue(r['created'])
        self.assertEqual(job['target'], str(core.target(self.media, job['metadata'], 'pluto:' + MOVIE['_id'])))
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(),
                         'Filme/Arrival (2015)/Arrival - (2015).mkv')
        self.assertEqual((job['origin'], job['pluto_id'], job['source']['_resolver']), ('pluto', MOVIE['_id'], 'pluto'))
        self.assertEqual((job['license']['kind'], job['license']['days']), ('pluto_offline', 30))
        self.assertEqual(job['metadata']['provider'], 'Pluto TV')
        # No stream address (with session token) is stored in the queue.
        self.assertNotIn(TOKEN, json.dumps(job))
        self.assertNotIn('m3u8', json.dumps(job['source']))
        self.assertTrue(nd.is_portal(job) and nd.is_offline(job))

    def test_episode_gets_series_layout(self):
        _, job = self.job(EPISODE)
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(),
                         'Serien/CSI/Season 01/CSI - S01E01.mkv')
        self.assertEqual(job['metadata']['episode_title'], 'Pilot')

    def test_episode_without_numbers_is_no_invented_season(self):
        meta = pd.metadata({'title': 'Pilot', 'kind': 'episode', 'season': None, 'episode': None}, 'CSI')
        self.assertEqual((meta['kind'], meta['title']), ('movie', 'CSI - Pilot'))

    def test_channels_series_and_unknown_titles_are_refused(self):
        for item, text in ((CHANNEL, 'Live-Sender'), (SERIES['_id'], 'einzelne Folge'),
                           ('abcdefabcdef', 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text):
                pd.enqueue(self.c, self.root, self.media, item)

    def test_no_duplicates_until_expired(self):
        first, job = self.job()
        self.assertFalse(pd.enqueue(self.c, self.root, self.media, MOVIE['_id'])['created'])
        self.publish(job)
        self.assertEqual(job['offline_until'], 1000 + 30 * 86400)
        self.assertEqual(nd.expire(self.c, now=1000 + 29 * 86400), [])
        listing = nd.listing(self.c, MOVIE['_id'], now=1000 + 29 * 86400, origin='pluto')
        self.assertEqual((listing['offline_days'], listing['items'][0]['days_left']), (30, 1))
        self.assertIn('Pluto-TV', listing['policy'])
        self.assertEqual(nd.expire(self.c, now=1000 + 30 * 86400 + 1), [job['id']])
        self.assertFalse(Path(job['target']).exists())
        self.assertTrue(pd.enqueue(self.c, self.root, self.media, MOVIE['_id'])['created'])

    def test_netzkino_and_pluto_listings_stay_apart(self):
        self.job()
        self.assertEqual(nd.listing(self.c, origin='netzkino')['items'], [])
        self.assertEqual(len(nd.listing(self.c, origin='pluto')['items']), 1)
        self.assertEqual(nd.summary(self.c, 'pluto')['queued'], 1)
        self.assertEqual(nd.summary(self.c)['queued'], 0)

    def test_delete_now(self):
        _, job = self.job()
        target = self.publish(job)
        self.assertEqual(nd.delete_now(self.c, job['id'])['state'], 'removed')
        self.assertFalse(target.exists())

    def test_resolver_fetches_fresh_session_address(self):
        _, job = self.job()
        real = pluto.play_source
        with mock.patch.object(pluto, 'play_source', lambda root, item: real(root, item, fetch=self.fetch)):
            url = downloads.source_url(job['source'])
        self.assertTrue(url.startswith('https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/v2/stitch/hls/episode/'))
        self.assertIn('jwt=' + TOKEN, url)
        stored = downloads.public_url(job['source'], url)
        self.assertNotIn('?', stored)
        self.assertNotIn(TOKEN, stored)
        # Other sources keep their full address in metadata.json.
        self.assertEqual(downloads.public_url({}, 'https://a/b.mp4?x=1'), 'https://a/b.mp4?x=1')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(downloads.tool('ffmpeg') and downloads.tool('ffprobe'), 'ffmpeg/ffprobe fehlen')
class HlsDownloadTests(OfflineFixture):
    """Shared pipeline end to end: HLS (served locally) -> MKV + NFO + metadata.json."""
    def serve_hls(self, seconds=4):
        web = self.root / 'web'
        web.mkdir()
        subprocess.run([downloads.tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=22050', '-t', str(seconds),
                        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1',
                        '-hls_playlist_type', 'vod', str(web / 'master.m3u8')], check=True)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(web)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:%d/master.m3u8?jwt=%s' % (server.server_address[1], TOKEN)

    def test_hls_download_produces_mediathek_layout_without_token(self):
        _, job = self.job()
        url = self.serve_hls()
        job['source']['duration'] = 4
        states = []
        with mock.patch.object(pd, 'resolve', return_value=url), mock.patch('artwork.save_image', return_value=True):
            downloads.run(job['source'], job['metadata'], job['root'], job['quality'],
                          lambda state, *a, **k: states.append(state), lambda: False)
        target = core.existing_download(job['target'])   # 0.5.42: name + resolution/codec
        self.assertTrue(target and target.is_file())
        self.assertTrue(target.with_suffix('.nfo').is_file())
        info = downloads.probe(target)
        self.assertEqual(sorted(s['codec_type'] for s in info['streams']), ['audio', 'video'])
        self.assertGreater(float(info['format']['duration']), 3)
        meta_text = target.with_suffix('.metadata.json').read_text()
        self.assertNotIn(TOKEN, meta_text)
        self.assertEqual(json.loads(meta_text)['metadata']['provider'], 'Pluto TV')
        self.assertEqual(states[0], 'downloading')
        self.assertEqual(states[-1], 'done')
        self.assertFalse(list(target.parent.glob('*.partial')))

    def test_short_stream_is_reported_incomplete(self):
        _, job = self.job()
        url = self.serve_hls(2)
        job['source']['duration'] = 600  # catalogue says 10 minutes, stream ends after 2 seconds
        with mock.patch.object(pd, 'resolve', return_value=url), mock.patch('artwork.save_image', return_value=True):
            with self.assertRaisesRegex(ValueError, 'unvollständig'):
                downloads.run(job['source'], job['metadata'], job['root'], job['quality'], lambda *a, **k: None, lambda: False)
        self.assertFalse(Path(job['target']).exists())

    def test_cancel_stops_ffmpeg(self):
        _, job = self.job()
        url = self.serve_hls(2)
        with mock.patch.object(pd, 'resolve', return_value=url):
            with self.assertRaisesRegex(ValueError, 'abgebrochen'):
                downloads.run(job['source'], job['metadata'], job['root'], job['quality'], lambda *a, **k: None, lambda: True)
        self.assertFalse(Path(job['target']).exists())
        self.assertFalse(list(Path(job['target']).parent.glob('*.partial')))


class WiringTests(unittest.TestCase):
    def test_server_and_ui(self):
        s = (ROOT / 'server.py').read_text()
        self.assertTrue(__import__('_wiring').wired('pluto_downloads.enqueue(c,ROOT,'))
        self.assertIn("'/api/offline-download-action'", s)
        # 0.5.40: the panel is the shared portal_panel.js, pluto.js configures it with key 'pluto'.
        js = (ROOT / 'web' / 'portal_panel.js').read_text()
        self.assertIn("key: 'pluto'", (ROOT / 'web' / 'pluto.js').read_text())
        # 0.5.47: the tile control is the shared offline_button.js.
        self.assertIn("AtlasOffline?.control(K, item.id", js)
        self.assertIn("source + '-download-add'", (ROOT / 'web' / 'offline_button.js').read_text())
        self.assertIn("'offline-download-action'", js)
        self.assertIn("item.kind !== 'channel'", js)
        self.assertIn('id="pluto-offline-jobs"', (ROOT / 'web' / 'index.html').read_text())
        self.assertIn("'pluto_downloads.py'", (ROOT / 'build_macos.py').read_text())


if __name__ == '__main__':
    unittest.main()
