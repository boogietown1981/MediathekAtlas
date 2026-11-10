"""0.5.30 sender-first, opt-in broadcaster pages, and safe episode evidence."""
import json,sqlite3,tempfile,threading,time,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import broadcaster,catalog,catalog_service,imdb_archive,metadata
from test_broadcaster import ARD_URL,ard_page

PAGE_ID=broadcaster.reference({'url_website':ARD_URL})[1]


def offer(title='Zecken im Garten',topic='Servicezeit',url=ARD_URL):
    return {'title':title,'topic':topic,'duration':1780,'channel':'WDR',
            'description':'Ein Beitrag','url_video':'https://example.org/video.mp4',
            'url_website':url}


def info(numbered=False,seconds=1770):
    result=broadcaster.parse_ard(ard_page(
        page_title='Zecken im Garten (S03/E07)' if numbered else None,
        seconds=seconds))
    result['reference_id']=PAGE_ID
    return result


class SenderEvidenceTests(unittest.TestCase):
    def setUp(self):
        broadcaster._CACHE.clear()
        broadcaster._PAUSED.clear()
        broadcaster._AUTOMATED_BUDGET.clear()

    def test_imported_offer_metadata_is_offline_and_unverified(self):
        src=offer()
        meta={'title':'Servicezeit','kind':'series','provider':'TMDB','reference_id':'123'}
        with patch('broadcaster.lookup_limited',side_effect=AssertionError('network')) as network:
            result=broadcaster.imported_episode_evidence(src,meta)
        network.assert_not_called()
        self.assertEqual(result['sender_page_id'],PAGE_ID)
        self.assertEqual(result['sender_evidence'],'imported_offer')
        self.assertFalse(result['sender_item_verified'])

    def test_other_hosts_and_wrong_series_are_not_evidence(self):
        m={'title':'Servicezeit','kind':'series','reference_id':'123'}
        self.assertIsNone(broadcaster.imported_episode_evidence(offer(topic='Lokalzeit'),m))
        self.assertIsNone(broadcaster.imported_episode_evidence(offer(url='https://bad.example/video/id'),m))
        self.assertIsNone(broadcaster.imported_episode_evidence(offer(topic='Filme im MDR'),m))

    def test_passive_arte_3sat_kika_import_never_uses_live_api(self):
        m={'title':'Servicezeit','kind':'series','provider':'TMDB','reference_id':'123'}
        for host,path in [('www.arte.tv','/de/videos/example'),('www.3sat.de','/kultur/sendung-100.html'),
                          ('www.kika.de','/serie/beitrag-100')]:
            with self.subTest(host=host),patch('broadcaster.lookup_limited',side_effect=AssertionError('no direct access')) as request:
                evidence=broadcaster.imported_episode_evidence(offer(url='https://'+host+path),m)
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence['sender_evidence'],'imported_offer')
                self.assertFalse(evidence['sender_item_verified'])
                self.assertTrue(evidence['sender_page_id'].startswith('link:'))
                request.assert_not_called()

    def test_sender_does_not_confirm_inherited_numbers(self):
        m={'title':'Servicezeit','kind':'series','season':3,'episode':7}
        candidate=broadcaster.candidate(offer(),m,info(numbered=False))
        self.assertEqual((candidate['season'],candidate['episode']),(3,7))
        self.assertFalse(candidate['episode_verified'])
        self.assertTrue(candidate['sender_item_verified'])

    def test_mismatched_runtime_does_not_confirm_sender_page(self):
        candidate=broadcaster.candidate(offer(),{'title':'Servicezeit','kind':'series'},info(numbered=True,seconds=500))
        self.assertFalse(candidate['episode_verified'])
        self.assertFalse(candidate['sender_item_verified'])

    def test_automatic_budget_and_cached_responses(self):
        src=offer()
        with patch.object(broadcaster,'AUTOMATED_HOURLY_LIMIT',2),patch('broadcaster.lookup',return_value=info()) as lookup:
            broadcaster.lookup_limited(src)
            broadcaster.lookup_limited(offer(url=ARD_URL+'a'))
            with self.assertRaises(broadcaster.Unavailable):
                broadcaster.lookup_limited(offer(url=ARD_URL+'b'))
            self.assertGreater(broadcaster.automated_retry_at('ARD Mediathek'),time.time())
        self.assertEqual(lookup.call_count,2)
        broadcaster._CACHE[(broadcaster.reference(src))]=(time.time(),info())
        with patch.object(broadcaster,'AUTOMATED_HOURLY_LIMIT',2),patch('broadcaster.lookup',side_effect=AssertionError('network')):
            self.assertEqual(broadcaster.lookup_limited(src)['series'],'Servicezeit')

    def test_main_pipeline_does_not_query_sender_without_permission(self):
        with patch.object(imdb_archive,'ACTIVE',None),patch('broadcaster.lookup_limited',side_effect=AssertionError('network')) as sender,patch('metadata.wikidata',return_value=None):
            metadata.candidates(offer(),{'title':'Servicezeit','kind':'series'},{})
        sender.assert_not_called()

    def test_main_pipeline_sender_first_when_permitted(self):
        with patch.object(imdb_archive,'ACTIVE',None),patch('broadcaster.lookup_limited',return_value=info(numbered=True)),patch('metadata.tvdb_candidates',side_effect=AssertionError('TVDB was not first')) as tvdb:
            result=metadata.candidates(offer(),{'title':'Servicezeit','kind':'series'},{'tvdb':'key','sender_direct_lookup':True})
        self.assertEqual(result['candidates'][0]['provider'],'ARD Mediathek')
        self.assertTrue(result['candidates'][0]['episode_verified'])
        tvdb.assert_not_called()


class EpisodeWorkerTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'catalog.db'
        self.direct=False
        self.settings=lambda:{'auto_metadata':True,'episode_workers':2,'metadata_workers':2,
                              'sender_direct_lookup':self.direct,'scan_priority':'series_first','complete_series':False}
        with self.db() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[offer()])
            row=c.execute('SELECT * FROM works').fetchone()
            m=json.loads(row['meta']);m.update(kind='series',title='Servicezeit',
                provider='TMDB',reference_id='123',year=None,episode_verified=False)
            c.execute("UPDATE works SET kind='series',title=?,state='identified',meta=?,next_try=? WHERE id=?",
                      ('Servicezeit',json.dumps(m),time.time()+86400,row['id']))
            self.wid=row['id']
        self.svc=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)
        broadcaster._AUTOMATED_BUDGET.clear()

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def data(self):
        with self.db() as c:
            row=c.execute('SELECT state,meta FROM works WHERE id=?',(self.wid,)).fetchone()
            wid=self.wid
            if row is None:
                alias=c.execute('SELECT new_id FROM work_aliases WHERE old_id=?',(wid,)).fetchone()
                if alias:
                    wid=alias[0]
                    row=c.execute('SELECT state,meta FROM works WHERE id=?',(wid,)).fetchone()
            queue=c.execute('SELECT * FROM episode_queue WHERE work_id=?',(wid,)).fetchone()
            return row['state'],json.loads(row['meta']),queue

    def test_off_by_default_preserves_imported_sender_page(self):
        archive=type('Offline',(),{'updated':1,'candidates':lambda self,*a:[]})()
        with patch.object(imdb_archive,'ACTIVE',archive),patch('broadcaster.lookup_limited',side_effect=AssertionError('network')) as request:
            self.assertTrue(self.svc.metadata_once('episode'))
        request.assert_not_called()
        state,m,q=self.data()
        self.assertEqual(state,'identified')
        self.assertEqual(m['sender_page_id'],PAGE_ID)
        self.assertFalse(m.get('episode_verified'))
        self.assertEqual(q['last_outcome'],'unresolved')
        self.assertEqual(self.svc.episode_sender_imported,1)

    def test_numbered_sender_episode_is_matched_without_imdb(self):
        self.direct=True
        with patch('broadcaster.lookup_limited',return_value=info(numbered=True)),patch.object(imdb_archive,'ACTIVE',None):
            self.assertTrue(self.svc.metadata_once('episode'))
        state,m,q=self.data()
        self.assertEqual(state,'matched')
        self.assertIsNone(q)
        self.assertTrue(m['episode_verified'])
        self.assertEqual((m['season'],m['episode']),(3,7))
        self.assertEqual(self.svc.episode_sender_matched,1)

    def test_unnumbered_sender_item_does_not_become_episode(self):
        self.direct=True
        archive=type('Offline',(),{'updated':1,'candidates':lambda self,*a:[]})()
        with patch('broadcaster.lookup_limited',return_value=info()),patch.object(imdb_archive,'ACTIVE',archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        state,m,q=self.data()
        self.assertEqual(state,'identified')
        self.assertTrue(m['sender_item_verified'])
        self.assertEqual(m['sender_evidence'],'original_sender_page')
        self.assertFalse(m['episode_verified'])
        self.assertIsNone(m.get('season'))
        self.assertEqual(q['last_outcome'],'unresolved')
        self.assertEqual(self.svc.episode_sender_items,1)

    def test_sender_outage_retries_and_preserves_queue(self):
        self.direct=True
        archive=type('Offline',(),{'updated':1,'candidates':lambda self,*a:[]})()
        with patch('broadcaster.lookup_limited',side_effect=broadcaster.Unavailable('down')),patch.object(imdb_archive,'ACTIVE',archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        state,m,q=self.data()
        self.assertEqual(state,'identified')
        self.assertEqual(q['last_outcome'],'retry')
        self.assertGreater(q['next_try'],time.time()+3500)
        self.assertEqual(self.svc.episode_sender_deferred,1)

    def test_sender_outage_falls_back_to_verified_imdb(self):
        self.direct=True
        class Offline:
            updated=1
            def candidates(self,src,m):
                return [{**m,'provider':'IMDb Offline','reference_id':'ttshow',
                         'episode_reference_id':'ttepisode','title':'Servicezeit',
                         'season':1,'episode':2,'episode_verified':True,
                         'similarity':1.0,'year_mismatch':False,'runtime_mismatch':False}]
        with patch('broadcaster.lookup_limited',side_effect=broadcaster.Unavailable('down')),patch.object(imdb_archive,'ACTIVE',Offline()):
            self.assertTrue(self.svc.metadata_once('episode'))
        state,m,q=self.data()
        self.assertEqual(state,'matched')
        self.assertIsNone(q)
        self.assertEqual(m['provider'],'IMDb Offline')

    def test_concurrent_manual_change_is_not_overwritten(self):
        self.direct=True
        def concurrent(*a):
            with self.db() as c:c.execute("UPDATE works SET state='manual' WHERE id=?",(self.wid,))
            return info(numbered=True)
        with patch('broadcaster.lookup_limited',side_effect=concurrent),patch.object(imdb_archive,'ACTIVE',None):
            self.assertTrue(self.svc.metadata_once('episode'))
        state,m,q=self.data()
        self.assertEqual(state,'manual')
        self.assertIsNone(q)


if __name__=='__main__':unittest.main()
