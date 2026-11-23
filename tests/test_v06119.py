"""0.6.119 (Mac-Prüfung 0.6.118): E6 Schreibweise falsch herum („Kikaninchen“ 418, „Reporter“ → „reporter“,
„FORUM WIRTSCHAFT“ → „forum wirtschaft“, „Trailer: SAARTHEMA“); E4 „Dein Song 2022“–„2026“ lagen auf „prüfen“."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c);self.n = 0

    def add(self, topic, title, work_title, state, kind='series', channel='ZDF', meta=None, show=None):
        self.n += 1
        catalog.ingest(self.c, [{'title': title, 'topic': topic, 'description': 'x', 'duration': 900, 'channel': channel,
                                 'url_video': 'https://example.org/%d.mp4' % self.n}])
        wid = self.c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?",
                             ('https://example.org/%d.mp4' % self.n,)).fetchone()[0]
        m = json.loads(self.c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
        m.update(kind=kind, title=work_title, **(meta or {}))
        sk = show or (catalog.showkey({'kind': 'series', 'title': work_title}) if kind == 'series' else '')
        self.c.execute('UPDATE works SET title=?,kind=?,state=?,show_key=?,meta=? WHERE id=?', (work_title, kind, state, sk, json.dumps(m), wid))
        return wid


class Spelling(Base):
    def titles(self, show):
        return {r[0] for r in self.c.execute('SELECT DISTINCT title FROM works WHERE show_key=?', (show,))}

    def test_brand_from_topic_wins_even_when_every_title_is_plain(self):
        show = catalog.showkey({'kind': 'series', 'title': 'Kikaninchen'})
        for i in range(4):self.add('KiKANiNCHEN', 'Folge %d' % i, 'Kikaninchen', 'identified', show=show)
        self.assertEqual(catalog.unify_show_spelling(self.c), {'Kikaninchen': 'KiKANiNCHEN'})
        self.assertEqual(self.titles(show), {'KiKANiNCHEN'})

    def test_plain_case_differences_stay(self):
        cases = (('reporter', 'Reporter'), ('forum wirtschaft', 'FORUM WIRTSCHAFT'), ('Trailer: SAARTHEMA', 'Trailer: Saarthema'),
                 ('aktiv und gesund', 'Aktiv und Gesund'), ('phoenix runde', 'Phoenix Runde'))
        shows = {}
        for topic, title in cases:
            show = catalog.showkey({'kind': 'series', 'title': title});shows[title] = show
            for i in range(3):self.add(topic, 'Ausgabe %d' % i, title, 'format', show=show)
            self.add(topic, 'Ausgabe x', topic, 'format', show=show)
        self.assertEqual(catalog.unify_show_spelling(self.c), {})
        for topic, title in cases:self.assertEqual(self.titles(shows[title]), {topic, title})

    def test_two_brand_spellings_are_left_alone(self):
        show = catalog.showkey({'kind': 'series', 'title': 'kulturMATINEE'})
        self.add('kulturMATINEE', 'A', 'kulturMATINEE', 'format', show=show)
        self.add('KulturMatinee', 'B', 'KulturMatinee', 'format', show=show)
        self.add('kulturmatinée', 'C', 'kulturmatinée', 'format', show=show)
        self.assertEqual(catalog.unify_show_spelling(self.c), {})


class OpenYearEditions(Base):
    def test_dein_song_years_in_review_go_under_the_known_reihe(self):
        show = catalog.showkey({'kind': 'series', 'title': 'Dein Song'})
        for i in range(6):self.add('Dein Song', 'Song %d' % i, 'Dein Song', 'format', meta={'provider': 'Sendung'}, show=show)
        for i in range(6):self.add('Dein Song', 'Folge %d' % i, 'Dein Song', 'identified', meta={'provider': 'IMDb Offline', 'reference_id': 'tt1'}, show=show)
        ids = []
        for year, n in ((2022, 1), (2023, 2), (2024, 2), (2025, 1)):
            for i in range(n):ids.append(self.add('Dein Song %d' % year, 'Lena %d' % i, 'Dein Song %d' % year, 'review',
                                                  meta={'provider': 'MediathekViewWeb'}))
        moved, merged = catalog.merge_year_editions(self.c)
        self.assertEqual(moved, 6);self.assertEqual(merged['Dein Song'], [2022, 2023, 2024, 2025])
        rows = self.c.execute('SELECT title,show_key,state,meta FROM works WHERE id IN (%s) ORDER BY id' % ','.join('?' * len(ids)), ids).fetchall()
        self.assertEqual({(r['title'], r['show_key'], r['state']) for r in rows}, {('Dein Song', show, 'format')})
        m = json.loads(self.c.execute('SELECT meta FROM works WHERE id=?', (ids[0],)).fetchone()[0]);self.assertEqual((m['provider'], m['year_edition_v06119']), ('Sendung', 2022))
        self.assertTrue(m['episode_title'].startswith('Dein Song 2022'))

    def test_single_open_year_without_known_reihe_stays(self):
        self.add('Sommerfest 2025', 'A', 'Sommerfest 2025', 'review')
        self.add('Sommerfest 2025', 'B', 'Sommerfest 2025', 'review')
        self.assertEqual(catalog.merge_year_editions(self.c)[0], 0)

    def test_events_and_films_never(self):
        show = catalog.showkey({'kind': 'series', 'title': 'Olympia'})
        for i in range(12):self.add('Olympia', 'x%d' % i, 'Olympia', 'format', meta={'provider': 'Sendung'}, show=show)
        self.add('Olympia 2024', 'Finale', 'Olympia 2024', 'review')
        self.add('Spielfilm', 'Paris 2024', 'Paris 2024', 'review', kind='movie')
        self.assertEqual(catalog.merge_year_editions(self.c)[0], 0)


if __name__ == '__main__':
    unittest.main()
