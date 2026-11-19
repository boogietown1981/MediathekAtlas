"""0.6.38: Chrome-Erweiterung einfacher installieren (entpackter Ordner, Erkennung, Selbst-Update)."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import browser_extension
from version import VERSION

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'web' / 'browser-extension' / 'chrome'
SERVER = (ROOT / 'server.py').read_text(encoding='utf-8')


class ProvideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_in_start_folder_with_every_file_and_version(self):
        info = browser_extension.provide('0.6.38', self.home)
        target = self.home / 'Chrome-Erweiterung' / 'MediathekAtlas-Videostart'
        self.assertEqual(info['path'], str(target))
        self.assertEqual(sorted(info['changed']), sorted(browser_extension.FILES))
        for name in browser_extension.FILES:
            self.assertTrue((target / name).is_file(), name)
        self.assertEqual(json.loads((target / 'manifest.json').read_text())['version'], '0.6.38')
        self.assertEqual((target / 'autostart.js').read_bytes(), (EXT / 'autostart.js').read_bytes())
        self.assertFalse(list(target.rglob('*.partial')))

    def test_unchanged_files_are_not_rewritten_and_update_changes_only_manifest(self):
        browser_extension.provide('0.6.38', self.home)
        target = browser_extension.install_dir(self.home)
        before = (target / 'autostart.js').stat().st_mtime_ns
        self.assertEqual(browser_extension.provide('0.6.38', self.home)['changed'], [])
        self.assertEqual(browser_extension.provide('0.6.39', self.home)['changed'], ['manifest.json'])
        self.assertEqual((target / 'autostart.js').stat().st_mtime_ns, before)

    def test_removes_stale_extension_files_but_never_foreign_ones(self):
        target = browser_extension.install_dir(self.home)
        target.mkdir(parents=True)
        (target / 'old_script.js').write_text('x')
        (target / 'notiz.txt').write_text('vom Nutzer')
        info = browser_extension.provide('0.6.38', self.home)
        self.assertFalse((target / 'old_script.js').exists())
        self.assertTrue((target / 'notiz.txt').exists())
        self.assertIn('-old_script.js', info['changed'])

    def test_status(self):
        st = browser_extension.status('0.6.38', self.home)
        self.assertEqual((st['version'], st['local'], st['ready']), ('0.6.38', True, False))
        browser_extension.provide('0.6.38', self.home)
        self.assertTrue(browser_extension.status('0.6.38', self.home)['ready'])
        self.assertFalse(browser_extension.status('0.6.40', self.home)['ready'])
        net = browser_extension.status('0.6.38', self.home, network=True)
        self.assertEqual((net['local'], net['path']), (False, ''))

    def test_reveal_per_system_and_without_file_manager(self):
        calls = []
        self.assertTrue(browser_extension.reveal('/a/b', runner=calls.append, platform='darwin'))
        self.assertTrue(browser_extension.reveal('C:\\a\\b', runner=calls.append, platform='win32'))
        self.assertTrue(browser_extension.reveal('/a/b', runner=calls.append, platform='linux'))
        self.assertEqual(calls, [['/usr/bin/open', '-R', '/a/b'], ['explorer', '/select,', 'C:\\a\\b'], ['xdg-open', '/a']])

        def missing(cmd):
            raise FileNotFoundError(cmd[0])
        self.assertFalse(browser_extension.reveal('/a/b', runner=missing, platform='linux'))


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))

    def test_manifest_version_background_and_bridge(self):
        self.assertEqual(self.manifest['version'], VERSION)
        self.assertEqual(self.manifest['background'], {'service_worker': 'background.js'})
        bridge = self.manifest['content_scripts'][1]
        self.assertEqual(bridge['matches'], ['http://127.0.0.1/*', 'http://localhost/*'])
        self.assertEqual(bridge['js'], ['atlas_bridge.js'])
        self.assertNotIn('all_frames', bridge)
        for name in ('atlas_bridge.js', 'background.js'):
            self.assertIn(name, browser_extension.FILES)

    def test_bridge_and_background_send_nothing_and_reload_only_for_own_page(self):
        bridge = (EXT / 'atlas_bridge.js').read_text(encoding='utf-8')
        background = (EXT / 'background.js').read_text(encoding='utf-8')
        for js in (bridge, background):
            for forbidden in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'cookies', 'innerHTML', 'textContent'):
                self.assertNotIn(forbidden, js)
        self.assertIn('root.dataset.atlasVideostart = version', bridge)
        self.assertIn("event.source !== window || event.origin !== location.origin", bridge)
        self.assertIn("data.source !== 'mediathekatlas' || data.type !== 'videostart-reload'", bridge)
        self.assertIn("host !== '127.0.0.1' && host !== 'localhost'", background)
        self.assertIn('chrome.runtime.reload()', background)
        self.assertIn("files: ['atlas_bridge.js']", background)


class WiringTests(unittest.TestCase):
    def test_routes_and_startup(self):
        import _wiring
        self.assertTrue(_wiring.routed('/api/browser-extension/status', 'GET', 'api'))
        self.assertTrue(_wiring.routed('/api/browser-extension/reveal', 'POST', 'api'))
        self.assertIn("return self.send(__import__('browser_extension').status(VERSION,HOME,NETWORK))", SERVER)
        self.assertRegex(SERVER, r"if NETWORK:raise ValueError\('Die App läuft auf einem anderen Gerät")
        # beim Start nur im Desktopbetrieb, nach dem Webserver und im Hintergrund
        start = SERVER.index("_boot('Webserver bereit')\n    if not NETWORK:")
        self.assertIn("name='browser_extension_provide'", SERVER[start:start + 900])

    def test_wizard_markup(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        for part in ('id="direct-start-ext-state"', 'id="direct-start-wizard"', 'id="direct-start-copy-url"', 'id="direct-start-reveal"',
                     'id="direct-start-path"', 'id="direct-start-copy-path"', 'id="direct-start-download"', 'data-local', 'data-remote hidden',
                     'Entwicklermodus', 'Entpackte Erweiterung laden'):
            self.assertIn(part, html)
        js = (ROOT / 'web' / 'direct_start.js').read_text(encoding='utf-8')
        for part in ("'/api/browser-extension/status'", "'/api/browser-extension/reveal'", "addEventListener('atlas-videostart'",
                     "type: 'videostart-reload'", 'atlas.videostartReload.'):
            self.assertIn(part, js)


if __name__ == '__main__':
    unittest.main()
