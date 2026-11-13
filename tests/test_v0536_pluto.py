"""0.5.36: Pluto TV catalogue (films, series, live) and playback in the in-app player."""
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import pluto, streaming  # noqa: E402

TOKEN = 'eyJhbGciOiJIUzI1NiJ9.' + 'x' * 40
BOOT = {'sessionToken': TOKEN, 'refreshInSec': 3600,
        'servers': {'stitcher': 'https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv'},
        'stitcherParams': 'advertisingId=&appName=web&deviceDNT=0&deviceType=web&sid=abc'}
MOVIE = {'_id': '5f1a2b3c4d5e6f7a8b9c0d1e', 'slug': 'arrival-2015-1-1', 'name': 'Arrival', 'type': 'movie',
         'description': 'Sci-Fi', 'duration': 6420000, 'rating': 'FSK 12', 'genre': 'Sci-Fi & Fantasy',
         'covers': [{'aspectRatio': '16:9', 'url': 'https://images.pluto.tv/a/wide.jpg'},
                    {'aspectRatio': '347:500', 'url': 'https://images.pluto.tv/a/poster.jpg'}],
         'stitched': {'path': '/stitch/hls/episode/5f1a2b3c4d5e6f7a8b9c0d1e/master.m3u8'}}
SERIES = {'_id': '60aabbccddeeff0011223344', 'slug': 'csi', 'name': 'CSI', 'type': 'series',
          'covers': [{'aspectRatio': '347:500', 'url': 'https://evil.example/p.jpg'}]}
VOD = {'categories': [{'name': 'Sci-Fi', 'items': [MOVIE, SERIES, {'_id': 'bad id', 'name': 'x'}]},
                      {'name': 'Neu', 'items': [MOVIE]}]}
CHANNELS = {'data': [{'id': '5ce4475cd43850831ca91ce7', 'name': 'Pluto TV Filme', 'number': 100, 'slug': 'filme',
                      'images': [{'type': 'colorLogoPNG', 'url': 'https://images.pluto.tv/channels/logo.png'}]}]}
SEASONS = {'name': 'CSI', 'seasons': [{'number': 1, 'episodes': [
    {'_id': '61aabbccddeeff0011220001', 'name': 'Pilot', 'number': 1, 'duration': 2580000,
     'stitched': {'urls': [{'type': 'hls', 'url': 'https://service-stitcher.clusters.pluto.tv/stitch/hls/episode/61aabbccddeeff0011220001/master.m3u8?x=1'}]}},
    {'_id': '61aabbccddeeff0011220002', 'name': 'Folge 2', 'number': 2}]}]}


class Fixture(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        pluto._SESSION.update(token='', expires=0, stitcher='', params='')
        pluto._SOURCES.clear()
        self.calls = []

    def fetch(self, url, token=''):
        self.calls.append((url, token))
        parts = urllib.parse.urlsplit(url)
        if parts.hostname == 'boot.pluto.tv':
            q = urllib.parse.parse_qs(parts.query)
            self.assertEqual(q['clientID'][0], pluto.client_id(self.root))
            return BOOT
        self.assertEqual(token, TOKEN)
        if '/vod/categories' in url:
            return VOD
        if '/guide/channels' in url:
            return CHANNELS
        if '/seasons' in url:
            return SEASONS
        raise AssertionError(url)

    def sync(self):
        return pluto.sync(self.root, fetch=self.fetch, now=1000)


class CatalogueTests(Fixture):
    def test_sync_films_series_and_live_channels(self):
        result = self.sync()
        self.assertEqual(result, {'ok': True, 'movie': 1, 'series': 1, 'channel': 1, 'partial': False})
        films = pluto.listing(self.root, 'movies')
        self.assertEqual(films['total'], 1)
        film = films['items'][0]
        self.assertEqual((film['title'], film['year'], film['duration'], film['poster']),
                         ('Arrival', 2015, 6420, 'https://images.pluto.tv/a/poster.jpg'))
        self.assertEqual(pluto.listing(self.root, 'series')['items'][0]['poster'], '')  # foreign image host
        live = pluto.listing(self.root, 'live')['items'][0]
        self.assertEqual((live['number'], live['path']), (100, '/stitch/hls/channel/5ce4475cd43850831ca91ce7/master.m3u8'))
        st = pluto.state(self.root)
        self.assertEqual((st['movies'], st['series'], st['channels'], st['last_result']), (1, 1, 1, 'complete'))
        self.assertNotIn(TOKEN, json.dumps(st))
        self.assertEqual(pluto.listing(self.root, 'movies', query='fantasy')['total'], 1)

    def test_rotated_titles_disappear_but_failed_sync_keeps_stock(self):
        self.sync()
        VOD['categories'][0]['items'].append({**MOVIE, '_id': '5f1a2b3c4d5e6f7a8b9c0d99', 'name': 'Neu'})
        try:
            pluto.sync(self.root, fetch=self.fetch, now=2000)
        finally:
            VOD['categories'][0]['items'].pop()
        pluto.sync(self.root, fetch=self.fetch, now=3000)
        self.assertEqual([i['title'] for i in pluto.listing(self.root, 'movies')['items']], ['Arrival'])

        def broken(url, token=''):
            raise pluto.urllib.error.URLError('down')
        result = pluto.sync(self.root, fetch=broken, now=4000)
        self.assertFalse(result['ok'])
        self.assertIn('nicht erreichbar', result['error'])
        self.assertEqual(pluto.listing(self.root, 'movies')['total'], 1)

    def test_series_episodes_on_demand_and_cached(self):
        self.sync()
        data = pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=1100)
        self.assertEqual([(e['season'], e['episode'], e['title']) for e in data['items']],
                         [(1, 1, 'Pilot'), (1, 2, 'Folge 2')])
        self.assertEqual(data['items'][0]['path'], '/stitch/hls/episode/61aabbccddeeff0011220001/master.m3u8')
        before = len(self.calls)
        pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=1200)
        self.assertEqual(len(self.calls), before)
        with self.assertRaises(ValueError):
            pluto.episodes(self.root, '../etc')


class PlaybackTests(Fixture):
    def test_official_stitcher_hls_with_session(self):
        self.sync()
        source = pluto.play_source(self.root, MOVIE['_id'], fetch=self.fetch, now=1100)
        url = urllib.parse.urlsplit(source['url'])
        self.assertEqual(url.hostname, 'cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv')
        self.assertEqual(url.path, '/v2/stitch/hls/episode/5f1a2b3c4d5e6f7a8b9c0d1e/master.m3u8')
        q = urllib.parse.parse_qs(url.query)
        self.assertEqual(q['jwt'][0], TOKEN)
        self.assertEqual(q['sid'][0], 'abc')
        info = streaming.plan(source)
        self.assertEqual((info['mode'], info['hls'], info['provider'], info['title']),
                         ('remux', True, 'pluto', 'Arrival (2015)'))
        live = streaming.plan(pluto.play_source(self.root, CHANNELS['data'][0]['id'], fetch=self.fetch, now=1100))
        self.assertTrue(live['live'])
        self.assertEqual(live['duration'], 0)

    def test_episode_title_and_series_refused(self):
        self.sync()
        pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=1100)
        src = pluto.play_source(self.root, '61aabbccddeeff0011220001', fetch=self.fetch, now=1100)
        self.assertEqual(src['title'], 'CSI · S01E01 · Pilot')
        with self.assertRaisesRegex(ValueError, 'Folge'):
            pluto.play_source(self.root, SERIES['_id'], fetch=self.fetch)
        with self.assertRaises(ValueError):
            pluto.play_source(self.root, 'ffffffffffffffffffffffff', fetch=self.fetch)

    def test_streaming_resolve_and_rejects_foreign_stitcher(self):
        self.sync()
        pluto._SESSION.update(expires=pluto.time.time() + 3600)  # session from the sync is reused
        source = streaming.resolve(None, pluto=MOVIE['_id'], root=self.root)
        self.assertTrue(source['hls'])
        with self.assertRaises(ValueError):
            pluto._stitcher('https://evil.example')
        with self.assertRaises(ValueError):
            pluto.stream_url({'stitcher': 'https://x.pluto.tv', 'params': '', 'token': TOKEN}, '/../etc/passwd')

    def test_unexpected_api_host_refused(self):
        with self.assertRaises(ValueError):
            pluto._fetch_json('https://evil.example/v4/start')


class WiringTests(unittest.TestCase):
    def test_server_ui_and_packages(self):
        server = (ROOT / 'server.py').read_text('utf-8')
        for needle in ("path=='/api/pluto'", "path=='/api/pluto-sync'", "('offer','job','netzkino','pluto','justwatch','rakuten','joyn','toggo','crunchyroll')",
                       "pluto=q.get('pluto',[''])[0]", "'pluto':pluto.state(ROOT)", "'/pluto.js'"):
            self.assertTrue(__import__('_wiring').wired(needle), needle)
        self.assertIn("'pluto.py'", (ROOT / 'build_macos.py').read_text('utf-8'))
        html = (ROOT / 'web' / 'index.html').read_text('utf-8')
        self.assertIn('<script src="/pluto.js"></script>', html)
        self.assertNotIn('Pluto TV (Vorschau)', html)
        self.assertIn('window.playPluto=function', (ROOT / 'web' / 'player.js').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
