"""0.5.102/0.5.107: RTL+ – the free guest area as a catalogue with links, never played (Widevine).

Answers have the shape the public open-source RTL+ clients read (OIDC token, Bedrock token, Bedrock
layout API with ``bffPaginated`` blocks of ``classic`` items; the free area is folder 193, further
block pages via ``/folder/<id>/block/<blockId>``). Titles and ids are made up; RTL+ is blocked here."""
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


def entry(ident, title, kind='program', locked=False, seo=None, highlight='Krimi • 2024', details='', parent=None):
    layout = {'type': kind, 'id': str(ident), 'seo': seo or 'titel-%s' % ident}
    if parent:
        layout['parent'] = {'type': 'program', 'id': str(parent), 'seo': 'titel-%s' % parent}
    target = {'type': 'layout', 'value_layout': layout}
    if locked:
        target = {'type': 'lock', 'value_lock': {'originalTarget': target}}
    return {'itemType': 'classic', 'itemContent': {
        'title': title, 'description': 'Über ' + title, 'highlight': highlight, 'extraDetails': details,
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
        if path == '/folder/193/layout':
            assert headers['X-Location'] == rtlplus.FREE_LOCATION
            if query['blockPage'] == '1':
                return json.dumps({'pagination': {'nextPage': 2}, 'blocks': [
                    block('frei-filme', [entry(101, 'Ein freier Film', details='Film • 2019'),
                                         entry(555, 'Folge 3', 'video', details='Serie', parent=201)], 2),
                    {'id': 'hero', 'type': 'hero', 'content': {'items': [entry(999, 'Banner', 'video')]}}]}).encode()
            return json.dumps({'blocks': [block('frei-serien', [entry(301, 'Eine Show', highlight='Reality'),
                                                                entry(777, 'Kostenlose Kinderserien', 'folder'),
                                                                entry(778, 'Alter Ordner', 'folder')], 4)]}).encode()
        if path == '/folder/193/block/frei-filme':
            assert query['page'] == '2'
            return json.dumps({'id': 'frei-filme', 'type': 'bffPaginated', 'content': {
                'items': [entry(103, 'Zweiter freier Film', details='Film')], 'pagination': {}}}).encode()
        if path == '/folder/193/block/frei-serien':
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)     # Björn's diagnosis: 404 on a further page
        if path == '/folder/777/layout':
            if self.fail_folder == '777':
                raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)
            return json.dumps({'blocks': [block('kinder', [entry(401, 'Kinderserie', highlight='Zeichentrick'),
                                                         entry(193, 'Zurück', 'folder')])]}).encode()
        # main folders: only counted (free titles appear there too)
        if path == '/folder/4/layout':
            return json.dumps({'blocks': [block('filme', [entry(101, 'Ein freier Film'), entry(102, 'Abo-Film'),
                                                        entry(104, 'Gesperrter Film', locked=True)])]}).encode()
        if path == '/folder/3/layout':
            return json.dumps({'blocks': [block('serien', [entry(201, 'Freie Serie'), entry(202, 'Abo-Serie')])]}).encode()
        if path == '/folder/1/layout':
            raise urllib.error.HTTPError(url, 500, 'Server Error', {}, None)  # counting may fail quietly
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
        # Free area only; 102, 104 and 202 need RTL+ and are only counted.
        self.assertEqual(result, {'ok': True, 'partial': False, 'movies': 2, 'series': 3, 'premium': 3})
        movies = rtlplus.listing(self.root, 'movies')
        self.assertEqual([i['title'] for i in movies['items']], ['Ein freier Film', 'Zweiter freier Film'])
        series = {i['id']: i for i in rtlplus.listing(self.root, 'series')['items']}
        self.assertEqual(set(series), {'s.201', 's.301', 's.401'})   # 201 from an episode tile, 401 from a sub-folder
        self.assertEqual(series['s.301']['web_url'], 'https://plus.rtl.de/titel-301-p_301')
        self.assertEqual(series['s.201']['web_url'], 'https://plus.rtl.de/titel-201-p_201')
        self.assertTrue(all(i['playable'] == 0 and i['drm'] == 1 for i in series.values()))
        self.assertTrue(any('/folder/193/block/frei-filme' in c for c in fake.calls))
        self.assertFalse(any('/service/' in c for c in fake.calls))
        self.assertEqual(sum(1 for c in fake.calls if '/folder/193/layout' in c), 2)   # layout page 2 as well
        state = rtlplus.state(self.root)
        self.assertEqual((state['movies'], state['series'], state['premium'], state['last_result']), (2, 3, 3, 'complete'))
        self.assertTrue(state['free_catalog'])

    def test_my_subscription_shows_abo_titles(self):
        # Björn 13.11.2026: "für Dienste, die einen Account brauchen ... RTL+ hätte ich"
        import ui_prefs
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        self.assertNotIn('m.102', {i['id'] for i in rtlplus.listing(self.root, 'movies')['items']})
        ui_prefs.save(self.root, {'abo_rtlplus': True})
        movies = {i['id']: i for i in rtlplus.listing(self.root, 'movies')['items']}
        self.assertEqual(set(movies), {'m.101', 'm.102', 'm.103', 'm.104'})
        self.assertEqual((movies['m.102']['badge'], movies['m.101']['badge']), ('In deinem RTL+ Abo', 'kostenlos'))
        self.assertEqual(movies['m.104']['web_url'], 'https://plus.rtl.de/titel-104-p_104')
        model = portal_title.model(self.root, 'rtlplus', 'm.102')
        self.assertIn(['Angebot', 'RTL+, nur mit Abo (in deinem Abo)'], model['provider_facts'])
        with self.assertRaises(hls_guard.DrmProtected):
            rtlplus.play_source(self.root, 'm.102')                  # still played only at RTL+
        self.assertFalse(any('pass' in k for k in ui_prefs.load(self.root)))   # no login data anywhere

    def test_subscription_titles_of_older_versions_disappear(self):
        db = rtlplus._connect(self.root)
        with db:
            rtlplus._store(db, [dict(rtlplus.item_from(entry(102, 'Abo-Film'), 'movie', 'filme')[0])], NOW - 100)
            rtlplus._set(db, 'last_success', NOW - 100)
        db.close()
        self.assertFalse(rtlplus.state(self.root)['free_catalog'])
        rtlplus.sync(self.root, opener=FakeRtl(fail_folder='777'), now=NOW)          # even a partial first run
        self.assertNotIn('m.102', {i['id'] for i in rtlplus.listing(self.root, 'movies')['items']})

    def test_video_tile_links_to_its_programme(self):
        tile = entry(1417600, 'Ein Film', 'video')
        tile['itemContent']['action']['target']['value_layout']['parent'] = {'id': '9001', 'seo': 'ein-film'}
        it, locked = rtlplus.item_from(tile, 'movie', 'filme')
        self.assertEqual((it['id'], it['path'], locked), ('m.9001', '9001', False))
        self.assertEqual(it['web_url'], 'https://plus.rtl.de/ein-film-p_9001')

    def test_link_scheme_confirmed_by_bjoern(self):
        # plus.rtl.de/kurbis-chaos-in-der-heimat-p_1068 (13.11.2026)
        self.assertEqual(rtlplus.web_url('filme', 'kurbis-chaos-in-der-heimat', '1068'),
                         'https://plus.rtl.de/kurbis-chaos-in-der-heimat-p_1068')
        self.assertEqual(rtlplus.web_url('filme', 'Böse Url', '1'), 'https://plus.rtl.de/')

    def test_old_links_are_rewritten_once(self):
        rtlplus.sync(self.root, opener=FakeRtl(), now=NOW)
        db = rtlplus._connect(self.root)
        with db:
            db.execute("UPDATE rtlplus_items SET web_url='https://plus.rtl.de/video-tv/filme/28-weeks-later-67082' WHERE id='m.101'")
            rtlplus._set(db, 'links_v2', 0)
        db.close()
        self.assertEqual(rtlplus.item(self.root, 'm.101')['item']['web_url'], 'https://plus.rtl.de/28-weeks-later-p_67082')

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
        result = rtlplus.sync(self.root, opener=FakeRtl(fail_folder='777'), now=NOW + 100)
        self.assertTrue(result['ok'] and result['partial'])
        state = rtlplus.state(self.root)
        self.assertEqual(state['last_result'], 'partial')
        self.assertIn('Unterordner 777): RTL+ antwortet mit HTTP 500', state['last_error'])
        # The series from the earlier full load stays visible.
        self.assertIn('s.401', {i['id'] for i in rtlplus.listing(self.root, 'series')['items']})

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
