"""0.6.26 (Björn, 19.11.2026): Während des Downloadumzugs und danach war der Dienst praktisch blockiert
(/api/state bis 579 s, /api/storage-locations bis 433 s, /api/diagnostics 84 s); „Protokoll herunterladen“
endete immer mit „seit 60 Sekunden nicht verfügbar“."""
import io
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import storage_locations as sl  # noqa: E402
from _wiring import SERVER  # noqa: E402


class BoundedProbeTests(unittest.TestCase):
    def test_hanging_probe_answers_default_then_cached_value(self):
        gate = threading.Event()

        def slow():
            gate.wait(5)
            return 'fertig'
        started = time.monotonic()
        self.assertEqual(sl._bounded(('test', id(self)), slow, wait=0.1, default='unbekannt'), 'unbekannt')
        self.assertLess(time.monotonic() - started, 1.0)
        # zweiter Aufruf startet keinen weiteren Thread, solange der erste läuft
        before = sum(1 for t in threading.enumerate() if t.name == 'storage_probe')
        sl._bounded(('test', id(self)), slow, wait=0.05, default='unbekannt')
        self.assertEqual(sum(1 for t in threading.enumerate() if t.name == 'storage_probe'), before)
        gate.set()
        time.sleep(0.2)
        self.assertEqual(sl._bounded(('test', id(self)), slow, wait=0.1, default='unbekannt'), 'fertig')

    def test_failing_probe_gives_default(self):
        self.assertEqual(sl._bounded(('boom', id(self)), lambda: 1 / 0, wait=1, default=[]), [])

    def test_overview_does_not_wait_for_hanging_volumes(self):
        from test_v0620_storage_locations import Env
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            real = sl.volumes
            gate = threading.Event()
            sl._SLOW.pop('volumes', None)
            sl.volumes = lambda: gate.wait(10) and []
            try:
                started = time.monotonic()
                data = env.ctx.overview()
                self.assertLess(time.monotonic() - started, 6.0)
                self.assertEqual(data['volumes'], [])
                self.assertEqual(len(data['locations']), 3)
            finally:
                gate.set()
                sl.volumes = real
                sl._SLOW.pop('volumes', None)


class PacingTests(unittest.TestCase):
    def test_copy_pauses_only_inside_a_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            src = base / 'a.bin'
            src.write_bytes(b'x' * (3 * sl.CHUNK + 10))
            sleeps = []
            real_sleep = sl.time.sleep
            sl.time.sleep = lambda s: sleeps.append(s)
            try:
                sl.copy_file(src, base / 'plain.bin')
                self.assertEqual(sleeps, [])           # Abschluss beim Start: volle Geschwindigkeit

                def moving():
                    sl._low_io_priority()
                    sl.copy_file(src, base / 'paced.bin')
                t = threading.Thread(target=moving)
                t.start()
                t.join(10)
            finally:
                sl.time.sleep = real_sleep
            self.assertGreaterEqual(len(sleeps), 3)
            self.assertEqual((base / 'paced.bin').read_bytes(), src.read_bytes())
            self.assertFalse(getattr(sl._PACE, 'on', False))   # Hauptthread unberührt

    def test_mover_thread_uses_low_priority(self):
        code = (ROOT / 'storage_locations.py').read_text(encoding='utf-8')
        run = code[code.index('    def _run(self, ctx, plan):'):]
        self.assertIn('_low_io_priority()', run[:300])
        self.assertIn('setiopolicy_np(0, 1, 3)', code)


class DiagnosticsExportTests(unittest.TestCase):
    def test_export_is_bounded_and_isolated(self):
        self.assertIn('def _bounded_parts(parts,budget=20.0)', SERVER)
        self.assertIn('found=_bounded_parts(parts)', SERVER)
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("request('diagnostics',undefined,180000)", app)
        self.assertIn('async function request(path,data,wait=60000)', app)

    def test_bounded_parts_behaviour(self):
        start = SERVER.index('def _bounded_parts(parts,budget=20.0):')
        end = SERVER.index("@ROUTES.get('/api/diagnostics')")
        scope = {'threading': threading, 'time': time,
                 'core': type('core', (), {'safe_error': staticmethod(lambda e: str(e))})}
        exec(SERVER[start:end], scope)
        gate = threading.Event()
        started = time.monotonic()
        out = scope['_bounded_parts']({'fast': lambda: 1, 'hangs': lambda: gate.wait(10), 'fails': lambda: 1 / 0},
                                       budget=0.3)
        gate.set()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(out['fast'], 1)
        self.assertTrue(out['hangs']['timeout'])
        self.assertIn('division', out['fails']['error'])
        self.assertIn('hangs', out['export_slow_parts'])

    def test_startup_log_comes_from_home(self):
        import diagnostics
        with tempfile.TemporaryDirectory() as tmp:
            home, data = Path(tmp) / 'home', Path(tmp) / 'data'
            home.mkdir()
            (home / 'startup.log').write_text('MediathekAtlas Startprüfung\n')
            old = (diagnostics._root, diagnostics._home)
            try:
                diagnostics.setup(data, home)
                z = zipfile.ZipFile(io.BytesIO(diagnostics.export({})))
                self.assertIn('Startprüfung', z.read('startup.txt').decode())
            finally:
                for h in list(diagnostics.logger.handlers):
                    diagnostics.logger.removeHandler(h)
                    h.close()
                diagnostics._root, diagnostics._home = old
                if old[0]:
                    diagnostics.setup(old[0], old[1])


class EpisodeCountTests(unittest.TestCase):
    def test_episode_count_runs_beside_the_request(self):
        code = (ROOT / 'catalog_service.py').read_text(encoding='utf-8')
        self.assertIn("name='episode_queue_count'", code)
        self.assertIn('counter.join(1.0)', code)


if __name__ == '__main__':
    unittest.main()
