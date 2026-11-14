"""0.5.47: one 30-day offline control in every tile, the same for all film platforms."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def web(name):
    return (ROOT / 'web' / name).read_text(encoding='utf-8')


class OfflineTileTests(unittest.TestCase):
    def test_one_control_for_all_sources(self):
        js = web('offline_button.js')
        for source in ('netzkino', 'pluto', 'justwatch'):
            self.assertIn(source + ':', js)
        self.assertIn("source + '-downloads?'", js)
        self.assertIn("api('retry'", js)
        self.assertIn("action: 'cancel'", js)

    def test_every_tile_view_uses_it(self):
        self.assertIn('AtlasOffline?.control(K, item.id', web('portal_panel.js'))
        self.assertIn("AtlasOffline?.control('netzkino', item.id", web('netzkino.js'))
        self.assertIn('AtlasOffline?.control(item.source,item.id', web('unified_catalog.js'))
        self.assertIn('AtlasOffline?.control(m.source, e.id', web('portal_title.js'))

    def test_no_second_tile_implementation_left(self):
        panel = web('portal_panel.js')
        for old in ('function offlineButton', 'function paintState', 'pluto-offline-state'):
            self.assertNotIn(old, panel)
        self.assertNotIn('30 Tage offline speicherbar', web('unified_catalog.js'))

    def test_served_and_loaded_before_users(self):
        html = web('index.html')
        self.assertLess(html.index('/offline_button.js'), html.index('/portal_title.js'))
        self.assertLess(html.index('/offline_button.js'), html.index('/unified_catalog.js'))
        self.assertIn("'/offline_button.js'", (ROOT / 'server.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
