"""0.5.25: race-safe metadata workers and authorized on-availability subscriptions."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

import catalog
import catalog_service
import subscriptions

def src(title,topic='Spielfilm',tag='one',duration=5500):
    return {'title':title,'topic':topic,'channel':'ARD','duration':duration,
            'description':'Ein regulär angebotener Film',
            'url_video':'https://example.org/'+tag+'.mp4'}

class SubscriptionsTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.c=sqlite3.connect(str(self.root/'library.db'))
        self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
        subscriptions.initialize(self.c)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
    def tearDown(self):self.c.close()
    def add_work(self,title='Der Film',topic='Spielfilm',tag='film',kind='movie',season=None,episode=None,
                 verified=False,year=2022,expiry=None):
        source=src(title,topic,tag,3600 if kind=='series' else 5400)
        if expiry:source['available_until']=expiry
        catalog.ingest(self.c,[source])
        offer=self.c.execute('SELECT work_id FROM offers WHERE payload LIKE ? LIMIT 1',('%'+tag+'.mp4%',)).fetchone()
        self.assertIsNotNone(offer)
        work=self.c.execute('SELECT * FROM works WHERE id=?',(offer['work_id'],)).fetchone()
        m=json.loads(work['meta']);m.update(kind=kind,
            title=topic if kind=='series' else title,year=year if kind=='movie' else None,
            provider='TVDB' if kind=='series' else 'TMDB',reference_id='123',
            season=season,episode=episode,episode_verified=verified,
            episode_title=title if kind=='series' else '')
        self.c.execute('UPDATE works SET kind=?,title=?,state=?,year=?,show_key=?,meta=? WHERE id=?',
            (kind,m['title'],'matched',m['year'],catalog.showkey(m),json.dumps(m),work['id']))
        return work['id']
    def subscribe(self,title='Der Film',kind='movie',**kwargs):
        return subscriptions.add(self.c,{'title':title,'kind':kind,'confirmed':True,**kwargs})
    def test_requires_explicit_consent(self):
        with self.assertRaises(ValueError):subscriptions.add(self.c,{'title':'Der Film','kind':'movie'})
    def test_on_availability_film_creates_one_job_and_never_queues_duplicate(self):
        self.add_work()
        sub=self.subscribe(include_existing=True)
        first=subscriptions.run_due(self.c,self.root,force_id=sub)
        self.assertEqual(first[0]['queued'],1)
        second=subscriptions.run_due(self.c,self.root,force_id=sub)
        self.assertEqual(second[0]['queued'],0)
        job=json.loads(self.c.execute('SELECT payload FROM jobs').fetchone()[0])
        self.assertEqual(job['subscription_id'],sub)
        self.assertEqual(job['state'],'queued')
        self.assertEqual(job['quality'],'best')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM subscription_jobs').fetchone()[0],1)
        self.assertEqual(subscriptions.get_all(self.c)[0]['queued_count'],1)
    def test_series_requires_real_episode_evidence(self):
        self.add_work(title='Staffel 1, Folge 2',topic='Beispielserie',tag='ep2',
            kind='series',season=1,episode=2,verified=False)
        sub=self.subscribe(title='Beispielserie',kind='series',include_existing=True)
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],0)
        row=self.c.execute("SELECT id,meta FROM works LIMIT 1").fetchone()
        meta=json.loads(row['meta']);meta['episode_verified']=True
        self.c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(meta),row['id']))
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],1)
    def test_recurring_series_defaults_to_future_only(self):
        self.add_work(title='Folge 1',topic='Beispielserie',tag='ep1',
            kind='series',season=1,episode=1,verified=True)
        sub=self.subscribe(title='Beispielserie',kind='series',include_existing=False)
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],0)
        self.add_work(title='Folge 2',topic='Beispielserie',tag='ep2',
            kind='series',season=1,episode=2,verified=True)
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],1)
    def test_expired_source_does_not_download(self):
        self.add_work(expiry='2020-01-01')
        sub=self.subscribe()
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],0)
    def test_downloaded_item_is_not_enqueued_again(self):
        wid=self.add_work()
        self.c.execute('INSERT INTO downloaded_items VALUES(?,?,?)',(wid,'/no-longer-mounted/film.mkv',time.time()))
        sub=self.subscribe()
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],0)
    def test_different_offers_for_same_film_are_not_duplicated(self):
        self.add_work()
        sub=self.subscribe()
        subscriptions.run_due(self.c,self.root,force_id=sub)
        self.assertEqual(subscriptions.run_due(self.c,self.root,force_id=sub)[0]['queued'],0)
    def test_weekly_schedule_is_in_future(self):
        now=time.time()
        sub=self.subscribe(mode='weekly',weekday=0,hour=19)
        row=subscriptions.get_all(self.c)[0]
        self.assertGreater(row['next_check'],now)
        self.assertLessEqual(row['next_check']-now,8*86400)
        self.assertEqual(subscriptions.due(self.c,now),[])
    def test_pause_resume_delete_keep_existing_jobs(self):
        self.add_work()
        sub=self.subscribe()
        subscriptions.run_due(self.c,self.root,force_id=sub)
        subscriptions.change(self.c,sub,'pause')
        self.assertFalse(subscriptions.get_all(self.c)[0]['enabled'])
        subscriptions.change(self.c,sub,'resume')
        self.assertTrue(subscriptions.get_all(self.c)[0]['enabled'])
        subscriptions.change(self.c,sub,'delete')
        self.assertEqual(subscriptions.get_all(self.c),[])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
    def test_subscriptions_survive_database_reopen(self):
        sub=self.subscribe()
        self.c.commit();self.c.close()
        self.c=sqlite3.connect(str(self.root/'library.db'));self.c.row_factory=sqlite3.Row
        self.assertEqual(subscriptions.get_all(self.c)[0]['id'],sub)

class WorkerLeasesTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.db_path=Path(self.t.name)/'workers.db'
        with self.connect() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[src('Film Eins',tag='one'),src('Film Zwei',tag='two')])
        self.svc=catalog_service.Service(self.connect,lambda:{'auto_metadata':True,'metadata_workers':2,'scan_priority':'movies_first','complete_series':False},threading.Event(),Path(self.t.name))
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db_path,timeout=20);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def test_two_workers_claim_different_works(self):
        one=self.svc.lease_work()
        two=self.svc.lease_work()
        self.assertIsNotNone(one);self.assertIsNotNone(two)
        self.assertNotEqual(one[0],two[0])
        self.assertIsNone(self.svc.lease_work())
        with self.connect() as c:c.execute('DELETE FROM metadata_leases WHERE work_id=?',(one[0],))
        self.assertEqual(self.svc.lease_work()[0],one[0])
    def test_stale_lease_recovers_after_crash(self):
        first=self.svc.lease_work()
        with self.connect() as c:c.execute('UPDATE metadata_leases SET expires=? WHERE work_id=?',(time.time()-1,first[0]))
        second=self.svc.lease_work()
        self.assertEqual(first[0],second[0])
    def test_priority_respects_active_lease(self):
        with self.connect() as c:
            row=c.execute('SELECT id FROM works LIMIT 1').fetchone()
            catalog.prioritize(c,ids=[row['id']])
        first=self.svc.lease_work()
        self.assertEqual(first[0],row['id'])
        second=self.svc.lease_work()
        self.assertNotEqual(first[0],second[0])

if __name__=='__main__':unittest.main()
