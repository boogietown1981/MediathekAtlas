"""0.6.20 Speicherorte (Björn, 16.11.2026): Downloads, Zwischenspeicher (YouTube-Abos) und System/Datenbank
einzeln festlegen; beim Ändern werden vorhandene Daten übernommen. Kopieren, prüfen, erst dann umstellen;
alter Ort bleibt bis zum ausdrücklichen Löschen; fehlender Datenordner beim Start wird gemeldet."""
import contextlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import storage_locations as sl  # noqa: E402
from _wiring import SERVER  # noqa: E402


def make_db(path, rows=50, wal=True):
    c = sqlite3.connect(path)
    if wal:
        c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS t(id INTEGER PRIMARY KEY, v TEXT)')
    c.executemany('INSERT INTO t(v) VALUES(?)', [('x' * 200,)] * rows)
    c.commit()
    return c


class Env:
    """Startordner, Datenordner, Downloads und catalog.db wie in der App."""

    def __init__(self, tmp):
        self.base = Path(tmp)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.downloads = self.base / 'Movies' / 'MediathekAtlas'
        (self.downloads / 'Filme' / 'Film (2020)').mkdir(parents=True)
        (self.downloads / 'Filme' / 'Film (2020)' / 'Film (2020).mkv').write_bytes(os.urandom(300_000))
        (self.downloads / 'Filme' / 'Film (2020)' / 'Film (2020).nfo').write_text('<movie/>')
        (self.downloads / 'Filme' / 'Film (2020)' / 'halb.mkv.partial').write_bytes(b'xx')
        abo = self.downloads / sl.ABO_FOLDER / 'Kanal'
        abo.mkdir(parents=True)
        (abo / 'Video [abc].mp4').write_bytes(os.urandom(50_000))
        self.ext = self.base / 'Volumes' / 'Extern'
        self.ext.mkdir(parents=True)
        self.store = {'download_dir': str(self.downloads), 'cache_dir': '', 'library_dirs': []}
        self.db_path = self.home / 'catalog.db'
        c = sqlite3.connect(self.db_path)
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT);'
                        'CREATE TABLE downloaded_items(identity TEXT PRIMARY KEY,path TEXT,finished REAL);'
                        'CREATE TABLE mesh_downloads(key TEXT PRIMARY KEY,local TEXT);')
        film = str(self.downloads / 'Filme' / 'Film (2020)' / 'Film (2020).mkv')
        video = str(abo / 'Video [abc].mp4')
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j1', json.dumps({'root': str(self.downloads), 'target': film,
                                                                       'source': {'_youtube_home': str(self.home)}}), 'done'))
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j2', json.dumps({'root': str(self.downloads), 'target': video,
                                                                       'youtube_abo': 1,
                                                                       'source': {'_target': video}}), 'queued'))
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j3', json.dumps({'root': '/anderswo', 'target': '/anderswo/x.mkv'}), 'done'))
        c.execute('INSERT INTO downloaded_items VALUES(?,?,?)', ('w1', film, 1.0))
        c.execute('INSERT INTO mesh_downloads VALUES(?,?)', ('m1', film))
        c.commit()
        c.close()
        self.ctx = sl.Context(self.home, self.home, lambda: dict(self.store), self.save, self.db)

    def save(self, s):
        self.store = dict(s)

    @contextlib.contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=5)
        try:
            with c:
                yield c
        finally:
            c.close()

    def job(self, ident):
        with self.db() as c:
            return json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (ident,)).fetchone()[0])


def run(ctx, kind, target, mode='copy'):
    sl.MOVER.start(ctx, kind, target, mode)
    sl.MOVER.thread.join(30)
    return sl.MOVER.status()


class InspectTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)

    def test_rejects_unsafe_targets(self):
        e = self.env
        bad = {'relativ/ordner': 'absoluten', '/': 'Unterordner', str(e.downloads / 'neu'): 'ineinander',
               '/Volumes/NichtVerbunden/MediathekAtlas': 'Laufwerk verbunden',
               '/mnt/nicht-eingehaengt/MediathekAtlas': 'Laufwerk verbunden', str(e.downloads): 'aktuelle'}
        for target, word in bad.items():
            r = sl.inspect('downloads', e.downloads, target, home=e.home)
            self.assertFalse(r['ok'], target)
            self.assertIn(word, ' '.join(r['problems']), target)
        # fehlende Unterordner auf einem vorhandenen Laufwerk werden angelegt
        self.assertTrue(sl.inspect('downloads', e.downloads, e.ext / 'neu' / 'tief', home=e.home)['ok'])
        self.assertFalse((e.ext / 'neu').exists())   # Prüfen verändert nichts

    def test_counts_size_skips_partial_and_checks_space(self):
        e = self.env
        r = sl.inspect('downloads', e.downloads, e.ext / 'Downloads', home=e.home)
        self.assertTrue(r['ok'], r)
        self.assertEqual(r['files'], 3)   # mkv, nfo, Abo-Video; .partial nicht
        self.assertEqual(r['bytes_total'], 300_000 + 8 + 50_000)
        real = sl.disk
        sl.disk = lambda p: {'free': 1000, 'total': 10**9}
        try:
            r = sl.inspect('downloads', e.downloads, e.ext / 'Downloads', home=e.home)
        finally:
            sl.disk = real
        self.assertFalse(r['ok'])
        self.assertIn('Zu wenig freier Platz', r['problems'][0])

    def test_conflicting_files_and_non_empty_system_target(self):
        e = self.env
        clash = e.ext / 'D' / 'Filme' / 'Film (2020)'
        clash.mkdir(parents=True)
        (clash / 'Film (2020).nfo').write_text('anders, länger')
        r = sl.inspect('downloads', e.downloads, e.ext / 'D', home=e.home)
        self.assertFalse(r['ok'])
        self.assertIn('Nichts wird überschrieben', ' '.join(r['problems']))
        (e.ext / 'S').mkdir()
        (e.ext / 'S' / 'fremd.txt').write_text('x')
        r = sl.inspect('system', e.home, e.ext / 'S', home=e.home)
        self.assertIn('nicht leer', ' '.join(r['problems']))

    def test_overlap_with_other_location(self):
        e = self.env
        r = e.ctx.plan('system', str(e.downloads / 'System'))['check']
        self.assertFalse(r['ok'])
        self.assertIn('überschneidet sich', ' '.join(r['problems']))


class CopyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_open_wal_database_copied_consistently_and_resume_skips(self):
        src, dst = self.base / 'src', self.base / 'dst'
        src.mkdir()
        live = make_db(src / 'catalog.db', 300)
        live.execute("INSERT INTO t(v) VALUES('nur im WAL')")
        live.commit()   # liegt noch im -wal, nicht in der Hauptdatei
        self.assertTrue((src / 'catalog.db-wal').exists())
        (src / 'notiz.json').write_text('{}')
        manifest = sl.sync_tree(src, dst)
        self.assertFalse((dst / 'catalog.db-wal').exists())
        c = sqlite3.connect(dst / 'catalog.db')
        self.assertEqual(c.execute("SELECT COUNT(*) FROM t WHERE v='nur im WAL'").fetchone()[0], 1)
        c.close()
        self.assertEqual(sl.verify_tree(src, dst, manifest=manifest), [])
        copied = []
        real = sl.copy_file
        sl.copy_file = lambda *a, **k: copied.append(a[0]) or real(*a, **k)
        try:
            sl.sync_tree(src, dst, manifest=manifest)
        finally:
            sl.copy_file = real
        self.assertEqual(copied, [])   # Wiederaufnahme: nichts doppelt
        live.close()

    def test_verify_detects_changed_content(self):
        src, dst = self.base / 'src', self.base / 'dst'
        src.mkdir()
        (src / 'a.txt').write_text('abc')
        sl.sync_tree(src, dst)
        (dst / 'a.txt').write_text('abd')
        self.assertEqual(sl.verify_tree(src, dst), ['a.txt Inhalt weicht ab'])
        (dst / 'a.txt').unlink()
        self.assertEqual(sl.verify_tree(src, dst), ['a.txt fehlt'])

    def test_cancel_leaves_no_half_file(self):
        src, dst = self.base / 'src', self.base / 'dst'
        src.mkdir()
        (src / 'gross.bin').write_bytes(os.urandom(sl.CHUNK * 2 + 10))
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 2
        with self.assertRaises(InterruptedError):
            sl.sync_tree(src, dst, cancelled=cancelled)
        self.assertEqual([p.name for p in dst.iterdir()], [])


class LargeDatabaseTests(unittest.TestCase):
    """0.6.22: Björns Umzug stand bei catalog.db (5,5 GB) über 10 Minuten ohne Anzeige (quick_check am Ziel)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.src = self.base / 'catalog.db'
        make_db(self.src, 4000).close()

    def test_steps_report_progress_and_survive_concurrent_writes(self):
        import threading
        sl.BACKUP_PAGES, old = 20, sl.BACKUP_PAGES
        self.addCleanup(setattr, sl, 'BACKUP_PAGES', old)
        stop = threading.Event()
        writes = [0]

        def writer():
            w = sqlite3.connect(self.src, timeout=30)
            while not stop.is_set():
                w.execute("INSERT INTO t(v) VALUES('neu')")
                w.commit()
                writes[0] += 1
                time.sleep(0.001)
            w.close()
        th = threading.Thread(target=writer)
        th.start()
        stages = []
        try:
            sl.copy_sqlite(self.src, self.base / 'kopie.db', on_stage=lambda *a: stages.append(a))
        finally:
            stop.set()
            th.join()
        copies = [a for a in stages if a[0] == 'copy']
        self.assertGreater(len(copies), 5)
        self.assertEqual([a[1] for a in copies], sorted(a[1] for a in copies))   # kein Neubeginn
        self.assertEqual(copies[-1][1], copies[-1][2])
        self.assertIn('check', [a[0] for a in stages])
        c = sqlite3.connect(self.base / 'kopie.db')
        self.assertGreaterEqual(c.execute('SELECT count(*) FROM t').fetchone()[0], 4000)
        self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        c.close()

    def test_cancel_inside_database_copy(self):
        sl.BACKUP_PAGES, old = 10, sl.BACKUP_PAGES
        self.addCleanup(setattr, sl, 'BACKUP_PAGES', old)
        calls = []
        with self.assertRaises(InterruptedError):
            sl.copy_sqlite(self.src, self.base / 'kopie.db', cancelled=lambda: calls.append(1) or len(calls) > 3)
        self.assertFalse((self.base / 'kopie.db').exists())
        self.assertFalse((self.base / 'kopie.db.partial').exists())

    def test_large_database_uses_structure_check(self):
        sl.QUICK_CHECK_LIMIT, old = 0, sl.QUICK_CHECK_LIMIT
        self.addCleanup(setattr, sl, 'QUICK_CHECK_LIMIT', old)
        seen = []
        sl.copy_sqlite(self.src, self.base / 'kopie.db', on_stage=lambda *a: seen.append(a[0]))
        self.assertEqual(seen[-1], 'sync')
        c = sqlite3.connect(self.base / 'kopie.db')
        self.assertEqual(c.execute('SELECT count(*) FROM t').fetchone()[0], 4000)
        c.close()

    def test_mover_state_shows_file_progress(self):
        src, dst = self.base / 'quelle', self.base / 'ziel'
        src.mkdir()
        make_db(src / 'catalog.db', 2000).close()
        states = []
        sl.sync_tree(src, dst, progress=states.append)
        db_states = [x for x in states if x.get('current') == 'catalog.db' and x.get('file_total')]
        self.assertTrue(db_states)
        self.assertTrue({x['step'] for x in db_states} >= {'copy', 'check'})


class DownloadMoveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)

    def test_move_copies_verifies_switches_and_rewrites_paths(self):
        e = self.env
        target = e.ext / 'MediathekAtlas' / 'Downloads'
        state = run(e.ctx, 'downloads', str(target))
        self.assertEqual(state['phase'], 'done', state)
        self.assertFalse(sl.downloads_held())
        self.assertEqual(e.store['download_dir'], str(target))
        self.assertTrue((target / sl.PLACE_MARKER).is_file())
        self.assertTrue((target / 'Filme' / 'Film (2020)' / 'Film (2020).mkv').is_file())
        self.assertFalse((target / 'Filme' / 'Film (2020)' / 'halb.mkv.partial').exists())
        self.assertFalse((target / sl.STAGING).exists())
        self.assertEqual(e.job('j1')['target'], str(target / 'Filme' / 'Film (2020)' / 'Film (2020).mkv'))
        self.assertEqual(e.job('j1')['root'], str(target))
        self.assertEqual(e.job('j1')['source']['_youtube_home'], str(e.home))   # Systempfad unverändert
        self.assertEqual(e.job('j2')['source']['_target'], str(target / sl.ABO_FOLDER / 'Kanal' / 'Video [abc].mp4'))
        self.assertEqual(e.job('j3')['root'], '/anderswo')
        with e.db() as c:
            self.assertTrue(c.execute('SELECT path FROM downloaded_items').fetchone()[0].startswith(str(target)))
            self.assertTrue(c.execute('SELECT local FROM mesh_downloads').fetchone()[0].startswith(str(target)))
        # alter Ort unverändert, bis ausdrücklich gelöscht
        self.assertTrue((e.downloads / 'Filme' / 'Film (2020)' / 'Film (2020).mkv').is_file())
        prev = sl.read_pointer(e.home)['previous']['downloads']
        self.assertEqual(prev['source'], str(e.downloads))
        with self.assertRaises(ValueError):
            e.ctx.cleanup('downloads', 'ja')
        (e.downloads / 'neu-nach-umzug.txt').write_text('nicht am Ziel')
        result = e.ctx.cleanup('downloads', sl.CONFIRM)
        self.assertEqual(result['removed'], 3)
        self.assertEqual(result['kept'], 1)
        self.assertTrue((e.downloads / 'neu-nach-umzug.txt').is_file())
        self.assertFalse((e.downloads / 'Filme' / 'Film (2020)' / 'Film (2020).mkv').exists())
        self.assertTrue((target / 'Filme' / 'Film (2020)' / 'Film (2020).mkv').is_file())

    def test_waits_for_running_download_and_can_be_cancelled(self):
        e = self.env
        with e.db() as c:
            c.execute("UPDATE jobs SET state='downloading' WHERE id='j2'")
        sl.MOVER.start(e.ctx, 'downloads', str(e.ext / 'D'))
        time.sleep(0.3)
        self.assertEqual(sl.MOVER.status()['phase'], 'waiting')
        self.assertTrue(sl.downloads_held())
        sl.MOVER.stop()
        sl.MOVER.thread.join(10)
        self.assertEqual(sl.MOVER.status()['phase'], 'cancelled')
        self.assertFalse(sl.downloads_held())
        self.assertEqual(e.store['download_dir'], str(e.downloads))

    def test_switch_only_keeps_files_and_paths(self):
        e = self.env
        state = run(e.ctx, 'downloads', str(e.ext / 'Neu'), mode='switch')
        self.assertEqual(state['phase'], 'done', state)
        self.assertEqual(e.store['download_dir'], str(e.ext / 'Neu'))
        self.assertEqual(e.job('j1')['root'], str(e.downloads))
        self.assertNotIn('downloads', sl.read_pointer(e.home).get('previous', {}))

    def test_unplugged_location_is_reported_and_blocks_jobs(self):
        e = self.env
        target = e.ext / 'D'
        run(e.ctx, 'downloads', str(target))
        self.assertEqual(sl.problems(e.store), [])
        (target / sl.PLACE_MARKER).rename(target / 'weg')
        self.assertIn('nicht erreichbar', sl.problems(e.store)[0]['text'])
        self.assertTrue(sl.root_problem(str(target), e.store))
        self.assertEqual(sl.root_problem('/anderswo', e.store), '')


class CacheMoveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)

    def test_abo_videos_move_to_own_cache_and_back(self):
        e = self.env
        self.assertEqual(sl.abo_base(e.store), str(e.downloads))
        base = e.ext / 'Zwischenspeicher'
        state = run(e.ctx, 'cache', str(base))
        self.assertEqual(state['phase'], 'done', state)
        self.assertEqual(e.store['cache_dir'], str(base))
        self.assertEqual(sl.abo_base(e.store), str(base))
        video = base / sl.ABO_FOLDER / 'Kanal' / 'Video [abc].mp4'
        self.assertTrue(video.is_file())
        job = e.job('j2')
        self.assertEqual(job['target'], str(video))
        self.assertEqual(job['root'], str(base))   # planned_target verlangt Ziel innerhalb von root
        self.assertEqual(e.job('j1')['root'], str(e.downloads))
        import downloads
        self.assertEqual(downloads.planned_target(job['root'], {}, {'_target': job['source']['_target'], '_container': 'mp4'}),
                         video.resolve())
        # Downloads-Umzug lässt den eigenen Zwischenspeicher außen vor
        plan = e.ctx.plan('downloads', str(e.ext / 'D'))
        self.assertTrue(plan['check']['ok'], plan['check'])
        # zurück in den Downloadordner
        state = run(e.ctx, 'cache', str(e.downloads))
        self.assertEqual(state['phase'], 'done', state)
        self.assertEqual(e.store['cache_dir'], '')
        self.assertEqual(e.job('j2')['root'], str(e.downloads))


class SystemMoveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)
        e = self.env
        (e.home / 'runtime' / 'abc').mkdir(parents=True)
        (e.home / 'runtime' / 'abc' / 'server.py').write_text('# code')
        (e.home / 'instance.lock').write_text('')
        (e.home / 'imdb').mkdir()
        self.imdb = make_db(e.home / 'imdb' / 'imdb_archive.db', 100, wal=False)
        self.imdb.close()
        (e.home / 'task-control.json').write_text('{}')
        self.say = []

    def test_copy_then_finalize_at_start_with_late_changes(self):
        e = self.env
        target = e.ext / 'MediathekAtlas' / 'System'
        state = run(e.ctx, 'system', str(target))
        self.assertEqual(state['phase'], 'ready', state)
        self.assertTrue(state['restart_needed'])
        self.assertFalse((target / 'runtime').exists())
        self.assertFalse((target / 'instance.lock').exists())
        self.assertEqual(sl.read_pointer(e.home)['pending']['state'], 'copied')
        # Änderungen zwischen Kopie und Neustart werden nachgezogen
        (e.home / 'task-control.json').write_text('{"geändert": true}')
        with e.db() as c:
            c.execute("INSERT INTO jobs VALUES('j9','{}','queued')")
        root = sl.data_root(e.home, log=self.say.append)
        self.assertEqual(root, target)
        self.assertEqual((target / 'task-control.json').read_text(), '{"geändert": true}')
        c = sqlite3.connect(target / 'catalog.db')
        self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs WHERE id='j9'").fetchone()[0], 1)
        home_ref = json.loads(c.execute("SELECT payload FROM jobs WHERE id='j1'").fetchone()[0])['source']['_youtube_home']
        c.close()
        self.assertEqual(home_ref, str(target))
        self.assertTrue((target / sl.DATA_MARKER).is_file())
        self.assertFalse((target / sl.STAGING).exists())
        cfg = sl.read_pointer(e.home)
        self.assertEqual(cfg['data_dir'], str(target))
        self.assertNotIn('pending', cfg)
        self.assertEqual(cfg['previous']['system']['source'], str(e.home))
        self.assertTrue((e.home / 'catalog.db').is_file())   # alter Ort bleibt
        # zweiter Start: einfach der neue Ort
        self.assertEqual(sl.data_root(e.home), target)
        # Laufwerk abgezogen: Meldung statt leerem Neuanfang
        target.rename(e.ext / 'weg')
        with self.assertRaises(sl.Unavailable) as err:
            sl.data_root(e.home, wait=0)
        self.assertIn(str(target), str(err.exception))
        self.assertIn('kein neuer, leerer Katalog', (e.home / sl.PROBLEM_FILE).read_text())
        self.assertFalse(target.exists())
        (e.ext / 'weg').rename(target)
        self.assertEqual(sl.data_root(e.home), target)
        self.assertFalse((e.home / sl.PROBLEM_FILE).exists())

    def test_cleanup_of_old_system_data_keeps_program_files(self):
        e = self.env
        target = e.ext / 'S'
        run(e.ctx, 'system', str(target))
        sl.data_root(e.home, log=self.say.append)
        ctx = sl.Context(e.home, target, e.ctx.settings, e.save, e.db)
        result = ctx.cleanup('system', sl.CONFIRM)
        self.assertGreaterEqual(result['removed'], 3)
        self.assertFalse((e.home / 'catalog.db').exists())
        self.assertFalse((e.home / 'imdb' / 'imdb_archive.db').exists())
        self.assertTrue((e.home / 'runtime' / 'abc' / 'server.py').is_file())
        self.assertTrue((e.home / sl.POINTER).is_file())
        self.assertTrue((target / 'catalog.db').is_file())

    def test_unreachable_target_at_start_keeps_old_place(self):
        e = self.env
        target = e.ext / 'S'
        run(e.ctx, 'system', str(target))
        (target / sl.STAGING).unlink()
        root = sl.data_root(e.home, log=self.say.append)
        self.assertEqual(root, e.home)
        cfg = sl.read_pointer(e.home)
        self.assertEqual(cfg['pending']['state'], 'failed')
        self.assertNotIn('data_dir', cfg)
        self.assertTrue(any('bisherigen Ort' in s for s in self.say))

    def test_move_back_to_default(self):
        e = self.env
        target = e.ext / 'S'
        run(e.ctx, 'system', str(target))
        sl.data_root(e.home, log=self.say.append)
        ctx = sl.Context(e.home, target, e.ctx.settings, e.save, e.db)
        plan = ctx.plan('system', str(e.home))
        self.assertTrue(plan['check']['ok'], plan['check'])
        state = run(ctx, 'system', str(e.home))
        self.assertEqual(state['phase'], 'ready', state)
        self.assertEqual(sl.data_root(e.home, log=self.say.append), e.home)
        self.assertNotIn('data_dir', sl.read_pointer(e.home))

    def test_system_switch_without_copy_is_refused(self):
        e = self.env
        check = e.ctx.plan('system', str(e.ext / 'leer'), 'switch')['check']
        self.assertFalse(check['ok'])


class WiringTests(unittest.TestCase):
    def test_server_and_ui_wiring(self):
        self.assertIn('storage_locations.data_root(HOME', SERVER)
        self.assertIn('Instance(HOME)', SERVER)
        self.assertIn('storage_locations.downloads_held()', SERVER)
        self.assertIn('storage_locations.root_problem(', SERVER)
        self.assertIn("'/storage_locations.js'", SERVER)
        self.assertIn("@ROUTES.post('/api/storage-locations')", SERVER)
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="storage-locations-panel"', html)
        self.assertIn('<script src="/storage_locations.js"></script>', html)
        self.assertIn('storage_locations.py', (ROOT / 'build_macos.py').read_text())
        launcher = (ROOT / 'launcher.sh').read_text()
        self.assertIn('storage-problem.txt', launcher)
        self.assertIn('"$STATUS" -eq 3', launcher)

    def test_abo_base_and_library_roots(self):
        import local_library
        with tempfile.TemporaryDirectory() as tmp:
            s = {'download_dir': tmp + '/d', 'cache_dir': tmp + '/c', 'library_dirs': []}
            self.assertEqual(sl.abo_base(s), tmp + '/c')
            self.assertIn(Path(tmp + '/c').resolve(), local_library.roots(s))
            self.assertEqual(sl.abo_base({'download_dir': '/x', 'cache_dir': ''}), '/x')


if __name__ == '__main__':
    unittest.main()
