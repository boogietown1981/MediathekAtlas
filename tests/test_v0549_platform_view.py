"""0.5.49: shared provider answers, JustWatch episodes per season, same overview in the platform tabs."""
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import justwatch  # noqa: E402
import reference_share  # noqa: E402

META = {'kind': 'movie', 'title': 'Bad Lieutenant – Cop ohne Gewissen', 'year': 2009}
ANSWER = {'candidates': [{'provider': 'IMDb', 'title': 'Bad Lieutenant', 'year': 2009, 'imdb_id': 'tt1095217'}], 'warnings': []}


class ShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_second_platform_does_not_ask_again(self):
        calls = []
        def lookup(row, meta, settings):
            calls.append(meta['title']); return dict(ANSWER)
        first = reference_share.wrap(self.root, lookup, 'JustWatch TV', now=1000)({}, dict(META), {})
        second = reference_share.wrap(self.root, lookup, 'Pluto TV', now=2000)(
            {}, {**META, 'title': 'BAD LIEUTENANT - Cop ohne Gewissen'}, {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(second['candidates'], first['candidates'])
        self.assertEqual(second['shared_from'], 'JustWatch TV')

    def test_not_shared_without_year_or_for_another_year(self):
        calls = []
        def lookup(row, meta, settings):
            calls.append(1); return dict(ANSWER)
        reference_share.wrap(self.root, lookup, 'A', now=1)({}, dict(META), {})
        reference_share.wrap(self.root, lookup, 'B', now=2)({}, {**META, 'year': 1992}, {})
        reference_share.wrap(self.root, lookup, 'B', now=3)({}, {**META, 'year': None}, {})
        reference_share.wrap(self.root, lookup, 'B', now=4)({}, {**META, 'year': None}, {})
        reference_share.wrap(self.root, lookup, 'B', now=5)({}, {**META, 'kind': 'series'}, {})
        self.assertEqual(len(calls), 5)

    def test_incomplete_answers_expiry_and_manual_recheck(self):
        calls = []
        def partial(row, meta, settings):
            calls.append(1); return {'candidates': [], 'warnings': ['provider_unavailable'], 'deferred_providers': ['TMDB']}
        reference_share.wrap(self.root, partial, 'A', now=1)({}, dict(META), {})
        self.assertIsNone(reference_share.get(self.root, META, now=2))
        def good(row, meta, settings):
            calls.append(1); return dict(ANSWER)
        reference_share.wrap(self.root, good, 'A', now=10)({}, dict(META), {})
        self.assertIsNotNone(reference_share.get(self.root, META, now=11))
        self.assertIsNone(reference_share.get(self.root, META, now=11 + reference_share.TTL + 1))
        before = len(calls)
        reference_share.wrap(self.root, good, 'B', now=12, fresh=True)({}, dict(META), {})
        self.assertEqual(len(calls), before + 1)
        self.assertEqual(reference_share.stats(self.root)['stored'], 1)

    def test_both_engines_use_the_shared_store(self):
        for name in ('portal_enrichment.py', 'netzkino_enrichment.py'):
            self.assertIn('reference_share.wrap(root', (ROOT / name).read_text(encoding='utf-8').replace('wrap(root,', 'wrap(root, '))
        self.assertIn("'reference_share.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))


def episode(n, stream=''):
    return {'id': 'tse%d' % n, 'content': {'title': 'Folge %d' % n, 'episodeNumber': n, 'seasonNumber': None, 'runtime': 42},
            'offers': [{'standardWebURL': 'https://www.justwatch.com/de/Serie/Andromeda?package=jwt',
                        'streamUrlExternalPlayer': stream or None, 'package': {'shortName': 'jwt'}}]}


class EpisodeFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        db = justwatch._connect(self.root)
        cols = 'id,kind,title,path,series_id,season,episode,year,duration,rating,genre,summary,poster,imdb_id,imdb_score,imdb_votes,playable,web_url,seen,updated'
        with db:
            db.execute('INSERT INTO justwatch_items(%s) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)' % cols,
                       ('ts10316', 'series', 'Andromeda', '/de/Serie/Andromeda', '', None, None, 2000, None, '12', 'Sci-Fi', '', '', '',
                        None, None, 0, 'https://www.justwatch.com/de/Serie/Andromeda?package=jwt', 1, 1))
        db.close()
        self.calls = []

    def api(self, combined):
        def post(query, variables):
            name = query.split('(')[0].split()[-1]
            self.calls.append((name, variables.get('fullPath'), variables.get('limit')))
            if name == 'MediathekAtlasJustWatchTvSeasons':
                return combined()
            if name == 'MediathekAtlasJustWatchTvSeasonList':
                return {'data': {'urlV2': {'node': {'id': 'ts10316', 'seasons': [
                    {'id': 'tss2', 'totalEpisodeCount': 22, 'content': {'seasonNumber': 2, 'fullPath': '/de/Serie/Andromeda/Staffel-2'}},
                    {'id': 'tss1', 'totalEpisodeCount': 22, 'content': {'seasonNumber': 1, 'fullPath': '/de/Serie/Andromeda/Staffel-1'}},
                    {'id': 'bad', 'totalEpisodeCount': 3, 'content': {'seasonNumber': 9, 'fullPath': 'https://evil.example/x'}}]}}}}
            if name == 'MediathekAtlasJustWatchTvSeason':
                if variables['limit'] != 20:
                    return {'errors': [{'message': 'limit too high'}]}
                season = 1 if variables['fullPath'].endswith('Staffel-1') else 2
                return {'data': {'urlV2': {'node': {'id': 'tss%d' % season, 'episodes': [episode(season * 100 + 1), episode(season * 100 + 2)]}}}}
            raise AssertionError(name)
        return post

    def test_refused_combined_query_falls_back_to_season_pages(self):
        post = self.api(lambda: {'errors': [{'message': 'query too complex'}]})
        data = justwatch.episodes(self.root, 'ts10316', post=post, now=5000)
        self.assertEqual(data['error'], '')
        self.assertEqual([(e['season'], e['episode']) for e in data['items']], [(1, 101), (1, 102), (2, 201), (2, 202)])
        names = [c[0] for c in self.calls]
        self.assertEqual(names[0], 'MediathekAtlasJustWatchTvSeasons')
        self.assertIn(('MediathekAtlasJustWatchTvSeason', '/de/Serie/Andromeda/Staffel-1', 20), self.calls)
        self.assertFalse(any(c[1] and 'evil' in c[1] for c in self.calls if c[0] == 'MediathekAtlasJustWatchTvSeason'))

    def test_empty_combined_answer_also_falls_back(self):
        post = self.api(lambda: {'data': {'urlV2': {'node': {'id': 'ts10316', 'seasons': []}}}})
        self.assertEqual(len(justwatch.episodes(self.root, 'ts10316', post=post, now=5000)['items']), 4)

    def test_network_failure_is_reported_once(self):
        def post(query, variables):
            self.calls.append(1); raise urllib.error.URLError('offline')
        data = justwatch.episodes(self.root, 'ts10316', post=post, now=5000)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('nicht erreichbar', data['error'])


class ViewTests(unittest.TestCase):
    def test_platform_tabs_show_the_catalogue_overview(self):
        web = ROOT / 'web'
        uc = (web / 'unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn('window.AtlasPlatformBoard={mount:mountTabBoard}', uc)
        self.assertIn('portalCard(p,true)', uc)
        self.assertIn('AtlasPlatformBoard?.mount(K)', (web / 'portal_panel.js').read_text(encoding='utf-8'))
        self.assertIn("AtlasPlatformBoard?.mount('netzkino')", (web / 'netzkino.js').read_text(encoding='utf-8'))

    def test_mediatheken_tab_is_named_after_its_content(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('data-catalog-source="mediatheken"', html)
        self.assertIn('>ARD, ZDF &amp; Co.</button>', html)
        self.assertNotIn('>Mediatheken</button>', html)


if __name__ == '__main__':
    unittest.main()
