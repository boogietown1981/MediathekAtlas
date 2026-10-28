import gzip,io,json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import imdb_archive as imdb,metadata,core

class ArchiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=imdb.Archive(self.root,threading.Event());self.files={}
  rows={
   'basics':['tt1\ttvSeries\tExample Show\tExample Show\t0\t2020\t\\N\t25\tAnimation,Family','tt2\ttvEpisode\tBeginning\tBeginning\t0\t2020\t\\N\t25\tFamily','tt3\tmovie\tFilm\tFilm\t0\t1999\t\\N\t90\tDrama'],
   'ratings':['tt1\t8.1\t100','tt3\t7.5\t40'],
   'episode':['tt2\ttt1\t2\t3'],
   'akas':['tt1\t1\tBeispielserie\tDE\tde\t\\N\t\\N\t0','tt2\t1\tDer Anfang\tDE\tde\t\\N\t\\N\t0']}
  rows.update(crew=['tt2\tnm1\tnm1'],principals=['tt2\t1\tnm1\tactor\t\\N\t["Figur"]'],people=['nm1\tPerson Eins\t1980\t\\N\tactor\ttt2'])
  for k in imdb.HEADERS:
   p=self.root/(k+'.gz');p.write_bytes(gzip.compress(('\t'.join(imdb.HEADERS[k])+'\n'+'\n'.join(rows[k])+'\n').encode()));self.files[k]=p
 def tearDown(self):self.tmp.cleanup()
 def build(self):
  imdb.build(self.a.path,self.files);self.a=imdb.Archive(self.root,threading.Event())
 def test_import_alias_episode_rating_nulls(self):
  self.build();m=self.a.candidates({'title':'Der Anfang'},{'kind':'series','title':'Beispielserie'})[0]
  self.assertEqual((m['season'],m['episode']),(2,3));self.assertTrue(m['episode_verified']);self.assertEqual(m['episode_reference_id'],'tt2');self.assertEqual(m['rating'],8.1)
  with sqlite3.connect(self.a.path) as c:self.assertIsNone(c.execute("SELECT endYear FROM title_basics WHERE tconst='tt1'").fetchone()[0])
  self.assertIn(b'>tt2<',core.nfo(m,[],1500));self.assertIn(b'>tt1<',core.show_nfo(m))
 def test_conflicting_number_not_verified(self):
  self.build();m=self.a.candidates({'title':'Der Anfang'},{'kind':'series','title':'Beispielserie','season':1,'episode':3})[0]
  self.assertFalse(m['episode_verified']);self.assertIsNone(m['season'])
 def test_unknown_episode_not_invented(self):
  self.build();m=self.a.candidates({'title':'Unknown'},{'kind':'series','title':'Beispielserie'})[0]
  self.assertFalse(m['episode_verified']);self.assertIsNone(m['episode'])
 def test_movie_year_and_runtime(self):
  self.build();m=self.a.candidates({'title':'Film','duration':5400},{'kind':'movie','title':'Film','year':2001})[0]
  self.assertTrue(m['year_mismatch']);self.assertTrue(m['runtime_agrees'])
 def test_failed_update_keeps_previous_and_cleans(self):
  self.build();old=self.a.path.read_bytes()
  with patch('core.open_url',side_effect=OSError('offline')):self.a.update()
  self.assertEqual(old,self.a.path.read_bytes());self.assertTrue(self.a.status()['ready']);self.assertGreater(self.a.retry_at,0);self.assertFalse((self.a.root/'building.db').exists())
 def test_successful_update_and_callback(self):
  events=[];self.a.on_update=lambda:events.append('done')
  class Response(io.BytesIO):
   def __init__(self,b):super().__init__(b);self.headers={'Content-Length':str(len(b))}
  def open_url(url):return Response(self.files[next(k for k,v in imdb.FILES.items() if url.endswith(v))].read_bytes())
  with patch('core.open_url',side_effect=open_url):self.a.update()
  self.assertEqual(self.a.status()['phase'],'ready');self.assertEqual(events,['done']);self.assertAlmostEqual(self.a.status()['next_update']-self.a.updated,imdb.WEEK)
  self.assertFalse(list(self.a.root.glob('*.gz')))
 def test_local_verified_match_skips_network(self):
  self.build()
  with patch.object(imdb,'ACTIVE',self.a),patch('metadata.tmdb_candidates',side_effect=AssertionError('network')):
   d=metadata.candidates({'title':'Der Anfang'},{'title':'Beispielserie','kind':'series'},{'tmdb':'key'})
  self.assertEqual(d['candidates'][0]['provider'],'IMDb Offline');self.assertFalse(d['warnings'])
 def test_bad_header_and_truncated_gzip_rejected(self):
  self.files['basics'].write_bytes(gzip.compress(b'bad\n'))
  with self.assertRaises(ValueError):imdb.build(self.root/'bad.db',self.files)

 def test_weekly_due_persists_across_restart(self):
  self.build();self.assertFalse(self.a.due(self.a.updated+imdb.WEEK-1));self.assertTrue(self.a.due(self.a.updated+imdb.WEEK))
  loaded=imdb.Archive(self.root,threading.Event());self.assertEqual(loaded.updated,self.a.updated)
  loaded.retry_at=loaded.updated+imdb.WEEK+3600;self.assertFalse(loaded.due(loaded.updated+imdb.WEEK))
 def test_manual_request_and_busy_deduplication(self):
  self.assertTrue(self.a.request());self.assertTrue(self.a.wake.is_set());self.a.wake.clear()
  self.a.progress(phase='importing');self.assertFalse(self.a.request());self.assertFalse(self.a.wake.is_set())
 def test_omdb_and_local_identity_are_same(self):
  import catalog
  m={'provider':'OMDb','reference_id':'tt1','kind':'series','season':2,'episode':3,'episode_verified':True}
  self.assertEqual(catalog.canonical(m),catalog.canonical({**m,'provider':'IMDb Offline'}))
 def test_truncated_gzip_rejected(self):
  self.files['basics'].write_bytes(self.files['basics'].read_bytes()[:-10])
  with self.assertRaises(EOFError):imdb.build(self.root/'truncated.db',self.files)

 def test_failed_import_never_replaces_live_database(self):
  self.build();old=self.a.path.read_bytes()
  self.files['ratings'].write_bytes(gzip.compress(b'wrong header\n'))
  class Response(io.BytesIO):
   def __init__(self,b):super().__init__(b);self.headers={'Content-Length':str(len(b))}
  def open_url(url):return Response(self.files[next(k for k,v in imdb.FILES.items() if url.endswith(v))].read_bytes())
  with patch('core.open_url',side_effect=open_url):self.a.update()
  self.assertEqual(self.a.path.read_bytes(),old);self.assertEqual(self.a.status()['phase'],'error')
  self.assertFalse((self.a.root/'building.db').exists())
 def test_cancelled_update_keeps_live_database(self):
  self.build();old=self.a.path.read_bytes();self.a.stop.set()
  with patch('core.open_url',side_effect=AssertionError('Must not download')):self.a.update()
  self.assertEqual(self.a.path.read_bytes(),old)
 def test_people_crew_and_cast_export(self):
  self.build();m=self.a.candidates({'title':'Der Anfang'},{'kind':'series','title':'Beispielserie'})[0]
  self.assertEqual(m['directors'],['Person Eins']);self.assertEqual(m['cast'][0]['role'],'Figur')
  self.assertIn(b'<director>Person Eins</director>',core.nfo(m,[],1500))
 def test_all_international_aliases_stored(self):
  with gzip.open(self.files['akas'],'at') as f:f.write('tt1\t2\tTitre Francais\tFR\tfr\t\\N\t\\N\t0\n')
  self.build();self.assertEqual(self.a.candidates({'title':'Unknown'},{'kind':'series','title':'Titre Francais'})[0]['reference_id'],'tt1')
  with sqlite3.connect(self.a.path) as c:self.assertEqual(c.execute("SELECT region FROM title_akas WHERE title='Titre Francais'").fetchone()[0],'FR')
 def test_old_archive_due_for_upgrade_and_stays_readable(self):
  self.build()
  with sqlite3.connect(self.a.path) as c:c.execute('PRAGMA user_version=0')
  a=imdb.Archive(self.root,threading.Event());self.assertTrue(a.due());self.assertTrue(a.candidates({'title':'Film'},{'kind':'movie','title':'Film'}))
