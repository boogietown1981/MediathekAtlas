"""0.5.75 (Björn, 12.11.2026, Diagnose 0.5.72): a new YouTube source is read right away, a running
catalogue run reports its progress, music videos have their own count on the platform card, the
YouTube database lets readers in during a run, and a log field called "level" never breaks a request."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import diagnostics  # noqa: E402
import youtube as yt  # noqa: E402
from test_v0571_youtube_music import MusicApi, MUSIC_PL  # noqa: E402


class ProgressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        db = yt._connect(self.root)
        with db:
            db.execute('DELETE FROM youtube_sources')
        db.close()
        yt.add_source(self.root, 'youtube.com/playlist?list=' + MUSIC_PL, kind='music', label='Meine Hits')

    def test_progress_and_reading_during_run(self):
        gate, seen = threading.Event(), {}
        api = MusicApi()

        def slow(endpoint, query):
            if endpoint == 'videos' and not gate.is_set():
                seen['progress'] = yt._PROGRESS
                # another connection reads while the run is between writes
                seen['listing'] = yt.listing(self.root, 'music')['total']
                gate.set()
            return api(endpoint, query)
        yt._ACTIVE = True
        try:
            result = yt.sync(self.root, request=slow, now=1_800_000_000, gap=0)
            self.assertEqual(yt.state(self.root)['progress'], seen['progress'])
        finally:
            yt._ACTIVE = False
        self.assertTrue(result['ok'], result)
        self.assertEqual(seen['progress'], 'Quelle 1 von 1: Meine Hits · 4 Videos werden geprüft')
        self.assertEqual(seen['listing'], 0)
        self.assertEqual(yt.state(self.root)['progress'], '')
        db = yt._connect(self.root)
        try:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
        finally:
            db.close()

    def test_source_added_during_run_is_read_afterwards(self):
        runs = []
        original = yt.sync
        yt.sync = lambda root, **kw: runs.append(root) or (yt.start_sync(root, queue=True) if len(runs) == 1 else None)
        try:
            self.assertTrue(yt.start_sync(self.root))
            for _ in range(100):
                if not yt._ACTIVE:
                    break
                threading.Event().wait(0.02)
        finally:
            yt.sync = original
        self.assertEqual(len(runs), 2)          # the request during run 1 caused exactly one more run
        self.assertFalse(yt._ACTIVE or yt._AGAIN)

    def test_level_field_never_breaks_logging(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        diagnostics.setup(tmp.name)
        diagnostics.event('playback_stats', level='1.6 Mbit/s')
        diagnostics.event('playback_stats', level='')
        diagnostics.event('fine', level='WARNING')
        text = (Path(tmp.name) / 'diagnostic.jsonl').read_text(encoding='utf-8')
        self.assertIn('"level_value": "1.6 Mbit/s"', text)
        self.assertIn('"level": "WARNING"', text)

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("action in ('add','enable')", server)
        self.assertIn("'music':yt.get('music',0)", server)
        self.assertNotIn(",level=(level or {})", server)
        self.assertIn('Musik-Playlists & -Videos', (ROOT / 'web/unified_catalog.js').read_text(encoding='utf-8'))
        self.assertIn('r.started', (ROOT / 'web/youtube.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
