import io,json,sys,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import metadata
class AccessTests(unittest.TestCase):
 def setUp(self):metadata._OMDB_PAUSED.clear();metadata._CACHE.clear()
 def failure(self,message,status=401):return urllib.error.HTTPError('https://www.omdbapi.com/?apikey=PRIVATE',status,'Unauthorized',{},io.BytesIO(json.dumps({'Response':'False','Error':message}).encode()))
 def test_401_limit_not_invalid_key(self):
  with patch('core.open_url',side_effect=self.failure('Request limit reached!')):r=metadata.test_omdb('PRIVATE')
  self.assertEqual(r['reason'],'limit');self.assertEqual(r['http_status'],401);self.assertNotIn('PRIVATE',r['message'])
 def test_invalid_key(self):
  with patch('core.open_url',side_effect=self.failure('Invalid API key!')):self.assertEqual(metadata.test_omdb('PRIVATE')['reason'],'key')
 def test_inactive_key(self):
  with patch('core.open_url',side_effect=self.failure('API key not activated!')):self.assertEqual(metadata.test_omdb('PRIVATE')['reason'],'inactive')
 def test_untrusted_response_not_echoed(self):
  with patch('core.open_url',side_effect=self.failure('PRIVATE arbitrary secret')):r=metadata.test_omdb('PRIVATE')
  self.assertEqual(r['reason'],'auth');self.assertNotIn('PRIVATE',r['message'])
 def test_pause_and_explicit_retest(self):
  with patch('core.open_url',side_effect=self.failure('Invalid API key!')) as request:
   metadata.test_omdb('PRIVATE')
   with self.assertRaises(metadata.OMDbError):metadata.omdb({'t':'Other'},'PRIVATE')
   self.assertEqual(request.call_count,1)
  with patch('core.open_url',return_value=io.BytesIO(b'{"Response":"True","imdbID":"tt0133093","Title":"The Matrix"}')) as request:
   self.assertTrue(metadata.test_omdb('PRIVATE')['ok']);self.assertEqual(request.call_count,1)
  self.assertFalse(metadata._OMDB_PAUSED)
 def test_timeout_is_distinct(self):
  with patch('core.open_url',side_effect=TimeoutError):self.assertEqual(metadata.test_omdb('PRIVATE')['reason'],'network')
 def test_missing_key_does_not_request(self):
  with patch('core.open_url') as request:self.assertEqual(metadata.test_omdb('')['reason'],'missing');request.assert_not_called()
 def test_paused_provider_skipped_before_each_title_and_others_continue(self):
  with patch('core.open_url',side_effect=self.failure('Request limit reached!')):metadata.test_omdb('PRIVATE')
  with patch('metadata.omdb_candidates') as omdb,patch('metadata.tmdb_candidates',return_value=[{'title':'Film','provider':'TMDB'}]) as tmdb,patch('diagnostics.event') as log:
   for n in range(10):
    r=metadata.candidates({'title':'Film'},{'kind':'movie','title':'Film'},{'omdb':'PRIVATE','tmdb':'OTHER'})
    self.assertEqual(r['deferred_providers'],['OMDb']);self.assertFalse(r['warnings']);self.assertEqual(r['candidates'][0]['provider'],'TMDB')
   omdb.assert_not_called();self.assertEqual(tmdb.call_count,10)
   self.assertFalse(any(c.kwargs.get('provider')=='OMDb' for c in log.call_args_list))
 def test_free_fallback_still_runs_during_pause(self):
  with patch('core.open_url',side_effect=self.failure('Request limit reached!')):metadata.test_omdb('PRIVATE')
  with patch('metadata.wikidata',return_value=None) as wiki,patch('metadata.omdb_candidates') as omdb:
   metadata.candidates({'title':'Film'},{'kind':'movie','title':'Film'},{'omdb':'PRIVATE'})
   wiki.assert_called_once();omdb.assert_not_called()
 def test_persistent_timer_and_expiry(self):
  import tempfile,time
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'pauses.json'
   try:
    metadata.configure_provider_state(path)
    with patch('core.open_url',side_effect=self.failure('Request limit reached!')):metadata.test_omdb('PRIVATE')
    until=metadata.omdb_status('PRIVATE')['retry_at'];self.assertNotIn('PRIVATE',path.read_text())
    metadata._OMDB_PAUSED.clear();metadata.configure_provider_state(path)
    self.assertTrue(metadata.omdb_status('PRIVATE')['paused']);self.assertFalse(metadata.omdb_status('NEW-KEY')['paused'])
    with patch('metadata.time.time',return_value=until+1),patch('core.open_url',return_value=io.BytesIO(b'{"Response":"True","Title":"Film"}')) as request:
     self.assertFalse(metadata.omdb_status('PRIVATE')['paused']);metadata.omdb({'t':'Film'},'PRIVATE');request.assert_called_once()
    self.assertFalse(metadata._OMDB_PAUSED)
   finally:metadata._OMDB_FILE=None
 def test_first_quota_failure_is_pause_not_per_title_warning(self):
  with patch('core.open_url',side_effect=self.failure('Request limit reached!')),patch('metadata.wikidata',return_value=None),patch('diagnostics.error') as log:
   result=metadata.candidates({'title':'Film'},{'kind':'movie','title':'Film'},{'omdb':'PRIVATE'})
  self.assertEqual(result['warnings'],[]);self.assertEqual(result['deferred_providers'],['OMDb']);log.assert_not_called()
  self.assertIn({'provider':'OMDb','status':'paused','count':0},result['provider_checks'])
  self.assertIn({'provider':'Wikidata','status':'checked','count':0},result['provider_checks'])
if __name__=='__main__':unittest.main()
