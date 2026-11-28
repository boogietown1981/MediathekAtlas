"""0.6.121 (Björn, 23.11.2026, Bildschirmfoto der Kinderecke): Kacheln mit Anfangsbuchstaben statt Bild („Animanimals“
einmal mit, einmal ohne Bild, „Anna auf dem Bauernhof“, „Carolin testet“, „Die wilde Natur“), eine Doku unter
„Zeichentrick“, die oberste Reihe schimmerte unscharf unter der Kopfleiste durch."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402
from test_v0646_kids_catalog import fake_page, portal  # noqa: E402


class Pictures(Mixed):
    def test_series_tile_takes_picture_of_another_episode(self):
        self.series('show:anna', 'Anna auf dem Bauernhof', [(3, 'KiKA', [], 'Folge %d')])
        with self.db() as c:
            c.execute("UPDATE works SET meta=json_set(meta,'$.poster','https://img.example.org/anna.jpg') WHERE id='show:anna-2'")
        d = self.data()
        tile = next(t for t in d['series'] if t['series']['show'] == 'show:anna')
        self.assertEqual(tile['poster'], 'https://img.example.org/anna.jpg')

    def test_same_title_shares_picture_and_other_offer_counts(self):
        series = [{'cats': ['Kinder'], 'title': 'Animanimals',
                   'offers': [portal('pluto', 'pl-1', 'Animanimals', kind='series', source_genres=['Kinder'], poster=''),
                              portal('plex', 'px-1', 'Animanimals', kind='series', source_genres=['Kinder'],
                                     poster='https://img.example.org/a1.jpg')]},
                  {'cats': ['Kinder'], 'title': 'Animanimals!',
                   'offers': [portal('pluto', 'pl-2', 'Animanimals!', kind='series', source_genres=['Kinder'], poster='')]}]
        kids_catalog.invalidate()
        d = kids_catalog.build('/r', None, page=fake_page({'series': series}))
        # 0.6.162 (Björn 27.11.: „Animanimals“ doppelt): gleichnamige Reihen sind EINE Kachel mit dem Bild, die zweite hängt an
        self.assertEqual([t['poster'] for t in d['series']], ['https://img.example.org/a1.jpg'])
        self.assertEqual([tw['series'] for tw in d['series'][0]['twins']], [{'id': 'pl-2'}])

    def test_documentary_never_in_cartoon_group(self):
        entry = {'title': 'Asterix und Co. – Die Comicwelten des Albert Uderzo',
                 'offers': [portal('pluto', 'pl-9', 'Asterix und Co.', source_genres=['Animation', 'Documentary'])]}
        self.assertEqual(kids_catalog.group_of(entry), 'wissen')
        entry = {'title': 'Asterix und Co.', 'offers': [portal('plex', 'px-9', 'Asterix', categories=['Animation', 'Dokumentation'])]}
        self.assertEqual(kids_catalog.group_of(entry), 'wissen')
        self.assertEqual(kids_catalog.group_of({'title': 'Peppa Wutz', 'offers': [portal('plex', 'px-8', 'Peppa Wutz', categories=['Animation'])]}), 'trick')


class Header(unittest.TestCase):
    def test_header_is_opaque(self):
        css = (ROOT / 'web' / 'kids.css').read_text(encoding='utf-8')
        top = css[css.index('.kids-top{'):css.index('}', css.index('.kids-top{'))]
        self.assertNotIn('rgba(27,20,70,0)', top + css[css.index('.kids-top{'):css.index('.kids-top{') + 400])


if __name__ == '__main__':
    unittest.main()
