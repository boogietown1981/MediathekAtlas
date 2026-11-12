"""0.5.70: HLS played by hls.js in the browser, uniform tiles, versions on the title pages."""
import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


class HlsTests(unittest.TestCase):
    def test_library_is_shipped_unchanged_with_its_licence(self):
        data = (ROOT / 'web' / 'hls.min.js').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'cfc70cc9e9fc63d071919e087670abc760c8fd1bc889b88588026e4d22193bbe')
        self.assertIn('Apache License', text('web/hls.LICENSE.txt'))
        self.assertIn("if path=='/hls.min.js'", text('server.py'))
        html = text('web/index.html')
        self.assertLess(html.index('/hls.min.js'), html.index('/player.js'))

    def test_player_prefers_hls_js_and_falls_back_to_ffmpeg(self):
        js = text('web/player.js')
        for part in ("function hlsJs()", "function startHls(url,t)", "if(S.info.ffmpeg)startRemux(at)", "hls.recoverMediaError()",
                     "else if(info.hls&&info.url&&hlsJs())startHls(info.url,t);", "S.hls.currentLevel=hlsLevel(wish())",
                     "function stopVideo(){stopHls();"):
            self.assertIn(part, js)
        # the browser's own HLS player only on Apple browsers (Chrome's new one plays live streams unevenly)
        self.assertIn("function nativeHls(){return /Apple/.test(navigator.vendor||'')&&", js)
        self.assertLess(js.index("hlsJs())startHls(info.url,t)"), js.index("nativeHls()&&(wish()==='auto'||!info.ffmpeg))startDirect"))

    def test_packages_take_the_whole_web_folder(self):
        self.assertTrue((ROOT / 'build' / 'MediathekAtlas.app').exists() is False or
                        any(p.name == 'hls.min.js' for p in (ROOT / 'build' / 'MediathekAtlas.app').rglob('hls.min.js')))


class TileTests(unittest.TestCase):
    def test_tiles(self):
        js = text('web/unified_catalog.js')
        tile = js[js.index('function actionNodes'):js.index('function makeCard')]
        self.assertIn("'⬇ Herunterladen'", tile)
        self.assertIn("edit(item.raw)", tile)
        self.assertNotIn('protectedNote', tile)          # no note where no download is possible
        self.assertIn("'↗ '+(EXTERNAL[item.source]", tile)

    def test_versions_on_title_pages(self):
        self.assertIn('function versions(source, id, title)', text('web/offline_button.js'))
        self.assertIn("window.AtlasOffline = {control, refresh, protectedNote, versions,", text('web/offline_button.js'))
        page = text('web/portal_title.js')
        self.assertIn("section('Fassungen zum Herunterladen')", page)
        self.assertIn("versionSection(m, host)", page)
        self.assertIn('function downloadVersions(item)', text('web/app.js'))
        self.assertIn('function edit(item,quality)', text('web/app.js'))
        self.assertIn('downloadVersions({...item,...selected,metadata:m})', text('web/titleview.js'))


if __name__ == '__main__':
    unittest.main()
