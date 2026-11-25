"""0.6.132 (Diagnose Air 0.6.131, 25.11.2026): Rücknahme holte Krimireihen-Folgen (Brokenwood 7/20) als Filme zurück,
3sat-Filme mit einem Kandidaten blieben „prüfen“, Genre-Nachtrag aus der Reihe schaukelte sich auf („Rudis Rasselbande“
als Nachrichten), freier Speicher ohne löschbaren APFS-Platz."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import matching  # noqa: E402
import metadata  # noqa: E402
import system_monitor  # noqa: E402
from test_v06123 import row  # noqa: E402
from test_v06127 import offer  # noqa: E402


def database(root):
    @contextmanager
    def db():
        c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    return db


class SeriesParts(unittest.TestCase):
    def test_numbered_series_parts_are_no_films(self):
        for title in ('Brokenwood – Mord in Neuseeland (7/20): Tod im Weinberg', 'Rebecka Martinsson (02/08)',
                      'Sophie Cross (1/3)', 'Inspector Mathias – Mord in Wales (3/9)', 'Mammon: Opfer (1/3)'):
            r = row(title, 'Krimi', 88 * 60, 'Krimiserie', 'ZDF')
            self.assertFalse(catalog.film_shaped(r, title, r['topic'], r['description']), title)

    def test_two_parters_and_single_films_stay(self):
        for title in ('Mordkommission Istanbul (1/2)', 'Der Amsterdam-Krimi (2)', 'It Follows'):
            r = row(title, 'Spielfilm', 88 * 60, 'Spielfilm, Deutschland 2020', 'ARD')
            self.assertTrue(catalog.film_shaped(r, title, r['topic'], r['description']), title)


class RestoreThenReseed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.db = database(self.root)
        rows = [row('Brokenwood – Mord in Neuseeland (7/20): Tod im Weinberg', 'Brokenwood – Mord in Neuseeland',
                    88 * 60, 'Krimiserie', 'ZDF'),
                row('It Follows (Englisch)', 'Filme', 96 * 60, 'Ein Horror um eine junge Frau.', 'ARTE')]
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), self.root)

    def state(self):
        with self.db() as c:
            return {r['title']: (r['kind'], r['state']) for r in c.execute('SELECT title,kind,state FROM works')}

    def test_0_6_131_restored_crime_episode_goes_back(self):
        with self.db() as c:
            catalog.set_state(c, 'film_seed_v06125', {'works': 1})   # as 0.6.131 left the Air
            catalog.set_state(c, 'film_seed_v06128', {'works': 1})
            for w in c.execute('SELECT id,meta FROM works').fetchall():
                m = json.loads(w['meta']);m['kind'] = 'movie'
                c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.assertEqual(self.svc.reseed_non_films(), 1)
        st = self.state()
        self.assertEqual(st['It Follows (Englisch)'][0], 'movie')
        brokenwood = [v for k, v in st.items() if k.startswith('Brokenwood')][0]
        self.assertNotEqual(brokenwood[0], 'movie')
        with self.db() as c:
            self.assertTrue(catalog.get_state(c, 'film_seed_v06132', False))
        self.assertIsNone(self.svc.reseed_non_films())   # once

    def test_restore_not_repeated_after_0_6_128(self):
        with self.db() as c:
            for key in ('film_seed_v06125', 'film_seed_v06128'):catalog.set_state(c, key, {'works': 1})
            for w in c.execute('SELECT id,meta FROM works').fetchall():   # 0.6.128 reseeded them to unknown
                m = json.loads(w['meta']);m.update(kind='unknown', reason=catalog.NON_FILM_REASON)
                c.execute("UPDATE works SET kind='unknown',state='pending',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.svc.reseed_non_films()
        self.assertEqual(self.state()['It Follows (Englisch)'][0], 'unknown')   # no second restore


class TitleParts(unittest.TestCase):
    def test_possessive_author_is_dropped(self):
        self.assertIn('Wallander – Eiskalt wie der Tod', metadata.film_title_parts('Mankells Wallander – Eiskalt wie der Tod'))
        self.assertNotIn('Pledge - Das Versprechen', metadata.film_title_parts('The Pledge - Das Versprechen'))

    def test_part_similarity_needs_year_and_runtime(self):
        meta = {'title': 'Mankells Wallander – Eiskalt wie der Tod', 'kind': 'unknown', 'year': 2005}
        parts = metadata.film_title_parts(meta['title'])
        base = {'kind': 'movie', 'title': 'Wallander – Eiskalt wie der Tod', 'year': 2005, 'similarity': .8,
                'provider': 'TMDB', 'reference_id': '1'}
        good = metadata.raise_part_similarity(meta, dict(base, runtime_agrees=True), parts)
        self.assertGreaterEqual(good['similarity'], .985)
        self.assertTrue(matching.verified(meta, good))
        self.assertEqual(matching.choose(meta, [good])['reference_id'], '1')
        for bad in (dict(base), dict(base, runtime_agrees=True, year=2007)):
            self.assertLess(metadata.raise_part_similarity(meta, bad, parts)['similarity'], .985)


class GenreBackfill(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)
        catalog.ingest(self.c, [offer('F%d' % i, 'Rudis Rasselbande', 'KiKA', i) for i in range(8)])
        self.c.execute('DELETE FROM work_genres')
        for w in self.c.execute('SELECT id,meta FROM works').fetchall():
            m = json.loads(w['meta']);m.update(kind='series', title='Rudis Rasselbande', year=None, genres=[])
            self.c.execute("UPDATE works SET kind='series',title='Rudis Rasselbande',show_key=?,meta=?,state='identified' WHERE id=?",
                           (catalog.showkey(m), json.dumps(m), w['id']))
        self.ids = [r[0] for r in self.c.execute('SELECT id FROM works ORDER BY id')]

    def own(self, wid, genre):
        self.c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, genre))

    def backfilled(self, wid, genre):
        m = json.loads(self.c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
        m.update(genres=[genre], genre_source=catalog.BACKFILL_SOURCE)
        self.c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), wid));self.own(wid, genre)

    def test_one_wrong_sibling_does_not_snowball(self):
        self.own(self.ids[0], 'Nachrichten')
        for wid in self.ids[1:4]:self.backfilled(wid, 'Nachrichten')   # earlier batches of 0.6.131
        self.assertEqual(catalog.backfill_genres(self.c, None)[0], 0)   # only one sibling with an own genre

    def test_two_thirds_of_at_least_three(self):
        for wid in self.ids[:3]:self.own(wid, 'Kinder')
        self.own(self.ids[3], 'Nachrichten')
        n, samples, _ = catalog.backfill_genres(self.c, None)
        self.assertEqual(n, 4)
        self.assertEqual(samples[0]['genres'], ['Kinder'])

    def test_undo_heal_once(self):
        self.own(self.ids[0], 'Nachrichten')
        for wid in self.ids[1:4]:self.backfilled(wid, 'Nachrichten')
        self.c.commit()
        root = Path(tempfile.mkdtemp());db = database(root)
        self.c.execute("VACUUM INTO ?", (str(root / 'catalog.db'),))
        svc = catalog_service.Service(db, lambda: {}, threading.Event(), root)
        self.assertEqual(svc.undo_genre_backfill(), 3)
        with db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM work_genres').fetchone()[0], 1)
            self.assertTrue(catalog.get_state(c, 'genre_backfill_v06132', False))
        self.assertEqual(svc.undo_genre_backfill(), 0)


class ImportantFreeSpace(unittest.TestCase):
    def setUp(self):
        system_monitor._IMPORTANT.clear();self.addCleanup(system_monitor._IMPORTANT.clear)

    def test_macos_counts_purgeable_space(self):
        plain = SimpleNamespace(total=500 * 10**9, used=495 * 10**9, free=5 * 10**9)
        done = SimpleNamespace(returncode=0, stdout='210000000000\n')
        with mock.patch.object(system_monitor.sys, 'platform', 'darwin'), \
             mock.patch.object(system_monitor.shutil, 'disk_usage', return_value=plain), \
             mock.patch.object(system_monitor.subprocess, 'run', return_value=done) as run:
            u = system_monitor.usage('/')
            system_monitor.usage('/')
        self.assertEqual(u['free'], 210 * 10**9)
        self.assertEqual(u['strict_free'], 5 * 10**9)
        self.assertEqual(run.call_count, 1)   # cached per volume
        self.assertEqual(system_monitor.drive('/')['path'], '/')

    def test_failure_and_other_systems_use_plain_value(self):
        plain = SimpleNamespace(total=100, used=90, free=10)
        with mock.patch.object(system_monitor.sys, 'platform', 'darwin'), \
             mock.patch.object(system_monitor.shutil, 'disk_usage', return_value=plain), \
             mock.patch.object(system_monitor.subprocess, 'run', side_effect=OSError('no osascript')):
            self.assertEqual(system_monitor.usage('/')['free'], 10)
        with mock.patch.object(system_monitor.sys, 'platform', 'linux'), \
             mock.patch.object(system_monitor.shutil, 'disk_usage', return_value=plain), \
             mock.patch.object(system_monitor.subprocess, 'run') as run:
            self.assertEqual(system_monitor.usage('/')['free'], 10)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
