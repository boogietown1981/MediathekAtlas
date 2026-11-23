"""0.6.116 (Vorbereitung auf 0.6.114): Mac-Prüfung 0.6.114 – 128 von 900 „Extra zu …“ waren ganze Sendungen
(„Brombeerland (9/14) – Die Pressekonferenz“ 39 min, „Wetter extrem (1/3)“ 30 min, Terra Xpress XXL 44 min). Ganze
Sendungen (≥ 25 min oder nummeriert ab 10 min) sind weder Extra noch Clip: sie werden erkannt; Heilung einmalig."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import diagnostics  # noqa: E402
from tests.test_v0683 import Worker  # noqa: E402
from tests.test_v06113 import src, wid_of  # noqa: E402


class FullProgramme(Worker):
    def setUp(self):
        super().setUp()
        rows = [src('Brombeerland', 'Brombeerland', 1, 2700, 'ARD'),
                src('Brombeerland (9/14) – Die Pressekonferenz', 'Brombeerland', 2, 2340, 'ARD'),
                src('Extra: Interview mit der Hauptdarstellerin', 'Brombeerland', 3, 300, 'ARD'),
                src('Wetter extrem (1/3)', 'Wetter extrem', 4, 1800, 'ZDF'),
                src('Trailer: Brombeerland', 'Brombeerland', 5, 120, 'ARD'),
                src('Podcast mit Nachklang (4316)', 'Brombeerland', 6, 2956, 'ARD'),
                src('u.a. Pressekonferenz von Angela Merkel', 'phoenix der tag', 7, 1857, 'PHOENIX')]
        with self.db() as c:
            catalog.ingest(c, rows)
            c.execute("UPDATE works SET kind='series',state='matched',meta=json_set(meta,'$.provider','TMDB') WHERE id=?", (wid_of(c, 1),))
            for n in (2, 3, 4, 5, 6, 7):
                c.execute("UPDATE works SET kind='other',state='pending',attempts=0 WHERE id=?", (wid_of(c, n),))

    def state(self, c, n):
        r = c.execute('SELECT kind,state,meta FROM works WHERE id=?', (wid_of(c, n),)).fetchone()
        return r['kind'], r['state'], json.loads(r['meta']).get('reason', '')

    def test_format_pass(self):
        with self.db() as c:
            catalog.set_state(c, 'format_rev', 5)
            while catalog.assign_formats(c)[0]:pass
            self.assertEqual(self.state(c, 2)[:2], ('unknown', 'pending'))          # whole episode: recognised
            self.assertEqual(self.state(c, 4)[:2], ('unknown', 'pending'))
            self.assertTrue(self.state(c, 3)[2].startswith('Extra zu „Brombeerland“'))   # short interview: extra
            self.assertEqual(self.state(c, 5)[:2], ('other', 'format'))            # trailer stays a trailer
            self.assertEqual(self.state(c, 6)[:2], ('other', 'format'))            # podcast never a Folge
            self.assertEqual(self.state(c, 7)[:2], ('other', 'format'))            # press conference stays a clip

    def test_heal_of_0_6_114_filings(self):
        with self.db() as c:
            for n, how in ((2, "json_set(meta,'$.reason','Extra zu „Brombeerland“ (Interview, Ausschnitt, Trailer); x')"),
                           (4, "json_set(meta,'$.format_grouping','clip')"),
                           (3, "json_set(meta,'$.reason','Extra zu „Brombeerland“ (Interview, Ausschnitt, Trailer); x')")):
                c.execute("UPDATE works SET state='format',meta=%s WHERE id=?" % how, (wid_of(c, n),))
        events = []
        with patch.object(diagnostics, 'event', lambda name, *a, **f: events.append((name, f))):
            self.assertEqual(self.svc.reopen_full_programmes(), 2)
            self.assertIsNone(self.svc.reopen_full_programmes())
        with self.db() as c:
            self.assertEqual(self.state(c, 2)[:2], ('unknown', 'pending'))
            self.assertEqual(self.state(c, 4)[:2], ('unknown', 'pending'))
            self.assertEqual(self.state(c, 3)[:2], ('other', 'format'))
            row = c.execute('SELECT w.* FROM works w WHERE id=?', (wid_of(c, 2),)).fetchone()
            self.assertEqual(self.svc.pick(c)['kind'], 'unknown')                # the worker takes it
        self.assertEqual([f['works'] for n, f in events if n == 'catalog_full_programmes_reopened'], [2])


if __name__ == '__main__':
    unittest.main()
