"""0.6.105: Altersregel nur mit Familiensignal (Mac-Prüfung 0.6.103, 22.11.2026).

Mit 0.6.99/0.6.103 kamen 533 Netzkino- und 77 Plex-Filme allein über FSK ≤ 12 und „Abenteuer“/„Fantasy“ in die
Kinderecke, u. a. „5-Headed Shark Attack“, „Alien Predator War“, „55 Tage in Peking“, „An Egypt Affair“,
„A Man called Hero“, „Anuk III“, „Prosperos Bücher“, „Jurassic Galaxy“, „Vom Suchen und Finden der Liebe“.
Jetzt: Altersweg nur mit Kategorie Familie, nie neben Science-Fiction/Action/Mystery/Romantik (und dem Sicherheitsnetz).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import categories  # noqa: E402
import portal_reference as pr  # noqa: E402


class AgePathTests(unittest.TestCase):
    OUT = {   # Titel aus der Prüfung: Genres wie bei Netzkino/IMDb, FSK 12 bzw. 6
        '5-Headed Shark Attack': (['Abenteuer', 'Horror', 'Science-Fiction'], 12),
        'Alien Predator War': (['Action', 'Abenteuer', 'Science-Fiction'], 12),
        '55 Tage in Peking': (['Abenteuer', 'Historie', 'Drama'], 12),
        'An Egypt Affair': (['Abenteuer', 'Drama'], 12),
        'A Man called Hero': (['Action', 'Fantasy'], 12),
        'Anuk III': (['Abenteuer', 'Fantasy'], 6),
        'Prosperos Bücher': (['Fantasy', 'Drama'], 12),
        'Jurassic Galaxy': (['Familie', 'Science-Fiction', 'Abenteuer'], 12),
        'Vom Suchen und Finden der Liebe': (['Familie', 'Romantik', 'Musik'], 6),
    }
    IN = {
        'Bibi & Tina': (['Familie', 'Komödie', 'Musik'], 0),
        'Das Märchen von den zwölf Monaten': (['Familie', 'Fantasy'], 6),
    }

    def test_titles(self):
        for title, (genres, age) in self.OUT.items():
            self.assertNotIn('Kinder', categories.classify(genres, [], True, age=age), title)
        for title, (genres, age) in self.IN.items():
            self.assertIn('Kinder', categories.classify(genres, [], True, age=age), title)

    def test_portal_rows(self):
        # Netzkino/Plex: Altersangabe aus der Plattform, Genres aus der Referenz
        report = {'status': 'candidate', 'metadata': {'genres': ['Adventure', 'Fantasy']}}
        self.assertNotIn('Kinder', pr.summary('', report, age=pr.age_of({'fsk': 6}))['categories'])
        report = {'status': 'candidate', 'metadata': {'genres': ['Family', 'Fantasy']}}
        self.assertIn('Kinder', pr.summary('', report, age=pr.age_of({'fsk': 6}))['categories'])


class ImdbIdTests(unittest.TestCase):
    def test_tmdb_match_uses_imdb_id(self):
        """reference_ages blieb auf der Prüfkopie leer: TMDB-Treffer tragen die IMDb-Kennung in meta.imdb_id."""
        import json, sqlite3, time
        import catalog, kids_rules
        c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
        catalog.initialize(c); kids_rules.ensure(c)
        for wid, meta in (('a', {'provider': 'TMDB', 'reference_id': '12345', 'imdb_id': 'tt0111111', 'genres': ['Familie']}),
                          ('b', {'provider': 'IMDb Offline', 'reference_id': 'tt0222222', 'genres': ['Familie']})):
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,1)",
                      (wid, wid, 'movie', 2000, wid, json.dumps(meta), 'matched'))
            c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, 'Familie'))
        self.assertEqual(sorted(kids_rules._candidates(c, time.time(), 10)), ['tt0111111', 'tt0222222'])


if __name__ == '__main__':
    unittest.main()
