"""0.5.22: user scheduling, first-pass ETA, conservative offer grouping and durable misses."""
import json,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import catalog,catalog_service,metadata,negative_cache,provider_stats

def film(title='Movie',channel='ARD',url='https://example.org/movie.mp4'):
    return {'title':title,'topic':'Spielfilm','description':'Spielfilm Deutschland 2020 · Testinhalt',
            'duration':6600,'channel':channel,'url_video':url,
            'url_video_hd':'https://example.org/movie-hd.mp4'}

def episode(num=1,channel='ARD'):
    return {'title':'Episode S01E%02d'%num,'topic':'Beispielserie','description':'Fernsehserie',
            'duration':2200,'channel':channel,'url_video':'https://example.org/ep-%02d.mp4'%num}

class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
        catalog.ingest(self.c,[film(),episode(1),episode(2)])
        self.stop=threading.Event()
    def tearDown(self):self.c.close()
    def service(self,**kw):
        return catalog_service.Service(None,lambda:{'scan_priority':'balanced','complete_series':True,**kw},self.stop,Path('.'))
    def test_user_can_prioritize_film_or_series(self):
        self.assertEqual(self.service(scan_priority='movies_first').pick(self.c)['kind'],'movie')
        self.assertEqual(self.service(scan_priority='series_first').pick(self.c)['kind'],'series')
    def test_focus_selects_sibling_only_in_bounded_window(self):
        show=self.c.execute("SELECT show_key FROM works WHERE kind='series' LIMIT 1").fetchone()[0]
        self.assertTrue(catalog.focus_series(self.c,show,limit=2))
        self.assertFalse(catalog.focus_series(self.c,show,limit=2))
        chosen=self.service().pick(self.c)
        self.assertEqual(chosen['kind'],'series')
        catalog.focus_take(self.c,show)
        catalog.focus_take(self.c,show)
        self.assertEqual(self.c.execute('SELECT remaining FROM series_focus').fetchone()[0],0)
        self.assertEqual(self.service(scan_priority='movies_first').pick(self.c)['kind'],'movie')
    def test_manual_priority_overrides_scan_order(self):
        item=self.c.execute("SELECT id FROM works WHERE kind='series' LIMIT 1").fetchone()[0]
        self.c.execute('INSERT INTO metadata_priority VALUES(?,?)',(item,time.time()))
        self.assertEqual(self.service(scan_priority='movies_first').pick(self.c)['id'],item)
    def test_first_pass_before_due_retries_and_kind_fairness(self):
        self.c.execute("UPDATE works SET attempts=7,state='retry' WHERE kind='movie'")
        self.assertEqual(self.service(scan_priority='movies_first').pick(self.c)['kind'],'series')
    def test_persisted_attempts_remain_after_canonical_merge(self):
        self.c.execute("UPDATE works SET attempts=5 WHERE kind='movie'")
        row=self.c.execute("SELECT * FROM works WHERE kind='movie'").fetchone()
        meta=json.loads(row['meta']);meta.update(kind='movie',provider='TMDB',reference_id='42',year=2020,genres=['Drama'])
        dest=catalog.save_metadata(self.c,row['id'],meta,'matched')
        self.assertEqual(self.c.execute('SELECT attempts FROM works WHERE id=?',(dest,)).fetchone()[0],5)
    def test_first_pass_rate_uses_unique_new_checks_not_total(self):
        svc=self.service();svc.started_at=time.monotonic()-120
        for _ in range(20):svc.record_check(True)
        for _ in range(60):svc.record_check(False)
        self.assertEqual(svc.scan_progress()['first_pass_session'],20)
        self.assertEqual(svc.scan_progress()['repeat_session'],60)
        self.assertAlmostEqual(svc.scan_rate(),10,delta=.1)
    def test_no_activity_has_no_fabricated_eta(self):
        self.assertEqual(self.service().scan_rate(),0)

class OfferGroupingTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
    def tearDown(self):self.c.close()
    def test_same_media_different_feed_titles_group_without_deleting(self):
        a=film('Der Rausch');b=film('Der Rausch (HD)')
        self.c.execute('BEGIN')
        catalog.ingest(self.c,[a,b])
        wid=self.c.execute('SELECT work_id FROM offers LIMIT 1').fetchone()[0]
        found=catalog.alternatives(self.c,wid)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['same_media_count'],2)
        self.assertEqual(len(found[0]['offer_ids']),2)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers').fetchone()[0],2)
    def test_audio_description_and_distinct_file_are_retained(self):
        a=film('Der Rausch');b=film('Der Rausch (Audiodeskription)')
        c={**film('Der Rausch (HD)'),'url_video':'https://example.org/different.mp4'}
        catalog.ingest(self.c,[a,b,c])
        wid=self.c.execute('SELECT work_id FROM offers LIMIT 1').fetchone()[0]
        found=catalog.alternatives(self.c,wid)
        self.assertEqual(len(found),3)
        self.assertTrue(any(a['special']=='Audiodeskription' for a in found))
    def test_signed_url_difference_is_not_treated_as_identical(self):
        a=film('Der Rausch',url='https://example.org/file.mp4?token=1')
        b=film('Der Rausch (HD)',url='https://example.org/file.mp4?token=2')
        self.assertNotEqual(catalog.media_equivalence_key(a,'',True),catalog.media_equivalence_key(b,'',True))

class NegativeCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_path=negative_cache._PATH
        negative_cache.configure(Path(self.tmp.name)/'misses.sqlite')
    def tearDown(self):
        c=getattr(negative_cache._LOCAL,'connection',None)
        if c:c.close();del negative_cache._LOCAL.connection
        negative_cache._PATH=self.old_path
        self.tmp.cleanup()
    def test_persistent_positive_miss_only_and_force(self):
        negative_cache.remember('TMDB','movie','A title',year=2020,credential='key')
        self.assertTrue(negative_cache.contains('TMDB','movie','A title',2020,'key'))
        self.assertFalse(negative_cache.contains('TMDB','movie','A title',2021,'key'))
        self.assertFalse(negative_cache.contains('TMDB','movie','A title',2020,'different'))
        self.assertFalse(negative_cache.contains('TMDB','movie','A title',2020,'key',force=True))
        # Close and reload to ensure records survive a simulated restart.
        c=getattr(negative_cache._LOCAL,'connection',None)
        if c:c.close();del negative_cache._LOCAL.connection
        negative_cache.configure(Path(self.tmp.name)/'misses.sqlite')
        self.assertTrue(negative_cache.contains('TMDB','movie','A title',2020,'key'))
    def test_successful_empty_lookup_avoids_second_provider_request(self):
        row={'title':'Unlisted Example Alpha 0522','topic':'Spielfilm','duration':5400}
        m={'kind':'movie','title':row['title']}
        with patch('metadata.tmdb_candidates',return_value=[]) as tmdb,patch('metadata.wikidata',return_value=None):
            metadata.candidates(row,m,{'tmdb':'credential-x'})
            metadata.candidates(row,m,{'tmdb':'credential-x'})
            self.assertEqual(tmdb.call_count,1)
            metadata.candidates(row,m,{'tmdb':'credential-x','_force_provider_refresh':True})
            self.assertEqual(tmdb.call_count,2)
    def test_provider_error_is_not_remembered(self):
        row={'title':'Unlisted Example Beta 0522','topic':'Spielfilm','duration':5400}
        m={'kind':'movie','title':row['title']}
        with patch('metadata.tmdb_candidates',side_effect=TimeoutError('offline')) as tmdb,patch('metadata.wikidata',return_value=None):
            metadata.candidates(row,m,{'tmdb':'credential-z'})
            metadata.candidates(row,m,{'tmdb':'credential-z'})
            self.assertEqual(tmdb.call_count,2)

if __name__=='__main__':unittest.main()
