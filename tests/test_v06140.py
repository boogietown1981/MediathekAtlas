"""0.6.140 (Mac-Prüfung 0.6.138, BEFUND-06138.txt): Reihenfilme unter Filme – Jahr der Reihe statt des Films, doppelte
Kacheln (Fassungen, „· NEU“), Folgen episodischer Reihen (Rebecka Martinsson „Del 1“, Brokenwood, Mord auf Shetland),
Reihenfilme, die schon eigene Filmwerke sind, Suche nach dem Filmtitel ohne Treffer."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import test_v06137  # noqa: E402
from test_v06137 import offer  # noqa: E402


class SeriesFilmFixes(test_v06137.SeriesFilms):
    def run_mark(self):
        after, cache, total = '', {}, 0
        while after is not None:
            n, _, after = catalog.mark_series_films(self.c, after, cache=cache);total += n
        return total

    def titles(self, **kw):
        return sorted((i['metadata']['title'], i['metadata']['year']) for i in catalog.listing(self.c, kind='movie', **kw)['items'])

    def test_versions_and_new_marks_are_one_film_two_parters_two(self):
        self.series([offer('Altlasten (9) – Die Drei von der Müllabfuhr', 'Die drei von der Müllabfuhr', 1,
                           description='Spielfilm Deutschland 2023 Werner Träsch räumt auf.'),
                     offer('Altlasten – Die Drei von der Müllabfuhr (9) (Originalversion)', 'Die drei von der Müllabfuhr', 2,
                           description='Spielfilm Deutschland 2023 Werner Träsch räumt auf.'),
                     offer('Geisternetze (26) · NEU', 'Der Usedom-Krimi', 3),
                     offer('Geisternetze (26)', 'Der Usedom-Krimi', 4),
                     offer('Tatort – Unvergänglich (1/2)', 'Tatort', 5, description='Fernsehfilm Deutschland 2024 Teil eins.'),
                     offer('Tatort – Unvergänglich (2/2)', 'Tatort', 6, description='Fernsehfilm Deutschland 2024 Teil zwei.')])
        self.run_mark()
        self.assertEqual(self.titles(), [('Der Usedom-Krimi – Geisternetze', 2024),
                                         ('Die drei von der Müllabfuhr – Altlasten', 2023),
                                         ('Tatort – Unvergänglich (1/2)', 2024), ('Tatort – Unvergänglich (2/2)', 2024)])
        # API: Filmjahr statt Startjahr der Reihe, Reihe bleibt erkennbar
        item = catalog.listing(self.c, kind='movie')['items'][0]
        self.assertTrue(item['series_film']);self.assertEqual(item['metadata']['series_title'], 'Der Usedom-Krimi')
        self.assertEqual(self.run_mark(), 0)

    def test_episodic_reihe_is_never_a_film(self):
        martinsson = 'Spielfilm Schweden 2017 Rebecka Martinsson kehrt zurück.'
        self.series([offer('Rebecka Martinsson – Det blod som spillts: Del 1', 'Rebecka Martinsson', 1, description=martinsson),
                     offer('Rebecka Martinsson – Husgrunden: Del 2', 'Rebecka Martinsson', 2, description=martinsson),
                     offer('Weiße Nacht (S01/E01)', 'Rebecka Martinsson', 3, description=martinsson),
                     offer('Die Familienfehde', 'Brokenwood - Mord in Neuseeland', 4),
                     offer('Tote im Weinberg (7/20)', 'Brokenwood - Mord in Neuseeland', 5, duration=5300),
                     offer('Folge 3: Tote Wasser – Mord auf Shetland (S01/E03)', 'Mord auf Shetland', 6),
                     # IMDbs eigene Nummer „(S05/E06)“ macht keine Folge aus einem Reihenfilm
                     offer('Aus heiterem Himmel · Praxis mit Meerblick (32) (S05/E06)', 'Praxis mit Meerblick', 7)])
        self.run_mark()
        self.assertEqual(self.titles(), [('Praxis mit Meerblick – Aus heiterem Himmel', 2024)])

    def test_film_work_of_its_own_and_edition_without_name(self):
        self.series([offer('Kassensturz (4) – Die Drei von der Müllabfuhr', 'Die drei von der Müllabfuhr', 1),
                     offer('Der Usedom-Krimi (12)', 'Der Usedom-Krimi', 2)])
        catalog.ingest(self.c, [offer('Die Drei von der Müllabfuhr – Kassensturz', 'Spielfilm', 9)])
        self.c.execute("UPDATE works SET kind='movie' WHERE kind!='series'")
        self.run_mark()
        self.assertEqual([t for t, _ in self.titles()], ['Die Drei von der Müllabfuhr – Kassensturz'])

    def test_search_by_film_title(self):
        self.series([offer('Altlasten (9) – Die Drei von der Müllabfuhr', 'Die drei von der Müllabfuhr', 1)])
        self.run_mark()
        self.assertEqual(catalog.listing(self.c, kind='movie', query='Altlasten')['total'], 1)
        self.assertEqual(catalog.listing(self.c, query='Altlasten')['total'], 1)
        self.assertEqual(catalog.listing(self.c, kind='movie', query='Geisternetze')['total'], 0)

    def test_only_candidates_are_read(self):
        self.series([offer('Kurz %d' % i, 'Kurzreihe', i, duration=1500) for i in range(5)])
        rows = self.c.execute("SELECT COUNT(*) FROM works w WHERE w.kind='series' AND " + catalog.SERIES_FILM_CANDIDATES,
                              (catalog.SERIES_FILM_MIN,)).fetchone()[0]
        self.assertEqual(rows, 0)
        self.c.execute("UPDATE works SET meta=json_set(meta,'$.series_film',1) WHERE id=(SELECT MIN(id) FROM works)")
        self.assertEqual(self.run_mark(), 1)   # ein altes Kennzeichen wird entfernt

    def test_0_6_141_foreign_series_with_imdb_numbers_stay_episodes(self):
        # Mac-Prüfung 0.6.140: Maria Wern/Rebecka Martinsson nur mit „(Sxx/Eyy)“, 85–88 min
        self.series([offer('Maria Wern, Kripo Gotland – Mittsommer (S09/E01)', 'Maria Wern, Kripo Gotland', 1, duration=5200,
                           description='Fernsehfilm Schweden 2023 Maria Wern ermittelt.'),
                     offer('Rebecka Martinsson – Weiße Nacht (S01/E01)', 'Rebecka Martinsson', 2,
                           description='Spielfilm Schweden 2017 Rebecka kehrt zurück.'),
                     offer('Brokenwood - Mord in Neuseeland – Die Familienfehde – Brokenwood – Mord in Neuseeland',
                           'Brokenwood - Mord in Neuseeland', 3, description='Spielfilm Neuseeland 2022 Mike Shepherd.'),
                     offer('Die Kämpferin · Praxis mit Meerblick (20) (S04/E02)', 'Praxis mit Meerblick', 4)])
        self.run_mark()
        self.assertEqual(self.titles(), [('Praxis mit Meerblick – Die Kämpferin', 2024)])
        self.assertEqual(catalog.series_film_part(
            'Brokenwood - Mord in Neuseeland – Die Familienfehde – Brokenwood – Mord in Neuseeland',
            'Brokenwood - Mord in Neuseeland'), 'Die Familienfehde')

    def test_0_6_141_one_film_across_show_keys_and_year_from_title(self):
        self.series([offer('Die Kämpferin · Praxis mit Meerblick (20) (S04/E02)', 'Praxis mit Meerblick', 1),
                     offer('Die Kämpferin (S01/E20)', 'Praxis mit Meerblick', 2),
                     offer('Tatort – Abbruchkante (2023)', 'Tatort', 3, description='Fernsehfilm Deutschland Kommissarin Lindholm.')])
        # zweite Kopie unter anderem Reihenschlüssel (wie auf der Pro-Kopie)
        self.c.execute("UPDATE works SET show_key='praxis-alt' WHERE title='Praxis mit Meerblick' AND id=(SELECT MAX(id) FROM works WHERE title='Praxis mit Meerblick')")
        self.run_mark()
        self.assertEqual(self.titles(), [('Praxis mit Meerblick – Die Kämpferin', 2024), ('Tatort – Abbruchkante', 2023)])

    def test_0_6_142_tatort_without_country_or_with_typo_stays(self):
        # Mac-Prüfung 0.6.141: BR „Spielfilm | Krimi 2021 … Tatort-Fall“, WDR „Fernsehfilm Deutschand 2024“
        self.series([offer('Flash (Audiodeskription)', 'Tatort', 1,
                           description='Spielfilm | Krimi 2021 Der Film „Flash“ ist der 1205. Tatort-Fall.'),
                     offer('Man stirbt nur zweimal (2024) (klare Sprache)', 'Tatort', 2,
                           description='Fernsehfilm Deutschand 2024 +++ Die Leiche des Anwalts'),
                     offer('Sturmfront (S08/E01)', 'Maria Wern, Kripo Gotland', 3, description='Spielfilm Schweden/Deutschland 2020 Sturm.'),
                     offer('Bedrohung (S07/E03)', 'Maria Wern, Kripo Gotland', 4, description='Spielfilm Schweden 2018 Maskenmann.')])
        self.run_mark()
        self.assertEqual(self.titles(), [('Maria Wern, Kripo Gotland – Sturmfront', 2020),   # Koproduktion: bis Björns Antwort drin
                                         ('Tatort – Flash', 2021), ('Tatort – Man stirbt nur zweimal', 2024)])
        self.assertFalse(catalog.series_film_german('Spielfilm Frankreich 2019 Kommissar'))
        self.assertTrue(catalog.series_film_german('Spielfilm Österreich 2020 Wien'))

    # die Grundfälle aus 0.6.137 laufen mit (geerbt)


if __name__ == '__main__':
    unittest.main()
