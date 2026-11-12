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
        # 0.5.52: without a youth-protection window it is copy protected (night reservation: test_v0552).
        self.assertFalse(jw['playable']); self.assertFalse(jw['offline']['allowed']); self.assertTrue(jw['protected'])
        self.assertFalse(pl['offline']['night'])
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


class LibraryNamingTests(unittest.TestCase):
    """Björn (12.11.2026): own folder, file name with resolution and codecs, images per file."""
    def test_quality_label(self):
        import core
        probe = lambda w, h, v, a: {'streams': [{'codec_type': 'video', 'codec_name': v, 'width': w, 'height': h},
                                                {'codec_type': 'audio', 'codec_name': a}]}
        self.assertEqual(core.quality_label(probe(1920, 1080, 'h264', 'eac3')), '1080p - H264 E-AC-3')
        self.assertEqual(core.quality_label(probe(1920, 800, 'hevc', 'aac')), '1080p - HEVC AAC')   # cinemascope
        self.assertEqual(core.quality_label(probe(1280, 720, 'h264', 'ac3')), '720p - H264 AC-3')
        self.assertEqual(core.quality_label(probe(960, 540, 'h264', 'aac')), '540p - H264 AAC')
        self.assertEqual(core.quality_label(probe(3840, 2160, 'av1', 'opus')), '2160p - AV1 Opus')
        self.assertEqual(core.quality_label({}), '')

    def test_names_and_existing_files(self):
        import core, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            m = {'kind': 'movie', 'title': 'Spellbound', 'year': 2024}
            planned = core.target(tmp, m, 'x')
            self.assertEqual(planned.relative_to(tmp).as_posix(), 'Filme/Spellbound (2024)/Spellbound - (2024).mkv')
            final = core.final_target(planned, {'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080},
                                                            {'codec_type': 'audio', 'codec_name': 'eac3'}]})
            self.assertEqual(final.name, 'Spellbound - (2024) - 1080p - H264 E-AC-3.mkv')
            self.assertIsNone(core.existing_download(planned))
            planned.parent.mkdir(parents=True)
            final.write_bytes(b'x')
            self.assertEqual(core.existing_download(planned), final)     # no second download
            final.unlink()
            legacy = planned.parent / 'Spellbound (2024).mkv'; legacy.write_bytes(b'x')
            self.assertEqual(core.existing_download(planned), legacy)    # files from before 0.5.42
            ep = core.target(tmp, {'kind': 'series', 'title': 'Tatort', 'year': 1970, 'season': 1, 'episode': 2}, 'y')
            self.assertEqual(ep.relative_to(tmp).as_posix(), 'Serien/Tatort (1970)/Season 01/Tatort - (1970) - S01E02.mkv')

    def test_images_with_dotted_names_and_expiry(self):
        import artwork, tempfile, netzkino_downloads as nd
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'Filme' / 'Mr. Robot (2015)'; folder.mkdir(parents=True)
            video = folder / 'Mr. Robot - (2015) - 1080p - H264 AAC.mkv'; video.write_bytes(b'v')
            class R:
                def __init__(self, data): self.data = data
                def read(self, n): return self.data
                def __enter__(self): return self
                def __exit__(self, *a): return False
            from unittest import mock
            with mock.patch('core.open_url', return_value=R(b'\xff\xd8\xff' + b'0' * 10)):
                self.assertTrue(artwork.save_image('https://images.pluto.tv/p.jpg', video.with_name(video.stem + '-poster')))
            poster = folder / 'Mr. Robot - (2015) - 1080p - H264 AAC-poster.jpg'
            self.assertTrue(poster.is_file())
            backdrop = folder / 'Mr. Robot - (2015) - 1080p - H264 AAC-backdrop.jpg'; backdrop.write_bytes(b'b')
            removed = nd.remove_files({'path': str(video), 'root': tmp, 'metadata': {'kind': 'movie'}})
            self.assertIn(str(poster), removed); self.assertIn(str(backdrop), removed)
            self.assertFalse(folder.exists())

    def test_portal_artwork_hosts(self):
        import artwork
        self.assertTrue(artwork.valid('https://images.pluto.tv/a.jpg'))
        self.assertTrue(artwork.valid('https://d3owf1x34yi7gd.cloudfront.net/x.jpg'))
        self.assertFalse(artwork.valid('https://pluto.tv.evil.example/a.jpg'))
        self.assertFalse(artwork.valid('http://images.pluto.tv/a.jpg'))


if __name__ == '__main__':
    unittest.main()
