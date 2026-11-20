"""0.6.52: filmfriend (film library of public libraries) as a catalogue with links.

Shapes as explored on Björn's Mac on 20.11.2026 (tenant for www.filmfriend.de with landingPageId, navigation,
pages with blocks and movie references {id, uriId, kind: "Movie"}, movie details with title, originalTitle,
synopsis, releaseDate, ageRatings, runtime, genres, categories, productionCountries, imdbUrl, tmdbUrl). Ids and
titles are made up. Watching needs a library card login: never a player here, every title opens on filmfriend.de."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import filmfriend
import platform_registry
import portal_title
import unified_index

TENANT = 'fba2f8b5-6a3a-4da3-b555-21613a88d3ef'
LANDING = 'e25869cd-2557-4bba-ba3b-672378285c2d'
GENRE_PAGE = '11111111-2222-3333-4444-555555555555'
GONE_PAGE = '99999999-2222-3333-4444-555555555555'
M1, M2, M3, M4 = ('aaaaaaaa-0000-0000-0000-00000000000%d' % n for n in (1, 2, 3, 4))
NOW = 1795132800


def ref(ident, uri, kind='Movie'):
    return {'id': ident, 'uriId': uri, 'kind': kind}


PAGES = {
    LANDING: {'id': LANDING, 'blocks': [
        {'kind': 'Banner', 'items': [ref(M1, 'das-boot')]},
        {'kind': 'Collection', 'title': 'Neu', 'items': [ref(M1, 'das-boot'), ref(M2, 'paddington')]},
        {'kind': 'Genres', 'items': [{'title': 'Kinderfilm', 'link': '/de/pages/' + GENRE_PAGE}]},
        {'kind': 'Video', 'items': [ref('bbbbbbbb-0000-0000-0000-000000000001', 'trailer', kind='Video')]}]},
    GENRE_PAGE: {'id': GENRE_PAGE, 'blocks': [{'kind': 'SearchResult', 'items': [ref(M2, 'paddington'), ref(M3, 'emil')]},
                                              {'kind': 'Collection', 'items': [ref(M4, 'weg')]}]},
}
MOVIES = {
    M1: {'id': M1, 'uriId': 'das-boot', 'title': 'Das Boot', 'originalTitle': 'Das Boot',
         'synopsis': 'U-Boot im Zweiten Weltkrieg.', 'releaseDate': '1981-09-17T00:00:00Z',
         'ageRatings': [{'country': 'DE', 'value': 'FSK 12'}], 'runtime': 149,
         'genres': [{'name': 'Drama'}, {'name': 'Kriegsfilm'}], 'categories': [{'name': 'Klassiker'}],
         'productionCountries': [{'name': 'Deutschland'}], 'imdbUrl': 'https://www.imdb.com/title/tt0082096/',
         'tmdbUrl': 'https://www.themoviedb.org/movie/387', 'hasTrailer': True,
         'images': [{'type': 'Poster', 'url': 'https://images.filmwerte.de/poster/das-boot.jpg'}]},
    M2: {'id': M2, 'uriId': 'paddington', 'title': 'Paddington', 'originalTitle': 'Paddington',
         'synopsis': 'Ein Bär in London.', 'releaseDate': '2014-11-28', 'ageRatings': [{'country': 'DE', 'value': '0'}],
         'runtime': 'PT1H35M', 'genres': ['Familie', 'Komödie'], 'imdbUrl': 'https://www.imdb.com/title/tt1109624'},
    M3: {'id': M3, 'title': 'Emil und die Detektive', 'releaseDate': '2001', 'runtime': 6600,
         'ageRatings': [{'country': 'AT', 'value': '10'}, {'country': 'DE', 'value': 'FSK 6'}]},
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
        path = parts.path[len('/v12/'):]
        self.calls.append(path)
        if path == 'www.filmfriend.de':
            return json.dumps({'id': TENANT, 'name': 'filmfriend', 'landingPageId': LANDING}).encode()
        if path == TENANT + '/navigation':
            return json.dumps({'items': [{'title': 'Start', 'pageId': LANDING},
                                         {'title': 'Weg', 'pageId': GONE_PAGE}]}).encode()
        if path.startswith(TENANT + '/pages/'):
            page = path.rsplit('/', 1)[1]
            if page not in PAGES:
                raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
            return json.dumps(PAGES[page]).encode()
        if path.startswith(TENANT + '/movies/'):
            movie = path.rsplit('/', 1)[1]
            if movie not in MOVIES:
                raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
            return json.dumps(MOVIES[movie]).encode()
        raise AssertionError(url)


class FilmfriendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake = FakeFilmfriend()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, now=NOW):
        return filmfriend.sync(self.root, opener=self.fake, now=now)

    def test_catalogue_from_pages_and_movies(self):
        result = self.load()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['movies'], 3)
        self.assertFalse(result['partial'])
        st = filmfriend.state(self.root)
        self.assertEqual((st['last_result'], st['movies'], st['pages']), ('complete', 3, 2))
        self.assertIn('Bibliotheksausweis', st['note'])
        # every film read once, the vanished page and film skipped quietly
        self.assertEqual(sum(1 for c in self.fake.calls if '/movies/' in c), 4)
        page = filmfriend.listing(self.root, view='movies')
        self.assertEqual([r['title'] for r in page['items']], ['Das Boot', 'Emil und die Detektive', 'Paddington'])
        boot = page['items'][0]
        self.assertEqual((boot['year'], boot['duration'], boot['rating'], boot['imdb_id']), (1981, 149 * 60, 'FSK 12', 'tt0082096'))
        self.assertEqual(boot['web_url'], 'https://www.filmfriend.de/de/movies/das-boot')
        self.assertEqual(boot['poster'], 'https://images.filmwerte.de/poster/das-boot.jpg')
        self.assertIn('Kriegsfilm', boot['genre'])
        self.assertIn('Klassiker', boot['genre'])
        self.assertEqual(boot['badge'], 'Mit Bibliotheksausweis')
        self.assertEqual(boot['playable'], 0)
        self.assertEqual(filmfriend.listing(self.root, view='series')['total'], 0)
        emil = page['items'][1]
        self.assertEqual((emil['duration'], emil['rating'], emil['year']), (6600, 'FSK 6', 2001))
        self.assertEqual(emil['web_url'], 'https://www.filmfriend.de/de/movies/emil')
        pad = page['items'][2]
        self.assertEqual((pad['duration'], pad['rating'], pad['genre']), (95 * 60, 'FSK 0', 'Familie, Komödie'))
        detail = filmfriend.item(self.root, 'm.' + M1)['item']
        self.assertEqual((detail['original_title'], detail['country'], detail['tmdb_id']), ('', 'Deutschland', '387'))

    def test_search_finds_original_title(self):
        MOVIES[M3]['originalTitle'] = 'Emil and the Detectives'
        try:
            self.load()
        finally:
            del MOVIES[M3]['originalTitle']
        self.assertEqual(filmfriend.listing(self.root, query='Detectives')['total'], 1)

    def test_never_plays_here(self):
        self.load()
        with self.assertRaisesRegex(ValueError, 'Bibliotheksausweis'):
            filmfriend.play_source(self.root, 'm.' + M1)
        model = portal_title.model(self.root, 'filmfriend', 'm.' + M1)
        self.assertFalse(model['playable'])
        self.assertEqual(model['web_url'], 'https://www.filmfriend.de/de/movies/das-boot')

    def test_offline_keeps_old_catalogue(self):
        self.load()
        self.fake.down = True
        result = filmfriend.sync(self.root, opener=self.fake, now=NOW + 86400)
        self.assertFalse(result['ok'])
        st = filmfriend.state(self.root)
        self.assertEqual(st['last_result'], 'failed')
        self.assertIn('nicht erreichbar', st['last_error'])
        self.assertEqual(filmfriend.listing(self.root)['total'], 3)

    def test_invalid_ids_and_hosts(self):
        for bad in ('', 'm.abc', 's.' + M1, '../x', 'm.' + M1 + ';'):
            with self.assertRaises(ValueError):
                filmfriend.item(self.root, bad)
        with self.assertRaises(ValueError):
            filmfriend._open('https://evil.example/v12/x', {})
        with self.assertRaises(ValueError):
            filmfriend._open('http://api.tenant-group.frontend.vod.filmwerte.de/v12/x', {})

    def test_parsing_helpers(self):
        self.assertEqual(filmfriend._runtime('PT2H'), 7200)
        self.assertEqual(filmfriend._runtime(90), 5400)
        self.assertIsNone(filmfriend._runtime('lang'))
        self.assertEqual(filmfriend._age([{'country': 'US', 'value': 'R'}]), None)
        self.assertEqual(filmfriend._age(['FSK 16']), 16)
        self.assertEqual(filmfriend.tenant_of({'tenant': {'id': TENANT}, 'settings': {'landingPageId': LANDING}}),
                         (TENANT, LANDING))

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
