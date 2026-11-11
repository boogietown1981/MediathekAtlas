"""Regression checks for category failures, partial coverage, UI and diagnostics."""
import json, pathlib, sqlite3, sys, tempfile, unittest, urllib.error
from unittest.mock import patch

HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import netzkino
import diagnostic_extensions
import apply_05314


def film(identifier, title, slug):
    return {'contentMovie':{'id':identifier,'title':title,'slug':slug,'productionYear':2020,
            'flags':['genres:Drama','properties:avod'],'fskRating':12,
            'coverImage':{'masterUrl':'https://www.netzkino.de/image.jpg'}},'contentSeries':None}

def homepage(n=8):
    cats=[{'slug':'category-'+str(i),'title':'Category '+str(i),
           'content':{'nodes':[film('a'+str(i),'Home title '+str(i),'home-'+str(i))]}}
          for i in range(n)]
    return {'parentCategory':{'title':'Frontpage','subcategories':{'nodes':cats}},
            'featured':{'content':{'nodes':[]}}}

class Netzkino05314Tests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=pathlib.Path(t.name)

    def test_many_failed_categories_leave_usable_partial_catalogue(self):
        def fetch(op, var):
            if op=='AllContent':return homepage(9)
            if var['slug']=='category-0':return {'category':{'content':{'nodes':[film('new','New film','new-film')]}}}
            raise ValueError('GraphQL category unavailable')
        result=netzkino.sync(self.root, graphql_fetch=fetch, now=100000)
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['partial'])
        self.assertEqual((result['categories_checked'],result['category_errors']),(9,8))
        self.assertEqual(result['count'],10)
        status=netzkino.state(self.root)
        self.assertEqual(status['last_result'],'partial')
        self.assertEqual(status['last_complete_success'],0)
        self.assertEqual(status['category_error_types'],{'invalid_payload':8})
        self.assertEqual(status['catalog_count'],10)
        self.assertGreater(status['next_attempt'],100000)
        diagnostic=diagnostic_extensions.collect(self.root)['netzkino']
        self.assertEqual(diagnostic['category_error_types'],{'invalid_payload':8})
        self.assertNotIn('category-8',str(diagnostic))

    def test_empty_category_is_not_error(self):
        def fetch(op,vars):return homepage(3) if op=='AllContent' else {'category':{'content':None}}
        result=netzkino.sync(self.root,graphql_fetch=fetch,now=110000)
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['partial'],result)
        self.assertEqual(result['categories_empty'],3)
        self.assertEqual(result['category_errors'],0)
        self.assertEqual(netzkino.state(self.root)['last_complete_success'],110000)

    def test_429_stops_repeated_category_calls_and_preserves_home(self):
        calls=[]
        def fetch(op,var):
            if op=='AllContent':return homepage(30)
            calls.append(var['slug'])
            raise urllib.error.HTTPError('https://data.netzkino.de/netzkino/graphql',429,'Rate Limited',{},None)
        result=netzkino.sync(self.root,graphql_fetch=fetch,now=120000)
        self.assertTrue(result['ok'])
        self.assertTrue(result['partial'])
        self.assertEqual(len(calls),1)
        self.assertEqual(result['count'],30)
        self.assertEqual(result['error_types'],{'http_429':1})
        self.assertEqual(netzkino.state(self.root)['last_http_status'],429)

    def test_failed_home_does_not_erase_partial_or_manual(self):
        netzkino.add(self.root,'My saved film','https://www.netzkino.de/details/my-film')
        netzkino.sync(self.root,graphql_fetch=lambda op,var:homepage(3) if op=='AllContent' else {'category':None},now=130000)
        old=netzkino.count_links(self.root)
        result=netzkino.sync(self.root,graphql_fetch=lambda *x: (_ for _ in ()).throw(ValueError('down')),now=140000)
        self.assertFalse(result['ok'])
        self.assertEqual(netzkino.count_links(self.root),old)
        self.assertEqual(netzkino.state(self.root)['last_result'],'failed')
        self.assertEqual(netzkino.state(self.root)['last_success'],130000)
        self.assertEqual(netzkino.list_links(self.root,origin='manual')[0]['title'],'My saved film')

    def test_graphql_errors_never_persist_provider_text(self):
        exc=netzkino.GraphQLCatalogError('some-unknown-raw-server-info')
        self.assertEqual(exc.code,'UNKNOWN')
        self.assertNotIn('some-unknown',str(exc))

    def test_ui_patch_keeps_archive_and_net_zones_separate(self):
        # Patch checker requires both sets of real APIs and UI anchors.
        # No destructive application-side DB updates are involved.
        import re
        source=(HERE/'apply_05314.py').read_text()
        self.assertIn('id="archive-full-mode"',source)
        self.assertIn('id="netzkino"',source)
        self.assertIn('#portals[data-platform="netzkino"] > #archive-full-mode',source)
        self.assertIn('#portals[data-platform="netzkino"] > .portal-dashboard',source)
        self.assertIn('#portals[data-platform="archive"] > #netzkino',source)
        self.assertIn('window.MediathekAtlasNetzkino?.refresh?.()',source)
        self.assertNotIn('DROP TABLE',source)

if __name__=='__main__':unittest.main()
