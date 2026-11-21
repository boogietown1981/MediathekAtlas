"""0.6.73: Mac-Prüfung 0.6.71 – dreistellige "Episode N" (215–999) blieben offen.

core.EPISODE liest "Episode 500" als Folge 500 ohne Staffel; die Metadaten tragen also
episode=500, season=None. Die absolute Nummernsuche lief bisher nur ohne jede Folgennummer.
Die Testhilfe aus 0.6.70 setzte episode=None fest und verdeckte das; hier kommt die Folge
wie in der App aus core.identify.
"""
import unittest

import core
import imdb_archive
from test_v0670 import Soaps


class ThreeDigitNumbers(Soaps):
    def real(self, title, topic, ref, **kw):
        ident = core.identify({'title': title, 'topic': topic})
        return self.match(title, topic, ref, season=ident['season'], episode=ident['episode'], **kw)

    def test_identify_reads_three_digits_as_episode_without_season(self):
        ident = core.identify({'title': 'Episode 150', 'topic': 'Sturm der Liebe'})
        self.assertEqual((ident['season'], ident['episode']), (None, 150))

    def test_three_digit_episode_n_is_matched(self):
        for title in ('Episode 150', 'Folge 150', 'Episode 150 (Audiodeskription)'):
            with self.subTest(title=title):
                chosen = self.real(title, 'Sturm der Liebe', 'tt0479846', timestamp=1782086400)  # 22.06.2026
                self.assertIsNotNone(chosen)
                self.assertEqual((chosen['season'], chosen['episode'], chosen['episode_reference_id']), (1, 150, 'tt8000150'))

    def test_guards_still_hold_with_a_parsed_episode(self):
        self.assertIsNone(self.real('Episode 3', 'Krimi mit Staffeln', 'tt7000000'))                 # several seasons
        self.assertIsNone(self.real('Episode 150', 'Sturm der Liebe', 'tt0479846', duration=200))     # short clip
        self.assertIsNone(self.real('Episode 150 · 17.08.15 | x', 'Sturm der Liebe', 'tt0479846'))   # title year 2015
        # a different number from another source contradicts the title
        self.assertIsNone(self.match('Folge 151', 'Sturm der Liebe', 'tt0479846', episode=150))
        # with a season the broadcaster's SxxExx wins, never the absolute fallback
        self.assertIsNone(self.match('Episode 150', 'Sturm der Liebe', 'tt0479846', season=2, episode=150))
        self.assertIsNone(imdb_archive.absolute_episode({'title': 'Folge 3/10'}, {}))


if __name__ == '__main__':
    unittest.main()
