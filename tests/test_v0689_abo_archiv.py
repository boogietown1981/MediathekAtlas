"""0.6.89 (Björn 22.11.2026): zu Ende gesehene YouTube-Abo-Videos wandern ins Archiv. Dort gilt keine
30-Tage-Frist, und sie zählen weder zu „höchstens N Videos“ noch zu den Budgets."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube_abos as ab, watch_state, netzkino_downloads as nd  # noqa: E402
from test_v0607_youtube_abos import Fixture, KIDS, NOW  # noqa: E402
from test_v0553_youtube import video, vid  # noqa: E402
from _wiring import routed  # noqa: E402


class ArchiveTests(Fixture):
    def finish_all(self, abo):
        """Alle Aufträge fertig, mit Datei und Vorschaubild im Abo-Ordner."""
        out = {}
        for j in self.jobs():
            path = Path(j['target'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'v' * 1000)
            path.with_name(path.stem + '-poster.jpg').write_bytes(b'\xff\xd8\xffjpg')
            self.set_job(j['id'], 'done', path=str(path), offline_until=NOW + 86400)
            out[j['source']['_video_id']] = j
        with self.db() as c:
            db = ab._connect(self.root)
            ab.sync_states(c, db, abo)
            db.close()
        return out

    def sweep(self, now):
        with self.db() as c:
            db = ab._connect(self.root)
            try:
                return ab.archive_watched(self.root, c, db, now=now)
            finally:
                db.close()

    def test_watched_video_moves_to_archive_without_period(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = self.finish_all(abo)
        key = 'job:' + jobs[vid(37)]['id']
        watch_state.progress(self.root, key, pos=400, duration=427, done=True, now=NOW + 100)
        # Abspann läuft noch: nicht sofort verschieben
        self.assertEqual(self.sweep(NOW + 120), 0)
        self.assertEqual(self.sweep(NOW + 100 + ab.ARCHIVE_GRACE), 1)
        job = {j['id']: j for j in self.jobs()}[jobs[vid(37)]['id']]
        new = Path(job['path'])
        self.assertIn(ab.ARCHIVE_FOLDER, new.parts)
        self.assertTrue(new.is_file())
        self.assertTrue(new.with_name(new.stem + '-poster.jpg').is_file())
        self.assertFalse(Path(job['archived_from']).exists())
        self.assertNotIn('offline_until', job)
        self.assertEqual(self.videos(abo)[vid(37)]['state'], 'archived')
        self.assertEqual(self.videos(abo)[vid(38)]['state'], 'done')
        # Frist: das archivierte bleibt, das ungesehene läuft nach 30 Tagen ab
        with self.db() as c:
            expired = nd.expire(c, now=NOW + 400 * 86400)
        self.assertEqual(expired, [jobs[vid(38)]['id']])
        self.assertTrue(new.is_file())
        with self.db() as c:
            db = ab._connect(self.root)
            ab.sync_states(c, db)
            db.close()
        self.assertEqual(self.videos(abo)[vid(37)]['state'], 'archived')
        # weiter abspielbar: Kinderecke zeigt es, Gesehen-Stand bleibt am selben Schlüssel
        with self.db() as c:
            kids = ab.kids(self.root, c)
        shown = {v['video']: v for v in kids['videos']}
        self.assertTrue(shown[vid(37)]['archived'])
        self.assertTrue(shown[vid(37)]['done'])

    def test_archived_does_not_count_for_keep_or_budget(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'keep': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = self.finish_all(abo)
        KIDS[41] = video(41, 'Bluey Folge 41', 500, channel='Kinderkanal')
        KIDS[41]['snippet']['publishedAt'] = '2026-11-21T08:00:00Z'
        self.addCleanup(KIDS.pop, 41)
        self.api.order.insert(0, 41)
        watch_state.progress(self.root, 'job:' + jobs[vid(37)]['id'], pos=400, duration=427, done=True, now=NOW)
        ab.check(self.root, abo, now=NOW + 7200, request=self.api)
        states = self.videos(abo)
        self.assertEqual(states[vid(41)]['state'], 'queued')       # Platz durch das Archiv, nicht durch Löschen
        self.assertEqual(states[vid(37)]['state'], 'archived')
        archived = {j['id']: j for j in self.jobs()}[jobs[vid(37)]['id']]
        self.assertTrue(Path(archived['path']).is_file())
        with self.db() as c:
            db = ab._connect(self.root)
            done, _queued = ab.held(c, db, {'id': abo, 'quality': '720'})
            total_done, _ = ab.total_held(c, db, self.root)
            db.close()
            summary = ab.archive_summary(self.root, c)
        self.assertEqual(done, 1000)                               # nur das ungesehene 38
        self.assertEqual(total_done, 1000)
        self.assertEqual((summary['videos'], summary['enabled']), (1, True))

    def test_switch_off_keeps_old_rule(self):
        ab.set_archive(self.root, False)
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = self.finish_all(abo)
        watch_state.progress(self.root, 'job:' + jobs[vid(38)]['id'], pos=400, duration=428, done=True, now=NOW)
        self.assertEqual(self.sweep(NOW + 9999), 0)
        self.assertEqual(self.videos(abo)[vid(38)]['state'], 'done')

    def test_manual_delete_from_archive_marks_expired(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = self.finish_all(abo)
        job_id = jobs[vid(38)]['id']
        watch_state.progress(self.root, 'job:' + job_id, pos=400, duration=428, done=True, now=NOW)
        self.sweep(NOW + 9999)
        with self.db() as c:
            nd.delete_now(c, job_id, NOW + 10000)
            db = ab._connect(self.root)
            ab.sync_states(c, db)
            db.close()
        self.assertEqual(self.videos(abo)[vid(38)]['state'], 'expired')
        self.assertFalse(any(p.is_file() and p.suffix == '.mp4' for p in self.downloads.rglob('*')))

    def test_archive_path(self):
        p = Path('/x/YouTube-Abos/Kanal/2026 - Titel [abc].mp4')
        self.assertEqual(ab.archive_path(p), Path('/x/YouTube-Abos/_Archiv/Kanal/2026 - Titel [abc].mp4'))
        self.assertIsNone(ab.archive_path(Path('/x/YouTube-Abos/_Archiv/Kanal/a.mp4')))
        self.assertIsNone(ab.archive_path(Path('/x/Filme/a.mp4')))

    def test_route_and_ui(self):
        self.assertIn("action=='archive'", (ROOT / 'server.py').read_text(encoding='utf-8'))
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn("action: 'archive'", js)
        self.assertIn('youtube-abos-archive', js)


if __name__ == '__main__':
    unittest.main()
