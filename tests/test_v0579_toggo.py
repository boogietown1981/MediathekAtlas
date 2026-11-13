"""0.5.79: TOGGO (children's series of toggo.de incl. TOGGOLINO).

toggo.de was not reachable while this was written and no HAR existed. The answers below have the
publicly documented shapes (sitemap standard; asset API and address patterns as in yt-dlp's Toggo
extractor; Brightcove Playback API); all values are synthetic. Nothing here proves the live formats."""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import hls_guard, portal_title, streaming, unified_index  # noqa: E402
import toggo, toggo_enrichment  # noqa: E402

ROBOTS = 'User-agent: *\nDisallow: /api/\nSitemap: https://www.toggo.de/sitemap.xml\nSitemap: https://evil.example/sitemap.xml\n'
INDEX = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
         '<sitemap><loc>https://www.toggo.de/sitemap-serien.xml</loc></sitemap>'
         '<sitemap><loc>https://www.toggo.de/sitemap-pages.xml</loc></sitemap>'
         '<sitemap><loc>https://evil.example/sitemap-x.xml</loc></sitemap></sitemapindex>')
SERIEN = ('<urlset>' + ''.join('<url><loc>%s</loc></url>' % u for u in (
    'https://www.toggo.de/serien/paw-patrol',
    'https://www.toggo.de/toggolino/paw-patrol/folge/der-wetter-zeppelin',
    'https://www.toggo.de/toggolino/paw-patrol/folge/der-chili-kochwettbewerb',
    'https://www.toggo.de/toggolino/paw-patrol/video/rettung-im-anflug',
    'https://www.toggo.de/weihnachtsmann--co-kg/folge/ein-geschenk-fuer-zwei',
    "https://www.toggo.de/grizzy--die-lemminge/folge/rock&apos;n&apos;lemming",
    'https://www.toggo.de/grizzy--die-lemminge/folge/rock%27n%27lemming',          # same episode, encoded
    'https://evil.example/x/folge/y',
    'https://www.toggo.de/spiele/irgendwas')) + '</urlset>')
PAGES = '<urlset><url><loc>https://www.toggo.de/weihnachtsmann--co-kg</loc></url><url><loc>https://www.toggo.de/</loc></url></urlset>'
IMG = 'https://images.toggo.de/%s.jpg?width=640'


def asset(ident, title, series, season, episode, video='6300000000001', images=True):
    return {'data': {'id': ident, 'title': title, 'description': title + ' Inhalt', 'language': 'de',
                     'images': {'Teaser': IMG % ident, 'Bad': 'http://insecure.example/x.jpg'} if images else {},
                     'custom_fields': [{'key': 'other', 'value': 'x'}, {'key': 'video-cloud-id', 'value': video}],
                     'series_title': series, 'season_title': series, 'season_no': season, 'season_id': 'VST1',
                     'episode_no': episode, 'earliest_start_date': 1637259179}}


ASSETS = {
    'der-wetter-zeppelin': asset('VEP1', 'Der Wetter-Zeppelin', 'PAW Patrol', 2, 5, '6300000000001'),
    'der-chili-kochwettbewerb': asset('VEP2', 'Der Chili-Kochwettbewerb', 'PAW Patrol', 2, 6, '6300000000002'),
    'rettung-im-anflug': asset('VCL1', 'Rettung im Anflug', 'PAW Patrol', None, None, '6300000000003'),
    'ein-geschenk-fuer-zwei': asset('VEP2977', 'Ein Geschenk für zwei', 'Weihnachtsmann & Co. KG', 1, 7, '6300000000004'),
    "rock'n'lemming": asset('VEP9', "Rock'n'Lemming", 'Grizzy & die Lemminge', 1, 3, '6300000000005'),
}
PK = 'BCpkADawqM0' + 'a' * 60
DRM_SOURCES = [
    {'src': 'https://manifest.prod.boltdns.net/manifest/v1/dash/live/cenc/6057955896001/x/2s/manifest.mpd', 'type': 'application/dash+xml',
     'key_systems': {'com.widevine.alpha': {'license_url': 'https://manifest.prod.boltdns.net/license/v1/cenc/widevine/x'}}},
    {'src': 'https://manifest.prod.boltdns.net/manifest/v1/hls/v4/fairplay/6057955896001/x/2s/master.m3u8', 'type': 'application/x-mpegURL',
     'key_systems': {'com.apple.fps.1_0': {'key_request_url': 'https://x'}}}]
CLEAR_HLS = {'src': 'https://manifest.prod.boltdns.net/manifest/v1/hls/v4/clear/6057955896001/x/2s/master.m3u8', 'type': 'application/x-mpegURL'}


class Site:
    """Stand-in for toggo._fetch: serves the documents above and records what was asked."""

    def __init__(self, sources=None, fail=(), config=True):
        self.sources = DRM_SOURCES if sources is None else sources
        self.fail, self.config, self.calls = set(fail), config, []

    def __call__(self, url, headers=None):
        self.calls.append((url, headers or {}))
        if any(part in url for part in self.fail):
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b'[]'))
        if url == 'https://www.toggo.de/robots.txt':
            return ROBOTS.encode()
        if url == 'https://www.toggo.de/sitemap.xml':
            return INDEX.encode()
        if url == 'https://www.toggo.de/sitemap-serien.xml':
            return SERIEN.encode()
        if url == 'https://www.toggo.de/sitemap-pages.xml':
            return PAGES.encode()
        if url.startswith(toggo.ASSET_API):
            slug = urllib.parse.unquote(url[len(toggo.ASSET_API):])
            if slug not in ASSETS:
                raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b'{}'))
            return json.dumps(ASSETS[slug]).encode()
        if url == toggo.PLAYER_CONFIG:
            if not self.config:
                raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
            return json.dumps({'video_cloud': {'policy_key': PK}}).encode()
        if url == toggo.PLAYER_SCRIPT:
            return ('x={accountId:"6057955896001",policyKey:"%s"}' % PK).encode()
        if url.startswith(toggo.PLAYBACK_API):
            assert (headers or {}).get('Accept') == 'application/json;pk=' + PK
            return json.dumps({'name': 'x', 'duration': 1320000, 'sources': self.sources}).encode()
        raise AssertionError('unexpected address ' + url)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        toggo._POLICY.clear()
        toggo._SOURCES.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, site=None, **kw):
        site = site or Site()
        return site, toggo.sync(self.root, fetch=site, now=1000.0, gap=0, **kw)

    def series(self, title):
        rows = toggo.listing(self.root, 'series', limit='all')['items']
        return next(r for r in rows if r['title'] == title)


class ParsingTests(unittest.TestCase):
    def test_addresses_of_episodes_and_clips(self):
        e = toggo.classify('https://www.toggo.de/toggolino/paw-patrol/folge/der-wetter-zeppelin')
        self.assertEqual(e, {'prefix': 'toggolino/', 'series': 'paw-patrol', 'clip': False, 'slug': 'der-wetter-zeppelin'})
        self.assertTrue(toggo.classify('https://www.toggo.de/paw-patrol/video/clip-1/')['clip'])
        for bad in ('https://www.toggo.de/paw-patrol', 'https://www.toggo.de/a/b/folge/c', 'http://www.toggo.de/a/folge/b',
                    'https://www.toggo.de.evil.example/a/folge/b', 'https://www.toggo.de/toggolino/folge/x',
                    'https://www.toggo.de/a/folge/b?x=1', 'https://www.toggo.de/a/folge/b"onload'):
            self.assertIsNone(toggo.classify(bad), bad)

    def test_link_is_encoded_for_the_page(self):
        e = toggo.classify("https://www.toggo.de/grizzy--die-lemminge/folge/rock'n'lemming")
        self.assertEqual(toggo.episode_url(e), 'https://www.toggo.de/grizzy--die-lemminge/folge/rock%27n%27lemming')

    def test_sitemap_text_and_robots(self):
        self.assertEqual(toggo.robots_sitemaps(ROBOTS), ['https://www.toggo.de/sitemap.xml'])
        self.assertTrue(toggo.is_index(INDEX))
        self.assertIn("https://www.toggo.de/grizzy--die-lemminge/folge/rock'n'lemming", toggo.locs(SERIEN))
        self.assertEqual(toggo.pretty('der-wetter-zeppelin'), 'Der Wetter Zeppelin')

    def test_shapes_carry_no_titles(self):
        shapes = toggo.shapes(toggo.locs(SERIEN))
        self.assertEqual(shapes['toggolino/*/folge/*'], 2)
        self.assertNotIn('paw', json.dumps(shapes))

    def test_asset_fields(self):
        f = toggo.asset_fields(ASSETS['ein-geschenk-fuer-zwei'])
        self.assertEqual((f['title'], f['series_title'], f['season'], f['episode'], f['video_id']),
                         ('Ein Geschenk für zwei', 'Weihnachtsmann & Co. KG', 1, 7, '6300000000004'))
        self.assertEqual(f['poster'], IMG % 'VEP2977')
        self.assertEqual(toggo.asset_fields({'error': 'x'}), {})
        bad = asset('V', 'T', 'S', 1, 1, video='../../etc')
        self.assertEqual(toggo.asset_fields(bad)['video_id'], '')

    def test_only_fixed_hosts_are_fetched(self):
        for url in ('https://evil.example/x', 'http://www.toggo.de/robots.txt', 'https://user@www.toggo.de/x',
                    'https://www.toggo.de:8443/x'):
            with self.assertRaises(ValueError):
                toggo._fetch(url)


class CatalogueTests(Fixture):
    def test_sync_builds_series_and_episodes(self):
        site, result = self.load()
        self.assertEqual((result['ok'], result['partial'], result['series'], result['episodes'], result['clips']),
                         (True, False, 3, 4, 1))
        self.assertFalse([u for u, _ in site.calls if 'evil.example' in u])
        rows = toggo.listing(self.root, 'series', limit='all')
        self.assertEqual([r['title'] for r in rows['items']], ['Grizzy & die Lemminge', 'PAW Patrol', 'Weihnachtsmann & Co. KG'])
        paw = self.series('PAW Patrol')
        self.assertEqual((paw['brand'], paw['poster'], paw['web_url']), ('TOGGOLINO', IMG % 'VEP1', 'https://www.toggo.de/serien/paw-patrol'))
        self.assertIn('Kinder & Familie', paw['categories'])
        self.assertIn('TOGGOLINO', paw['categories'])
        self.assertEqual(self.series('Weihnachtsmann & Co. KG')['web_url'], 'https://www.toggo.de/weihnachtsmann--co-kg')
        self.assertEqual(toggo.listing(self.root, 'movies')['total'], 0)
        self.assertEqual(toggo.listing(self.root, 'live')['total'], 0)
        self.assertEqual(toggo.listing(self.root, 'series', genre='TOGGOLINO')['total'], 1)
        self.assertEqual(toggo.listing(self.root, 'series', query='grizzy')['total'], 1)

    def test_state_after_run_and_protection_probe(self):
        self.load()
        st = toggo.state(self.root)
        self.assertEqual((st['last_result'], st['series'], st['episodes'], st['clips'], st['movies'], st['channels']),
                         ('complete', 3, 4, 1, 0, 0))
        self.assertEqual((st['protection'], st['protected'], st['playable']), ('drm', 3, 0))

    def test_episodes_are_completed_on_demand(self):
        self.load()
        paw = self.series('PAW Patrol')
        site = Site()
        data = toggo.episodes(self.root, paw['id'], fetch=site)
        self.assertEqual([(e['season'], e['episode'], e['title']) for e in data['items']],
                         [(2, 5, 'Der Wetter-Zeppelin'), (2, 6, 'Der Chili-Kochwettbewerb'), (None, None, 'Clip · Rettung im Anflug')])
        self.assertEqual((data['error'], data['note']), ('', ''))
        self.assertEqual(len([u for u, _ in site.calls if u.startswith(toggo.ASSET_API)]), 2)   # first episode came with the run
        again = Site()
        toggo.episodes(self.root, paw['id'], fetch=again)
        self.assertEqual(again.calls, [])
        self.assertTrue(all(e['web_url'].startswith('https://www.toggo.de/toggolino/paw-patrol/') for e in data['items']))

    def test_missing_episode_details_are_reported_not_fatal(self):
        self.load()
        paw = self.series('PAW Patrol')
        data = toggo.episodes(self.root, paw['id'], fetch=Site(fail=('der-chili',)))
        self.assertEqual(len(data['items']), 3)
        self.assertIn('1 Folgen fehlen noch', data['note'])
        self.assertIn('HTTP 404', data['error'])
        self.assertIn('Der Chili Kochwettbewerb', [e['title'] for e in data['items']])   # title from the address meanwhile

    def test_second_run_keeps_loaded_details_and_hides_vanished_series(self):
        self.load()
        paw = self.series('PAW Patrol')
        toggo.episodes(self.root, paw['id'], fetch=Site())

        class Smaller(Site):
            def __call__(self, url, headers=None):
                if url == 'https://www.toggo.de/sitemap-serien.xml':
                    self.calls.append((url, {}))
                    return SERIEN.replace('<url><loc>https://www.toggo.de/weihnachtsmann--co-kg/folge/ein-geschenk-fuer-zwei</loc></url>', '').encode()
                return super().__call__(url, headers)
        site = Smaller()
        result = toggo.sync(self.root, fetch=site, now=5000.0, gap=0)
        self.assertEqual(result['series'], 2)
        self.assertEqual([r['title'] for r in toggo.listing(self.root, 'series', limit='all')['items']],
                         ['Grizzy & die Lemminge', 'PAW Patrol'])
        self.assertFalse([u for u, _ in site.calls if u.startswith(toggo.ASSET_API)])   # titles are still fresh
        self.assertEqual(toggo.episodes(self.root, paw['id'], fetch=Site())['items'][0]['title'], 'Der Wetter-Zeppelin')

    def test_sitemap_without_episodes_is_a_clear_failure(self):
        class Empty(Site):
            def __call__(self, url, headers=None):
                if url == 'https://www.toggo.de/sitemap-serien.xml':
                    return b'<urlset><url><loc>https://www.toggo.de/spiele/x</loc></url></urlset>'
                return super().__call__(url, headers)
        result = toggo.sync(self.root, fetch=Empty(), now=1000.0, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('Sitemap', result['error'])
        self.assertIn('3 Sitemaps', result['error'])   # index + two lists
        self.assertEqual(toggo.state(self.root)['last_result'], 'failed')

    def test_unreachable_site_keeps_the_stored_catalogue(self):
        self.load()

        def down(url, headers=None):
            raise urllib.error.URLError(OSError('down'))
        result = toggo.sync(self.root, fetch=down, now=9000.0, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('nicht erreichbar', result['error'])
        self.assertEqual(toggo.listing(self.root, 'series')['total'], 3)

    def test_series_details_failing_gives_partial_catalogue(self):
        site, result = self.load(Site(fail=('assetstore',)))
        self.assertEqual((result['ok'], result['partial'], result['series']), (True, True, 3))
        self.assertIn('Paw Patrol', [r['title'] for r in toggo.listing(self.root, 'series', limit='all')['items']])
        self.assertIn('fehlen noch', toggo.state(self.root)['last_error'])

    def test_usual_sitemap_places_when_robots_names_none(self):
        class NoRobots(Site):
            def __call__(self, url, headers=None):
                if url.endswith('/robots.txt'):
                    return b'User-agent: *\n'
                if url.endswith('/sitemap_index.xml') or url.endswith('/sitemap-index.xml') or url.endswith('/sitemaps/sitemap.xml'):
                    raise urllib.error.HTTPError(url, 404, 'x', {}, io.BytesIO(b''))
                return super().__call__(url, headers)
        self.assertEqual(toggo.sync(self.root, fetch=NoRobots(), now=1000.0, gap=0)['series'], 3)


class PlaybackTests(Fixture):
    def episode(self, title='Der Wetter-Zeppelin'):
        paw = self.series('PAW Patrol')
        return next(e for e in toggo.episodes(self.root, paw['id'], fetch=Site())['items'] if e['title'] == title)

    def test_protected_sources_are_refused_and_remembered(self):
        self.load()
        ep = self.episode()
        self.assertEqual(ep['playable'], 0)                      # the run's probe found DRM only
        with self.assertRaises(hls_guard.DrmProtected) as ctx:
            toggo.play_source(self.root, ep['id'], fetch=Site())
        self.assertIn('Kopierschutz', str(ctx.exception))
        self.assertEqual(toggo.item(self.root, ep['id'])['item']['drm'], 1)

    def test_no_address_is_rewritten_to_reach_an_unlisted_variant(self):
        self.load()
        site = Site()
        with self.assertRaises(hls_guard.DrmProtected):
            toggo.play_source(self.root, self.episode()['id'], fetch=site)
        self.assertFalse([u for u, _ in site.calls if '/clear/' in u])
        self.assertEqual(toggo.pick_source(DRM_SOURCES), (None, 2))

    def test_plain_stream_plays_and_flips_the_catalogue(self):
        site = Site(sources=DRM_SOURCES + [CLEAR_HLS])
        checked = []
        toggo.sync(self.root, fetch=site, now=1000.0, gap=0, check=lambda url: None)
        self.assertEqual(toggo.state(self.root)['protection'], 'clear')
        toggo._SOURCES.clear()
        ep_id = self.episode()['id']
        source = toggo.play_source(self.root, ep_id, fetch=site, check=checked.append)
        self.assertEqual(checked, [CLEAR_HLS['src']])
        self.assertEqual((source['kind'], source['hls'], source['provider'], source['duration']), ('url', True, 'toggo', 1320))
        self.assertEqual(source['title'], 'PAW Patrol · Der Wetter-Zeppelin')
        st = toggo.state(self.root)
        self.assertEqual(st['protection'], 'clear')
        self.assertNotIn('playable', st)
        self.assertEqual(self.episode('Der Chili-Kochwettbewerb')['playable'], 1)

    def test_playlist_that_announces_drm_counts_as_protected(self):
        toggo.sync(self.root, fetch=Site(sources=[CLEAR_HLS]), now=1000.0, gap=0, check=lambda url: None)

        def refuse(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        toggo._SOURCES.clear()
        with self.assertRaises(hls_guard.DrmProtected):
            toggo.play_source(self.root, self.episode('Der Chili-Kochwettbewerb')['id'], fetch=Site(sources=[CLEAR_HLS]), check=refuse)
        # One protected episode does not turn the whole catalogue to "protected".
        self.assertEqual(toggo.state(self.root)['protection'], 'clear')
        self.assertEqual(self.episode('Der Chili-Kochwettbewerb')['playable'], 0)
        self.assertEqual(self.episode('Der Wetter-Zeppelin')['playable'], 1)

    def test_mp4_fallback_prefers_up_to_1080p(self):
        sources = [{'src': 'https://cdn.example/a_2160.mp4', 'type': 'video/mp4', 'height': 2160},
                   {'src': 'https://cdn.example/a_720.mp4', 'container': 'MP4', 'height': 720},
                   {'src': 'https://cdn.example/a_1080.mp4', 'type': 'video/mp4', 'height': 1080},
                   {'src': 'http://cdn.example/insecure.mp4', 'type': 'video/mp4', 'height': 1080}]
        picked, protected = toggo.pick_source(sources)
        self.assertEqual((picked['url'], picked['hls'], protected), ('https://cdn.example/a_1080.mp4', False, 0))

    def test_policy_key_from_script_when_config_is_missing(self):
        self.assertEqual(toggo.policy_key(Site(config=False), now=1.0), PK)

    def test_series_and_bad_ids(self):
        self.load()
        with self.assertRaises(ValueError):
            toggo.play_source(self.root, self.series('PAW Patrol')['id'], fetch=Site())
        for bad in ('', 'e.xyz', "e.0000000000000000' OR 1=1", 's.123'):
            with self.assertRaises(ValueError):
                toggo.play_source(self.root, bad, fetch=Site())

    def test_streaming_resolve_routes_to_toggo(self):
        self.load()
        with self.assertRaises(ValueError):
            streaming.resolve(None, toggo='e.0000000000000000', root=self.root)


class IntegrationTests(Fixture):
    def test_title_page_model(self):
        self.load()
        paw = self.series('PAW Patrol')
        toggo.episodes(self.root, paw['id'], fetch=Site())
        m = portal_title.model(self.root, 'toggo', paw['id'])
        self.assertEqual((m['kind'], m['title'], m['provider']), ('series', 'PAW Patrol', 'TOGGO'))
        self.assertEqual(len(m['episodes']), 3)
        self.assertFalse(any(e['offline'] for e in m['episodes']))
        self.assertIn(['Angebot', 'TOGGOLINO (Vorschule), kostenlos'], m['provider_facts'])
        self.assertIn(['Folgen und Clips laut TOGGO', '3'], m['provider_facts'])
        ep = portal_title.model(self.root, 'toggo', m['episodes'][0]['id'])
        self.assertEqual((ep['kind'], ep['playable'], ep['offline']['allowed']), ('episode', False, False))
        self.assertTrue(ep['web_url'].startswith('https://www.toggo.de/toggolino/paw-patrol/folge/'))
        self.assertTrue(any('Kopierschutz' in fact[1] for fact in ep['provider_facts']))

    def test_reference_spec_and_merged_index(self):
        self.load()
        self.assertEqual(toggo_enrichment.SPEC.items, 'toggo_items')
        self.assertTrue(toggo_enrichment.pending(self.root, 10))
        self.assertIn('toggo', unified_index.SOURCES)
        offers, _ = unified_index._portal_offers('toggo', toggo.listing, self.root, 'series', '', '', '')
        self.assertEqual(len(offers), 3)

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        for needle in ("path=='/api/toggo'", "path=='/api/toggo-details'", "path=='/api/toggo-sync'", "path=='/api/toggo-auto'",
                       "path=='/api/toggo-enrich'", "toggo=q.get('toggo',[''])[0]", "'/toggo.js'", 'toggo_catalog_scheduler',
                       "'toggo':toggo.state(ROOT)"):
            self.assertTrue(__import__('_wiring').wired(needle), needle)
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        for needle in ('data-catalog-source="toggo"', 'data-platform="toggo"', '<section id="toggo"', '<script src="/toggo.js">',
                       'id="toggo-sync"', 'id="toggo-items"'):
            self.assertIn(needle, html)
        self.assertNotIn('toggo-download-add', server)            # no offline copies in this version
        self.assertIn('window.playToggo', (ROOT / 'web' / 'player.js').read_text(encoding='utf-8'))
        for name in ('toggo.py', 'toggo_enrichment.py'):
            self.assertIn("'%s'" % name, (ROOT / 'build_macos.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
