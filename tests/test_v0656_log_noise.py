"""0.6.56: Mac check of the Verbund (20.11.2026) – two error entries that were no errors."""
import gzip,sqlite3,tempfile,threading,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import catalog_service,imdb_archive as imdb

class ImdbQuitTests(unittest.TestCase):
    def test_quitting_during_the_update_is_no_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=imdb.Archive(Path(tmp),threading.Event());errors=[];events=[]
            with patch.object(archive,'fetch',side_effect=InterruptedError('IMDb-Import beendet')),\
                 patch.object(imdb.diagnostics,'error',side_effect=lambda name,e,**f:errors.append(name)),\
                 patch.object(imdb.diagnostics,'event',side_effect=lambda name,**f:events.append(name)):
                archive.update()
            self.assertEqual(errors,[])
            self.assertIn('imdb_archive_interrupted',events)
            self.assertEqual((archive.failures,archive.retry_at),(0,0))
            self.assertNotEqual(archive.state.get('phase'),'error')

class SchedulerTests(unittest.TestCase):
    def test_locked_database_at_start_is_retried_quietly(self):
        stop=threading.Event()
        @contextmanager
        def db():
            raise sqlite3.OperationalError('database is locked');yield
        svc=catalog_service.Service(db,lambda:{'download_dir':'/tmp'},stop,Path('/tmp'))
        class Wake:
            def wait(self,t):stop.set()
            def clear(self):pass
        svc.subscription_wake=Wake();errors=[];events=[]
        with patch.object(catalog_service.task_control,'wait_if_paused',return_value=True),\
             patch.object(catalog_service.diagnostics,'error',side_effect=lambda name,e,**f:errors.append(name)),\
             patch.object(catalog_service.diagnostics,'event',side_effect=lambda name,**f:events.append(name)):
            svc.subscription_loop()
        self.assertEqual(errors,[]);self.assertEqual(events,['subscription_scheduler_busy'])

if __name__=='__main__':unittest.main()
