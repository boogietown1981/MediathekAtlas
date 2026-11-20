"""0.6.58 (Björns Diagnose 20.11.2026 nachts, 0.6.54 auf dem M3 MacBook Pro): Erkennung.

* Episodensuche: „BR retro – Das Magazin“ wurde in 4,5 Minuten 399-mal mit 226–453 Beiträgen neu eingeordnet
  (Zähler „Beiträge“ 165.000 in 23 Minuten). Ursache: catalog.propagate_series setzte bei jeder weiteren
  Erkennung in derselben Serie alle schon abgelegten Ausgaben/Beiträge (Zustand „format“) auf „identified“
  zurück; sie kamen zurück in die Episodensuche und wurden Sekunden später erneut abgelegt.
* Werke, deren Senderabruf gerade am Stundenkontingent hängt, werden nicht mehr vorgezogen.
* Wikidata: Personen, Lebewesen und Begriffe sind keine Film-/Serienvorschläge mehr.
* „Too Many Requests“ (429/503) pausiert den Anbieter sofort, statt Fehlerserien zu schreiben.
"""
import io
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import broadcaster, catalog, catalog_service, imdb_archive, metadata  # noqa: E402

SHOW = 'BR retro - Das Magazin'
NO_EPISODES = type('Offline', (), {'updated': 1,
                                   'episode_evidence': lambda self, *a: {'candidates': [], 'series': 1, 'series_with_episodes': 0}})()


def offers(n, duration=300):
    return [{'title': 'Beitrag %d über etwas' % i, 'topic': SHOW, 'duration': duration, 'channel': 'BR',
             'description': 'x' * 60 + str(i), 'url_video': 'https://example.org/v%d.mp4' % i,
             'url_website': 'https://example.org/p%d' % i} for i in range(n)]


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'catalog.db'
        self.direct = False
        self.settings = lambda: {'auto_metadata': True, 'episode_workers': 4, 'metadata_workers': 2,
                                 'sender_direct_lookup': self.direct, 'complete_series': False}
        with self.db() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c, offers(12))
            for row in c.execute('SELECT * FROM works').fetchall():
                m = json.loads(row['meta'])
                m.update(kind='series', title=SHOW, provider='IMDb Offline', reference_id='tt0001', year=None,
                         episode_verified=False)
                c.execute("UPDATE works SET kind='series',title=?,show_key='SHOW',state='identified',meta=? WHERE id=?",
                          (SHOW, json.dumps(m), row['id']))
        self.svc = catalog_service.Service(self.db, self.settings, threading.Event(), self.root)
        self.events = []
        patcher = patch('diagnostics.event', side_effect=lambda name, **kw: self.events.append((name, kw)))
        patcher.start()
        self.addCleanup(patcher.stop)
        broadcaster._AUTOMATED_BUDGET.clear()

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def states(self):
        with self.db() as c:
            return sorted(r[0] for r in c.execute('SELECT state FROM works'))

    def queued(self):
        with self.db() as c:
            return c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0]

    def run_queue(self):
        with patch.object(imdb_archive, 'ACTIVE', NO_EPISODES):
            for _ in range(50):
                if not self.svc.metadata_once('episode'):
                    break

    def classified(self):
        return [kw for name, kw in self.events if name == 'episode_series_editions_classified']


class FiledEditionsStayFiled(Fixture):
    def test_propagation_keeps_filed_contributions(self):
        self.run_queue()
        self.assertEqual(self.states(), ['format'] * 12)
        with self.db() as c:
            meta = json.loads(c.execute('SELECT meta FROM works LIMIT 1').fetchone()[0])
            meta.update(poster='https://example.org/neues-bild.jpg')
            catalog.propagate_series(c, 'SHOW', meta)
            posters = {json.loads(r[0]).get('poster') for r in c.execute('SELECT meta FROM works')}
        self.assertEqual(self.states(), ['format'] * 12)              # filing kept …
        self.assertEqual(posters, {'https://example.org/neues-bild.jpg'})  # … shared series data follow
        self.assertEqual(self.queued(), 0)

    def test_no_refiling_loop_after_further_recognitions(self):
        self.run_queue()
        first = sum(e['segments'] + e['editions'] for e in self.classified())
        for _ in range(5):                       # five more recognitions in the same series, as in the diagnosis
            with self.db() as c:
                meta = json.loads(c.execute('SELECT meta FROM works LIMIT 1').fetchone()[0])
                catalog.propagate_series(c, 'SHOW', meta)
            self.run_queue()
        self.assertEqual(sum(e['segments'] + e['editions'] for e in self.classified()), first)
        self.assertEqual(self.svc.episode_segments, 12)

    def test_unchanged_siblings_are_not_rewritten(self):
        self.run_queue()
        with self.db() as c:
            before = [tuple(r) for r in c.execute('SELECT id,updated FROM works ORDER BY id')]
            meta = json.loads(c.execute('SELECT meta FROM works LIMIT 1').fetchone()[0])
            catalog.propagate_series(c, 'SHOW', meta)
            after = [tuple(r) for r in c.execute('SELECT id,updated FROM works ORDER BY id')]
        self.assertEqual(before, after)

    def test_reset_edition_is_refiled_without_lookup(self):
        """Works set back by 0.6.55 and older come back as filed without asking IMDb or the sender."""
        self.run_queue()
        with self.db() as c:                      # what the old propagate_series left behind
            for row in c.execute('SELECT id,meta FROM works').fetchall():
                c.execute("UPDATE works SET state='identified' WHERE id=?", (row['id'],))
        self.assertEqual(self.queued(), 12)
        self.events.clear()
        broken = type('Offline', (), {'updated': 1, 'episode_evidence': lambda self, *a: (_ for _ in ()).throw(AssertionError('IMDb'))})()
        with patch.object(imdb_archive, 'ACTIVE', broken):
            for _ in range(20):
                if not self.svc.metadata_once('episode'):
                    break
        self.assertEqual(self.states(), ['format'] * 12)
        self.assertEqual(self.queued(), 0)
        self.assertEqual(self.classified(), [])

    def test_user_rescan_is_not_refiled(self):
        row = {'id': 'x', 'state': 'identified'}
        meta = {'state': 'format', 'format_grouping': 'segment', 'scan_requested': True}
        with self.db() as c:
            self.assertIsNone(catalog.refile_reset_edition(c, row, meta))
            self.assertIsNone(catalog.refile_reset_edition(c, row, {'state': 'format', 'format_grouping': 'single'}))


class SenderAllowanceOrder(Fixture):
    def test_spent_allowance_does_not_put_sender_works_first(self):
        self.direct = True
        with self.db() as c:
            rows = c.execute('SELECT id,meta FROM works ORDER BY id').fetchall()
            sender_id, plain_id = rows[0]['id'], rows[1]['id']
            m = json.loads(rows[0]['meta'])
            m.update(sender_page_id='abc', sender_provider='ARD Mediathek', sender_evidence='imported_offer')
            c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), sender_id))
            m = json.loads(rows[1]['meta'])
            m.update(episode_title='Eigener Titel')
            c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), plain_id))
            self.assertEqual(self.svc.pick_episode(c)['id'], sender_id)          # allowance left: sender first
            broadcaster._AUTOMATED_BUDGET['ARD Mediathek'] = (time.time(), broadcaster.AUTOMATED_HOURLY_LIMIT)
            self.assertEqual(self.svc.pick_episode(c)['id'], plain_id)           # spent: others first


def claim(*classes, description=''):
    return {'claims': {'P31': [{'mainsnak': {'datavalue': {'value': {'id': q}}}} for q in classes]},
            'descriptions': {'de': {'value': description}}}


class WikidataMediaOnly(unittest.TestCase):
    def test_people_taxa_and_concepts_are_no_candidates(self):
        self.assertFalse(metadata.wikidata_media(claim('Q5'), {'evidence_type': 'text_type'}))   # "film director"
        self.assertFalse(metadata.wikidata_media(claim('Q16521'), {'evidence_type': 'unknown_type'}))
        self.assertFalse(metadata.wikidata_media(claim('Q1361864'), {'evidence_type': 'unknown_type'}))  # other class
        self.assertTrue(metadata.wikidata_media(claim('Q11424'), {'evidence_type': 'correct_type'}))
        self.assertTrue(metadata.wikidata_media(claim('Q93204'), {'evidence_type': 'text_type'}))   # documentary
        self.assertTrue(metadata.wikidata_media(claim(), {'evidence_type': 'unknown_type'}))        # no classes at all

    def test_lookup_drops_a_person_and_remembers_it(self):
        metadata._WD_CACHE.clear()
        found = {'candidate_id': 'Q45402', 'candidate_title': 'Rainhard Fendrich', 'candidate_year': None,
                 'evidence_type': 'unknown_type', 'similarity': 1.0, 'confidence': 'possible', 'reason': ''}
        entity = {'entities': {'Q45402': claim('Q5')}}
        with patch('core.wikidata_lookup', return_value=dict(found)), \
                patch('external_metadata.fetch_json', return_value=entity), patch('diagnostics.event') as log:
            self.assertIsNone(metadata.wikidata('Rainhard Fendrich', 'movie', None))
        self.assertEqual(log.call_args.args[0], 'wikidata_not_media')
        with patch('core.wikidata_lookup', side_effect=AssertionError('cached')):
            self.assertIsNone(metadata.wikidata('Rainhard Fendrich', 'movie', None))

    def test_film_keeps_its_genres(self):
        metadata._WD_CACHE.clear()
        found = {'candidate_id': 'Q1', 'candidate_title': 'Tatort: Colonius', 'candidate_year': 2025,
                 'evidence_type': 'correct_type', 'similarity': 1.0, 'confidence': 'high', 'reason': ''}
        with patch('core.wikidata_lookup', return_value=dict(found)), \
                patch('external_metadata.fetch_json', return_value={'entities': {'Q1': claim('Q11424')}}):
            self.assertEqual(metadata.wikidata('Tatort: Colonius', 'movie', 2025)['candidate_id'], 'Q1')


def too_many(retry_after=None):
    headers = {'Retry-After': retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError('https://www.wikidata.org/w/api.php', 429, 'Too Many Requests', headers, io.BytesIO())


class RateLimit(unittest.TestCase):
    def setUp(self):
        metadata._OUTAGES.clear()
        metadata._WD_CACHE.clear()
        self.addCleanup(metadata._OUTAGES.clear)

    def test_429_pauses_at_once_for_retry_after(self):
        with patch('diagnostics.event') as log:
            self.assertTrue(metadata.provider_failure('Wikidata', too_many('120')))
        self.assertAlmostEqual(metadata.provider_pause('Wikidata'), 120, delta=2)
        self.assertEqual(log.call_args.args[0], 'provider_rate_limited')
        metadata._OUTAGES.clear()
        metadata.provider_failure('Wikidata', too_many('1'))                  # at least a minute
        self.assertGreater(metadata.provider_pause('Wikidata'), 55)
        metadata._OUTAGES.clear()
        metadata.provider_failure('Wikidata', too_many('86400'))              # at most 15 minutes
        self.assertLessEqual(metadata.provider_pause('Wikidata'), 900)
        metadata._OUTAGES.clear()
        self.assertFalse(metadata.provider_failure('Wikidata', urllib.error.HTTPError('u', 404, 'nf', {}, io.BytesIO())))

    def test_check_is_paused_not_failed(self):
        quiet = patch('negative_cache.contains', return_value=False)   # other tests may have cached the title
        quiet.start()
        self.addCleanup(quiet.stop)
        with patch('imdb_archive.ACTIVE', None), patch('metadata.wikidata', side_effect=too_many()), \
                patch('diagnostics.error') as error, patch('diagnostics.event'):
            r = metadata.candidates({'title': 'Unbekannt'}, {'title': 'Unbekannt', 'kind': 'movie'}, {})
        self.assertIn('Wikidata', r['deferred_providers'])
        self.assertIn({'provider': 'Wikidata', 'status': 'paused', 'count': 0}, r['provider_checks'])
        self.assertEqual(r['warnings'], [])
        error.assert_not_called()
        with patch('imdb_archive.ACTIVE', None), patch('metadata.wikidata', side_effect=AssertionError('asked')):
            r = metadata.candidates({'title': 'Unbekannt 2'}, {'title': 'Unbekannt 2', 'kind': 'movie'}, {})
        self.assertIn({'provider': 'Wikidata', 'status': 'paused', 'count': 0}, r['provider_checks'])


if __name__ == '__main__':
    unittest.main()
