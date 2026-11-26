"""0.6.154: Korrektur der Filmreihen-/Mehrteiler-Kacheln nach der Mac-Prüfung 0.6.150 (BEFUND-06150.txt):
Praxis mit Meerblick doppelt (zwei show_keys), eigene Filmwerke „Tatort: Azra“ einzeln, Fortsetzungen und Fassungen als
Mehrteiler, „Fremde Verwandte Teil“ abgeschnitten, Maria Wern (zusammengeführt) nicht in der Reihe."""
import json
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import unified_index  # noqa: E402

SERIES = [('a1', 'praxis a', 'Praxis mit Meerblick'), ('a2', 'praxis a', 'Praxis mit Meerblick'),
          ('b1', 'praxis b', 'Praxis mit Meerblick'), ('t1', 'tatort', 'Tatort'), ('t2', 'tatort', 'Tatort'),
          ('w1', 'maria wern', 'Maria Wern, Kripo Gotland'), ('w2', 'maria wern', 'Maria Wern, Kripo Gotland'),
          ('w3', 'maria wern', 'Maria Wern, Kripo Gotland')]


def entry(title, wid, year=2020, other=False):
    offers = [{'source': 'mediatheken', 'id': wid, 'episodes': 1}]
    if other:
        offers.append({'source': 'plex', 'item': {'id': 'x' + wid}})
    return {'title': title, 'year': year, 'offers': offers}


class Collapse(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE works(id TEXT, show_key TEXT, title TEXT, kind TEXT, meta TEXT)')
        for wid, show, title in SERIES:
            self.con.execute('INSERT INTO works VALUES(?,?,?,?,?)', (wid, show, title, 'series', json.dumps({'series_film': 1})))

    @contextmanager
    def db(self):
        yield self.con

    def run_on(self, entries):
        out = unified_index.collapse_reihen(self.db, entries)
        return {e['title']: e for e in out}

    def test_one_tile_per_name_with_own_film_works_and_merged_titles(self):
        got = self.run_on([entry('Praxis: Film 1', 'a1'), entry('Praxis: Film 2', 'a2'), entry('Praxis: Film 3', 'b1'),
                           entry('Mord am Deich', 't1'), entry('Kinder der Nacht', 't2'),
                           entry('Tatort: Azra', 'm1'), entry('Tatort – Angezählt', 'm2'), entry('Tatort Matterhorn', 'm3'),
                           entry('Maria Wern: Die Tote', 'w1', other=True), entry('Maria Wern: Spuren', 'w2'),
                           entry('Maria Wern: Ende', 'w3')])
        self.assertEqual(got['Praxis mit Meerblick']['mehrteiler'], {'query': 'Praxis mit Meerblick', 'parts': 3, 'reihe': True})
        self.assertEqual(got['Tatort']['mehrteiler']['parts'], 4)          # 2 Reihenfilme + 2 eigene Filmwerke
        self.assertEqual(got['Tatort']['offers'][0]['id'], 't1')           # öffnet über einen Reihenfilm
        self.assertIn('Tatort Matterhorn', got)                            # ohne Trenner nicht sicher → einzeln
        self.assertNotIn('Tatort: Azra', got)
        self.assertEqual(got['Maria Wern, Kripo Gotland']['mehrteiler']['parts'], 3)
        self.assertEqual(len(got), 4)

    def test_parts_sequels_versions_and_cut_title(self):
        got = self.run_on([entry('Zärtliche Chaoten – Teil 1', 'z1', 1986), entry('Zärtliche Chaoten – Teil 2', 'z2', 1987),
                           entry('Fremde Verwandte Teil 1/ 2', 'f1'), entry('Fremde Verwandte Teil 2/ 2', 'f2'),
                           entry('Unschuldig (1/2)', 'u1'), entry('Unschuldig (2/2)', 'u2'),
                           entry('Unschuldig (1/2) - Audiodeskription', 'u3'), entry('Unschuldig (2/2)', 'u4')])
        self.assertIn('Zärtliche Chaoten – Teil 1', got);self.assertIn('Zärtliche Chaoten – Teil 2', got)
        self.assertEqual(got['Fremde Verwandte']['mehrteiler'], {'query': 'Fremde Verwandte', 'parts': 2})
        self.assertEqual(got['Unschuldig']['mehrteiler']['parts'], 2)       # Fassungen zählen nicht als Teil
        self.assertEqual(unified_index._part('Fremde Verwandte Teil 1/ 2'), ('Fremde Verwandte', 1))

    def test_ui_opens_the_reihe_as_search_and_default_is_on(self):
        js = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn("showParts(parts.query,parts.reihe?'year':'title')", js)
        self.assertIn("main.reihe||parts?.reihe?(parts?.parts||main.film_count||main.episode_count)+' Filme'", js)
        self.assertIn('UNIFIED_REIHEN=True', (ROOT / 'server.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
