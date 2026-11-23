"""0.6.123 (Björn 23.11.2026, Bildschirmfoto „Filme > Unbekannt 2008“): Sendungsausgaben, nummerierte Teile und
Kurzbeiträge als Film."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
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
    """0.6.123/0.6.125 (Mac-Prüfungen 0.6.120/0.6.123): saving settings during the start heals answered „database is
    locked“ (later 134 s). Now: short try, else kept in memory and written in the background."""

    def test_busy_write_is_deferred_and_visible_at_once(self):
        import sqlite3
        import server
        locked = threading.Event();locked.set()
        written = []

        @contextmanager
        def fake_db(timeout=30):
            if locked.is_set():
                raise sqlite3.OperationalError('database is locked')
            yield 'conn'

        old_db, old_quick = server.db, server.SETTINGS_QUICK_TIMEOUT
        server.db = fake_db
        try:
            payload = json.dumps({'series_autoload': {'enabled': True}, 'marker': 'v06125'})
            started = time.monotonic()
            self.assertFalse(server.write_waiting(lambda c: written.append(1), payload))
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(json.loads(server._settings_payload())['marker'], 'v06125')
            # a second change while the first waits is queued behind it, never written before it
            self.assertFalse(server.write_waiting(lambda c: written.append(2), json.dumps({'marker': 'second'})))
            self.assertEqual(json.loads(server._settings_payload())['marker'], 'second')
            locked.clear()
            deadline = time.monotonic() + 10
            while server._SETTINGS_DEFERRED and time.monotonic() < deadline:
                time.sleep(.1)
            self.assertEqual(written, [1, 2])
            self.assertEqual(json.loads(server._settings_payload())['marker'], 'second')
            self.assertTrue(server.write_waiting(lambda c: written.append(3)))   # free database: written at once
            self.assertEqual(written, [1, 2, 3])
            with self.assertRaises(sqlite3.OperationalError):   # other errors are not deferred
                server.write_waiting(lambda c: (_ for _ in ()).throw(sqlite3.OperationalError('no such table: x')))
        finally:
            server.db, server.SETTINGS_QUICK_TIMEOUT = old_db, old_quick
            server.invalidate_settings()

    def test_settings_endpoints_use_waiting_write(self):
        from pathlib import Path
        s = (Path(__file__).resolve().parent.parent / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn('with db() as c:store_settings(c,s)', s)
        self.assertIn('write_waiting(write,json.dumps(s))', s)
