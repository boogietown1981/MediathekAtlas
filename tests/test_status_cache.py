"""Exercise the server cache without starting its download workers."""
import ast,contextlib,types,unittest
from pathlib import Path
class StatusCacheTests(unittest.TestCase):
 def function(self,clock,cache,stats):
  source=ast.parse((Path(__file__).resolve().parents[1]/'server.py').read_text())
  fn=next(x for x in source.body if isinstance(x,ast.FunctionDef) and x.name=='catalog_status')
  ns={'time':types.SimpleNamespace(monotonic=clock),'_STATUS_CACHE':cache,'catalog':types.SimpleNamespace(stats=stats),'db':lambda:contextlib.nullcontext(None),'SERVICE':types.SimpleNamespace(current={})}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'server.py','exec'),ns)
  return ns
 def test_invalidation_during_read_retains_snapshot(self):
  def clock():ns['_STATUS_CACHE']=(0,{});return 105
  ns=self.function(clock,(100,{'offers':123,'sync':{}}),lambda c:self.fail('Fresh snapshot should be retained'))
  self.assertEqual(ns['catalog_status']()['offers'],123)
 def test_empty_cache_loaded_even_with_recent_timestamp(self):
  ns=self.function(lambda:105,(100,{}),lambda c:{'offers':42})
  self.assertEqual(ns['catalog_status']()['offers'],42)
