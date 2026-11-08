"""Regression: IMDb dataset inventory persists across app restarts without a huge COUNT scan."""
import gzip,os,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
import imdb_archive as imdb

class ImdbDatasetManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.archive=imdb.Archive(self.root,threading.Event())
        rows={
            'basics':['tt1\tmovie\tFilm A\tFilm A\t0\t2022\t\\N\t90\tDrama'],
            'ratings':['tt1\t8.1\t123'],
            'episode':['tt2\tt1\t1\t1'],
            'akas':['tt1\t1\tFilm A DE\tDE\tde\t\\N\t\\N\t0'],
            'crew':['tt1\tnm1\tnm1'],
            'principals':['tt1\t1\tnm1\tactor\t\\N\t["Figur"]'],
            'people':['nm1\tSchauspieler Eins\t1980\t\\N\tactor\ttt1']
        }
        self.files={}
        for index,kind in enumerate(imdb.HEADERS):
            path=self.root/(kind+'.tsv.gz')
            path.write_bytes(gzip.compress(('\t'.join(imdb.HEADERS[kind])+'\n'+'\n'.join(rows[kind])+'\n').encode()))
            os.utime(path,(1738000000+index,1738000000+index))
            self.files[kind]=path
    def test_snapshot_retains_every_dataset_rowcount_and_retrieval_date(self):
        expected={k:self.files[k].stat().st_mtime for k in self.files}
        counts=imdb.build(self.archive.path,self.files)
        self.assertEqual(len(counts),7)
        first=imdb.Archive(self.root,threading.Event()).status()
        self.assertTrue(first['ready'])
        self.assertEqual(first['archive_version'],imdb.VERSION)
        self.assertGreater(first['archive_bytes'],0)
        self.assertEqual(len(first['datasets']),7)
        self.assertEqual({row['key'] for row in first['datasets']},set(imdb.HEADERS))
        for row in first['datasets']:
            self.assertTrue(row['available'])
            self.assertEqual(row['rows'],counts[row['key']])
            self.assertAlmostEqual(row['retrieved_at'],expected[row['key']],delta=0.01)
            self.assertTrue(row['file'].endswith('.tsv.gz'))
        second=imdb.Archive(self.root,threading.Event()).status()
        self.assertEqual(second['datasets'],first['datasets'])
        self.assertEqual(second['updated'],first['updated'])
    def test_failed_refresh_never_changes_last_successful_manifest(self):
        imdb.build(self.archive.path,self.files)
        archive=imdb.Archive(self.root,threading.Event())
        before=archive.status()
        archive.progress(phase='error',error='Kein Speicherplatz')
        after=archive.status()
        self.assertEqual(after['updated'],before['updated'])
        self.assertEqual(after['datasets'],before['datasets'])
        self.assertEqual(after['phase'],'error')
        self.assertTrue(after['ready'])
    def test_old_archive_without_manifest_remains_usable(self):
        with sqlite3.connect(self.archive.path) as c:
            c.execute('CREATE TABLE snapshot(updated REAL)')
            c.execute('INSERT INTO snapshot VALUES(?)',(time.time()-3600,))
            c.execute('CREATE TABLE title_basics(tconst TEXT)')
            c.execute('CREATE TABLE title_ratings(tconst TEXT)')
            c.execute('PRAGMA user_version=2')
        result=imdb.Archive(self.root,threading.Event()).status()
        self.assertTrue(result['ready'])
        self.assertEqual(len(result['datasets']),7)
        basic=next(x for x in result['datasets'] if x['key']=='basics')
        self.assertTrue(basic['available'])
        self.assertIsNone(basic['rows'])
        self.assertIsNone(basic['retrieved_at'])
        episodes=next(x for x in result['datasets'] if x['key']=='episode')
        self.assertFalse(episodes['available'])
    def test_unbuilt_archive_advertises_expected_datasets_without_fake_counts(self):
        status=self.archive.status()
        self.assertFalse(status['ready'])
        self.assertEqual(status['updated'],0)
        self.assertEqual(len(status['datasets']),7)
        self.assertTrue(all(not x['available'] and x['rows'] is None for x in status['datasets']))

if __name__=='__main__':unittest.main()
