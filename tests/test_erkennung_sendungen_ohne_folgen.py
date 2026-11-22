"""Zwischendiagnose Pro 22.11.2026 (0.6.91, 17 min): 0.6.88 ordnete 1.235 Werke als Folge der vorgeschlagenen
Sendung ein; die Folgensuche prüfte 1.100 davon mit 2 Treffern (Sportpanorama, NZZ Standpunkte, Euromaxx: IMDb kennt
keine Einzelfolgen). Solche Werke sind Beiträge der Sendung, mit der Datenbank-Identität als Hinweis. DW „Europa“ ist
ein Themenwort.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import imdb_archive  # noqa: E402
import metadata  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402
from test_v0649_unknown_rest import offer, series  # noqa: E402
from tests.test_v0683 import Worker  # noqa: E402


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Sportler des Jahres', 'Sportpanorama', n=1, duration=3000), offer('Eishockey', 'Sportpanorama', n=2, duration=3000),
                offer('Ski alpin', 'Sportpanorama', n=3, duration=3000), offer('Die Bruderschaft', 'Schätze', n=4), offer('B', 'Schätze', n=5),
                offer('C', 'Schätze', n=6)]
        setup = {'Sportler des Jahres': [series('Sportpanorama', ref='tt77', year=2001)],
                 'Die Bruderschaft': [{'provider': 'Wikidata', 'kind': 'series', 'title': 'Schätze', 'similarity': 1.0,
                                       'reference_id': 'Q1', 'year': 2010, 'confidence': 'high'}]}
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
                m = json.loads(meta)
                if m['title'] in setup:m['suggestions'] = setup[m['title']]
                c.execute("UPDATE works SET state='review', attempts=2, meta=? WHERE id=?", (json.dumps(m), wid))
        self.service = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def work(self, title):
        with self.db() as c:
            for r in c.execute('SELECT * FROM works'):
                m = json.loads(r['meta'])
                if (m.get('unknown_before') or {}).get('title') == title or m.get('episode_title') == title or r['title'] == title:
                    return dict(r, meta=m)

    def test_sendung_without_imdb_episodes_becomes_its_contribution(self):
        archive = SimpleNamespace(updated=1, series_has_episodes=lambda m: False)
        with patch.object(imdb_archive, 'ACTIVE', archive):
            self.service.unknown_sweep(force=True)
        # 0.6.97 (Mac-Prüfung 0.6.88): a Wikidata suggestion alone never decides – „Die Bruderschaft“ stays open
        self.assertEqual(self.work('Die Bruderschaft')['kind'], 'unknown')
        for title, ident in (('Sportler des Jahres', 'tt77'),):
            r = self.work(title)
            self.assertEqual((r['kind'], r['state'], r['title']), ('series', 'format', r['meta']['title']), title)
            self.assertEqual(r['meta']['sendung_identity']['reference_id'], ident)
            self.assertIn('keine Einzelfolgen', r['meta']['reason'])
            self.assertEqual(catalog.restore_unknown(r['meta'])[1], 'unknown')
        with self.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 0)

    def test_without_archive_the_work_waits(self):
        with patch.object(imdb_archive, 'ACTIVE', None):
            self.service.unknown_sweep(force=True)
        self.assertEqual(self.work('Sportler des Jahres')['kind'], 'unknown')


class EpisodePathTests(Worker):
    def test_0688_filings_of_a_sendung_without_episodes_are_refiled_at_once(self):
        ids = []
        with self.db() as c:
            catalog.ingest(c, [{'title': 'Ausgabe %d' % i, 'topic': 'Euromaxx', 'duration': 1500, 'channel': 'DW', 'description': 'x',
                                'url_video': 'https://example.org/em%d.mp4' % i, 'timestamp': 1795100000} for i in range(3)])
            for i in range(3):
                wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')=?", ('Ausgabe %d' % i,)).fetchone()[0]
                ids.append(wid)
                m = {'kind': 'series', 'title': 'Euromaxx', 'provider': 'IMDb Offline', 'reference_id': 'tt2620362', 'year': 2003,
                     'episode_title': 'Ausgabe %d' % i, 'episode_verified': False, 'sendung_suggestion_v0688': True,
                     'sendung_grouping': 'contribution', 'unknown_before': {'kind': 'unknown', 'title': 'Ausgabe %d' % i, 'rev': 7}}
                catalog.save_metadata(c, wid, m, 'identified')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 3)
        self.only_due(ids[0])
        self.run_once()                                   # the test archive has no Euromaxx: no episodes
        with self.db() as c:
            rows = [c.execute('SELECT state,title,meta FROM works WHERE id=?', (w,)).fetchone() for w in ids]
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 0)
        for r in rows:
            m = json.loads(r['meta'])
            self.assertEqual((r['state'], r['title'], m['format_grouping'], m['sendung_identity']['reference_id']),
                             ('format', 'Euromaxx', 'contribution', 'tt2620362'))


class TopicWordTests(unittest.TestCase):
    def test_europa_is_a_subject(self):
        self.assertTrue(metadata.generic_topic('Europa'))
        self.assertFalse(catalog.template_topic('Europa'))


if __name__ == '__main__':
    unittest.main()
