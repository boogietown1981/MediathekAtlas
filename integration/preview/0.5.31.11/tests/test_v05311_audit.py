"""Regression tests for safe re-audit and UPSERT-resistant episode triggers."""
import json
import pathlib
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_05311

# Import video_backfill with injectable catalogue dependencies, without needing
# to download the entire upstream MediathekAtlas project into this test sandbox.
cat=types.ModuleType('catalog')
cat.get_state=lambda c,k,default=None:json.loads(c.execute('SELECT value FROM catalog_state WHERE key=?',(k,)).fetchone()[0]) if c.execute('SELECT 1 FROM catalog_state WHERE key=?',(k,)).fetchone() else default
cat.set_state=lambda c,k,v:c.execute('INSERT INTO catalog_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v)))
caus=types.ModuleType('video_causality')
def _evidence(source,m):
    expected=float(m.get('reference_runtime_seconds') or 0)
    actual=float(source.get('duration') or 0)
    if actual and expected >=600 and actual<=min(600,expected*.4):
        return {'video_role':'short_excerpt_suspected',
                'video_role_reason':'Laufzeit unplausibel',
                'video_role_evidence':'independent_runtime',
                'source_duration_seconds':actual,'expected_runtime_seconds':expected,
                'expected_runtime_source':m.get('reference_runtime_source')}
    return None
caus.evaluate=_evidence
caus.expected_seconds=lambda m:float(m.get('reference_runtime_seconds') or 0)
caus.sample_series_runtime=lambda c,show_key,exclude_work='':None
with patch.dict(sys.modules,{'catalog':cat,'video_causality':caus}):
    import video_backfill

class TriggerTests(unittest.TestCase):
    def test_safe_trigger_does_not_duplicate_under_outer_upsert(self):
        # SQLite's outer UPSERT can override OR IGNORE in a trigger. Use an
        # explicit NOT EXISTS guard instead of relying on conflict precedence.
        c=sqlite3.connect(':memory:')
        c.executescript('''
            CREATE TABLE works(id TEXT PRIMARY KEY,meta TEXT,kind TEXT,state TEXT);
            CREATE TABLE episode_queue(work_id TEXT PRIMARY KEY);
            CREATE TRIGGER episode_queue_work_update AFTER UPDATE OF meta ON works BEGIN
               INSERT INTO episode_queue(work_id)
               SELECT NEW.id WHERE NEW.kind='series' AND NEW.state='identified'
                 AND NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);
            END;
        ''')
        c.execute("INSERT INTO works VALUES('x','{}','series','identified')")
        c.execute("INSERT INTO episode_queue VALUES('x')")
        for _ in range(3):
            c.execute("INSERT INTO works VALUES('x','{}','series','identified') ON CONFLICT(id) DO UPDATE SET meta=excluded.meta")
        self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0],1)
        c.close()

class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE catalog_state(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE works(id TEXT PRIMARY KEY,kind TEXT,state TEXT,meta TEXT,title TEXT,updated REAL,show_key TEXT);
          CREATE TABLE offers(work_id TEXT,active INTEGER,rank INTEGER,seen REAL,payload TEXT);
        ''')
        source={'title':'Anime E03', 'duration':120}
        meta={'kind':'series','title':'Beispielserie','provider':'TMDB',
              'reference_id':'123','reference_runtime_seconds':1200,'episode_verified':True}
        for ident,state in [('m','manual'),('a','matched'),('i','identified')]:
            self.c.execute('INSERT INTO works VALUES(?,?,?,?,?,?,?)',(ident,'series',state,json.dumps(meta),'Beispiel',1.0,'show123'))
            self.c.execute('INSERT INTO offers VALUES(?,?,?,?,?)',(ident,1,10,1.0,json.dumps(source)))
        self.c.commit()

    def tearDown(self):self.c.close()

    def test_existing_manual_and_auto_verified_are_preserved(self):
        original=dict(self.c.execute("SELECT * FROM works WHERE id='m'").fetchone())
        video_backfill.initialize(self.c)
        n=video_backfill.audit_batch(self.c,2)
        self.assertEqual(n,2)
        self.assertEqual(dict(self.c.execute("SELECT * FROM works WHERE id='m'").fetchone()),original)
        self.assertEqual(self.c.execute("SELECT state FROM works WHERE id='a'").fetchone()[0],'matched')
        self.assertTrue(json.loads(self.c.execute("SELECT meta FROM works WHERE id='a'").fetchone()[0])['episode_verified'])
        self.assertEqual(video_backfill.audit_batch(self.c,2),1)
        self.assertEqual(video_backfill.audit_batch(self.c,2),0)
        self.assertEqual(video_backfill.status(self.c)['phase'],'complete')
        self.assertEqual(video_backfill.status(self.c)['flagged'],3)
        self.assertEqual(video_backfill.status(self.c)['manual_flags'],1)
        self.assertTrue(json.loads(self.c.execute("SELECT meta FROM works WHERE id='i'").fetchone()[0])['video_role_needs_review'])
        self.assertFalse(json.loads(self.c.execute("SELECT meta FROM works WHERE id='i'").fetchone()[0])['episode_verified'])

    def test_series_median_fallback_flags_short_existing_episode(self):
        # When the provider has no duration, five comparable existing episodes
        # supply weaker evidence for review, not automatic reclassification.
        row=self.c.execute("SELECT meta FROM works WHERE id='i'").fetchone()
        m=json.loads(row['meta']);m.pop('reference_runtime_seconds',None)
        self.c.execute("UPDATE works SET meta=? WHERE id='i'",(json.dumps(m),))
        with patch.object(video_backfill.video_causality,'sample_series_runtime',return_value=1200) as median:
            video_backfill.initialize(self.c)
            video_backfill.audit_batch(self.c,10)
        self.assertTrue(median.called)
        stored=json.loads(self.c.execute("SELECT meta FROM works WHERE id='i'").fetchone()[0])
        self.assertTrue(stored.get('video_role_needs_review'))
        self.assertEqual(self.c.execute("SELECT state FROM works WHERE id='i'").fetchone()[0],'identified')
        self.assertEqual(stored.get('expected_runtime_source'),'Serien-Katalogmedian (mind. 5 Vergleichsangebote)')

    def test_resume_from_saved_cursor_no_repeat(self):
        video_backfill.initialize(self.c)
        self.assertEqual(video_backfill.audit_batch(self.c,1),1)
        marker=cat.get_state(self.c,video_backfill.CURSOR)
        self.assertEqual(video_backfill.audit_batch(self.c,2),2)
        self.assertEqual(video_backfill.status(self.c)['processed'],3)
        self.assertNotEqual(marker,cat.get_state(self.c,video_backfill.CURSOR))

class InstallerIntegration(unittest.TestCase):
    def test_expected_real_anchor_fixtures(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            (root/'web').mkdir()
            # In this fixture the complete Netzkino preview has already been
            # installed, so only the 0.5.31.1 changes are applied.
            (root/'catalog.py').write_text("""SCHEMA='''
CREATE TABLE episode_queue(work_id TEXT PRIMARY KEY);
CREATE TRIGGER episode_queue_work_insert AFTER INSERT ON works BEGIN
 INSERT OR IGNORE INTO episode_queue(work_id) VALUES(NEW.id);
END;
CREATE TRIGGER episode_queue_work_update AFTER UPDATE OF id,kind,state,meta ON works BEGIN
 INSERT OR IGNORE INTO episode_queue(work_id)
 SELECT NEW.id WHERE NEW.kind='series'
 AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0;
END;
'''
def initialize(c):
    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:pass
""")
            (root/'catalog_service.py').write_text("""    def start(self):
        for fn in (self.sync_loop,self.reclassify_loop,self.artwork_loop):pass
    def reclassify_loop(self):
        pass
""")
            (root/'server.py').write_text("""import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino
if path in ('/app.js','/player.js','/netzkino.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')
        if path=='/api/netzkino':
            pass
""")
            (root/'web/index.html').write_text('<section id="review" hidden><script src="/netzkino.js"></script>')
            (root/'web/style.css').write_text('body{}')
            (root/'version.py').write_text("VERSION='0.5.31'\n")
            (root/'build_macos.py').write_text("for name in ('netzkino.py','server.py'): pass")
            (root/'CHANGELOG.md').write_text('Previous changes\n')
            update=apply_05311.patches(root)
            self.assertIn('video_backfill.py',update)
            self.assertIn('video-audit',update['web/index.html'].decode())
            self.assertIn('episode_queue_safe_upsert_v05311',update['catalog.py'].decode())
            self.assertNotIn('INSERT OR IGNORE INTO episode_queue(work_id)',update['catalog.py'].decode())
            self.assertIn("VERSION='0.5.31.1'",update['version.py'].decode())
            apply_05311.install(root)
            self.assertEqual((root/'video_backfill.py').read_bytes(),(ROOT/'video_backfill.py').read_bytes())
            with self.assertRaises(RuntimeError):apply_05311.install(root)

if __name__=='__main__':unittest.main()
