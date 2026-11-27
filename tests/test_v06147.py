"""0.6.147 (Mac-Prüfung 0.6.144, BEFUND-06144.txt): eine vor dem Reihenfilm-Markierlauf gestellte Suche („Geisternetze“,
0 Treffer) blieb danach veraltet, auch 10 min später; erst ein Neustart lieferte den Treffer. Suchen werden nach einer
Katalogänderung neu gebaut, ohne auf die Build-Sperren zu warten."""
import contextlib
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import catalog  # noqa: E402
import unified_index as ui  # noqa: E402
import test_v06137  # noqa: E402
from test_v06137 import offer  # noqa: E402


class SearchAfterMark(unittest.TestCase):
    series = test_v06137.SeriesFilms.series
    mark = test_v06137.SeriesFilms.mark

    def setUp(self):
        test_v06137.SeriesFilms.setUp(self)
        self.c.commit()
        path = self.c.execute('PRAGMA database_list').fetchone()[2]

        @contextlib.contextmanager
        def factory():
            x = sqlite3.connect(path);x.row_factory = sqlite3.Row
            try:
                yield x;x.commit()
            finally:
                x.close()
        self.factory = factory
        p = mock.patch.object(catalog, 'LISTING_DB', factory);p.start();self.addCleanup(p.stop)
        p = mock.patch.object(catalog, 'LISTING_FILE', None);p.start();self.addCleanup(p.stop)
        p = mock.patch.dict(catalog._LISTING, clear=True);p.start();self.addCleanup(p.stop)
        ui.invalidate();self.addCleanup(ui.invalidate)
        self.root = tempfile.mkdtemp()
        self.series([offer('Geisternetze (26)', 'Der Usedom-Krimi', 3)]);self.c.commit()

    def hits(self, wait):
        return len(catalog.listing(self.c, query='Geisternetze', kind='movie', index_only=True, wait=wait))

    def unified(self):
        return ui.page(self.root, self.factory, kind='movies', query='Geisternetze', modules={})['total']

    def test_search_is_fresh_right_after_the_mark_while_builds_hold_the_locks(self):
        self.assertEqual((self.hits(True), self.hits(False), self.unified()), (0, 0, 0))
        self.mark();self.c.commit()
        catalog.invalidate_listings();ui.invalidate(soft=True)        # wie mark_series_films im Dienst
        with catalog._LISTING_BUILD, ui._BUILD:                        # Kinderecke/Index bauen gerade
            started = time.monotonic()
            self.assertEqual((self.hits(True), self.hits(False), self.unified()), (1, 1, 1))
            self.assertLess(time.monotonic() - started, 1.0)

    def test_outdated_search_is_rebuilt_not_served_from_memory(self):
        self.assertEqual(self.hits(True), 0)
        self.mark();self.c.commit()
        later = time.monotonic() + 600                                  # TTL abgelaufen, ohne invalidate
        with catalog._LISTING_BUILD, mock.patch.object(catalog.time, 'monotonic', lambda: later):
            self.assertEqual(self.hits(True), 1)

    def test_plain_lists_still_answer_outdated_while_the_lock_is_held(self):
        self.assertEqual(len(catalog.listing(self.c, kind='movie', index_only=True)), 0)
        self.mark();self.c.commit();catalog.invalidate_listings()
        with catalog._LISTING_BUILD:
            self.assertEqual(len(catalog.listing(self.c, kind='movie', index_only=True)), 0)   # 0.6.144 bleibt


class Suggestions(unittest.TestCase):
    def test_kids_page_has_suggestions(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        html = (ROOT / 'web' / 'kids.html').read_text(encoding='utf-8')
        self.assertIn('function suggest(v, skip, n)', js);self.assertIn('showSuggestions(v, n)', js)
        self.assertIn('id="kids-suggest-list"', html);self.assertIn('Mehr davon', html)


if __name__ == '__main__':
    unittest.main()
