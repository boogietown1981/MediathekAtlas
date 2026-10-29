import os,unittest,sys,tempfile,subprocess,json,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core,downloads
class Tests(unittest.TestCase):
    def test_no_broadcast_year(self):
        m=core.identify({'title':'Ein Film','description':'Spielfilm über eine Familie','timestamp':1792955820})
        self.assertIsNone(m['year'])
    def test_production_year(self):
        self.assertEqual(core.identify({'title':'Ein Film','description':'Spielfilm Deutschland 1998'})['year'],1998)
    def test_no_invented_season(self):
        m=core.identify({'title':'Folge 12','topic':'Beispielserie'})
        self.assertEqual(m['episode'],12);self.assertIsNone(m['season'])
        with self.assertRaises(ValueError):core.validate_meta(m)
    def test_explicit_episode(self):
        m=core.identify({'title':'Neuanfang S02E03','topic':'Beispielserie'})
        self.assertEqual((m['title'],m['season'],m['episode']),('Beispielserie',2,3))
    def test_safe_path(self):
        m={'kind':'movie','title':'../../A <Film>','year':2020}
        with tempfile.TemporaryDirectory() as root:
            root=os.path.realpath(root)  # macOS: /var is a symlink to /private/var
            p=core.target(root,m,'abc');self.assertTrue(p.is_relative_to(root));self.assertEqual(p.suffix,'.mkv')
    def test_wrong_kind(self):
        with self.assertRaises(ValueError):core.target('/tmp',{'kind':'unknown','title':'News'},'x')
    def test_no_false_audio_language(self):
        parsed=core.parse_streams({'streams':[{'codec_type':'audio','codec_name':'aac','index':0}]})
        self.assertIsNone(parsed[0]['language'])
    def test_local_urls_blocked(self):
        for url in ['file:///etc/passwd','http://127.0.0.1/a','http://[::1]/a','http://user:pass@server/a']:
            with self.assertRaises(ValueError):core.public_url(url)
    def test_xml_escaping(self):
        from xml.etree import ElementTree as ET
        m={'kind':'movie','title':'A & <B>','provider':'manuell','description':'<test>'}
        self.assertEqual(ET.fromstring(core.nfo(m,[],60)).findtext('title'),'A & <B>')
    def test_episode_nfo_title(self):
        from xml.etree import ElementTree as ET
        m={'kind':'series','title':'Serie','episode_title':'Anfang','provider':'TMDB','reference_id':'123','season':2,'episode':3}
        r=ET.fromstring(core.nfo(m,[],60));self.assertEqual(r.findtext('title'),'Anfang');self.assertEqual(r.findtext('showtitle'),'Serie')
    def test_series_export_identity_and_path(self):
        from xml.etree import ElementTree as ET
        m={'kind':'series','title':'Testserie','episode_title':'Anfang','year':2020,'provider':'TMDB','reference_id':'123','season':2,'episode':3,'genres':['Familie']}
        path=core.target('/tmp/export',m,'fixture')
        self.assertEqual(path.name,'Testserie (2020) - S02E03.mkv')
        self.assertEqual(path.parent.name,'Season 02')
        episode=ET.fromstring(core.nfo(m,[],60));show=ET.fromstring(core.show_nfo(m))
        self.assertIsNone(episode.find('uniqueid'))
        self.assertEqual(show.find('uniqueid').text,'123')
        self.assertEqual(json.loads(show.findtext('episodeguide')),{'tmdb':'123'})
        self.assertEqual(show.findtext('genre'),'Familie')
    def test_full_download_remux_and_sidecars(self):
        if not downloads.tool('ffmpeg'):self.skipTest('ffmpeg unavailable')
        with tempfile.TemporaryDirectory() as root:
            sample=Path(root)/'sample.mp4'
            subprocess.run([downloads.tool('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=64x64:d=1','-c:v','mpeg4',str(sample)],check=True)
            raw=sample.read_bytes()
            class Response(io.BytesIO):headers={'Content-Length':str(len(raw)),'Content-Type':'video/mp4'}
            row={'_id':'fixture','url_video':'https://example.org/video.mp4','title':'Test'}
            m={'title':'Test & Film','kind':'movie','year':2020,'description':'Testbeschreibung','provider':'manuell'}
            states=[];updates=[]
            with patch('core.open_url',return_value=Response(raw)):
                downloads.run(row,m,Path(root)/'export','hd',lambda s,*a,**k:(states.append(s),updates.append((s,k))),lambda:False)
            done=next(k for state,k in updates if state=='done')
            self.assertEqual(done['measured'][0]['width'],64)
            self.assertGreater(done['size_bytes'],0)
            self.assertIsNone(done['eta'])
            dest=core.target(Path(root)/'export',m,'fixture')
            self.assertTrue(dest.exists());self.assertTrue(dest.with_suffix('.nfo').exists());self.assertTrue(dest.with_suffix('.metadata.json').exists())
            tags=downloads.probe(dest)['format']['tags'];self.assertEqual(tags['title'],'Test & Film');self.assertIn('done',states)
            with self.assertRaises(FileExistsError):downloads.run(row,m,Path(root)/'export','hd',lambda *a:None,lambda:False)
    def test_series_download_writes_show_and_episode_nfo(self):
        from xml.etree import ElementTree as ET
        if not downloads.tool('ffmpeg'):self.skipTest('ffmpeg unavailable')
        with tempfile.TemporaryDirectory() as root:
            sample=Path(root)/'sample.mp4'
            subprocess.run([downloads.tool('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=64x64:d=1','-c:v','mpeg4',str(sample)],check=True)
            raw=sample.read_bytes()
            class Response(io.BytesIO):headers={'Content-Length':str(len(raw)),'Content-Type':'video/mp4'}
            row={'_id':'episode-fixture','url_video':'https://example.org/video.mp4'}
            m={'title':'Testserie','episode_title':'Anfang','kind':'series','year':2020,'season':1,'episode':2,'provider':'TVDB','reference_id':'123','genres':['Familie']}
            with patch('core.open_url',return_value=Response(raw)):
                downloads.run(row,m,Path(root)/'export','hd',lambda *a,**k:None,lambda:False)
            dest=core.target(Path(root)/'export',m,row['_id'])
            show=ET.parse(dest.parent.parent/'tvshow.nfo').getroot()
            episode=ET.parse(dest.with_suffix('.nfo')).getroot()
            self.assertEqual(show.find('uniqueid').attrib['type'],'tvdb')
            self.assertEqual(show.findtext('uniqueid'),'123')
            self.assertEqual(episode.findtext('title'),'Anfang')
            self.assertEqual(episode.findtext('episode'),'2')
            self.assertIsNone(episode.find('uniqueid'))
    def test_hls_not_fake_download(self):
        with self.assertRaisesRegex(ValueError,'HLS'):
            downloads.run({'url_video':'https://example.org/a.m3u8'}, {},'/tmp','hd',None,None)
if __name__=='__main__':unittest.main()
