"""0.5.66: playback (A/V offset, quality levels), resolution and provider before a download,
more generous merging of "title" and "title: subtitle", Live-TV tab hardened."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import download_quality
import downloads
import hls_variants
import portal_reference
import streaming
import unified_index

ROOT = Path(__file__).resolve().parents[1]
MASTER = '''#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="de",DEFAULT=YES,URI="a/pl.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="de",URI="s/pl.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="aud",SUBTITLES="sub"
v1080/pl.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3300000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2",AUDIO="aud",SUBTITLES="sub"
v720/pl.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2",AUDIO="aud"
v720low/pl.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=854x480,CODECS="avc1.64001e,mp4a.40.2",AUDIO="aud"
v480/pl.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=128000,CODECS="mp4a.40.2",AUDIO="aud"
audio-only/pl.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=640x360,CODECS="avc1.64001e,mp4a.40.2"
file:///etc/passwd
'''
BASE = 'https://cdn.example/live/master.m3u8?session=abc'
FETCH = lambda url: (MASTER, BASE)
SOURCE = {'kind': 'url', 'url': BASE, 'hls': True, 'title': 'Sender', 'live': True}


class LevelTests(unittest.TestCase):
    def test_levels_without_audio_only_and_local_addresses(self):
        variants = hls_variants.parse(MASTER, BASE)
        self.assertEqual([v['height'] for v in variants], [1080, 720, 720, 480])
        self.assertTrue(all(v['url'].startswith('https://cdn.example/live/') for v in variants))
        self.assertEqual([l['id'] for l in hls_variants.levels(variants)], ['1080', '720', '480'])
        self.assertEqual(hls_variants.parse('#EXTM3U\n#EXTINF:6,\nseg.ts\n', BASE), [])

    def test_choice(self):
        variants = hls_variants.parse(MASTER, BASE)
        pick = lambda wish: (hls_variants.choose(variants, wish)['height'], hls_variants.choose(variants, wish)['bandwidth'])
        self.assertEqual(pick('auto'), (720, 2500000))     # at most 720p, the lighter of the two
        self.assertEqual(pick('max'), (1080, 6000000))
        self.assertEqual(pick('480'), (480, 1400000))
        self.assertEqual(pick('600'), (480, 1400000))
        self.assertEqual(pick('240'), (480, 1400000))      # nothing smaller: the smallest
        self.assertIsNone(hls_variants.choose([], 'auto'))

    def test_single_level_playlist(self):
        variants = hls_variants.parse(MASTER, BASE)
        text = hls_variants.single(MASTER, BASE, hls_variants.choose(variants, '480'))
        self.assertEqual(text.count('#EXT-X-STREAM-INF'), 1)
        self.assertIn('https://cdn.example/live/v480/pl.m3u8', text)
        self.assertIn('URI="https://cdn.example/live/a/pl.m3u8"', text)
        self.assertNotIn('SUBTITLES', text)
        self.assertNotIn('file:', text)
        self.assertNotIn('v1080', text)


class StreamTests(unittest.TestCase):
    def test_prepare_writes_one_level_and_finish_removes_it(self):
        with tempfile.TemporaryDirectory() as d:
            path, level = streaming.prepare(SOURCE, 'auto', Path(d) / 'streams', FETCH)
            self.assertEqual((level['height'], level['levels']), (720, 4))
            self.assertTrue(path.name.endswith('.m3u8') and path.is_file())

            class Proc:
                returncode = 0
                stderr = type('E', (), {'read': lambda self: b''})()
                atlas_cleanup = path
                def poll(self): return 0
            streaming.finish(Proc())
            self.assertFalse(path.exists())
        # nothing to choose or provider unreachable: ffmpeg gets the address as before
        self.assertEqual(streaming.prepare(SOURCE, 'auto', None, FETCH), (None, None))
        other = {**SOURCE, 'url': 'https://cdn.example/unreachable.m3u8'}   # answers are cached per address
        self.assertEqual(streaming.prepare(other, 'auto', Path(d), lambda u: (_ for _ in ()).throw(OSError('x'))), (None, None))
        self.assertEqual(streaming.prepare({'kind': 'file', 'path': '/x'}, 'auto', Path(d), FETCH), (None, None))
        self.assertEqual(streaming.hls_levels(other, lambda u: (_ for _ in ()).throw(OSError('x'))), [])

    def test_command(self):
        streaming.tool = lambda name: '/usr/bin/' + name
        try:
            plain = streaming.command(SOURCE, 0, 'aac')
            listed = streaming.command(SOURCE, 30, 'aac', playlist='/tmp/x.m3u8')
            local = streaming.command({'kind': 'file', 'path': '/f.mkv', 'title': 't'}, 0, True)
        finally:
            import runtime_tools
            streaming.tool = runtime_tools.resolve
        for args in (plain, listed, local):
            # the header is written with the first fragment, so a track that starts later keeps its offset
            self.assertIn('frag_keyframe+delay_moov+default_base_moof', args)
            self.assertNotIn('empty_moov', ' '.join(args))
        self.assertIn('-reconnect', plain)
        self.assertEqual(plain[plain.index('-i') + 1], BASE)
        self.assertNotIn('-reconnect', listed)             # a file input does not know the option
        self.assertEqual(listed[listed.index('-protocol_whitelist') + 1], 'file,http,https,tcp,tls,crypto')
        self.assertEqual(listed[listed.index('-i') + 1], '/tmp/x.m3u8')
        self.assertEqual(plain[plain.index('-max_reload') + 1], '60')
        self.assertNotIn('-max_reload', local)

    def test_broadcaster_file_follows_the_wish(self):
        c = sqlite3.connect(':memory:')
        c.executescript('CREATE TABLE offers(id TEXT,payload TEXT,work_id TEXT);CREATE TABLE works(id TEXT,meta TEXT);'
                        'CREATE TABLE records(id TEXT,payload TEXT);CREATE TABLE downloaded_items(identity TEXT,path TEXT);')
        row = {'title': 'Film', 'url_video_hd': 'https://cdn.example/f_1080.mp4', 'url_video': 'https://cdn.example/f_720.mp4',
               'url_video_low': 'https://cdn.example/f_360.mp4'}
        c.execute('INSERT INTO records VALUES(?,?)', ('r1', json.dumps(row)))
        import catalog
        hints = {l['url']: l['height_hint'] for l in catalog.links(row)}
        small = streaming.resolve(c, offer='r1', quality='360')
        best = streaming.resolve(c, offer='r1', quality='max')
        if all(hints.values()):
            self.assertLessEqual(hints[small['url']], 360)
            self.assertEqual(hints[best['url']], max(h for h in hints.values() if h <= 1080))
        self.assertEqual(streaming.quality_limit('auto'), 720)
        self.assertEqual(streaming.quality_limit('max'), 1080)
        self.assertEqual(streaming.quality_limit('480'), 480)
        self.assertEqual(streaming.quality_limit('quatsch'), 720)
        levels = streaming.plan(small)['levels']
        self.assertEqual([l['height'] for l in levels], sorted((l['height'] for l in levels), reverse=True))


class DownloadQualityTests(unittest.TestCase):
    def test_normalize(self):
        for given, want in (('best', 'best'), (None, 'best'), ('max', 'best'), ('480', '480'), (720, '720'), ('hd', 'hd'),
                            ('99999', 'best'), ('1; rm', 'best'), ('100', 'best')):
            self.assertEqual(download_quality.normalize(given), want)
        self.assertEqual([download_quality.mediathek_key(q) for q in ('best', '1080', '720', '480', '360', 'low')],
                         ['best', 'best', 'hd', 'standard', 'low', 'low'])

    def test_hls_playlist(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(download_quality.hls_playlist(BASE, 'best', d, FETCH), (None, None))
            path, level = download_quality.hls_playlist(BASE, '480', d, FETCH)
            self.assertEqual(level['height'], 480)
            self.assertTrue(path.name.endswith('.m3u8'))   # ffmpeg refuses other endings
            self.assertEqual(path.read_text().count('#EXT-X-STREAM-INF'), 1)

    def test_youtube_and_netzkino(self):
        self.assertIn('height<=480', download_quality.youtube_format('480'))
        self.assertIn('height<=2160', download_quality.youtube_format('2160'))
        self.assertIn('height<=1080', download_quality.youtube_format('best'))
        import youtube_downloads
        self.assertEqual(youtube_downloads._format({}), youtube_downloads.FORMAT)
        self.assertIn('height<=720', youtube_downloads._format({'_quality': '720'}))
        formats = [{'url': 'https://x/a_360.mp4', 'height': 360}, {'url': 'https://x/a_1080.mp4', 'height': 1080},
                   {'url': 'https://x/a.m3u8', 'height': 720}]
        self.assertEqual(download_quality.pick_format(formats, '720')['height'], 360)
        self.assertEqual(download_quality.pick_format(formats, '240')['height'], 360)
        self.assertIsNone(download_quality.pick_format(formats, 'best'))
        self.assertIsNone(download_quality.pick_format([{'url': 'https://x/a.mp4'}], '480'))

    def test_wish_is_stored_in_the_new_job_only(self):
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j1', json.dumps({'id': 'j1', 'quality': 'best'}), 'queued'))
        self.assertEqual(download_quality.set_job(c, {'created': True, 'id': 'j1'}, '480'), '480')
        self.assertEqual(json.loads(c.execute('SELECT payload FROM jobs').fetchone()[0])['quality'], '480')
        download_quality.set_job(c, {'created': False, 'id': 'j1'}, '720')      # existing job stays
        download_quality.set_job(c, {'created': True, 'id': 'j1'}, '<script>')  # nonsense = best = untouched
        self.assertEqual(json.loads(c.execute('SELECT payload FROM jobs').fetchone()[0])['quality'], '480')

    def test_options(self):
        got = download_quality.options('pluto', lambda: dict(SOURCE), FETCH)
        self.assertEqual([l['height'] for l in got['levels']], [1080, 720, 480])
        broken = download_quality.options('rakuten', lambda: (_ for _ in ()).throw(ValueError('Sender weg')))
        self.assertEqual(broken['levels'], [])
        self.assertIn('Sender weg', broken['note'])
        self.assertTrue(download_quality.options('youtube')['note'])

    def test_download_passes_the_playlist_to_ffmpeg(self):
        seen = {}
        class Fake:
            def __init__(self, args, **kw): seen['args'] = args; raise OSError('stop')
        real, downloads.subprocess.Popen = downloads.subprocess.Popen, Fake
        realtool, downloads.tool = downloads.tool, lambda name: '/usr/bin/' + name
        try:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(Exception):
                    downloads.fetch_hls(BASE, Path(d) / 'o.mkv', d, 0, lambda *a, **k: None, lambda: False, reserve=1, playlist=Path(d) / 'l.m3u8')
        finally:
            downloads.subprocess.Popen, downloads.tool = real, realtool
        args = seen['args']
        self.assertTrue(args[args.index('-i') + 1].endswith('l.m3u8'))
        self.assertNotIn('-reconnect', args)
        self.assertIn('file,http,https,tcp,tls,crypto', args)


def offer(source, title, year=None, **item):
    return {'source': source, 'title': title, 'year': year, 'item': item}


class MergeTests(unittest.TestCase):
    """Björn (12.11.2026, 0.5.61): "Ab ins Meer" (YouTube, no year, TMDB) still next to
    "Ab ins Meer: Auf der Suche nach der verlorenen Perle" (Netzkino, 2012, IMDb)."""
    LONG = 'Ab ins Meer: Auf der Suche nach der verlorenen Perle'

    def joined(self, *offers):
        return len(unified_index.merge(list(offers))) == 1 and len(unified_index.merge(list(offers)[::-1])) == 1

    def test_reference_year_proves_the_same_film(self):
        yt = offer('youtube', 'Ab ins Meer', 2023, raw_title='Ab ins Meer', duration=5400, reference={'provider': 'TMDB', 'id': '80321', 'year': 2011})
        nk = offer('netzkino', self.LONG, 2012, duration=5160, reference={'provider': 'IMDb Offline', 'id': 'tt1'})
        self.assertTrue(self.joined(yt, nk))

    def test_reference_title_proves_the_same_film(self):
        yt = offer('youtube', 'Ab ins Meer', 2023, reference={'provider': 'TMDB', 'id': '80321', 'title': 'Ab ins Meer – Auf der Suche nach der verlorenen Perle'})
        self.assertTrue(self.joined(yt, offer('netzkino', self.LONG, 2012)))

    def test_similar_description_proves_the_same_film(self):
        text = 'Kevin ist ein Fliegender Fisch und lebt im Hafen von New York, doch eines Tages landet er unfreiwillig im Aquarium eines chinesischen Restaurants.'
        self.assertTrue(self.joined(offer('youtube', 'Ab ins Meer', 2023, summary=text), offer('netzkino', self.LONG, 2012, summary=text + ' Schnell lernt er neue Freunde kennen.')))

    def test_missing_year_is_neither_contradiction_nor_proof(self):
        self.assertFalse(self.joined(offer('youtube', 'Ab ins Meer', 2023), offer('netzkino', self.LONG, 2012)))

    def test_other_works_stay_apart(self):
        self.assertFalse(self.joined(offer('youtube', 'Alien', 2020, duration=7020, reference={'provider': 'TMDB', 'id': '348', 'year': 1979}),
                                     offer('netzkino', 'Alien: Covenant', 2017, duration=7320)))
        self.assertFalse(self.joined(offer('pluto', 'Alien', 1979), offer('netzkino', 'Alien: Covenant', 2017)))
        # same year, but running times far apart
        self.assertFalse(self.joined(offer('pluto', 'Titel', 2012, duration=5400), offer('netzkino', 'Titel: Die Dokumentation', 2012, duration=2700)))
        # same database, different entries
        self.assertFalse(self.joined(offer('pluto', 'Titel', 2012, reference={'provider': 'TMDB', 'id': '1'}),
                                     offer('netzkino', 'Titel: Zwei', 2012, reference={'provider': 'TMDB', 'id': '2'})))

    def test_catalogue_rows_carry_year_and_title_of_the_reference(self):
        report = {'status': 'candidate', 'from_reference': True, 'metadata': {},
                  'references': [{'provider': 'TMDB', 'reference_id': '80321', 'eligible': True, 'year': 2011, 'title': 'Ab ins Meer'}]}
        self.assertEqual(portal_reference.summary('Animation', report)['reference'],
                         {'provider': 'TMDB', 'id': '80321', 'year': 2011, 'title': 'Ab ins Meer'})
        import portal_snapshot
        self.assertEqual(portal_snapshot.FORMAT, 2)   # stored views are rebuilt once so the rows get the fields


class WiringTests(unittest.TestCase):
    def text(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_server(self):
        s = self.text('server.py')
        for part in ("streaming.prepare(source,_play_quality(q),ROOT/'runtime'/'streams')", 'playlist=playlist', 'cleanup=playlist',
                     "'/api/playback-stats'", "'/api/download-options'", "'playback_stream'", "'live_tv_overview'"):
            self.assertIn(part, s)
        self.assertEqual(s.count("download_quality.set_job(c,result,d.get('quality'))"), 5)
        import server
        self.assertEqual(server._play_quality({'quality': ['480']}), '480')
        self.assertEqual(server._play_quality({'quality': ['../x']}), 'auto')
        self.assertEqual(server._play_quality({}), 'auto')

    def test_player(self):
        js, html = self.text('web/player.js'), self.text('web/index.html')
        self.assertIn('id="player-quality"', html)
        for part in ("quality:S.level||wish()", "atlas-play-quality", "function stepDown()", "api('playback-stats'",
                     "nativeHls()&&(wish()==='auto'||!info.ffmpeg)"):
            self.assertIn(part, js)

    def test_download_dialogue(self):
        js = self.text('web/offline_button.js')
        for part in ("function choose(ctl, title, alternatives)", "'download-options?'", "{id: pick.id, quality: pick.quality}",
                     "atlas-download-quality", "'Anbieter'"):
            self.assertIn(part, js)
        self.assertIn("{night,alternatives}", self.text('web/unified_catalog.js'))
        self.assertIn('dialog.atlas-offline-choice', self.text('web/style.css'))

    def test_live_tab_keeps_working_with_a_faulty_station(self):
        js = self.text('web/live_tv.js')
        self.assertIn("Live-Sender konnten nicht dargestellt werden", js)
        self.assertIn("Alle Sender zeigen", js)
        self.assertIn("window.atlasReportError=", self.text('web/app.js'))

    def test_packages_contain_the_new_modules(self):
        self.assertIn("'hls_variants.py','download_quality.py'", self.text('build_macos.py'))


if __name__ == '__main__':
    unittest.main()
