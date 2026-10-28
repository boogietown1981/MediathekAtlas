import unittest,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog,provider_stats
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;catalog.initialize(self.c)
  for n in range(3):catalog.ingest(self.c,[{'title':f'Folge {n+1}','topic':'Testserie','channel':'Sender','duration':1500,'description':'','url_video':f'https://example.org/{n}.mp4'}])
 def tearDown(self):self.c.close()
 def test_flat_review_keeps_all_episodes_and_excludes_confirmed(self):
  self.c.execute("UPDATE works SET kind='series',show_key='same',state='identified'")
  self.assertEqual(catalog.review_listing(self.c)['total'],3)
  first=self.c.execute('SELECT id FROM works LIMIT 1').fetchone()[0]
  self.c.execute("UPDATE works SET state='manual' WHERE id=?",(first,))
  self.assertEqual(catalog.review_listing(self.c)['total'],2)
  self.assertEqual(catalog.review_listing(self.c,state='manual')['total'],1)
  self.assertEqual(catalog.review_listing(self.c,query='not-present')['total'],0)
 def test_inactive_excluded(self):
  self.c.execute('UPDATE offers SET active=0');self.assertEqual(catalog.review_listing(self.c)['total'],0)
 def test_query_is_bound(self):self.assertEqual(catalog.review_listing(self.c,query="' OR 1=1 --")['total'],0)
class StatsTests(unittest.TestCase):
 def test_checks_hits_errors_and_skips_separate(self):
  with provider_stats._LOCK:old=provider_stats._ROWS;provider_stats._ROWS={}
  try:
   provider_stats.observe('TMDB','checked',2);provider_stats.observe('TMDB','checked',0);provider_stats.observe('TMDB','error');provider_stats.observe('OMDb','paused');provider_stats.observe('TVDB','not_configured')
   rows={r['provider']:r for r in provider_stats.snapshot()['rows']}
   self.assertEqual((rows['TMDB']['checks'],rows['TMDB']['with_hits'],rows['TMDB']['candidates'],rows['TMDB']['errors']),(3,1,2,1))
   self.assertEqual(rows['OMDb']['checks'],0);self.assertEqual(rows['OMDb']['paused_skips'],1);self.assertEqual(rows['TVDB']['checks'],0)
   self.assertIsNotNone(rows['TMDB']['last_success'])
  finally:
   with provider_stats._LOCK:provider_stats._ROWS=old
