"""0.6.72: Mac check of 0.6.69 (21.11.2026) – double start of the backup, version in the start log, Samsung next load."""
import os,shutil,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import db_backup,samsung_tvplus as stv,task_control
from version import VERSION
ROOT=Path(__file__).resolve().parents[1]

class DoubleStartTests(unittest.TestCase):
    def test_click_while_running_requests_nothing(self):
        import server
        events=[]
        with patch.dict(db_backup._STATE,{'phase':'running'}),patch.object(task_control,'request') as req,\
             patch.object(task_control,'note'),patch.object(task_control,'set_paused'),patch.object(server,'tasks_overview',return_value={}),\
             patch.object(server.diagnostics,'event',side_effect=lambda n,**f:events.append(n)):
            server.task_action('backup','start')
        req.assert_not_called();self.assertIn('db_backup_busy',events)

    def test_request_made_during_a_backup_does_not_start_a_second_one(self):
        made={'ok':True,'backup':{'name':'catalog-auto-1.db'}};created=[];events=[]
        def create(root,automatic=False):
            created.append(1);task_control.request('backup')   # second click while the first copy runs
            db_backup._STATE['last']={'name':'catalog-auto-1.db'};return made
        stop=threading.Event();rounds=[0]
        def wait(t):
            rounds[0]+=1;return rounds[0]>=3
        task_control.request('backup')
        self.addCleanup(task_control.take_request,'backup')
        with patch.object(db_backup,'create',side_effect=create),patch.object(db_backup,'rotate',return_value=[]),\
             patch.object(task_control,'wait_if_paused',return_value=True),patch.object(task_control,'note'),\
             patch.object(stop,'wait',side_effect=wait):
            db_backup.loop(Path('/nowhere'),stop,lambda n,**f:events.append(n),lambda n,e,**f:self.fail(n),first_delay=3600)
        self.assertEqual(len(created),1)
        self.assertEqual(events,['db_backup_created','db_backup_busy'])

@unittest.skipIf(os.name=='nt','bash launcher')
class LauncherVersionTests(unittest.TestCase):
    def test_start_log_names_the_installed_version(self):
        from tests.test_v0647_mac_launcher import build_app
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            launcher=build_app(base,server='print("ok")\n')
            shutil.copy2(ROOT/'version.py',launcher.parents[1]/'Resources'/'app'/'version.py')
            env={**os.environ,'MEDIATHEKATLAS_PYTHON':sys.executable,'MEDIATHEKATLAS_HOME':str(base/'state'),
                 'MEDIATHEKATLAS_FOREGROUND':'1','MEDIATHEKATLAS_NO_DIALOG':'1','MA_TEST_OUT':str(base/'o')}
            env.pop('MEDIATHEKATLAS_SUPERVISED',None)
            subprocess.run(['/bin/bash',str(launcher)],env=env,capture_output=True,timeout=30)
            log=(base/'state'/'startup.log').read_text()
        self.assertIn('MediathekAtlas %s Startprüfung'%VERSION,log)
        self.assertNotIn('0.6.62 Startprüfung',(ROOT/'launcher.sh').read_text())

class SamsungNextLoadTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def test_switching_auto_back_on_sets_a_real_time(self):
        last=time.time()-3600
        stv._update(self.root,last_success=last,last_attempt=last,next_attempt=0.0,auto=False)
        st=stv.set_auto(self.root,True)
        self.assertAlmostEqual(st['next_attempt'],last+stv.REFRESH,delta=2)
        self.assertFalse(stv.due(st))
        stv._update(self.root,next_attempt=0.0,auto=False,last_success=time.time()-2*stv.REFRESH)
        st=stv.set_auto(self.root,True)
        self.assertGreater(st['next_attempt'],time.time()-5)

    def test_same_region_keeps_the_planned_time(self):
        planned=time.time()+5000
        stv._update(self.root,region='de',next_attempt=planned,last_success=time.time(),last_attempt=time.time(),auto=True)
        self.assertEqual(stv.set_region(self.root,'de')['next_attempt'],planned)
        self.assertEqual(stv.set_region(self.root,'at')['next_attempt'],0.0)

if __name__=='__main__':unittest.main()
