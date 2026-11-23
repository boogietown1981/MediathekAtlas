"""0.6.117 (Langzeitdiagnose MacBook Air 23.11.2026, 0.6.85, 34,5 h): N-B Bilderabgleich fragt TVDB-404 stündlich neu
(„The True Story of…“ 1.002×); N-A Sportart „Schwimmen“ als Serie über Wikidata an 1.144 Werken."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artwork  # noqa: E402
import catalog  # noqa: E402
import catalog_service  # noqa: E402


class ArtworkNotFound(unittest.TestCase):
    def test_404_is_an_answer_shared_and_retried_after_a_week(self):
        with tempfile.TemporaryDirectory() as root:
            @contextmanager
            def db():
                c = sqlite3.connect(Path(root) / 'catalog.db');c.row_factory = sqlite3.Row
                try:
                    with c:yield c
                finally:c.close()
            with db() as c:
                catalog.initialize(c)
                catalog.ingest(c, [{'title': 'The True Story of X (%d)' % i, 'topic': 'Doku', 'description': 'x', 'duration': 3000,
                                    'channel': 'ARTE', 'url_video': 'https://example.org/t%d.mp4' % i} for i in range(3)])
                meta = {'kind': 'series', 'title': 'The True Story of', 'provider': 'Wikidata', 'reference_id': 'Q1'}
                for (wid,) in c.execute('SELECT id FROM works').fetchall():
                    catalog.save_metadata(c, wid, dict(meta), 'identified')
            service = catalog_service.Service(db, lambda: {'tvdb': 'k'}, threading.Event(), Path(root))
            with patch('artwork.lookup', return_value=({}, ['TVDB HTTP 404'])) as lookup:
                while artwork.run_once(service):pass
            self.assertEqual(lookup.call_count, 1)                             # before: once per work and hour
            with db() as c:
                waits = [r[0] - time.time() for r in c.execute('SELECT next_try FROM artwork_checks')]
            self.assertTrue(waits and all(w > 6 * 86400 for w in waits), waits)

    def test_real_failures_still_retry_hourly(self):
        with tempfile.TemporaryDirectory() as root:
            @contextmanager
            def db():
                c = sqlite3.connect(Path(root) / 'catalog.db');c.row_factory = sqlite3.Row
                try:
                    with c:yield c
                finally:c.close()
            with db() as c:
                catalog.initialize(c)
                catalog.ingest(c, [{'title': 'Film', 'topic': 'Film', 'description': 'Spielfilm 2020', 'duration': 5400, 'channel': 'ARD',
                                    'url_video': 'https://example.org/a.mp4'}])
                c.execute("UPDATE works SET state='manual'")
            service = catalog_service.Service(db, lambda: {'tmdb': 'k'}, threading.Event(), Path(root))
            with patch('artwork.lookup', return_value=({}, ['TMDB HTTP 503'])):
                artwork.run_once(service)
            with db() as c:wait = c.execute('SELECT next_try FROM artwork_checks').fetchone()[0] - time.time()
            self.assertLess(wait, 3700)


class WikidataOnly(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        @contextmanager
        def db():
            c = sqlite3.connect(self.root / 'catalog.db');c.row_factory = sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.db = db
        with db() as c:catalog.initialize(c)
        self.svc = catalog_service.Service(db, lambda: {}, threading.Event(), self.root)

    def identify(self, c, topic, n, provider='Wikidata', ref='Q42', imdb=None):
        rows = [{'title': '%s – Beitrag %d' % (topic, i), 'topic': topic, 'description': 'x', 'duration': 900, 'channel': 'ZDF',
                 'url_video': 'https://example.org/%s%d.mp4' % (topic, i)} for i in range(n)]
        catalog.ingest(c, rows)
        for r in rows:
            wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?", (r['url_video'],)).fetchone()[0]
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
            m.update(kind='series', title=topic, provider=provider, reference_id=ref, episode_title=r['title'])
            if imdb:m['imdb_id'] = imdb
            catalog.save_metadata(c, wid, m, 'identified')

    def test_sports_are_subjects(self):
        import metadata
        for w in ('Schwimmen', 'Biathlon', 'Ski alpin', 'Formel 1'):
            self.assertTrue(metadata.generic_topic(w), w);self.assertFalse(catalog.template_topic(w), w)
        self.assertTrue(catalog.template_topic('Sportschau Club'))

    def test_wikidata_only_template_never_used(self):
        with self.db() as c:
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', (catalog.key('Kunstturnen'), 'Wikidata', 'Q9',
                      json.dumps({'kind': 'series', 'title': 'Kunstturnen', 'provider': 'Wikidata', 'reference_id': 'Q9'})))
            catalog.ingest(c, [{'title': 'Kür am Barren', 'topic': 'Kunstturnen', 'description': 'x', 'duration': 900, 'channel': 'ZDF',
                                'url_video': 'https://example.org/k.mp4'}])
            row = c.execute('SELECT * FROM works').fetchone()
            src = json.loads(c.execute('SELECT payload FROM offers').fetchone()[0])
            self.assertIsNone(catalog.series_template_candidate(c, row, src))
            self.assertEqual(catalog.drop_portal_templates(c), 1)

    def test_heal_resets_spread_wikidata_identities_only(self):
        with self.db() as c:
            self.identify(c, 'Kunstturnen', 25)                                  # spread, Wikidata only
            self.identify(c, 'Schwimmen', 3)                                     # sport word
            self.identify(c, 'Unser Dorf', 5, ref='Q7')                          # small, kept
            self.identify(c, 'Lindenstraße', 25, ref='Q8', imdb='tt0090509')     # Wikidata with IMDb ID, kept
        self.svc.reset_generic_identities()
        with self.db() as c:
            left = {r[0]: r[1] for r in c.execute("SELECT topic,COUNT(*) FROM works WHERE state='identified' AND kind='series' GROUP BY topic")}
            done = catalog.get_state(c, 'generic_templates_v06117')
        self.assertNotIn('Kunstturnen', left);self.assertNotIn('Schwimmen', left)
        self.assertEqual((left.get('Unser Dorf'), left.get('Lindenstraße')), (5, 25))
        self.assertEqual(done['works'], 28)
        self.assertIsNone(self.svc.reset_generic_identities())                  # once


class MacFunde0616(unittest.TestCase):
    """Mac-Prüfung 0.6.116: „Trailer Park“ (55 min) als Extra, „KiKANiNCHEN“ unter „Kikaninchen“."""
    def test_long_title_beginning_with_trailer_is_a_programme(self):
        self.assertTrue(catalog.full_programme({'title': 'Trailer Park', 'duration': 3300}))
        self.assertFalse(catalog.full_programme({'title': 'Trailer: Tatort', 'duration': 35}))

    def test_heal_reopens_trailer_park_and_restores_spelling(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        @contextmanager
        def db():
            c = sqlite3.connect(root / 'catalog.db');c.row_factory = sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        with db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [{'title': 'Trailer Park', 'topic': 'Theater und Tanz', 'description': 'x', 'duration': 3300, 'channel': '3sat',
                                'url_video': 'https://example.org/tp.mp4'},
                               {'title': 'Folge 1', 'topic': 'KiKANiNCHEN', 'description': 'x', 'duration': 600, 'channel': 'KiKA',
                                'url_video': 'https://example.org/kk.mp4'}])
            tp = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')='Trailer Park'").fetchone()[0]
            kk = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')='Folge 1'").fetchone()[0]
            c.execute("UPDATE works SET kind='other',state='format',meta=json_set(meta,'$.reason','Extra zu „Theater und Tanz“ (Interview, Ausschnitt, Trailer); x') WHERE id=?", (tp,))
            row = c.execute('SELECT * FROM works WHERE id=?', (kk,)).fetchone()
            catalog.file_under_sendung(c, row, dict(json.loads(row['meta']), sendung_identity={'provider': 'TMDB', 'reference_id': '1', 'title': 'Kikaninchen'}),
                                       {'title': 'Folge 1', 'topic': 'KiKANiNCHEN'}, 'Kikaninchen', 'contribution',
                                       reason='Folge der Sendung „Kikaninchen“ (TMDB kennt die Sendung, aber keine Einzelfolgen)')
            catalog.set_state(c, 'full_programmes_v06116', {'reopened': 0})       # 0.6.116 heal already ran
        svc = catalog_service.Service(db, lambda: {}, threading.Event(), root)
        self.assertEqual(svc.reopen_full_programmes(), 1)
        with db() as c:
            self.assertEqual(c.execute('SELECT kind,state FROM works WHERE id=?', (tp,)).fetchone()[:], ('unknown', 'pending'))
            r = c.execute('SELECT title,meta FROM works WHERE id=?', (kk,)).fetchone()
        self.assertEqual(r['title'], 'KiKANiNCHEN')
        self.assertIn('„KiKANiNCHEN“', json.loads(r['meta'])['reason'])

    def test_new_b2_filing_keeps_broadcaster_spelling(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with sqlite3.connect(Path(tmp.name) / 'c.db') as c:
            c.row_factory = sqlite3.Row;catalog.initialize(c)
            catalog.ingest(c, [{'title': 'Folge 2', 'topic': 'KiKANiNCHEN', 'description': 'x', 'duration': 600, 'channel': 'KiKA',
                                'url_video': 'https://example.org/k2.mp4'}])
            row = c.execute('SELECT * FROM works').fetchone()
            catalog.file_sendung_without_episodes(c, row, json.loads(row['meta']), {'title': 'Folge 2', 'topic': 'KiKANiNCHEN'},
                                                  {'provider': 'TMDB', 'reference_id': '1', 'title': 'Kikaninchen'}, 'Kikaninchen', 'contribution')
            self.assertEqual(c.execute('SELECT title FROM works').fetchone()[0], 'KiKANiNCHEN')


if __name__ == '__main__':
    unittest.main()
