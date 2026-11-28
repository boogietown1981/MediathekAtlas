"""0.6.167 – Mac-Prüfung 0.6.165/0.6.166: Reihenprüfung der Kinderecke (kids_shows) 6,7 s von 13,7 s Aufbau.
* Reihen mit Kinder-Thema einmal je Aufbau lesen statt je Reihe eine Abfrage mit bis zu 5.000 Themen.
* Werk-Fakten einer Reihe einmal je Aufbau (show_basis-Stichprobe und _has_episode nutzen dieselben).
* kids_undo_result prüft nach Kachel-Schlüssel (der gleichnamige Netzkino-Film zählt nicht).
* Heidi (HEIDI-EINGRENZUNG-06166: Suche zeigte Heidi, die sortierte Kinder-Serienliste nicht): eine Listen-Aggregation,
  die während der Sperre begann, speicherte ihr Ergebnis nach dem Zurücknehmen als frisch (bis zu 10 min, bzw. ein
  Wartender bekam das alte Ergebnis). Jetzt werden Ergebnisse von vor einer Änderung verworfen."""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import catalog  # noqa: E402
import kids_catalog as kc  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


class MemoTests(Mixed):
    def test_same_result_with_and_without_memo(self):
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', ['Kinder'], 'Maus %d')])
        self.series('show:kika', 'Bluey', [(2, 'KiKA', [], 'Bluey %d')])
        self.series('show:news', 'Tagesschau', [(2, 'ARD', [], 'Nachrichten %d')])
        with self.db() as c:
            plain = {s: (kc.show_basis(c, s), kc._work_facts(c, s)) for s in ('show:maus', 'show:kika', 'show:news')}
            query = kc._work_query(c)
            memo = {s: (kc.show_basis(c, s, query=query), kc._work_facts(c, s, None, query)) for s in plain}
            self.assertEqual(plain, memo)
            self.assertEqual(kc._work_facts(c, 'show:maus', 2, query), plain['show:maus'][1][:2])
            for s in plain:
                self.assertEqual(kc._curated_topic(c, s), kc._curated_topic(c, s, query[2]))

    def test_curated_topics_read_once_per_build(self):
        self.series('show:a', 'A', [(1, 'ARD', [], 'A %d')])
        with self.db() as c, mock.patch('catalog.kids_topics', return_value=['Die Sendung mit der Maus'] * 3000):
            memo, calls = {}, []
            real = c.execute
            proxy = mock.MagicMock(wraps=c)
            proxy.execute.side_effect = lambda *a: calls.append(a[0]) or real(*a)
            for _ in range(5):
                kc._curated_topic(proxy, 'show:a', memo)
        self.assertEqual(len(calls), 1)


class StaleListingTests(unittest.TestCase):
    KEY = ('w.kind=?', ('series',), 'g', 'o')

    def setUp(self):
        catalog.invalidate_listings(drop=True)
        self.addCleanup(catalog.invalidate_listings, True)
        self.release, self.started, self.calls = threading.Event(), threading.Event(), []
        orig_db, orig_build = catalog.LISTING_DB, catalog._listing_build

        def build(c, where, args, grouping, order):
            self.calls.append(len(self.calls))
            if len(self.calls) == 1:              # erste Aggregation: Stand „gesperrt“, langsam
                self.started.set()
                self.release.wait(5)
                return [('alt', 1, 'Maus', 2020)], 0.1
            return [('alt', 1, 'Maus', 2020), ('heidi', 2, 'Heidi', 2015)], 0.1
        catalog.LISTING_DB = lambda: _Null()
        catalog._listing_build = build
        self.addCleanup(setattr, catalog, 'LISTING_DB', orig_db)
        self.addCleanup(setattr, catalog, '_listing_build', orig_build)

    def test_refresh_begun_before_change_is_not_stored(self):
        t = threading.Thread(target=catalog._listing_refresh, args=(self.KEY, *self.KEY[:1], list(self.KEY[1]), 'g', 'o'))
        t.start()
        self.started.wait(5)
        catalog.invalidate_listings(drop=True)        # Zurücknehmen
        self.release.set()
        t.join(5)
        self.assertNotIn(self.KEY, catalog._LISTING)
        rows = catalog._listing_groups(None, *self.KEY[:1], list(self.KEY[1]), 'g', 'o', wait=True)
        self.assertIn('heidi', [r[0] for r in rows])

    def test_waiting_caller_gets_new_build_after_change(self):
        with self.assertRaises(catalog.ListingPending):
            catalog._listing_groups(None, *self.KEY[:1], list(self.KEY[1]), 'g', 'o', wait=False)
        self.started.wait(5)
        catalog.invalidate_listings(drop=True)
        self.release.set()
        rows = None
        for _ in range(50):
            try:
                rows = catalog._listing_groups(None, *self.KEY[:1], list(self.KEY[1]), 'g', 'o', wait=False)
                break
            except catalog.ListingPending:
                threading.Event().wait(0.1)
        self.assertIn('heidi', [r[0] for r in rows or []])


class _Null:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


if __name__ == '__main__':
    unittest.main()
