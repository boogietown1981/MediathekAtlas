"""0.6.3: Plex films and episodes without copy protection can be kept offline for 30 days.

Björn (14.11.2026): "der film läuft aber ich kann nicht offline in den 30 tage sicherung aufnehmen".
Same shared queue as Pluto TV, JustWatch TV and Rakuten TV; protected titles, series and live
channels are refused; the token-bearing stream address is fetched at download time only.
Also: the network probe of the diagnostics uses the same trust store as the catalogue requests."""
import json
import sqlite3
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import downloads  # noqa: E402
import netcheck  # noqa: E402
import netzkino_downloads as nd  # noqa: E402
import platform_registry  # noqa: E402
import plex  # noqa: E402
import plex_downloads as pd  # noqa: E402
import portal_title  # noqa: E402
from test_v0598_plex import NOW, FakePlex  # noqa: E402


class PlexOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        plex._SOURCES.clear()
        self.fake = FakePlex(total=3)
        plex.sync(self.root, opener=self.fake, fetch_token=self.fake.fetch_token, now=NOW)
        plex.load_episodes(self.root, 's.show001', opener=self.fake, fetch_token=self.fake.fetch_token, now=NOW)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')

    def check(self, root, item_id):
        return plex.play_source(root, item_id, opener=self.fake, fetch_token=self.fake.fetch_token, now=NOW)

    def enqueue(self, item_id):
        job = pd.build_job(self.root, self.media, item_id, now=1000, check=self.check)
        return nd.portal_duplicate(self.c, job) or nd.insert(self.c, job)

    def test_clear_film_goes_into_the_shared_queue(self):
        r = self.enqueue('m.m000abc')               # unchecked (drm -1): checked first, then accepted
        self.assertTrue(r['created'])
        self.assertEqual(plex.item(self.root, 'm.m000abc')['item']['drm'], 0)
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        self.assertEqual((job['origin'], job['plex_id'], job['license']['kind'], job['license']['days']),
                         ('plex', 'm.m000abc', 'plex_offline', 30))
        self.assertEqual(Path(job['target']).relative_to(self.media.resolve()).parts[0], 'Filme')
        self.assertNotIn('tok', json.dumps(job))                         # no Plex token in the stored job
        self.assertEqual(job['source']['_resolver'], 'plex')
        self.assertEqual(self.enqueue('m.m000abc')['created'], False)    # same title twice -> existing job
        listing = nd.listing(self.c, origin='plex')
        self.assertEqual((listing['offline_days'], listing['items'][0]['plex_id']), (30, 'm.m000abc'))
        self.assertIn('Kopierschutz', listing['policy'])
        self.assertEqual(nd.portal_days('plex'), 30)
        self.assertEqual(nd.summary(self.c, 'plex')['queued'], 1)

    def test_episode_is_stored_as_series_episode(self):
        r = self.enqueue('e.ep0011')
        job = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (r['id'],)).fetchone()[0])
        meta = job['metadata']
        self.assertEqual((meta['kind'], meta['title'], meta['season'], meta['episode'], meta['episode_title']),
                         ('series', 'Die Serie', 1, 1, 'Anfang'))

    def test_protected_series_and_channels_are_refused(self):
        for item, text in (('m.m001abc', 'Kopierschutz'), ('m.m002abc', 'Kopierschutz'), ('s.show001', 'einzelne Folge'),
                           ('c.5e20b730f2f8d5003d739db7-abc123', 'Live-Sender'), ('m.nope000', 'nicht im Katalog'), ('../x', 'Ungültig')):
            with self.assertRaisesRegex(ValueError, text):
                self.enqueue(item)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)
        # Known as protected: refused without asking Plex again.
        calls = len(self.fake.calls)
        with self.assertRaisesRegex(ValueError, 'umgeht ihn nicht'):
            self.enqueue('m.m001abc')
        self.assertEqual(len(self.fake.calls), calls)

    def test_download_resolves_fresh_address_and_keeps_the_token_off_disk(self):
        job = pd.build_job(self.root, self.media, 'm.m000abc', now=1000, check=self.check)
        real = plex.play_source
        with mock.patch.object(plex, 'play_source', lambda root, item_id: real(root, item_id, opener=self.fake,
                                                                               fetch_token=self.fake.fetch_token, now=NOW)):
            url = downloads._source_url(job['source'])
        self.assertIn('X-Plex-Token=', url)
        self.assertIn('plex', downloads.HLS_RESOLVERS)                   # ffmpeg copies HLS and DASH
        self.assertEqual(downloads.public_url(job['source'], url), url.split('?', 1)[0])

    def test_title_page_and_routes(self):
        self.assertTrue(portal_title.model(self.root, 'plex', 'm.m000abc')['offline']['allowed'])
        self.check(self.root, 'm.m000abc')
        m = portal_title.model(self.root, 'plex', 'm.m000abc')
        self.assertEqual(m['offline'], {'allowed': True, 'days': 30, 'night': False})
        self.assertTrue(any('30 Tage offline' in f[1] for f in m['provider_facts']))
        with self.assertRaises(Exception):
            self.check(self.root, 'm.m001abc')
        self.assertFalse(portal_title.model(self.root, 'plex', 'm.m001abc')['offline']['allowed'])
        self.assertIn(('POST', '/api/plex-download-add'), platform_registry.routes())
        self.assertIs(platform_registry.BY_KEY['plex'].offline, pd)

    def test_wiring(self):
        web = ROOT / 'web'
        self.assertIn("plex: {name: 'Plex', action: 'offline-download-action'}", (web / 'offline_button.js').read_text())
        self.assertIn("add: 'plex-download-add'", (web / 'portal_title.js').read_text())
        self.assertIn('<details id="plex-offline" class="nk-offline plex-offline">', (web / 'index.html').read_text())
        self.assertIn('offlineNote', (web / 'plex.js').read_text())
        self.assertIn("'plex_downloads.py'", (ROOT / 'build_macos.py').read_text())
        self.assertIn("'offline_days':plex_downloads.OFFLINE_DAYS", (ROOT / 'server.py').read_text())


class NetworkProbeTrustStoreTest(unittest.TestCase):
    def test_probe_uses_the_patched_https_context(self):
        # Björn's diagnosis 14.11.2026: all 21 hosts "certificate" although the catalogues loaded
        # with the macOS fallback bundle; the probe built its own bare context.
        made = []

        def context(*a, **k):
            made.append(True)
            raise ssl.SSLCertVerificationError('stop')
        with mock.patch.object(ssl, '_create_default_https_context', context), \
                mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('1.2.3.4', 443))]):
            rows = netcheck.probe(('example.invalid',), timeout=0.1)
        self.assertEqual(made, [True])
        self.assertEqual(rows[0]['error'], 'certificate')


if __name__ == '__main__':
    unittest.main()
