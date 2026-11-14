"""0.5.55: dashboard with films and series only, merged tiles, Verwaltung (tasks, presentation),
fast catalogue pages (diagnosis 12.11.2026: /api/catalog took 7-31 s on every call)."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402
import job_queue  # noqa: E402
import netzkino_enrichment  # noqa: E402
import streaming  # noqa: E402
import task_control  # noqa: E402
import ui_prefs  # noqa: E402
import unified_index  # noqa: E402


class TaskControlTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'task-control.json'
        task_control.configure(self.path)

    def tearDown(self):
        task_control.configure(Path(self.dir.name) / 'unused.json')
        self.dir.cleanup()

    def test_pause_and_priority_survive_restart(self):
        self.assertFalse(task_control.paused('recognition'))
        task_control.set_paused('recognition', True)
        task_control.set_priority('enrich:pluto', 'high')
        self.assertLess(task_control.factor('enrich:pluto'), 1)
        task_control.configure(self.path)   # restart
        self.assertTrue(task_control.paused('recognition'))
        self.assertEqual(task_control.priority('enrich:pluto'), 'high')
        self.assertEqual(task_control.priority('enrich:rakuten'), 'normal')
        task_control.set_paused('recognition', False)
        task_control.set_priority('enrich:pluto', 'normal')
        self.assertEqual(json.loads(self.path.read_text()), {})   # only deviations are stored

    def test_invalid_requests_are_refused(self):
        for call in (lambda: task_control.set_paused('nope', True),
                     lambda: task_control.set_priority('recognition', 'high'),     # no priority for workers
                     lambda: task_control.set_priority('enrich:pluto', 'urgent'),
                     lambda: task_control.request('nope')):
            with self.assertRaises(ValueError):
                call()

    def test_unknown_or_broken_file_is_ignored(self):
        self.path.write_text('{"gone-task":{"paused":true},"downloads":{"paused":true,"priority":"x"}}')
        task_control.configure(self.path)
        self.assertTrue(task_control.paused('downloads'))
        self.assertEqual(task_control.priority('downloads'), 'normal')
        self.path.write_text('not json')
        task_control.configure(self.path)
        self.assertFalse(task_control.paused('downloads'))

    def test_group_pause_request_and_overview(self):
        task_control.pause_all(True, 'Katalogabrufe')
        self.assertTrue(task_control.paused('catalog:youtube'))
        self.assertTrue(task_control.paused('filmlist'))
        self.assertFalse(task_control.paused('downloads'))
        task_control.pause_all(False)
        self.assertFalse(any(row['paused'] for row in task_control.overview()))
        task_control.request('imdb')
        self.assertTrue(task_control.take_request('imdb'))
        self.assertFalse(task_control.take_request('imdb'))
        ids = [row['id'] for row in task_control.overview()]
        for portal in ('netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube'):
            self.assertIn('catalog:' + portal, ids)
            self.assertIn('enrich:' + portal, ids)

    def test_wait_if_paused_ends_with_stop(self):
        task_control.set_paused('artwork', True)
        stop = threading.Event()
        threading.Timer(0.15, stop.set).start()
        started = time.monotonic()
        self.assertFalse(task_control.wait_if_paused('artwork', stop, poll=0.05))
        self.assertLess(time.monotonic() - started, 2)
        task_control.set_paused('artwork', False)
        self.assertTrue(task_control.wait_if_paused('artwork', threading.Event()))

    def test_enrichment_loop_honours_pause(self):
        checked, stop = [], threading.Event()

        def enrich_one(root, item_id, settings):
            checked.append(item_id)
            if len(checked) == 2:
                task_control.set_paused('enrich:pluto', True)

        def pending(root, limit=20, **_):
            return [i for i in ('a', 'b', 'c', 'd') if i not in checked][:limit]
        worker = threading.Thread(target=netzkino_enrichment.loop, daemon=True,
                                  args=(None, lambda: {'auto_metadata': True}, threading.Semaphore(2), stop),
                                  kwargs={'gap': 0.01, 'idle': 0.05, 'enrich_one': enrich_one, 'pending_fn': pending, 'name': 'pluto'})
        worker.start()
        time.sleep(0.6)
        self.assertEqual(checked, ['a', 'b'])          # paused after the running title
        task_control.set_paused('enrich:pluto', False)
        deadline = time.monotonic() + 5
        while len(checked) < 4 and time.monotonic() < deadline:
            time.sleep(0.05)
        stop.set()
        worker.join(3)
        self.assertEqual(checked, ['a', 'b', 'c', 'd'])


def queue(*jobs):
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
    for job in jobs:
        c.execute('INSERT INTO jobs VALUES(?,?,?)', (job['id'], json.dumps(job), job.get('state', 'queued')))
    return c


class DownloadOrderTests(unittest.TestCase):
    def test_priority_hold_and_night(self):
        c = queue({'id': 'a'}, {'id': 'b'}, {'id': 'night', 'not_before': 2000, 'night': True}, {'id': 'c'})
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'a')
        job_queue.control(c, 'c', 'first')
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'c')
        job_queue.control(c, 'c', 'hold')
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'a')
        job_queue.control(c, 'a', 'hold')
        job_queue.control(c, 'b', 'hold')
        self.assertIsNone(job_queue.next_job(c, now=1000))      # held and night jobs do not start
        self.assertEqual(job_queue.summary(c, now=1000), {'queued': 0, 'held': 3, 'night': 1, 'active': 0, 'failed': 0})
        job_queue.control(c, 'night', 'now')
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'night')
        job_queue.control(c, 'c', 'release')
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'c')   # still first after release
        job_queue.control(c, 'c', 'normal')
        self.assertEqual(job_queue.next_job(c, now=1000)['id'], 'night')

    def test_only_waiting_jobs_and_known_actions(self):
        c = queue({'id': 'run', 'state': 'downloading'}, {'id': 'q'})
        with self.assertRaises(ValueError):
            job_queue.control(c, 'run', 'first')
        with self.assertRaises(ValueError):
            job_queue.control(c, 'q', 'delete-everything')
        self.assertEqual(job_queue.summary(c)['active'], 1)


class MergeTests(unittest.TestCase):
    def test_title_key(self):
        key = unified_index.title_key
        self.assertEqual(key('#Roxy (ROMANTISCHE KOMÖDIE mit SARAH FISHER, Comedy Filme , Teenager', True), key('#Roxy'))
        self.assertEqual(key('#Squadgoals (HIGHSCHOOL HORROR , Horror Slasher Filme komplett neu', True), key('#SquadGoals'))
        self.assertEqual(key('Die Brücke | Ganzer Film auf Deutsch', True), key('Die Brücke'))
        self.assertEqual(key('Größe & Würde'), key('Grosse und Wurde'))
        self.assertNotEqual(key('Der Pate'), key('Der Pate 2'))
        self.assertEqual(key('Film (Teil 1)'), 'filmteil1')       # curated titles keep their brackets

    def test_same_title_of_several_providers_is_one_entry(self):
        offers = [{'source': 'youtube', 'title': '#Roxy (ROMANTISCHE KOMÖDIE mit SARAH FISHER', 'year': 2026},
                  {'source': 'pluto', 'title': '#Roxy', 'year': 2018},
                  {'source': 'netzkino', 'title': '#Roxy', 'year': 2018}]
        entries = unified_index.merge(offers)
        self.assertEqual(len(entries), 1)
        self.assertEqual([o['source'] for o in entries[0]['offers']], ['netzkino', 'pluto', 'youtube'])
        self.assertEqual((entries[0]['title'], entries[0]['year']), ('#Roxy', 2018))
        self.assertEqual(len(unified_index.merge(offers, enabled=False)), 3)   # switch in Verwaltung → Darstellung

    def test_conservative_rules(self):
        merge = unified_index.merge
        # Remake: same title, years far apart -> two tiles.
        self.assertEqual(len(merge([{'source': 'pluto', 'title': 'Solaris', 'year': 1972},
                                    {'source': 'netzkino', 'title': 'Solaris', 'year': 2002}])), 2)
        # Cinema year vs. broadcast year: one apart -> one tile.
        self.assertEqual(len(merge([{'source': 'pluto', 'title': 'Solaris', 'year': 1972},
                                    {'source': 'mediatheken', 'title': 'Solaris', 'year': 1973}])), 1)
        # Two offers of the same provider never share a tile.
        self.assertEqual(len(merge([{'source': 'pluto', 'title': 'Heidi', 'year': None},
                                    {'source': 'pluto', 'title': 'Heidi', 'year': None}])), 2)
        # Unknown year joins, the upload year of YouTube is not a film year.
        entries = merge([{'source': 'rakuten', 'title': 'Heidi', 'year': None}, {'source': 'youtube', 'title': 'Heidi', 'year': 2025},
                         {'source': 'justwatch', 'title': 'Heidi', 'year': 1952}])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['year'], 1952)
        # Empty keys (titles of symbols only) never collapse into one tile.
        self.assertEqual(len(merge([{'source': 'pluto', 'title': '???', 'year': None}, {'source': 'netzkino', 'title': '!!!', 'year': None}])), 2)


class Portal:
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls = rows, fail, 0

    def listing(self, root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
        self.calls += 1
        if self.fail:
            raise OSError('Datenbank gesperrt')
        assert limit == 'all'
        kind = 'series' if view == 'series' else 'movie'
        rows = [dict(r) for r in self.rows if r['kind'] == kind and query.casefold() in r['title'].casefold()]
        return {'items': rows, 'total': len(rows), 'genre_counts': [{'genre': 'Drama', 'n': len(rows)}]}

    def grouped_catalog(self, root, view='movies', series_key='', query='', origin='all', offset=0, limit=80, genre='',
                        sort='updated', collection=''):
        data = self.listing(root, view=view, query=query, limit=limit)
        for row in data['items']:
            row['media_type'] = row.pop('kind')
        return data


class UnifiedPageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / 'catalog.db'

        @contextmanager
        def db():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()
        self.db = db
        with db() as c:
            catalog.initialize(c)
            for i, (title, year) in enumerate((('Zebra', 2001), ('#Roxy', 2018), ('Ärger im Paradies', 1990))):
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          ('w%d' % i, title, 'movie', year, '', json.dumps({'title': title, 'kind': 'movie', 'year': year}), 'matched', 1.0))
                c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                          ('o%d' % i, 'w%d' % i, json.dumps({'title': title, 'channel': 'ARD', 'url_video': 'https://example.org/v.mp4'}), '', 1, 1.0))
        self.modules = {
            'netzkino': Portal([{'id': 'n1', 'kind': 'movie', 'title': '#Roxy', 'year': 2018}]),
            'pluto': Portal([{'id': 'p1', 'kind': 'movie', 'title': '#Roxy', 'year': 2018},
                             {'id': 'p2', 'kind': 'movie', 'title': 'Alpha', 'year': 1999},
                             {'id': 'p3', 'kind': 'series', 'title': 'Serie', 'year': 2000}]),
            'youtube': Portal([{'id': 'y1', 'kind': 'movie', 'title': '#Roxy (ROMANTISCHE KOMÖDIE)', 'year': 2026}]),
            'rakuten': Portal([], fail=True)}
        unified_index.invalidate()

    def tearDown(self):
        unified_index.invalidate()
        self.dir.cleanup()

    def test_merged_sorted_page(self):
        page = unified_index.page(self.dir.name, self.db, modules=self.modules)
        self.assertEqual([i['title'] for i in page['items']], ['Alpha', 'Ärger im Paradies', '#Roxy', 'Zebra'])
        roxy = page['items'][2]
        self.assertEqual([o['source'] for o in roxy['offers']], ['mediatheken', 'netzkino', 'pluto', 'youtube'])
        self.assertEqual(roxy['offers'][0]['item']['work_id'], 'w1')          # full catalogue row for the tile
        self.assertEqual(page['total'], 4)
        self.assertEqual(page['merged'], 1)
        self.assertEqual(page['counts'], {'mediatheken': 3, 'netzkino': 1, 'pluto': 2, 'youtube': 1})
        self.assertIn('rakuten', page['errors'])                              # a broken source hides nothing else
        self.assertEqual(page['genre_counts'], [{'genre': 'Drama', 'n': 4}])

    def test_filters_paging_and_cache(self):
        first = unified_index.page(self.dir.name, self.db, query='roxy', modules=self.modules)
        self.assertEqual(first['total'], 1)
        calls = self.modules['pluto'].calls
        unified_index.page(self.dir.name, self.db, query='roxy', offset=48, modules=self.modules)
        self.assertEqual(self.modules['pluto'].calls, calls)                  # paging reads the index from memory
        self.assertEqual(unified_index.page(self.dir.name, self.db, kind='series', modules=self.modules)['total'], 1)
        self.assertEqual(unified_index.page(self.dir.name, self.db, merge_duplicates=False, modules=self.modules)['total'], 7)
        by_year = unified_index.page(self.dir.name, self.db, sort='year', modules=self.modules)
        self.assertEqual(by_year['items'][0]['title'], '#Roxy')
        self.assertEqual(unified_index.page(self.dir.name, self.db, offset='x', sort='drop table', modules=self.modules)['offset'], 0)

    def test_removed_work_is_skipped(self):
        unified_index.page(self.dir.name, self.db, modules=self.modules)
        with self.db() as c:
            c.execute("DELETE FROM works WHERE id='w0'")
        page = unified_index.page(self.dir.name, self.db, modules=self.modules)   # index still cached
        self.assertNotIn('Zebra', [i['title'] for i in page['items']])


class ListingCacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / 'catalog.db'

        @contextmanager
        def db():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()
        self.db = db
        with db() as c:
            catalog.initialize(c)
            for i in range(60):
                self.add(c, i)
        catalog.invalidate_listings(drop=True)
        catalog.LISTING_DB = db

    def tearDown(self):
        catalog.LISTING_DB = None
        catalog.invalidate_listings(drop=True)
        self.dir.cleanup()

    @staticmethod
    def add(c, i, show='show%02d'):
        c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                  ('w%03d' % i, 'Serie %02d' % (i // 2), 'series', 2000, show % (i // 2),
                   json.dumps({'title': 'Serie %02d' % (i // 2), 'kind': 'series', 'season': 1, 'episode': i % 2 + 1}), 'matched', 1.0))
        c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                  ('o%03d' % i, 'w%03d' % i, json.dumps({'title': 'Folge', 'channel': 'ARD'}), '', 1, 1.0))

    def test_index_covers_the_grouping(self):
        with self.db() as c:
            plan = ' '.join(r[3] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT MIN(w.id),COUNT(*) FROM works w WHERE w.kind=? GROUP BY w.show_key", ('series',)))
        self.assertIn('COVERING INDEX work_listing', plan)

    def test_pages_come_from_memory_until_invalidated(self):
        with self.db() as c:
            first = catalog.listing(c, kind='series', downloaded='all')
            builds = catalog.listing_cache_stats()['builds']
            second = catalog.listing(c, kind='series', downloaded='all', offset=24)
        self.assertEqual((first['total'], len(first['items']), second['total']), (30, 30, 30))
        self.assertEqual(first['items'][0]['episodes'], 2)
        self.assertEqual(catalog.listing_cache_stats()['builds'], builds)       # second page: no new aggregation
        with self.db() as c:
            self.add(c, 60)
            self.add(c, 61)
            self.assertEqual(catalog.listing(c, kind='series', downloaded='all')['total'], 30)   # served from memory
            catalog.invalidate_listings()
            self.assertEqual(catalog.listing(c, kind='series', downloaded='all')['total'], 31)   # quick lists renew at once

    def test_slow_aggregation_answers_stale_and_renews_in_background(self):
        with self.db() as c:
            catalog.listing(c, kind='series', downloaded='all')
        with catalog._LISTING_LOCK:
            for entry in catalog._LISTING.values():
                entry['seconds'] = 30.0                                          # as measured on Björn's catalogue
        with self.db() as c:
            self.add(c, 60)
        catalog.invalidate_listings()
        with self.db() as c:
            started = time.monotonic()
            self.assertEqual(catalog.listing(c, kind='series', downloaded='all')['total'], 30)
            self.assertLess(time.monotonic() - started, 1)
        deadline = time.monotonic() + 5
        total = 30
        while total == 30 and time.monotonic() < deadline:
            time.sleep(0.05)
            with catalog._LISTING_LOCK:
                total = max(len(e['rows']) for e in catalog._LISTING.values())
        self.assertEqual(total, 31)

    def test_without_server_every_call_reads_the_database(self):
        catalog.LISTING_DB = None
        with self.db() as c:
            self.assertEqual(catalog.listing(c, kind='series', downloaded='all')['total'], 30)
            self.add(c, 60)
            self.assertEqual(catalog.listing(c, kind='series', downloaded='all')['total'], 31)
            self.assertEqual(len(catalog.listing(c, kind='series', downloaded='all', index_only=True)[0]), 4)


class DisplayTests(unittest.TestCase):
    def test_defaults_validation_and_storage(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(ui_prefs.load(root), ui_prefs.DEFAULTS)
            self.assertEqual((ui_prefs.DEFAULTS['start_source'], ui_prefs.DEFAULTS['start_kind']), ('all', 'movies'))
            saved = ui_prefs.save(root, {'card_description': False, 'card_size': 'compact', 'start_source': 'evil',
                                         'card_poster': 'no', 'unknown': 1})
            self.assertFalse(saved['card_description'])
            self.assertEqual(saved['card_size'], 'compact')
            self.assertEqual(saved['start_source'], 'all')
            self.assertTrue(saved['card_poster'])
            self.assertNotIn('unknown', saved)
            self.assertEqual(ui_prefs.save(root, {'card_size': 'large'})['card_description'], False)   # other choices stay
            (Path(root) / 'display.json').write_text('{broken')
            self.assertEqual(ui_prefs.load(root), ui_prefs.DEFAULTS)

    def test_every_switch_has_a_style_rule(self):
        css = (ROOT / 'web' / 'style.css').read_text()
        for key in ui_prefs.SWITCHES:
            if key.startswith(('card_', 'title_')):
                self.assertIn('body.atlas-hide-' + key.replace('_', '-') + ' ', css, key)


class StreamTests(unittest.TestCase):
    def test_online_streams_are_delivered_in_short_fragments(self):
        original = streaming.tool
        streaming.tool = lambda name: '/usr/bin/' + name
        try:
            online = streaming.command({'kind': 'url', 'url': 'https://example.org/live.m3u8', 'hls': True})
            local = streaming.command({'kind': 'file', 'path': '/tmp/a.mkv'})
        finally:
            streaming.tool = original
        self.assertEqual(online[online.index('-frag_duration') + 1], '1000000')
        self.assertNotIn('-frag_duration', local)
        self.assertEqual(online[-3:], ['-f', 'mp4', 'pipe:1'])


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / 'web' / 'index.html').read_text()
        self.app = (ROOT / 'web' / 'app.js').read_text()
        self.server = (ROOT / 'server.py').read_text()

    def test_navigation_dashboard_and_verwaltung(self):
        nav = self.html[self.html.index('<nav>'):self.html.index('</nav>')]
        self.assertEqual(nav.count('class="nav'), 5)
        for label in ('Dashboard', 'Plattformen', 'Live-TV', 'Downloads', 'Verwaltung'):
            self.assertIn(label, nav)
        for view in ('admin', 'status', 'display', 'review', 'subscriptions', 'legacy', 'logs', 'settings'):
            self.assertIn('class="admin-tab" data-view="%s"' % view, self.html)
            self.assertIn('<section id="%s"' % view, self.html)
        self.assertIn('data-catalog-source="all" class="primary"', self.html)
        self.assertIn('data-cross-kind="movies" class="primary"', self.html)

    def test_existing_areas_are_kept(self):
        # Moved, not removed: status boards, work catalogue with genre tree, settings.
        for marker in ('id="catalog-status"', 'id="provider-status"', 'id="catalog-tree"', 'id="results"',
                       'id="metadata-workers-status"', 'id="config"', 'id="state-filter"', 'id="imdb-dataset-grid"'):
            self.assertIn(marker, self.html, marker)
        js = (ROOT / 'web' / 'unified_catalog.js').read_text()
        self.assertIn("$('legacy-body')", js)
        self.assertIn("$('status-boards')", js)

    def test_work_catalogue_no_longer_reloads_all_the_time(self):
        self.assertIn("atlasView==='legacy'&&Date.now()-catalogReloaded>60000", self.app)
        self.assertNotIn('renderTree([]);loadCatalog();', self.app)
        self.assertIn("if(!appStopped&&atlasView==='legacy')loadTree()", self.app)

    def test_platform_tabs_use_the_shared_tile(self):
        self.assertIn('shared.card(shared.portalRow(item, K))', (ROOT / 'web' / 'portal_panel.js').read_text())
        self.assertIn('shared.card(shared.netzkinoRow(item))', (ROOT / 'web' / 'netzkino.js').read_text())
        self.assertIn('window.AtlasCards={card:makeCard', (ROOT / 'web' / 'unified_catalog.js').read_text())
        self.assertIn("platform-admin", (ROOT / 'web' / 'admin.js').read_text())

    def test_server_endpoints_and_loops(self):
        for needle in ("@ROUTES.get('/api/tasks')", "@ROUTES.post('/api/task-action')", "@ROUTES.get('/api/display')", "@ROUTES.get('/api/unified')",
                       "@ROUTES.post('/api/job-control')", "'/admin.js','/display.js'", "task_control.paused('downloads')",
                       'catalog.LISTING_DB=db', 'prewarm_listing'):
            self.assertIn(needle, self.server, needle)
        service = (ROOT / 'catalog_service.py').read_text()
        for task in ('filmlist', 'recognition', 'episodes', 'artwork', 'subscriptions'):
            self.assertIn("'%s'" % task, service)
        # 0.6.0: the pause switch is asked by the shared planner (and the old per-platform loop in provider_base).
        self.assertIn("task_control.paused('catalog:' + job.key)", (ROOT / 'planner.py').read_text())
        for module in ('netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube'):
            self.assertIn("provider_base.loop(root, stop, '%s'" % module, (ROOT / (module + '.py')).read_text())
        for name in ('task_control.py', 'ui_prefs.py', 'unified_index.py'):
            self.assertIn("'%s'" % name, (ROOT / 'build_macos.py').read_text())


if __name__ == '__main__':
    unittest.main()
