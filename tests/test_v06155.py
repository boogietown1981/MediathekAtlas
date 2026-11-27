"""0.6.155: Hinweise aus den Mac-Prüfungen 0.6.152–0.6.154 (BEFUND-06152/06154, PRUEFVERMERK-06153).
(a) Jahresregel trennte echte Mehrteiler (Traktorgiganten Teil 1–4, 2010/2011); (b) Kinderecke-Bilder ohne Ergebnis, wenn das
Sender-Stundenlimit erreicht ist (Air: asked 1, stopped true); (c) Zeitanzeige „3:18 / 3:00“ am Ende der Leiste;
(d) merge-Anteile (Reihen, Geladen) im Ereignis unified_index_built."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import broadcaster  # noqa: E402
import kids_catalog  # noqa: E402
import unified_index  # noqa: E402
import test_v06152  # noqa: E402
import test_v06154  # noqa: E402
from test_v06154 import entry  # noqa: E402


class Sequels(test_v06154.Collapse):
    test_one_tile_per_name_with_own_film_works_and_merged_titles = test_parts_sequels_versions_and_cut_title = None
    test_ui_opens_the_reihe_as_search_and_default_is_on = None

    def movie(self, wid, imdb):
        self.con.execute('INSERT INTO works VALUES(?,?,?,?,?)', (wid, '', '', 'movie', json.dumps({'imdb_id': imdb})))

    def test_years_alone_do_not_split_but_own_imdb_films_do(self):
        self.movie('z1', 'tt0091262');self.movie('z2', 'tt0093258')
        got = self.run_on([entry('Traktorgiganten Teil 1', 'k1', 2010), entry('Traktorgiganten Teil 2', 'k2', 2010),
                           entry('Traktorgiganten Teil 3', 'k3', 2011), entry('Traktorgiganten Teil 4', 'k4', 2011),
                           entry('Zärtliche Chaoten – Teil 1', 'z1', 1986), entry('Zärtliche Chaoten – Teil 2', 'z2', 1987)])
        self.assertEqual(got['Traktorgiganten']['mehrteiler']['parts'], 4)
        self.assertIn('Zärtliche Chaoten – Teil 1', got);self.assertIn('Zärtliche Chaoten – Teil 2', got)

    def test_same_imdb_mini_series_stays_together(self):
        self.movie('e1', 'tt0447987');self.movie('e2', 'tt0447987')
        got = self.run_on([entry('Elvis: Teil 1', 'e1', 2005), entry('Elvis: Teil 2', 'e2', 2013)])
        self.assertEqual(got['Elvis']['mehrteiler']['parts'], 2)


class StoppedSenderStillUsesYoutube(test_v06152.YoutubePictures):
    test_phrase_match_only = test_show_without_sender_page_takes_youtube_picture_and_old_failures_retry = None
    test_budget_stop_is_reported_for_early_retry = None

    def test_budget_stop_falls_back_to_youtube(self):
        self.prepare()
        self.shelf()
        self.seed_youtube(abo_titles=['Checker Reportagen: Wie kommt der Strom in die Steckdose?'])

        def full(row):
            raise broadcaster.BudgetExhausted('ARD Mediathek: automatisches Stundenlimit erreicht')
        found, asked, _ = kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=full)
        self.assertEqual((found, asked), (1, 1))
        self.assertTrue(kids_catalog.LAST_FETCH['stopped'])
        self.assertTrue(self.tile(self.shelf())['poster'].startswith('https://i.ytimg.com/vi/'))


class Wiring(unittest.TestCase):
    def test_player_clamps_and_merge_parts_are_logged(self):
        js = (ROOT / 'web' / 'player.js').read_text(encoding='utf-8')
        self.assertIn("const p=S.offset+(video.currentTime||0),d=duration();return d?Math.min(p,d):p;", js)
        src = (ROOT / 'unified_index.py').read_text(encoding='utf-8')
        self.assertIn("seconds['reihen'] = round(", src);self.assertIn("seconds['local'] = round(", src)


if __name__ == '__main__':
    unittest.main()
