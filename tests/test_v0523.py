"""v0.5.23: moved downloads are recoverable without losing work history."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
import catalog,local_library

def db():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
    c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
    return c

class MovedMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.old=self.root/'library'/'film.mkv'
        self.old.parent.mkdir()
        self.old.write_bytes(b'Test media data 123456789')
        self.new=self.root/'archive'/'Film'/'film.mkv'
        self.new.parent.mkdir(parents=True)
        self.c=db()
        src={'title':'Testfilm','topic':'Filme','url_video':'https://example.org/film.mp4','channel':'ARD','duration':6000}
        catalog.ingest(self.c,[src])
        self.wid=self.c.execute('SELECT id FROM works').fetchone()[0]
        self.oid=self.c.execute('SELECT id FROM offers').fetchone()[0]
        self.job={'id':'a1','state':'done','path':str(self.old),'target':str(self.old),
                  'size_bytes':self.old.stat().st_size,'source':{'_id':self.oid},
                  'metadata':{'title':'Testfilm','kind':'movie'}}
        self.c.execute("INSERT INTO jobs VALUES(?,?,?)",('a1',json.dumps(self.job),'done'))
        catalog.mark_downloaded(self.c,self.job)
        local_library.invalidate(self.old,self.new)
    def tearDown(self):
        self.c.close()
        local_library.invalidate(self.old,self.new)
        self.tmp.cleanup()
    def test_moved_file_is_not_download_failure_and_relink_restores_history(self):
        self.assertEqual(local_library.file_state(self.old),'available')
        self.old.rename(self.new)
        local_library.invalidate(self.old)
        self.assertEqual(local_library.file_state(self.old),'missing')
        before=catalog.item(self.c,self.c.execute('SELECT * FROM works').fetchone())
        self.assertTrue(before['downloaded'])
        self.assertEqual(before['file_state'],'missing')
        allowed=local_library.roots({'download_dir':str(self.old.parent),'library_dirs':[str(self.new.parent)]})
        self.assertEqual(local_library.candidates(self.job,allowed)['matches'],[str(self.new)])
        result=local_library.relink(self.c,'a1',str(self.new),allowed)
        self.assertTrue(result['ok'])
        self.assertEqual(self.c.execute("SELECT state FROM jobs WHERE id='a1'").fetchone()[0],'done')
        saved=json.loads(self.c.execute("SELECT payload FROM jobs WHERE id='a1'").fetchone()[0])
        self.assertEqual(saved['path'],str(self.new))
        self.assertEqual(saved['previous_paths'],[str(self.old)])
        self.assertEqual(self.c.execute('SELECT path FROM downloaded_items WHERE identity=?',(self.wid,)).fetchone()[0],str(self.new))
        after=catalog.item(self.c,self.c.execute('SELECT * FROM works').fetchone())
        self.assertEqual((after['downloaded'],after['file_state']),(True,'available'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers').fetchone()[0],1)
    def test_offline_volume_preserves_download_history(self):
        self.old.unlink()
        local_library.invalidate(self.old)
        item=catalog.item(self.c,self.c.execute('SELECT * FROM works').fetchone())
        self.assertTrue(item['downloaded'])
        self.assertEqual(item['file_state'],'missing')
        self.assertEqual(self.c.execute("SELECT state FROM jobs WHERE id='a1'").fetchone()[0],'done')
    def test_relink_rejects_unapproved_folder(self):
        self.old.rename(self.new)
        allowed=local_library.roots({'download_dir':str(self.old.parent)})
        with self.assertRaisesRegex(ValueError,'nicht freigegeben'):
            local_library.relink(self.c,'a1',str(self.new),allowed)
    def test_relink_rejects_different_size_and_preserves_original(self):
        self.old.rename(self.new)
        self.new.write_bytes(b'different')
        allowed=local_library.roots({'download_dir':str(self.old.parent),'library_dirs':[str(self.new.parent)]})
        with self.assertRaisesRegex(ValueError,'Dateigröße'):
            local_library.relink(self.c,'a1',str(self.new),allowed)
        self.assertEqual(self.c.execute('SELECT path FROM downloaded_items WHERE identity=?',(self.wid,)).fetchone()[0],str(self.old))
    def test_symlink_cannot_escape_approved_root(self):
        outside=self.root/'outside';outside.mkdir()
        film=outside/'film.mkv';film.write_bytes(b'x'*self.job['size_bytes'])
        link=self.old.parent/'evil.mkv';link.symlink_to(film)
        with self.assertRaisesRegex(ValueError,'nicht freigegeben'):
            local_library.validated_path(link,[self.old.parent.resolve()])
    def test_search_is_bounded_and_never_auto_picks_ambiguous_match(self):
        self.old.rename(self.new)
        duplicate=self.root/'archive'/'Another'/'film.mkv'
        duplicate.parent.mkdir();duplicate.write_bytes(self.new.read_bytes())
        allowed=local_library.roots({'download_dir':str(self.root/'archive')})
        r=local_library.candidates(self.job,allowed,max_files=50,seconds=5)
        self.assertEqual(set(r['matches']),{str(self.new),str(duplicate)})
    def test_unknown_size_requires_exact_basename_even_manual(self):
        self.job.pop('size_bytes');self.old.rename(self.new)
        wrong=self.new.with_name('other.mkv');self.new.rename(wrong)
        with self.assertRaisesRegex(ValueError,'Dateiname'):
            local_library.check_identity(self.job,wrong)
    def test_root_directory_and_relative_paths_not_authorized(self):
        dirs=local_library.roots({'download_dir':'/','library_dirs':['relative','/']})
        self.assertEqual(dirs,[])
        with self.assertRaisesRegex(ValueError,'absoluten'):
            local_library.validated_path('relative.mkv',[])

if __name__=='__main__':unittest.main()
