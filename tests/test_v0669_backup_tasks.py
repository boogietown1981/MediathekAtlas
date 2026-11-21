"""0.6.69: Mac check of 0.6.61 (21.11.2026) – database backup from „Aufgaben“ and while recognising."""
import sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import db_backup,task_control

class TaskStartTests(unittest.TestCase):
    def test_every_startable_task_starts_without_key_error(self):
        import server
        startable=[k for k,v in task_control.TASKS.items() if 'start' in v['can']]
        self.assertIn('backup',startable)
        with patch.object(task_control,'request') as req,patch.object(task_control,'set_paused'),\
             patch.object(server.SERVICE.restart,'set'),patch.object(server.IMDB,'request'),\
             patch.object(server.samsung_tvplus,'start_sync'),patch.object(server,'tasks_overview',return_value={}):
            mods={k:v for k,v in server._PORTAL_MODULES.items()}
            for key in mods:
                patch.object(mods[key][0],'start_sync').start()
            self.addCleanup(patch.stopall)
            for task in startable:
                server.task_action(task,'start')
        req.assert_called_once_with('backup')

class BackupRunningTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        with sqlite3.connect(self.root/'catalog.db') as c:
            c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE t(id INTEGER PRIMARY KEY,v TEXT)')
            c.executemany('INSERT INTO t(v) VALUES(?)',[('x'*400,)]*100000)

    def test_second_start_is_a_state_not_an_error(self):
        events=[];errors=[]
        self.assertTrue(db_backup._LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(db_backup.BackupRunning):db_backup.create(self.root)
            stop=threading.Event()
            with patch.object(task_control,'take_request',return_value=True),patch.object(task_control,'wait_if_paused',return_value=True),\
                 patch.object(task_control,'note') as note,patch.object(stop,'wait',side_effect=lambda t:True):
                db_backup.loop(self.root,stop,lambda n,**f:events.append(n),lambda n,e,**f:errors.append(n),first_delay=0)
        finally:db_backup._LOCK.release()
        self.assertEqual((events,errors),(['db_backup_busy'],[]))
        self.assertIn('läuft bereits',note.call_args_list[-1][0][1])

    def test_backup_finishes_while_another_connection_keeps_writing(self):
        stop=threading.Event();writes=[0]
        def writer():
            c=sqlite3.connect(self.root/'catalog.db',timeout=30)
            while not stop.is_set():
                c.execute('INSERT INTO t(v) VALUES(?)',('y',));c.commit();writes[0]+=1;time.sleep(0.002)
            c.close()
        t=threading.Thread(target=writer);t.start()
        box={}
        def run():
            with patch.object(db_backup.backup_manager,'list_backups',return_value={'backups':[]}):
                box['made']=db_backup.create(self.root,automatic=True)
        b=threading.Thread(target=run,daemon=True);b.start()
        try:
            b.join(20)   # before 0.6.69 the copy started over after every write and never finished
            finished=not b.is_alive()
        finally:stop.set();t.join()
        b.join(60)
        self.assertTrue(finished,'Sicherung beginnt bei laufenden Schreibvorgängen immer wieder von vorn')
        self.assertTrue(box['made']['ok']);self.assertGreater(writes[0],0)
        copy=next((self.root/'Backups').glob('catalog-auto-*.db'))
        with sqlite3.connect(copy) as c:self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM t').fetchone()[0],100000)

    def test_single_snapshot_with_wal_small_steps_without(self):
        calls=[]
        class Src:
            def __init__(self,mode):self.mode=mode
            def execute(self,q):
                return type('R',(),{'fetchone':lambda s:(self.mode,)})()
            def backup(self,out,pages=-1,progress=None,sleep=0.25):calls.append(pages)
        part=self.root/'x.part'
        self.assertEqual(db_backup._copy(Src('wal'),None,part,1),'snapshot')
        self.assertEqual(db_backup._copy(Src('delete'),None,part,1),'steps')
        self.assertEqual(calls,[-1,2048])

if __name__=='__main__':unittest.main()
