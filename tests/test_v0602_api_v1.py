"""0.6.2: API v1 for clients outside the page, device keys and stream tickets (api_keys.py)."""
import json
import os
import re
import socket
import sqlite3
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
import api_keys  # noqa: E402

SERVER = (ROOT / 'server.py').read_text(encoding='utf-8')


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        api_keys._USED.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_verify_revoke(self):
        self.assertEqual(api_keys.listing(self.root), [])
        self.assertIsNone(api_keys.verify(self.root, 'atlas_' + 'x' * 43))
        made = api_keys.create(self.root, '  Apple TV   Wohnzimmer ', now=1000)
        self.assertEqual(made['name'], 'Apple TV Wohnzimmer')
        self.assertTrue(made['key'].startswith('atlas_') and len(made['key']) >= 40)
        stored = (self.root / 'api_keys.json').read_text(encoding='utf-8')
        self.assertNotIn(made['key'], stored, 'only the hash is kept')
        self.assertNotIn(made['key'][6:], stored)
        if os.name != 'nt':
            self.assertEqual(os.stat(self.root / 'api_keys.json').st_mode & 0o777, 0o600)
        self.assertEqual(api_keys.listing(self.root), [{'id': made['id'], 'name': 'Apple TV Wohnzimmer', 'created': 1000, 'last_used': 0}])
        hit = api_keys.verify(self.root, made['key'], now=5000)
        self.assertEqual((hit['id'], hit['name']), (made['id'], 'Apple TV Wohnzimmer'))
        self.assertNotIn('hash', hit)
        self.assertEqual(api_keys.listing(self.root)[0]['last_used'], 5000)
        api_keys.verify(self.root, made['key'], now=5100)
        self.assertEqual(api_keys.listing(self.root)[0]['last_used'], 5000, 'at most one write in five minutes')
        api_keys.verify(self.root, made['key'], now=5400)
        self.assertEqual(api_keys.listing(self.root)[0]['last_used'], 5400)
        for wrong in (made['key'] + 'x', made['key'][:-1], made['key'].upper(), 'atlas_', '', None, 5, made['key'][6:], 'x' * 5000):
            self.assertIsNone(api_keys.verify(self.root, wrong), repr(wrong)[:30])
        self.assertFalse(api_keys.revoke(self.root, 'nope'))
        self.assertTrue(api_keys.revoke(self.root, made['id']))
        self.assertIsNone(api_keys.verify(self.root, made['key']))
        self.assertEqual(api_keys.listing(self.root), [])

    def test_names_and_limit(self):
        with self.assertRaises(ValueError):
            api_keys.create(self.root, '   ')
        api_keys.create(self.root, 'TV')
        with self.assertRaises(ValueError):
            api_keys.create(self.root, 'tv')
        self.assertEqual(len(api_keys.create(self.root, 'x' * 200)['name']), 60)
        for n in range(api_keys.MAX_KEYS - 2):
            api_keys.create(self.root, 'Gerät %d' % n)
        with self.assertRaises(ValueError):
            api_keys.create(self.root, 'eins zu viel')
        self.assertEqual(len(api_keys.listing(self.root)), api_keys.MAX_KEYS)

    def test_two_keys_and_a_damaged_file(self):
        a, b = api_keys.create(self.root, 'A', now=1), api_keys.create(self.root, 'B', now=2)
        self.assertNotEqual(a['key'], b['key'])
        self.assertEqual(api_keys.verify(self.root, b['key'])['name'], 'B')
        self.assertEqual([k['name'] for k in api_keys.listing(self.root)], ['B', 'A'])
        api_keys.revoke(self.root, a['id'])
        self.assertIsNone(api_keys.verify(self.root, a['key']))
        self.assertEqual(api_keys.verify(self.root, b['key'])['name'], 'B')
        (self.root / 'api_keys.json').write_text('{kaputt', encoding='utf-8')
        self.assertIsNone(api_keys.verify(self.root, b['key']), 'a damaged file opens nothing')
        self.assertEqual(api_keys.listing(self.root), [])

    def test_tickets(self):
        t = api_keys.ticket('secret', now=1000)
        self.assertTrue(api_keys.ticket_valid('secret', t, now=1000))
        self.assertTrue(api_keys.ticket_valid('secret', t, now=1000 + api_keys.TICKET_SECONDS - 1))
        self.assertFalse(api_keys.ticket_valid('secret', t, now=1000 + api_keys.TICKET_SECONDS + 1))
        self.assertFalse(api_keys.ticket_valid('other', t, now=1000), 'a restart (new secret) ends every ticket')
        expiry, mac = t.split('.')
        self.assertFalse(api_keys.ticket_valid('secret', '%d.%s' % (int(expiry) + 99999, mac), now=1000), 'the expiry is signed')
        for bad in ('', None, 'x', '.', '12', 'abc.def', t + '0', '9999999999.' + '0' * 64):
            self.assertFalse(api_keys.ticket_valid('secret', bad, now=1000), repr(bad))


class WiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.v1 = [(m, p, n) for m, p, s, n in server.ROUTES.listing() if s == 'v1']

    def test_addresses(self):
        self.assertEqual(sorted((m, p) for m, p, _ in self.v1), sorted([
            ('GET', '/api/v1'), ('GET', '/api/v1/catalog'), ('GET', '/api/v1/title'), ('GET', '/api/v1/show'), ('GET', '/api/v1/live'),
            ('GET', '/api/v1/play'), ('GET', '/api/v1/stream'), ('GET', '/api/v1/file'), ('GET', '/api/v1/downloads'), ('GET', '/api/v1/watch'),
            ('POST', '/api/v1/watch-progress'), ('POST', '/api/v1/watch-mark'), ('POST', '/api/v1/watch-forget')]))
        for _, path, name in self.v1:
            self.assertTrue((getattr(self.server, name).__doc__ or '').strip(), 'summary for ' + path)
        self.assertEqual(self.server.V1_MEDIA, ('/api/v1/stream', '/api/v1/file'))

    def test_a_key_cannot_reach_the_key_management_or_settings(self):
        for method, path in (('GET', '/api/api-keys'), ('POST', '/api/api-key-create'), ('POST', '/api/api-key-revoke'), ('POST', '/api/settings')):
            self.assertEqual(self.server.ROUTES.stage(method, path), 'api', path)
        writes = sorted(p for m, p, _ in self.v1 if m == 'POST')
        self.assertEqual(writes, ['/api/v1/watch-forget', '/api/v1/watch-mark', '/api/v1/watch-progress'], 'a device writes the watch list only')

    def test_order_in_the_handler(self):
        get = SERVER[SERVER.index('    def get(self):'):SERVER.index('    def download_file(self,q')]
        marks = [get.index(x) for x in ('if not self.valid_host()', "ROUTES.find('GET',path,'open')", "return self.v1('GET',path)", 'if not self.authorized():')]
        self.assertEqual(marks, sorted(marks))
        post = SERVER[SERVER.index('    def post(self):'):SERVER.index('    def v1_allowed(self')]
        marks = [post.index(x) for x in ('if not self.valid_host()', "return self.v1('POST',", 'if not self.authorized()')]
        self.assertEqual(marks, sorted(marks))
        allowed = SERVER[SERVER.index('    def v1_allowed(self'):SERVER.index('    def v1(self,method,path):')]
        for part in ("if media and api_keys.ticket_valid(TOKEN,", "self.authorized() and self.headers.get('X-Atlas-Token')==TOKEN",
                     "head.startswith('Bearer ')", 'ACCESS.blocked(client)', 'api_keys.verify(ROOT,', 'ACCESS._failed(client)'):
            self.assertIn(part, allowed)
        v1 = SERVER[SERVER.index('    def v1(self,method,path):'):SERVER.index('    def login(self):')]
        self.assertLess(v1.index('self.v1_allowed('), v1.index("ROUTES.find(method,path,'v1')"), 'unknown addresses are not revealed without a key')

    def test_page_and_packages(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        js = (ROOT / 'web' / 'system.js').read_text(encoding='utf-8')
        for part in ('id="system-keys"', 'id="system-key-form"', 'id="system-key-value"', 'id="system-key-list"'):
            self.assertIn(part, html)
        for part in ("window.api('api-keys')", "window.api('api-key-create', {name})", "window.api('api-key-revoke', {id: k.id})"):
            self.assertIn(part, js)
        self.assertIn("'api_keys.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        doc = (ROOT / 'docs' / 'API_V1.md').read_text(encoding='utf-8')
        for _, path, _n in self.v1:
            self.assertIn('`' + path + '`', doc, 'docs/API_V1.md names ' + path)


class _Live(unittest.TestCase):
    network = False

    @classmethod
    def setUpClass(cls):
        if cls is _Live:
            raise unittest.SkipTest('base class')
        cls.home = tempfile.TemporaryDirectory()
        cls.before()
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()
        env = dict(os.environ, MEDIATHEKATLAS_HOME=cls.home.name, MEDIATHEKATLAS_PORT=str(cls.port), MEDIATHEKATLAS_DISABLE_BACKGROUND='1')
        env.pop('MEDIATHEKATLAS_LOGIN', None)
        if cls.network:
            env['MEDIATHEKATLAS_LOGIN'] = '1'
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
        cls.page = page

    @classmethod
    def before(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.home.cleanup()

    @classmethod
    def call(cls, path, data=None, headers=None):
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (cls.port, path),
                                     data=None if data is None else json.dumps(data).encode(), headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class LocalTests(_Live):
    def test_everything_in_order(self):
        token = {'X-Atlas-Token': re.search(r'atlas-token" content="([^"]+)"', self.page).group(1)}
        # closed without a key
        for path in ('/api/v1', '/api/v1/catalog', '/api/v1/stream?job=1', '/api/v1/file?id=1', '/api/v1/gibt-es-nicht'):
            status, body = self.call(path)
            self.assertEqual((status, json.loads(body).get('api')), (401, 'v1'), path)
        self.assertEqual(self.call('/api/v1/watch-forget', {'key': 'x'})[0], 401)
        self.assertEqual(self.call('/api/v1', headers={'Authorization': 'Bearer atlas_' + 'x' * 43})[0], 401)
        self.assertEqual(self.call('/api/v1', headers={'Authorization': 'Basic abc'})[0], 401)
        self.assertEqual(self.call('/api/v1/stream?job=1&ticket=1.abc')[0], 401)
        # the page creates a key
        self.assertEqual(json.loads(self.call('/api/api-keys', headers=token)[1])['items'], [])
        status, body = self.call('/api/api-key-create', {'name': 'Test TV'}, token)
        self.assertEqual(status, 200)
        made = json.loads(body)['created']
        key = {'Authorization': 'Bearer ' + made['key']}
        self.assertEqual(self.call('/api/api-key-create', {'name': 'Test TV'}, token)[0], 400)      # name taken
        self.assertEqual(self.call('/api/api-key-create', {'name': ''}, token)[0], 400)
        # description
        status, body = self.call('/api/v1', headers=key)
        info = json.loads(body)
        self.assertEqual((status, info['api'], info['name']), (200, 'v1', 'MediathekAtlas'))
        self.assertEqual(info['version'], __import__('version').VERSION)
        paths = {(e['method'], e['path']) for e in info['endpoints']}
        self.assertIn(('GET', '/api/v1/catalog'), paths)
        self.assertIn(('POST', '/api/v1/watch-progress'), paths)
        self.assertTrue(all(e['summary'] for e in info['endpoints']))
        self.assertTrue(all(p.startswith('/api/v1') for _, p in paths), 'the description lists nothing but v1')
        # reading
        for path, field in (('/api/v1/catalog?kind=movies', 'items'), ('/api/v1/live', 'stations'), ('/api/v1/watch', 'continue'),
                            ('/api/v1/downloads', 'items')):
            status, body = self.call(path, headers=key)
            self.assertEqual(status, 200, path)
            self.assertIn(field, json.loads(body), path)
        self.assertEqual(self.call('/api/v1/watch', headers=token)[0], 200, 'the page itself may use v1 as well')
        self.assertEqual(self.call('/api/v1/title?source=unbekannt&id=1', headers=key)[0], 404)
        status, body = self.call('/api/v1/gibt-es-nicht', headers=key)
        self.assertEqual((status, json.loads(body)), (404, {'error': 'Nicht gefunden', 'api': 'v1'}))
        self.assertEqual(self.call('/api/v1/catalog', {}, key)[0], 404, 'a GET address is not a POST address')
        # a key opens v1 only
        for path in ('/api/tasks', '/api/api-keys', '/api/settings', '/api/storage', '/api/stream?job=1'):
            self.assertEqual(self.call(path, headers=key)[0], 403, path)
        for path in ('/api/api-key-create', '/api/settings', '/api/shutdown', '/api/task-action'):
            self.assertEqual(self.call(path, {'name': 'x'}, key)[0], 403, path)
        # watch list
        status, body = self.call('/api/v1/watch-progress', {'key': 'netzkino:abc', 'pos': 120, 'duration': 3600, 'info': {'title': 'Ein Film'}}, key)
        self.assertEqual((status, json.loads(body)['ok']), (200, True))
        state = json.loads(self.call('/api/v1/watch', headers=key)[1])
        self.assertEqual(state['progress']['netzkino:abc']['pos'], 120)
        self.assertEqual(self.call('/api/v1/watch-mark', {'key': 'netzkino:abc', 'favorite': True, 'info': {'title': 'Ein Film'}}, key)[0], 200)
        self.assertEqual(json.loads(self.call('/api/watch', headers=token)[1])['marks']['netzkino:abc']['favorite'], True, 'the page sees it')
        self.assertEqual(self.call('/api/v1/watch-forget', {'key': 'netzkino:abc'}, key)[0], 200)
        req = urllib.request.Request('http://127.0.0.1:%d/api/v1/watch-forget' % self.port, data=b'[1]', headers=key)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(ctx.exception.code, 400)
        # a finished download: list, play info with ticket, the file itself with the ticket alone
        media = Path(self.home.name) / 'film.mp4'
        media.write_bytes(b'\x00\x00\x00\x18ftypmp42' + b'v' * 5000)
        db = sqlite3.connect(str(Path(self.home.name) / 'catalog.db'), timeout=10)
        db.execute("INSERT INTO jobs(id,payload,state) VALUES(?,?,'done')",
                   ('job1', json.dumps({'id': 'job1', 'path': str(media), 'target': str(media), 'metadata': {'title': 'Ein Film', 'year': 2001, 'kind': 'movie'}})))
        db.commit()
        db.close()
        listing = json.loads(self.call('/api/v1/downloads', headers=key)[1])
        self.assertEqual([(i['id'], i['title'], i['file'], i['play']) for i in listing['items']], [('job1', 'Ein Film', 'film.mp4', '/api/v1/play?job=job1')])
        self.assertNotIn(self.home.name, json.dumps(listing), 'no folders of the server for a device')
        status, body = self.call('/api/v1/play?job=job1', headers=key)
        self.assertEqual(status, 200, body)
        play = json.loads(body)
        self.assertTrue(play['src'].startswith('/api/v1/stream?job=job1'), play['src'])
        self.assertTrue(play['remux'].startswith('/api/v1/stream?'))
        ticket = play['ticket']
        self.assertEqual(self.call('/api/play?job=job1', headers=token)[0], 200)
        self.assertNotIn('ticket', json.loads(self.call('/api/play?job=job1', headers=token)[1]), 'the page keeps its own model')
        self.assertTrue(json.loads(self.call('/api/play?job=job1', headers=token)[1])['src'].startswith('/api/stream?'))
        status, body = self.call('/api/v1/file?id=job1&inline=1&ticket=' + ticket)       # no header at all, as a video player would
        self.assertEqual((status, body), (200, media.read_bytes()))
        self.assertEqual(self.call('/api/v1/file?id=job1&inline=1', headers=key)[1], media.read_bytes())
        self.assertEqual(self.call('/api/v1/file?id=job1&inline=1&ticket=' + ticket[:-1] + ('0' if ticket[-1] != '0' else '1'))[0], 401)
        if 'raw=1' in play['src']:
            self.assertEqual(self.call(play['src'] + '&ticket=' + ticket)[1], media.read_bytes())
        # a ticket opens the media addresses only
        self.assertEqual(self.call('/api/v1/catalog?ticket=' + ticket)[0], 401)
        self.assertEqual(self.call('/api/v1/watch-forget?ticket=' + ticket, {'key': 'x'})[0], 401)
        self.assertEqual(self.call('/api/download-file?id=job1&token=' + ticket)[0], 403)
        # withdraw the key
        self.assertEqual(json.loads(self.call('/api/api-keys', headers=token)[1])['items'][0]['name'], 'Test TV')
        self.assertEqual(self.call('/api/api-key-revoke', {'id': made['id']}, token)[0], 200)
        self.assertEqual(self.call('/api/api-key-revoke', {'id': made['id']}, token)[0], 400)
        self.assertEqual(self.call('/api/v1', headers=key)[0], 401)
        self.assertEqual(self.call('/api/v1/file?id=job1&inline=1&ticket=' + ticket)[0], 200, 'a ticket already given out runs until it expires')
        log = (Path(self.home.name) / 'diagnostic.jsonl').read_text(encoding='utf-8')
        self.assertIn('api_key_created', log)
        self.assertNotIn(made['key'], log)
        self.assertNotIn(ticket, log)


class NetworkTests(_Live):
    network = True

    @classmethod
    def before(cls):
        cls.key = api_keys.create(cls.home.name, 'Netz-Gerät')['key']

    def test_key_instead_of_login(self):
        key = {'Authorization': 'Bearer ' + self.key}
        self.assertIn('login', self.page.lower())                               # not signed in: the login page
        self.assertEqual(self.call('/api/v1')[0], 401)
        self.assertEqual(self.call('/api/v1', headers=key)[0], 200)
        self.assertEqual(self.call('/api/v1/watch', headers=key)[0], 200)
        self.assertEqual(self.call('/api/v1/watch-progress', {'key': 'pluto:1', 'pos': 5, 'duration': 50}, key)[0], 200)
        for path in ('/api/tasks', '/api/api-keys', '/api/state'):
            status, body = self.call(path, headers=key)
            self.assertEqual((status, json.loads(body).get('login')), (401, True), path)
        self.assertEqual(self.call('/api/settings', {}, key)[0], 401)
        self.assertEqual(self.call('/api/api-key-create', {'name': 'x'}, key)[0], 401)
        self.assertNotIn('atlas-token', self.call('/', headers=key)[1].decode(), 'a key does not open the page')
        # wrong keys count like wrong passwords; then even the right key waits
        import access
        for n in range(access.FAILURES):
            self.assertEqual(self.call('/api/v1', headers={'Authorization': 'Bearer atlas_%043d' % n})[0], 401)
        self.assertEqual(self.call('/api/v1', headers=key)[0], 401, 'blocked after too many wrong keys')


if __name__ == '__main__':
    unittest.main()
