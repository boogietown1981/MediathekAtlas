"""0.6.157: Befunde Mac-Prüfung 0.6.156 (BEFUND-06156.txt): YouTube-Bilder falsch zugeordnet („Die drei Musketiere“ ← „Die drei
Musketiere der Neuzeit (ACTION …)“, „Die Serie“ ← TOGGO-Short), „Kolbenfresser“/„Monster High Webisodes“ nicht mehr als
Mehrteiler; Hinweise: Reihenfilm in der Suche als „Serie · 1 Folgen“, Player-Titel „Tatort (1970)“."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import catalog  # noqa: E402
import kids_catalog  # noqa: E402
import streaming  # noqa: E402
import test_v06152  # noqa: E402
import test_v06154  # noqa: E402
from test_v06154 import entry  # noqa: E402


class Pictures(test_v06152.YoutubePictures):
    test_phrase_match_only = test_show_without_sender_page_takes_youtube_picture_and_old_failures_retry = None
    test_budget_stop_is_reported_for_early_retry = None

    def test_whole_title_part_only_and_generic_names_skipped(self):
        self.seed_youtube(abo_titles=['Habt ihr die Serie schon gesehen? #witchdetectives', 'Lernen mit Spaß | Vania Mania',
                                      'Abenteuer Griechenland | Film für Kinder | Checker Tobi'],
                          item_titles=['Die drei Musketiere der Neuzeit (ACTION ABENTEUER ganzer Film)', 'Die Checker-Webshow | Folge 1'])
        pic = lambda t: kids_catalog.youtube_picture(self.root, t)
        self.assertEqual(pic('Die drei Musketiere'), '')
        self.assertEqual(pic('Die Serie'), '');self.assertEqual(pic('Lernen mit Spaß'), '')
        self.assertTrue(pic('Abenteuer Griechenland').startswith('https://i.ytimg.com/'))
        self.assertTrue(pic('Die Checker-Webshow').startswith('https://i.ytimg.com/'))


class Parts(test_v06154.Collapse):
    test_one_tile_per_name_with_own_film_works_and_merged_titles = test_parts_sequels_versions_and_cut_title = None
    test_ui_opens_the_reihe_as_search_and_default_is_on = None

    def test_years_without_fiction_genre_stay_parts(self):
        got = self.run_on([entry('Kolbenfresser Teil 1 Maisernte hautnah', 'k1', 2012), entry('Kolbenfresser Teil 2', 'k2', 2013),
                           entry('Kolbenfresser Teil 3', 'k3', 2015),
                           entry('Monster High Webisodes: Volume 1 (1/2)', 'h1', 2010), entry('Monster High Webisodes: Volume 1 (2/2)', 'h2', 2011)])
        self.assertEqual(got['Kolbenfresser']['mehrteiler']['parts'], 3)
        self.assertEqual(got['Monster High Webisodes: Volume 1']['mehrteiler']['parts'], 2)


class SeriesFilm(unittest.TestCase):
    META = {'title': 'Tatort', 'kind': 'series', 'year': 1970, 'series_film': 1, 'series_film_title': 'Die letzten Menschen von Köln',
            'series_film_year': 2026}

    def test_listed_as_film_and_player_title(self):
        row = catalog.as_series_film({'metadata': dict(self.META)})
        self.assertEqual((row['metadata']['kind'], row['metadata']['title'], row['metadata']['year']), ('movie', 'Die letzten Menschen von Köln', 2026))
        self.assertEqual(streaming._title(dict(self.META), {}), 'Tatort – Die letzten Menschen von Köln (2026)')
        self.assertEqual(streaming._title(dict(self.META, series_film_title='Tatort – Azra'), {}), 'Tatort – Azra (2026)')


if __name__ == '__main__':
    unittest.main()
