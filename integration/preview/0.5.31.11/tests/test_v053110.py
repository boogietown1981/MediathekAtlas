"""Regression tests: source parity, in-app playback and Netzkino startpage coverage."""
from __future__ import annotations
import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_053110


class NativePlayerAndCoverage(unittest.TestCase):
    def setUp(self):
        ctx=tempfile.TemporaryDirectory();self.addCleanup(ctx.cleanup)
        self.root=pathlib.Path(ctx.name)
        for name in ('netzkino.py','diagnostic_extensions.py','netzkino_webplayer.swift',
                     'web/netzkino.js','web/netzkino_detail.js','web/unified_catalog.js'):
            t=self.root/name;t.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,t)
        for name in ('archive_companion.py','portal_control.py','netzkino_downloads.py',
                     'yt_dlp_probe.py','netzkino_enrichment.py','web/style.css'):
            t=self.root/name;t.parent.mkdir(parents=True,exist_ok=True);t.write_text('pass\n')
        # The download UI is wired by the previous (0.5.31.9) patch.
        dt=self.root/'web/netzkino_detail.js'
        dt.write_text(dt.read_text()+'\n// window.AtlasNetzkinoDownloads\n')
        (self.root/'server.py').write_text('''# /api/netzkino-downloads /api/archive-companion /api/netzkino-watch
# /api/netzkino-metadata-probe /api/video-audit /api/netzkino-enrich
                diagnostics.event('netzkino_official_player',mode='official_browser')
                return self.send({'mode':'official_browser','page_url':page})
''')
        (self.root/'web/index.html').write_text('''<div id="archive-full-mode"></div>
<div id="atlas-nk-downloads"></div><div id="atlas-nk-reference"></div>
<button data-catalog-source="all"></button><summary>Download / Offline-Nutzung</summary>
''')
        (self.root/'version.py').write_text("VERSION='0.5.31.9'")
        (self.root/'build_macos.py').write_text("bundle={'CFBundleVersion':'519'}")
        (self.root/'CHANGELOG.md').write_text('# Changelog\n')

    def patch(self):
        apply_053110.patch(self.root)
        spec=importlib.util.spec_from_file_location('netzkino_standalone_test',self.root/'netzkino.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        return mod

    def test_preflight_and_preservation(self):
        originals={p:(self.root/p).read_bytes() for p in ('archive_companion.py',
             'portal_control.py','netzkino_downloads.py','yt_dlp_probe.py','netzkino_enrichment.py')}
        out=apply_053110.patch(self.root,dry_run=True)
        self.assertIn('netzkino.py',out)
        self.assertIn("VERSION='0.5.31.9'",(self.root/'version.py').read_text())
        self.patch()
        self.assertEqual(originals,{p:(self.root/p).read_bytes() for p in originals})
        self.assertIn("VERSION='0.5.31.10'",(self.root/'version.py').read_text())
        self.assertIn('mode=\'native_unavailable\'',(self.root/'server.py').read_text())
        self.assertNotIn('NSWorkspace.shared.open',(self.root/'netzkino_webplayer.swift').read_text())
        self.assertNotIn('window.open(',(self.root/'web/netzkino_detail.js').read_text())
        self.assertIn('window.AtlasNetzkinoDetail = {open, play}',(self.root/'web/netzkino_detail.js').read_text())
        self.assertIn('separat lizenzierte Videodateien',(self.root/'web/index.html').read_text())
        with self.assertRaises(RuntimeError):apply_053110.patch(self.root,dry_run=True)

    def test_category_limit_detected_but_not_wrongly_claimed_complete(self):
        nk=self.patch()
        def movie(i):return {'contentMovie':{'id':f'id{i}', 'title':'Titel '+str(i),
                                         'slug':'film-'+str(i),'flags':[]}}
        home={'parentCategory':{'title':'Home', 'subcategories':{'nodes':[
            {'title':'Action','slug':'action-frontpage','content':{'nodes':[movie(0)]}}]}}}
        category={'category':{'title':'Action','content':{'nodes':[movie(i) for i in range(20)]}}}
        result=nk.sync_graphql(self.root/'data',fetch=lambda op,v:home if op=='AllContent' else category,now=1000)
        self.assertTrue(result['ok'])
        self.assertEqual(result['category_cap_hits'],1)
        self.assertEqual(result['coverage_status'],'startpage_only')
        self.assertEqual(nk.state(self.root/'data')['category_cap_hits'],1)
        self.assertIn('nicht der vollständige',nk.state(self.root/'data')['catalog_scope'])
        self.assertEqual(nk.state(self.root/'data')['catalog_count'],20)
        category['category']['content']['nodes']=category['category']['content']['nodes'][:19]
        result=nk.sync_graphql(self.root/'data',fetch=lambda op,v:home if op=='AllContent' else category,now=2000)
        self.assertEqual(result['category_cap_hits'],0)
        self.assertEqual(nk.state(self.root/'data')['category_cap_hits'],0)
        self.assertEqual(nk.state(self.root/'data')['catalog_count'],20) # non-destructive

    def test_export_does_not_leak_licenses_or_urls(self):
        nk=self.patch()
        # Diagnostic is read-only; absence of catalog should be safe.
        spec=importlib.util.spec_from_file_location('diagnostics_053110_test',self.root/'diagnostic_extensions.py')
        diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)
        result=diag.netzkino(self.root/'none')
        self.assertEqual(result['catalog_count'],0)
        self.assertNotIn('file_url',str(result))
        self.assertIn('category_cap_hits',(self.root/'diagnostic_extensions.py').read_text())

    def test_js_syntax_and_installer_steps(self):
        self.patch()
        if shutil.which('node'):
            for js in ('netzkino.js','netzkino_detail.js','unified_catalog.js'):
                subprocess.run(['node','--check',str(self.root/'web'/js)],check=True,capture_output=True)
        script=(ROOT/'Netzkino-Testversion-bauen.command').read_text()
        self.assertIn('apply_053110.py',script)
        self.assertIn('[16/16]',script)
        self.assertIn('ArchiveMedia-PR24-Quelle',script)
        self.assertIn('category_cap_hits',script)
        self.assertNotIn('git fetch --depth 1',script)
        self.assertIn('MediathekAtlas-0.5.31.11-Integration-Test.app',script)

    def test_invalid_parent_is_noop(self):
        (self.root/'version.py').write_text("VERSION='0.5.31.11'")
        previous=(self.root/'netzkino.py').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'Ausgangsversion'):apply_053110.patch(self.root)
        self.assertEqual(previous,(self.root/'netzkino.py').read_bytes())

if __name__=='__main__':unittest.main()
