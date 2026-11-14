"""0.5.93: Björns Test von 0.5.91 (13.11.2026).

- SAT.1 spielt joyn.de nur mit Joyn+, obwohl Joyns Navigation den Sender frei führt (PUBLIC_VALUE, ohne PLUS).
- TOGGO (pinker Play-Knopf) und JustWatch (Mini-Player) brauchten noch einen Klick: die Erweiterung
  klickt jetzt auch Play-Knöpfe ohne Beschriftung über dem Player und startet Videos mit preload="none".
"""
import json
import tempfile
import unittest
from pathlib import Path

import joyn
import live_tv
from test_v0590_joyn_live_links import Api, LIVE

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'web' / 'browser-extension' / 'chrome'


class JoynPlusChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_the_exact_channel_is_plus(self):
        found = {joyn.channel_from(n)['title']: joyn.channel_from(n) for n in LIVE}
        self.assertEqual(found['SAT.1']['offer'], 'plus')
        self.assertEqual(found['SAT.1']['category'], joyn.PLUS)
        self.assertEqual(found['Sat.1 Bayern']['offer'], 'free')     # Regionalfenster bleibt frei
        self.assertEqual(found['Das Erste']['offer'], 'free')
        self.assertEqual(found['ProSieben FUN']['offer'], 'plus')    # Markierung von Joyn wie bisher
        for title in ('SAT.1 GOLD', 'SAT.1 emotions', 'Sat.1 NRW', ''):
            self.assertFalse(joyn.plus_channel(title), title)

    def test_stored_catalogue_is_marked_without_new_request(self):
        joyn.sync(self.root, request=Api(), now=1794500000.0, gap=0)
        db = joyn._connect(self.root)
        with db:   # Stand von 0.5.65–0.5.92: SAT.1 als frei gespeichert
            db.execute("UPDATE joyn_items SET offer='free', category=? WHERE title='SAT.1'", (joyn.FREE,))
        db.close()
        live = {c['title']: c for c in live_tv.joyn_channels(self.root)}
        self.assertTrue(live['SAT.1']['quality'].startswith('Joyn+'))
        self.assertTrue(live['Das Erste']['quality'].startswith('kostenlos'))
        listed = {c['title']: c for c in joyn.listing(self.root, 'live')['items']}
        self.assertEqual(listed['SAT.1']['offer'], 'plus')
        sat1 = next(c for c in listed.values() if c['title'] == 'SAT.1')
        self.assertEqual(joyn.item(self.root, sat1['id'])['item']['offer_label'], joyn.PLUS)


class ExtensionOverlayTests(unittest.TestCase):
    def test_unlabelled_play_buttons_and_lazy_videos(self):
        js = (EXT / 'autostart.js').read_text(encoding='utf-8')
        for part in ('function clickOverlay()', 'function press(el)', "'.vjs-big-play-button'", "'.bmpui-ui-hugeplaybacktogglebutton'",
                     'document.elementFromPoint(', "hit.tagName !== 'IFRAME'", 'v.currentSrc || v.src', 'overlayClicks >= 3',
                     'Date.now() - lastVideoTry < 2500'):
            self.assertIn(part, js)
        self.assertNotIn('v.readyState < 2', js)
        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['content_scripts'][0]['all_frames'])   # Player in eigenem Frame derselben Seite


if __name__ == '__main__':
    unittest.main()
