import unittest
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import merge_portals

class MergePortalsTests(unittest.TestCase):
    def test_merge_preserves_both_without_duplicate_nav(self):
        ours={
          'server.py':"import x, subscriptions, netzkino, video_backfill\n    subscriptions.initialize(c)\n        if path=='/api/catalog':\n            if path=='/api/search':\n        SERVICE.start()",
          'web/index.html':'<button class="nav" data-view="netzkino">▶ &nbsp; Netzkino</button>\n<section id="title-view" hidden>Other</section><section id="netzkino" hidden><p>Netzkino catalog</p></section><section id="review" hidden>Review',
          'web/app.js':"['discover','netzkino','review','queue','subscriptions','settings','logs'];if(b.dataset.view==='subscriptions')loadSubscriptions();",
          'web/style.css':'body{}',
          'build_macos.py':"('video_backfill.py','server.py')",
          'web/netzkino.js':'''  document.querySelector('[data-view="netzkino"]').addEventListener('click', refresh);
if (!$('netzkino').hidden) refresh();''',
          'CHANGELOG.md':'Version'}
        theirs={
          'server.py':"        if path=='/api/archive-companion':\n            do_companion()\n        if path=='/api/catalog':\n            if path=='/api/portal-controls':\n                do_ports()\n            if path=='/api/search':",
          'web/index.html':'<section id="portals" data-platform="overview" hidden>\n  <div id="portal-status" role="status" class="muted"></div></section>\n<section id="title-view"',
          'web/app.js':'let portalOffset=0,portalBusy=false;\nfunction loadPortals(){}',
          'web/style.css':'/* External portal catalogue: rights-first, compact responsive layout. */\n#portals{}',
          'CHANGELOG.md':'## In Arbeit – Isolierte externe Filmportale (noch keine Release-Freigabe)\nhi\n## 0.5.30'}
        merged=merge_portals.integrate(ours,theirs)
        self.assertEqual(merged['web/index.html'].count('id="netzkino"'),1)
        self.assertIn('Netzkino catalog',merged['web/index.html'])
        self.assertIn('id="portals"',merged['web/index.html'])
        self.assertNotIn('data-view="netzkino"',merged['web/index.html'])
        self.assertIn('/api/archive-companion',merged['server.py'])
        self.assertIn('portal_sources.initialize',merged['server.py'])
        self.assertIn('portal_sources.py',merged['build_macos.py'])
        self.assertIn('let portalOffset',merged['web/app.js'])
        self.assertIn("data-platform=\"netzkino\"",merged['web/netzkino.js'])
    def test_abort_on_broken_anchor(self):
        with self.assertRaises(RuntimeError):
            merge_portals.integrate({'server.py':'broken'},{})

if __name__=='__main__':unittest.main()
