"""Regression tests for 0.5.19 local matching and IMDb reader reuse."""
import io,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import imdb_archive as imdb
import matching
import metadata

class MatchingTests(unittest.TestCase):
    def test_verified_movie_without_genres_skips_online_fallback(self):
        meta={'kind':'movie','title':'Example','year':2020}
        local={'provider':'IMDb Offline','kind':'movie','title':'Example','year':2020,
               'similarity':1.0,'genres':[],'runtime_agrees':True,'reference_id':'tt1'}
        self.assertTrue(matching.sufficient(meta,[local]))
        self.assertFalse(matching.sufficient(meta,[{**local,'runtime_agrees':False}]))
        self.assertFalse(matching.sufficient(meta,[{**local,'provider':'TVDB'}]))
        self.assertFalse(matching.sufficient(meta,[{**local,'year':2019}]))
    def test_verified_episode_without_genres_can_stop(self):
        meta={'kind':'series','title':'Example','season':1,'episode':2}
        local={'provider':'IMDb Offline','kind':'series','title':'Example','year':2020,
               'similarity':1.0,'genres':[],'episode_verified':True,'season':1,'episode':2,
               'reference_id':'tt1'}
        self.assertTrue(matching.sufficient(meta,[local]))
        self.assertFalse(matching.sufficient(meta,[{**local,'episode_verified':False}]))
        self.assertFalse(matching.sufficient(meta,[{**local,'episode':3}]))

class ImdbCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.a=imdb.Archive(Path(self.tmp.name),threading.Event())
        self._write_db(self.a.path,'tt1')
        self.a.updated=1
        self.a.version=0
    def tearDown(self):
        cached=getattr(self.a._reader_local,'opened',None)
        if cached:cached[1].close()
        self.tmp.cleanup()
    @staticmethod
    def _write_db(path,ident):
        with sqlite3.connect(path) as c:
            c.executescript("""CREATE TABLE names(name TEXT,tconst TEXT);
CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,startYear INTEGER,runtimeMinutes INTEGER,genres TEXT);
CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);
CREATE TABLE title_episode(tconst TEXT,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER);
""")
            c.execute("INSERT INTO names VALUES('example',?)",(ident,))
            c.execute("INSERT INTO title_basics VALUES(?,'movie',2020,90,'\\N')",(ident,))
    def test_reuses_connection_and_raw_results_without_reusing_work_decision(self):
        base={'title':'Example','kind':'movie','year':2020}
        first=self.a.candidates({'title':'Example','duration':5400},base)
        connection=self.a._reader()
        second=self.a.candidates({'title':'Example','duration':7200},base)
        self.assertIs(connection,self.a._reader())
        self.assertEqual(len(self.a._reader_local.queries),1)
        metrics=self.a.status()['performance']
        self.assertEqual(metrics['reader_opens'],1)
        self.assertEqual((metrics['query_hits'],metrics['query_misses']),(1,1))
        self.assertTrue(first[0]['runtime_agrees'])
        self.assertTrue(second[0]['runtime_mismatch'])
    def test_atomic_replacement_invalidates_connection_and_query_cache(self):
        base={'title':'Example','kind':'movie','year':2020}
        self.assertEqual(self.a.candidates({'title':'Example'},base)[0]['reference_id'],'tt1')
        old=self.a._reader()
        replacement=self.a.root/'replacement.db'
        self._write_db(replacement,'tt2')
        os.replace(replacement,self.a.path)
        self.assertEqual(self.a.candidates({'title':'Example'},base)[0]['reference_id'],'tt2')
        self.assertIsNot(old,self.a._reader())
        with self.assertRaises(sqlite3.ProgrammingError):old.execute('SELECT 1')
    def test_two_threads_use_separate_connections(self):
        one=self.a._reader()
        output=[]
        def other():
            output.append(self.a._reader())
            output.append(self.a.candidates({'title':'Example'},{'title':'Example','kind':'movie'})[0]['reference_id'])
            self.a._reader().close()
        t=threading.Thread(target=other);t.start();t.join()
        self.assertIsNot(one,output[0]);self.assertEqual(output[1],'tt1')
    def test_preflight_does_not_touch_partial_file_when_disk_is_full(self):
        partial=self.a.root/'basics.tsv.gz.part';partial.write_bytes(b'old partial')
        class Reply(io.BytesIO):
            status=200
            headers={'Content-Length':str(8*1024**2)}
        with patch('core.open_url',return_value=Reply(b'')),patch('imdb_archive.shutil.disk_usage',return_value=SimpleNamespace(free=512*1024**2)):
            with self.assertRaisesRegex(OSError,'Speicher'):self.a.fetch('basics',self.a.root/'basics.tsv.gz')
        self.assertEqual(partial.read_bytes(),b'old partial')
        self.assertFalse((self.a.root/'basics.tsv.gz').exists())

class EpisodeNumberTests(unittest.TestCase):
    def test_explicit_season_episode_matches_complete_official_list(self):
        meta={'title':'Example','kind':'series','season':2,'episode':3,
              'episode_title':'S02E03','_source_duration':2700}
        official=[{'name':'The Pilot','season_number':2,'episode_number':3,'runtime':45}]
        c={'title':'Example','description':'','episode_verified':False,'episode_scan_complete':True}
        self.assertTrue(metadata.resolve_episode(meta,c,official)['episode_verified'])
        self.assertEqual((c['season'],c['episode']),(2,3))
        self.assertTrue(c['runtime_agrees'])
    def test_incomplete_or_ambiguous_numbering_never_verifies(self):
        meta={'title':'Example','kind':'series','season':2,'episode':3,'episode_title':'S02E03'}
        ep={'name':'The Pilot','season_number':2,'episode_number':3}
        for entries,complete in [([ep],False),([ep,dict(ep)],True),([],True)]:
            with self.subTest(n=len(entries),complete=complete):
                candidate={'title':'Example','description':'','episode_verified':False,'episode_scan_complete':complete}
                self.assertFalse(metadata.resolve_episode(meta,candidate,entries)['episode_verified'])
    def test_imdb_offline_number_fallback_requires_unique_match(self):
        with tempfile.TemporaryDirectory() as root:
            a=imdb.Archive(Path(root),threading.Event())
            with sqlite3.connect(a.path) as c:
                c.executescript("""CREATE TABLE names(name TEXT,tconst TEXT);
CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,primaryTitle TEXT,startYear INTEGER,runtimeMinutes INTEGER,genres TEXT);
CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);
CREATE TABLE title_episode(tconst TEXT PRIMARY KEY,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER);
""")
                c.execute("INSERT INTO names VALUES('example','ttshow')")
                c.execute("INSERT INTO title_basics VALUES('ttshow','tvSeries','Example',2020,45,'Drama')")
                c.execute("INSERT INTO title_basics VALUES('tt45','tvEpisode','The Pilot',2020,45,'Drama')")
                c.execute("INSERT INTO title_episode VALUES('tt45','ttshow',2,3)")
            a.updated=1;a.version=0
            meta={'kind':'series','title':'Example','season':2,'episode':3,'episode_title':'S02E03'}
            hit=a.candidates({'title':'S02E03','duration':2700},meta)[0]
            self.assertTrue(hit['episode_verified'])
            self.assertEqual((hit['episode_reference_id'],hit['episode_title']),('tt45','The Pilot'))
            assert matching.choose(meta,[hit]) is not None
            a._reader().close()

class QueueRecoveryTests(unittest.TestCase):
    def test_queued_jobs_survive_restart(self):
        import catalog
        with sqlite3.connect(':memory:') as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            states=['queued','downloading','tagging','done','error','cancelled','remote']
            c.executemany('INSERT INTO jobs VALUES(?,?,?)',[(x,'{}',x) for x in states])
            catalog.recover_download_queue(c)
            after=dict(c.execute('SELECT id,state FROM jobs'))
        self.assertEqual(after['queued'],'queued')
        self.assertEqual(after['downloading'],'interrupted')
        self.assertEqual(after['tagging'],'interrupted')
        for state in ('done','error','cancelled','remote'):
            self.assertEqual(after[state],state)

if __name__=='__main__':unittest.main()
