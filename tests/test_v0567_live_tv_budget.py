"""0.5.67: the Live-TV tab never waits for one busy provider (Björn, 12.11.2026: with 0.5.61 the
tab stayed at "Live-Sender werden geladen …")."""
import sqlite3
import time
import unittest
from pathlib import Path

import live_tv

ROOT = Path(__file__).resolve().parents[1]


def channel(provider, name):
    return live_tv._channel(provider, name, name, {provider: name})


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live_tv.mediathek_channels, live_tv.pluto_channels, live_tv.rakuten_channels, live_tv.joyn_channels,
                      live_tv.samsung_channels)
        live_tv._LAST.clear()
        live_tv.mediathek_channels = lambda c: [channel('mediathek', 'Das Erste')]
        live_tv.pluto_channels = lambda root: [channel('pluto', 'Pluto Krimi')]
        live_tv.rakuten_channels = lambda root: [channel('rakuten', 'Rakuten Action')]
        live_tv.joyn_channels = lambda root: []
        live_tv.samsung_channels = lambda root: []   # 0.5.97

    def tearDown(self):
        (live_tv.mediathek_channels, live_tv.pluto_channels, live_tv.rakuten_channels, live_tv.joyn_channels,
         live_tv.samsung_channels) = self.saved
        live_tv._LAST.clear()

    def test_all_providers_answer(self):
        found, errors = live_tv.channels(None, None)
        self.assertEqual(sorted(ch['provider'] for ch in found), ['mediathek', 'pluto', 'rakuten'])
        self.assertEqual(errors, {})

    def test_slow_provider_does_not_hold_back_the_others(self):
        live_tv.channels(None, None)                      # remembers Pluto's channels
        live_tv.pluto_channels = lambda root: time.sleep(3) or []
        began = time.monotonic()
        found, errors = live_tv.channels(None, None, budget=0.3)
        self.assertLess(time.monotonic() - began, 1.5)
        self.assertEqual(sorted(ch['provider'] for ch in found), ['mediathek', 'pluto', 'rakuten'])   # last known state
        self.assertIn('antwortet gerade nicht', errors['pluto'])
        self.assertIn('1 Sender', errors['pluto'])
        self.assertNotIn('rakuten', errors)

    def test_slow_provider_without_earlier_answer(self):
        live_tv.rakuten_channels = lambda root: time.sleep(3) or []
        found, errors = live_tv.channels(None, None, budget=0.2)
        self.assertEqual(sorted(ch['provider'] for ch in found), ['mediathek', 'pluto'])
        self.assertIn('antwortet gerade nicht', errors['rakuten'])

    def test_broken_provider_is_named(self):
        def broken(root):
            raise sqlite3.OperationalError('database is locked')
        live_tv.pluto_channels = broken
        live_tv.mediathek_channels = lambda c: (_ for _ in ()).throw(sqlite3.OperationalError('kaputt'))
        found, errors = live_tv.channels(None, None)
        self.assertEqual([ch['provider'] for ch in found], ['rakuten'])
        self.assertEqual(errors['pluto'], 'database is locked')
        self.assertEqual(errors['mediathek'], 'kaputt')

    def test_wiring(self):
        js = (ROOT / 'web' / 'live_tv.js').read_text(encoding='utf-8')
        self.assertIn('Erneut versuchen', js)
        self.assertIn("except Exception:data['pluto']={}", (ROOT / 'server.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
