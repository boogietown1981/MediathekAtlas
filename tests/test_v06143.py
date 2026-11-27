"""0.6.143 (Diagnose MacBook Air M1 8 GB, 26.11.2026, mobil): IMDb-Update ohne Platz nicht starten, Filmliste nach
Abbruch fortsetzen, wachsende Wartezeit ohne Netz, filmfriend hält bei Netzverlust an, Diagnose mit Arbeitsspeicher/
Auslagerung/Rosetta, Startskript bevorzugt arm64-Python."""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
import filmfriend  # noqa: E402
import filmlist  # noqa: E402
import imdb_archive  # noqa: E402
import system_monitor  # noqa: E402

GB = 1000 ** 3


class Temp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class ImdbSpaceGate(Temp):
    def archive(self):
        a = imdb_archive.Archive(self.root, threading.Event())
        c = sqlite3.connect(a.path)
        with c:
            c.execute('CREATE TABLE snapshot(updated)');c.execute('INSERT INTO snapshot VALUES(1)')
        c.close()
        a.updated, a.version = 1, imdb_archive.VERSION
        return a

    def test_update_waits_without_download_and_keeps_staged_files(self):
        a = self.archive()
        staged = a.root / 'basics.tsv.gz';staged.write_bytes(b'x' * 1000)
        events = []
        with mock.patch.object(imdb_archive, 'update_space', return_value=24 * GB), \
             mock.patch.object(imdb_archive, '_free_bytes', return_value=14 * GB), \
             mock.patch.object(a, 'fetch', side_effect=AssertionError('kein Download')), \
             mock.patch.object(imdb_archive.diagnostics, 'event', side_effect=lambda n, **k: events.append(n)):
            self.assertFalse(a.update())
            self.assertFalse(a.update())
            st = a.status()
        self.assertEqual(st['phase'], 'waiting_space');self.assertTrue(st['space_short']);self.assertTrue(st['ready'])
        self.assertEqual(a.failures, 0)                         # kein Fehler, kein Back-off bis 24 h
        self.assertGreater(a.retry_at, 0);self.assertFalse(a.due(a.retry_at - 1))
        self.assertEqual(events, ['imdb_archive_waiting_space'])   # einmal, nicht alle 15 min
        self.assertTrue(staged.exists())

    def test_staged_downloads_count_and_enough_space_starts(self):
        a = self.archive()
        (a.root / 'basics.tsv.gz').write_bytes(b'x' * 2000)
        a.state = {'phase': 'waiting_space', 'need_bytes': 1}
        with mock.patch.object(imdb_archive, 'update_space', return_value=10000), \
             mock.patch.object(imdb_archive, '_free_bytes', return_value=8500):
            self.assertIsNone(a.space_gate())               # 8.500 frei + 2.000 schon geladen
            with mock.patch.object(a, 'fetch', side_effect=InterruptedError('stop')):
                a.update()
        self.assertNotIn('need_bytes', a.state)

    def test_space_error_keeps_finished_downloads(self):
        a = self.archive()
        done = a.root / 'basics.tsv.gz';done.write_bytes(b'x')
        with mock.patch.object(a, 'space_gate', return_value=None), \
             mock.patch.object(a, 'fetch', side_effect=OSError('IMDb: zu wenig freier Speicher')):
            a.update()
        self.assertTrue(done.exists());self.assertEqual(a.failures, 1)

    def test_ui_names_the_phase(self):
        self.assertIn("waiting_space:'Wartet auf Speicherplatz", (ROOT / 'web' / 'app.js').read_text(encoding='utf-8'))


class Response:
    def __init__(self, body, status=200, length=None, etag='"v1"', ctype='application/x-xz'):
        self.body, self.status = io.BytesIO(body), status
        self.headers = {'Content-Length': str(len(body) if length is None else length), 'Content-Type': ctype}
        if etag:
            self.headers['ETag'] = etag

    def read1(self, n):
        return self.body.read(min(n, 4096))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


DATA = filmlist.XZ_MAGIC + bytes(range(256)) * 100


class FilmlistResume(Temp):
    def test_truncated_download_is_kept_and_resumed_with_range(self):
        calls = []

        def opener(url, headers=None):
            calls.append(dict(headers or {}))
            if len(calls) == 1:
                return Response(DATA[:7881], length=len(DATA))
            return Response(DATA[7881:], status=206)
        with mock.patch.object(filmlist.core, 'open_url', side_effect=opener):
            with self.assertRaises(filmlist.Truncated) as err:
                filmlist._download(self.root, lambda **k: None, lambda: False)
            self.assertTrue(filmlist.network_error(err.exception))
            self.assertEqual((self.root / 'filmliste.part').stat().st_size, 7881)
            path = filmlist._download(self.root, lambda **k: None, lambda: False)
        self.assertEqual(path.read_bytes(), DATA)
        self.assertEqual(calls[1], {'Range': 'bytes=7881-', 'If-Range': '"v1"'})
        self.assertFalse((self.root / 'filmliste.part').exists());self.assertFalse((self.root / 'filmliste.part.tag').exists())

    def test_changed_file_restarts_from_zero(self):
        (self.root / 'filmliste.part').write_bytes(b'alt' * 10);(self.root / 'filmliste.part.tag').write_text('"v0"')
        with mock.patch.object(filmlist.core, 'open_url', return_value=Response(DATA, status=200, etag='"v2"')):
            path = filmlist._download(self.root, lambda **k: None, lambda: False)
        self.assertEqual(path.read_bytes(), DATA)

    def test_hotspot_page_is_not_a_filmlist_and_not_kept(self):
        page = b'<html>Bitte anmelden</html>' * 10
        with mock.patch.object(filmlist.core, 'open_url', return_value=Response(page, ctype='text/html')):
            with self.assertRaises(ValueError) as err:
                filmlist._download(self.root, lambda **k: None, lambda: False)
        self.assertIn('Hotspot', str(err.exception));self.assertFalse((self.root / 'filmliste.part').exists())

    def test_http_error_drops_part(self):
        (self.root / 'filmliste.part').write_bytes(b'x' * 10);(self.root / 'filmliste.part.tag').write_text('"v1"')
        error = urllib.error.HTTPError(filmlist.URL, 416, 'Range Not Satisfiable', {}, None)
        with mock.patch.object(filmlist.core, 'open_url', side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                filmlist._download(self.root, lambda **k: None, lambda: False)
        self.assertFalse((self.root / 'filmliste.part').exists())

    def test_network_backoff_grows_and_resets(self):
        svc = catalog_service.Service.__new__(catalog_service.Service)
        net = urllib.error.URLError('nodename nor servname provided')
        self.assertEqual([svc.feed_retry_delay(net) for _ in range(4)], [600, 1800, 3600, 3600])
        self.assertEqual(svc.feed_retry_delay(ValueError('Leere Filmliste')), 300)
        self.assertEqual(svc.feed_retry_delay(net), 600)
        self.assertFalse(filmlist.network_error(urllib.error.HTTPError('u', 404, 'x', {}, None)))


class FilmfriendNetStop(Temp):
    def test_stops_after_three_network_failures(self):
        calls = []

        def opener(url, headers):
            calls.append(url)
            raise urllib.error.URLError('Network is unreachable')
        crawl = filmfriend.Crawl(opener, 0)
        for _ in range(6):
            with self.assertRaises(OSError):
                crawl.get('/x')
        self.assertTrue(crawl.stopped);self.assertTrue(crawl.truncated)
        self.assertEqual((crawl.net_failures, len(calls)), (3, 3))   # danach keine Anfrage mehr
        # Suche und Details brechen sofort ab statt Hunderte Fehler zu sammeln
        crawl.entries = {i: {'id': i, 'kind': 'movie', 'path': 'p%d' % i} for i in range(50)}
        crawl.tenant = 't';crawl.add_details({}, 10 ** 9)
        self.assertEqual(len(crawl.errors), 0);self.assertEqual(len(calls), 3)


class Diagnosis(Temp):
    def test_swapusage_parser(self):
        self.assertEqual(system_monitor._swapusage('total = 2048.00M  used = 1024.50M  free = 1023.50M  (encrypted)'),
                         (2048 * 1024 ** 2, int(1024.5 * 1024 ** 2)))
        self.assertEqual(system_monitor._swapusage('kaputt'), (None, None))

    def test_machine_details_and_zip(self):
        details = system_monitor.machine_details()
        for key in ('memory_total', 'memory_available', 'swap_total', 'swap_used', 'process_memory', 'rosetta', 'hints'):
            self.assertIn(key, details)
        with mock.patch.object(diagnostics, '_root', self.root):
            (self.root / 'catalog.db').write_bytes(b'x' * 100)
            data = diagnostics.export({})
        status = json.loads(zipfile.ZipFile(io.BytesIO(data)).read('status.json'))
        self.assertIn('machine_details', status);self.assertEqual(status['databases']['total_bytes'], 100)

    def test_rosetta_hint_on_mac(self):
        values = {'kern.memorystatus_level': '23', 'sysctl.proc_translated': '1', 'hw.optional.arm64': '1', 'vm.swapusage': None}
        with mock.patch.object(system_monitor.sys, 'platform', 'darwin'), \
             mock.patch.object(system_monitor, '_sysctl', side_effect=values.get), \
             mock.patch.object(system_monitor, 'memory', return_value=(8 * 1024 ** 3, 1024 ** 3)), \
             mock.patch.object(system_monitor, 'swap', return_value=(4 * 1024 ** 3, 3 * 1024 ** 3)):
            d = system_monitor.machine_details()
        self.assertTrue(d['rosetta']);self.assertTrue(d['apple_silicon']);self.assertEqual(d['memory_free_percent'], 23)
        self.assertEqual(len(d['hints']), 2)


@unittest.skipIf(os.name == 'nt', 'bash launcher')
class Launcher(unittest.TestCase):
    def test_arm64_first_and_rosetta_fallback(self):
        text = (ROOT / 'launcher.sh').read_text(encoding='utf-8')
        self.assertIn('hw.optional.arm64', text);self.assertIn('/usr/bin/arch -arm64', text)
        self.assertIn('try_python "$candidate" arm64', text)
        # nach der Auswahl laufen alle Aufrufe über PYCMD (mit arch-Präfix)
        after = text[text.index('Ausgewähltes Python'):]
        self.assertNotRegex(after, r'(?<!=)"\$FOUND_PYTHON" ')
        r = subprocess.run(['bash', '-n', str(ROOT / 'launcher.sh')], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
