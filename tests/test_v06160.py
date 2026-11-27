"""0.6.160 – Ursache B1 (Mac-Prüfung 27.11.2026): yt-dlp 2026.10.26/2026.11.06 mit Lösungsskript
yt-dlp-ejs 0.8.0 löst die „n challenge“ des aktuellen YouTube-Players nicht (Deno: „TypeError:
a.addOnDisposeCallback is not a function“). Kindervideos haben nur den web/web_embedded-Weg und enden in
„This video is not available“; normale Videos laufen über den tv-Client weiter.

* Erkennung „n challenge solving failed“ → MediathekAtlas holt automatisch ein neueres yt-dlp (stabil,
  sonst die offizielle Nightly-Ausgabe, Prüfsumme wie bisher), höchstens alle 12 Stunden.
* Danach bekommen „not available“-Aufträge (aufgegeben oder in der Wartezeit) einen neuen Versuch.
* Das eigene, neuere yt-dlp hat Vorrang vor einem älteren installierten.
"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import youtube_abos as ab
import youtube_downloads as yd

LOG = Path(__file__).resolve().parent / 'data'
CHALLENGE_LOG = '''WARNING: [youtube] [jsc] Error solving n challenge request using "deno" provider: Error running deno process (returncode: 1): error: Uncaught (in promise) TypeError: a.addOnDisposeCallback is not a function
WARNING: [youtube] bFJHcm_GVlc: n challenge solving failed: Some formats may be missing.
WARNING: [youtube] bFJHcm_GVlc: Some web_embedded client https formats have been skipped as they are missing a URL.
ERROR: [youtube] bFJHcm_GVlc: This video is not available
'''


def release(version):
    data = ('#!/usr/bin/env python3\n# %s\n' % version).encode()
    sums = ('%s  yt-dlp\n' % hashlib.sha256(data).hexdigest()).encode()
    return data, sums


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        yd.take_refreshed()

    def fake(self, stable, nightly):
        calls = []
        files = {yd.RELEASE: release(stable), yd.NIGHTLY: release(nightly)}

        def fetch(url):
            calls.append(url)
            base, name = url.rsplit('/', 1)
            data, sums = files[base + '/']
            return sums if name == 'SHA2-256SUMS' else data

        def version(argv):
            text = Path(argv[-1]).read_text() if Path(argv[-1]).is_file() else ''
            for v in (stable, nightly):
                if v in text:
                    return tuple(int(x) for x in v.split('.'))
            return (2026, 10, 26)
        return fetch, calls, version

    def test_detects_challenge_failure(self):
        self.assertTrue(yd.challenge_failed(CHALLENGE_LOG))
        self.assertFalse(yd.challenge_failed('ERROR: [youtube] x: This video is not available'))

    def test_newer_stable_first_then_nightly_and_gap(self):
        fetch, calls, version = self.fake('2026.11.6', '2026.11.27')
        old = (['/x/yt-dlp'], 'installiert')
        with mock.patch.object(yd, 'tool_version', side_effect=version):
            self.assertEqual(yd.refresh_for_challenge(self.root, old, fetch=fetch, now=1000), '2026.11.6')
            self.assertTrue(all(u.startswith(yd.RELEASE) for u in calls))
            self.assertEqual(yd.take_refreshed(), '2026.11.6')
            self.assertEqual(yd.take_refreshed(), '')
            # within 12 hours nothing happens again
            self.assertEqual(yd.refresh_for_challenge(self.root, old, fetch=fetch, now=2000), '')
            # later: stable is not newer than the current one → nightly
            own = ([sys.executable, str(yd._managed(self.root))], 'von MediathekAtlas eingerichtet')
            calls.clear()
            self.assertEqual(yd.refresh_for_challenge(self.root, own, fetch=fetch, now=1000 + yd.REFRESH_GAP + 1), '2026.11.27')
            self.assertTrue(any(u.startswith(yd.NIGHTLY) for u in calls))
            state = json.loads((self.root / 'tools' / 'yt-dlp-refresh.json').read_text())
            self.assertEqual(state['channel'], 'nightly')
            # the button stays on the nightly channel
            calls.clear()
            yd._install_ytdlp(self.root, fetch)
            self.assertTrue(all(u.startswith(yd.NIGHTLY) for u in calls))

    def test_checksum_mismatch_installs_nothing(self):
        def fetch(url):
            return b'0' * 64 + b'  yt-dlp\n' if url.endswith('SUMS') else b'boese'
        with mock.patch.object(yd, 'tool_version', return_value=(2026, 10, 26)):
            self.assertEqual(yd.refresh_for_challenge(self.root, (['/x'], 'i'), fetch=fetch, now=5), '')
        self.assertFalse(yd._managed(self.root).exists())

    def test_own_newer_copy_wins_over_installed(self):
        yd._managed(self.root).parent.mkdir(parents=True)
        yd._managed(self.root).write_text('x')
        versions = {'/usr/bin/yt-dlp': (2026, 10, 26), str(yd._managed(self.root)): (2026, 11, 27)}
        with mock.patch('shutil.which', return_value='/usr/bin/yt-dlp'), mock.patch.dict('os.environ', {}, clear=False), \
                mock.patch.object(yd, 'tool_version', side_effect=lambda argv: versions[argv[-1]]):
            self.assertEqual(yd.find_tool(self.root)[1], 'von MediathekAtlas eingerichtet')
            versions[str(yd._managed(self.root))] = (2026, 10, 1)
            self.assertTrue(yd.find_tool(self.root)[1].startswith('installiert'))


class FakeProc:
    def __init__(self, args, stdout=None, stderr=None, **kw):
        stderr.write(CHALLENGE_LOG)
        self.stdout = iter(['[youtube] bFJHcm_GVlc: Downloading web embedded client config\n'])

    def wait(self):
        return 1

    def poll(self):
        return 1

    def kill(self):
        pass


class FetchTests(unittest.TestCase):
    def test_challenge_failure_refreshes_and_says_so(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {'_youtube_home': root, '_video_id': 'bFJHcm_GVlc', '_abo': 3, '_container': 'mp4'}
            with mock.patch.object(yd, 'enabled', return_value=True), \
                    mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'von MediathekAtlas eingerichtet')), \
                    mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 6)), \
                    mock.patch.object(yd, 'find_js_runtime', return_value=('deno', '/d')), \
                    mock.patch.object(yd, 'refresh_for_challenge', return_value='2026.11.27') as refresh, \
                    mock.patch('downloads.require_space'), mock.patch('downloads.tool', return_value=None), \
                    mock.patch('diagnostics.event', side_effect=lambda name, *a, **f: events.append((name, f))):
                with self.assertRaises(Exception) as ctx:
                    yd.fetch(row, str(root / 'o.mkv'), root, lambda *a, **k: None, lambda: False,
                             runner=lambda args, **kw: FakeProc(args, **kw))
        refresh.assert_called_once()
        text = str(ctx.exception)
        self.assertIn('n challenge', text)
        self.assertIn('2026.11.27', text)
        self.assertIn(ab.NOT_AVAILABLE, text)                 # requeue marker stays
        self.assertNotIn('Deno einrichten', text)
        self.assertTrue(getattr(ctx.exception, 'block', None) is False)
        event = [f for n, f in events if n == 'youtube_download_failed'][0]
        self.assertTrue(event['challenge_failed'])
        self.assertEqual(event['clients'], ['web_embedded'])


class RequeueTests(unittest.TestCase):
    def test_new_ytdlp_gives_each_job_one_more_try(self):
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        err = 'YouTube … („This video is not available“ …) (nach 7 automatischen Versuchen aufgegeben)'
        rows = {'given_up': ('error', {'error': err, 'requeued_0636': True}),
                'waiting': ('queued', {'last_error': err, 'retries': 3, 'not_before': 10 ** 10}),
                'due': ('queued', {'last_error': err, 'not_before': 0}),
                'other': ('error', {'error': 'Video nicht mehr verfügbar'})}
        for jid, (state, extra) in rows.items():
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'id': jid, 'origin': 'youtube', **extra}), state))
        self.assertEqual(ab.requeue_not_available(c, now=100, tool='2026.11.27'), 2)
        got = {r[0]: (r[2], json.loads(r[1])) for r in c.execute('SELECT * FROM jobs')}
        self.assertEqual(got['given_up'][0], 'queued')
        self.assertEqual(got['given_up'][1]['requeued_tool'], '2026.11.27')
        self.assertLess(got['waiting'][1]['not_before'], 10 ** 6)
        self.assertEqual(got['other'][0], 'error')
        # same version again: nothing; old call without version: old one-time marker still respected
        self.assertEqual(ab.requeue_not_available(c, now=100, tool='2026.11.27'), 0)

    def test_server_wiring(self):
        server = (Path(__file__).resolve().parents[1] / 'server.py').read_text(encoding='utf-8')
        self.assertIn('youtube_downloads.take_refreshed()', server)
        self.assertIn('requeue_not_available(c,tool=fresh)', server)


if __name__ == '__main__':
    unittest.main()
