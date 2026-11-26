"""0.6.137 (Björn 26.11.2026, Entscheidung „In der Reihe und unter Filme“): Reihenfilme wie „Der Usedom-Krimi“,
„Die Füchsin“ oder „Die drei von der Müllabfuhr“ bleiben in ihrer Reihe und stehen zusätzlich einzeln unter Filme.
Mehrteiler ohne Filmangabe („Das Adlon“, „Bodyguard (2/3)“) bleiben nur Folgen."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402
import unified_index  # noqa: E402


def offer(title, topic, n, duration=5300, description='Spielfilm Deutschland 2024 Kommissarin Karin Lossow ermittelt.'):
    return {'title': title, 'topic': topic, 'channel': 'ARD', 'duration': duration, 'description': description,
            'url_video': 'https://example.org/ard-%d.mp4' % n}


class SeriesFilms(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)
        patch = mock.patch.object(catalog, 'LISTING_DB', None);patch.start();self.addCleanup(patch.stop)

    def series(self, rows, state='identified'):
        catalog.ingest(self.c, rows)
        for w in self.c.execute("SELECT id,meta,topic,title FROM works WHERE kind!='series' OR state!=?", (state,)).fetchall():
            m = json.loads(w['meta']);m.update(kind='series', title=w['topic'], episode_title=w['title'], year=None)
            self.c.execute("UPDATE works SET kind='series',title=?,year=NULL,show_key=?,meta=?,state=? WHERE id=?",
                           (w['topic'], catalog.showkey(m), json.dumps(m), state, w['id']))

    def mark(self):
        after, total = '', 0
        while after is not None:
            n, _, after = catalog.mark_series_films(self.c, after);total += n
        return total

    def films(self):
        return sorted(i['metadata']['episode_title'] for i in catalog.listing(self.c, kind='movie')['items'])

    def test_feature_films_of_a_reihe_also_under_filme(self):
        self.series([offer('Mörderische Brandung', 'Der Usedom-Krimi', 1), offer('Nachtschatten', 'Der Usedom-Krimi', 2),
                     offer('Das Haus am Meer', 'Die Füchsin', 3,
                           description='Fernsehfilm Deutschland 2021 Anne Marie Fuchs ermittelt.'),
                     offer('Der Seerosenteich (1)', 'Der Seerosenteich', 4,
                           description='Zweiteiliger Spielfilm Deutschland 2002 Isabelle ersteigert ein Bild.')])
        self.assertEqual(self.mark(), 4)
        self.assertEqual(self.films(), ['Das Haus am Meer', 'Der Seerosenteich (1)', 'Mörderische Brandung', 'Nachtschatten'])
        movies = catalog.listing(self.c, kind='movie')
        self.assertEqual(movies['total'], 4)
        self.assertFalse(any(i['series_parent'] for i in movies['items']))
        # in der Reihe bleiben sie unverändert, die Reihe zählt wie bisher einmal
        series = catalog.listing(self.c, kind='series')
        self.assertEqual(sorted((i['metadata']['title'], i['episodes']) for i in series['items']),
                         [('Der Seerosenteich', 1), ('Der Usedom-Krimi', 2), ('Die Füchsin', 1)])
        self.assertTrue(all(i['series_parent'] for i in series['items']))
        show = catalog.listing(self.c, show=series['items'][1]['show_key'])
        self.assertEqual(show['total'], 2)
        # Kategorienzahlen: Reihe einmal, Reihenfilm je Film
        tree = {(r['kind'], r['genre']): r['n'] for r in catalog.category_tree(self.c)}
        self.assertEqual(sum(n for (k, _), n in tree.items() if k == 'movie'), 4)
        self.assertEqual(sum(n for (k, _), n in tree.items() if k == 'series'), 3)
        # Filmtitel und Jahr im zusammengeführten Katalog (unified_index nutzt index_only)
        groups = catalog.listing(self.c, kind='movie', index_only=True)
        self.assertEqual([(g[2], g[3]) for g in groups],
                         [('Der Seerosenteich (1)', 2002), ('Der Usedom-Krimi – Mörderische Brandung', 2024),
                          ('Der Usedom-Krimi – Nachtschatten', 2024), ('Die Füchsin – Das Haus am Meer', 2021)])
        self.assertEqual(self.mark(), 0)   # zweiter Lauf ändert nichts

    def test_mehrteiler_episodes_and_short_parts_stay_episodes(self):
        self.series([offer('Bodyguard (2/3)', 'Bodyguard', 1, duration=6642,
                           description='Zwischen David und Julia entwickelt sich eine Liebesbeziehung.'),
                     offer('Das Adlon. Eine Familiensaga (1)', 'Das Adlon. Eine Familiensaga', 2, duration=5751,
                           description='Während im Hotel Adlon der Familienvater Louis Adlon um die Gunst wirbt.'),
                     offer('Brokenwood (7/20)', 'Brokenwood', 3, description='Spielfilm Neuseeland 2020 Mike Shepherd.'),
                     offer('Bewährungsprobe', 'Kanzlei Liebling Kreuzberg', 4, duration=2700),
                     offer('Dreiteiler (1/3)', 'Dreiteiler', 5, description='Spielfilm Deutschland 2019 Erster Teil.')])
        self.assertEqual(self.mark(), 0)
        self.assertEqual(catalog.listing(self.c, kind='movie')['total'], 0)

    def test_open_work_not_listed_and_flag_cleared_when_no_longer_recognized(self):
        self.series([offer('Mörderische Brandung', 'Der Usedom-Krimi', 1)], state='review')
        self.assertEqual(self.mark(), 0)
        self.c.execute("UPDATE works SET state='identified'");self.assertEqual(self.mark(), 1)
        self.c.execute("UPDATE works SET state='review'");self.assertEqual(self.mark(), 1)
        self.assertEqual(catalog.listing(self.c, kind='movie')['total'], 0)

    def test_3sat_film_suffix_counts(self):
        self.series([offer('Der Wolf - Spielfilm, Norwegen 2008', 'Der Wolf', 1, description='Varg Veum ermittelt.')])
        self.assertEqual(self.mark(), 1)
        groups = catalog.listing(self.c, kind='movie', index_only=True)
        self.assertEqual([(g[2], g[3]) for g in groups], [('Der Wolf', 2008)])

    def test_partial_index_used_and_listing_unchanged_without_it(self):
        self.series([offer('Mörderische Brandung', 'Der Usedom-Krimi', 1)]);self.mark()
        self.c.execute(catalog.SERIES_FILM_INDEX_SQL)
        plan = ' '.join(r[3] for r in self.c.execute(
            'EXPLAIN QUERY PLAN SELECT id FROM works w WHERE ' + catalog.MOVIE_VIEW_SQL))
        self.assertIn('work_series_film', plan)
        self.assertEqual(catalog.listing(self.c, kind='movie')['total'], 1)

    def test_unified_index_shows_series_film_as_single_film(self):
        source = Path(unified_index.__file__).read_text(encoding='utf-8')
        self.assertIn("series_parent=work['kind'] == 'series' and kind == 'series'", source)


if __name__ == '__main__':
    unittest.main()
