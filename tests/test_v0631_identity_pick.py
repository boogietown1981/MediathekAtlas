"""0.6.31: Hauptworker standen auf Björns Mac (Datenbank auf USB-Laufwerk) bei „0 / 4 aktiv“ und
„Wird gestartet · 0 Abgleiche seit Start“. Ursache: Die Auswahl der nächsten Prüfung (Service.pick)
las für Zustand „identified“ alle ~220.000 Serien der Folgen-Warteschlange Zeile für Zeile, ebenso
die Prioritätenabfrage. Jetzt Teilindex work_identity_recheck und CROSS JOIN von metadata_priority."""
import json
import sqlite3
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog, catalog_service as cs  # noqa: E402

QUEUED = json.dumps({'reference_id': 'tt1', 'provider': 'TMDB'})


class PickTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        catalog.initialize(self.c)
        self.now = time.time()
        self.svc = types.SimpleNamespace(settings=lambda: {}, turn=0, mesh_filter=None)

    def add(self, wid, kind, state, meta='{}', next_try=0, attempts=1):
        self.c.execute('INSERT INTO works(id,title,kind,show_key,meta,state,next_try,attempts,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (wid, wid, kind, wid, meta, state, next_try, attempts, self.now))
        self.c.execute('INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)',
                       ('o' + wid, wid, '{}', '', 0, self.now))

    def steps(self):
        n = [0]

        def tick():
            n[0] += 1
            return 0
        self.c.set_progress_handler(tick, 100)
        row = cs.Service.pick(self.svc, self.c)
        self.c.set_progress_handler(None, 0)
        return row, n[0]

    def test_queued_series_are_not_walked(self):
        for i in range(3000):
            self.add('q%05d' % i, 'series', 'identified', QUEUED)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 3000)
        row, steps = self.steps()
        self.assertIsNone(row)
        self.assertLess(steps, 50)            # before 0.6.31: thousands of steps (all 3,000 rows read)
        self.add('free', 'series', 'identified', '{}', next_try=self.now - 10)
        row, _ = self.steps()
        self.assertEqual(row['id'], 'free')    # identified outside the queue is still re-checked

    def test_index_matches_queue_rule(self):
        self.add('a', 'series', 'identified', QUEUED)
        self.add('b', 'series', 'identified', json.dumps({'reference_id': 'tt2', 'episode_verified': 1}))
        self.add('c', 'movie', 'identified', QUEUED)
        queued = {r[0] for r in self.c.execute('SELECT work_id FROM episode_queue')}
        rechecks = {r[0] for r in self.c.execute('SELECT w.id FROM works w INDEXED BY work_identity_recheck WHERE w.kind IN (\'series\',\'movie\') AND ' + catalog.IDENTITY_RECHECK)}
        self.assertEqual(queued, {'a'})
        self.assertEqual(rechecks, {'b', 'c'})

    def test_priority_lookup_starts_from_priority_table(self):
        for i in range(2000):
            self.add('q%05d' % i, 'series', 'identified', QUEUED)
        self.add('p', 'movie', 'pending', attempts=0)
        self.c.execute('INSERT INTO metadata_priority VALUES(?,?)', ('p', self.now))
        row, steps = self.steps()
        self.assertEqual(row['id'], 'p')
        self.assertLess(steps, 50)


if __name__ == '__main__':
    unittest.main()
