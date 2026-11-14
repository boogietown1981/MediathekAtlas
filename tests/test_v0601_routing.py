"""0.6.1: the route table (routing.py) replaces the if-chains in server.py's Handler.get/post."""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import platform_registry as registry  # noqa: E402
import routing  # noqa: E402
from _wiring import ROUTES as WRITTEN, routed  # noqa: E402

SERVER = (ROOT / 'server.py').read_text(encoding='utf-8')


class TableTests(unittest.TestCase):
    def test_register_and_find_by_stage(self):
        t = routing.Table()

        @t.get('/a', '/b')
        def a(self, path):
            return 'a'

        @t.post('/a')
        def b(self, path, d):
            return 'b'

        @t.get('/open', stage='open')
        def c(self, path):
            return 'c'
        self.assertIs(t.find('GET', '/a', 'api'), a)
        self.assertIs(t.find('GET', '/b', 'api'), a)
        self.assertIs(t.find('POST', '/a', 'api'), b)
        self.assertIsNone(t.find('GET', '/a', 'open'), 'a route answers only in its own stage')
        self.assertIsNone(t.find('GET', '/open', 'api'))
        self.assertIs(t.find('GET', '/open', 'open'), c)
        self.assertIsNone(t.find('GET', '/missing', 'api'))
        self.assertIsNone(t.find('PUT', '/a', 'api'))
        self.assertEqual(t.stage('GET', '/open'), 'open')
        self.assertTrue(t.has('POST', '/a'))
        self.assertFalse(t.has('POST', '/b'))
        self.assertEqual(t.listing(), [('GET', '/a', 'api', 'a'), ('GET', '/b', 'api', 'a'), ('GET', '/open', 'open', 'c'),
                                       ('POST', '/a', 'api', 'b')])

    def test_mistakes_are_rejected_at_start(self):
        t = routing.Table()
        t.get('/a')(lambda self, path: None)
        with self.assertRaises(ValueError):
            t.get('/a')(lambda self, path: None)          # the same address twice
        with self.assertRaises(ValueError):
            t.get('a')(lambda self, path: None)           # no leading slash
        with self.assertRaises(ValueError):
            t.get('/x', stage='public')
        with self.assertRaises(ValueError):
            t.add('PUT', ('/x',))
        with self.assertRaises(ValueError):
            t.get()
        t.post('/a')(lambda self, path, d: None)           # the same address for the other method is fine


class ServerTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.listing = server.ROUTES.listing()

    def test_table_matches_the_source(self):
        self.assertEqual({(m, p): s for m, p, s, _ in self.listing}, WRITTEN)
        self.assertGreaterEqual(len(self.listing), 130)

    def test_no_if_chain_left_in_the_handler(self):
        get = SERVER[SERVER.index('    def get(self):'):SERVER.index('    def download_file(self,q')]
        post = SERVER[SERVER.index('    def post(self):'):SERVER.index('    def login(self):')]
        handler = get + post
        left = re.findall(r"if path=='(/[^']*)'", handler)
        self.assertEqual(left, ['/api/v1', '/'], 'the branch to API v1 (0.6.2) and the login page for a visitor who is not signed in')
        self.assertEqual(handler.count("ROUTES.find('GET',path,"), 3)
        self.assertEqual(handler.count("ROUTES.find('POST',path,'api')"), 1)
        self.assertLess(len(handler), 8000, 'Handler.get and Handler.post stay short')

    def test_stage_order_in_the_handler(self):
        get = SERVER[SERVER.index('    def get(self):'):SERVER.index('    def download_file(self,q')]
        marks = [get.index(x) for x in ("ROUTES.find('GET',path,'open')", 'if not self.authorized():', "ROUTES.find('GET',path,'signed')",
                                        "self.headers.get('X-Atlas-Token')!=TOKEN", "ROUTES.find('GET',path,'api')",
                                        'platform_registry.handle_get(')]
        self.assertEqual(marks, sorted(marks))
        post = SERVER[SERVER.index('    def post(self):'):SERVER.index('    def login(self):')]
        marks = [post.index(x) for x in ("if self.headers.get('X-Atlas-Token')!=TOKEN", 'platform_registry.handle_post(', "ROUTES.find('POST',path,'api')")]
        self.assertEqual(marks, sorted(marks), 'no POST route runs before the page token is checked')

    def test_what_is_open_before_the_login(self):
        opened = sorted(p for m, p, s, _ in self.listing if s == 'open')
        self.assertEqual(opened, ['/api/login-state', '/icon.svg', '/login.js', '/style.css', '/theme-light.css'])
        signed = sorted(p for m, p, s, _ in self.listing if s == 'signed')
        self.assertEqual(signed, ['/', '/api/download-file', '/api/stream', '/hls.min.js', '/titleview.js'])
        self.assertTrue(all(s == 'api' or p.startswith('/api/v1/') for m, p, s, _ in self.listing if m == 'POST'))
        self.assertTrue(all((s == 'v1') == (p == '/api/v1' or p.startswith('/api/v1/')) for m, p, s, _ in self.listing))      # 0.6.2
        # the two addresses a <video> or <a download> calls check the token from the query themselves
        for name in ('download_file', 'stream'):
            body = SERVER[SERVER.index('    def %s(self' % name):][:200]
            self.assertIn("secrets.compare_digest(q.get('token',[''])[0],TOKEN)", body, name)

    def test_no_address_is_answered_twice(self):
        both = [(m, p) for m, p, _, _ in self.listing if registry.serves(m, p)]
        self.assertEqual(both, [], 'the platform registry and the route table must not share an address')
        for m, p, _, _ in self.listing:
            self.assertFalse(p.startswith('/api/peer/') or p.startswith('/code/'), p)

    def test_function_names_and_arguments(self):
        import inspect
        for m, p, _, name in self.listing:
            fn = self.server.ROUTES.find(m, p, self.server.ROUTES.stage(m, p))
            self.assertTrue(name.startswith(m.lower() + '_'), name)
            required = [n for n, par in inspect.signature(fn).parameters.items() if par.default is par.empty]
            self.assertEqual(required, ['self', 'path'] + (['d'] if m == 'POST' else []), name)

    def test_guards_that_used_to_stand_in_front_of_the_chain(self):
        s = self.server
        fn = inspect_source(s.post_shutdown)
        self.assertLess(fn.index('if MANAGED:raise ValueError'), fn.index('STOP.set()'))
        fn = inspect_source(s.post_open_download)
        self.assertLess(fn.index('if NETWORK:raise ValueError'), fn.index('SELECT payload FROM jobs'))
        fn = inspect_source(s.post_youtube_download_add)
        self.assertLess(fn.index("if d.get('album') or isinstance(d.get('ids'),list):"), fn.index('youtube_downloads.enqueue('))
        post = SERVER[SERVER.index('    def post(self):'):SERVER.index('    def login(self):')]
        self.assertIn("if path in ('/api/save-metadata','/api/review','/api/search'):", post)      # stored pages dropped first
        self.assertLess(post.index('catalog.invalidate_listings(drop=True)'), post.index("ROUTES.find('POST'"))

    def test_page_calls_have_an_address(self):
        """Every ``api('name…')`` in the page's scripts is answered by the table or the platform registry."""
        known = {p for _, p, _, _ in self.listing} | {p for _, p in registry.routes()}
        known |= {'/api/login', '/api/logout', '/api/password', '/api/archive-list-import'}      # answered in the handler itself
        missing = set()
        for script in sorted((ROOT / 'web').glob('*.js')):
            for name in re.findall(r"\bapi\(\s*['`]([a-z][a-z0-9-]*)", script.read_text(encoding='utf-8')):
                if '/api/' + name not in known:
                    missing.add((script.name, name))
        self.assertEqual(sorted(missing), [])

    def test_wiring_helper(self):
        self.assertTrue(routed('/api/tasks', 'GET', 'api'))
        self.assertTrue(routed('/api/task-action', 'POST'))
        self.assertFalse(routed('/api/tasks', 'POST'))
        self.assertFalse(routed('/api/tasks', 'GET', 'open'))

    def test_packaged(self):
        self.assertIn("'routing.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertEqual(self.server.VERSION, __import__('version').VERSION)


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


class LiveTests(unittest.TestCase):
    """The real server on a free port: stages, 404 and a few addresses of each kind."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()
        env = dict(os.environ, MEDIATHEKATLAS_HOME=cls.home.name, MEDIATHEKATLAS_PORT=str(cls.port),
                   MEDIATHEKATLAS_DISABLE_BACKGROUND='1')
        env.pop('MEDIATHEKATLAS_NETWORK', None)
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--no-browser'], env=env, cwd=str(ROOT),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = None
        for _ in range(150):
            try:
                page = cls.call('/')[1].decode()
                break
            except OSError:
                time.sleep(0.2)
        if page is None:
            cls.tearDownClass()
            raise RuntimeError('server did not start')
        cls.token = re.search(r'atlas-token" content="([^"]+)"', page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.home.cleanup()

    @classmethod
    def call(cls, path, data=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Atlas-Token'] = token
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (cls.port, path),
                                     data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_stages(self):
        for path in ('/icon.svg', '/style.css', '/login.js', '/theme-light.css', '/api/login-state', '/', '/titleview.js', '/hls.min.js'):
            self.assertEqual(self.call(path)[0], 200, path)                       # no page token needed
        self.assertEqual(self.call('/api/tasks')[0], 403)                         # stage 'api' without the token
        self.assertEqual(self.call('/api/tasks', token='wrong')[0], 403)
        self.assertEqual(self.call('/api/tasks', token=self.token)[0], 200)
        self.assertEqual(self.call('/api/stream')[0], 403)                        # checks the token in the query itself
        self.assertEqual(self.call('/api/download-file')[0], 403)
        self.assertEqual(self.call('/api/task-action', {})[0], 403)
        self.assertEqual(self.call('/api/login-state', token=self.token)[0], 200)

    def test_unknown_addresses(self):
        for path in ('/api/gibt-es-nicht', '/api/tasks/', '/api/taskss', '/nichts'):
            status, body = self.call(path, token=self.token)
            self.assertEqual((status, json.loads(body)), (404, {'error': 'Nicht gefunden'}), path)
        status, body = self.call('/api/gibt-es-nicht', {}, token=self.token)
        self.assertEqual((status, json.loads(body)), (404, {'error': 'Nicht gefunden'}))
        self.assertEqual(self.call('/api/tasks', {}, token=self.token)[0], 404, 'a GET address is not a POST address')
        self.assertEqual(self.call('/api/task-action', token=self.token)[0], 404)

    def test_every_get_address_answers(self):
        import server
        for method, path, stage, _ in server.ROUTES.listing():
            if method != 'GET':
                continue
            status, body = self.call(path, token=self.token)
            self.assertNotEqual(body, b'{"error": "Nicht gefunden"}', path)
            self.assertIn(status, (200, 400, 403, 404, 500), path)
            if status == 500:      # an address that needs an id says so; it must not be a programming error
                self.assertNotRegex(body.decode(), r'NameError|UnboundLocal|AttributeError|TypeError|not defined', path)
        for path in ('/api/state', '/api/portals', '/api/system-monitor', '/api/unified', '/api/live-tv', '/api/storage'):
            status, body = self.call(path, token=self.token)
            self.assertEqual(status, 200, path)
            self.assertIsInstance(json.loads(body), dict, path)

    def test_posts(self):
        status, body = self.call('/api/display', {}, token=self.token)
        self.assertEqual(status, 200)
        self.assertIn('display', json.loads(body))
        status, body = self.call('/api/task-action', {}, token=self.token)
        self.assertEqual((status, json.loads(body)), (400, {'error': 'Unbekannte Aktion'}))
        status, body = self.call('/api/open-download', {'id': 1}, token=self.token)
        self.assertEqual((status, json.loads(body)['error']), (400, 'Nur abgeschlossene Downloads können geöffnet werden'))
        status, body = self.call('/api/netzkino-auto', {'enabled': False}, token=self.token)      # platform registry, before the table
        self.assertEqual(status, 200)
        self.assertIn('status', json.loads(body))
        status, body = self.call('/api/settings', {'background_profile': 'low'}, token=self.token)
        self.assertEqual(status, 200)
        status, body = self.call('/api/system-monitor', token=self.token)
        self.assertEqual(json.loads(body)['activity']['planner']['choice'], 'low')


if __name__ == '__main__':
    unittest.main()
