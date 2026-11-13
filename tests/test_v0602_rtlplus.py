"""0.5.102: RTL+ – the free part of RTL+ as a catalogue with links, never played (Widevine).

Answers have the shape the public open-source RTL+ clients read (OIDC token, Bedrock token, Bedrock
layout API with ``bffPaginated`` blocks of ``classic`` items, further pages via
``service/rtlplus_root/block``). Titles and ids are made up; RTL+ is blocked in the build environment."""
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import hls_guard
import portal_title
import rtlplus
import streaming

NOW = 1794556800


def entry(ident, title, kind='program', locked=False, seo=None, highlight='Krimi • 2024'):
    target = {'type': 'layout', 'value_layout': {'type': kind, 'id': str(ident), 'seo': seo or 'titel-%s' % ident}}
    if locked:
        target = {'type': 'lock', 'value_lock': {'originalTarget': target}}
    return {'itemType': 'classic', 'itemContent': {
        'title': title, 'description': 'Über ' + title, 'highlight': highlight,
        'image': {'idsByRatio': {'2:3': 'img%s' % ident}}, 'action': {'target': target}}}


def block(block_id, items, next_page=None):
    return {'id': block_id, 'type': 'bffPaginated',
            'content': {'items': items, 'pagination': {'nextPage': next_page} if next_page else {}}}


class FakeRtl:
    def __init__(self, deny_layout=0, fail_folder=None):
        self.calls, self.deny_layout, self.fail_folder, self.logins = [], deny_layout, fail_folder, 0

    def __call__(self, url, headers, data=None):
        self.calls.append(url)
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if url.startswith(rtlplus.TOKEN_URL):
            self.logins += 1
            self.assertBody(data)
            return json.dumps({'access_token': 'anon-token-' + 'a' * 30}).encode()
        if url.startswith(rtlplus.BEDROCK_AUTH):
            assert headers['Authorization'].startswith('Bearer anon-token-')
            return json.dumps({'token': 'bedrock-token-' + 'b' * 30}).encode()
        assert headers['X-Bedrock-Token'].startswith('bedrock-token-')
        if self.deny_layout:
            self.deny_layout -= 1
            raise urllib.error.HTTPError(url, 401, 'Unauthorized', {}, None)
        path = parts.path.split('token-web-31', 1)[1]
        if path == '/folder/4/layout':
            return json.dumps({'blocks': [
                block('filme-neu', [entry(101, 'Ein freier Film', 'video'), entry(102, 'Premium-Film', 'video', locked=True)], 2),
                {'id': 'hero', 'type': 'hero', 'content': {'items': [entry(999, 'Banner', 'video')]}}]}).encode()
        if path == '/service/rtlplus_root/block/filme-neu':
            assert query['page'] == '2'
            return json.dumps({'id': 'filme-neu', 'type': 'bffPaginated', 'content': {
                'items': [entry(103, 'Zweiter freier Film', 'video')], 'pagination': {}}}).encode()
        if path == '/folder/3/layout':
            return json.dumps({'blocks': [block('serien', [entry(201, 'Freie Serie'), entry(202, 'Premium-Serie', locked=True),
                                                         {'itemType': 'promo'}])]}).encode()
        if path == '/folder/1/layout':
            if self.fail_folder == '1':
                raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)
            return json.dumps({'blocks': [block('shows', [entry(301, 'Eine Show', highlight='Reality')])]}).encode()
        if path == '/folder/148/layout':
            return json.dumps({'blocks': [block('kids', [entry(201, 'Freie Serie'), entry(401, 'Kinderserie', highlight='Zeichentrick'),
                                                         entry(777, 'Genre Zeichentrick', 'folder'), entry(778, 'Alter Ordner', 'folder')], 5)]}).encode()
        if path == '/service/rtlplus_root/block/kids':
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)     # Björn's diagnosis: 404 on a further page
        if path == '/folder/777/layout':
            return json.dumps({'blocks': [block('genre-777', [entry(402, 'Genre-Serie'), entry(4, 'Filme', 'folder')])]}).encode()
        raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)

    @staticmethod
    def assertBody(data):
        body = dict(urllib.parse.parse_qsl(data.decode()))
        assert body['client_id'] == 'anonymous-user' and body['grant_type'] == 'client_credentials'


class RtlPlusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalogue_lists_free_titles_and_counts_premium(self):
        fake = FakeRtl()
        result = rtlplus.sync(self.root, opener=fake, now=NOW)
        self.assertEqual(result, {'ok': True, 'partial': False, 'movies': 2, 'series': 4, 'premium': 2})
        movies = rtlplus.listing(self.root, 'movies')
        self.assertEqual([i['title'] for i in movies['items']], ['Ein freier Film', 'Zweiter freier Film'])
        series = {i['id']: i for i in rtlplus.listing(self.root, 'series')['items']}
        self.assertEqual(set(series), {'s.201', 's.301', 's.401', 's.402'})   # 402 from the linked genre folder
        self.assertEqual(sum(1 for c in fake.calls if '/folder/4/layout' in c), 1)
        self.assertEqual(series['s.301']['web_url'], 'https://plus.rtl.de/video-tv/shows/titel-301-301')
        self.assertIn('Kinder', series['s.401']['genre'])
        self.assertNotIn('2024', series['s.201']['genre'])
        self.assertTrue(all(i['playable'] == 0 and i['drm'] == 1 for i in series.values()))
        self.assertTrue(any('/service/rtlplus_root/block/filme-neu' in c for c in fake.calls))
        state = rtlplus.state(self.root)
        self.assertEqual((state['movies'], state['series'], state['premium'], state['last_result']), (2, 4, 2, 'complete'))

    def test_video_tile_links_to_its_programme(self):
        tile = entry(1417600, 'Ein Film', 'video')
        tile['itemContent']['action']['target']['value_layout']['parent'] = {'id': '9001', 'seo': 'ein-film'}
        it, locked = rtlplus.item_from(tile, 'movie', 'filme')
        self.assertEqual((it['id'], it['path'], locked), ('m.9001', '9001', False))
        self.assertEqual(it['web_url'], 'https://plus.rtl.de/video-tv/filme/ein-film-9001')

    def test_signed_images(self):
        url = rtlplus.image_url('img101')
        self.assertTrue(url.startswith('https://images-fio.rtlde.bedrock.tech/v2/images/img101/raw?'))
        self.assertRegex(url, r'&hash=[0-9a-f]{40}$')
        self.assertEqual(rtlplus.image_url('../evil'), '')
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        film = rtlplus.item(self.root, 'm.101')['item']
        self.assertEqual(film['poster'], rtlplus.image_url('img101'))

    def test_expired_token_is_renewed_once(self):
        fake = FakeRtl(deny_layout=1)
        self.assertTrue(rtlplus.sync(self.root, opener=fake, now=NOW)['ok'])
        self.assertEqual(fake.logins, 2)

    def test_failed_folder_keeps_rest_and_old_catalogue(self):
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        result = rtlplus.sync(self.root, opener=FakeRtl(fail_folder='1'), now=NOW + 100)
        self.assertTrue(result['ok'] and result['partial'])
        state = rtlplus.state(self.root)
        self.assertEqual(state['last_result'], 'partial')
        self.assertIn('Shows: RTL+ antwortet mit HTTP 500', state['last_error'])
        # The show from the earlier full load stays visible.
        self.assertIn('s.301', {i['id'] for i in rtlplus.listing(self.root, 'series')['items']})

    def test_unreachable_keeps_catalogue(self):
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)

        def down(url, headers, data=None):
            raise urllib.error.URLError('blocked')
        result = rtlplus.sync(self.root, opener=down, now=NOW + 100)
        self.assertFalse(result['ok'])
        self.assertEqual(rtlplus.state(self.root)['last_result'], 'failed')
        self.assertEqual(rtlplus.listing(self.root, 'movies')['total'], 2)

    def test_never_played(self):
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        with self.assertRaises(hls_guard.DrmProtected) as caught:
            rtlplus.play_source(self.root, 'm.101')
        self.assertIn('Kopierschutz', str(caught.exception))
        with self.assertRaises(hls_guard.DrmProtected):
            streaming.resolve(None, rtlplus='m.101', root=self.root)
        with self.assertRaises(ValueError):
            rtlplus.play_source(self.root, 'x.1')

    def test_series_page_links_out(self):
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        answer = rtlplus.episodes(self.root, 's.201')
        self.assertEqual(answer['items'], [])
        self.assertIn('RTL+', answer['note'])
        model = portal_title.model(self.root, 'rtlplus', 'm.101')
        self.assertFalse(model['offline']['allowed'])

    def test_only_rtl_hosts(self):
        with self.assertRaises(ValueError):
            rtlplus._open('https://example.com/x', {})
        with self.assertRaises(ValueError):
            rtlplus.Api(opener=FakeRtl()).layout('/../etc', {})

    def test_wiring(self):
        here = Path(__file__).resolve().parent.parent
        server = (here / 'server.py').read_text(encoding='utf-8')
        for needle in ("'rtlplus')", "rtlplus=q.get('rtlplus',[''])[0]", "'rtlplus':rtlplus.state(ROOT)",
                       "'/rtlplus.js'", "'source':'rtlplus'"):
            self.assertIn(needle, server)
        self.assertIn("'rtlplus.py','rtlplus_enrichment.py'", (here / 'build_macos.py').read_text(encoding='utf-8'))
        index = (here / 'web' / 'index.html').read_text(encoding='utf-8')
        for needle in ('id="rtlplus"', 'data-platform="rtlplus"', 'data-catalog-source="rtlplus"', '/rtlplus.js'):
            self.assertIn(needle, index)
        import platform_registry
        self.assertIn('rtlplus', platform_registry.KEYS)
        self.assertIsNone(platform_registry.BY_KEY['rtlplus'].offline)


if __name__ == '__main__':
    unittest.main()
