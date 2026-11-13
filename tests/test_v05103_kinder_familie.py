"""0.5.103: „Kinder“ und „Familie“ getrennt (Björn, 13.11.2026: Filme mit Tod usw. unter Kinder).

Bis 0.5.102 hieß die Kategorie „Kinder & Familie“ und nahm TMDBs „Family“, Weihnachtsfilme, „Jugend“
und „Teen“ mit auf. Jetzt: Kinder nur bei eindeutigen Kinder-Signalen, nie neben Horror/Thriller/
Krimi/Erotik/Krieg und nur bis FSK 6; Familie getrennt, nie neben Horror/Erotik, bis FSK 12.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import categories  # noqa: E402
import catalog  # noqa: E402
import metadata  # noqa: E402
import portal_reference as pr  # noqa: E402


class RuleTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(categories.of_label('Family'), ['Familie'])
        self.assertEqual(categories.of_label('Kinder & Familie'), ['Familie'])   # altes Mischlabel
        for label in ('Kinderfilm', 'Kinderserie', 'Kids', 'Children', 'KiKA', 'Kinderfernsehen'):
            self.assertEqual(categories.of_label(label), ['Kinder'], label)
        self.assertEqual(categories.of_label('Jugend'), [])
        self.assertEqual(categories.of_label('Teen-Horror'), ['Horror'])
        self.assertNotIn('Kinder', categories.of_label('Weihnachtsfilm'))

    def test_dark_titles_never_kids(self):
        for extra in ('Horror', 'Thriller', 'Crime', 'War', 'Erotik'):
            self.assertNotIn('Kinder', categories.classify(['Kids', extra]), extra)
        self.assertEqual(categories.classify(['Family', 'Horror']), ['Horror'])
        self.assertIn('Familie', categories.classify(['Family', 'Drama']))
        self.assertNotIn('Kinder', categories.classify(['Family', 'Drama']))   # Familiendrama ist kein Kinderfilm

    def test_age(self):
        self.assertEqual([categories.age_of(v) for v in ('FSK 0', 'ab 6', 12, 'de/16', 'TV-MA', '', None, 'PG-13')],
                         [0, 6, 12, 16, 16, None, None, 12])
        self.assertIn('Kinder', categories.classify(['Kinderfilm'], age='FSK 6'))
        self.assertNotIn('Kinder', categories.classify(['Kinderfilm', 'Abenteuer'], age='FSK 12'))
        self.assertIn('Familie', categories.classify(['Family', 'Abenteuer'], age='FSK 12'))
        self.assertNotIn('Familie', categories.classify(['Family', 'Abenteuer'], age='FSK 16'))

    def test_animated_family_film_is_for_kids(self):
        self.assertEqual(categories.classify(['Family', 'Animation']), ['Animation', 'Kinder', 'Familie'])

    def test_portal_rows_use_fsk(self):
        report = {'status': 'candidate', 'metadata': {'genres': ['Family', 'Adventure']}}
        self.assertNotIn('Familie', pr.summary('', report, age=pr.age_of({'rating': 'FSK 16'}))['categories'])
        self.assertIsNone(pr.age_of({'rating': 7.4}))          # Bewertung, kein Alter
        self.assertEqual(pr.age_of({'fsk': 12}), 12)

    def test_legacy_filter_value(self):
        self.assertEqual(categories.wanted('Kinder & Familie')[0], 'Familie')
        self.assertEqual(metadata.genres(['Family', 'Kids']), ['Familie', 'Kinder'])


class MediathekTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        catalog.initialize(self.c)

    def add(self, wid, genres, source='TMDB'):
        self.c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,?)",
                       (wid, wid, 'movie', 2000, wid, json.dumps({'genres': genres, 'genre_source': source}), 'matched', 1))
        self.c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)",
                       ('o' + wid, wid, json.dumps({'title': wid, 'url_video': 'https://example.org/v.mp4'})))
        for g in genres:
            self.c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))

    def test_migration_and_filters(self):
        self.add('maus', ['Kinder & Familie'], source='Sender (abgeleitet)')   # KiKA
        self.add('drama', ['Kinder & Familie', 'Drama'])                         # TMDB Family
        self.add('grusel', ['Kinder & Familie', 'Horror'])
        self.add('pixar', ['Familie', 'Animation'])
        self.add('kidskrimi', ['Kinder', 'Krimi'])
        self.assertEqual(catalog.split_kids_family(self.c), 3)
        labels = lambda wid: sorted(r[0] for r in self.c.execute('SELECT genre FROM work_genres WHERE work_id=?', (wid,)))
        self.assertEqual(labels('maus'), ['Kinder'])
        self.assertEqual(labels('drama'), ['Drama', 'Familie'])
        self.assertEqual(json.loads(self.c.execute("SELECT meta FROM works WHERE id='drama'").fetchone()[0])['genres'], ['Drama', 'Familie'])
        titles = lambda g: sorted(i['work_id'] for i in catalog.listing(self.c, kind='movie', genre=g, downloaded='all')['items'])
        self.assertEqual(titles('Kinder'), ['maus', 'pixar'])
        self.assertEqual(titles('Familie'), ['drama', 'pixar'])
        tree = {r['genre']: r['n'] for r in catalog.category_tree(self.c)}
        self.assertEqual((tree['Kinder'], tree['Familie'], tree['Horror']), (2, 2, 1))


if __name__ == '__main__':
    unittest.main()
