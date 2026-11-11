"""0.5.31.8 tests for read-only cross-source taxonomy and series isolation."""
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_05318,apply_05317,apply_05315
from test_v05317_installer import Installer05317

class SharedUI(unittest.TestCase):
    def setUp(self):
        fixture=Installer05317('test_extends_and_preserves_references')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.root=fixture.root
        apply_05317.patch(self.root)
        server=self.root/'server.py'
        server.write_text(server.read_text().replace(
            "        if path=='/api/netzkino-grouped':pass",apply_05315.ROUTE.rstrip()))

    def test_additive_and_idempotency_guard(self):
        guarded={name:(self.root/name).read_bytes() for name in
             ('archive_companion.py','portal_sources.py','portal_control.py',
              'netzkino_enrichment.py','video_backfill.py','web/netzkino.js')}
        old=(self.root/'server.py').read_bytes()
        self.assertIn('web/unified_catalog.js',apply_05318.patch(self.root,dry_run=True))
        self.assertEqual(old,(self.root/'server.py').read_bytes())
        apply_05318.patch(self.root)
        self.assertEqual(guarded,{name:(self.root/name).read_bytes() for name in guarded})
        self.assertIn("VERSION='0.5.31.8'",(self.root/'version.py').read_text())
        self.assertIn("'CFBundleVersion':'518'",(self.root/'build_macos.py').read_text())
        with self.assertRaises(RuntimeError):apply_05318.patch(self.root)

    def test_nested_sidebar_no_longer_globally_positioned(self):
        apply_05318.patch(self.root)
        html=(self.root/'web/index.html').read_text()
        css=(self.root/'web/style.css').read_text()
        self.assertNotIn('<aside class="nk-detail-sidebar">',html)
        self.assertIn('<div class="nk-detail-sidebar">',html)
        self.assertIn('grid-template-columns:minmax(185px,245px) minmax(0,1fr)',css)
        self.assertIn('position:static!important',css)
        for identifier in ('atlas-cross-genre','atlas-cross-query','atlas-cross-sort',
                           'atlas-cross-items','atlas-cross-back-series','atlas-netzkino-detail',
                           'archive-full-mode','atlas-nk-reference'):
            self.assertIn('id="'+identifier+'"',html)
        server=(self.root/'server.py').read_text()
        for route in ('/api/archive-companion','/api/portal-archive-probe','/api/netzkino-watch',
                      '/api/netzkino-enrich','/api/video-audit'):
            self.assertIn(route,server)
        self.assertIn("genre=q.get('genre',[''])[0]",server)

    def test_patch_guard_missing_archive(self):
        (self.root/'archive_companion.py').unlink()
        old=(self.root/'server.py').read_bytes()
        with self.assertRaises(RuntimeError):apply_05318.patch(self.root)
        self.assertEqual(old,(self.root/'server.py').read_bytes())

class NetzkinoGroups(unittest.TestCase):
    def setUp(self):
        f=SharedUI('test_additive_and_idempotency_guard')
        f.setUp();self.addCleanup(f.doCleanups)
        apply_05318.patch(f.root)
        spec=importlib.util.spec_from_file_location('netzkino_v05318_tmp',f.root/'netzkino.py')
        self.nk=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.nk)

    def test_filter_and_sort_movies_and_series(self):
        data=[
         {'id':'a','title':'Z Film','kind':'movie','genres':'Action, Thriller','updated':8,'year':2005,'url':'https://www.netzkino.de/details/z','origin':'catalog','poster':'', 'summary':''},
         {'id':'b','title':'A Film','kind':'movie','genres':'["Drama"]','updated':9,'year':2021,'url':'https://www.netzkino.de/details/a','origin':'catalog','poster':'', 'summary':''},
         {'id':'c','title':'Serie Staffel 1 - 1. Pilot','kind':'movie','genres':'Drama','updated':11,'year':2020,'url':'https://www.netzkino.de/details/c','origin':'catalog','poster':''},
         {'id':'d','title':'Serie Staffel 1 - 2. Weiter','kind':'movie','genres':'Drama','updated':12,'year':2020,'url':'https://www.netzkino.de/details/d','origin':'catalog','poster':''}
        ]
        with patch.object(self.nk,'_view_rows',return_value=data):
            movies=self.nk.grouped_catalog(None,view='movies',sort='title')
            self.assertEqual([x['title'] for x in movies['items']],['A Film','Z Film'])
            self.assertIn('thriller',movies['genres'])
            self.assertEqual(self.nk.grouped_catalog(None,view='movies',genre='Drama')['total'],1)
            self.assertEqual(self.nk.grouped_catalog(None,view='movies',genre='Fantasy')['total'],0)
            series=self.nk.grouped_catalog(None,view='series',genre='Drama')
            self.assertEqual(series['total'],1)
            self.assertEqual(series['items'][0]['episode_count'],2)
            self.assertEqual(self.nk.grouped_catalog(None,view='series',genre='Horror')['total'],0)
            eps=self.nk.grouped_catalog(None,view='episodes',series_key=series['items'][0]['series_key'],genre='Drama')
            self.assertEqual(eps['total'],2)
            newest=self.nk.grouped_catalog(None,view='movies',sort='year')
            self.assertEqual(newest['items'][0]['title'],'A Film')

if __name__=='__main__':unittest.main()
