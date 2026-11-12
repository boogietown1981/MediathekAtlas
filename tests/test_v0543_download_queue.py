"""0.5.43: failed downloads can be removed, one card per file, retry keeps the job."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import job_queue  # noqa: E402


def db(*jobs):
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
    for jid, state, target in jobs:
        c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'id': jid, 'target': target, 'state': state}), state))
    return c


def ids(c):
    return [r[0] for r in c.execute('SELECT id FROM jobs ORDER BY rowid')]


class QueueTests(unittest.TestCase):
    def test_dedupe_keeps_newest_and_successful(self):
        c = db(('old', 'interrupted', '/w.mkv'), ('new', 'error', '/w.mkv'),     # Björn: 006 am Wolfgangsee twice
               ('a1', 'error', '/a.mkv'), ('a2', 'done', '/a.mkv'),
               ('solo', 'error', '/s.mkv'), ('q', 'queued', '/q.mkv'))
        self.assertEqual(job_queue.dedupe(c), 2)
        self.assertEqual(ids(c), ['new', 'a2', 'solo', 'q'])

    def test_retry_reuses_job_and_drops_twins(self):
        c = db(('x1', 'cancelled', '/x.mkv'), ('x2', 'error', '/x.mkv'))
        job = job_queue.retry(c, 'x2')
        self.assertEqual(job['id'], 'x2')
        self.assertEqual(ids(c), ['x2'])
        self.assertEqual(c.execute("SELECT state FROM jobs WHERE id='x2'").fetchone()[0], 'queued')
        with self.assertRaises(ValueError):
            job_queue.retry(c, 'x2')      # already queued

    def test_remove_only_unsuccessful(self):
        c = db(('e', 'error', '/e.mkv'), ('d', 'done', '/d.mkv'), ('r', 'downloading', '/r.mkv'))
        job_queue.remove(c, 'e')
        for jid in ('d', 'r', 'missing'):
            with self.assertRaises(ValueError):
                job_queue.remove(c, jid)
        self.assertEqual(ids(c), ['d', 'r'])

    def test_new_portal_order_replaces_failed_one(self):
        import netzkino_downloads as nd, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / 'Filme' / 'X (2000)' / 'X - (2000).mkv')
            c = db(('old', 'error', target))
            res = nd.insert(c, {'id': 'new', 'target': target, 'state': 'queued', 'origin': 'pluto', 'pluto_id': 'p1'})
            self.assertTrue(res['created'])
            self.assertEqual(ids(c), ['new'])

    def test_wiring_and_ad_tolerance(self):
        server = (ROOT / 'server.py').read_text()
        self.assertIn("'/api/job-remove'", server)
        self.assertIn('job_queue.dedupe(c)', server)
        self.assertIn("job_queue.retry(c,", server)
        self.assertIn("api('job-remove'", (ROOT / 'web' / 'app.js').read_text())
        self.assertIn("originalContentDuration') or node.get('duration')", (ROOT / 'pluto.py').read_text())
        import inspect, downloads
        self.assertEqual(inspect.signature(downloads.fetch_hls).parameters['min_share'].default, .85)


if __name__ == '__main__':
    unittest.main()
