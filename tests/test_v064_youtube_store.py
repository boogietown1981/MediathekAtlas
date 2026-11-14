"""0.6.4 (Björn, 14.11.2026): the films YouTube itself offers free with adverts ("Filme & TV").
The list comes through JustWatch's public GraphQL API (synthetic answers in the shape of
justwatch.CATALOG_QUERY); the titles are copy protected: catalogue entry with link, no own player,
no offline copy."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube as yt, youtube_downloads as yd, youtube_store as ys  # noqa: E402
from test_v0553_youtube import Api, VIDEOS, video, vid, NOW  # noqa: E402

FREE = {30: video(30, 'Der Film bei YouTube Movies', 5400, embeddable=False, channel='YouTube Movies'),
        31: video(31, 'Einbettbarer Film', 6000, channel='YouTube Movies')}


def node(n, title, *, kind='MOVIE', url=None, money='ADS', runtime=95):
    return {'node': {'id': 'tm%d' % n, 'objectType': kind,
                     'content': {'title': title, 'originalReleaseYear': 1999, 'shortDescription': 'Inhalt.', 'runtime': runtime,
                                 'ageCertification': '12', 'posterUrl': '/poster/%d/{profile}/film.{format}' % n,
                                 'genres': [{'shortName': 'act', 'translation': 'Action'}],
                                 'externalIds': {'imdbId': 'tt0133093'}, 'scoring': {'imdbScore': 8.7, 'imdbVotes': 2000000}},
                     'offers': [{'standardWebURL': url if url is not None else 'https://www.youtube.com/watch?v=' + vid(n),
                                 'monetizationType': money, 'package': {'shortName': 'yfr', 'clearName': 'YouTube Free'}}]}}


class Post:
    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        if self.fail:
            raise self.fail
        if 'packages(' in query:
            return {'data': {'packages': [{'shortName': 'yot', 'clearName': 'YouTube'}, {'shortName': 'yfr', 'clearName': 'YouTube Free'},
                                          {'shortName': 'ytp', 'clearName': 'YouTube Premium'}, {'shortName': 'nfx', 'clearName': 'Netflix'}]}}
        if not variables.get('after'):
            return {'data': {'popularTitles': {'edges': [node(30, 'Matrix'), node(99, 'Kauffilm', money='BUY'),
                                                          node(98, 'Eine Serie', kind='SHOW')],
                                               'pageInfo': {'endCursor': 'C1', 'hasNextPage': True}}}}
        return {'data': {'popularTitles': {'edges': [node(31, 'Zweiter Film'), node(97, 'Fremder Link', url='https://example.org/watch?v=' + vid(97))],
                                           'pageInfo': {'endCursor': 'C2', 'hasNextPage': False}}}}


class StoreApi(Api):
    def __call__(self, endpoint, query):
        if endpoint == 'videos':
            self.calls.append((endpoint, dict(query)))
            wanted = query['id'].split(',')
            return {'items': [v for v in list(VIDEOS.values()) + list(FREE.values()) if v['id'] in wanted]}
        return super().__call__(endpoint, query)


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        db = yt._connect(self.root)
        with db:
            db.execute('DELETE FROM youtube_sources')
        db.close()
        yt.add_source(self.root, 'https://www.youtube.com/feed/storefront?bp=kgEDCPYDogUCKAU%3D')
        self.post = Post()

    def sync(self):
        return yt.sync(self.root, request=StoreApi(), now=NOW, gap=0, store_post=self.post)

    def test_reference_and_source(self):
        self.assertEqual(yt.parse_ref('store:free'), 'store:free')
        src = yt.sources(self.root)[0]
        self.assertEqual((src['ref'], src['kind'], src['label']), ('store:free', 'movies', ys.LABEL))
        with self.assertRaisesRegex(ValueError, 'Filme'):
            yt.add_source(self.root, 'store:free', kind='music')
        self.assertEqual(ys.video_id('https://www.youtube.com/watch?v=%s&feature=x' % vid(1)), vid(1))
        self.assertEqual(ys.video_id('https://evil.example/watch?v=' + vid(1)), '')

    def test_catalogue_from_justwatch(self):
        result = self.sync()
        self.assertTrue(result['ok'], result)
        rows = {r['title']: r for r in yt.listing(self.root, 'movies')['items']}
        self.assertEqual(sorted(rows), ['Matrix', 'Zweiter Film'])       # no purchase offer, no series, no foreign link
        m = rows['Matrix']
        self.assertEqual((m['id'], m['year'], m['duration'], m['imdb_id'], m['category'], m['drm'], m['playable'], m['offline']),
                         ('v.' + vid(30), 1999, 95 * 60, 'tt0133093', ys.CHANNEL, 1, 0, 0))
        self.assertEqual(m['web_url'], yt.video_url(vid(30)))
        self.assertTrue(m['poster'].startswith('https://images.justwatch.com/poster/30/'))
        self.assertIn('kopiergeschützt', m['reason'])
        self.assertEqual(rows['Zweiter Film']['playable'], 1)             # embedding allowed -> official embedded player
        # package lookup by name: Premium is left out, the offer filter asks for FREE and ADS only
        query, variables = self.post.calls[1]
        self.assertIn('packages: ["yot", "yfr"], monetizationTypes: [FREE, ADS]', query)
        self.assertEqual(variables['filter']['monetizationTypes'], ['FREE', 'ADS'])
        src = yt.sources(self.root)[0]
        self.assertEqual((src['films'], json.loads(src['skipped'])), (2, {'ohne YouTube-Adresse bei JustWatch': 3}))

    def test_protected_titles_never_reach_own_player_or_queue(self):
        self.sync()
        yd.set_enabled(self.root, True, confirmed=True)
        self.assertEqual({r['offline'] for r in yt.listing(self.root, 'movies')['items']}, {0})
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        with self.assertRaisesRegex(ValueError, 'Kopiergeschützt'):
            yd.enqueue(c, self.root, self.root, 'v.' + vid(30))
        started = []
        with self.assertRaisesRegex(ValueError, 'Kopiergeschützt'):
            yd.play_source(self.root, 'v.' + vid(31), runner=lambda *a, **k: started.append(a))
        self.assertEqual(started, [])                                     # yt-dlp is not even started
        with self.assertRaisesRegex(ValueError, 'kopiergeschützt'):
            yt.play_info(self.root, 'v.' + vid(30))
        self.assertEqual(yt.play_info(self.root, 'v.' + vid(31))['mode'], 'embed')

    def test_justwatch_failure_is_named_and_keeps_other_sources(self):
        yt.add_source(self.root, 'https://www.youtube.com/@ParamountVault')
        self.post.fail = OSError('down')
        result = self.sync()
        self.assertTrue(result['ok'] and result['partial'], result)       # the channel is still read
        src = next(s for s in yt.sources(self.root) if s['ref'] == 'store:free')
        self.assertIn('Filme & TV: JustWatch', src['last_error'])

    def test_packages_fallback_and_wiring(self):
        self.assertEqual(ys.packages(lambda q, v: (_ for _ in ()).throw(OSError())), list(ys.KNOWN_PACKAGES))
        self.assertIn("'youtube_store.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn('youtube-store-add', (ROOT / 'web/index.html').read_text(encoding='utf-8'))
        self.assertIn("url: 'store:free'", (ROOT / 'web/youtube.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
