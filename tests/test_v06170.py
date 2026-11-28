"""0.6.170 – Abo-Profile (Umfang 28.11.2026, Punkt 1–2): benannte Kinderprofile mit eigenem Gesehen-Stand und
Kanalauswahl je Kind, „Wer schaut?“ in der Kinderecke. Browser-Ablauf: tests/browser/kids_corner.cjs (kidsProfiles)."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_profiles as kp  # noqa: E402
import watch_state  # noqa: E402
from _wiring import routed  # noqa: E402


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')

    def test_create_rename_hide_delete(self):
        mia = kp.save(self.c, {'name': '  Mia  '})
        ben = kp.save(self.c, {'name': 'Ben', 'hidden': [3, '5', 3]})
        self.assertEqual((mia['id'], mia['name'], ben['hidden']), (1, 'Mia', [3, 5]))
        self.assertIn(mia['color'], kp.COLORS)
        self.assertEqual(kp.save(self.c, {'id': 2, 'name': 'Benno'})['hidden'], [3, 5])   # Name ändern lässt Kanäle
        self.assertEqual(kp.save(self.c, {'id': 2, 'hidden': []})['name'], 'Benno')
        for bad in ({'name': ''}, {'name': 'x' * 31}, {'name': 'MIA'}, {'name': 'Neu', 'hidden': ['a']},
                    {'name': 'Neu', 'hidden': [True]}, {'id': 9, 'name': 'X'}):
            with self.assertRaises(ValueError, msg=bad):
                kp.save(self.c, bad)
        kp.delete(self.c, 2)
        self.assertEqual(kp.save(self.c, {'name': 'Lea'})['id'], 3)        # Kennung nie wiederverwendet
        with self.assertRaises(ValueError):
            kp.delete(self.c, 2)

    def test_limit(self):
        for i in range(kp.MAX_PROFILES):
            kp.save(self.c, {'name': 'Kind %d' % i})
        with self.assertRaises(ValueError):
            kp.save(self.c, {'name': 'Eins zu viel'})

    def test_keys_and_marks(self):
        self.assertEqual(kp.key({'id': 1}, 'job:a'), 'job:a')           # erstes Profil = bisheriger Stand
        self.assertEqual(kp.key({'id': 2}, 'job:a'), 'kp2:job:a')
        self.assertEqual(kp.key({'id': 2}, 'kp3:job:a'), 'kp2:job:a')   # kein fremdes oder doppeltes Präfix
        self.assertEqual(kp.key(None, 'job:a'), 'job:a')
        progress = {'job:a': 1, 'kp2:job:a': 2, 'kp2:netzkino:x': 3, 'kp12:job:b': 4}
        self.assertEqual(kp.marks(progress, None), {'job:a': 1})
        self.assertEqual(kp.marks(progress, {'id': 1}), {'job:a': 1})
        self.assertEqual(kp.marks(progress, {'id': 2}), {'job:a': 2, 'netzkino:x': 3})
        self.assertEqual(kp.marks(progress, {'id': 12}), {'job:b': 4})
        self.assertTrue(watch_state.valid_key('kp12:job:b'))

    def test_visible(self):
        data = {'channels': [{'id': 1}, {'id': 2}], 'videos': [{'abo': '1'}, {'abo': '2'}], 'catalog': {}}
        out = kp.visible(data, {'hidden': [2]})
        self.assertEqual(([c['id'] for c in out['channels']], [v['abo'] for v in out['videos']]), ([1], ['1']))
        self.assertIs(kp.visible(data, None), data)
        self.assertEqual(len(data['channels']), 2)                       # Original unverändert


class WatchOverviewTests(unittest.TestCase):
    def test_other_profiles_not_in_continue_or_marked(self):
        with tempfile.TemporaryDirectory() as root:
            watch_state.progress(root, 'job:a', 120, 600, info={'title': 'A'})
            watch_state.progress(root, 'kp2:job:a', 200, 600, info={'title': 'A'})
            watch_state.mark(root, 'kp2:job:b', favorite=True, info={'title': 'B'})
            out = watch_state.overview(root)
            self.assertEqual([e['key'] for e in out['continue']], ['job:a'])
            self.assertEqual(out['marked'], [])
            self.assertIn('kp2:job:a', out['progress'])


class WiringTests(unittest.TestCase):
    def test_routes_ui_and_package(self):
        self.assertTrue(routed('/api/kids-profiles', 'GET'))
        self.assertTrue(routed('/api/kids-profiles', 'POST'))
        self.assertIn("'kids_profiles.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn('id="kids-profiles"', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('id="kids-who"', (ROOT / 'web' / 'kids.html').read_text(encoding='utf-8'))
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn('kids_profile: state.profile', js)
        self.assertIn("withProfile('kids-episodes", js)


if __name__ == '__main__':
    unittest.main()
