"""0.5.101/0.5.102: ServusTV On – free video library and live channels, plain HLS in the own player.

Answers have the shape recorded in Björn's HAR of servustv.com (13.11.2026): tv-api.redbull.com
products (``collections`` with ids) and collections (``cards``, ``meta.total``/``meta.next``, 20 per
page), api-player.redbull.com/tv (``videoUrl`` or ``playabilityErrors``). Titles and ids are made
up; ServusTV is blocked in the build environment."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import hls_guard
import live_tv
import portal_title
import servustv
import streaming

NOW = 1794556800
IMG = 'https://resources.redbull.tv/%s/rbtv_display_art_portrait/{im}?namespace=stv&refresh=true'


def card(ident, title, ctype, **extra):
    base = {'id': ident, 'title': title, 'type': 'video' if ctype not in ('show', 'subchannel') else ctype,
            'content_type': ctype, 'long_description': 'Über ' + title, 'duration': 2812160, 'playable': True,
            'media_resources': {'rbtv_display_art_portrait': {'url': IMG % ident}},
            'share_url': 'https://www.servustv.com/de/page/page:' + ident}
    base.update(extra)
    return base


NATUR = [card('AA%018d' % n, 'Folge %d' % n, 'episode', show_name='Bergwelten', subheading='Bergwelten',
              season_number=13, episode_number=n, content_color=['Natur']) for n in range(1, 26)]
FILMS = [card('AAU3HRL0S34IKQ6NINUP', 'Sundown - Geheimnisse in Acapulco', 'film', duration=4766040,
              tags=['Unterhaltung'], content_color=['Unterhaltung']),
         card('AACLIPCLIPCLIPCLIP01', 'Kurzer Clip', 'clip', duration=222880),
         card('AASHORTSHORTSHORT01', 'Kurzes Video ohne Sendung', 'video', duration=300000)]
SHOW = card('AA-25RX849FN1W11', 'Messner erklärt die Achttausender', 'show', content_color=['Natur'])
SEASON = [card('AAMESSNER%011d' % n, 'Teil %d' % n, 'episode', season_number=1, episode_number=n) for n in (1, 2)]
CHANNELS = [card('PN0B1EC15B2FE10', 'ServusTV: Der Livestream', 'video_channel'),
            card('PN2C35800228344', 'Wetterpanorama On', 'video_channel')]
PRODUCTS = {
    'sendungen': {'id': 'sendungen', 'type': 'page', 'collections': [
        {'id': '16f72eb7-0bb8-43e7-a314-287205fe9a06', 'list_type': 'reference'},
        {'id': '1d9e083e-5b80-4f57-96dd-24d1e7cc6e27'}, {'id': 'dbca43da-6420-475b-94b8-6fd187dd347e'}]},
    'PN3MIRXVT1EXR8T': {'id': 'PN3MIRXVT1EXR8T', 'content_type': 'subchannel', 'collections': [
        {'id': 'c688c1d4-62f5-49e1-bd19-8e33242088cf'}, {'id': '0834cca5-f64d-49c0-9ef3-a666bdac652e'}]},
    'AA-25RX849FN1W11': {'id': 'AA-25RX849FN1W11', 'content_type': 'show', 'collections': [
        {'id': '27e85b45-1d42-43e7-9997-f97958db461a'}]},
}
COLLECTIONS = {
    '1d9e083e-5b80-4f57-96dd-24d1e7cc6e27': [card('PN3MIRXVT1EXR8T', 'Filme & Serien', 'subchannel'), SHOW],
    'dbca43da-6420-475b-94b8-6fd187dd347e': NATUR,
    'c688c1d4-62f5-49e1-bd19-8e33242088cf': FILMS,
    '0834cca5-f64d-49c0-9ef3-a666bdac652e': CHANNELS,
    '27e85b45-1d42-43e7-9997-f97958db461a': SEASON,
}


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'no', {}, io.BytesIO(b''))


class FakeServus:
    def __init__(self):
        self.calls, self.player, self.down = [], {}, False

    def __call__(self, url, headers, limit=None):
        if self.down:
            raise urllib.error.URLError('offline')
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.hostname, parts.path, q))
        assert headers['Referer'] == 'https://www.servustv.com/'
        if parts.hostname == 'tv-api.redbull.com':
            kind, ident = parts.path.split('/stv/de/de/')
            if kind == '/products/v5.3':
                if ident not in PRODUCTS:
                    raise http_error(url, 404)
                return json.dumps(PRODUCTS[ident]).encode()
            cards = COLLECTIONS.get(ident)
            if cards is None:
                raise http_error(url, 404)
            offset = int(q.get('offset', 0))
            page = cards[offset:offset + 20]
            meta = {'total': len(cards)}
            if offset + 20 < len(cards):
                meta['next'] = '/collections/v5.1/stv/de/de/%s?offset=%d' % (ident, offset + 20)
            return json.dumps({'id': ident, 'cards': page, 'meta': meta}).encode()
        if parts.hostname == 'api-player.redbull.com' and parts.path == '/tv':
            vid = q['videoId']
            self.assert_query(q)
            answer = self.player.get(vid) or {
                'videoId': vid, 'playabilityErrors': [], 'duration': 4766,
                'videoUrl': 'https://play.redbull.com/main/v1/stv/de/de/personal_computer/http/%s.m3u8?device_group=group_5' % vid}
            return json.dumps(answer).encode()
        raise AssertionError('unexpected host ' + url)

    @staticmethod
    def assert_query(q):
        assert (q['deviceGroup'], q['locale'], q['tenant']) == ('group_5', 'de', 'stv'), q


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()
        self.fake = FakeServus()

    def tearDown(self):
        self.tmp.cleanup()


class CatalogueTests(Base):
    def test_crawl_pages_rails_and_shows(self):
        result = servustv.sync(self.root, opener=self.fake, now=NOW)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['partial'])
        self.assertEqual((result['movies'], result['series'], result['episodes'], result['channels']), (1, 2, 27, 2))
        offsets = [c[2]['offset'] for c in self.fake.calls if c[1].endswith('dbca43da-6420-475b-94b8-6fd187dd347e')]
        self.assertEqual(offsets, ['0', '20'])           # 25 cards: two pages
        self.assertNotIn('/collections/v5.3/stv/de/de/16f72eb7-0bb8-43e7-a314-287205fe9a06',
                         [c[1] for c in self.fake.calls])  # personal list skipped
        film = servustv.listing(self.root, 'movies')['items']
        self.assertEqual([f['title'] for f in film], ['Sundown - Geheimnisse in Acapulco'])   # no clips
        self.assertEqual(film[0]['duration'], 4766)
        self.assertEqual(film[0]['poster'], 'https://resources.redbull.tv/AAU3HRL0S34IKQ6NINUP/rbtv_display_art_portrait/'
                                            'im:i:w_480,q_70?namespace=stv&refresh=true')
        self.assertEqual(film[0]['web_url'], 'https://www.servustv.com/de/page/AAU3HRL0S34IKQ6NINUP')
        shows = {s['title']: s for s in servustv.listing(self.root, 'series')['items']}
        self.assertEqual({k: v['episodes'] for k, v in shows.items()},
                         {'Bergwelten': 25, 'Messner erklärt die Achttausender': 2})
        self.assertEqual(shows['Messner erklärt die Achttausender']['id'], 's.AA-25RX849FN1W11')
        eps = servustv.episodes(self.root, 's.n-bergwelten')['items']
        self.assertEqual([(e['season'], e['episode']) for e in eps[:2]], [(13, 1), (13, 2)])
        live = servustv.listing(self.root, 'live')['items']
        self.assertEqual([(c['title'], c['number']) for c in live], [('ServusTV: Der Livestream', 1), ('Wetterpanorama On', 2)])

    def test_failure_keeps_catalogue(self):
        servustv.sync(self.root, opener=self.fake, now=NOW)
        self.fake.down = True
        result = servustv.sync(self.root, opener=self.fake, now=NOW + 10)
        self.assertFalse(result['ok'])
        self.assertEqual(servustv.listing(self.root, 'movies')['total'], 1)
        self.assertEqual(servustv.state(self.root)['last_result'], 'failed')
        self.assertEqual(len(servustv.channels(self.root)), 2)

    def test_live_fallback_after_failed_first_run(self):
        self.assertEqual(servustv.channels(self.root), [])          # never tried: nothing yet
        self.fake.down = True
        servustv.sync(self.root, opener=self.fake, now=NOW)
        self.assertEqual([c['id'] for c in servustv.channels(self.root)], ['c.PN0B1EC15B2FE10'])

    def test_ids_and_images(self):
        self.assertTrue(servustv.VALID_ID.fullmatch('v.AAU3HRL0S34IKQ6NINUP'))
        self.assertTrue(servustv.VALID_ID.fullmatch('s.n-bergwelten'))
        self.assertFalse(servustv.VALID_ID.fullmatch('v.AA-1;drop'))
        self.assertEqual(servustv.image({'media_resources': {'rbtv_display_art_portrait': {'url': 'http://x/{im}'}}}), '')
        with self.assertRaises(ValueError):
            servustv.collection(self.fake, '../x')


class PlaybackTests(Base):
    def setUp(self):
        super().setUp()
        servustv.sync(self.root, opener=self.fake, now=NOW)
        self.checked = []

    def check(self, url):
        self.checked.append(url)
        return {'variants': 1, 'protected': False}

    def test_episode_plays_as_checked_hls(self):
        vid = 'v.AA%018d' % 2
        src = servustv.play_source(self.root, vid, opener=self.fake, check=self.check, now=NOW)
        self.assertTrue(src['url'].startswith('https://play.redbull.com/main/v1/stv/de/de/personal_computer/http/AA'))
        self.assertTrue(src['hls'])
        self.assertEqual(src['title'], 'Bergwelten · S13E02 · Folge 2')
        servustv.play_source(self.root, vid, opener=self.fake, check=self.check, now=NOW + 5)
        self.assertEqual(len(self.checked), 1)          # remembered for two minutes

    def test_youth_protection_and_geo_are_named(self):
        self.fake.player['AAU3HRL0S34IKQ6NINUP'] = {
            'playabilityErrors': ['FSK_BLOCKED'],
            'playabilityErrorDetails': {'FSK_BLOCKED': {'minEveningHour': 22, 'maxMorningHour': 6, 'minAge': 16}}}
        with self.assertRaises(ValueError) as ctx:
            servustv.play_source(self.root, 'v.AAU3HRL0S34IKQ6NINUP', opener=self.fake, check=self.check, now=NOW)
        self.assertEqual(str(ctx.exception), 'Jugendschutz: ServusTV zeigt dieses Video nur von 22:00 bis 06:00 Uhr (ab 16 Jahren).')
        self.fake.player['AA%018d' % 3] = {'playabilityErrors': ['GEO_BLOCKED']}
        with self.assertRaisesRegex(ValueError, 'Geosperre'):
            servustv.play_source(self.root, 'v.AA%018d' % 3, opener=self.fake, check=self.check, now=NOW)

    def test_protected_stream_is_refused_and_remembered(self):
        def drm(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        vid = 'v.AA%018d' % 4
        with self.assertRaises(hls_guard.DrmProtected):
            servustv.play_source(self.root, vid, opener=self.fake, check=drm, now=NOW)
        servustv.sync(self.root, opener=self.fake, now=NOW + 100)       # a new catalogue run keeps it
        self.assertEqual(servustv.item(self.root, vid)['item']['playable'], 0)

    def test_live_channel(self):
        src = servustv.play_source(self.root, 'c.PN0B1EC15B2FE10', opener=self.fake, check=self.check, now=NOW)
        self.assertTrue(src['live'])
        self.assertEqual(src['duration'], 0)
        rows = live_tv.servustv_channels(self.root)
        self.assertEqual([(r['title'], r['play']) for r in rows],
                         [('ServusTV: Der Livestream', {'servustv': 'c.PN0B1EC15B2FE10'}),
                          ('Wetterpanorama On', {'servustv': 'c.PN2C35800228344'})])

    def test_streaming_resolve(self):
        original = servustv.play_source
        servustv.play_source = lambda root, item_id: {'kind': 'url', 'url': 'https://a/b.m3u8', 'item': item_id}
        try:
            self.assertEqual(streaming.resolve(None, servustv='c.PN0B1EC15B2FE10', root=self.root)['item'], 'c.PN0B1EC15B2FE10')
        finally:
            servustv.play_source = original

    def test_title_page(self):
        m = portal_title.model(self.root, 'servustv', 's.AA-25RX849FN1W11')
        self.assertEqual(len(m['episodes']), 2)
        m = portal_title.model(self.root, 'servustv', 'v.AAU3HRL0S34IKQ6NINUP')
        self.assertFalse(m['offline']['allowed'])
        self.assertIn(['Angebot', 'ServusTV On, kostenlos (ohne Konto)'], m['provider_facts'])


class WiringTests(unittest.TestCase):
    def test_stale_wordpress_error_cleared_on_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = servustv._connect(tmp)
            with db:
                servustv._set(db, 'last_error', 'WordPress: ServusTV ist nicht erreichbar')
            db.close()
            servustv.sync(tmp, opener=FakeServus(), now=NOW)
            self.assertEqual(servustv.state(tmp)['last_error'], '')

    def test_wiring(self):
        here = Path(__file__).resolve().parent.parent
        server = (here / 'server.py').read_text(encoding='utf-8')
        for needle in ("'servustv',", "servustv=q.get('servustv',[''])[0]", "'servustv':servustv.state(ROOT)",
                       "'/servustv.js'", "'source':'servustv'"):
            self.assertIn(needle, server)
        self.assertIn("'servustv.py','servustv_enrichment.py'", (here / 'build_macos.py').read_text(encoding='utf-8'))
        index = (here / 'web' / 'index.html').read_text(encoding='utf-8')
        for needle in ('id="servustv"', 'data-platform="servustv"', 'data-catalog-source="servustv"', '/servustv.js'):
            self.assertIn(needle, index)
        import platform_registry
        self.assertIn('servustv', platform_registry.KEYS)
        self.assertIsNone(platform_registry.BY_KEY['servustv'].offline)


if __name__ == '__main__':
    unittest.main()
