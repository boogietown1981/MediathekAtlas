"""ARD/ZDF Mediathek programme data. Fixtures follow the field paths used by yt-dlp's ard.py/zdf.py
(page-gateway item with mcV6, ZDF GraphQL videoByCanonical); they are reduced, not recorded live."""
import io,json,sys,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import artwork,broadcaster,diagnostics,matching,metadata

ARD_URL='https://www.ardmediathek.de/video/servicezeit/zecken-im-garten/wdr/Y3JpZDovL3dkci5kZS9CZWl0cmFnLXNvcGhvcmEtMTIz'
ZDF_URL='https://www.zdf.de/video/dokus/terra-x-100/terra-x-history-ein-tag-im-juli-ahrtalflut-100'

def ard_page(series='Servicezeit',title='Zecken im Garten',page_title=None,seconds=1770):
    return {'title':page_title or title,'widgets':[{'type':'player_ondemand','title':title,'show':{'id':'Y3JpZDovL3dkci5kZS9TZXJ2aWNlemVpdA','title':series,'image':{'src':'https://api.ardmediathek.de/image-service/images/urn:ard:image:show?w={width}'}},
        'mediaCollection':{'embedded':{'meta':{'title':title,'synopsis':'Was hilft gegen Zecken? Ein Verbrauchermagazin.','seriesTitle':series,'durationSeconds':seconds,'clipSourceName':'WDR',
            'broadcastedOnDateTime':'2026-10-20T16:15:00Z','images':[{'url':'https://api.ardmediathek.de/image-service/images/urn:ard:image:ep?w=1280'}]}}}},{'type':'gridlist'}]}

def zdf_data(season=2,episode=3):
    return {'data':{'videoByCanonical':{'canonical':'terra-x-history-ein-tag-im-juli-ahrtalflut-100','title':'Ein Tag im Juli','leadParagraph':'Die Flut im Ahrtal.','editorialDate':'2026-07-14T20:15:00+02:00',
        'teaser':{'description':'Kurz','image':{'list':{'384x216':'https://www.zdf.de/assets/flut~384x216','original':'https://www.zdf.de/assets/flut~original','bad':'https://evil.example/x.jpg'}}},
        'episodeInfo':{'episodeNumber':episode,'seasonNumber':season},'smartCollection':{'canonical':'terra-x-history-102','title':'Terra X History'},
        'currentMedia':{'nodes':[{'duration':2640}]}}}}

class ReferenceTests(unittest.TestCase):
    def test_supported_pages(self):
        self.assertEqual(broadcaster.reference({'url_website':ARD_URL}),('ARD Mediathek','Y3JpZDovL3dkci5kZS9CZWl0cmFnLXNvcGhvcmEtMTIz'))
        self.assertEqual(broadcaster.reference({'url_website':ZDF_URL}),('ZDF Mediathek','terra-x-history-ein-tag-im-juli-ahrtalflut-100'))
        self.assertEqual(broadcaster.reference({'url_website':'https://www.zdf.de/dokumentation/terra-x/flut-100.html'}),('ZDF Mediathek','flut-100'))
    def test_other_or_unsafe_pages_ignored(self):
        for url in ('','http://www.ardmediathek.de/video/x/Y3JpZDovL3dkci5kZS9h','https://www.3sat.de/film/x-100.html','https://evil.example/video/Y3JpZDovL3dkci5kZS9h','https://www.zdf.de/','https://www.ardmediathek.de/sendung/x/Y3JpZDovL3dkci5kZS9h'):
            self.assertIsNone(broadcaster.reference({'url_website':url}),url)

class ParseTests(unittest.TestCase):
    def test_ard_item(self):
        info=broadcaster.parse_ard(ard_page(page_title='Zecken im Garten (S03/E07)'))
        self.assertEqual((info['series'],info['title'],info['season'],info['episode'],info['duration'],info['channel']),('Servicezeit','Zecken im Garten',3,7,1770,'WDR'))
        self.assertEqual(info['series_image'],'https://api.ardmediathek.de/image-service/images/urn:ard:image:show?w=1280')
        self.assertIsNone(broadcaster.parse_ard({'widgets':[{'type':'gridlist'}]}))
    def test_zdf_prefers_original_image_on_allowed_host(self):
        info=broadcaster.parse_zdf(zdf_data())
        self.assertEqual((info['series'],info['series_id'],info['season'],info['episode'],info['duration']),('Terra X History','terra-x-history-102',2,3,2640))
        self.assertEqual(info['image'],'https://www.zdf.de/assets/flut~original')
        self.assertIsNone(broadcaster.parse_zdf({'data':{'videoByCanonical':None}}))

class CandidateTests(unittest.TestCase):
    row={'title':'Zecken im Garten','topic':'Servicezeit','duration':1780,'url_website':ARD_URL}
    def test_own_series_identifies_work(self):
        meta={'kind':'unknown','title':'Zecken im Garten'}
        c=broadcaster.candidate(self.row,meta,broadcaster.parse_ard(ard_page()))
        self.assertEqual((c['kind'],c['title'],c['provider'],c['year']),('series','Servicezeit','ARD Mediathek',None))
        self.assertEqual(c['genres'],['Magazin']);self.assertFalse(c['episode_verified'])
        chosen=matching.choose(meta,[c],work_only=True);self.assertEqual(chosen['title'],'Servicezeit')
        self.assertIsNone(matching.choose(meta,[c]))
    def test_numbered_episode_is_verified(self):
        c=broadcaster.candidate(self.row,{'kind':'series','title':'Servicezeit'},broadcaster.parse_ard(ard_page(page_title='Zecken im Garten (S03/E07)')))
        self.assertTrue(c['episode_verified']);self.assertEqual(matching.choose({'kind':'series','title':'Servicezeit'},[c])['episode'],7)
    def test_film_container_is_no_series(self):
        row={'title':'Liebe auf vier Pfoten','topic':'Filme im MDR','duration':5400,'url_website':ARD_URL}
        info=broadcaster.parse_ard(ard_page(series='Filme im MDR',title='Liebe auf vier Pfoten',seconds=5390))
        self.assertIsNone(broadcaster.candidate(row,{'kind':'unknown','title':'Liebe auf vier Pfoten'},info))
        film=broadcaster.candidate(row,{'kind':'movie','title':'Liebe auf vier Pfoten'},info)
        self.assertEqual(film['kind'],'movie');self.assertIsNone(film['year']);self.assertTrue(film['runtime_agrees'])
    def test_topic_mismatch_is_no_series(self):
        row={**self.row,'topic':'Lokalzeit'}
        self.assertIsNone(broadcaster.candidate(row,{'kind':'unknown','title':'Zecken'},broadcaster.parse_ard(ard_page())))

class LookupTests(unittest.TestCase):
    def setUp(self):
        broadcaster._CACHE.clear();broadcaster._PAUSED.clear();broadcaster._TOKEN.clear();broadcaster.MIN_INTERVAL=0
    def test_ard_request_and_cache(self):
        with patch('core.open_url',return_value=io.BytesIO(json.dumps(ard_page()).encode())) as request:
            a=broadcaster.lookup({'url_website':ARD_URL});b=broadcaster.lookup({'url_website':ARD_URL})
        self.assertEqual(a,b);request.assert_called_once()
        self.assertTrue(request.call_args.args[0].startswith(broadcaster.ARD_ITEM+'Y3JpZDovL3dkci5kZS9CZWl0cmFnLXNvcGhvcmEtMTIz?'))
    def test_zdf_token_is_secret_and_reused(self):
        responses=[io.BytesIO(b'{"type":"Bearer","token":"SECRET-TOKEN","expires":9999999999}'),io.BytesIO(json.dumps(zdf_data()).encode()),io.BytesIO(json.dumps(zdf_data()).encode())]
        with patch('core.open_url',side_effect=responses) as request,patch('diagnostics.register_secrets') as secrets:
            broadcaster.lookup({'url_website':ZDF_URL});broadcaster._CACHE.clear();info=broadcaster.lookup({'url_website':ZDF_URL})
        self.assertEqual(request.call_count,3);secrets.assert_called_once_with('SECRET-TOKEN')
        self.assertEqual(request.call_args.args[2]['Api-Auth'],'Bearer SECRET-TOKEN');self.assertEqual(info['series'],'Terra X History')
    def test_rate_limit_pauses_provider(self):
        error=urllib.error.HTTPError(ARD_URL,429,'Too Many',{},io.BytesIO(b''))
        with patch('core.open_url',side_effect=error) as request,patch('diagnostics.event'):
            for _ in range(3):
                with self.assertRaises(broadcaster.Unavailable):broadcaster.lookup({'url_website':ARD_URL})
        request.assert_called_once();self.assertTrue(broadcaster.status('ARD Mediathek')['paused'])
    def test_unknown_page_is_cached_as_none(self):
        with patch('core.open_url',side_effect=urllib.error.HTTPError(ARD_URL,404,'Not Found',{},io.BytesIO(b''))) as request:
            self.assertIsNone(broadcaster.lookup({'url_website':ARD_URL}));self.assertIsNone(broadcaster.lookup({'url_website':ARD_URL}))
        request.assert_called_once()

class IntegrationTests(unittest.TestCase):
    row={'title':'Zecken im Garten','topic':'Servicezeit','duration':1780,'url_website':ARD_URL}
    def setUp(self):broadcaster._CACHE.clear();broadcaster._PAUSED.clear()
    def test_fallback_after_film_databases(self):
        with patch('metadata.tmdb_candidates',return_value=[]),patch('metadata.wikidata') as wiki,patch('broadcaster.lookup',return_value=broadcaster.parse_ard(ard_page())):
            r=metadata.candidates(self.row,{'kind':'unknown','title':'Zecken im Garten'},{'tmdb':'k'})
        self.assertEqual(r['candidates'][0]['provider'],'ARD Mediathek');wiki.assert_not_called()
        self.assertIn({'provider':'ARD Mediathek','status':'checked','count':1},r['provider_checks'])
    def test_known_sendereihe_skips_film_databases(self):
        meta={'kind':'series','title':'Servicezeit','provider':'ARD Mediathek','reference_id':'x'}
        with patch('metadata.tmdb_candidates') as tmdb,patch('metadata.tvdb_candidates') as tvdb,patch('broadcaster.lookup',return_value=broadcaster.parse_ard(ard_page())):
            r=metadata.candidates(self.row,meta,{'tmdb':'k','tvdb':'k'})
        tmdb.assert_not_called();tvdb.assert_not_called();self.assertEqual(r['candidates'][0]['title'],'Servicezeit')
    def test_unavailable_defers_instead_of_warning(self):
        with patch('broadcaster.lookup',side_effect=broadcaster.Unavailable('ARD Mediathek: HTTP 503')),patch('metadata.wikidata',return_value=None):
            r=metadata.candidates(self.row,{'kind':'unknown','title':'Zecken im Garten'},{})
        self.assertEqual(r['deferred_providers'],['ARD Mediathek']);self.assertEqual(r['warnings'],[])
    def test_broadcaster_images_allowed(self):
        self.assertTrue(artwork.valid('https://api.ardmediathek.de/image-service/images/urn:ard:image:ep?w=1280'))
        self.assertTrue(artwork.valid('https://www.zdf.de/assets/flut~original'))
        self.assertFalse(artwork.valid('https://www.zdf.de.evil.example/x.jpg'))
if __name__=='__main__':unittest.main()
