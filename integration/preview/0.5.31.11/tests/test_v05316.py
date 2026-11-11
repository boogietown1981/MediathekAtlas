"""0.5.31.6 tests: metadata allowlist, provider regressions and local GUI scaffolding."""
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys
from types import SimpleNamespace

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import yt_dlp_probe, netzkino_details, netzkino, apply_05316


class SafeYtDlp(unittest.TestCase):
    def test_legal_page_only(self):
        for url in ['http://www.netzkino.de/details/film','https://attacker.example/details/film',
                    'https://www.netzkino.de/','https://www.netzkino.de/details/film?token=secret',
                    'https://www.netzkino.de@evil.example/details/film',
                    'https://www.netzkino.de/details/film#foo']:
            with self.subTest(url=url),self.assertRaises(ValueError):yt_dlp_probe.safe_netmovie(url)
        self.assertEqual(yt_dlp_probe.safe_netmovie('https://netzkino.de/details/snow-beast'),
                         'https://www.netzkino.de/details/snow-beast')

    def test_allowlist_drops_stream_urls_secrets_and_drm(self):
        data={'title':'Film','duration':5400,'release_year':2003,'age_limit':12,
              'description':'Test','cast':['Alice','Alice','Bob'], 'creators':['A'],
              'formats':[{'url':'https://token.example/secret.mp4'}],
              'url':'https://private.example/stream', 'http_headers':{'Cookie':'secret'},
              'license_info':{'drm':'secret'}, 'cookies':'secret', 'subtitles':{'key':'secret'}}
        fields=yt_dlp_probe.sanitize(data)
        self.assertEqual(fields['year'],2003)
        self.assertEqual(fields['cast'],['Alice','Bob'])
        self.assertFalse(any('secret' in str(v) for v in fields.values()))
        self.assertNotIn('formats',fields)
        self.assertNotIn('url',fields)
        self.assertFalse(fields['rights_verified'])

    def test_simulates_and_never_returns_raw_json(self):
        calls=[]
        def run(cmd,**kwargs):
            calls.append((cmd,kwargs))
            return SimpleNamespace(returncode=0,stdout=json.dumps({
               'title':'Film','release_year':2003,'duration':200,'url':'https://signed-url/secret',
               'formats':[{'url':'https://signed-url/secret'}], 'http_headers':{'Authorization':'secret'}}),stderr='')
        result=yt_dlp_probe.probe('https://www.netzkino.de/details/film',
               {'title':'Film','year':2004,'duration_seconds':1600}, runner=run,executable='yt-dlp')
        self.assertEqual(result['status'],'ok')
        self.assertIn('Signifikant unterschiedliche Laufzeiten',result['warnings'])
        self.assertIn('Produktionsjahre weichen ab',result['warnings'])
        self.assertNotIn('signed-url',json.dumps(result))
        cmd,kwargs=calls[0]
        self.assertIn('--skip-download',cmd)
        self.assertIn('--dump-single-json',cmd)
        self.assertIn('--ignore-config',cmd)
        self.assertNotIn('--cookies-from-browser',cmd)
        self.assertFalse(kwargs.get('shell',False))

    def test_provider_errors_redacted(self):
        def run(cmd,**kwargs):return SimpleNamespace(returncode=1,stdout='',stderr='SECRET URL https://x/foo')
        result=yt_dlp_probe.probe('https://www.netzkino.de/details/film', runner=run,executable='yt-dlp')
        self.assertEqual(result['status'],'provider_error')
        self.assertNotIn('https://x/foo',json.dumps(result))
        self.assertEqual(yt_dlp_probe.probe('https://www.netzkino.de/details/film',executable='')['status'],'not_installed')

    def test_bad_json(self):
        def run(cmd,**kwargs):return SimpleNamespace(returncode=0,stdout='{bad}',stderr='')
        self.assertEqual(yt_dlp_probe.probe('https://www.netzkino.de/details/film',runner=run,executable='yt-dlp')['status'],'invalid_response')


class NetzkinoDetails(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=pathlib.Path(temp.name)
        self.id=netzkino._key('https://www.netzkino.de/details/test-film')
        self.content_id='a0U01000004e7d2'
        with netzkino._connect(self.root) as db:
            db.execute("""INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,content_id)
                    VALUES(?,?,?,'test','unverified',1,1,?)""",
                (self.id,'Test Film','https://www.netzkino.de/details/test-film',self.content_id))

    def test_public_fields_only_and_caching(self):
        calls=[]
        def fetch(op, variables):
            calls.append(op)
            return {'movie':{'id':self.content_id,'title':'Test Film','originalTitle':'Original',
               'longSynopsis':'Test Inhalt','productionYear':2001,'runtimeInSeconds':5300,
               'originalLanguage':'English', 'cast':{'nodes':[{'person':{'name':'Actor'}}]},
               'videoSource':{'pmdUrl':'https://private.example/secret.mp4'},
               'licenses':{'nodes':[{'properties':'DRM-secret'}]},
               'flags':['genres:Thriller','properties:avod']}}
        r=netzkino_details.get(self.root,self.id,fetch=fetch,now=1000)
        self.assertEqual(r['error_type'],None)
        self.assertEqual(r['details']['title'],'Test Film')
        self.assertEqual(r['details']['cast'],['Actor'])
        self.assertEqual(r['details']['genres'],['Thriller'])
        self.assertEqual(r['details']['access_types'],['AVOD'])
        self.assertNotIn('secret',json.dumps(r))
        second=netzkino_details.get(self.root,self.id,fetch=lambda *args: (_ for _ in ()).throw(AssertionError()),now=1001)
        self.assertTrue(second['cached'])
        self.assertEqual(len(calls),1)
        self.assertEqual(netzkino_details.stats(self.root)['cached_details'],1)

    def test_failure_not_cached_as_success(self):
        def fail(*_):raise ValueError('bad schema raw url https://secret.invalid/path')
        r=netzkino_details.get(self.root,self.id,fetch=fail,now=1000)
        self.assertEqual(r['error_type'],'invalid_details')
        self.assertEqual(netzkino_details.stats(self.root)['detail_errors'],1)
        self.assertNotIn('secret.invalid',json.dumps(r))
        repeat=netzkino_details.get(self.root,self.id,fetch=fail,now=1002)
        self.assertEqual(repeat['error_type'],'invalid_details')

    def test_har_hash_exact_and_script_guards(self):
        src=(ROOT/'netzkino.py').read_text()
        self.assertNotIn("    'MovieDetails':",src)  # only applied to installed project, not template
        app=(ROOT/'apply_05316.py').read_text()
        self.assertIn('692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97',app)
        self.assertIn('archive-full-mode',app)
        ui=(ROOT/'web/unified_catalog.js').read_text()
        self.assertIn("'mediatheken'",ui)
        self.assertIn("'netzkino'",ui)
        self.assertIn("'all'",ui)
        self.assertIn('openSeries',ui)
        player=(ROOT/'netzkino_webplayer.swift').read_text()
        self.assertIn('WKWebView',player)
        self.assertNotIn('evaluateJavaScript',player)

if __name__=='__main__':unittest.main()
