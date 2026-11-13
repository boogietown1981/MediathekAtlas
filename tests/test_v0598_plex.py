"""0.5.98: Plex – free films, series and live channels without an account.

The answers below have the shape documented by public open-source Plex clients (python-plexapi,
Kodi add-ons, FastChannels): MediaContainer with Directory / Metadata / Hub / Channel, parts with
``key``, ``container`` and, for protected titles, ``license``. Titles and keys are made up; Plex
itself is blocked in the build environment."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import hls_guard
import live_tv
import plex
import portal_title
import streaming

NOW = 1794556800


def movie(key, title, **extra):
    return {'ratingKey': key, 'type': 'movie', 'title': title, 'year': 1999, 'duration': 5400000,
            'summary': 'Ein Film.', 'thumb': 'https://metadata-static.plex.tv/%s.jpg' % key, 'slug': title.lower().replace(' ', '-'),
            'contentRating': 'de/12', 'Genre': [{'tag': 'Action'}, {'tag': 'Thriller'}],
            'Guid': [{'id': 'imdb://tt0133093'}, {'id': 'tmdb://603'}], **extra}


class FakePlex:
    """Answers of plex.tv, vod.provider.plex.tv and epg.provider.plex.tv."""

    def __init__(self, all_works=True, total=3, sections_work=True):
        self.calls, self.tokens, self.all_works, self.total = [], 0, all_works, total
        self.sections_work = sections_work
        self.refuse_token = None

    def fetch_token(self, cid):
        self.tokens += 1
        return 'tok%d' % self.tokens

    def __call__(self, url, headers, data=None, limit=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.hostname, parts.path, q, headers.get('X-Plex-Token')))
        if self.refuse_token and headers.get('X-Plex-Token') == self.refuse_token:
            raise urllib.error.HTTPError(url, 401, 'no', {}, io.BytesIO(b''))
        path = parts.path
        if path == '/library/sections' and not self.sections_work:
            raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
        if path == '/hubs':
            return self.json({'MediaContainer': {'Hub': [
                {'key': 'https://vod.provider.plex.tv/hubs/home/neu?x=1', 'more': True, 'size': 1,
                 'Metadata': [movie('top001', 'Top Film')]},
                {'key': '/hubs/home/serien', 'size': 1, 'Metadata': [
                    {'ratingKey': 'show002', 'type': 'show', 'title': 'Hub Serie', 'slug': 'hub-serie'}]}]}})
        if path == '/hubs/promoted':
            raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
        if path == '/hubs/home/neu':
            start = int(q['X-Plex-Container-Start'])
            rows = [movie('top%03d' % i, 'Top Film %d' % i) for i in range(2, 5)] if start == 1 else []
            return self.json({'MediaContainer': {'Metadata': rows}})
        if path == '/library/sections':
            return self.json({'MediaContainer': {'Directory': [{'key': 'movies-1', 'type': 'movie', 'title': 'Filme'},
                                                               {'key': '/library/sections/shows-1', 'type': 'show', 'title': 'Serien'},
                                                               {'key': 'music', 'type': 'artist'}]}})
        if path == '/library/sections/movies-1/all':
            if not self.all_works:
                raise urllib.error.HTTPError(url, 404, 'no', {}, io.BytesIO(b''))
            start = int(q['X-Plex-Container-Start'])
            rows = [movie('m%03dabc' % i, 'Film %d' % i) for i in range(self.total)][start:start + int(q['X-Plex-Container-Size'])]
            return self.json({'MediaContainer': {'totalSize': self.total, 'Metadata': rows}})
        if path == '/hubs/sections/movies-1':
            return self.json({'MediaContainer': {'Hub': [{'key': '/hubs/sections/movies-1/action', 'more': True,
                                                          'Metadata': [movie('hub001', 'Hub Film')]}]}})
        if path == '/hubs/sections/movies-1/action':
            return self.json({'MediaContainer': {'Metadata': [movie('hub002', 'Hub Film 2')]}})
        if path == '/library/sections/shows-1/all':
            return self.json({'MediaContainer': {'totalSize': 1, 'Metadata': [
                {'ratingKey': 'show001', 'type': 'show', 'title': 'Die Serie', 'year': 2010, 'slug': 'die-serie',
                 'thumb': '/library/metadata/show001/thumb', 'Genre': [{'tag': 'Drama'}]}]}})
        if path == '/library/metadata/show001/allLeaves':
            return self.json({'MediaContainer': {'Metadata': [
                {'ratingKey': 'ep0012', 'type': 'episode', 'title': 'Pilot', 'parentIndex': 1, 'index': 2, 'duration': 2400000},
                {'ratingKey': 'ep0011', 'type': 'episode', 'title': 'Anfang', 'parentIndex': 1, 'index': 1, 'duration': 2400000}]}})
        if path.startswith('/library/metadata/'):
            key = path.rsplit('/', 1)[-1]
            part = {'key': '/library/parts/%s-part.mpd' % key, 'container': 'mpd'}
            if key == 'm001abc':
                part['license'] = '/library/parts/%s/license' % key
            return self.json({'MediaContainer': {'Metadata': [{'ratingKey': key, 'Media': [{'Part': [part]}]}]}})
        if path.startswith('/library/parts/') and path.endswith('.mpd'):
            if 'm002abc' in path:
                return (b'<MPD><Period><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:edef8ba9"/></AdaptationSet></Period></MPD>', url)
            return (b'<MPD><Period><AdaptationSet mimeType="video/mp4"/></Period></MPD>', url)
        if parts.hostname == 'epg.provider.plex.tv' and path == '/lineups/plex/channels':
            return self.json({'MediaContainer': {'Channel': [
                {'id': '5e20b730f2f8d5003d739db7-abc123', 'title': 'Plex Krimi', 'thumb': 'https://provider-static.plex.tv/k.png',
                 'summary': 'Krimis rund um die Uhr', 'slug': 'plex-krimi', 'Genre': [{'tag': 'Krimi'}]},
                {'id': 'bad id', 'title': 'Kaputt'}]}})
        raise AssertionError('unexpected request ' + url)

    @staticmethod
    def json(value):
        return json.dumps(value).encode(), ''


class PlexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        plex._SOURCES.clear()
        live_tv._LAST.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, fake=None):
        fake = fake or FakePlex()
        result = plex.sync(self.root, opener=fake, fetch_token=fake.fetch_token, now=NOW)
        return fake, result

    def test_catalogue_sections_pages_and_live(self):
        fake = FakePlex(total=230)
        _, result = self.load(fake)
        self.assertEqual(result, {'ok': True, 'partial': False, 'movies': 230, 'series': 1, 'channels': 1})
        pages = [c for c in fake.calls if c[1] == '/library/sections/movies-1/all']
        self.assertEqual([c[2]['X-Plex-Container-Start'] for c in pages], ['0', '100', '200'])
        self.assertTrue(all(c[3] == 'tok1' for c in fake.calls))          # one token for the whole run
        listing = plex.listing(self.root, 'movies', limit=5)
        first = listing['items'][0]
        self.assertEqual((first['id'], first['year'], first['duration'], first['imdb_id']), ('m.m000abc', 1999, 5400, 'tt0133093'))
        self.assertEqual(first['web_url'], 'https://watch.plex.tv/de/movie/film-0')
        series = plex.listing(self.root, 'series')['items'][0]
        self.assertEqual(series['poster'], '')                              # relative image needs the token: left out
        st = plex.state(self.root)
        self.assertEqual((st['movies'], st['series'], st['channels'], st['last_result']), (230, 1, 1, 'complete'))
        self.assertNotIn('tok1', json.dumps(st))

    def test_hub_fallback_when_all_is_missing(self):
        _, result = self.load(FakePlex(all_works=False))
        self.assertTrue(result['ok'])
        self.assertEqual({r['title'] for r in plex.listing(self.root, 'movies')['items']}, {'Hub Film', 'Hub Film 2'})

    def test_top_level_hubs_when_sections_answer_404(self):
        # Björn's diagnosis 13.11.2026: /library/sections answered 404, the catalogue stayed empty.
        fake, result = self.load(FakePlex(sections_work=False))
        self.assertEqual(result, {'ok': True, 'partial': False, 'movies': 4, 'series': 1, 'channels': 1})
        self.assertIn(('vod.provider.plex.tv', '/hubs/home/neu'), [c[:2] for c in fake.calls])
        self.assertNotIn('/hubs/home/serien', [c[1] for c in fake.calls])   # complete preview, no extra page

    def test_token_renewed_once_on_401(self):
        fake = FakePlex()
        self.load(fake)
        fake.refuse_token = 'tok1'
        rows = plex.load_episodes(self.root, 's.show001', opener=fake, fetch_token=fake.fetch_token, now=NOW)
        self.assertEqual(fake.tokens, 2)
        self.assertEqual([(r['season'], r['episode']) for r in rows], [(1, 2), (1, 1)])
        data = plex.episodes(self.root, 's.show001', opener=fake, fetch_token=fake.fetch_token, now=NOW + 1)
        self.assertEqual([r['title'] for r in data['items']], ['Anfang', 'Pilot'])

    def test_play_clear_dash_protected_and_live(self):
        fake, _ = self.load(FakePlex(total=3))
        src = plex.play_source(self.root, 'm.m000abc', opener=fake, fetch_token=fake.fetch_token, now=NOW)
        self.assertEqual((src['hls'], src['remux'], src['server_only'], src['provider'], src['title']),
                         (False, True, True, 'plex', 'Film 0 (1999)'))
        self.assertTrue(src['url'].startswith('https://vod.provider.plex.tv/library/parts/m000abc-part.mpd?'))
        plan = streaming.plan(src, levels=False)
        self.assertEqual(plan['mode'], 'remux')
        self.assertNotIn('url', plan)                                       # the token stays on the server
        self.assertEqual(plex.item(self.root, 'm.m000abc')['item']['drm'], 0)
        # Licence on the part -> refused and remembered; the catalogue then shows the link.
        with self.assertRaises(hls_guard.DrmProtected):
            plex.play_source(self.root, 'm.m001abc', opener=fake, fetch_token=fake.fetch_token, now=NOW)
        # ContentProtection in the manifest -> refused as well.
        with self.assertRaises(hls_guard.DrmProtected) as caught:
            plex.play_source(self.root, 'm.m002abc', opener=fake, fetch_token=fake.fetch_token, now=NOW)
        self.assertIn('umgeht ihn nicht', str(caught.exception))
        rows = {r['id']: r for r in plex.listing(self.root, 'movies')['items']}
        self.assertEqual((rows['m.m001abc']['playable'], rows['m.m002abc']['playable'], rows['m.m000abc']['playable']), (0, 0, 1))
        self.assertEqual(plex.state(self.root)['protected'], 2)
        # A new catalogue run keeps what playback learnt.
        plex.sync(self.root, opener=fake, fetch_token=fake.fetch_token, now=NOW + 10)
        self.assertEqual(plex.item(self.root, 'm.m001abc')['item']['playable'], 0)
        # Live: HLS checked with hls_guard.
        checked = []
        live = plex.play_source(self.root, 'c.5e20b730f2f8d5003d739db7-abc123', opener=fake, fetch_token=fake.fetch_token,
                                check=checked.append, now=NOW)
        self.assertTrue(live['live'] and live['hls'])
        self.assertTrue(checked[0].startswith('https://epg.provider.plex.tv/library/parts/5e20b730f2f8d5003d739db7-abc123.m3u8?'))
        with self.assertRaises(ValueError):
            plex.play_source(self.root, 's.show001', opener=fake, fetch_token=fake.fetch_token, now=NOW)
        with self.assertRaises(ValueError):
            plex.play_source(self.root, 'm.../x', opener=fake, fetch_token=fake.fetch_token, now=NOW)

    def test_live_tv_and_title_page(self):
        self.load()
        import sqlite3
        c = sqlite3.connect(':memory:')
        c.executescript('CREATE TABLE works(id INTEGER, topic TEXT); CREATE TABLE offers(id INTEGER, work_id INTEGER, payload TEXT, active INTEGER, rank INTEGER);')
        data = live_tv.overview(c, self.root, provider='plex')
        self.assertEqual([s['name'] for s in data['stations']], ['Plex Krimi'])
        self.assertEqual(data['stations'][0]['sources'][0]['play'], {'plex': 'c.5e20b730f2f8d5003d739db7-abc123'})
        m = portal_title.model(self.root, 'plex', 'm.m000abc')
        self.assertEqual(m['offline']['allowed'], False)
        self.assertIn(['Angebot', 'Plex, kostenlos mit Werbung (ohne Konto)'], m['provider_facts'])
        self.assertTrue(m['playable'])

    def test_failure_keeps_catalogue(self):
        fake, _ = self.load()

        def down(url, headers, data=None, limit=None):
            raise urllib.error.URLError(OSError('kein Netz'))
        result = plex.sync(self.root, opener=down, fetch_token=fake.fetch_token, now=NOW + 5)
        self.assertFalse(result['ok'])
        self.assertIn('nicht erreichbar', plex.state(self.root)['last_error'])
        self.assertEqual(plex.listing(self.root, 'movies')['total'], 3)

    def test_helpers(self):
        self.assertTrue(plex.dash_protected('<cenc:ContentProtection value="cenc"/>'))
        self.assertFalse(plex.dash_protected('<MPD></MPD>'))
        self.assertEqual(plex.image('https://x.plex.tv/a.jpg?X-Plex-Token=abc'), '')
        self.assertEqual(plex.image('/library/metadata/1/thumb'), '')
        with self.assertRaises(ValueError):
            plex._open('https://evil.example/x', {})

    def test_wiring(self):
        here = Path(__file__).resolve().parent.parent
        server = (here / 'server.py').read_text(encoding='utf-8')
        for needle in ("plex=q.get('plex',[''])[0]", "'/plex.js'", "'source':'plex'"):
            self.assertIn(needle, server)
        self.assertIn("'plex.py','plex_enrichment.py'", (here / 'build_macos.py').read_text(encoding='utf-8'))
        index = (here / 'web' / 'index.html').read_text(encoding='utf-8')
        for needle in ('data-platform="plex"', 'data-catalog-source="plex"', '<section id="plex"', 'id="plex-sync"'):
            self.assertIn(needle, index)
        self.assertIn('window.playPlex', (here / 'web' / 'player.js').read_text(encoding='utf-8'))
        import platform_registry
        self.assertIn('plex', platform_registry.KEYS)


if __name__ == '__main__':
    unittest.main()
