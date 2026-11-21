"""0.6.64: Samsung TV Plus – Region und Automatik im Live-TV bedienbar (Code-Review 21.11.2026, Befund C2).

Bis 0.6.61 gab es /api/samsung-region und /api/samsung-auto nur auf dem Server; die Seite rief sie nie auf."""
import tempfile
import time
import unittest
from pathlib import Path

import samsung_tvplus as stv
from tests.test_v0597_samsung_tvplus import sample

HERE = Path(__file__).resolve().parent.parent


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.started = []

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, root):
        self.started.append(root)
        return True

    def test_new_region_loads_at_once(self):
        status, started = stv.change_region(self.root, 'at', start=self.start)
        self.assertTrue(started)
        self.assertEqual(status['region'], 'at')
        self.assertEqual(self.started, [self.root])

    def test_same_region_does_not_load_again(self):
        status, started = stv.change_region(self.root, 'DE', start=self.start)
        self.assertFalse(started)
        self.assertEqual((status['region'], self.started), ('de', []))

    def test_unknown_region_is_refused_and_kept(self):
        with self.assertRaises(ValueError):
            stv.change_region(self.root, 'fr', start=self.start)
        self.assertEqual((stv.state(self.root)['region'], self.started), ('de', []))

    def test_region_change_lists_that_region(self):
        stv.sync(self.root, fetch=sample, now=time.time())
        self.assertEqual(stv.state(self.root)['channels'], 2)
        stv.change_region(self.root, 'at', start=lambda root: stv.sync(root, fetch=sample, now=time.time()) or True)
        self.assertEqual([c['title'] for c in stv.channels(self.root)], ['Nur Österreich'])

    def test_automatic_switch_off_stops_reloads(self):
        stv.sync(self.root, fetch=sample, now=time.time())
        later = time.time() + 13 * 3600
        self.assertTrue(stv.due(stv.state(self.root), later))
        stv.set_auto(self.root, False)
        self.assertFalse(stv.due(stv.state(self.root), later))
        with self.assertRaises(ValueError):
            stv.set_auto(self.root, 'nein')


class WiringTests(unittest.TestCase):
    def test_page_uses_both_routes(self):
        js = (HERE / 'web' / 'live_tv.js').read_text(encoding='utf-8')
        html = (HERE / 'web' / 'index.html').read_text(encoding='utf-8')
        server = (HERE / 'server.py').read_text(encoding='utf-8')
        for needle in ("'samsung-region'", "'samsung-auto'", 'samsungSetup(d.samsung)'):
            self.assertIn(needle, js)
        for needle in ('id="samsung-setup"', 'id="samsung-region"', '<option value="at">Österreich</option>', 'id="samsung-auto"', 'id="samsung-sync"'):
            self.assertIn(needle, html)
        self.assertIn('samsung_tvplus.change_region(ROOT,', server)
        self.assertEqual(stv.REGIONS, ('de', 'at', 'ch'))


if __name__ == '__main__':
    unittest.main()
