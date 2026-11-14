"""0.5.73: every script of the page arrives – larger listen backlog, second address, automatic reload."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


class ScriptLoadingTests(unittest.TestCase):
    def test_server_accepts_many_connections_at_once(self):
        server = text('server.py')
        self.assertIn('request_queue_size=128', server)
        self.assertIn('daemon_threads=True', server)

    def test_every_script_of_the_page_has_a_second_address(self):
        server = text('server.py')
        scripts = re.search(r"^SCRIPTS=\((.*)\)$", server, re.M).group(1)
        for src in re.findall(r'<script src="(/[^"]+)"', text('web/index.html')):
            self.assertIn("'%s'" % src, scripts, src)
            self.assertTrue((ROOT / 'web' / src[1:]).is_file(), src)
        self.assertIn("if path.startswith('/code/'):", server)
        self.assertIn("path[7:][::-1] if path[6:7]=='~'", server)
        self.assertNotIn("'/hls.min.js'", scripts)

    def test_page_reloads_a_failed_script_and_names_the_cause(self):
        js = text('web/app.js')
        for part in ("s.src='/code/'+", 'tries[name]>3', "'Skript nachgeladen: '", 'Anfrage vom Browser abgelehnt', "'Server antwortet mit HTTP '"):
            self.assertIn(part, js)


if __name__ == '__main__':
    unittest.main()
