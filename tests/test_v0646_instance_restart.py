"""0.6.46 (Björn, 20.11.2026): nach „App beenden“ im Browser ließ sich die App nicht mehr starten, bis der
Python-Prozess von Hand beendet war. Start erkennt gesunde/startende/hängende Instanzen (instance.claim),
das Beenden kann nicht mehr hängen bleiben (exit_guard, leave)."""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import instance  # noqa: E402
from instance import Instance  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class ClaimTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.held = Instance(self.root)
        self.addCleanup(self.held.close)
        self.new = Instance(self.root)
        self.addCleanup(self.new.close)
        self.log, self.opened, self.killed = [], [], []
        self.clock = Clock()

    def claim(self, **kw):
        args = dict(opener=self.opened.append, log=self.log.append, sleep=self.clock.sleep, clock=self.clock,
                    responds=lambda url: False, alive=lambda pid: True, ours=lambda pid: True,
                    kill=lambda pid: self.killed.append(pid))
        args.update(kw)
        return instance.claim(self.new, **args)

    def test_free_lock_is_taken(self):
        self.assertEqual(self.claim(), 'acquired')
        self.assertEqual(self.log, [])

    def test_healthy_instance_is_opened_in_the_browser(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.46')
        self.assertEqual(self.claim(responds=lambda url: True), 'reused')
        self.assertEqual(self.opened, ['http://127.0.0.1:23456'])
        self.assertEqual(self.killed, [])

    def test_hanging_instance_is_ended_and_replaced(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.45')
        self.held.mark('stopping')

        def kill(pid):
            self.killed.append(pid)
            self.held.close()                 # der Prozess ist weg, das System gibt die Sperre frei
        self.assertEqual(self.claim(kill=kill), 'acquired')
        self.assertEqual(self.killed, [os.getpid()])
        self.assertEqual(self.opened, [])
        self.assertGreaterEqual(self.clock.t, instance.SILENT_GRACE)
        self.assertTrue(any('wird beendet' in line for line in self.log))

    def test_stopping_instance_that_finishes_is_only_awaited(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.46')
        self.held.mark('stopping')
        ticks = []

        def sleep(s):
            self.clock.sleep(s)
            ticks.append(s)
            if len(ticks) == 3:
                self.held.close()
        self.assertEqual(self.claim(sleep=sleep, responds=lambda url: True), 'acquired')   # „stopping“ wird nie wiederverwendet
        self.assertEqual(self.killed, [])

    def test_starting_instance_gets_time_and_is_then_opened(self):
        self.assertTrue(self.held.acquire())
        self.held.mark('starting', '0.6.46')
        self.assertEqual(self.held.info()['state'], 'starting')
        ticks = []

        def sleep(s):
            self.clock.sleep(s)
            ticks.append(s)
            if len(ticks) == 60:              # nach 30 s ist der Webserver da
                self.held.publish('http://127.0.0.1:23457', '0.6.46')
        self.assertEqual(self.claim(sleep=sleep, responds=lambda url: url.endswith(':23457')), 'reused')
        self.assertEqual(self.killed, [])
        self.assertEqual(self.opened, ['http://127.0.0.1:23457'])

    def test_foreign_process_is_never_killed(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.45')
        self.assertEqual(self.claim(ours=lambda pid: False), 'failed')
        self.assertEqual(self.killed, [])

    def test_managed_service_is_never_killed(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.45')
        self.assertEqual(self.claim(managed=True), 'failed')
        self.assertEqual(self.killed, [])

    def test_gives_up_when_the_lock_stays_taken_after_the_kill(self):
        self.assertTrue(self.held.acquire())
        self.held.publish('http://127.0.0.1:23456', '0.6.45')
        self.assertEqual(self.claim(), 'failed')
        self.assertEqual(len(self.killed), 1)

    def test_is_ours_checks_the_command_line(self):
        self.assertTrue(instance.is_ours(4242, command=lambda pid: '/opt/homebrew/bin/python3 server.py'))
        self.assertFalse(instance.is_ours(4242, command=lambda pid: '/usr/bin/vim notes.txt'))
        self.assertFalse(instance.is_ours(4242, command=lambda pid: ''))
        self.assertFalse(instance.is_ours(os.getpid(), command=lambda pid: 'python server.py'))
        self.assertFalse(instance.is_ours(None))

    def test_exit_guard_and_leave(self):
        codes = []
        dump = self.root / 'hang.log'
        t = instance.exit_guard(lambda: 7, seconds=0.05, dump=str(dump), exit=codes.append)
        t.join(5)
        self.assertEqual(codes, [7])
        self.assertIn('Stand der Threads', dump.read_text(encoding='utf-8'))
        instance.leave(3, exit=codes.append)
        self.assertEqual(codes, [7, 3])


@unittest.skipIf(os.name == 'nt', 'Prozess-Signale wie auf macOS/Linux')
class RealProcessTests(unittest.TestCase):
    """Echter Server: beenden, hängen lassen (SIGSTOP), neu starten."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'home'
        self.home.mkdir()
        self.env = {**os.environ, 'MEDIATHEKATLAS_HOME': str(self.home), 'MEDIATHEKATLAS_DOWNLOAD_DIR': str(Path(tmp.name) / 'dl'),
                    'MEDIATHEKATLAS_DISABLE_BACKGROUND': '1', 'MEDIATHEKATLAS_PORT': '0'}
        self.env.pop('MEDIATHEKATLAS_MANAGED', None)
        self.procs = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.kill(p.pid, signal.SIGCONT)
                except OSError:
                    pass
                p.kill()
            p.wait(10)
            p.stdout.close()

    def start(self):
        p = subprocess.Popen([sys.executable, 'server.py', '--no-browser'], cwd=ROOT, env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        return p

    def url(self, pid, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = Instance(self.home).info()
            if info.get('pid') == pid and info.get('state') == 'running' and instance.responds(info['url'], 2):
                return info['url']
            time.sleep(0.2)
        self.fail('Server wurde nicht bereit')

    def shutdown(self, url):
        page = urllib.request.urlopen(url + '/', timeout=20).read().decode()
        token = re.search(r'name="atlas-token" content="([^"]+)"', page).group(1)
        req = urllib.request.Request(url + '/api/shutdown', data=b'{}', headers={'X-Atlas-Token': token, 'Content-Type': 'application/json'})
        self.assertEqual(json.loads(urllib.request.urlopen(req, timeout=20).read()), {'ok': True})

    def test_quit_ends_the_process_and_the_next_start_works(self):
        first = self.start()
        url = self.url(first.pid)
        self.assertEqual(json.loads(urllib.request.urlopen(url + '/api/instance', timeout=10).read())['app'], 'MediathekAtlas')
        self.shutdown(url)
        self.assertEqual(first.wait(15), 0)
        self.assertEqual(Instance(self.home).info()['state'], 'stopping')
        second = self.start()
        self.assertNotEqual(self.url(second.pid), '')

    def test_second_start_reuses_a_healthy_instance(self):
        first = self.start()
        url = self.url(first.pid)
        second = self.start()
        out, _ = second.communicate(timeout=30)
        self.assertEqual(second.returncode, 0)
        self.assertIn('läuft bereits', out)
        self.assertIn(url, out)
        self.assertIsNone(first.poll())

    def test_frozen_instance_is_replaced_on_the_next_start(self):
        first = self.start()
        self.url(first.pid)
        os.kill(first.pid, signal.SIGSTOP)        # hängt: hält die Sperre, antwortet nicht
        second = self.start()
        self.assertNotEqual(self.url(second.pid, timeout=90), '')
        self.assertIsNotNone(first.wait(10))      # die hängende Instanz wurde beendet


class WiringTests(unittest.TestCase):
    def test_server_uses_claim_guard_and_leave(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('_instance.claim(INSTANCE', server)
        self.assertIn("INSTANCE.mark('starting',VERSION)", server)
        self.assertIn("@ROUTES.get('/api/instance',stage='open')", server)
        self.assertIn(".leave(LOST_EXIT[0] or (1 if _failed else 0))", server)
        self.assertNotIn('dort „App beenden“ wählen', server)

    def test_quit_button_asks_first(self):
        app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
        line = next(l for l in app.splitlines() if l.startswith("$('quit-app').onclick"))
        self.assertLess(line.index('confirm('), line.index("api('shutdown'"))


if __name__ == '__main__':
    unittest.main()
