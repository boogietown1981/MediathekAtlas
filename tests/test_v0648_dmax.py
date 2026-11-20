"""0.6.48/0.6.50: DMAX & TLC (HGTV left out in 0.6.50) – programmes with all episodes.

0.6.50: answers in the shape found on Björn's Mac on 20.11.2026 (public.aurora.enhanced.live/site/: page
"sendungen" with ``blocks[0].items[]`` and programme pages with ``showHeaderBlock`` and ``seoSonicShowBlock``).
Playback is not confirmed, so episodes open on the channel's website; the own-player path is still tested with
``PLAYBACK_CONFIRMED`` switched on. Titles and ids are made up."""
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


def episode(vid, show, name, season, number, package='free', **extra):
    alt = 'season-%d-episode-%d' % (season, number)
    entry = {'id': str(vid), 'alternateId': alt, 'videoType': 'EPISODE', 'videoDuration': 2632000,
             'seasonNumber': season, 'episodeNumber': number, 'publishStart': '2025-10-16T20:05:00Z',
             'publishEnd': '2030-01-01T00:00:00Z', 'package': {'type': package},
             'meta': {'name': name, 'description': 'Über ' + name,
                      'thumbnailUrl': 'https://eu1-prod-images.disco-api.com/%s.jpeg' % vid,
                      'embedUrl': '{domain}/sendungen/%s/%s' % (show, alt)}}
    entry.update(extra)
    return entry


def show_page(slug, title, episodes):
    blocks = [{'type': 'showHeaderBlock', 'show': {'title': title, 'description': 'Sendung ' + title, 'seasons': 2,
                                                   'image': {'src': 'https://eu1-prod-images.disco-api.com/%s.jpeg' % slug}}}]
    if episodes is not None:
        blocks.append({'type': 'seoSonicShowBlock', 'items': episodes})
    return {'blocks': blocks}


CMS = {'dmaxde': {'blocks': [{'type': 'categoryCollectionBlock', 'items': [
           {'title': 'Feuerwache 3 - Alarm in München', 'slug': 'feuerwache-3-alarm-in-muenchen', 'attributes': {'showId': 101},
            'metaMedia': [{'media': {'url': 'https://eu1-prod-images.disco-api.com/show101.jpeg'}}]},
           {'title': 'Goldrausch in Australien', 'slug': 'goldrausch-in-australien', 'attributes': {'showId': '102'}},
           {'title': 'Feuerwache 3 - Alarm in Rostock', 'slug': 'feuerwache-3-alarm-in-rostock', 'attributes': {'showId': 103}},
           {'title': 'Werbung', 'attributes': {}}]}]},
       'tlcde': {'blocks': [{'items': [{'title': 'Ghost Adventures', 'slug': 'ghost-adventures', 'attributes': {'showId': 201}}]}]}}
SHOWS = {
    'feuerwache-3-alarm-in-muenchen': show_page('feuerwache-3-alarm-in-muenchen', 'Feuerwache 3', [
        episode(8873549, 'feuerwache-3-alarm-in-muenchen', '24 Stunden auf der Feuerwache 3', 1, 1),
        episode(8873550, 'feuerwache-3-alarm-in-muenchen', 'Großeinsatz', 1, 2),
        episode(8873551, 'feuerwache-3-alarm-in-muenchen', 'Nachtschicht', 1, 3, package='premium'),
        episode(8873552, 'feuerwache-3-alarm-in-muenchen', 'Abgelaufen', 1, 4, publishEnd='2025-01-01T00:00:00Z'),
        {'id': '999', 'videoType': 'CLIP', 'meta': {'name': 'Ausschnitt'}}]),
    'goldrausch-in-australien': show_page('goldrausch-in-australien', 'Goldrausch', [
        episode(4756322, 'goldrausch-in-australien', 'German Gold', 5, 1, drmEnabled=True)]),
    'feuerwache-3-alarm-in-rostock': show_page('feuerwache-3-alarm-in-rostock', 'Rostock', None),
    'ghost-adventures': show_page('ghost-adventures', 'Ghost Adventures', [
        episode(4550602, 'ghost-adventures', 'Der Poltergeist im Kostümladen', 25, 1)]),
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
        if parts.hostname == 'public.aurora.enhanced.live':
            env = q['filter[environment]']
            assert q['include'] == 'default' and q['v'] == '2'
            if parts.path == '/site/page/sendungen/':
                if env not in CMS:
                    raise http_error(url, 500)
                return json.dumps(CMS[env]).encode()
            slug = parts.path[len('/site/shows/'):-1]
            if slug not in SHOWS:
                raise http_error(url, 404)
            return json.dumps(SHOWS[slug]).encode()
        if parts.path == '/token':
            assert q['realm'] in ('dmaxde', 'tlcde', 'hgtv') and q.get('deviceId')
            return json.dumps({'data': {'attributes': {'token': 'tok-' + q['realm']}}}).encode()
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

    def load(self, now=NOW):
        return dmax.sync(self.root, opener=self.fake, now=now)

    def test_catalogue_from_the_website_api(self):
        result = self.load()
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['series'], result['episodes']), (3, 5))
        st = dmax.state(self.root)
        # HGTV is left out (environment name unknown): no request for it
        self.assertEqual(st['last_result'], 'complete')
        self.assertEqual(st['per_channel'], {'dmax': 4, 'tlc': 1})
        self.assertEqual(st['unavailable'], [])
        self.assertEqual(st['note'], 'Folgen öffnen vorerst beim Sender')
        self.assertEqual(st['protected'], 2)       # one paid episode, one with DRM
        hosts = {c[0] for c in self.fake.calls}
        self.assertEqual(hosts, {'public.aurora.enhanced.live'})      # no token, no loma-cms
        envs = [c[2]['filter[environment]'] for c in self.fake.calls if c[1] == '/site/page/sendungen/']
        self.assertEqual(envs, ['dmaxde', 'tlcde'])
        page = dmax.listing(self.root, view='series')
        titles = [r['title'] for r in page['items']]
        self.assertEqual(titles, ['Feuerwache 3 - Alarm in München', 'Ghost Adventures', 'Goldrausch in Australien'])
        fw = page['items'][0]
        self.assertEqual((fw['id'], fw['episodes'], fw['category']), ('s.dmaxde.101', 3, 'DMAX'))
        self.assertEqual(fw['web_url'], 'https://dmax.de/sendungen/feuerwache-3-alarm-in-muenchen')
        self.assertEqual(fw['poster'], 'https://eu1-prod-images.disco-api.com/show101.jpeg')
        self.assertEqual(fw['summary'] if 'summary' in fw else '', 'Sendung Feuerwache 3')
        self.assertEqual(page['items'][1]['web_url'], 'https://tlc.de/sendungen/ghost-adventures')
        self.assertEqual(page['items'][2]['badge'], 'Kopiergeschützt')
        self.assertEqual(dmax.listing(self.root, view='movies')['total'], 0)
        # episodes in order; clip and expired episode left out; nothing plays in the own player yet
        eps = dmax.episodes(self.root, 's.dmaxde.101')['items']
        self.assertEqual([(e['season'], e['episode'], e['playable'], e['badge']) for e in eps],
                         [(1, 1, 0, 'Kostenlos'), (1, 2, 0, 'Kostenlos'), (1, 3, 0, 'Nur mit discovery+')])
        self.assertEqual(eps[0]['duration'], 2632)
        self.assertEqual(eps[0]['web_url'], 'https://dmax.de/sendungen/feuerwache-3-alarm-in-muenchen/season-1-episode-1')
        self.assertEqual(eps[0]['year'], 2025)
        self.assertEqual(eps[0]['poster'], 'https://eu1-prod-images.disco-api.com/8873549.jpeg')
        self.assertTrue(all(c[3]['User-Agent'] for c in self.fake.calls))

    def test_episodes_open_on_the_website_until_playback_is_confirmed(self):
        self.load()
        with self.assertRaisesRegex(ValueError, 'Website des Senders'):
            dmax.play_source(self.root, 'e.8873549', opener=self.fake, now=NOW)
        self.assertFalse(any(c[1] == '/playback/v3/videoPlaybackInfo' for c in self.fake.calls))

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
        original = CMS['tlcde']
        CMS['tlcde'] = {'blocks': []}
        try:
            result = self.load()
        finally:
            CMS['tlcde'] = original
        self.assertTrue(result['ok'] and result['partial'])
        self.assertIn('TLC nennt keine Sendungen', dmax.state(self.root)['last_error'])

    def test_server_error_of_a_known_channel_is_an_error(self):
        original = CMS.pop('dmaxde')
        try:
            result = self.load()
        finally:
            CMS['dmaxde'] = original
        self.assertTrue(result['ok'] and result['partial'])
        self.assertIn('DMAX', dmax.state(self.root)['last_error'])

    def test_invalid_ids_and_hosts(self):
        for bad in ('', 'e.abc', 's.foo.1', '../x', 'e.1;drop'):
            with self.assertRaises(ValueError):
                dmax.item(self.root, bad)
        with self.assertRaises(ValueError):
            dmax._open('https://evil.example/token', {})
        with self.assertRaises(ValueError):
            dmax._open('http://public.aurora.enhanced.live/site/', {})
        with self.assertRaises(ValueError):
            dmax._open('https://de-api.loma-cms.com/feloma/page/sendungen/', {})

    def test_embed_url_only_on_the_channel_site(self):
        site = dmax.SITES[0]
        bad = show_page('x', 'X', [episode(1, 'x', 'Eins', 1, 1)])
        bad['blocks'][1]['items'][0]['meta']['embedUrl'] = 'https://evil.example/sendungen/x/season-1-episode-1'
        rows, _ = dmax.show_page(bad, site, '1', 'x', NOW)
        self.assertEqual(rows[0]['web_url'], 'https://dmax.de/sendungen/x/season-1-episode-1')

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


class DmaxOwnPlayerTest(unittest.TestCase):
    """The own-player path (switched off until a recording confirms the free stream)."""
    def setUp(self):
        DmaxTest.setUp(self)
        dmax.PLAYBACK_CONFIRMED = True
        self.addCleanup(setattr, dmax, 'PLAYBACK_CONFIRMED', False)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return dmax.sync(self.root, opener=self.fake, now=NOW)

    def test_playback_plain_hls(self):
        self.load()
        self.assertEqual([e['playable'] for e in dmax.episodes(self.root, 's.dmaxde.101')['items']], [1, 1, 0])
        checked = []
        source = dmax.play_source(self.root, 'e.8873549', opener=self.fake, check=checked.append, now=NOW)
        self.assertEqual(source['url'], 'https://dplaynordics-vod-80.akamaized.net/dplaydni/8873549/playlist.m3u8')
        self.assertTrue(source['hls'])
        self.assertEqual(source['provider'], 'dmax')
        self.assertIn('S01E01', source['title'])
        self.assertEqual(checked, [source['url']])
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


if __name__ == '__main__':
    unittest.main()
