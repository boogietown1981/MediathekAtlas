"""0.6.19: Korrekturen aus Björns Diagnose von 0.6.18 (16.11.2026, MacBook Air).

* ServusTV: Der Lauf von 11:35 wurde vom Neustart unterbrochen; 0.6.18 wartete bis zum nächsten Tag,
  der neue Abruf aus 0.6.16 lief also nie. Unterbrochene Katalogläufe starten jetzt sofort neu.
* YouTube-Abos: Nach der Bot-Sperre scheiterten alle 18 Versuche mit „This video is not available“
  (dauerhafter Fehler), dazu 20 Aufträge an zu wenig Speicher, jeder dauerhaft. Beides wartet jetzt
  und wird automatisch wiederholt; die alten Fehler werden einmal neu eingereiht."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import download_retry as dr, downloads, provider_base, servustv, youtube_downloads as yd, youtube_abos as ab  # noqa: E402

GONE = "ERROR: [youtube] ERaHJ84OlEM: This video is not available"


def job(**extra):
    return {'id': 'j1', 'origin': 'youtube', 'state': 'downloading', 'source': {'_resolver': 'youtube'}, **extra}


class InterruptedCatalogueTests(unittest.TestCase):
    def test_interrupted_run_starts_again(self):
        module = types.SimpleNamespace(_connect=None)
        with mock.patch('portal_reference.retry_after_update', lambda root, m, c: False):
            current = {'last_attempt': 5, 'last_success': 4, 'auto': True, 'next_attempt': 9e9, 'last_result': 'interrupted'}
            self.assertTrue(provider_base.catalog_due('/r', module, current, now=10))
            self.assertTrue(provider_base.catalog_due('/r', module, {**current, 'auto': False}, now=10))
            self.assertFalse(provider_base.catalog_due('/r', module, {**current, 'last_result': 'partial'}, now=10))
            self.assertFalse(provider_base.catalog_due('/r', module, {**current, 'running': True}, now=10))

    def test_servustv_left_running_by_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = servustv._connect(tmp)
            with db:
                for key, value in [('last_attempt', 100), ('last_success', 50), ('last_result', 'running'),
                                   ('next_attempt', time.time() + 86400), ('auto', '1')]:
                    servustv._set(db, key, value)
            db.close()
            current = servustv.state(tmp)
            self.assertEqual(current['last_result'], 'interrupted')
            self.assertTrue(servustv.should_sync(tmp))


class NotAvailableTests(unittest.TestCase):
    def setUp(self):
        dr.clear()
        self.addCleanup(dr.clear)

    def test_not_available_is_retried(self):
        message, retry, block = yd._failure(GONE)
        self.assertEqual((retry, block), (True, False))
        self.assertIn('nicht heraus', message)
        self.assertEqual(yd._failure('ERROR: [youtube] x: Video unavailable')[1:], (False, False))
        self.assertEqual(yd._failure('ERROR: [youtube] x: Private video')[1:], (False, False))


class NoSpaceTests(unittest.TestCase):
    def setUp(self):
        dr.clear()
        self.addCleanup(dr.clear)

    def test_require_space_raises_a_retry_for_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dr.NoSpace) as caught:
                downloads.require_space(tmp, 1 << 60)
            self.assertIsInstance(caught.exception, ValueError)         # old callers still catch it
            self.assertIn('Zu wenig freier Speicher', str(caught.exception))

    def test_low_disk_pauses_every_source(self):
        now = time.time()
        first = job()
        self.assertTrue(dr.reschedule(first, dr.NoSpace('Zu wenig freier Speicher am Downloadziel'), now=now, rand=lambda: .5))
        self.assertEqual((first['state'], first['retries']), ('queued', 1))
        self.assertAlmostEqual(first['not_before'] - now, dr.BACKOFF_BLOCK[0])
        other = {'id': 'x', 'origin': 'pluto', 'source': {'_resolver': 'pluto'}}
        self.assertTrue(dr.hold(other, now=now + 60))                    # andere Quelle wartet ebenfalls
        self.assertIn('Speicher', other['note'])
        self.assertFalse(dr.hold({'id': 'y', 'source': {'_resolver': 'pluto'}}, now=first['not_before'] + 1))
        self.assertFalse(dr.hold(job(id='z', force_now=True), now=now + 60))   # „Jetzt versuchen“


class RequeueTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def put(self, jid, state, **extra):
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'id': jid, 'origin': 'youtube', **extra}), state))

    def test_old_permanent_errors_come_back_once(self):
        self.put('na', 'error', retries=1, error='yt-dlp meldet einen Fehler: ' + GONE)
        self.put('disk', 'error', error='Zu wenig freier Speicher am Downloadziel: 2.0 GiB frei, mindestens 2.0 GiB benötigt')
        self.put('gone', 'error', error='Video nicht mehr verfügbar')
        self.assertEqual(ab.requeue_on_start(self.c, now=1000), 2)
        states = dict(self.c.execute('SELECT id,state FROM jobs'))
        self.assertEqual(states, {'na': 'queued', 'disk': 'queued', 'gone': 'error'})
        na = json.loads(self.c.execute("SELECT payload FROM jobs WHERE id='na'").fetchone()[0])
        self.assertTrue(na['requeued_0619'])
        self.assertGreaterEqual(na['not_before'], 1000 + dr.BACKOFF[0])
        # failing again after the requeue: stays an error at the next start
        na.update(error='yt-dlp meldet einen Fehler: ' + GONE)
        self.c.execute("UPDATE jobs SET payload=?,state='error' WHERE id='na'", (json.dumps(na),))
        self.c.execute("UPDATE jobs SET state='done' WHERE id='disk'")
        self.assertEqual(ab.requeue_on_start(self.c, now=2000), 0)


if __name__ == '__main__':
    unittest.main()
