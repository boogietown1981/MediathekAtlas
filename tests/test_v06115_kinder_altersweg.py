"""0.6.115 (Mac-Prüfung Kinderecke 0.6.114, 23.11.2026):
* K13: „Trauung mit Hindernissen“ (3sat, nur Familie, FSK 6) blieb über den Altersweg. Festlegung: auf dem Altersweg
  braucht ein Film ohne Kindersender immer ein eigenes Kindersignal (Animation, Märchen, Märchen-/Kinderbuch-Titel,
  bekannte Kinderreihe); Familie + Freigabe allein reicht nicht.
* Liste wackelte zwischen zwei Skriptläufen (548 → 553 Filme, 629 → 614 Serien): Stempel der Liste und Diagnose
  kids_list_changed, damit die Prüfung einen Neuaufbau erkennt."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog, kids_rules  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


class AgePathNeedsOwnSignal(Mixed):
    def test_family_alone_waits_classics_stay(self):
        films = (('trauung', 'Trauung mit Hindernissen', ['Familie']),
                 ('immenhof', 'Hochzeit auf Immenhof', ['Familie', 'Romantik']),
                 ('urlaub', 'Familienurlaub', ['Familie', 'Komödie']),
                 ('eugen', 'Mein Name ist Eugen', ['Familie', 'Komödie']),          # Kinderbuch-Vorlage
                 ('hotz', 'Der Räuber Hotzenplotz', ['Familie']),
                 ('haensel', 'Hänsel und Gretel', ['Familie', 'Fantasy']),
                 ('nase', 'Zwerg Nase', ['Familie', 'Fantasy']),
                 ('bibi', 'Bibi & Tina: Voll verhext!', ['Familie', 'Komödie']),
                 ('trick', 'Ein Trickfilm', ['Familie', 'Animation']))
        for i, (wid, title, genres) in enumerate(films):
            self.add(wid, title, genres, ref='tt72000%02d' % i, channel='3sat')
        self.ages(**{'tt72000%02d' % i: 6 for i in range(len(films))})
        d = self.data()
        self.assertEqual(sorted(t['title'] for t in d['movies']),
                         ['Bibi & Tina: Voll verhext!', 'Der Räuber Hotzenplotz', 'Ein Trickfilm', 'Hänsel und Gretel',
                          'Mein Name ist Eugen', 'Zwerg Nase'])
        with self.db() as c:
            waiting = {w['title']: w['reason'] for w in kids_rules.waiting(c)}
        self.assertIn('kein eigenes Kindersignal', waiting['Trauung mit Hindernissen'])
        self.assertIn('Familienurlaub', waiting)

    def test_known_series_topic_counts_as_own_signal(self):
        self.add('sechs', 'Die Gänseprinzessin', ['Familie'], ref='tt7300001', channel='ARD', topic='Sechs auf einen Streich')
        self.ages(tt7300001=0)
        self.assertEqual([t['title'] for t in self.data()['movies']], ['Die Gänseprinzessin'])


class Stamp(Mixed):
    def shelf(self):
        import time, unified_index, catalog
        unified_index.invalidate(); catalog.invalidate_listings(drop=True)
        for _ in range(100):
            kids_catalog.invalidate()
            d = kids_catalog.shelf(self.root, self.db, modules={}, fresh=True)
            if not d['pending']:
                return d
            time.sleep(0.1)
        self.fail('Liste wurde nicht fertig')

    def test_stamp_changes_with_list_and_change_is_logged(self):
        kids_catalog._LAST.clear()
        self.add('rabe', 'Der kleine Rabe Socke', ['Kinder'])
        first = self.shelf()
        self.assertTrue(first['stamp'])
        self.assertEqual(kids_catalog.with_progress(first, {})['stamp'], first['stamp'])
        self.add('maja', 'Die Biene Maja', ['Kinder'])
        with mock.patch('diagnostics.event') as event:
            second = self.shelf()
        self.assertNotEqual(first['stamp'], second['stamp'])
        calls = [c for c in event.call_args_list if c.args and c.args[0] == 'kids_list_changed']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs['added'], 1)
        self.assertIn('Die Biene Maja', calls[0].kwargs['added_titles'][0])


if __name__ == '__main__':
    unittest.main()
