"""Regression tests for opt-in, rights-aware portal catalog adapters."""
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

import catalog
import portal_sources as portals


class PortalSecurityTests(unittest.TestCase):
    def test_only_real_netzkino_https_page_links(self):
        for url in ('http://www.netzkino.de/filme/example','https://evil.example/film/123',
                    'https://netzkino.de.evil.example/film/123',
                    'https://user:secret@netzkino.de/film/example',
                    'https://www.netzkino.de/','https://netzkino.de/filme',
                    'https://netzkino.de:8443/film/test'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                portals.netzkino_page(url)
        item=portals.manual_netzkino('Beispiel Film',
            'https://netzkino.de/film/beispiel?utm_source=chat#watch',1996)
        self.assertEqual(item['page_url'],'https://www.netzkino.de/film/beispiel')
        self.assertEqual(item['year'],1996)
        self.assertFalse(item['download_allowed'])
        self.assertEqual(item['access'],'official_site_only')
        self.assertFalse(item['rights_verified'])

    def test_manual_netzkino_does_not_fetch_third_party_website(self):
        with patch('core.open_url',side_effect=AssertionError('not an API')) as get:
            portals.manual_netzkino('Filmtitel','https://www.netzkino.de/film/filmtitel')
        get.assert_not_called()

    def test_query_is_bounded_and_not_solr_injection(self):
        url=portals.archive_query('film* OR mediatype:software',rows=99999)
        p=urlsplit(url)
        self.assertEqual((p.scheme,p.hostname),('https','archive.org'))
        query=parse_qs(p.query)
        self.assertIn('mediatype:movies',query['q'][0])
        self.assertNotIn('mediatype:software',query['q'][0])
        self.assertEqual(query['rows'],['30'])
        self.assertEqual(query['page'],['1'])
        with self.assertRaises(ValueError):portals.archive_query('!')

    def test_unknown_portal_rejected(self):
        with self.assertRaises(ValueError):portals.entry('not-a-portal','1','Film','https://example.org')

    def test_archive_identifier_rejects_paths_and_urls(self):
        for value in ('../escape','https://evil.example/a','abc/a',''):
            with self.subTest(value=value),self.assertRaises(ValueError):
                portals.internet_archive_id(value)


class InternetArchiveSearchTests(unittest.TestCase):
    def test_official_api_response_is_metadata_not_download_permission(self):
        doc={'response':{'numFound':5000,'docs':[
            {'identifier':'silent_movie_1920','title':'Stummfilm Beispiel',
             'year':'1920','licenseurl':'https://creativecommons.org/publicdomain/mark/1.0/',
             'rights':'Declared public domain','description':'An old film.'},
            {'identifier':'silent_movie_1920','title':'duplicate'},
            {'identifier':'../bad','title':'malicious id'},
            {'identifier':'an_id_missing_title','title':''}
        ]}}
        response=io.BytesIO(json.dumps(doc).encode())
        with patch('core.open_url',return_value=response) as fetch:
            rows=portals.search_archive('Stummfilm')
        self.assertEqual(len(rows),1)
        item=rows[0]
        self.assertEqual(item['page_url'],'https://archive.org/details/silent_movie_1920')
        self.assertEqual(item['year'],1920)
        self.assertEqual(item['evidence'],'official_archive_search_metadata')
        self.assertEqual(item['license_url'],'https://creativecommons.org/publicdomain/mark/1.0/')
        self.assertFalse(item['download_allowed'])
        self.assertFalse(item['rights_verified'])
        self.assertEqual(fetch.call_count,1)
        self.assertIn('archive.org/advancedsearch.php',fetch.call_args.args[0])

    def test_archive_missing_fields_and_invalid_responses(self):
        with self.assertRaisesRegex(ValueError,'keine Dokumentliste'):
            portals.archive_document({'response':{'docs':None}})
        with patch('core.open_url',return_value=io.BytesIO(b'not json')):
            with self.assertRaisesRegex(ValueError,'ungültige Metadatenantwort'):
                portals.search_archive('dokumentation')
        with patch('core.open_url',return_value=io.BytesIO(b'x'*(portals.MAX_RESPONSE_BYTES+1))):
            with self.assertRaisesRegex(ValueError,'Antwort zu groß'):
                portals.search_archive('dokumentation')

    def test_archive_network_outage_is_safe_error(self):
        with patch('core.open_url',side_effect=urllib.error.URLError('offline')):
            with self.assertRaisesRegex(ValueError,'nicht erreichbar'):
                portals.search_archive('film')

    def test_no_background_crawling_or_video_links(self):
        item=portals.archive_document({'response':{'docs':[{
            'identifier':'example_123','title':'Film','download':'https://evil.example/movie.mp4',
            'files':[{'name':'file.mp4'}]}]}})[0]
        self.assertFalse(item['download_allowed'])
        self.assertNotIn('url_video',item)
        self.assertNotIn('files',item)


class SqlitePortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=sqlite3.connect(str(Path(self.temp.name)/'catalog.db'))
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        catalog.initialize(self.db)
        portals.initialize(self.db)

    def test_idempotent_persistence_and_no_download_offer(self):
        item=portals.manual_netzkino('Vorhandener Film',
                                     'https://www.netzkino.de/film/beispiel',1996)
        with self.db:portals.save(self.db,[item])
        original=portals.listing(self.db)
        self.assertEqual(original['total'],1)
        with self.db:portals.save(self.db,[item])
        self.assertEqual(portals.listing(self.db)['total'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM offers').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] if
                         self.db.execute("SELECT 1 FROM sqlite_master WHERE name='jobs'").fetchone() else 0,0)
        self.assertEqual(portals.state(self.db)['sources'][1]['items'],1)

    def test_archive_and_netzkino_same_title_remain_distinct(self):
        manual=portals.manual_netzkino('Der Film','https://netzkino.de/filme/der-film',1988)
        archive=portals.entry('internet_archive','film1988','Der Film',
                               'https://archive.org/details/film1988',1988,
                               evidence='official_archive_search_metadata')
        with self.db:portals.save(self.db,[manual,archive])
        all_rows=portals.listing(self.db)
        self.assertEqual(all_rows['total'],2)
        self.assertEqual(len({r['id'] for r in all_rows['items']}),2)
        self.assertEqual(portals.listing(self.db,source='netzkino')['total'],1)
        self.assertEqual(portals.listing(self.db,query='Der Film')['total'],2)

    def test_exact_local_title_year_is_hint_only(self):
        self.db.execute("INSERT INTO works(id,title,kind,year,meta,updated) VALUES(?,?,?,?,?,?)",
                         ('local123','Beispiel Film','movie',1996,'{}',1))
        good=portals.manual_netzkino('Beispiel Film','https://netzkino.de/film/123456',1996)
        bad=portals.manual_netzkino('Beispiel Film','https://netzkino.de/film/987654',2002)
        with self.db:portals.save(self.db,[good,bad])
        r=portals.listing(self.db)
        found={e['year']:e.get('local_work_id') for e in r['items']}
        self.assertEqual(found[1996],'local123')
        self.assertIsNone(found[2002])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM offers').fetchone()[0],0)

    def test_failed_batch_transaction_keeps_older_links(self):
        base=portals.manual_netzkino('Safe Film','https://netzkino.de/film/safe')
        invalid=dict(base,source='invalid')
        with self.assertRaises(ValueError):
            with self.db:portals.save(self.db,[base,invalid])
        self.assertEqual(portals.listing(self.db)['total'],0)

    def test_incomplete_search_does_not_retire_previous_results(self):
        good=portals.entry('internet_archive','archive_id_1','One',
                           'https://archive.org/details/archive_id_1')
        with self.db:portals.save(self.db,[good],query='first')
        with self.db:portals.save(self.db,[],query='new search yielded nothing')
        self.assertEqual(portals.listing(self.db)['total'],1)
        status=portals.state(self.db)
        self.assertEqual(status['total'],1)
        self.assertEqual(status['sources'][0]['last_search']['query'],'first')


class IntegrationContractTests(unittest.TestCase):
    def test_api_requires_existing_app_auth_and_uses_separate_sqlite_table(self):
        root=Path(__file__).resolve().parents[1]
        server=(root/'server.py').read_text()
        page=(root/'web/index.html').read_text()
        js=(root/'web/app.js').read_text()
        bundle=(root/'build_macos.py').read_text()
        self.assertLess(server.index("if not self.authorized():"),server.index("if path=='/api/portals':"))
        self.assertIn("if path=='/api/portal-netzkino-add':",server)
        self.assertIn("if path=='/api/portal-search':",server)
        self.assertIn('portal_sources.initialize(c)',server)
        self.assertIn("'portal_sources.py'",bundle)
        self.assertIn('data-view="portals"',page)
        self.assertIn('id="portal-netzkino-add"',page)
        self.assertIn("function portalItemCard(item)",js)
        self.assertIn("link.rel='noopener noreferrer'",js)


if __name__=='__main__':unittest.main()
