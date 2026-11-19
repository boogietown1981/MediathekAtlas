"""0.6.28: Korrekturen aus Björns Diagnose von 0.6.26 (19.11.2026, Mac mit externen Laufwerken).

* YouTube-Abos: Auf /Volumes/Docking (Laufwerk ohne Hardlinks, z. B. exFAT) scheiterte jeder fertige
  Download beim Veröffentlichen mit „[Errno 45] Operation not supported“ (os.link). Jetzt weicht
  core.publish_exclusive auf Reservieren + Umbenennen aus, ohne je eine Datei zu überschreiben;
  die gescheiterten Aufträge werden einmal neu eingereiht.
* YouTube-Katalog: Eine einzelne abgebrochene Verbindung ließ eine Quelle für 24 h ausfallen und die
  Anzeige fiel von 4.265 auf 1.936 Titel, obwohl die Titel sichtbar blieben. Jetzt Wiederholung bei
  Netzfehlern, Zähler aus den sichtbaren Titeln und neuer Versuch nach 2 h."""
import errno
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import core, portal_enrichment as engine, youtube as yt, youtube_abos as ab  # noqa: E402
from test_v0553_youtube import Fixture, NOW  # noqa: E402


def no_hardlinks(src, dst):
    raise OSError(errno.ENOTSUP, 'Operation not supported', str(src), None, str(dst))


class PublishTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_hardlink_when_available(self):
        a, b = self.dir / 'a.partial', self.dir / 'b.nfo'
        a.write_text('x')
        self.assertEqual(core.publish_exclusive(a, b), 'link')
        self.assertEqual(b.read_text(), 'x')

    def test_rename_fallback_on_volume_without_hardlinks(self):
        a, b = self.dir / 'a.partial', self.dir / 'b.nfo'
        a.write_text('inhalt')
        with mock.patch('os.link', no_hardlinks):
            self.assertEqual(core.publish_exclusive(a, b), 'rename')
        self.assertEqual(b.read_text(), 'inhalt')
        self.assertFalse(a.exists())

    def test_never_overwrites(self):
        a, b = self.dir / 'a.partial', self.dir / 'b.nfo'
        a.write_text('neu')
        b.write_text('alt')
        for patch in (mock.patch('os.link', no_hardlinks), mock.patch('os.link', os.link)):
            with patch, self.assertRaises(FileExistsError):
                core.publish_exclusive(a, b)
            self.assertEqual(b.read_text(), 'alt')
            self.assertEqual(a.read_text(), 'neu')

    def test_missing_source_keeps_original_error(self):
        with mock.patch('os.link', no_hardlinks), self.assertRaises(OSError) as ctx:
            core.publish_exclusive(self.dir / 'fehlt', self.dir / 'ziel')
        self.assertEqual(ctx.exception.errno, errno.ENOTSUP)
        self.assertFalse((self.dir / 'ziel').exists())

    def test_downloads_and_artwork_use_the_helper(self):
        for name in ('downloads.py', 'artwork.py'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('core.publish_exclusive(', text, name)
            self.assertNotIn('os.link(', text, name)


class RequeueTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def test_errno45_jobs_come_back_once(self):
        err = ("[Errno 45] Operation not supported: '/Volumes/Docking/MediathekAtlas/Zwischenspeicher/YouTube-Abos/"
               "YouTube-Abos/Breaking Lab/.mediathekatlas-k78zzdxv.partial/video.nfo.partial' -> '…nfo'")
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', ('x', json.dumps({'id': 'x', 'origin': 'youtube', 'error': err}), 'error'))
        self.assertEqual(ab.requeue_on_start(self.c, now=1000), 1)
        payload, state = self.c.execute("SELECT payload,state FROM jobs WHERE id='x'").fetchone()
        job = json.loads(payload)
        self.assertEqual(state, 'queued')
        self.assertTrue(job['requeued_0628'])
        job['error'] = err
        self.c.execute("UPDATE jobs SET payload=?,state='error' WHERE id='x'", (json.dumps(job),))
        self.assertEqual(ab.requeue_on_start(self.c, now=2000), 0)


class FlakyApi:
    """Wraps the synthetic API: the first n calls of one endpoint fail like a reset connection."""

    def __init__(self, api, endpoint, failures):
        self.api, self.endpoint, self.left = api, endpoint, failures

    def __call__(self, endpoint, query):
        if endpoint == self.endpoint and self.left:
            self.left -= 1
            raise urllib.error.URLError(ConnectionResetError(54, 'Connection reset by peer'))
        return self.api(endpoint, query)


class RequestRetryTests(unittest.TestCase):
    def test_transient_errors_are_retried(self):
        answers = [ConnectionResetError(54, 'reset'), urllib.error.URLError(TimeoutError('timed out')), b'{"items": []}']

        class Resp:
            def __init__(self, raw):
                self.raw = raw

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return self.raw

        def urlopen(req, timeout):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return Resp(a)

        waits = []
        with mock.patch('urllib.request.urlopen', urlopen), mock.patch.object(yt, '_SLEEP', waits.append):
            self.assertEqual(yt._request('videos', {'id': 'x'}, 'KEY'), {'items': []})
        self.assertEqual(waits, list(yt.RETRY_WAITS[:2]))

    def test_gives_up_after_retries(self):
        calls = []

        def urlopen(req, timeout):
            calls.append(1)
            raise ConnectionResetError(54, 'reset')

        with mock.patch('urllib.request.urlopen', urlopen), mock.patch.object(yt, '_SLEEP', lambda s: None):
            with self.assertRaises(ConnectionResetError):
                yt._request('videos', {'id': 'x'}, 'KEY')
        self.assertEqual(len(calls), len(yt.RETRY_WAITS) + 1)

    def test_api_errors_are_not_retried(self):
        calls = []

        def urlopen(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)

        with mock.patch('urllib.request.urlopen', urlopen), mock.patch.object(yt, '_SLEEP', lambda s: None):
            with self.assertRaises(yt.ApiError):
                yt._request('videos', {'id': 'x'}, 'KEY')
        self.assertEqual(len(calls), 1)


class PartialSyncTests(Fixture):
    def test_counts_and_next_attempt_after_network_failure(self):
        full = self.sync()
        self.assertGreater(full['movies'], 0)
        # second run: the film channel's list breaks off (as on 19.11.), the series still loads
        flaky = FlakyApi(self.api, 'playlistItems', 1)
        result = yt.sync(self.root, request=flaky, now=NOW + 86400, gap=0)
        self.assertTrue(result['ok'] and result['partial'], result)
        st = yt.state(self.root)
        self.assertEqual(st['movies'], full['movies'])                  # still listed, so still counted
        self.assertEqual(st['episodes'], full['episodes'])
        self.assertEqual(len(yt.listing(self.root, 'movie', limit='all')['items']), st['movies'])
        self.assertEqual(st['next_attempt'], NOW + 86400 + yt.RETRY_PARTIAL)
        self.assertIn('1 von 2 Quellen', st['last_error'])
        # the next complete run counts normally and returns to the daily rhythm
        result = yt.sync(self.root, request=self.api, now=NOW + 2 * 86400, gap=0)
        self.assertFalse(result['partial'])
        self.assertEqual(yt.state(self.root)['next_attempt'], NOW + 3 * 86400)


class MetricsTests(unittest.TestCase):
    """„3.894 von 3.075 geprüft“ (Joyn): only reports of titles listed now count."""

    def test_only_listed_titles_count(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'p.db'

        def connect(root):
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, kind TEXT, seen REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)')
            return db
        spec = engine.Spec(name='Test', key='test', items='items', checks='checks', connect=connect,
                           valid_id=lambda v: True,
                           last_success=lambda db: (db.execute("SELECT v FROM meta WHERE k='last'").fetchone() or ['0'])[0])
        db = engine._conn(spec, None)
        with db:
            db.execute("INSERT INTO meta VALUES('last','100')")
            db.executemany('INSERT INTO items VALUES(?,?,?)', [('a', 'movie', 100), ('b', 'series', 100), ('c', 'movie', 100),
                                                               ('gone', 'movie', 50), ('ep', 'episode', 100)])
            for item, status in (('a', 'candidate'), ('b', 'no_match'), ('gone', 'candidate'), ('ep', 'candidate'), ('lost', 'review')):
                db.execute('INSERT INTO checks VALUES(?,?,?,?)', (item, 1, '', json.dumps({'status': status})))
        db.close()
        m = engine.metrics(spec, None)
        self.assertEqual(m, {'checked': 2, 'by_status': {'candidate': 1, 'no_match': 1}, 'listed': 3})

    def test_overview_uses_listed_titles(self):
        js = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn('ref.listed', js)
        self.assertIn("num(pool)+' geprüft", js)


if __name__ == '__main__':
    unittest.main()
