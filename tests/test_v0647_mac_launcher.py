"""0.6.47 (found on Björn's MacBook Pro M4, 20.11.2026): inside the macOS app the start script must not stay as
the waiting parent of the server. macOS counted the app as running while the script waited for a hanging Python
process, so a double click did nothing and the start check of 0.6.46 never ran.

The test builds the .app layout (Contents/MacOS/MediathekAtlas = launcher.sh, Contents/Resources/app = code) with
a stand-in server.py that keeps running, and checks that the start script ends at once while the server goes on
in its own session. Real macOS (LaunchServices, App Translocation) is not available here."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVER = '''import os, sys, time
from pathlib import Path
Path(os.environ["MA_TEST_OUT"]).write_text("%d %d %s" % (os.getpid(), os.getsid(0), " ".join(sys.argv[1:])))
time.sleep(30)
'''


def build_app(base, server=SERVER):
    app = Path(base) / 'App Translocation' / 'd3adb33f' / 'MediathekAtlas.app' / 'Contents'
    code = app / 'Resources' / 'app'
    (code / 'web').mkdir(parents=True)
    (app / 'MacOS').mkdir(parents=True)
    (code / 'web' / 'index.html').write_text('<!doctype html>')
    (code / 'server.py').write_text(server)
    shutil.copy2(ROOT / 'stable_runtime.py', code / 'stable_runtime.py')
    launcher = app / 'MacOS' / 'MediathekAtlas'
    shutil.copy2(ROOT / 'launcher.sh', launcher)
    launcher.chmod(0o755)
    return launcher


@unittest.skipIf(os.name == 'nt', 'bash launcher')
class MacLauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.out = self.base / 'server.txt'
        self.env = {**os.environ, 'MEDIATHEKATLAS_PYTHON': sys.executable, 'MEDIATHEKATLAS_HOME': str(self.base / 'state'),
                    'MA_TEST_OUT': str(self.out)}
        self.env.pop('MEDIATHEKATLAS_SUPERVISED', None)
        self.env.pop('MEDIATHEKATLAS_FOREGROUND', None)

    def tearDown(self):
        if self.out.exists():
            try:
                os.kill(int(self.out.read_text().split()[0]), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.tmp.cleanup()

    def wait_for_server(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.out.exists() and self.out.read_text().strip():
                return self.out.read_text().split()
            time.sleep(0.1)
        self.fail('server did not start; log: ' + (self.base / 'state' / 'startup.log').read_text())

    def test_app_launcher_returns_at_once_and_server_runs_detached(self):
        launcher = build_app(self.base)
        began = time.monotonic()
        r = subprocess.run(['/bin/bash', str(launcher)], env=self.env, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r)
        self.assertLess(time.monotonic() - began, 10)
        pid, sid = self.wait_for_server()[:2]
        self.assertTrue(Path('/proc/%s' % pid).exists() or os.kill(int(pid), 0) is None)
        self.assertNotEqual(int(sid), os.getsid(0))        # own session: not tied to the start script
        log = (self.base / 'state' / 'startup.log').read_text()
        self.assertIn('übergibt an einen eigenständigen Prozess', log)
        self.assertEqual(log.count('Startprüfung'), 2)      # the supervisor keeps the log of this start

    def test_terminal_start_stays_in_foreground(self):
        launcher = build_app(self.base, server='import os\nfrom pathlib import Path\nPath(os.environ["MA_TEST_OUT"]).write_text("%d %d" % (os.getpid(), os.getsid(0)))\n')
        env = {**self.env, 'MEDIATHEKATLAS_FOREGROUND': '1'}
        r = subprocess.run(['/bin/bash', str(launcher)], env=env, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertIn('Startprüfung', (self.base / 'state' / 'startup.log').read_text())
        self.assertNotIn('eigenständigen Prozess', (self.base / 'state' / 'startup.log').read_text())
        self.assertTrue(self.out.exists())                  # ran before the script returned

    def test_path_of_the_app_does_not_matter(self):
        launcher = build_app(self.base)
        subprocess.run(['/bin/bash', str(launcher)], env=self.env, capture_output=True, timeout=20)
        self.wait_for_server()
        runtime = [p for p in (self.base / 'state' / 'runtime').iterdir() if p.is_dir() and not p.name.startswith('stage-')]
        self.assertEqual(len(runtime), 1)                   # copied by content hash, not by the translocated path
        self.assertNotIn('Translocation', str(runtime[0]))


if __name__ == '__main__':
    unittest.main()
