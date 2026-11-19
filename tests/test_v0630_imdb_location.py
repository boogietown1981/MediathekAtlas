"""0.6.30 (Björn, 19.11.2026): „warum kann ich die IMDb-DB noch nicht auf ein Dock ziehen?“ – eigener
Speicherort für das IMDb-Archiv: Umzug wie die anderen Orte (kopieren, prüfen, umstellen, alter Ort bleibt),
vorhandenes Archiv übernehmen ohne Kopie, fehlendes Laufwerk ohne leeres Neuanlegen."""
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import storage_locations as sl  # noqa: E402
import imdb_archive  # noqa: E402
from _wiring import SERVER  # noqa: E402
from test_v0620_storage_locations import Env, run  # noqa: E402

SCHEMA = ('CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,primaryTitle TEXT,originalTitle TEXT,'
          'isAdult INTEGER,startYear INTEGER,endYear INTEGER,runtimeMinutes INTEGER,genres TEXT);'
          'CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);'
          'CREATE TABLE names(name TEXT,tconst TEXT,title TEXT,localized INTEGER);'
          'CREATE TABLE snapshot(updated REAL,details TEXT); PRAGMA user_version=1;')


def make_archive(folder, updated=1000.0, title='film'):
    folder.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(folder / sl.IMDB_DB)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO title_basics VALUES('tt1','movie',?,?,0,2001,NULL,90,'Drama')", (title, title))
    c.execute("INSERT INTO names VALUES(?,?,?,0)", (title, 'tt1', title))
    c.execute('INSERT INTO snapshot VALUES(?,?)', (updated, '{}'))
    c.commit()
    c.close()


class FakeArchive:
    def __init__(self):
        self.moves, self.running = [], False

    def busy(self):
        return self.running

    def relocate(self, folder, available):
        self.moves.append((str(folder), available))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Env(tmp.name)
        self.archive = FakeArchive()
        e = self.env
        self.ctx = sl.Context(e.home, e.home, e.ctx.settings, e.save, e.db, imdb=self.archive)
        make_archive(e.home / 'imdb')
        (e.home / 'imdb' / 'building.db').write_bytes(b'halb')
        (e.home / 'imdb' / 'title.basics.tsv.gz.part').write_bytes(b'x')


class MoveTests(Base):
    def test_move_to_drive_copies_verifies_switches_and_keeps_old(self):
        e = self.env
        target = e.ext / 'MediathekAtlas' / 'IMDb'
        state = run(self.ctx, 'imdb', str(target))
        self.assertEqual(state['phase'], 'done', state)
        self.assertFalse(sl.imdb_held())
        self.assertTrue((target / sl.IMDB_DB).is_file())
        self.assertFalse((target / 'building.db').exists())          # Zwischenstand zieht nicht mit
        self.assertTrue((target / sl.PLACE_MARKER).is_file())
        self.assertEqual(sl.read_pointer(e.home)['imdb_dir'], str(target))
        self.assertEqual(self.archive.moves, [(str(target), True)])
        self.assertTrue((e.home / 'imdb' / sl.IMDB_DB).is_file())     # alter Ort bleibt
        self.assertEqual(sl.imdb_location(e.home, e.home), (target, True))
        rows = {r['kind']: r for r in self.ctx.overview()['locations']}
        self.assertEqual(rows['imdb']['path'], str(target))
        self.assertFalse(rows['imdb']['is_default'])
        # alte Kopie löschen: nur was am neuen Ort gleich vorliegt
        result = self.ctx.cleanup('imdb', sl.CONFIRM)
        self.assertGreaterEqual(result['removed'], 1)
        self.assertFalse((e.home / 'imdb' / sl.IMDB_DB).exists())
        self.assertTrue((e.home / 'catalog.db').is_file())
        # zurück in den Datenordner
        state = run(self.ctx, 'imdb', str(e.home / 'imdb'))
        self.assertEqual(state['phase'], 'done', state)
        self.assertNotIn('imdb_dir', sl.read_pointer(e.home))
        self.assertEqual(sl.imdb_location(e.home, e.home), (e.home / 'imdb', True))

    def test_existing_archive_is_adopted_never_overwritten(self):
        e = self.env
        other = e.ext / 'Docking' / 'System' / 'imdb'
        make_archive(other, updated=2000.0, title='anders')
        before = (other / sl.IMDB_DB).read_bytes()
        copy = self.ctx.plan('imdb', str(other))['check']
        self.assertFalse(copy['ok'])
        self.assertIn('nicht überschrieben', ' '.join(copy['problems']))
        adopt = self.ctx.plan('imdb', str(other), 'adopt')['check']
        self.assertTrue(adopt['ok'], adopt)
        state = run(self.ctx, 'imdb', str(other), 'adopt')
        self.assertEqual(state['phase'], 'done', state)
        self.assertEqual((other / sl.IMDB_DB).read_bytes(), before)
        cfg = sl.read_pointer(e.home)
        self.assertEqual(cfg['imdb_dir'], str(other))
        self.assertTrue(cfg['previous']['imdb']['replaceable'])
        # bisheriges Archiv ist ersetzbar: Löschen gibt den Platz frei, obwohl die Archive verschieden sind
        result = self.ctx.cleanup('imdb', sl.CONFIRM)
        self.assertGreaterEqual(result['removed'], 2)
        self.assertFalse((e.home / 'imdb' / sl.IMDB_DB).exists())
        self.assertFalse((e.home / 'imdb' / 'building.db').exists())
        self.assertEqual((other / sl.IMDB_DB).read_bytes(), before)
        self.assertTrue((e.home / 'catalog.db').is_file())

    def test_replaced_archive_not_deleted_when_new_one_unreadable(self):
        e = self.env
        other = e.ext / 'D' / 'imdb'
        make_archive(other)
        run(self.ctx, 'imdb', str(other), 'adopt')
        (other / sl.IMDB_DB).write_bytes(b'kaputt' * 100)
        with self.assertRaises(ValueError):
            self.ctx.cleanup('imdb', sl.CONFIRM)
        self.assertTrue((e.home / 'imdb' / sl.IMDB_DB).is_file())

    def test_waits_for_running_rebuild_and_holds_updates(self):
        e = self.env
        self.archive.running = True
        sl.MOVER.start(self.ctx, 'imdb', str(e.ext / 'I'))
        try:
            for _ in range(50):
                if sl.MOVER.status()['phase'] == 'waiting':
                    break
                threading.Event().wait(0.02)
            self.assertEqual(sl.MOVER.status()['phase'], 'waiting')
            self.assertTrue(sl.imdb_held())
        finally:
            self.archive.running = False
            sl.MOVER.thread.join(30)
        self.assertEqual(sl.MOVER.status()['phase'], 'done')
        self.assertFalse(sl.imdb_held())

    def test_system_move_leaves_old_archive_when_imdb_has_own_place(self):
        e = self.env
        run(self.ctx, 'imdb', str(e.ext / 'I'))
        plan = self.ctx.plan('system', str(e.ext / 'S'))
        self.assertIn(str(e.home / 'imdb'), plan['exclude'])
        state = run(self.ctx, 'system', str(e.ext / 'S'))
        self.assertEqual(state['phase'], 'ready', state)
        sl.data_root(e.home, log=lambda *_: None)
        self.assertFalse((e.ext / 'S' / 'imdb').exists())
        # Ziel des Systemumzugs darf nicht im Archivordner liegen
        self.assertFalse(self.ctx.plan('system', str(e.ext / 'I' / 'x'))['check']['ok'])


class ArchiveTests(unittest.TestCase):
    def test_unreachable_place_runs_without_archive_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / 'home'
            home.mkdir()
            sl.write_pointer(home, {'imdb_dir': str(base / 'Volumes' / 'Weg' / 'IMDb')})
            folder, ok = sl.imdb_location(home, home)
            self.assertFalse(ok)
            a = imdb_archive.Archive(home, threading.Event(), folder=folder, available=ok)
            self.assertFalse(folder.exists())
            self.assertEqual(a.status()['phase'], 'unavailable')
            self.assertEqual(a.candidates({'title': 'film'}, {'title': 'film', 'kind': 'movie'}), [])
            ctx = sl.Context(home, home, lambda: {'download_dir': '', 'cache_dir': ''}, lambda s: None, None)
            row = {r['kind']: r for r in ctx.overview()['locations']}['imdb']
            self.assertIn('nicht erreichbar', row['problem'])
            # Laufwerk wieder da: Archiv meldet sich ohne Neustart zurück
            make_archive(folder)
            (folder / sl.PLACE_MARKER).write_text('{}')
            a.locate = lambda: sl.imdb_location(home, home)
            a.relocate(*a.locate())
            self.assertTrue(a.status()['ready'])
            self.assertEqual(len(a.candidates({'title': 'film'}, {'title': 'film', 'kind': 'movie'})), 1)
            self.assertIsNotNone(a.timing()['average_ms'])

    def test_vanishing_drive_switches_archive_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'IMDb'
            make_archive(folder)
            a = imdb_archive.Archive(tmp, threading.Event(), folder=folder)
            self.assertTrue(a.updated)
            (folder / sl.IMDB_DB).rename(Path(tmp) / 'weg.db')
            with self.assertRaises(OSError):
                a.candidates({'title': 'film'}, {'title': 'film', 'kind': 'movie'})
            self.assertEqual(a.status()['phase'], 'unavailable')
            self.assertEqual(a.candidates({'title': 'film'}, {'title': 'film', 'kind': 'movie'}), [])

    def test_wiring(self):
        self.assertIn('storage_locations.imdb_location(HOME,ROOT', SERVER)
        self.assertIn('folder=_IMDB_DIR,available=_IMDB_OK', SERVER)
        self.assertIn('imdb=IMDB)', SERVER)
        js = (ROOT / 'web' / 'storage_locations.js').read_text(encoding='utf-8')
        self.assertIn('Vorhandenes Archiv am Ziel verwenden', js)
        self.assertIn('Zurück in den Datenordner', js)


if __name__ == '__main__':
    unittest.main()
