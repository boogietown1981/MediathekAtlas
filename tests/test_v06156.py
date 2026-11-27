"""0.6.156: Befunde Mac-Prüfung 0.6.155 (BEFUND-06155.txt): Reihenkachel „Serie nicht gefunden“ (auch 0.6.154), Kinderecke-
Bildabruf lief auf dem Air-Weg nicht durch, „Kolbenfresser Teil 1 Maisernte hautnah“ fiel heraus, „Zärtliche Chaoten“ ohne
IMDb-Nummer wieder zusammengefasst. Browsertest: tests/browser/film_reihen.cjs."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog  # noqa: E402
import test_v06152  # noqa: E402
import test_v06154  # noqa: E402
from test_v06154 import entry  # noqa: E402


class Parts(test_v06154.Collapse):
    test_one_tile_per_name_with_own_film_works_and_merged_titles = test_parts_sequels_versions_and_cut_title = None
    test_ui_opens_the_reihe_as_search_and_default_is_on = None

    def movie(self, wid, genres=()):
        self.con.execute('INSERT INTO works VALUES(?,?,?,?,?)', (wid, '', '', 'movie', json.dumps({'genres': list(genres)})))

    def test_part_with_subtitle_joins_and_sequels_without_imdb_stay_single(self):
        for wid in ('k1', 'k2', 'k3'):
            self.movie(wid, ['Dokumentation'])
        got = self.run_on([entry('Kolbenfresser Teil 1 Maisernte hautnah', 'k1', 2012), entry('Kolbenfresser Teil 2', 'k2', 2013),
                           entry('Kolbenfresser Teil 3', 'k3', 2015),
                           entry('Zärtliche Chaoten – Teil 1', 'z1', 1986), entry('Zärtliche Chaoten – Teil 2', 'z2', 1987),
                           entry('Traktorgiganten Teil 1', 'g1', 2010), entry('Traktorgiganten Teil 2', 'g2', 2010),
                           entry('Traktorgiganten Teil 3', 'g3', 2011), entry('Traktorgiganten Teil 4', 'g4', 2011),
                           entry('Krieg und Frieden Teil 1 Der Aufbruch', 'x1', 2016)])     # Zusatz ohne strenge Teile: einzeln
        self.assertEqual(got['Kolbenfresser']['mehrteiler']['parts'], 3)
        self.assertEqual(got['Traktorgiganten']['mehrteiler']['parts'], 4)
        self.assertIn('Zärtliche Chaoten – Teil 1', got);self.assertIn('Zärtliche Chaoten – Teil 2', got)
        self.assertIn('Krieg und Frieden Teil 1 Der Aufbruch', got)


class PictureRun(test_v06152.YoutubePictures):
    test_phrase_match_only = test_show_without_sender_page_takes_youtube_picture_and_old_failures_retry = None
    test_budget_stop_is_reported_for_early_retry = None

    def test_youtube_read_once_event_every_run(self):
        self.prepare()
        self.shelf()
        self.seed_youtube(abo_titles=['Checker Reportagen: Wie kommt der Strom in die Steckdose?'])
        events = []

        def full(row):
            raise __import__('broadcaster').BudgetExhausted('Limit')
        with mock.patch.object(kids_catalog, 'youtube_index', wraps=kids_catalog.youtube_index) as index, \
             mock.patch('diagnostics.event', side_effect=lambda name, **kw: events.append((name, kw))):
            kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=full)
            kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=full)     # nichts mehr offen: Ereignis trotzdem
        self.assertEqual(index.call_count, 1)
        runs = [kw for name, kw in events if name == 'kids_pictures_fetched']
        self.assertEqual(len(runs), 2);self.assertIn('seconds', runs[1])
        self.assertEqual(runs[0]['from_youtube'], 1)


class Wiring(unittest.TestCase):
    def test_reihe_keeps_real_show_key_and_button_opens_films(self):
        src = (ROOT / 'unified_index.py').read_text(encoding='utf-8')
        self.assertIn("reihe_key=offer['reihe']", src);self.assertNotIn("show_key=offer['reihe']", src)
        js = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn("if (parts?.reihe) {const d=actions.querySelector('.atlas-uc-details');if(d){d.textContent='Alle Filme';d.onclick=open;}}", js)
        self.assertIn("(parts?.reihe&&item.entryYear)||main.year", js)
        self.assertTrue((ROOT / 'tests' / 'browser' / 'film_reihen.cjs').exists())
        self.assertEqual(kids_catalog.PICTURE_SECONDS, 120)


if __name__ == '__main__':
    unittest.main()
