"""0.6.35: 0.6.34 startete auf Björns Mac nicht („Python reagiert nicht“). Ursache: der neue
Teilindex work_identity_recheck stand im Schema und wurde beim Start vor dem Webserver angelegt –
ein voller Durchlauf durch catalog.db (5,5 GB auf USB-Laufwerk). Jetzt entsteht er nach dem Start
im Hintergrund; bis dahin lässt die Auswahl nur die Nachprüfungen „identified“ aus."""
import json
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog, catalog_service as cs  # noqa: E402


class DeferredIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'catalog.db'
        self.now = time.time()
        self.svc = types.SimpleNamespace(settings=lambda: {}, turn=0, mesh_filter=None)
        with self.db() as c:
            catalog.initialize(c, defer_heavy=True)
        catalog.MAINTENANCE.clear(); catalog.MAINTENANCE['phase'] = 'idle'

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5); c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add(self, c, wid, kind, state, meta='{}', attempts=1):
        c.execute('INSERT INTO works(id,title,kind,show_key,meta,state,next_try,attempts,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                  (wid, wid, kind, wid, meta, state, 0, attempts, self.now))
        c.execute('INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)',
                  ('o' + wid, wid, '{}', '', 0, self.now))

    def test_schema_and_deferred_start_leave_index_out(self):
        self.assertNotIn('INDEX IF NOT EXISTS work_identity_recheck', catalog.SCHEMA)
        with self.db() as c:
            self.assertFalse(catalog.index_ready(c))

    def test_pick_works_without_index_and_skips_only_rechecks(self):
        with self.db() as c:
            self.add(c, 'recheck', 'movie', 'identified')
            self.assertIsNone(cs.Service.pick(self.svc, c))          # no "no such index" error
            self.add(c, 'new', 'movie', 'pending', attempts=0)
            self.assertEqual(cs.Service.pick(self.svc, c)['id'], 'new')

    def test_background_build_creates_index_once(self):
        with self.db() as c:
            self.add(c, 'recheck', 'movie', 'identified')
        events = []
        self.assertTrue(catalog.build_deferred_indexes(self.db, lambda name, **kw: events.append(name)))
        self.assertEqual(catalog.MAINTENANCE['phase'], 'done')
        self.assertEqual(events, ['catalog_index_build_started', 'catalog_index_build_finished'])
        with self.db() as c:
            self.assertTrue(catalog.index_ready(c))
            self.assertEqual(cs.Service.pick(self.svc, c)['id'], 'recheck')
        events.clear()
        self.assertTrue(catalog.build_deferred_indexes(self.db, lambda name, **kw: events.append(name)))
        self.assertEqual(events, [])                                  # second start: nothing to do

    def test_failed_build_is_reported_not_raised(self):
        with self.db() as c:
            c.execute("DROP TRIGGER IF EXISTS episode_queue_work_insert")
            self.add(c, 'broken', 'series', 'identified', meta='kein json')
        errors = []
        self.assertFalse(catalog.build_deferred_indexes(self.db, None, lambda name, e, **kw: errors.append(name)))
        self.assertEqual(catalog.MAINTENANCE['phase'], 'failed')
        self.assertTrue(catalog.MAINTENANCE['text'])
        self.assertEqual(errors, ['catalog_index_build_failed'])

    def test_initialize_default_still_builds_index(self):
        c = sqlite3.connect(':memory:')
        catalog.initialize(c)
        self.assertTrue(catalog.index_ready(c))


class WiringTests(unittest.TestCase):
    def test_server_defers_index_and_reports_start_steps(self):
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("catalog.initialize(c,defer_heavy=__name__=='__main__')", src)
        self.assertIn('file=sys.stderr', src)                         # stdout line 1 stays the URL
        build = src.index('catalog.build_deferred_indexes(db,diagnostics.event,diagnostics.error)\n            if not STOP.is_set():SERVICE.start()')
        self.assertGreater(build, src.index('server=') if 'server=' in src else 0)
        self.assertIn("'maintenance':dict(catalog.MAINTENANCE)", src)
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("d.maintenance", app)


if __name__ == '__main__':
    unittest.main()
