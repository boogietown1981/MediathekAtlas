import io,json,sys,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tvdb,metadata,catalog,core,diagnostics
class TVDBTests(unittest.TestCase):
 def setUp(self):tvdb._CACHE.clear();tvdb._TOKENS.clear();tvdb._PAUSED.clear()
 def response(self,d):return io.BytesIO(json.dumps({'status':'success','data':d}).encode())
 def test_login_pin_cache_and_token_private(self):
  with patch('core.open_url',side_effect=[self.response({'token':'private-token'}),self.response([])]) as fetch:
   tvdb.request('search','project-key','subscriber-pin',{'query':'Serie'})
   tvdb.request('search','project-key','subscriber-pin',{'query':'Serie'})
  self.assertEqual(fetch.call_count,2)
  self.assertEqual(json.loads(fetch.call_args_list[0].args[1]),{'apikey':'project-key','pin':'subscriber-pin'})
  self.assertEqual(fetch.call_args_list[1].args[2]['Authorization'],'Bearer private-token')
  self.assertNotIn('private-token',diagnostics.clean('private-token'))
 def test_no_pin_sent_when_empty(self):
  with patch('core.open_url',side_effect=[self.response({'token':'token'}),self.response([])]) as fetch:tvdb.request('search','key')
  self.assertNotIn('pin',json.loads(fetch.call_args_list[0].args[1]))
 def test_auth_error_pauses_and_force_test_recovers(self):
  error=urllib.error.HTTPError('https://api4.thetvdb.com/v4/login',401,'No',{},io.BytesIO(b'secret'))
  with patch('core.open_url',side_effect=error) as fetch:
   for _ in range(2):
    with self.assertRaises(tvdb.TVDBError) as caught:tvdb.request('search','key')
    self.assertNotIn('secret',str(caught.exception))
   self.assertEqual(fetch.call_count,1)
  with patch('core.open_url',side_effect=[self.response({'token':'new'}),self.response([])]):self.assertTrue(tvdb.test_access('key')['ok'])
  self.assertFalse(tvdb._PAUSED)
 def test_expired_token_reauthenticates_once(self):
  error=urllib.error.HTTPError('https://api4.thetvdb.com/v4/search',401,'No',{},io.BytesIO())
  with patch('core.open_url',side_effect=[self.response({'token':'old'}),error,self.response({'token':'new'}),self.response([])]) as fetch:tvdb.request('search','key')
  self.assertEqual(fetch.call_count,4)
 def test_rate_limit_no_login_storm(self):
  error=urllib.error.HTTPError('https://api4.thetvdb.com/v4/search',429,'No',{},io.BytesIO())
  with patch('core.open_url',side_effect=[self.response({'token':'old'}),error]) as fetch:
   for _ in range(2):
    with self.assertRaisesRegex(tvdb.TVDBError,'Anfragelimit'):tvdb.request('search','key')
   self.assertEqual(fetch.call_count,2)
 def candidates(self,ambiguous=False,incomplete=False):
  def get(path,*args):
   if path=='search':return {'data':[{'tvdb_id':'12','name':'Bibi & Tina','translations':{'deu':'Bibi und Tina'}}]}
   if path.endswith('extended'):return {'data':{'name':'Bibi & Tina','firstAired':'2004-01-01','genres':[{'name':'Family'}]}}
   page=args[-1]['page'];ep={'name':'Freundschaft','seasonNumber':2,'number':4}
   return {'data':{'episodes':[ep] if page==0 else [dict(ep,seasonNumber=3)]},'links':{'next':'next' if incomplete or (ambiguous and page==0) else None}}
  row={'title':'Freundschaft','topic':'Bibi und Tina'};meta={'kind':'series','title':'Bibi und Tina','description':''}
  with patch('tvdb.request',side_effect=get):return metadata.tvdb_candidates(row,meta,('key','pin'),'series','Bibi und Tina')[0]
 def test_german_episode_genre_and_catalog_identity(self):
  c=self.candidates();self.assertTrue(c['episode_verified']);self.assertEqual((c['season'],c['episode']),(2,4));self.assertEqual(c['genres'],['Kinder & Familie'])
  self.assertIsNotNone(catalog.auto_choice({'kind':'series'},[c]));self.assertIsNotNone(catalog.canonical(c))
 def test_ambiguous_or_truncated_pages_never_verify(self):
  self.assertFalse(self.candidates(ambiguous=True)['episode_verified']);self.assertFalse(self.candidates(incomplete=True)['episode_verified'])
 def test_movies_do_not_call_tvdb(self):
  with patch('tvdb.request') as fetch:self.assertEqual(metadata.tvdb_candidates({}, {}, ('key',''),'movie','Film'),[])
  fetch.assert_not_called()
 def test_missing_key(self):
  with patch('core.open_url') as fetch:self.assertFalse(tvdb.test_access('')['ok'])
  fetch.assert_not_called()
 def test_nfo_tvdb_id(self):
  m={'title':'Serie','kind':'series','year':2004,'season':1,'episode':2,'episode_title':'Folge','description':'','provider':'TVDB','reference_id':'12','genres':[]}
  self.assertNotIn(b'type="tvdb"',core.nfo(m,[],1500))
  self.assertIn(b'type="tvdb"',core.show_nfo(m))
