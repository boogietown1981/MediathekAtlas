"""0.5.96: Crunchyroll as a catalogue with links (subscription only since 1.1.2026, Widevine streams).

The answers below follow the shapes of Crunchyroll's public web API (discover/browse, cms seasons and
episodes, movie_listings, auth/v1/token) as used by yt-dlp up to 2024.12; every value is synthetic.
Not covered: a live request (crunchyroll.com is blocked in the build environment) and Cloudflare's
real behaviour towards Python clients."""
import io
import json
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hls_guard, platform_registry, portal_title, streaming, unified_index, youtube  # noqa: E402
import crunchyroll, crunchyroll_enrichment  # noqa: E402

NOW = 1_900_000_000.0


def img(name, w):
    return {'source': 'https://imgsrv.crunchyroll.com/cdn-cgi/image/width=%d/catalog/crunchyroll/%s.jpg' % (w, name),
            'width': w, 'height': int(w * 1.5), 'type': 'poster_tall'}


def series(ident, title, slug, cats, audio, subs, rating='16', seasons=2, episodes=24):
    return {'id': ident, 'type': 'series', 'title': title, 'slug_title': slug, 'description': title + ' Beschreibung',
            'images': {'poster_tall': [[img(ident, 60), img(ident, 480), img(ident, 1560)]],
                       'poster_wide': [[{'source': 'http://insecure.example/x.jpg', 'width': 480}]]},
            'series_metadata': {'season_count': seasons, 'episode_count': episodes, 'series_launch_year': 2019,
                                'maturity_ratings': [rating], 'tenant_categories': cats,
                                'audio_locales': audio, 'subtitle_locales': subs, 'is_mature': False}}


SERIES = [
    series('GY19NQ2QR', 'Frieren', 'frieren', ['Adventure', 'Fantasy', 'Drama'], ['ja-JP', 'de-DE'], ['de-DE', 'en-US']),
    series('GR751KNZY', 'Attack on Titan', 'attack-on-titan', ['Action', 'Drama'], ['ja-JP'], ['de-DE']),
    series('GRMG8ZQZR', 'Englisch only', 'english-only', ['Comedy'], ['ja-JP'], ['en-US']),
    {'id': 'bad id', 'type': 'series', 'title': 'Kaputt'},
    {'id': 'MU1234567', 'type': 'music_video', 'title': 'Musik'},
]
MOVIES = [
    {'id': 'G6NQ5DWZ6', 'type': 'movie_listing', 'title': 'Jujutsu Kaisen 0', 'slug_title': 'jujutsu-kaisen-0',
     'description': 'Film', 'images': {'poster_tall': [[img('G6NQ5DWZ6', 480)]]},
     'movie_listing_metadata': {'movie_release_year': 2021, 'duration_ms': 6_000_000, 'is_premium_only': True,
                                'maturity_ratings': ['FSK 12'], 'tenant_categories': ['Action', 'Fantasy'],
                                'audio_locales': ['ja-JP', 'de-DE'], 'subtitle_locales': ['de-DE']}},
]
SEASONS = {
    'GY19NQ2QR': [{'id': 'GYE5CQNJ2', 'season_number': 1, 'title': 'Frieren Staffel 1'},
                  {'id': 'GYQ4MW246', 'season_number': 2, 'title': 'Frieren Staffel 2'}],
    'GR751KNZY': [{'id': 'GR49C7EPD', 'season_number': 1, 'title': 'Attack on Titan'}],
}


def episode(ident, number, season, premium=True, **extra):
    out = {'id': ident, 'title': 'Folge %d' % number, 'slug_title': 'folge-%d' % number, 'description': 'Inhalt',
           'episode_number': number, 'sequence_number': number, 'season_number': season, 'duration_ms': 1_420_000,
           'is_premium_only': premium, 'audio_locale': 'ja-JP', 'subtitle_locales': ['de-DE'],
           'images': {'thumbnail': [[{'source': 'https://imgsrv.crunchyroll.com/thumb/%s.jpg' % ident, 'width': 640}]]}}
    out.update(extra)
    return out


EPISODES = {
    'GYE5CQNJ2': [episode('GRDQPM1ZY', 1, 1, premium=False), episode('GRDQPM2ZY', 2, 1)],
    'GYQ4MW246': [episode('GRDQPM3ZY', 1, 2), episode('GRDQPM4ZY', 2, 2, is_clip=True)],
    'GR49C7EPD': [episode('GR49C7E01', 1, 1), episode('GR49C7E02', 2, 1)],
}
FILMS = {'G6NQ5DWZ6': [{'id': 'G25FVD45Q', 'type': 'movie', 'title': 'Jujutsu Kaisen 0', 'slug_title': 'jujutsu-kaisen-0-movie',
                        'duration_ms': 6_000_000, 'is_premium_only': True}]}


class Site:
    """Answers like www.crunchyroll.com/content/v2; records every request."""
    page = None

    def __init__(self):
        self.calls = []

    def __call__(self, path, query=None):
        self.calls.append((path, dict(query or {})))
        if path == '/content/v2/discover/browse':
            items = SERIES + MOVIES
            start = int(query['start'])
            part = items[start:start + self.page] if self.page else items[start:]
            return {'total': len(items), 'data': part}
        parts = path.split('/')
        if path.startswith('/content/v2/cms/series/'):
            return {'total': 0, 'data': SEASONS.get(parts[5], [])}
        if path.startswith('/content/v2/cms/seasons/'):
            return {'data': EPISODES.get(parts[5], [])}
        if path.startswith('/content/v2/cms/movie_listings/'):
            return {'data': FILMS.get(parts[5], [])}
        raise AssertionError(path)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        crunchyroll._TOKEN.update(value='', expires=0.0)

    def load(self, site=None):
        site = site or Site()
        return site, crunchyroll.sync(self.root, fetch=site, now=NOW, gap=0)

    def titles(self, view, **kw):
        return [r['title'] for r in crunchyroll.listing(self.root, view, **kw)['items']]


class ParsingTests(unittest.TestCase):
    def test_series_fields(self):
        it = crunchyroll.item_from(SERIES[0])
        self.assertEqual((it['id'], it['kind'], it['title'], it['path']), ('s.GY19NQ2QR', 'series', 'Frieren', 'frieren'))
        self.assertEqual((it['seasons'], it['episodes_total'], it['year'], it['rating']), (2, 24, 2019, 'ab 16'))
        self.assertEqual(it['web_url'], 'https://www.crunchyroll.com/de/series/GY19NQ2QR/frieren')
        self.assertIn('width=480', it['poster'])
        self.assertEqual((it['offer'], it['category'], it['languages']), ('plus', 'Nur mit Abo', 'dub,sub'))
        self.assertTrue(it['genre'].startswith('Animation, Anime, Adventure'))

    def test_film_entry_links_to_search_until_its_film_is_known(self):
        it = crunchyroll.item_from(MOVIES[0])
        self.assertEqual((it['id'], it['kind'], it['duration'], it['year'], it['rating']), ('m.G6NQ5DWZ6', 'movie', 6000, 2021, 'ab 12'))
        self.assertTrue(it['web_url'].startswith('https://www.crunchyroll.com/de/search?q=Jujutsu'))

    def test_skips_other_types_bad_ids_and_insecure_images(self):
        self.assertIsNone(crunchyroll.item_from(SERIES[3]))
        self.assertIsNone(crunchyroll.item_from(SERIES[4]))
        self.assertIsNone(crunchyroll.item_from({'id': 'GRDQPM1ZY', 'type': 'episode', 'title': 'x'}))   # no series
        self.assertEqual(crunchyroll.image('http://imgsrv.crunchyroll.com/a.jpg'), '')
        self.assertEqual(crunchyroll.image('https://evil.example/a.jpg'), '')

    def test_only_explicit_free_flag_counts_as_free(self):
        s = {'id': 's.GY19NQ2QR', 'genre': 'Animation', 'rating': ''}
        self.assertEqual(crunchyroll.item_from(episode('GRDQPM1ZY', 1, 1, premium=False), s)['offer'], 'free')
        self.assertEqual(crunchyroll.item_from(episode('GRDQPM1ZY', 1, 1, premium=None), s)['offer'], 'plus')
        self.assertIsNone(crunchyroll.item_from(episode('GRDQPM1ZY', 1, 1, is_clip=True), s))

    def test_cloudflare_challenge_is_recognised(self):
        self.assertTrue(crunchyroll._cloudflare(403, {'cf-mitigated': 'challenge'}, b''))
        self.assertTrue(crunchyroll._cloudflare(403, {}, b'<title>Just a moment...</title>'))
        self.assertFalse(crunchyroll._cloudflare(403, {}, b'{"code":"forbidden"}'))
        self.assertIn('Cloudflare', crunchyroll._error(crunchyroll.Blocked(403, 'cloudflare')))
        self.assertIn('Region', crunchyroll._error(crunchyroll.Blocked(451, 'region')))

    def test_only_fixed_hosts(self):
        for bad in ('https://evil.example/content', 'http://www.crunchyroll.com/x', 'https://www.crunchyroll.com:8443/x'):
            with self.assertRaises(ValueError):
                crunchyroll._check_url(bad)


class TokenTests(Fixture):
    def test_rejected_client_falls_back_to_the_next_and_is_remembered(self):
        seen = []

        def opener(req):
            seen.append(req.get_header('Authorization'))
            if req.full_url.endswith('/auth/v1/token'):
                self.assertEqual(req.data, b'grant_type=client_id')
                self.assertTrue(req.get_header('Etp-anonymous-id'))
                if len(seen) == 1:
                    raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, io.BytesIO(b'{}'))
                return json.dumps({'access_token': 'tok', 'expires_in': 300, 'token_type': 'Bearer'}).encode()
            self.assertEqual(req.get_header('Authorization'), 'Bearer tok')
            self.assertIn('locale=de-DE', req.full_url)
            return json.dumps({'total': 0, 'data': []}).encode()

        crunchyroll._fetch('/content/v2/discover/browse', {'n': 1}, self.root, opener)
        self.assertTrue(seen[0].startswith('Basic ') and seen[1].startswith('Basic ') and seen[0] != seen[1])
        self.assertEqual(crunchyroll.state(self.root)['client'], crunchyroll.CLIENTS[1][0])
        crunchyroll._fetch('/content/v2/discover/browse', {'n': 1}, self.root, opener)   # cached token
        self.assertEqual(sum(1 for s in seen if s.startswith('Basic ')), 2)

    def test_expired_token_is_renewed_once(self):
        state = {'tokens': 0, 'gets': 0}

        def opener(req):
            if req.full_url.endswith('/auth/v1/token'):
                state['tokens'] += 1
                return json.dumps({'access_token': 'tok%d' % state['tokens'], 'expires_in': 300}).encode()
            state['gets'] += 1
            if state['gets'] == 1:
                raise urllib.error.HTTPError(req.full_url, 401, 'expired', {}, io.BytesIO(b'{}'))
            return b'{"data": []}'

        self.assertEqual(crunchyroll._fetch('/content/v2/cms/series/GY19NQ2QR/seasons', None, self.root, opener), {'data': []})
        self.assertEqual(state, {'tokens': 2, 'gets': 2})


class CatalogueTests(Fixture):
    def test_sync_loads_series_and_films(self):
        site, result = self.load()
        self.assertEqual((result['ok'], result['series'], result['movies'], result['free']), (True, 3, 1, 0))
        self.assertEqual(self.titles('series'), ['Attack on Titan', 'Englisch only', 'Frieren'])
        self.assertEqual(self.titles('movies'), ['Jujutsu Kaisen 0'])
        st = crunchyroll.state(self.root)
        self.assertEqual((st['series'], st['movies'], st['playable'], st['protection'], st['last_result']), (3, 1, 0, 'drm', 'complete'))
        self.assertIn('31.12.2025', st['note'])
        self.assertEqual(site.calls[0][1]['sort_by'], 'alphabetical')

    def test_paging(self):
        site = Site()
        site.page = 2
        _, result = self.load(site)
        self.assertEqual((result['series'], result['movies']), (3, 1))
        self.assertEqual([c[1]['start'] for c in site.calls], [0, 2, 4])

    def test_failure_keeps_the_stored_catalogue_and_names_the_cause(self):
        self.load()

        def blocked(path, query=None):
            raise crunchyroll.Blocked(403, 'cloudflare')

        result = crunchyroll.sync(self.root, fetch=blocked, now=NOW + 10, gap=0)
        self.assertFalse(result['ok'])
        self.assertIn('Cloudflare', result['error'])
        self.assertEqual(len(self.titles('series')), 3)
        self.assertEqual(crunchyroll.state(self.root)['last_result'], 'failed')

    def test_empty_answer_is_a_failure(self):
        result = crunchyroll.sync(self.root, fetch=lambda p, q=None: {'total': 0, 'data': []}, now=NOW, gap=0)
        self.assertFalse(result['ok'])

    def test_filters_offer_and_language(self):
        self.load()
        self.assertEqual(self.titles('series', genre='Deutsche Synchronfassung'), ['Frieren'])
        self.assertEqual(self.titles('series', genre='Deutsche Untertitel'), ['Attack on Titan', 'Frieren'])
        self.assertEqual(self.titles('series', genre='Kostenlos'), [])
        self.assertEqual(len(self.titles('series', genre='Nur mit Abo')), 3)
        row = crunchyroll.listing(self.root, 'series', query='Frieren')['items'][0]
        self.assertIn('Animation', row['categories'])
        self.assertEqual((row['badge'], row['playable']), ('Nur mit Abo · Deutsch', 0))

    def test_my_subscription_relabels_abo_titles(self):
        # 0.5.107, Björn: "Crunchyroll hätte ich ein Account" – only the label changes, no login data.
        import ui_prefs
        self.load()
        ui_prefs.save(self.root, {'abo_crunchyroll': True})
        row = crunchyroll.listing(self.root, 'series', query='Frieren')['items'][0]
        self.assertEqual(row['badge'], 'In deinem Abo · Deutsch')
        self.assertEqual(len(self.titles('series', genre='Nur mit Abo')), 3)   # the filter keeps its name

    def test_episodes_on_demand_mark_free_ones(self):
        site, _ = self.load()
        data = crunchyroll.episodes(self.root, 's.GY19NQ2QR', fetch=site, now=time.time())
        self.assertEqual([(e['season'], e['episode']) for e in data['items']], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual([e['offer'] for e in data['items']], ['free', 'plus', 'plus'])
        self.assertIn('1 von 3 Folgen', data['note'])
        self.assertTrue(data['items'][0]['web_url'].startswith('https://www.crunchyroll.com/de/watch/GRDQPM1ZY/'))
        self.assertEqual(self.titles('series', genre='Kostenlos'), ['Frieren'])     # series flips to free
        calls = len(site.calls)
        crunchyroll.episodes(self.root, 's.GY19NQ2QR', fetch=site, now=time.time())
        self.assertEqual(len(site.calls), calls)                                    # cached
        other = crunchyroll.episodes(self.root, 's.GR751KNZY', fetch=site, now=time.time())
        self.assertIn('nur mit Abo', other['note'])

    def test_film_entry_learns_its_watch_page(self):
        site, _ = self.load()
        item = crunchyroll.item(self.root, 'm.G6NQ5DWZ6', fetch=site)['item']
        self.assertEqual(item['web_url'], 'https://www.crunchyroll.com/de/watch/G25FVD45Q/jujutsu-kaisen-0-movie')
        self.load(site)     # next catalogue run keeps the watch page
        row = crunchyroll.listing(self.root, 'movies')['items'][0]
        self.assertTrue(row['web_url'].startswith('https://www.crunchyroll.com/de/watch/G25FVD45Q'))

    def test_never_plays(self):
        self.load()
        with self.assertRaises(hls_guard.DrmProtected):
            crunchyroll.play_source(self.root, 'e.GRDQPM1ZY')
        with self.assertRaises(hls_guard.DrmProtected):
            streaming.resolve(None, crunchyroll='m.G6NQ5DWZ6', root=self.root)
        for bad in ('', '../x', 'x.ABCDEFG'):
            with self.assertRaises(ValueError):
                crunchyroll.play_source(self.root, bad)


class IntegrationTests(Fixture):
    def test_title_page_models(self):
        site, _ = self.load()
        crunchyroll.episodes(self.root, 's.GY19NQ2QR', fetch=site, now=time.time())
        m = portal_title.model(self.root, 'crunchyroll', 's.GY19NQ2QR')
        self.assertEqual((m['kind'], m['title'], m['provider']), ('series', 'Frieren', 'Crunchyroll'))
        self.assertEqual(len(m['episodes']), 3)
        self.assertFalse(any(e['offline'] or e['playable'] for e in m['episodes']))
        facts = dict(m['provider_facts'])
        self.assertEqual(facts['Sprache'], 'Deutsche Synchronfassung, Deutsche Untertitel')
        self.assertEqual(facts['Staffeln laut Crunchyroll'], '2')
        self.assertTrue(any('YouTube' in n for n in m['notes']))
        film = portal_title.model(self.root, 'crunchyroll', 'm.G6NQ5DWZ6')
        self.assertEqual((film['kind'], film['playable'], film['offline']['allowed']), ('movie', False, False))
        self.assertIn('Widevine', dict(film['provider_facts'])['Stream'])

    def test_registry_index_and_reference(self):
        self.load()
        self.assertIn('crunchyroll', platform_registry.KEYS)
        self.assertIn(('GET', '/api/crunchyroll'), platform_registry.routes())
        self.assertNotIn(('POST', '/api/crunchyroll-download-add'), platform_registry.routes())
        self.assertEqual(crunchyroll_enrichment.SPEC.items, 'crunchyroll_titles')
        self.assertEqual(len(crunchyroll_enrichment.pending(self.root, 20)), 4)
        offers, _ = unified_index._portal_offers('crunchyroll', crunchyroll.listing, self.root, 'series', '', '', '')
        self.assertEqual(len(offers), 3)

    def test_youtube_suggests_the_official_channel_once(self):
        db = youtube._connect(self.root)
        db.close()
        refs = [s['ref'] for s in youtube.sources(self.root)]
        self.assertIn('@CrunchyrollDE', refs)
        source = next(s for s in youtube.sources(self.root) if s['ref'] == '@CrunchyrollDE')
        youtube.update_source(self.root, source['id'], 'remove')
        youtube._connect(self.root).close()
        self.assertNotIn('@CrunchyrollDE', [s['ref'] for s in youtube.sources(self.root)])

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'web' / 'browser-extension' / 'chrome' / 'manifest.json').read_text(encoding='utf-8'))
        direct = (ROOT / 'web' / 'direct_start.js').read_text(encoding='utf-8')
        self.assertIn("'/crunchyroll.js'", server)
        for needle in ('id="crunchyroll-view-movies"', 'id="crunchyroll-view-series"', 'id="crunchyroll-pick"',
                       'data-platform="crunchyroll"', 'data-catalog-source="crunchyroll"', 'src="/crunchyroll.js"'):
            self.assertIn(needle, html)
        for name in ('crunchyroll.py', 'crunchyroll_enrichment.py'):
            self.assertIn("'%s'" % name, build)
        self.assertIn('https://www.crunchyroll.com/*', manifest['content_scripts'][0]['matches'])
        self.assertIn("crunchyroll: ['www.crunchyroll.com']", direct)


if __name__ == '__main__':
    unittest.main()
