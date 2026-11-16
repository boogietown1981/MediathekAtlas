"""0.6.9: findings of the diagnosis of 16.11.2026 (0.6.8, macOS arm64)."""
import ast,contextlib,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch
import catalog,catalog_service,netzkino,runtime_tools
from test_diagnosis_fixes import database

ROOT=Path(__file__).resolve().parents[1]

def edition(n,topic='Schleswig-Holstein Magazin',duration=1800):
    # Editions of a Sendung titled like the Sendung itself, told apart only by their text.
    return {'title':topic,'topic':topic,'channel':'NDR','duration':duration,
            'description':'Ausgabe %d mit Themen aus dem ganzen Land, Reportagen und dem Wetter für morgen.'%n,
            'url_video':'https://example.org/sh/%d.mp4'%n}

class IdentifiedDelayTests(unittest.TestCase):
    def test_edition_of_a_sendereihe_waits_30_days_for_any_provider(self):
        for provider in ('IMDb Offline','TMDB','TVDB','ARD Mediathek'):
            d=catalog_service.identified_delay({'kind':'series','title':'Schleswig-Holstein Magazin','provider':provider},
                                               {'topic':'Schleswig-Holstein Magazin'},rand=lambda:0)
            self.assertEqual(d,30*86400,provider)
    def test_spread_is_bounded(self):
        d=catalog_service.identified_delay({'kind':'series','title':'NDR Info','provider':'TMDB'},{'topic':'NDR Info'},rand=lambda:.999)
        self.assertTrue(30*86400<=d<37*86400)
    def test_other_identified_works_keep_the_daily_check(self):
        self.assertEqual(catalog_service.identified_delay({'kind':'movie','title':'Film','provider':'TMDB'},{'topic':'Film'}),86400)
        self.assertEqual(catalog_service.identified_delay({'kind':'series','title':'Tatort','provider':'TMDB'},{'topic':'Filme im Ersten'}),86400)
        self.assertEqual(catalog_service.identified_delay({'kind':'series','title':'','provider':'TMDB'},{'topic':''}),86400)

    def test_service_does_not_requery_identified_edition_daily(self):
        with tempfile.TemporaryDirectory() as root:
            db=database(root)
            with db() as c:
                catalog.initialize(c)
                c.execute('CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
                catalog.ingest(c,[edition(1),edition(2)])
                # In the field these works reach the queue as series/unknown (provider_complete kind=series), not as clips.
                c.execute("UPDATE works SET kind='series'")
                works=c.execute('SELECT COUNT(*) FROM works').fetchone()[0]
            self.assertEqual(works,2)
            found={'kind':'series','title':'Schleswig-Holstein Magazin','provider':'IMDb Offline','reference_id':'tt0123456','year':None}
            result={'candidates':[found],'warnings':[],'provider_checks':[{'provider':'IMDb Offline','status':'checked','count':1}]}
            service=catalog_service.Service(db,lambda:{'auto_metadata':True},threading.Event(),Path(root))
            with patch('core.candidates',return_value=result),patch('catalog.auto_choice',return_value=None),\
                 patch('catalog.work_choice',side_effect=lambda m,cands:dict(cands[0])):
                self.assertTrue(service.metadata_once())
            with db() as c:
                rows=c.execute("SELECT next_try FROM works WHERE state='identified'").fetchall()
            self.assertTrue(rows)
            for r in rows:self.assertGreater(r['next_try'],time.time()+29*86400)

class StatusCacheBackgroundTests(unittest.TestCase):
    def function(self,clock,cache,stats,threads):
        source=ast.parse((ROOT/'server.py').read_text())
        body=[x for x in source.body if isinstance(x,ast.FunctionDef) and x.name in ('catalog_status','refresh_catalog_status')]
        class FakeThread:
            def __init__(self,target,**kw):self.target=target
            def start(self):threads.append(self.target)
        ns={'time':types.SimpleNamespace(monotonic=clock),'_STATUS_CACHE':cache,'_STATUS_BUSY':False,
            'catalog':types.SimpleNamespace(stats=stats),'db':lambda:contextlib.nullcontext(None),
            'SERVICE':types.SimpleNamespace(current={}),'threading':types.SimpleNamespace(Thread=FakeThread),
            'diagnostics':types.SimpleNamespace(error=lambda *a,**k:None)}
        exec(compile(ast.Module(body=body,type_ignores=[]),'server.py','exec'),ns)
        return ns
    def test_stale_snapshot_answers_at_once_and_refreshes_in_background(self):
        threads=[];calls=[]
        ns=self.function(lambda:200,(100,{'offers':1}),lambda c:calls.append(1) or {'offers':2},threads)
        self.assertEqual(ns['catalog_status']()['offers'],1)
        self.assertEqual((len(threads),calls),(1,[]))
        self.assertEqual(ns['catalog_status']()['offers'],1)
        self.assertEqual(len(threads),1,'only one refresh at a time')
        threads[0]()
        self.assertEqual(ns['catalog_status']()['offers'],2)
        self.assertFalse(ns['_STATUS_BUSY'])
    def test_empty_cache_still_loads_synchronously(self):
        threads=[]
        ns=self.function(lambda:5,(0,{}),lambda c:{'offers':42},threads)
        self.assertEqual(ns['catalog_status']()['offers'],42)
        self.assertEqual(threads,[])

class RuntimeReportTests(unittest.TestCase):
    def setUp(self):
        runtime_tools._REPORT.update(at=float('-inf'),value=None,busy=False)
    tearDown=setUp
    def test_cached_report_probes_once_then_in_background(self):
        calls=[]
        def fake(refresh=False):
            calls.append(refresh);return {'ffmpeg':{'ok':True},'ffprobe':{'ok':True},'n':len(calls)}
        with patch.object(runtime_tools,'report',side_effect=fake):
            self.assertEqual(runtime_tools.cached_report()['n'],1)
            self.assertEqual(runtime_tools.cached_report()['n'],1)
            self.assertEqual(len(calls),1)
            runtime_tools._REPORT['at']=time.monotonic()-120
            self.assertEqual(runtime_tools.cached_report()['n'],1)   # old answer at once
            for t in threading.enumerate():
                if t.name=='runtime_tools':t.join(5)
            self.assertEqual(runtime_tools.cached_report()['n'],2)
            self.assertEqual(runtime_tools.refreshed_report()['n'],3)
            self.assertEqual(runtime_tools.cached_report()['n'],3)

class NetzkinoHintTests(unittest.TestCase):
    def test_unknown_graphql_error_keeps_a_short_clean_hint(self):
        exc=netzkino.GraphQLCatalogError('SOMETHING_ELSE','Category <b>"krimi-x"</b> not found\n'+'x'*200)
        self.assertEqual(exc.code,'UNKNOWN')
        self.assertNotIn('<',exc.hint);self.assertNotIn('\n',exc.hint)
        self.assertLessEqual(len(exc.hint),80)
        self.assertIn('not found',exc.hint)
        self.assertEqual(netzkino.GraphQLCatalogError('FORBIDDEN').hint,'')

class StateRouteTests(unittest.TestCase):
    def test_state_route_uses_background_tool_report(self):
        src=(ROOT/'server.py').read_text()
        fn=src[src.index("def get_state(self,path):"):src.index("# 0.5.97: Samsung TV Plus")]
        self.assertIn('runtime_tools.cached_report',fn)
        self.assertNotIn('downloads.tool(',fn)
        self.assertIn('state_slow_parts',fn)

if __name__=='__main__':unittest.main()
