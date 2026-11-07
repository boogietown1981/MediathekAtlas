"""0.5.20: incremental feed imports, shared series evidence, and safe expiry dates."""
import io,json,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import broadcaster,catalog,catalog_service,filmlist
from test_diagnosis_fixes import database
from test_broadcaster import ard_page,zdf_data

def offer(title='Pilot',topic='Example Series',url='https://example.org/1.mp4',duration=1800):
    return {'title':title,'topic':topic,'description':'','duration':duration,
            'channel':'ARD','url_video':url}

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
        catalog.ingest(self.c,[offer()],seen=1)
    def tearDown(self):self.c.close()
    def test_identical_does_not_rewrite_row_or_manual_identity(self):
        original=self.c.execute('SELECT payload,seen FROM offers').fetchone()
        self.c.execute("UPDATE works SET state='manual',updated=999")
        stats={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        catalog.begin_snapshot(self.c)
        catalog.ingest_incremental(self.c,[offer()],2,stats)
        diff=catalog.finish_snapshot(self.c,2,stats)
        current=self.c.execute('SELECT payload,seen,active FROM offers').fetchone()
        self.assertEqual((current['payload'],current['seen']),tuple(original))
        self.assertEqual(current['active'],1)
        self.assertEqual(self.c.execute('SELECT state,updated FROM works').fetchone()[:],('manual',999))
        self.assertEqual(diff,{'added':0,'changed':0,'unchanged':1,'reactivated':0,'removed':0})
    def test_added_changed_removed_and_reactivated(self):
        stats={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        catalog.begin_snapshot(self.c)
        changed={**offer(),'description':'An updated synopsis'}
        new=offer(title='Second',url='https://example.org/2.mp4')
        catalog.ingest_incremental(self.c,[changed,new],10,stats)
        result=catalog.finish_snapshot(self.c,10,stats)
        self.assertEqual((result['changed'],result['added'],result['removed']),(1,1,0))
        catalog.begin_snapshot(self.c)
        stats={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        catalog.ingest_incremental(self.c,[new],11,stats)
        result=catalog.finish_snapshot(self.c,11,stats)
        self.assertEqual(result['removed'],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers WHERE active=0').fetchone()[0],1)
        catalog.begin_snapshot(self.c)
        stats={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        catalog.ingest_incremental(self.c,[offer(),new],12,stats)
        result=catalog.finish_snapshot(self.c,12,stats)
        self.assertEqual((result['reactivated'],result['unchanged'],result['removed']),(1,1,0))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers WHERE active=1').fetchone()[0],2)
    def test_old_availability_survives_failed_feed(self):
        with tempfile.TemporaryDirectory() as root:
            db=database(root)
            with db() as c:
                c.executescript(catalog.SCHEMA)
                catalog.ingest(c,[offer()],seen=1)
            svc=catalog_service.Service(db,lambda:{},threading.Event(),Path(root))
            def broken(_):
                yield offer('Other','Other','https://example.org/other.mp4')
                raise ValueError('abgeschnitten')
            with patch('filmlist.read_rows',side_effect=broken):
                with self.assertRaises(ValueError):svc.import_snapshot('unused',2,lambda:False)
            with db() as c:
                self.assertEqual(c.execute('SELECT active FROM offers WHERE id=(SELECT id FROM offers LIMIT 1)').fetchone()[0],1)
                self.assertFalse(catalog.get_state(c,'last_complete',False))
    def test_new_entries_tracked_for_incremental_format_pass(self):
        catalog.set_state(self.c,'format_cursor','complete')
        catalog.set_state(self.c,'format_rev',catalog.FORMAT_REV)
        catalog.begin_snapshot(self.c)
        changes={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        catalog.ingest_incremental(self.c,[offer('Second',url='https://example.org/2.mp4')],20,changes)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM format_dirty').fetchone()[0],1)
        catalog.assign_formats(self.c)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM format_dirty').fetchone()[0],0)
        self.assertEqual(catalog.get_state(self.c,'format_cursor'),'complete')

class SeriesIdentityTests(unittest.TestCase):
    def test_unique_confirmed_show_identity_never_invents_episode_evidence(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[offer('One-off episode')])
            r=c.execute('SELECT * FROM works').fetchone()
            template={'kind':'series','title':'Example Series','provider':'TVDB','reference_id':'998',
                      'year':2021,'season':9,'episode':77,'episode_verified':True,'episode_reference_id':'episode_77',
                      'genres':['Drama']}
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)',(catalog.key('Example Series'),'TVDB','998',json.dumps(template)))
            known=catalog.series_template_candidate(c,r,offer('One-off episode'))
            self.assertEqual((known['kind'],known['provider'],known['reference_id']),('series','TVDB','998'))
            self.assertIsNone(known.get('season'))
            self.assertIsNone(known.get('episode'))
            self.assertFalse(known['episode_verified'])
            self.assertNotIn('episode_reference_id',known)
    def test_ambiguous_or_mismatched_template_is_not_applied(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
            catalog.ingest(c,[offer('Episode')])
            row=c.execute('SELECT * FROM works').fetchone()
            for reference in ('a','b'):
                c.execute('INSERT INTO series_templates VALUES(?,?,?,?)',(catalog.key('Example Series'),'TVDB',reference,json.dumps({'kind':'series','title':'Example Series','provider':'TVDB','reference_id':reference})))
            self.assertIsNone(catalog.series_template_candidate(c,row,offer('Episode')))

class AvailabilityTests(unittest.TestCase):
    def test_date_only_and_timezone_and_invalid(self):
        self.assertEqual(broadcaster.expiry_iso('30.11.2026'),'2026-11-30')
        self.assertEqual(broadcaster.expiry_iso('2026-11-30'),'2026-11-30')
        self.assertEqual(broadcaster.expiry_iso('2026-11-30T22:00:00Z'),'2026-11-30T22:00:00Z')
        self.assertEqual(broadcaster.expiry_iso('2026-11-30T22:00:00'),'')
        self.assertEqual(broadcaster.expiry_iso('unbekannt'),'')
    def test_broadcast_date_is_not_availability_end(self):
        self.assertEqual(broadcaster.parse_ard(ard_page())['available_until'],'')
        self.assertEqual(broadcaster.parse_zdf(zdf_data())['available_until'],'')
        page=ard_page();page['widgets'][0]['mediaCollection']['embedded']['meta']['availableUntil']='2026-11-30T22:00:00Z'
        self.assertEqual(broadcaster.parse_ard(page)['available_until'],'2026-11-30T22:00:00Z')
    def test_optional_feed_expiry_stays_unknown_without_column(self):
        header=['Sender','Thema','Titel','Dauer','Url','Verfügbar bis']
        raw=['ARD','Example Series','Pilot','00:30:00','https://example.org/1.mp4','30.11.2026']
        text='{"Filmliste":'+json.dumps(header)+',"X":'+json.dumps(raw)+'}'
        rows=list(filmlist.adapt(filmlist.pairs(io.StringIO(text))))
        self.assertEqual(rows[0]['available_until'],'2026-11-30')
        header=header[:-1];raw=raw[:-1]
        text='{"Filmliste":'+json.dumps(header)+',"X":'+json.dumps(raw)+'}'
        rows=list(filmlist.adapt(filmlist.pairs(io.StringIO(text))))
        self.assertNotIn('available_until',rows[0])
    def test_offer_availability_is_per_offer_not_shared_between_episodes(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row;c.executescript(catalog.SCHEMA)
            a=offer();b=offer(title='Second',url='https://example.org/2.mp4')
            catalog.ingest(c,[a,b])
            ids=[r[0] for r in c.execute('SELECT id FROM offers ORDER BY id')]
            c.execute('INSERT INTO offer_availability VALUES(?,?,?,?)',(ids[0],'2026-12-01','ARD Mediathek',time.time()))
            self.assertEqual(catalog.source(c,ids[0])['available_until'],'2026-12-01')
            self.assertNotIn('available_until',catalog.source(c,ids[1]))

if __name__=='__main__':unittest.main()
