"""No destructive overwrite of historical portal UI, diagnosis, or source trees."""
import pathlib,tempfile,unittest,sys
HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import apply_05315

class NetzkinoConsolidationInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        files={
          'server.py':"""        if path=='/api/netzkino': pass
if path=='/api/netzkino-sync': pass
if path=='/api/archive-companion': pass
if path=='/api/portal-archive-inspect': pass
if path=='/api/video-audit': pass
""",
          'web/index.html':'<section id="portals"><div id="archive-full-mode"></div><div id="archive-platform-controls"></div><section id="netzkino">  <div class="netzkino-toolbar"></div></section></section><div id="video-audit-panel"></div>',
          'web/style.css':'/* 0.5.31.4: exact platform isolation */\n#portals[data-platform="archive"] #netzkino{display:none}',
          'web/netzkino.js':'window.MediathekAtlasNetzkino = {refresh};',
          'netzkino.py':'def _category_failure_type(exc):pass\n',
          'diagnostic_extensions.py':'# previous diagnosis\n',
          'archive_companion.py':'# archive companion retained',
          'portal_control.py':'# archive queue retained',
          'portal_sources.py':'# archive search retained',
          'video_backfill.py':'# audit retained',
          'version.py':"VERSION='0.5.31.4'\n",
          'build_macos.py':"plist={'CFBundleVersion':'514'}",
          'CHANGELOG.md':'## Previous release\n',
        }
        for name,content in files.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)

    def test_safe_dry_run_then_patch_retains_other_platforms(self):
        old=(self.root/'web/index.html').read_bytes()
        changes=apply_05315.patch(self.root,dry_run=True)
        self.assertEqual((self.root/'web/index.html').read_bytes(),old)
        self.assertIn('netzkino.py',changes)
        apply_05315.patch(self.root)
        self.assertIn("'/api/netzkino-grouped'",(self.root/'server.py').read_text())
        self.assertIn('id="archive-full-mode"',(self.root/'web/index.html').read_text())
        self.assertIn('id="archive-platform-controls"',(self.root/'web/index.html').read_text())
        self.assertIn('id="netzkino-view-series"',(self.root/'web/index.html').read_text())
        self.assertIn('def grouped_catalog(',(self.root/'netzkino.py').read_text())
        self.assertIn('media_classification',(self.root/'diagnostic_extensions.py').read_text())
        self.assertEqual((self.root/'portal_control.py').read_text(),'# archive queue retained')
        self.assertEqual((self.root/'video_backfill.py').read_text(),'# audit retained')
        self.assertIn("VERSION='0.5.31.5'",(self.root/'version.py').read_text())
        with self.assertRaises(RuntimeError):apply_05315.patch(self.root,dry_run=True)

    def test_unexpected_source_fails_without_writes(self):
        (self.root/'server.py').write_text('not a known checkout')
        old=(self.root/'version.py').read_bytes()
        with self.assertRaises(RuntimeError):apply_05315.patch(self.root)
        self.assertEqual((self.root/'version.py').read_bytes(),old)

if __name__=='__main__':unittest.main()
