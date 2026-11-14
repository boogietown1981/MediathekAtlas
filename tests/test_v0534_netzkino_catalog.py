"""0.5.34: Netzkino catalogue beyond the frontpage (category discovery, related titles, recordings)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import diagnostic_extensions, netzkino, netzkino_details  # noqa: E402

A_ID = netzkino._key('https://www.netzkino.de/details/a')  # same id the catalogue sync derives


def movie(slug, title, typename=None):
    node = {'id': 'id-' + slug, 'slug': slug, 'title': title, 'productionYear': 2001}
    if typename:
        node['__typename'] = typename
    return node


def home(_op, _vars):
    return {'parentCategory': {'title': 'Start', 'content': {'nodes': []}, 'subcategories': {'nodes': [
        {'slug': 'neu', 'title': 'Neu', 'content': {'nodes': [{'contentMovie': movie('a', 'Film A')}]}}]}}}


CATEGORIES = {
    'neu': {'category': {'title': 'Neu', '__typename': 'CmsCategory',
                         'content': {'nodes': [{'contentMovie': movie('a', 'Film A')}],
                                     'pageInfo': {'hasNextPage': True, 'endCursor': 'x', 'totalCount': 118}},
                         'subcategories': {'nodes': [{'slug': 'horror', 'title': 'Horror'}]}}},
    'horror': {'category': {'title': 'Horror',
                            'content': {'nodes': [{'contentMovie': movie('b', 'Film B')}]},
                            'rows': [{'items': [movie('c', 'Film C', 'CmsMovie')]}],
                            'related': [{'__typename': 'CmsCategory', 'slug': 'heimatfilm', 'title': 'Heimatfilm'}]}},
    'heimatfilm': {'category': {'title': 'Heimatfilm', 'content': {'nodes': [{'contentMovie': movie('d', 'Film D')}]}}},
}


class Fixture(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)

    def titles(self):
        db = netzkino._connect(self.root)
        try:
            return {r['title']: r['source'] for r in db.execute('SELECT title,source FROM netzkino_catalog')}
        finally:
            db.close()


class DiscoveryTests(Fixture):
    def fetch(self, op, variables):
        if op == 'AllContent':
            return home(op, variables)
        return CATEGORIES.get(variables['slug'], {'category': None})

    def test_categories_inside_answers_are_followed(self):
        result = netzkino.sync_graphql(self.root, fetch=self.fetch, now=10)
        roots = len(netzkino._SEED_CATEGORIES)
        self.assertEqual(result['categories'], 3 + roots)
        self.assertEqual(result['categories_discovered'], 2 + roots)
        self.assertEqual(set(self.titles()), {'Film A', 'Film B', 'Film C', 'Film D'})
        self.assertEqual(result['category_pagination'], {'pageInfo': 1})
        self.assertEqual(result['category_total_max'], 118)
        st = netzkino.state(self.root)
        self.assertEqual(st['categories_discovered'], 2 + roots)
        self.assertEqual(st['category_total_max'], 118)
        self.assertFalse(result['partial'])
        diag = diagnostic_extensions.netzkino(self.root)
        self.assertEqual(diag['categories_discovered'], 2 + roots)
        self.assertEqual(diag['category_total_max'], 118)
        self.assertEqual(diag['category_pagination'], {'pageInfo': 1})

    def test_discovery_is_bounded(self):
        many = {'category': {'title': 'X', 'content': {'nodes': [{'contentMovie': movie('a', 'Film A')}]},
                             'subcategories': {'nodes': [{'slug': 'c%d' % i, 'title': 'C'} for i in range(400)]}}}
        calls = []

        def fetch(op, v):
            calls.append(op)
            return home(op, v) if op == 'AllContent' else many
        result = netzkino.sync_graphql(self.root, fetch=fetch, now=10)
        self.assertEqual(result['categories_discovered'], netzkino._MAX_DISCOVERED)
        self.assertEqual(len(calls), 1 + 1 + netzkino._MAX_DISCOVERED + len(netzkino._TREE_ROOTS))  # + AllContent per tree root


class RelatedAndRecordingTests(Fixture):
    def seed(self):
        db = netzkino._connect(self.root)
        with db:
            db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,content_id)
                VALUES(?,?,?,?,?,?,?,?,?)''', (A_ID, 'Film A', 'https://www.netzkino.de/details/a',
                                              'graphql', 'x', 1, 1, 'movie', 'id-a'))
        db.close()

    def test_movie_details_add_related_titles(self):
        self.seed()
        payload = {'movie': {**movie('a', 'Film A', 'CmsMovie'),
                             'recommendations': {'nodes': [movie('r1', 'Empfehlung 1', 'CmsMovie'),
                                                           {'contentMovie': movie('r2', 'Empfehlung 2')}]}}}
        info = netzkino_details.get(self.root, A_ID, fetch=lambda op, v: payload, now=50)
        self.assertIsNone(info['error_type'])
        titles = self.titles()
        self.assertEqual(titles['Film A'], 'graphql')            # existing row untouched
        self.assertEqual(titles['Empfehlung 1'], 'graphql_related')
        self.assertEqual(titles['Empfehlung 2'], 'graphql_related')
        self.assertEqual(netzkino.state(self.root)['related_new'], 2)

    def test_recording_import_reads_graphql_and_next_data_only(self):
        self.seed()
        nextdata = {'props': {'pageProps': {'dehydratedState': {'queries': [
            {'state': {'data': {'movie': movie('n1', 'Aus Next-Daten', 'CmsMovie')}}}]}}}}
        entries = [
            {'url': 'https://data.netzkino.de/netzkino/graphql?operationName=CategoryContentPaged',
             'text': json.dumps({'data': {'category': {'content': {'nodes': [
                 {'contentMovie': movie('h1', 'Mitschnitt 1')}, {'contentMovie': movie('a', 'Film A')}]}}}})},
            {'url': 'https://www.netzkino.de/details/n1',
             'text': '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(nextdata) + '</script>'},
            {'url': 'https://evil.example/graphql', 'text': json.dumps({'contentMovie': movie('x', 'Fremd')})},
            {'url': 'https://data.netzkino.de/netzkino/graphql?operationName=Bad;Name', 'text': 'kein json'},
        ]
        r = netzkino.import_recording(self.root, entries, now=70)
        self.assertEqual((r['answers'], r['added'], r['ignored']), (2, 2, 2))
        self.assertEqual(r['operations'], ['CategoryContentPaged'])
        titles = self.titles()
        self.assertEqual(titles['Mitschnitt 1'], 'har_import')
        self.assertEqual(titles['Aus Next-Daten'], 'har_import')
        self.assertNotIn('Fremd', titles)
        self.assertEqual(titles['Film A'], 'graphql')
        st = netzkino.state(self.root)
        self.assertEqual(st['har_import_added'], 2)
        self.assertEqual(st['har_operations'], {'CategoryContentPaged': 1})
        # Idempotent
        self.assertEqual(netzkino.import_recording(self.root, entries, now=80)['added'], 0)

    def test_film_details_teach_full_categories_for_the_next_sync(self):
        # Shape of MovieDetails.categories as recorded on netzkino.de (HAR 12.11.2026), trimmed.
        self.seed()
        cat = lambda slug, parent: {'category': {'id': 'c-' + slug, 'title': slug.title(), 'slug': slug,
            'parentId': 'p', '__typename': 'CmsCategory',
            'parent': {'id': 'p', 'slug': parent, '__typename': 'CmsCategory'}}}
        payload = {'movie': {**movie('a', 'Film A', 'CmsMovie'), 'categories': {'nodes': [
            cat('krimi', 'thrillerkino'), cat('sozialdrama', 'dramakino'), cat('joyn-netzkino', 'joyn')]}}}
        netzkino_details.get(self.root, A_ID, fetch=lambda op, v: payload, now=50)
        slugs = [s for s, _ in netzkino._known_categories(self.root)]
        for slug in ('krimi', 'thrillerkino', 'sozialdrama', 'dramakino', 'joyn-netzkino', 'joyn'):
            self.assertIn(slug, slugs)
        requested = []

        def fetch(op, v):
            if op == 'AllContent':
                return home(op, v)
            requested.append(v['slug'])
            if v['slug'] == 'krimi':
                return {'category': {'title': 'Krimi', 'content': {'nodes': [
                    {'contentMovie': movie('k%d' % i, 'Krimi %d' % i)} for i in range(150)]}}}
            return {'category': None}
        result = netzkino.sync_graphql(self.root, fetch=fetch, now=60)
        self.assertIn('krimi', requested)
        self.assertIn('netzkino-genre', requested)
        self.assertEqual(sum(1 for t in self.titles() if t.startswith('Krimi ')), 150)
        self.assertGreaterEqual(netzkino.state(self.root)['categories_known'], 6)
        self.assertFalse(result['partial'])

    def test_recording_rejects_garbage(self):
        with self.assertRaises(ValueError):
            netzkino.import_recording(self.root, 'nope')

    def test_server_and_ui_wiring(self):
        server = (ROOT / 'server.py').read_text('utf-8')
        self.assertIn("@ROUTES.post('/api/netzkino-recording')", server)
        ui = (ROOT / 'web' / 'netzkino.js').read_text('utf-8')
        self.assertIn("endpoint('netzkino-recording'", ui)
        self.assertNotIn('e.request?.headers', ui)
        self.assertIn('netzkino-recording-file', (ROOT / 'web' / 'index.html').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
