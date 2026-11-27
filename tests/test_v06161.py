"""0.6.161 – „YouTube-Zugang prüfen“ (Mac-Prüfung 0.6.160, 27.11.2026): die automatische yt-dlp-Erneuerung
war in einer Testkopie nicht nachweisbar (alte Abo-Aufträge verworfen, Einzel-Download nur für katalogisierte
Videos). Neu: ein Knopf prüft ein Video per Simulation (kein Download), erneuert yt-dlp bei
Challenge-Fehler sofort und reiht danach gescheiterte „not available“-Aufträge neu ein.
Am Mac (BEFUND-06159-06160): stable 2026.11.23 und nightly 2026.11.24 lösen Player b485e332.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import youtube_abos as ab
import youtube_downloads as yd

ROOT = Path(__file__).resolve().parents[1]
OLD_ERR = ('WARNING: [youtube] [jsc] Error solving n challenge request using "deno" provider\n'
           'WARNING: [youtube] bFJHcm_GVlc: n challenge solving failed: Some formats may be missing.\n'
           'ERROR: [youtube] bFJHcm_GVlc: This video is not available\n')


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_check(self, video, results, refreshed='2026.11.23', js=('deno', '/d')):
        calls = []
        versions = iter([(2026, 10, 26), (2026, 11, 23), (2026, 11, 23)])

        def runner(args, **kw):
            calls.append(args)
            return results.pop(0)
        with mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'von MediathekAtlas eingerichtet')), \
                mock.patch.object(yd, 'tool_version', side_effect=lambda argv: next(versions, (2026, 11, 23))), \
                mock.patch.object(yd, 'find_js_runtime', return_value=js), \
                mock.patch.object(yd, '_js_ok', return_value=True), \
                mock.patch.object(yd, 'refresh_for_challenge', return_value=refreshed) as refresh, \
                mock.patch('diagnostics.event'):
            r = yd.check_access(self.root, video, runner=runner)
        return r, calls, refresh

    def test_old_solver_renewed_at_once_then_ok(self):
        r, calls, refresh = self.run_check('https://www.youtube.com/watch?v=bFJHcm_GVlc', [
            SimpleNamespace(returncode=1, stdout='[youtube] bFJHcm_GVlc: Downloading web embedded client config\n', stderr=OLD_ERR),
            SimpleNamespace(returncode=0, stdout='[youtube] bFJHcm_GVlc: Downloading tv client config\n', stderr='')])
        refresh.assert_called_once()
        self.assertTrue(refresh.call_args.kwargs['force'])          # button = no 12-hour pause
        self.assertEqual(len(calls), 2)
        self.assertIn('-s', calls[0])                                # simulation only, never a download
        self.assertNotIn('-o', calls[0])
        self.assertIn('--js-runtimes', calls[0])
        self.assertTrue(r['ok'])
        self.assertEqual((r['refreshed'], r['tool_version'], r['clients']), ('2026.11.23', '2026.11.23', ['tv']))
        self.assertIn('eben aktualisiert von 2026.10.26', r['message'])

    def test_no_newer_version_says_so(self):
        r, calls, _ = self.run_check('bFJHcm_GVlc', [SimpleNamespace(returncode=1, stdout='', stderr=OLD_ERR)], refreshed='')
        self.assertEqual(len(calls), 1)
        self.assertFalse(r['ok'])
        self.assertIn('noch nicht entschlüsseln', r['message'])

    def test_without_deno_no_refresh_and_deno_hint(self):
        r, _, refresh = self.run_check('bFJHcm_GVlc', [SimpleNamespace(returncode=1, stdout='', stderr=OLD_ERR)], js=None)
        refresh.assert_not_called()
        self.assertIn('Deno einrichten', r['message'])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            yd.check_access(self.root, 'https://example.com/watch?v=bFJHcm_GVlc')
        self.assertEqual(yd._video_of('https://youtu.be/bFJHcm_GVlc'), 'bFJHcm_GVlc')

    def test_force_skips_gap(self):
        (self.root / 'tools').mkdir()
        (self.root / 'tools' / 'yt-dlp-refresh.json').write_text(json.dumps({'at': 1000, 'channel': 'stable'}))
        with mock.patch.object(yd, '_install_ytdlp') as inst, mock.patch.object(yd, 'tool_version', return_value=(2026, 1, 1)):
            yd.refresh_for_challenge(self.root, (['/x'], 'i'), now=1001)
            inst.assert_not_called()
            yd.refresh_for_challenge(self.root, (['/x'], 'i'), now=1002, force=True)
            self.assertTrue(inst.called)


class JobTests(unittest.TestCase):
    def test_latest_not_available_video(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        for jid, state, extra in (('a', 'error', {'error': 'This video is not available', 'source': {'_video_id': 'AAAAAAAAAAA'}}),
                                  ('b', 'queued', {'last_error': 'x This video is not available', 'source': {'_video_id': 'BBBBBBBBBBB'}}),
                                  ('c', 'error', {'error': 'Video nicht mehr verfügbar', 'source': {'_video_id': 'CCCCCCCCCCC'}})):
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'origin': 'youtube', **extra}), state))
        self.assertEqual(ab.not_available_video(c), 'BBBBBBBBBBB')
        c.execute('DELETE FROM jobs')
        self.assertEqual(ab.not_available_video(c), '')

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("@ROUTES.post('/api/youtube-access-check')", server)
        self.assertIn('requeue_not_available(c,tool=r[\'tool_version\'])', server)
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="youtube-access-check"', html)
        js = (ROOT / 'web' / 'youtube.js').read_text(encoding='utf-8')
        self.assertIn("window.api('youtube-access-check'", js)


if __name__ == '__main__':
    unittest.main()
