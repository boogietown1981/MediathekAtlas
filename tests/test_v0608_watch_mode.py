"""0.6.8 Ansehen-Modus für Erwachsene (Björn, 15.11.2026: „Bitte auch einen Erwachsenen-Modus“).
/ansehen = dieselbe Seite wie „/“ ohne Verwaltung; /api/watch-home liefert Offline-Kopien und alle Abo-Videos."""
import json
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import watch_home, youtube_abos as ab, watch_state  # noqa: E402
from _wiring import routed, SERVER  # noqa: E402


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.catalog = self.root / 'catalog.db'
        with self.db() as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.catalog)
        try:
            with c:
                yield c
        finally:
            c.close()

    def job(self, jid, title, state='done', exists=True, **extra):
        path = self.root / 'Downloads' / (title + '.mp4')
        path.parent.mkdir(exist_ok=True)
        if exists:
            path.write_bytes(b'x')
        payload = {'id': jid, 'path': str(path), 'metadata': {'kind': 'movie', 'title': title, 'year': 2020,
                   'provider': 'pluto', 'poster': 'https://img.example.org/p.jpg'}, 'source': {'duration': 600}, **extra}
        with self.db() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps(payload), state))
        return path


class OfflineTests(Fixture):
    def test_lists_finished_files_newest_first_without_abo_videos(self):
        self.job('a1', 'Alt')
        self.job('b2', 'Neu')
        self.job('c3', 'Fehlt', exists=False)
        self.job('d4', 'Läuft noch', state='downloading')
        self.job('e5', 'Abo-Video', youtube_abo=1)
        with self.db() as c:
            rows = watch_home.offline(c, {})
        self.assertEqual([r['title'] for r in rows], ['Neu', 'Alt'])
        self.assertEqual(rows[0]['poster'], 'https://img.example.org/p.jpg')
        self.assertTrue(rows[0]['new'])

    def test_progress_and_seen_marks(self):
        self.job('a1', 'Angefangen')
        self.job('b2', 'Gesehen')
        marks = {'job:a1': {'pos': 150, 'done': False}, 'job:b2': {'pos': 0, 'done': True}}
        with self.db() as c:
            rows = {r['job']: r for r in watch_home.offline(c, marks)}
        self.assertEqual(rows['a1']['progress'], 0.25)
        self.assertFalse(rows['a1']['new'])
        self.assertTrue(rows['b2']['done'])
        self.assertEqual(rows['b2']['progress'], 0)

    def test_episode_label_and_unsafe_poster(self):
        self.job('a1', 'Serie', metadata={'kind': 'series', 'title': 'Serie', 'season': 1, 'episode': 2,
                                          'episode_title': 'Pilot', 'poster': 'javascript:alert(1)'})
        with self.db() as c:
            row = watch_home.offline(c, {})[0]
        self.assertEqual(row['title'], 'Serie · S01E02 · Pilot')
        self.assertEqual(row['kind'], 'episode')
        self.assertEqual(row['poster'], '')


class AboTests(Fixture):
    def setUp(self):
        super().setUp()
        now = time.time()
        db = ab._connect(self.root)
        with db:
            for i, (name, kids) in enumerate((('Kinderkanal', 1), ('Doku-Kanal', 0)), 1):
                db.execute("INSERT INTO youtube_abos(id,ref,label,kids,profile,added) VALUES(?,?,?,?,?,?)", (i, '@k%d' % i, name, kids, 'kinder' if kids else 'erwachsene', now))
                jid = 'job%d' % i
                db.execute("INSERT INTO youtube_abo_videos(abo_id,video,title,state,job_id,found,done_at,duration) "
                           "VALUES(?,?,?,'done',?,?,?,300)", (i, 'v%010d' % i, 'Video %d' % i, jid, now, now))
                self.job(jid, 'Video %d' % i, youtube_abo=i)
        db.close()

    def test_kids_view_still_only_kids_channels(self):
        with self.db() as c:
            data = ab.kids(self.root, c, watch={})
        self.assertEqual([ch['name'] for ch in data['channels']], ['Kinderkanal'])

    def test_watch_home_has_only_own_channels(self):
        # 0.6.11 (Björn, 16.11.2026): Kinder-Abos erscheinen nicht mehr im Ansehen-Modus.
        with self.db() as c:
            data = watch_home.home(self.root, c, watch={})
        self.assertEqual([ch['name'] for ch in data['abos']['channels']], ['Doku-Kanal'])
        self.assertEqual(len(data['abos']['videos']), 1)
        self.assertEqual(data['offline'], [])          # Abo-Videos stehen nicht doppelt unter „Offline“


class WiringTests(unittest.TestCase):
    def test_routes(self):
        self.assertTrue(routed('/ansehen', 'GET', 'signed'))
        self.assertTrue(routed('/api/watch-home', 'GET', 'api'))
        self.assertIn('data-mode="watch"', SERVER)

    def test_page_and_scripts(self):
        html = text('web/index.html')
        self.assertIn('href="/ansehen"', html)
        self.assertIn('<section id="watch"', html)
        self.assertIn('<script src="/watch_mode.js"></script></body>', html)
        scripts = re.search(r"^SCRIPTS=\((.*)\)$", SERVER, re.M).group(1)
        self.assertIn("'/watch_mode.js'", scripts)
        app = text('web/app.js')
        self.assertIn("const ATLAS_VIEWS=['watch',", app)
        self.assertIn("window.AtlasWatchMode?.show()", app)
        self.assertIn("for(const v of ['watch',", text('web/titleview.js'))
        self.assertIn('rowOf,open:openItem', text('web/unified_catalog.js'))

    def test_fullscreen_before_player(self):
        # Erst nach dem Wechsel ins Vollbild abspielen; sonst liegt die Seite über dem Player.
        js = text('web/watch_mode.js')
        self.assertIn("fullscreen().then(() => window.playRef(", js)
        self.assertIn("fullscreen().then(() => window.playLive(", js)
        self.assertNotIn('localStorage.setItem', js)   # Ansicht ändert keine Einstellungen

    def test_player_sends_page_token_for_local_files(self):
        self.assertIn("src.startsWith('/api/stream?')&&!/[?&]token=/.test(src)", text('web/player.js'))

    def test_kids_image_serves_any_finished_job_poster(self):
        self.assertIn("found=youtube_abos.poster_file(job)   # 0.6.8", SERVER)


if __name__ == '__main__':
    unittest.main()
