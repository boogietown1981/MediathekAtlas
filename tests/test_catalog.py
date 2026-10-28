import unittest,sqlite3,sys,io,json,lzma,tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog,filmlist,catalog_service

def row(title='Beispiel',channel='ARD',year=2020,hd=True):
 return {'title':title,'topic':'Film','channel':channel,'description':'Spielfilm Deutschland '+str(year)+' Eine ausführliche Beispielhandlung für die sichere Zuordnung der Titel.','duration':5400,'url_video':'https://example.org/'+channel+'/'+title+'.mp4','url_video_hd':'https://example.org/'+channel+'/'+title+'-1080p.mp4' if hd else ''}
class CatalogTests(unittest.TestCase):
 def setUp(self):self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.executescript(catalog.SCHEMA)
 def tearDown(self):self.c.close()
 def test_multiple_broadcasters_one_film(self):
  catalog.ingest(self.c,[row(),row(channel='ZDF')]);d=catalog.listing(self.c);self.assertEqual(d['total'],1);self.assertEqual(d['items'][0]['offer_count'],2)
 def test_regular_preferred_over_ad(self):
  catalog.ingest(self.c,[row(hd=False),row('Beispiel (Audiodeskription)','ZDF')]);d=catalog.listing(self.c);self.assertEqual(d['total'],1);self.assertEqual(d['items'][0]['source']['channel'],'ARD');self.assertEqual(len(catalog.alternatives(self.c,d['items'][0]['work_id'])),2)
 def test_hd_preferred(self):
  catalog.ingest(self.c,[row(hd=False),row(channel='ZDF')]);self.assertEqual(catalog.listing(self.c)['items'][0]['source']['channel'],'ZDF')
 def test_remakes_separate(self):
  catalog.ingest(self.c,[row(year=1980),row(year=2020,channel='ZDF')]);self.assertEqual(catalog.listing(self.c)['total'],2)
 def test_title_alone_does_not_merge(self):
  a=row();b=row(channel='ZDF');a['description']='Eine lange Geschichte über Wale, Schiffe und den Ozean.';b['description']='Eine lange Geschichte über Berge, Wanderer und das Klettern.'
  catalog.ingest(self.c,[a,b]);self.assertEqual(catalog.listing(self.c,kind='unknown')['total'],2)
 def test_series_group_and_episodes(self):
  a=row('Start (S01/E01)');b=row('Weiter S01E02');a['topic']=b['topic']='Beispielserie';catalog.ingest(self.c,[a,b]);d=catalog.listing(self.c);self.assertEqual(d['total'],1);self.assertEqual(d['items'][0]['episodes'],2);self.assertEqual(catalog.listing(self.c,show=d['items'][0]['show_key'])['total'],2)
 def test_manual_metadata_survives_import(self):
  catalog.ingest(self.c,[row()]);w=catalog.listing(self.c)['items'][0];m={**w['metadata'],'title':'Korrigiert','provider':'TMDB','reference_id':'42','genres':['Drama']};catalog.save_metadata(self.c,w['work_id'],m);catalog.ingest(self.c,[row()]);d=catalog.listing(self.c);self.assertEqual(d['total'],1);self.assertEqual(d['items'][0]['metadata']['title'],'Korrigiert');self.assertEqual(d['items'][0]['state'],'manual')
 def test_provider_merge(self):
  catalog.ingest(self.c,[row(),row(year=2021,channel='ZDF')]);items=catalog.listing(self.c)['items'];self.assertEqual(len(items),2)
  for w in items:catalog.save_metadata(self.c,w['work_id'],{**w['metadata'],'provider':'TMDB','reference_id':'42','year':2020})
  self.assertEqual(catalog.listing(self.c)['total'],1)
 def test_archived_preserved(self):
  catalog.ingest(self.c,[row()]);self.c.execute('UPDATE offers SET active=0');self.assertEqual(catalog.listing(self.c)['total'],0);self.assertEqual(catalog.listing(self.c,archive=True)['total'],1)
 def test_tree_and_genre(self):
  a=row();a['description']='Krimi. '+a['description'];catalog.ingest(self.c,[a]);self.assertEqual(catalog.listing(self.c,genre='Krimi')['total'],1);self.assertTrue(any(r['genre']=='Krimi' for r in catalog.tree(self.c)))
 def test_automatic_needs_corroboration(self):
  m={'kind':'movie'};a={'kind':'movie','similarity':1,'provider':'TMDB','reference_id':'42'};self.assertIsNone(catalog.auto_choice(m,[a]));a['runtime_agrees']=True;self.assertIsNotNone(catalog.auto_choice(m,[a]));a['year_mismatch']=True;self.assertIsNone(catalog.auto_choice(m,[a]))
 def test_ambiguous_not_auto(self):
  a={'kind':'movie','similarity':1,'provider':'TMDB','reference_id':'42','runtime_agrees':True};self.assertIsNone(catalog.auto_choice({'kind':'movie'},[a,{**a,'reference_id':'43'}]))
 def test_direct_file_over_unsupported_hls(self):
  a=row();a['url_video_hd']='https://example.org/hd.m3u8';self.assertEqual(catalog.links(a)[0]['quality'],'Standard')
 def test_highest_resolution_hint(self):
  a=row();a['url_video']='https://example.org/2160p.mp4';self.assertEqual(catalog.links(a)[0]['height_hint'],2160)
 def test_feed_repeated_keys_and_url_expansion(self):
  header=['Sender','Thema','Titel','Dauer','Url','Url HD'];a=['ARD','Serie','Start','00:42:00','https://host/a.mp4','13|b.mp4'];b=['','','Weiter','00:43:00','https://host/c.mp4',''];text='{"Filmliste":'+json.dumps(header)+',"X":'+json.dumps(a)+',"X":'+json.dumps(b)+'}'
  rows=list(filmlist.adapt(filmlist.pairs(io.StringIO(text))));self.assertEqual(len(rows),2);self.assertEqual(rows[1]['channel'],'ARD');self.assertEqual(rows[1]['topic'],'Serie');self.assertEqual(rows[0]['duration'],2520);self.assertEqual(rows[0]['url_video_hd'],'https://host/b.mp4')
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'list.xz';p.write_bytes(lzma.compress(text.encode()));self.assertEqual(len(list(filmlist.read_rows(p))),2);p.write_bytes(p.read_bytes()[:-12])
   with self.assertRaises((ValueError,lzma.LZMAError)):list(filmlist.read_rows(p))
 def test_truncated_json(self):
  with self.assertRaises(ValueError):list(filmlist.pairs(io.StringIO('{"X":["a"]')))

 def test_episodes_sorted_numerically(self):
  a=row('Zweite S01E02');b=row('Erste S01E01');a['topic']=b['topic']='Serie';catalog.ingest(self.c,[a,b]);d=catalog.listing(self.c);episodes=catalog.listing(self.c,show=d['items'][0]['show_key'])['items'];self.assertEqual([e['metadata']['episode'] for e in episodes],[1,2])
 def test_trailer_not_grouped_as_episode(self):
  a=row('Trailer: Test S01E00');a['topic']='Serie';catalog.ingest(self.c,[a]);self.assertEqual(catalog.listing(self.c)['total'],0);self.assertEqual(catalog.listing(self.c,kind='other')['total'],1)
 def test_sports_drama_is_not_film_genre(self):
  a=row('FCK verliert dramatisch');a.update(topic='Sport',description='Drama beim 1. FC Kaiserslautern. Acht Tore im Spiel.');m=catalog.seed(a);self.assertNotEqual(m['kind'],'movie');self.assertNotIn('Drama',m['genres'])
 def test_explicit_genre_label(self):
  a=row();a['description']='Drama Deutschland 2020';self.assertIn('Drama',catalog.seed(a)['genres'])
 def test_partial_series_metadata_can_be_saved(self):
  import core
  m={'title':'Serie','kind':'series','season':None,'episode':None};self.assertEqual(core.validate_meta(dict(m),require_episode=False)['title'],'Serie')
  with self.assertRaises(ValueError):core.validate_meta(dict(m))

class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  with self.db() as c:c.executescript(catalog.SCHEMA);c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)');catalog.ingest(c,[row()],seen=10)
  self.service=catalog_service.Service(self.db,lambda:{'auto_metadata':True},threading.Event(),self.root)
 def tearDown(self):self.tmp.cleanup()
 def db(self):
  c=sqlite3.connect(self.root/'c.db');c.row_factory=sqlite3.Row;return c
 def test_automatic_queue_match_persisted(self):
  candidate={**catalog.seed(row()),'provider':'TMDB','reference_id':'42','similarity':1,'runtime_agrees':True,'genres':['Drama']}
  with patch('core.candidates',return_value={'candidates':[candidate],'warnings':[]}):self.assertTrue(self.service.metadata_once())
  with self.db() as c:
   d=catalog.listing(c)['items'][0];self.assertEqual(d['state'],'matched');self.assertEqual(d['metadata']['genres'],['Drama'])
 def test_network_error_retried_not_confirmed(self):
  with patch('core.candidates',return_value={'candidates':[],'warnings':['HTTP 429']}):self.service.metadata_once()
  with self.db() as c:self.assertEqual(catalog.listing(c)['items'][0]['state'],'retry')
 def test_interrupted_snapshot_preserves_old_availability(self):
  def bad(path):yield row('Neu');raise ValueError('truncated')
  with patch('filmlist.read_rows',bad):
   with self.assertRaises(ValueError):self.service.import_snapshot('unused',20,lambda:False)
  with self.db() as c:self.assertEqual(c.execute('SELECT active FROM offers').fetchone()[0],1);self.assertFalse(catalog.get_state(c,'last_complete',False))
 def test_successful_snapshot_retires_old_offer(self):
  with patch('filmlist.read_rows',return_value=iter([row('Neu')])):self.service.import_snapshot('unused',20,lambda:False)
  with self.db() as c:
   self.assertEqual(catalog.listing(c)['total'],1);self.assertEqual(catalog.listing(c,archive=True)['total'],2);self.assertTrue(catalog.get_state(c,'last_complete'))
if __name__=='__main__':unittest.main()
