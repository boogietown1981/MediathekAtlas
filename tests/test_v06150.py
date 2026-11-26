"""0.6.150 (Björn 26.11.2026): Filmreihen (Tatort, Polizeiruf …) und Mehrteiler (Teil 1–n) unter Filme als eine Kachel."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog  # noqa: E402
import unified_index  # noqa: E402
import test_v0555_dashboard_admin as base  # noqa: E402


class Reihen(base.UnifiedPageTests):
    test_merged_sorted_page = test_filters_paging_and_cache = test_removed_work_is_skipped = None

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(catalog, 'LISTING_DB', None);patch.start();self.addCleanup(patch.stop)
        with self.db() as c:
            def film(wid, show, show_title, film_title, year):
                meta = {'title': show_title, 'kind': 'series', 'series_film': 1, 'series_film_title': film_title, 'series_film_year': year}
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          (wid, show_title, 'series', 1970, show, json.dumps(meta), 'matched', 1.0))
                c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                          ('o' + wid, wid, json.dumps({'title': film_title, 'channel': 'ARD', 'url_video': 'https://example.org/v.mp4'}), '', 1, 1.0))
            for i, (t, y) in enumerate((('Murot und das Prinzip Hoffnung', 2023), ('Borowski und der Wiedergänger', 2021), ('Kinder der Nacht', 2024))):
                film('t%d' % i, 'tatort', 'Tatort', t, y)
            for i, t in enumerate(('Die Füchsin', 'Der Tote im See', 'Ein Sommer in Rom')):
                film('m%d' % i, 'filmmittwoch im ersten', 'FilmMittwoch im Ersten', t, 2022)
            film('p0', 'polizeiruf 110', 'Polizeiruf 110', 'Daniel A.', 2020)
            film('p1', 'polizeiruf 110', 'Polizeiruf 110', 'Hildes Erbe', 2021)
            for i, (t, y) in enumerate((('Der Schatz im Silbersee (2/2)', 2019), ('Der Schatz im Silbersee (1/2)', 2019), ('Unsere Mütter, Teil 1', 2013))):
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          ('s%d' % i, t, 'movie', y, '', json.dumps({'title': t, 'kind': 'movie', 'year': y}), 'matched', 1.0))
                c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                          ('os%d' % i, 's%d' % i, json.dumps({'title': t, 'channel': 'ZDF', 'url_video': 'https://example.org/v.mp4'}), '', 1, 1.0))

    def page(self, **kw):
        catalog.invalidate_listings(drop=True);unified_index.invalidate()
        return unified_index.page(self.dir.name, self.db, modules=self.modules, **kw)

    def test_tatort_and_parts_collapse_slots_and_small_reihen_stay(self):
        page = self.page(reihen=True)
        titles = [i['title'] for i in page['items']]
        self.assertIn('Tatort', titles)
        for single in ('Murot und das Prinzip Hoffnung', 'Borowski und der Wiedergänger', 'Der Schatz im Silbersee (1/2)'):
            self.assertNotIn(single, titles)
        for keep in ('Die Füchsin', 'Der Tote im See', 'Daniel A.', 'Hildes Erbe', 'Unsere Mütter, Teil 1'):
            self.assertIn(keep, titles)                      # Sendeplatz, Reihe mit 2 Filmen, einzelner Teil
        tatort = page['items'][titles.index('Tatort')]
        row = tatort['offers'][0]['item']
        self.assertEqual((row['reihe'], row['show_key'], row['film_count'], row['series_parent']), (True, 'tatort', 3, True))
        self.assertEqual(tatort['year'], 2024)
        parts = page['items'][titles.index('Der Schatz im Silbersee')]
        self.assertEqual(parts['mehrteiler'], {'query': 'Der Schatz im Silbersee', 'parts': 2})
        self.assertEqual(titles, sorted(titles, key=unified_index._sort_title))

    def test_search_and_default_show_every_film(self):
        titles = [i['title'] for i in self.page()['items']]
        self.assertIn('Murot und das Prinzip Hoffnung', titles);self.assertNotIn('Tatort', titles)
        found = [i['title'] for i in self.page(query='silbersee', reihen=True)['items']]
        self.assertEqual(sorted(found), ['Der Schatz im Silbersee (1/2)', 'Der Schatz im Silbersee (2/2)'])

    def test_part_parser(self):
        self.assertEqual(unified_index._part('Unsere Mütter, unsere Väter - Teil zwei'), ('Unsere Mütter, unsere Väter', 2))
        self.assertIsNone(unified_index._part('12 Monkeys'));self.assertIsNone(unified_index._part('Teil 1'))

    def test_ui_and_server(self):
        js = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn("function showParts(query,order='title')", js);self.assertIn("'Filmreihe'", js);self.assertIn("' Teile'", js)
        self.assertIn("reihen: '0'", (ROOT / 'web' / 'watch_mode.js').read_text(encoding='utf-8'))
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("reihen=q.get('reihen',['1' if UNIFIED_REIHEN else '0'])[0]=='1'", server)
        self.assertIn('UNIFIED_REIHEN=True', server)       # 0.6.153 aus, 0.6.154 nach der Korrektur wieder an


if __name__ == '__main__':
    unittest.main()
