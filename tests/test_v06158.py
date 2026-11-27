"""0.6.158: Befunde Mac-Prüfung 0.6.157 (BEFUND-06157.txt), nachgebaut mit Angeboten in der Form des echten Index
(unified_index._portal_offers: {'source','title','year','item'} mit Plattform-Genres in categories/source_genres/genre):
„Zärtliche Chaoten – Teil 1/2“ (Pluto TV, Komödie, 1986/1987, ohne IMDb) und „Freitag der 13“ (Rakuten/Joyn/Netzkino,
Horror) sind Fortsetzungen und bleiben einzeln; echte Mehrteiler bleiben zusammen. Dazu „Die wilde Natur“ (YouTube-Bild)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog  # noqa: E402
import test_v06152  # noqa: E402
import test_v06154  # noqa: E402
import unified_index  # noqa: E402


def portal(source, title, year, genre='', categories=()):
    item = {'id': '%s-%s' % (source, abs(hash((title, year))) % 10**8), 'title': title, 'year': year, 'kind': 'movie',
            'genre': genre, 'categories': list(categories), 'source_genres': [g for g in genre.split(', ') if g]}
    return {'title': title, 'year': year, 'offers': [{'source': source, 'title': title, 'year': year, 'item': item}]}


class PortalSequels(test_v06154.Collapse):
    test_one_tile_per_name_with_own_film_works_and_merged_titles = test_parts_sequels_versions_and_cut_title = None
    test_ui_opens_the_reihe_as_search_and_default_is_on = None

    def test_befund_06157(self):
        got = self.run_on([
            portal('pluto', 'Zärtliche Chaoten – Teil 1', 1986, 'Komödie', ['Komödie']),
            portal('pluto', 'Zärtliche Chaoten – Teil 2', 1987, 'Komödie', ['Komödie']),
            portal('rakuten', 'Freitag der 13 – Teil 2', 1981, 'Horror', ['Horror']),
            portal('joyn', 'Freitag der 13. Teil 3 – Und wieder ist Freitag der 13.', 1982, 'Horror, Thriller', ['Horror']),
            portal('netzkino', 'Freitag der 13. Teil 4 – Das letzte Kapitel', 1984, 'Horror', ['Horror']),
            portal('netzkino', 'Freitag der 13. Teil 5 – Ein neuer Anfang', 1985, 'Horror', ['Horror']),
            # echte Mehrteiler aus derselben Prüfung
            portal('netzkino', 'Vera Brühne Teil 1', 2001, 'Crime, Drama', ['Krimi', 'Drama']),
            portal('netzkino', 'Vera Brühne Teil 2', 2001, 'Crime, Drama', ['Krimi', 'Drama']),
            portal('plex', 'Monster High Webisodes: Volume 1 (1/2)', 2010, 'Animation, Kinder', ['Animation']),
            portal('plex', 'Monster High Webisodes: Volume 1 (2/2)', 2011, 'Animation, Kinder', ['Animation']),
            portal('netzkino', 'DDR Traktoren im Einsatz Teil 1', 2007, 'Dokumentation', ['Dokumentation']),
            portal('netzkino', 'DDR Traktoren im Einsatz Teil 4', 2010, 'Dokumentation', ['Dokumentation'])])
        for single in ('Zärtliche Chaoten – Teil 1', 'Zärtliche Chaoten – Teil 2', 'Freitag der 13 – Teil 2',
                       'Freitag der 13. Teil 4 – Das letzte Kapitel'):
            self.assertIn(single, got)
        self.assertNotIn('Freitag der 13', got)
        self.assertEqual(got['Vera Brühne']['mehrteiler']['parts'], 2)
        self.assertEqual(got['Monster High Webisodes: Volume 1']['mehrteiler']['parts'], 2)
        self.assertEqual(got['DDR Traktoren im Einsatz']['mehrteiler']['parts'], 2)

    def test_offer_genres(self):
        self.assertEqual(unified_index._offer_genres({'genre': 'Horror, Thriller', 'categories': ['Krimi']}), {'horror', 'thriller', 'krimi'})


class WildeNatur(test_v06152.YoutubePictures):
    test_phrase_match_only = test_show_without_sender_page_takes_youtube_picture_and_old_failures_retry = None
    test_budget_stop_is_reported_for_early_retry = None

    def test_abo_part_may_end_with_the_name(self):
        self.seed_youtube(abo_titles=['Zeitreise am Gletscher | Anna, Paula, Pia und die wilde Natur | BR'],
                          item_titles=['Abenteuer | Pia und die wilde Natur'])
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Die wilde Natur'), 'https://i.ytimg.com/vi/v0000000000/hqdefault.jpg')


class RealCandidates(unittest.TestCase):
    """Alle 86 Mehrteiler-Kandidaten der Pro-Kopie (Mac, 27.11.2026, werkzeuge/mehrteiler_dump.py, Genres je Quelle):
    nur Freitag der 13, Zärtliche Chaoten und The Lies We Tell (Part 2 2012 / Part 3 2014, eigene Spielfilme) bleiben einzeln."""
    def test_rule_against_all_groups(self):
        import csv
        import json
        import sqlite3
        from contextlib import contextmanager
        rows = list(csv.DictReader(open(ROOT / 'tests' / 'data' / 'mehrteiler-kandidaten-06157.tsv', encoding='utf-8'), delimiter='\t'))
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE works(id TEXT, show_key TEXT, title TEXT, kind TEXT, meta TEXT)')

        @contextmanager
        def db():
            yield con
        entries = []
        for n, r in enumerate(rows):
            genres = [g for g in r['genres'].split(',') if g]
            offers = []
            for source in r['quellen'].split(','):
                if source == 'mediatheken':
                    con.execute('INSERT INTO works VALUES(?,?,?,?,?)', ('w%d' % n, '', r['titel'], 'movie',
                                json.dumps({'genres': [g for g in genres if ':' not in g], 'imdb_id': r['imdb']})))
                    offers.append({'source': 'mediatheken', 'id': 'w%d' % n})
                else:
                    offers.append({'source': source, 'item': {'imdb_id': r['imdb'],
                                   'categories': [g.split(':', 1)[1] for g in genres if g.startswith(source + ':')]}})
            entries.append({'title': r['titel'], 'year': int(r['jahr']) if r['jahr'] else None, 'offers': offers})
        out = unified_index.collapse_reihen(db, entries)
        merged = {unified_index.title_key(e['title']) for e in out if e.get('mehrteiler')}
        groups = {unified_index.title_key(r['gruppe']) for r in rows}
        self.assertEqual(groups - merged, {'freitagder13', 'zartlichechaoten', 'thelieswetellbutthesecretswekeep'})
        self.assertEqual(len(merged), 79)


if __name__ == '__main__':
    unittest.main()
