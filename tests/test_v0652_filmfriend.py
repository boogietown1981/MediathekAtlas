"""0.6.52: filmfriend (film library of public libraries) as a catalogue with links.

Answers in the shape saved on Björn's Mac on 20.11.2026 (filmfriend_samples.zip): tenant, navigation with
``primary[].target`` pages, pages whose ``FilterableThumbnails`` part names the full search, ``search`` with
take/skip and ``totalCount`` null, details with ageRatings/imdbUrl/artworkUris. Ids and titles are made up here;
if the saved answers are in the project folder, they are read as well. Watching needs a library card login:
never a player here, every title opens on filmfriend.de."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path

import filmfriend
import platform_registry
import portal_title
import unified_index

SAMPLES = Path('/mnt/project-files/filmfriend_samples.zip')
TENANT = 'fba2f8b5-6a3a-4da3-b555-21613a88d3ef'
LANDING = 'e25869cd-2557-4bba-ba3b-672378285c2d'
P_ALL, P_KIDS, P_COLL = ('4d1da4aa-f4bd-479f-ab60-b3e2878704%02d' % n for n in (36, 37, 38))
CAT_ALL, CAT_KIDS = 'd36cbed2-7569-4b94-9080-03ce79c2ecee', 'b6278374-8536-48ff-9bd5-636ea3d3d975'
NOW = 1795132800


def uid(n):
    return 'aaaaaaaa-0000-4000-8000-%012d' % n


def art(kind, url):
    return {'kind': kind, 'resolution1x': url, 'resolution720': url}


def movie(n, title, runtime=5400, **extra):
    node = {'kind': 'Movie', 'id': uid(n), 'uriId': title.lower().replace(' ', '-'), 'title': title, 'originalTitle': None,
            'synopsis': 'Über ' + title, 'releaseDate': None, 'ageRatings': None, 'imdbUrl': None, 'tmdbUrl': None,
            'runtime': runtime, 'genres': [{'id': uid(900), 'name': 'Drama'}],
            'categories': [{'id': CAT_ALL, 'name': 'Filme & Serien'}],
            'productionCountries': [{'id': uid(901), 'name': 'Deutschland'}],
            'artworkUris': [art('Background', 'https://filmwerte-vod.b-cdn.net/videos/%d/bg.jpg?width=1280&height=720' % n)]}
    node.update(extra)
    return node


def series(n, title, **extra):
    node = {'id': uid(n), 'uriId': title.lower().replace(' ', '-'), 'title': title, 'originalTitle': None,
            'synopsis': 'Serie ' + title, 'imdbUrl': None, 'tmdbUrl': None, 'genres': [{'name': 'Krimi'}],
            'categories': [{'name': 'Filme & Serien'}], 'artworkUris': []}
    node.update(extra)
    return node


ALL = [{'kind': 'Movie', 'movie': movie(1, 'Abschied')}, {'kind': 'Series', 'series': series(2, 'Allein gegen die Zeit')}]
ALL += [{'kind': 'Movie', 'movie': movie(10 + i, 'Film %02d' % i)} for i in range(23)]          # first page full (24)
ALL += [{'kind': 'Movie', 'movie': movie(50, 'Zug')}]                                            # second page: 1
KIDS = [{'kind': 'Movie', 'movie': movie(60, 'Emil', runtime=204)}, {'kind': 'Movie', 'movie': movie(1, 'Abschied')}]
DETAILS = {
    ('movies', uid(1)): movie(1, 'Abschied', originalTitle="L'Adieu", releaseDate='2023-11-01T00:00:00Z',
                              ageRatings=[{'id': uid(902), 'name': 'FSK 12', 'minimumAge': 12, 'contentWarnings': []}],
                              imdbUrl='https://www.imdb.com/title/tt18224752', tmdbUrl='https://www.themoviedb.org/movie/792614',
                              artworkUris=[art('Thumbnail', 'https://filmwerte-vod.b-cdn.net/videos/1/thumb.jpg?width=640&height=360'),
                                           {'kind': 'CoverPortrait', 'thumbnail': 'https://filmwerte-vod.b-cdn.net/videos/1/cover.jpg?width=224&height=320',
                                            'resolution1x': 'https://filmwerte-vod.b-cdn.net/videos/1/cover.jpg?width=448&height=640'}]),
    ('series', uid(2)): series(2, 'Allein gegen die Zeit', originalTitle='Allein gegen die Zeit',
                               imdbUrl='https://www.imdb.com/title/tt1461962', tmdbUrl='https://www.themoviedb.org/tv/39902'),
    ('movies', uid(60)): movie(60, 'Emil', runtime=204, ageRatings=[{'name': 'FSK 0', 'minimumAge': 0}], releaseDate='2018-01-01T00:00:00+00:00'),
}
PAGES = {
    LANDING: {'id': LANDING, 'parts': [{'kind': 'Heading', 'heading': 'Willkommen'}]},
    P_ALL: {'id': P_ALL, 'parts': [
        {'kinds': ['Movie', 'Series', 'Collection'], 'categoryIds': [], 'collectionId': uid(990), 'displayMode': 'ScrollableHorizontalThumbnails'},
        {'kinds': ['Movie', 'Series'], 'categoryIds': [CAT_ALL], 'genreIds': [], 'collectionId': None,
         'displayMode': 'FilterableThumbnails', 'orderBy': 'Title', 'title': 'Alle Filme und Serien'}]},
    P_KIDS: {'id': P_KIDS, 'parts': [{'kinds': ['Movie', 'Series'], 'categoryIds': [CAT_KIDS], 'genreIds': [],
                                      'collectionId': None, 'displayMode': 'FilterableThumbnails'}]},
    P_COLL: {'id': P_COLL, 'parts': [{'kinds': ['Collection'], 'categoryIds': [], 'displayMode': 'FilterableThumbnails'}]},
}


class FakeFilmfriend:
    def __init__(self):
        self.calls, self.down = [], False

    def __call__(self, url, headers):
        if self.down:
            raise urllib.error.URLError('offline')
        parts = urllib.parse.urlsplit(url)
        assert parts.hostname == 'api.tenant-group.frontend.vod.filmwerte.de'
        assert headers['Origin'] == 'https://www.filmfriend.de' and headers['User-Agent']
        assert headers['Accept-Language'].startswith('de')
        path = parts.path[len('/v12/'):]
        q = urllib.parse.parse_qs(parts.query)
        self.calls.append((path, q))
        if path == 'www.filmfriend.de':
            return json.dumps({'id': TENANT, 'displayName': 'filmfriend', 'landingPageId': LANDING}).encode()
        if path == TENANT + '/navigation':
            return json.dumps({'primary': [
                {'title': 'Filme & Serien', 'target': {'id': P_ALL, 'uriId': 'filme-und-serien', 'kind': 'Page'}},
                {'title': 'Sammlungen', 'target': {'id': P_COLL, 'uriId': 'sammlungen', 'kind': 'Page'}},
                {'title': 'Kinder', 'target': {'id': P_KIDS, 'uriId': 'kinder', 'kind': 'Page'}}],
                'secondary': [{'title': 'Ist meine Bibliothek dabei?', 'target': {'url': 'https://weristdabei.filmfriend.de/', 'kind': 'Url'}}]}).encode()
        if path.startswith(TENANT + '/pages/'):
            return json.dumps(PAGES[path.rsplit('/', 1)[1]]).encode()
        if path == TENANT + '/search':
            assert q['orderBy'] == ['Title'] and q['take'] == ['24'] and q['kinds'] == ['Movie', 'Series']
            source = KIDS if q['categoryIds'] == [CAT_KIDS] else ALL
            skip = int(q['skip'][0])
            return json.dumps({'results': source[skip:skip + 24], 'facets': None, 'totalCount': None}).encode()
        section, ident = path[len(TENANT) + 1:].split('/')
        if (section, ident) not in DETAILS and ident != uid(50):       # 'Zug' has no detail page (404)
            for entry in ALL + KIDS:
                node = entry.get('movie') or entry.get('series')
                if node['id'] == ident:
                    return json.dumps(node).encode()
        if (section, ident) not in DETAILS:
            raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
        return json.dumps(DETAILS[(section, ident)]).encode()


class FilmfriendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake = FakeFilmfriend()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, now=NOW):
        return filmfriend.sync(self.root, opener=self.fake, now=now)

    def test_catalogue_from_the_searches(self):
        result = self.load()
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['partial'])
        self.assertEqual((result['movies'], result['series']), (26, 1))
        searches = [c[1] for c in self.fake.calls if c[0].endswith('/search')]
        self.assertEqual([(s['categoryIds'], s['skip']) for s in searches],
                         [([CAT_ALL], ['0']), ([CAT_ALL], ['24']), ([CAT_KIDS], ['0'])])
        st = filmfriend.state(self.root)
        self.assertEqual((st['last_result'], st['movies'], st['series'], st['pages']), ('complete', 26, 1, 3))
        self.assertIn('Bibliotheksausweis', st['note'])
        page = filmfriend.listing(self.root, view='movies', limit=100)
        by_title = {r['title']: r for r in page['items']}
        boot = by_title['Abschied']
        self.assertEqual((boot['year'], boot['duration'], boot['rating'], boot['imdb_id'], boot['tmdb_id']),
                         (2023, 5400, 'FSK 12', 'tt18224752', '792614'))
        self.assertEqual(boot['original_title'], "L'Adieu")
        self.assertEqual(boot['web_url'], 'https://www.filmfriend.de/de/movies/abschied')
        self.assertEqual(boot['poster'], 'https://filmwerte-vod.b-cdn.net/videos/1/cover.jpg?width=448&height=640')
        self.assertEqual((boot['badge'], boot['playable']), ('Mit Bibliotheksausweis', 0))
        emil = by_title['Emil']
        self.assertEqual((emil['duration'], emil['rating']), (204, 'FSK 0'))       # runtime is seconds
        self.assertEqual(by_title['Zug']['poster'], 'https://filmwerte-vod.b-cdn.net/videos/50/bg.jpg?width=1280&height=720')
        shows = filmfriend.listing(self.root, view='series')['items']
        self.assertEqual([(s['title'], s['imdb_id'], s['web_url']) for s in shows],
                         [('Allein gegen die Zeit', 'tt1461962', 'https://www.filmfriend.de/de/series/allein-gegen-die-zeit')])
        self.assertEqual(shows[0]['original_title'], '')
        self.assertIn('filmfriend.de', filmfriend.episodes(self.root, shows[0]['id'])['note'])

    def test_details_are_fetched_gently_and_kept(self):
        original = filmfriend.MAX_DETAILS
        filmfriend.MAX_DETAILS = 5
        try:
            self.load()
            first = sum(1 for c in self.fake.calls if '/movies/' in c[0] or '/series/' in c[0])
            self.assertEqual(first, 5)
            st = filmfriend.state(self.root)
            self.assertEqual(st['details_waiting'], 22)
            self.fake.calls.clear()
            self.load(NOW + 86400)
            second = [c[0] for c in self.fake.calls if '/movies/' in c[0] or '/series/' in c[0]]
            self.assertEqual(len(second), 5)
            self.assertEqual(filmfriend.state(self.root)['details_waiting'], 17)
        finally:
            filmfriend.MAX_DETAILS = original
        # details from the first run stay although the title was not read in detail again
        rows = {r['title']: r for r in filmfriend.listing(self.root, limit=100)['items']}
        self.assertEqual(rows['Abschied']['imdb_id'], 'tt18224752')
        self.assertEqual(rows['Abschied']['rating'], 'FSK 12')

    def test_detail_after_ttl_only(self):
        self.load()
        self.fake.calls.clear()
        self.load(NOW + 3600)
        self.assertFalse([c for c in self.fake.calls if '/movies/' in c[0]])
        self.load(NOW + filmfriend.DETAIL_TTL + 10)
        self.assertTrue([c for c in self.fake.calls if '/movies/' in c[0]])

    def test_never_plays_here(self):
        self.load()
        with self.assertRaisesRegex(ValueError, 'Bibliotheksausweis'):
            filmfriend.play_source(self.root, 'm.' + uid(1))
        model = portal_title.model(self.root, 'filmfriend', 'm.' + uid(1))
        self.assertFalse(model['playable'])
        self.assertEqual(model['web_url'], 'https://www.filmfriend.de/de/movies/abschied')

    def test_offline_keeps_old_catalogue(self):
        self.load()
        self.fake.down = True
        result = filmfriend.sync(self.root, opener=self.fake, now=NOW + 86400)
        self.assertFalse(result['ok'])
        st = filmfriend.state(self.root)
        self.assertEqual(st['last_result'], 'failed')
        self.assertIn('nicht erreichbar', st['last_error'])
        self.assertEqual(filmfriend.listing(self.root, limit=100)['total'], 26)

    def test_without_filterable_part_the_known_search_is_used(self):
        saved = dict(PAGES)
        for key in (P_ALL, P_KIDS):
            PAGES[key] = {'id': key, 'parts': []}
        try:
            self.load()
        finally:
            PAGES.update(saved)
        searches = [c[1]['categoryIds'] for c in self.fake.calls if c[0].endswith('/search')]
        self.assertEqual(searches, [[filmfriend.ALL_CATEGORY]] * 2)

    def test_invalid_ids_and_hosts(self):
        for bad in ('', 'm.abc', 'x.' + uid(1), '../x', 'm.' + uid(1) + ';'):
            with self.assertRaises(ValueError):
                filmfriend.item(self.root, bad)
        with self.assertRaises(ValueError):
            filmfriend._open('https://evil.example/v12/x', {})
        with self.assertRaises(ValueError):
            filmfriend._open('http://api.tenant-group.frontend.vod.filmwerte.de/v12/x', {})

    def test_age_ratings(self):
        self.assertEqual(filmfriend._age([{'name': 'FSK 16', 'minimumAge': 16}]), 16)
        self.assertEqual(filmfriend._age([{'name': 'USK 12', 'minimumAge': 12}]), None)
        self.assertEqual(filmfriend._age([{'name': 'FSK 6'}, {'name': 'FSK 12', 'minimumAge': 12}]), 12)
        self.assertIsNone(filmfriend._age(None))

    @unittest.skipUnless(SAMPLES.exists(), 'gespeicherte filmfriend-Antworten vom 20.11.2026 fehlen')
    def test_saved_answers_of_20_11_2026(self):
        with zipfile.ZipFile(SAMPLES) as z:
            read = lambda name: json.loads(z.read('filmfriend_samples/' + name))
            self.assertEqual(filmfriend.tenant_of(read('01_tenant.json')), (TENANT, LANDING))
            pages = filmfriend.menu_pages(read('02_navigation.json'))
            self.assertEqual(len(pages), 4)
            self.assertEqual(filmfriend.page_searches(read('04_seite_movies-and-series.json')),
                             [(('Movie', 'Series'), (CAT_ALL,), (), '')])
            entries = filmfriend.search_entries(read('05_suche_alle_seite1.json'))
            self.assertEqual(len(entries), 24)
            rows = [filmfriend.item_row(k, n) for k, n in entries]
            self.assertTrue(all(r and r['web_url'].startswith('https://www.filmfriend.de/de/') for r in rows))
            blake = filmfriend.item_row('movie', read('07_film_mit_imdbUrl.json'), detailed=True)
            self.assertEqual((blake['imdb_id'], blake['rating'], blake['duration'], blake['year']), ('tt18224752', 'FSK 0', 6349, 2023))
            self.assertIn('b-cdn.net', blake['poster'])
            show = filmfriend.item_row('series', read('09_serie_13-hours.json'), detailed=True)
            self.assertEqual((show['kind'], show['imdb_id'], show['tmdb_id']), ('series', 'tt1461962', '39902'))

    def test_wiring(self):
        self.assertIn('filmfriend', [p.key for p in platform_registry.PLATFORMS])
        self.assertIsNone(next(p for p in platform_registry.PLATFORMS if p.key == 'filmfriend').offline)
        self.assertIn('filmfriend', unified_index.SOURCES)
        self.assertIn('filmfriend', portal_title.PROVIDER_PLAYER_ONLY)
        root = Path(__file__).resolve().parents[1]
        html = (root / 'web' / 'index.html').read_text('utf-8')
        self.assertIn('<section id="filmfriend"', html)
        self.assertIn('<script src="/filmfriend.js"></script>', html)
        self.assertIn("'filmfriend.py'", (root / 'build_macos.py').read_text('utf-8'))
        self.assertIn('./mediathekatlas/filmfriend.py', (root / 'qpkg-files.txt').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
