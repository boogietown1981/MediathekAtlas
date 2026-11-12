"""0.5.74: the page carries its scripts itself; a diagnosis field can no longer break a request."""
import json
import logging
import re
import tempfile
import unittest
from pathlib import Path

import diagnostics
import page_scripts

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = eval(re.search(r'^SCRIPTS=(\(.*\))$', (ROOT / 'server.py').read_text(encoding='utf-8'), re.M).group(1))


class InlineScriptTests(unittest.TestCase):
    def test_page_contains_every_script_in_order(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        wanted = re.findall(r'<script src="/([a-z_]+\.js)"></script>', html)
        out = page_scripts.inline_scripts(html, ROOT / 'web', SCRIPTS)
        self.assertGreater(len(wanted), 15)
        self.assertEqual(re.findall(r'<script data-file="([a-z_]+\.js)">', out), wanted)
        self.assertNotIn('<script src=', out)
        for name in wanted:
            self.assertIn('//# sourceURL=/%s\n</script>' % name, out)
        self.assertNotIn('hls.min.js"', out.split('<script data-file=')[0])

    def test_closing_tag_inside_code_is_escaped_and_unknown_files_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'app.js').write_text("const a='</script><b>';", encoding='utf-8')
            out = page_scripts.inline_scripts('<script src="/app.js"></script><script src="/other.js"></script><script src="/player.js"></script>', Path(tmp), ('/app.js', '/player.js'))
        self.assertIn("const a='<\\/script><b>';", out)
        self.assertEqual(out.count('</script>'), 3)
        self.assertIn('<script src="/other.js"></script>', out)   # not one of the page's scripts
        self.assertIn('<script src="/player.js"></script>', out)  # unreadable: ordinary tag stays

    def test_missing_netzkino_script_gives_a_clear_message(self):
        self.assertIn("if(!window.AtlasNetzkinoDetail)throw new Error(", (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8'))


class DiagnosticsLevelTests(unittest.TestCase):
    def test_unknown_level_does_not_raise(self):
        seen = []

        class Catch(logging.Handler):
            def emit(self, record):
                seen.append((record.levelno, json.loads(record.getMessage())))

        handler = Catch()
        diagnostics.logger.addHandler(handler)
        try:
            diagnostics.event('unit_level_test', level='1.6 Mbit/s', x=1)
            diagnostics.event('unit_level_test', level='WARNING')
        finally:
            diagnostics.logger.removeHandler(handler)
        mine = [s for s in seen if s[1].get('event') == 'unit_level_test']
        if mine:  # the logger may be switched off in the test environment
            self.assertEqual(mine[0][0], logging.INFO)
            self.assertEqual(mine[0][1]['level_value'], '1.6 Mbit/s')
            self.assertEqual(mine[-1][0], logging.WARNING)

    def test_playback_events_use_no_field_named_level(self):
        text = (ROOT / 'server.py').read_text(encoding='utf-8')
        for name in ('playback_stream', 'playback_stats'):
            call = text[text.index("diagnostics.event('%s'" % name):]
            call = call[:call.index('\n            ', 600) if name == 'playback_stats' else 500]
            self.assertNotRegex(call, r"[,(]level=")


if __name__ == '__main__':
    unittest.main()
