"""0.6.41: episode search files Sendungsausgaben and Beiträge instead of failing on them.

Diagnosis 19.11.2026 (0.6.40, Björn): 20,965 episode checks, 2.4 % matched, 66 % without result,
32 % "unsicher". 82 % of the series identified in the diagnosis window were editions of news and
regional magazines (SWR Aktuell Rheinland-Pfalz, buten un binnen, MDR Sachsenspiegel, DER TAG …);
91 % of the runtime suspicions were 1–6 minute clips of 28-minute Sendungen; 43,648 sender claims were
postponed by the hourly sender allowance. No threshold is lowered: editions and contributions are
filed as such (state 'format'), never counted as matched episodes.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import broadcaster
import catalog
import catalog_service
import diagnostics
import imdb_archive
import matching
from tests import test_v0624_episode_search as base


EXTRA={
    'basics':[
        'tt500\ttvSeries\t3nach9\t3nach9\t0\t1974\t\\N\t180\tTalk-Show',
        'tt501\ttvEpisode\tEpisode dated 14 November 2026\tEpisode dated 14 November 2026\t0\t2026\t\\N\t\\N\tTalk-Show',
        'tt502\ttvEpisode\tEpisode dated 7 November 2026\tEpisode dated 7 November 2026\t0\t2026\t\\N\t\\N\tTalk-Show',
        'tt600\ttvSeries\tMDR Sachsenspiegel\tMDR Sachsenspiegel\t0\t1992\t\\N\t30\tNews',
        'tt700\ttvSeries\tDonna Leon\tDonna Leon\t0\t2000\t\\N\t90\tCrime',
        'tt701\ttvEpisode\tDas Gesetz der Lagune\tDas Gesetz der Lagune\t0\t2008\t\\N\t90\tCrime',
    ],
    'episode':['tt501\ttt500\t52\t10','tt502\ttt500\t52\t9','tt701\ttt700\t1\t12'],
}


def build_archive(root):
    rows={k:list(v) for k,v in base.ROWS.items()}
    for kind,more in EXTRA.items():rows[kind]=rows[kind]+more
    with patch.object(base,'ROWS',rows):
        return base.build_archive(root)


class RuleTests(unittest.TestCase):
    def role(self,title,series='MDR Sachsenspiegel',duration=1700,**meta):
        date=imdb_archive.title_date(title)
        stamp=int(time.mktime((date[1],date[2],date[3],19,0,0,0,0,-1))) if date else int(time.time())
        return catalog.recurring_edition({'kind':'series','title':series,**meta},
                                         {'title':title,'topic':series,'duration':duration,'timestamp':stamp})

    def test_dated_title_is_an_edition(self):
        for title in ('MDR Sachsenspiegel vom 19.11.2026','Sachsenspiegel | 19.11.2026',
                      'ttt vom 2. Februar 2025','28 minutes (13/11/2026)'):
            with self.subTest(title=title):self.assertEqual(self.role(title),'edition')
        # Without a format word only the offer's own broadcast day counts as edition date.
        stamp=int(time.mktime((2026,11,14,22,0,0,0,0,-1)))
        def other(title,timestamp):
            return catalog.recurring_edition({'kind':'series','title':'3nach9'},
                {'title':title,'topic':'3nach9','duration':10800,'timestamp':timestamp})
        self.assertEqual(other('3nach9 vom 14.11.2026',stamp),'edition')
        self.assertIsNone(other('3nach9 vom 14.11.2026',stamp+30*86400))
        self.assertIsNone(other('3nach9 vom 14.11.2026',None))
        tatort=catalog.recurring_edition({'kind':'series','title':'Tatort'},
            {'title':'Die Nacht vom 9. November 1989','topic':'Tatort','duration':5400,'timestamp':stamp})
        self.assertIsNone(tatort)

    def test_magazine_title_alone_is_an_edition_and_short_clip_a_contribution(self):
        self.assertEqual(self.role('buten un binnen | regionalmagazin',series='buten un binnen | regionalmagazin'),'edition')
        self.assertEqual(self.role('Werder-Fans feiern in der Innenstadt',series='buten un binnen | regionalmagazin',duration=149),'segment')
        self.assertEqual(self.role('Unwetter im Westerwald',series='SWR Aktuell Rheinland-Pfalz',duration=105),'segment')

    def test_scripted_series_and_numbered_offers_are_never_editions(self):
        # Short clip of a drama: stays with the runtime check ("unsicher"), no Sendung rule applies.
        self.assertIsNone(self.role('Ein Abschied',series='In aller Freundschaft – Die jungen Ärzte',duration=150))
        self.assertIsNone(self.role('Ein Abschied',series='In aller Freundschaft – Die jungen Ärzte'))
        for title in ('Folge 12 vom 19.11.2026','Rückblick (2/6)','S01E02 Wetterlage','Teil 3: Wetter'):
            with self.subTest(title=title):self.assertIsNone(self.role(title,duration=150))
        self.assertIsNone(self.role('Wetter',episode=4,duration=150))
        self.assertIsNone(self.role('Trailer: Sachsenspiegel vom 19.11.2026'))
        self.assertIsNone(self.role('MDR Sachsenspiegel vom 19.11.2026',scan_requested=True))
        self.assertIsNone(self.role('MDR Sachsenspiegel vom 19.11.2026',episode_verified=True))
        # A full-length magazine edition with its own topic is not filed by length alone.
        self.assertIsNone(self.role('Die Wahl in Sachsen',duration=1700))

    def test_title_date_and_imdb_name(self):
        self.assertEqual(imdb_archive.dated_episode_name('3nach9 vom 14.11.2026'),'Episode dated 14 November 2026')
        self.assertEqual(imdb_archive.dated_episode_name('ttt vom 2. Februar 2025'),'Episode dated 2 February 2025')
        self.assertEqual(imdb_archive.dated_episode_name('28 minutes (13/11/2026)'),'Episode dated 13 November 2026')
        self.assertEqual(imdb_archive.dated_episode_name('Ausgabe 31.02.2026'),'')
        self.assertEqual(imdb_archive.dated_episode_name('Vom 1.11.2026 bis 8.11.2026'),'')
        self.assertEqual(imdb_archive.dated_episode_name('Das Vorsprechen'),'')

    def test_labels_and_counters_are_removed_from_probes(self):
        terms=imdb_archive.episode_search_terms({'title':'Donna Leon (12) – Das Gesetz der Lagune'},{},'Donna Leon')
        self.assertIn('das gesetz der lagune',terms)
        terms=imdb_archive.episode_search_terms({'title':'Das Vorsprechen - Audiodeskription'},{},'Find me in Paris')
        self.assertIn('das vorsprechen',terms)
        terms=imdb_archive.episode_search_terms({'title':'3nach9 vom 14.11.2026'},{},'3nach9')
        self.assertEqual(terms[-1],'episode dated 14 november 2026')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.archive=build_archive(Path(tmp.name))

    def tearDown(self):
        opened=getattr(self.archive._reader_local,'opened',None)
        if opened:opened[1].close()

    def choose(self,title,topic,year,duration=10800):
        src={'title':title,'topic':topic,'duration':duration}
        m=base.identified(catalog.seed(src),title=topic,provider='TVDB',reference_id='5',year=year)
        return matching.choose(m,self.archive.episode_evidence(src,m)['candidates'])

    def test_dated_edition_matches_imdb_episode_dated(self):
        chosen=self.choose('3nach9 vom 14.11.2026','3nach9',1974)
        self.assertEqual(chosen['episode_reference_id'],'tt501')
        self.assertEqual(chosen['episode_match'],'date')
        self.assertEqual(chosen['episode_title'],'3nach9 vom 14.11.2026')
        self.assertIn('Sendedatum',chosen['reason'])
        self.assertIsNone(self.choose('3nach9 vom 21.11.2026','3nach9',1974))

    def test_counter_in_title_no_longer_blocks_the_episode(self):
        chosen=self.choose('Donna Leon (12) – Das Gesetz der Lagune','Donna Leon',2000,duration=5400)
        self.assertEqual((chosen['season'],chosen['episode'],chosen['episode_reference_id']),(1,12,'tt701'))


class WorkerTests(base.WorkerTests):
    """Reuses the 0.6.24 worker fixture with the extended archive."""

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'catalog.db'
        self.archive=build_archive(self.root)
        self.addCleanup(self.close_archive)
        self.direct=False
        self.settings=lambda:{'auto_metadata':True,'episode_workers':2,'metadata_workers':2,
                              'sender_direct_lookup':self.direct,'scan_priority':'series_first',
                              'complete_series':False}
        with self.db() as c:c.executescript(catalog.SCHEMA)
        self.svc=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)

    def run_once(self):
        with patch.object(imdb_archive,'ACTIVE',self.archive):
            self.assertTrue(self.svc.metadata_once('episode'))

    def work(self,wid):
        with self.db() as c:
            row=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
            return row['state'],json.loads(row['meta'])

    def only_due(self,wid):
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=?',(time.time()+3600,))
            c.execute('UPDATE episode_queue SET next_try=0 WHERE work_id=?',(wid,))

    def magazine(self,title,tag,duration=1700,series='MDR Sachsenspiegel',site=''):
        src=base.offer(title,series,tag,site);src['duration']=duration
        date=imdb_archive.title_date(title)
        # MediathekView lists each offer with its broadcast time.
        src['timestamp']=int(time.mktime((date[1],date[2],date[3],19,0,0,0,0,-1))) if date else int(time.time())
        return self.add(src,series,1992,reference='600')

    def test_dated_editions_are_filed_with_their_sendung_in_one_pass(self):
        ids=[self.magazine('MDR Sachsenspiegel vom %d.11.2026'%d,'s%d'%d) for d in range(1,6)]
        clip=self.magazine('Hochwasser in Grimma','s-clip',duration=140)
        numbered=self.magazine('Folge 7: Sachsen im Wandel','s-num')
        with self.db() as c:c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(ids[4],time.time()))
        self.only_due(ids[0])
        self.run_once()
        state,m=self.work(ids[0])
        self.assertEqual(state,'format')
        self.assertEqual((m['format_grouping'],m['provider'],m['reference_id'],m['title']),
                         ('edition','TMDB','600','MDR Sachsenspiegel'))
        self.assertFalse(m['episode_verified'])
        self.assertIn('Ausgabe der Sendung',m['reason'])
        for wid in ids[1:4]:
            self.assertEqual(self.work(wid)[0],'format');self.assertIsNone(self.queue(wid))
        self.assertEqual(self.work(clip)[1]['format_grouping'],'segment')
        # A user priority and a numbered episode stay in the queue.
        self.assertEqual(self.work(ids[4])[0],'identified');self.assertIsNotNone(self.queue(ids[4]))
        self.assertEqual(self.work(numbered)[0],'identified');self.assertIsNotNone(self.queue(numbered))
        self.assertEqual((self.svc.episode_editions,self.svc.episode_segments,self.svc.episode_matched),(4,1,0))
        progress=self.svc.scan_progress()
        self.assertEqual((progress['episode_editions_session'],progress['episode_segments_session']),(4,1))

    def test_short_contribution_is_filed_not_suspected(self):
        # Without a format word and without filed editions a clip is not filed as contribution.
        lone=self.magazine('Hochwasser in Grimma','c0',duration=140)
        self.only_due(lone)
        self.run_once()
        self.assertEqual(self.work(lone)[0],'identified')
        self.assertEqual(self.svc.episode_segments,0)
        a=self.magazine('Unwetter im Westerwald','c1',duration=140,series='SWR Aktuell Rheinland-Pfalz')
        b=self.magazine('Neue Brücke in Mainz','c2',duration=200,series='SWR Aktuell Rheinland-Pfalz')
        self.only_due(a)
        self.run_once()
        for wid in (a,b):
            state,m=self.work(wid)
            self.assertEqual((state,m['format_grouping']),('format','segment'))
            self.assertFalse(m.get('video_role_needs_review'))
        self.assertEqual((self.svc.episode_segments,self.svc.episode_suspected),(2,0))

    def test_imdb_dated_episode_is_matched_unless_two_editions_share_the_day(self):
        src=base.offer('3nach9 vom 14.11.2026','3nach9','t1');src['duration']=10800
        wid=self.add(src,'3nach9',1974,reference='500')
        self.only_due(wid)
        self.run_once()
        with self.db() as c:
            rows=c.execute("SELECT * FROM works WHERE state='matched'").fetchall()
        self.assertEqual(len(rows),1)
        m=json.loads(rows[0]['meta'])
        self.assertEqual((m['episode_reference_id'],m['episode_match'],m['season'],m['episode']),('tt501','date',52,10))
        self.assertEqual(self.svc.episode_matched,1)
        # Two offers of 7 November: IMDb's single "Episode dated 7 November 2026" cannot be both.
        first=base.offer('3nach9 vom 7.11.2026','3nach9','t2');first['duration']=10800
        second=base.offer('3nach9 (Wiederholung) vom 7.11.2026','3nach9','t3');second['duration']=10800
        first['timestamp']=second['timestamp']=int(time.mktime((2026,11,7,22,0,0,0,0,-1)))
        a=self.add(first,'3nach9',1974,reference='500');self.add(second,'3nach9',1974,reference='500')
        self.only_due(a)
        self.run_once()
        state,m=self.work(a)
        self.assertEqual((state,m['format_grouping']),('format','edition'))
        self.assertIsNone(m.get('episode_reference_id'))

    def test_dated_edition_does_not_use_the_sender_allowance(self):
        self.direct=True
        ard='https://www.ardmediathek.de/video/sachsenspiegel/folge/mdr/Y3JpZDovL21kci5kZS9hYmMxMjM'
        wid=self.magazine('MDR Sachsenspiegel vom 3.11.2026','a1',site=ard)
        self.only_due(wid)
        with patch.object(broadcaster,'lookup_limited',side_effect=AssertionError('sender asked')):
            self.run_once()
        self.assertEqual(self.work(wid)[0],'format')
        self.assertEqual(self.svc.episode_retried,0)

    def test_unresolved_checks_leave_countable_examples(self):
        src=base.offer('Ein Abschied','Find me in Paris','u1')
        wid=self.add(src,'Find me in Paris',2018)
        self.only_due(wid)
        with patch.object(diagnostics,'event') as event:self.run_once()
        samples=[k for a,k in event.call_args_list if a and a[0]=='episode_unresolved_sample']
        self.assertEqual(len(samples),1)
        self.assertEqual((samples[0]['cause'],samples[0]['title'],samples[0]['series']),
                         ('no_episode_match','Ein Abschied','Find me in Paris'))

    def test_earlier_results_without_hit_are_rechecked_once_after_start(self):
        a=self.magazine('Neues aus Leipzig','r1')
        b=self.magazine('Neues aus Dresden','r2')
        later=time.time()+20*86400
        with self.db() as c:
            c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=? WHERE work_id=?",(later,a))
            c.execute("UPDATE episode_queue SET last_outcome='no_imdb_episodes',next_try=? WHERE work_id=?",(later,b))
        self.assertTrue(catalog.build_deferred_indexes(self.db))
        self.assertEqual((self.queue(a)['next_try'],self.queue(b)['next_try']),(0,0))
        with self.db() as c:c.execute('UPDATE episode_queue SET next_try=?',(later,))
        catalog.build_deferred_indexes(self.db)
        self.assertEqual(self.queue(a)['next_try'],later)


# The inherited 0.6.24 cases run in their own module.
for name in [n for n in vars(base.WorkerTests) if n.startswith('test_')]:
    if not hasattr(WorkerTests,name) or getattr(WorkerTests,name) is getattr(base.WorkerTests,name):
        setattr(WorkerTests,name,None)


if __name__=='__main__':unittest.main()
