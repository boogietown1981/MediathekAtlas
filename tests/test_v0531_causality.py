"""0.5.31: independently grounded video causality and responsive settings."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import downloads
import matching
import video_causality


ROOT=Path(__file__).resolve().parents[1]


def offer(title='Anime – Trailer', duration=120, topic='Musteranime'):
    return {'title':title,'topic':topic,'description':'Zeichentrickserie',
            'duration':duration,'channel':'ARD',
            'url_video':'https://example.org/anime.mp4'}


class VideoCausalityUnitTests(unittest.TestCase):
    def test_explicit_trailer_and_opening_are_extras(self):
        for title in ('Musteranime - Trailer','Trailer: Musteranime',
                      'Musteranime | Opening','Musteranime (Ausschnitt)',
                      'Anime – Preview','Teaser zur Anime-Serie'):
            with self.subTest(title=title):
                self.assertIsNotNone(video_causality.explicit_format(offer(title=title)))
        for title in ('Trailer Park Boys','Anime mit Trailer im Interview',
                      'Ein kurzer Film','Die Geschichte eines Teasers'):
            with self.subTest(title=title):
                self.assertIsNone(video_causality.explicit_format(offer(title=title)))

    def test_two_minutes_against_twenty_minutes_is_a_conflict(self):
        observed=video_causality.evaluate(offer('Episode 3',120),
                            {'kind':'series','reference_runtime_seconds':1200})
        self.assertEqual(observed['video_role'],'short_excerpt_suspected')
        self.assertEqual(observed['source_duration_seconds'],120)
        self.assertEqual(observed['expected_runtime_seconds'],1200)

    def test_short_format_anime_is_not_rejected_without_independent_reference(self):
        for expected in (None,120,150,240):
            with self.subTest(expected=expected):
                meta={'reference_runtime_seconds':expected}
                self.assertIsNone(video_causality.evaluate(offer('Episode 3',120),meta))

    def test_unknown_duration_never_causes_false_suspicion(self):
        self.assertIsNone(video_causality.evaluate(offer('Episode 3',0),
                  {'reference_runtime_seconds':1200}))

    def test_movie_like_title_is_not_declared_episode(self):
        matched=video_causality.evaluate(offer('Trailer Park Boys',120),
                  {'reference_runtime_seconds':1200})
        self.assertEqual(matched['video_role'],'short_excerpt_suspected')
        self.assertEqual(matched['video_role_evidence'],'independent_runtime')

    def test_episode_conflict_keeps_series_identity_without_full_match(self):
        meta={'title':'Musteranime','kind':'series','episode_title':'Episode 3'}
        candidate={'title':'Musteranime','kind':'series',
                   'provider':'IMDb Offline','reference_id':'tt123',
                   'similarity':1.0,'confidence':'high','year':2010,
                   'episode_verified':True,'season':1,'episode':3,
                   'reference_runtime_seconds':1200}
        video_causality.annotate(offer('Episode 3',120),candidate)
        self.assertTrue(candidate['runtime_mismatch'])
        self.assertFalse(candidate['episode_verified'])
        self.assertIsNone(matching.choose(meta,[candidate]))
        work=matching.choose(meta,[candidate],work_only=True)
        self.assertIsNotNone(work)
        self.assertTrue(work['video_role_needs_review'])

    def test_explicit_extra_import_cannot_become_series_template(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            catalog.initialize(c)
            c.execute('INSERT INTO series_templates(topic,provider,reference,meta) VALUES(?,?,?,?)',
                ('musteranime','TMDB','23',json.dumps({'kind':'series','title':'Musteranime',
                    'provider':'TMDB','reference_id':'23','genres':[]})))
            catalog.ingest(c,[offer('Musteranime - Trailer',120)])
            w=c.execute('SELECT * FROM works').fetchone()
            self.assertEqual(w['kind'],'other')
            self.assertEqual(w['state'],'format')
            self.assertEqual(json.loads(w['meta'])['video_role'],'trailer')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)

    def test_existing_automatic_series_trailer_is_reclassified(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            catalog.initialize(c)
            src=offer('Musteranime - Trailer',120)
            catalog.ingest(c,[src])
            w=c.execute('SELECT * FROM works').fetchone()
            m=json.loads(w['meta'])
            m.update(kind='series',title='Musteranime',provider='TMDB',reference_id='23')
            c.execute("UPDATE works SET title='Musteranime',kind='series',state='identified',meta=? WHERE id=?",
                      (json.dumps(m),w['id']))
            w=c.execute('SELECT * FROM works').fetchone()
            self.assertTrue(catalog.mark_explicit_extra(c,w,src))
            row=c.execute('SELECT * FROM works').fetchone()
            self.assertEqual((row['kind'],row['state']),('other','format'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)

    def test_manual_classification_is_preserved(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            catalog.initialize(c)
            catalog.ingest(c,[offer()])
            w=c.execute('SELECT * FROM works').fetchone()
            c.execute("UPDATE works SET state='manual' WHERE id=?",(w['id'],))
            w=c.execute('SELECT * FROM works').fetchone()
            self.assertFalse(catalog.mark_explicit_extra(c,w,offer()))

    def test_suspected_episode_is_not_queued(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            catalog.initialize(c)
            catalog.ingest(c,[offer('Episode 3',120)])
            w=c.execute('SELECT * FROM works').fetchone()
            m=json.loads(w['meta'])
            m.update(kind='series',title='Musteranime',provider='IMDb Offline',
                     reference_id='tt123',reference_runtime_seconds=1200,
                     video_role_needs_review=True)
            c.execute("UPDATE works SET state='identified',kind='series',meta=? WHERE id=?",
                      (json.dumps(m),w['id']))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)

    def test_no_ffprobe_needed_for_catalog_preflight(self):
        meta={'kind':'series','title':'Musteranime','season':1,'episode':3,
              'reference_runtime_seconds':1200}
        with patch('downloads.tool',side_effect=AssertionError('No tool may run')):
            with self.assertRaisesRegex(ValueError,'keine vollständige Folge'):
                downloads.run(offer('Episode 3',120),meta,Path('/tmp'),'hd',
                              lambda *a,**k:None,lambda:False)

    def test_probe_only_confirms_actual_downloaded_file(self):
        meta={'kind':'series','reference_runtime_seconds':1200}
        self.assertTrue(downloads.check_episode_runtime(offer('Episode 3',1200),meta))
        with self.assertRaisesRegex(ValueError,'keine vollständige Folge'):
            downloads.check_episode_runtime(offer('Episode 3',1200),meta,measured_seconds=120)


class EpisodeQueueRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db_path=self.root/'catalog.db'
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c,[offer('Episode 3',120)])
            w=c.execute('SELECT * FROM works').fetchone()
            self.wid=w['id']
            m=json.loads(w['meta'])
            m.update(kind='series',title='Musteranime',provider='TMDB',
                     reference_id='44',reference_runtime_seconds=1200)
            c.execute("UPDATE works SET kind='series',state='identified',title='Musteranime',meta=? WHERE id=?",
                      (json.dumps(m),self.wid))
        self.settings=lambda:{'auto_metadata':True,'episode_workers':1,
                              'metadata_workers':1,'sender_direct_lookup':False}
        self.service=catalog_service.Service(self.db,self.settings,threading.Event(),self.root)

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=5)
        c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def test_episode_worker_uses_feed_duration_and_no_network_or_probe(self):
        with patch('broadcaster.lookup_limited',side_effect=AssertionError('No remote')):
            with patch('downloads.probe',side_effect=AssertionError('No ffprobe')):
                self.assertTrue(self.service.metadata_once('episode'))
        with self.db() as c:
            w=c.execute('SELECT state,meta FROM works WHERE id=?',(self.wid,)).fetchone()
            m=json.loads(w['meta'])
            self.assertEqual(w['state'],'identified')
            self.assertEqual(m['video_role'],'short_excerpt_suspected')
            self.assertFalse(m['episode_verified'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],0)


class SettingsStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids={}
        self.forms=[]
        self.depth=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids[attrs['id']]=self.ids.get(attrs['id'],0)+1
        if tag=='form':
            self.depth+=1
            self.forms.append((attrs.get('id'),self.depth))
    def handle_endtag(self,tag):
        if tag=='form':self.depth-=1


class SettingsLayoutTests(unittest.TestCase):
    def test_settings_use_full_width_submenus_with_existing_controls(self):
        html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
        css=(ROOT/'web'/'style.css').read_text(encoding='utf-8')
        parser=SettingsStructure();parser.feed(html)
        self.assertEqual(parser.depth,0)
        self.assertTrue(all(depth==1 for _,depth in parser.forms))
        for field in ('config','download_dir','metadata_workers','episode_workers',
                      'sender_direct_lookup','tmdb','omdb','tvdb','tvdb_pin',
                      'clear-keys','mesh-config','runtime-details','recheck-tools'):
            self.assertEqual(parser.ids.get(field),1,field)
        self.assertIn('atlas-settings-layout',html)
        self.assertEqual(html.count('atlas-settings-submenu'),3)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',css)
        self.assertIn('.atlas-settings-layout>.panel{max-width:none;',css)
        self.assertIn('@media(max-width:660px)',css)


    def test_checkbox_inputs_keep_native_dimensions_on_wide_panels(self):
        """Regression: width:100% on checkbox caused 800px tall labels."""
        css=(ROOT/'web'/'style.css').read_text(encoding='utf-8')
        html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
        # Ordinary inputs stay fluid; checkboxes retain a fixed compact size.
        self.assertIn('.atlas-settings-fields input:not([type="checkbox"])',css)
        self.assertIn('.atlas-settings-fields>label.check>input[type="checkbox"]{width:16px;height:16px;',css)
        self.assertIn('flex:0 0 16px;',css)
        self.assertIn('.atlas-settings-fields>.check{display:flex;align-items:flex-start;grid-column:auto;',css)
        for field in ('auto_catalog','auto_metadata','sender_direct_lookup','complete_series'):
            self.assertIn('type="checkbox" id="'+field+'"',html)
        # Two-column desktop settings remain independent of the window height.
        self.assertIn('.atlas-settings-fields{padding:',css)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',css)


if __name__=='__main__':unittest.main()
