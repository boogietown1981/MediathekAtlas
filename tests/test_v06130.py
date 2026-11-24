"""0.6.130 (Mac-Prüfung 0.6.129): die Leerzeichen-Regel schrieb Reihen in Großbuchstaben um (Nachtcafé → NACHTCAFÉ,
Presseclub → PRESSECLUB) und „Betrifft“ → „betrifft: ...“."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
from test_v06127 import offer, SpacingVariants  # noqa: E402


class CaseStays(SpacingVariants):
    def test_capitals_never_win(self):
        self.assertEqual(catalog.best_spelling({'Nachtcafé': 1, 'NACHTCAFÉ': 9}), 'Nachtcafé')
        self.assertEqual(catalog.best_spelling({'eishockeyaktuell': 9, 'Eishockey aktuell': 1}), 'Eishockey aktuell')
        self.assertEqual(catalog.best_spelling({'super.markt': 3, 'SUPER.MARKT': 1}), 'super.markt')

    def test_case_variants_in_one_reihe_are_left_alone(self):
        self.series([offer('A%d' % i, 'Nachtcafé', 'SWR', i) for i in range(3)] + [offer('B1', 'NACHTCAFÉ', 'SWR', 9)] +
                    [offer('C1', 'Nacht café', 'SWR', 10)])
        catalog.merge_spacing_variants(self.c)
        titles = {t: n for (t, _), n in self.shows().items()}
        self.assertNotIn('NACHT CAFÉ', titles)
        self.assertEqual(titles.get('Nachtcafé', 0) + titles.get('NACHTCAFÉ', 0), 5)   # „Nacht café“ joined, case untouched
        self.assertEqual(titles.get('NACHTCAFÉ'), 1)
        self.assertNotIn('Nacht café', titles)   # the spacing variant joined
        self.assertEqual(catalog.respace_show_titles(self.c), {})

    def test_trailing_punctuation_is_no_word_break(self):
        self.series([offer('A%d' % i, 'Betrifft', 'SWR', i) for i in range(2)])
        self.c.execute("UPDATE works SET topic='betrifft: ...'")
        self.assertEqual(catalog.respace_show_titles(self.c), {})


if __name__ == '__main__':
    unittest.main()
