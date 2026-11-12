"""0.5.51: Rakuten TV (free films, series and live channels). Answers have the shape recorded in
Björn's HAR (12.11.2026, gizmo.rakuten.tv/v3); values are synthetic. Free films and episodes are
delivered only with Widevine/PlayReady (HAR), so they get catalogue, title page and the official
link, never the player or an offline copy; live channels are plain HLS and play live."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hls_guard, portal_title, streaming  # noqa: E402
import rakuten as rk, rakuten_downloads as rd, rakuten_enrichment as re_  # noqa: E402
import netzkino_downloads as nd  # noqa: E402

IMG = 'https://images-2.rakuten.tv/storage/global-movie/translation/artwork/%s.jpeg'
AVOD = {'purchase_types': [{'type': 'purchase_types', 'id': '5', 'name': 'AVOD', 'label': 'Kostenlos mit Anzeigen', 'kind': 'avod'}]}
IMDB = {'type': 'sites', 'id': '1', 'name': 'IMDb', 'scale': 10}


def movie(slug, title, year, genres=('Drama',), score=7.1, labels=AVOD):
    return {'type': 'movies', 'id': slug, 'numerical_id': 1, 'title': title, 'short_plot': title + ' Inhalt',
            'year': year, 'duration': 99, 'label': 'Kostenlos',
            'classification': {'type': 'classifications', 'id': '30', 'name': 'FSK 16', 'age': 16},
            'images': {'artwork': IMG % slug, 'snapshot': IMG % (slug + '-s')},
            'highlighted_score': {'score': score, 'amount_of_votes': 3574, 'site': IMDB},
            'labels': labels, 'genres': [{'type': 'genres', 'id': g.lower(), 'name': g} for g in genres]}


def show(slug, title):
    return {'type': 'tv_shows', 'id': slug, 'title': title, 'short_plot': 'Serie', 'label': '9',
            'classification': {'name': 'FSK 12'}, 'images': {'artwork': IMG % slug},
            'highlighted_score': {'score': 8.1, 'amount_of_votes': 18000, 'site': IMDB},
            'labels': AVOD, 'number_of_seasons': 2, 'genres': [{'name': 'Krimi'}]}


def first_page(ident, entries, pages):
    return {'data': {'type': 'lists', 'id': ident, 'category': 'avod', 'name': 'KOSTENLOS | Alle',
                     'contents': {'data': entries, 'meta': {'pagination': {'page': 1, 'per_page': 24, 'total_pages': pages}}}}}


def channel(slug, title, number, program='Tagesschau'):
    return {'type': 'live_channels', 'id': slug, 'title': title, 'channel_number': number,
            'classification': {'name': 'FSK 6'}, 'images': {'artwork': IMG % slug},
            'labels': {'tags': [{'type': 'tags', 'name': 'Nachrichten'}]},
            'live_programs': [{'type': 'live_programs', 'title': program, 'starts_at': '2026-11-12T16:45:01.000+01:00',
                               'ends_at': '2026-11-12T17:00:00.000+01:00'}]}


NOW = 1794498600.0   # 12.11.2026 16:50 CET, inside the programme above
PAID = {'purchase_types': [{'kind': 'tvod'}]}
ANSWERS = {
    'lists/free-all-movies': first_page('free-all-movies', [movie('fortress', 'Fortress', 2021), movie('kauf', 'Kauffilm', 2020, labels=PAID)], 2),
    ('lists/free-all-movies/contents', 2): {'data': [movie('meet-dave', 'Meet Dave', 2008, ('Komödien',), 5.1)],
                                            'meta': {'pagination': {'page': 2, 'total_pages': 2}}},
    'lists/free-all-tv-shows': first_page('free-all-tv-shows', [show('z-nation', 'Z Nation')], 1),
    ('live_channels', 1): {'data': [channel('france-24-en', 'France 24', 910)], 'meta': {'pagination': {'page': 1, 'total_pages': 2}}},
    ('live_channels', 2): {'data': [channel('top-movies-rakuten-tv', 'Top Movies', 5)], 'meta': {'pagination': {'page': 2, 'total_pages': 2}}},
    'tv_shows/z-nation/current_season': {'data': {'type': 'seasons', 'id': 'z-nation-1', 'numerical_id': 1}},
    'seasons/z-nation-1': {'data': {'type': 'seasons', 'id': 'z-nation-1', 'number': 1, 'title': 'Staffel 1',
                                    'other_seasons': [{'type': 'seasons', 'id': 'z-nation-2', 'title': 'Staffel 2'}],
                                    'episodes': [{'type': 'episodes', 'id': 'z-nation-1-1', 'number': 1, 'season_number': 1,
                                                  'title': 'Welpen und Kätzchen', 'duration': 43, 'year': 2014, 'short_plot': 'x'}]}},
    'seasons/z-nation-2': {'data': {'type': 'seasons', 'id': 'z-nation-2', 'number': 2, 'episodes': [
        {'type': 'episodes', 'id': 'z-nation-2-1', 'number': 1, 'season_number': 2, 'title': 'Zurück', 'duration': 42}]}},
}
LIVE_URL = ('https://top-movies-rakuten-tv-de.fast.rakuten.tv/v1/master/0547/production-hls-aes128-rtv-5985-playout/'
            'master.m3u8?ads.did=x&channel_id=5985')


class Api:
    def __init__(self):
        self.calls = []

    def __call__(self, path, query=None, body=None):
        query = dict(query or {})
        self.calls.append((path, query, body))
        if path == 'avod/streamings':
            assert body['content_type'] == 'live_channels' and body['player'] == 'web:HLS-NONE:NONE'
            return {'data': {'type': 'streamings', 'stream_infos': [{'player': 'web:HLS-NONE:NONE', 'url': LIVE_URL}]}}
        key = (path, query['page']) if path in ('live_channels', 'lists/free-all-movies/contents') else path
        if key not in ANSWERS:
            raise urllib.error.HTTPError('x', 404, 'nf', {}, None)
        return ANSWERS[key]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = Api()
        rk._SOURCES.clear()
        self.addCleanup(rk._SOURCES.clear)

    def sync(self, now=NOW):
        return rk.sync(self.root, request=self.api, now=now, gap=0)


class CatalogueTests(Fixture):
    def test_free_lists_paging_and_live_channels(self):
        r = self.sync()
        self.assertEqual((r['ok'], r['partial'], r['movies'], r['series'], r['channels']), (True, False, 2, 1, 2))
        first = [c for c in self.api.calls if c[0] == 'lists/free-all-movies'][0]
        self.assertEqual(first[1], {'contents[page]': 1, 'contents[per_page]': 24})
        self.assertIn(('lists/free-all-movies/contents', {'page': 2, 'per_page': 24}, None), self.api.calls)
        films = rk.listing(self.root, 'movies')['items']
        self.assertEqual([f['id'] for f in films], ['m.fortress', 'm.meet-dave'])   # rental title dropped
        f = films[0]
        self.assertEqual((f['year'], f['duration'], f['rating'], f['genre'], f['poster']),
                         (2021, 99 * 60, 'FSK 16', 'Drama', IMG % 'fortress'))
        self.assertEqual((f['web_url'], f['playable'], f['drm']), ('https://www.rakuten.tv/de/movies/fortress', 0, 1))
        self.assertEqual(f['score'], {'value': 7.1, 'source': 'IMDb', 'votes': 3574})
        live = rk.listing(self.root, 'live')['items']
        self.assertEqual([(c['id'], c['number'], c['playable'], c['category']) for c in live],
                         [('c.top-movies-rakuten-tv', 5, 1, 'Nachrichten'), ('c.france-24-en', 910, 1, 'Nachrichten')])
        self.assertEqual(live[0]['summary'], 'Jetzt: Tagesschau')
        st = rk.state(self.root)
        self.assertEqual((st['movies'], st['series'], st['channels'], st['protected'], st['last_result']), (2, 1, 2, 3, 'complete'))

    def test_failures(self):
        self.sync()
        broken = mock.Mock(side_effect=urllib.error.HTTPError('x', 403, 'no', {}, None))
        r = rk.sync(self.root, request=broken, now=NOW + 10, gap=0)
        self.assertEqual((r['ok'], r['error']), (False, 'Rakuten TV verweigert den Zugriff (HTTP 403)'))
        self.assertEqual(len(rk.listing(self.root, 'movies')['items']), 2)   # stored stock stays
        with self.assertRaisesRegex(ValueError, 'lehnte die Abfrage ab: market not available'):
            rk._data({'errors': [{'code': 'x', 'message': 'market not available'}]})

    def test_live_failure_keeps_films(self):
        def api(path, query=None, body=None):
            if path == 'live_channels':
                raise urllib.error.HTTPError('x', 500, 'err', {}, None)
            return self.api(path, query, body)
        r = rk.sync(self.root, request=api, now=NOW, gap=0)
        self.assertEqual((r['ok'], r['partial'], r['movies'], r['channels']), (True, True, 2, 0))
        self.assertIn('Live-Sender', rk.state(self.root)['last_error'])

    def test_validation(self):
        self.assertEqual(rk.image('https://evil.example/x.jpg'), '')
        self.assertEqual(rk.image('http://images-2.rakuten.tv/x.jpg'), '')
        self.assertEqual(rk.web_url('movie', '../x'), '')
        self.assertIsNone(rk.item_from({'id': 'a b', 'type': 'movies', 'title': 'x'}))
        self.assertIsNone(rk.item_from({'id': 'x', 'type': 'people', 'title': 'x'}))
        with self.assertRaises(ValueError):
            rk._request('../../etc')
        for bad in ('x.film', 'm.', 'm.A', '../m.x'):
            self.assertFalse(rk.VALID_ID.fullmatch(bad))
        self.assertEqual(rk.stream_info({'data': {'stream_infos': [{'url': 'https://evil.example/a.m3u8'}]}}), ('', ''))

    def test_series_all_seasons_on_demand(self):
        self.sync()
        data = rk.episodes(self.root, 's.z-nation', request=self.api, now=NOW + 100)
        self.assertEqual([(e['id'], e['season'], e['episode'], e['drm']) for e in data['items']],
                         [('e.z-nation-1-1', 1, 1, 1), ('e.z-nation-2-1', 2, 1, 1)])
        self.assertEqual(data['items'][0]['poster'], IMG % 'z-nation')
        before = len(self.api.calls)
        rk.episodes(self.root, 's.z-nation', request=self.api, now=NOW + 200)   # cached six hours
        self.assertEqual(len(self.api.calls), before)


class PlaybackTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()

    def test_films_and_episodes_refused_without_network(self):
        rk.episodes(self.root, 's.z-nation', request=self.api, now=NOW + 100)
        before = len(self.api.calls)
        for item in ('m.fortress', 'e.z-nation-1-1'):
            with self.assertRaisesRegex(hls_guard.DrmProtected, 'Widevine'):
                rk.play_source(self.root, item, request=self.api)
        self.assertEqual(len(self.api.calls), before)   # no stream (and no ad session) is requested
        with self.assertRaisesRegex(ValueError, 'Folge'):
            rk.play_source(self.root, 's.z-nation', request=self.api)
        with self.assertRaisesRegex(ValueError, 'nicht im Katalog'):
            rk.play_source(self.root, 'm.nope', request=self.api)

    def test_live_channel_plays_after_check(self):
        seen = []
        src = rk.play_source(self.root, 'c.top-movies-rakuten-tv', request=self.api, check=seen.append)
        self.assertEqual((src['url'], src['live'], src['hls'], src['provider'], src['title']),
                         (LIVE_URL, True, True, 'rakuten', '5 · Top Movies'))
        self.assertEqual(seen, [LIVE_URL])
        self.assertEqual(streaming.plan(src)['mode'], 'remux')
        body = [c[2] for c in self.api.calls if c[0] == 'avod/streamings'][0]
        self.assertEqual((body['content_id'], body['classification_id']), ('top-movies-rakuten-tv', '307'))
        self.assertNotIn('gdpr_consent', body)
        self.assertNotIn('ads.did', (self.root / 'rakuten.sqlite3').read_bytes().decode('latin-1'))

    def test_live_with_licence_or_protected_playlist_refused(self):
        def licensed(path, query=None, body=None):
            return {'data': {'stream_infos': [{'url': LIVE_URL, 'license_url': 'https://prod-widevine.rakuten.tv/license/x'}]}}
        with self.assertRaises(hls_guard.DrmProtected):
            rk.play_source(self.root, 'c.france-24-en', request=licensed, check=lambda u: None)
        rk._SOURCES.clear()
        protected = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"\n'
        with self.assertRaises(hls_guard.DrmProtected):
            rk.play_source(self.root, 'c.france-24-en', request=self.api,
                           check=lambda u: hls_guard.check(u, fetch=lambda x: (protected, x)))
        # Rakuten's live playlists use AES-128 with key format identity (HAR): ordinary HLS, allowed.
        plain = '#EXTM3U\n#EXT-X-KEY:KEYFORMATVERSIONS="1",METHOD=AES-128,URI="https://k.rakuten.tv/k",IV=0x1,KEYFORMAT="identity"\n'
        self.assertFalse(hls_guard.check(LIVE_URL, fetch=lambda x: (plain, x))['protected'])


class LiveTabTests(Fixture):
    def test_channels_in_live_tv_tab(self):
        import live_tv
        self.sync()
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.executescript('CREATE TABLE works(id TEXT, topic TEXT); CREATE TABLE offers(id TEXT, work_id TEXT, payload TEXT, active INT, rank INT);')
        found, errors = live_tv.channels(c, self.root)
        mine = [ch for ch in found if ch['provider'] == 'rakuten']
        self.assertEqual(errors, {})
        self.assertEqual([(ch['id'], ch['play'], ch['number'], ch['quality']) for ch in mine],
                         [('c.top-movies-rakuten-tv', {'rakuten': 'c.top-movies-rakuten-tv'}, 5, 'mit Werbung'),
                          ('c.france-24-en', {'rakuten': 'c.france-24-en'}, 910, 'mit Werbung')])
        self.assertIn(('rakuten', 'Rakuten TV'), live_tv.PROVIDERS)


class OfflineTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sync()
        rk.episodes(self.root, 's.z-nation', request=self.api, now=NOW + 100)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def test_protected_titles_and_channels_are_refused(self):
        for item, text in (('m.fortress', 'Kopierschutz'), ('e.z-nation-1-1', 'Kopierschutz'), ('s.z-nation', 'einzelne Folge'),
                           ('c.france-24-en', 'Live-Sender'), ('m.nope', 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text):
                rd.enqueue(self.c, self.root, self.media, item)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_unprotected_title_uses_shared_queue(self):
        # Should Rakuten ever publish a title without copy protection (drm=0), the shared queue takes it.
        db = rk._connect(self.root)
        with db:
            db.execute("UPDATE rakuten_items SET drm=0, playable=1 WHERE id='m.fortress'")
        db.close()
        r = rd.enqueue(self.c, self.root, self.media, 'm.fortress', now=1000)
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).as_posix(), 'Filme/Fortress (2021)/Fortress - (2021).mkv')
        self.assertEqual((job['origin'], job['rakuten_id'], job['license']['kind'], job['license']['days']),
                         ('rakuten', 'm.fortress', 'rakuten_offline', 30))
        listing = nd.listing(self.c, origin='rakuten')
        self.assertEqual((listing['offline_days'], listing['items'][0]['rakuten_id']), (30, 'm.fortress'))
        self.assertIn('Rakuten-TV', listing['policy'])


class EnrichmentAndTitleTests(Fixture):
    def test_shared_engine_and_title_pages(self):
        self.sync()

        def lookup(row, meta, settings):
            return {'candidates': [{'provider': 'IMDb Offline', 'reference_id': 'tt0765476', 'title': meta['title'], 'kind': meta['kind'],
                                    'year': meta.get('year'), 'similarity': 1.0, 'genres': ['Comedy', 'Sci-Fi'], 'rating': 5.1,
                                    'votes': 42000, 'cast': ['Eddie Murphy']}],
                    'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 1}]}
        self.assertIn('m.meet-dave', re_.pending(self.root, now=time.time()))
        self.assertNotIn('c.france-24-en', re_.pending(self.root, now=time.time()))
        report = re_.enrich(self.root, 'm.meet-dave', {}, lookup=lookup, now=time.time())
        self.assertEqual(report['status'], 'candidate')
        m = portal_title.model(self.root, 'rakuten', 'm.meet-dave')
        self.assertEqual((m['provider'], m['playable'], m['offline']['allowed'], m['cast']), ('Rakuten TV', False, False, ['Eddie Murphy']))
        self.assertEqual(m['web_url'], 'https://www.rakuten.tv/de/movies/meet-dave')
        self.assertTrue(any('Kopierschutz' in n for n in m['notes']))
        live = portal_title.model(self.root, 'rakuten', 'c.france-24-en')
        self.assertEqual((live['kind'], live['playable']), ('channel', True))
        with mock.patch.object(rk, '_request', self.api):
            s = portal_title.model(self.root, 'rakuten', 's.z-nation')
        self.assertEqual([(e['id'], e['playable'], e['offline']) for e in s['episodes']],
                         [('e.z-nation-1-1', False, False), ('e.z-nation-2-1', False, False)])


class WiringTests(unittest.TestCase):
    def test_server_ui_and_bundle(self):
        s = (ROOT / 'server.py').read_text()
        for needle in ("path=='/api/rakuten'", "'/api/rakuten-details'", "'/api/rakuten-download-add'", "'/api/rakuten-downloads'",
                       "'/api/rakuten-sync'", "'/api/rakuten-auto'", "'/api/rakuten-enrich'", 'rakuten_enrichment.loop',
                       'rakuten.loop', "rakuten=q.get('rakuten',[''])[0]", "'/rakuten.js'", "'rakuten':rakuten.state(ROOT)"):
            self.assertIn(needle, s)
        html = (ROOT / 'web' / 'index.html').read_text()
        for needle in ('id="rakuten"', 'data-platform="rakuten"', 'data-catalog-source="rakuten"', 'id="rakuten-offline-jobs"',
                       'id="rakuten-sync"', 'id="rakuten-view-live"', '<script src="/rakuten.js"></script>'):
            self.assertIn(needle, html)
        self.assertEqual(html.count('id="rakuten-items"'), 1)
        for name, needle in (('portal_title.js', 'rakuten-download-add'), ('offline_button.js', "rakuten: {name: 'Rakuten TV'"),
                             ('unified_catalog.js', "rakuten:'Rakuten TV'"), ('player.js', 'window.playRakuten'),
                             ('rakuten.js', 'live: true'), ('style.css', '#portals[data-platform="rakuten"] > #rakuten')):
            self.assertIn(needle, (ROOT / 'web' / name).read_text())
        build = (ROOT / 'build_macos.py').read_text()
        for name in ('rakuten.py', 'rakuten_downloads.py', 'rakuten_enrichment.py'):
            self.assertIn("'%s'" % name, build)
        self.assertIn('gizmo.rakuten.tv', (ROOT / 'netcheck.py').read_text())

    def test_ui_scripts(self):
        for name in ('rakuten.js', 'portal_panel.js', 'portal_title.js', 'offline_button.js', 'unified_catalog.js', 'player.js', 'app.js'):
            r = subprocess.run(['node', '--check', str(ROOT / 'web' / name)], capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
