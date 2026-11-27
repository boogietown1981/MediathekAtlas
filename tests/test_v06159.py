"""0.6.159 – B1 aus Björns Air-Diagnose (27.11.2026): Abo-Downloads neuer Kinder-Kanäle scheiterten mit
„This video is not available“, obwohl Deno eingerichtet war; die Meldung riet trotzdem „Deno einrichten“.

* Der Deno-Rat erscheint nur noch, wenn keine JavaScript-Laufzeit gefunden wird.
* yt-dlp-Warnungen werden nicht mehr unterdrückt; ein Diagnose-Ereignis nennt Video, Abo, Laufzeit,
  ob --js-runtimes gesetzt war, yt-dlp-Version, benutzte YouTube-Clients und die letzten Meldungen (ohne URLs).
* Die Bewertung des Fehlers stützt sich nur auf die ERROR-Zeilen.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import youtube_abos as ab
import youtube_downloads as yd

NA = 'ERROR: [youtube] abcdefghijk: This video is not available'


class FailureTextTests(unittest.TestCase):
    def test_deno_advice_only_without_runtime(self):
        without, temp, _ = yd._failure(NA, js_runtime=False, js_used=False)
        self.assertIn('Deno einrichten', without)
        self.assertTrue(temp)
        present, temp, block = yd._failure(NA, js_runtime=True, js_used=True)
        self.assertNotIn('Deno einrichten', present)
        self.assertIn('Deno ist eingerichtet', present)
        self.assertIn('Kindervideo', present)
        self.assertEqual((temp, block), (True, False))
        self.assertIn(ab.NOT_AVAILABLE, present)          # requeue marker of 0.6.36 stays

    def test_runtime_present_but_old_ytdlp_points_to_ytdlp(self):
        reason, temp, _ = yd._failure(NA, js_runtime=True, js_used=False)
        self.assertIn('yt-dlp einrichten', reason)
        self.assertNotIn('Deno einrichten', reason)

    def test_client_lines(self):
        self.assertEqual(yd._client('[youtube] abc: Downloading tv client config'), 'tv')
        self.assertEqual(yd._client('[youtube] abc: Downloading web safari player API JSON'), 'web_safari')
        self.assertEqual(yd._client('[youtube] abc: Downloading webpage'), '')


class FakeProc:
    def __init__(self, args, stdout=None, stderr=None, **kw):
        self.args = args
        stderr.write('WARNING: [youtube] abcdefghijk: Some web client https formats have been skipped: https://x.example/?token=geheim timeout\n')
        stderr.write(NA + '\n')
        self.stdout = iter(['[youtube] abcdefghijk: Downloading webpage\n',
                            '[youtube] abcdefghijk: Downloading tv client config\n',
                            '[youtube] abcdefghijk: Downloading web safari player API JSON\n'])
        self.returncode = 1

    def wait(self):
        return 1

    def poll(self):
        return 1

    def kill(self):
        pass


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_fetch(self, js):
        events = []
        seen = {}

        def runner(args, **kw):
            seen['args'] = args
            return FakeProc(args, **kw)
        row = {'_youtube_home': self.root, '_video_id': 'abcdefghijk', '_abo': 7, '_container': 'mp4'}
        with mock.patch.object(yd, 'enabled', return_value=True), \
                mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'von MediathekAtlas eingerichtet')), \
                mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 6)), \
                mock.patch.object(yd, 'find_js_runtime', return_value=js), \
                mock.patch('downloads.require_space'), mock.patch('downloads.tool', return_value=None), \
                mock.patch('diagnostics.event', side_effect=lambda name, *a, **f: events.append((name, f))):
            with self.assertRaises(Exception) as ctx:
                yd.fetch(row, str(self.root / 'out.mkv'), self.root, lambda *a, **k: None, lambda: False, runner=runner)
        return ctx.exception, seen['args'], [f for n, f in events if n == 'youtube_download_failed']

    def test_with_deno_no_deno_advice_and_full_event(self):
        exc, args, events = self.run_fetch(('deno', '/app/tools/deno/deno'))
        self.assertNotIn('--no-warnings', args)
        self.assertIn('--js-runtimes', args)
        self.assertNotIn('Deno einrichten', str(exc))
        self.assertIn('Deno ist eingerichtet', str(exc))
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e['video'], e['abo'], e['js_runtime'], e['js_args'], e['tool_version'], e['retry']),
                         ('abcdefghijk', 7, 'deno', True, '2026.11.6', True))
        self.assertEqual(e['clients'], ['tv', 'web_safari'])
        text = json.dumps(e)
        self.assertNotIn('geheim', text)                   # no addresses with tokens
        self.assertIn('<url>', text)
        self.assertTrue(any(m.startswith('ERROR:') for m in e['messages']))

    def test_warning_does_not_change_judgement(self):
        # the warning says "timeout"; judged on the ERROR line it stays "not available", not a network error
        exc, _, _ = self.run_fetch(('deno', '/d'))
        self.assertIn(ab.NOT_AVAILABLE, str(exc))

    def test_without_runtime_keeps_deno_advice(self):
        exc, args, events = self.run_fetch(None)
        self.assertNotIn('--js-runtimes', args)
        self.assertIn('Deno einrichten', str(exc))
        self.assertEqual(events[0]['js_runtime'], '')
        self.assertFalse(events[0]['js_args'])


if __name__ == '__main__':
    unittest.main()
