import io,json,tempfile,unittest,zipfile,threading,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnostics,filmlist,catalog_service
class DiagnosticsTests(unittest.TestCase):
 def test_export_redacts_and_excludes_database(self):
  with tempfile.TemporaryDirectory() as d:
   diagnostics.setup(d);Path(d,'catalog.db').write_text('PRIVATE');Path(d,'startup.log').write_text('https://example.org/?api_key=SECRET')
   diagnostics.event('test',api_key='SECRET',url='https://example.org/?token=SECRET',detail='token=SECRET')
   with zipfile.ZipFile(io.BytesIO(diagnostics.export({'token':'SECRET'}))) as z:
    self.assertNotIn('catalog.db',z.namelist());self.assertNotIn('SECRET',''.join(z.read(n).decode() for n in z.namelist()));self.assertIn('diagnostic.jsonl',z.namelist())
 def test_known_secret_redacted_in_traceback(self):
  diagnostics.register_secrets('private-provider-key')
  self.assertNotIn('private-provider-key',diagnostics.clean('Exception private-provider-key'))
 def test_offline_export_without_server(self):
  import os,subprocess
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);(home/'Desktop').mkdir();root=home/'state';root.mkdir();(root/'startup.log').write_text('startup failure')
   result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'diagnostics_cli.py')],env={**os.environ,'HOME':d,'MEDIATHEKATLAS_HOME':str(root)},capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   with zipfile.ZipFile(Path(result.stdout.strip())) as z:self.assertIn('startup.txt',z.namelist())
 def test_tail_bounded_and_rotation(self):
  with tempfile.TemporaryDirectory() as d:
   diagnostics.setup(d)
   for n in range(500):diagnostics.event('test',number=n)
   self.assertLessEqual(len(diagnostics.tail().splitlines()),400)
   self.assertEqual(json.loads(diagnostics.tail().splitlines()[-1])['number'],499)
 def test_feed_retries_and_reports(self):
  progress=[]
  with patch('filmlist._download',side_effect=[TimeoutError('stalled'),'ok']) as f,patch('filmlist.time.sleep'):
   self.assertEqual(filmlist.download('.',lambda **s:progress.append(s),lambda:False),'ok');self.assertEqual(f.call_count,2);self.assertEqual(progress[0]['phase'],'retrying')
 def test_feed_cancellation_not_retried(self):
  with patch('filmlist._download',side_effect=InterruptedError) as f:
   with self.assertRaises(InterruptedError):filmlist.download('.',lambda **s:None,lambda:False)
   self.assertEqual(f.call_count,1)
 def test_worker_recovers_after_exception(self):
  stop=threading.Event();service=catalog_service.Service(None,None,stop,None);calls=[]
  def worker():
   calls.append(1)
   if len(calls)==1:raise RuntimeError('database locked')
   stop.set()
  with patch.object(stop,'wait',return_value=False):service.supervise(worker)
  self.assertEqual(len(calls),2)
 def tearDown(self):
  for h in list(diagnostics.logger.handlers):diagnostics.logger.removeHandler(h);h.close()
if __name__=='__main__':unittest.main()
