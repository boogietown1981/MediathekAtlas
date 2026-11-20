"""0.6.67 (Code-Review 0.6.59, Schritt 1 „Episoden-Einordnung absichern“, Befunde A1/A2/B1).

* Zähler und Protokolleinträge erst nach dem Speichern: eine zurückgerollte Runde („database is locked“)
  hinterlässt keine Spur, die Wiederholung zählt genau einmal.
* Eine Sendung wird gleichzeitig nur von einem Worker eingeordnet; der andere lässt die Geschwister liegen.
* Sperren werden je Stelle gezählt und angezeigt.
"""
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import catalog, imdb_archive  # noqa: E402
from test_v0658 import Fixture, NO_EPISODES  # noqa: E402


class AfterCommit(Fixture):
    def test_rolled_back_round_leaves_no_counts_and_retry_counts_once(self):
        real = catalog.mark_recurring_edition
        calls = {'n': 0}

        def locked_once(*a, **k):
            calls['n'] += 1
            if calls['n'] == 3:                   # inside the first claim's sibling filing
                raise sqlite3.OperationalError('database is locked')
            return real(*a, **k)
        with patch.object(catalog, 'mark_recurring_edition', locked_once):
            self.run_queue()
        self.assertEqual(self.states(), ['format'] * 12)
        self.assertEqual(self.svc.episode_segments, 12)          # not 12 + the rolled-back round
        self.assertEqual(sum(e['segments'] + e['editions'] for e in self.classified()), 11)
        self.assertEqual(self.svc.sqlite_busy_by_label, {'episode': 1})
        self.assertEqual(self.svc.scan_progress()['sqlite_busy_by_label'], {'episode': 1})

    def test_effects_run_only_after_the_unit(self):
        seen = []

        def unit():
            self.svc.after_commit(lambda: seen.append('counted'))
            self.assertEqual(seen, [])
            return 'done'
        self.assertEqual(self.svc.write(unit), 'done')
        self.assertEqual(seen, ['counted'])
        self.svc.after_commit(lambda: seen.append('outside'))   # outside a unit: at once
        self.assertEqual(seen, ['counted', 'outside'])

    def test_failed_unit_drops_its_effects(self):
        seen = []

        def unit():
            self.svc.after_commit(lambda: seen.append('x'))
            raise ValueError('kaputt')
        with self.assertRaises(ValueError):
            self.svc.write(unit)
        self.assertEqual(seen, [])
        self.svc.write(lambda: None)
        self.assertEqual(seen, [])


class OneWorkerPerShow(Fixture):
    def test_show_lock_is_exclusive_within_units(self):
        inside, release, results = threading.Event(), threading.Event(), []

        def holder():
            def unit():
                results.append(('a', self.svc.show_lock('SHOW')))
                inside.set()
                release.wait(5)
            self.svc.write(unit)
        t = threading.Thread(target=holder)
        t.start()
        inside.wait(5)
        self.svc.write(lambda: results.append(('b', self.svc.show_lock('SHOW'))))
        release.set()
        t.join(5)
        self.svc.write(lambda: results.append(('c', self.svc.show_lock('SHOW'))))   # released after the unit
        self.assertEqual(results, [('a', True), ('b', False), ('c', True)])
        self.assertEqual(self.svc.episode_show_skipped, 1)

    def test_four_workers_file_each_contribution_once(self):
        with patch.object(imdb_archive, 'ACTIVE', NO_EPISODES):
            def work():
                for _ in range(30):
                    if not self.svc.metadata_once('episode'):
                        break
            threads = [threading.Thread(target=work) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(self.states(), ['format'] * 12)
        self.assertEqual(self.svc.episode_segments, 12)
        self.assertEqual(self.queued(), 0)

    def test_page_shows_lock_places(self):
        js = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('c.sqlite_busy_by_label', js)
        self.assertIn('Sendung gerade bei anderem Worker', js)


if __name__ == '__main__':
    unittest.main()
