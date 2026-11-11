# Ported from the 0.5.31.x integration kit, where it ran against stale module copies.
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netzkino

class LinkStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_persist_and_isolate(self):
        link = netzkino.add(self.root, 'Mein Film', 'https://netzkino.de/#!/filme/mein-film')
        self.assertEqual(link['url'], 'https://www.netzkino.de/#!/filme/mein-film')
        self.assertEqual(netzkino.list_links(self.root)[0]['title'], 'Mein Film')
        self.assertFalse((self.root / 'catalog.sqlite3').exists())
        self.assertEqual(len(netzkino.list_links(self.root)), 1)

    def test_upsert_and_filtered_lookup(self):
        url = 'https://www.netzkino.de/#!/filme/a-film'
        a = netzkino.add(self.root, 'Erster Film', url)
        b = netzkino.add(self.root, 'Neuer Film', url)
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(len(netzkino.list_links(self.root)), 1)
        self.assertEqual(len(netzkino.list_links(self.root, '%')), 0)
        self.assertEqual(len(netzkino.list_links(self.root, 'Neuer')), 1)

    def test_remove_and_invalid_id(self):
        data = netzkino.add(self.root, 'Testfilm', 'https://www.netzkino.de/filme/testfilm')
        with self.assertRaises(ValueError):
            netzkino.remove(self.root, "' OR 1=1--")
        self.assertTrue(netzkino.remove(self.root, data['id']))
        self.assertFalse(netzkino.remove(self.root, data['id']))
        self.assertEqual(netzkino.list_links(self.root), [])

    def test_reject_non_netzkino_and_untrusted_domains(self):
        bad = [
            'https://netzkino.de.evil.test/filme/x',
            'https://evil.test/?next=https://netzkino.de/filme/x',
            'http://www.netzkino.de/filme/x',
            'javascript:alert(1)',
            'https://www.netzkino.de:8080/filme/x',
            'https://user:pass@netzkino.de/filme/x',
            'https://www.netzkino.de/',
            'https://www.netzkino.de/%0Aevil',
        ]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                netzkino.verified_url(url)

if __name__ == '__main__':
    unittest.main()
