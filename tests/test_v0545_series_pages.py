"""0.5.45: series pages with all episodes, the same for Netzkino, Pluto TV and JustWatch TV."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

SERIES = '5f1a2b3c4d5e6f7a8b9c0d10'


class SeriesModelTests(unittest.TestCase):
    def setUp(self):
        import pluto
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        db = pluto._connect(self.root)
        cols = 'id,kind,title,slug,series_id,season,episode,number,year,duration,rating,genre,summary,poster,path,category,seen,updated'
        rows = [(SERIES, 'series', '21 Jump Street', '21-jump-street', '', None, None, None, 1987, None, 'FSK 12', 'Krimi', 'Undercover',
                 'https://images.pluto.tv/s.jpg', '', 'Krimi', 1, 1),
                ('5f1a2b3c4d5e6f7a8b9c0d12', 'episode', 'Folge B', 'b', SERIES, 2, 1, None, None, 2700, '', '', '', '', '/x', '', 1, 1),
                ('5f1a2b3c4d5e6f7a8b9c0d11', 'episode', 'Folge A', 'a', SERIES, 1, 2, None, None, 2700, '', '', 'Inhalt', '', '/y', '', 1, 1),
                ('5f1a2b3c4d5e6f7a8b9c0d13', 'episode', 'Pilot', 'p', SERIES, 1, 1, None, None, 2700, '', '', '', '', '/z', '', 1, 1)]
        with db:
            db.executemany('INSERT INTO pluto_items(%s) VALUES(%s)' % (cols, ','.join('?' * 18)), rows)
            pluto._set(db, 'series_checked:' + SERIES, time.time())  # no network in tests
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_series_model_carries_sorted_episodes(self):
        import portal_title
        m = portal_title.model(self.root, 'pluto', SERIES)
        self.assertEqual(m['kind'], 'series')
        self.assertEqual([(e['season'], e['episode']) for e in m['episodes']], [(1, 1), (1, 2), (2, 1)])
        first = m['episodes'][0]
        self.assertEqual(set(first), {'id', 'title', 'season', 'episode', 'duration', 'year', 'summary', 'poster',
                                      'playable', 'offline', 'night', 'protected', 'web_url'})
        # Episodes without artwork use the series poster.
        self.assertEqual(first['poster'], 'https://images.pluto.tv/s.jpg')
        self.assertTrue(first['playable']); self.assertTrue(first['offline'])

    def test_episode_rows_are_the_same_for_every_portal(self):
        import portal_title
        nk = portal_title._episode('netzkino', {'id': 'abc', 'episode_title': 'Einsatz', 'season': '1', 'episode': 3})
        jw = portal_title._episode('justwatch', {'id': 'tse1', 'title': 'Folge 1', 'season': 1, 'episode': 1, 'playable': 0, 'night': 1})
        self.assertEqual(set(nk), set(jw))
        self.assertEqual((nk['season'], nk['episode'], nk['title']), (1, 3, 'Einsatz'))
        self.assertFalse(jw['playable']); self.assertTrue(jw['offline']); self.assertTrue(jw['night'])
        self.assertFalse(nk['night'])
        self.assertIsNone(portal_title._episode('pluto', {'id': 'x', 'season': -1})['season'])


class NetzkinoSeriesIdTests(unittest.TestCase):
    def test_episode_and_group_share_the_series_id(self):
        import netzkino
        cls = netzkino.classify_media({'title': 'Acapulco H.E.A.T. Staffel 1 - 1. Einsatz wider Willen (1)'})
        self.assertEqual(cls['media_type'], 'episode')
        key = netzkino.series_id(cls['series_title'])
        self.assertRegex(key, r'^series-[a-f0-9]{24}$')
        self.assertEqual(key, netzkino.series_id(cls['series_title'].upper()))
        self.assertEqual(netzkino.series_id(''), '')

    def test_unknown_netzkino_series_is_rejected(self):
        import portal_title
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                portal_title.model(Path(tmp), 'netzkino', 'series-' + '0' * 24)


class JobListingTests(unittest.TestCase):
    def test_listing_for_many_episode_ids(self):
        import netzkino_downloads
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, payload TEXT, state TEXT)')
        for i in range(5):
            job = {'id': 'j%d' % i, 'origin': 'pluto', 'pluto_id': 'e%d' % i, 'target': '/t/%d.mkv' % i}
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (job['id'], json.dumps(job), 'queued'))
        got = netzkino_downloads.listing(c, item_id=['e1', 'e3'], origin='pluto')
        self.assertEqual(sorted(j['pluto_id'] for j in got['items']), ['e1', 'e3'])
        self.assertEqual(len(netzkino_downloads.listing(c, item_id='e2', origin='pluto')['items']), 1)


class WiringTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / 'web' / name).read_text(encoding='utf-8')

    def test_title_page_uses_model_episodes_with_season_tabs(self):
        js = self.read('portal_title.js')
        self.assertIn('m.episodes', js)
        self.assertIn("'tv-tabs'", js)
        self.assertIn("'Staffel ' + s", js)
        self.assertNotIn('view=episodes&series=', js)

    def test_every_provider_opens_the_series_page(self):
        self.assertIn('openDetail(item.id) ||', self.read('portal_panel.js'))
        self.assertIn("AtlasPortalTitle?.open('netzkino', item.series_key)", self.read('netzkino.js'))
        self.assertIn("AtlasPortalTitle.open('netzkino',item.series_key)", self.read('unified_catalog.js'))

    def test_server_accepts_episode_id_lists(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertEqual(server.count('item_id=job_ids(q)') + sum(p.jobs for p in __import__('_wiring').registry.PLATFORMS), 7)   # + Rakuten TV (0.5.49), YouTube (0.5.53), Joyn (0.5.65), TOGGO (0.5.79)


if __name__ == '__main__':
    unittest.main()
