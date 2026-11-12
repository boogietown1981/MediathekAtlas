"""0.5.53: YouTube – complete free films and series from official channels (YouTube Data API v3,
synthetic answers in the documented shape), official embedded player, offline only after the
opt-in switch (Björn's decision 12.11.2026), download through yt-dlp."""
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portal_title  # noqa: E402
import youtube as yt, youtube_downloads as yd, youtube_enrichment as ye  # noqa: E402
import netzkino_downloads as nd  # noqa: E402

NOW = 1_800_000_000


def vid(n):
    return ('v%010d' % n)[:11]


def video(n, title, seconds, *, region=None, embeddable=True, age=False, live='none', privacy='public', channel='Paramount Vault'):
    details = {'duration': 'PT%dH%dM%dS' % (seconds // 3600, seconds % 3600 // 60, seconds % 60)}
    if region:
        details['regionRestriction'] = region
    if age:
        details['contentRating'] = {'ytRating': 'ytAgeRestricted'}
    return {'kind': 'youtube#video', 'id': vid(n),
            'snippet': {'title': title, 'description': 'Ein Film.\nhttps://example.org abonnieren!\n#film',
                        'channelTitle': channel, 'publishedAt': '2024-05-01T10:00:00Z', 'liveBroadcastContent': live,
                        'defaultAudioLanguage': 'en',
                        'thumbnails': {'high': {'url': 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % vid(n)},
                                       'maxres': {'url': 'https://i.ytimg.com/vi/%s/maxresdefault.jpg' % vid(n)}}},
            'contentDetails': details,
            'status': {'privacyStatus': privacy, 'uploadStatus': 'processed', 'embeddable': embeddable}}


UPLOADS = 'UU' + 'a' * 22
SERIES_PL = 'PLserien1234567890'
VIDEOS = {
    1: video(1, 'THE TERMINATOR | Full Movie | Paramount Vault', 6420),
    2: video(2, 'Der Pate (Ganzer Film Deutsch, HD) | Krimi | 1972', 9000),
    3: video(3, 'Trailer: Dune (2021)', 7000),
    4: video(4, 'Kurzfilm', 600),
    5: video(5, 'Geoblocked Movie', 6000, region={'blocked': ['DE']}),
    6: video(6, 'Only US Movie', 6000, region={'allowed': ['US']}),
    7: video(7, 'Not Embeddable Movie (1999)', 6000, embeddable=False),
    8: video(8, 'Adult Movie', 6000, age=True),
    9: video(9, '24/7 Movies', 0, live='live'),
    10: video(10, 'Die Serie Staffel 1 Folge 1', 1500, channel='Serienkanal'),
    11: video(11, 'Die Serie Staffel 1 Folge 2', 1500, channel='Serienkanal'),
    12: video(12, 'Private', 6000, privacy='private'),
}


class Api:
    def __init__(self):
        self.calls = []
        self.fail = {}

    def __call__(self, endpoint, query):
        self.calls.append((endpoint, dict(query)))
        if endpoint in self.fail:
            raise self.fail[endpoint]
        if endpoint == 'channels':
            if query.get('forHandle') == '@ParamountVault':
                return {'items': [{'id': 'UC' + 'a' * 22, 'snippet': {'title': 'Paramount Vault'},
                                   'contentDetails': {'relatedPlaylists': {'uploads': UPLOADS}}}]}
            return {'items': []}
        if endpoint == 'playlists':
            return {'items': [{'id': query['id'], 'snippet': {'title': 'Die Serie – alle Folgen', 'channelId': 'UC' + 'b' * 22}}]}
        if endpoint == 'playlistItems':
            ids = list(range(1, 10)) + [12] if query['playlistId'] == UPLOADS else [10, 11]
            page = 1 if 'pageToken' not in query else 2
            chunk = ids[:5] if page == 1 else ids[5:]
            answer = {'items': [{'snippet': {'position': i}, 'contentDetails': {'videoId': vid(n)}}
                                for i, n in enumerate(chunk, start=0 if page == 1 else 5)]}
            if page == 1 and len(ids) > 5:
                answer['nextPageToken'] = 'NEXT'
            return answer
        if endpoint == 'videos':
            wanted = query['id'].split(',')
            return {'items': [v for v in VIDEOS.values() if v['id'] in wanted]}
        raise AssertionError(endpoint)


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.api = Api()
        db = yt._connect(self.root)
        with db:
            db.execute('DELETE FROM youtube_sources')
        db.close()
        yt.add_source(self.root, 'https://www.youtube.com/@ParamountVault/videos')
        yt.add_source(self.root, 'youtube.com/playlist?list=' + SERIES_PL, kind='series', label='Die Serie')
        self.addCleanup(yt.configure, lambda: '')

    def sync(self):
        result = yt.sync(self.root, request=self.api, now=NOW, gap=0)
        self.assertTrue(result['ok'], result)
        return result


class ParsingTests(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(yt.clean_title('Der Pate (Ganzer Film Deutsch, HD) | Krimi | 1972'), ('Der Pate', 1972, ['Krimi'], 'Deutsch'))
        self.assertEqual(yt.clean_title('THE TERMINATOR | Full Movie | Paramount Vault', 'Paramount Vault')[0], 'The Terminator')
        self.assertEqual(yt.clean_title('Nosferatu (1922) [Horror, Stummfilm] ganzer Film')[:3], ('Nosferatu', 1922, ['Horror']))
        self.assertEqual(yt.clean_title('Hangman - Thriller (ganzer Film auf Deutsch) mit Al Pacino')[:3], ('Hangman', None, ['Thriller']))
        self.assertEqual(yt.episode_numbers('S02E05 Titel'), (2, 5))
        self.assertEqual(yt.episode_numbers('Staffel 3 – Folge 7'), (3, 7))
        self.assertEqual(yt.episode_numbers('ohne Nummer', 4), (1, 5))
        self.assertEqual(yt.duration_seconds('PT1H32M10S'), 5530)
        self.assertEqual(yt.duration_seconds('P1DT1M'), 86460)
        self.assertEqual(yt.duration_seconds('junk'), 0)

    def test_references(self):
        for text, ref in (('https://www.youtube.com/@Sony_Pictures/videos', '@Sony_Pictures'), ('@abc', '@abc'),
                          ('youtube.com/channel/UC' + 'x' * 22, 'UC' + 'x' * 22),
                          ('https://m.youtube.com/playlist?list=PL1234567890ab', 'PL1234567890ab'),
                          ('https://www.youtube.com/user/sonypictures', 'user:sonypictures')):
            self.assertEqual(yt.parse_ref(text), ref)
        for bad in ('https://evil.example/@x', 'https://www.youtube.com/c/Foo', 'x' * 400):
            with self.assertRaises(ValueError):
                yt.parse_ref(bad)
        self.assertEqual(yt.image('https://i.ytimg.com/vi/x/hq.jpg'), 'https://i.ytimg.com/vi/x/hq.jpg')
        self.assertEqual(yt.image('https://evil.example/x.jpg'), '')


class CatalogueTests(Fixture):
    def test_only_complete_available_films(self):
        result = self.sync()
        self.assertEqual((result['movies'], result['series'], result['episodes'], result['partial']), (4, 1, 2, False))
        rows = {r['path']: r for r in yt.listing(self.root, 'movies')['items']}
        # trailer, short film, geo-blocked (blocked/allowed), live stream and private video are left out
        self.assertEqual(sorted(rows), sorted(vid(n) for n in (1, 2, 7, 8)))
        pate = rows[vid(2)]
        self.assertEqual((pate['title'], pate['year'], pate['genre'], pate['language'], pate['duration']), ('Der Pate', 1972, 'Krimi', 'Deutsch', 9000))
        self.assertEqual(pate['poster'], 'https://i.ytimg.com/vi/%s/maxresdefault.jpg' % vid(2))
        self.assertEqual(pate['summary'], 'Ein Film.')
        self.assertEqual(pate['web_url'], 'https://www.youtube.com/watch?v=' + vid(2))
        self.assertEqual((rows[vid(7)]['playable'], rows[vid(8)]['playable'], rows[vid(1)]['playable']), (0, 0, 1))
        self.assertEqual(pate['offline'], 0)          # switch is off by default
        # the key is never part of a request issued by the test api; videos are read in one chunk
        self.assertEqual(sum(1 for e, _ in self.api.calls if e == 'videos'), 2)
        src = {s['ref']: s for s in yt.sources(self.root)}
        self.assertEqual((src['@ParamountVault']['films'], src['@ParamountVault']['videos'], src['@ParamountVault']['title']), (4, 10, 'Paramount Vault'))

    def test_series_and_cache(self):
        self.sync()
        series = yt.listing(self.root, 'series')['items']
        self.assertEqual([(s['id'], s['title'], s['number']) for s in series], [('s.' + SERIES_PL, 'Die Serie', 2)])
        eps = yt.episodes(self.root, 's.' + SERIES_PL)['items']
        self.assertEqual([(e['season'], e['episode'], e['playable']) for e in eps], [(1, 1, 1), (1, 2, 1)])
        self.api.calls.clear()
        yt.sync(self.root, request=self.api, now=NOW + 3600, gap=0)
        self.assertFalse([c for c in self.api.calls if c[0] in ('videos', 'channels', 'playlists')])   # week cache, resolved sources

    def test_failures_and_missing_key(self):
        result = yt.sync(self.root, now=NOW, key='')
        self.assertFalse(result['ok'])
        self.assertIn('API-Schlüssel', yt.state(self.root)['last_error'])
        self.api.fail['playlistItems'] = yt.ApiError(403, {'error': {'errors': [{'reason': 'quotaExceeded'}]}})
        result = yt.sync(self.root, request=self.api, now=NOW, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('Tageskontingent', result['error'])
        self.assertGreaterEqual(yt.state(self.root)['next_attempt'], NOW + 12 * 3600)
        self.api.fail.clear()
        yt.add_source(self.root, '@Unbekannt')
        result = yt.sync(self.root, request=self.api, now=NOW + 10, gap=0)
        self.assertTrue(result['ok'] and result['partial'])
        self.assertTrue(any(s['last_error'] == 'Kanal nicht gefunden' for s in yt.sources(self.root)))

    def test_source_management(self):
        with self.assertRaisesRegex(ValueError, 'Playlist'):
            yt.add_source(self.root, '@Kanal', kind='series')
        with self.assertRaisesRegex(ValueError, 'Mindestlänge'):
            yt.add_source(self.root, '@Kanal', min_minutes='0')
        sid = next(s['id'] for s in yt.sources(self.root) if s['ref'] == '@ParamountVault')
        self.assertFalse(next(s for s in yt.update_source(self.root, sid, 'disable') if s['id'] == sid)['enabled'])
        self.assertNotIn(sid, [s['id'] for s in yt.update_source(self.root, sid, 'remove')])
        # suggestions are seeded once only; a removed suggestion stays removed
        db = yt._connect(self.root)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM youtube_sources WHERE suggested=1").fetchone()[0], 0)
        db.close()


class PlaybackTests(Fixture):
    def test_embed_only_for_playable(self):
        self.sync()
        info = yt.play_info(self.root, 'v.' + vid(1))
        self.assertEqual((info['mode'], info['embed']), ('embed', 'https://www.youtube-nocookie.com/embed/' + vid(1)))
        for item, text in (('v.' + vid(8), 'Altersbeschränkt'), ('v.' + vid(7), 'Einbettung'),
                           ('s.' + SERIES_PL, 'Folge'), ('v.' + vid(99), 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text):
                yt.play_info(self.root, item)


class OfflineTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def test_switch_is_off_and_needs_confirmation(self):
        with self.assertRaisesRegex(ValueError, 'ausgeschaltet'):
            yd.enqueue(self.c, self.root, self.media, 'v.' + vid(2))
        with self.assertRaisesRegex(ValueError, 'bestätigen'):
            yd.set_enabled(self.root, True)
        st = yd.set_enabled(self.root, True, confirmed=True, now=5)
        self.assertEqual((st['enabled'], st['consent_at']), (True, 5))
        flags = {r['path']: r['offline'] for r in yt.listing(self.root, 'movies')['items']}
        self.assertEqual(flags[vid(8)], 0)     # age restricted: never (no sign-in)
        self.assertEqual(flags[vid(7)], 1)     # not embeddable, but storable
        yd.set_enabled(self.root, False)
        self.assertFalse(yt.state(self.root)['offline_enabled'])

    def test_job_in_shared_queue_and_title_page(self):
        yd.set_enabled(self.root, True, confirmed=True)
        r = yd.enqueue(self.c, self.root, self.media, 'v.' + vid(2), now=1000)
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(), 'Filme/Der Pate (1972)/Der Pate - (1972).mkv')
        self.assertEqual((job['origin'], job['youtube_id'], job['license']['kind'], job['license']['days'], job['source']['_resolver']),
                         ('youtube', 'v.' + vid(2), 'youtube_offline', 30, 'youtube'))
        self.assertFalse(yd.enqueue(self.c, self.root, self.media, 'v.' + vid(2))['created'])
        with self.assertRaisesRegex(ValueError, 'Altersbeschränkt'):
            yd.enqueue(self.c, self.root, self.media, 'v.' + vid(8))
        ep = yd.enqueue(self.c, self.root, self.media, 'e.' + vid(10))
        target = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (ep['id'],)).fetchone()[0])['target']
        self.assertIn('S01E01', target)
        listing = nd.listing(self.c, origin='youtube')
        self.assertEqual((listing['offline_days'], listing['items'][0]['youtube_id'] is not None), (30, True))
        self.assertIn('Nutzungsbedingungen', listing['policy'])
        m = portal_title.model(self.root, 'youtube', 'v.' + vid(2))
        self.assertEqual((m['provider'], m['playable'], m['offline']['allowed']), ('YouTube', True, True))
        yd.set_enabled(self.root, False)
        m = portal_title.model(self.root, 'youtube', 'v.' + vid(2))
        self.assertFalse(m['offline']['allowed'])
        self.assertTrue(any('Nutzungsbedingungen' in n for n in m['notes']))
        s = portal_title.model(self.root, 'youtube', 's.' + SERIES_PL)
        self.assertEqual([(e['playable'], e['offline']) for e in s['episodes']], [(True, False), (True, False)])

    def test_fetch_with_ytdlp(self):
        yd.set_enabled(self.root, True, confirmed=True)
        seen = {}

        class Proc:
            def __init__(self, args, **kw):
                seen['args'] = args
                out = Path(args[args.index('-o') + 1].replace('%(ext)s', 'mkv'))
                out.write_bytes(b'x' * 2048)
                self.stdout = io.StringIO('MAP 100 1000\nMAP 1000 1000\nMAP 50 500\nMAP 500 500\n')
                self.returncode = 0

            def wait(self):
                return 0

            def poll(self):
                return 0

            def kill(self):
                pass
        src = self.root / 'original.bin.partial'
        updates = []
        row = {'_youtube_home': str(self.root), '_video_id': vid(1)}
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')):
            size = yd.fetch(row, src, self.root, lambda *a, **k: updates.append(a), lambda: False, runner=Proc)
        self.assertEqual(size, 2048)
        self.assertTrue(src.exists())
        args = seen['args']
        for flag in ('--ignore-config', '--no-playlist', '--merge-output-format'):
            self.assertIn(flag, args)
        self.assertNotIn('--cookies', args)
        self.assertEqual(args[-1], 'https://www.youtube.com/watch?v=' + vid(1))
        self.assertIn('Bot', yd._reason("ERROR: Sign in to confirm you're not a bot"))
        self.assertIn('Altersbeschränkt', yd._reason('Sign in to confirm your age'))
        yd.set_enabled(self.root, False)
        with self.assertRaisesRegex(ValueError, 'ausgeschaltet'):
            yd.fetch(row, src, self.root, lambda *a, **k: None, lambda: False, runner=Proc)

    def test_install_checks_checksum(self):
        blob = b'#!/usr/bin/env python3\nprint(1)\n'
        good = hashlib.sha256(blob).hexdigest()
        files = {yd.RELEASE + 'SHA2-256SUMS': ('%s  yt-dlp\n%s  yt-dlp.exe\n' % (good, '0' * 64)).encode(), yd.RELEASE + 'yt-dlp': blob}
        with mock.patch('shutil.which', return_value=None), mock.patch.dict('os.environ', {'MEDIATHEKATLAS_YTDLP': ''}):
            st = yd.install_tool(self.root, fetch=files.__getitem__)
            self.assertTrue(st['tool'])
            files[yd.RELEASE + 'yt-dlp'] = b'tampered'
            with self.assertRaisesRegex(ValueError, 'Prüfsumme'):
                yd.install_tool(self.root, fetch=files.__getitem__)


class EnrichmentTests(Fixture):
    def test_shared_engine(self):
        self.sync()

        def lookup(row, meta, settings):
            return {'candidates': [{'provider': 'IMDb Offline', 'reference_id': 'tt0068646', 'title': meta['title'], 'kind': meta['kind'],
                                    'year': meta.get('year'), 'similarity': 1.0, 'genres': ['Crime', 'Drama'], 'rating': 9.2,
                                    'votes': 2000000, 'cast': ['Marlon Brando']}],
                    'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 1}]}
        self.assertIn('v.' + vid(2), ye.pending(self.root, limit=50, now=time.time()))
        report = ye.enrich(self.root, 'v.' + vid(2), {}, lookup=lookup, now=time.time())
        self.assertEqual(report['status'], 'candidate')
        row = next(r for r in yt.listing(self.root, 'movies')['items'] if r['path'] == vid(2))
        self.assertEqual(row['score']['value'], 9.2)
        m = portal_title.model(self.root, 'youtube', 'v.' + vid(2))
        self.assertEqual(m['cast'], ['Marlon Brando'])
        self.assertTrue(any(f[0] == 'YouTube-Kanal' for f in m['provider_facts']))


class WiringTests(unittest.TestCase):
    def test_server_ui_and_bundle(self):
        s = (ROOT / 'server.py').read_text()
        for needle in ("path=='/api/youtube'", "'/api/youtube-details'", "'/api/youtube-download-add'", "'/api/youtube-downloads'",
                       "'/api/youtube-sync'", "'/api/youtube-auto'", "'/api/youtube-enrich'", "'/api/youtube-sources'",
                       "'/api/youtube-key'", "'/api/youtube-offline'", "'/api/youtube-ytdlp-install'", 'youtube_enrichment.loop',
                       'youtube.loop', 'youtube.play_info', "'/youtube.js'", 'youtube.configure', "stored.get('youtube')"):
            self.assertIn(needle, s)
        html = (ROOT / 'web' / 'index.html').read_text()
        for needle in ('id="youtube"', 'data-platform="youtube"', 'data-catalog-source="youtube"', 'id="youtube-offline-switch"',
                       'id="youtube-key-form"', 'id="player-embed"', 'referrerpolicy="strict-origin-when-cross-origin"',
                       '<script src="/youtube.js"></script>'):
            self.assertIn(needle, html)
        for name, needle in (('portal_title.js', 'youtube-download-add'), ('offline_button.js', "youtube: {name: 'YouTube'"),
                             ('unified_catalog.js', "youtube:'YouTube'"), ('player.js', 'window.playYouTube'),
                             ('player.js', 'youtube-nocookie.com'), ('style.css', '#portals[data-platform="youtube"] > #youtube')):
            self.assertIn(needle, (ROOT / 'web' / name).read_text())
        build = (ROOT / 'build_macos.py').read_text()
        for name in ('youtube.py', 'youtube_downloads.py', 'youtube_enrichment.py'):
            self.assertIn("'%s'" % name, build)
        self.assertIn("_resolver')=='youtube'", (ROOT / 'downloads.py').read_text())

    def test_ui_scripts(self):
        for name in ('youtube.js', 'portal_panel.js', 'portal_title.js', 'offline_button.js', 'unified_catalog.js', 'player.js', 'app.js'):
            r = subprocess.run(['node', '--check', str(ROOT / 'web' / name)], capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
