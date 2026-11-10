"""Regression tests: accurate episode counts, transparent runtime, outage circuits."""
import json
import sqlite3
import time
import unittest
import urllib.error
from unittest.mock import patch

import catalog_service
import matching
import metadata
import video_causality
from test_v0531_causality import EpisodeQueueRuntimeTests, offer


class EpisodeClaimCounters(EpisodeQueueRuntimeTests):
    # Reuse a real in-memory-backed SQLite catalog and its persistent triggers.
    def test_preflight_runtime_conflict_increases_completed_count(self):
        with patch('broadcaster.lookup_limited',side_effect=AssertionError('network must not run')):
            self.assertTrue(self.service.metadata_once('episode'))
        stats=self.service.scan_progress()
        self.assertEqual(stats['episode_checked_session'],1)
        self.assertEqual(stats['episode_suspected_session'],1)
        self.assertEqual(stats['episode_extras_session'],0)
        self.assertEqual(stats['episode_matched_session'],0)
        self.assertEqual(stats['episode_unresolved_session'],0)
        self.assertEqual(stats['episode_queue_total'],0)
        self.assertEqual(stats['episode_queue_due'],0)

    def test_explicit_trailer_counts_as_extra_not_an_episode(self):
        with self.db() as c:
            row=c.execute("SELECT payload FROM offers WHERE work_id=?",(self.wid,)).fetchone()
            payload=json.loads(row[0]);payload['title']='Musteranime - Trailer'
            c.execute('UPDATE offers SET payload=? WHERE work_id=?',
                      (json.dumps(payload),self.wid))
        self.assertTrue(self.service.metadata_once('episode'))
        stats=self.service.scan_progress()
        self.assertEqual(stats['episode_checked_session'],1)
        self.assertEqual(stats['episode_extras_session'],1)
        self.assertEqual(stats['episode_suspected_session'],0)
        self.assertEqual(stats['episode_matched_session'],0)
        with self.db() as c:
            work=c.execute('SELECT state,kind FROM works WHERE id=?',(self.wid,)).fetchone()
            self.assertEqual((work['state'],work['kind']),('format','other'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)


class ProviderOutageTests(unittest.TestCase):
    def setUp(self):
        with metadata._OUTAGE_LOCK:metadata._OUTAGES.clear()
        self.addCleanup(lambda:metadata._OUTAGES.clear())

    def test_only_transient_errors_open_provider_pause(self):
        e=urllib.error.URLError('TLS handshake timed out')
        self.assertFalse(metadata.provider_failure('TMDB',e))
        self.assertTrue(metadata.provider_failure('TMDB',e))
        self.assertGreater(metadata.provider_pause('TMDB'),100)
        self.assertEqual(metadata.provider_pause('Wikidata'),0)
        http=urllib.error.HTTPError('https://provider.example',404,'Not found',{},None)
        self.assertFalse(metadata.provider_failure('Wikidata',http))
        self.assertEqual(metadata.provider_pause('Wikidata'),0)

    def test_success_resets_only_its_provider(self):
        error=urllib.error.URLError('connection reset')
        for p in ('TMDB','Wikidata'):
            metadata.provider_failure(p,error)
            metadata.provider_failure(p,error)
        metadata.provider_success('Wikidata')
        self.assertEqual(metadata.provider_pause('Wikidata'),0)
        self.assertGreater(metadata.provider_pause('TMDB'),0)

    def test_paused_tmdb_does_not_block_independent_fallback(self):
        err=urllib.error.URLError('network down')
        metadata.provider_failure('TMDB',err)
        metadata.provider_failure('TMDB',err)
        source=offer('Ein unbekannter Film',3800,topic='Kino')
        meta={'title':'Ein unbekannter Film','kind':'movie','year':None}
        with patch('imdb_archive.ACTIVE',None),patch('metadata.tmdb_candidates',side_effect=AssertionError('TMDB not called')),patch('metadata.wikidata',return_value=None),patch('negative_cache.contains',return_value=False):
            result=metadata.candidates(source,meta,{'tmdb':'dummy'})
        self.assertIn('TMDB',result['deferred_providers'])
        self.assertIn('paused',[x['status'] for x in result['provider_checks'] if x['provider']=='TMDB'])
        self.assertIn('Wikidata',[x['provider'] for x in result['provider_checks']])

    def test_offline_imdb_can_complete_with_network_circuit_open(self):
        err=urllib.error.URLError('TLS timeout')
        metadata.provider_failure('TMDB',err)
        metadata.provider_failure('TMDB',err)
        class Offline:
            updated=1
            def candidates(self,source,meta):
                return [{'kind':'movie','title':meta['title'],'provider':'IMDb Offline',
                         'reference_id':'tt123','similarity':1.0,
                         'year_mismatch':False,'runtime_mismatch':False}]
        source=offer('Musterfilm',6500,topic='Kino')
        meta={'kind':'movie','title':'Musterfilm','year':None}
        with patch('imdb_archive.ACTIVE',Offline()),patch('matching.sufficient',return_value=True),patch('metadata.tmdb_candidates',side_effect=AssertionError('No network call')):
            result=metadata.candidates(source,meta,{'tmdb':'dummy'})
        self.assertEqual(result['candidates'][0]['provider'],'IMDb Offline')
        self.assertEqual(result['warnings'],[])


class RuntimeEvidenceTests(unittest.TestCase):
    def test_source_and_reference_provenance_are_persistable(self):
        role=video_causality.evaluate(offer('Anime Episode 3',120),{
            'kind':'series','provider':'TVDB','reference_runtime_seconds':1200})
        self.assertEqual(role['video_role'],'short_excerpt_suspected')
        self.assertEqual(role['source_duration_seconds'],120)
        self.assertEqual(role['expected_runtime_seconds'],1200)
        self.assertEqual(role['source_runtime_source'],'Sender-Katalogimport')
        self.assertIn('TVDB',role['expected_runtime_source'])
        self.assertEqual(json.loads(json.dumps(role)),role)

    def test_local_median_reference_is_labeled_as_less_authoritative(self):
        source={'kind':'series','reference_runtime_seconds':2220,
                'reference_runtime_source':'Serien-Katalogmedian (mind. 5 Vergleichsangebote)'}
        role=video_causality.evaluate(offer('Episode 5',100),source)
        self.assertIn('Katalogmedian',role['expected_runtime_source'])

    def test_ui_shows_causality_fields_and_dedicated_counters(self):
        from pathlib import Path
        app=(Path(__file__).resolve().parents[1]/'web'/'app.js').read_text(encoding='utf-8')
        for name in ('source_duration_seconds','source_runtime_source',
                     'expected_runtime_seconds','expected_runtime_source',
                     'episode_suspected_session','episode_extras_session',
                     'episode_checked_session'):
            self.assertIn(name,app)


if __name__=='__main__':
    unittest.main()
