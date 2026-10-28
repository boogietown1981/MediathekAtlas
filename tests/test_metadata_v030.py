import unittest,sys,sqlite3,json,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core,catalog,metadata,series_download,catalog_service

def source(title='Eine tierische Freundschaft'):
 return {'title':title,'topic':'Bibi und Tina','description':'Bibi und Tina helfen ihren Freunden.','channel':'ZDF','duration':1509,'url_video':'https://example.org/'+title+'.mp4'}
class ProviderTests(unittest.TestCase):
 def test_bibi_episode_without_number_resolved(self):
  row=source();m=catalog.seed(row)
  def tmdb(path,*args):
   if path=='search/tv':return {'results':[{'id':1,'name':'Bibi und Tina'}]}
   if path=='tv/1':return {'id':1,'name':'Bibi und Tina','first_air_date':'2004-07-03','genres':[{'name':'Animation'},{'name':'Kids'}],'seasons':[{'season_number':2}]}
   return {'episodes':[{'name':row['title'],'season_number':2,'episode_number':8}]}
  with patch('core.tmdb',side_effect=tmdb):result=metadata.tmdb_candidates(row,m,'test','series',row['topic'])
  self.assertTrue(result[0]['episode_verified']);self.assertEqual((result[0]['season'],result[0]['episode']),(2,8));self.assertIn('Kinder & Familie',result[0]['genres']);self.assertIsNotNone(catalog.auto_choice(m,result))
 def test_duplicate_episode_names_not_guessed(self):
  m={'episode_title':'Anfang'};c={'title':'Serie','description':''}
  out=metadata.resolve_episode(m,c,[{'name':'Anfang','season_number':1,'episode_number':1},{'name':'Anfang','season_number':2,'episode_number':1}]);self.assertFalse(out.get('episode_verified'))
 def test_number_conflict_not_silently_overwritten(self):
  out=metadata.resolve_episode({'episode_title':'Anfang','season':1,'episode':2},{'title':'Serie','description':''},[{'name':'Anfang','season_number':1,'episode_number':1}]);self.assertFalse(out.get('episode_verified'))
 def test_omdb_preserves_genre_runtime_plot(self):
  m={'title':'Ein Film','kind':'movie','year':2020,'description':''}
  with patch('metadata.omdb',return_value={'Title':'Ein Film','Type':'movie','Year':'2020','Runtime':'90 min','Genre':'Comedy, Family','Plot':'Handlung','imdbID':'tt1234567'}):r=metadata.omdb_candidates({'duration':5400},m,'key','movie','Ein Film')[0]
  self.assertEqual(r['description'],'Handlung');self.assertTrue(r['runtime_agrees']);self.assertEqual(r['genres'],['Kinder & Familie','Komödie']);self.assertIsNotNone(catalog.auto_choice(m,[r]))
 def test_clip_mentioning_film_not_a_movie(self):
  m=catalog.seed({'title':'Filmtricks','topic':'Wissen','description':'Heute schauen wir, wie der Film gemacht wird.','duration':120});self.assertEqual(m['kind'],'unknown')
 def test_series_identity_not_episode_confirmation(self):
  c={'kind':'series','title':'Serie','provider':'TMDB','reference_id':'12','similarity':1}
  self.assertIsNone(catalog.auto_choice({'kind':'series'},[c]));self.assertEqual(catalog.work_choice({'kind':'series'},[c]),c)
class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;catalog.initialize(self.c);self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
 def tearDown(self):self.c.close()
 def test_assignment_filter_includes_unclassified_works(self):
  catalog.ingest(self.c,[{'title':'Kurzer unbekannter Beitrag','topic':'','description':'','duration':90,'channel':'ARD','url_video':'https://example.org/clip.mp4'}])
  self.assertEqual(catalog.listing(self.c)['total'],0)
  self.assertEqual(catalog.listing(self.c,state='pending')['total'],1)
  self.assertEqual(catalog.listing(self.c,state='pending',kind='movie')['total'],0)

 def test_new_episode_reuses_recognized_series_template(self):
  template={'title':'Bibi und Tina','year':2004,'provider':'TMDB','reference_id':'1','poster':'','genres':['Animation'],'genre_source':'TMDB'}
  self.c.execute('INSERT INTO series_templates VALUES(?,?,?,?)',(catalog.key('Bibi und Tina'),'TMDB','1',json.dumps(template)))
  catalog.ingest(self.c,[source()]);w=self.c.execute('SELECT * FROM works').fetchone();self.assertEqual(w['kind'],'series');self.assertEqual(w['state'],'identified');self.assertIsNone(json.loads(w['meta'])['season'])
 def test_search_by_series_topic_before_identification(self):
  catalog.ingest(self.c,[source()]);self.assertEqual(catalog.listing(self.c,query='Bibi')['total'],1)
 def test_reclassify_preserves_manual(self):
  catalog.ingest(self.c,[source()]);w=self.c.execute('SELECT * FROM works').fetchone();m=json.loads(w['meta']);m.update(title='Meine Serie',kind='series');catalog.save_metadata(self.c,w['id'],m);catalog.reclassify_batch(self.c);self.assertEqual(self.c.execute('SELECT title FROM works').fetchone()[0],'Meine Serie')
 def add_episode(self,title,ep,state='matched'):
  catalog.ingest(self.c,[source(title)]);w=self.c.execute('SELECT * FROM works WHERE title=?',(title,)).fetchone();m=json.loads(w['meta']);m.update(title='Bibi und Tina',kind='series',year=2004,season=2,episode=ep,episode_title=title,episode_verified=state=='matched',provider='TMDB',reference_id='1');catalog.save_metadata(self.c,w['id'],m,state);return catalog.showkey(m)
 def test_batch_one_best_offer_per_episode_and_skip_unknown(self):
  show=self.add_episode('Folge A',1);self.add_episode('Folge B',2,'identified')
  with tempfile.TemporaryDirectory() as root:
   p=series_download.plan(self.c,show,root);self.assertEqual(len(p['eligible']),1);self.assertEqual(len(p['skipped']),1)
   series_download.enqueue(self.c,show,root,p['fingerprint']);self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
   p2=series_download.plan(self.c,show,root);self.assertFalse(p2['eligible'])
 def test_batch_rejects_changed_preview(self):
  show=self.add_episode('Folge A',1)
  with tempfile.TemporaryDirectory() as root:
   p=series_download.plan(self.c,show,root);self.add_episode('Folge B',2)
   with self.assertRaises(ValueError):series_download.enqueue(self.c,show,root,p['fingerprint'])
   self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
 def test_batch_selects_only_requested_episode(self):
  show=self.add_episode('Folge A',1);self.add_episode('Folge B',2)
  with tempfile.TemporaryDirectory() as root:
   p=series_download.plan(self.c,show,root)
   for ids in ([],['unknown']):
    with self.assertRaises(ValueError):series_download.enqueue(self.c,show,root,p['fingerprint'],ids)
   self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
   result=series_download.enqueue(self.c,show,root,p['fingerprint'],[p['eligible'][1]['id']])
   self.assertEqual(result['queued'],1)
   job=json.loads(self.c.execute('SELECT payload FROM jobs').fetchone()[0]);self.assertEqual(job['metadata']['episode'],2)
 def test_legacy_schema_migrates(self):
  self.c.execute('DROP TABLE works');self.c.execute("CREATE TABLE works(id TEXT PRIMARY KEY,title TEXT,kind TEXT,year INTEGER,show_key TEXT,meta TEXT,state TEXT,next_try REAL,attempts INTEGER,updated REAL)");catalog.initialize(self.c);self.assertIn('topic',[r[1] for r in self.c.execute('PRAGMA table_info(works)')])
class QueueTests(unittest.TestCase):
 def test_recognized_series_propagates_without_copying_episode(self):
  with tempfile.TemporaryDirectory() as root:
   def db():
    c=sqlite3.connect(Path(root)/'c.db');c.row_factory=sqlite3.Row;return c
   with db() as c:
    catalog.initialize(c);c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)');catalog.ingest(c,[source('Anfang'),source('Weiter')])
   s=catalog_service.Service(db,lambda:{'auto_metadata':True},threading.Event(),Path(root))
   def lookup(row,m,settings):return {'candidates':[{**m,'title':'Bibi und Tina','kind':'series','year':2004,'provider':'TMDB','reference_id':'1','similarity':1,'episode_verified':True,'season':1,'episode':1,'episode_title':row['title'],'genres':['Animation']}],'warnings':[]}
   with patch('core.candidates',side_effect=lookup):s.metadata_once()
   with db() as c:
    data=catalog.listing(c);self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['episodes'],2)
    pending=c.execute("SELECT meta FROM works WHERE state='identified'").fetchone();self.assertIsNotNone(pending);self.assertIsNone(json.loads(pending[0])['episode'])
 def test_series_not_starved_by_movies(self):
  with tempfile.TemporaryDirectory() as root:
   def db():
    c=sqlite3.connect(Path(root)/'c.db');c.row_factory=sqlite3.Row;return c
   with db() as c:
    catalog.initialize(c);c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
    for n in range(4):catalog.ingest(c,[{**source('Film '+str(n)),'topic':'Film','description':'Spielfilm Deutschland 2020'}])
    catalog.ingest(c,[{**source('Anfang S01E01'),'topic':'Serie'}])
   s=catalog_service.Service(db,lambda:{'auto_metadata':True},threading.Event(),Path(root));kinds=[]
   def candidates(row,m,settings):kinds.append(m['kind']);return {'candidates':[],'warnings':[]}
   with patch('core.candidates',side_effect=candidates):s.metadata_once();s.metadata_once()
   self.assertEqual(kinds,['movie','series']);self.assertEqual(s.metadata_status['checked_session'],2)
if __name__=='__main__':unittest.main()
