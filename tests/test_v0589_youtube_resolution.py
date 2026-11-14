"""0.5.89: YouTube im eigenen Player in 720p/1080p statt 480p (Björn, 13.11.2026).

Until 0.5.88 the format string demanded H.264 as a separate HTTPS file first; without a sign-in
YouTube often offers those only up to 480p, the higher levels as HLS or VP9.
"""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import streaming,youtube_downloads as yd

def fmt(i,h,v,a,proto,ext,tbr):
    url=('https://rr1---sn-x.googlevideo.com/videoplayback?itag=%s'%i if proto=='https'
         else 'https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/%s/index.m3u8'%i)
    return {'format_id':str(i),'url':url,'height':h,'vcodec':v,'acodec':a,'protocol':proto,'ext':ext,'tbr':tbr,
            'video_ext':ext if v!='none' else 'none','audio_ext':ext if v=='none' else 'none'}

BASE=[fmt(140,None,'none','mp4a.40.2','https','m4a',129),fmt(251,None,'none','opus','https','webm',140),
      fmt(18,360,'avc1.42001E','mp4a.40.2','https','mp4',500),fmt(135,480,'avc1.4d401f','none','https','mp4',800)]
VP9=[fmt(247,720,'vp9','none','https','webm',1200),fmt(248,1080,'vp9','none','https','webm',2400),fmt(313,2160,'vp9','none','https','webm',12000)]
HLS=[fmt(95,720,'avc1.4d401f','mp4a.40.2','m3u8_native','mp4',1800),fmt(96,1080,'avc1.640028','mp4a.40.2','m3u8_native','mp4',3500)]
HTTPS=[fmt(136,720,'avc1.4d401f','none','https','mp4',1500),fmt(137,1080,'avc1.640028','none','https','mp4',3000)]


def _ytdlp():
    try:import yt_dlp  # noqa: F401
    except ImportError:return False
    return True


@unittest.skipUnless(_ytdlp(),'yt-dlp nicht installiert')
class FormatChoiceTests(unittest.TestCase):
    """Real yt-dlp with a stored info file (--load-info-json): which formats it picks."""
    def pick(self,formats,height):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'info.json'
            p.write_text(json.dumps({'id':'abcdefghijk','title':'t','extractor':'youtube','extractor_key':'Youtube',
                                     'webpage_url':'https://www.youtube.com/watch?v=abcdefghijk','formats':formats,'_type':'video'}))
            r=subprocess.run([sys.executable,'-m','yt_dlp','--ignore-config','--no-warnings','--load-info-json',str(p),
                              '-f',yd.FORMAT.format(h=height),'-S',yd.SORT.format(h=height),'-j'],capture_output=True,text=True,timeout=60)
        self.assertEqual(r.returncode,0,r.stderr[-400:])
        return json.loads(r.stdout)['format_id'],r.stdout

    def test_old_string_stopped_at_480p(self):
        # documents Björn's case: the 0.5.88 string took the 480p H.264 file although 1080p existed
        old='bv*[height<=1080][vcodec^=avc1][protocol^=http]+ba[acodec^=mp4a][protocol^=http]/b[height<=1080][vcodec^=avc1]/b[vcodec^=avc1]/b'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'info.json';p.write_text(json.dumps({'id':'abcdefghijk','title':'t','extractor':'youtube','extractor_key':'Youtube','webpage_url':'https://www.youtube.com/watch?v=abcdefghijk','formats':BASE+VP9+HLS,'_type':'video'}))
            r=subprocess.run([sys.executable,'-m','yt_dlp','--ignore-config','--no-warnings','--load-info-json',str(p),'-f',old,'-j'],capture_output=True,text=True,timeout=60)
        self.assertEqual(json.loads(r.stdout)['format_id'],'135+140')

    def test_highest_picture_up_to_the_limit(self):
        self.assertEqual(self.pick(BASE+VP9+HLS,1080)[0],'96')          # H.264 with sound as HLS before VP9
        self.assertEqual(self.pick(BASE+VP9+HLS,720)[0],'95')
        self.assertEqual(self.pick(BASE+VP9,1080)[0],'248+140')         # VP9 when no H.264 above 480p exists
        self.assertEqual(self.pick(BASE+VP9,2160)[0],'313+140')
        self.assertEqual(self.pick(BASE+HTTPS+HLS+VP9,1080)[0],'137+140')   # separate HTTPS files before HLS
        self.assertEqual(self.pick(BASE,1080)[0],'135+140')            # the video really has only 480p

    def test_source_for_hls_and_menu(self):
        _,out=self.pick(BASE+VP9+HLS,1080)
        urls,headers,height=yd._stream_urls(out)
        self.assertEqual((len(urls),height),(1,1080))
        self.assertEqual(yd._heights(out),[2160,1080,720,480,360])


class SourceTests(unittest.TestCase):
    def test_auto_is_1080_and_max_2160(self):
        seen=[]
        class Done:
            returncode=0;stderr=''
            stdout=json.dumps({'requested_formats':[{'url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=137','height':1080},
                                                    {'url':'https://rr1---sn-x.googlevideo.com/videoplayback?itag=140'}],
                               'formats':BASE+HTTPS})
        def runner(args,**kw):
            seen.append(args[args.index('-f')+1]);return Done()
        row={'kind':'video','reason':'','path':'abcdefghijk','title':'T','duration':200}
        with mock.patch.object(yd,'enabled',return_value=True),mock.patch.object(yd,'find_tool',return_value=(['yt-dlp'],'t')), \
             mock.patch('youtube._connect'),mock.patch('youtube._row',return_value=row),mock.patch('youtube.VALID_ID') as valid:
            valid.fullmatch.return_value=True
            src=yd.play_source('/x','t.abcdefghijk','auto',runner=runner,now=1)
            yd.play_source('/x','t.abcdefghijk','max',runner=runner,now=1)
            yd.play_source('/x','t.abcdefghijk','480',runner=runner,now=1)
        self.assertEqual([('height<=1080' in f,'height<=2160' in f,'height<=480' in f) for f in seen],
                         [(True,False,False),(False,True,False),(False,False,True)])
        self.assertEqual(src['quality'],'eigener Player, 1080p')
        plan=streaming.plan(src)
        self.assertEqual([l['height'] for l in plan['levels']],[1080,720,480,360])
        self.assertEqual(plan['auto_height'],1080)
        self.assertNotIn('url',plan)

    def test_hls_source_stays_on_the_server(self):
        src={'kind':'url','url':'https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/96/index.m3u8','audio_url':'','hls':True,
             'remux':True,'server_only':True,'ranged':False,'provider':'youtube','title':'t','files':[1080,720],'auto_height':1080}
        plan=streaming.plan(src)
        self.assertEqual((plan['mode'],'url' in plan,[l['height'] for l in plan['levels']]),('remux',False,[1080,720]))
        # broadcaster HLS without 'server_only' keeps its address for hls.js
        plan=streaming.plan({'kind':'url','url':'https://x.example/master.m3u8','hls':True,'title':'t'},levels=False)
        self.assertIn('url',plan)

    def test_player_uses_the_servers_automatic_height(self):
        js=(ROOT/'web'/'player.js').read_text(encoding='utf-8')
        self.assertIn("const auto=S.info?.auto_height||AUTO_HEIGHT,top=w==='auto'?auto:Number(w)||auto;",js)


if __name__=='__main__':
    unittest.main()
