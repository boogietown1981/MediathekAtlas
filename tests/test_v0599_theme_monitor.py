"""0.5.99: helles Design (light_theme.py), Systemmonitor (system_monitor.py), Klicktest in der CI."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import light_theme  # noqa: E402
import system_monitor  # noqa: E402
import ui_prefs  # noqa: E402
from tests._wiring import wired  # noqa: E402

GB = 1024 ** 3


def luminance(colour):
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class LightThemeTests(unittest.TestCase):
    def test_colours_change_sides_and_keep_their_hue(self):
        self.assertGreater(luminance(light_theme.recolour('#0c111a')), 0.85, 'page background becomes light')
        self.assertLess(luminance(light_theme.recolour('#e9edf4')), 0.1, 'text becomes dark')
        green = light_theme.recolour('#67e1bc')
        r, g, b = (int(green[i:i + 2], 16) for i in (1, 3, 5))
        self.assertTrue(g > r and g > b, 'the accent stays green')
        self.assertEqual(light_theme.recolour('#000b')[-2:], 'bb', 'transparency is kept')
        self.assertEqual(len(light_theme.recolour('#abc')), 7)
        self.assertEqual(light_theme.recolour('1px solid white'), '1px solid black')
        self.assertTrue(light_theme.recolour('rgba(0,0,0,.4)').endswith(',.4)'))
        self.assertIsNone(light_theme.recolour('12px 4px'))
        self.assertIsNone(light_theme.recolour('nowrap'), 'the word inside "nowrap" is no colour')

    def test_rules(self):
        css = ('/* note { */ :root{color:#e9edf4;background:#0c111a;font-size:14px}.card,.panel:hover{border:1px solid #2b3948;padding:4px}'
               '.x{box-shadow:0 0 4px #000;color:#fff}#player .bar,.tile{color:#fff}.hero-title{color:#fff}dialog::backdrop{background:#000b}'
               '@media(max-width:600px){.card{background:#131d2a}.plain{margin:0}}@keyframes pulse{from{color:#fff}to{color:#000}}'
               '.url{background:url("a;b{}.png") #101722}')
        out = light_theme.build(css)
        self.assertIn('html[data-theme="light"]{color-scheme:light}', out)
        self.assertRegex(out, r'html\[data-theme="light"\]\{color:#[0-9a-f]{6};background:#[0-9a-f]{6}\}')
        self.assertNotIn('font-size', out, 'only declarations with a colour are repeated')
        self.assertRegex(out, r'html\[data-theme="light"\] \.card,html\[data-theme="light"\] \.panel:hover\{border:1px solid #[0-9a-f]{6}\}')
        self.assertNotIn('box-shadow', out)
        self.assertNotIn('player', out, 'the player keeps its dark surface')
        self.assertIn('html[data-theme="light"] .tile{', out, 'the other selector of the same rule is themed')
        self.assertNotIn('hero', out)
        self.assertNotIn('::backdrop', out)
        self.assertRegex(out, r'@media\(max-width:600px\)\{html\[data-theme="light"\] \.card\{background:#[0-9a-f]{6}\}\}')
        self.assertNotIn('plain', out)
        self.assertNotIn('keyframes', out)
        self.assertRegex(out, r'\.url\{background:url\("a;b\{\}\.png"\) #[0-9a-f]{6}\}')
        self.assertEqual(out.count('{'), out.count('}'))

    def test_real_stylesheet(self):
        path = ROOT / 'web' / 'style.css'
        out = light_theme.sheet(path).decode()
        self.assertIs(light_theme.sheet(path), light_theme.sheet(path), 'built once per version of the file')
        self.assertEqual(out.count('{'), out.count('}'))
        self.assertGreater(out.count('html[data-theme="light"]'), 250)
        for selector in ('body>aside{', '.nav.active{', '.storage-metric{', '.atlas-uc-card{', 'dialog{'):
            self.assertTrue(selector in out, selector)
        self.assertGreater(len(re.findall(r'@media[^{]*\{html\[data-theme="light"\]', out)), 0, 'rules inside media queries are themed too')
        # Every themed surface colour of the base rules is light, every text colour dark enough to read on it.
        first = re.search(r'html\[data-theme="light"\]\{color:(#[0-9a-f]{6});background:(#[0-9a-f]{6})\}', out)
        self.assertLess(luminance(first.group(1)), 0.1)
        self.assertGreater(luminance(first.group(2)), 0.85)

    def test_setting_and_page(self):
        self.assertEqual(ui_prefs.clean({})['theme'], 'dark', 'nothing changes for existing installations')
        self.assertEqual(ui_prefs.clean({'theme': 'light'})['theme'], 'light')
        self.assertEqual(ui_prefs.clean({'theme': 'auto'})['theme'], 'auto')
        self.assertEqual(ui_prefs.clean({'theme': 'pink'})['theme'], 'dark')
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(ui_prefs.save(root, {'theme': 'light'})['theme'], 'light')
            self.assertEqual(ui_prefs.load(root)['theme'], 'light')
        page = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertLess(page.index('href="/style.css"'), page.index('href="/theme-light.css"'), 'the light sheet comes after the base sheet')
        self.assertIn('localStorage.getItem("atlas-theme")', page)
        self.assertTrue(wired("'/theme-light.css'"))
        self.assertIn("choice('theme'", (ROOT / 'web' / 'admin.js').read_text(encoding='utf-8'))
        self.assertIn('prefers-color-scheme: light', (ROOT / 'web' / 'display.js').read_text(encoding='utf-8'))


class SystemMonitorTests(unittest.TestCase):
    def test_memory_readers(self):
        self.assertEqual(system_monitor._meminfo('MemTotal:       2048 kB\nMemFree: 100 kB\nMemAvailable:    512 kB\n'), (2048 * 1024, 512 * 1024))
        self.assertEqual(system_monitor._meminfo('MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 150 kB\n'), (1024000, 300 * 1024), 'old kernels without MemAvailable')
        self.assertEqual(system_monitor._meminfo('unsinn'), (None, None))
        text = 'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\nPages active: 500.\nPages inactive: 50.\nPages purgeable: 10.\n'
        self.assertEqual(system_monitor._vm_stat(text, 8 * GB), 160 * 16384)
        self.assertIsNone(system_monitor._vm_stat('', 8 * GB))

    def test_temperature(self):
        with tempfile.TemporaryDirectory() as base:
            for name, value in (('thermal_zone0', '41000'), ('thermal_zone1', '56500'), ('thermal_zone2', 'kaputt'), ('thermal_zone3', '-273000')):
                (Path(base) / name).mkdir()
                (Path(base) / name / 'temp').write_text(value)
            self.assertEqual(system_monitor.temperature(base), 56.5)
        self.assertIsNone(system_monitor.temperature('/does/not/exist'))

    def test_hints(self):
        calm = {'cores': 4, 'load': (0.5, 0.4, 0.3), 'memory_total': 8 * GB, 'memory_available': 4 * GB, 'temperature': 45,
                'drives': [{'label': 'Downloads', 'total_bytes': 500 * GB, 'free_bytes': 200 * GB}]}
        self.assertEqual(system_monitor.assess(calm), [])
        self.assertEqual(system_monitor.assess({}), [], 'unknown values produce no hint')
        busy = dict(calm, load=(9.0, 7.0, 3.0), memory_available=int(0.3 * GB), temperature=91,
                    drives=[{'label': 'Daten', 'total_bytes': 500 * GB, 'free_bytes': 1 * GB}, {'label': 'Downloads', 'total_bytes': 500 * GB, 'free_bytes': 1 * GB},
                            {'label': 'Extern', 'total_bytes': 100 * GB, 'free_bytes': 6 * GB}, {'label': 'Unbekannt', 'total_bytes': None, 'free_bytes': None}])
        hints = system_monitor.assess(busy)
        self.assertEqual([h['level'] for h in hints], ['warn', 'warn', 'warn', 'error', 'warn'])
        text = ' '.join(h['text'] for h in hints)
        for part in ('Prozessor', 'Arbeitsspeicher', '91 °C', 'weniger als 2 GB', '„Extern“'):
            self.assertIn(part, text)
        self.assertEqual(text.count('weniger als 2 GB'), 1, 'two folders on the same drive are reported once')

    def test_snapshot_on_this_machine(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'catalog.db').write_bytes(b'x' * 2048)
            (Path(root) / 'pluto.sqlite3').write_bytes(b'x' * 10)
            (Path(root) / 'notes.txt').write_bytes(b'x' * 99999)
            reading = system_monitor.snapshot(root, root, {'downloads_running': 2})
        self.assertGreaterEqual(reading['cores'], 1)
        self.assertEqual(reading['databases'], {'total_bytes': 2058, 'files': [{'name': 'catalog.db', 'bytes': 2048}, {'name': 'pluto.sqlite3', 'bytes': 10}], 'count': 2})
        self.assertEqual([d['label'] for d in reading['drives']], ['Daten und Datenbanken', 'Downloads'])
        self.assertGreater(reading['drives'][0]['total_bytes'], 0)
        self.assertEqual(reading['activity'], {'downloads_running': 2})
        self.assertIsInstance(reading['hints'], list)
        self.assertGreater(reading['threads'], 0)
        if sys.platform.startswith('linux'):
            self.assertGreater(reading['memory_total'], 0)
            self.assertGreater(reading['process_memory'], 0)
            self.assertEqual(len(reading['load']), 3)
        self.assertEqual(system_monitor.drive('/does/not/exist/anywhere')['total_bytes'], None)

    def test_wiring(self):
        self.assertTrue(wired("'/api/system-monitor'"))
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("'/system.js'", server)
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        self.assertIn("'light_theme.py','system_monitor.py'", build)
        page = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('data-view="system"', page)
        self.assertIn('<script src="/system.js">', page)
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertEqual(app.count("'storage','system','review'"), 2, 'known view and area of the Verwaltung')


class ClickTestTests(unittest.TestCase):
    def test_click_test_is_in_the_ci_for_three_browsers(self):
        workflow = (ROOT / '.github' / 'workflows' / 'tests.yml').read_text(encoding='utf-8')
        self.assertIn('browser: [chromium, firefox, webkit]', workflow)
        self.assertIn('node tests/browser/click_all.cjs ${{ matrix.browser }}', workflow)
        script = (ROOT / 'tests' / 'browser' / 'click_all.cjs').read_text(encoding='utf-8')
        for part in ("MEDIATHEKATLAS_DISABLE_BACKGROUND: '1'", "'--no-browser'", 'pageerror', "theme: 'light'", '#admin-tabs .admin-tab', 'process.exit(failed ? 1 : 0)'):
            self.assertIn(part, script)
        self.assertEqual(sorted(p.name for p in (ROOT / 'tests').glob('*.cjs') if 'click' in p.name), [], 'not among the scripts the unit job runs without browsers')


if __name__ == '__main__':
    unittest.main()
