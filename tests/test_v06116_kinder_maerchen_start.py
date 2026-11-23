"""Vorbereitung 0.6.116 (Prüfvermerk Kinderecke 0.6.115, 23.11.2026):
* Gegenrichtung: echte Märchen-/Kinderfilme standen auf der Warteliste (Aschenputtel, Der Hirsch mit dem goldenen
  Geweih, Die Seekönigin, Vier zauberhafte Schwestern, Heidi und Peter, Huck Finn, Der kleine Lord, Grüße vom Mars,
  Die Baumhauskönige). Märchen-/Kinderbuchtitel ersetzen den Familien-Hinweis; FSK bleibt Pflicht. „Gevatter Tod“ wartet.
* Startphase: neun Kinderserien fehlten 2,5 min, weil der gemeinsame Index zwischen zwei Seiten neu aufgebaut wurde."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog, kids_rules, unified_index  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402
from test_v0646_kids_catalog import portal  # noqa: E402


class FairyTales(Mixed):
    def test_tale_titles_without_family_genre_visible_with_rating(self):
        films = (('asche', 'Aschenputtel', ['Fantasy']),
                 ('hirsch', 'Der Hirsch mit dem goldenen Geweih', ['Fantasy', 'Abenteuer']),
                 ('see', 'Die Seekönigin', ['Fantasy']),
                 ('vier', 'Vier zauberhafte Schwestern', ['Fantasy', 'Familie']),
                 ('heidi', 'Heidi und Peter', ['Drama', 'Familie']),
                 ('huck', 'Die Abenteuer des Huck Finn', ['Abenteuer', 'Familie']),
                 ('lord', 'Der kleine Lord', ['Drama', 'Familie']),
                 ('mars', 'Grüße vom Mars', ['Komödie', 'Familie']),
                 ('baum', 'Die Baumhauskönige', ['Abenteuer', 'Familie']),
                 ('tod', 'Gevatter Tod', ['Fantasy', 'Familie']),
                 ('fanta', 'Ein Fantasyfilm', ['Fantasy']),
                 ('ohne', 'Rotkäppchen', ['Fantasy']))                 # ohne belegte Freigabe
        for i, (wid, title, genres) in enumerate(films):
            self.add(wid, title, genres, ref='tt74000%02d' % i, channel='ARD')
        self.ages(**{'tt74000%02d' % i: 6 for i in range(len(films) - 1)})
        d = self.data()
        self.assertEqual(sorted(t['title'] for t in d['movies']),
                         ['Aschenputtel', 'Der Hirsch mit dem goldenen Geweih', 'Der kleine Lord', 'Die Abenteuer des Huck Finn',
                          'Die Baumhauskönige', 'Die Seekönigin', 'Grüße vom Mars', 'Heidi und Peter',
                          'Vier zauberhafte Schwestern'])
        self.assertEqual({t['weg'] for t in d['movies']}, {'alter'})
        with self.db() as c:
            waiting = {w['title'] for w in kids_rules.waiting(c)}
        self.assertIn('Gevatter Tod', waiting)
        self.assertIn('Rotkäppchen', waiting)

    def test_tale_title_with_adult_genre_stays_out(self):
        self.add('grimm', 'Schneewittchen und der Jäger', ['Fantasy', 'Action', 'Abenteuer'], ref='tt7500001')
        self.add('horror', 'Hänsel und Gretel: Hexenjäger', ['Fantasy', 'Horror'], ref='tt7500002')
        self.ages(tt7500001=12, tt7500002=12)
        self.assertEqual(self.data()['movies'], [])


class PagingDuringRebuild(unittest.TestCase):
    def test_list_reread_when_index_changes_between_pages(self):
        kids_catalog.invalidate()
        names = ['Serie %03d' % i for i in range(120)]
        state = {'calls': 0}

        def page(root, db, kind='movies', genre='', offset=0, **kw):
            if kind != 'series':
                return {'items': [], 'total': 0, 'pending': [], 'index': 1}
            state['calls'] += 1
            # erster Durchlauf: nach Seite 1 wird der Index neu gebaut, 20 Titel vorn verschwinden (Namensheilung)
            rebuilt = state['calls'] > 1
            rows = names[20:] if rebuilt else names
            entries = [{'cats': ['Kinder'], 'title': n,
                        'offers': [portal('pluto', 'pl-%s' % n[-3:], n, kind='series', source_genres=['Kinder'])]} for n in rows]
            return {'items': [{'title': e['title'], 'offers': e['offers']} for e in entries[offset:offset + 48]],
                    'total': len(entries), 'pending': [], 'index': 2 if rebuilt else 1}
        d = kids_catalog.build('/r', None, page=page)
        # ohne Neulesen: Serie 000–047 aus dem alten Stand, dann ab Seite 2 versetzt – Serie 048–067 fehlen
        self.assertEqual([t['title'] for t in d['series']], names[20:])
        self.assertFalse(d['pending'])

    def test_page_reports_index_serial(self):
        key = ('test-0716',)
        unified_index._build_into(key, lambda: {'entries': []})
        first = unified_index._CACHE[key][1]['serial']
        unified_index._build_into(key, lambda: {'entries': []})
        self.assertGreater(unified_index._CACHE[key][1]['serial'], first)
        unified_index._CACHE.pop(key, None)


if __name__ == '__main__':
    unittest.main()
