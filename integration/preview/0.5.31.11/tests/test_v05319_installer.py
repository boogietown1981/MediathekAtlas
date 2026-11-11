"""0.5.31.9 patch construction, module whitelists and branch preservation."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import apply_05319

class InstallerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        roots={
          'server.py':'''import portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment
class Handler:
    def get(self):
        if path=='/api/netzkino-reference-report':pass
        if path=='/api/netzkino-watch':pass
        if path=='/api/archive-companion':pass
        if path=='/api/video-audit':pass
    def do_POST(self):
            if path=='/api/netzkino-enrich':pass
    def serves(self):
        if path in ('/app.js','/player.js','/netzkino.js','/video_audit.js','/netzkino_detail.js','/unified_catalog.js'):pass
    def worker(self):
        threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()
        snapshot={'threads':[t.name for t in threading.enumerate()]}
''',
          'web/index.html':'''<div id="atlas-nk-download-placeholder"></div><div id="atlas-nk-actions"></div><script src="/netzkino_detail.js"></script>''',
          'web/netzkino_detail.js':'''function open(id) {
      const m = data.details || {};
      return m;
}''',
          'web/style.css':'#atlas-netzkino-detail {}',
          'build_macos.py':'''modules=('netzkino_enrichment.py','netzkino_details.py')\nbundle={'CFBundleVersion':'518'}''',
          'version.py':"VERSION='0.5.31.8'",
          'CHANGELOG.md':'# Changelog\n'
        }
        for n in ('netzkino.py','archive_companion.py','portal_control.py','yt_dlp_probe.py','netzkino_enrichment.py','video_backfill.py'):
            roots[n]='module placeholder\n'
        for path,content in roots.items():
            target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content)

    def test_dry_run_has_no_writes(self):
        original=(self.root/'server.py').read_text()
        files=apply_05319.patch(self.root,dry_run=True)
        self.assertIn('netzkino_downloads.py',files)
        self.assertEqual(original,(self.root/'server.py').read_text())
        self.assertFalse((self.root/'netzkino_downloads.py').exists())

    def test_patch_wires_all_without_replacing_other_sources(self):
        apply_05319.patch(self.root)
        server=(self.root/'server.py').read_text()
        for route in ('/api/netzkino-download-add','/api/netzkino-download-action','/api/netzkino-downloads',
                      '/api/archive-companion','/api/video-audit','/api/netzkino-enrich'):
            self.assertIn(route,server)
        self.assertIn('netzkino_licensed_file_worker',server)
        self.assertIn('id="atlas-nk-download-form"',(self.root/'web/index.html').read_text())
        self.assertIn('netzkino_downloads.js',(self.root/'web/index.html').read_text())
        self.assertIn("VERSION='0.5.31.9'",(self.root/'version.py').read_text())
        self.assertIn("'CFBundleVersion':'519'",(self.root/'build_macos.py').read_text())
        self.assertTrue((self.root/'netzkino_downloads.py').is_file())

    def test_wrong_version_fails_without_partial_edit(self):
        (self.root/'version.py').write_text("VERSION='0.5.31.10'")
        before=(self.root/'server.py').read_text()
        with self.assertRaises(RuntimeError):apply_05319.patch(self.root)
        self.assertEqual(before,(self.root/'server.py').read_text())

if __name__=='__main__':unittest.main()
