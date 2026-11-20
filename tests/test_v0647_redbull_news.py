"""0.6.47: Red Bull TV on the ServusTV engine, WELT and n-tv straight from the broadcasters.

Red Bull TV and the broadcasters are blocked in the build environment; the answers have the shape of the
ServusTV recording (same Red Bull Media House platform). The Red Bull TV scope and player tenant are
assumptions: the tests check that the module finds a working scope, falls back to the ServusTV player
tenant and fails with a plain message when nothing answers."""
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

import hls_guard
import live_tv
import platform_registry
import portal_title
import redbulltv
import redbulltv_enrichment
import sender_live
import servustv
import streaming
import unified_index

ROOT = Path(__file__).resolve().parents[1]
NOW = 1794556800


def card(ident, title, ctype, **extra):
    base = {'id': ident, 'title': title, 'type': 'video' if ctype not in ('show', 'subchannel') else ctype,
            'content_type': ctype, 'long_description': 'Über ' + title, 'duration': 2812160, 'playable': True,
            'media_resources': {'rbtv_display_art_portrait': {'url': 'https://resources.redbull.tv/%s/rbtv_display_art_portrait/{im}' % ident}},
            'share_url': 'https://www.redbull.com/de-de/tv/video/' + ident}
    base.update(extra)
    return base


SHOW = card('AP-1SHOWSHOW1W11', 'Frontiers', 'show')
EPISODES = [card('AP-1EPISODE%04dW1' % n, 'Folge %d' % n, 'episode', season_number=1, episode_number=n) for n in (1, 2, 3)]
FILM = card('AP-1Q6XCDTAN1W11', 'Kilimanjaro – Berg der Größe', 'film', duration=5400000)
CHANNEL = card('PN1REDBULLTV0001', 'Red Bull TV', 'video_channel')
PRODUCTS = {'discover': {'id': 'discover', 'type': 'page', 'collections': [{'id': 'aaaaaaaa-1111-2222-3333-444444444444'}]},
            'AP-1SHOWSHOW1W11': {'id': 'AP-1SHOWSHOW1W11', 'content_type': 'show',
                                 'collections': [{'id': 'bbbbbbbb-1111-2222-3333-444444444444'}]}}
COLLECTIONS = {'aaaaaaaa-1111-2222-3333-444444444444': [SHOW, FILM, CHANNEL],
               'bbbbbbbb-1111-2222-3333-444444444444': EPISODES}


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'no', {}, io.BytesIO(b''))


class FakeRedBull:
    def __init__(self, scope='/rbtv/de/int/', player=('rbtv',)):
        self.scope, self.player, self.calls = scope, player, []

    def __call__(self, url, headers, limit=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.path, q))
        assert headers['Referer'] == 'https://www.redbull.tv/'
        if parts.hostname == 'tv-api.redbull.com':
            if self.scope not in parts.path:
                raise http_error(url, 404)
            kind, ident = parts.path.split(self.scope)
            data = PRODUCTS.get(ident) if kind == '/products/v5.3' else (
                {'cards': COLLECTIONS[ident], 'meta': {'total': len(COLLECTIONS[ident])}} if ident in COLLECTIONS else None)
            if data is None:
                raise http_error(url, 404)
            return json.dumps(data).encode()
        if parts.hostname == 'api-player.redbull.com':
            if q['tenant'] not in self.player:
                raise http_error(url, 404)
            return json.dumps({'videoUrl': 'https://play.redbull.com/main/v1/%s/x.m3u8' % q['videoId'],
                               'playabilityErrors': [], 'duration': 100}).encode()
        raise AssertionError(url)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()
        sender_live._SOURCES.clear()

    def tearDown(self):
        self.tmp.cleanup()


class RedBullCatalogue(Base):
    def test_crawl_stores_in_own_database_with_own_tables(self):
        result = redbulltv.sync(self.root, opener=FakeRedBull(), now=NOW)
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['movies'], result['series'], result['episodes'], result['channels']), (1, 1, 3, 1))
        db = sqlite3.connect(str(self.root / 'redbulltv.sqlite3'))
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        db.close()
        self.assertIn('redbulltv_items', tables)
        self.assertNotIn('servustv_items', tables)
        self.assertFalse((self.root / 'servustv.sqlite3').exists())
        state = redbulltv.state(self.root)
        self.assertEqual(state['last_result'], 'complete')
        self.assertTrue(state['scope_assumed'])
        self.assertEqual(servustv.state(self.root)['movies'], 0)      # ServusTV untouched

    def test_listing_episodes_item_and_link(self):
        redbulltv.sync(self.root, opener=FakeRedBull(), now=NOW)
        films = redbulltv.listing(self.root, 'movies')
        self.assertEqual([r['title'] for r in films['items']], ['Kilimanjaro – Berg der Größe'])
        self.assertEqual(films['items'][0]['web_url'], 'https://www.redbull.com/de-de/tv/video/AP-1Q6XCDTAN1W11')
        series = redbulltv.listing(self.root, 'series')['items']
        self.assertEqual((series[0]['title'], series[0]['episodes']), ('Frontiers', 3))
        eps = redbulltv.episodes(self.root, series[0]['id'])
        self.assertEqual([e['episode'] for e in eps['items']], [1, 2, 3])
        detail = redbulltv.item(self.root, 'v.AP-1Q6XCDTAN1W11')
        self.assertEqual(detail['item']['kind'], 'movie')
        self.assertEqual([c['title'] for c in redbulltv.channels(self.root)], ['Red Bull TV'])

    def test_second_scope_is_found_and_remembered(self):
        fake = FakeRedBull(scope='/rbtv/de/de/')
        self.assertTrue(redbulltv.sync(self.root, opener=fake, now=NOW)['ok'])
        db = redbulltv._connect(self.root)
        try:
            self.assertEqual(redbulltv._get(db, 'scope'), '/rbtv/de/de/')
        finally:
            db.close()
        fake.calls.clear()
        redbulltv.sync(self.root, opener=fake, now=NOW + 10)
        self.assertTrue(fake.calls[0][0].startswith('/products/v5.3/rbtv/de/de/'))   # remembered scope first

    def test_no_scope_answers_plain_message(self):
        with mock.patch('servustv._notify') as note:
            result = redbulltv.sync(self.root, opener=FakeRedBull(scope='/nowhere/'), now=NOW)
        self.assertFalse(result['ok'])
        self.assertIn('Red Bull TV antwortet mit HTTP 404', result['error'])
        self.assertIn('redbulltv_scope_missing', [c.args[0] for c in note.call_args_list])
        self.assertEqual(redbulltv.state(self.root)['last_result'], 'failed')

    def test_playback_with_servustv_tenant_as_fallback(self):
        fake = FakeRedBull(player=('stv',))
        redbulltv.sync(self.root, opener=fake, now=NOW)
        src = redbulltv.play_source(self.root, 'v.AP-1Q6XCDTAN1W11', opener=fake, check=lambda url: None, now=NOW)
        self.assertEqual((src['provider'], src['hls'], src['live']), ('redbulltv', True, False))
        self.assertEqual(src['quality'], 'Red Bull TV (kostenlos)')
        tenants = [c[1]['tenant'] for c in fake.calls if c[0] == '/tv']
        self.assertEqual(tenants, ['rbtv', 'stv'])

    def test_drm_is_refused_and_remembered(self):
        fake = FakeRedBull()
        redbulltv.sync(self.root, opener=fake, now=NOW)

        def protected(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        with self.assertRaises(hls_guard.DrmProtected):
            redbulltv.play_source(self.root, 'v.AP-1Q6XCDTAN1W11', opener=fake, check=protected, now=NOW)
        self.assertEqual(redbulltv.item(self.root, 'v.AP-1Q6XCDTAN1W11')['item']['drm'], 1)

    def test_running_flags_are_separate(self):
        with mock.patch('threading.Thread'):
            self.assertTrue(redbulltv.start_sync(self.root))
            self.assertTrue(redbulltv._ACTIVE)
            self.assertFalse(servustv._ACTIVE)
            self.assertFalse(redbulltv.start_sync(self.root))
        servustv._mark_running(redbulltv.T, False)
        self.assertFalse(redbulltv._ACTIVE)

    def test_reference_checks_use_own_tables(self):
        redbulltv.sync(self.root, opener=FakeRedBull(), now=NOW)
        self.assertEqual(redbulltv_enrichment.all_cached(self.root), {})
        self.assertIsInstance(redbulltv_enrichment.metrics(self.root), dict)

    def test_wiring(self):
        self.assertIn('redbulltv', platform_registry.BY_KEY)
        self.assertIn('redbulltv', unified_index.SOURCES)
        self.assertEqual(portal_title.PROVIDERS['redbulltv'], 'Red Bull TV')
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        for needle in ("redbulltv=q.get('redbulltv',[''])[0]", "sender=q.get('sender',[''])[0]", "'/redbulltv.js'",
                       "'source':'redbulltv'", "'redbulltv':lambda:redbulltv.state(ROOT)"):
            self.assertIn(needle, server)
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        for name in ('redbulltv.py', 'redbulltv_enrichment.py', 'sender_live.py'):
            self.assertIn("'%s'" % name, build)
            self.assertIn('./mediathekatlas/' + name, (ROOT / 'qpkg-files.txt').read_text(encoding='utf-8'))
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        for needle in ('<section id="redbulltv"', 'data-platform="redbulltv"', 'data-catalog-source="redbulltv"',
                       '<script src="/redbulltv.js"></script>', 'id="redbulltv-sync"'):
            self.assertIn(needle, html)
        self.assertIn('window.playRedBullTV', (ROOT / 'web' / 'player.js').read_text(encoding='utf-8'))


class NewsStations(Base):
    def test_welt_plays_official_stream_after_check(self):
        seen = []
        src = sender_live.play_source(self.root, 'welt', check=seen.append, now=NOW)
        self.assertEqual((src['provider'], src['live'], src['hls'], src['duration']), ('sender', True, True, 0))
        self.assertTrue(src['url'].startswith('https://w-live2weltcms.akamaized.net/'))
        self.assertEqual(seen, [src['url']])
        sender_live.play_source(self.root, 'welt', check=seen.append, now=NOW + 10)
        self.assertEqual(len(seen), 1)                    # cached for two minutes

    def test_ntv_is_link_only(self):
        with self.assertRaises(ValueError) as ctx:
            sender_live.play_source(self.root, 'ntv')
        self.assertIn('n-tv.de', str(ctx.exception))

    def test_failures_are_plain_and_logged_without_address(self):
        def down(url):
            raise http_error(url, 403)
        with mock.patch('sender_live._notify') as note:
            with self.assertRaises(ValueError) as ctx:
                sender_live.play_source(self.root, 'welt', check=down, now=NOW)
        self.assertIn('HTTP 403', str(ctx.exception))
        self.assertIn('welt.de', str(ctx.exception))
        self.assertEqual(note.call_args.kwargs, {'station': 'welt', 'error_type': 'http', 'http_status': 403})

        def protected(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        with self.assertRaises(hls_guard.DrmProtected):
            sender_live.play_source(self.root, 'welt', check=protected, now=NOW + 1000)
        with self.assertRaises(ValueError):
            sender_live.play_source(self.root, '../x')

    def test_live_tv_merges_welt_from_samsung_and_lists_ntv_as_link(self):
        welt = live_tv._channel('samsung', 'DE2200005GX', 'Welt', {'samsung': 'DE2200005GX'})
        self.assertEqual((welt['station'], welt['group']), ('WELT', live_tv.PRIVATE_NEWS))
        rows = {r['id']: r for r in live_tv.sender_channels(self.root)}
        self.assertEqual(rows['welt']['play'], {'sender': 'welt'})
        self.assertIsNone(rows['ntv']['play'])
        self.assertEqual(rows['ntv']['link'], 'https://www.n-tv.de/mediathek/livestream/')
        self.assertEqual(live_tv.station_key('n-tv'), 'ntv')

    def test_streaming_resolves_sender(self):
        with mock.patch('hls_guard.check', lambda url: None):
            src = streaming.resolve(None, root=self.root, sender='welt')
        self.assertEqual(src['provider'], 'sender')
        plan = streaming.plan(src)
        self.assertTrue(plan['live'])


if __name__ == '__main__':
    unittest.main()
