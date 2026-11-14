"""0.5.48: JustWatch titles released only at night (youth protection) are reserved and start then."""
import datetime
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import job_queue  # noqa: E402
import justwatch  # noqa: E402
import justwatch_downloads  # noqa: E402
import netzkino_downloads  # noqa: E402


def berlin(day, hour, minute):
    import zoneinfo
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=zoneinfo.ZoneInfo('Europe/Berlin')).timestamp()


def jobs_db():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, payload TEXT, state TEXT)')
    return c


class NightWindowTests(unittest.TestCase):
    def test_afternoon_waits_until_after_midnight(self):
        start = justwatch.night_start(berlin(12, 17, 25))
        self.assertEqual(start, berlin(13, 0, 10))

    def test_inside_window_starts_now(self):
        now = berlin(13, 1, 30)
        self.assertEqual(justwatch.night_start(now), now)

    def test_too_late_in_the_morning_waits_for_next_night(self):
        self.assertEqual(justwatch.night_start(berlin(13, 5, 30)), berlin(14, 0, 10))
        self.assertEqual(justwatch.night_start(berlin(13, 0, 5)), berlin(13, 0, 10))


class ReservedJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        db = justwatch._connect(self.root)
        cols = 'id,kind,title,path,series_id,season,episode,year,duration,rating,genre,summary,poster,imdb_id,imdb_score,imdb_votes,playable,web_url,seen,updated'
        with db:
            for item_id, title, playable in (('tm1', 'Bad Lieutenant', 0), ('tm2', 'An Honest Liar', 1)):
                db.execute('INSERT INTO justwatch_items(%s) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)' % cols,
                           (item_id, 'movie', title, '/de/Film/x' + item_id, '', None, None, 2009, 7200, '16', 'Drama', '', '', '', None, None,
                            playable, 'https://www.justwatch.com/de/Film/x?package=jwt', 1, 1))
            db.execute("UPDATE justwatch_items SET night=1 WHERE id='tm1'")   # 0.5.52: real time window
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_without_stream_is_reserved_for_the_night(self):
        now = berlin(12, 17, 25)
        job = justwatch_downloads.build_job(self.root, self.root / 'media', 'tm1', now, released=lambda row: False)
        self.assertEqual(job['not_before'], berlin(13, 0, 10))
        self.assertTrue(job['night']); self.assertIn('Jugendschutz', job['note'])
        free = justwatch_downloads.build_job(self.root, self.root / 'media', 'tm2', now)
        self.assertNotIn('not_before', free); self.assertNotIn('night', free)

    def test_reserved_job_does_not_block_the_queue(self):
        c = jobs_db(); now = berlin(12, 17, 25)
        for job in ({'id': 'a', 'not_before': berlin(13, 0, 10)}, {'id': 'b'}):
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (job['id'], json.dumps(job), 'queued'))
        self.assertEqual(job_queue.next_job(c, now)['id'], 'b')
        c.execute("UPDATE jobs SET state='done' WHERE id='b'")
        self.assertIsNone(job_queue.next_job(c, now))
        self.assertEqual(job_queue.next_job(c, berlin(13, 0, 11))['id'], 'a')

    def test_listing_shows_the_start_time_only_while_waiting(self):
        c = jobs_db(); now = berlin(12, 17, 25)
        job = {'id': 'a', 'origin': 'justwatch', 'justwatch_id': 'tm1', 'target': '/t/a.mkv', 'not_before': berlin(13, 0, 10)}
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('a', json.dumps(job), 'queued'))
        self.assertEqual(netzkino_downloads.listing(c, item_id='tm1', origin='justwatch', now=now)['items'][0]['not_before'], berlin(13, 0, 10))
        self.assertIsNone(netzkino_downloads.listing(c, item_id='tm1', origin='justwatch', now=berlin(13, 1, 0))['items'][0]['not_before'])


class WiringTests(unittest.TestCase):
    def test_ui_and_worker(self):
        web = ROOT / 'web'
        button = (web / 'offline_button.js').read_text(encoding='utf-8')
        self.assertIn('Heute Nacht offline speichern', button)
        self.assertIn('Vorgemerkt für', button)
        self.assertIn('nightOffline: true', (web / 'justwatch.js').read_text(encoding='utf-8'))
        self.assertIn('{night,alternatives}', (web / 'unified_catalog.js').read_text(encoding='utf-8'))
        self.assertIn('Geplant für', (web / 'app.js').read_text(encoding='utf-8'))
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('job_queue.next_job(c)', server)
        self.assertIn('justwatch.night_start()', server)


if __name__ == '__main__':
    unittest.main()
