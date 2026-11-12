"""0.5.38: categories + ratings from IMDb/TVDB checks for Netzkino and Pluto, Pluto details,
download metadata like ARD/ZDF, Pluto 30 days offline."""
import json
import sqlite3
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core, pluto, pluto_downloads, pluto_enrichment, portal_reference as pr  # noqa: E402
from test_v0536_pluto import Fixture, MOVIE, SERIES  # noqa: E402

EPISODE = '61aabbccddeeff0011220001'


def imdb_lookup(calls):
    def lookup(row, meta, settings):
        calls.append((row, meta))
        self_title = meta['title']
        kind = meta['kind']
        return {'candidates': [{'provider': 'IMDb Offline', 'reference_id': 'tt2543164' if kind == 'movie' else 'tt0247082',
                                'title': self_title, 'kind': kind, 'year': meta.get('year'), 'similarity': 1.0,
                                'genres': ['Drama', 'Mystery', 'Sci-Fi'] if kind == 'movie' else ['Crime', 'Drama'],
                                'rating': 7.9, 'votes': 750000, 'cast': ['Amy Adams', 'Jeremy Renner'],
                                'poster': 'https://m.media-amazon.com/images/arrival.jpg'}],
                'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 1}]}
    return lookup


class SharedRulesTests(unittest.TestCase):
    def test_categories_are_the_mediathek_genres(self):
        report = {'metadata': {'genres': ['Comedy', 'Crime']}}
        self.assertEqual(pr.categories('Action', report), ['Komödie', 'Krimi'])  # reference first
        self.assertEqual(pr.categories('Sci-Fi & Fantasy', None), ['Fantasy', 'Science-Fiction'])
        self.assertEqual(pr.categories('["Kinderfilm","Familie"]', {}), ['Kinder & Familie'])
        self.assertEqual(pr.categories('', None), [pr.UNKNOWN])

    def test_facets_and_matching(self):
        rows = [{'categories': ['Drama', 'Krimi']}, {'categories': ['Drama']}, {'categories': [pr.UNKNOWN]}]
        self.assertEqual(pr.facets(rows), [{'genre': 'Drama', 'n': 2}, {'genre': 'Krimi', 'n': 1}, {'genre': pr.UNKNOWN, 'n': 1}])
        self.assertTrue(pr.matches(rows[0], 'krimi'))
        self.assertFalse(pr.matches(rows[1], 'Krimi'))
        self.assertTrue(pr.matches(rows[1], ''))

    def test_rating_only_from_valid_reference(self):
        self.assertEqual(pr.rating({'metadata': {'rating': 7.94, 'votes': 10}, 'field_sources': {'rating': 'IMDb Offline'}}),
                         {'value': 7.9, 'source': 'IMDb', 'votes': 10})
        self.assertIsNone(pr.rating({'metadata': {'rating': 11}}))
        self.assertIsNone(pr.rating(None))

    def test_apply_like_ard_download(self):
        report = {'status': 'candidate', 'from_reference': True,
                  'metadata': {'genres': ['Drama'], 'cast': ['A B'], 'poster': 'https://image.tmdb.org/p.jpg',
                               'description': 'Serieninhalt', 'rating': 8.0, 'votes': 5},
                  'field_sources': {'rating': 'IMDb Offline'},
                  'references': [{'provider': 'IMDb Offline', 'reference_id': 'tt0000001', 'eligible': True}]}
        meta = pr.apply({'kind': 'movie', 'title': 'X', 'genres': ['Action'], 'poster': '', 'description': ''}, report, 'Pluto TV')
        self.assertEqual((meta['provider'], meta['reference_id'], meta['imdb_id'], meta['source_provider']),
                         ('IMDb Offline', 'tt0000001', 'tt0000001', 'Pluto TV'))
        self.assertEqual(meta['genres'], ['Drama'])
        self.assertEqual(meta['cast'], [{'name': 'A B'}])
        self.assertEqual((meta['rating'], meta['description']), (8.0, 'Serieninhalt'))
        episode = pr.apply({'kind': 'series', 'title': 'S', 'season': 1, 'episode': 2, 'description': ''},
                           report, 'Pluto TV', series_report=True)
        self.assertEqual((episode['description'], episode['show_description']), ('', 'Serieninhalt'))
        # Ambiguous checks never set an identity.
        self.assertNotIn('reference_id', pr.apply({'kind': 'movie', 'title': 'X'}, {**report, 'status': 'review'}, 'Netzkino'))


class PlutoReferenceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()
        pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=2000)
        self.lookups = []

    def enrich(self, item):
        return pluto_enrichment.enrich(self.root, item, {}, lookup=imdb_lookup(self.lookups), now=time.time())

    def test_reference_check_feeds_categories_rating_and_filter(self):
        self.assertEqual(set(pluto_enrichment.pending(self.root, now=time.time())), {MOVIE['_id'], SERIES['_id']})
        report = self.enrich(MOVIE['_id'])
        self.assertEqual(report['status'], 'candidate')
        self.assertEqual(self.lookups[0][0]['channel'], 'Pluto TV')
        self.assertEqual(pluto_enrichment.pending(self.root, now=time.time()), [SERIES['_id']])
        films = pluto.listing(self.root, 'movies')
        film = films['items'][0]
        self.assertEqual(film['categories'], ['Drama', 'Mystery', 'Science-Fiction'])
        self.assertEqual(film['score'], {'value': 7.9, 'source': 'IMDb', 'votes': 750000})
        self.assertEqual(film['rating'], 'FSK 12')  # Pluto's age rating is kept
        self.assertEqual(films['genre_counts'][0], {'genre': 'Drama', 'n': 1})
        self.assertEqual(pluto.listing(self.root, 'movies', genre='Mystery')['total'], 1)
        self.assertEqual(pluto.listing(self.root, 'movies', genre='Western')['total'], 0)
        # Not yet checked: Pluto's own genre label, canonical.
        self.assertEqual(pluto.listing(self.root, 'series')['items'][0]['categories'], [pr.UNKNOWN])

    def test_episode_uses_series_report_in_detail_and_episode_list(self):
        self.enrich(EPISODE)  # checks the series
        self.assertEqual(self.lookups[0][1]['kind'], 'series')
        self.assertEqual(self.lookups[0][1]['title'], 'CSI')
        detail = pluto.item(self.root, EPISODE)
        self.assertEqual(detail['series']['title'], 'CSI')
        self.assertEqual(detail['item']['categories'], ['Drama', 'Krimi'])
        self.assertEqual(detail['reference']['status'], 'candidate')
        listed = pluto.episodes(self.root, SERIES['_id'], fetch=self.fetch, now=2001)
        self.assertEqual(listed['items'][0]['score']['value'], 7.9)
        with self.assertRaises(ValueError):
            pluto.item(self.root, '../etc')

    def test_cached_report_is_discarded_after_title_change(self):
        self.enrich(MOVIE['_id'])
        db = pluto._connect(self.root)
        with db:
            db.execute('UPDATE pluto_items SET title=? WHERE id=?', ('Arrival (Neu)', MOVIE['_id']))
        db.close()
        self.assertEqual(pluto_enrichment.cached(self.root, MOVIE['_id'])['status'], 'unchecked')

    def test_download_metadata_like_ard(self):
        self.enrich(MOVIE['_id'])
        c = sqlite3.connect(':memory:'); self.addCleanup(c.close)
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        media = self.root / 'media'; media.mkdir()
        r = pluto_downloads.enqueue(c, self.root, media, MOVIE['_id'], now=1000)
        job = json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        meta = job['metadata']
        self.assertEqual((meta['provider'], meta['reference_id'], meta['source_provider']), ('IMDb Offline', 'tt2543164', 'Pluto TV'))
        self.assertEqual(meta['genres'], ['Drama', 'Mystery', 'Science-Fiction'])
        self.assertEqual(meta['cast'], [{'name': 'Amy Adams'}, {'name': 'Jeremy Renner'}])
        self.assertEqual(job['license']['days'], 30)
        self.assertEqual(Path(job['target']).relative_to(media.resolve()).as_posix(), 'Filme/Arrival (2015)/Arrival (2015).mkv')
        nfo = core.nfo(meta, [], 6420).decode()
        self.assertIn('<uniqueid type="imdb" default="true">tt2543164</uniqueid>', nfo)
        self.assertIn('<genre>Science-Fiction</genre>', nfo)
        self.assertIn('Amy Adams', nfo)


class NetzkinoCategoryTests(unittest.TestCase):
    def test_grouped_catalog_uses_reference_categories(self):
        import tempfile, netzkino, netzkino_enrichment
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = netzkino._connect(root)
            now = time.time()
            with db:
                for item, title, genres in (('ab' * 16, 'Hin und Weg', 'Comedy,Drama'), ('cd' * 16, 'Gruselnacht', 'Horror')):
                    db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,genres)
                        VALUES(?,?,?,?,?,?,?,?,?)''', (item, title, 'https://www.netzkino.de/details/' + item, 'graphql',
                        'unverified', now, now, 'movie', genres))
            db.close()
            db = netzkino_enrichment._conn(root)
            with db:
                db.execute('INSERT INTO netzkino_reference_checks VALUES(?,?,?,?)', ('ab' * 16, 'x', now, json.dumps(
                    {'status': 'candidate', 'metadata': {'genres': ['Romance'], 'rating': 6.8},
                     'field_sources': {'rating': 'TMDB'}})))
            db.close()
            data = netzkino.grouped_catalog(root, view='movies', sort='rating')
            first = data['items'][0]
            self.assertEqual((first['title'], first['categories'], first['score']['value']), ('Hin und Weg', ['Romantik'], 6.8))
            self.assertEqual(data['items'][1]['categories'], ['Horror'])
            self.assertEqual([g['genre'] for g in data['genre_counts']], ['Horror', 'Romantik'])
            self.assertEqual(netzkino.grouped_catalog(root, view='movies', genre='horror')['total'], 1)


class WiringTests(unittest.TestCase):
    def test_server_ui_and_bundle(self):
        s = (ROOT / 'server.py').read_text()
        for needle in ("'/api/pluto-details'", "'/api/pluto-enrich'", 'pluto_enrichment.loop', "'film_platforms'",
                       "pluto_enrichment.enrich(ROOT,item_id,settings())", "netzkino_enrichment.enrich(ROOT,item_id,settings())"):
            self.assertIn(needle, s)
        html = (ROOT / 'web' / 'index.html').read_text()
        # 0.5.42: details on the shared title page (portal_title.js) instead of a Pluto dialog.
        for needle in ('<script src="/portal_title.js"></script>', 'id="pluto-categories"', 'id="netzkino-categories"',
                       'data-catalog-source="pluto"', '/portal_categories.js'):
            self.assertIn(needle, html)
        self.assertIn("'pluto'", (ROOT / 'web' / 'unified_catalog.js').read_text())
        build = (ROOT / 'build_macos.py').read_text()
        self.assertIn("'pluto_enrichment.py'", build)
        self.assertIn("'portal_reference.py'", build)
        self.assertEqual(pluto_downloads.OFFLINE_DAYS, 30)


if __name__ == '__main__':
    unittest.main()
