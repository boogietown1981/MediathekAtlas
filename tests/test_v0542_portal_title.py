"""0.5.42: Netzkino addresses with spaces, one title page model for all film portals."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import downloads  # noqa: E402


class SafeUrlTests(unittest.TestCase):
    def test_space_in_netzkino_path(self):
        url = 'https://pmd.netzkino-seite.netzkino.de/YFEN/Die_verwegenen_Vier_reissen_aus_-_Teil 1.mp4'
        self.assertEqual(downloads.safe_url(url),
                         'https://pmd.netzkino-seite.netzkino.de/YFEN/Die_verwegenen_Vier_reissen_aus_-_Teil%201.mp4')

    def test_existing_escapes_and_query_kept(self):
        self.assertEqual(downloads.safe_url('https://a.de/x%20y.mp4?a=1&b=2'), 'https://a.de/x%20y.mp4?a=1&b=2')
        self.assertEqual(downloads.safe_url('https://a.de/p.mp4?t=a b'), 'https://a.de/p.mp4?t=a%20b')

    def test_resolver_result_is_encoded(self):
        import ytdl_bridge
        old = ytdl_bridge.resolve
        ytdl_bridge.resolve = lambda page: {'url': 'https://cdn.example/Teil 1.mp4'}
        try:
            self.assertEqual(downloads.source_url({'_resolver': 'netzkino', '_page_url': 'https://www.netzkino.de/details/x'}),
                             'https://cdn.example/Teil%201.mp4')
        finally:
            ytdl_bridge.resolve = old

    def test_request_line_accepts_result(self):
        import urllib.request
        req = urllib.request.Request(downloads.safe_url('https://cdn.example/a b\tc.mp4'))
        self.assertNotIn(' ', req.selector)


class TitleModelTests(unittest.TestCase):
    def setUp(self):
        import tempfile, pluto, justwatch
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        db = pluto._connect(self.root)
        with db:
            db.execute("INSERT INTO pluto_items(id,kind,title,slug,series_id,season,episode,number,year,duration,rating,genre,summary,poster,path,category,seen,updated) "
                       "VALUES('5f1a2b3c4d5e6f7a8b9c0d1e','movie','Arrival','arrival','',NULL,NULL,NULL,2016,6960,'FSK 12','Sci-Fi & Fantasy','Inhalt',"
                       "'https://images.pluto.tv/a.jpg','/stitch/hls/episode/x/master.m3u8','Sci-Fi',1,1)")
        db.close()
        jdb = justwatch._connect(self.root)
        with jdb:
            jdb.execute("INSERT INTO justwatch_items(id,kind,title,path,series_id,season,episode,year,duration,rating,genre,summary,poster,imdb_id,imdb_score,imdb_votes,playable,web_url,seen,updated) "
                        "VALUES('tm1','movie','[Rec]','/de/Film/Rec','',NULL,NULL,2007,4680,'16','Horror, Mystery & Thriller','Inhalt',"
                        "'https://images.justwatch.com/poster/1/s718/rec.jpg','tt1038988',7.4,220000,0,'https://www.justwatch.com/de/Film/Rec?package=jwt',1,1)")
        jdb.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_fields_for_every_portal(self):
        import portal_title
        pl = portal_title.model(self.root, 'pluto', '5f1a2b3c4d5e6f7a8b9c0d1e')
        jw = portal_title.model(self.root, 'justwatch', 'tm1')
        self.assertEqual(set(pl), set(jw))
        self.assertEqual(pl['kind_label'], 'Film')
        self.assertTrue(pl['playable']); self.assertTrue(pl['offline']['allowed'])
        # Provider-specific information is kept in its own block.
        self.assertIn(['Pluto TV-Genre', 'Sci-Fi & Fantasy'], pl['provider_facts'])
        self.assertIn(['IMDb-ID laut JustWatch TV', 'tt1038988'], jw['provider_facts'])
        # JustWatch title without external stream: no player, no offline copy, official page.
        self.assertFalse(jw['playable']); self.assertFalse(jw['offline']['allowed'])
        self.assertTrue(jw['web_url'].startswith('https://www.justwatch.com/'))
        self.assertEqual(jw['rating']['value'], 7.4)
        self.assertIn('Horror', jw['categories'])

    def test_rejects_unknown(self):
        import portal_title
        with self.assertRaises(ValueError):
            portal_title.model(self.root, 'youtube', 'x')
        with self.assertRaises(ValueError):
            portal_title.model(self.root, 'pluto', '../../etc')


class WiringTests(unittest.TestCase):
    def test_everything_opens_the_title_page(self):
        html = (ROOT / 'web' / 'index.html').read_text()
        self.assertNotIn('atlas-pluto-detail', html); self.assertNotIn('atlas-justwatch-detail', html)
        self.assertIn('<script src="/portal_title.js"></script>', html)
        self.assertIn("window.AtlasPortalTitle?.open(K, id)", (ROOT / 'web' / 'portal_panel.js').read_text())
        self.assertIn("AtlasPortalTitle?.open('netzkino'", (ROOT / 'web' / 'netzkino.js').read_text())
        uc = (ROOT / 'web' / 'unified_catalog.js').read_text()
        self.assertIn("window.AtlasPortalTitle?.open(item.source,item.id)", uc)
        self.assertIn("window.AtlasPortalTitle.open('netzkino',item.id)", uc)
        server = (ROOT / 'server.py').read_text()
        self.assertIn("'/api/portal-title'", server); self.assertIn("'/portal_title.js'", server)
        self.assertIn("'portal_title.py'", (ROOT / 'build_macos.py').read_text())
        self.assertIn('image||artImage', (ROOT / 'web' / 'titleview.js').read_text())


if __name__ == '__main__':
    unittest.main()
