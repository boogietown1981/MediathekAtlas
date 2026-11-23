"""0.6.113: Mac-Prüfung Erkennung 0.6.108 (23.11.2026) – B2 nicht nachweisbar, Arbeiter nach 22 min „waiting“ bei
4.854 pending (2.499 Art other, 2.222 unknown).

- B2: die 0.6.88-Folgen einer vorgeschlagenen Sendung ruhen nach der ersten Folgensuche 30 Tage; ein Geschwister ohne
  Merker parkte sie erneut. Jetzt einmalige Ablage aus dem IMDb-Archiv (sendung_refile_v06113) und Ablage der
  Merker-Geschwister auch im Geschwisterzweig.
- Leerlauf: Ereignis recognition_idle nennt je Art den Grund, aus dem pick() offene Werke auslässt.
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
import diagnostics  # noqa: E402
import imdb_archive  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402
from tests.test_v0683 import Worker  # noqa: E402


def src(title, topic, n, duration=1500, channel='DW'):
    return {'title': title, 'topic': topic, 'duration': duration, 'channel': channel, 'description': 'x',
            'url_video': 'https://example.org/v%d.mp4' % n, 'timestamp': 1795100000}


def wid_of(c, n):
    return c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?", ('https://example.org/v%d.mp4' % n,)).fetchone()[0]


def suggested(c, wid, sendung, ref, title, marker=True):
    m = {'kind': 'series', 'title': sendung, 'provider': 'IMDb Offline', 'reference_id': ref, 'year': 2003,
         'episode_title': title, 'episode_verified': False, 'sendung_grouping': 'contribution',
         'unknown_before': {'kind': 'unknown', 'title': title, 'rev': 7}}
    if marker:m['sendung_suggestion_v0688'] = True
    return catalog.save_metadata(c, wid, m, 'identified') or wid


class RefileHealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [src('Ausgabe %d' % i, 'Euromaxx', i) for i in range(3)] +
                              [src('Folge %d' % i, 'Tatort Doku', 10 + i) for i in range(2)])
            for i in range(3):suggested(c, wid_of(c, i), 'Euromaxx', 'tt2620362', 'Ausgabe %d' % i)
            for i in range(2):suggested(c, wid_of(c, 10 + i), 'Tatort Doku', 'tt999', 'Folge %d' % i)
        self.service = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def states(self):
        with self.db() as c:
            return {r['title']: r['state'] for r in c.execute('SELECT title,state FROM works')}, \
                   c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0]

    def test_sendung_without_episodes_refiled_with_episodes_kept(self):
        archive = SimpleNamespace(updated=1, series_has_episodes=lambda m: m.get('reference_id') == 'tt999')
        events = []
        with patch.object(imdb_archive, 'ACTIVE', archive), \
                patch.object(diagnostics, 'event', lambda name, **f: events.append((name, f))):
            self.assertEqual(self.service.refile_suggested_sendungen(), 3)
            self.assertIsNone(self.service.refile_suggested_sendungen())   # once
        with self.db() as c:
            rows = c.execute('SELECT state,meta FROM works').fetchall()
            done = catalog.get_state(c, 'sendung_refile_v06113')
        by = {}
        for r in rows:
            m = json.loads(r['meta']);by.setdefault(m['title'], []).append((r['state'], m.get('format_grouping'), (m.get('sendung_identity') or {}).get('reference_id')))
        self.assertEqual(by['Euromaxx'], [('format', 'contribution', 'tt2620362')] * 3)
        self.assertEqual({s for s, *_ in by['Tatort Doku']}, {'identified'})
        self.assertEqual((done['refiled'], done['shows'], done['kept']), (3, 1, 1))
        ev = [f for n, f in events if n == 'catalog_sendung_suggestions_refiled']
        self.assertEqual((ev[0]['works'], ev[0]['kept_with_episodes'], ev[0]['samples']), (3, 1, {'Euromaxx': 3}))

    def test_without_archive_nothing_is_decided(self):
        with patch.object(imdb_archive, 'ACTIVE', None):
            self.assertIsNone(self.service.refile_suggested_sendungen())
        with self.db() as c:
            self.assertFalse(catalog.get_state(c, 'sendung_refile_v06113', False))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE state='identified'").fetchone()[0], 5)

    def test_runs_in_the_format_pass(self):
        archive = SimpleNamespace(updated=1, series_has_episodes=lambda m: False)
        def sweep():
            self.service.stop.set()                       # one format pass only
        with patch.object(imdb_archive, 'ACTIVE', archive), patch.object(self.service, 'unknown_sweep', sweep), \
                patch.object(self.service.format_wake, 'wait', lambda t: True):
            self.service.format_loop()
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'sendung_refile_v06113')['refiled'], 5)


class SiblingPathTests(Worker):
    def test_marker_siblings_are_filed_when_a_plain_work_is_searched(self):
        with self.db() as c:
            catalog.ingest(c, [src('Ausgabe %d' % i, 'Euromaxx', i) for i in range(4)])
            plain = suggested(c, wid_of(c, 0), 'Euromaxx', 'tt2620362', 'Ausgabe 0', marker=False)
            marked = [suggested(c, wid_of(c, i), 'Euromaxx', 'tt2620362', 'Ausgabe %d' % i) for i in (1, 2, 3)]
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 4)
        self.only_due(plain)
        events = []
        with patch.object(diagnostics, 'event', lambda name, **f: events.append((name, f))):
            self.run_once()                               # the test archive has no Euromaxx: no episodes
        with self.db() as c:
            states = [c.execute('SELECT state FROM works WHERE id=?', (w,)).fetchone()[0] for w in marked]
            left = c.execute('SELECT state FROM works WHERE id=?', (plain,)).fetchone()[0]
        self.assertEqual(states, ['format'] * 3)
        self.assertEqual(left, 'identified')            # the searched work itself carries no 0.6.88 filing
        ev = [f for n, f in events if n == 'episode_sendung_without_episodes']
        self.assertEqual((ev[0]['works'], ev[0]['via']), (3, 'sibling'))


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        now = time.time()
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [src('Clip %d' % i, 'Irgendwas', i, 120) for i in range(5)])
            ids = [wid_of(c, i) for i in range(5)]
            c.execute("UPDATE works SET kind='unknown',state='pending',attempts=1,next_try=0")
            c.execute("UPDATE works SET kind='other' WHERE id=?", (ids[0],))
            c.execute('UPDATE works SET next_try=? WHERE id=?', (now + 3600, ids[1]))
            c.execute('UPDATE offers SET active=0 WHERE work_id=?', (ids[2],))
            c.execute('INSERT INTO metadata_leases(work_id,owner,expires) VALUES(?,?,?)', (ids[3], 'x', now + 600))
        self.ids = ids
        self.service = catalog_service.Service(self.db, lambda: {'auto_metadata': True, 'scan_priority': 'balanced', 'complete_series': False},
                                               threading.Event(), Path(self.tmp.name))

    def test_blockers_follow_the_selection(self):
        with self.db() as c:
            b = catalog.queue_blockers(c)
            row = self.service.pick(c)
        self.assertEqual(b, {'other': {'not_selected_kind': 1},
                             'unknown': {'not_due': 1, 'no_active_offer': 1, 'leased': 1, 'selectable': 1}})
        self.assertEqual(row['id'], self.ids[4])        # the only selectable one is what pick() takes

    def test_idle_event_once_per_half_hour(self):
        with self.db() as c:c.execute("UPDATE works SET state='review' WHERE id=?", (self.ids[4],))
        events = []
        with patch.object(diagnostics, 'event', lambda name, **f: events.append((name, f))):
            self.assertFalse(self.service.metadata_once())
            self.service.metadata_state(phase='result')
            self.assertFalse(self.service.metadata_once())
        idle = [f for n, f in events if n == 'recognition_idle']
        self.assertEqual(len(idle), 1)
        self.assertEqual(idle[0]['selectable'], 0)
        self.assertEqual(idle[0]['blockers']['unknown']['no_active_offer'], 1)


class OpenClipTests(unittest.TestCase):
    """Rückstau-Abfrage an der 0.6.112-Prüfkopie: 2.414 'other'/pending mit 0 Versuchen (Trailer, Vorschau, Podcast)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [src('Trailer: Ein Freund, ein guter Freund', 'Tatort', 1, 35, 'ARD'),
                src('Podcast mit Nachklang (4316)', 'Rote Rosen', 2, 2956, 'ARD'),
                src('SPD setzt in Pressekonferenz auf Kurskorrektur', 'tagesschau24', 3, 1220, 'tagesschau24'),
                src('Wetter am Abend', 'Hessenschau', 4, 120, 'HR'), src('Hessenschau vom 1.12.', 'Hessenschau', 5, 1800, 'HR')]
        rows += [src('Rote Rosen (%d)' % (4300 + i), 'Rote Rosen', 10 + i, 2900, 'ARD') for i in range(3)]
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            for n in (1, 2, 3, 4):
                c.execute("UPDATE works SET kind='other',state='pending',attempts=0 WHERE id=?", (wid_of(c, n),))
            c.execute("UPDATE works SET kind='series',state='matched' WHERE id IN (SELECT work_id FROM offers WHERE json_extract(payload,'$.title') LIKE 'Rote Rosen (%')")
            catalog.set_state(c, 'format_rev', 5);catalog.set_state(c, 'format_cursor', 'complete')

    def row(self, c, n):
        r = c.execute('SELECT * FROM works WHERE id=?', (wid_of(c, n),)).fetchone()
        return r['kind'], r['state'], json.loads(r['meta']).get('format_grouping')

    def test_new_format_rev_ends_every_open_clip(self):
        with self.db() as c:
            while catalog.assign_formats(c)[0]:pass
            self.assertEqual(self.row(c, 1), ('other', 'format', None))          # trailer: extra of „Tatort“
            self.assertIn('Trailer/Vorschau zu „Tatort“', json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid_of(c, 1),)).fetchone()[0])['reason'])
            self.assertEqual(self.row(c, 2), ('other', 'format', 'clip'))        # never a Folge of „Rote Rosen“
            self.assertEqual(self.row(c, 3), ('other', 'format', 'clip'))
            self.assertEqual(self.row(c, 4)[1:], ('format', None))              # Sendung rule unchanged: under Hessenschau
            self.assertEqual(self.row(c, 4)[0], 'series')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE kind='other' AND state='pending'").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE title='Rote Rosen' AND state='format'").fetchone()[0], 0)

    def test_requested_check_is_left_alone_and_recheck_reopens(self):
        with self.db() as c:
            catalog.prioritize(c, [wid_of(c, 2)])
            while catalog.assign_formats(c)[0]:pass
            self.assertEqual(self.row(c, 2)[1], 'pending')
            self.assertIsNotNone(c.execute('SELECT 1 FROM metadata_priority WHERE work_id=?', (wid_of(c, 2),)).fetchone())


if __name__ == '__main__':
    unittest.main()
