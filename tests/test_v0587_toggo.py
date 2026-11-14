"""0.5.87: TOGGO follows the formats of Björn's recording of www.toggo.de (13.11.2026, not signed in).

The answers below have the recorded shapes (catalogue POST with a JSON filter, series detail with
``episodes``, playout variants with licences); every value is synthetic. Nothing of the recording
itself is stored here. Not covered: a live request (toggo.de is not reachable from the build
environment) and the second page of a list (not recorded)."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hls_guard, portal_title, streaming, unified_index  # noqa: E402
import toggo, toggo_enrichment  # noqa: E402

IMG = 'https://ameepublic.imgix.net/img/%s.jpg?w=600'
NOW = 1_900_000_000.0


def node(kind, ident, u_name, title, packages, **extra):
    out = {'id': ident, 'type': kind, 'u_name': u_name, 'title': title, 'titleShort': title,
           'description': title + ' Beschreibung', 'summary': title + ' Inhalt', 'short_summary': '',
           'images': {'SeriesCover': IMG % ident, 'MovieCover': IMG % ident, 'Thumbnail': IMG % (ident + 't'),
                      'Bad': 'http://insecure.example/x.jpg'},
           'genres': ['Abenteuer', 'Allgemein'], 'related_tags': [], 'target_age_group': ['school'],
           'age_range_start': 6, 'age_range_end': 9, 'available_packages': packages, 'release_year': 0,
           'fvod_latest_end_date': None, 'catchup_latest_end_date': None, 'svod_latest_end_date': 2001189540}
    out.update(extra)
    return out


SERIES = [
    node('series', 'VSE302', 'paw-patrol--helfer-auf-vier-pfoten', 'PAW Patrol', ['svod', 'catchup'],
         target_age_group=['preschool'], age_range_start=3, season_count=2),
    node('series', 'VSE11', 'woozle-goozle', 'Woozle Goozle', ['svod', 'fvod'], season_count=1),
    node('series', 'VSE12', 'nur-abo-serie', 'Nur-Abo-Serie', ['svod']),
    node('series', 'VSE13', 'ohne-paket', 'Ohne Paket', []),
    node('audio_series', 'ASE1', 'hoerspiel', 'Hörspiel', ['fvod']),
    node('series', 'bad id', 'x', 'Kaputt', ['fvod']),
]
MOVIES = [
    node('movie', 'MOV116', 'der-kleine-drache', 'Der kleine Drache', ['svod', 'fvod'], run_length=5100, release_year=2014,
         video_audio_amee_asset_id='ASV100', original_title='Little Dragon', fvod_latest_end_date=2001189540),
    node('movie', 'MOV117', 'abo-film', 'Abo-Film', ['svod'], run_length=4800, release_year=2019, video_audio_amee_asset_id='ASV101'),
    node('movie', 'MOV118', 'zauberwald', 'Zauberwald', ['fvod'], run_length=4000, video_audio_amee_asset_id='ASV102',
         target_age_group=['preschool', 'school']),
]
EPISODES = [
    node('episode', 'VEP1', 'der-wetter-zeppelin', 'Der Wetter-Zeppelin', ['svod'], season_no=2, episode_no=5, run_length=660,
         video_audio_amee_asset_id='ASV200', series_uname='paw-patrol--helfer-auf-vier-pfoten'),
    node('episode', 'VEP2', "rock'n'pfote", "Rock'n'Pfote", ['svod', 'catchup'], season_no=1, episode_no=3, run_length=700,
         video_audio_amee_asset_id='ASV201', catchup_latest_end_date=NOW + 5 * 86400),
    node('episode', 'VEP3', 'ohne-nummer', 'Ohne Nummer', ['svod'], run_length=600, video_audio_amee_asset_id='ASV202'),
    node('marketing', 'VMK1', 'trailer', 'Trailer', ['fvod']),
]
PROTECTED = [
    {'name': 'dashsd', 'licenses': [{'type': 'WIDEVINE', 'variant': 'x'}, {'type': 'PLAYREADY', 'variant': 'x'}],
     'sources': [{'url': 'https://vod.example.net/a/1-sd.ism/v1.mpd'}]},
    {'name': 'dashhd', 'licenses': [{'type': 'WIDEVINE', 'variant': 'x'}], 'sources': [{'url': 'https://vod.example.net/a/1-hd.ism/v1.mpd'}]},
    {'name': 'hlsfairplayhd', 'licenses': [{'type': 'FAIRPLAY', 'variant': 'x'}], 'sources': [{'url': 'https://vod.example.net/a/1-hd.ism/v1.m3u8'}]},
    {'name': 'hlsfairplaysd', 'licenses': [{'type': 'FAIRPLAY', 'variant': 'x'}], 'sources': [{'url': 'https://vod.example.net/a/1-sd.ism/v1.m3u8'}]},
]
PLAIN = PROTECTED[:2] + [{'name': 'hlshd', 'licenses': [], 'sources': [{'url': 'https://vod.example.net/a/plain.m3u8'}]}]


def answer(data):
    return json.dumps({'success': True, 'data': data, 'err': None}).encode()


class Site:
    """Answers like production-n.toggo.de and the playout service; records every request."""
    series, movies, episodes, variants, page = SERIES, MOVIES, EPISODES, PROTECTED, None

    def __init__(self):
        self.calls = []

    def __call__(self, url, body=None):
        self.calls.append((url, body))
        parts = urllib.parse.urlsplit(url)
        if parts.hostname == 'stus.player.streamingtech.de':
            return json.dumps(self.variants).encode()
        assert parts.hostname == 'production-n.toggo.de', url
        if body is not None:
            assert parts.path == '/api/assetstore/vod/asset' and parts.query == 'expand=false', url
            kind = body['filter']['and'][0]['type'][0]
            assert body['sort'] == 'title[asc]' and body['size'] == toggo.PAGE
            items = {'series': self.series, 'movie': self.movies}[kind]
            start = body.get('offset', 0)
            part = items[start:start + self.page] if self.page else items
            return answer({'size': len(part), 'offset': start, 'total_items': len(items), 'items': part})
        assert parts.query == 'filter=rootParentTypes[not|hidden]', url
        return answer({'id': 'VSE302', 'type': 'series', 'episodes': self.episodes, 'seasons': []})


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        toggo._SOURCES.clear()

    def load(self, site=None, **kw):
        site = site or Site()
        result = toggo.sync(self.root, fetch=site, now=NOW, gap=0, **kw)
        return site, result

    def titles(self, view, **kw):
        return [r['title'] for r in toggo.listing(self.root, view, **kw)['items']]


class ParsingTests(unittest.TestCase):
    def test_item_fields(self):
        s = toggo.item_from(SERIES[0])
        self.assertEqual((s['id'], s['kind'], s['path'], s['offer'], s['ages'], s['rating'], s['seasons']),
                         ('s.VSE302', 'series', 'paw-patrol--helfer-auf-vier-pfoten', 'free', 'preschool', 'ab 3', 2))
        self.assertEqual(s['poster'], IMG % 'VSE302')
        self.assertEqual(s['web_url'], 'https://www.toggo.de/videos/serien/paw-patrol--helfer-auf-vier-pfoten')
        self.assertIsNone(s['year'])                                # release_year 0 = unknown
        m = toggo.item_from(MOVIES[0])
        self.assertEqual((m['id'], m['duration'], m['year'], m['video_id'], m['original_title']),
                         ('m.MOV116', 5100, 2014, 'ASV100', 'Little Dragon'))
        self.assertEqual(m['web_url'], 'https://www.toggo.de/sammlung/alle-filme/filme/der-kleine-drache/video/der-kleine-drache')
        self.assertEqual(m['genre'], 'Kinder, Abenteuer')

    def test_episode_needs_its_series_and_link_is_encoded(self):
        self.assertIsNone(toggo.item_from(EPISODES[1]))
        e = toggo.item_from(EPISODES[1], toggo.item_from(SERIES[0]))
        self.assertEqual((e['id'], e['season'], e['episode'], e['series_id'], e['offer']), ('e.VEP2', 1, 3, 's.VSE302', 'free'))
        self.assertEqual(e['web_url'], 'https://www.toggo.de/videos/serien/paw-patrol--helfer-auf-vier-pfoten/folge/rock%27n%27pfote')
        self.assertEqual(e['until'], NOW + 5 * 86400)

    def test_other_types_and_titles_without_package_are_skipped(self):
        for bad in (SERIES[3], SERIES[4], SERIES[5], EPISODES[3], None, 'x', {}):
            self.assertIsNone(toggo.item_from(bad))

    def test_offer(self):
        self.assertEqual(toggo.offer({'available_packages': ['svod']}), 'plus')
        self.assertEqual(toggo.offer({'available_packages': ['svod', 'catchup']}), 'free')
        self.assertEqual(toggo.offer({'available_packages': None}), '')

    def test_images_only_from_toggo_hosts(self):
        self.assertEqual(toggo.image('http://ameepublic.imgix.net/a.jpg'), '')
        self.assertEqual(toggo.image('https://evil.example/a.jpg'), '')
        self.assertEqual(toggo.image('https://ameepublic.imgix.net:8443/a.jpg'), '')

    def test_request_as_the_website_sends_it(self):
        self.assertEqual(toggo.list_body('movie'), {'filter': {'and': [{'type': ['movie']}]}, 'sort': 'title[asc]', 'size': 500})
        self.assertEqual(toggo.list_body('series', 500)['offset'], 500)
        head = toggo.headers(True)
        self.assertEqual((head['x-authorized-user'], head['x-paid-user'], head['x-platform-type'], head['Content-Type']),
                         ('false', 'false', 'Web', 'application/json'))
        self.assertFalse([k for k in head if k.lower() in ('cookie', 'authorization', 'x-device-id')])

    def test_only_fixed_hosts_are_fetched(self):
        for url in ('http://production-n.toggo.de/api/x', 'https://evil.example/api', 'https://production-n.toggo.de:8443/x',
                    'https://user@production-n.toggo.de/x', 'https://www.toggo.de/'):
            with self.assertRaises(ValueError):
                toggo._fetch(url)

    def test_rejected_answer_is_a_clear_message(self):
        with self.assertRaises(ValueError) as ctx:
            toggo._data({'success': False, 'data': None, 'err': {'message': 'bad filter'}})
        self.assertIn('bad filter', str(ctx.exception))
        with self.assertRaises(ValueError):
            toggo._json(b'<html>')


class CatalogueTests(Fixture):
    def test_sync_loads_series_and_films(self):
        site, result = self.load()
        self.assertEqual(result, {'ok': True, 'partial': False, 'movies': 3, 'series': 3, 'plus': 2})
        self.assertEqual(self.titles('series'), ['Nur-Abo-Serie', 'PAW Patrol', 'Woozle Goozle'])
        self.assertEqual(self.titles('movies'), ['Abo-Film', 'Der kleine Drache', 'Zauberwald'])
        self.assertEqual(toggo.listing(self.root, 'live')['items'], [])
        posts = [body for url, body in site.calls if body is not None]
        self.assertEqual([b['filter']['and'][0]['type'] for b in posts], [['series'], ['movie']])

    def test_state_counts_and_protection(self):
        self.load()
        st = toggo.state(self.root)
        self.assertEqual((st['movies'], st['series'], st['plus'], st['last_result'], st['protection'], st['playable']),
                         (3, 3, 2, 'complete', 'drm', 0))
        self.assertEqual(st['protected'], 6)
        self.assertFalse(any(r['playable'] for r in toggo.listing(self.root, 'movies')['items']))

    def test_categories_and_own_filters(self):
        self.load()
        page = toggo.listing(self.root, 'movies')
        self.assertTrue(all('Kinder' in r['categories'] for r in page['items']))
        self.assertIn('Kinder', [c['genre'] for c in page['genre_counts']])
        self.assertNotIn('Nur mit Abo', [c['genre'] for c in page['genre_counts']])   # offer is no category
        self.assertEqual(self.titles('movies', genre='Kostenlos'), ['Der kleine Drache', 'Zauberwald'])
        self.assertEqual(self.titles('movies', genre='Nur mit Abo'), ['Abo-Film'])
        self.assertEqual(self.titles('movies', genre='TOGGOLINO'), ['Zauberwald'])
        self.assertEqual(self.titles('series', genre='TOGGOLINO'), ['PAW Patrol'])
        self.assertEqual(self.titles('series', genre='TOGGO'), ['Nur-Abo-Serie', 'Woozle Goozle'])
        self.assertEqual(self.titles('movies', query='little'), ['Der kleine Drache'])     # original title
        badges = {r['title']: r['badge'] for r in page['items']}
        self.assertEqual((badges['Abo-Film'], badges['Zauberwald']), ('Nur mit Abo', 'kostenlos'))
        self.assertEqual(self.titles('movies', sort='year')[0], 'Abo-Film')

    def test_paging_with_offset_when_one_answer_is_not_enough(self):
        class Paged(Site):
            page = 2
        site, result = self.load(Paged())
        self.assertEqual((result['ok'], result['partial'], result['series'], result['movies']), (True, False, 3, 3))
        offsets = [b.get('offset', 0) for _, b in site.calls if b and b['filter']['and'][0]['type'] == ['series']]
        self.assertEqual(offsets, [0, 2, 4])

    def test_ignored_offset_ends_as_partial_instead_of_looping(self):
        class Stuck(Site):
            def __call__(self, url, body=None):
                if body is not None and body['filter']['and'][0]['type'] == ['series']:
                    self.calls.append((url, body))
                    return answer({'size': 2, 'offset': 0, 'total_items': 6, 'items': SERIES[:2]})
                return super().__call__(url, body)
        site, result = self.load(Stuck())
        self.assertEqual((result['ok'], result['partial'], result['series']), (True, True, 2))
        self.assertEqual(len([1 for _, b in site.calls if b and b['filter']['and'][0]['type'] == ['series']]), 2)
        self.assertEqual(toggo.state(self.root)['last_result'], 'partial')

    def test_films_failing_gives_partial_catalogue(self):
        class NoFilms(Site):
            def __call__(self, url, body=None):
                if body is not None and body['filter']['and'][0]['type'] == ['movie']:
                    raise urllib.error.HTTPError(url, 500, 'x', {}, None)
                return super().__call__(url, body)
        _, result = self.load(NoFilms())
        self.assertEqual((result['ok'], result['partial'], result['movies']), (True, True, 0))
        self.assertIn('Filme', toggo.state(self.root)['last_error'])

    def test_unreachable_site_keeps_the_stored_catalogue(self):
        self.load()

        def down(url, body=None):
            raise urllib.error.HTTPError(url, 403, 'x', {}, None)
        result = toggo.sync(self.root, fetch=down, now=NOW + 100, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('HTTP 403', result['error'])
        st = toggo.state(self.root)
        self.assertEqual((st['last_result'], st['last_http_status'], st['series']), ('failed', 403, 3))
        self.assertEqual(len(self.titles('series')), 3)

    def test_empty_answer_is_a_clear_failure(self):
        class Empty(Site):
            series = []
        _, result = self.load(Empty())
        self.assertEqual(result, {'ok': False, 'error': 'TOGGO lieferte keine Serien'})

    def test_second_run_hides_vanished_titles(self):
        self.load()

        class Smaller(Site):
            series = SERIES[1:]
        toggo.sync(self.root, fetch=Smaller(), now=NOW + 86400, gap=0)
        self.assertEqual(self.titles('series'), ['Nur-Abo-Serie', 'Woozle Goozle'])

    def test_episodes_in_one_request_and_cached(self):
        site, _ = self.load()
        before = len(site.calls)
        data = toggo.episodes(self.root, 's.VSE302', fetch=site, now=NOW)
        self.assertEqual(len(site.calls), before + 1)
        self.assertTrue(site.calls[-1][0].endswith('/vod/asset/paw-patrol--helfer-auf-vier-pfoten?filter=rootParentTypes[not|hidden]'))
        self.assertEqual([(r['season'], r['episode'], r['title']) for r in data['items']],
                         [(1, 3, "Rock'n'Pfote"), (2, 5, 'Der Wetter-Zeppelin'), (None, None, 'Ohne Nummer')])
        self.assertEqual(data['note'], '1 von 3 Folgen sind bei TOGGO kostenlos, die übrigen nur mit Abo.')
        self.assertEqual([r['badge'] for r in data['items']][1:], ['Nur mit Abo', 'Nur mit Abo'])
        self.assertTrue(data['items'][0]['badge'].startswith('kostenlos'))
        self.assertFalse(any(r['playable'] for r in data['items']))
        self.assertTrue(all(r['poster'] for r in data['items']))
        toggo.episodes(self.root, 's.VSE302', fetch=site, now=NOW + 60)
        self.assertEqual(len(site.calls), before + 1)                                # six hours from the store
        toggo.episodes(self.root, 's.VSE302', fetch=site, now=NOW + 7 * 3600)
        self.assertEqual(len(site.calls), before + 2)

    def test_episode_error_keeps_the_stored_episodes(self):
        site, _ = self.load()
        toggo.episodes(self.root, 's.VSE302', fetch=site, now=NOW)

        def down(url, body=None):
            raise urllib.error.URLError('down')
        data = toggo.episodes(self.root, 's.VSE302', fetch=down, now=NOW + 7 * 3600)
        self.assertEqual(len(data['items']), 3)
        self.assertIn('TOGGO ist nicht erreichbar', data['error'])
        for bad in ('m.MOV116', 's.VSE9999', 'x', ''):
            with self.assertRaises(ValueError):
                toggo.episodes(self.root, bad, fetch=site)

    def test_store_of_the_first_version_is_replaced(self):
        db = sqlite3.connect(str(self.root / 'toggo.sqlite3'))
        db.executescript("CREATE TABLE toggo_items(id TEXT PRIMARY KEY, title TEXT);INSERT INTO toggo_items VALUES('s.0123456789abcdef','Alt');"
                         "CREATE TABLE toggo_state(name TEXT PRIMARY KEY, value TEXT NOT NULL);INSERT INTO toggo_state VALUES('series','99');"
                         "CREATE TABLE toggo_reference_checks(item_id TEXT PRIMARY KEY, checked REAL, identity TEXT, payload TEXT);")
        db.commit()
        db.close()
        self.assertEqual(toggo.state(self.root)['series'], 0)
        self.load()
        self.assertEqual(toggo.state(self.root)['series'], 3)
        self.assertEqual(toggo_enrichment.metrics(self.root).get('checked', 0), 0)


class PlaybackTests(Fixture):
    def test_every_recorded_variant_is_protected(self):
        self.assertEqual(toggo.pick_variant(PROTECTED), ('', 4))
        self.assertEqual(toggo.pick_variant(None), ('', 0))

    def test_protected_title_is_refused_and_remembered(self):
        site, _ = self.load()
        with self.assertRaises(hls_guard.DrmProtected) as ctx:
            toggo.play_source(self.root, 'm.MOV118', fetch=site, now=NOW)
        self.assertIn('Kopierschutz', str(ctx.exception))
        self.assertEqual(toggo.item(self.root, 'm.MOV118')['item']['drm'], 1)
        self.assertTrue(any('movie-playout-variants/superrtl/ASV102?platform=web' in url for url, _ in site.calls))

    def test_subscription_title_is_not_even_requested(self):
        site, _ = self.load()
        before = len(site.calls)
        with self.assertRaises(hls_guard.DrmProtected) as ctx:
            toggo.play_source(self.root, 'm.MOV117', fetch=site)
        self.assertIn('nur mit Abo', str(ctx.exception))
        self.assertEqual(len(site.calls), before)

    def test_no_licence_or_entitlement_request_is_ever_made(self):
        site, _ = self.load()
        toggo.episodes(self.root, 's.VSE302', fetch=site, now=NOW)
        for row_id in ('m.MOV116', 'e.VEP2'):
            with self.assertRaises(hls_guard.DrmProtected):
                toggo.play_source(self.root, row_id, fetch=site, now=NOW)
        self.assertFalse([url for url, _ in site.calls if 'entitlement' in url or 'license' in url])

    def test_plain_stream_plays_and_flips_the_catalogue(self):
        class Clear(Site):
            variants = PLAIN
        checked = []
        site, _ = self.load(Clear(), check=checked.append)
        st = toggo.state(self.root)
        self.assertEqual((st['protection'], st['protected']), ('clear', 0))
        self.assertNotIn('playable', st)
        free = {r['title']: r['playable'] for r in toggo.listing(self.root, 'movies')['items']}
        self.assertEqual(free, {'Abo-Film': 0, 'Der kleine Drache': 1, 'Zauberwald': 1})
        source = toggo.play_source(self.root, 'm.MOV116', fetch=site, check=checked.append, now=NOW)
        self.assertEqual((source['url'], source['hls'], source['provider']), ('https://vod.example.net/a/plain.m3u8', True, 'toggo'))
        self.assertTrue(checked)

    def test_playlist_that_announces_drm_counts_as_protected(self):
        class Clear(Site):
            variants = PLAIN

        def check(url):
            raise hls_guard.DrmProtected('x')
        site, _ = self.load(Clear(), check=check)
        self.assertEqual(toggo.state(self.root)['protection'], 'drm')

    def test_series_and_bad_ids(self):
        site, _ = self.load()
        with self.assertRaises(ValueError):
            toggo.play_source(self.root, 's.VSE302', fetch=site)
        for bad in ('', 'e.1', '../x', 'm.MOV999'):
            with self.assertRaises(ValueError):
                toggo.play_source(self.root, bad, fetch=site)

    def test_streaming_resolve_routes_to_toggo(self):
        with self.assertRaises(ValueError) as ctx:
            streaming.resolve(None, toggo='m.MOV999', root=self.root)
        self.assertIn('TOGGO', str(ctx.exception))


class IntegrationTests(Fixture):
    def test_title_page_models(self):
        site, _ = self.load()
        toggo.episodes(self.root, 's.VSE302', fetch=site, now=time.time())
        m = portal_title.model(self.root, 'toggo', 's.VSE302')
        self.assertEqual((m['kind'], m['title'], m['provider']), ('series', 'PAW Patrol', 'TOGGO'))
        self.assertEqual(len(m['episodes']), 3)
        self.assertFalse(any(e['offline'] or e['playable'] for e in m['episodes']))
        self.assertIn('Nur mit Abo', [e['badge'] for e in m['episodes']])
        facts = dict(m['provider_facts'])
        self.assertEqual((facts['Angebot'], facts['Bereich'], facts['Empfohlen'], facts['Staffeln laut TOGGO']),
                         ('TOGGO (Super RTL), kostenlos', 'TOGGOLINO (Vorschule)', 'ab 3 Jahren', '2'))
        film = portal_title.model(self.root, 'toggo', 'm.MOV117')
        facts = dict(film['provider_facts'])
        self.assertEqual((film['kind'], film['playable'], film['offline']['allowed']), ('movie', False, False))
        self.assertEqual(facts['Angebot'], 'TOGGO, nur mit Abo')
        self.assertIn('Kopierschutz', facts['Stream'])
        self.assertTrue(film['web_url'].startswith('https://www.toggo.de/sammlung/alle-filme/filme/abo-film/'))
        self.assertIn('Kinder', film['categories'])
        ep = portal_title.model(self.root, 'toggo', 'e.VEP2')
        self.assertEqual((ep['kind'], ep['series']['title']), ('episode', 'PAW Patrol'))
        self.assertIn('Kostenlos bis', dict(ep['provider_facts']))

    def test_reference_spec_and_merged_index(self):
        self.load()
        self.assertEqual(toggo_enrichment.SPEC.items, 'toggo_assets')
        self.assertEqual(len(toggo_enrichment.pending(self.root, 20)), 6)
        for view, n in (('series', 3), ('movies', 3)):
            offers, _ = unified_index._portal_offers('toggo', toggo.listing, self.root, view, '', '', '')
            self.assertEqual(len(offers), n)

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        panel = (ROOT / 'web' / 'portal_panel.js').read_text(encoding='utf-8')
        catalog = (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8')
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        self.assertIn("'/toggo.js'", server)
        for needle in ('id="toggo-view-movies"', 'id="toggo-view-series"', 'id="toggo-pick"', 'data-platform="toggo"'):
            self.assertIn(needle, html)
        self.assertIn("$(P + '-pick')", panel)
        self.assertNotIn('seriesOnly', panel)
        self.assertNotIn("kind!=='movies';   // TOGGO", catalog)
        for name in ('toggo.py', 'toggo_enrichment.py'):
            self.assertIn("'%s'" % name, build)
        self.assertTrue((ROOT / 'web' / 'toggo.js').is_file())


if __name__ == '__main__':
    unittest.main()
