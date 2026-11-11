"""Patch preflight ensures ArchiveMedia and older integrations cannot disappear."""
import pathlib
import sys
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_05316,apply_05317
from test_v05316_installer import Installer05316

class Installer05317(unittest.TestCase):
    def setUp(self):
        fixture=Installer05316('test_valid_integrations_are_additive')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root=fixture.root
        apply_05316.patch(self.root)
        (self.root/'metadata.py').write_text("    def checked(value):\n        checks.append(value);provider_stats.observe(value['provider'],value['status'],value['count'])\n")

    def test_extends_and_preserves_references(self):
        old={(name,(self.root/name).read_bytes()) for name in
            ['archive_companion.py','portal_sources.py','portal_control.py','video_backfill.py','yt_dlp_probe.py']}
        unmodified=(self.root/'server.py').read_bytes()
        names=apply_05317.patch(self.root,dry_run=True)
        self.assertIn('netzkino_enrichment.py',names)
        self.assertEqual((self.root/'server.py').read_bytes(),unmodified)
        apply_05317.patch(self.root)
        self.assertEqual(old,{(name,(self.root/name).read_bytes()) for name,_ in old})
        server=(self.root/'server.py').read_text('utf-8')
        html=(self.root/'web/index.html').read_text('utf-8')
        js=(self.root/'web/netzkino_detail.js').read_text('utf-8')
        for path in ['/api/netzkino-enrich','/api/netzkino-reference-report',
                     '/api/netzkino-metadata-probe','/api/netzkino-watch',
                     '/api/archive-companion','/api/portal-archive-probe']:
            self.assertIn(path,server)
        for ident in ('archive-full-mode','archive-platform-controls',
                      'atlas-nk-reference','atlas-nk-validation'):
            self.assertIn('id="'+ident+'"',html)
        self.assertIn('netzkino_enrichment.py',(self.root/'build_macos.py').read_text())
        self.assertIn("VERSION='0.5.31.7'",(self.root/'version.py').read_text())
        self.assertIn('IMDb, TMDB, TVDB und Co.',js)
        self.assertIn('external_references',(self.root/'diagnostic_extensions.py').read_text())
        self.assertIn('_external_reference_validation',(self.root/'metadata.py').read_text())
        with self.assertRaises(RuntimeError):apply_05317.patch(self.root,dry_run=True)

    def test_compact_details_and_aria_not_mingling_archive_media(self):
        apply_05317.patch(self.root)
        html=(self.root/'web/index.html').read_text('utf-8')
        js=(self.root/'web/netzkino_detail.js').read_text('utf-8')
        css=(self.root/'web/style.css').read_text('utf-8')
        self.assertIn('id="atlas-nk-quickfacts" aria-label="Netzkino-Kurzdaten"',html)
        self.assertIn('class="nk-detail-sidebar"',html)
        self.assertIn('class="nk-detail-main"',html)
        self.assertIn("makeField(quickFacts, 'Jahr'",js)
        self.assertIn("makeField(quickFacts, 'FSK'",js)
        self.assertIn("makeField(quickFacts, 'Originalsprache'",js)
        self.assertIn("makeField(facts, 'Besetzung'",js)
        self.assertIn('value === null || value === undefined',js)
        self.assertIn('quickFacts.replaceChildren()',js)
        self.assertIn('#atlas-nk-quickfacts .nk-detail-field--wide',css)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',css)
        self.assertIn('@media(max-width:520px)',css)
        self.assertIn('id="archive-full-mode"',html)
        self.assertIn('id="archive-platform-controls"',html)

    def test_failed_preflight_unchanged(self):
        (self.root/'archive_companion.py').unlink()
        old=(self.root/'server.py').read_bytes()
        with self.assertRaises(RuntimeError):apply_05317.patch(self.root)
        self.assertEqual((self.root/'server.py').read_bytes(),old)

if __name__=='__main__':unittest.main()
