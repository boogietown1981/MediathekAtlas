"""0.6.112 (Mac-Prüfung 0.6.109, 23.11.2026): Zulassungsweg je Folge, Jugendformate, leere Reihen, Altersgrenze zurück.

Befunde: „Young Crime“ zeigte 5 ZDF-Folgen („Böllern und Zündeln“, „Geld oder Schläge!“ …), „POV · Deine Geschichte
zählt“ eine WDR-Folge („Rechtsextremismus unter Jugendlichen“) – über die Kinder-Regel je Werk; „#Ukraine · Mein Land
im Krieg“ stand mit 0 Folgen in der Liste; 231 TOGGO- und 18 Rakuten-Reihen öffneten ohne Folge (Kopierschutz);
Altersgrenze 6 → 12 ließ Netzkino bei 270 (gespeicherte Plattform-Ansicht ohne Grenze im Stempel).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import categories, kids_catalog, unified_index  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402
from test_v0646_kids_catalog import fake_page, portal  # noqa: E402


class Paths(Mixed):
    def test_youth_formats_only_kids_channel_episodes(self):
        self.series('show:young', 'Young Crime', [(2, 'KiKA', [], 'KiKA-Folge %d'),
                                                  (5, 'ZDF', ['Kinder'], 'Böllern und Zündeln %d')])   # Kinder-Regel je Werk
        self.series('show:pov', 'POV · Deine Geschichte zählt', [(2, 'KiKA', [], 'Mut %d'),
                                                                 (1, 'WDR', ['Kinder'], 'Rechtsextremismus unter Jugendlichen %d')])
        self.series('show:echt', 'ECHT', [(4, 'ZDF', ['Kinder'], 'Reportage %d')])                  # ohne Kindersender
        with self.db() as c:   # wie auf der Prüfkopie: ZDF/WDR-Folgen erkannt, Referenz-Genre Kinder
            c.execute("UPDATE works SET state='identified' WHERE id IN ('show:young-3','show:young-4','show:young-5','show:young-6',"
                      "'show:young-7','show:pov-3') OR show_key='show:echt'")
        d = self.data()
        self.assertEqual({ch for _, ch in self.episodes(d, 'show:young')}, {'KiKA'})
        self.assertEqual({ch for _, ch in self.episodes(d, 'show:pov')}, {'KiKA'})
        self.assertNotIn('show:echt', [t['series']['show'] for t in d['series']])
        with self.db() as c:
            self.assertFalse(kids_catalog.work_allowed(c, 'show:young-3'))
            self.assertTrue(kids_catalog.work_allowed(c, 'show:young-1'))

    def test_mixed_kids_programme_of_other_channels_keeps_documented_path(self):
        self.series('show:dschungel', 'Das Dschungelbuch', [(2, 'KiKA', [], 'KiKA %d'), (2, 'ZDF', ['Kinder'], 'ZDF %d'),
                                                            (2, 'ZDF', [], 'Ohne Einordnung %d')])
        with self.db() as c:   # ZDF-Folgen sind erkannt (TMDB-Serie mit Genre Kinder)
            c.execute("UPDATE works SET state='identified' WHERE show_key='show:dschungel' AND id IN ('show:dschungel-3','show:dschungel-4')")
        d = self.data()
        with self.db() as c:
            eps = kids_catalog.episodes(self.root, c, d, 'mediatheken', 'show:dschungel')['episodes']
        self.assertEqual(sorted((e['title'], e['weg']) for e in eps),
                         [('KiKA 1', 'sender'), ('KiKA 2', 'sender'), ('ZDF 3', 'regel'), ('ZDF 4', 'regel')])

    def test_every_listed_episode_has_a_path(self):
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', [], 'Maus %d')])
        self.series('show:kika', 'Der Krieg und ich', [(2, 'KiKA', [], 'Teil %d')])
        d = self.data()
        with self.db() as c:
            for show in ('show:maus', 'show:kika'):
                for e in kids_catalog.episodes(self.root, c, d, 'mediatheken', show)['episodes']:
                    self.assertIn(e['weg'], ('sender', 'reihe', 'regel', 'anteil', 'freigabe'), e)

    def test_series_without_any_admissible_episode_hidden(self):
        # 0.6.109: Reihe stand mit 0 Folgen in der Liste – alle Folgentitel gesperrt, kein Kindersender
        self.series('show:land', 'Mein Land', [(3, 'rbtv', ['Kinder'], 'Krieg im Osten %d')])
        with self.db() as c:
            c.execute("UPDATE works SET state='identified' WHERE show_key='show:land'")
        self.assertEqual(self.data()['series'], [])


class Platforms(unittest.TestCase):
    def test_unplayable_platform_series_hidden(self):
        kids_catalog.invalidate()
        series = [{'cats': ['Kinder'], 'offers': [portal('toggo', 'tg-1', 'Paw Patrol', kind='series', playable=0)]},
                  {'cats': ['Kinder'], 'offers': [portal('rakuten', 'rk-1', 'Kinderserie', kind='series', playable=0, drm=1)]},
                  {'cats': ['Kinder'], 'offers': [portal('toggo', 'tg-2', 'Spielbar', kind='series', playable=1)]}]
        d = kids_catalog.build('/r', None, page=fake_page({'series': series}))
        self.assertEqual([t['title'] for t in d['series']], ['Spielbar'])

    def test_snapshot_stamp_follows_age_limit(self):
        # server nicht importieren (setzt globale Zustände anderer Tests); die Stempel-Funktion muss die Grenze tragen
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        body = src[src.index('def _snapshot_stamp('):src.index('def platform_context(')]
        self.assertIn('categories.KIDS_MAX_AGE', body)

    def test_build_started_before_invalidate_is_not_stored(self):
        key = ('test-0712',)

        def builder():
            unified_index.invalidate()          # Grenze geändert, während der Bau läuft
            return {'entries': ['alt']}
        unified_index._build_into(key, builder)
        self.assertNotIn(key, unified_index._CACHE)


if __name__ == '__main__':
    unittest.main()
