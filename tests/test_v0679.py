"""0.6.79: Nachtdiagnose 21.11.2026 (65 → 24 GB frei in 9,5 h) und Mac-Prüfung 0.6.78.

* Gesamtbudget aller Abos (Standard 30 GB) zusätzlich zum Budget je Abo.
* Liegen Abos und IMDb-Archiv auf demselben Laufwerk, bleibt Platz für das wöchentliche Update (Archiv + 2 GB).
* Die Kurzclip-Regel (0.6.77) lässt Folgen mit Nummer stehen; schon so eingeordnete kommen zurück (Moin Piet, Doc Fischer).
"""
import json
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import imdb_archive  # noqa: E402
import youtube_abos as ab  # noqa: E402
import watch_state  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW  # noqa: E402

MB = 1000 ** 2
GB = 1000 ** 3


class TotalBudget(Fixture):
    def _conn(self):
        c = sqlite3.connect(self.catalog)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def finish(self, job, size):
        path = self.downloads / ('%s.mp4' % job['source']['_video_id'])
        with open(path, 'wb') as f:
            f.truncate(size)
        self.set_job(job['id'], 'done', path=str(path), offline_until=NOW + 86400)

    def test_setting(self):
        self.assertEqual(ab.total_gb(self.root), ab.TOTAL_DEFAULT_GB)
        self.assertEqual(ab.TOTAL_DEFAULT_GB, 0)          # 0.6.80: Björn „Ohne Grenze starten“
        self.assertEqual(ab.set_total(self.root, 10), 10)
        self.assertEqual(ab.total_gb(self.root), 10)
        with self.assertRaises(ValueError):
            ab.set_total(self.root, 7)
        st = ab.overview(self.root, self._conn())['storage']
        self.assertEqual((st['total_gb'], st['total_choices'][0]), (10, 0))

    def test_two_abos_share_the_total(self):
        ab.set_total(self.root, 10)
        one = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'budget_gb': 0}, now=NOW)
        ab.check(self.root, one, now=NOW, request=self.api)
        jobs = self.jobs()
        for job in jobs:
            self.finish(job, 5500 * MB)                       # 11 GB in one abo without its own budget
        conn = self._conn()
        job = dict(jobs[0], _state='queued')
        with mock.patch.object(ab, 'per_hour', lambda root: 1000):
            self.assertTrue(ab.pace(self.root, job, now=NOW, c=conn))
        self.assertIn('Gesamtbudget aller Abos erreicht', job['note'])
        db = ab._connect(self.root)
        try:
            self.assertEqual(ab.total_held(conn, db, self.root)[0], 11 * GB)
            self.assertTrue(ab.over_total(conn, db, self.root, 100 * MB, NOW))
        finally:
            db.close()
        st = ab.overview(self.root, conn)['storage']
        self.assertTrue(st['total_full'])
        self.assertEqual(st['used_total_gb'], 11.0)
        ab.set_total(self.root, 0)                            # ohne Gesamtgrenze
        db = ab._connect(self.root)
        try:
            self.assertEqual(ab.over_total(conn, db, self.root, 100 * MB, NOW), '')
        finally:
            db.close()
        self.assertIn('waiting_for_total', ab.summary(self.root))


class ImdbSpace(unittest.TestCase):
    def test_reserve_grows_for_imdb_update(self):
        with mock.patch.object(ab, 'imdb_space', return_value=24 * GB), \
             mock.patch.object(ab, 'free_bytes', return_value=23 * GB), \
             mock.patch.object(ab, 'reserve_gb', return_value=5):
            note = ab.no_room('/x', '/x/abos', 0)
        self.assertIn('Platz für das IMDb-Update', note)
        with mock.patch.object(ab, 'imdb_space', return_value=0), \
             mock.patch.object(ab, 'free_bytes', return_value=23 * GB), \
             mock.patch.object(ab, 'reserve_gb', return_value=5):
            self.assertEqual(ab.no_room('/x', '/x/abos', 0), '')

    def test_imdb_space_same_drive_only(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            arch = Path(tmp) / 'imdb'
            arch.mkdir()
            (arch / 'imdb.db').write_bytes(b'x' * 1000)
            fake = mock.Mock(updated=1.0, root=arch, path=arch / 'imdb.db')
            with mock.patch.object(imdb_archive, 'ACTIVE', fake):
                self.assertEqual(ab.imdb_space(Path(tmp) / 'abos' / 'neu'), 1000 + imdb_archive.UPDATE_MARGIN)
            with mock.patch.object(imdb_archive, 'ACTIVE', None):
                self.assertEqual(ab.imdb_space(tmp), 0)
        self.assertEqual(imdb_archive.update_space(0), 0)

    def test_ui_names_total_and_imdb(self):
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn("action: 'total'", js)
        self.assertIn('IMDb-Update', js)
        self.assertIn("action=='total'", (ROOT / 'server.py').read_text(encoding='utf-8'))
        self.assertIn('space_short', (ROOT / 'web' / 'app.js').read_text(encoding='utf-8'))


def database():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(catalog.SCHEMA)
    return c


class ClipEpisodes(unittest.TestCase):
    def test_numbered_episodes_come_back(self):
        c = database()
        catalog.ingest(c, [{'title': 'Moin Piet Folge %d' % i, 'topic': 'Moin Piet', 'duration': 330, 'channel': 'NDR',
                            'description': 'x' * 70 + str(i), 'url_video': 'https://example.org/m%d.mp4' % i, 'timestamp': 1782086400}
                           for i in range(3)])
        for n, row in enumerate(c.execute('SELECT * FROM works').fetchall()):
            m = json.loads(row['meta'])
            m.update(kind='series', title='Moin Piet', provider='TMDB', reference_id='123', state='format',
                     format_grouping='segment', format_rule='clip_show_v0677', episode_verified=False,
                     season=1 if n < 2 else None, episode=n + 1 if n < 2 else None)
            c.execute("UPDATE works SET kind='series',title='Moin Piet',state='format',meta=? WHERE id=?", (json.dumps(m), row['id']))

        class Ctx:
            def __enter__(self_):return c
            def __exit__(self_, *a):c.commit()
        svc = catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None)
        svc.restore_clip_episodes()
        rows = c.execute("SELECT state,json_extract(meta,'$.format_undone') u,(SELECT 1 FROM episode_queue q WHERE q.work_id=works.id) q FROM works ORDER BY CAST(json_extract(meta,'$.episode') IS NULL AS INTEGER)").fetchall()
        self.assertEqual([r['state'] for r in rows], ['identified', 'identified', 'format'])
        self.assertTrue(all(r['u'] == 'v0679' and r['q'] for r in rows[:2]))
        self.assertEqual(catalog.get_state(c, 'clip_episodes_v0679', {})['works'], 2)

    def test_has_episode(self):
        self.assertTrue(catalog.has_episode({'episode': 4}))
        self.assertTrue(catalog.has_episode({'episode_reference_id': 'tt1'}))
        self.assertFalse(catalog.has_episode({'episode': None}))
        self.assertFalse(catalog.has_episode({'episode': True}))


if __name__ == '__main__':
    unittest.main()


class DropUnseen(TotalBudget):
    """0.6.83 (Björn 21.11.2026: „Ja, als Schalter je Abo“): über dem Budget dürfen die ältesten ungesehenen weichen."""
    def prepared(self, drop):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 3, 'budget_gb': 0, 'drop_unseen': drop}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = sorted(self.jobs(), key=lambda j: j['source']['_video_id'])
        for job in jobs:
            self.finish(job, 100 * MB)
        conn = self._conn()
        db = ab._connect(self.root)
        self.addCleanup(db.close)
        ab.sync_states(conn, db)
        for n, job in enumerate(jobs):                       # oldest first
            db.execute('UPDATE youtube_abo_videos SET done_at=? WHERE job_id=?', (NOW + n, job['id']))
        db.commit()
        row = dict(db.execute('SELECT * FROM youtube_abos WHERE id=?', (abo,)).fetchone(), _root=str(self.root))
        return conn, db, row, jobs

    def test_default_off_keeps_unseen(self):
        self.assertEqual(ab._clean({})['drop_unseen'], 0)
        conn, db, row, jobs = self.prepared(False)
        self.assertFalse(ab._make_room(conn, db, row, NOW))
        self.assertEqual(sum(1 for v in self.videos(row['id']).values() if v['state'] == 'done'), 3)

    def test_switch_removes_oldest_unseen_but_keeps_marked(self):
        conn, db, row, jobs = self.prepared(True)
        self.assertEqual(row['drop_unseen'], 1)
        watch_state.mark(self.root, 'job:' + jobs[0]['id'], pinned=True)           # oldest is pinned: stays
        watch_state.progress(self.root, 'job:' + jobs[1]['id'], 120, 600)          # second is started: stays
        self.assertTrue(ab._make_room(conn, db, row, NOW))
        db.commit()
        states = {v['job_id']: v['state'] for v in self.videos(row['id']).values() if v['job_id']}
        self.assertEqual(states[jobs[0]['id']], 'done')
        self.assertEqual(states[jobs[1]['id']], 'done')
        self.assertEqual(states[jobs[2]['id']], 'expired')
        self.assertFalse(ab._make_room(conn, db, row, NOW))                     # nothing else may go

    def test_ui_names_switch(self):
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn('drop_unseen: unseen.checked', js)
        self.assertIn('auch ungesehene Videos löschen', js)
