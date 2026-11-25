"""0.6.135 (Prüfvermerk 0.6.134, 25.11.2026): Wallander „… 01 - …“ und More than Honey (2010/2012) blieben „prüfen“,
Sport-Sendungen trugen Nachrichten/Talk, Kopierschutz-Filme von Netzkino/Plex standen in der Kinderecke,
strict_free fehlte im Diagnose-Export."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import broadcaster  # noqa: E402
import catalog  # noqa: E402
import hls_guard  # noqa: E402
import kids_catalog  # noqa: E402
import matching  # noqa: E402
import metadata  # noqa: E402
import storage_locations  # noqa: E402
import system_monitor  # noqa: E402
from test_v06127 import offer  # noqa: E402


def database(root):
    @contextmanager
    def db():
        c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    return db


class Films(unittest.TestCase):
    META = {'title': 'Mankells Wallander – Eiskalt wie der Tod', 'kind': 'unknown', 'year': 2005}

    def test_series_index_in_database_title(self):
        c = {'kind': 'movie', 'title': 'Mankells Wallander 01 - Eiskalt wie der Tod', 'year': 2005, 'similarity': .962,
             'runtime_agrees': True, 'provider': 'TMDB', 'reference_id': '7'}
        out = metadata.raise_part_similarity(self.META, dict(c), metadata.film_title_parts(self.META['title']))
        self.assertGreaterEqual(out['similarity'], .985)
        self.assertEqual(matching.choose(self.META, [out])['reference_id'], '7')
        # a sequel number at the end stays a different film
        sequel = dict(c, title='Mankells Wallander – Eiskalt wie der Tod 2', similarity=.97)
        self.assertLess(metadata.raise_part_similarity(self.META, sequel, [])['similarity'], .985)

    def test_two_years_apart_exact_feature(self):
        meta = {'title': 'More than Honey', 'kind': 'unknown', 'year': 2010}
        c = {'kind': 'movie', 'title': 'More Than Honey', 'year': 2012, 'similarity': 1.0, 'runtime_agrees': True,
             'year_mismatch': True, 'source_duration_seconds': 5400, 'provider': 'IMDb Offline', 'reference_id': 'tt1'}
        self.assertEqual(matching.issues(meta, c), [])
        self.assertTrue(matching.issues(meta, dict(c, year=2013)))
        self.assertTrue(matching.issues(meta, dict(c, runtime_agrees=False)))

    def test_stored_suggestion_rematched(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        c = sqlite3.connect(Path(tmp.name) / 'catalog.db');c.row_factory = sqlite3.Row;self.addCleanup(c.close)
        catalog.initialize(c)
        title = 'More than Honey – Dokumentarfilm von Markus Imhoof, Schweiz 2010'
        catalog.ingest(c, [{'title': title, 'topic': 'Dokumentarfilm', 'channel': '3sat', 'duration': 5400,
                            'description': 'Dokumentarfilm', 'url_video': 'https://example.org/honey.mp4'}])
        w = c.execute('SELECT id,meta FROM works').fetchone()
        m = json.loads(w['meta']);m.update(kind='movie', suggestions=[{'kind': 'movie', 'title': 'More than Honey',
            'year': 2012, 'similarity': 1.0, 'runtime_agrees': True, 'year_mismatch': True, 'provider': 'IMDb Offline',
            'reference_id': 'tt2'}])
        c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.assertEqual(catalog.rematch_movie_suggestions(c)[0], 1)
        meta = json.loads(c.execute('SELECT meta FROM works').fetchone()[0])
        self.assertEqual(meta['reason'], catalog.YEAR_TWO_REASON)


class Genres(unittest.TestCase):
    def test_sport_and_name_only(self):
        self.assertEqual(broadcaster.genres('Sport-Clip', 'Eishockey aktuell', names=('Sport-Clip',)), ['Sport'])
        self.assertEqual(broadcaster.genres('Sportschau Wintersport', 'Interview', names=('Sportschau Wintersport',)), ['Sport'])
        self.assertEqual(broadcaster.genres('Paris 2024', 'Nachrichten', names=('Paris 2024',)), ['Sport'])
        self.assertEqual(broadcaster.genres('Kunst + Krempel', 'Journal', names=('Kunst + Krempel',)), [])
        self.assertEqual(broadcaster.genres('tagesschau', 'x', names=('tagesschau',)), ['Nachrichten'])
        self.assertEqual(broadcaster.genres('Transport-Doku', names=('Transport-Doku',)), ['Dokumentation'])
        self.assertIn('Nachrichten', broadcaster.genres('Eishockey aktuell'))   # ohne names wie bisher

    def test_heal_derived(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        c = sqlite3.connect(Path(tmp.name) / 'catalog.db');c.row_factory = sqlite3.Row;self.addCleanup(c.close)
        catalog.initialize(c)
        catalog.ingest(c, [offer('Tor des Monats', 'Sport-Clip', 'ARD', 1), offer('Kochen', 'Kunst + Krempel', 'BR', 2),
                           offer('heute 19 Uhr', 'heute', 'ZDF', 3)])
        wanted = {'Tor des Monats': ['Nachrichten', 'Dokumentation'], 'Kochen': ['Nachrichten'], 'heute 19 Uhr': ['Nachrichten']}
        for w in c.execute('SELECT id,meta,title FROM works').fetchall():
            g = wanted[w['title']]
            m = json.loads(w['meta']);m.update(genres=g, genre_source='Sender (abgeleitet)')
            c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), w['id']))
            c.execute('DELETE FROM work_genres WHERE work_id=?', (w['id'],))
            for x in g:c.execute('INSERT INTO work_genres VALUES(?,?)', (w['id'], x))
        n, samples, _ = catalog.heal_derived_genres(c)
        got = {r['title']: sorted(json.loads(r['meta'])['genres']) for r in c.execute('SELECT title,meta FROM works')}
        self.assertEqual(got['Tor des Monats'], ['Dokumentation', 'Sport'])
        self.assertEqual(got['Kochen'], [])
        self.assertEqual(got['heute 19 Uhr'], ['Nachrichten'])
        self.assertEqual(n, 2)


class KidsDrm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.db = database(Path(tmp.name))

    def test_drm_tile_hidden_network_error_not(self):
        tiles = [{'id': 'p1', 'source': 'plex', 'ref': {'plex': 'a'}}, {'id': 'n1', 'source': 'netzkino', 'ref': {'netzkino': 'b'}},
                 {'id': 'n2', 'source': 'netzkino', 'ref': {'netzkino': 'c'}}]
        with self.db() as c:
            self.assertTrue(kids_catalog.note_unplayable(c, {'plex': 'a'}, hls_guard.DrmProtected('Widevine')))
            self.assertTrue(kids_catalog.note_unplayable(c, {'netzkino': 'b'}, ValueError('bei Netzkino nicht mehr verfügbar')))
            self.assertFalse(kids_catalog.note_unplayable(c, {'netzkino': 'c'}, ValueError('Zeitüberschreitung')))
            self.assertFalse(kids_catalog.note_unplayable(c, {'offer': 'x'}, hls_guard.DrmProtected('x')))
        self.assertEqual([t['id'] for t in kids_catalog._drop_unplayable_platform_films(self.db, tiles)], ['n2'])
        with self.db() as c:
            c.execute('UPDATE kids_unplayable SET checked=?', (time.time() - kids_catalog.EMPTY_TTL - 1,))
        self.assertEqual(len(kids_catalog._drop_unplayable_platform_films(self.db, tiles)), 3)   # neuer Versuch nach 7 Tagen


class StrictFree(unittest.TestCase):
    def test_disk_reports_strict_free(self):
        with mock.patch.object(system_monitor, 'usage', return_value={'free': 9, 'total': 10, 'used': 1, 'strict_free': 4}):
            self.assertEqual(storage_locations.disk(tempfile.gettempdir())['strict_free'], 4)


if __name__ == '__main__':
    unittest.main()
