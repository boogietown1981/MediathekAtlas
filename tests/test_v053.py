import json,os,re,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import catalog,metadata
import test_nas_packages as nas
call,free_port,wait_http=nas.call,nas.free_port,nas.wait_http

class GenreSpellingTests(unittest.TestCase):
    def test_variants_fold_to_one_name(self):
        same={'Dokumentation':['Dokumentarfilm','Documentary','dokumentation','Doku'],'Drama':['Filmdrama','Dramaserie','drama'],
              'Komödie':['Filmkomödie','Comedy','Comedy-Serie','komödie'],'Krimi':['Kriminalfilm','Krimiserie','Crime','KRIMI'],
              'Romantik':['Liebesfilm','Romance'],'Mystery':['Mysteryfilm'],'Biografie':['Biography','Biographie'],
              'Kinder & Familie':['Familie','Kinder und Familie','Family','Kids'],'Science-Fiction':['Science Fiction','science-fiction','Sci-Fi','Science-Fiction-Film'],
              'Historie':['History','Historienfilm'],'Animation':['Animationsfilm','Zeichentrickfilm'],'Talk':['Talk-Show','Talkshow']}
        for name,variants in same.items():
            for v in variants:self.assertEqual(metadata.genre_names(v),[name],v)
    def test_compound_provider_genres_split_and_media_words_drop(self):
        self.assertEqual(metadata.genres(['Action & Adventure','Sci-Fi & Fantasy']),['Abenteuer','Action','Fantasy','Science-Fiction'])
        self.assertEqual(metadata.genres(['Fernsehserie','Spielfilm','N/A','']),[])
        self.assertEqual(metadata.genres(['Kinder & Familie']),['Kinder & Familie'])
        self.assertEqual(metadata.genres(['heimatfilm']),['Heimatfilm'])

    def test_stored_genres_are_merged_once(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
        for wid,gs in (('a',['Dokumentarfilm','Biography']),('b',['Dokumentation']),('c',['Kriminalfilm','Krimi'])):
            c.execute('INSERT INTO works(id,title,kind,meta) VALUES(?,?,?,?)',(wid,wid,'movie',json.dumps({'genres':gs})))
            for g in gs:c.execute('INSERT INTO work_genres VALUES(?,?)',(wid,g))
        c.execute('INSERT INTO series_templates VALUES(?,?,?,?)',('t','TMDB','1',json.dumps({'genres':['Krimiserie']})))
        catalog.initialize(c)
        self.assertEqual(sorted(r[0] for r in c.execute('SELECT DISTINCT genre FROM work_genres')),['Biografie','Dokumentation','Krimi'])
        self.assertEqual(json.loads(c.execute("SELECT meta FROM works WHERE id='a'").fetchone()[0])['genres'],['Biografie','Dokumentation'])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM work_genres WHERE work_id='c'").fetchone()[0],1)
        self.assertEqual(json.loads(c.execute('SELECT meta FROM series_templates').fetchone()[0])['genres'],['Krimi'])
        c.execute("INSERT INTO work_genres VALUES('b','Filmdrama')");catalog.initialize(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM work_genres WHERE genre='Filmdrama'").fetchone()[0],1,'runs once')

class NasFileAccessTests(unittest.TestCase):
    def test_finished_download_is_served_over_http_with_login(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(os.path.realpath(d));home=d/'home';home.mkdir();share=d/'share';share.mkdir()
            film=share/'Der Himmel über Berlin (1987).mkv';film.write_bytes(bytes(range(256))*40)
            c=sqlite3.connect(home/'catalog.db')
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            for jid,state in (('fertig','done'),('laeuft','queued')):
                c.execute('INSERT INTO jobs VALUES(?,?,?)',(jid,json.dumps({'id':jid,'state':state,'path':str(film),'target':str(film),'metadata':{'title':'x'},'source':{}}),state))
            c.commit();c.close()
            (home/'initial-password').write_text('nas-passwort\n')
            port=free_port()
            env={**nas.NasPackageTests.env,'MEDIATHEKATLAS_HOME':str(home),'MEDIATHEKATLAS_LISTEN':'127.0.0.1','MEDIATHEKATLAS_LOGIN':'1','MEDIATHEKATLAS_PORT':str(port),'MEDIATHEKATLAS_DOWNLOAD_DIR':str(share)}
            p=subprocess.Popen([sys.executable,'server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                wait_http(port)
                self.assertEqual(call(port,'GET','/api/download-file?id=fertig&token=x')[0],401)
                cookie=call(port,'POST','/api/login',{'password':'nas-passwort'})[2].split(';')[0]
                token=re.search(r'name="atlas-token" content="([^"]+)"',call(port,'GET','/',headers={'Cookie':cookie})[1]).group(1)
                self.assertEqual(call(port,'GET','/api/download-file?id=fertig&token=falsch',headers={'Cookie':cookie})[0],403)
                self.assertEqual(call(port,'GET','/api/download-file?id=laeuft&token='+token,headers={'Cookie':cookie})[0],404)
                import http.client
                h=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
                h.request('GET','/api/download-file?id=fertig&token='+token,headers={'Cookie':cookie});r=h.getresponse();body=r.read()
                self.assertEqual((r.status,body),(200,film.read_bytes()))
                self.assertIn("filename*=UTF-8''Der%20Himmel%20%C3%BCber%20Berlin%20%281987%29.mkv",r.getheader('Content-Disposition'))
                self.assertTrue(r.getheader('Content-Disposition').startswith('attachment'))
                h.request('GET','/api/download-file?id=fertig&inline=1&token='+token,headers={'Cookie':cookie,'Range':'bytes=100-199'});r=h.getresponse();body=r.read()
                self.assertEqual((r.status,body,r.getheader('Content-Range')),(206,film.read_bytes()[100:200],'bytes 100-199/10240'))
                h.request('GET','/api/download-file?id=fertig&token='+token,headers={'Cookie':cookie,'Range':'bytes=-10'});r=h.getresponse();body=r.read()
                self.assertEqual((r.status,body),(206,film.read_bytes()[-10:]))
                h.request('GET','/api/download-file?id=fertig&token='+token,headers={'Cookie':cookie,'Range':'bytes=99999-'});r=h.getresponse();r.read()
                self.assertEqual(r.status,416);h.close()
                film.unlink()
                self.assertEqual(call(port,'GET','/api/download-file?id=fertig&token='+token,headers={'Cookie':cookie})[0],404)
            finally:p.terminate();p.wait(10)

if __name__=='__main__':unittest.main()
