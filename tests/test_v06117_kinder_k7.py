"""Vorbereitung 0.6.117 (Mac-Prüfung 0.6.116, K7, 23.11.2026): „Gevatter Tod“ (MDR 1980, nur Fantasy, FSK 6, Märchen-Thema)
war über den Altersweg sichtbar; „Aschenputtel“ (Familie/Fantasy/Romantik, FSK 0) stand wegen „Romantik“ auf der
Warteliste."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_rules  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


class K7(Mixed):
    def test_dark_tale_waits_romantic_tale_visible(self):
        self.add('tod', 'Gevatter Tod', ['Fantasy'], ref='tt7600001', channel='MDR', topic='DDR-Märchenfilme')
        self.add('asche', 'Aschenputtel', ['Familie', 'Fantasy', 'Romantik'], ref='tt7600002', channel='ARD')
        self.add('holle', 'Frau Holle', ['Fantasy'], ref='tt7600003', channel='MDR', topic='DDR-Märchenfilme')
        self.add('pilcher', 'Liebe in Cornwall', ['Familie', 'Romantik'], ref='tt7600004', channel='ZDF')
        self.add('jaeger', 'Schneewittchen und der Jäger', ['Fantasy', 'Action'], ref='tt7600005')
        self.ages(tt7600001=6, tt7600002=0, tt7600003=6, tt7600004=0, tt7600005=12)
        d = self.data()
        self.assertEqual(sorted(t['title'] for t in d['movies']), ['Aschenputtel', 'Frau Holle'])
        with self.db() as c:
            waiting = {w['title'] for w in kids_rules.waiting(c)}
            self.assertIn('Gevatter Tod', waiting)
            kids_rules.choose(c, 'work', 'tod', 'allow', 'Gevatter Tod')    # Eltern können freigeben
        self.assertIn('Gevatter Tod', [t['title'] for t in self.data()['movies']])

    def test_dark_tale_on_kids_channel_unchanged(self):
        self.add('tod', 'Gevatter Tod', ['Fantasy'], ref='tt7700001', channel='KiKA')
        self.ages(tt7700001=6)
        self.assertEqual([t['title'] for t in self.data()['movies']], ['Gevatter Tod'])


if __name__ == '__main__':
    unittest.main()
