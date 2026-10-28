import unittest,io,tempfile,json,sqlite3,threading
from pathlib import Path
from unittest.mock import patch
import artwork,catalog,catalog_service
class ArtTests(unittest.TestCase):
 def test_external_id_preserves_identity(self):
  m={'title':'Serie','kind':'series','year':2020,'provider':'IMDb Offline','reference_id':'tt1'};before=dict(m);calls=[]
  def get(path,*args):
   calls.append(path)
   return {'tv_results':[{'id':12}]} if path.startswith('find/') else {'poster_path':'/p.jpg','backdrop_path':'/f.jpg'}
  with patch('core.tmdb',side_effect=get):result,errors=artwork.lookup(m,{'tmdb':'k'})
  self.assertEqual(m,before);self.assertIn('fanart',result);self.assertFalse(errors);self.assertEqual(calls,['find/tt1','tv/12'])
 def test_ambiguous_search_no_wrong_art(self):
  m={'title':'Film','kind':'movie','year':2020,'provider':'manuell'}
  with patch('core.tmdb',return_value={'results':[{'id':1,'title':'Film','release_date':'2020'},{'id':2,'title':'Film','release_date':'2020'}]}):
   result,_=artwork.lookup(m,{'tmdb':'k'})
  self.assertFalse(result)
 def test_wrong_year_no_art(self):
  self.assertFalse(artwork.compatible({'title':'Film','year':2000},{'title':'Film','release_date':'2020'}))
 def test_image_validation_and_exclusive_export(self):
  with tempfile.TemporaryDirectory() as root:
   stem=Path(root)/'poster'
   with patch('core.open_url',return_value=io.BytesIO(b'<html>')):self.assertFalse(artwork.save_image('https://image.tmdb.org/a',stem))
   with patch('core.open_url',return_value=io.BytesIO(b'\xff\xd8\xffexample')):self.assertTrue(artwork.save_image('https://artworks.thetvdb.com/a',stem))
   with patch('core.open_url',side_effect=AssertionError('overwrite')):self.assertTrue(artwork.save_image('https://image.tmdb.org/a',stem))
   self.assertFalse(artwork.save_image('http://localhost/a',stem))
 def test_background_enriches_confirmed_without_changing_metadata(self):
  with tempfile.TemporaryDirectory() as root:
   from contextlib import contextmanager
   @contextmanager
   def db():
    c=sqlite3.connect(Path(root)/'catalog.db');c.row_factory=sqlite3.Row
    try:
     with c:yield c
    finally:c.close()
   with db() as c:
    catalog.initialize(c);catalog.ingest(c,[{'title':'Film','topic':'Film','description':'Spielfilm 2020','duration':5400,'channel':'ARD','url_video':'https://example.org/a.mp4'}])
    c.execute("UPDATE works SET state='manual'");before=json.loads(c.execute('SELECT meta FROM works').fetchone()[0])
   service=catalog_service.Service(db,lambda:{'tmdb':'k'},threading.Event(),Path(root))
   with patch('artwork.lookup',return_value=({'poster':'https://image.tmdb.org/p.jpg','fanart':'https://image.tmdb.org/f.jpg'},[])) as lookup:
    self.assertTrue(artwork.run_once(service));self.assertFalse(artwork.run_once(service));lookup.assert_called_once()
   with db() as c:after=json.loads(c.execute('SELECT meta FROM works').fetchone()[0])
   self.assertEqual(before['title'],after['title']);self.assertTrue(after['fanart'])
