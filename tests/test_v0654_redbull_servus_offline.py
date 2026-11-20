"""0.6.54: private 30-day offline copies of ServusTV and Red Bull TV films and episodes.

Björn (20.11.2026): "bei redbull und servus tv gibts keine download option, warum?" – then "ja bitte einbauen".
Same shared queue and life cycle as Pluto TV, Netzkino and Plex; only titles the player releases right now as
plain HLS (youth protection hours, geo blocks, copy protection and live channels are refused); a provider-named
end of availability is never exceeded; "best" means up to 1080p H.264. Answers have the shape of the existing
ServusTV / Red Bull TV test fakes; the Red Bull hosts are not reachable from the build environment."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import download_quality  # noqa: E402
import downloads  # noqa: E402
import hls_guard  # noqa: E402
import hls_variants  # noqa: E402
import netzkino_downloads as nd  # noqa: E402
import platform_registry  # noqa: E402
import portal_title  # noqa: E402
import redbulltv  # noqa: E402
import redbulltv_downloads as rd  # noqa: E402
import servustv  # noqa: E402
import servustv_downloads as sd  # noqa: E402
import storage_policy  # noqa: E402
from test_v0601_servustv import NOW, FakeServus  # noqa: E402
from test_v0647_redbull_news import FakeRedBull  # noqa: E402

FILM = 'v.AAU3HRL0S34IKQ6NINUP'
EPISODE = 'v.AA%018d' % 2
SHOW = 's.AA-25RX849FN1W11'
CHANNEL = 'c.PN0B1EC15B2FE10'


def iso(ts):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()
        self.fake = FakeServus()
        self.assertTrue(servustv.sync(self.root, opener=self.fake, now=NOW)['ok'])
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        self.hls_checks = []

    def hls(self, url):
        self.hls_checks.append(url)
        return {'variants': 1, 'protected': False}

    def check(self, root, item_id):
        return servustv.play_source(root, item_id, opener=self.fake, check=self.hls, now=NOW)

    def enqueue(self, item_id, now=NOW):
        return sd.enqueue(self.c, self.root, self.media, item_id, now=now, check=self.check)

    def job(self, job_id):
        return json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()[0])


class ServusOffline(Base):
    def test_film_goes_into_the_shared_queue(self):
        r = self.enqueue(FILM)
        self.assertTrue(r['created'])
        job = self.job(r['id'])
        self.assertEqual((job['origin'], job['servustv_id'], job['license']['kind'], job['license']['days']),
                         ('servustv', FILM, 'servustv_offline', 30))
        self.assertNotIn('until', job['license'])                       # no end named by the player
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).parts[0], 'Filme')
        self.assertEqual((job['source']['_resolver'], job['quality'], job['source']['_prefer_codec']), ('servustv', '1080', 'avc1'))
        self.assertNotIn('m3u8', json.dumps(job))                         # stream address never stored
        self.assertEqual(len(self.hls_checks), 1)                         # checked for a key before queueing
        self.assertFalse(self.enqueue(FILM)['created'])                   # same title twice -> existing job
        listing = nd.listing(self.c, origin='servustv')
        self.assertEqual((listing['offline_days'], listing['items'][0]['servustv_id']), (30, FILM))
        self.assertIn('keine Downloads', listing['policy'])
        self.assertIn('Geosperren', listing['policy'])
        self.assertEqual((nd.portal_days('servustv'), nd.portal_days('redbulltv')), (30, 30))
        self.assertEqual(nd.summary(self.c, 'servustv')['queued'], 1)
        self.assertTrue(nd.is_portal(job) and nd.is_offline(job))         # never shared in the Verbund

    def test_episode_is_stored_as_series_episode(self):
        job = self.job(self.enqueue(EPISODE)['id'])
        meta = job['metadata']
        self.assertEqual((meta['kind'], meta['title'], meta['season'], meta['episode'], meta['episode_title']),
                         ('series', 'Bergwelten', 13, 2, 'Folge 2'))
        self.assertEqual(meta['provider'], 'ServusTV')

    def test_refusals_change_nothing(self):
        self.fake.player['AA%018d' % 3] = {'playabilityErrors': ['GEO_BLOCKED']}
        self.fake.player['AA%018d' % 4] = {
            'playabilityErrors': ['FSK_BLOCKED'],
            'playabilityErrorDetails': {'FSK_BLOCKED': {'minEveningHour': 22, 'maxMorningHour': 6, 'minAge': 16}}}
        for item, text in ((CHANNEL, 'Live-Sender'), (SHOW, 'einzelne Folge'), ('v.AA%018d' % 3, 'Geosperre'),
                           ('v.AA%018d' % 4, 'Jugendschutz'), ('v.AAZZZZZZZZZZZZZZZZZZ', 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text, msg=item):
                self.enqueue(item)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_protected_stream_is_refused_and_remembered(self):
        def drm(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        with self.assertRaisesRegex(ValueError, 'Kopierschutz'):
            sd.enqueue(self.c, self.root, self.media, FILM, now=NOW,
                       check=lambda r, i: servustv.play_source(r, i, opener=self.fake, check=drm, now=NOW))
        self.assertEqual(servustv.item(self.root, FILM)['item']['drm'], 1)
        calls = len(self.fake.calls)
        with self.assertRaisesRegex(ValueError, 'Kopierschutz'):
            self.enqueue(FILM)                                            # known: refused without asking again
        self.assertEqual(len(self.fake.calls), calls)
        self.assertFalse(portal_title.model(self.root, 'servustv', FILM)['offline']['allowed'])

    def test_end_of_availability_caps_the_offline_period(self):
        end = NOW + 5 * 86400
        self.fake.player['AAU3HRL0S34IKQ6NINUP'] = {
            'playabilityErrors': [], 'duration': 4766, 'availableUntil': iso(end),
            'videoUrl': 'https://play.redbull.com/main/v1/stv/de/de/personal_computer/http/AAU3.m3u8'}
        job = self.job(self.enqueue(FILM)['id'])
        self.assertEqual(job['license']['until'], end)
        self.assertIn('Verfügbarkeitsende', job['license']['note'])
        nd.stamp(job, now=NOW + 3600)
        self.assertEqual((job['offline_until'], job['offline_capped']), (end, True))
        # without an end the full 30 days apply
        plain = {'license': {'kind': 'servustv_offline', 'days': 30}}
        nd.stamp(plain, now=NOW)
        self.assertEqual(plain['offline_until'], NOW + 30 * 86400)
        self.assertNotIn('offline_capped', plain)

    def test_expired_copy_is_removed_at_the_end_of_availability(self):
        end = NOW + 2 * 86400
        self.fake.player['AAU3HRL0S34IKQ6NINUP'] = {
            'playabilityErrors': [], 'duration': 4766, 'currentSunset': int(end * 1000),
            'videoUrl': 'https://play.redbull.com/main/v1/stv/de/de/personal_computer/http/AAU3.m3u8'}
        r = self.enqueue(FILM)
        job = self.job(r['id'])
        video = Path(job['target'])
        video.parent.mkdir(parents=True)
        video.write_bytes(b'mkv')
        video.with_suffix('.nfo').write_text('<movie/>')
        nd.stamp(job, now=NOW + 60)
        job['state'] = 'done'
        self.c.execute("UPDATE jobs SET payload=?,state='done' WHERE id=?", (json.dumps(job), r['id']))
        self.assertEqual(nd.expire(self.c, now=end - 1), [])
        self.assertEqual(nd.expire(self.c, now=end + 1), [r['id']])
        self.assertFalse(video.exists() or video.with_suffix('.nfo').exists())
        item = nd.listing(self.c, origin='servustv')['items'][0]
        self.assertEqual(item['state'], 'expired')

    def test_title_ending_within_the_hour_is_not_started(self):
        self.fake.player['AAU3HRL0S34IKQ6NINUP'] = {
            'playabilityErrors': [], 'availableUntil': iso(NOW + 600),
            'videoUrl': 'https://play.redbull.com/main/v1/stv/de/de/personal_computer/http/AAU3.m3u8'}
        with self.assertRaisesRegex(ValueError, 'nur noch kurz'):
            self.enqueue(FILM)

    def test_availability_end_reads_only_explicit_values(self):
        self.assertIsNone(servustv.availability_end({'availableUntil': '2027-01-01T10:00:00'}))   # no zone
        self.assertIsNone(servustv.availability_end({'availableUntil': 'bald'}))
        self.assertIsNone(servustv.availability_end({'sunset': True}))
        self.assertIsNone(servustv.availability_end({}))
        self.assertEqual(servustv.availability_end({'availability': {'availableTo': 1800000000}}), 1800000000)
        self.assertEqual(servustv.availability_end({'currentSunset': '1800000000000'}), 1800000000)

    def test_download_resolves_a_fresh_address(self):
        job = sd.build_job(self.root, self.media, FILM, now=NOW, check=self.check)
        real = servustv.play_source
        servustv.play_source = lambda root, item_id, **kw: real(root, item_id, opener=self.fake, check=self.hls, now=NOW)
        try:
            url = downloads.source_url(job['source'])
        finally:
            servustv.play_source = real
        self.assertTrue(url.startswith('https://play.redbull.com/'))
        self.assertIn('servustv', downloads.HLS_RESOLVERS)
        self.assertNotIn('?', downloads.public_url(job['source'], url + '?token=1'))

    def test_title_page_offers_the_private_copy(self):
        m = portal_title.model(self.root, 'servustv', FILM)
        self.assertEqual((m['offline']['allowed'], m['offline']['days']), (True, 30))
        self.assertTrue(any('keine Downloads' in n for n in m['notes']))
        series = portal_title.model(self.root, 'servustv', SHOW)
        self.assertFalse(series['offline']['allowed'])
        self.assertTrue(all(e['offline'] for e in series.get('episodes', [])))


class RedBullOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()
        self.fake = FakeRedBull()
        self.assertTrue(redbulltv.sync(self.root, opener=self.fake, now=NOW)['ok'])
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def check(self, root, item_id):
        return redbulltv.play_source(root, item_id, opener=self.fake, check=lambda u: {'variants': 1}, now=NOW)

    def test_film_and_episode(self):
        film = redbulltv.listing(self.root, 'movies')['items'][0]['id']
        r = rd.enqueue(self.c, self.root, self.root / 'media', film, now=NOW, check=self.check)
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        self.assertEqual((job['origin'], job['redbulltv_id'], job['license']['kind'], job['source']['_resolver']),
                         ('redbulltv', film, 'redbulltv_offline', 'redbulltv'))
        self.assertEqual(job['metadata']['provider'], 'Red Bull TV')
        self.assertTrue(any(q.get('tenant') == 'rbtv' for _, q in self.fake.calls))
        series = redbulltv.listing(self.root, 'series')['items'][0]['id']
        episode = redbulltv.episodes(self.root, series)['items'][0]['id']
        r = rd.enqueue(self.c, self.root, self.root / 'media', episode, now=NOW, check=self.check)
        meta = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])['metadata']
        self.assertEqual((meta['kind'], meta['title'], meta['season']), ('series', 'Frontiers', 1))
        self.assertEqual(nd.listing(self.c, origin='redbulltv')['items'][0]['redbulltv_id'], episode)
        with self.assertRaisesRegex(ValueError, 'Live-Sender'):
            rd.enqueue(self.c, self.root, self.root / 'media', redbulltv.channels(self.root)[0]['id'], now=NOW, check=self.check)


MASTER = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="Deutsch",DEFAULT=YES,URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L150,mp4a.40.2",AUDIO="aac"
hevc2160.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3500000,RESOLUTION=1920x1080,CODECS="hvc1.2.4.L120,mp4a.40.2",AUDIO="aac"
hevc1080.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="aac"
avc1080.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2",AUDIO="aac"
avc720.m3u8
'''


class QualityTests(unittest.TestCase):
    def test_h264_preferred_up_to_1080p_4k_on_request(self):
        variants = hls_variants.parse(MASTER, 'https://play.redbull.com/main/v1/x/master.m3u8')
        self.assertEqual(hls_variants.choose(variants, '1080')['uri'], 'hevc1080.m3u8')            # unchanged default
        self.assertEqual(hls_variants.choose(variants, '1080', prefer='avc1')['uri'], 'avc1080.m3u8')
        self.assertEqual(hls_variants.choose(variants, '720', prefer='avc1')['uri'], 'avc720.m3u8')
        self.assertEqual(hls_variants.choose(variants, '2160', prefer='avc1')['uri'], 'hevc2160.m3u8')
        with tempfile.TemporaryDirectory() as tmp:
            path, level = download_quality.hls_playlist(
                'https://play.redbull.com/main/v1/x/master.m3u8', '1080', tmp, prefer='avc1',
                fetch=lambda url: (MASTER, url))
            text = Path(path).read_text('utf-8')
        self.assertIn('avc1080.m3u8', text)
        self.assertIn('audio.m3u8', text)                                  # separate audio rendition kept
        self.assertEqual(level['height'], 1080)


class WiringTests(unittest.TestCase):
    def test_routes_labels_and_packages(self):
        for key, module in (('servustv', sd), ('redbulltv', rd)):
            self.assertIs(platform_registry.BY_KEY[key].offline, module)
            self.assertIn(('POST', '/api/%s-download-add' % key), platform_registry.routes())
        self.assertEqual((storage_policy.ORIGIN_LABEL['servustv'], storage_policy.ORIGIN_LABEL['redbulltv']), ('ServusTV', 'Red Bull TV'))
        build = (ROOT / 'build_macos.py').read_text('utf-8')
        qpkg = (ROOT / 'qpkg-files.txt').read_text('utf-8')
        for name in ('servustv_downloads.py', 'redbulltv_downloads.py'):
            self.assertIn("'%s'" % name, build)
            self.assertIn('./mediathekatlas/' + name, qpkg)
        web = (ROOT / 'web' / 'offline_button.js').read_text('utf-8')
        self.assertIn("servustv: {name: 'ServusTV'", web)
        self.assertIn("redbulltv: {name: 'Red Bull TV'", web)
        title = (ROOT / 'web' / 'portal_title.js').read_text('utf-8')
        self.assertIn("add: 'servustv-download-add'", title)
        self.assertIn("add: 'redbulltv-download-add'", title)
        index = (ROOT / 'web' / 'index.html').read_text('utf-8')
        self.assertNotIn('Offline-Speichern gibt es nicht, ServusTV', index)
        self.assertNotIn('id="servustv-offline" class="nk-offline servustv-offline" hidden', index)
        server = (ROOT / 'server.py').read_text('utf-8')
        self.assertIn("'servustv':servustv,'redbulltv':redbulltv}.get(source)", server)
        self.assertIn("'offline_days':servustv_downloads.OFFLINE_DAYS", server)


if __name__ == '__main__':
    unittest.main()


# ------------------------------------------------------------------ 0.6.54 additions (check of 0.6.52 on the Mac)
import os  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from unittest import mock  # noqa: E402

import dmax  # noqa: E402
import filmfriend  # noqa: E402
import provider_base  # noqa: E402


class SilentServer:
    """Accepts connections and never answers (a request then hangs in http.client._read_status)."""

    def __init__(self, answer=None):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.answer, self.conns = answer, []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(conn)
            if self.answer:
                conn.recv(65536)
                conn.sendall(self.answer)
                conn.close()

    def close(self):
        for c in self.conns:
            c.close()
        self.sock.close()


class DeadlineBeforeHeadTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {'no_proxy': '127.0.0.1,localhost', 'NO_PROXY': '127.0.0.1,localhost'})
        patch.start()
        self.addCleanup(patch.stop)

    def test_hanging_answer_head_ends_after_the_deadline_not_the_socket_timeout(self):
        server = SilentServer()
        self.addCleanup(server.close)
        req = urllib.request.Request('http://127.0.0.1:%d/x' % server.port)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            with provider_base.open_capped(req, timeout=30, deadline=1.0) as response:
                response.read()
        self.assertLess(time.monotonic() - started, 10)

    def test_normal_answer_and_http_errors_pass(self):
        ok = SilentServer(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi')
        self.addCleanup(ok.close)
        with provider_base.open_capped(urllib.request.Request('http://127.0.0.1:%d/' % ok.port), deadline=5) as r:
            self.assertEqual(provider_base.read_capped(r, 100), b'hi')
        bad = SilentServer(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        self.addCleanup(bad.close)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            with provider_base.open_capped(urllib.request.Request('http://127.0.0.1:%d/' % bad.port), deadline=5):
                pass
        self.assertEqual(ctx.exception.code, 404)

    def test_catalogue_modules_use_the_deadline(self):
        for name in ('dmax', 'filmfriend', 'servustv', 'plex', 'pluto', 'rakuten', 'toggo', 'joyn', 'crunchyroll', 'samsung_tvplus'):
            text = (ROOT / (name + '.py')).read_text('utf-8')
            self.assertIn('provider_base.open_capped(req', text, name)
            self.assertNotIn('urllib.request.urlopen(req, timeout=30) as response:\n        if', text, name)

    def test_network_failure_kinds(self):
        self.assertTrue(provider_base.network_failure(TimeoutError()))
        self.assertTrue(provider_base.network_failure(urllib.error.URLError('x')))
        self.assertFalse(provider_base.network_failure(urllib.error.HTTPError('u', 500, 'x', {}, None)))
        self.assertFalse(provider_base.network_failure(ValueError('kaputt')))


class DmaxBudgetTests(unittest.TestCase):
    def test_run_stops_after_three_network_failures_and_retries_in_two_hours(self):
        from test_v0648_dmax import FakeDisco, NOW as DNOW
        fake = FakeDisco()

        def flaky(url, headers, data=None):
            if '/site/shows/' in url and 'muenchen' not in url:
                fake.calls.append(('timeout', url))
                raise TimeoutError('hängt')
            return fake(url, headers, data)
        with tempfile.TemporaryDirectory() as tmp:
            dmax._TOKENS.clear()
            result = dmax.sync(tmp, opener=flaky, now=DNOW)
            self.assertTrue(result['ok'] and result['partial'], result)
            self.assertEqual(sum(1 for c in fake.calls if c[0] == 'timeout'), provider_base.NET_FAILURE_BUDGET)
            state = dmax.state(tmp)
            self.assertEqual(state['next_attempt'], DNOW + provider_base.NET_RETRY)


class FilmfriendFskTests(unittest.TestCase):
    def test_more_details_per_run(self):
        self.assertEqual(filmfriend.MAX_DETAILS, 1200)
        self.assertIn("'FSK noch unbekannt (wird im Hintergrund nachgeladen)'", (ROOT / 'portal_title.py').read_text('utf-8'))
