"""0.6.86: Diagnose MacBook Air 22.11.2026 (0.6.85, erster echter Lauf).

- Umzug von exFAT nach intern brach ab: „._dailyme.sqlite3 fehlt“ – macOS-Hilfsdateien (AppleDouble) gibt es auf APFS
  nicht. Der Rückweg-Knopf hieß „Bisherigen Ort verwenden“ und führte in den Standardordner.
- Die Folgensuche startete 21 s vor der Planet-Schule-Heilung.
- Serienvorlagen „Sport“ und „Masterclass“.
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

import catalog
import catalog_service
import storage_locations as sl

ROOT = Path(__file__).resolve().parents[1]


class AppleDouble(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name) / 'usb';self.dst = Path(tmp.name) / 'intern'
        (self.src / 'sub').mkdir(parents=True);self.dst.mkdir()
        c = sqlite3.connect(self.src / 'dailyme.sqlite3');c.execute('CREATE TABLE t(x)');c.commit();c.close()
        (self.src / 'sub' / 'notiz.txt').write_text('hallo')
        for name in ('._dailyme.sqlite3', 'sub/._notiz.txt', '._.'):
            (self.src / name).write_bytes(b'\x00\x05\x16\x07AppleDouble')

    def test_helper_files_are_neither_copied_nor_checked_and_go_with_their_file(self):
        rels = sorted(str(rel) for _, rel, _ in sl.walk(self.src))
        self.assertEqual(rels, ['dailyme.sqlite3', os.path.join('sub', 'notiz.txt')])
        for full, rel, _ in sl.walk(self.src):
            (self.dst / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dst / rel).write_bytes(full.read_bytes())
        self.assertEqual(sl.verify_tree(self.src, self.dst), [])
        sl.remove_verified(self.src, self.dst)
        self.assertFalse((self.src / 'sub' / '._notiz.txt').exists())
        self.assertFalse((self.src / '._dailyme.sqlite3').exists())

    def test_target_with_only_helper_files_counts_as_empty(self):
        (self.dst / '._x').write_bytes(b'x')
        result = sl.inspect('system', self.src, self.dst)
        self.assertNotIn('Der Zielordner ist nicht leer. Bitte einen leeren oder neuen Ordner wählen.', result.get('problems', []))

    def test_revert_button_names_the_default_folder(self):
        self.assertEqual(sl.revert_label({'is_default': True}), 'Standardordner verwenden')
        self.assertEqual(sl.revert_label({'is_default': False}), 'Bisherigen Ort verwenden')
        launcher = (ROOT / 'launcher.sh').read_text()
        self.assertIn('Standardordner verwenden', launcher);self.assertIn('4) REVERT=', launcher)
        self.assertIn("rv.is_default?'Standardordner wieder verwenden'", (ROOT / 'web' / 'storage_locations.js').read_text())


def database_service():
    c = sqlite3.connect(':memory:', check_same_thread=False);c.row_factory = sqlite3.Row;c.executescript(catalog.SCHEMA)

    class Ctx:
        def __enter__(self_):return c
        def __exit__(self_, *a):c.commit()
    return c, catalog_service.Service(lambda: Ctx(), lambda: {'auto_metadata': True, 'episode_workers': 1}, threading.Event(), None)


class HealsFirst(unittest.TestCase):
    def test_workers_wait_for_the_heals_and_then_run(self):
        c, svc = database_service()
        svc.heals_done = threading.Event();svc.heals_started = time.monotonic()
        claimed = []
        svc.metadata_once = lambda queue='identity': claimed.append(queue) or svc.stop.set() or False
        worker = threading.Thread(target=svc.episode_loop, args=(0,), daemon=True);worker.start()
        time.sleep(.3)
        self.assertEqual(claimed, [])              # still waiting
        svc.early_heals()
        worker.join(5)
        self.assertEqual(claimed, ['episode'])
        self.assertTrue(catalog.get_state(c, 'portal_reseed_v0692', False))
        self.assertTrue(catalog.get_state(c, 'generic_templates_v0692', False))

    def test_gate_opens_after_the_bound(self):
        _, svc = database_service()
        svc.heals_done = threading.Event();svc.heals_started = time.monotonic() - svc.HEAL_WAIT - 1
        self.assertFalse(svc.wait_for_heals());self.assertTrue(svc.heals_done.is_set())
        self.assertFalse(catalog_service.Service.__new__(catalog_service.Service).wait_for_heals())  # outside start(): open


class SubjectTemplates(unittest.TestCase):
    def test_subject_templates_dropped_and_works_recognised_again(self):
        c, svc = database_service()
        sport = {'kind': 'series', 'title': 'Sport', 'provider': 'IMDb Offline', 'reference_id': 'tt1', 'year': 2001}
        puls = {'kind': 'series', 'title': 'Puls', 'provider': 'TMDB', 'reference_id': '9', 'year': 2001}
        for topic, m in (('sport', sport), ('puls', puls)):
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', (topic, m['provider'], m['reference_id'], json.dumps(m)))
        catalog.ingest(c, [{'title': t, 'topic': topic, 'duration': 1500, 'channel': 'SRF', 'description': 'x' * 60 + t,
                            'url_video': 'https://example.org/%d.mp4' % i, 'timestamp': 1782086400}
                           for i, (t, topic) in enumerate((('Skirennen in Wengen', 'Sport'), ('Schlaf und Gesundheit', 'Puls')))])
        self.assertFalse(catalog.template_topic('Sport'));self.assertFalse(catalog.template_topic('Masterclass'))
        self.assertTrue(catalog.template_topic('Puls'))
        rows = {r['t']: r for r in c.execute("SELECT w.*,json_extract(o.payload,'$.title') t FROM works w JOIN offers o ON o.work_id=w.id")}
        self.assertEqual(rows['Skirennen in Wengen']['kind'], 'unknown')       # no template on import
        self.assertEqual((rows['Schlaf und Gesundheit']['title'], rows['Schlaf und Gesundheit']['state']), ('Puls', 'identified'))
        # a work that took „Sport“ from the template before 0.6.86
        wid = rows['Skirennen in Wengen']['id']
        m = dict(json.loads(rows['Skirennen in Wengen']['meta']), **sport, reason='Serienidentität aus bereits bestätigter Folge übernommen; Episode noch zu prüfen')
        c.execute("UPDATE works SET title='Sport',kind='series',state='identified',meta=? WHERE id=?", (json.dumps(m), wid))
        svc.reset_generic_identities()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM series_templates WHERE topic='sport'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM series_templates WHERE topic='puls'").fetchone()[0], 1)
        row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
        self.assertEqual((row['state'], row['title']), ('pending', 'Skirennen in Wengen'))
        puls_row = c.execute('SELECT * FROM works WHERE id=?', (rows['Schlaf und Gesundheit']['id'],)).fetchone()
        self.assertEqual((puls_row['title'], puls_row['state']), ('Puls', 'identified'))
        self.assertEqual(catalog.get_state(c, 'generic_templates_v0692')['works'], 1)


if __name__ == '__main__':
    unittest.main()
