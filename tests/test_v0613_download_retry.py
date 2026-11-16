"""0.6.13 Abo-Downloads: Bot-Prüfung und Hänger (Björn, 16.11.2026: „0.0 MiB · Geschwindigkeit wird
ermittelt“ und „YouTube verlangt eine Anmeldung („kein Bot“) … Später erneut versuchen“).

Vorübergehende Fehler werden mit wachsendem Abstand automatisch wiederholt, eine Bot-Prüfung pausiert
alle YouTube-Aufträge, ein Download ohne Daten wird erkannt und später neu versucht."""
import io
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import download_retry as dr, job_queue, youtube_downloads as yd, youtube_abos as ab  # noqa: E402
from _wiring import SERVER  # noqa: E402

BOT = "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser"


def job(**extra):
    return {'id': 'j1', 'origin': 'youtube', 'state': 'downloading', 'source': {'_resolver': 'youtube'}, **extra}


class RetryTests(unittest.TestCase):
    def setUp(self):
        dr.clear()
        self.addCleanup(dr.clear)

    def test_growing_gaps_then_error(self):
        j = job()
        gaps = []
        for n in range(len(dr.BACKOFF)):
            self.assertTrue(dr.reschedule(j, dr.RetryLater('Netz weg'), now=1000, rand=lambda: .5))
            gaps.append(j['not_before'] - 1000)
            self.assertEqual((j['state'], j['retries'], j['error']), ('queued', n + 1, ''))
            self.assertIn('Versuch %d von %d' % (n + 2, len(dr.BACKOFF) + 1), j['note'])
        self.assertEqual(gaps, list(dr.BACKOFF))
        self.assertFalse(dr.reschedule(j, dr.RetryLater('Netz weg'), now=1000))
        self.assertIn('nach 7 automatischen Versuchen', j['error'])

    def test_other_errors_stay_errors(self):
        j = job()
        self.assertFalse(dr.reschedule(j, ValueError('Video nicht mehr verfügbar'), now=1000))
        self.assertNotIn('retries', j)

    def test_bot_check_pauses_the_whole_source(self):
        now = time.time()
        first = job()
        dr.reschedule(first, dr.RetryLater('kein Bot', block=True), now=now, rand=lambda: .5)
        until = first['not_before']
        other = job(id='j2')
        self.assertTrue(dr.hold(other, now=now + 60))
        self.assertEqual(other['not_before'], until)
        self.assertIn('Pausiert bis', other['note'])
        self.assertFalse(dr.hold({'id': 'x', 'source': {'_resolver': 'pluto'}}, now=now + 60))   # andere Quelle läuft
        forced = job(id='j3', force_now=True)                                                       # „Jetzt versuchen“
        self.assertFalse(dr.hold(forced, now=now + 60))
        self.assertNotIn('force_now', forced)
        self.assertFalse(dr.hold(job(id='j4'), now=until + 1))                                     # Pause vorbei

    def test_queue_controls_reset_and_force(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        j = job(state='error', retries=7, not_before=5, error='x')
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j1', json.dumps(j), 'error'))
        again = job_queue.retry(c, 'j1')
        self.assertEqual((again['retries'], again['not_before'], again['force_now']), (0, 0, True))
        c.execute("UPDATE jobs SET payload=?,state='queued' WHERE id='j1'", (json.dumps({**again, 'not_before': 9e9}),))
        self.assertTrue(job_queue.control(c, 'j1', 'now')['force_now'])


class FailureTextTests(unittest.TestCase):
    def test_classification(self):
        message, retry, block = yd._failure(BOT)
        self.assertEqual((retry, block), (True, True))
        self.assertIn('kein Bot', message)
        self.assertNotIn('Später erneut versuchen', message)        # das übernimmt jetzt MediathekAtlas
        self.assertEqual(yd._failure('ERROR: HTTP Error 429: Too Many Requests')[1:], (True, True))
        self.assertEqual(yd._failure('ERROR: Read timed out.')[1:], (True, False))
        self.assertEqual(yd._failure('ERROR: [youtube] x: Video unavailable')[1:], (False, False))
        self.assertEqual(yd._failure('ERROR: Sign in to confirm your age')[1:], (False, False))

    def test_phases(self):
        self.assertEqual(yd._phase('[youtube] abc: Downloading webpage'), 'Videoseite wird abgerufen')
        self.assertEqual(yd._phase('[youtube] abc: Downloading android player API JSON'), 'Videodaten werden abgefragt')
        self.assertIn('Pause', yd._phase('[download] Sleeping 7.00 seconds ...'))
        self.assertEqual(yd._phase('irgendwas'), '')


class FetchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        yd.set_enabled(self.root, True, confirmed=True)
        self.row = {'_youtube_home': str(self.root), '_video_id': 'abcdefghijk', '_container': 'mp4', '_abo': 1}

    def run_fetch(self, proc, **patch):
        updates = []
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')), \
                mock.patch.multiple(yd, **patch) if patch else mock.patch.object(yd, 'STALL', yd.STALL):
            try:
                yd.fetch(self.row, self.root / 'src.partial', self.root, lambda *a, **k: updates.append((a, k)),
                         lambda: False, runner=proc)
            finally:
                self.updates = updates

    def test_bot_check_becomes_retry_with_pause(self):
        seen = {}

        class Proc:
            def __init__(self, args, stderr=None, **kw):
                seen['args'] = args
                stderr.write(BOT + '\n')
                self.stdout = io.StringIO('[youtube] abcdefghijk: Downloading webpage\n')

            def wait(self):
                return 1

            def poll(self):
                return 1

            def kill(self):
                pass
        with self.assertRaises(dr.RetryLater) as caught:
            self.run_fetch(Proc)
        self.assertTrue(caught.exception.block)
        self.assertIn('--sleep-interval', seen['args'])                      # Abo-Downloads mit Pausen
        notes = [k.get('note') for a, k in self.updates]
        self.assertIn('Videoseite wird abgerufen', notes)                     # statt „Geschwindigkeit wird ermittelt“

    def test_download_without_data_is_stopped(self):
        killed = threading.Event()

        class Silent:
            def __iter__(self):
                killed.wait(10)
                return iter(())

        class Proc:
            def __init__(self, args, **kw):
                self.stdout = Silent()

            def wait(self):
                return -9

            def poll(self):
                return -9 if killed.is_set() else None

            def kill(self):
                killed.set()
        started = time.monotonic()
        with self.assertRaisesRegex(dr.RetryLater, 'noch keine Daten'):
            self.run_fetch(Proc, STALL_START=1)
        self.assertLess(time.monotonic() - started, 8)

    def test_single_click_without_extra_pauses(self):
        seen = {}

        class Proc:
            def __init__(self, args, **kw):
                seen['args'] = args
                Path(args[args.index('-o') + 1].replace('%(ext)s', 'mkv')).write_bytes(b'x' * 10)
                self.stdout = io.StringIO('MAP 5 10\nMAP 10 10\n')

            def wait(self):
                return 0

            def poll(self):
                return 0

            def kill(self):
                pass
        self.row = {'_youtube_home': str(self.root), '_video_id': 'abcdefghijk'}
        self.run_fetch(Proc)
        self.assertNotIn('--sleep-interval', seen['args'])
        self.assertEqual(self.updates[-1][1].get('note'), '')               # Hinweis verschwindet bei Daten


class AboTests(unittest.TestCase):
    def setUp(self):
        dr.clear()
        self.addCleanup(dr.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def put(self, jid, state, **extra):
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'id': jid, 'origin': 'youtube', **extra}), state))

    def test_requeue_on_start(self):
        self.put('bot', 'error', error='YouTube verlangt eine Anmeldung („kein Bot“); MediathekAtlas umgeht das nicht. Später erneut versuchen')
        self.put('gone', 'error', error='Video nicht mehr verfügbar')
        self.put('cut', 'interrupted', youtube_abo=3)
        self.put('hand', 'interrupted')                                       # von Hand bestellt: bleibt
        self.assertEqual(ab.requeue_on_start(self.c, now=1000), 2)
        states = dict(self.c.execute('SELECT id,state FROM jobs'))
        self.assertEqual(states, {'bot': 'queued', 'gone': 'error', 'cut': 'queued', 'hand': 'interrupted'})
        bot = json.loads(self.c.execute("SELECT payload FROM jobs WHERE id='bot'").fetchone()[0])
        self.assertGreaterEqual(bot['not_before'], 1000 + dr.BACKOFF[0])
        self.assertEqual(bot['retries'], 1)

    def test_check_waits_during_pause_and_overview_shows_it(self):
        dr.block('youtube', time.time() + 600, 'kein Bot')
        abo = ab.add(self.root, {'url': 'https://www.youtube.com/@Kanal', 'profile': 'kinder'})
        abo_id = abo['id'] if isinstance(abo, dict) and 'id' in abo else ab.overview(self.root)['abos'][0]['id']
        runner = mock.Mock(side_effect=AssertionError('yt-dlp darf während der Pause nicht laufen'))
        result = ab.check(self.root, abo_id, runner=runner, request=None)
        self.assertTrue(result.get('paused'), result)
        self.assertEqual(ab.overview(self.root)['pause']['reason'], 'kein Bot')

    def test_waiting_retry_reason_on_video(self):
        abo = ab.add(self.root, {'url': 'https://www.youtube.com/@Kanal', 'profile': 'kinder'})
        abo_id = abo['id'] if isinstance(abo, dict) and 'id' in abo else ab.overview(self.root)['abos'][0]['id']
        db = ab._connect(self.root)
        with db:
            db.execute("INSERT INTO youtube_abo_videos(abo_id,video,state,job_id,found) VALUES(?,?,?,?,?)",
                       (abo_id, 'abcdefghijk', 'queued', 'j1', 1))
        self.put('j1', 'queued', retries=2, last_error='YouTube bremst gerade (zu viele Anfragen)')
        ab.sync_states(self.c, db)
        self.assertEqual(db.execute('SELECT state,reason FROM youtube_abo_videos').fetchone()[:],
                         ('queued', 'YouTube bremst gerade (zu viele Anfragen)'))
        db.close()
        data = ab.overview(self.root, self.c)
        self.assertEqual(data['abos'][0]['counts'].get('retry'), 1)
        self.assertEqual(data['abos'][0]['counts'].get('queued'), 0)


class WiringTests(unittest.TestCase):
    def test_worker_uses_retry(self):
        self.assertIn('download_retry.hold(j)', SERVER)
        self.assertIn('download_retry.reschedule(j,e)', SERVER)
        self.assertIn('youtube_abos.requeue_on_start(c)', SERVER)
        self.assertIn("'download_retry.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))

    def test_ui(self):
        app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
        self.assertIn("j.note||'Geschwindigkeit wird ermittelt'", app)
        abos = (ROOT / 'web/youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn("['retry', 'neuer Versuch geplant', 'wait']", abos)
        self.assertIn('d.pause?.until', abos)


if __name__ == '__main__':
    unittest.main()
