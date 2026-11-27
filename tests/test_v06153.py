"""0.6.153: Filmreihen-/Mehrteiler-Kacheln ab Werk aus (Mac-Prüfung 0.6.150 nicht bestanden) und Befunde der
Mac-Prüfung 0.6.151 (lokale Filmarchive): „sample.mkv“ als zweiter Film, kleine Dateien ohne Hinweis, Eingabefehler als ERROR."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lokal  # noqa: E402


class SkipNames(unittest.TestCase):
    def test_sample_and_trailer_files(self):
        for name in ('sample.mkv', 'Sample-2.mkv', 'trailer.mp4', 'Film-trailer.mp4', 'Film.sample.mkv', '._Film.mkv'):
            self.assertTrue(lokal.SKIP_FILE.search(name), name)
        for name in ('Trailer Park Boys S01E01.mkv', 'Samplers.mkv', 'Metropolis.mkv', 'Der Sampler (1999).mkv'):
            self.assertFalse(lokal.SKIP_FILE.search(name), name)


class Scan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'data';self.root.mkdir()
        self.share = Path(tmp.name) / 'share'
        (self.share / 'Metropolis (1927)').mkdir(parents=True)
        (self.share / 'Metropolis (1927)' / 'film.mp4').write_bytes(b'x' * 50)
        (self.share / 'Metropolis (1927)' / 'sample.mkv').write_bytes(b'x' * 50)
        (self.share / 'klein.mkv').write_bytes(b'x' * 5)
        patch = mock.patch.object(lokal, 'MIN_SIZE', 20);patch.start();self.addCleanup(patch.stop)

    def test_sample_skipped_small_counted_event_has_seconds(self):
        lokal.set_dirs(str(self.root), str(self.share))
        events = []
        with mock.patch('diagnostics.event', side_effect=lambda name, **kw: events.append((name, kw))):
            summary = lokal.scan(str(self.root), now=1.0)
        self.assertEqual((summary[0]['files'], summary[0]['small']), (1, 1))
        self.assertEqual([m['title'] for m in lokal.listing(str(self.root))['items']], ['Metropolis'])
        name, kw = events[-1]
        self.assertEqual(name, 'lokal_scan');self.assertIn('seconds', kw);self.assertEqual(kw['small'], 1)


class Wiring(unittest.TestCase):
    def test_input_errors_are_answers_and_tiles_off(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("except ValueError as e:return self.send({'error':str(e)},400)", server)
        self.assertIn("return self.send({'error':'Noch kein Archivordner eingetragen'},400)", server)
        self.assertIn('UNIFIED_REIHEN=', server)   # 0.6.154: wieder an (test_v06154)
        self.assertIn("kleine Videos unter 20 MB übergangen", (ROOT / 'web' / 'lokal_archive.js').read_text(encoding='utf-8'))


class RangeHelpers(unittest.TestCase):
    """Byte-Anfragen des Browsers an den umgewandelten Strom einer Datei ersetzen den Hauptstrom nicht (MKV-Befund)."""
    def setUp(self):
        import streaming
        self.streaming = streaming
        self.addCleanup(self.stop_all)

    def stop_all(self):
        with self.streaming._LOCK:
            procs = list(self.streaming._RUNNING.values());self.streaming._RUNNING.clear()
        for p in procs:
            self.streaming._stop(p)

    def test_helper_keeps_main_stream_and_has_own_limit(self):
        sleep = [sys.executable, '-c', 'import time;time.sleep(30)']
        main = self.streaming.start(list(sleep), 'sitzung')
        helpers = [self.streaming.start(list(sleep), 'sitzung', helper=True) for _ in range(self.streaming.MAX_RANGE_HELPERS)]
        self.assertIsNone(main.poll())
        self.assertTrue(all(h.poll() is None for h in helpers))
        with self.assertRaises(RuntimeError):
            self.streaming.start(list(sleep), 'sitzung', helper=True)
        again = self.streaming.start(list(sleep), 'sitzung')     # Spulen: neuer Hauptstrom ersetzt den alten
        main.wait(5)
        self.assertIsNotNone(main.poll());self.assertIsNone(again.poll())

    def test_server_answers_ranges_with_206(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("m=re.fullmatch(r'bytes=(\\d+)-',(self.headers.get('Range') or '').strip())", server)
        self.assertIn("self.send_response(206 if skip else 200)", server)
        self.assertIn("helper=bool(skip)", server)


if __name__ == '__main__':
    unittest.main()
