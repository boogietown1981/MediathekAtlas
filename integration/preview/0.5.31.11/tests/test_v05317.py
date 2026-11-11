"""No external traffic: ARD-grade, non-destructive Netzkino reference validation."""
import json
import pathlib
import tempfile
import unittest
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import netzkino,netzkino_details,netzkino_enrichment as ne

class ProviderResults(unittest.TestCase):
    movie={'kind':'movie','title':'Die Probe','year':2008,'season':None,'episode':None}
    def candidate(self,provider='TMDB',**updates):
        out={'provider':provider,'reference_id':'12345','title':'Die Probe','kind':'movie',
             'year':2008,'similarity':1,'description':'Ausführliche Referenzhandlung',
             'genres':['Drama'],'cast':['Beispielperson'],'poster':'https://image.tmdb.org/t/p/w500/xyz.jpg',
             'rating':7.2,'votes':55,'runtime_agrees':True,
             'url':'https://signed.example/hls/master.m3u8?token=DO_NOT_EXPORT',
             'http_headers':{'Authorization':'DO_NOT_EXPORT'},'formats':[{'url':'DO_NOT_EXPORT'}]}
        out.update(updates)
        return out

    def test_enrich_only_missing_fields_with_sources(self):
        editorial={'title':'Die Probe','description':'', 'genres':['Thriller'],
                   'cast':[],'directors':[],'writers':[],'poster':'https://www.netzkino.de/poster.jpg'}
        report=ne.analyze(self.movie,editorial,[{'candidates':[self.candidate()], 'provider_checks':[
            {'provider':'TMDB','status':'checked','count':1}]}],match_issues=lambda m,c:[])
        self.assertEqual(report['status'],'candidate')
        self.assertEqual(report['metadata']['description'],'Ausführliche Referenzhandlung')
        self.assertEqual(report['field_sources']['description'],'TMDB')
        self.assertEqual(report['metadata']['genres'],['Thriller'])
        self.assertEqual(report['field_sources']['genres'],'Netzkino')
        self.assertEqual(report['metadata']['rating'],7.2)
        self.assertFalse(report['identity_verified'])
        self.assertFalse(report['download_authorized'])
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(report))
        self.assertEqual(report['provider_checks'][0]['provider'],'TMDB')

    def test_longer_external_description_does_not_replace_netzkino(self):
        note='Kurze offizielle Handlung.'
        other='Eine ausführliche alternative Inhaltsangabe. '+('Zusätzliche historische Angaben. '*20)
        result=ne.analyze(self.movie,{'title':'Die Probe','description':note},
              [{'candidates':[self.candidate(description=other)]}],
              match_issues=lambda m,c:[])
        self.assertEqual(result['metadata']['description'],note)
        self.assertEqual(result['metadata']['reference_description'],other.strip())
        self.assertEqual(result['field_sources']['reference_description'],'TMDB')

    def test_year_and_title_conflicts_do_not_enrich(self):
        r=ne.analyze(self.movie,{'title':'Die Probe','description':''},
            [{'candidates':[self.candidate(year=2020)]}],match_issues=lambda m,c:[])
        self.assertEqual(r['status'],'review')
        self.assertEqual(r['metadata']['description'],'')
        self.assertTrue(r['references'][0]['issues'])
        r=ne.analyze(self.movie,{'title':'Die Probe','description':''},
            [{'candidates':[self.candidate(similarity=.76)]}],match_issues=lambda m,c:[])
        self.assertEqual(r['status'],'review')

    def test_ambiguous_same_provider_reference_blocks_choice(self):
        result=ne.analyze(self.movie,{'title':'Die Probe','description':''},
           [{'candidates':[self.candidate(),self.candidate(reference_id='9999')]}],match_issues=lambda m,c:[])
        self.assertEqual(result['status'],'review')
        self.assertFalse(result['from_reference'])
        self.assertEqual(result['metadata']['description'],'')

    def test_real_series_episode_not_assumed_verified(self):
        meta={'kind':'series','title':'Große Serie','year':None,'season':1,'episode':2}
        series={'provider':'TVDB','reference_id':'938383','title':'Große Serie','kind':'series',
                'year':2008,'similarity':1.,'episode_verified':False,
                'description':'Über die Serie','show_description':'Serieninhalt'}
        report=ne.analyze(meta,{'title':'Große Serie - 2','description':''},
            [{'candidates':[series]}],match_issues=lambda m,c:[])
        self.assertEqual(report['status'],'candidate')
        self.assertEqual(report['metadata']['description'],'')
        self.assertEqual(report['metadata']['series_description'],'Serieninhalt')
        self.assertFalse(report['episode_verified'])
        series.update(episode_verified=True,season=1,episode=2,description='Über die Folge')
        report=ne.analyze(meta,{'title':'Große Serie - 2','description':''},
            [{'candidates':[series]}],match_issues=lambda m,c:[])
        self.assertEqual(report['metadata']['description'],'Über die Folge')
        self.assertTrue(report['episode_verified'])

    def test_one_wrong_episode_does_not_confirm(self):
        meta={'kind':'series','title':'Große Serie','year':None,'season':2,'episode':3}
        series={'provider':'TVDB','reference_id':'938383','title':'Große Serie','kind':'series',
                'similarity':1,'episode_verified':True,'season':1,'episode':3,
                'description':'Andere Folge'}
        report=ne.analyze(meta,{'description':''},[{'candidates':[series]}],match_issues=lambda m,c:[])
        self.assertFalse(report['episode_verified'])
        self.assertEqual(report['metadata']['description'],'')

    def test_provider_id_and_image_safety(self):
        c=ne._candidate(self.candidate(reference_id='https://evil/test'),self.movie,match_issues=lambda m,c:[])
        self.assertIsNone(c)
        c=ne._candidate(self.candidate(poster='https://image.tmdb.org/p?token=secret'),self.movie,
                        match_issues=lambda m,c:[])
        self.assertEqual(c['poster'],'')
        self.assertEqual(ne._image('https://example.net/secret'),'')
        self.assertEqual(ne._ref_id('TVDB','12ab'),'')

    def test_transient_provider_failures_are_generic(self):
        report=ne.analyze(self.movie,{'title':'Die Probe'},
                          [{'candidates':[], 'warnings':['https://api.example/?apikey=secret'],
                            'provider_checks':[{'provider':'Faux','status':'error','count':2}]}],
                          match_issues=lambda m,c:[])
        self.assertEqual(report['status'],'partial')
        self.assertNotIn('secret',json.dumps(report))

class Persistence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.url='https://www.netzkino.de/details/die-probe'
        self.item=netzkino.add(self.root,'Die Probe',self.url)
        self.item_id=self.item['id'] if isinstance(self.item,dict) else self.item

    def test_invalid_local_id_rejected(self):
        with self.assertRaises(ValueError):ne.enrich(self.root,'../catalog.db',{},lookup=lambda *a:None)

    def test_on_demand_caches_and_force_refresh_no_broadcaster_db(self):
        calls=[]
        def lookup(row,meta,config):
            calls.append((row,meta))
            return {'candidates':[{'provider':'TMDB','reference_id':'1224','title':'Die Probe',
                                  'kind':'movie','similarity':1,'year':2008,'description':'Plot'}],
                    'provider_checks':[{'provider':'TMDB','status':'checked','count':1}]}
        a=ne.enrich(self.root,self.item_id,{},lookup=lookup,now=90000)
        b=ne.enrich(self.root,self.item_id,{},lookup=lookup,now=90020)
        self.assertEqual(len(calls),1)
        self.assertFalse(a['cached']);self.assertTrue(b['cached'])
        self.assertEqual(ne.metrics(self.root)['checked'],1)
        self.assertEqual(ne.cached(self.root,self.item_id)['status'],a['status'])
        c=ne.enrich(self.root,self.item_id,{},lookup=lookup,now=90025,force=True)
        self.assertEqual(len(calls),2)
        self.assertFalse(c['cached'])
        self.assertFalse((self.root/'catalog.db').exists())

    def test_cached_report_does_not_survive_source_title_change(self):
        def lookup(row,meta,config):
            return {'candidates':[],'provider_checks':[]}
        ne.enrich(self.root,self.item_id,{},lookup=lookup,now=90000)
        db=netzkino._connect(self.root)
        with db:db.execute('UPDATE netzkino_links SET title=? WHERE id=?',('Ein anderer Titel',self.item_id))
        db.close()
        self.assertEqual(ne.cached(self.root,self.item_id)['status'],'unchecked')

    def test_series_identity_based_on_episode_title(self):
        r=ne._identity({'title':'Acapulco H.E.A.T. Staffel 1 - 1. Pilot','year':1999},
            {'title':'Acapulco H.E.A.T. Staffel 1 - 1. Pilot','year':1999},
            netzkino.classify_media({'kind':'movie','title':'Acapulco H.E.A.T. Staffel 1 - 1. Pilot'}))
        self.assertEqual(r['kind'],'series')
        self.assertEqual(r['title'],'Acapulco H.E.A.T.')
        self.assertIsNone(r['year'])
        self.assertEqual(r['season'],1)
        self.assertEqual(r['episode'],1)

if __name__=='__main__': unittest.main()
