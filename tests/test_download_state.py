import json,sqlite3,tempfile,unittest,shutil
from pathlib import Path
import catalog,stable_runtime
class DownloadStateTests(unittest.TestCase):
 def test_flag_hides_in_all_genres_without_deletion(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;catalog.initialize(c)
  oid=catalog.ingest(c,[{'title':'Film','channel':'ARD','description':'Spielfilm 2020','duration':5400,'url_video':'https://example.org/a.mp4'}])[0]
  w=c.execute('SELECT * FROM works').fetchone();m=json.loads(w['meta']);m.update(kind='movie',title='Film',year=2020,genres=['Drama','Thriller'],provider='TMDB',reference_id='1',state='user_confirmed');catalog.save_metadata(c,w['id'],m)
  catalog.mark_downloaded(c,{'metadata':m,'source':{'_id':oid},'path':'/tmp/film.mkv'})
  for genre in ('Drama','Thriller'):self.assertEqual(catalog.listing(c,genre=genre)['total'],0)
  self.assertEqual(catalog.listing(c,downloaded='only')['total'],1);self.assertTrue(catalog.listing(c,downloaded='all')['items'][0]['downloaded'])
  catalog.ingest(c,[{'title':'Film','channel':'ARD','description':'Spielfilm 2020','duration':5400,'url_video':'https://example.org/a.mp4'}]);self.assertEqual(catalog.listing(c)['total'],0)
  self.assertEqual(c.execute('SELECT COUNT(*) FROM works').fetchone()[0],1);c.close()
 def test_stable_runtime_survives_removed_app(self):
  with tempfile.TemporaryDirectory() as root:
   source=Path(root)/'AppTranslocation';source.mkdir();(source/'web').mkdir();(source/'server.py').write_text('pass');(source/'web'/'index.html').write_text('test')
   dest=stable_runtime.prepare(source,Path(root)/'state');self.assertEqual(stable_runtime.prepare(source,Path(root)/'state'),dest)
   shutil.rmtree(source);self.assertEqual((dest/'web'/'index.html').read_text(),'test')
