import json,sqlite3,unittest
from unittest.mock import patch
import artwork,catalog,metadata
class DiscoveryTests(unittest.TestCase):
 def test_rating_scales_and_invalid_values(self):
  d={'Ratings':[{'Source':'Rotten Tomatoes','Value':'94%'},{'Source':'Metacritic','Value':'82/100'},{'Source':'Internet Movie Database','Value':'7.8/10'},{'Source':'Rotten Tomatoes','Value':'110%'},{'Source':'Other','Value':'5'}]}
  self.assertEqual([x['value'] for x in metadata.parse_ratings(d)],['94%','82/100','7.8/10'])
 def test_omdb_pause_prevents_enrichment_requests(self):
  m={'title':'Film','kind':'movie','provider':'IMDb Offline','reference_id':'tt123'}
  with patch('metadata.omdb_status',return_value={'paused':True}),patch('metadata.omdb') as call:
   result,errors=artwork.lookup(m,{'omdb':'k'})
  call.assert_not_called();self.assertFalse(errors);self.assertNotIn('ratings',result)
 def test_id_and_kind_must_match_for_ratings(self):
  m={'title':'Film','kind':'movie','provider':'IMDb Offline','reference_id':'tt123'}
  for identity,kind,expected in [('tt123','movie',True),('tt456','movie',False),('tt123','series',False)]:
   d={'imdbID':identity,'Type':kind,'Ratings':[{'Source':'Rotten Tomatoes','Value':'90%'}]}
   with patch('metadata.omdb_status',return_value={'paused':False}),patch('metadata.omdb',return_value=d):r,_=artwork.lookup(m,{'omdb':'k'})
   self.assertEqual(bool(r.get('ratings')),expected)
 def test_collections_quality_votes_and_download_flag(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;catalog.initialize(c)
  for i,(kind,rating,votes,source,state) in enumerate([('movie',8,10000,'IMDb','matched'),('movie',9,3,'IMDb','matched'),('movie',8,1000,'TMDB','matched'),('series',8,20000,'IMDb','identified'),('movie',9,20000,'IMDb','pending'),('movie',11,20000,'IMDb','matched')]):
   m={'kind':kind,'title':'Test '+str(i),'year':2020,'rating':rating,'votes':votes,'rating_source':source}
   c.execute('INSERT INTO works(id,title,kind,year,show_key,meta,state) VALUES(?,?,?,?,?,?,?)',(str(i),m['title'],kind,2020,'show'+str(i),json.dumps(m),state))
   c.execute('INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)',(str(i),str(i),json.dumps({'title':m['title'],'url_video':'https://example.org/a.mp4'})))
  self.assertEqual(catalog.listing(c,collection='cinema')['total'],2)
  self.assertEqual(catalog.listing(c,collection='series')['total'],1)
  c.execute('INSERT INTO downloaded_items VALUES(?,?,?)',('0','/film.mkv',1))
  self.assertEqual(catalog.listing(c,collection='cinema')['total'],1)
  self.assertEqual(catalog.listing(c,collection='cinema',downloaded='all')['total'],2)
  c.close()
