"""0.5.46: catalogue errors name the network cause; diagnostics probe the catalogue hosts."""
import socket
import ssl
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import netcheck  # noqa: E402


class CauseTests(unittest.TestCase):
    def test_causes_are_distinguished(self):
        cases = [(urllib.error.URLError(socket.gaierror(8, 'nodename nor servname provided')), 'dns', 'Name nicht auflösbar'),
                 (urllib.error.URLError(ssl.SSLCertVerificationError(1, 'certificate verify failed')), 'certificate', 'Zertifikat'),
                 (socket.timeout('timed out'), 'timeout', 'Zeitüberschreitung'),
                 (urllib.error.URLError(ConnectionRefusedError(61, 'refused')), 'refused', 'abgelehnt'),
                 (urllib.error.URLError('Tunnel connection failed: 403 Forbidden'), 'url', 'Proxy')]
        for exc, key, text in cases:
            self.assertEqual(netcheck.kind(exc), key)
            self.assertIn(text, netcheck.cause(exc))

    def test_no_url_or_secret_in_message(self):
        exc = urllib.error.URLError(socket.gaierror(8, 'https://secret.example/?key=abc'))
        self.assertNotIn('secret', netcheck.with_cause('X ist nicht erreichbar', exc))
        self.assertEqual(netcheck.cause(ValueError('x')), '')

    def test_portal_messages_carry_the_cause(self):
        import pluto, justwatch
        exc = urllib.error.URLError(socket.gaierror(8, 'x'))
        self.assertIn('Name nicht auflösbar', pluto._error(exc))
        self.assertIn('Name nicht auflösbar', justwatch._error(exc))
        self.assertTrue(pluto._error(exc).startswith('Pluto TV ist nicht erreichbar – '))

    def test_probe_reports_without_raising(self):
        rows = netcheck.probe(hosts=('host.invalid',), timeout=1)
        self.assertEqual(rows[0]['host'], 'host.invalid')
        self.assertIn('error', rows[0])
        self.assertNotIn('tls', rows[0])

    def test_trust_store_is_reported(self):
        trust = netcheck.ensure_trust_store()
        self.assertIn(trust['source'] == 'system' or bool(trust['source']), (True,))
        self.assertIn('ca_certs', trust)

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("'network':{'trust_store':netcheck.ensure_trust_store(),'hosts':netcheck.probe()}", server)
        self.assertIn("'netcheck.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn("with_cause('Netzkino-Katalogserver nicht erreichbar',exc)", (ROOT / 'netzkino.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
