import http.client,json,os,re,shutil,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import catalog,streaming
import test_nas_packages as nas

def database():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
    c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)');c.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT)')
    return c

def offer(c,oid,row,meta=None,work='w1'):
    c.execute('INSERT OR REPLACE INTO works(id,title,kind,meta) VALUES(?,?,?,?)',(work,(meta or {}).get('title','x'),(meta or {}).get('kind','movie'),json.dumps(meta or {})))
    c.execute('INSERT INTO offers(id,work_id,payload,special,rank,seen) VALUES(?,?,?,?,?,?)',(oid,work,json.dumps(row),'',0,0))

class ResolveTests(unittest.TestCase):
    def test_direct_file_is_preferred_over_hls_and_capped_at_1080p(self):
        c=database()
        offer(c,'o1',{'title':'Film','duration':5400,'url_video_hd':'https://cdn.example/film_2160p.mp4','url_video':'https://cdn.example/film_1080p.mp4','url_video_low':'https://cdn.example/master.m3u8'},{'title':'Der Film','kind':'movie','year':1999})
        s=streaming.resolve(c,offer='o1')
        self.assertEqual((s['kind'],s['url'],s['hls'],s['title'],s['duration']),('url','https://cdn.example/film_1080p.mp4',False,'Der Film (1999)',5400))
        p=streaming.plan(s);self.assertEqual((p['mode'],p['origin']),('direct','online'))

    def test_hls_only_needs_the_remux_stream_and_dash_is_rejected(self):
        c=database()
        offer(c,'o1',{'title':'Folge','url_video':'https://cdn.example/master.m3u8?x=1'},{'title':'Serie','kind':'series','season':1,'episode':2,'episode_title':'Pilot'})
        s=streaming.resolve(c,offer='o1')
        self.assertTrue(s['hls']);self.assertEqual(s['title'],'Serie · S01E02 · Pilot');self.assertEqual(streaming.plan(s)['mode'],'remux')
        offer(c,'o2',{'title':'D','url_video':'https://cdn.example/a.mpd'},work='w2')
        with self.assertRaisesRegex(ValueError,'keinen abspielbaren'):streaming.resolve(c,offer='o2')
        offer(c,'o3',{'title':'F','url_video':'file:///etc/passwd'},work='w3')
        with self.assertRaisesRegex(ValueError,'keinen abspielbaren'):streaming.resolve(c,offer='o3')

    def test_finished_local_download_wins_and_unfinished_job_is_refused(self):
        c=database()
        with tempfile.TemporaryDirectory() as d:
            film=Path(d)/'Film.mkv';film.write_bytes(b'x')
            offer(c,'o1',{'title':'Film','url_video':'https://cdn.example/a.mp4'},{'title':'Film','kind':'movie'})
            c.execute('INSERT INTO downloaded_items VALUES(?,?,?)',('w1',str(film),0))
            self.assertEqual(streaming.resolve(c,offer='o1')['path'],str(film))
            film.unlink();self.assertEqual(streaming.resolve(c,offer='o1')['kind'],'url','moved file falls back to the stream')
            c.execute('INSERT INTO jobs VALUES(?,?,?)',('j1',json.dumps({'path':str(film),'metadata':{}}),'queued'))
            with self.assertRaisesRegex(ValueError,'abgeschlossene'):streaming.resolve(c,job='j1')
        c.execute('INSERT INTO records VALUES(?,?)',('r1',json.dumps({'title':'Suche','url_video':'https://cdn.example/b.mp4'})))
        self.assertEqual(streaming.resolve(c,offer='r1')['url'],'https://cdn.example/b.mp4')
        with self.assertRaises(ValueError):streaming.resolve(c,offer='fehlt')

    def test_plan_for_local_files(self):
        src={'kind':'file','path':'/x/Film.mkv','title':'Film','duration':0}
        info=lambda v,a:{'format':{'duration':'61.5'},'streams':[{'codec_type':'video','codec_name':v},{'codec_type':'audio','codec_name':a}]}
        self.assertEqual(streaming.plan(src,info('h264','aac'))['mode'],'remux')
        self.assertEqual(streaming.plan({**src,'path':'/x/Film.mp4'},info('h264','aac'))['mode'],'direct')
        self.assertEqual(streaming.plan({**src,'path':'/x/Film.mp4'},info('h264','ac3'))['mode'],'remux')
        self.assertEqual(streaming.plan(src,info('h264','aac'))['duration'],61.5)
        with self.assertRaisesRegex(ValueError,'mpeg2video'):streaming.plan(src,info('mpeg2video','mp2'))
        self.assertFalse(streaming.audio_copy(src,info('h264','mp2')));self.assertEqual(streaming.audio_copy(src,info('h264','aac')),'aac');self.assertIs(streaming.audio_copy(src,info('h264','opus')),True)

    def test_command_seeks_before_input_and_writes_fragmented_mp4(self):
        with unittest.mock.patch('streaming.tool',return_value='/bin/ffmpeg'):
            args=streaming.command({'kind':'url','url':'https://cdn.example/m.m3u8'},125.5)
            self.assertLess(args.index('-ss'),args.index('-i'));self.assertIn('-reconnect',args);self.assertIn('aac_adtstoasc',args);self.assertEqual(args[-3:],['-f','mp4','pipe:1'])
            args=streaming.command({'kind':'file','path':'/x/a.mkv'},0,audio_copy=False)
            self.assertNotIn('-ss',args);self.assertNotIn('-reconnect',args);self.assertIn('aac',args)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg fehlt')
class StreamEndpointTests(unittest.TestCase):
    def test_mkv_download_is_streamed_as_mp4_from_a_position(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(os.path.realpath(d));home=d/'home';home.mkdir();film=d/'Film (2020).mkv'
            r=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc=duration=6:size=160x120:rate=25','-f','lavfi','-i','sine=duration=6','-c:v','libx264','-g','25','-c:a','mp2','-y',str(film)],capture_output=True)
            if r.returncode:self.skipTest('ffmpeg ohne libx264')
            c=sqlite3.connect(home/'catalog.db');c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            c.execute('INSERT INTO jobs VALUES(?,?,?)',('fertig',json.dumps({'id':'fertig','path':str(film),'metadata':{'title':'Film','kind':'movie','year':2020},'source':{}}),'done'));c.commit();c.close()
            port=nas.free_port()
            env={**nas.NasPackageTests.env,'MEDIATHEKATLAS_HOME':str(home),'MEDIATHEKATLAS_PORT':str(port),'MEDIATHEKATLAS_DOWNLOAD_DIR':str(d)}
            p=subprocess.Popen([sys.executable,'server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                nas.wait_http(port)
                token=re.search(r'name="atlas-token" content="([^"]+)"',nas.call(port,'GET','/')[1]).group(1)
                status,body,_=nas.call(port,'GET','/api/play?job=fertig',headers={'X-Atlas-Token':token})
                info=json.loads(body);self.assertEqual(status,200,body)
                self.assertEqual((info['mode'],info['origin'],info['title'],round(info['duration'])),('remux','local','Film (2020)',6))
                self.assertEqual(nas.call(port,'GET','/api/stream?job=fertig&token=falsch')[0],403)
                self.assertEqual(nas.call(port,'GET','/api/play?job=fehlt',headers={'X-Atlas-Token':token})[0],404)
                h=http.client.HTTPConnection('127.0.0.1',port,timeout=30)
                h.request('GET',info['src']+'&t=2&session=a&token='+token);resp=h.getresponse();data=resp.read();h.close()
                self.assertEqual((resp.status,resp.getheader('Content-Type')),(200,'video/mp4'));self.assertEqual(data[4:8],b'ftyp')
                out=d/'out.mp4';out.write_bytes(data)
                probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)],capture_output=True).stdout)
                self.assertEqual(sorted(s['codec_name'] for s in probe['streams']),['aac','h264'])
                self.assertAlmostEqual(float(probe['format']['duration']),4,delta=1.2)
                self.assertEqual(nas.call(port,'GET','/player.js')[0],200)
            finally:p.terminate();p.wait(10)

import unittest.mock
if __name__=='__main__':unittest.main()
