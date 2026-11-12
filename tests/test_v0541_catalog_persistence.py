"""0.5.41: portal catalogues (Netzkino, Pluto, JustWatch) stay after a restart; an interrupted
run is reported as such, partial runs keep the stock visible, one automatic first load."""
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import justwatch as jw, pluto, portal_reference as pr  # noqa: E402
from test_v0540_justwatch import Fixture as JwFixture, PAGE1  # noqa: E402
from test_v0536_pluto import Fixture as PlutoFixture  # noqa: E402


class RuleTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(pr.stored_result('running', False), 'interrupted')
        self.assertEqual(pr.stored_result('running', True), 'running')
        self.assertEqual(pr.stored_result('complete', False), 'complete')
        self.assertTrue(pr.first_load_due({'last_success': 0, 'last_attempt': 0, 'running': False}))
        self.assertFalse(pr.first_load_due({'last_success': 0, 'last_attempt': 5, 'running': False}))
        self.assertFalse(pr.first_load_due({'last_success': 9, 'last_attempt': 9, 'running': False}))


class JustWatchRestartTests(JwFixture):
    def test_catalogue_survives_restart_and_interrupted_run(self):
        self.sync(now=1000)
        db = jw._connect(self.root)
        with db:
            jw._set(db, 'last_result', 'running')   # app quit during a run
        db.close()
        importlib.reload(jw)   # fresh process state
        st = jw.state(self.root)
        self.assertEqual((st['last_result'], st['movies'], st['running']), ('interrupted', 2, False))
        self.assertEqual(jw.listing(self.root, 'movies')['total'], 2)
        self.assertFalse(pr.first_load_due(st))

    def test_partial_run_keeps_older_titles(self):
        self.sync(now=1000)
        def second(query, variables):
            if variables['after']:
                raise OSError('weg')
            return {'data': {'popularTitles': {'edges': [{'cursor': '0', 'node': PAGE1[0]}], 'totalCount': 4,
                                               'pageInfo': {'endCursor': 'NDA=', 'hasNextPage': True}}}}
        result = jw.sync(self.root, post=second, now=5000, gap=0)
        self.assertTrue(result['partial'])
        self.assertEqual(jw.listing(self.root, 'series')['total'], 1)   # Spy City from the first run stays
        self.assertEqual(jw.listing(self.root, 'movies')['total'], 2)


class PlutoRestartTests(PlutoFixture):
    def test_catalogue_survives_restart(self):
        self.sync()
        db = pluto._connect(self.root)
        with db:
            pluto._set(db, 'last_result', 'running')
        db.close()
        st = pluto.state(self.root)
        self.assertEqual(st['last_result'], 'interrupted')
        self.assertGreater(pluto.listing(self.root, 'movies')['total'], 0)


class UiTests(unittest.TestCase):
    def test_labels(self):
        panel = (ROOT / 'web' / 'portal_panel.js').read_text()
        self.assertIn('Gespeicherter Bestand', panel)
        self.assertIn('bleibt nach Neustart erhalten', panel)
        self.assertIn("'interrupted'", (ROOT / 'web' / 'netzkino.js').read_text())
        for name in ('pluto.py', 'justwatch.py', 'netzkino.py'):
            self.assertIn('first_load_due', (ROOT / name).read_text())


class RequestTimingTests(unittest.TestCase):
    def test_active_and_slow_requests(self):
        import http_timing
        logged = []
        k1 = http_timing.start('GET', '/api/pluto?view=movies&q=geheim', now=100.0)
        k2 = http_timing.start('GET', '/api/state', now=103.0)
        snap = http_timing.snapshot(now=110.0)
        paths = [a['endpoint'] for a in snap['active']]
        self.assertIn('/api/pluto', paths)
        self.assertNotIn('geheim', str(snap))           # query strings are never kept
        self.assertEqual(snap['active'][0]['endpoint'], '/api/pluto')   # oldest first
        http_timing.finish(k1, log=lambda *a: logged.append(a), now=112.0)
        http_timing.finish(k2, log=lambda *a: logged.append(a), now=104.0)   # fast: not logged
        self.assertEqual(logged, [('/api/pluto', 12.0, 'GET')])
        self.assertEqual(http_timing.snapshot()['slow']['/api/pluto']['count'], 1)
        k3 = http_timing.start('GET', '/api/pluto', now=130.0)
        http_timing.finish(k3, log=lambda *a: logged.append(a), now=160.0)   # within a minute: counted only
        self.assertEqual(len(logged), 1)
        self.assertEqual(http_timing.snapshot()['slow']['/api/pluto']['max_seconds'], 30.0)
        k4 = http_timing.start('GET', '/api/stream', now=0.0)
        http_timing.finish(k4, log=lambda *a: logged.append(a), now=500.0)
        self.assertNotIn('/api/stream', http_timing.snapshot()['slow'])

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text()
        self.assertIn("'http':http_timing.snapshot()", server)
        self.assertIn("def do_POST(self):return self.timed('POST',self.post)", server)
        self.assertIn('http_timing.py', (ROOT / 'build_macos.py').read_text())
        app = (ROOT / 'web' / 'app.js').read_text()
        self.assertIn('window.atlasWaiting', app)
        self.assertIn("portalView($('portals').dataset.platform||'overview')", app)
        self.assertIn('atlasWaiting', (ROOT / 'web' / 'portal_panel.js').read_text())
        self.assertIn('atlasWaiting', (ROOT / 'web' / 'netzkino.js').read_text())


if __name__ == '__main__':
    unittest.main()
