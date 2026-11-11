"""0.5.32: titles beyond the curated GraphQL frontpage come from the sitemap."""
import sys, tempfile, unittest, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netzkino, netzkino_details  # noqa: E402

INDEX = b'''<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.netzkino.de/sitemap-movies-0.xml</loc></sitemap>
<sitemap><loc>https://www.netzkino.de/sitemap-movies-1.xml</loc></sitemap></sitemapindex>'''
PART0 = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.netzkino.de/details/film-a</loc></url>
<url><loc>https://www.netzkino.de/details/neuer-film</loc></url>
<url><loc>https://www.netzkino.de/kategorie/action</loc></url>
<url><loc>https://www.netzkino.de/impressum</loc></url></urlset>'''
PART1 = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.netzkino.de/details/noch-ein-film</loc></url></urlset>'''


def home():
    node = lambda slug, title: {'contentMovie': {'id': 'id-' + slug, 'slug': slug, 'title': title}}
    return {'parentCategory': {'title': 'Start', 'content': {'nodes': [node('film-a', 'Film A')]},
                               'subcategories': {'nodes': []}}}


class SitemapCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fetch(self, url):
        pages = {'https://www.netzkino.de/sitemap.xml': INDEX,
                 'https://www.netzkino.de/sitemap-movies-0.xml': PART0,
                 'https://www.netzkino.de/sitemap-movies-1.xml': PART1}
        if url not in pages:
            raise urllib.error.HTTPError(url, 404, 'nf', {}, None)
        return pages[url]

    def test_details_routes_are_catalogue_items(self):
        items, children, kind = netzkino.parse_sitemap(PART0)
        self.assertEqual(sorted(i['url'] for i in items), ['https://www.netzkino.de/details/film-a',
                                                         'https://www.netzkino.de/details/neuer-film'])
        self.assertEqual(kind, 'urlset')

    def test_sync_adds_missing_titles_without_touching_graphql_rows(self):
        result = netzkino.sync(self.root, graphql_fetch=lambda op, v: home(), sitemap_fetch=self.fetch, now=100)
        self.assertTrue(result['ok'])
        self.assertEqual(result['sitemap']['entries'], 3)
        self.assertEqual(result['sitemap']['new'], 2)        # film-a already came from GraphQL
        self.assertEqual(result['coverage_status'], 'startpage_plus_sitemap')
        db = netzkino._connect(self.root)
        try:
            rows = {r['url']: (r['source'], r['content_id']) for r in db.execute('SELECT url,source,content_id FROM netzkino_catalog')}
        finally:
            db.close()
        self.assertEqual(rows['https://www.netzkino.de/details/film-a'], ('graphql', 'id-film-a'))
        self.assertEqual(rows['https://www.netzkino.de/details/neuer-film'][0], 'sitemap')
        st = netzkino.state(self.root)
        self.assertEqual(st['coverage_status'], 'startpage_plus_sitemap')
        self.assertEqual(st['sitemap_entries'], 3)
        # Second run: idempotent, nothing new
        again = netzkino.complete_from_sitemap(self.root, fetcher=self.fetch, now=200)
        self.assertEqual(again['new'], 0)

    def test_unreachable_sitemap_keeps_graphql_result(self):
        def down(url):
            raise urllib.error.URLError('offline')
        result = netzkino.sync(self.root, graphql_fetch=lambda op, v: home(), sitemap_fetch=down, now=100)
        self.assertTrue(result['ok'])
        self.assertFalse(result['sitemap']['ok'])
        self.assertEqual(netzkino.state(self.root)['coverage_status'], 'startpage_only')

    def test_sitemap_title_loads_details_by_slug(self):
        netzkino.complete_from_sitemap(self.root, fetcher=self.fetch, now=100)
        db = netzkino._connect(self.root)
        item = db.execute("SELECT id FROM netzkino_catalog WHERE url LIKE '%neuer-film'").fetchone()['id']
        db.close()
        seen = []
        def fetch(op, variables):
            seen.append(variables['slug'])
            return {'movie': {'id': 'a0Uxyz123', 'title': 'Neuer Film', 'productionYear': 2020}}
        data = netzkino_details.get(self.root, item, fetch=fetch, now=300)
        self.assertEqual(seen, ['neuer-film'])
        self.assertEqual(data['details']['year'], 2020)
        db = netzkino._connect(self.root)
        self.assertEqual(db.execute('SELECT content_id,year FROM netzkino_catalog WHERE id=?', (item,)).fetchone()[:], ('a0Uxyz123', 2020))
        db.close()


if __name__ == '__main__':
    unittest.main()
