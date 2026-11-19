"""0.6.36 (Björn, 19.11.2026): "Anna und die wilden Tiere" lädt nicht.

Kindervideos ("Made for Kids") liefert YouTube dem yt-dlp-Client "visionos" nicht; ohne JavaScript-Laufzeit
hat yt-dlp keinen anderen Client und meldet "This video is not available". MediathekAtlas richtet jetzt
Deno ein (offizielle Version, Prüfsumme), übergibt es mit --js-runtimes und reiht die gescheiterten
Aufträge einmal neu ein."""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import youtube_abos as ab  # noqa: E402
import youtube_downloads as yd  # noqa: E402

NA = 'YouTube gibt das Video gerade nicht heraus („This video is not available“, oft nach der Bot-Sperre) (nach 7 automatischen Versuchen aufgegeben)'


def deno_zip(name='deno'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(name, b'#!/bin/sh\necho deno\n')
    return buf.getvalue()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        yd._VERSIONS.clear()

    def no_system(self):
        return mock.patch.multiple(yd, JS_DIRS=()), mock.patch('shutil.which', return_value=None)

    def test_managed_deno_first_and_args_only_for_new_ytdlp(self):
        a, b = self.no_system()
        with a, b:
            self.assertIsNone(yd.find_js_runtime(self.root))
            target = yd._deno_managed(self.root)
            target.parent.mkdir(parents=True)
            target.write_bytes(b'x')
            self.assertEqual(yd.find_js_runtime(self.root), ('deno', str(target)))
            new, old = (['/x/yt-dlp'], 'installiert'), (['/y/yt-dlp'], 'installiert')
            with mock.patch.object(yd, 'tool_version', side_effect=lambda argv: (2026, 11, 6) if argv[0] == '/x/yt-dlp' else (2025, 6, 30)):
                self.assertEqual(yd.js_args(self.root, new), ['--js-runtimes', 'deno:' + str(target), '--remote-components', 'ejs:github'])
                self.assertEqual(yd.js_args(self.root, old), [])     # old yt-dlp would stop at the unknown option

    def test_version_is_read_once(self):
        tool = self.root / 'yt-dlp'
        tool.write_text('#!/bin/sh\necho 2026.11.06\n')
        tool.chmod(0o755)
        with mock.patch('subprocess.run', wraps=__import__('subprocess').run) as run:
            self.assertEqual(yd.tool_version([str(tool)]), (2026, 11, 6))
            self.assertEqual(yd.tool_version([str(tool)]), (2026, 11, 6))
            self.assertEqual(run.call_count, 1)

    def test_old_system_ytdlp_gives_way_to_own_copy(self):
        own = yd._managed(self.root)
        own.parent.mkdir(parents=True)
        own.write_bytes(b'x')
        with mock.patch('shutil.which', return_value='/opt/homebrew/bin/yt-dlp'), mock.patch.dict('os.environ', {'MEDIATHEKATLAS_YTDLP': ''}), \
                mock.patch.object(yd, 'tool_version', return_value=(2025, 1, 1)):
            self.assertEqual(yd.find_tool(self.root)[1], 'von MediathekAtlas eingerichtet')
        with mock.patch('shutil.which', return_value='/opt/homebrew/bin/yt-dlp'), mock.patch.dict('os.environ', {'MEDIATHEKATLAS_YTDLP': ''}), \
                mock.patch.object(yd, 'tool_version', return_value=(2026, 11, 6)):
            self.assertTrue(yd.find_tool(self.root)[1].startswith('installiert'))

    def test_install_deno_checks_checksum(self):
        data = deno_zip('deno.exe' if os.name == 'nt' else 'deno')
        with mock.patch.object(yd, '_deno_asset', return_value='deno-aarch64-apple-darwin.zip'):
            files = {yd.DENO_RELEASE + 'deno-aarch64-apple-darwin.zip.sha256sum': ('%s  deno-aarch64-apple-darwin.zip\n' % hashlib.sha256(data).hexdigest()).encode(),
                     yd.DENO_RELEASE + 'deno-aarch64-apple-darwin.zip': data}
            yd.install_js_runtime(self.root, fetch=files.__getitem__)
            target = yd._deno_managed(self.root)
            self.assertTrue(target.is_file())
            self.assertTrue(os.access(target, os.X_OK))
            target.unlink()
            files[yd.DENO_RELEASE + 'deno-aarch64-apple-darwin.zip'] = b'tampered'
            with self.assertRaisesRegex(ValueError, 'Prüfsumme'):
                yd.install_js_runtime(self.root, fetch=files.__getitem__)
            self.assertFalse(target.exists())

    def test_assets(self):
        for machine, system, asset in (('arm64', 'Darwin', 'deno-aarch64-apple-darwin.zip'), ('x86_64', 'Darwin', 'deno-x86_64-apple-darwin.zip'),
                                       ('aarch64', 'Linux', 'deno-aarch64-unknown-linux-gnu.zip'), ('AMD64', 'Windows', 'deno-x86_64-pc-windows-msvc.zip'),
                                       ('armv7l', 'Linux', '')):
            with mock.patch('platform.machine', return_value=machine), mock.patch('platform.system', return_value=system):
                self.assertEqual(yd._deno_asset(), asset)

    def test_install_tool_reports_deno_failure_without_failing(self):
        with mock.patch.object(yd, 'find_tool', return_value=(['/x/yt-dlp'], 'installiert (/x/yt-dlp)')), \
                mock.patch.object(yd, '_js_ok', return_value=True), mock.patch.object(yd, 'find_js_runtime', return_value=None), \
                mock.patch.object(yd, 'install_js_runtime', side_effect=ValueError('kein Netz')), mock.patch.object(yd, '_install_ytdlp') as ytdlp:
            st = yd.install_tool(self.root)
        ytdlp.assert_not_called()             # a current system yt-dlp is left alone
        self.assertIn('Deno konnte nicht eingerichtet werden', st['js_error'])
        self.assertIn('Kindervideos', st['tool_hint'])

    def test_failure_text_names_deno_and_keeps_marker(self):
        reason, temporary, _ = yd._failure('ERROR: [youtube] abc: This video is not available')
        self.assertTrue(temporary)
        self.assertIn('Deno', reason)
        self.assertIn(ab.NOT_AVAILABLE, reason)


class RequeueTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def put(self, jid, state, **extra):
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', (jid, json.dumps({'id': jid, 'origin': 'youtube', **extra}), state))

    def test_given_up_kids_videos_come_back_once_with_runtime(self):
        self.put('na', 'error', retries=7, error=NA, requeued_0619=True)
        self.put('gone', 'error', error='Video nicht mehr verfügbar')
        self.put('wait', 'queued', retries=3, last_error=NA)
        self.assertEqual(ab.requeue_on_start(self.c, now=1000), 0)          # no runtime: nothing changes
        self.assertEqual(ab.requeue_on_start(self.c, now=1000, js_ready=True), 1)
        job = json.loads(self.c.execute("SELECT payload FROM jobs WHERE id='na'").fetchone()[0])
        self.assertEqual((job['state'], job['retries'], job['not_before']), ('queued', 0, 1060))
        self.assertTrue(job['requeued_0636'])
        self.assertIn('Deno', job['note'])
        # once only
        self.c.execute("UPDATE jobs SET state='error', payload=json_set(payload,'$.error',?) WHERE id='na'", (NA,))
        self.assertEqual(ab.requeue_not_available(self.c, now=2000), 0)


class WiringTests(unittest.TestCase):
    def test_server_ui_and_both_ytdlp_calls(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('requeue_on_start(c,js_ready=js_ready)', server)
        self.assertIn('youtube_abos.requeue_not_available(c)', server)
        src = (ROOT / 'youtube_downloads.py').read_text(encoding='utf-8')
        self.assertEqual(src.count('*js_args(root, tool)'), 2)
        js = (ROOT / 'web' / 'youtube.js').read_text(encoding='utf-8')
        self.assertIn("'Deno einrichten'", js)
        self.assertIn('o.js_runtime', js)


if __name__ == '__main__':
    unittest.main()
