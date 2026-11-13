"""0.5.83: einheitliche deutsche Kategorien für Filme und Serien aller Quellen (Björn, 13.11.2026).

Vorher wurden die Genre-Bezeichnungen jedes Anbieters direkt als Chips gezeigt: Dubletten wie
„Fantasie“/„Fantasy“, „Krimi“/„Kriminalfilms“, Englisch/Deutsch gemischt, „Joyn (kostenlos)“ als
Kategorie. Jetzt: feste Liste, Zuordnung erst nach dem Abgleich, davor „Unklassifiziert“.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import categories  # noqa: E402
import catalog  # noqa: E402
import portal_reference as pr  # noqa: E402


class FixedListTests(unittest.TestCase):
    def test_screenshot_duplicates_collapse(self):
        pairs = {
            'Fantasie': ['Fantasy'], 'Fantasy': ['Fantasy'], 'Fantasy television series': ['Fantasy'],
            'Krimi': ['Krimi'], 'Kriminalfilms': ['Krimi'], 'Crime': ['Krimi'], 'Neo-Noir': ['Krimi'],
            'Science-Fiction': ['Science-Fiction'], 'Sciencefiction-Horrorfilm': ['Horror', 'Science-Fiction'],
            'Science fiction television series': ['Science-Fiction'], 'Sci-Fi & Fantasy': ['Fantasy', 'Science-Fiction'],
            'Dokumentation': ['Dokumentation'], 'Dokumentationen': ['Dokumentation'], 'Documentary': ['Dokumentation'],
            'Romantische Komödie': ['Komödie', 'Romantik'], 'Kriegsfilm': ['Krieg'], 'War & Politics': ['Krieg', 'Politik & Gesellschaft'],
            'Dokusoap': ['Reality-TV'], 'Doku-Soap': ['Reality-TV'], 'Talkshow': ['Talk'], 'Kinderfernsehen': ['Kinder & Familie'],
            'Angeln': ['Sport'], 'Skifahren': ['Sport'], 'Kochen': ['Ratgeber & Lifestyle'], 'Komoedie': ['Komödie'],
        }
        for label, expected in pairs.items():
            self.assertEqual(categories.of_label(label), expected, label)

    def test_formats_and_platform_labels_are_no_category(self):
        for label in ('Joyn (kostenlos)', 'Joyn+', 'TV-Film', 'Miniserie', 'Kurzfilm', 'Spielfilm', 'Unbekannt', ''):
            self.assertEqual(categories.of_label(label), [], label)

    def test_every_result_is_in_the_fixed_list(self):
        for label in ('Mantel-und-Degen-Film', 'Bruceploitation', 'Öffentliche Angelegenheiten', 'Haus und Garten',
                      'Stand-up-Comedy/Kabarett', 'Reality-Spielshow', 'Point-and-Click-Adventure', 'E-Sport'):
            names = categories.of_label(label)
            self.assertTrue(names, label)
            self.assertTrue(set(names) <= set(categories.CATEGORIES), label)

    def test_classify_only_after_check(self):
        self.assertEqual(categories.classify([], ['Krimi'], checked=False), ['Unklassifiziert'])
        self.assertEqual(categories.classify(['Crime'], ['Komödie'], checked=True), ['Krimi'])   # reference first
        self.assertEqual(categories.classify([], ['Kriminalfilms'], checked=True), ['Krimi'])  # provider fallback
        self.assertEqual(categories.classify([], ['Deutscher Film'], checked=True), ['Sonstige'])

    def test_wanted_understands_old_links(self):
        self.assertEqual(categories.wanted('krimi'), ('Krimi', 'krimi'))
        self.assertEqual(categories.wanted('Unbekannt')[0], 'Unklassifiziert')
        self.assertEqual(categories.wanted('Kriminalfilms')[0], 'Krimi')


class PortalTests(unittest.TestCase):
    def test_rows_filter_by_category_and_source_genres_stay(self):
        report = {'status': 'no_match'}
        out = pr.summary('Kriminalfilms, Fantasie', report)
        self.assertEqual(out['categories'], ['Fantasy', 'Krimi'])
        self.assertEqual(out['source_genres'], ['Kriminalfilms', 'Fantasie'])
        self.assertTrue(pr.matches(out, 'Krimi'))
        self.assertTrue(pr.matches(out, 'Kriminalfilms'))     # old raw label in a saved link
        self.assertFalse(pr.matches(out, 'Unklassifiziert'))
        pending = pr.summary('Krimi', None)
        self.assertEqual(pending['categories'], ['Unklassifiziert'])
        self.assertTrue(pr.matches(pending, 'Unbekannt'))
        self.assertFalse(pr.matches(pending, 'Krimi'))

    def test_identified_by_provider(self):
        self.assertEqual(pr.summary('Horror', None, identified=True)['categories'], ['Horror'])

    def test_facets_in_fixed_order_specials_last(self):
        rows = [{'categories': ['Unklassifiziert']}, {'categories': ['Western']}, {'categories': ['Action', 'Krimi']},
                {'categories': ['Sonstige']}]
        self.assertEqual([f['genre'] for f in pr.facets(rows)], ['Action', 'Krimi', 'Western', 'Unklassifiziert', 'Sonstige'])

    def test_download_genres_unchanged(self):
        meta = pr.apply({'title': 'X', 'kind': 'movie'}, {'status': 'candidate', 'metadata': {'genres': ['Crime']}}, 'pluto')
        self.assertEqual(meta['genres'], ['Krimi'])


class MediathekTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        catalog.initialize(self.c)

    def add(self, wid, kind, genres, attempts=0, state='pending', show=None):
        self.c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,?)",
                       (wid, wid, kind, 2000, show or wid, '{}', state, attempts))
        self.c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)", ('o' + wid, wid, '{"title": "x", "url_video": "https://example.org/v.mp4"}'))
        for g in genres:
            self.c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))

    def test_tree_and_filters(self):
        self.add('a', 'movie', ['Krimi', 'Kriminalfilms'], attempts=1)      # one film, two spellings
        self.add('b', 'movie', ['Fantasie'], state='matched')
        self.add('c', 'movie', ['Deutscher Film'], attempts=2)              # checked, no category
        self.add('d', 'movie', ['Horror'])                                  # not yet checked
        self.add('e1', 'series', ['Comedy'], attempts=1, show='s1')         # one checked episode ...
        self.add('e2', 'series', [], show='s1')                             # ... classifies the show
        tree = {(r['kind'], r['genre']): r['n'] for r in catalog.category_tree(self.c)}
        self.assertEqual(tree, {('movie', 'Krimi'): 1, ('movie', 'Fantasy'): 1, ('movie', 'Sonstige'): 1,
                                ('movie', 'Unklassifiziert'): 1, ('series', 'Komödie'): 1})
        total = lambda g: catalog.listing(self.c, kind='movie', genre=g, downloaded='all')['total']
        self.assertEqual((total('Krimi'), total('Fantasy'), total('Sonstige'), total('Unklassifiziert'), total('Horror')),
                         (1, 1, 1, 1, 0))
        # Classic raw tree (Verwaltung → Werkkatalog) still filters by the stored label.
        self.assertEqual(total('Kriminalfilms'), 1)
        self.assertTrue(any(r['genre'] == 'Kriminalfilms' for r in catalog.tree(self.c)))


class UiTests(unittest.TestCase):
    def test_chips_and_selection_use_fixed_list(self):
        js = (ROOT / 'web' / 'unified_catalog.js').read_text()
        self.assertIn("data.categories||[]", js)
        self.assertIn('CATEGORY_NAMES', js)
        for name in categories.CATEGORIES:
            self.assertIn("'" + name + "'", js)
        self.assertIn('portal-category-special', (ROOT / 'web' / 'portal_categories.js').read_text())
        self.assertIn("'categories.py'", (ROOT / 'build_macos.py').read_text())


if __name__ == '__main__':
    unittest.main()
