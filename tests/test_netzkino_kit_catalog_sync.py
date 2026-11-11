# Ported from the 0.5.31.x integration kit, where it ran against stale module copies.
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import netzkino

HEADER=b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
FOOTER=b'</urlset>'

def feed(*links):
    rows=''.join('<url><loc>'+link.replace('&','&amp;')+'</loc></url>' for link in links)
    return HEADER+rows.encode()+FOOTER

class CatalogSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_extract_only_movie_links(self):
        xml=feed('https://www.netzkino.de/filme/ein-film',
                 'https://www.netzkino.de/genre/action',
                 'https://www.netzkino.de/#!/filme/alter-film',
                 'https://evil.test/filme/phishing',
                 'https://www.netzkino.de/info/agb',
                 'https://www.netzkino.de/filme/ein-film')
        items, _, kind=netzkino.parse_sitemap(xml)
        self.assertEqual(kind, 'urlset')
        self.assertEqual(len(items),2)
        self.assertEqual(set(x['title'] for x in items),{'Ein Film','Alter Film'})

    def test_success_persistence_and_incremental(self):
        data=feed('https://www.netzkino.de/filme/titel-eins',
                  'https://www.netzkino.de/filme/titel-zwei')
        result=netzkino.sync(self.root,fetcher=lambda url:data,now=10000)
        self.assertEqual(result['new'],2)
        self.assertTrue(result['ok'])
        again=netzkino.sync(self.root,fetcher=lambda url:data,now=11000)
        self.assertEqual(again['new'],0)
        self.assertEqual(again['unchanged'],2)
        self.assertEqual(netzkino.state(self.root)['catalog_count'],2)
        self.assertEqual(netzkino.state(self.root)['next_attempt'],11000+86400)

    def test_incomplete_scan_preserves_prior_catalogue(self):
        data=feed('https://www.netzkino.de/filme/titel-eins')
        netzkino.sync(self.root,fetcher=lambda _:data,now=10000)
        fail=netzkino.sync(self.root,fetcher=lambda _:feed('https://www.netzkino.de/genre/action'),now=11000)
        self.assertFalse(fail['ok'])
        state=netzkino.state(self.root)
        self.assertEqual(state['last_success'],10000)
        self.assertEqual(state['catalog_count'],1)
        self.assertEqual(state['next_attempt'],11000+3600)
        self.assertIn('keine eindeutig',state['last_error'])

    def test_manual_entries_survive_and_override_catalogue(self):
        url='https://www.netzkino.de/filme/bekannter-film'
        key=netzkino.add(self.root,'Mein korrekter Name',url)['id']
        netzkino.sync(self.root,fetcher=lambda _:feed(url),now=100)
        both=netzkino.list_links(self.root)
        self.assertEqual(len(both),1)
        self.assertEqual(both[0]['origin'],'manual')
        self.assertEqual(both[0]['title'],'Mein korrekter Name')
        self.assertEqual(len(netzkino.list_links(self.root,origin='catalog')),0)
        self.assertTrue(netzkino.remove(self.root,key))
        self.assertEqual(netzkino.list_links(self.root)[0]['origin'],'catalog')

    def test_disabled_auto_by_default_and_explicit_toggle(self):
        self.assertFalse(netzkino.state(self.root)['auto'])
        with self.assertRaises(ValueError):netzkino.set_auto(self.root,'true')
        netzkino.set_auto(self.root,True)
        self.assertTrue(netzkino.state(self.root)['auto'])
        netzkino.set_auto(self.root,False)
        self.assertFalse(netzkino.state(self.root)['auto'])

    def test_fail_closed_xml_and_external_sitemap(self):
        with self.assertRaises(ValueError):netzkino.parse_sitemap(b'<!DOCTYPE html><html/>')
        index=b'''<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://evil.test/x.xml</loc></sitemap>
        <sitemap><loc>https://www.netzkino.de/api/sitemap-filme.xml</loc></sitemap></sitemapindex>'''
        children=netzkino.parse_sitemap(index)[1]
        self.assertEqual(children,['https://www.netzkino.de/api/sitemap-filme.xml'])
        outcome=netzkino.sync(self.root,fetcher=lambda url:index if url.endswith('/sitemap') else feed('https://www.netzkino.de/filme/eins'),now=100)
        self.assertTrue(outcome['ok'])
        self.assertEqual(outcome['count'],1)

    def test_partial_sitemap_index_does_not_commit(self):
        index=b'<sitemapindex><sitemap><loc>https://www.netzkino.de/s1.xml</loc></sitemap><sitemap><loc>https://www.netzkino.de/s2.xml</loc></sitemap></sitemapindex>'
        def fetch(url):
            if url.endswith('/sitemap'):return index
            if url.endswith('s1.xml'):return feed('https://www.netzkino.de/filme/eins')
            raise OSError('network down')
        outcome=netzkino.sync(self.root,fetcher=fetch,now=100)
        self.assertFalse(outcome['ok'])
        self.assertEqual(netzkino.state(self.root)['catalog_count'],0)

if __name__=='__main__':unittest.main()
