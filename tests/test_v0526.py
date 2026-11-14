"""Regression tests for 0.5.26: careful episode matching, eight workers, SQLite safety."""
import gzip
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import imdb_archive
import matching
import metadata


def source(title, tag):
    return {'title': title, 'topic': 'Spielfilm', 'channel': 'ARD', 'duration': 5400,
            'description': 'Ein regulärer Spielfilm', 'url_video': 'https://example.org/'+tag+'.mp4'}


class EpisodeEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.archive=imdb_archive.Archive(self.root,threading.Event())
        names=['Example Show', 'Beginning','Next Episode','Film']
        datasets={
            'basics': [
                'tt1\ttvSeries\tExample Show\tExample Show\t0\t2020\t\\N\t25\tDrama',
                'tt2\ttvEpisode\tBeginning\tBeginning\t0\t2020\t\\N\t25\tDrama',
                'tt3\ttvEpisode\tNext Episode\tNext Episode\t0\t2020\t\\N\t25\tDrama',
                'tt4\tmovie\tFilm\tFilm\t0\t2020\t\\N\t90\tDrama',
            ],
            'ratings': ['tt1\t8.0\t1000'],
            'episode': ['tt2\ttt1\t1\t1','tt3\ttt1\t1\t2'],
            'akas': ['tt2\t1\tDer Anfang\tDE\tde\t\\N\t\\N\t0'],
            'crew': ['tt1\t\\N\t\\N'],
            'principals': ['tt1\t1\tnm1\tactor\t\\N\t[\"Figur\"]'],
            'people': ['nm1\tTest Person\t1980\t\\N\tactor\ttt1']}
        files={}
        for kind,rows in datasets.items():
            path=self.root/(kind+'.gz')
            path.write_bytes(gzip.compress(('\t'.join(imdb_archive.HEADERS[kind])+'\n'+'\n'.join(rows)+'\n').encode()))
            files[kind]=path
        imdb_archive.build(self.archive.path,files)
        self.archive=imdb_archive.Archive(self.root,threading.Event())
    def tearDown(self):
        opened=getattr(self.archive._reader_local,'opened',None)
        if opened:opened[1].close()
    def get(self,title,**kw):
        return self.archive.candidates({'title':title,'duration':1500},
                 {'kind':'series','title':'Example Show',**kw})[0]
    def test_prefix_with_explicit_delimiter_now_confirms_episode(self):
        for t in ('Example Show: Beginning','Example Show - Beginning','Example Show – Beginning'):
            with self.subTest(t=t):
                m=self.get(t)
                self.assertTrue(m['episode_verified']);self.assertEqual((m['season'],m['episode']),(1,1))
                self.assertTrue(matching.verified({'kind':'series'},m))
    def test_unrelated_or_no_delimiter_never_guesses_episode(self):
        for t in ('Example Show Beginning', 'Example Show: Unknown', 'Beginning Bonus'):
            with self.subTest(t=t):
                self.assertFalse(self.get(t)['episode_verified'])
    def test_episode_number_conflict_is_still_rejected(self):
        self.assertFalse(self.get('Example Show: Beginning',season=1,episode=2)['episode_verified'])
    def test_ambiguous_episode_title_never_auto_matches(self):
        with sqlite3.connect(self.archive.path) as c:
            c.execute('INSERT INTO title_basics VALUES(?,?,?,?,?,?,?,?,?)',
                      ('tt5','tvEpisode','Beginning','Beginning',0,2021,None,25,'Drama'))
            c.execute('INSERT INTO names VALUES(?,?,?,?)',('beginning','tt5','Beginning',0))
            c.execute('INSERT INTO title_episode VALUES(?,?,?,?)',('tt5','tt1',2,1))
        unnumbered=self.get('Example Show: Beginning')
        self.assertFalse(unnumbered['episode_verified'])
        # Only an explicitly known season and episode resolves the ambiguity.
        numbered=self.get('Example Show: Beginning',season=1,episode=1)
        self.assertTrue(numbered['episode_verified'])
        self.assertEqual(numbered['episode_reference_id'],'tt2')
    def test_full_provider_pipeline_skips_unnecessary_calls_on_exact_episode(self):
        with patch.object(imdb_archive,'ACTIVE',self.archive), patch('metadata.tmdb_candidates',side_effect=AssertionError('should not call network')):
            d=metadata.candidates({'title':'Example Show: Beginning','duration':1500},
                      {'title':'Example Show','kind':'series'}, {'tmdb':'key'})
        self.assertTrue(d['candidates'][0]['episode_verified'])
        self.assertEqual([x['provider'] for x in d['provider_checks']],['IMDb Offline'])


class WorkerAndCatalogueTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.db_path=self.root/'library.db'
        with self.connect() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[source('Film Nummer '+str(i),'film'+str(i)) for i in range(12)])
        self.settings=lambda:{'auto_metadata':True,'metadata_workers':8,
                'scan_priority':'movies_first','complete_series':False}
        self.svc=catalog_service.Service(self.connect,self.settings,threading.Event(),self.root)
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db_path,timeout=.1)
        c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def test_all_eight_workers_start(self):
        started=[]
        def fake_thread(*args,**kw):
            class Fake:
                def start(self):started.append(kw.get('name'))
            return Fake()
        with patch('catalog_service.threading.Thread',side_effect=fake_thread):self.svc.start()
        self.assertEqual(len([x for x in started if x.startswith('recognition_worker_')]),8)
    def test_eight_concurrent_claims_are_distinct(self):
        barrier=threading.Barrier(8);results=[];exceptions=[]
        def acquire():
            try:
                barrier.wait(timeout=6)
                results.append(self.svc.lease_work())
            except Exception as exc:exceptions.append(exc)
        threads=[threading.Thread(target=acquire) for _ in range(8)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=12)
        self.assertFalse(exceptions,exceptions)
        self.assertEqual(len(results),8)
        self.assertEqual(len([r for r in results if r]),8)
        self.assertEqual(len({r[0] for r in results}),8)
    def test_sqlite_busy_does_not_crash_worker(self):
        # Deterministically inject a transient SQLite write lock. Real timing-
        # based locks can expire before slow CI runners reach BEGIN IMMEDIATE.
        connect=self.svc.db
        failures=[0]
        @contextmanager
        def locked_once():
            with connect() as c:
                class Connection:
                    def execute(self,sql,*args):
                        if sql=='BEGIN IMMEDIATE' and failures[0]==0:
                            failures[0]+=1
                            raise sqlite3.OperationalError('database is locked')
                        return c.execute(sql,*args)
                yield Connection()
        self.svc.db=locked_once
        claimed=self.svc.lease_work()
        self.assertIsNotNone(claimed)
        self.assertEqual(failures,[1])
        self.assertGreaterEqual(self.svc.sqlite_busy_count,1)
    def test_quality_metrics_distinguish_full_from_partial(self):
        self.svc.record_check(True,outcome='identified')
        self.svc.record_check(True,outcome='matched')
        self.svc.record_check(False,outcome='review')
        data=self.svc.scan_progress()
        self.assertEqual(data['quality_session'],{'matched':1,'identified':1,'review':1,'retry':0})
        self.assertAlmostEqual(data['match_rate_session'],33.3,delta=.1)
        self.assertAlmostEqual(data['identified_rate_session'],66.7,delta=.1)
        self.assertEqual(data['recognition_workers_configured'],8)
    def test_missing_canonical_item_is_ignored(self):
        with self.connect() as c:self.assertIsNone(catalog.item(c,None))
    def test_listing_race_tolerates_removed_representative(self):
        class AbsentRow:
            def __init__(self,real):self.real=real
            def execute(self,sql,params=()):
                cursor=self.real.execute(sql,params)
                if sql.startswith('SELECT * FROM works WHERE id=?'):
                    class Missing:
                        def fetchone(self):return None
                    return Missing()
                return cursor
        with self.connect() as c:
            result=catalog.listing(AbsentRow(c),kind='movie')
        self.assertEqual(result['items'],[])
        self.assertGreater(result['total'],0)

if __name__=='__main__':unittest.main()
