import unittest
from unittest.mock import patch
import matching,metadata
class MatchingTests(unittest.TestCase):
 def candidate(self,provider='TVDB',**kw):return dict({'provider':provider,'reference_id':'123','kind':'series','title':'Serie','similarity':1,'year':2020,'season':1,'episode':2,'episode_verified':True,'genres':['Drama']},**kw)
 def test_order_and_early_stop(self):
  calls=[]
  def provider(name,hits):
   def fn(*a):calls.append(name);return hits
   return fn
  with patch('imdb_archive.ACTIVE',None),patch('metadata.tvdb_candidates',side_effect=provider('TVDB',[self.candidate()])),patch('metadata.tmdb_candidates',side_effect=provider('TMDB',[])),patch('metadata.omdb_candidates',side_effect=provider('OMDb',[])):
   metadata.candidates({'title':'Folge'},{'title':'Serie','kind':'series'},{'tvdb':'k','tmdb':'k','omdb':'k'})
  self.assertEqual(calls,['TVDB'])
 def test_fallback_order_on_insufficient_results(self):
  calls=[]
  def fn(name):
   def run(*a):calls.append(name);return [self.candidate(name,genres=[])]
   return run
  with patch('imdb_archive.ACTIVE',None),patch('metadata.tvdb_candidates',side_effect=fn('TVDB')),patch('metadata.tmdb_candidates',side_effect=fn('TMDB')),patch('metadata.omdb_candidates',side_effect=fn('OMDb')):
   metadata.candidates({'title':'Folge'},{'title':'Serie','kind':'series'},{'tvdb':'k','tmdb':'k','omdb':'k'})
  self.assertEqual(calls,['TVDB','TMDB','OMDb'])
 def test_missing_key_skipped(self):
  with patch('imdb_archive.ACTIVE',None),patch('metadata.tvdb_candidates',side_effect=AssertionError('missing key')),patch('metadata.tmdb_candidates',return_value=[self.candidate('TMDB')]) as tm:
   metadata.candidates({'title':'Folge'},{'title':'Serie','kind':'series'},{'tmdb':'k'})
  tm.assert_called_once()
 def test_contradictions_block_automatic_match(self):
  for change in ({'year':2021},{'season':2},{'episode':3},{'runtime_mismatch':True},{'kind':'movie'},{'similarity':.9},{'episode_scan_complete':False}):
   self.assertFalse(matching.verified({'kind':'series','year':2020,'season':1,'episode':2},self.candidate(**change)))
 def test_ambiguity_does_not_prefer_tmdb(self):
  self.assertIsNone(matching.choose({'kind':'series'},[self.candidate(),self.candidate('TMDB',episode=3)]))
  self.assertIsNone(matching.choose({'kind':'series'},[self.candidate(),self.candidate(reference_id='456')]))
 def test_compatible_missing_genres_enriched(self):
  a=self.candidate('IMDb Offline',genres=[]);b=self.candidate()
  c=matching.choose({'kind':'series'},[a,b]);self.assertEqual(c['provider'],'IMDb Offline');self.assertEqual(c['genres'],['Drama']);self.assertEqual(c['field_sources']['genres'],'TVDB')
 def test_missing_evidence_not_sufficient(self):
  self.assertFalse(matching.sufficient({'kind':'series'},[self.candidate(episode_verified=False)]))
  self.assertFalse(matching.sufficient({'kind':'series'},[self.candidate(year=None)]))

 def test_episode_runtime_rejects_short_clip(self):
  c=self.candidate(description='')
  metadata.resolve_episode({'_source_title':'Anfang','_source_duration':60},c,[{'name':'Anfang','season_number':1,'episode_number':2,'runtime':25}])
  self.assertTrue(c['runtime_mismatch']);self.assertFalse(matching.verified({'kind':'series'},c))
