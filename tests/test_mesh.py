import json,sqlite3,tempfile,threading,time,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import catalog,catalog_service,meshjournal

def row(i):
    return {'title':'Spielfilm Nummer %d'%i,'channel':'ARD','topic':'Spielfilm','description':'Spielfilm Deutschland, eine lange Beschreibung für Werk %d mit genug Text'%i,'duration':5400,'url_video':'https://example.org/%d.mp4'%i}

def candidate(source,meta,config):
    return {'candidates':[{**meta,'kind':'movie','provider':'TMDB','reference_id':'ref-'+meta['title'],'similarity':1,'runtime_agrees':True,'genres':['Drama']}],'warnings':[]}

class Node:
    def __init__(self,root,shared,**config):
        self.root=Path(root);self.config={'auto_metadata':True,'mesh_dir':str(shared),**config}
        with self.db() as c:c.executescript(catalog.SCHEMA);c.execute('CREATE TABLE metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
        self.service=catalog_service.Service(self.db,lambda:self.config,threading.Event(),self.root)
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.root/'c.db',timeout=20);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def ingest(self,rows):
        with self.db() as c:catalog.ingest(c,rows,seen=10)
    def sync(self):
        if self.service.mesh:self.service.mesh.flush(force=True)
        self.service.mesh_tick()
    def states(self):
        with self.db() as c:return {r['id']:(r['state'],json.loads(r['meta']).get('reference_id')) for r in c.execute('SELECT * FROM works')}

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'MediathekAtlasSync';self.root.mkdir();(self.root/'.meshsync-folder').write_text('token')
    def tearDown(self):self.tmp.cleanup()
    def event(self,work='ab12'):return {'work':work,'outcome':'matched','meta':{'title':'Film','kind':'movie'},'providers':['TMDB']}
    def test_folder_checks_never_create_missing_mounts(self):
        with self.assertRaisesRegex(meshjournal.MeshError,'fehlt'):meshjournal.check_folder(self.root/'offline')
        plain=Path(self.tmp.name)/'plain';plain.mkdir()
        with self.assertRaisesRegex(meshjournal.MeshError,'kein MeshSync-Ordner'):meshjournal.check_folder(plain)
        self.assertEqual(meshjournal.check_folder(plain,create=True),plain.resolve())
        self.assertEqual(meshjournal.check_folder(self.root),self.root.resolve())
        self.assertEqual(json.loads((self.root/meshjournal.FORMAT_FILE).read_text())['format'],meshjournal.FORMAT)
        (plain/meshjournal.FORMAT_FILE).write_text(json.dumps({'format':'mediathekatlas-events-v2'}))
        with self.assertRaisesRegex(meshjournal.MeshError,'anderes Format'):meshjournal.check_folder(plain)
    def test_only_published_segments_are_read_and_cursors_resume(self):
        a=meshjournal.Journal(self.root,'a'*32);b=meshjournal.Journal(self.root,'b'*32)
        a.append('match.result',self.event('01'))
        self.assertTrue(all(p.name.endswith('.partial') for p in a.dir.iterdir()))
        self.assertEqual(b.read({})[0],[])
        a.flush(force=True);a.append('match.result',self.event('02'));a.flush(force=True)
        events,cursors,invalid=b.read({});self.assertEqual([e['data']['work'] for e in events],['01','02']);self.assertEqual(invalid,0)
        self.assertEqual(b.read(cursors)[0],[])
        self.assertGreater(b.hlc,events[-1]['hlc']-1)
    def test_torn_line_is_dropped_and_sequence_continues(self):
        a=meshjournal.Journal(self.root,'a'*32);a.append('match.result',self.event())
        with a._partial().open('ab') as f:f.write(b'{"v":1,"broken')
        again=meshjournal.Journal(self.root,'a'*32);self.assertEqual(again.seq,1)
        self.assertEqual(again.append('match.result',self.event())['seq'],2);again.flush(force=True)
        events,_,invalid=meshjournal.Journal(self.root,'b'*32).read({});self.assertEqual([e['seq'] for e in events],[1,2]);self.assertEqual(invalid,0)
    def test_foreign_or_spoofed_lines_are_skipped(self):
        d=self.root/'nodes'/('c'*32);d.mkdir(parents=True)
        good={'v':1,'id':'x','node':'c'*32,'seq':1,'hlc':1,'type':'match.result','data':self.event()}
        lines=[json.dumps({**good,'node':'d'*32}),'not json',json.dumps({**good,'data':{**self.event(),'meta':{'title':'x','kind':'script'}}}),json.dumps(good)]
        (d/'events-000001.jsonl').write_text('\n'.join(lines)+'\n')
        events,_,invalid=meshjournal.Journal(self.root,'a'*32).read({});self.assertEqual(len(events),1);self.assertEqual(invalid,3)
    def test_partitions_are_disjoint_complete_and_weighted(self):
        members={'a'*32:10.0,'b'*32:30.0,'c'*32:0.0}
        owned=[meshjournal.Journal(self.root,n).assignment(members) for n in members]
        self.assertEqual(sorted(p for parts in owned for p in parts),list(range(256)))
        self.assertGreater(len(owned[1]),len(owned[0]))
        self.assertEqual(meshjournal.Journal(self.root,'a'*32).assignment({}),set(range(256)))
    def test_stale_and_idle_nodes_get_no_partitions(self):
        a=meshjournal.Journal(self.root,'a'*32);now=time.time()
        nodes={'a'*32:{'time':now,'recognizing':True,'rate':1},'b'*32:{'time':now-meshjournal.STALE-1,'recognizing':True},'c'*32:{'time':now,'recognizing':False}}
        self.assertEqual(a.members(nodes,now),{'a'*32:1.0})

class MeshServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name)
        self.shared=base/'shared';self.shared.mkdir();(self.shared/'.meshsync-folder').write_text('token')
        for name in ('a','b'):(base/name).mkdir()
        self.a=Node(base/'a',self.shared);self.b=Node(base/'b',self.shared)
    def tearDown(self):self.tmp.cleanup()
    def join(self):
        for _ in range(2):
            for n in (self.a,self.b):n.service.mesh_beat=0;n.sync()
    def test_two_instances_split_work_without_duplicates(self):
        rows=[row(i) for i in range(60)];self.a.ingest(rows);self.b.ingest(rows);self.join()
        self.assertEqual(self.a.service.mesh_status['partitions']+self.b.service.mesh_status['partitions'],256)
        calls={'a':0,'b':0}
        def counted(name):
            def run(*a):calls[name]+=1;return candidate(*a)
            return run
        busy=True
        while busy:
            busy=False
            for name,n in (('a',self.a),('b',self.b)):
                with patch('core.candidates',side_effect=counted(name)):busy=n.service.metadata_once() or busy
            for n in (self.a,self.b):n.sync()
        # Both meet in the middle; at most the item(s) in flight at that moment are checked twice.
        self.assertLessEqual(calls['a']+calls['b'],62)
        self.assertGreater(min(calls.values()),15)
        self.assertEqual(self.a.states(),self.b.states())
        self.assertTrue(all(state=='matched' for state,_ in self.a.states().values()))
    def test_late_import_adopts_result_without_provider_query(self):
        self.a.ingest([row(1)]);self.join()
        with patch('core.candidates',side_effect=candidate):
            while self.a.service.metadata_once():pass
        self.a.sync();self.b.sync();self.b.ingest([row(1)])
        with patch('core.candidates',side_effect=AssertionError('queried twice')):self.assertTrue(self.b.service.metadata_once())
        self.assertEqual(self.a.states(),self.b.states())
    def test_manual_assignment_wins_and_local_manual_survives(self):
        self.a.ingest([row(1),row(2)]);self.b.ingest([row(1),row(2)]);self.join()
        with self.a.db() as c:wids=[r[0] for r in c.execute('SELECT id FROM works ORDER BY id')]
        with self.b.db() as c:
            meta={'title':'Eigener Titel','kind':'movie','year':1999,'provider':'TMDB','reference_id':'manual-1','state':'user_confirmed'}
            self.b.service.mesh_manual(c,wids[0],catalog.save_metadata(c,wids[0],meta) or wids[0],meta)
        with self.a.db() as c:catalog.save_metadata(c,wids[1],{'title':'Lokal','kind':'movie','year':2001,'state':'user_confirmed'})
        for n in (self.a,self.b):
            with patch('core.candidates',side_effect=candidate):
                while n.service.metadata_once():pass
            n.sync()
        self.a.sync();self.b.sync()
        refs={ref:state for state,ref in self.a.states().values()}
        self.assertEqual(refs.get('manual-1'),'manual')
        with self.a.db() as c:self.assertEqual(c.execute("SELECT title FROM works WHERE id=?",(wids[1],)).fetchone()[0],'Lokal')
    def test_weaker_review_does_not_block_better_equipped_instance(self):
        self.a.config['tmdb']='key';self.a.ingest([row(1)]);self.b.ingest([row(1)])
        with self.b.db() as c:wid=c.execute('SELECT id FROM works').fetchone()[0]
        event={'v':1,'id':'x','node':'b'*32,'seq':1,'hlc':1,'type':'match.result','data':{'work':wid,'outcome':'review','meta':{'title':'x','kind':'movie'},'providers':[]}}
        with self.a.db() as c:self.assertFalse(self.a.service.mesh_apply(c,event))
        with self.a.db() as c:self.assertEqual(c.execute('SELECT state FROM works').fetchone()[0],'pending')
    def test_missing_folder_falls_back_to_standalone(self):
        self.a.config['mesh_dir']=str(self.shared/'unmounted');self.a.ingest([row(1)]);self.a.sync()
        self.assertFalse(self.a.service.mesh_status['enabled']);self.assertIn('fehlt',self.a.service.mesh_status['error'])
        self.assertIsNone(self.a.service.mesh_filter)
        with patch('core.candidates',side_effect=candidate):self.assertTrue(self.a.service.metadata_once())
        self.assertFalse((self.shared/'unmounted').exists())

if __name__=='__main__':unittest.main()
