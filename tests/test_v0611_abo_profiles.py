"""0.6.11 (Björn, 16.11.2026): Kanal-Abos getrennt für die Tochter (Kinderecke) und für ihn selbst
(Ansehen-Modus), ohne Vermischung; derselbe Kanal darf in beiden Profilen stehen."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube as yt, youtube_abos as ab, youtube_downloads as yd, watch_home, watch_state  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW, vid  # noqa: E402


class MigrationTests(unittest.TestCase):
    def test_old_table_gets_profiles_and_keeps_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = yt._connect(root)
            with db:   # Tabelle wie bis 0.6.10: ref eindeutig, kids-Schalter
                db.executescript('''CREATE TABLE youtube_abos(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE,
                  kind TEXT NOT NULL DEFAULT 'channel', label TEXT NOT NULL DEFAULT '', kids INTEGER NOT NULL DEFAULT 1,
                  mode TEXT NOT NULL DEFAULT 'new', added REAL NOT NULL);''')
                db.execute("INSERT INTO youtube_abos(id,ref,label,kids,added) VALUES(7,'@kind','Kinderkanal',1,1)")
                db.execute("INSERT INTO youtube_abos(id,ref,label,kids,added) VALUES(9,'@doku','Doku',0,1)")
            db.close()
            db = ab._connect(root)
            rows = {r['id']: (r['ref'], r['profile'], r['label'], r['mode']) for r in db.execute('SELECT * FROM youtube_abos')}
            db.close()
            self.assertEqual(rows, {7: ('@kind', 'kinder', 'Kinderkanal', 'new'), 9: ('@doku', 'erwachsene', 'Doku', 'new')})
            # zweites Öffnen ändert nichts
            db = ab._connect(root)
            self.assertFalse(ab._migrate(db))
            db.close()
            # derselbe Kanal jetzt auch für Erwachsene
            ab.add(root, {'url': '@kind', 'profile': 'erwachsene'})
            with self.assertRaises(ValueError):
                ab.add(root, {'url': '@kind', 'profile': 'kinder'})


class ProfileTests(Fixture):
    def setUp(self):
        super().setUp()
        self.kid = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'profile': 'kinder'}, now=NOW)
        self.me = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 1, 'profile': 'erwachsene', 'label': 'Für mich'}, now=NOW)
        for abo in (self.kid, self.me):
            ab.check(self.root, abo, now=NOW, request=self.api)

    def finish_all(self):
        for i, j in enumerate(self.jobs()):
            path = self.downloads / ('%d.mp4' % i)
            path.write_bytes(b'x')
            self.set_job(j['id'], 'done', path=str(path), offline_until=NOW + 86400)

    def test_views_do_not_mix(self):
        self.finish_all()
        with self.db() as c:
            kids = ab.kids(self.root, c, watch={})
            mine = watch_home.home(self.root, c, watch={})['abos']
        self.assertEqual({ch['id'] for ch in kids['channels']}, {self.kid})
        self.assertEqual({ch['id'] for ch in mine['channels']}, {self.me})
        self.assertEqual({v['abo'] for v in kids['videos']}, {self.kid})
        self.assertEqual({v['abo'] for v in mine['videos']}, {self.me})
        self.assertEqual(len(kids['videos']), 2)
        self.assertEqual(len(mine['videos']), 1)
        self.assertEqual(mine['channels'][0]['profile'], 'erwachsene')

    def test_same_video_is_one_file(self):
        # Das neueste Video steht in beiden Profilen: ein Auftrag, eine Datei.
        self.assertEqual(len(self.jobs()), 2)
        kid = self.videos(self.kid)[vid(38)]['job_id']
        self.assertEqual(self.videos(self.me)[vid(38)]['job_id'], kid)

    def test_making_room_keeps_a_file_the_other_profile_holds(self):
        self.finish_all()
        job = self.videos(self.me)[vid(38)]['job_id']
        watch_state.progress(self.root, 'job:' + job, pos=400, duration=420, done=True)
        abo = dict(self.overview_row(self.kid), _root=str(self.root))
        with self.db() as c:
            db = ab._connect(self.root)
            ab.sync_states(c, db)
            # vid(38) ist das älteste fertige? Reihenfolge done_at gleich – wir prüfen gezielt dieses Video
            db.execute("UPDATE youtube_abo_videos SET done_at=1 WHERE abo_id=? AND video=?", (self.kid, vid(38)))
            db.commit()
            self.assertTrue(ab._make_room(c, db, abo, NOW))
            db.commit()
            db.close()
        self.assertEqual(self.videos(self.kid)[vid(38)]['state'], 'expired')
        self.assertTrue(any(j['id'] == job and j['_state'] == 'done' for j in self.jobs()))   # Datei bleibt für „Für mich“

    def overview_row(self, abo_id):
        return next(a for a in ab.overview(self.root)['abos'] if a['id'] == abo_id)

    def test_overview_counts_per_profile_and_move(self):
        data = ab.overview(self.root)
        self.assertEqual({p['key']: p['abos'] for p in data['profiles']}, {'kinder': 1, 'erwachsene': 1})
        with self.assertRaises(ValueError):           # gleiches Profil zweimal für denselben Kanal
            ab.change(self.root, self.me, {'profile': 'kinder'})
        ab.change(self.root, self.me, {'action': 'remove'})
        ab.change(self.root, self.kid, {'profile': 'erwachsene'})
        self.assertEqual(self.overview_row(self.kid)['profile'], 'erwachsene')
        self.assertEqual(self.overview_row(self.kid)['kids'], 0)

    def test_legacy_kids_flag_still_works(self):
        self.assertEqual(ab.profile_of({'kids': False}), 'erwachsene')
        self.assertEqual(ab.profile_of({'kids': True}), 'kinder')
        self.assertEqual(ab.profile_of({}), 'kinder')
        with self.assertRaises(ValueError):
            ab.profile_of({'profile': 'oma'})
        with self.db() as c, self.assertRaises(ValueError):
            ab.kids(self.root, c, profile='oma')


class InterfaceTests(unittest.TestCase):
    def test_admin_has_profile_tabs_and_shared_form(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="youtube-abos-profiles"', html)
        self.assertIn('id="youtube-abo-add"', html)
        self.assertNotIn('id="youtube-abo-form"', html)
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        for needle in ("kinder: {icon", "erwachsene: {icon", "'Für wen?'", "'Weitere Einstellungen'", "aria-selected"):
            self.assertIn(needle, js)
        self.assertNotIn('auch in der Kinderecke', (ROOT / 'web' / 'watch_mode.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
