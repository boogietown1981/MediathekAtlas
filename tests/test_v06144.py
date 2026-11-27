"""0.6.144 (Mac-Prüfung 0.6.142, BEFUND-06142.txt): Filme auf dem Air 54 s direkt nach dem Reihenfilm-Markierlauf. Der
Lauf leerte den Index-Speicher; die nächste Anfrage baute neu und wartete dabei hinter dem Kinderecke-Aufbau auf _BUILD.
Jetzt bleibt der alte Index lesbar und wird im Hintergrund erneuert."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import unified_index as ui  # noqa: E402


class SoftInvalidate(unittest.TestCase):
    def setUp(self):
        ui.invalidate();self.addCleanup(ui.invalidate)

    def test_old_index_answers_while_another_build_holds_the_lock(self):
        ui._cached('k', lambda: {'entries': ['alt']})
        renewed = threading.Event()

        def builder():
            renewed.set();return {'entries': ['neu']}
        ui.invalidate(soft=True)
        with ui._BUILD:                       # Kinderecke baut gerade
            started = time.monotonic()
            self.assertEqual(ui._cached('k', builder)['entries'], ['alt'])
            self.assertLess(time.monotonic() - started, .5)
        self.assertTrue(renewed.wait(5))
        for _ in range(50):
            if ui._cached('k', builder)['entries'] == ['neu']:
                break
            time.sleep(.05)
        self.assertEqual(ui._cached('k', builder)['entries'], ['neu'])

    def test_pending_entries_and_hard_invalidate_are_dropped(self):
        ui._cached('p', lambda: {'entries': [], 'pending': ['x']})
        ui._cached('k', lambda: {'entries': ['alt']})
        ui.invalidate(soft=True)
        self.assertNotIn('p', ui._CACHE);self.assertIn('k', ui._CACHE)
        ui.invalidate()
        self.assertEqual(ui._CACHE, {})

    def test_build_started_before_soft_invalidate_is_not_stored(self):
        def builder():
            ui.invalidate(soft=True);return {'entries': ['vorher']}
        ui._build_into('k', builder)
        self.assertNotIn('k', ui._CACHE)

    def test_series_film_mark_uses_soft_invalidate(self):
        svc = catalog_service.Service.__new__(catalog_service.Service)
        with mock.patch.object(svc, 'batched', return_value=(3, [])), \
             mock.patch.object(catalog_service.catalog, 'invalidate_listings'), \
             mock.patch.object(ui, 'invalidate') as inv:
            svc.mark_series_films(force=True)
        inv.assert_called_once_with(soft=True)


class ListingNoQueue(unittest.TestCase):
    """/api/catalog (catalog.listing) – die eigentliche Wartestelle im Befund."""

    def setUp(self):
        import contextlib
        import sqlite3
        self.c = sqlite3.connect(':memory:', check_same_thread=False);self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE works(id,title,year,kind)')
        self.c.executemany('INSERT INTO works VALUES(?,?,?,?)', [(str(i), 'T%d' % i, 2000, 'movie') for i in range(5)])

        @contextlib.contextmanager
        def factory():
            yield self.c
        for name, value in (('LISTING_DB', factory), ('LISTING_FILE', None)):
            p = mock.patch.object(catalog, name, value);p.start();self.addCleanup(p.stop)
        p = mock.patch.dict(catalog._LISTING, clear=True);p.start();self.addCleanup(p.stop)
        self.args = ("w.kind='movie'", (), 'w.id', 'w.title')

    def groups(self, search=False):
        return catalog._listing_groups(self.c, *self.args, search=search)

    def test_quick_outdated_list_answers_while_another_build_runs(self):
        self.assertEqual(len(self.groups()), 5)
        catalog.invalidate_listings()
        self.c.execute("INSERT INTO works VALUES('9','Neu',2024,'movie')")
        with catalog._LISTING_BUILD:          # Kinderecke/Index baut gerade
            started = time.monotonic()
            self.assertEqual(len(self.groups()), 5)          # alte Liste sofort
            self.assertLess(time.monotonic() - started, .5)
        for _ in range(100):
            if len(self.groups()) == 6:
                break
            time.sleep(.02)
        self.assertEqual(len(self.groups()), 6)              # im Hintergrund erneuert

    def test_quick_outdated_list_without_contention_is_rebuilt_at_once(self):
        self.groups();catalog.invalidate_listings()
        self.c.execute("INSERT INTO works VALUES('9','Neu',2024,'movie')")
        self.assertEqual(len(self.groups()), 6)

    def test_search_does_not_wait_for_the_build_lock(self):
        with catalog._LISTING_BUILD:
            started = time.monotonic()
            self.assertEqual(len(catalog._listing_groups(self.c, "w.kind='movie' AND w.title='T1'", (), 'w.id', 'w.title',
                                                         search=True)), 1)
            self.assertLess(time.monotonic() - started, .5)


if __name__ == '__main__':
    unittest.main()
