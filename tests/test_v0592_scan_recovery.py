"""0.5.92: sicherer, wiederanlaufender Archive.org-Scan (ArchiveMedia clean_scan, scan_recovery)."""
import datetime as dt
import io
import json
import re
import sqlite3
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_scan_recovery as recovery  # noqa: E402
import portal_control as control  # noqa: E402
import portal_sources  # noqa: E402

NOW = dt.datetime(2026, 11, 13).timestamp()


class Archive:
    """A stand-in for Archive.org's search: sorted pages, publicdate ranges, the 10 000 limit."""

    def __init__(self, count, limit=10000):
        first = dt.datetime(2001, 1, 1)
        # Uploads spread over the years; a burst in one month forces further halving.
        self.items = [('item%06d' % n, first + dt.timedelta(hours=7 * n) if n % 3 else dt.datetime(2015, 6, 1) + dt.timedelta(seconds=n))
                      for n in range(count)]
        self.limit, self.requests, self.fault = limit, [], None

    def open(self, url, timeout=0):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.requests.append(q)
        if self.fault:
            fault, self.fault = self.fault, None
            if isinstance(fault, Exception):
                raise fault
            return io.BytesIO(json.dumps(fault(q)).encode())
        hits = sorted(self.items)
        m = re.search(r'publicdate:\[(\S+) TO (\S+)\]', q['q'])
        if m:
            lo, hi = (dt.datetime.strptime(x, recovery.STAMP) for x in m.groups())
            hits = [h for h in hits if lo <= h[1] <= hi]
        start = (int(q['page']) - 1) * int(q['rows'])
        if start + int(q['rows']) > self.limit:
            raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b''))
        docs = [{'identifier': name, 'title': 'Film ' + name} for name, _ in hits[start:start + int(q['rows'])]]
        return io.BytesIO(json.dumps({'response': {'numFound': len(hits), 'start': start, 'docs': docs}}).encode())


class Base(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:', isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        portal_sources.initialize(self.c)
        control.initialize(self.c)
        control.set_controls(self.c, 'internet_archive', enabled=True)
        self.seen = []
        for patch in (mock.patch.object(portal_sources, 'save', lambda c, rows, query=None: self.seen.extend(r['external_id'] for r in rows)),
                      mock.patch.object(recovery.time, 'time', lambda: NOW), mock.patch.object(control.time, 'time', lambda: NOW)):
            patch.start()
            self.addCleanup(patch.stop)

    def scope(self, sid):
        return dict(self.c.execute('SELECT * FROM portal_scopes WHERE id=?', (sid,)).fetchone())

    def run_scope(self, sid, archive, starts=400):
        """Press Start until the source is complete or stops by itself; returns the number of pages."""
        pages = 0
        with mock.patch.object(control.core, 'open_url', archive.open):
            for _ in range(starts):
                if self.scope(sid)['state'] == 'complete':
                    break
                control.control_scope(self.c, sid, 'start')
                while True:
                    task = control._claim(self.c)
                    self.c.execute('COMMIT')
                    if not task:
                        break
                    try:
                        rows, more, detail = control.fetch_scope_page(task)
                        control.finish(self.c, sid, rows, more, detail, task)
                    except Exception as error:
                        control.failure(self.c, sid, error)
                    self.c.execute('UPDATE portal_scopes SET next_try=0 WHERE id=?', (sid,))
                    pages += 1
        return pages


class VerifiedScanTests(Base):
    def test_a_small_source_is_read_sorted_and_counted(self):
        archive = Archive(60)
        sid = control.add_scope(self.c, 'collection', 'kleine_sammlung', page_budget=25)
        self.assertEqual(self.run_scope(sid, archive), 3)
        self.assertEqual(self.seen, ['item%06d' % n for n in range(60)])
        scope = self.scope(sid)
        self.assertEqual((scope['state'], scope['imported'], scope['provider_total'], scope['last_identifier'], scope['mode']),
                         ('complete', 60, 60, 'item000059', recovery.VERIFIED))
        self.assertEqual(archive.requests[0]['sort[]'], 'identifier asc')
        self.assertNotIn('publicdate', archive.requests[0]['q'])
        listed = control.list_scopes(self.c)[0]['coverage']
        self.assertEqual((listed['coverage'], listed['gap'], listed['windows'], listed['verified']), ('count_plausible', 0, 0, True))

    def test_a_large_source_is_split_into_time_windows(self):
        archive = Archive(700, limit=250)
        with mock.patch.object(recovery, 'RESULT_LIMIT', 200):
            sid = control.add_scope(self.c, 'uploader', '@viel_hochlader', page_budget=25)
            self.run_scope(sid, archive)
            scope = self.scope(sid)
            self.assertEqual((scope['state'], scope['provider_total'], scope['imported']), ('complete', 700, 700))
            # Every upload exactly once, none lost at a window border.
            self.assertEqual(sorted(self.seen), ['item%06d' % n for n in range(700)])
            states = dict(self.c.execute('SELECT state,COUNT(*) FROM portal_scope_windows WHERE scope_id=? GROUP BY state', (sid,)).fetchall())
            self.assertGreater(states['split'], 2)
            self.assertNotIn('queued', states)
            self.assertNotIn('error', states)
            self.assertIn('_uploader_useritem:"@viel_hochlader" AND publicdate:[', archive.requests[-1]['q'])
            facts = control.list_scopes(self.c)[0]['coverage']
            self.assertEqual((facts['coverage'], facts['windows'], facts['windows_done']), ('count_plausible', states['complete'], states['complete']))
            # Start on the finished source asks once and changes nothing.
            before = len(self.seen)
            control.control_scope(self.c, sid, 'start')
            self.run_scope(sid, archive, starts=1)
            self.assertEqual((self.scope(sid)['state'], len(self.seen)), ('complete', before))

    def test_a_burst_within_one_second_is_reported_not_looped(self):
        archive = Archive(0)
        archive.items = [('b%04d' % n, dt.datetime(2020, 1, 1)) for n in range(300)]
        with mock.patch.object(recovery, 'RESULT_LIMIT', 200):
            sid = control.add_scope(self.c, 'collection', 'burst', page_budget=25)
            self.run_scope(sid, archive, starts=20)
        self.assertEqual(self.scope(sid)['state'], 'complete')
        note = self.c.execute("SELECT note FROM portal_scope_windows WHERE state='error'").fetchone()[0]
        self.assertIn('nicht weiter teilbar', note)
        facts = control.list_scopes(self.c)[0]['coverage']
        self.assertEqual((facts['coverage'], facts['windows_failed'], facts['gap']), ('needs_review', 1, 300))


class WrongPageTests(Base):
    def setUp(self):
        super().setUp()
        self.archive = Archive(80)
        self.sid = control.add_scope(self.c, 'collection', 'sammlung', page_budget=25)

    def first_pages(self, n):
        with mock.patch.object(control.core, 'open_url', self.archive.open):
            control.control_scope(self.c, self.sid, 'start')
            for _ in range(n):
                task = control._claim(self.c)
                self.c.execute('COMMIT')
                rows, more, detail = control.fetch_scope_page(task)
                control.finish(self.c, self.sid, rows, more, detail, task)

    def test_a_repeated_first_page_is_not_progress(self):
        self.first_pages(1)
        page_one = lambda q: {'response': {'numFound': 80, 'docs': [{'identifier': 'item%06d' % n, 'title': 'Film'} for n in range(25)]}}
        for attempt in (1, 2, 3):
            self.archive.fault = page_one
            self.c.execute('UPDATE portal_scopes SET next_try=0 WHERE id=?', (self.sid,))
            with mock.patch.object(control.core, 'open_url', self.archive.open):
                task = control._claim(self.c)
                self.c.execute('COMMIT')
                with self.assertRaises(recovery.Stalled):
                    control.fetch_scope_page(task)
                control.failure(self.c, self.sid, recovery.Stalled('Suchseite wiederholt'))
            scope = self.scope(self.sid)
            self.assertEqual((scope['cursor'], scope['imported'], scope['failures']), (2, 25, attempt))
            self.assertEqual(scope['state'], 'retry' if attempt < recovery.MAX_STALLS else 'stalled')
            self.c.execute('UPDATE portal_scopes SET next_try=0 WHERE id=?', (self.sid,))
        # Start continues at the kept position and finishes.
        self.run_scope(self.sid, self.archive)
        self.assertEqual((self.scope(self.sid)['state'], sorted(set(self.seen))), ('complete', ['item%06d' % n for n in range(80)]))
        self.assertEqual(len(self.seen), 80)

    def test_position_and_empty_page(self):
        docs = [{'identifier': 'x%d' % n} for n in range(25)]
        with self.assertRaisesRegex(recovery.Stalled, 'andere Seite'):
            recovery.check({'response': {'numFound': 80, 'start': 0, 'docs': docs}}, 2, 25, 'a')
        with self.assertRaisesRegex(recovery.Stalled, 'Leere Suchseite'):
            recovery.check({'response': {'numFound': 80, 'start': 50, 'docs': []}}, 3, 25, 'a')
        for bad in ({}, {'response': {'docs': [], 'numFound': True}}, {'response': {'docs': None, 'numFound': 1}}, None):
            with self.assertRaises(ValueError):
                recovery.check(bad, 1, 25)
        self.assertEqual(recovery.check({'response': {'numFound': 0, 'start': 0, 'docs': []}}, 1, 25)['more'], False)
        self.assertEqual(recovery.check({'response': {'numFound': 20000, 'docs': docs}}, 1, 25)['too_large'], True)


class FallbackTests(Base):
    def test_a_stalled_page_scan_changes_to_time_windows(self):
        archive = Archive(80)
        sid = control.add_scope(self.c, 'collection', 'sammlung', page_budget=25)
        control.control_scope(self.c, sid, 'start')
        with mock.patch.object(control.core, 'open_url', archive.open):
            task = control._claim(self.c)
            self.c.execute('COMMIT')
            rows, more, detail = control.fetch_scope_page(task)
            control.finish(self.c, sid, rows, more, detail, task)
            for attempt in range(recovery.MAX_STALLS):
                self.c.execute('UPDATE portal_scopes SET next_try=0 WHERE id=?', (sid,))
                task = control._claim(self.c)
                self.c.execute('COMMIT')
                action = control.failure(self.c, sid, recovery.Stalled('Suchseite wiederholt'), task)
        self.assertEqual(action, 'windows')
        scope = self.scope(sid)
        self.assertEqual((scope['state'], scope['failures'], scope['imported'], scope['cursor']), ('queued', 0, 0, 2))
        kept = json.loads(self.c.execute('SELECT snapshot FROM portal_scope_history WHERE scope_id=?', (sid,)).fetchone()[0])['fallback']
        self.assertEqual((kept['cursor'], kept['imported'], kept['last_identifier']), (2, 25, 'item000024'))
        del self.seen[:]
        self.run_scope(sid, archive)
        self.assertEqual((self.scope(sid)['state'], sorted(self.seen)), ('complete', ['item%06d' % n for n in range(80)]))
        self.assertIn('publicdate', archive.requests[-1]['q'])

    def test_a_stalled_window_is_halved_and_legacy_scans_are_left_alone(self):
        sid = control.add_scope(self.c, 'collection', 'sammlung')
        recovery.split(self.c, sid, '2020-01-01T00:00:00Z', '2020-01-03T00:00:00Z')
        window = recovery.next_window(self.c, sid)
        self.assertEqual(recovery.fallback(self.c, {'id': sid, 'kind': 'collection', 'mode': recovery.VERIFIED, 'window': window}), 'window_split')
        self.assertEqual(sorted(tuple(r) for r in self.c.execute('SELECT start_utc,end_utc,state FROM portal_scope_windows WHERE scope_id=?', (sid,))),
                         [('2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z', 'queued'), ('2020-01-02T00:00:00Z', '2020-01-02T12:00:00Z', 'queued'),
                          ('2020-01-02T00:00:00Z', '2020-01-03T00:00:00Z', 'split'), ('2020-01-02T12:00:00Z', '2020-01-03T00:00:00Z', 'queued')])
        second = {'id': 1, 'start_utc': '2020-01-01T00:00:00Z', 'end_utc': '2020-01-01T00:00:01Z', 'page': 1, 'last_identifier': ''}
        self.assertEqual(recovery.fallback(self.c, {'id': sid, 'kind': 'collection', 'mode': recovery.VERIFIED, 'window': second}), '')
        self.assertEqual(recovery.fallback(self.c, {'id': sid, 'kind': 'collection', 'mode': recovery.LEGACY}), '')
        # A source that already has windows is not seeded a second time.
        self.assertEqual(recovery.fallback(self.c, {'id': sid, 'kind': 'collection', 'mode': recovery.VERIFIED}), '')


class FailureTests(Base):
    def test_kinds(self):
        http = lambda code: urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(b''))
        self.assertEqual([recovery.kind_of(e) for e in (TimeoutError('timed out'), http(503), http(429), urllib.error.URLError('down'), OSError('Network is unreachable'))],
                         ['transient'] * 5)
        self.assertEqual([recovery.kind_of(e) for e in (http(400), http(404), ValueError('Archive.org: ungültige Suchantwort'), KeyError('x'))], ['permanent'] * 4)
        self.assertEqual(recovery.kind_of(recovery.Stalled('x')), 'stalled')

    def test_plan(self):
        self.assertEqual(recovery.plan(TimeoutError(), 1), ('retry', 60))
        self.assertEqual(recovery.plan(TimeoutError(), recovery.MAX_TRANSIENT - 1)[0], 'retry')
        self.assertEqual(recovery.plan(TimeoutError(), recovery.MAX_TRANSIENT), ('error', 0))
        self.assertEqual(recovery.plan(ValueError('ungültig'), 1), ('error', 0))
        self.assertEqual(recovery.plan(TimeoutError(), 1, enabled=False)[0], 'paused')

    def test_a_refusal_stops_and_start_resumes_at_the_same_page(self):
        archive = Archive(80)
        sid = control.add_scope(self.c, 'collection', 'sammlung', page_budget=25)
        control.control_scope(self.c, sid, 'start')
        archive.fault = urllib.error.HTTPError('u', 400, 'Bad Request', {}, io.BytesIO(b''))
        with mock.patch.object(control.core, 'open_url', archive.open):
            task = control._claim(self.c)
            self.c.execute('COMMIT')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                control.fetch_scope_page(task)
            control.failure(self.c, sid, caught.exception)
        scope = self.scope(sid)
        self.assertEqual((scope['state'], scope['cursor'], scope['failures']), ('error', 1, 1))
        self.assertIsNone(control._claim(self.c))
        self.c.execute('COMMIT')
        self.run_scope(sid, archive)
        scope = self.scope(sid)
        self.assertEqual((scope['state'], scope['failures'], len(self.seen)), ('complete', 0, 80))
        self.assertEqual(control.source_status(self.c)['platforms'][0]['queues'].get('stalled', 0), 0)


class RescanTests(Base):
    def test_rescan_keeps_history_and_reads_everything_again(self):
        archive = Archive(60)
        sid = control.add_scope(self.c, 'collection', 'sammlung', page_budget=25)
        self.run_scope(sid, archive)
        archive.items.append(('item999999', dt.datetime(2026, 11, 1)))
        control.control_scope(self.c, sid, 'rescan')
        scope = self.scope(sid)
        self.assertEqual((scope['state'], scope['cursor'], scope['imported'], scope['generation'], scope['provider_total']), ('queued', 1, 0, 1, None))
        saved = json.loads(self.c.execute('SELECT snapshot FROM portal_scope_history WHERE scope_id=?', (sid,)).fetchone()[0])
        self.assertEqual((saved['previous']['imported'], saved['previous']['state'], saved['previous']['provider_total']), (60, 'complete', 60))
        self.run_scope(sid, archive)
        self.assertEqual((self.scope(sid)['imported'], self.seen[-1], len(self.seen)), (61, 'item999999', 121))

    def test_refusals_and_removal(self):
        item = control.add_scope(self.c, 'item', 'ein_upload')
        with self.assertRaisesRegex(ValueError, 'einzelner Upload'):
            control.control_scope(self.c, item, 'rescan')
        with self.assertRaisesRegex(ValueError, 'nicht gefunden'):
            recovery.rescan(self.c, 9999)
        sid = control.add_scope(self.c, 'collection', 'sammlung')
        recovery.split(self.c, sid, *recovery.full_window(NOW))
        self.c.execute("UPDATE portal_scopes SET state='running' WHERE id=?", (sid,))
        with self.assertRaisesRegex(ValueError, 'pausieren'):
            control.control_scope(self.c, sid, 'rescan')
        self.c.execute("UPDATE portal_scopes SET state='paused' WHERE id=?", (sid,))
        control.control_scope(self.c, sid, 'remove')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM portal_scope_windows').fetchone()[0], 0)


class MigrationTests(unittest.TestCase):
    def test_a_scan_in_the_middle_of_unsorted_pages_keeps_its_order(self):
        c = sqlite3.connect(':memory:', isolation_level=None)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        portal_sources.initialize(c)
        c.executescript(control.SCHEMA)
        for scope, cursor, state in (('mitten', 7, 'paused'), ('fertig', 9, 'complete'), ('neu', 1, 'paused')):
            c.execute("INSERT INTO portal_scopes(source,kind,scope,cursor,state,updated) VALUES('internet_archive','collection',?,?,?,0)", (scope, cursor, state))
        control.initialize(c)
        control.initialize(c)
        self.assertEqual(dict(c.execute('SELECT scope,mode FROM portal_scopes').fetchall()), {'mitten': recovery.LEGACY, 'fertig': recovery.VERIFIED, 'neu': recovery.VERIFIED})
        # The old scan asks as before: its page number, no sorting.
        control.set_controls(c, 'internet_archive', enabled=True)
        sid = c.execute("SELECT id FROM portal_scopes WHERE scope='mitten'").fetchone()[0]
        control.control_scope(c, sid, 'start')
        task = control._claim(c)
        c.execute('COMMIT')
        archive = Archive(400)
        with mock.patch.object(control.core, 'open_url', archive.open):
            rows, more, detail = control.fetch_scope_page(task)
        self.assertEqual((archive.requests[0]['page'], 'sort[]' in archive.requests[0], len(rows), more, '_facts' in task), ('7', False, 25, True, False))

    def test_windows(self):
        start, end = recovery.full_window(NOW)
        self.assertEqual((start, end), ('1996-01-01T00:00:00Z', '2026-12-01T00:00:00Z'))
        self.assertEqual(recovery.full_window(dt.datetime(2026, 12, 31).timestamp())[1], '2027-01-01T00:00:00Z')
        self.assertEqual(recovery.window_clause({'start_utc': '2020-01-01T00:00:00Z', 'end_utc': '2020-02-01T00:00:00Z'}),
                         ' AND publicdate:[2020-01-01T00:00:00Z TO 2020-01-31T23:59:59Z]')
        with self.assertRaises(ValueError):
            recovery.window_clause({'start_utc': end, 'end_utc': start})


class WiringTests(unittest.TestCase):
    def test_module_is_packaged_and_shown(self):
        self.assertIn("'archive_scan_recovery.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("action:'rescan'", app)
        self.assertIn('scope.coverage', app)


if __name__ == '__main__':
    unittest.main()
