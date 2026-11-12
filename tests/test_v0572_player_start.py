"""0.5.72: the player starts although hls.js or a page element is missing, and the last click wins."""
import unittest
from pathlib import Path

import streaming

ROOT = Path(__file__).resolve().parents[1]


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


class PlayerStartTests(unittest.TestCase):
    def test_last_click_wins_and_library_loads_on_demand(self):
        js = text('web/player.js')
        for part in ('const call=++S.call', 'if(call!==S.call)return;', 'function loadHls()', 'function hlsWanted()' if 'function hlsWanted()' in js else 'const hlsWanted=', "levels:'0'", "probe:'1'"):
            self.assertIn(part, js)

    def test_missing_player_names_the_cause_everywhere(self):
        self.assertIn('window.atlasPlayerMissing', text('web/app.js'))
        self.assertIn('atlasScriptErrors', text('web/app.js'))
        for name in ('live_tv.js', 'portal_panel.js', 'portal_title.js', 'netzkino_detail.js', 'unified_catalog.js'):
            self.assertIn('atlasPlayerMissing', text('web/' + name), name)

    def test_plan_without_levels_does_not_ask_the_provider(self):
        calls = []
        original = streaming.hls_levels
        streaming.hls_levels = lambda source, fetch=None: calls.append(1) or [{'id': '720', 'label': '720p', 'height': 720, 'bandwidth': 1}]
        try:
            source = {'kind': 'url', 'url': 'https://example.invalid/a.m3u8', 'hls': True, 'title': 'T', 'live': True}
            self.assertEqual(streaming.plan(source, levels=False)['levels'], [])
            self.assertEqual(calls, [])
            self.assertEqual(len(streaming.plan(source)['levels']), 1)
        finally:
            streaming.hls_levels = original

    def test_server_offers_levels_only_answer(self):
        server = text('server.py')
        self.assertIn("q.get('levels',[''])[0]!='0'", server)
        self.assertIn("q.get('probe',[''])[0]=='1'", server)


if __name__ == '__main__':
    unittest.main()
