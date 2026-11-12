"""Ported from the 0.5.31.x integration kit (ran against stale module copies there). Tests for 0.5.31.2 public Netzkino catalogue extraction and offline bootstrap."""
import os,tempfile,unittest,json
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import netzkino


def item(i,title,slug,flag='properties:avod',series=False):
    return {'contentMovie':None if series else {'id':i,'title':title,'slug':slug,
      'productionYear':2016,'fskRating':12,'flags':['genres:Drama',flag],
      'coverImage':{'masterUrl':'https://cdn.example.invalid/film.jpg'}, 'genres':{'nodes':[]}},
     'contentSeries': {'id':i,'title':title,'slug':slug,'productionYear':2016,'flags':['genres:Drama',flag]}
        if series else None}

def home():
    return {'parentCategory':{'title':'Frontpage','subcategories':{'nodes':[
      {'title':'Neu bei Netzkino','slug':'neu-frontpage',
        'content':{'nodes':[item('first','Ein Filmtitel','film-a')]}}]},
      },'featured':{'content':{'nodes':[]}}}

def cat():
    return {'category':{'title':'Neu bei Netzkino',
       'content':{'nodes':[item('first','Ein Filmtitel','film-a'),
                            item('second','Eine Serie','serie-b',series=True)]}}}

class GraphQLCatalogTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)

    def test_persisted_queries_only_and_url_safety(self):
        url=netzkino.graphql_url('AllContent',{'parentSlug':'frontpage'})
        self.assertTrue(url.startswith('https://data.netzkino.de/netzkino/graphql?'))
        with self.assertRaises(ValueError):netzkino.graphql_url('VideoData',{'contentId':'film'})
        # Since 0.5.31.6 MovieDetails is an allowed read-only detail query (no playback query).
        self.assertIn('operationName=MovieDetails',netzkino.graphql_url('MovieDetails',{}))
        with self.assertRaises(ValueError):netzkino._GraphQLRedirect().redirect_request(None,None,302,'',{},'https://evil.example/v')

    def test_graphql_categorization_and_dedup_and_no_direct_download(self):
        def fetch(op,var):return home() if op=='AllContent' else cat()
        result=netzkino.sync(self.root,graphql_fetch=fetch,now=120000)
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['new'],2)
        self.assertEqual(result['categories'],1+len(netzkino._SEED_CATEGORIES))  # 0.5.34: category tree roots + known full lists
        self.assertEqual(netzkino.count_links(self.root),2)
        films=netzkino.list_links(self.root,query='Ein Filmtitel')
        self.assertEqual(films[0]['url'],'https://www.netzkino.de/details/film-a')
        self.assertEqual(films[0]['genres'],'Drama')
        self.assertEqual(films[0]['year'],2016)
        self.assertEqual(films[0]['access_hint'],'AVOD (Hinweis)')
        self.assertEqual(netzkino.list_links(self.root,query='Eine Serie')[0]['kind'],'series')
        self.assertNotIn('hls',json.dumps(films))
        self.assertEqual(netzkino.state(self.root)['categories_checked'],1+len(netzkino._SEED_CATEGORIES))
        again=netzkino.sync(self.root,graphql_fetch=fetch,now=130000)
        self.assertTrue(again['ok'],again)
        self.assertEqual(again['new'],0)
        self.assertEqual(again['unchanged'],2)

    def test_live_failure_preserves_prior_and_reports(self):
        fetch=lambda op,var:home() if op=='AllContent' else cat()
        netzkino.sync(self.root,graphql_fetch=fetch,now=120000)
        def fail(*_):raise ValueError('Netzkino hat die Katalogabfrage abgewiesen oder geändert.')
        result=netzkino.sync(self.root,graphql_fetch=fail,now=130000)
        self.assertFalse(result['ok'])
        self.assertEqual(netzkino.count_links(self.root),2)
        self.assertEqual(netzkino.state(self.root)['last_success'],120000)
        self.assertGreater(netzkino.state(self.root)['next_attempt'],130000)

    def test_manual_title_wins_over_catalogue(self):
        url='https://www.netzkino.de/details/film-a'
        netzkino.add(self.root,'Manueller Titel',url)
        netzkino.sync(self.root,graphql_fetch=lambda op,v: home() if op=='AllContent' else cat(),now=120000)
        matches=netzkino.list_links(self.root,query='Manueller Titel')
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['origin'],'manual')
        self.assertEqual(matches[0]['year'],2016)

    def test_snapshot_bootstrap_only_in_application_root(self):
        self.assertEqual(netzkino.count_links(self.root),0)
        with patch.dict(os.environ,{'MEDIATHEKATLAS_HOME':str(self.root)}):
            st=netzkino.state(self.root)
            self.assertEqual(st['snapshot_seed_count'],449)
            self.assertEqual(st['catalog_count'],449)
            self.assertEqual(st['last_success'],0)
            self.assertEqual(netzkino.list_links(self.root,query='Darkweb')[0]['source'],'har_snapshot')

    def test_snapshot_contains_no_private_session_or_video_data(self):
        path=Path(netzkino.__file__).parent/'assets'/'netzkino_seed.json'
        contents=path.read_text('utf-8')
        for private in ('"cookies"','"headers"','"sessionId"','"Authorization"','"dashUrl"','"hlsUrl"','"videoSource"'):
            self.assertNotIn(private,contents)
        self.assertEqual(len(json.loads(contents)['items']),449)

if __name__=='__main__':unittest.main()
