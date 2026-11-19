"""0.6.24: episode search finds episodes of already identified series.

Diagnosis 0.6.8/0.6.18 (Mac): 25,700 episode checks, 4 matches. Causes:
1. The queued work keeps the identifying provider's series year (TMDB/TVDB);
   IMDb's start year is often one year apart, and the strict year check
   rejected every IMDb episode.
2. Broadcaster titles carry numbering ("Titel (S01/E12)", "Folge 12: Titel");
   IMDb's exact name probe never matched them.
3. The queue is dominated by magazine/news editions whose IMDb series has no
   episodes; every edition was checked on its own.
4. Postponed claims (sender budget) were counted as checks.
"""
import gzip
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
import matching


ROWS={
    'basics':[
        'tt100\ttvSeries\tFind Me in Paris\tFind Me in Paris\t0\t2018\t\\N\t25\tComedy',
        'tt101\ttvEpisode\tThe Audition\tThe Audition\t0\t2018\t\\N\t25\tComedy',
        'tt102\ttvEpisode\tGhost of a Chance\tGhost of a Chance\t0\t2018\t\\N\t25\tComedy',
        'tt300\ttvSeries\tSchleswig-Holstein Magazin\tSchleswig-Holstein Magazin\t0\t1990\t\\N\t30\tNews',
        'tt400\ttvSeries\tDoppelt\tDoppelt\t0\t2010\t\\N\t45\tDrama',
        'tt401\ttvEpisode\tGleicher Name\tGleicher Name\t0\t2010\t\\N\t25\tDrama',
        'tt410\ttvSeries\tDoppelt\tDoppelt\t0\t2011\t\\N\t45\tDrama',
        'tt411\ttvEpisode\tGleicher Name\tGleicher Name\t0\t2011\t\\N\t25\tDrama',
    ],
    'ratings':['tt100\t7.1\t1000'],
    'episode':['tt101\ttt100\t1\t12','tt102\ttt100\t1\t13','tt401\ttt400\t1\t1','tt411\ttt410\t2\t5'],
    'akas':['tt101\t1\tDas Vorsprechen\tDE\tde\t\\N\t\\N\t0',
            'tt102\t1\tGeisterstunde\tDE\tde\t\\N\t\\N\t0',
            'tt100\t2\tFind me in Paris\tDE\tde\t\\N\t\\N\t0'],
    'crew':['tt101\t\\N\t\\N'],
    'principals':['tt101\t1\tnm1\tactress\t\\N\t["Lena"]'],
    'people':['nm1\tJessica Lord\t\\N\t\\N\tactress\ttt100'],
}


def build_archive(root):
    files={}
    for kind,rows in ROWS.items():
        path=root/(kind+'.gz')
        path.write_bytes(gzip.compress(('\t'.join(imdb_archive.HEADERS[kind])+'\n'+'\n'.join(rows)+'\n').encode()))
        files[kind]=path
    archive=imdb_archive.Archive(root,threading.Event())
    imdb_archive.build(archive.path,files)
    return imdb_archive.Archive(root,threading.Event())


def identified(seed,**kw):
    return {**seed,'kind':'series','episode_verified':False,**kw}


class NameTests(unittest.TestCase):
    def test_numbering_decoration_is_removed(self):
        for raw in ('Das Vorsprechen (S01/E12)','Folge 12: Das Vorsprechen','Das Vorsprechen (Folge 12)',
                    'S01E12 - Das Vorsprechen','Staffel 1, Folge 12: Das Vorsprechen','Das Vorsprechen (1x12)'):
            with self.subTest(raw=raw):
                self.assertEqual(imdb_archive.episode_name(raw),'Das Vorsprechen')

    def test_bare_number_and_show_title_are_no_probe(self):
        terms=imdb_archive.episode_search_terms({'title':'Folge 12'},{'episode_title':'Folge 12'},'Rote Rosen')
        self.assertEqual(terms,['folge 12'])
        terms=imdb_archive.episode_search_terms({'title':'Rote Rosen (S01/E02)'},{},'Rote Rosen')
        self.assertNotIn('rote rosen',terms)

    def test_show_prefix_still_needs_explicit_delimiter(self):
        terms=imdb_archive.episode_search_terms({'title':'Example Show Beginning'},{},'Example Show')
        self.assertNotIn('beginning',terms)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.archive=build_archive(Path(tmp.name))

    def tearDown(self):
        opened=getattr(self.archive._reader_local,'opened',None)
        if opened:opened[1].close()

    def check(self,title,topic='Find me in Paris',**kw):
        src={'title':title,'topic':topic,'duration':1500}
        m=identified(catalog.seed(src),title=topic,provider='TMDB',reference_id='77',**kw)
        ev=self.archive.episode_evidence(src,m)
        return m,ev,matching.choose(m,ev['candidates'])

    def test_provider_year_one_apart_still_finds_episode_and_keeps_identity(self):
        for year in (2017,2018,2019,None):
            for title in ('Das Vorsprechen (S01/E12)','Folge 12: Das Vorsprechen','Das Vorsprechen (Folge 12)'):
                with self.subTest(year=year,title=title):
                    m,ev,chosen=self.check(title,year=year)
                    self.assertIsNotNone(chosen)
                    self.assertEqual((chosen['season'],chosen['episode']),(1,12))
                    self.assertEqual(chosen['episode_reference_id'],'tt101')
                    # The series identity of the work is never replaced.
                    for field in ('title','year','provider','reference_id'):
                        self.assertEqual(chosen.get(field),m.get(field))
                    self.assertEqual(catalog.showkey(chosen),catalog.showkey(m))
                    self.assertEqual(chosen['episode_title'],'Das Vorsprechen')
                    self.assertEqual(chosen['imdb_id'],'tt100')
                    self.assertEqual(chosen['cast'][0]['name'],'Jessica Lord')

    def test_old_strict_candidates_rejected_provider_year(self):
        # Documents the cause: the identification lookup compares years strictly.
        src={'title':'Das Vorsprechen (S01/E12)','topic':'Find me in Paris','duration':1500}
        m=identified(catalog.seed(src),title='Find me in Paris',provider='TMDB',reference_id='77',year=2017)
        self.assertIsNone(matching.choose(m,self.archive.candidates(src,m)))

    def test_distant_year_is_another_series(self):
        _,ev,chosen=self.check('Das Vorsprechen (S01/E12)',year=2014)
        self.assertIsNone(chosen);self.assertEqual(ev['series'],0)

    def test_conflicting_numbers_are_rejected(self):
        _,_,chosen=self.check('Das Vorsprechen (S02/E12)',year=2018)
        self.assertIsNone(chosen)

    def test_known_imdb_reference_beats_title(self):
        src={'title':'Geisterstunde','topic':'Paris-Serie','duration':1500}
        m=identified(catalog.seed(src),title='Paris-Serie',provider='TMDB',reference_id='77',year=2005,imdb_id='tt100')
        chosen=matching.choose(m,self.archive.episode_evidence(src,m)['candidates'])
        self.assertEqual((chosen['season'],chosen['episode']),(1,13))
        self.assertEqual(chosen['title'],'Paris-Serie')
        m2=identified(catalog.seed(src),title='Paris-Serie',provider='IMDb Offline',reference_id='tt100',year=2018)
        self.assertEqual(matching.choose(m2,self.archive.episode_evidence(src,m2)['candidates'])['episode'],13)

    def test_two_series_with_same_episode_name_stay_unresolved(self):
        _,ev,chosen=self.check('Gleicher Name',topic='Doppelt',year=2010)
        self.assertIsNone(chosen);self.assertTrue(ev['ambiguous'])
        _,ev,chosen=self.check('Gleicher Name',topic='Doppelt',year=2009)
        self.assertEqual(chosen['episode_reference_id'],'tt401')
        self.assertEqual(chosen['imdb_id'],'tt400')

    def test_series_without_imdb_episodes_is_reported(self):
        _,ev,chosen=self.check('Schleswig-Holstein Magazin vom 15.11.2026',topic='Schleswig-Holstein Magazin',year=1990)
        self.assertIsNone(chosen)
        self.assertEqual((ev['series'],ev['series_with_episodes']),(1,0))

    def test_unknown_episode_is_not_invented(self):
        _,ev,chosen=self.check('Unbekannte Folge',year=2018)
        self.assertIsNone(chosen);self.assertEqual(ev['candidates'],[])


def offer(title,topic,tag,site=''):
    return {'title':title,'topic':topic,'channel':'NDR','duration':1500,
            'description':'Sendung','url_video':'https://example.org/'+tag+'.mp4',
            'url_website':site or 'https://www.ndr.de/'+tag+'.html'}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'catalog.db'
        self.archive=build_archive(self.root)
        self.addCleanup(self.close_archive)
        self.direct=False
        self.settings=lambda:{'auto_metadata':True,'episode_workers':2,'metadata_workers':2,
                              'sender_direct_lookup':self.direct,'scan_priority':'series_first',
                              'complete_series':False}
        with self.db() as c:c.executescript(catalog.SCHEMA)
        self.svc=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)

    def close_archive(self):
        opened=getattr(self.archive._reader_local,'opened',None)
        if opened:opened[1].close()

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def add(self,src,title,year,reference='77'):
        with self.db() as c:
            catalog.ingest(c,[src])
            row=c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.url_video')=?",
                          (src['url_video'],)).fetchone()
            m=json.loads(row['meta'])
            m.update(kind='series',title=title,provider='TMDB',reference_id=reference,year=year,episode_verified=False)
            catalog.save_metadata(c,row['id'],m,'identified')
            return row['id']

    def queue(self,wid):
        with self.db() as c:return c.execute('SELECT * FROM episode_queue WHERE work_id=?',(wid,)).fetchone()

    def test_queued_episode_is_matched_with_series_identity_kept(self):
        wid=self.add(offer('Folge 12: Das Vorsprechen','Find me in Paris','a'),'Find me in Paris',2017)
        with self.db() as c:show=c.execute('SELECT show_key FROM works WHERE id=?',(wid,)).fetchone()[0]
        self.assertIsNotNone(self.queue(wid))
        with patch.object(imdb_archive,'ACTIVE',self.archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        with self.db() as c:
            rows=c.execute("SELECT * FROM works WHERE state='matched'").fetchall()
            self.assertEqual(len(rows),1)
            m=json.loads(rows[0]['meta'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)
        self.assertEqual((m['season'],m['episode'],m['provider'],m['year']),(1,12,'TMDB',2017))
        self.assertEqual(rows[0]['show_key'],show)
        self.assertEqual(self.svc.episode_matched,1);self.assertEqual(self.svc.episode_checked,1)

    def test_editions_of_series_without_imdb_episodes_are_postponed_together(self):
        ids=[self.add(offer('Schleswig-Holstein Magazin vom %d.11.2026'%d,'Schleswig-Holstein Magazin','sh%d'%d),
                      'Schleswig-Holstein Magazin',1990,reference='9') for d in range(1,6)]
        other=self.add(offer('Folge 12: Das Vorsprechen','Find me in Paris','b'),'Find me in Paris',2018)
        with self.db() as c:catalog.prioritize(c,[ids[4]])
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=0')
            c.execute('DELETE FROM metadata_priority WHERE work_id!=?',(ids[0],))
            c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(ids[0],0))
            c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(ids[4],1))
            c.execute('UPDATE episode_queue SET next_try=1 WHERE work_id=?',(ids[4],))
        with patch.object(imdb_archive,'ACTIVE',self.archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        first=self.queue(ids[0]);self.assertEqual(first['last_outcome'],'unresolved')
        now=time.time()
        for wid in ids[1:4]:
            q=self.queue(wid)
            self.assertEqual(q['last_outcome'],'no_imdb_episodes')
            self.assertEqual(q['attempts'],0)
            self.assertGreaterEqual(q['next_try'],now+29*86400)
            self.assertLessEqual(q['next_try'],now+38*86400)
        # A user priority and another series stay due.
        self.assertEqual(self.queue(ids[4])['next_try'],1)
        self.assertEqual(self.queue(other)['next_try'],0)
        self.assertEqual(self.svc.episode_series_deferred,3)
        self.assertEqual(self.svc.scan_progress()['episode_series_deferred_session'],3)

    def test_sender_linked_editions_stay_due_when_sender_lookup_allowed(self):
        self.direct=True
        ard='https://www.ardmediathek.de/video/sh-magazin/folge/ndr/Y3JpZDovL25kci5kZS9hYmMxMjM'
        a=self.add(offer('Schleswig-Holstein Magazin vom 1.11.2026','Schleswig-Holstein Magazin','x1'),'Schleswig-Holstein Magazin',1990,'9')
        b=self.add(offer('Schleswig-Holstein Magazin vom 2.11.2026','Schleswig-Holstein Magazin','x2',site=ard),'Schleswig-Holstein Magazin',1990,'9')
        c_=self.add(offer('Schleswig-Holstein Magazin vom 3.11.2026','Schleswig-Holstein Magazin','x3'),'Schleswig-Holstein Magazin',1990,'9')
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=0')
            c.execute('UPDATE episode_queue SET next_try=1 WHERE work_id!=?',(a,))
        with patch.object(imdb_archive,'ACTIVE',self.archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        self.assertEqual(self.queue(b)['next_try'],1)
        self.assertEqual(self.queue(c_)['last_outcome'],'no_imdb_episodes')

    def test_earlier_unresolved_results_are_rechecked_once(self):
        a=self.add(offer('Folge 12: Das Vorsprechen','Find me in Paris','m1'),'Find me in Paris',2017)
        b=self.add(offer('Folge 13: Geisterstunde','Find me in Paris','m2'),'Find me in Paris',2017)
        later=time.time()+20*86400
        with self.db() as c:
            catalog.set_state(c,'episode_queue_recheck_v0624',False)
            c.execute("UPDATE episode_queue SET last_outcome='unresolved',attempts=2,next_try=? WHERE work_id=?",(later,a))
            c.execute("UPDATE episode_queue SET last_outcome='suspected',next_try=? WHERE work_id=?",(later,b))
            catalog.initialize(c)
            self.assertEqual(c.execute('SELECT next_try,attempts FROM episode_queue WHERE work_id=?',(a,)).fetchone()[:],(0,2))
            self.assertEqual(c.execute('SELECT next_try FROM episode_queue WHERE work_id=?',(b,)).fetchone()[0],later)
            c.execute('UPDATE episode_queue SET next_try=? WHERE work_id=?',(later,a))
            catalog.initialize(c)
            self.assertEqual(c.execute('SELECT next_try FROM episode_queue WHERE work_id=?',(a,)).fetchone()[0],later)

    def test_pick_walks_the_queue_by_due_index(self):
        ids=[self.add(offer('Folge %d: Titel %d'%(i,i),'Find me in Paris','p%d'%i),'Find me in Paris',2018) for i in range(1,4)]
        with self.db() as c:
            for n,wid in enumerate(ids):c.execute('UPDATE episode_queue SET next_try=? WHERE work_id=?',(10-n,wid))
            c.execute('UPDATE episode_queue SET next_try=? WHERE work_id=?',(time.time()+3600,ids[2]))
            plan=' '.join(str(r[-1]) for r in c.execute('EXPLAIN QUERY PLAN SELECT w.* FROM episode_queue q CROSS JOIN works w ON w.id=q.work_id WHERE q.next_try<=? ORDER BY q.next_try LIMIT 48',(time.time(),)))
            self.assertIn('episode_queue_due',plan)
            self.assertNotIn('TEMP B-TREE',plan)
            self.assertEqual(self.svc.pick_episode(c)['id'],ids[1])
            catalog.prioritize(c,[ids[0]])
            self.assertEqual(self.svc.pick_episode(c)['id'],ids[0])

    def test_postponed_claim_is_not_counted_as_check(self):
        self.svc.record_episode_result('retry')
        self.svc.record_episode_result('unresolved')
        self.assertEqual((self.svc.episode_checked,self.svc.episode_retried,self.svc.episode_unresolved),(1,1,1))


if __name__=='__main__':unittest.main()
