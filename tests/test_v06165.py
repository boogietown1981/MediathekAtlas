"""0.6.165 – Mac-Prüfung 0.6.164 (BEFUND-06163-06164.txt):
* ZDF-tivi und KiKA zählen dieselbe Folge verschoben (Conni S1E5/S1E6, beide 685 s; Checkpoint S5E5/S5E8; Rudis
  S1E1/S1E10): gleicher Titel und gleiche Dauer (±10 s) = dieselbe Folge, auch bei anderer Nummer. Nummern-Titel
  („Folge 5“) und Folgen, die nur den Reihennamen tragen, entscheiden weiter nach Nummern; andere Dauer bleibt getrennt.
* Heidi gesperrt und zurückgenommen – Reihe blieb weg. Wahrscheinliche Ursache: eine Sperre ersetzte eine Freigabe
  (gleicher Schlüssel), Zurücknehmen löschte beides. Jetzt stellt Zurücknehmen die ersetzte Wahl wieder her."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import kids_catalog as kc
import kids_rules
from test_v06164 import show, ep, run
import download_retry as dr
import youtube_downloads as yd


class ShiftedNumbersTests(unittest.TestCase):
    def head(self, title):
        h = show('a', title)
        h['twins'] = [{'source': 'mediatheken', 'series': {'show': 'b'}}]
        return h

    def test_same_title_same_length_other_number_once(self):
        parts = {'a': [ep('mediatheken', 'z5', 'Conni schläft im Kindergarten', 1, 5, 685)],
                 'b': [ep('mediatheken', 'k6', 'Conni schläft im Kindergarten', 1, 6, 690),
                       ep('mediatheken', 'k7', 'Conni lernt Rad fahren', 1, 7, 685)]}
        self.assertEqual([e['title'] for e in run(self.head('Meine Freundin Conni'), parts)],
                         ['Conni schläft im Kindergarten', 'Conni lernt Rad fahren'])

    def test_other_length_number_titles_and_series_name_stay(self):
        parts = {'a': [ep('mediatheken', 't6', 'Der Shredder', 1, 6, 1300), ep('mediatheken', 'f1', 'Folge 5', 1, 5, 600),
                       ep('mediatheken', 'n1', 'Checkpoint', 5, 1, 1471)],
                 'b': [ep('mediatheken', 't106', 'Der Shredder', 1, 106, 1100), ep('mediatheken', 'f2', 'Folge 5', 2, 5, 600),
                       ep('mediatheken', 'n2', 'Checkpoint', 5, 2, 1471)]}
        self.assertEqual(len(run(self.head('Checkpoint'), parts)), 6)


class UndoRestoresTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        kids_rules.ensure(self.c)

    def choice(self, key):
        row = self.c.execute('SELECT choice FROM kids_choices WHERE key=?', (key,)).fetchone()
        return row[0] if row else ''

    def test_block_over_allow_then_undo_restores_allow(self):
        kids_rules.choose(self.c, 'show', 'heidi', 'allow', 'Heidi')
        kids_rules.choose(self.c, 'show', 'heidi', 'block', 'Heidi')
        self.assertEqual(self.choice('show:heidi'), 'block')
        self.assertTrue(kids_rules.blocked_works(self.c, 'heidi') is None)
        result = kids_rules.choose(self.c, 'show', 'heidi', '')
        self.assertEqual((result['choice'], result.get('restored')), ('allow', True))
        self.assertTrue(kids_rules.show_allowed(self.c, 'heidi'))
        kids_rules.choose(self.c, 'show', 'heidi', '')                 # zweites Zurücknehmen: ganz weg
        self.assertEqual(self.choice('show:heidi'), '')

    def test_plain_block_undo_deletes_and_twins_restore(self):
        kids_rules.choose(self.c, 'show', 'neu', 'block', 'Neu')
        kids_rules.choose(self.c, 'show', 'neu', '')
        self.assertEqual(self.choice('show:neu'), '')
        kids_rules.choose(self.c, 'show', 'heidi-zdf', 'allow', 'Heidi')
        head = show('heidi', 'Heidi')
        head['block'] = kc.block_target(head)
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'heidi-zdf'}, 'block': {'kind': 'show', 'id': 'heidi-zdf'}}]
        with mock.patch.dict(kc._CACHE, {'/r': (0, {'movies': [], 'series': [head]})}):
            kc.apply_to_twins(self.c, '/r', 'show', 'heidi', 'block', 'Heidi')
            kids_rules.choose(self.c, 'show', 'heidi', 'block', 'Heidi')
        self.assertEqual(self.choice('show:heidi-zdf'), 'block')
        kc.apply_to_twins(self.c, '/r', 'show', 'heidi', '', 'Heidi')
        kids_rules.choose(self.c, 'show', 'heidi', '')
        self.assertEqual((self.choice('show:heidi'), self.choice('show:heidi-zdf')), ('', 'allow'))

    def test_old_table_gets_column(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.execute('CREATE TABLE kids_choices(key TEXT PRIMARY KEY, choice TEXT NOT NULL, title TEXT, kind TEXT, updated REAL)')
        c.execute("INSERT INTO kids_choices VALUES('show:x','allow','X','show',1)")
        kids_rules.ensure(c)
        self.assertEqual(kids_rules.choose(c, 'show', 'x', 'block', 'X')['choice'], 'block')
        self.assertEqual(kids_rules.choose(c, 'show', 'x', '')['choice'], 'allow')


class StallChallengeTests(unittest.TestCase):
    """Air-Diagnose 27.11. abends (Y5): Download blieb stehen, der Wächter brach ab, ohne die n-challenge zu sehen."""
    def test_stall_with_challenge_renews_ytdlp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        killed = threading.Event()

        class Silent:
            def __iter__(self):
                killed.wait(10)
                return iter(())

        class Proc:
            def __init__(self, args, stderr=None, **kw):
                stderr.write('WARNING: [youtube] abcdefghijk: n challenge solving failed: Some formats may be missing\n')
                self.stdout = Silent()

            def wait(self):
                return -9

            def poll(self):
                return -9 if killed.is_set() else None

            def kill(self):
                killed.set()
        row = {'_youtube_home': str(root), '_video_id': 'abcdefghijk', '_container': 'mp4', '_abo': 1}
        refreshed = []
        with mock.patch.object(yd, 'enabled', return_value=True), \
                mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'eingerichtet')), \
                mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 6)), \
                mock.patch.object(yd, 'find_js_runtime', return_value=('deno', '/d')), \
                mock.patch.object(yd, 'refresh_for_challenge', side_effect=lambda r, t: refreshed.append(1) or '2026.11.23'), \
                mock.patch.object(yd, 'STALL_START', 1), mock.patch('downloads.require_space'), \
                mock.patch('downloads.tool', return_value=None), mock.patch('diagnostics.event'):
            started = time.monotonic()
            with self.assertRaises(dr.RetryLater) as ctx:
                yd.fetch(row, str(root / 'out.mkv'), root, lambda *a, **k: None, lambda: False, runner=Proc)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(refreshed, [1])
        self.assertIn('n challenge', str(ctx.exception))
        self.assertIn('2026.11.23', str(ctx.exception))


class TimingTests(unittest.TestCase):
    def test_finish_reports_step_timings(self):
        out = kc._finish(None, None, {'movies': [], 'series': []}, False, {'collect_movies': 1.0})
        self.assertIn('collect_movies', out['timings'])
        self.assertIn('kids_shows', out['timings'])
        src = (Path(__file__).resolve().parents[1] / 'kids_catalog.py').read_text(encoding='utf-8')
        self.assertIn("steps=value.get('timings') or {}", src)


if __name__ == '__main__':
    unittest.main()
