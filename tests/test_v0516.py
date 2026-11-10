"""Fixes from the field diagnosis of 6 Nov 2026 (version 0.5.15)."""
import gzip,io,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog,catalog_service,imdb_archive as imdb,metadata
from test_diagnosis_fixes import database

def offer(title,topic,channel='NDR',n=0,duration=1800):
    return {'title':title,'topic':topic,'description':'','duration':duration,'channel':channel,'url_video':'https://example.org/%s-%d.mp4'%(channel,n)}

class BroadcasterFormatTests(unittest.TestCase):
    """Editions of a magazine identified only by the Mediathek leave the recognition queue."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=database(self.tmp.name)
        with self.db() as c:
            catalog.initialize(c)
            rows=[offer('Sendung vom %d.11.'%i,'Schleswig-Holstein Magazin',n=i) for i in range(3)]+[offer('Folge %d'%i,'In aller Freundschaft',channel='ARD',n=10+i) for i in range(2)]
            catalog.ingest(c,rows)
            for r in c.execute('SELECT * FROM works').fetchall():
                m=json.loads(r['meta']);m.update(kind='series',title=r['topic'],provider='ARD Mediathek',reference_id='x',poster='https://example.org/p.jpg')
                c.execute("UPDATE works SET kind='series',meta=?,state='identified',next_try=0 WHERE id=?",(json.dumps(m),r['id']))
            # A catalogue that already finished the format pass of 0.5.15.
            catalog.set_state(c,'format_cursor','complete')
    def tearDown(self):self.tmp.cleanup()
    def test_magazine_editions_become_format_and_keep_programme_data(self):
        with self.db() as c:
            catalog.assign_formats(c)
            rows=c.execute('SELECT * FROM works').fetchall()
            states={r['topic']:set() for r in rows}
            for r in rows:states[r['topic']].add(r['state'])
            self.assertEqual(states,{'Schleswig-Holstein Magazin':{'format'},'In aller Freundschaft':{'identified'}})
            m=json.loads(c.execute("SELECT meta FROM works WHERE state='format'").fetchone()[0])
            self.assertEqual((m['provider'],m['poster']),('ARD Mediathek','https://example.org/p.jpg'))
            service=catalog_service.Service(self.db,dict,threading.Event(),Path(self.tmp.name))
            # Known scripted shows stay eligible for episode matching, but
            # must no longer occupy the main title-identification queue.
            self.assertIsNone(service.pick(c))
            self.assertEqual(service.pick_episode(c)['topic'],'In aller Freundschaft')
    def test_rule_change_runs_once(self):
        with self.db() as c:
            catalog.assign_formats(c);catalog.assign_formats(c)
            self.assertEqual(catalog.get_state(c,'format_cursor'),'complete');self.assertEqual(catalog.assign_formats(c),(0,0))

class TitleTests(unittest.TestCase):
    def test_language_version_suffixes_removed(self):
        for raw,clean in [('Mapping the World - Cyprus: A Divided Island (Originalversion mit Untertitel)','Mapping the World - Cyprus: A Divided Island'),
                          ('Die Legenden von Paris (4/4) - Zeiten der Veränderung (mit Untertitel)','Die Legenden von Paris (4/4) - Zeiten der Veränderung'),
                          ('Der Pate (OmU)','Der Pate'),('Film (2020)','Film (2020)')]:
            self.assertEqual(catalog.cleaned(raw),clean)
    def test_arte_section_is_no_series_and_prefix_is_used(self):
        seen=[]
        def fn(name):
            def run(row,meta,key,kind,title):seen.append((name,kind,title));return []
            return run
        with patch('imdb_archive.ACTIVE',None),patch('metadata.tvdb_candidates',side_effect=fn('TVDB')),patch('metadata.tmdb_candidates',side_effect=fn('TMDB')),patch('metadata.wikidata',return_value=None):
            metadata.candidates({'title':'Mapping the World - Cyprus (Originalversion mit Untertitel)','topic':'Politics and society - Insights'},{'title':'Mapping the World - Cyprus (Originalversion mit Untertitel)','kind':'unknown'},{'tvdb':'k','tmdb':'k'})
        titles={t for _,_,t in seen}
        self.assertNotIn('Politics and society - Insights',titles)
        self.assertIn(('TVDB','series','Mapping the World'),seen);self.assertIn(('TMDB','movie','Mapping the World - Cyprus'),seen)
        self.assertFalse(catalog.format_contribution({'kind':'unknown'},offer('Clip','Culture - Pop culture',duration=200),9))

class ProviderTests(unittest.TestCase):
    def test_paused_omdb_does_not_defer_after_imdb_snapshot(self):
        class Snapshot:
            updated=1
            def candidates(self,row,meta):return []
        with patch('imdb_archive.ACTIVE',Snapshot()),patch('metadata.tmdb_candidates',return_value=[]),patch('metadata.omdb_status',return_value={'paused':True}),patch('metadata.wikidata',return_value=None):
            r=metadata.candidates({'title':'Unbekannt'},{'title':'Unbekannt','kind':'movie'},{'tmdb':'k','omdb':'k'})
        self.assertEqual(r['deferred_providers'],[]);self.assertIn({'provider':'OMDb','status':'paused','count':0},r['provider_checks'])
        with patch('imdb_archive.ACTIVE',None),patch('metadata.tmdb_candidates',return_value=[]),patch('metadata.omdb_status',return_value={'paused':True}),patch('metadata.wikidata',return_value=None):
            r=metadata.candidates({'title':'Unbekannt'},{'title':'Unbekannt','kind':'movie'},{'tmdb':'k','omdb':'k'})
        self.assertEqual(r['deferred_providers'],['OMDb'])
    def test_oversized_wikidata_answer_is_no_hit(self):
        metadata._WD_CACHE.clear()
        with patch('core.wikidata_lookup',side_effect=ValueError('Metadatenantwort zu groß')):
            self.assertIsNone(metadata.wikidata('Tiere','movie',None))
        with patch('core.wikidata_lookup',side_effect=ValueError('anders')):
            with self.assertRaises(ValueError):metadata.wikidata('Andere','movie',None)

class ImdbResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.a=imdb.Archive(Path(self.tmp.name),threading.Event())
        self.data={k:gzip.compress(('\t'.join(imdb.HEADERS[k])+'\n').encode())+os.urandom(3000) for k in imdb.HEADERS}
    def tearDown(self):self.tmp.cleanup()
    def test_interrupted_download_resumes_with_range(self):
        calls=[]
        class Response(io.BytesIO):
            def __init__(self,b,status,length):super().__init__(b);self.status=status;self.headers={'Content-Length':str(length)}
        state={'fail':True}
        def open_url(url,headers=None):
            kind=next(k for k,v in imdb.FILES.items() if url.endswith(v));data=self.data[kind];calls.append((kind,(headers or {}).get('Range')))
            if headers:
                start=int(headers['Range'][6:-1]);return Response(data[start:],206,len(data)-start)
            if kind=='akas' and state['fail']:
                state['fail']=False
                class Broken(Response):
                    def read(self,n=-1):
                        if self.tell()>=500:raise TimeoutError('The read operation timed out')
                        return super().read(500)
                return Broken(data,200,len(data))
            return Response(data,200,len(data))
        with patch('core.open_url',side_effect=open_url),patch('imdb_archive.build',side_effect=ValueError('stop after download')):
            # A transient read timeout is retried immediately and the 500-byte
            # partial transfer is resumed in the same update, not next hour.
            with patch.object(self.a.stop,'wait',return_value=False):
                self.a.update()
            self.assertEqual(self.a.failures,1);self.assertGreater(self.a.retry_at,time.time()+3000)
            self.assertFalse((self.a.root/'akas.tsv.gz.part').exists())
            self.assertTrue((self.a.root/'basics.tsv.gz').exists())
            self.assertEqual((self.a.root/'akas.tsv.gz').read_bytes(),self.data['akas'])
            self.assertEqual(calls.count(('akas','bytes=500-')),1)
            # When import (not download) fails, all seven completed datasets
            # must survive for the next attempt without another network call.
            calls.clear();self.a.update()
        self.assertEqual(calls,[])
        self.assertEqual(self.a.failures,2);self.assertGreater(self.a.retry_at,time.time()+7000)

if __name__=='__main__':unittest.main()
