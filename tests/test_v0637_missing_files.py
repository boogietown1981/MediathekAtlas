"""0.6.37 (Björn, 19.11.2026): Downloads als Liste; fehlende Dateien automatisch an den bekannten
Speicherorten suchen und Einträge ohne Datei entfernen; Umzug mit „Vorhandene übernehmen“ passt Pfade an;
YouTube-Abos als Unteransicht von YouTube."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import local_library, storage_locations  # noqa: E402

read = lambda name: (ROOT / name).read_text(encoding='utf-8')


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.c = sqlite3.connect(':memory:')
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        self.c.execute('CREATE TABLE downloaded_items(identity TEXT PRIMARY KEY,path TEXT)')
        self.addCleanup(self.c.close)

    def job(self, job_id, path, size=None, state='done'):
        data = {'id': job_id, 'state': state, 'path': str(path), 'target': str(path)}
        if size is not None:
            data['size_bytes'] = size
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', (job_id, json.dumps(data), state))
        self.c.execute('INSERT INTO downloaded_items VALUES(?,?)', ('id-' + job_id, str(path)))

    def path_of(self, job_id):
        row = self.c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row[0])['path'] if row else None

    def file(self, rel, data=b'x' * 10):
        p = self.base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p


class RepairTests(Base):
    def test_moved_download_folder_found_by_relative_path(self):
        old = self.base / 'alt' / 'Downloads'
        new = self.base / 'Docking' / 'Downloads'
        self.job('a', old / 'ZDF' / 'Tod in den Wäldern.mkv', size=10)
        self.file('Docking/Downloads/ZDF/Tod in den Wäldern.mkv')
        r = local_library.repair_missing(self.c, [new], old_roots=[old, new])
        self.assertEqual((r['checked'], r['relinked'], r['missing']), (1, 1, 0))
        self.assertEqual(self.path_of('a'), str(new / 'ZDF' / 'Tod in den Wäldern.mkv'))
        self.assertEqual(self.c.execute('SELECT path FROM downloaded_items').fetchone()[0], self.path_of('a'))

    def test_found_by_name_elsewhere_size_must_match(self):
        new = self.base / 'Docking'
        self.job('a', '/gibtsnicht/Film.mkv', size=10)
        self.job('b', '/gibtsnicht/Anders.mkv', size=99)
        self.file('Docking/irgendwo/tief/Film.mkv')
        self.file('Docking/x/Anders.mkv')                 # falsche Größe
        r = local_library.repair_missing(self.c, [new])
        self.assertEqual((r['relinked'], r['missing']), (1, 1))
        self.assertEqual(self.path_of('b'), '/gibtsnicht/Anders.mkv')

    def test_two_candidates_stay_open(self):
        new = self.base / 'Docking'
        self.job('a', '/weg/Film.mkv', size=10)
        self.file('Docking/a/Film.mkv')
        self.file('Docking/b/Film.mkv')
        r = local_library.repair_missing(self.c, [new])
        self.assertEqual((r['relinked'], r['ambiguous']), (0, 1))

    def test_existing_files_untouched(self):
        p = self.file('Docking/Film.mkv')
        self.job('a', p, size=10)
        r = local_library.repair_missing(self.c, [self.base / 'Docking'])
        self.assertEqual(r['checked'], 0)


class RemoveTests(Base):
    def test_only_missing_done_entries_go(self):
        here = self.file('Docking/Film.mkv')
        self.job('ok', here)
        self.job('weg1', '/weg/a.mkv')
        self.job('weg2', '/weg/b.mkv')
        self.job('wartet', '/weg/c.mkv', state='queued')
        self.assertEqual(local_library.remove_missing(self.c, ['weg1']), 1)
        self.assertEqual(local_library.remove_missing(self.c), 1)
        left = {r[0] for r in self.c.execute('SELECT id FROM jobs')}
        self.assertEqual(left, {'ok', 'wartet'})
        self.assertTrue(here.is_file())
        self.assertEqual({r[0] for r in self.c.execute('SELECT path FROM downloaded_items')}, {str(here), '/weg/c.mkv'})


class AdoptTests(Base):
    def test_adopt_rewrites_only_where_file_exists(self):
        src, dst = self.base / 'alt', self.base / 'neu'
        self.job('da', src / 'A.mkv')
        self.job('fehlt', src / 'B.mkv')
        self.file('neu/A.mkv')
        changed = storage_locations.rewrite_paths(self.c, [(src, dst)], only_existing=True)
        self.assertEqual(changed, 2)                      # Auftrag + downloaded_items von A
        self.assertEqual(self.path_of('da'), str(dst / 'A.mkv'))
        self.assertEqual(self.path_of('fehlt'), str(src / 'B.mkv'))

    def test_commit_uses_pairs_also_for_adopt(self):
        code = read('storage_locations.py')
        self.assertIn("only_existing=mode != 'copy'", code)
        self.assertEqual(code.count("pairs = [(source, target)] if source else []"), 2)


class WiringTests(unittest.TestCase):
    def test_routes_and_ui(self):
        server, app, css = read('server.py'), read('web/app.js'), read('web/style.css')
        self.assertIn("@ROUTES.post('/api/library-repair')", server)
        self.assertIn("@ROUTES.post('/api/library-remove-missing')", server)
        self.assertIn('function jobRow(j,server,shared)', app)
        self.assertNotIn('function jobCard(', app)
        self.assertIn("key:'missing'", app)
        self.assertIn("api('library-repair',{})", app)
        self.assertIn('.queue-table', css)

    def test_abos_below_youtube(self):
        uc, index, shelf = read('web/unified_catalog.js'), read('web/index.html'), read('web/abo_shelf.js')
        self.assertIn('data-cross-kind="abos"', index)
        self.assertIn("b.hidden=source!=='youtube'", uc)
        self.assertNotIn("'abos','mediatheken'", uc)
        self.assertIn("source === 'youtube' && kind === 'abos'", shelf)
        self.assertNotIn('renderCompact', shelf)

    def test_work_catalogue_under_platforms(self):
        index, app, css, title = read('web/index.html'), read('web/app.js'), read('web/style.css'), read('web/titleview.js')
        self.assertIn('<button class="platform-tab" type="button" data-platform="mediatheken"', index)
        self.assertNotIn('data-view="legacy"', index)
        self.assertNotIn("'legacy'", app.split('\n')[36] + app.split('\n')[37])
        self.assertIn("if(name==='legacy'){$('portals').dataset.platform='mediatheken';name='portals';}", app)
        self.assertIn("if(name==='mediatheken'){catalogKey='';loadCatalog()", app)
        self.assertIn('#portals[data-platform="mediatheken"] > #legacy {display:block!important}', css)
        self.assertNotIn("'legacy'", title)


if __name__ == '__main__':
    unittest.main()
