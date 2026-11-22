"""Lernreihen ohne Treffer in den Filmdatenbanken (Diagnose MacBook Pro 22.11.2026, 0.6.87).

283 von 286 „erneut versuchen“ in 70 min nur wegen „ARD Mediathek pausiert“ (Stundenkontingent), dieselben
Reihen je Folge wieder und wieder („Frage trifft Antwort“ 35×, „Spickzettel“ 23×). Jetzt: wartet ein Werk nur noch
auf den Sender, wartet es bis zum neuen Kontingent, und die Geschwister der Reihe, die ebenso nur auf den Sender
warten, mit ihm. Eine gelernte Serienvorlage der Reihe gilt auch für Werke, die zuletzt auf einen Dienst warteten.
"""
import json
import time
import unittest
from unittest.mock import patch

import broadcaster
import catalog
import catalog_service
import core
from tests.test_v0683 import Worker

ARD_ONLY = {'candidates': [], 'warnings': [], 'deferred_providers': ['ARD Mediathek'], 'provider_checks': []}


class SenderWaitTests(unittest.TestCase):
    def test_only_the_broadcaster_allowance_counts(self):
        soon = time.time() + 1800
        with patch.object(broadcaster, 'automated_retry_at', return_value=soon):
            self.assertAlmostEqual(catalog_service.sender_wait(ARD_ONLY), 1800, delta=5)
            self.assertIsNone(catalog_service.sender_wait(dict(ARD_ONLY, deferred_providers=['ARD Mediathek', 'OMDb'])))
            self.assertIsNone(catalog_service.sender_wait(dict(ARD_ONLY, warnings=['TVDB: Zeitüberschreitung'])))
            self.assertIsNone(catalog_service.sender_wait(dict(ARD_ONLY, deferred_providers=[])))
        with patch.object(broadcaster, 'automated_retry_at', return_value=0):
            self.assertIsNone(catalog_service.sender_wait(ARD_ONLY))


class ReiheTests(Worker):
    def setUp(self):
        super().setUp()
        rows = [{'title': 'Folge %s' % t, 'topic': topic, 'duration': 900, 'channel': 'SWR', 'description': 'Lernvideo ' + t,
                 'url_video': 'https://example.org/sz-%s.mp4' % t, 'timestamp': 1795100000}
                for t, topic in (('A', 'Spickzettel'), ('B', 'Spickzettel'), ('C', 'Spickzettel'), ('D', 'Spickzettel'),
                                 ('E', 'Spickzettel'), ('F', 'Andere Reihe'))]
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
            catalog.ingest(c, rows)
            self.ids = {}
            for t in 'ABCDEF':
                wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')=?", ('Folge ' + t,)).fetchone()[0]
                self.ids[t] = wid
                m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
                m['deferred_providers'] = ['OMDb'] if t == 'E' else ['ARD Mediathek']
                c.execute("UPDATE works SET state='retry',attempts=3,next_try=0,meta=? WHERE id=?", (json.dumps(m), wid))

    def due(self):
        with self.db() as c:
            return {t: c.execute('SELECT next_try FROM works WHERE id=?', (w,)).fetchone()[0] for t, w in self.ids.items()}

    def test_the_reihe_waits_for_the_allowance_together(self):
        calls = []
        soon = time.time() + 1800
        def candidates(row, meta, settings):
            calls.append(row['title']);return dict(ARD_ONLY)
        with patch.object(core, 'candidates', side_effect=candidates), \
             patch.object(broadcaster, 'automated_retry_at', return_value=soon):
            self.assertTrue(self.svc.metadata_once('identity'))
        self.assertEqual(len(calls), 1)
        due = self.due()
        for t in 'ABCD':
            self.assertGreaterEqual(due[t], soon - 5, t)                       # the checked one and its siblings
        self.assertLess(due['E'], time.time())                                  # waits for OMDb: unchanged
        if calls[0] != 'Folge F':self.assertLess(due['F'], time.time())        # other Reihe: unchanged

    def test_learned_reihe_identity_also_for_works_that_waited_for_a_service(self):
        known = {'kind': 'series', 'title': 'Spickzettel', 'provider': 'ARD Mediathek', 'reference_id': 'Y3JpZDovL3NwaWNr',
                 'year': None, 'genres': [], 'episode_verified': False}
        with self.db() as c:
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', ('spickzettel', known['provider'], known['reference_id'], json.dumps(known)))
            c.execute("UPDATE works SET next_try=? WHERE id!=?", (time.time() + 3600, self.ids['A']))
        with patch.object(core, 'candidates', side_effect=AssertionError('no provider call needed')):
            self.assertTrue(self.svc.metadata_once('identity'))
        state, m = self.work(self.ids['A'])
        self.assertEqual((state, m['title'], m['provider']), ('identified', 'Spickzettel', 'ARD Mediathek'))


class WikidataWarningTests(unittest.TestCase):
    def test_a_wikidata_error_alone_does_not_hold_the_work(self):
        row = {'attempts': 1}
        src = {'duration': 1500, 'timestamp': 1795100000, 'title': 'Konzert', 'topic': 'hr-Sinfonieorchester'}
        self.assertIsNone(catalog.unknown_soft_check(row, {'metadata_warnings': ['Wikidata: HTTP 429', 'Wikidata: HTTP 429']},
                                                     src, 'contribution', 'hr-Sinfonieorchester', 10))
        self.assertEqual(catalog.unknown_soft_check(row, {'metadata_warnings': ['Wikidata: HTTP 429', 'TVDB: Zeitüberschreitung']},
                                                    src, 'contribution', 'hr-Sinfonieorchester', 10), 'warnings')


if __name__ == '__main__':
    unittest.main()
