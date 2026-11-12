"""0.5.32: Netzkino titles are enriched automatically, downloads use the result."""
import json, sqlite3, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netzkino, netzkino_downloads as nd, netzkino_enrichment as ne  # noqa: E402

A, B = 'aa' * 16, 'bb' * 16


class AutoEnrichTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'
        db = netzkino._connect(self.root)
        with db:
            for i, (item, title) in enumerate(((A, 'Hin und Weg'), (B, 'Zweiter Film'))):
                db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,year)
                    VALUES(?,?,?,?,?,?,?,?,?)''', (item, title, 'https://www.netzkino.de/details/f%d' % i,
                    'graphql', 'x', 1, 1 + i, 'movie', 2014))
        db.close()
        self.offline = lambda op, v: (_ for _ in ()).throw(OSError('offline'))

    def lookup(self, row, meta, settings):
        return {'candidates': [{'provider': 'TMDB', 'reference_id': '123', 'title': meta['title'], 'similarity': 1.0,
                                'kind': 'movie', 'year': 2014, 'genres': ['Drama'],
                                'cast': ['Florian David Fitz'], 'description': 'Roadmovie über Freundschaft.'}],
                'provider_checks': [{'provider': 'TMDB', 'status': 'checked', 'count': 1}]}

    def run_once(self, item):
        return ne.enrich(self.root, item, {}, lookup=self.lookup, fetch=self.offline, now=1000)

    def test_pending_lists_unchecked_first_and_skips_fresh(self):
        self.assertEqual(ne.pending(self.root, now=1000), [B, A])
        self.run_once(B)
        self.assertEqual(ne.pending(self.root, now=1000 + ne.RETRY_TTL + 1), [A])
        self.assertIn(B, ne.pending(self.root, now=1000 + ne.GOOD_TTL + 1))

    def test_background_loop_checks_all_titles_without_click(self):
        stop = threading.Event(); seen = []
        def one(root, item, settings):
            seen.append(item); r = ne.enrich(root, item, settings, lookup=self.lookup, fetch=self.offline)
            if len(seen) >= 2: stop.set()
            return r
        t = threading.Thread(target=ne.loop, args=(self.root, lambda: {'auto_metadata': True},
                             threading.BoundedSemaphore(1), stop), kwargs={'gap': 0, 'idle': 0, 'enrich_one': one})
        t.start(); t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(sorted(seen), sorted([A, B]))
        self.assertEqual(ne.cached(self.root, A)['status'], 'candidate')

    def test_loop_respects_auto_metadata_switch(self):
        stop = threading.Event(); calls = []
        stop_later = threading.Timer(0.3, stop.set); stop_later.start()
        ne.loop(self.root, lambda: {'auto_metadata': False}, threading.BoundedSemaphore(1), stop,
                gap=0, idle=0, enrich_one=lambda *a: calls.append(a))
        self.assertEqual(calls, [])

    def test_download_metadata_uses_reference(self):
        self.run_once(A)
        media = Path(self.tmp.name) / 'media'
        import netzkino_details
        orig = netzkino_details.get
        netzkino_details.get = lambda root, item, **k: orig(root, item, fetch=self.offline, now=1000)
        try:
            job = nd.build_job(self.root, media, A)
        finally:
            netzkino_details.get = orig
        m = job['metadata']
        self.assertEqual(m['genres'], ['Drama'])
        self.assertEqual(m['cast'], [{'name': 'Florian David Fitz'}])
        self.assertEqual((m['provider'], m['reference_id'], m['source_provider']), ('TMDB', '123', 'Netzkino'))
        self.assertTrue(job['target'].endswith('Filme/Hin und Weg (2014)/Hin und Weg (2014).mkv'))


if __name__ == '__main__':
    unittest.main()
