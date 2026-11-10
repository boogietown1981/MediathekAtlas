"""0.5.28: independent persistent episode queue and conservative offline evidence."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import imdb_archive


def source(tag, topic='Beispielserie'):
    return {'title':'Beitrag '+tag,'topic':topic,'channel':'ARD',
            'duration':1800,'description':'Eine Ausstrahlung',
            'url_video':'https://example.org/'+tag+'.mp4'}


class QueueTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.path=self.root/'catalog.db'
        with self.db() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[source('first'),source('second'),source('third')])
        self.settings=lambda:{'auto_metadata':True,'episode_workers':2,
                              'metadata_workers':2,'complete_series':False,
                              'scan_priority':'series_first'}
        self.svc=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)

    @contextmanager
    def db(self):
        conn=sqlite3.connect(self.path, timeout=2)
        conn.row_factory=sqlite3.Row
        try:
            with conn:
                yield conn
        finally:conn.close()

    def work_ids(self):
        with self.db() as c:return [r[0] for r in c.execute('SELECT id FROM works ORDER BY id')]

    def recognize(self,wid, provider='TMDB', reference='88',deferred=False):
        with self.db() as c:
            original=json.loads(c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()[0])
            original.update(kind='series',title='Beispielserie',provider=provider,
                            reference_id=reference,episode_verified=False,
                            episode_title=original.get('title'),year=None)
            if deferred:original['deferred_providers']=['TVDB']
            c.execute("UPDATE works SET kind='series',state='identified',title=?,meta=?,next_try=? WHERE id=?",
                      ('Beispielserie',json.dumps(original),time.time()+86400,wid))

    def test_identity_worker_never_takes_recognised_episode(self):
        ids=self.work_ids()
        self.recognize(ids[0])
        with self.db() as c:
            episode=self.svc.pick_episode(c)
            main=self.svc.pick(c)
            self.assertEqual(episode['id'],ids[0])
            self.assertIn(main['id'],ids[1:])
        a=self.svc.lease_work('episode')
        b=self.svc.lease_work()
        self.assertEqual(a[0],ids[0])
        self.assertNotEqual(a[0],b[0])
        self.assertIsNone(self.svc.lease_work('episode'))

    def test_concurrent_episode_leases_cannot_take_same_work(self):
        ids=self.work_ids()
        for wid in ids:self.recognize(wid)
        gate=threading.Barrier(3)
        claimed=[];errors=[]
        def take():
            try:
                gate.wait(timeout=5)
                claimed.append(self.svc.lease_work('episode'))
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=take) for _ in ids]
        for t in threads:t.start()
        for t in threads:t.join(timeout=8)
        self.assertFalse(errors,errors)
        self.assertEqual({r[0] for r in claimed},set(ids))
        self.assertEqual(len(claimed),3)

    def test_deleting_work_cleans_up_episode_queue(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        with self.db() as c:
            c.execute('DELETE FROM works WHERE id=?',(wid,))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue WHERE work_id=?',(wid,)).fetchone()[0],0)

    def test_queued_episode_has_own_due_date(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        with self.db() as c:
            self.assertGreater(c.execute('SELECT next_try FROM works WHERE id=?',(wid,)).fetchone()[0],time.time()+20000)
            self.assertEqual(c.execute('SELECT next_try FROM episode_queue WHERE work_id=?',(wid,)).fetchone()[0],0)

    def test_manual_confirmation_and_format_changes_remove_task(self):
        ids=self.work_ids()
        self.recognize(ids[0]);self.recognize(ids[1])
        with self.db() as c:
            c.execute("UPDATE works SET state='manual' WHERE id=?",(ids[0],))
            c.execute("UPDATE works SET state='format' WHERE id=?",(ids[1],))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)

    def test_deferred_provider_keeps_identity_refresh_path(self):
        wid=self.work_ids()[0]
        self.recognize(wid,deferred=True)
        with self.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)
            c.execute('UPDATE works SET next_try=0 WHERE id=?',(wid,))
            self.assertEqual(self.svc.pick(c)['id'],wid)

    def test_one_time_migration_reconstructs_old_queue(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        with self.db() as c:
            c.execute('DELETE FROM episode_queue')
            catalog.initialize(c)
            self.assertIsNotNone(c.execute('SELECT * FROM episode_queue WHERE work_id=?',(wid,)).fetchone())
            c.execute('UPDATE episode_queue SET attempts=3,next_try=123456 WHERE work_id=?',(wid,))
            catalog.initialize(c)
            self.assertEqual(c.execute('SELECT attempts FROM episode_queue WHERE work_id=?',(wid,)).fetchone()[0],3)

    def test_failed_local_evidence_is_persisted_across_restart(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        offline=type('OfflineArchive',(),{'updated':1,'candidates':lambda self,*args:[]})()
        with patch.object(imdb_archive,'ACTIVE',offline):
            self.assertTrue(self.svc.metadata_once('episode'))
        with self.db() as c:
            q=c.execute('SELECT * FROM episode_queue WHERE work_id=?',(wid,)).fetchone()
            self.assertEqual(q['attempts'],1)
            self.assertEqual(q['last_outcome'],'unresolved')
            self.assertGreater(q['next_try'],time.time()+25*86400)
            self.assertEqual(c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()[0],'identified')
        resumed=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)
        self.assertIsNone(resumed.lease_work('episode'))
        with self.db() as c:
            catalog.prioritize(c,[wid])
            self.assertEqual(c.execute('SELECT next_try FROM episode_queue WHERE work_id=?',(wid,)).fetchone()[0],0)
        self.assertEqual(resumed.lease_work('episode')[0],wid)

    def test_only_unique_verified_episode_is_matched(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        def found(row,meta):
            return [{**meta,'title':'Beispielserie','provider':'IMDb Offline',
                     'reference_id':'tt-series','episode_reference_id':'tt-episode',
                     'season':1,'episode':4,'episode_verified':True,
                     'similarity':1.0,'year_mismatch':False,
                     'runtime_mismatch':False}]
        archive=type('Archive',(),{'updated':1,'candidates':lambda self,*args:found(*args)})()
        with patch.object(imdb_archive,'ACTIVE',archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        with self.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE state='matched'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)
        self.assertEqual(self.svc.episode_matched,1)

    def test_priority_routes_to_episode_worker(self):
        ids=self.work_ids();self.recognize(ids[0]);self.recognize(ids[1])
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=?',(time.time()+86400,))
            catalog.prioritize(c,[ids[1]])
            self.assertEqual(self.svc.pick_episode(c)['id'],ids[1])
            self.assertNotEqual(self.svc.pick(c)['id'],ids[1])

    def test_disjoint_first_pass_uses_identity_queue_only(self):
        wid=self.work_ids()[0]
        self.recognize(wid)
        with self.db() as c:
            self.assertEqual(catalog.stats(c)['first_pass_remaining'],2)
        metrics=self.svc.scan_progress()
        self.assertEqual(metrics['episode_queue_total'],1)
        self.assertEqual(metrics['episode_queue_due'],1)


if __name__=='__main__':unittest.main()
