"""0.6.121 (Langzeitdiagnose Air 23.11.2026): N-D abgeschnittener Fassungshinweis im Suchtitel, N-F Protokoll voller
Bilder-Abgleich-Einträge."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artwork  # noqa: E402
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import metadata  # noqa: E402


class TruncatedNote(unittest.TestCase):
    def test_cut_version_notes_leave_the_search_title(self):
        for raw, want in (('Simone de Beauvoir (Originalversion', 'Simone de Beauvoir'),
                          ('Der Fall X (mit Untert', 'Der Fall X'), ('Ein Film (OmU', 'Ein Film'), ('Hörbuch (Hörf', 'Hörbuch')):
            self.assertEqual(metadata.query_title(raw), want, raw)

    def test_other_brackets_stay(self):
        for raw in ('Kinder (Adoption', 'Bauer (Hof) sucht', 'Die Oper (Ouvertüre'):
            self.assertEqual(metadata.query_title(raw), raw, raw)

    def test_work_identity_is_unchanged(self):
        self.assertEqual(catalog.cleaned('Simone de Beauvoir (Originalversion'), 'Simone de Beauvoir (Originalversion')

    def test_open_works_requeued_once(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        @contextmanager
        def db():
            c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        with db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [{'title': t, 'topic': 'Dokumentation', 'description': 'x', 'duration': 3000, 'channel': 'ARTE',
                                'url_video': 'https://example.org/%d.mp4' % i}
                               for i, t in enumerate(('Simone de Beauvoir (Originalversion', 'Ein ganz normaler Film'))])
            c.execute("UPDATE works SET state='review',attempts=5,next_try=9e9")
        svc = catalog_service.Service(db, lambda: {}, threading.Event(), root)
        self.assertEqual(svc.requeue_truncated_notes(), 1)
        self.assertEqual(svc.requeue_truncated_notes(), 0)
        with db() as c:
            states = {r['title']: (r['state'], r['attempts']) for r in c.execute('SELECT title,state,attempts FROM works')}
        self.assertEqual(states['Simone de Beauvoir (Originalversion'], ('pending', 0))
        self.assertEqual(states['Ein ganz normaler Film'], ('review', 5))


class ArtworkLog(unittest.TestCase):
    def setUp(self):
        artwork._LOGGED.clear();artwork._SUCCESSES[0] = 0

    def test_failing_title_once_a_day(self):
        self.assertTrue(artwork.log_due('Usedom-Krimi', ['HTTP 404']))
        self.assertFalse(artwork.log_due('Usedom-Krimi', ['HTTP 404']))
        self.assertTrue(artwork.log_due('Zürich-Krimi', ['HTTP 404']))

    def test_successes_sampled(self):
        logged = sum(artwork.log_due('T%d' % i, []) for i in range(100))
        self.assertEqual(logged, 100 // artwork.LOG_EVERY)


if __name__ == '__main__':
    unittest.main()
