"""0.6.65 (Mac-Gegenprüfung 0.6.58, 21.11.2026): Episodensuche „steht nach 4 Minuten“.

* Nachgestellt: große Warteschlange, Senderkontingent aufgebraucht, vier Worker. Die Warteschlange wird
  vollständig abgearbeitet; ohne IMDb-Offline-Archiv kann jede Prüfung nur zurückgestellt werden (1 h).
  Die Anzeige sagt das jetzt („wartet auf das IMDb-Offline-Archiv“).
* „Davon bereit“ zählte Werke ohne aktives Angebot, die die Worker nie nehmen (5.748 „bereit“, Stillstand).
* Die von 0.6.41–0.6.55 zurückgesetzten Ausgaben/Beiträge werden einmalig im Hintergrund wieder abgelegt,
  auch ohne aktives Angebot (777 blieben in der Prüfung stehen).
* Wikidata: Film „Der Baum“ und Serie „100% Wolf“ wurden als „kein Film“ verworfen.
"""
import json
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import broadcaster, catalog, catalog_service, imdb_archive, metadata  # noqa: E402
from test_v0658 import claim  # noqa: E402

EMPTY = type('Offline', (), {'updated': 1, 'episode_evidence':
                             lambda self, *a: {'candidates': [], 'series': 1, 'series_with_episodes': 1}})()
NOT_READY = type('Offline', (), {'updated': 0})()


class LargeQueue(unittest.TestCase):
    N = 600

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'catalog.db'
        self.settings = lambda: {'auto_metadata': True, 'episode_workers': 4, 'sender_direct_lookup': True,
                                 'complete_series': False}
        with self.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c, [{'title': 'Folge über Thema %d' % i, 'topic': 'Abenteuer am Fluss %d' % (i % 30),
                                'duration': 1500, 'channel': 'ARD', 'description': 'x' * 60 + str(i),
                                'url_video': 'https://example.org/v%d.mp4' % i,
                                'url_website': 'https://www.ardmediathek.de/video/x/abcdefgh%06d' % i}
                               for i in range(self.N)])
            for row in c.execute('SELECT * FROM works').fetchall():
                src = json.loads(c.execute('SELECT payload FROM offers WHERE work_id=?', (row['id'],)).fetchone()[0])
                m = json.loads(row['meta'])
                m.update(kind='series', title=src['topic'], provider='IMDb Offline', reference_id='tt0001',
                         year=None, episode_verified=False)
                c.execute("UPDATE works SET kind='series',state='identified',title=?,meta=? WHERE id=?",
                          (src['topic'], json.dumps(m), row['id']))
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)
        self.svc = catalog_service.Service(self.db, self.settings, self.stop, self.root)
        for target in ('diagnostics.event', 'diagnostics.error'):
            p = patch(target)
            mocked = p.start()
            self.addCleanup(p.stop)
            if target == 'diagnostics.event':
                self.event = mocked
        broadcaster._AUTOMATED_BUDGET.clear()
        broadcaster._AUTOMATED_BUDGET['ARD Mediathek'] = (time.time(), broadcaster.AUTOMATED_HOURLY_LIMIT)
        self.addCleanup(broadcaster._AUTOMATED_BUDGET.clear)

    def db(self):
        from contextlib import contextmanager

        @contextmanager
        def conn():
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()
        return conn()

    def due(self):
        with self.db() as c:
            return c.execute('SELECT COUNT(*) FROM episode_queue WHERE next_try<=?', (time.time(),)).fetchone()[0]

    def drain(self, archive, seconds=60):
        with patch.object(imdb_archive, 'ACTIVE', archive), patch.object(catalog_service, 'METADATA_PAUSE', .01):
            threads = [threading.Thread(target=self.svc.supervise, args=(lambda i=i: self.svc.episode_loop(i),),
                                        daemon=True) for i in range(4)]
            for t in threads:
                t.start()
            deadline = time.time() + seconds
            while self.due() and time.time() < deadline:
                time.sleep(.2)
            left = self.due()
            self.stop.set()
            for t in threads:
                t.join(10)
            return left

    def test_spent_allowance_with_archive_works_through_the_whole_queue(self):
        self.assertEqual(self.drain(EMPTY), 0)
        self.assertEqual(self.svc.episode_unresolved, self.N)
        self.assertEqual(self.svc.episode_sender_budget, self.N)
        with self.db() as c:      # a spent allowance brings the work back in a week, not in an hour
            soonest = c.execute('SELECT MIN(next_try) FROM episode_queue').fetchone()[0]
        self.assertGreater(soonest, time.time() + 6 * 86400)

    def test_without_archive_everything_is_postponed_and_the_page_says_why(self):
        self.assertEqual(self.drain(NOT_READY), 0)
        self.assertEqual(self.svc.episode_retried, self.N)
        self.assertEqual(self.svc.episode_checked, 0)
        self.assertIn('episode_waiting_for_imdb_archive', [a.args[0] for a in self.event.call_args_list])
        with patch.object(imdb_archive, 'ACTIVE', NOT_READY):
            self.assertIs(self.svc.scan_progress()['episode_imdb_ready'], False)
        with patch.object(imdb_archive, 'ACTIVE', EMPTY):
            self.assertIs(self.svc.scan_progress()['episode_imdb_ready'], True)
        js = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('Folgensuche wartet auf das IMDb-Offline-Archiv', js)

    def test_ready_counts_only_works_the_workers_can_take(self):
        with self.db() as c:
            ids = [r[0] for r in c.execute('SELECT id FROM works ORDER BY id LIMIT 100')]
            c.executemany('UPDATE offers SET active=0 WHERE work_id=?', [(i,) for i in ids])
        self.svc._count_episode_queue()
        _, total, due = self.svc.episode_last_count
        self.assertEqual(total, self.N)
        self.assertEqual(due, self.N - 100)

    def test_reset_editions_without_offers_are_filed_again_once(self):
        with self.db() as c:
            rows = c.execute('SELECT id,meta FROM works ORDER BY id LIMIT 50').fetchall()
            for row in rows:
                m = json.loads(row['meta'])
                m.update(state='format', format_grouping='edition' if row['id'] < rows[25]['id'] else 'segment')
                c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), row['id']))
                if row['id'] < rows[25]['id']:
                    c.execute('UPDATE offers SET active=0 WHERE work_id=?', (row['id'],))   # expired editions
                else:                                                   # active offer, but not due (Mac: 749)
                    c.execute('UPDATE episode_queue SET next_try=? WHERE work_id=?', (time.time() + 7 * 86400, row['id']))
            kept = json.loads(rows[0]['meta'])
            kept.update(state='format', format_grouping='edition', scan_requested=True)  # the user's rescan stays
            c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(kept), rows[0]['id']))
        self.svc.refile_loop()
        with self.db() as c:
            states = dict(c.execute("SELECT state,COUNT(*) FROM works GROUP BY state").fetchall())
            self.assertTrue(catalog.get_state(c, 'refile_reset_v0670', False))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], self.N - 49)
        self.assertEqual(states.get('format'), 49)
        self.assertEqual(self.svc.episode_editions + self.svc.episode_segments, 49)
        with patch.object(catalog, 'reset_editions', side_effect=AssertionError('second pass')):
            self.svc.refile_loop()                                        # done once, never again


class WikidataFilmsWithOtherClasses(unittest.TestCase):
    def test_films_and_series_outside_the_class_list_stay(self):
        def entity(cls, **claims):
            ent = claim(cls)
            for prop, value in claims.items():
                ent['claims'][prop] = [{'mainsnak': {'datavalue': {'value': value}}}]
            return ent
        unknown = {'evidence_type': 'unknown_type'}
        # „Der Baum“ (Q121338268): director and IMDb title ID
        self.assertTrue(metadata.wikidata_media(entity('Q838948', P57={'id': 'Q1'}, P345='tt1234567'), unknown))
        # „100% Wolf“ (Q140129284): number of episodes
        self.assertTrue(metadata.wikidata_media(entity('Q2389789', P1113={'amount': '+26'}), unknown))
        self.assertFalse(metadata.wikidata_media(entity('Q1361864'), unknown))            # plain concept
        self.assertFalse(metadata.wikidata_media(entity('Q1361864', P345='nm0000001'), unknown))  # IMDb person
        self.assertFalse(metadata.wikidata_media(entity('Q5', P57={'id': 'Q1'}), unknown))       # a person stays out


if __name__ == '__main__':
    unittest.main()
