"""0.6.27 (Björn, 19.11.2026): YouTube-Abos im Dashboard je Kanal, einheitliche Katalogübersicht,
gegliederte Downloadwarteschlange, Zeitpunkt der Werkzuordnung bei den Aufgaben."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import pluto, pluto_enrichment, ui_prefs, youtube_abos as ab  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW  # noqa: E402

WEB = ROOT / 'web'
read = lambda name: (ROOT / name).read_text(encoding='utf-8')


class LibraryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.kid = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'profile': 'kinder'}, now=NOW)
        self.me = ab.add(self.root, {'url': '@Doku', 'mode': 'new', 'start_count': 1, 'profile': 'erwachsene', 'label': 'Doku'}, now=NOW)
        for abo in (self.kid, self.me):
            ab.check(self.root, abo, now=NOW, request=self.api)

    def test_all_profiles_grouped_by_channel(self):
        jobs = self.jobs()
        self.assertGreaterEqual(len(jobs), 2)
        done = jobs[0]
        path = self.downloads / 'eins.mp4'
        path.write_bytes(b'x')
        self.set_job(done['id'], 'done', path=str(path), offline_until=NOW + 86400)
        with self.db() as c:
            data = ab.library(self.root, c, watch={})
        self.assertEqual({ch['id'] for ch in data['channels']}, {self.kid, self.me})
        # Die Testquelle liefert für beide Abos dieselben Videos: ein Auftrag, je Kanal ein Eintrag.
        self.assertTrue(data['videos'])
        self.assertEqual({v['job'] for v in data['videos']}, {done['id']})
        owners = {v['abo'] for v in data['videos']}
        self.assertIn(data['channels'][0]['id'], owners)  # Kanal mit neuem Video zuerst
        self.assertEqual(data['channels'][0]['new'], 1)
        for ch in data['channels']:
            for key in ('profile_label', 'checked', 'next_check', 'queued', 'failed', 'retry', 'enabled', 'url'):
                self.assertIn(key, ch)
            self.assertTrue(ch['checked'])                 # geprüft mit Zeitpunkt
        self.assertTrue(all(ch['queued'] >= 0 for ch in data['channels']))
        self.assertGreater(sum(ch['queued'] for ch in data['channels']), 0)
        self.assertIn('pause', data)

    def test_profile_views_unchanged(self):
        with self.db() as c:
            self.assertEqual({ch['id'] for ch in ab.kids(self.root, c, watch={})['channels']}, {self.kid})
            with self.assertRaises(ValueError):
                ab.kids(self.root, c, watch={}, profile='gibtsnicht')


class MetricsTests(unittest.TestCase):
    def test_only_current_catalogue_counts_and_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = pluto._connect(root)
            with db:
                pluto._set(db, 'last_success', '1000')
                for i, seen in (('a', 1000), ('b', 1000), ('alt', 10)):
                    db.execute("INSERT INTO pluto_items(id,kind,title,seen,updated) VALUES(?,?,?,?,?)", (i, 'movie', i, seen, seen))
            db.close()
            pluto_enrichment.metrics(root)   # legt die Prüftabelle an
            db = pluto._connect(root)
            with db:
                for i, at, status in (('a', 2000, 'candidate'), ('b', 3000, 'no_match'), ('alt', 50, 'candidate'), ('weg', 60, 'review')):
                    db.execute('INSERT INTO pluto_reference_checks(item_id,checked,identity,payload) VALUES(?,?,?,?)',
                               (i, at, '', json.dumps({'status': status})))
            db.close()
            m = pluto_enrichment.metrics(root)
        self.assertEqual(m['checked'], 2)
        self.assertEqual(m['by_status'], {'candidate': 1, 'no_match': 1})
        self.assertEqual((m['last_checked'], m['oldest_checked'], m['stored'], m['listed']), (3000, 2000, 4, 2))


class WiringTests(unittest.TestCase):
    def test_dashboard_abos(self):
        server, index, js = read('server.py'), read('web/index.html'), read('web/abo_shelf.js')
        self.assertIn("@ROUTES.get('/api/youtube-abo-videos')", server)
        self.assertIn("'/abo_shelf.js'", server)
        self.assertIn('data-cross-kind="abos"', index)        # 0.6.37: Unteransicht von YouTube
        self.assertNotIn('data-catalog-source="abos"', index)
        self.assertIn('<script src="/abo_shelf.js"></script>', index)
        self.assertIn("window.api('youtube-abo-videos')", js)
        self.assertIn("'atlas-source'", read('web/unified_catalog.js'))
        self.assertIn('abos', ui_prefs.START_SOURCES)
        self.assertEqual(ui_prefs.clean({'start_source': 'abos'}).get('start_source'), 'abos')
        # eigene Klassen, keine Überschneidung mit der Abo-Verwaltung (.abo-*)
        self.assertNotIn("'abo-", js.replace("'abo-shelf", ''))

    def test_uniform_overview_and_queue(self):
        uc, app, admin, css = read('web/unified_catalog.js'), read('web/app.js'), read('web/admin.js'), read('web/style.css')
        self.assertIn('function portalTable(list)', uc)
        self.assertIn("if (list.length>1) board.append(portalTable(list));", uc)
        for label in ("'Filme & Serien im Katalog'", "'eindeutig zugeordnet'", "'zu prüfen'", "'ohne Treffer'", "'noch offen'", "'offline'"):
            self.assertIn(label, uc)
        self.assertIn('function renderQueue(jobs,server)', app)
        for key in ("key:'running'", "key:'waiting'", "key:'planned'", "key:'held'", "key:'failed'", "key:'done'"):
            self.assertIn(key, app)
        self.assertIn("'YouTube-Abo · '", app)
        self.assertIn("'zuletzt geprüft '", admin)
        self.assertIn('.queue-group', css)
        self.assertIn('.atlas-portal-table', css)
        self.assertIn("'last_checked':ref.get('last_checked')", read('server.py'))


if __name__ == '__main__':
    unittest.main()
