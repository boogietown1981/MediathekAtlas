"""0.6.163 (Björn 27.11.2026: „bei youtube gibt es ziemlich viele Botwarnungen, obwohl wir nicht viel
runterladen“): (a) ein Abo mit Rückstand fragt YouTube nicht mehr alle 20 Minuten nach der Kanalliste,
sondern arbeitet die gemerkten Videos ab und liest die Liste erst nach dem eingestellten Abstand neu;
(c) scheitern mehrere verschiedene Videos nacheinander mit „not available“ (Air-Diagnose 27.11.: 8 Videos,
17 Meldungen, 0 Erfolge), pausieren die YouTube-Downloads einmal gemeinsam statt je Video zu melden;
„YouTube-Zugang prüfen“ hebt die Pause bei Erfolg auf;
(b) „This video is not available“ heißt in den Meldungen nicht mehr „Bot-Sperre“ (eine echte Bot-Prüfung
meldet YouTube mit „confirm you're not a bot“ und bleibt eine Pause)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube_downloads as yd, youtube_abos as ab  # noqa: E402
import download_retry  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW  # noqa: E402
from test_v06159 import FakeProc  # noqa: E402


class BacklogTests(Fixture):
    def setUp(self):
        super().setUp()
        mock.patch.object(ab, 'MAX_QUEUE', 3).start()

    def listings(self):
        return self.api.calls.count('playlistItems')

    def test_backlog_is_worked_off_without_new_listing(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all'}, now=NOW)
        first = ab.check(self.root, abo, now=NOW, request=self.api)
        self.assertEqual((first['queued'], first['pending']), (3, 6))
        lists = self.listings()
        self.assertGreater(lists, 0)
        row = ab.overview(self.root)['abos'][0]
        self.assertEqual(row['next_check'] - NOW, ab.BACKLOG_RECHECK)       # Rückstand: bald wieder dran
        second = ab.check(self.root, abo, now=NOW + ab.BACKLOG_RECHECK, request=self.api)
        self.assertTrue(second['ok'], second)
        self.assertEqual(self.listings(), lists)                            # keine neue Kanalliste
        self.assertEqual((second['listed'], second['queued'], second['pending']), (0, 3, 3))
        # nach dem eingestellten Abstand (3 h) wird die Liste wieder gelesen
        ab.check(self.root, abo, now=NOW + 3 * 3600, request=self.api)
        self.assertGreater(self.listings(), lists)

    def test_without_backlog_and_on_manual_check_the_list_is_read(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all'}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        lists = self.listings()
        ab.change(self.root, abo, {'action': 'check'})                     # „jetzt prüfen“
        ab.check(self.root, abo, now=NOW + 60, request=self.api)
        self.assertGreater(self.listings(), lists)
        lists = self.listings()
        ab.change(self.root, abo, {'include': 'Bluey'})                      # Einstellung geändert
        ab.check(self.root, abo, now=NOW + 120, request=self.api)
        self.assertGreater(self.listings(), lists)

    def test_backlog_skips_the_bot_pause_wait_for_the_list_only(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all'}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        # ohne API-Schlüssel und mit Rückstand: kein yt-dlp-Aufruf für die Liste
        runner = mock.Mock(side_effect=AssertionError('keine Liste erwartet'))
        with mock.patch.object(ab, '_request_for_key', return_value=None):
            result = ab.check(self.root, abo, now=NOW + ab.BACKLOG_RECHECK, runner=runner)
        self.assertTrue(result['ok'], result)
        runner.assert_not_called()

    def test_existing_database_gets_the_column(self):
        db = ab._connect(self.root)
        try:
            self.assertIn('listed', {r[1] for r in db.execute('PRAGMA table_info(youtube_abos)')})
        finally:
            db.close()


class WordingTests(unittest.TestCase):
    NA = 'ERROR: [youtube] abcdefghijk: This video is not available'

    def test_not_available_is_not_called_a_bot_block(self):
        for kw in ({}, {'js_runtime': False}, {'js_runtime': 'deno', 'js_used': True},
                   {'js_runtime': 'deno', 'js_used': False}):
            reason, temporary, pause = yd._failure(self.NA, **kw)
            self.assertNotIn('Bot', reason, kw)
            self.assertIn('This video is not available', reason)
            self.assertEqual((temporary, pause), (True, False))

    def test_real_bot_check_still_pauses(self):
        reason, temporary, pause = yd._failure("ERROR: Sign in to confirm you're not a bot")
        self.assertEqual((temporary, pause), (True, True))


class StreakTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        yd._streak_reset()
        download_retry.clear()
        self.addCleanup(yd._streak_reset)
        self.addCleanup(download_retry.clear)

    def fail(self, video):
        row = {'_youtube_home': self.root, '_video_id': video, '_abo': 7, '_container': 'mp4'}
        with mock.patch.object(yd, 'enabled', return_value=True), \
                mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'eingerichtet')), \
                mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 23)), \
                mock.patch.object(yd, 'find_js_runtime', return_value=('deno', '/d')), \
                mock.patch('downloads.require_space'), mock.patch('downloads.tool', return_value=None), \
                mock.patch('diagnostics.event'):
            with self.assertRaises(download_retry.RetryLater) as ctx:
                yd.fetch(row, str(self.root / 'out.mkv'), self.root, lambda *a, **k: None, lambda: False,
                         runner=lambda args, **kw: FakeProc(args, **kw))
        return ctx.exception

    def test_one_video_is_retried_alone_two_different_pause_youtube(self):
        first = self.fail('abcdefghijk')
        self.assertFalse(first.block)
        self.assertFalse(self.fail('abcdefghijk').block)          # dasselbe Video zählt nicht doppelt
        second = self.fail('bbcdefghijk')
        self.assertTrue(second.block)
        self.assertIn('YouTube-Zugang prüfen', str(second))
        self.assertIn(ab.NOT_AVAILABLE, str(second))              # „Neu einreihen“ findet die Aufträge weiter
        self.assertNotIn('Bot', str(second))
        job = {'origin': 'youtube', 'source': {'_resolver': 'youtube'}}
        self.assertTrue(download_retry.reschedule(job, second, now=NOW))
        self.assertTrue(download_retry.blocked_until('youtube', NOW)[0])

    def test_success_and_access_check_end_the_series(self):
        self.fail('abcdefghijk')
        yd._streak_reset()                                         # erfolgreicher Download
        self.assertFalse(self.fail('bbcdefghijk').block)
        download_retry.block('youtube', 4e9, 'Pause')
        with mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'eingerichtet')), \
                mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 23)), \
                mock.patch.object(yd, 'find_js_runtime', return_value=('deno', '/d')), \
                mock.patch.object(yd, '_simulate', return_value=(0, False, ['tv'], '')), \
                mock.patch('diagnostics.event'):
            self.assertTrue(yd.check_access(self.root, 'abcdefghijk')['ok'])
        self.assertEqual(download_retry.blocked_until('youtube')[0], 0)
        self.assertFalse(yd._STREAK['videos'])


if __name__ == '__main__':
    unittest.main()
