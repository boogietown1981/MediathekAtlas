import ast,contextlib,json,sys,tempfile,threading,time,types,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from instance import Instance
class InstanceTests(unittest.TestCase):
 def test_lock_release_and_reopen(self):
  with tempfile.TemporaryDirectory() as d:
   a=Instance(Path(d));b=Instance(Path(d))
   try:
    self.assertTrue(a.acquire());a.publish('http://127.0.0.1:23456','0.3.4');self.assertFalse(b.acquire());self.assertEqual(b.existing()['version'],'0.3.4')
    a.close();self.assertTrue(b.acquire())
   finally:a.close();b.close()
 def test_external_url_not_opened(self):
  with tempfile.TemporaryDirectory() as d:
   a=Instance(Path(d));a.publish('https://example.org','bad');self.assertEqual(a.existing(),{})
def tree_namespace(tree,clock=time):
 source=ast.parse((Path(__file__).resolve().parents[1]/'server.py').read_text())
 nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in ('catalog_tree','refresh_tree') or isinstance(n,ast.Assign) and any(getattr(t,'id','')=='_TREE_CACHE' for t in n.targets)]
 ns={'threading':threading,'time':clock,'db':lambda:contextlib.nullcontext(None),'catalog':types.SimpleNamespace(tree=tree),'diagnostics':types.SimpleNamespace(event=lambda *a,**k:None),'_TREE_LOCK':threading.Lock(),'_TREE_BUSY':False,'_TREE_ERROR':''}
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'server.py','exec'),ns);return ns
class TreeTests(unittest.TestCase):
 def test_first_request_loads_even_shortly_after_boot(self):
  done=threading.Event()
  def tree(c):done.set();return [{'kind':'movie','genre':'Drama','n':1}]
  ns=tree_namespace(tree,types.SimpleNamespace(monotonic=lambda:5.0))
  self.assertTrue(ns['catalog_tree']()['loading']);self.assertTrue(done.wait(1))
 def test_slow_query_does_not_block_http_and_runs_only_once(self):
  release=threading.Event();started=threading.Event();calls=[]
  def tree(c):calls.append(1);started.set();release.wait(3);return [{'kind':'movie','genre':'Drama','n':12}]
  ns=tree_namespace(tree)
  try:
   before=time.monotonic();first=ns['catalog_tree']();self.assertLess(time.monotonic()-before,.5);self.assertTrue(first['loading']);self.assertTrue(started.wait(1))
   second=ns['catalog_tree']();self.assertTrue(second['loading']);self.assertEqual(len(calls),1)
  finally:release.set()
  deadline=time.monotonic()+3
  while ns['_TREE_BUSY'] and time.monotonic()<deadline:time.sleep(.01)
  final=ns['catalog_tree']();self.assertFalse(final['loading']);self.assertEqual(final['tree'][0]['genre'],'Drama');self.assertEqual(len(calls),1)
