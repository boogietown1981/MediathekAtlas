"""0.5.91: Videostart bei Anbietern mit Kopierschutz (direkter Player-Link + optionale Chrome-Erweiterung)."""
import io
import json
import re
import unittest
import zipfile
from pathlib import Path

import browser_extension
from version import VERSION

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'web' / 'browser-extension' / 'chrome'
SERVER = (ROOT / 'server.py').read_text(encoding='utf-8')
SCRIPTS = eval(re.search(r'^SCRIPTS=(\(.*\))$', SERVER, re.M).group(1))


class ExtensionPackageTests(unittest.TestCase):
    def test_manifest_is_mv3_and_limited_to_the_four_providers(self):
        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['version'], VERSION)
        self.assertEqual(manifest['permissions'], ['storage'])
        self.assertNotIn('host_permissions', manifest)
        self.assertEqual(len(manifest['content_scripts']), 1)
        script = manifest['content_scripts'][0]
        self.assertEqual(sorted(script['matches']), ['https://www.joyn.de/*', 'https://www.justwatch.com/*',
                                                     'https://www.rakuten.tv/*', 'https://www.toggo.de/*'])
        self.assertEqual(script['js'], ['autostart.js'])
        for path in list(manifest['icons'].values()) + [manifest['action']['default_popup']]:
            self.assertTrue((EXT / path).is_file(), path)

    def test_zip_has_one_folder_with_every_file_and_the_app_version(self):
        data = browser_extension.package('0.5.91')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            self.assertEqual(sorted(names), sorted('MediathekAtlas-Videostart/' + f for f in browser_extension.FILES))
            manifest = json.loads(z.read('MediathekAtlas-Videostart/manifest.json'))
            self.assertEqual(manifest['version'], '0.5.91')
            self.assertEqual(z.read('MediathekAtlas-Videostart/autostart.js'), (EXT / 'autostart.js').read_bytes())
        self.assertEqual(data, browser_extension.package('0.5.91'))   # reproduzierbar

    def test_chrome_version_is_numbers_only(self):
        self.assertEqual(browser_extension.chrome_version('0.5.91'), '0.5.91')
        self.assertEqual(browser_extension.chrome_version('0.6.0-beta2'), '0.6.0.2')
        self.assertEqual(browser_extension.chrome_version('1.2.3.4.5'), '1.2.3.4')
        self.assertEqual(browser_extension.chrome_version(''), '0.0.0')

    def test_content_script_acts_only_on_links_from_mediathekatlas(self):
        js = (EXT / 'autostart.js').read_text(encoding='utf-8')
        self.assertIn("const MARK = 'mediathekatlas-autostart';", js)
        self.assertIn("if (!since || Date.now() - since > WINDOW_MS) return;", js)
        self.assertIn('/hdcp/i.test', js)
        for word in ("'kauf'", "'leih'", "'abo'", "'anmeld'", "'cookie'", "'zustimm'", "'akzeptier'"):
            self.assertIn(word, js)
        # nichts wird verschickt, kein Zugriff auf Kopierschutz oder Lizenz
        for forbidden in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'license', 'widevine', 'requestMediaKeySystemAccess'):
            self.assertNotIn(forbidden, js)


class WebWiringTests(unittest.TestCase):
    def test_route_script_and_panel(self):
        self.assertIn("if path=='/api/browser-extension':return self.send(__import__('browser_extension').package(VERSION),ctype='application/zip')", SERVER)
        # hinter der Token-Prüfung wie alle /api-Routen
        self.assertLess(SERVER.index("if self.headers.get('X-Atlas-Token')!=TOKEN"), SERVER.index("path=='/api/browser-extension'"))
        self.assertIn('/direct_start.js', SCRIPTS)
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<script src="/direct_start.js"></script>', html)
        for part in ('id="direct-start-panel"', 'id="direct-start-toggle"', 'id="direct-start-download"', 'chrome://extensions', 'Entpackte Erweiterung laden'):
            self.assertIn(part, html)

    def test_every_provider_link_goes_through_the_direct_helper(self):
        title = (ROOT / 'web' / 'portal_title.js').read_text(encoding='utf-8')
        self.assertEqual(title.count('direct(m.source, e.web_url'), 2)
        self.assertIn("direct(source, m.web_url)", title)
        self.assertIn("window.AtlasDirect.href(item.source,item.web_url)", (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8'))
        self.assertIn("window.AtlasDirect.href(K, item.web_url)", (ROOT / 'web' / 'portal_panel.js').read_text(encoding='utf-8'))

    def test_packages_carry_the_extension(self):
        import build_nas
        self.assertIn('web', build_nas.APP_DIRS)
        self.assertIn('browser_extension.py', build_nas.app_files())
        self.assertIn("'browser_extension.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
