"""0.5.65: Joyn (films, series, live channels; free and Joyn+). Answers have the shape recorded in
Björn's HAR (12.11.2026, api.joyn.de/graphql: Navigation, PageOverviewGenre); values are synthetic.
Playback was not recorded: every title and channel links to joyn.de, nothing plays or is stored."""
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hls_guard, live_tv, portal_title, streaming  # noqa: E402
import joyn, joyn_enrichment  # noqa: E402

IMG = 'https://img.joyn.de/ingest/t_001/i_%s.jpg/profile:nextgen-web-heroportrait-243x365'


def card(typename, ident, title, path, licences=('AVOD',), genres=('Horror',), markings=(), seasons=None):
    node = {'id': ident, 'title': title, '__typename': typename, 'description': title + ' Inhalt',
            'primaryImage': {'id': 'p', 'url': IMG % ident}, 'heroPortrait': {'id': 'h', 'url': IMG % (ident + 'h')},
            'genres': [{'name': g, 'type': g.upper(), '__typename': 'Genre'} for g in genres],
            'brands': [{'id': '1', 'title': 'ProSieben', 'logo': {'type': 'BRAND_LOGO', 'url': IMG % 'logo'}}],
            'path': path, 'licenseTypes': list(licences), 'markings': list(markings), 'languages': [],
            'ageRating': {'minAge': 12}}
    if seasons is not None:
        node['numberOfSeasons'] = seasons
    return node


def brand(title, live_id, path='/channels/x', groups=(), markings=(), quality='HD', radio=False):
    return {'id': '1', 'title': title, '__typename': 'Brand', 'path': path, 'isRadio': radio,
            'logo': {'type': 'BRAND_LOGO', 'url': IMG % live_id},
            'livestream': {'id': live_id, 'title': title, 'quality': quality, 'liveStreamGroups': list(groups),
                           'markings': list(markings)} if live_id else None, 'audioStreams': []}


def lane(*paths):
    return {'blocks': [{'headline': 'Genres', 'assets': [{'__typename': 'GenreItem', 'path': p, 'title': p} for p in paths]}]}


NAVIGATION = {'data': {'navigation': [], 'mediatheken': {'blocks': []},
                       'liveTv': [brand('Das Erste', 'daserste-de-hd', '/channels/das-erste', ['PUBLIC_VALUE']),
                                  brand('ProSieben', 'prosieben-de', '/mediatheken/prosieben', quality='SD'),
                                  brand('ProSieben FUN', 'prosiebenfun-de-hd', None, markings=['PLUS']),
                                  brand('Radio', 'radio-x', radio=True),
                                  brand('DYN Sport Mix', None, '/channels/dyn')],
                       'movieGenre': lane('/filme/genre/horror'),
                       'seriesGenre': lane('/serien/genre/comedy', '/bad/path')}}
GENRES_PATHS = {'data': {'movies': lane('/filme/genre/horror'), 'series': {'blocks': []},
                         'plusMovies': lane('/plus/filme/genre/thriller'), 'plusSeries': None}}


def page(path, assets):
    return {'data': {'page': {'id': 'o1', 'path': path, 'title': 'x', 'blocks': [{'assets': assets}]}}}


HORROR_1 = [card('Movie', 'b_cloverfield%02d' % i, 'Film %02d' % i, '/filme/film-%02d' % i) for i in range(32)]
HORROR_2 = [card('Movie', 'b_last', 'Letzter Film', '/filme/letzter'),
            card('Compilation', 'c_x', 'Sammlung', '/compilation/x'),
            card('Movie', 'b_rent', 'Unbekannte Lizenz', '/filme/rent', licences=('OTHER',))]
COMEDY = [card('Series', 'a_stromberg', 'Stromberg', '/serien/stromberg', genres=('Comedy',), seasons=5),
          card('Movie', 'b_cloverfield00', 'Film 00', '/filme/film-00', genres=('Komödie',))]
THRILLER = [card('Movie', 'b_plus', 'Plus-Film', '/filme/plus-film', licences=('SVOD',), genres=('Thriller',)),
            card('Movie', 'b_cloverfield01', 'Film 01', '/filme/film-01', licences=('SVOD',))]


class Api:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, operation, variables=None):
        self.calls.append((operation, variables))
        if operation in self.fail:
            return self.fail[operation]
        if operation == 'Navigation':
            return NAVIGATION
        if operation == 'GenresPaths':
            return GENRES_PATHS
        path, offset = variables['path'], variables['offset']
        assert variables['first'] == 32
        return page(path, {('/filme/genre/horror', 0): HORROR_1, ('/filme/genre/horror', 32): HORROR_2,
                           ('/serien/genre/comedy', 0): COMEDY,
                           ('/plus/filme/genre/thriller', 0): THRILLER}.get((path, offset), []))


class JoynTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, api=None):
        return joyn.sync(self.root, request=api or Api(), now=1794500000.0, gap=0)

    def test_query_url_is_built_like_the_website(self):
        url = joyn.query_url('PageOverviewGenre', {'first': 32, 'path': '/filme/genre/horror', 'offset': 0})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertTrue(url.startswith('https://api.joyn.de/graphql?operationName=PageOverviewGenre'))
        self.assertEqual(json.loads(q['variables'][0]), {'first': 32, 'path': '/filme/genre/horror', 'offset': 0})
        self.assertEqual(json.loads(q['extensions'][0])['persistedQuery']['sha256Hash'], joyn.HASHES['PageOverviewGenre'])
        self.assertEqual(q['enable_user_location'], ['true'])
        self.assertNotIn('variables', urllib.parse.parse_qs(urllib.parse.urlsplit(joyn.query_url('Navigation')).query))
        h = joyn.headers()
        self.assertEqual((h['Joyn-Platform'], h['Joyn-Country'], h['x-api-key']), ('web', 'DE', joyn.API_KEY))
        with self.assertRaises(ValueError):
            joyn.query_url('Unbekannt')

    def test_sync_free_and_plus_catalogue_and_channels(self):
        api = Api()
        result = self.load(api)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['partial'])
        # 33 free films (2 pages, compilation and unknown licence dropped) + 1 Joyn+ film; 1 series
        self.assertEqual((result['movies'], result['series'], result['channels']), (34, 1, 3))
        self.assertEqual(result['plus'], 2)            # Plus film + Plus channel
        paths = [v['path'] for op, v in api.calls if op == 'PageOverviewGenre']
        self.assertNotIn('/bad/path', paths)
        self.assertEqual(paths.count('/filme/genre/horror'), 2)    # navigation and GenresPaths deduplicated
        movies = {r['id']: r for r in joyn.listing(self.root, 'movies', limit='all')['items']}
        free = movies['m.b_cloverfield01']
        self.assertEqual(free['offer'], 'free')       # free listing wins over the Joyn+ genre page
        self.assertIn('Joyn (kostenlos)', free['categories'])
        plus = movies['m.b_plus']
        self.assertEqual((plus['offer'], plus['category']), ('plus', 'Joyn+'))
        self.assertIn('Joyn+', plus['categories'])
        self.assertEqual(plus['web_url'], 'https://www.joyn.de/filme/plus-film')
        self.assertEqual(plus['rating'], 'FSK 12')
        self.assertEqual((plus['playable'], plus['drm']), (0, 1))
        self.assertTrue(plus['poster'].startswith('https://img.joyn.de/'))
        self.assertIn('Komödie', movies['m.b_cloverfield00']['genre'])   # genres of all pages collected
        only_plus = joyn.listing(self.root, 'movies', genre='Joyn+', limit='all')
        self.assertEqual([r['id'] for r in only_plus['items']], ['m.b_plus'])
        series = joyn.listing(self.root, 'series')['items'][0]
        self.assertEqual((series['id'], series['seasons'], series['brand']), ('s.a_stromberg', 5, 'ProSieben'))
        live = joyn.listing(self.root, 'live')['items']
        self.assertEqual([c['id'] for c in live], ['c.daserste-de-hd', 'c.prosieben-de', 'c.prosiebenfun-de-hd'])
        self.assertEqual(live[0]['web_url'], 'https://www.joyn.de/channels/das-erste')
        self.assertEqual(live[1]['web_url'], 'https://www.joyn.de/play/live-tv')
        self.assertEqual(live[2]['offer'], 'plus')
        st = joyn.state(self.root)
        self.assertEqual((st['last_result'], st['movies'], st['playable']), ('complete', 34, 0))

    def test_unknown_persisted_query_is_explained(self):
        api = Api({'Navigation': {'errors': [{'message': 'PersistedQueryNotFound'}]}})
        result = self.load(api)
        self.assertFalse(result['ok'])
        self.assertIn('PersistedQueryNotFound', result['error'])
        self.assertEqual(joyn.state(self.root)['last_result'], 'failed')

    def test_failed_genre_page_keeps_the_rest(self):
        class Broken(Api):
            def __call__(self, operation, variables=None):
                if variables and variables.get('path') == '/serien/genre/comedy':
                    raise OSError('timeout')
                return super().__call__(operation, variables)
        result = self.load(Broken())
        self.assertTrue(result['ok'])
        self.assertTrue(result['partial'])
        self.assertEqual(result['series'], 0)
        self.assertIn('teilweise', joyn.state(self.root)['last_error'])

    def test_rotation_hides_titles_of_older_runs(self):
        self.load()
        later = Api()
        later_horror = page('/filme/genre/horror', HORROR_2[:1])
        later.fail = {}
        orig = later.__call__

        def call(operation, variables=None):
            if variables and variables.get('path') == '/filme/genre/horror':
                return later_horror
            return orig(operation, variables)
        joyn.sync(self.root, request=call, now=1794600000.0, gap=0)
        ids = {r['id'] for r in joyn.listing(self.root, 'movies', limit='all')['items']}
        self.assertIn('m.b_last', ids)
        self.assertNotIn('m.b_cloverfield05', ids)

    def test_playback_is_refused_and_details_link_to_joyn(self):
        self.load()
        with self.assertRaises(hls_guard.DrmProtected):
            joyn.play_source(self.root, 'm.b_plus')
        with self.assertRaises(hls_guard.DrmProtected):
            streaming.resolve(None, joyn='c.prosieben-de', root=self.root)
        with self.assertRaises(ValueError):
            joyn.play_source(self.root, '../etc')
        m = portal_title.model(self.root, 'joyn', 'm.b_plus')
        self.assertFalse(m['playable'])
        self.assertFalse(m['offline']['allowed'])
        self.assertEqual(m['web_url'], 'https://www.joyn.de/filme/plus-film')
        self.assertIn(['Angebot', 'Joyn+ (mit Joyn-Konto)'], m['provider_facts'])
        channel = portal_title.model(self.root, 'joyn', 'c.daserste-de-hd')
        self.assertFalse(channel['playable'])
        series = portal_title.model(self.root, 'joyn', 's.a_stromberg')
        self.assertEqual(series['episodes'], [])
        self.assertTrue(any('bei Joyn ansehen' in n for n in series['notes']))

    def test_live_tv_tab_merges_joyn_by_station_as_link(self):
        self.load()
        found = live_tv.joyn_channels(self.root)
        first = found[0]
        self.assertEqual((first['key'], first['play'], first['link']),
                         ('daserste', None, 'https://www.joyn.de/channels/das-erste'))
        self.assertIn('Joyn+', next(c for c in found if c['id'] == 'c.prosiebenfun-de-hd')['quality'])
        self.assertIn(('joyn', 'Joyn'), live_tv.PROVIDERS)

    def test_image_and_link_guards(self):
        self.assertEqual(joyn.image('https://evil.example/x.jpg'), '')
        self.assertEqual(joyn.image('http://img.joyn.de/x.jpg'), '')
        self.assertEqual(joyn.web_url('/filme/../../x'), '')
        self.assertEqual(joyn.web_url('javascript:alert(1)'), '')
        self.assertIsNone(joyn.item_from(card('Movie', 'b_x', 'X', '/filme/x', licences=())))
        self.assertEqual(joyn.item_from(card('Movie', 'b_x', 'X', '/filme/x', licences=()), plus_page=True)['offer'], 'plus')

    def test_enrichment_spec_uses_joyn_tables(self):
        self.load()
        self.assertEqual(joyn_enrichment.SPEC.items, 'joyn_items')
        pending = joyn_enrichment.pending(self.root, limit=5)
        self.assertTrue(pending)
        self.assertTrue(all(not str(p).startswith('c.') for p in pending))


if __name__ == '__main__':
    unittest.main()
