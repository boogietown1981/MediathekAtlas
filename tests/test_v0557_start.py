"""0.5.57: the dashboard never shows the status blocks, and a start does not wait for the catalogue."""
import json
import re
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
import unified_index  # noqa: E402


class StaticLayoutTests(unittest.TestCase):
    """Björn (12.11.2026): the dashboard showed the status figures and the old catalogue again."""

    def setUp(self):
        self.html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')

    def section(self, name):
        start = self.html.index('<section id="%s"' % name)
        depth, pos = 0, start
        for match in re.finditer(r'<section\b|</section>', self.html[start:]):
            depth += 1 if match.group().startswith('<section') else -1
            if depth == 0:
                pos = start + match.end()
                break
        return self.html[start:pos]

    def test_dashboard_contains_only_the_catalogue(self):
        dashboard = self.section('discover')
        for unwanted in ('id="catalog-status"', 'id="metadata-status"', 'id="provider-status"', 'id="results"',
                         'id="catalog-tree"', 'id="query"', 'background-status', 'Katalog &amp; Metadatenabgleich'):
            self.assertNotIn(unwanted, dashboard)
        self.assertIn('id="atlas-cross-items"', dashboard)

    def test_blocks_stand_in_verwaltung_without_script(self):
        status, legacy = self.section('status'), self.section('legacy')
        for wanted in ('id="atlas-main-dashboard"', 'id="catalog-status"', 'id="metadata-status"', 'id="sync-now"',
                       'id="metadata-workers-status"', 'id="provider-status"', 'id="imdb-dataset-grid"'):
            self.assertIn(wanted, status)
        for wanted in ('id="results"', 'id="catalog-tree"', 'id="query"', 'id="download-filter"', 'id="series-pick"'):
            self.assertIn(wanted, legacy)
        self.assertIn('<section id="status" hidden>', self.html)
        self.assertIn('<section id="legacy" hidden>', self.html)

    def test_every_id_exists_once(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        twice = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(twice, [])

    def test_script_reports_errors_and_waits_for_pending_sources(self):
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        js = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("/api/client-error", app)
        self.assertIn("path=='/api/client-error'", server)
        self.assertIn('data.pending', js)
        self.assertIn("catalog.load_listings(ROOT/'listing-cache.json')", server)


class Base(unittest.TestCase):
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
            for i in range(30):
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          ('m%03d' % i, 'Film %02d' % i, 'movie', 2000 + i, '',
                           json.dumps({'title': 'Film %02d' % i, 'kind': 'movie'}), 'matched', 1.0))
                c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                          ('o%03d' % i, 'm%03d' % i, json.dumps({'title': 'Film', 'channel': 'ARD'}), '', 1, 1.0))
        self.saved = (catalog.LISTING_SLOW, catalog.LISTING_WAIT, catalog.LISTING_FILE, catalog._listing_build)
        catalog.invalidate_listings(drop=True)
        catalog.LISTING_DB = db
        unified_index.invalidate()

    def tearDown(self):
        catalog.LISTING_SLOW, catalog.LISTING_WAIT, catalog.LISTING_FILE, catalog._listing_build = self.saved
        catalog.LISTING_DB = None
        deadline = time.time() + 5
        while time.time() < deadline and catalog._LISTING_QUEUED:
            time.sleep(0.02)
        catalog.invalidate_listings(drop=True)
        unified_index.invalidate()
        self.dir.cleanup()

    def slow_build(self, gate):
        real = self.saved[3]

        def build(c, where, args, grouping, order):
            gate.wait(5)
            rows, _ = real(c, where, args, grouping, order)
            return rows, 9.0
        catalog._listing_build = build


class PersistedListingTests(Base):
    def test_slow_listing_survives_a_restart_and_is_renewed(self):
        cache = Path(self.dir.name) / 'listing-cache.json'
        catalog.load_listings(cache)
        catalog.LISTING_SLOW = 0.0
        with self.db() as c:
            first = catalog.listing(c, kind='movie', downloaded='all', index_only=True)
        self.assertEqual(len(first), 30)
        self.assertTrue(cache.exists())
        # "Restart": memory is empty, one film was added meanwhile.
        catalog.invalidate_listings(drop=True)
        with self.db() as c:
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES('m999','Neu','movie',2020,'','{}','matched',1.0)")
            c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES('o999','m999','{}','',1,1.0,1)")
        self.assertEqual(catalog.load_listings(cache), 1)
        builds = catalog.listing_cache_stats()['builds']
        with self.db() as c:
            again = catalog.listing(c, kind='movie', downloaded='all', index_only=True)
        self.assertEqual(len(again), 30)                       # answered from the file at once …
        deadline = time.time() + 5
        while time.time() < deadline and catalog.listing_cache_stats()['builds'] == builds:
            time.sleep(0.02)
        time.sleep(0.05)
        with self.db() as c:
            renewed = catalog.listing(c, kind='movie', downloaded='all', index_only=True)
        self.assertEqual(len(renewed), 31)                     # … and renewed in the background

    def test_searches_are_not_written_to_the_file(self):
        cache = Path(self.dir.name) / 'listing-cache.json'
        catalog.load_listings(cache)
        catalog.LISTING_SLOW = 0.0
        with self.db() as c:
            catalog.listing(c, kind='movie', query='Film 0', downloaded='all', index_only=True)
        self.assertFalse(cache.exists())

    def test_broken_file_is_ignored(self):
        cache = Path(self.dir.name) / 'listing-cache.json'
        cache.write_text('{"version":1,"entries":[{"key":"x"},7]}', encoding='utf-8')
        self.assertEqual(catalog.load_listings(cache), 0)
        cache.write_text('kaputt', encoding='utf-8')
        self.assertEqual(catalog.load_listings(cache), 0)

    def test_first_aggregation_does_not_block_a_caller_that_cannot_wait(self):
        gate = threading.Event()
        self.slow_build(gate)
        catalog.LISTING_WAIT = 0.05
        started = time.monotonic()
        with self.db() as c:
            with self.assertRaises(catalog.ListingPending):
                catalog.listing(c, kind='movie', downloaded='all', index_only=True, wait=False)
            with self.assertRaises(catalog.ListingPending):   # asked again: no second build is started
                catalog.listing(c, kind='movie', downloaded='all', index_only=True, wait=False)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(catalog._LISTING_QUEUED), 1)
        gate.set()
        deadline = time.time() + 5
        while time.time() < deadline and catalog._LISTING_QUEUED:
            time.sleep(0.02)
        with self.db() as c:
            rows = catalog.listing(c, kind='movie', downloaded='all', index_only=True, wait=False)
        self.assertEqual(len(rows), 30)


class FailingListingTests(Base):
    def test_failed_background_aggregation_is_reported_not_repeated(self):
        calls = []

        def broken(c, where, args, grouping, order):
            calls.append(1)
            raise sqlite3.OperationalError('database is locked')
        catalog._listing_build = broken
        index = unified_index.build(self.dir.name, self.db, modules={})
        self.assertEqual(index['pending'], [])
        self.assertIn('locked', index['errors']['mediatheken'])
        unified_index.build(self.dir.name, self.db, modules={})
        self.assertEqual(len(calls), 1)


class Portal:
    def __init__(self, rows):
        self.rows = rows

    def listing(self, root, view='movies', query='', offset=0, limit=48, genre='', sort='title', collection=''):
        return {'items': list(self.rows), 'total': len(self.rows), 'genre_counts': []}


class UnifiedStartTests(Base):
    def modules(self):
        return {'pluto': Portal([{'id': 'p1', 'title': 'Film 01', 'year': 2001}, {'id': 'p2', 'title': 'Nur Pluto', 'year': 1999}])}

    def test_other_sources_are_shown_while_the_catalogue_is_grouped(self):
        gate = threading.Event()
        self.slow_build(gate)
        catalog.LISTING_WAIT = 0.05
        unified_index.PENDING_TTL, keep = 0.0, unified_index.PENDING_TTL
        try:
            first = unified_index.page(self.dir.name, self.db, modules=self.modules())
            self.assertEqual(first['pending'], ['mediatheken'])
            self.assertEqual([i['title'] for i in first['items']], ['Film 01', 'Nur Pluto'])
            gate.set()
            deadline = time.time() + 5
            while time.time() < deadline and catalog._LISTING_QUEUED:
                time.sleep(0.02)
            second = unified_index.page(self.dir.name, self.db, modules=self.modules())
        finally:
            unified_index.PENDING_TTL = keep
        self.assertEqual(second['pending'], [])
        self.assertEqual(second['total'], 31)
        merged = [i for i in second['items'] if len(i['offers']) > 1]
        self.assertEqual([i['title'] for i in merged], ['Film 01'])

    def test_outdated_index_is_served_and_renewed_in_the_background(self):
        calls = []

        def builder():
            calls.append(1)
            return {'entries': [], 'n': len(calls)}
        ttl, unified_index.TTL = unified_index.TTL, 0.0
        try:
            self.assertEqual(unified_index._cached('k', builder)['n'], 1)
            time.sleep(0.01)
            self.assertEqual(unified_index._cached('k', builder)['n'], 1)   # old answer, no waiting
            deadline = time.time() + 5
            while time.time() < deadline and len(calls) < 2:
                time.sleep(0.02)
            time.sleep(0.05)
            unified_index.TTL = 60.0
            self.assertEqual(unified_index._cached('k', builder)['n'], 2)
        finally:
            unified_index.TTL = ttl

    def test_build_reports_seconds_per_source(self):
        seen = []
        unified_index.ON_BUILD = lambda key, index, seconds: seen.append((key[1], index['seconds']))
        try:
            unified_index.page(self.dir.name, self.db, modules=self.modules())
        finally:
            unified_index.ON_BUILD = None
        self.assertEqual(seen[0][0], 'movies')
        self.assertEqual(set(seen[0][1]), {'mediatheken', 'pluto', 'merge'})


if __name__ == '__main__':
    unittest.main()
