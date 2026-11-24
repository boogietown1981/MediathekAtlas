"""0.6.130 (Mac-Prüfung 0.6.129): die Leerzeichen-Regel schrieb Reihen in Großbuchstaben um (Nachtcafé → NACHTCAFÉ,
Presseclub → PRESSECLUB) und „Betrifft“ → „betrifft: ...“."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
from test_v06127 import offer, SpacingVariants  # noqa: E402


class CaseStays(SpacingVariants):
    def test_capitals_never_win(self):
        self.assertEqual(catalog.best_spelling({'Nachtcafé': 1, 'NACHTCAFÉ': 9}), 'Nachtcafé')
        self.assertEqual(catalog.best_spelling({'eishockeyaktuell': 9, 'Eishockey aktuell': 1}), 'Eishockey aktuell')
        self.assertEqual(catalog.best_spelling({'super.markt': 3, 'SUPER.MARKT': 1}), 'super.markt')

    def test_case_variants_in_one_reihe_are_left_alone(self):
        self.series([offer('A%d' % i, 'Nachtcafé', 'SWR', i) for i in range(3)] + [offer('B1', 'NACHTCAFÉ', 'SWR', 9)] +
                    [offer('C1', 'Nacht café', 'SWR', 10)])
        catalog.merge_spacing_variants(self.c)
        titles = {t: n for (t, _), n in self.shows().items()}
        self.assertNotIn('NACHT CAFÉ', titles)
        self.assertEqual(titles.get('Nachtcafé', 0) + titles.get('NACHTCAFÉ', 0), 5)   # „Nacht café“ joined, case untouched
        self.assertEqual(titles.get('NACHTCAFÉ'), 1)
        self.assertNotIn('Nacht café', titles)   # the spacing variant joined
        self.assertEqual(catalog.respace_show_titles(self.c), {})

    def test_trailing_punctuation_is_no_word_break(self):
        self.series([offer('A%d' % i, 'Betrifft', 'SWR', i) for i in range(2)])
        self.c.execute("UPDATE works SET topic='betrifft: ...'")
        self.assertEqual(catalog.respace_show_titles(self.c), {})


if __name__ == '__main__':
    unittest.main()


class FilmTrailers(unittest.TestCase):
    """Mac-Prüfung 0.6.129: „Kurzer Prozess – Righteous Kill – Spielfilm, USA 2008“ hat nur einen 162-s-Trailer."""

    def setUp(self):
        import sqlite3, tempfile, json
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)
        rows = [{'title': 'Kurzer Prozess - Righteous Kill - Spielfilm, USA 2008', 'topic': 'Spielfilm', 'channel': '3sat',
                 'duration': 162, 'description': 'Spielfilm', 'url_video': 'https://example.org/t.mp4'},
                {'title': 'Der Pate - Spielfilm, USA 1972', 'topic': 'Spielfilm', 'channel': '3sat', 'duration': 10000,
                 'description': 'Spielfilm', 'url_video': 'https://example.org/p.mp4'},
                {'title': 'Kleine Welt - Kurzfilm, Schweiz 2020', 'topic': 'Kurzfilm', 'channel': '3sat', 'duration': 400,
                 'description': 'Kurzfilm', 'url_video': 'https://example.org/k.mp4'}]
        catalog.ingest(self.c, rows)
        self.c.execute("UPDATE works SET state='review'")
        self.json = json

    def state(self):
        return {r['title'][:14]: (r['kind'], r['state']) for r in self.c.execute('SELECT title,kind,state FROM works')}

    def test_trailer_filed_full_film_and_short_film_stay(self):
        filed, reopened, samples = catalog.file_film_trailers(self.c)
        self.assertEqual((filed, reopened), (1, 0))
        st = self.state()
        self.assertEqual(st['Kurzer Prozess'], ('other', 'format'))
        self.assertEqual(st['Der Pate - Spi'][1], 'review')
        self.assertEqual(st['Kleine Welt - '][1], 'review')
        self.assertEqual(catalog.file_film_trailers(self.c)[:2], (0, 0))

    def test_reopened_when_the_full_film_arrives(self):
        catalog.file_film_trailers(self.c)
        wid = self.c.execute("SELECT id FROM works WHERE title LIKE 'Kurzer%'").fetchone()[0]
        self.c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1)', ('full', wid, self.json.dumps({'title': 'Kurzer Prozess - Righteous Kill - Spielfilm, USA 2008',
                       'topic': 'Spielfilm', 'channel': '3sat', 'duration': 6000, 'description': 'Spielfilm', 'url_video': 'https://example.org/f.mp4'}), '', 1, 0))
        self.assertEqual(catalog.file_film_trailers(self.c)[:2], (0, 1))
        self.assertEqual(self.state()['Kurzer Prozess'], ('movie', 'pending'))


class ShoutUndo(SpacingVariants):
    def test_capitals_from_0_6_128_come_back_from_topics(self):
        self.series([offer('A%d' % i, 'Nachtcafé', 'SWR', i) for i in range(3)])
        self.c.execute("UPDATE works SET title='NACHTCAFÉ'")
        self.assertEqual(catalog.respace_show_titles(self.c), {'NACHTCAFÉ': 'Nachtcafé'})

    def test_sender_capitals_stay(self):
        self.series([offer('A%d' % i, 'PRESSECLUB', 'WDR', i) for i in range(2)])
        self.assertEqual(catalog.respace_show_titles(self.c), {})
