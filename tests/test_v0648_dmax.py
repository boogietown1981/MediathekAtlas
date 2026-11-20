"""0.6.48: DMAX, TLC & HGTV – programmes with all episodes, plain HLS in the own player.

The answers have the shape the public clients use (yt-dlp dplay.py, Brawl345/Get-DMAX-Links): CMS page
"sendungen" with ``blocks[].items[].attributes.showId``, disco-api token, JSON:API ``content/videos`` with
``included`` show and images, ``playback/v3/videoPlaybackInfo``. Titles and ids are made up; the hosts are
blocked in the build environment."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import dmax
import hls_guard
import platform_registry
import streaming
import unified_index

NOW = 1795132800   # 20.11.2026


def video(vid, show, name, season, episode, **extra):
    attrs = {'name': name, 'description': 'Über ' + name, 'seasonNumber': season, 'episodeNumber': episode,
             'videoDuration': 2632000, 'alternateId': name.lower().replace(' ', '-'), 'airDate': '2025-10-16T20:05:00Z',
             'drmEnabled': False}
    attrs.update(extra)
    return {'id': str(vid), 'type': 'video', 'attributes': attrs,
            'relationships': {'show': {'data': {'id': str(show), 'type': 'show'}},
                              'images': {'data': [{'id': 'img%s' % vid, 'type': 'image'}]},
                              'genres': {'data': [{'id': 'g1', 'type': 'genre'}]}}}


def page(videos, show, show_name, slug, total=1):
    inc = [{'id': str(show), 'type': 'show', 'attributes': {'name': show_name, 'alternateId': slug, 'description': 'Sendung ' + show_name}},
           {'id': 'g1', 'type': 'genre', 'attributes': {'name': 'Blaulicht'}}]
    inc += [{'id': 'img%s' % v['id'], 'type': 'image', 'attributes': {'src': 'https://eu1-prod-images.disco-api.com/%s.jpeg' % v['id']}}
            for v in videos]
    return {'data': videos, 'included': inc, 'meta': {'totalPages': total}}


CMS = {'dmax': {'blocks': [{'items': [
           {'title': 'Feuerwache 3 - Alarm in München', 'slug': 'feuerwache-3-alarm-in-muenchen', 'attributes': {'showId': 101},
            'image': {'src': 'https://eu1-prod-images.disco-api.com/show101.jpeg'}},
           {'title': 'Goldrausch in Australien', 'attributes': {'showId': '102'}},
           {'title': 'Werbung', 'attributes': {}}]}]},
       'tlc': {'blocks': [{'items': [{'title': 'Ghost Adventures', 'url': '/sendungen/ghost-adventures', 'attributes': {'showId': 201}}]}]},
       'hgtv': {'blocks': [{'items': [{'title': 'Leere Sendung', 'attributes': {'showId': 301}}]}]}}
EPISODES = {
    '101': [page([video(8873549, 101, '24 Stunden auf der Feuerwache 3', 1, 1),
                  video(8873550, 101, 'Großeinsatz', 1, 2)], 101, 'Feuerwache 3', 'feuerwache-3-alarm-in-muenchen', total=2),
            page([video(8873551, 101, 'Nachtschicht', 1, 3,
                        availabilityWindows=[{'package': 'Premium', 'playableStart': '2025-01-01T00:00:00Z'}])],
                 101, 'Feuerwache 3', 'feuerwache-3-alarm-in-muenchen', total=2)],
    '102': [page([video(4756322, 102, 'German Gold', 5, 1, drmEnabled=True)], 102, 'Goldrausch in Australien', 'goldrausch-in-australien')],
    '201': [page([video(4550602, 201, 'Der Poltergeist im Kostümladen', 25, 1,
                        availabilityWindows=[{'package': 'Free', 'playableStart': '2024-12-23T10:00:00Z',
                                              'playableEnd': '2030-01-01T00:00:00Z'}])], 201, 'Ghost Adventures', 'ghost-adventures')],
}


def http_error(url, code, body=b''):
    return urllib.error.HTTPError(url, code, 'no', {}, io.BytesIO(body))


class FakeDisco:
    def __init__(self):
        self.calls, self.down, self.playback = [], False, None
        self.invalid_once = False

    def __call__(self, url, headers, data=None):
        if self.down:
            raise urllib.error.URLError('offline')
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.hostname, parts.path, q, dict(headers), data))
        if parts.hostname == 'de-api.loma-cms.com':
            return json.dumps(CMS[q['environment']]).encode()
        if parts.path == '/token':
            assert q['realm'] in ('dmaxde', 'tlcde', 'hgtv') and q.get('deviceId')
            return json.dumps({'data': {'attributes': {'token': 'tok-' + q['realm']}}}).encode()
        if parts.path == '/content/videos/':
            assert headers['Authorization'].startswith('Bearer tok-')
            pages = EPISODES.get(q['filter[show.id]'])
            if not pages:
                raise http_error(url, 404)
            return json.dumps(pages[int(q['page[number]']) - 1]).encode()
        if parts.path == '/playback/v3/videoPlaybackInfo':
            body = json.loads(data.decode())
            assert body['deviceInfo']['drmSupported'] is False
            if self.invalid_once:
                self.invalid_once = False
                raise http_error(url, 401, json.dumps({'errors': [{'code': 'invalid.token'}]}).encode())
            if self.playback is not None:
                return json.dumps(self.playback).encode()
            return json.dumps({'data': {'attributes': {'streaming': [
                {'type': 'hls', 'url': 'https://dplaynordics-vod-80.akamaized.net/dplaydni/%s/playlist.m3u8' % body['videoId'],
                 'protection': {'drmEnabled': False}}]}}}).encode()
        raise AssertionError(url)


class DmaxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        dmax._TOKENS.clear()
        dmax._SOURCES.clear()
        self.fake = FakeDisco()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return dmax.sync(self.root, opener=self.fake, now=NOW)

    def test_catalogue_of_three_channels(self):
        result = self.load()
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['series'], result['episodes']), (3, 5))
        st = dmax.state(self.root)
        self.assertEqual(st['last_result'], 'complete')
        self.assertEqual(st['per_channel'], {'dmax': 4, 'tlc': 1, 'hgtv': 0})
        self.assertEqual(st['protected'], 2)       # one discovery+ episode, one with DRM
        page = dmax.listing(self.root, view='series')
        titles = [r['title'] for r in page['items']]
        self.assertEqual(titles, ['Feuerwache 3 - Alarm in München', 'Ghost Adventures', 'Goldrausch in Australien'])
        fw = page['items'][0]
        self.assertEqual((fw['id'], fw['episodes'], fw['category']), ('s.dmaxde.101', 3, 'DMAX'))
        self.assertIn('Blaulicht', fw['genre'])
        self.assertEqual(fw['web_url'], 'https://dmax.de/sendungen/feuerwache-3-alarm-in-muenchen')
        self.assertEqual(fw['poster'], 'https://eu1-prod-images.disco-api.com/show101.jpeg')
        self.assertEqual(page['items'][1]['web_url'], 'https://tlc.de/sendungen/ghost-adventures')
        self.assertEqual(page['items'][2]['badge'], 'Kopiergeschützt')
        self.assertEqual(dmax.listing(self.root, view='movies')['total'], 0)
        # pages through all episode pages (totalPages 2), episodes in order, badges per episode
        eps = dmax.episodes(self.root, 's.dmaxde.101')['items']
        self.assertEqual([(e['season'], e['episode'], e['playable'], e['badge']) for e in eps],
                         [(1, 1, 1, ''), (1, 2, 1, ''), (1, 3, 0, 'Nur mit discovery+')])
        self.assertEqual(eps[0]['duration'], 2632)
        self.assertEqual(eps[0]['web_url'], 'https://dmax.de/sendungen/feuerwache-3-alarm-in-muenchen/24-stunden-auf-der-feuerwache-3')
        self.assertEqual(eps[0]['year'], 2025)
        # every request to the platform carries the Discovery client headers; tokens are per realm
        content = [c for c in self.fake.calls if c[1] == '/content/videos/']
        self.assertTrue(all(c[3]['X-Disco-Client'] == dmax.DISCO_CLIENT for c in content))
        self.assertEqual({c[3]['X-Disco-Params'] for c in content}, {'realm=dmaxde', 'realm=tlcde', 'realm=hgtv'})

    def test_offline_keeps_old_catalogue_and_names_the_cause(self):
        self.load()
        self.fake.down = True
        result = dmax.sync(self.root, opener=self.fake, now=NOW + 86400)
        self.assertFalse(result['ok'])
        st = dmax.state(self.root)
        self.assertEqual(st['last_result'], 'failed')
        self.assertIn('nicht erreichbar', st['last_error'])
        self.assertEqual(dmax.listing(self.root, view='series')['total'], 3)

    def test_one_failing_channel_gives_a_partial_catalogue(self):
        original = CMS['tlc']
        CMS['tlc'] = {'blocks': []}
        try:
            result = self.load()
        finally:
            CMS['tlc'] = original
        self.assertTrue(result['ok'] and result['partial'])
        self.assertIn('TLC nennt keine Sendungen', dmax.state(self.root)['last_error'])

    def test_playback_plain_hls(self):
        self.load()
        checked = []
        source = dmax.play_source(self.root, 'e.8873549', opener=self.fake, check=checked.append, now=NOW)
        self.assertEqual(source['url'], 'https://dplaynordics-vod-80.akamaized.net/dplaydni/8873549/playlist.m3u8')
        self.assertTrue(source['hls'])
        self.assertEqual(source['provider'], 'dmax')
        self.assertIn('S01E01', source['title'])
        self.assertEqual(checked, [source['url']])
        # the stored episode is now known to be unprotected
        self.assertEqual(dmax.item(self.root, 'e.8873549')['item']['drm'], 0)

    def test_expired_token_is_renewed_once(self):
        self.load()
        self.fake.invalid_once = True
        source = dmax.play_source(self.root, 'e.8873550', opener=self.fake, check=lambda url: None, now=NOW)
        self.assertIn('8873550', source['url'])

    def test_protected_and_paid_episodes_are_refused(self):
        self.load()
        with self.assertRaises(hls_guard.DrmProtected):
            dmax.play_source(self.root, 'e.4756322', opener=self.fake, now=NOW)
        with self.assertRaisesRegex(ValueError, 'discovery\\+'):
            dmax.play_source(self.root, 'e.8873551', opener=self.fake, now=NOW)
        # a stream answer marked as protected is remembered
        self.fake.playback = {'data': {'attributes': {'streaming': [
            {'type': 'hls', 'url': 'https://x.akamaized.net/hls_fairPlay_ts/master.m3u8', 'protection': {'drmEnabled': True}}]}}}
        with self.assertRaises(hls_guard.DrmProtected):
            dmax.play_source(self.root, 'e.4550602', opener=self.fake, now=NOW)
        self.assertEqual(dmax.item(self.root, 'e.4550602')['item']['badge'], 'Kopiergeschützt')

    def test_streaming_resolves_dmax(self):
        self.load()
        original = dmax._open
        dmax._open = self.fake
        try:
            import hls_guard as guard
            saved = guard.check
            guard.check = lambda url, fetch=None: None
            try:
                source = streaming.resolve(None, root=self.root, dmax='e.8873549')
            finally:
                guard.check = saved
        finally:
            dmax._open = original
        self.assertIn('8873549', source.get('url', '') or json.dumps(source))

    def test_invalid_ids_and_hosts(self):
        for bad in ('', 'e.abc', 's.foo.1', '../x', 'e.1;drop'):
            with self.assertRaises(ValueError):
                dmax.item(self.root, bad)
        with self.assertRaises(ValueError):
            dmax._open('https://evil.example/token', {})
        with self.assertRaises(ValueError):
            dmax._open('http://eu1-prod.disco-api.com/token', {})

    def test_offer_windows(self):
        self.assertEqual(dmax.offer_of({}, NOW), 'free')
        self.assertEqual(dmax.offer_of({'availabilityWindows': [{'package': 'Premium'}]}, NOW), 'premium')
        self.assertEqual(dmax.offer_of({'availabilityWindows': [{'package': 'Registered', 'playableEnd': '2020-01-01T00:00:00Z'}]}, NOW), 'premium')
        self.assertEqual(dmax.offer_of({'availabilityWindows': [{'package': 'Free'}]}, NOW), 'free')

    def test_wiring(self):
        self.assertIn('dmax', [p.key for p in platform_registry.PLATFORMS])
        self.assertIsNone(next(p for p in platform_registry.PLATFORMS if p.key == 'dmax').offline)
        self.assertIn('dmax', unified_index.SOURCES)
        root = Path(__file__).resolve().parents[1]
        html = (root / 'web' / 'index.html').read_text('utf-8')
        self.assertIn('<section id="dmax"', html)
        self.assertIn('<script src="/dmax.js"></script>', html)
        self.assertIn("'dmax.py'", (root / 'build_macos.py').read_text('utf-8'))
        self.assertIn('window.playDmax', (root / 'web' / 'player.js').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
