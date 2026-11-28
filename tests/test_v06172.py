"""0.6.172 – PIN für den Elternbereich (Umfang 28.11.2026, Punkt 3). Browser-Ablauf: tests/browser/kids_corner.cjs (kidsPin).
Dazu Mac-Prüfung 0.6.170 (BEFUND-06170-06171): (a) Folgenliste nach Profilwechsel neu, (b) Stände eines entfernten Profils weg."""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_lock as kl  # noqa: E402
import tempfile  # noqa: E402
import watch_state  # noqa: E402
from _wiring import routed  # noqa: E402


class PinTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        kl._FAILS.clear()
        self.addCleanup(kl._FAILS.clear)
        self.fast = mock.patch.object(kl, 'ITERATIONS', 1000)
        self.fast.start()
        self.addCleanup(self.fast.stop)

    def test_pin_rules_and_no_plaintext(self):
        for bad in ('', '123', '1234567', '12a4', None, 1234, '4711\n', '٤٧١١'):
            with self.assertRaises(ValueError, msg=bad):
                kl.set_pin(self.c, bad)
        kl.set_pin(self.c, '0815')
        row = self.c.execute('SELECT salt,hash,iterations FROM kids_pin').fetchone()
        self.assertEqual((len(row[0]), len(row[1])), (32, 64))          # nur Salz und Hash, kein Klartext
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM kids_pin WHERE salt LIKE '%0815%' AND hash='0815'").fetchone()[0], 0)
        kl.set_pin(self.c, '0815')
        self.assertNotEqual(self.c.execute('SELECT salt FROM kids_pin').fetchone()[0], row[0])   # neues Salz

    def test_lock_only_with_pin_and_cleared_pin_frees(self):
        self.assertIsNone(kl.lock(self.c))
        kl.set_pin(self.c, '4711')
        token = kl.lock(self.c)
        self.assertTrue(kl.locked(self.c, token))
        self.assertFalse(kl.locked(self.c, 'fremd'))
        self.assertFalse(kl.locked(self.c, ''))
        kl.clear_pin(self.c)
        self.assertFalse(kl.locked(self.c, token))

    def test_unlock_and_growing_wait(self):
        kl.set_pin(self.c, '4711')
        token = kl.lock(self.c)
        now = 1000.0
        for i in range(kl.MAX_FAILS - 1):
            with self.assertRaisesRegex(ValueError, '^Falsche PIN$'):
                kl.unlock(self.c, token, '0000', now=now)
        with self.assertRaisesRegex(ValueError, 'warten'):
            kl.unlock(self.c, token, '0000', now=now)
        self.assertEqual(kl.wait_seconds(token, now), kl.FIRST_WAIT)
        with self.assertRaisesRegex(ValueError, 'warten'):
            kl.unlock(self.c, token, '4711', now=now + 1)      # auch die richtige PIN wartet
        with self.assertRaisesRegex(ValueError, 'Falsche PIN – bitte 60'):
            kl.unlock(self.c, token, '0000', now=now + kl.FIRST_WAIT + 1)
        self.assertTrue(kl.unlock(self.c, token, '4711', now=now + 200))
        self.assertFalse(kl.locked(self.c, token))
        self.assertEqual(kl.failures(token), 0)

    def test_allowed_paths(self):
        for path in ('/kinder', '/kids.js', '/api/kids', '/api/kids-play', '/api/stream', '/api/kids-lock'):
            self.assertTrue(kl.allowed('GET', path), path)
        for path in ('/', '/ansehen', '/api/watch', '/api/status', '/api/kids-rules', '/api/kids-profiles'):
            self.assertFalse(kl.allowed('GET', path), path)
        self.assertTrue(kl.allowed('POST', '/api/watch-progress'))
        for path in ('/api/kids-pin', '/api/kids-rules', '/api/kids-profiles', '/api/settings'):
            self.assertFalse(kl.allowed('POST', path), path)

    def test_cookie(self):
        self.assertEqual(kl.cookie('abc'), 'atlas_kids_lock=abc; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d' % kl.COOKIE_SECONDS)
        self.assertTrue(kl.cookie('', 0).endswith('Max-Age=0'))


class ProfileHintTests(unittest.TestCase):
    def test_forget_prefix_only_that_profile(self):
        with tempfile.TemporaryDirectory() as root:
            for key in ('job:a', 'kp2:job:a', 'kp2:netzkino:x', 'kp12:job:a'):
                watch_state.progress(root, key, 120, 600, info={'title': key})
            self.assertEqual(watch_state.forget_prefix(root, 'kp2:'), 2)
            self.assertEqual(sorted(watch_state.overview(root)['progress']), ['job:a', 'kp12:job:a'])
            for bad in ('', 'job:', 'kp:', "kp2:' OR 1", 'kp2'):
                with self.assertRaises(ValueError):
                    watch_state.forget_prefix(root, bad)

    def test_wiring(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn('if (state.show) { const s = state.show; s.loaded = false;', js)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('watch_state.forget_prefix(ROOT,kids_profiles.prefix(result))', server)


class WiringTests(unittest.TestCase):
    def test_routes_gate_and_package(self):
        self.assertTrue(routed('/api/kids-lock', 'GET'))
        self.assertTrue(routed('/api/kids-lock', 'POST'))
        self.assertTrue(routed('/api/kids-pin', 'POST'))
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertEqual(server.count("kids_lock.allowed("), 2)              # GET und POST
        self.assertIn("'kids_lock.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="kids-pin-input"', html)
        self.assertIn('schützt nur den Browser', html)
        self.assertIn('id="kids-pin"', (ROOT / 'web' / 'kids.html').read_text(encoding='utf-8'))
        # die PIN geht nie in Ereignisse
        self.assertNotRegex(server, r"diagnostics\.event\('kids_(pin|unlock|locked)[^\n]*pin=")


if __name__ == '__main__':
    unittest.main()
