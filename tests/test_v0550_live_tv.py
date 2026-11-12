"""0.5.50: Live-TV by station – broadcaster live streams from the film list and Pluto TV live channels."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
import catalog, live_tv, pluto, streaming  # noqa: E402
import test_v0536_pluto as pluto_test  # noqa: E402


def live_row(channel, title, url='https://live.example/%s/master.m3u8'):
    return {'channel': channel, 'topic': 'Livestream', 'title': title, 'description': '', 'timestamp': 0,
            'duration': 0, 'size': 0, 'url_video': url % channel.lower(), 'url_video_hd': '', 'url_video_low': '',
            'url_subtitle': '', 'url_website': '', 'geo': ''}


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row
        catalog.initialize(self.c)
        self.c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        self.c.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT)')
        pluto._SESSION.update(token='', expires=0, stitcher='', params='')
        pluto._SOURCES.clear()

    def ingest(self, *rows):
        return catalog.ingest(self.c, list(rows), seen=100)


class StationNames(unittest.TestCase):
    def test_film_list_titles_become_station_names(self):
        self.assertEqual(live_tv.station_name('Das Erste Livestream'), 'Das Erste')
        self.assertEqual(live_tv.station_name('BR Livestream Nord'), 'BR Nord')
        self.assertEqual(live_tv.station_name('ZDF HD - Livestream'), 'ZDF')
        self.assertEqual(live_tv.station_name('Livestream', 'KiKA'), 'KiKA')

    def test_spellings_map_to_one_station(self):
        for name in ('ARD', 'Das Erste', 'das erste'):
            self.assertEqual(live_tv.station_key(name), 'daserste')
        self.assertEqual(live_tv.station_key('ARTE.DE'), 'arte')
        self.assertEqual(live_tv.station_key('3Sat'), '3sat')

    def test_regional_windows_only_for_broadcasters(self):
        regional = live_tv._channel('mediathek', 'o', 'BR Livestream Nord', {'offer': 'o'}, group=live_tv.PUBLIC)
        self.assertEqual((regional['station'], regional['group']), ('BR Nord', live_tv.REGIONAL))
        pluto_like = live_tv._channel('pluto', 'p', 'Bravo Classics', {'pluto': 'p'}, group='Musik')
        self.assertEqual(pluto_like['group'], 'Musik')


class MediathekLive(Base):
    def test_livestreams_are_kept_out_of_the_work_scan(self):
        self.ingest(live_row('ARD', 'Das Erste Livestream'),
                    {**live_row('ZDF', 'Tatort'), 'topic': 'Tatort', 'url_video': 'https://cdn.example/t.mp4'})
        rows = {r['title']: r for r in self.c.execute('SELECT * FROM works')}
        live = [r for r in rows.values() if r['topic'] == 'Livestream'][0]
        self.assertEqual((live['state'], live['kind']), ('format', 'other'))
        self.assertTrue(json.loads(live['meta'])['live'])
        other = [r for r in rows.values() if r['topic'] == 'Tatort'][0]
        self.assertNotEqual(other['state'], 'format')

    def test_existing_databases_are_migrated_and_manual_decisions_stay(self):
        self.c.execute("INSERT INTO works(id,title,kind,meta,state,topic) VALUES('a','ZDF Livestream','movie','{}','pending','Livestream')")
        self.c.execute("INSERT INTO works(id,title,kind,meta,state,topic) VALUES('b','3sat Livestream','movie','{}','manual','Livestream')")
        catalog.initialize(self.c)
        states = dict(self.c.execute('SELECT id,state FROM works'))
        self.assertEqual(states, {'a': 'format', 'b': 'manual'})

    def test_overview_groups_public_stations_in_broadcast_order(self):
        self.ingest(live_row('ZDF', 'ZDF Livestream'), live_row('ARD', 'Das Erste Livestream'),
                    live_row('BR', 'BR Livestream Süd'), live_row('3Sat', '3Sat Livestream'),
                    live_row('BR', 'BR Livestream Nord'))
        data = live_tv.overview(self.c, self.root)
        names = [s['name'] for s in data['stations']]
        self.assertEqual(names[:3], ['Das Erste', 'ZDF', '3sat'])
        self.assertEqual(set(names[3:]), {'BR Nord', 'BR Süd'})
        self.assertEqual([g['name'] for g in data['groups']], [live_tv.PUBLIC, live_tv.REGIONAL])
        self.assertEqual(data['providers'][0], {'key': 'mediathek', 'name': 'ARD, ZDF & Co.', 'channels': 5, 'error': ''})
        self.assertEqual(data['stations'][0]['sources'][0]['play'].keys(), {'offer'})
        only = live_tv.overview(self.c, self.root, group=live_tv.REGIONAL)
        self.assertEqual(only['total'], 2)
        self.assertEqual(live_tv.overview(self.c, self.root, query='zdf')['total'], 1)

    def test_inactive_offers_and_non_http_links_are_skipped(self):
        self.ingest(live_row('ARD', 'Das Erste Livestream'), live_row('ZDF', 'ZDF Livestream', 'file:///%s'))
        self.c.execute('UPDATE offers SET active=0')
        self.assertEqual(live_tv.mediathek_channels(self.c), [])

    def test_playback_is_live_without_resume_length(self):
        oid = self.ingest(live_row('ARD', 'Das Erste Livestream'))[0]
        src = streaming.resolve(self.c, offer=oid)
        self.assertTrue(src['live']); self.assertEqual((src['duration'], src['title'], src['provider']), (0, 'Das Erste', 'mediathek'))
        plan = streaming.plan(src)
        self.assertTrue(plan['live']); self.assertEqual(plan['mode'], 'remux')

    def test_regular_offers_are_not_live(self):
        oid = self.ingest({**live_row('ARD', 'Film'), 'topic': 'Spielfilm', 'url_video': 'https://cdn.example/f.mp4'})[0]
        self.assertNotIn('live', streaming.resolve(self.c, offer=oid))


class PlutoLive(Base, pluto_test.Fixture):
    def setUp(self):
        Base.setUp(self)
        self.calls = []

    def test_pluto_channels_join_the_overview_and_merge_with_same_station(self):
        pluto.sync(self.root, fetch=self.fetch, now=1000)
        self.ingest(live_row('ARD', 'Das Erste Livestream'))
        data = live_tv.overview(self.c, self.root)
        counts = {p['key']: p['channels'] for p in data['providers']}
        self.assertEqual(counts, {'mediathek': 1, 'pluto': 1})
        pl = [s for s in data['stations'] if s['sources'][0]['provider'] == 'pluto'][0]
        self.assertEqual((pl['name'], pl['number'], pl['logo']), ('Pluto TV Filme', 100, 'https://images.pluto.tv/channels/logo.png'))
        self.assertEqual(pl['sources'][0]['play'], {'pluto': '5ce4475cd43850831ca91ce7'})
        self.assertEqual(live_tv.overview(self.c, self.root, provider='pluto')['total'], 1)
        # A station at two providers is one entry with two buttons.
        merged = live_tv._channel('pluto', 'x', 'ZDF', {'pluto': 'x'}, group='News')
        self.assertEqual(merged['key'], live_tv.station_key('ZDF Livestream'.replace(' Livestream', '')))

    def test_summary_has_counters_only(self):
        pluto.sync(self.root, fetch=self.fetch, now=1000)
        s = live_tv.summary(self.c, self.root)
        self.assertEqual(s['channels'], {'mediathek': 0, 'pluto': 1})
        self.assertNotIn('Pluto TV Filme', json.dumps(s))


if __name__ == '__main__':
    unittest.main()
