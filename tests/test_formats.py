"""News and magazine contributions go under their format and stay out of the provider scan (0.5.1)."""
import json,sys,tempfile,threading,unittest,unittest.mock
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog,catalog_service
from test_diagnosis_fixes import database

def offer(title,topic,channel='ZDF',duration=900,n=0):
    return {'title':title,'topic':topic,'description':'','duration':duration,'channel':channel,'url_video':'https://example.org/%s-%d.mp4'%(channel,n)}

class FormatRuleTests(unittest.TestCase):
    def test_format_words_need_a_recurring_topic(self):
        m={'kind':'unknown'}
        self.assertTrue(catalog.format_contribution(m,offer('Merz in Washington','aktuell (16 Uhr)'),2))
        self.assertFalse(catalog.format_contribution(m,offer('Merz in Washington','aktuell (16 Uhr)'),1))
    def test_short_clips_of_a_frequent_topic(self):
        self.assertTrue(catalog.format_contribution({'kind':'unknown'},offer('Zecken im Garten','Servicezeit',duration=240),3))
        self.assertFalse(catalog.format_contribution({'kind':'unknown'},offer('Zecken im Garten','Servicezeit',duration=1800),3))
    def test_films_series_generic_topics_and_requests_stay(self):
        source=offer('Ein Tag im Juli','tagesschau')
        for m in ({'kind':'movie'},{'kind':'series'},{'kind':'unknown','scan_requested':True}):self.assertFalse(catalog.format_contribution(m,source,5))
        self.assertFalse(catalog.format_contribution({'kind':'unknown'},offer('Liebe aktuell','Filme im Ersten'),9))
        self.assertFalse(catalog.format_contribution({'kind':'unknown'},offer('Trailer: Tatort','heute journal'),9))
        self.assertFalse(catalog.format_contribution({'kind':'unknown'},offer('Leben heute','37 Grad'),9))

class AssignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=database(self.tmp.name)
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c,[offer('Merz in Washington','aktuell (16 Uhr)',n=1),offer('Unwetter in Bayern','aktuell (16 Uhr)',n=2),offer('Der Pate','Spielfilm',duration=10000,n=3)])
    def tearDown(self):self.tmp.cleanup()
    def test_contributions_grouped_and_skipped_by_queue(self):
        with self.db() as c:
            self.assertEqual(catalog.assign_formats(c),(3,2));self.assertEqual(catalog.assign_formats(c),(0,0))
            self.assertEqual(catalog.get_state(c,'format_cursor'),'complete')
            rows=c.execute("SELECT * FROM works WHERE state='format'").fetchall()
            self.assertEqual({r['title'] for r in rows},{'aktuell (16 Uhr)'});self.assertEqual(len({r['show_key'] for r in rows}),1)
            m=json.loads(rows[0]['meta']);self.assertEqual((m['kind'],m['provider']),('series','Sendung'));self.assertIn(m['episode_title'],('Merz in Washington','Unwetter in Bayern'))
            self.assertEqual(catalog.stats(c)['formats'],2);self.assertEqual(catalog.stats(c)['pending'],1)
            service=catalog_service.Service(self.db,dict,threading.Event(),Path(self.tmp.name))
            picked=service.pick(c);self.assertEqual(picked['kind'],'movie')
            self.assertEqual(catalog.listing(c,state='format')['total'],1)
    def test_explicit_request_scans_once_and_stays_out(self):
        with self.db() as c:
            catalog.assign_formats(c);wid=c.execute("SELECT id FROM works WHERE state='format'").fetchone()[0]
            self.assertEqual(catalog.prioritize(c,[wid]),1)
            self.assertEqual(c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()[0],'pending')
            self.assertTrue(json.loads(c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()[0])['scan_requested'])
            catalog.restart_formats(c);catalog.assign_formats(c)
            self.assertEqual(c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()[0],'pending')
    def test_recognition_per_channel(self):
        with self.db() as c:
            catalog.assign_formats(c);c.execute("UPDATE works SET state='identified' WHERE kind='movie'")
            rows=catalog.recognition(c)
        self.assertEqual(rows,[{'channel':'ZDF','works':3,'matched':0,'identified':1,'format':2,'open':0,'review':0}])
    def test_import_restarts_format_pass(self):
        service=catalog_service.Service(self.db,dict,threading.Event(),Path(self.tmp.name))
        with self.db() as c:catalog.assign_formats(c);catalog.assign_formats(c)
        rows=[offer('Neue Ausgabe','aktuell (16 Uhr)',n=9)]
        with unittest.mock.patch('filmlist.read_rows',return_value=rows):service.import_snapshot('x',0,lambda:False)
        with self.db() as c:self.assertEqual(catalog.get_state(c,'format_cursor'),0)
        self.assertTrue(service.format_wake.is_set())
if __name__=='__main__':unittest.main()
