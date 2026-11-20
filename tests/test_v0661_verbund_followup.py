"""0.6.61: findings of the Mac check of 0.6.56 (20.11.2026)."""
import json,logging,os,sqlite3,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch
import db_backup,diagnostics,meshjournal
from tests.test_v0656_mesh_share import event_data

class BackupMessageTests(unittest.TestCase):
    def test_field_called_name_is_logged_not_a_type_error(self):
        seen=[]
        with patch.object(diagnostics.logger,'log',side_effect=lambda lvl,msg:seen.append(json.loads(msg))):
            diagnostics.event('db_backup_created',name='catalog-auto-1.db',removed=['old'])
            diagnostics.event('x',level='WARNING',name='n')
            diagnostics.error('db_backup_failed',ValueError('kaputt'),name='n')
        self.assertEqual([(e['event'],e.get('name')) for e in seen],[('db_backup_created','catalog-auto-1.db'),('x','n'),('db_backup_failed','n')])
        self.assertEqual(seen[1]['level'],'WARNING')

    def test_auto_tick_reports_and_rotates(self):
        made={'ok':True,'backup':{'name':'catalog-auto-2.db'}};seen=[]
        with patch.object(db_backup,'auto_due',return_value=True),patch.object(db_backup,'create',return_value=made),\
             patch.object(db_backup,'rotate',return_value=['catalog-auto-0.db']) as rot,\
             patch.object(diagnostics.logger,'log',side_effect=lambda lvl,msg:seen.append(json.loads(msg))):
            self.assertIs(db_backup.auto_tick(Path('/nowhere'),diagnostics.event),made)
        rot.assert_called_once()
        self.assertEqual((seen[0]['event'],seen[0]['name'],seen[0]['removed']),('db_backup_created','catalog-auto-2.db',['catalog-auto-0.db']))

class DatalessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'iCloud'/'MediathekAtlas-Verbund';self.root.mkdir(parents=True)
        meshjournal.check_folder(self.root,create=True)
        self.a=meshjournal.Journal(self.root,'a'*32)
        self.a.append('match.result',event_data('01'));self.a.flush(force=True)
        self.seg=self.a.dir/'events-000001.jsonl'
        self.addCleanup(meshjournal._fetching.clear)

    def test_dataless_flag_is_recognised(self):
        real=os.stat
        def fake(p,*a,**k):
            st=real(p,*a,**k)
            return types.SimpleNamespace(st_flags=meshjournal.SF_DATALESS if str(p)==str(self.seg) else 0,st_size=st.st_size)
        with patch.object(meshjournal.os,'stat',side_effect=fake):
            self.assertTrue(meshjournal.dataless(self.seg))
            self.assertFalse(meshjournal.dataless(self.a.dir/'node.json'))
        self.assertFalse(meshjournal.dataless(self.seg))

    def test_slow_download_waits_and_is_not_started_twice(self):
        gate=threading.Event();calls=[];real=meshjournal.segment_lines
        def slow(path):
            calls.append(path);gate.wait(5);return real(path)
        b=meshjournal.Journal(self.root,'b'*32)
        with patch.object(meshjournal,'dataless',side_effect=lambda p:str(p)==str(self.seg)),\
             patch.object(meshjournal,'segment_lines',side_effect=slow),patch.object(meshjournal,'request_download') as dl,\
             patch.object(meshjournal,'FETCH_TIMEOUT',0.05):
            events,cur,_=b.read({})
            self.assertEqual(events,[]);self.assertEqual(b.waiting,{'a'*32:1});self.assertEqual(cur.get('a'*32,[0,0]),[0,0])
            events,cur,_=b.read(cur)
            self.assertEqual(events,[])
            gate.set();time.sleep(0.1)
            events,cur,_=b.read(cur)
        self.assertEqual([e['data']['work'] for e in events],['01']);self.assertEqual(b.waiting,{})
        self.assertEqual(len(calls),1);dl.assert_called_once()

    def test_read_error_keeps_the_cursor_and_retries(self):
        b=meshjournal.Journal(self.root,'b'*32)
        with patch.object(meshjournal,'segment_lines',side_effect=OSError(60,'Operation timed out')):
            events,cur,_=b.read({})
        self.assertEqual(events,[]);self.assertEqual(b.waiting,{'a'*32:1})
        events,cur,_=b.read(cur)
        self.assertEqual([e['data']['work'] for e in events],['01'])

class MetadataCacheTests(unittest.TestCase):
    def service(self,db):
        import catalog_service
        return catalog_service.Service(db,lambda:{},threading.Event(),Path('/tmp'))

    def test_locked_cache_write_is_skipped_not_failed(self):
        from contextlib import contextmanager
        @contextmanager
        def db():
            raise sqlite3.OperationalError('database is locked');yield
        svc=self.service(db);events=[]
        with patch.object(diagnostics,'event',side_effect=lambda name,**f:events.append(name)):
            self.assertFalse(svc.cache_result('k',{'candidates':[]}))
        self.assertEqual((svc.sqlite_busy_count,events),(1,['metadata_cache_skipped']))

    def test_other_errors_still_raise_and_normal_write_works(self):
        from contextlib import contextmanager
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);path=Path(tmp.name)/'c.db'
        with sqlite3.connect(path) as c:c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
        @contextmanager
        def db():
            c=sqlite3.connect(path)
            try:
                yield c;c.commit()
            finally:c.close()
        svc=self.service(db)
        self.assertTrue(svc.cache_result('k',{'candidates':[1]}))
        with sqlite3.connect(path) as c:self.assertEqual(json.loads(c.execute('SELECT payload FROM metadata_cache').fetchone()[0]),{'candidates':[1]})
        @contextmanager
        def broken():
            raise sqlite3.OperationalError('no such table: metadata_cache');yield
        with self.assertRaises(sqlite3.OperationalError):self.service(broken).cache_result('k',{})

    def test_worker_uses_the_tolerant_cache_write(self):
        src=(Path(__file__).resolve().parents[1]/'catalog_service.py').read_text(encoding='utf-8')
        self.assertEqual(src.count("INSERT OR REPLACE INTO metadata_cache"),1)
        self.assertIn("self.cache_result(ck,result)",src)

if __name__=='__main__':unittest.main()
