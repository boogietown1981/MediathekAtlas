"""0.5.101: ServusTV On – free video library and live channels, plain HLS in the own player.

The player answers have the shape documented by yt-dlp's ServusIE (videoUrl, title, label, season,
chapter, playabilityErrors). The WordPress media assets follow the page data yt-dlp reads
(title.rendered, stv_date.raw, stv_duration, category_names, stv_short_description); their exact
list route is not known, so the fake answers the REST index with one. ServusTV is blocked here."""
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


def asset(n, series='', season=None, chapter=None, cat='Natur'):
    node = {'id': 1000 + n, 'title': {'rendered': 'Video &amp; %d' % n}, 'aa_id': 'AA-%013d' % n,
            'link': 'https://www.servustv.com/natur/v/aa-%013d/' % n, 'stv_date': {'raw': NOW - n * 3600},
            'stv_duration': 2823.4, 'category_names': [cat], 'stv_short_description': '<p>Kurz &uuml;ber %d</p>' % n,
            'stv_image': 'https://backend.servustv.com/wp-content/uploads/%d.jpg' % n}
    if series:
        node.update(stv_format=series, stv_season='Season %d' % season if season else None,
                    stv_episode='Episode %d - Folge %d' % (chapter, n) if chapter else None)
    return node


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'no', {}, io.BytesIO(b''))


class FakeServus:
    def __init__(self, rest=True, total=130, sitemap_titles=False):
        self.calls, self.rest, self.total, self.sitemap_titles = [], rest, total, sitemap_titles
        self.player = {}

    def __call__(self, url, headers, limit=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.hostname, parts.path, q))
        if parts.hostname == 'backend.servustv.com':
            if not self.rest:
                raise http_error(url, 403)
            if parts.path == '/wp-json/':
                return self.json({'routes': {'/wp/v2/posts': {}, '/rbmh/v2/media_asset': {},
                                             '/rbmh/v2/media_asset/aa_id/(?P<id>[\\w-]+)': {}}})
            if parts.path == '/wp-json/rbmh/v2/media_asset':
                page, size = int(q['page']), int(q['per_page'])
                rows = []
                for n in range(1, self.total + 1):
                    if n <= 4:
                        rows.append(asset(n, 'Bergwelten', 11, n))
                    elif n == 5:
                        rows.append(asset(n, 'Servus Krimi', cat='Krimi'))
                    else:
                        rows.append(asset(n))
                rows = rows[(page - 1) * size:page * size]
                if not rows:
                    raise http_error(url, 400)
                return self.json(rows)
            raise http_error(url, 404)
        if parts.hostname == 'www.servustv.com':
            if parts.path == '/robots.txt':
                return b'User-agent: *\nSitemap: https://www.servustv.com/sitemap_index.xml\n', url
            if parts.path == '/sitemap_index.xml':
                return (b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        b'<sitemap><loc>https://www.servustv.com/post-sitemap.xml</loc></sitemap>'
                        b'<sitemap><loc>https://www.servustv.com/video-sitemap1.xml</loc></sitemap></sitemapindex>'), url
            if parts.path == '/video-sitemap1.xml':
                video = (b'<video:video><video:title>Sitemap-Titel</video:title><video:duration>600</video:duration>'
                         b'<video:thumbnail_loc>https://backend.servustv.com/x.jpg</video:thumbnail_loc></video:video>') \
                    if self.sitemap_titles else b''
                return (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                        b'xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">'
                        b'<url><loc>https://www.servustv.com/natur/v/aa-28bycqnh92111/</loc>' + video + b'</url>'
                        b'<url><loc>https://www.servustv.com/wissen/v/aa-1xg5xwmgw2112/</loc></url>'
                        b'<url><loc>https://www.servustv.com/aktuelles/b/nachrichten/</loc></url></urlset>'), url
            if parts.path == '/post-sitemap.xml':
                return (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        b'<url><loc>https://www.servustv.com/a/b/</loc></url></urlset>'), url
            raise http_error(url, 404)
        if parts.hostname == 'api-player.redbull.com':
            vid = q['videoId']
            answer = self.player.get(vid) or {'videoUrl': 'https://dms.redbull.tv/%s/playlist.m3u8' % vid,
                                              'title': 'Vie Ferrate - Klettersteige', 'label': 'Bergwelten',
                                              'season': 'Season 11', 'chapter': 'Episode 8 - Vie Ferrate',
                                              'poster': 'https://resources.redbull.tv/p.jpg', 'duration': 2823}
            return self.json(answer)
        raise AssertionError('unexpected host ' + url)

    @staticmethod
    def json(obj):
        return json.dumps(obj).encode(), 'https://x'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()

    def tearDown(self):
        self.tmp.cleanup()


class CatalogueTests(Base):
    def test_rest_catalogue_with_formats_and_paging(self):
        fake = FakeServus()
        result = servustv.sync(self.root, opener=fake, now=NOW)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['source'], 'rest')
        self.assertFalse(result['partial'])
        self.assertEqual((result['movies'], result['series'], result['episodes'], result['channels']), (126, 1, 4, 2))
        pages = [c[2]['page'] for c in fake.calls if c[1] == '/wp-json/rbmh/v2/media_asset']
        self.assertEqual(pages, ['1', '2'])          # 130 entries: second page shorter, no third request
        films = servustv.listing(self.root, 'movies', limit='all')
        first = next(r for r in films['items'] if r['id'] == 'v.AA-0000000000010')
        self.assertEqual(first['title'], 'Video & 10')
        self.assertEqual(first['summary'], 'Kurz über 10')
        self.assertEqual(first['duration'], 2823)
        self.assertIsNone(first['year'])                # publication date is not the production year
        self.assertEqual(first['web_url'], 'https://www.servustv.com/natur/v/aa-0000000000010/')
        shows = servustv.listing(self.root, 'series')
        self.assertEqual([(s['title'], s['episodes']) for s in shows['items']], [('Bergwelten', 4)])
        # A film format without season/episode (Servus Krimi) stays a film.
        self.assertIn('v.AA-0000000000005', [r['id'] for r in films['items']])
        eps = servustv.episodes(self.root, 's.bergwelten')
        self.assertEqual([(e['season'], e['episode'], e['title']) for e in eps['items']][:2], [(11, 1, 'Folge 1'), (11, 2, 'Folge 2')])
        self.assertEqual(servustv.state(self.root)['source'], 'rest')

    def test_sitemap_fallback_fills_titles_from_player(self):
        fake = FakeServus(rest=False)
        result = servustv.sync(self.root, opener=fake, now=NOW)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['source'], 'sitemap')
        players = [c for c in fake.calls if c[0] == 'api-player.redbull.com']
        self.assertEqual(len(players), 2)               # one per video without a title
        eps = servustv.episodes(self.root, 's.bergwelten')['items']
        self.assertEqual({e['id'] for e in eps}, {'v.AA-28BYCQNH92111', 'v.AA-1XG5XWMGW2112'})
        self.assertEqual((eps[0]['season'], eps[0]['episode'], eps[0]['title']), (11, 8, 'Vie Ferrate'))
        self.assertNotIn('/aktuelles/b/', json.dumps(servustv.listing(self.root, 'movies', limit='all')))

    def test_sitemap_titles_need_no_player(self):
        fake = FakeServus(rest=False, sitemap_titles=True)
        servustv.sync(self.root, opener=fake, now=NOW)
        films = servustv.listing(self.root, 'movies', limit='all')['items']
        self.assertIn('Sitemap-Titel', [f['title'] for f in films])
        self.assertEqual(next(f for f in films if f['title'] == 'Sitemap-Titel')['genre'], 'Natur')

    def test_failure_keeps_catalogue(self):
        servustv.sync(self.root, opener=FakeServus(), now=NOW)

        def down(url, headers, limit=None):
            raise urllib.error.URLError('offline')
        result = servustv.sync(self.root, opener=down, now=NOW + 10)
        self.assertFalse(result['ok'])
        self.assertEqual(servustv.listing(self.root, 'movies')['total'], 126)
        self.assertEqual(servustv.state(self.root)['last_result'], 'failed')

    def test_sitemap_rejects_entities(self):
        with self.assertRaises(ValueError):
            servustv.parse_sitemap(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset/>')

    def test_ids_and_images(self):
        self.assertEqual(servustv.video_id('https://www.servustv.com/natur/v/aa-28bycqnh92111/'), 'AA-28BYCQNH92111')
        self.assertEqual(servustv.video_id('aansszcx3yi9jmlmhdc1'), 'AANSSZCX3YI9JMLMHDC1')
        self.assertEqual(servustv.image('http://x/y.jpg'), '')
        self.assertEqual(servustv.image({'url': 'https://a.b/c.jpg'}), 'https://a.b/c.jpg')
        self.assertFalse(servustv.VALID_ID.fullmatch('v.AA-1;drop'))


class PlaybackTests(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeServus()
        servustv.sync(self.root, opener=self.fake, now=NOW)
        self.checked = []

    def check(self, url):
        self.checked.append(url)
        return {'variants': 1, 'protected': False}

    def test_episode_plays_as_checked_hls(self):
        src = servustv.play_source(self.root, 'v.AA-0000000000002', opener=self.fake, check=self.check, now=NOW)
        self.assertEqual(src['url'], 'https://dms.redbull.tv/AA-0000000000002/playlist.m3u8')
        self.assertTrue(src['hls'])
        self.assertEqual(src['title'], 'Bergwelten · S11E02 · Folge 2')
        self.assertEqual(self.checked, [src['url']])
        servustv.play_source(self.root, 'v.AA-0000000000002', opener=self.fake, check=self.check, now=NOW + 5)
        self.assertEqual(len(self.checked), 1)          # remembered for two minutes

    def test_youth_protection_is_named(self):
        self.fake.player['AA-0000000000010'] = {'playabilityErrors': ['FSK_BLOCKED'],
                                                'playabilityErrorDetails': {'FSK_BLOCKED': {'minEveningHour': 22, 'maxMorningHour': 6, 'minAge': 16}}}
        with self.assertRaises(ValueError) as ctx:
            servustv.play_source(self.root, 'v.AA-0000000000010', opener=self.fake, check=self.check, now=NOW)
        self.assertEqual(str(ctx.exception), 'Jugendschutz: ServusTV zeigt dieses Video nur von 22:00 bis 06:00 Uhr (ab 16 Jahren).')
        self.fake.player['AA-0000000000011'] = {'playabilityErrors': ['GEO_BLOCKED']}
        with self.assertRaisesRegex(ValueError, 'Geosperre'):
            servustv.play_source(self.root, 'v.AA-0000000000011', opener=self.fake, check=self.check, now=NOW)

    def test_protected_stream_is_refused_and_remembered(self):
        def drm(url):
            raise hls_guard.DrmProtected(hls_guard.DRM_MESSAGE)
        with self.assertRaises(hls_guard.DrmProtected):
            servustv.play_source(self.root, 'v.AA-0000000000020', opener=self.fake, check=drm, now=NOW)
        self.assertEqual(servustv.item(self.root, 'v.AA-0000000000020')['item']['playable'], 0)
        servustv.sync(self.root, opener=self.fake, now=NOW + 100)       # a new catalogue run keeps it
        self.assertEqual(servustv.item(self.root, 'v.AA-0000000000020')['item']['drm'], 1)

    def test_live_tries_candidates(self):
        def first_fails(url):
            if url == servustv.LIVE[0][3][0]:
                raise ValueError('Der Anbieter lieferte keine HLS-Wiedergabeliste')
            return {}
        src = servustv.play_source(self.root, 'c.de', check=first_fails, now=NOW)
        self.assertEqual(src['url'], servustv.LIVE[0][3][1])
        self.assertTrue(src['live'])

    def test_streaming_and_live_tv(self):
        original = servustv.play_source
        servustv.play_source = lambda root, item_id: {'kind': 'url', 'url': 'https://a/b.m3u8', 'provider': 'servustv', 'item': item_id}
        try:
            self.assertEqual(streaming.resolve(None, servustv='c.at', root=self.root)['item'], 'c.at')
        finally:
            servustv.play_source = original
        rows = live_tv.servustv_channels(self.root)
        self.assertEqual([(r['title'], r['play']) for r in rows],
                         [('ServusTV Deutschland', {'servustv': 'c.de'}), ('ServusTV Österreich', {'servustv': 'c.at'})])

    def test_title_page(self):
        m = portal_title.model(self.root, 'servustv', 's.bergwelten')
        self.assertEqual(len(m['episodes']), 4)
        m = portal_title.model(self.root, 'servustv', 'v.AA-0000000000010')
        self.assertFalse(m['offline']['allowed'])
        self.assertIn(['Angebot', 'ServusTV On, kostenlos (ohne Konto)'], m['provider_facts'])


class WiringTests(unittest.TestCase):
    def test_wiring(self):
        here = Path(__file__).resolve().parent.parent
        server = (here / 'server.py').read_text(encoding='utf-8')
        for needle in ("'plex','servustv')}", "servustv=q.get('servustv',[''])[0]", "'servustv':servustv.state(ROOT)",
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
