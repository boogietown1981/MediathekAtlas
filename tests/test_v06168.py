"""0.6.168 – Mac-Prüfung 0.6.167 (BEFUND-06167): kids_shows weiter 7,08 s, kids_slow_parts „shelf“ 4,2–11,2 s.
* Werk-Fakten: Livestream-/Ausschluss-Prüfung je Werk einmal (gleiches Ergebnis wie die alte Abfrage).
* Teilzeiten der Reihenprüfung (kids_shows_parts, langsamste Reihen) in kids_shelf_refreshed, auch wartende Aufbauten.
* Eine unfertige Liste (pending) wird im Hintergrund erneuert statt bei jedem Aufruf wartend neu gebaut.
* kids_undo_result: keine Gründe, wenn die Reihe wieder da ist."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog as kc  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


def old_query(c):
    """Abfrage aus 0.6.167 (Referenz)."""
    import catalog
    import categories
    import kids_rules
    kids, kids_args = catalog.category_clause(c, kc.CATEGORY)
    sig, sig_args = catalog.kids_signal_clause(c)
    labels = catalog.category_labels(c)
    bad = [r for name in categories.NOT_FOR_KIDS for r in labels.get(name) or []]
    bad_sql = ('EXISTS(SELECT 1 FROM work_genres b WHERE b.work_id=w.id AND b.genre IN (%s))' % ','.join('?' * len(bad))) if bad else '0'
    live, live_args = kids_rules.live_clause()
    chans = list(kids_rules.ALWAYS_CHANNELS)
    sender = ("(NOT %s AND EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 "
              "AND lower(trim(json_extract(k.payload,'$.channel'))) IN (%s)))" % (live, ','.join('?' * len(chans))))
    sql = ("SELECT w.id, (NOT %s AND ((%s) OR ((%s) AND NOT %s))) AS kids, (%s OR %s) AS bad, "
           "(SELECT group_concat(g.genre, char(31)) FROM work_genres g WHERE g.work_id=w.id) AS genres, %s AS sender, "
           "%s AS live FROM works w WHERE w.show_key=? ORDER BY w.rowid DESC LIMIT ?"
           % (live, kids, sig, bad_sql, live, bad_sql, sender, live))
    args = (list(live_args) + list(kids_args) + list(sig_args) + bad + list(live_args) + bad
            + list(live_args) + chans + list(live_args))
    return lambda show, limit: [(r[0], bool(r[1]), bool(r[2]), r[3], bool(r[4]), bool(r[5]))
                                for r in c.execute(sql, args + [show, limit])]


class FactsTests(Mixed):
    SHOWS = ('show:maus', 'show:kika', 'show:news', 'show:wumms', 'show:live')

    def fill(self):
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', ['Kinder'], 'Maus %d')])
        self.series('show:kika', 'Bluey', [(2, 'KiKA', [], 'Bluey %d')])
        self.series('show:news', 'Tagesschau', [(2, 'ARD', ['Nachrichten'], 'Nachrichten %d')])
        self.series('show:wumms', 'WUMMS', [(2, 'KiKA', ['Kinder'], 'KiKA %d'), (4, 'ARD', ['Krimi'], 'EM %d')])
        self.series('show:live', 'Livestream', [(2, 'KiKA', ['Kinder'], 'KiKA Livestream %d')])
        with self.db() as c:
            c.execute("UPDATE works SET meta=json_set(meta,'$.live',1) WHERE show_key='show:live'")

    def raw(self, c, query, show, limit):
        sql, args, _ = query
        return [(r[0], bool(r[1]), bool(r[2]), r[3], bool(r[4]), bool(r[5]))
                for r in c.execute(sql, [show, limit] + list(args))]

    def test_same_facts_as_before(self):
        self.fill()
        with self.db() as c:
            old, query = old_query(c), kc._work_query(c)
            for show in self.SHOWS:
                for limit in (-1, 2):
                    self.assertEqual(self.raw(c, query, show, limit), old(show, limit), (show, limit))
            self.assertTrue(any(r[5] for r in old('show:live', -1)))      # die Prüfung sieht wirklich Livestreams
            self.assertTrue(any(r[4] for r in old('show:kika', -1)))

    def test_without_materialized_keyword(self):
        self.fill()
        with self.db() as c, mock.patch.object(kc, '_MATERIALIZED', ''):
            old, query = old_query(c), kc._work_query(c)
            self.assertNotIn('MATERIALIZED', query[0])
            for show in self.SHOWS:
                self.assertEqual(self.raw(c, query, show, -1), old(show, -1))

    def test_parts_measured(self):
        self.fill()
        tiles = [{'id': 'mediatheken:' + s, 'source': 'mediatheken', 'title': s, 'series': {'show': s}} for s in self.SHOWS]
        timings = {}
        kc._kids_shows(self.db, tiles, timings)
        self.assertEqual(set(timings['kids_shows_parts']), {'query', 'facts', 'channels', 'basis', 'episodes'})
        self.assertEqual(timings['kids_shows_count'], 5)
        self.assertGreater(timings['kids_shows_works'], 0)
        self.assertLessEqual(len(timings['kids_shows_slowest']), 5)
        self.assertIsNone(kc._PARTS[0])


class PendingShelfTests(unittest.TestCase):
    def setUp(self):
        kc.invalidate()
        self.addCleanup(kc.invalidate)
        self.addCleanup(kc._BUILDING.clear)

    def test_pending_list_refreshes_in_background(self):
        hit = {'movies': [], 'series': [], 'pending': True}
        kc._CACHE['/r'] = (time.monotonic() - 30, hit)
        with mock.patch.object(kc, '_build_store') as wait, mock.patch.object(kc.threading, 'Thread') as thread:
            self.assertIs(kc.shelf('/r', None), hit)
            self.assertIs(kc.shelf('/r', None), hit)
        wait.assert_not_called()
        self.assertEqual(thread.call_count, 1)        # höchstens ein Aufbau gleichzeitig

    def test_without_list_waits(self):
        with mock.patch.object(kc, '_build_store', return_value={'x': 1}) as wait:
            self.assertEqual(kc.shelf('/r', None), {'x': 1})
        self.assertEqual(wait.call_args.kwargs.get('via'), 'wartend')

    def test_waiting_build_is_reported(self):
        value = {'movies': [], 'series': [], 'pending': False, 'timings': {'kids_shows': 3}}
        clock = iter([0.0, 3.0])
        with mock.patch.object(kc, 'build', return_value=value), \
                mock.patch.object(kc.time, 'monotonic', side_effect=lambda: next(clock, 10.0)), \
                mock.patch('diagnostics.event') as event:
            kc._build_store('/r', None, None, True, None, via='wartend')
        calls = [k for a, k in event.call_args_list if a[0] == 'kids_shelf_refreshed']
        self.assertEqual(calls[0]['via'], 'wartend')
        self.assertEqual(calls[0]['steps'], {'kids_shows': 3})


class UndoReasonTests(unittest.TestCase):
    def test_no_reasons_when_back(self):
        kc.UNDONE.clear()
        kc.UNDONE.add(('heidi', 'mediatheken:h'))
        value = {'series': [{'id': 'mediatheken:h', 'title': 'Heidi', 'source': 'mediatheken'}], 'movies': []}
        with mock.patch('diagnostics.event') as event:
            kc._report_undone(value)
        self.assertEqual(event.call_args.kwargs['reasons'], [])
        self.assertTrue(event.call_args.kwargs['back'])


if __name__ == '__main__':
    unittest.main()
