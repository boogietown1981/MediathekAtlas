"""0.5.31.6 preflight: atomic patches and ArchiveMedia preservation."""
import pathlib
import tempfile
import unittest
import sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_05316

class Installer05316(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=pathlib.Path(temp.name)
        server="""import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy
class Handler:
    def get(self):
        if path in ('/app.js','/player.js','/netzkino.js','/video_audit.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')
        if path=='/api/archive-companion':pass
        if path=='/api/video-audit':pass
        if path=='/api/netzkino-grouped':pass
    def do_POST(self):
        if path=='/api/portal-archive-probe':pass
            if path=='/api/portal-netzkino-add':pass
"""
        html='''<section id="discover"><p>Existing Mediathek catalogue</p></section>
<section id="portals"><div class="platform-tabs"><button class="platform-tab" type="button" data-platform="netzkino">Netzkino</button></div>
  <div id="portal-platform-overview"></div><div id="archive-full-mode"></div><div id="archive-platform-controls"></div>
<section id="netzkino"><button id="netzkino-view-series">Serien</button></section></section>
<div id="video-audit-panel"></div>
<script src="/app.js"></script><script src="/netzkino.js"></script><script src="/video_audit.js"></script></body>'''
        def read(p):return (ROOT/p).read_text('utf-8')
        files={
           'server.py':server,'web/index.html':html,'web/netzkino.js':read('web/netzkino.js'),
           'web/style.css':'/* ArchiveMedia preserved */',
           'netzkino.py':read('netzkino.py'),
           'diagnostic_extensions.py':read('diagnostic_extensions.py'),
           'build_macos.py':"for name in ('netzkino.py','video_backfill.py'):pass\nplist={'CFBundleVersion':'515'}",
           'version.py':"VERSION='0.5.31.5'",'CHANGELOG.md':'# Existing changelog',
           'portal_sources.py':'ArchiveMedia scanner retained',
           'archive_companion.py':'ArchiveMedia full mode retained',
           'portal_control.py':'ArchiveMedia queue retained',
           'video_backfill.py':'Existing catalog audit retained'}
        for name,contents in files.items():
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents,'utf-8')

    def test_valid_integrations_are_additive(self):
        original=(self.root/'portal_control.py').read_bytes()
        before=(self.root/'version.py').read_bytes()
        names=apply_05316.patch(self.root,dry_run=True)
        self.assertIn('yt_dlp_probe.py',names)
        self.assertEqual((self.root/'version.py').read_bytes(),before)
        apply_05316.patch(self.root)
        self.assertEqual((self.root/'portal_control.py').read_bytes(),original)
        s=(self.root/'server.py').read_text()
        for expected in ['/api/netzkino-details','/api/netzkino-watch','/api/netzkino-metadata-probe','/api/archive-companion']:
            self.assertIn(expected,s)
        h=(self.root/'web/index.html').read_text()
        for expected in ['id="archive-full-mode"','id="pluto-info"','data-catalog-source="all"','id="atlas-netzkino-detail"']:
            self.assertIn(expected,h)
        self.assertIn("VERSION='0.5.31.6'",(self.root/'version.py').read_text())
        self.assertIn("'MovieDetails'",(self.root/'netzkino.py').read_text())
        with self.assertRaises(RuntimeError):apply_05316.patch(self.root,dry_run=True)

    def test_missing_archivemedia_fails_without_writes(self):
        before=(self.root/'version.py').read_bytes()
        (self.root/'archive_companion.py').unlink()
        with self.assertRaises(RuntimeError):apply_05316.patch(self.root)
        self.assertEqual((self.root/'version.py').read_bytes(),before)

if __name__=='__main__':unittest.main()
