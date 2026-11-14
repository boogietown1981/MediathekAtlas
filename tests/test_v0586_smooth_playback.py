"""0.5.86: smooth playback in the own player (Björn, 13.11.2026: stutters, picture and sound out of step).

- range_relay loads online files in ranged pieces (YouTube serves open-ended requests at playback speed)
- no output '-ss 0' any more: picture starts exactly at the seek position instead of up to a GOP later
- the start/stall reserve (GATE) no longer applies to streams converted by MediathekAtlas
"""
import http.server,json,re,shutil,socketserver,subprocess,sys,tempfile,threading,time,unittest,urllib.request
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import range_relay,streaming,youtube_downloads as yd


class _Throttled(http.server.BaseHTTPRequestHandler):
    """Imitates googlevideo: a request over 10 MB or without an end is slowed down after the first MB."""
    protocol_version='HTTP/1.1'
    data=b'';rate=200_000;seen=[]
    def log_message(self,*a):pass
    def do_GET(self):
        size=len(self.data);spec=self.headers.get('Range');a,b=0,size-1
        if spec:
            m=re.match(r'bytes=(\d+)-(\d*)',spec);a=int(m[1]);b=min(size-1,int(m[2])) if m[2] else size-1
        self.seen.append(spec)
        slow=b-a+1>10*2**20 or not (spec and re.match(r'bytes=\d+-\d+$',spec))
        self.send_response(206 if spec else 200);self.send_header('Content-Length',str(b-a+1))
        if spec:self.send_header('Content-Range','bytes %d-%d/%d'%(a,b,size))
        self.send_header('Content-Type','video/mp4');self.end_headers()
        pos=a;t0=time.monotonic();sent=0
        try:
            while pos<=b:
                chunk=self.data[pos:min(b+1,pos+65536)];self.wfile.write(chunk);pos+=len(chunk);sent+=len(chunk)
                if slow and sent>2**20:
                    due=t0+(sent-2**20)/self.rate
                    if due>time.monotonic():time.sleep(due-time.monotonic())
        except (BrokenPipeError,ConnectionResetError):pass


class _Server(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True


class RelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Throttled.data=bytes(range(256))*(12*4096)   # 12 MB
        cls.server=_Server(('127.0.0.1',0),_Throttled)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url='http://127.0.0.1:%d/videoplayback'%cls.server.server_address[1]
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()

    def setUp(self):
        _Throttled.seen=[]
        self.relay=range_relay.Relay()
    def tearDown(self):
        self.relay.close()

    def test_pieces_cover_the_range_with_a_short_first_piece(self):
        p=range_relay.pieces(0,10*2**20-1)
        self.assertEqual(p[0],(0,2**20-1))
        self.assertEqual(p[-1][1],10*2**20-1)
        self.assertTrue(all(b-a+1<=range_relay.PIECE for a,b in p))
        self.assertTrue(all(p[i][1]+1==p[i+1][0] for i in range(len(p)-1)))
        self.assertEqual(range_relay.pieces(5,5),[(5,5)])

    def test_whole_file_arrives_fast_and_complete(self):
        local=self.relay.local(self.url,{'User-Agent':'Test-UA'})
        self.assertTrue(local.startswith('http://127.0.0.1:'))
        self.assertEqual(self.relay.local(self.url,{'User-Agent':'Test-UA'}),local)   # same token again
        t0=time.monotonic()
        with urllib.request.urlopen(local,timeout=30) as r:
            body=r.read();self.assertEqual(r.headers['Accept-Ranges'],'bytes')
        took=time.monotonic()-t0
        self.assertEqual(body,_Throttled.data)
        # 11 MB at 200 kB/s would take about a minute in one throttled request
        self.assertLess(took,10)
        self.assertTrue(all(re.fullmatch(r'bytes=\d+-\d+',s or '') for s in _Throttled.seen))

    def test_range_requests_and_errors(self):
        local=self.relay.local(self.url)
        req=urllib.request.Request(local,headers={'Range':'bytes=5000000-5000099'})
        with urllib.request.urlopen(req,timeout=30) as r:
            self.assertEqual(r.status,206)
            self.assertEqual(r.headers['Content-Range'],'bytes 5000000-5000099/%d'%len(_Throttled.data))
            self.assertEqual(r.read(),_Throttled.data[5000000:5000100])
        req=urllib.request.Request(local,headers={'Range':'bytes=-10'})
        with urllib.request.urlopen(req,timeout=30) as r:self.assertEqual(r.read(),_Throttled.data[-10:])
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(local,headers={'Range':'bytes=99999999-'}),timeout=10)
        self.assertEqual(e.exception.code,416)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(local.rsplit('/',1)[0]+'/'+'x'*24,timeout=10)
        self.assertEqual(e.exception.code,404)

    def test_expired_address_is_not_retried(self):
        calls=[]
        def opener(req,timeout):
            calls.append(req.get_header('Range'))
            raise urllib.error.HTTPError(req.full_url,403,'Forbidden',{},None)
        entry=range_relay._Entry('https://x.googlevideo.com/videoplayback',{})
        with self.assertRaises(range_relay.UpstreamError):range_relay.fetch(entry,0,0,opener,sleep=lambda s:None)
        self.assertEqual(len(calls),1)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg fehlt')
class SeekTests(unittest.TestCase):
    """A seek must not start the picture later than the sound (measured 3.6 s before 0.5.86)."""
    def test_picture_and_sound_start_together_after_a_seek(self):
        with tempfile.TemporaryDirectory() as d:
            v,a,out=Path(d)/'v.mp4',Path(d)/'a.m4a',Path(d)/'out.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=25','-t','40','-c:v','libx264','-preset','ultrafast','-g','120','-an',str(v)],check=True)
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440','-t','40','-c:a','aac',str(a)],check=True)
            src={'kind':'url','url':str(v),'audio_url':str(a),'hls':False,'remux':True,'title':'t'}
            args=streaming.command(src,30.0)
            self.assertNotIn('0',[args[i+1] for i,x in enumerate(args) if x=='-ss'])
            self.assertIn('-max_interleave_delta',args)
            # same output options, inputs as local files (the HTTP reconnect options belong to addresses)
            cmd=[streaming.tool('ffmpeg') or 'ffmpeg','-nostdin','-v','error','-ss','30','-i',str(v),'-ss','30','-i',str(a)]+args[args.index('-map'):]
            cmd[-1]=str(out);cmd.insert(-1,'-y')
            subprocess.run(cmd,check=True,timeout=60)
            info=json.loads(subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,start_time','-of','json',str(out)],capture_output=True,text=True).stdout)
            start={s['codec_type']:float(s['start_time']) for s in info['streams']}
            # picture from the keyframe before 30 s (negative, decoded silently), sound from 30 s
            self.assertLessEqual(start['video'],0.0)
            self.assertAlmostEqual(start['audio'],0.0,places=1)


class YouTubeSourceTests(unittest.TestCase):
    def test_json_output_gives_addresses_headers_and_height(self):
        out=json.dumps({'requested_formats':[
            {'url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=136','height':720,'http_headers':{'User-Agent':'UA/1','Accept':'*/*','Cookie':'no','Sec-Fetch-Mode':'navigate'}},
            {'url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=140','height':None}]})
        urls,headers,height=yd._stream_urls(out+'\n')
        self.assertEqual([u[-8:] for u in urls],['itag=136','itag=140'])
        self.assertEqual(headers,{'User-Agent':'UA/1','Accept':'*/*'})    # no cookies, nothing else
        self.assertEqual(height,720)
        self.assertEqual(yd._stream_urls('https://evil.example/videoplayback\n'),([],{},0))
        self.assertEqual(yd._stream_urls(json.dumps({'url':'https://evil.example/x'})),([],{},0))

    def test_ranged_sources_go_through_the_relay(self):
        src={'kind':'url','url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=136','audio_url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=140',
             'hls':False,'remux':True,'ranged':True,'headers':{'User-Agent':'UA/1'},'title':'t'}
        seen=[]
        with mock.patch.object(streaming,'tool',return_value='ffmpeg'),mock.patch('range_relay.local',side_effect=lambda u,h=None:seen.append((u,h)) or 'http://127.0.0.1:1/r/'+u[-3:]):
            args=streaming.command(src,0)
        inputs=[args[i+1] for i,x in enumerate(args) if x=='-i']
        self.assertEqual(inputs,['http://127.0.0.1:1/r/136','http://127.0.0.1:1/r/140'])
        self.assertEqual(seen[0][1],{'User-Agent':'UA/1'})
        plan=streaming.plan(src)
        self.assertNotIn('headers',plan);self.assertNotIn('url',plan)
        src.update(ranged=False)
        with mock.patch.object(streaming,'tool',return_value='ffmpeg'):args=streaming.command(src,0)
        self.assertIn(src['url'],args)


class PlayerTests(unittest.TestCase):
    def test_no_reserve_wait_for_converted_streams(self):
        js=(ROOT/'web'/'player.js').read_text(encoding='utf-8')
        self.assertIn("S.mode==='remux'||!S.mode||ahead()>=need",js)
        self.assertIn('getVideoPlaybackQuality',js)
        self.assertIn('...frames(),gates:',js)

    def test_page_does_not_reload_while_playing(self):
        js=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
        self.assertIn('async function refresh(){if(refreshing||appStopped||playerOpen())return;',js)
        self.assertIn('async function refreshLog(){if(appStopped||playerOpen()||',js)
        css=(ROOT/'web'/'style.css').read_text(encoding='utf-8')
        self.assertIn('dialog.player::backdrop{background:#000c;-webkit-backdrop-filter:none;backdrop-filter:none}',css)

    def test_diagnosis_gets_frame_counts(self):
        server=(ROOT/'server.py').read_text(encoding='utf-8')
        self.assertIn("dropped_frames=int(num('dropped',10**7))",server)


if __name__=='__main__':
    unittest.main()
