"""0.6.123 (Björn 23.11.2026, Bildschirmfoto „Filme > Unbekannt 2008“): Sendungsausgaben, nummerierte Teile und
Kurzbeiträge als Film."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402
import catalog_service  # noqa: E402


def row(title, topic, duration, desc='Spielfilm-Tipp der Woche', channel='SRF'):
    return {'title': title, 'topic': topic, 'duration': duration, 'description': desc, 'channel': channel,
            'url_video': 'https://example.org/%s.mp4' % abs(hash(title))}


class Seed(unittest.TestCase):
    def test_no_film(self):
        for r in (row('10 vor 10 vom 02.06.2022', '10 vor 10', 1500), row('18.00 Uhr (22.01.2019)', '18.00 Uhr', 960),
                  row('67. Nordische Filmtage starten in Lübeck', 'Kultur', 240, '170 Spielfilme', 'NDR'),
                  row('125 Jahre Truppenübungsplatz Münsingen', 'SWR Aktuell', 180, 'Dokumentarfilm-Ausschnitt', 'SWR'),
                  row('11er Haus (4/5): 1991 - 1995: Funkschatten', '11er Haus', 2700, 'Fernsehfilm', 'BR')):
            self.assertNotEqual(catalog.seed(r)['kind'], 'movie', r['title'])

    def test_films_stay(self):
        for r in (row('Der Pate', 'Spielfilm', 9000, 'Spielfilm, USA 1972', 'ARD'), row('8 Mile - Spielfilm, USA 2002', 'Spielfilm', 6000, '', '3sat'),
                  row('Kleine Welt', 'Kurzfilm', 900, 'Kurzfilm über Freundschaft. Spielfilm', 'ARTE'),
                  row('Ein Abend im Mai', 'Fernsehfilm', 5400, 'Fernsehfilm, Deutschland 2020', 'ZDF')):
            self.assertEqual(catalog.seed(r)['kind'], 'movie', r['title'])


class Heal(unittest.TestCase):
    def test_open_non_films_reseeded_once_matches_kept(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        @contextmanager
        def db():
            c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        rows = [row('10 vor 10 vom 02.06.2022', '10 vor 10', 1500), row('10 vor 10 vom 03.06.2022', '10 vor 10', 1500),
                row('Der Pate', 'Spielfilm', 9000, 'Spielfilm, USA 1972', 'ARD')]
        with db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            for w in c.execute('SELECT id,meta FROM works').fetchall():   # as 0.6.122 left them: films „prüfen“
                m = json.loads(w['meta']);m['kind'] = 'movie'
                c.execute("UPDATE works SET kind='movie',state='review',attempts=3,meta=? WHERE id=?", (json.dumps(m), w['id']))
            c.execute("UPDATE works SET state='matched' WHERE title='10 vor 10 vom 03.06.2022'")
        svc = catalog_service.Service(db, lambda: {}, threading.Event(), root)
        self.assertEqual(svc.reseed_non_films(), 1)
        self.assertIsNone(svc.reseed_non_films())
        with db() as c:
            st = {r['title']: (r['kind'], r['state']) for r in c.execute('SELECT title,kind,state FROM works')}
        self.assertEqual(st['10 vor 10 vom 02.06.2022'], ('unknown', 'pending'))
        self.assertEqual(st['10 vor 10 vom 03.06.2022'], ('movie', 'matched'))
        self.assertEqual(st['Der Pate'], ('movie', 'review'))


if __name__ == '__main__':
    unittest.main()


class SettingsWriteWaitsTests(unittest.TestCase):
    """0.6.123 (Mac-Prüfung 0.6.120): saving settings during the start heals answered „database is locked“."""

    def test_write_waits_for_busy_database(self):
        import sqlite3
        import server
        calls = []

        def fn(c):
            calls.append(1)
            if len(calls) < 3:
                raise sqlite3.OperationalError('database is locked')
            return 'ok'

        class FakeDb:
            def __call__(self):
                return self
            def __enter__(self):
                return None
            def __exit__(self, *a):
                return False
        old = server.db
        server.db = FakeDb()
        try:
            self.assertEqual(server.write_waiting(fn, wait=0), 'ok')
            self.assertEqual(len(calls), 3)
            calls.clear()
            with self.assertRaises(sqlite3.OperationalError):
                server.write_waiting(lambda c: calls.append(1) or (_ for _ in ()).throw(sqlite3.OperationalError('database is locked')), tries=2, wait=0)
            self.assertEqual(len(calls), 2)
            with self.assertRaises(sqlite3.OperationalError):   # other errors are not retried
                server.write_waiting(lambda c: (_ for _ in ()).throw(sqlite3.OperationalError('no such table: x')), wait=0)
        finally:
            server.db = old

    def test_settings_endpoints_use_waiting_write(self):
        from pathlib import Path
        s = (Path(__file__).resolve().parent.parent / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn('with db() as c:store_settings(c,s)', s)
        self.assertIn('write_waiting(write)', s)
