"""Diagnose Air 23.11.2026 (0.6.116): 18 von 18 3sat-Filmen „… - Spielfilm, Land Jahr“ blieben „prüfen“ – das Jahr aus
dem Titel galt nur für die Suche, nicht für die Entscheidung. Dazu: Altersrunde der Kinderecke bei belegter Datenbank."""
import sqlite3
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402
import kids_rules  # noqa: E402


def film(**kw):
    base = {'kind': 'movie', 'title': 'Lauf Junge lauf', 'year': 2013, 'provider': 'IMDb Offline', 'reference_id': 'tt2085888',
            'similarity': 1.0}
    base.update(kw);return base


class SuffixYear(unittest.TestCase):
    def setUp(self):
        self.m = catalog.seed({'title': 'Lauf Junge lauf - Spielfilm, Deutschland/Frankreich 2013', 'topic': 'Spielfilm',
                               'channel': '3sat', 'duration': 6000, 'description': 'x'})

    def test_same_year_from_the_title_matches_without_running_time(self):
        self.assertIsNone(self.m.get('year'))
        self.assertIsNone(catalog.auto_choice(self.m, [film()]))                       # before: „prüfen“
        self.assertEqual(catalog.auto_choice(catalog.match_meta(self.m), [film()])['reference_id'], 'tt2085888')

    def test_year_off_by_one_still_needs_running_time(self):
        judged = catalog.match_meta(self.m)
        self.assertIsNone(catalog.auto_choice(judged, [film(year=2014)]))
        ok = film(year=2014, runtime_agrees=True, source_duration_seconds=6000)
        self.assertEqual(catalog.auto_choice(judged, [ok])['year'], 2014)

    def test_other_year_or_title_is_never_matched(self):
        judged = catalog.match_meta(self.m)
        self.assertIsNone(catalog.auto_choice(judged, [film(year=2009)]))
        self.assertIsNone(catalog.auto_choice(judged, [film(similarity=.9)]))

    def test_meta_with_own_year_or_series_unchanged(self):
        self.assertIs(catalog.match_meta(dict(self.m, year=2012)).get('year'), 2012)
        s = dict(self.m, kind='series');self.assertIs(catalog.match_meta(s), s)
        plain = catalog.seed({'title': 'Tatort: Borowski', 'topic': 'Tatort', 'channel': 'ARD', 'duration': 5400, 'description': 'x'})
        self.assertIsNone(catalog.match_meta(plain).get('year'))


class KidsAgesBusy(unittest.TestCase):
    def test_busy_round_is_a_warning_and_retried_soon(self):
        events, errors, pauses = [], [], []
        stop = threading.Event()
        def wait(s):
            pauses.append(s)
            return len(pauses) > 2
        stop.wait = wait
        calls = {'n': 0}
        def fetch(db, version, stop=None):
            calls['n'] += 1
            raise sqlite3.OperationalError('database is locked')
        orig = kids_rules.fetch_round;kids_rules.fetch_round = fetch
        try:
            kids_rules.loop(None, stop, event=lambda e, **k: events.append(e), error=lambda e, x: errors.append(e), ready=lambda: True)
        finally:kids_rules.fetch_round = orig
        self.assertEqual(errors, []);self.assertIn('kids_ages_busy', events)
        self.assertEqual(pauses[1:], [kids_rules.BUSY_RETRY, kids_rules.BUSY_RETRY])

    def test_first_round_waits_for_the_heals(self):
        pauses, state = [], {'ready': False}
        stop = threading.Event()
        def wait(s):
            pauses.append(s)
            if len(pauses) == 3:state['ready'] = True
            return len(pauses) > 4
        stop.wait = wait
        orig = kids_rules.fetch_round;kids_rules.fetch_round = lambda *a, **k: 0
        try:kids_rules.loop(None, stop, ready=lambda: state['ready'])
        finally:kids_rules.fetch_round = orig
        self.assertEqual(pauses[:3], [180, 5, 5])


if __name__ == '__main__':
    unittest.main()
