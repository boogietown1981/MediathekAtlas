import unittest,sqlite3,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog,artwork

def ep(title,channel='ARD',topic='Beispielserie',desc='Folgenhandlung'):
 return {'title':title,'topic':topic,'channel':channel,'description':desc+' '+title,'duration':2700,'url_video':'https://example.org/'+channel+'/'+title.replace(' ','_')+'.mp4'}
class ShowDetailTests(unittest.TestCase):
 def setUp(self):self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.executescript(catalog.SCHEMA)
 def tearDown(self):self.c.close()
 def show(self):return catalog.listing(self.c)['items'][0]['show_key']
 def test_seasons_and_order(self):
  catalog.ingest(self.c,[ep('Drei S02E01'),ep('Zwei S01E02'),ep('Eins S01E01'),ep('Eins S01E01','ZDF')])
  d=catalog.show_detail(self.c,self.show())
  self.assertEqual([(e['metadata']['season'],e['metadata']['episode']) for e in d['episodes']],[(1,1),(1,2),(2,1)])
  self.assertEqual(d['show']['seasons'],[{'season':1,'episodes':2},{'season':2,'episodes':1}])
  self.assertEqual(d['show']['episode_count'],3);self.assertEqual(d['episodes'][0]['offer_count'],2)
  self.assertEqual(d['show']['channels'],['ARD','ZDF'])
 def test_show_metadata_from_best_episode_not_episode_plot(self):
  catalog.ingest(self.c,[ep('Eins S01E01'),ep('Zwei S01E02')]);show=self.show()
  rows=self.c.execute('SELECT id,meta FROM works WHERE show_key=? ORDER BY id',(show,)).fetchall()
  m=json.loads(rows[1]['meta']);m.update(poster='https://image.tmdb.org/p.jpg',fanart='https://image.tmdb.org/f.jpg',show_description='Die Serie handelt von …',description='Nur diese Folge',rating=8.1)
  self.c.execute("UPDATE works SET meta=?,state='matched' WHERE id=?",(json.dumps(m),rows[1]['id']))
  s=catalog.show_detail(self.c,show)['show']
  self.assertEqual(s['show_description'],'Die Serie handelt von …');self.assertEqual(s['fanart'],'https://image.tmdb.org/f.jpg');self.assertEqual(s['state'],'matched');self.assertNotIn('description',s)
 def test_broadcaster_series_text_fallback(self):
  catalog.ingest(self.c,[ep('Eins S01E01'),ep('Zwei S01E02')]);show=self.show()
  for r in self.c.execute('SELECT id,meta FROM works WHERE show_key=?',(show,)).fetchall():
   m=json.loads(r['meta']);m['series_description']='Sendereihe XY';self.c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),r['id']))
  self.assertEqual(catalog.show_detail(self.c,show)['show']['show_description'],'Sendereihe XY')
 def test_unknown_show(self):
  with self.assertRaises(ValueError):catalog.show_detail(self.c,'gibt-es-nicht')
 def test_archived_hidden_unless_requested(self):
  catalog.ingest(self.c,[ep('Eins S01E01')]);show=self.show();self.c.execute('UPDATE offers SET active=0')
  with self.assertRaises(ValueError):catalog.show_detail(self.c,show)
  self.assertEqual(len(catalog.show_detail(self.c,show,archive=True)['episodes']),1)
 def test_propagation_carries_series_overview(self):
  catalog.ingest(self.c,[ep('Eins S01E01'),ep('Zwei S01E02')]);show=self.show()
  catalog.propagate_series(self.c,show,{'title':'Beispielserie','provider':'TMDB','reference_id':'7','show_description':'Überblick'})
  metas=[json.loads(r[0]) for r in self.c.execute('SELECT meta FROM works WHERE show_key IS NOT NULL')]
  self.assertTrue(any(m.get('show_description')=='Überblick' for m in metas))
class ArtworkOverviewTests(unittest.TestCase):
 def test_apply_keeps_existing_overview(self):
  m={'kind':'series','show_description':'alt'};artwork.apply(m,{'show_description':'neu'});self.assertEqual(m['show_description'],'alt')
  m={'kind':'series'};artwork.apply(m,{'show_description':'neu'});self.assertEqual(m['show_description'],'neu')
if __name__=='__main__':unittest.main()
