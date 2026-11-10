"""0.5.27: TVDB outage resilience and durable partial identification."""
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import metadata
import tvdb


def response(data):
    return io.BytesIO(json.dumps({'status': 'success', 'data': data}).encode())


def failure(status):
    return urllib.error.HTTPError(
        'https://api4.thetvdb.com/v4/search', status, 'Unavailable', {},
        io.BytesIO(b'sensitive response must never appear in diagnostics'))


class TVDBCircuitTests(unittest.TestCase):
    def setUp(self):
        tvdb._CACHE.clear()
        tvdb._TOKENS.clear()
        tvdb._PAUSED.clear()
        tvdb._FAILURES.clear()

    def test_timeout_is_provider_specific(self):
        with patch('core.open_url', side_effect=[response({'token': 'secret'}), response([])]) as fetch:
            tvdb.request('search', 'api-key')
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(call.kwargs['timeout'] == 12 for call in fetch.call_args_list))

    def test_service_failure_opens_circuit_and_skips_repeated_calls(self):
        with patch('core.open_url', side_effect=[response({'token': 'secret'}), failure(503)]) as fetch:
            with self.assertRaises(tvdb.TVDBError) as first:
                tvdb.request('search', 'api-key')
            self.assertTrue(first.exception.paused)
            self.assertEqual(first.exception.status, 503)
            for i in range(12):
                with self.assertRaises(tvdb.TVDBError) as later:
                    tvdb.request('search', 'api-key')
                self.assertTrue(later.exception.paused)
            self.assertEqual(fetch.call_count, 2)

    def test_cached_series_still_available_during_outage(self):
        with patch('core.open_url',
                   side_effect=[response({'token': 'secret'}), response([]), failure(503)]) as fetch:
            prior = tvdb.request('search', 'key', params={'query': 'Known Show'})
            with self.assertRaises(tvdb.TVDBError):
                tvdb.request('series/123/extended', 'key')
            self.assertEqual(tvdb.request('search', 'key',
                                          params={'query': 'Known Show'}), prior)
            self.assertEqual(fetch.call_count, 3)

    def test_network_failures_back_off_exponentially_per_credential(self):
        clock = [1000.0]
        error = urllib.error.URLError('internal-hostname-never-leak')
        with patch('tvdb.time.monotonic', side_effect=lambda: clock[0]), \
             patch('core.open_url', side_effect=error) as fetch, \
             patch('diagnostics.event') as log:
            for attempt, delay in enumerate((60, 120, 240), 1):
                with self.assertRaises(tvdb.TVDBError) as caught:
                    tvdb.request('search', 'private-key')
                self.assertTrue(caught.exception.paused)
                self.assertEqual(tvdb._FAILURES[next(iter(tvdb._FAILURES))], attempt)
                self.assertAlmostEqual(next(iter(tvdb._PAUSED.values()))[0], clock[0] + delay)
                self.assertNotIn('internal-hostname', str(caught.exception))
                clock[0] += delay + 1
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(len([x for x in log.call_args_list
                                  if x.args[0] == 'tvdb_circuit_open']), 3)
            self.assertNotIn('private-key', str(log.call_args_list))

    def test_force_connectivity_test_recovers_and_clears_pause(self):
        with patch('core.open_url', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(tvdb.TVDBError):
                tvdb.request('search', 'api-key')
        with patch('core.open_url', side_effect=[response({'token': 'new-token'}), response([])]) as fetch:
            self.assertTrue(tvdb.test_access('api-key')['ok'])
            self.assertEqual(fetch.call_count, 2)
        self.assertFalse(tvdb._PAUSED)
        self.assertFalse(tvdb._FAILURES)

    def test_credential_circuit_is_isolated(self):
        with patch('core.open_url', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(tvdb.TVDBError):
                tvdb.request('search', 'broken-key')
        with patch('core.open_url', side_effect=[response({'token': 'good'}), response([])]) as fetch:
            self.assertEqual(tvdb.request('search', 'other-key')['data'], [])
            self.assertEqual(fetch.call_count, 2)


class DeferredRecognitionTests(unittest.TestCase):
    def test_fallback_remains_available_when_tvdb_is_paused(self):
        source = {'title': 'Folge 10', 'topic': 'Testserie', 'duration': 1800}
        meta = {'title': 'Testserie', 'kind': 'series'}
        tmdb_hit = {**meta, 'provider': 'TMDB', 'reference_id': '12',
                    'similarity': 1.0, 'episode_verified': False,
                    'year_mismatch': False, 'runtime_mismatch': False}
        with patch('imdb_archive.ACTIVE', None), \
             patch('metadata.tvdb_candidates', side_effect=tvdb.TVDBError(paused=True)), \
             patch('metadata.tmdb_candidates', return_value=[tmdb_hit]):
            result = metadata.candidates(source, meta, {'tvdb': 'secret', 'tmdb': 'secret2'})
        self.assertEqual(result['deferred_providers'], ['TVDB'])
        self.assertEqual(result['warnings'], [])
        self.assertTrue(any(c['provider'] == 'TMDB' for c in result['candidates']))
        checks = {x['provider']: x['status'] for x in result['provider_checks']}
        self.assertEqual(checks['TVDB'], 'paused')
        self.assertEqual(checks['TMDB'], 'checked')

    def test_partial_series_identity_is_saved_for_later_enrichment(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'catalog.db'

            @contextmanager
            def db():
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                try:
                    with conn:
                        yield conn
                finally:
                    conn.close()

            with db() as conn:
                conn.executescript(catalog.SCHEMA)
                catalog.ingest(conn, [{
                    'title': 'Folge 1', 'topic': 'Testserie', 'channel': 'ARD',
                    'description': 'Eine Folge', 'duration': 1800,
                    'url_video': 'https://example.org/episode1.mp4'
                }])
                row = conn.execute('SELECT * FROM works LIMIT 1').fetchone()
                wid = row['id']
                source = catalog.item(conn, row)
                meta = json.loads(row['meta'])
                recognized = {**meta, 'title': 'Testserie', 'kind': 'series',
                              'provider': 'TMDB', 'reference_id': '12',
                              'episode_verified': False}
                service = catalog_service.Service(
                    db, lambda: {'complete_series': False}, threading.Event(), Path(root))
                before = time.time()
                outcome, _ = service.store_outcome(
                    conn, row, source, meta, recognized, None,
                    {'candidates': [recognized], 'warnings': [],
                     'deferred_providers': ['TVDB']}, 'retry')
                self.assertEqual(outcome, 'identified')
                work = conn.execute("SELECT meta,state,next_try FROM works WHERE id=?", (wid,)).fetchone()
                self.assertIsNotNone(work)
                self.assertEqual(work['state'], 'identified')
                self.assertEqual(json.loads(work['meta'])['deferred_providers'], ['TVDB'])
                self.assertGreater(work['next_try'], before + 3000)
                self.assertLess(work['next_try'], before + 3700)


if __name__ == '__main__':
    unittest.main()
