"""0.6.128 (Diagnose Pro 0.6.127, 24.11.2026): „Kurzer Prozess“ mit kurzem Ausschnitt aus den Filmen genommen;
Leerzeichen-Reihen nahmen die Mehrheitsschreibweise („eishockeyaktuell“, „sportarena“, weicher Trennstrich)."""
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
from test_v06127 import offer, SpacingVariants  # noqa: E402

FILM = 'Kurzer Prozess - Righteous Kill - Spielfilm, USA 2008'


def database(root):
    @contextmanager
    def db():
        c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    return db


class FilmWithTrailer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.db = database(self.root)
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [{'title': FILM, 'topic': 'Spielfilm', 'channel': '3sat', 'duration': 6000,
                                'description': 'Spielfilm', 'url_video': 'https://example.org/full.mp4'}])
            wid = c.execute('SELECT id FROM works').fetchone()[0]
            # a short clip with the full title, ranked first
            c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1)', ('clip1', wid, json.dumps({'title': FILM, 'topic': 'Spielfilm', 'channel': '3sat',
                      'duration': 120, 'description': 'Ausschnitt', 'url_video': 'https://example.org/clip.mp4'}), '', 10**12, 0))
        self.wid = wid
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), self.root)

    def work(self):
        with self.db() as c:
            return dict(c.execute('SELECT kind,state FROM works WHERE id=?', (self.wid,)).fetchone())

    def test_longest_offer_decides(self):
        with self.db() as c:
            self.assertEqual(catalog.best_source(c, self.wid)['duration'], 120)
            self.assertEqual(catalog.film_source(c, self.wid)['duration'], 6000)
            c.execute("UPDATE works SET kind='movie',state='review' WHERE id=?", (self.wid,))
        self.svc.reseed_non_films()
        self.assertEqual(self.work()['kind'], 'movie')

    def test_film_taken_out_by_0_6_125_comes_back_also_when_filed(self):
        with self.db() as c:
            catalog.set_state(c, 'film_seed_v06125', {'works': 1})
            m = json.loads(c.execute('SELECT meta FROM works').fetchone()[0])
            m.update(kind='series', unknown_before={'title': FILM, 'kind': 'unknown', 'state': 'review', 'rev': 8})
            c.execute("UPDATE works SET kind='series',state='format',meta=? WHERE id=?", (json.dumps(m), self.wid))
        self.svc.reseed_non_films()
        self.assertEqual(self.work(), {'kind': 'movie', 'state': 'pending'})
        with self.db() as c:
            self.assertTrue(catalog.get_state(c, 'film_seed_v06128', False))


class Spelling(SpacingVariants):
    def test_readable_spelling_wins_over_majority(self):
        self.series([offer('A%d' % i, 'eishockeyaktuell', 'SRF', i) for i in range(5)] +
                    [offer('B1', 'Eishockey aktuell', 'SRF', 20)])
        catalog.merge_spacing_variants(self.c)
        self.assertEqual({t for t, _ in self.shows()}, {'Eishockey aktuell'})

    def test_soft_hyphen_removed(self):
        self.series([offer('A1', 'Sommer.Son­ne.Elternfrei.', 'SWR', 1), offer('B1', 'Sommer.Sonne.Elternfrei.', 'SWR', 2),
                     offer('B2', 'Sommer.Sonne.Elternfrei.', 'SWR', 3)])
        catalog.merge_spacing_variants(self.c)
        self.assertEqual({t for t, _ in self.shows()}, {'Sommer.Sonne.Elternfrei.'})

    def test_already_merged_title_gets_its_spacing_back_from_topics(self):
        self.series([offer('A%d' % i, 'Sport-Arena', 'SWR', i) for i in range(3)])
        self.c.execute("UPDATE works SET title='sportarena'")   # as 0.6.127 left it
        out = catalog.respace_show_titles(self.c)
        self.assertEqual(out, {'sportarena': 'Sport-Arena'})
        self.assertEqual(catalog.respace_show_titles(self.c), {})


if __name__ == '__main__':
    unittest.main()


class ThreeSatFilms(unittest.TestCase):
    def test_sequel_spellings(self):
        import metadata
        self.assertIn('Der Pate - Teil II', metadata.film_number_variants('Der Pate II'))
        self.assertEqual(metadata.film_number_variants('Apollo 13'), [])

    def test_sequel_found_in_archive(self):
        from unittest.mock import patch
        import imdb_archive
        import metadata
        from test_v06124 import Archive
        title = 'Der Pate II - Spielfilm, USA 1974'
        row = {'title': title, 'topic': 'Spielfilm', 'duration': 200 * 60, 'provider': '3sat'}
        archive = Archive({'Der Pate - Teil II': ('tt0071562', 1974, 202)})
        with patch.object(imdb_archive, 'ACTIVE', archive):
            result = metadata.candidates(row, {'title': title, 'kind': 'movie', 'year': None}, {})
        judged = catalog.match_meta({'title': title, 'kind': 'movie', 'year': None}, row)
        import matching
        self.assertEqual(matching.choose(judged, result['candidates'])['reference_id'], 'tt0071562')

    def test_runtime_and_year_decide_between_disagreeing_films(self):
        import matching
        meta = {'title': 'Terrified', 'kind': 'movie', 'year': 2017}
        base = {'kind': 'movie', 'similarity': 1.0, 'title': 'Terrified'}
        right = dict(base, provider='IMDb Offline', reference_id='tt1', year=2017, runtime_agrees=True)
        other = dict(base, provider='TMDB', reference_id='99', year=2017, runtime_agrees=False)   # same year, other film
        self.assertEqual(matching.choose(meta, [right, other])['reference_id'], 'tt1')
        twin = dict(right, reference_id='tt2')   # two films with year and runtime: nothing
        self.assertIsNone(matching.choose(meta, [right, twin]))
