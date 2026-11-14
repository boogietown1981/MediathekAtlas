"""0.5.40: JustWatch TV (own free titles, package jwt): catalogue, categories, details, playback
with DRM check, 30 days offline through the shared queue. Answers have the shape recorded in
Björn's HAR (12.11.2026); values are synthetic."""
import base64
import functools
import http.server
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import core, downloads, hls_guard, justwatch as jw, justwatch_downloads as jd, justwatch_enrichment as je  # noqa: E402
import netzkino_downloads as nd  # noqa: E402


def ext(video):
    inner = base64.urlsafe_b64encode(('https://cdndirector.dailymotion.com/cdn/manifest/video/%s.m3u8?sec=abc' % video).encode()).decode().rstrip('=')
    return 'https://apis.justwatch.com/jwtv/manifest/external/%s.SiGnAtUrE_123.m3u8' % inner


def offer(package='jwt', stream=None, path='/de/Film/Arrival'):
    return {'__typename': 'Offer', 'standardWebURL': 'https://www.justwatch.com%s?package=%s' % (path, package),
            'streamUrlExternalPlayer': stream, 'monetizationType': 'FREE',
            'package': {'shortName': package, 'clearName': 'JustWatch TV Free'}}


def node(id_, kind, title, path, year, package='jwt', stream=None, genres=(('drm', 'Drama'),), imdb=7.9, votes=750000):
    return {'__typename': 'Movie' if kind == 'MOVIE' else 'Show', 'id': id_, 'objectType': kind, 'content': {
        'title': title, 'fullPath': path, 'originalReleaseYear': year, 'shortDescription': title + ' Inhalt',
        'runtime': 116, 'ageCertification': '12', 'posterUrl': '/poster/330715857/{profile}/%s.{format}' % path.rsplit('/', 1)[1],
        'genres': [{'shortName': s, 'translation': t} for s, t in genres],
        'externalIds': {'imdbId': 'tt2543164'}, 'scoring': {'imdbScore': imdb, 'imdbVotes': votes}},
        'watchNowOffer': offer(package, stream, path)}


PAGE1 = [node('tm100', 'MOVIE', 'Arrival', '/de/Film/Arrival', 2016, stream=ext('x1'),
              genres=(('scf', 'Science-Fiction'), ('drm', 'Drama'), ('eur', 'Produziert in Europa'))),
         node('tm101', 'MOVIE', 'Kleiner Film', '/de/Film/Kleiner-Film', 2019, imdb=6.0, votes=300,
              genres=(('cmy', 'Komödien'),)),
         node('tm102', 'MOVIE', 'Plus-Film', '/de/Film/Plus-Film', 2020, package='jut')]
PAGE2 = [node('ts200', 'SHOW', 'Spy City', '/de/Serie/Spy-City', 2020, genres=(('trl', 'Mystery & Thriller'), ('war', 'Krieg & Militär')))]


def seasons_answer():
    def episode(i, number, jwt=True, stream=True):
        return {'id': 'tse%d' % i, 'content': {'title': 'Folge %d' % number, 'shortDescription': 'x', 'episodeNumber': number,
                                                 'seasonNumber': 1, 'runtime': 52},
                'offers': [offer('jwt', ext('e%d' % i) if stream else None, '/de/Serie/Spy-City')] if jwt else []}
    return {'data': {'urlV2': {'node': {'id': 'ts200', 'seasons': [{'id': 'tss1', 'content': {'seasonNumber': 1}, 'episodes': [
        episode(301, 1), episode(302, 2, stream=False), episode(303, 3, jwt=False)]}]}}}}


class Api:
    def __init__(self):
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query.split('(')[0].split()[-1], variables))
        if 'popularTitles' in query:
            assert variables['filter']['packages'] == ['jwt'] and variables['watchNowFilter']['packages'] == ['jwt']
            first = not variables['after']
            edges = [{'cursor': str(i), 'node': n} for i, n in enumerate(PAGE1 if first else PAGE2)]
            return {'data': {'popularTitles': {'edges': edges, 'totalCount': 4,
                                               'pageInfo': {'endCursor': 'NDA=' if first else 'ODA=', 'hasNextPage': first}}}}
        if 'seasons' in query:
            return seasons_answer()
        if 'watchNowOffer' in query:
            return {'data': {'urlV2': {'node': {'id': 'tm100', 'watchNowOffer': offer('jwt', ext('fresh')), 'offers': []}}}}
        raise AssertionError(query)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = Api()
        jw._SOURCES.clear()
        self.addCleanup(jw._SOURCES.clear)

    def sync(self, now=1000):
        return jw.sync(self.root, post=self.api, now=now, gap=0)


class CatalogueTests(Fixture):
    def test_only_own_free_titles_with_paging(self):
        result = self.sync()
        self.assertEqual((result['ok'], result['movies'], result['series'], result['playable']), (True, 2, 1, 1))
        self.assertEqual([c[0] for c in self.api.calls], ['MediathekAtlasJustWatchTv'] * 2)
        self.assertEqual(self.api.calls[1][1]['after'], 'NDA=')
        films = jw.listing(self.root, 'movies')
        self.assertEqual([f['title'] for f in films['items']], ['Arrival', 'Kleiner Film'])   # Plus title dropped
        arrival = films['items'][0]
        self.assertEqual(arrival['poster'], 'https://images.justwatch.com/poster/330715857/s718/Arrival.jpg')
        self.assertEqual(arrival['web_url'], 'https://www.justwatch.com/de/Film/Arrival?package=jwt')
        self.assertEqual((arrival['duration'], arrival['imdb_id'], arrival['playable']), (116 * 60, 'tt2543164', 1))
        self.assertEqual(arrival['genre'], 'Science-Fiction, Drama')    # "Produziert in Europa" ignored
        self.assertEqual(arrival['categories'], ['Drama', 'Science-Fiction'])
        self.assertEqual(arrival['score'], {'value': 7.9, 'source': 'IMDb', 'votes': 750000})
        self.assertEqual(jw.listing(self.root, 'movies', collection='cinema')['total'], 1)
        series = jw.listing(self.root, 'series')['items'][0]
        self.assertEqual(series['categories'], ['Krieg', 'Mystery', 'Thriller'])
        # No stream address is stored anywhere in the database.
        dump = '\n'.join(sqlite3.connect(self.root / 'justwatch.sqlite3').iterdump())
        self.assertNotIn('manifest/external', dump)

    def test_failed_run_keeps_stock(self):
        self.sync()
        def down(*a):
            raise OSError('offline')
        result = jw.sync(self.root, post=down, now=2000, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('nicht erreichbar', result['error'])
        self.assertEqual(jw.listing(self.root, 'movies')['total'], 2)

    def test_graphql_error_is_reported(self):
        result = jw.sync(self.root, post=lambda q, v: {'errors': [{'message': 'Cannot query field'}]}, now=1, gap=0)
        self.assertIn('lehnte die Abfrage ab', result['error'])

    def test_episodes_only_from_justwatch_tv(self):
        self.sync()
        data = jw.episodes(self.root, 'ts200', post=self.api, now=1500)
        self.assertEqual([(e['id'], e['season'], e['episode'], e['playable']) for e in data['items']],
                         [('tse301', 1, 1, 1), ('tse302', 1, 2, 0)])
        self.assertEqual(data['items'][0]['categories'], ['Krieg', 'Mystery', 'Thriller'])
        detail = jw.item(self.root, 'tse301')
        self.assertEqual((detail['series']['title'], detail['item']['web_url']),
                         ('Spy City', 'https://www.justwatch.com/de/Serie/Spy-City?package=jwt'))

    def test_address_validation(self):
        self.assertTrue(jw.stream_url(ext('a')))
        for bad in ('http://apis.justwatch.com/jwtv/manifest/external/abcdefghij.m3u8',
                    'https://evil.example/jwtv/manifest/external/abcdefghij.m3u8',
                    'https://apis.justwatch.com/graphql', 'https://user@apis.justwatch.com/jwtv/manifest/external/abcdefghij.m3u8'):
            self.assertEqual(jw.stream_url(bad), '', bad)
        self.assertEqual(jw.poster('https://evil.example/poster/1/s718/a.jpg'), '')
        self.assertEqual(jw.web_url('https://evil.example/de/Film/x', ''), '')


class PlaybackTests(Fixture):
    def test_fresh_stream_checked_for_drm(self):
        self.sync()
        checked = []
        src = jw.play_source(self.root, 'tm100', post=self.api, check=checked.append, now=3000)
        self.assertEqual(src['url'], ext('fresh'))
        self.assertEqual(checked, [ext('fresh')])
        self.assertEqual((src['provider'], src['hls'], src['title']), ('justwatch', True, 'Arrival (2016)'))
        with self.assertRaises(hls_guard.DrmProtected):
            jw.play_source(self.root, 'tm100', post=self.api, check=lambda u: hls_guard.check(
                u, fetch=lambda url: ('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"\n', url)))

    def test_title_without_external_stream(self):
        self.sync()
        api = lambda q, v: {'data': {'urlV2': {'node': {'watchNowOffer': offer('jwt', None), 'offers': []}}}}
        with self.assertRaisesRegex(ValueError, 'kopiergeschützten Player'):
            jw.play_source(self.root, 'tm101', post=api, check=lambda u: None)
        with self.assertRaisesRegex(ValueError, 'Folge'):
            jw.play_source(self.root, 'ts200', post=self.api, check=lambda u: None)

    def test_episode_stream_from_season_query(self):
        self.sync()
        jw.episodes(self.root, 'ts200', post=self.api, now=1500)
        jw._SOURCES.clear()
        src = jw.play_source(self.root, 'tse301', post=self.api, check=lambda u: None, now=4000)
        self.assertEqual(src['url'], ext('e301'))
        self.assertEqual(src['title'], 'Spy City · S01E01 · Folge 1')


class GuardTests(unittest.TestCase):
    def test_protection_rules(self):
        self.assertEqual(hls_guard.protection('#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n'), '')
        self.assertEqual(hls_guard.protection('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="https://k/key"\n'), '')
        self.assertEqual(hls_guard.protection('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="data:x"'), 'SAMPLE-AES')
        self.assertEqual(hls_guard.protection('#EXT-X-SESSION-KEY:METHOD=AES-128,KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",URI="x"'),
                         'urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed')

    def test_variant_is_checked(self):
        pages = {'https://a/master.m3u8': '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhd/index.m3u8\n',
                 'https://a/hd/index.m3u8': '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,URI="x"\n#EXTINF:4,\ns.ts\n'}
        with self.assertRaises(hls_guard.DrmProtected):
            hls_guard.check('https://a/master.m3u8', fetch=lambda u: (pages[u], u))
        pages['https://a/hd/index.m3u8'] = '#EXTM3U\n#EXTINF:4,\ns.ts\n'
        self.assertEqual(hls_guard.check('https://a/master.m3u8', fetch=lambda u: (pages[u], u))['variants'], 1)
        with self.assertRaisesRegex(ValueError, 'keine HLS'):
            hls_guard.check('https://a/x', fetch=lambda u: ('<html>', u))


class OfflineTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()
        jw.episodes(self.root, 'ts200', post=self.api, now=1500)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def job(self, item='tm100'):
        r = jd.enqueue(self.c, self.root, self.media, item, now=1000)
        return r, json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])

    def test_film_job_like_mediathek_with_thirty_days(self):
        r, job = self.job()
        self.assertTrue(r['created'])
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(), 'Filme/Arrival (2016)/Arrival - (2016).mkv')
        self.assertEqual((job['origin'], job['justwatch_id'], job['source']['_resolver']), ('justwatch', 'tm100', 'justwatch'))
        self.assertEqual((job['license']['kind'], job['license']['days']), ('justwatch_offline', 30))
        meta = job['metadata']
        self.assertEqual((meta['provider'], meta['imdb_id'], meta['rating'], meta['genres']),
                         ('JustWatch TV', 'tt2543164', 7.9, ['Drama', 'Science-Fiction']))
        self.assertNotIn('manifest', json.dumps(job))
        self.assertIn(b'<uniqueid type="imdb" default="true">tt2543164</uniqueid>', core.nfo(meta, [], 0))
        self.assertFalse(jd.enqueue(self.c, self.root, self.media, 'tm100')['created'])
        listing = nd.listing(self.c, origin='justwatch')
        self.assertEqual((listing['offline_days'], len(listing['items'])), (30, 1))
        self.assertIn('JustWatch-TV', listing['policy'])
        self.assertTrue(nd.is_portal(job) and nd.is_offline(job))

    def test_episode_layout_and_refusals(self):
        _, job = self.job('tse301')
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(), 'Serien/Spy City/Season 01/Spy City - S01E01.mkv')
        self.assertEqual(job['metadata']['show_imdb_id'], 'tt2543164')
        for item, text in (('ts200', 'einzelne Folge'), ('tm999', 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text):
                jd.enqueue(self.c, self.root, self.media, item)

    def test_resolver_and_public_url(self):
        _, job = self.job()
        real = jw.play_source
        with mock.patch.object(jw, 'play_source', lambda root, item: real(root, item, post=self.api, check=lambda u: None)):
            url = downloads.source_url(job['source'])
        self.assertEqual(url, ext('fresh'))
        self.assertNotIn('?', downloads.public_url(job['source'], url + '?sec=1'))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(downloads.tool('ffmpeg') and downloads.tool('ffprobe'), 'ffmpeg/ffprobe fehlen')
class HlsDownloadTests(OfflineTests):
    def test_real_hls_download(self):
        _, job = self.job()
        web = self.root / 'web'
        web.mkdir()
        subprocess.run([downloads.tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=22050', '-t', '4', '-pix_fmt', 'yuv420p',
                        '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1', '-hls_playlist_type', 'vod',
                        str(web / 'master.m3u8')], check=True)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(web)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        job['source']['duration'] = 4
        url = 'http://127.0.0.1:%d/master.m3u8?sec=secret' % server.server_address[1]
        with mock.patch.object(jd, 'resolve', return_value=url), mock.patch('artwork.save_image', return_value=True):
            downloads.run(job['source'], job['metadata'], job['root'], job['quality'], lambda *a, **k: None, lambda: False)
        target = core.existing_download(job['target'])   # 0.5.42: name + resolution/codec
        self.assertTrue(target and target.is_file())
        self.assertIn(b'tt2543164', target.with_suffix('.nfo').read_bytes())
        self.assertNotIn('secret', target.with_suffix('.metadata.json').read_text())


class EnrichmentTests(Fixture):
    def test_reference_check_uses_shared_engine(self):
        self.sync()
        calls = []

        def lookup(row, meta, settings):
            calls.append(row['channel'])
            return {'candidates': [{'provider': 'IMDb Offline', 'reference_id': 'tt2543164', 'title': meta['title'], 'kind': meta['kind'],
                                    'year': meta.get('year'), 'similarity': 1.0, 'genres': ['Drama', 'Mystery'], 'rating': 8.0,
                                    'votes': 800000, 'cast': ['Amy Adams']}],
                    'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 1}]}
        self.assertIn('tm100', je.pending(self.root, now=time.time()))
        report = je.enrich(self.root, 'tm100', {}, lookup=lookup, now=time.time())
        self.assertEqual((report['status'], calls), ('candidate', ['JustWatch TV']))
        film = jw.listing(self.root, 'movies')['items'][0]
        self.assertEqual(film['categories'], ['Drama', 'Mystery'])
        self.assertEqual(film['score']['value'], 8.0)
        self.assertEqual(je.metrics(self.root)['checked'], 1)


class WiringTests(unittest.TestCase):
    def test_server_ui_and_bundle(self):
        s = (ROOT / 'server.py').read_text()
        for needle in ("path=='/api/justwatch'", "'/api/justwatch-details'", "'/api/justwatch-download-add'",
                       "'/api/justwatch-sync'", "'/api/justwatch-enrich'", 'justwatch_enrichment.loop', 'justwatch.loop',
                       "justwatch=q.get('justwatch',[''])[0]", "'/justwatch.js'", "'/portal_panel.js'"):
            self.assertTrue(__import__('_wiring').wired(needle), needle)
        html = (ROOT / 'web' / 'index.html').read_text()
        for needle in ('id="justwatch"', 'data-platform="justwatch"', 'data-catalog-source="justwatch"',
                       '<script src="/portal_title.js"></script>', 'id="justwatch-offline-jobs"', '<script src="/justwatch.js"></script>'):
            self.assertIn(needle, html)
        self.assertNotIn('id="justwatch-view-live"', html)
        build = (ROOT / 'build_macos.py').read_text()
        for name in ('justwatch.py', 'justwatch_downloads.py', 'justwatch_enrichment.py', 'portal_enrichment.py', 'hls_guard.py'):
            self.assertIn("'%s'" % name, build)
        self.assertIn('images.justwatch.com', (ROOT / 'artwork.py').read_text())

    def test_ui_scripts(self):
        for name in ('portal_panel.js', 'justwatch.js', 'pluto.js', 'unified_catalog.js', 'player.js'):
            r = subprocess.run(['node', '--check', str(ROOT / 'web' / name)], capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
