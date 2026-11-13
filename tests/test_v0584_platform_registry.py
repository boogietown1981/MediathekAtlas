"""0.5.84: the routes and threads every film platform shares come from platform_registry
instead of copied blocks in server.py. Addresses, answers and event names stay as they were."""
import sys
import threading
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import platform_registry as registry  # noqa: E402

# The addresses 0.5.82 answered with written-out blocks in server.py.
BEFORE = {
    'GET': ['/api/pluto', '/api/justwatch', '/api/rakuten', '/api/joyn', '/api/toggo',
            '/api/pluto-details', '/api/justwatch-details', '/api/rakuten-details', '/api/joyn-details', '/api/toggo-details',
            '/api/youtube-details', '/api/pluto-downloads', '/api/justwatch-downloads', '/api/rakuten-downloads',
            '/api/joyn-downloads', '/api/toggo-downloads', '/api/youtube-downloads'],
    'POST': ['/api/pluto-sync', '/api/pluto-auto', '/api/pluto-enrich', '/api/pluto-download-add',
             '/api/justwatch-sync', '/api/justwatch-auto', '/api/justwatch-enrich', '/api/justwatch-download-add',
             '/api/rakuten-sync', '/api/rakuten-auto', '/api/rakuten-enrich', '/api/rakuten-download-add',
             '/api/joyn-sync', '/api/joyn-auto', '/api/joyn-enrich', '/api/toggo-sync', '/api/toggo-auto', '/api/toggo-enrich',
             '/api/youtube-sync', '/api/youtube-auto', '/api/youtube-enrich'],
}
# Routes that only one platform has; they stay in server.py and must not be taken over here.
OWN = [('GET', '/api/youtube'), ('GET', '/api/youtube-sources'), ('POST', '/api/youtube-download-add'), ('POST', '/api/youtube-sources'),
       ('POST', '/api/youtube-key'), ('POST', '/api/youtube-offline'), ('GET', '/api/netzkino'), ('GET', '/api/netzkino-details'),
       ('GET', '/api/netzkino-downloads'), ('POST', '/api/netzkino-sync'), ('POST', '/api/netzkino-auto'), ('POST', '/api/netzkino-enrich'),
       ('POST', '/api/netzkino-download-add'), ('POST', '/api/joyn-download-add'), ('POST', '/api/toggo-download-add')]


class RouteTableTests(unittest.TestCase):
    def test_exactly_the_former_routes(self):
        table = registry.routes()
        self.assertEqual(sorted(table), sorted((m, p) for m, paths in BEFORE.items() for p in paths))
        self.assertEqual(len(table), len(set(table)))

    def test_own_routes_stay_in_server(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        for method, path in OWN:
            self.assertFalse(registry.serves(method, path), path)
            if 'joyn-download' not in path and 'toggo-download' not in path:
                self.assertIn("'%s'" % path, server)
        # None of the shared routes is written out a second time.
        for method, paths in BEFORE.items():
            for path in paths:
                self.assertNotIn("path=='%s'" % path, server, path)
        self.assertIn('platform_registry.handle_get(platform_context()', server)
        self.assertIn('platform_registry.handle_post(platform_context()', server)
        self.assertIn('platform_registry.start_background(platform_context(),STOP)', server)

    def test_platforms_match_the_task_list(self):
        import task_control
        self.assertEqual(sorted(registry.KEYS), sorted(k for k, _ in task_control.PORTALS))
        self.assertEqual(registry.BY_KEY['justwatch'].name, 'JustWatch TV')
        self.assertEqual(len(registry.thread_names()), 2 * len(registry.PLATFORMS))
        for name in ('netzkino_auto_enrichment', 'toggo_catalog_scheduler', 'youtube_auto_enrichment'):
            self.assertIn(name, registry.thread_names())


class Fake:
    """A platform made of recording stand-ins."""

    def __init__(self):
        self.calls = []
        self.module = types.SimpleNamespace(
            episodes=lambda root, series: self._note('episodes', series) or {'items': [series]},
            item=self._item, state=lambda root: {'series': 3},
            start_sync=lambda root: self._note('sync') or True,
            set_auto=lambda root, enabled: self._note('auto', enabled) or {'auto': bool(enabled)},
            loop=lambda root, stop: self._note('catalog_loop'))
        self.enrichment = types.SimpleNamespace(enrich=self._enrich, loop=lambda root, settings, slots, stop: self._note('enrich_loop'))
        self.offline = types.SimpleNamespace(enqueue=lambda c, root, folder, item_id: self._note('enqueue', folder, item_id) or {'created': 1, 'jobs': []})

    def _note(self, *what):
        self.calls.append(what)

    def _item(self, root, item_id):
        if item_id == 'missing':
            raise ValueError('Titel nicht im Katalog')
        return {'id': item_id}

    def _enrich(self, root, item_id, settings, force=False):
        self._note('enrich', item_id, force)
        if item_id == 'broken':
            raise OSError('provider down')
        return {'status': 'candidate', 'references': [{}, {}]}


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.platform = registry.Platform('pluto', self.fake.module, self.fake.enrichment, self.fake.offline)
        patch = mock.patch.dict(registry.BY_KEY, {'pluto': self.platform,
                                                  'joyn': registry.Platform('joyn', self.fake.module, self.fake.enrichment)})
        patch.start()
        self.addCleanup(patch.stop)

        @contextmanager
        def db():
            yield 'connection'
        self.ctx = types.SimpleNamespace(root=Path('/nowhere'), db=db, settings=lambda: {'download_dir': '/dl'}, slots=threading.Semaphore(2),
                                         portal_page=lambda key, module, q: {'page': key, 'view': q.get('view', ['movies'])[0]},
                                         job_ids=lambda q: q.get('id', [''])[0] or None)

    def test_page_episodes_and_details(self):
        self.assertEqual(registry.handle_get(self.ctx, '/api/pluto', {}), ({'page': 'pluto', 'view': 'movies'}, 200))
        with mock.patch.object(registry.portal_snapshot, 'status', lambda key, fn: {'key': key, **fn()}):
            data, status = registry.handle_get(self.ctx, '/api/pluto', {'view': ['episodes'], 'series': ['s1']})
        self.assertEqual((data, status), ({'items': ['s1'], 'status': {'key': 'pluto', 'series': 3}}, 200))
        self.assertEqual(registry.handle_get(self.ctx, '/api/pluto-details', {'id': ['a1']}), ({'id': 'a1'}, 200))
        self.assertEqual(registry.handle_get(self.ctx, '/api/pluto-details', {'id': ['missing']}), ({'error': 'Titel nicht im Katalog'}, 404))

    def test_offline_list_also_without_offline_copies(self):
        seen = []
        with mock.patch.object(registry.netzkino_downloads, 'listing', lambda c, item_id=None, origin='': seen.append((c, item_id, origin)) or {'jobs': []}), \
                mock.patch.object(registry.downloads, 'tool', lambda name: '/usr/bin/' + name):
            self.assertEqual(registry.handle_get(self.ctx, '/api/pluto-downloads', {'id': ['x']}), ({'jobs': [], 'ffmpeg': True}, 200))
            self.assertEqual(registry.handle_get(self.ctx, '/api/joyn-downloads', {})[0], {'jobs': [], 'ffmpeg': True})
        self.assertEqual(seen, [('connection', 'x', 'pluto'), ('connection', None, 'joyn')])

    def test_unknown_routes_are_left_to_the_server(self):
        for path in ('/api/state', '/api/pluto-unknown', '/api/plutox', '/pluto', '/api/joyn-download-add'):
            self.assertIsNone(registry.handle_get(self.ctx, path, {}), path)
            self.assertIsNone(registry.handle_post(self.ctx, path, {}), path)
        self.assertIsNone(registry.handle_post(self.ctx, '/api/pluto', {}))
        self.assertIsNone(registry.handle_get(self.ctx, '/api/pluto-sync', {}))

    def test_actions(self):
        events = []
        with mock.patch.object(registry.diagnostics, 'event', lambda name, **kw: events.append((name, kw))), \
                mock.patch.object(registry.diagnostics, 'error', lambda name, exc: events.append((name, type(exc).__name__))), \
                mock.patch.object(registry.download_quality, 'set_job', lambda c, result, quality: events.append(('quality', quality))):
            self.assertEqual(registry.handle_post(self.ctx, '/api/pluto-sync', {}), {'started': True})
            self.assertEqual(registry.handle_post(self.ctx, '/api/pluto-auto', {'enabled': True}), {'status': {'auto': True}})
            self.assertEqual(registry.handle_post(self.ctx, '/api/pluto-enrich', {'id': 'a1', 'force': True})['status'], 'candidate')
            self.assertEqual(registry.handle_post(self.ctx, '/api/pluto-download-add', {'id': 'a1', 'quality': '720'}), {'created': 1, 'jobs': []})
            # A provider failure never blocks the download.
            self.assertEqual(registry.handle_post(self.ctx, '/api/pluto-download-add', {'id': 'broken'})['created'], 1)
        self.assertEqual(self.fake.calls, [('sync',), ('auto', True), ('enrich', 'a1', True), ('enrich', 'a1', False), ('enqueue', '/dl', 'a1'),
                                           ('enrich', 'broken', False), ('enqueue', '/dl', 'broken')])
        self.assertEqual(events, [('pluto_reference_check', {'status': 'candidate', 'candidates': 2}), ('quality', '720'),
                                  ('pluto_download_enqueued', {'created': 1}), ('pluto_download_enrich_failed', 'OSError'),
                                  ('quality', None), ('pluto_download_enqueued', {'created': 1})])

    def test_background_threads(self):
        with mock.patch.object(registry, 'PLATFORMS', (self.platform,)):
            threads = registry.start_background(self.ctx, threading.Event())
        for t in threads:
            t.join(2)
        self.assertEqual(sorted(t.name for t in threads), ['pluto_auto_enrichment', 'pluto_catalog_scheduler'])
        self.assertEqual(sorted(self.fake.calls), [('catalog_loop',), ('enrich_loop',)])


class BundleTests(unittest.TestCase):
    def test_module_is_packaged_and_packages_left_git(self):
        self.assertIn("'platform_registry.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn('downloads/', (ROOT / '.gitignore').read_text(encoding='utf-8').split())


if __name__ == '__main__':
    unittest.main()
