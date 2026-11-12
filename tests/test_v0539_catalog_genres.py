"""0.5.39: unified catalogue keeps the Mediathek genre assignment (category bar with counts)
and the "Entdecken" views Großes Kino / Serienfavoriten for every source."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pluto, pluto_enrichment, portal_reference as pr  # noqa: E402
from test_v0536_pluto import Fixture, MOVIE  # noqa: E402
from test_v0538_portal_categories import imdb_lookup  # noqa: E402


class PickRuleTests(unittest.TestCase):
    def test_same_thresholds_as_mediathek_catalogue(self):
        self.assertTrue(pr.is_pick({'value': 7.5, 'source': 'IMDb', 'votes': 10000}))
        self.assertFalse(pr.is_pick({'value': 7.4, 'source': 'IMDb', 'votes': 900000}))
        self.assertFalse(pr.is_pick({'value': 8.0, 'source': 'IMDb', 'votes': 9999}))
        self.assertTrue(pr.is_pick({'value': 8.0, 'source': 'TMDB', 'votes': 1000}))
        self.assertFalse(pr.is_pick({'value': 9.0, 'source': 'Wikidata', 'votes': 10 ** 6}))
        self.assertFalse(pr.is_pick(None))
        row = {'score': {'value': 8.0, 'source': 'IMDb', 'votes': 20000}}
        self.assertTrue(pr.in_collection(row, 'cinema', 'movie'))
        self.assertFalse(pr.in_collection(row, 'series', 'movie'))
        self.assertTrue(pr.in_collection({}, '', 'movie'))


class PlutoCollectionTests(Fixture):
    def test_great_cinema_filter(self):
        self.sync()
        self.assertEqual(pluto.listing(self.root, 'movies', collection='cinema')['total'], 0)
        pluto_enrichment.enrich(self.root, MOVIE['_id'], {}, lookup=imdb_lookup([]), now=time.time())
        self.assertEqual(pluto.listing(self.root, 'movies', collection='cinema')['total'], 1)
        self.assertEqual(pluto.listing(self.root, 'series', collection='series')['total'], 0)


class NetzkinoCollectionTests(unittest.TestCase):
    def test_grouped_catalog_collection(self):
        import netzkino, netzkino_enrichment
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = netzkino._connect(root)
            now = time.time()
            with db:
                for item, title in (('ab' * 16, 'Hin und Weg'), ('cd' * 16, 'Gruselnacht')):
                    db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,genres)
                        VALUES(?,?,?,?,?,?,?,?,?)''', (item, title, 'https://www.netzkino.de/details/' + item, 'graphql',
                        'unverified', now, now, 'movie', 'Drama'))
            db.close()
            db = netzkino_enrichment._conn(root)
            with db:
                db.execute('INSERT INTO netzkino_reference_checks VALUES(?,?,?,?)', ('ab' * 16, 'x', now, json.dumps(
                    {'status': 'candidate', 'metadata': {'rating': 8.1, 'votes': 50000},
                     'field_sources': {'rating': 'IMDb Offline'}})))
            db.close()
            data = netzkino.grouped_catalog(root, view='movies', collection='cinema')
            self.assertEqual([r['title'] for r in data['items']], ['Hin und Weg'])
            self.assertEqual(netzkino.grouped_catalog(root, view='movies')['total'], 2)


class UiTests(unittest.TestCase):
    def test_unified_catalogue_has_genre_bar_and_discover(self):
        html = (ROOT / 'web' / 'index.html').read_text()
        self.assertIn('id="atlas-cross-collection"', html)
        self.assertIn('id="atlas-cross-categories"', html)
        js = (ROOT / 'web' / 'unified_catalog.js').read_text()
        for needle in ('paintCategories(counts)', 'medTree.filter(r=>r.kind===', "collection", "'Großes Kino'"):
            self.assertIn(needle, js)
        s = (ROOT / 'server.py').read_text()
        self.assertGreaterEqual(s.count("collection=q.get('collection',[''])[0][:20]"), 2)

    def test_smoke_script(self):
        r = subprocess.run(['node', str(ROOT / 'tests' / 'unified_catalog_ui_smoke.cjs')], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode()[-500:])


if __name__ == '__main__':
    unittest.main()
