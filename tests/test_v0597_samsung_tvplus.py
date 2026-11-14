"""0.5.97: Samsung TV Plus live channels in the Live-TV tab.

The list below has the shape of the public channel list (i.mjh.nz/SamsungTVPlus/.channels.json.gz,
checked on 13.11.2026: 216 channels for Germany, 16 of them with ``license_url`` = Widevine).
Names and numbers here are made up."""
import gzip
import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

import hls_guard
import live_tv
import samsung_tvplus as stv
import streaming

NOW = 1794556800


def sample():
    return {'slug': 'stvp-{id}', 'headers': {'user-agent': 'okhttp/4.12.0'}, 'regions': {
        'de': {'name': 'Germany', 'logo': 'https://flagcdn.com/h240/de.png', 'channels': {
            'DEBD2600001AA': {'name': 'Krimi Kanal', 'chno': 4601, 'group': 'Crime',
                              'logo': 'https://tvpnlogopeu.samsungcloud.tv/a.png', 'description': 'Spannung rund um die Uhr.',
                              'programs': [[NOW - 7200, 'Alt'], [NOW - 600, 'Der Fall'], [NOW + 1200, 'Der nächste Fall']]},
            'DE2600002BB': {'name': 'Doku Welt', 'chno': 4520, 'group': 'Dokus & Wissen',
                            'logo': 'javascript:alert(1)', 'description': '', 'programs': []},
            'DE2600003CC': {'name': 'Geschützt', 'chno': 4700, 'group': 'Filme', 'logo': '', 'description': '',
                            'license_url': 'https://example.invalid/wv', 'programs': []},
            '../bad': {'name': 'Kaputt', 'chno': 1}}},
        'at': {'name': 'Austria', 'channels': {'AT1000001': {'name': 'Nur Österreich', 'chno': 1, 'group': 'News'}}}}}


class SamsungTvPlusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        stv._SOURCES.clear()
        live_tv._LAST.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_skips_protected_and_invalid(self):
        channels, protected, slug = stv.parse(sample(), 'de', NOW)
        self.assertEqual([c['title'] for c in channels], ['Doku Welt', 'Krimi Kanal'])   # sorted by number
        self.assertEqual(protected, 1)
        self.assertEqual(slug, 'stvp-{id}')
        doku, krimi = channels
        self.assertEqual(doku['logo'], '')                       # only https addresses
        self.assertEqual(krimi['programs'][0], [NOW - 600, 'Der Fall'])   # finished entries dropped
        with self.assertRaises(ValueError):
            stv.parse({'regions': {}}, 'de', NOW)
        bad = sample(); bad['slug'] = 'https://evil/{id}'
        with self.assertRaises(ValueError):
            stv.parse(bad, 'de', NOW)

    def test_sync_store_state_and_failure_keeps_list(self):
        packed = gzip.compress(json.dumps(sample()).encode())
        self.assertEqual(stv.parse(json.loads(gzip.GzipFile(fileobj=io.BytesIO(packed)).read()), 'de', NOW)[1], 1)
        result = stv.sync(self.root, fetch=sample, now=NOW)
        self.assertEqual(result, {'ok': True, 'channels': 2, 'protected': 1})
        st = stv.state(self.root)
        self.assertEqual((st['channels'], st['protected'], st['last_result'], st['auto']), (2, 1, 'ok', True))
        self.assertEqual(st['next_attempt'], NOW + stv.REFRESH)

        def broken():
            raise urllib.error.URLError(OSError('kein Netz'))
        result = stv.sync(self.root, fetch=broken, now=NOW + 99)
        self.assertFalse(result['ok'])
        st = stv.state(self.root)
        self.assertEqual((st['channels'], st['last_result']), (2, 'error'))
        self.assertIn('nicht erreichbar', st['last_error'])
        self.assertEqual(st['next_attempt'], NOW + 99 + stv.RETRY)
        self.assertNotIn('i.mjh.nz/SamsungTVPlus', json.dumps(stv.summary(self.root)))

    def test_due_rules(self):
        st = stv.state(self.root)
        self.assertTrue(stv.due(st, NOW))                 # first start
        stv.sync(self.root, fetch=sample, now=NOW)
        self.assertFalse(stv.due(stv.state(self.root), NOW + 60))
        self.assertTrue(stv.due(stv.state(self.root), NOW + stv.REFRESH + 1))
        stv.set_auto(self.root, False)
        self.assertFalse(stv.due(stv.state(self.root), NOW + stv.REFRESH + 1))
        with self.assertRaises(ValueError):
            stv.set_auto(self.root, 'ja')
        with self.assertRaises(ValueError):
            stv.set_region(self.root, 'us')
        self.assertEqual(stv.set_region(self.root, 'at')['region'], 'at')

    def test_now_next_text(self):
        progs = [[NOW - 600, 'Der Fall'], [NOW + 1200, 'Der nächste Fall']]
        text = stv.now_next(progs, NOW)
        self.assertTrue(text.startswith('Jetzt: Der Fall · danach '))
        self.assertTrue(text.endswith('Der nächste Fall'))
        self.assertTrue(stv.now_next(progs, NOW - 3600).startswith('Ab '))
        self.assertEqual(stv.now_next([], NOW), '')

    def test_live_tv_lists_samsung_channels(self):
        stv.sync(self.root, fetch=sample, now=time.time())
        import sqlite3
        c = sqlite3.connect(':memory:')
        c.executescript('CREATE TABLE works(id INTEGER, topic TEXT); CREATE TABLE offers(id INTEGER, work_id INTEGER, payload TEXT, active INTEGER, rank INTEGER);')
        data = live_tv.overview(c, self.root, provider='samsung')
        self.assertEqual({s['name'] for s in data['stations']}, {'Krimi Kanal', 'Doku Welt'})
        src = next(s for s in data['stations'] if s['name'] == 'Krimi Kanal')['sources'][0]
        self.assertEqual(src['play'], {'samsung': 'DEBD2600001AA'})
        self.assertEqual(src['provider_name'], 'Samsung TV Plus')
        counts = {p['key']: p['channels'] for p in data['providers']}
        self.assertEqual(counts['samsung'], 2)

    def test_play_source_checks_and_caches(self):
        stv.sync(self.root, fetch=sample, now=NOW)
        asked, checked = [], []

        def resolver(url):
            asked.append(url)
            return 'https://cdn.example.net/live/master.m3u8'
        src = stv.play_source(self.root, 'DEBD2600001AA', resolver=resolver, check=checked.append, now=NOW)
        self.assertEqual(asked, ['https://jmp2.uk/stvp-DEBD2600001AA'])
        self.assertEqual(checked, ['https://cdn.example.net/live/master.m3u8'])
        self.assertEqual((src['provider'], src['live'], src['hls'], src['title']), ('samsung', True, True, '4601 · Krimi Kanal'))
        stv.play_source(self.root, 'DEBD2600001AA', resolver=resolver, check=checked.append, now=NOW + 10)
        self.assertEqual(len(asked), 1)                    # cached for two minutes
        with self.assertRaises(ValueError):
            stv.play_source(self.root, 'DE2600003CC', resolver=resolver, check=checked.append, now=NOW)  # protected: not listed
        with self.assertRaises(ValueError):
            stv.play_source(self.root, '../x', resolver=resolver, check=checked.append, now=NOW)

        def drm(url):
            raise hls_guard.DrmProtected('x')
        with self.assertRaises(hls_guard.DrmProtected) as caught:
            stv.play_source(self.root, 'DE2600002BB', resolver=resolver, check=drm, now=NOW)
        self.assertIn('umgeht ihn nicht', str(caught.exception))

    def test_streaming_resolve_routes_samsung(self):
        stv.sync(self.root, fetch=sample, now=time.time())
        stv._SOURCES['DEBD2600001AA'] = (time.time() + 60, 'https://cdn.example.net/x.m3u8')
        src = streaming.resolve(None, root=self.root, samsung='DEBD2600001AA')
        self.assertEqual(src['url'], 'https://cdn.example.net/x.m3u8')
        plan = streaming.plan(src, levels=False)
        self.assertEqual((plan['mode'], plan['provider'], plan.get('live')), ('remux', 'samsung', True))

    def test_wiring(self):
        here = Path(__file__).resolve().parent.parent
        server = (here / 'server.py').read_text(encoding='utf-8')
        for needle in ("'toggo','crunchyroll','samsung','plex','servustv','rtlplus')", "samsung=q.get('samsung',[''])[0]", "@ROUTES.post('/api/samsung-sync')",
                       "planner.CatalogJob('samsung',samsung_tvplus)", "'samsung':samsung_tvplus.summary(ROOT)", "spec.get('portal')=='samsung'"):
            self.assertIn(needle, server)
        self.assertIn("'samsung_tvplus.py'", (here / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn('catalog:samsung', __import__('task_control').TASKS)
        js = (here / 'web' / 'live_tv.js').read_text(encoding='utf-8')
        self.assertIn("'samsung-sync'", js)
        self.assertIn("'samsung'", (here / 'web' / 'player.js').read_text(encoding='utf-8'))
        self.assertIn('jmp2.uk', __import__('netcheck').CATALOG_HOSTS)


if __name__ == '__main__':
    unittest.main()
