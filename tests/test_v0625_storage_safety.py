"""0.6.25 (Björn, 19.11.2026): Nach dem Abschluss des System-Umzugs fiel das Ziellaufwerk Sekunden später weg
(„database disk image is malformed“, Errno 6/5). Sicherer Rückweg nur über den Zeiger, Wächter für einen
verschwundenen Datenordner, keine WAL-Umstellung und kein blindes Löschen an der Datenbankkopie, nie den
früheren Stand am Standardort überschreiben."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import storage_locations as sl  # noqa: E402
from _wiring import SERVER  # noqa: E402
from test_v0620_storage_locations import Env, run, make_db  # noqa: E402


class SafetyBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)
        (self.env.home / 'runtime').mkdir()
        self.say = []

    def moved(self):
        e = self.env
        target = e.ext / 'MediathekAtlas' / 'System'
        state = run(e.ctx, 'system', str(target))
        self.assertEqual(state['phase'], 'ready', state)
        self.assertEqual(sl.data_root(e.home, log=self.say.append), target)
        return target


class RevertTests(SafetyBase):
    def test_drive_lost_after_finalize_offers_revert_without_touching_anything(self):
        e = self.env
        target = self.moved()
        before = (e.home / 'catalog.db').read_bytes()
        target.parent.rename(e.ext / 'weg')          # Laufwerk weg
        with self.assertRaises(sl.Unavailable) as err:
            sl.data_root(e.home, wait=0)
        self.assertIn('Bisherigen Ort verwenden', str(err.exception))
        self.assertIn(str(e.home), (e.home / sl.PROBLEM_FILE).read_text())
        info = sl.revert_info(e.home)
        self.assertEqual(info['path'], str(e.home))
        self.assertTrue(info['is_default'])
        sl.revert_system(e.home)
        cfg = sl.read_pointer(e.home)
        self.assertNotIn('data_dir', cfg)
        self.assertNotIn('system', cfg['previous'])      # „Alte Daten löschen“ kann den aktiven Ort nie treffen
        self.assertEqual(cfg['abandoned']['path'], str(target))
        self.assertEqual(cfg['last']['phase'], 'reverted')
        self.assertFalse((e.home / sl.PROBLEM_FILE).exists())
        self.assertEqual(sl.data_root(e.home), e.home)
        self.assertEqual((e.home / 'catalog.db').read_bytes(), before)
        # Laufwerk wieder da: Kopie liegt unverändert, nichts gelöscht
        (e.ext / 'weg').rename(target.parent)
        self.assertTrue((target / 'catalog.db').is_file())
        self.assertIsNone(sl.revert_info(e.home))

    def test_revert_from_ui_context_and_cleanup_refuses_afterwards(self):
        e = self.env
        target = self.moved()
        ctx = sl.Context(e.home, target, e.ctx.settings, e.save, e.db)
        self.assertEqual(ctx.overview()['revert']['path'], str(e.home))
        result = ctx.revert()
        self.assertTrue(result['restart_needed'])
        with self.assertRaises(ValueError):
            ctx.cleanup('system', sl.CONFIRM)
        self.assertTrue((e.home / 'catalog.db').is_file())
        self.assertTrue((target / 'catalog.db').is_file())
        ctx.dismiss('system')
        self.assertNotIn('abandoned', sl.read_pointer(e.home))

    def test_no_revert_without_catalog_at_old_place(self):
        e = self.env
        target = self.moved()
        ctx = sl.Context(e.home, target, e.ctx.settings, e.save, e.db)
        ctx.cleanup('system', sl.CONFIRM)               # alter Stand gelöscht
        self.assertIsNone(sl.revert_info(e.home))
        with self.assertRaises(ValueError):
            sl.revert_system(e.home)
        self.assertEqual(sl.read_pointer(e.home)['data_dir'], str(target))

    def test_cli_for_launcher(self):
        e = self.env
        self.moved()
        script = str(ROOT / 'storage_locations.py')
        info = subprocess.run([sys.executable, script, '--home', str(e.home), '--revert-info'],
                              capture_output=True, text=True)
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertIn(str(e.home), info.stdout)
        done = subprocess.run([sys.executable, script, '--home', str(e.home), '--revert'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn('data_dir', sl.read_pointer(e.home))
        again = subprocess.run([sys.executable, script, '--home', str(e.home), '--revert-info'], capture_output=True, text=True)
        self.assertEqual(again.returncode, 1)

    def test_copy_back_over_older_default_state_is_refused_adopt_offered(self):
        e = self.env
        target = self.moved()
        ctx = sl.Context(e.home, target, e.ctx.settings, e.save, e.db)
        check = ctx.plan('system', str(e.home))['check']
        self.assertFalse(check['ok'])
        self.assertIn('nicht überschrieben', ' '.join(check['problems']))
        adopt = ctx.plan('system', str(e.home), 'adopt')['check']
        self.assertTrue(adopt['ok'], adopt)


class WatchTests(SafetyBase):
    def test_watchdog_reports_vanished_data_folder(self):
        e = self.env
        target = self.moved()
        stop, lost = threading.Event(), []
        t = threading.Thread(target=sl.watch_root, args=(e.home, target, stop, lost.append, 0.02, 2))
        t.start()
        target.parent.rename(e.ext / 'weg')
        t.join(5)
        stop.set()
        self.assertFalse(t.is_alive())
        self.assertEqual(len(lost), 1)
        self.assertIn('nicht mehr erreichbar', lost[0])
        self.assertIn('Bisherigen Ort verwenden', (e.home / sl.PROBLEM_FILE).read_text())

    def test_watchdog_idle_for_default_place_and_short_glitch(self):
        e = self.env
        stop, lost = threading.Event(), []
        sl.watch_root(e.home, e.home, stop, lost.append, 0.01)   # Standardort: kehrt sofort zurück
        target = self.moved()
        marker = target / sl.DATA_MARKER
        t = threading.Thread(target=sl.watch_root, args=(e.home, target, stop, lost.append, 0.05, 3))
        t.start()
        data = marker.read_bytes()
        marker.unlink()
        stop.wait(0.06)
        marker.write_bytes(data)                       # kurzer Aussetzer
        stop.wait(0.3)
        stop.set()
        t.join(5)
        self.assertEqual(lost, [])


class SqliteCopyTests(unittest.TestCase):
    def test_wal_source_copy_leaves_no_side_files_and_keeps_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            src = base / 'a.db'
            c = make_db(src, 300, wal=True)            # offen, Daten im WAL
            sl.copy_sqlite(src, base / 'out' / 'a.db')
            c.close()
            out = base / 'out'
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['a.db'])
            d = sqlite3.connect(out / 'a.db')
            self.assertEqual(d.execute('SELECT COUNT(*) FROM t').fetchone()[0], 300)
            self.assertEqual(d.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            d.close()

    def test_no_journal_switch_in_code(self):
        code = (ROOT / 'storage_locations.py').read_text(encoding='utf-8')
        self.assertNotIn("target.execute('PRAGMA journal_mode=WAL')", code)


class WiringTests(unittest.TestCase):
    def test_server_launcher_ui(self):
        self.assertIn('storage_locations.watch_root', SERVER)
        self.assertIn("action=='revert'", SERVER)
        self.assertIn('LOST_EXIT', SERVER)
        launcher = (ROOT / 'launcher.sh').read_text(encoding='utf-8')
        self.assertIn('Bisherigen Ort verwenden', launcher)
        self.assertIn('--revert-info', launcher)
        js = (ROOT / 'web' / 'storage_locations.js').read_text(encoding='utf-8')
        self.assertIn("action:'revert'", js)
        self.assertIn('Bisherigen Ort wieder verwenden', js)


if __name__ == '__main__':
    unittest.main()
