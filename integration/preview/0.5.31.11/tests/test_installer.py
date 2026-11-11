import tempfile
import unittest
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import apply_preview

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name) / 'MediathekAtlas'
        (self.root / 'web').mkdir(parents=True)
        # Minimal fixtures contain the exact stable anchors from the 0.5.31 branch.
        (self.root / 'server.py').write_text('''from version import VERSION\nimport core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions\n'
class Handler:\n    def get(self):\n        if path in ('/app.js','/player.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')\n        if path=='/api/play':\n            pass\n    def do_POST(self):\n        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Sitzung'},403)\n        try:\n            d=json.loads(self.rfile.read(length));path=self.path\n            if path=='/api/shutdown' and MANAGED:pass\nif __name__=='__main__':\n    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()\n''')
        (self.root / 'web/index.html').write_text('''<button class="nav active" data-view="discover">▤ &nbsp; Katalog</button><section id="review" hidden><script src="/player.js"></script>''')
        (self.root / 'web/app.js').write_text("['discover','review','queue','subscriptions','settings','logs'];")
        (self.root / 'web/style.css').write_text('body{margin:0;}')
        (self.root / 'CHANGELOG.md').write_text('## Existing release\n')
        (self.root / 'version.py').write_text("VERSION='0.5.31'\n")
        (self.root / 'build_macos.py').write_text("for name in ('core.py','server.py','version.py'): pass\n")

    def test_dry_run_keeps_tree_unchanged(self):
        before = (self.root / 'server.py').read_bytes()
        apply_preview.install(self.root, dry_run=True)
        self.assertEqual(before, (self.root / 'server.py').read_bytes())
        self.assertFalse((self.root / 'netzkino.py').exists())

    def test_write_then_repeat_abort(self):
        changes = apply_preview.install(self.root)
        self.assertIn('netzkino.py', changes)
        self.assertIn('data-view="netzkino"', (self.root / 'web/index.html').read_text())
        self.assertIn("'/api/netzkino'", (self.root / 'server.py').read_text())
        self.assertIn("'/api/netzkino-sync'", (self.root / 'server.py').read_text())
        self.assertIn("'netzkino.py'", (self.root / 'build_macos.py').read_text())
        with self.assertRaises(RuntimeError):
            apply_preview.install(self.root)


    def test_upgrade_old_preview_preserves_existing_link_data(self):
        # Recreate the anchor-bearing code of the previous preview.
        old = (self.root / 'server.py').read_text()
        old = old.replace('import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions',
                          'import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino')
        old = old.replace("if path in ('/app.js','/player.js'):", "if path in ('/app.js','/player.js','/netzkino.js'):")
        old = old.replace("        if path=='/api/play':", "        if path=='/api/netzkino':\n            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)\n            return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0])})\n        if path=='/api/play':")
        old = old.replace("            if path=='/api/shutdown' and MANAGED:",
                          "            if path=='/api/netzkino-add':\n                return self.send({'item':netzkino.add(ROOT,d.get('title'),d.get('url'))})\n"
                          "            if path=='/api/netzkino-remove':\n                return self.send({'removed':netzkino.remove(ROOT,d.get('id'))})\n"
                          "            if path=='/api/shutdown' and MANAGED:")
        (self.root/'server.py').write_text(old)
        (self.root/'web/index.html').write_text('<button class="nav active" data-view="discover">Katalog</button>'
                         '<button class="nav" data-view="netzkino">Netzkino</button>'
                         '<section id="netzkino" hidden><p>Alte Verknüpfungen</p></section>'
                         '<section id="review" hidden><script src="/player.js"></script><script src="/netzkino.js"></script>')
        (self.root/'web/app.js').write_text("['discover','netzkino','review','queue','subscriptions','settings','logs'];")
        (self.root/'netzkino.py').write_text('OLD')
        (self.root/'web/netzkino.js').write_text('OLD')
        original_database = b'SQLite-like user data must be preserved'
        (self.root/'netzkino_links.sqlite3').write_bytes(original_database)
        apply_preview.install(self.root)
        self.assertIn('netzkino-sync', (self.root/'web/index.html').read_text())
        self.assertIn('netzkino.loop', (self.root/'server.py').read_text())
        self.assertIn('def sync(', (self.root/'netzkino.py').read_text())
        self.assertIn("'netzkino.py'", (self.root/'build_macos.py').read_text())
        self.assertEqual((self.root/'netzkino_links.sqlite3').read_bytes(),original_database)

    def test_reject_unrecognized_sources_before_write(self):
        original = (self.root / 'web/app.js').read_text()
        (self.root / 'web/app.js').write_text('unrelated js')
        with self.assertRaises(RuntimeError):
            apply_preview.install(self.root)
        self.assertEqual((self.root / 'web/app.js').read_text(), 'unrelated js')
        self.assertFalse((self.root / 'netzkino.py').exists())

if __name__ == '__main__':
    unittest.main()
