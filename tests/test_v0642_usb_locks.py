"""0.6.42: Björns Nachtdiagnose 0.6.40 (20.11.2026) – IMDb-Update auf exFAT, Sperren auf USB, Protokolllänge."""
import gzip,re,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import catalog_service,diagnostics,imdb_archive as imdb

ROOT=Path(__file__).resolve().parents[1]

class ImdbStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.files={}
        rows={'basics':['tt1\ttvSeries\tExample Show\tExample Show\t0\t2020\t\\N\t25\tFamily'],'ratings':['tt1\t8.1\t100'],'episode':['tt2\ttt1\t1\t1'],
              'akas':['tt1\t1\tBeispielserie\tDE\tde\t\\N\t\\N\t0'],'crew':['tt1\tnm1\tnm1'],'principals':['tt1\t1\tnm1\tactor\t\\N\t\\N'],'people':['nm1\tPerson\t1980\t\\N\tactor\ttt1']}
        for k in imdb.HEADERS:
            p=self.root/(k+'.gz');p.write_bytes(gzip.compress(('\t'.join(imdb.HEADERS[k])+'\n'+''.join(r+'\n' for r in rows[k])).encode()));self.files[k]=p
    def tearDown(self):self.tmp.cleanup()
    def test_staging_file_is_never_empty_when_sqlite_opens_it(self):
        # exFAT/FAT on macOS: an empty file changes its ID with the first write → SQLite „readonly database“.
        target=self.root/'building.db';seen=[];real=sqlite3.connect
        def spy(path,*a,**k):
            if Path(str(path))==target:seen.append(target.stat().st_size if target.exists() else -1)
            return real(path,*a,**k)
        with patch.object(imdb.sqlite3,'connect',side_effect=spy):imdb.build(target,self.files)
        self.assertTrue(seen);self.assertTrue(all(size>0 for size in seen),seen)
        with sqlite3.connect(target) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT primaryTitle FROM title_basics').fetchone()[0],'Example Show')
            self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'delete')
    def test_seed_overwrites_leftover_and_has_full_schema(self):
        target=self.root/'building.db';target.write_bytes(b'')
        imdb.seed_file(target)
        self.assertTrue(target.read_bytes().startswith(b'SQLite format 3\x00'))
        with sqlite3.connect(target) as c:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'title_basics','title_ratings','title_episode','names','title_akas','title_crew','title_principals','name_basics','snapshot'})
    def test_failed_update_logs_sqlite_error_name(self):
        archive=imdb.Archive(self.root,threading.Event());logged=[]
        err=sqlite3.OperationalError('attempt to write a readonly database')
        try:err.sqlite_errorname='SQLITE_READONLY_DBMOVED'
        except AttributeError:pass
        with patch.object(archive,'fetch'),patch.object(imdb,'build',side_effect=err),\
             patch.object(imdb.diagnostics,'error',side_effect=lambda name,e,**f:logged.append((name,f))):
            archive.update()
        self.assertEqual(logged[0][0],'imdb_archive_failed')
        self.assertEqual(logged[0][1]['sqlite_error'],'SQLITE_READONLY_DBMOVED')
        self.assertIn('folder_free',logged[0][1])
        self.assertFalse((self.root/'building.db').exists())

class FakeJournal:
    def __init__(self,result):self.result=result
    def read(self,cursors,limit):return self.result(cursors)

class MeshCursorTests(unittest.TestCase):
    def service(self,writes):
        from contextlib import contextmanager
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'c.db'
        with sqlite3.connect(path) as c:c.execute('CREATE TABLE catalog_state(key TEXT PRIMARY KEY,value TEXT)')
        @contextmanager
        def db():
            c=sqlite3.connect(path)
            try:
                with c:yield c
            finally:c.close()
        s=catalog_service.Service(db,lambda:{},threading.Event(),Path(tmp.name))
        return s
    def test_idle_round_does_not_write(self):
        s=self.service([])
        with patch.object(catalog_service.catalog,'set_state') as set_state:
            s.mesh_import(FakeJournal(lambda cur:([],dict(cur),0)))
        set_state.assert_not_called()
    def test_moved_cursor_is_saved(self):
        s=self.service([])
        with patch.object(catalog_service.catalog,'set_state') as set_state:
            s.mesh_import(FakeJournal(lambda cur:([],{'node':5},1)))
        set_state.assert_called_once();self.assertEqual(s.mesh_invalid,1)

class SourceChecks(unittest.TestCase):
    server=(ROOT/'server.py').read_text(encoding='utf-8')
    def test_catalog_connections_use_normal_sync(self):
        block=self.server[self.server.index('def db():'):self.server.index('_BOOT=')]
        self.assertIn("PRAGMA synchronous=NORMAL",block)
    def test_settings_writes_go_through_cache_invalidation(self):
        writes=re.findall(r"INSERT OR REPLACE INTO settings",self.server)
        self.assertEqual(len(writes),1)   # only inside store_settings
        body=self.server[self.server.index('def store_settings'):self.server.index('def _settings_payload')]
        # 0.6.53: write-through with a generation counter (a reader before the commit kept the old row).
        self.assertIn("_SETTINGS_CACHE.update(payload=payload",body);self.assertIn("gen=_SETTINGS_CACHE['gen']+1",body)
        # 0.6.123: callers go through _save_settings/write_waiting (waits for a busy database), which calls store_settings
        self.assertGreaterEqual(self.server.count('store_settings(c,s)')+self.server.count('_save_settings(s)'),4)
    def test_diagnostic_log_holds_a_night(self):
        self.assertGreaterEqual(diagnostics.LOG_BYTES*(diagnostics.LOG_BACKUPS+1),32*1024*1024)

if __name__=='__main__':unittest.main()
