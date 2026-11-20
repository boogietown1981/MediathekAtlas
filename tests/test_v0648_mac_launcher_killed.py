"""0.6.48 (Björn's Mac, 20.11.2026): when a new start replaces a hanging instance, the old supervisor saw status
137 (SIGKILL) and showed "Python wurde gefunden, aber die Anwendung konnte nicht gestartet werden" plus the log
in TextEdit. 137/143 are an end from outside, not a start error: no dialog, a plain line in the start log."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_v0647_mac_launcher import build_app


@unittest.skipIf(os.name == 'nt', 'bash launcher')
class KilledServerTest(unittest.TestCase):
    def run_with(self, signal_name):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            server = 'import os, signal\nos.kill(os.getpid(), signal.%s)\n' % signal_name
            launcher = build_app(base, server=server)
            env = {**os.environ, 'MEDIATHEKATLAS_PYTHON': sys.executable, 'MEDIATHEKATLAS_HOME': str(base / 'state'),
                   'MEDIATHEKATLAS_FOREGROUND': '1'}
            env.pop('MEDIATHEKATLAS_SUPERVISED', None)
            r = subprocess.run(['/bin/bash', str(launcher)], env=env, capture_output=True, timeout=30)
            return r.returncode, (base / 'state' / 'startup.log').read_text()

    def test_sigkill_and_sigterm_are_no_start_error(self):
        for name, status in (('SIGKILL', 137), ('SIGTERM', 143)):
            code, log = self.run_with(name)
            self.assertEqual(code, 0, log)
            self.assertIn('von außen beendet (Status %d' % status, log)

    def test_real_error_keeps_its_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            launcher = build_app(base, server='raise SystemExit(1)\n')
            env = {**os.environ, 'MEDIATHEKATLAS_PYTHON': sys.executable, 'MEDIATHEKATLAS_HOME': str(base / 'state'),
                   'MEDIATHEKATLAS_FOREGROUND': '1'}
            r = subprocess.run(['/bin/bash', str(launcher)], env=env, capture_output=True, timeout=30)
            self.assertEqual(r.returncode, 1)


if __name__ == '__main__':
    unittest.main()
