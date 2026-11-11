import sqlite3, tempfile, pathlib, unittest, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import diagnostic_extensions as ex

class DiagnosticExtensionTests(unittest.TestCase):
    def test_missing_is_readonly_and_safe(self):
        with tempfile.TemporaryDirectory() as d:
            x=ex.collect(d)
            self.assertFalse(x['netzkino']['available'])
            self.assertFalse(x['video_audit']['available'])
            self.assertFalse((pathlib.Path(d)/'catalog.db').exists())
            self.assertFalse((pathlib.Path(d)/'netzkino_links.sqlite3').exists())

    def test_status_counts_no_titles_or_urls(self):
        with tempfile.TemporaryDirectory() as d:
            db=sqlite3.connect(str(pathlib.Path(d)/'netzkino_links.sqlite3'))
            db.executescript("""CREATE TABLE netzkino_links(id TEXT,title TEXT,url TEXT);
            CREATE TABLE netzkino_catalog(id TEXT,title TEXT,url TEXT,source TEXT,kind TEXT,year INTEGER,poster TEXT,genres TEXT,summary TEXT,fsk INTEGER,content_id TEXT,access_hint TEXT);
            CREATE TABLE netzkino_state(name TEXT,value TEXT);
            INSERT INTO netzkino_catalog VALUES('a','SEKRET FILMTITEL','https://www.netzkino.de/details/sehrprivat','har_snapshot','movie',1999,'https://www.netzkino.de/cover','Drama','Plot',12,'movie-a','AVOD');
            INSERT INTO netzkino_links VALUES('b','MANUELL SECRET','https://www.netzkino.de/details/privat');
            INSERT INTO netzkino_state VALUES('last_error','HTTP 429: https://private.example/?token=123');
            INSERT INTO netzkino_state VALUES('categories_checked','13');
            """)
            db.commit();db.close()
            x=ex.collect(d)['netzkino']
            self.assertEqual(x['catalog_count'],1)
            self.assertEqual(x['by_source'],{'har_snapshot':1})
            self.assertEqual(x['metadata_coverage']['year'],1)
            self.assertEqual(x['categories_checked'],13)
            self.assertNotIn('token=123',str(x))
            self.assertNotIn('SEKRET',str(x))
            self.assertNotIn('privat',str(x))

    def test_audit_and_portal_counts(self):
        with tempfile.TemporaryDirectory() as d:
            db=sqlite3.connect(str(pathlib.Path(d)/'catalog.db'))
            db.executescript("""CREATE TABLE catalog_state(key TEXT,value TEXT);
            CREATE TABLE video_role_audit(work_id TEXT,video_role TEXT);
            CREATE TABLE portal_items(source TEXT);
            INSERT INTO catalog_state VALUES('video_role_audit_checked_v05311','25');
            INSERT INTO catalog_state VALUES('video_role_audit_skipped_v05311','75');
            INSERT INTO video_role_audit VALUES('a','trailer');
            INSERT INTO portal_items VALUES('internet_archive');
            """)
            db.commit();db.close()
            x=ex.collect(d)
            self.assertEqual(x['video_audit']['processed'],100)
            self.assertEqual(x['video_audit']['by_role'],{'trailer':1})
            self.assertEqual(x['portals']['by_source'],{'internet_archive':1})

if __name__=='__main__':unittest.main()
