"""0.6.125 (Mac-Prüfung 0.6.123, 23.11.2026): die Heilung film_seed_v06123 stufte 489 Werke um, 244 ab 80 min ohne
Datum (Löwenzahn-Filme, Bullerbü, „It Follows (Englisch)“, „Der Amsterdam-Krimi (2)“, „Wo ist Anne Frank – Teil 1/2“)."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
from test_v06123 import row  # noqa: E402


def database(root):
    @contextmanager
    def db():
        c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    return db


class Shape(unittest.TestCase):
    def test_feature_length_numbered_films_stay(self):
        for title, minutes in (('Der Amsterdam-Krimi (2)', 86), ('Wo ist Anne Frank – Die Hintergründe, Teil 1', 90),
                               ('Mammon: Opfer (1/3)', 111)):
            r = row(title, 'Spielfilm', minutes * 60, 'Spielfilm, Deutschland 2020', 'ARD')
            self.assertTrue(catalog.film_shaped(r, title, r['topic'], r['description']), title)
            self.assertEqual(catalog.seed(r)['kind'], 'movie', title)

    def test_dated_and_short_numbered_stay_no_film(self):
        for title, minutes in (('10 vor 10 vom 02.06.2022', 95), ('11er Haus (4/5): Funkschatten', 45), ('Clip Teil 2', 10)):
            r = row(title, 'x', minutes * 60)
            self.assertFalse(catalog.film_shaped(r, title, 'x', r['description']), title)


class Heal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.db = database(self.root)
        rows = [row('It Follows (Englisch)', 'Filme', 96 * 60, 'Ein Horror um eine junge Frau.', 'ARTE'),
                row('Löwenzahn – Das blaue Juwel', 'Löwenzahn', 85 * 60, 'Spielfilm mit Fritz Fuchs', 'KiKA'),
                row('10 vor 10 vom 02.06.2022', '10 vor 10', 1500)]
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), self.root)

    def state(self):
        with self.db() as c:
            return {r['title']: (r['kind'], r['state']) for r in c.execute('SELECT title,kind,state FROM works')}

    def test_only_film_shaped_rejects_are_reseeded(self):
        with self.db() as c:
            for w in c.execute('SELECT id,meta FROM works').fetchall():   # recognition made them films („prüfen“)
                m = json.loads(w['meta']);m['kind'] = 'movie'
                c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.assertEqual(self.svc.reseed_non_films(), 1)
        st = self.state()
        self.assertEqual(st['It Follows (Englisch)'][0], 'movie')
        self.assertEqual(st['10 vor 10 vom 02.06.2022'], ('unknown', 'pending'))

    def test_0_6_123_reseed_is_undone_on_copies(self):
        with self.db() as c:
            catalog.set_state(c, 'film_seed_v06123', {'works': 2})
            for w in c.execute('SELECT id,meta,title FROM works').fetchall():   # as 0.6.123 left them
                m = json.loads(w['meta']);m.update(kind='unknown', reason=catalog.NON_FILM_REASON)
                c.execute("UPDATE works SET kind='unknown',state='pending',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.svc.reseed_non_films()
        st = self.state()
        self.assertEqual(st['It Follows (Englisch)'], ('movie', 'pending'))
        self.assertEqual(st['Löwenzahn – Das blaue Juwel'], ('movie', 'pending'))
        self.assertEqual(st['10 vor 10 vom 02.06.2022'][0], 'unknown')
        with self.db() as c:
            self.assertTrue(catalog.get_state(c, 'film_seed_v06125', False))
        self.assertIsNone(self.svc.reseed_non_films())   # once


if __name__ == '__main__':
    unittest.main()
