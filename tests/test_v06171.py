"""0.6.171 – Mac-Prüfung 0.6.169 (BEFUND-06169): nach dem Start nur die vorläufige Kinderliste (14 Serien), die volle
entstand erst nach einem Besuch; seit 0.6.168 bekam der erste Besucher die vorläufige Liste. Jetzt erneuert sich eine
unfertige Liste von selbst im Hintergrund, bis sie fertig ist."""
import threading
import time
import unittest
from unittest import mock

import kids_catalog as kc


class FollowUpTests(unittest.TestCase):
    def setUp(self):
        kc.invalidate()
        kc._FOLLOW.clear()
        kc._BUILDING.clear()
        self.addCleanup(kc.invalidate)
        self.addCleanup(kc._FOLLOW.clear)
        self.addCleanup(kc._BUILDING.clear)
        self.done = threading.Event()
        self.results = [True, True, False]      # zweimal unfertig, dann fertig

        def build(*a, **k):
            pending = self.results.pop(0) if self.results else False
            if not pending:
                self.done.set()
            return {'movies': [], 'series': [{'id': 'x'}] * (14 if pending else 552), 'pending': pending, 'timings': {}}
        self.build = build

    def test_pending_list_completes_without_visitor(self):
        with mock.patch.object(kc, 'build', side_effect=self.build), mock.patch.object(kc, 'PENDING_RETRY', 0.01):
            first = kc.shelf('/r', None)                 # wie der Vorabbau nach dem Start
            self.assertTrue(first['pending'])
            self.assertTrue(self.done.wait(5), 'volle Liste entsteht ohne weiteren Aufruf')
            for _ in range(100):
                if not kc._BUILDING:
                    break
                time.sleep(0.01)
            hit = kc._CACHE['/r'][1]
        self.assertFalse(hit['pending'])
        self.assertEqual(len(hit['series']), 552)
        self.assertNotIn('/r', kc._FOLLOW)

    def test_follow_up_stops_after_limit(self):
        kc._FOLLOW['/r'] = time.monotonic() - kc.PENDING_FOLLOW - 1
        with mock.patch.object(kc.threading, 'Timer') as timer:
            self.assertFalse(kc._follow_up('/r', None, None, True, None))
        timer.assert_not_called()

    def test_only_one_follow_up_at_a_time(self):
        with mock.patch.object(kc.threading, 'Timer') as timer:
            self.assertTrue(kc._follow_up('/r', None, None, True, None))
            self.assertFalse(kc._follow_up('/r', None, None, True, None))
        self.assertEqual(timer.call_count, 1)


if __name__ == '__main__':
    unittest.main()
