"""Regressions found in the 0.4.7 field diagnosis (OMDb pause, series repetition, log volume)."""
import json,sqlite3,sys,tempfile,threading,time,types,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import artwork,catalog,catalog_service,metadata
from test_instance import tree_namespace

def database(root):
 @contextmanager
 def db():
  c=sqlite3.connect(Path(root)/'catalog.db');c.row_factory=sqlite3.Row
  try:
   with c:yield c
  finally:c.close()
 return db

def series_episodes(db,count=3):
 with db() as c:
  catalog.initialize(c)
  catalog.ingest(c,[{'title':'Folge %d'%n,'topic':'Servicezeit','description':'','duration':1800,'channel':'WDR','url_video':'https://example.org/%d.mp4'%n} for n in range(count)])
  meta={'title':'Servicezeit','kind':'series','year':2010,'provider':'TVDB','reference_id':'7'}
  c.execute("UPDATE works SET kind='series',show_key='show',state='identified',meta=?",(json.dumps(meta),))
  return [r[0] for r in c.execute('SELECT id FROM works ORDER BY id')]

class RetryTests(unittest.TestCase):
 def test_paused_provider_backs_off_instead_of_hourly(self):
  deferred={'warnings':[],'deferred_providers':['OMDb']}
  self.assertEqual([catalog_service.retry_delay(n,deferred) for n in range(1,8)],[3600,7200,14400,28800,57600,86400,86400])
 def test_real_errors_still_retry_hourly(self):
  self.assertEqual(catalog_service.retry_delay(9,{'warnings':['TMDB: Zeitüberschreitung'],'deferred_providers':['OMDb']}),3600)
  self.assertEqual(catalog_service.retry_delay(1,{'warnings':[],'deferred_providers':[]}),86400)
 def test_unresolved_work_scheduled_with_backoff(self):
  with tempfile.TemporaryDirectory() as root:
   db=database(root)
   with db() as c:
    catalog.initialize(c);c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)');catalog.ingest(c,[{'title':'Unbekannt','topic':'Unbekannt','description':'Spielfilm','duration':5400,'channel':'ARD','url_video':'https://example.org/a.mp4'}])
    c.execute("UPDATE works SET kind='movie',state='retry',attempts=3")
   service=catalog_service.Service(db,lambda:{'tmdb':'k','omdb':'o'},threading.Event(),Path(root))
   with patch('core.candidates',return_value={'candidates':[],'warnings':[],'deferred_providers':['OMDb'],'provider_checks':[]}):
    before=time.time();self.assertTrue(service.metadata_once())
   with db() as c:row=c.execute('SELECT state,next_try,attempts FROM works').fetchone()
   self.assertEqual(row['state'],'retry');self.assertEqual(row['attempts'],4);self.assertGreaterEqual(row['next_try']-before,8*3600-5)

class LogTests(unittest.TestCase):
 def setUp(self):metadata._OMDB_PAUSED.clear();metadata._CACHE.clear()
 def test_one_event_per_provider_check_with_duration(self):
  with patch('metadata.tmdb_candidates',return_value=[]),patch('metadata.wikidata',return_value=None),patch('diagnostics.event') as log:
   metadata.candidates({'title':'Film'},{'kind':'movie','title':'Film'},{'tmdb':'k'})
  events=[(c.args[0],c.kwargs) for c in log.call_args_list]
  self.assertNotIn('provider_start',[e for e,_ in events])
  done=[k for e,k in events if e=='provider_complete']
  self.assertEqual([k['provider'] for k in done],['TMDB','Wikidata']);self.assertTrue(all('seconds' in k for k in done))
 def test_access_error_is_warning(self):
  import io,urllib.error
  failure=urllib.error.HTTPError('https://www.omdbapi.com/',401,'Unauthorized',{},io.BytesIO(b'{"Response":"False","Error":"Request limit reached!"}'))
  with patch('core.open_url',side_effect=failure),patch('diagnostics.event') as log:metadata.test_omdb('PRIVATE')
  access=[c for c in log.call_args_list if c.args[0]=='provider_access_error'][0]
  self.assertEqual(access.args[1],'WARNING');self.assertEqual(access.kwargs['reason'],'limit')

class SeriesTests(unittest.TestCase):
 def test_propagation_skips_unchanged_siblings(self):
  with tempfile.TemporaryDirectory() as root:
   db=database(root);series_episodes(db)
   with db() as c,patch('catalog.save_metadata') as save:
    catalog.propagate_series(c,'show',{'title':'Servicezeit','kind':'series','year':2010,'provider':'TVDB','reference_id':'7'})
    save.assert_not_called()
    catalog.propagate_series(c,'show',{'title':'Servicezeit','kind':'series','year':2010,'provider':'TVDB','reference_id':'8'})
    self.assertEqual(save.call_count,3)
 def test_artwork_lookup_shared_by_episodes(self):
  with tempfile.TemporaryDirectory() as root:
   db=database(root);ids=series_episodes(db)
   service=catalog_service.Service(db,lambda:{'tvdb':'k'},threading.Event(),Path(root))
   found={'poster':'https://artworks.thetvdb.com/p.jpg','fanart':'https://artworks.thetvdb.com/f.jpg','artwork_provider':'TVDB'}
   with patch('artwork.lookup',return_value=(found,[])) as lookup,patch('diagnostics.event') as log:
    self.assertTrue(artwork.run_once(service));self.assertFalse(artwork.run_once(service))
   lookup.assert_called_once();self.assertEqual(service.artwork_checked,3)
   self.assertEqual(log.call_args.kwargs['shared'],2)
   with db() as c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM artwork_checks WHERE next_try>?',(time.time(),)).fetchone()[0],3)
    self.assertTrue(all(json.loads(r[0])['fanart']==found['fanart'] for r in c.execute('SELECT meta FROM works')))
 def test_errors_are_not_shared(self):
  with tempfile.TemporaryDirectory() as root:
   db=database(root);series_episodes(db)
   service=catalog_service.Service(db,lambda:{'tvdb':'k'},threading.Event(),Path(root))
   with patch('artwork.lookup',return_value=({},['TVDB: Zeitüberschreitung'])):self.assertTrue(artwork.run_once(service))
   with db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM artwork_checks').fetchone()[0],1)

class QueueTests(unittest.TestCase):
 def test_queue_pauses_only_when_idle(self):
  stop=threading.Event();service=catalog_service.Service(None,dict,stop,Path('.'));waits=[];results=iter([True,True,False])
  def once():
   try:return next(results)
   except StopIteration:stop.set();return False
  class Wake:
   def wait(self,seconds):waits.append(seconds)
   def clear(self):pass
  service.metadata_once=once;service.metadata_wake=Wake();service.metadata_loop()
  self.assertEqual(waits[:3],[catalog_service.METADATA_PAUSE,catalog_service.METADATA_PAUSE,2]);self.assertLess(catalog_service.METADATA_PAUSE,.5)

class TreeTtlTests(unittest.TestCase):
 def test_slow_tree_refreshes_less_often(self):
  clock=types.SimpleNamespace(now=100.0);clock.monotonic=lambda:clock.now
  def tree(c):clock.now+=4;return [{'kind':'movie','genre':'Drama','n':1}]
  ns=tree_namespace(tree,clock)
  ns['refresh_tree']();self.assertEqual(ns['_TREE_TTL'],240)
  clock.now+=120;self.assertFalse(ns['catalog_tree']()['loading'])
  clock.now+=121;self.assertTrue(ns['catalog_tree']()['loading'])
if __name__=='__main__':unittest.main()
