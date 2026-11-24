"""Programmführer (epg.py): programme data of ARD, ZDF and SRF for the Live-TV tab and as recognition evidence.

The SRF sample is shortened from a real answer of il.srgssr.ch (21.11.2026); the ARD sample follows a real answer of
programm-api.ard.de (20.11.2026); the ZDF sample follows the documented answer in mediathekview/zapp-backend."""
import datetime
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog, epg, live_tv  # noqa: E402

SRF = {'programGuide': [
    {'channel': {'id': '23ffbe1b', 'title': 'SRF 1', 'vendor': 'SRF'}, 'programList': [
        {'title': 'Tagesschau', 'startTime': '2026-11-21T19:30:00+01:00', 'endTime': '2026-11-21T19:55:00+01:00',
         'genre': 'News', 'productionYear': 2026, 'productionCountry': 'Schweiz', 'subtitle': 'Hauptausgabe',
         'isLive': False, 'isRepetition': False, 'mediaUrn': 'urn:srf:video:b217f65d-5329-49c1-90df-eb77c5bc9755'},
        {'title': 'Arena', 'startTime': '2026-11-21T02:35:00+01:00', 'endTime': '2026-11-21T03:45:00+01:00',
         'lead': 'An der Klimakonferenz verhandelt die Welt über den Ausstieg aus den Fossilen.', 'genre': 'Info / Dok (alt)',
         'subtitle': 'Raus aus den Fossilen – aber wie?', 'isRepetition': True,
         'mediaUrn': 'urn:srf:video:6dc690da-228f-4859-8be6-8fb0864dc84e'}]},
    {'channel': {'id': 'e4d5ad08', 'title': 'SRF zwei', 'vendor': 'SRF'}, 'programList': [
        {'title': 'Transplant – Ein besonderer Notarzt', 'startTime': '2026-11-21T00:45:00+01:00',
         'endTime': '2026-11-21T01:25:00+01:00', 'genre': 'Arzt (alt)', 'productionYear': 2022, 'productionCountry': 'Kanada',
         'subtitle': 'Noch schlimmer', 'seasonNumber': 2, 'episodeNumber': 9, 'episodesTotal': 13, 'isRepetition': False,
         'mediaUrn': 'urn:srf:video:3280d1e7-5eec-4de9-92ef-e258b82f69fe'},
        {'title': 'Meine Stunden mit Leo', 'startTime': '2026-11-21T01:25:00+01:00', 'endTime': '2026-11-21T03:00:00+01:00',
         'genre': 'Drama', 'productionYear': 2022, 'productionCountry': 'Grossbritannien', 'isRepetition': True,
         'originalTitle': 'Good Luck to You, Leo Grande', 'mediaUrn': 'not-an-urn'}]},
    {'channel': {'id': '34c2819e', 'title': 'SRF info', 'vendor': 'SRF'}, 'programList': [
        {'title': '10 vor 10', 'startTime': '2026-11-21T00:20:00+01:00', 'endTime': '2026-11-21T00:45:00+01:00',
         'genre': 'News', 'isRepetition': True}, 'kaputt', {'title': '', 'startTime': '2026-11-21T00:45:00+01:00'}]}]}

ARD = {'channels': [{'id': 'daserste', 'timeSlots': [[
    {'id': 'a1', 'type': 'epg', 'title': 'ARD-Morgenmagazin', 'coreTitle': 'ARD-Morgenmagazin', 'duration': 12600,
     'channel': {'id': 'daserste', 'name': 'Das Erste'}, 'broadcastedOn': '2026-11-20T05:30:00+01:00',
     'broadcastEnd': '2026-11-20T09:00:00+01:00', 'subline': 'Moderation: Anna Planken und Till Nassif',
     'synopsis': 'Themen:\n* Klimakonferenz'},
    {'id': 'a2', 'type': 'epg', 'title': 'Tatort: Tod im Park', 'coreTitle': 'Tatort', 'duration': 5400,
     'channel': {'id': 'daserste', 'name': 'Das Erste'}, 'broadcastedOn': '2026-11-20T20:15:00+01:00'}]]},
    {'id': 'ndr', 'timeSlots': [[{'id': 'n1', 'type': 'epg', 'title': 'Hallo Niedersachsen', 'duration': 1800,
                                  'channel': {'id': 'ndr', 'name': 'NDR'}, 'broadcastedOn': '2026-11-20T19:30:00+01:00',
                                  'broadcastEnd': '2026-11-20T20:00:00+01:00'},
                                 {'id': 'x', 'type': 'teaser', 'title': 'Werbung', 'broadcastedOn': '2026-11-20T19:00:00+01:00'}]]}]}

ZDF = {'http://zdf.de/rels/cmdm/broadcasts': [
    {'airtimeBegin': '2020-08-26T09:05:00+02:00', 'airtimeEnd': '2020-08-26T10:30:00+02:00', 'live': False,
     'tvService': 'ZDF', 'http://zdf.de/rels/tvservice': {'tvServiceTitle': 'ZDF', 'tvServiceId': 'ZDF'},
     'title': 'Volle Kanne - Service täglich', 'primaryBrand': 'Volle Kanne', 'subtitle': None,
     'text': '<b>Pasta aus dem Kühlregal</b><br/>Ist teurer auch gleich besser?'},
    {'airtimeBegin': '2020-08-26T19:00:00+02:00', 'airtimeEnd': '2020-08-26T19:20:00+02:00',
     'http://zdf.de/rels/tvservice': {'tvServiceTitle': '3sat'}, 'title': 'heute', 'primaryBrand': 'heute'}]}


def stamp(text):
    return int(datetime.datetime.fromisoformat(text).timestamp())


class Parsers(unittest.TestCase):
    def test_srf_fields_and_station_keys(self):
        rows = {(r['station'], r['title']): r for r in epg.parse_srf(SRF)}
        self.assertEqual(set(k[0] for k in rows), {'srf1', 'srfzwei', 'srfinfo'})
        news = rows[('srf1', 'Tagesschau')]
        self.assertEqual((news['genre'], news['subtitle'], news['year'], news['repeat']), ('News', 'Hauptausgabe', 2026, 0))
        self.assertEqual(news['media'], 'urn:srf:video:b217f65d-5329-49c1-90df-eb77c5bc9755')
        self.assertEqual(news['start'], stamp('2026-11-21T19:30:00+01:00'))
        self.assertEqual(news['stop'] - news['start'], 25 * 60)
        series = rows[('srfzwei', 'Transplant – Ein besonderer Notarzt')]
        self.assertEqual((series['season'], series['episode'], series['episodes']), (2, 9, 13))
        film = rows[('srfzwei', 'Meine Stunden mit Leo')]
        self.assertEqual((film['genre'], film['media'], film['repeat']), ('Drama', '', 1))   # broken urn is dropped
        self.assertIn(('srfinfo', '10 vor 10'), rows)
        self.assertEqual(len(rows), 5)                                                   # broken entries skipped

    def test_ard_show_and_edition(self):
        rows = {r['title']: r for r in epg.parse_ard(ARD)}
        self.assertEqual(set(rows), {'ARD-Morgenmagazin', 'Tatort', 'Hallo Niedersachsen'})
        self.assertEqual(rows['ARD-Morgenmagazin']['subtitle'], '')       # „Moderation: …“ is no edition title
        self.assertEqual(rows['ARD-Morgenmagazin']['station'], 'daserste')
        self.assertEqual(rows['Tatort']['subtitle'], 'Tod im Park')
        self.assertEqual(rows['Tatort']['stop'] - rows['Tatort']['start'], 5400)  # from the duration
        self.assertEqual(rows['Hallo Niedersachsen']['station'], 'ndr')

    def test_zdf_brand_becomes_show(self):
        rows = epg.parse_zdf(ZDF)
        self.assertEqual([(r['station'], r['title'], r['subtitle']) for r in rows],
                         [('zdf', 'Volle Kanne', 'Service täglich'), ('3sat', 'heute', '')])
        self.assertNotIn('<b>', rows[0]['description'])

    def test_garbage_never_raises(self):
        for parse in (epg.parse_srf, epg.parse_ard, epg.parse_zdf):
            for value in (None, [], 'x', {'programGuide': 'x', 'channels': {}, 'http://zdf.de/rels/cmdm/broadcasts': None}):
                self.assertEqual(parse(value), [])


class Runs(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        epg._ZDF_TOKEN.clear()
        self.calls = []

    def fake(self, answers):
        def fetch(url, headers):
            self.calls.append(url)
            for key, value in answers.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return value(url) if callable(value) else value
            return None
        return fetch

    def test_first_run_fills_and_later_runs_skip_final_days(self):
        now = stamp('2026-11-21T12:00:00+01:00')
        fetch = self.fake({'il.srgssr.ch': SRF, 'programm-api.ard.de': ARD, 'mediathekV2/token': {'token': 'x' * 40},
                           'api.zdf.de/cmdm': ZDF})
        result = epg.sync(self.root, fetch=fetch, now=now)
        self.assertEqual(result['result'], 'ok')
        days = epg.BACKFILL_DAYS + epg.AHEAD_DAYS + 1
        self.assertEqual(sum('il.srgssr.ch' in u for u in self.calls), days)
        st = epg.state(self.root)
        self.assertEqual(st['last_result'], 'ok')
        self.assertGreater(st['broadcasts'], 5)
        self.assertEqual(st['next_attempt'], now + epg.REFRESH)
        self.calls.clear()
        epg.sync(self.root, fetch=fetch, now=now + epg.REFRESH)
        # only yesterday … AHEAD_DAYS are fetched again, older days are final
        self.assertEqual(sum('il.srgssr.ch' in u for u in self.calls), epg.AHEAD_DAYS + 2)

    def test_unreachable_source_does_not_stop_the_others(self):
        now = stamp('2026-11-21T12:00:00+01:00')
        fetch = self.fake({'il.srgssr.ch': SRF, 'programm-api.ard.de': epg.Unavailable('HTTP 503'),
                           'mediathekV2/token': epg.Unavailable('Netzwerkfehler'), 'www.zdf.de': ''})
        result = epg.sync(self.root, fetch=fetch, now=now)
        self.assertEqual(result['result'], 'partial')
        self.assertTrue(result['sources']['ard']['error'])
        self.assertIn('Gast-Token', result['sources']['zdf']['error'])
        self.assertGreater(result['sources']['srf']['broadcasts'], 0)
        self.assertEqual(sum('programm-api.ard.de' in u for u in self.calls), 1)     # stops after the first failure

    def test_zdf_token_from_page_when_token_service_fails(self):
        fetch = self.fake({'mediathekV2/token': epg.Unavailable('HTTP 403'),
                           'www.zdf.de/live-tv': '<script>{"videoToken":{"apiToken":"%s"}}</script>' % ('a' * 40)})
        self.assertEqual(epg._zdf_token(fetch), 'Bearer ' + 'a' * 40)

    def test_should_sync_and_switch(self):
        self.assertTrue(epg.should_sync(self.root))            # first start
        epg.set_auto(self.root, False)
        self.assertFalse(epg.should_sync(self.root))
        with self.assertRaises(ValueError):
            epg.set_auto(self.root, 'ja')

    def test_old_broadcasts_are_removed(self):
        now = time.time()
        db = epg.connect(self.root)
        with db:
            epg.store(db, [epg._row('srf', 'SRF 1', int(now - (epg.KEEP_DAYS + 2) * 86400), None, 'Alt')], now)
        db.close()
        epg.sync(self.root, fetch=self.fake({}), now=now)
        self.assertEqual(epg.state(self.root)['broadcasts'], 0)


class LiveTab(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)

    def put(self, channel, start, stop, title, **extra):
        db = epg.connect(self.root)
        with db:
            epg.store(db, [epg._row('ard', channel, int(start), int(stop), title, **extra)])
        db.close()

    def test_now_next_and_line(self):
        now = time.time()
        self.put('Das Erste', now - 600, now + 300, 'Tagesschau')
        self.put('Das Erste', now + 300, now + 3600, 'Tatort', subtitle='Tod im Park')
        self.put('ZDF', now + 7200, now + 9000, 'heute-journal')
        guide = epg.now_next(self.root, now=now)
        self.assertEqual(guide['daserste']['now']['title'], 'Tagesschau')
        self.assertEqual(guide['daserste']['next']['subtitle'], 'Tod im Park')
        self.assertIsNone(guide['zdf']['now'])
        self.assertTrue(epg.line(guide['daserste']).startswith('Jetzt: Tagesschau · danach '))
        self.assertTrue(epg.line(guide['zdf']).startswith('Ab '))
        self.assertEqual(epg.now_next(self.root, ['zdf'], now=now).keys(), {'zdf'})

    def test_overview_shows_programme(self):
        now = time.time()
        self.put('Das Erste', now - 600, now + 300, 'Tagesschau')
        catalog.ingest(self.c, [{'channel': 'ARD', 'topic': 'Livestream', 'title': 'Das Erste Livestream', 'description': 'Der Sender',
                                 'timestamp': 0, 'duration': 0, 'size': 0, 'url_video': 'https://live.example/a.m3u8',
                                 'url_video_hd': '', 'url_video_low': '', 'url_subtitle': '', 'url_website': '', 'geo': ''}], seen=1)
        data = live_tv.overview(self.c, self.root)
        st = next(s for s in data['stations'] if s['key'] == 'daserste')
        self.assertEqual(st['programme']['now']['title'], 'Tagesschau')
        self.assertTrue(st['summary'].startswith('Jetzt: Tagesschau'))
        self.assertTrue(st['summary'].endswith('— Der Sender'))
        json.dumps(data)

    def test_without_guide_nothing_changes(self):
        self.assertEqual(epg.now_next(self.root), {})
        self.assertEqual(epg.schedule(self.root, 'daserste'), [])

    def test_schedule_of_a_day(self):
        base = datetime.datetime(2026, 11, 21, 6, 0).timestamp()
        self.put('Das Erste', base, base + 1800, 'Früh')
        self.put('Das Erste', base + 86400, base + 86400 + 1800, 'Nächster Tag')
        self.assertEqual([b['title'] for b in epg.schedule(self.root, 'daserste', '2026-11-21')], ['Früh'])
        with self.assertRaises(ValueError):
            epg.schedule(self.root, 'daserste', '21.11.2026')


class Evidence(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.db = epg.connect(Path(t.name)); self.addCleanup(self.db.close)
        with self.db:
            epg.store(self.db, epg.parse_srf(SRF) + epg.parse_ard(ARD))

    def test_srf_by_video_id(self):
        hit = epg.match(self.db, {'channel': 'SRF', 'timestamp': 1,
                                  'url_website': 'https://www.srf.ch/play/tv/x/video/y?urn=urn:srf:video:3280d1e7-5eec-4de9-92ef-e258b82f69fe'})
        self.assertEqual(hit['how'], 'media')
        self.assertEqual((hit['broadcast']['season'], hit['broadcast']['episode']), (2, 9))
        self.assertEqual(epg.kind_hint(hit['broadcast']), 'show')

    def test_by_station_and_time(self):
        start = stamp('2026-11-20T20:15:00+01:00')
        hit = epg.match(self.db, {'channel': 'ARD', 'timestamp': start + 60, 'duration': 5300})
        self.assertEqual((hit['how'], hit['broadcast']['title'], hit['broadcast']['subtitle']), ('time', 'Tatort', 'Tod im Park'))
        self.assertIsNone(epg.match(self.db, {'channel': 'ARD', 'timestamp': start + 60, 'duration': 180}))   # a clip
        self.assertIsNone(epg.match(self.db, {'channel': 'ARD', 'timestamp': start + 1800, 'duration': 5300}))
        self.assertIsNone(epg.match(self.db, {'channel': 'ZDF', 'timestamp': start, 'duration': 5300}))

    def test_kind_hint(self):
        self.assertEqual(epg.kind_hint({'genre': 'News'}), 'show')
        self.assertEqual(epg.kind_hint({'genre': 'Spielfilm'}), 'movie')
        self.assertEqual(epg.kind_hint({'genre': 'Drama'}), 'movie')
        self.assertEqual(epg.kind_hint({'genre': 'Drama', 'episode': 3}), 'show')
        self.assertEqual(epg.kind_hint({'genre': ''}), '')


class LiveFindings0129(unittest.TestCase):
    """0.6.129: Befunde L1–L5 aus Björns erstem Echtlauf (Diagnose 24.11.2026, Abschnitt 11)."""
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)

    def put(self, source, channel, start, stop, title, **extra):
        db = epg.connect(self.root)
        with db:
            epg.store(db, [epg._row(source, channel, int(start), int(stop), title, **extra)])
        db.close()

    def test_l3_shortest_running_and_one_source(self):
        now = time.time()
        self.put('zdf', 'phoenix', now - 3600, now + 8 * 3600, 'PHOENIX', subtitle='vor ort')
        self.put('ard', 'phoenix', now - 3600, now + 8 * 3600, 'phoenix vor ort')
        self.put('ard', 'phoenix', now - 600, now + 900, 'Bundestag', subtitle='110. Sitzung')
        self.put('ard', 'phoenix', now + 900, now + 2000, 'phoenix der tag')
        slot = epg.now_next(self.root, now=now)['phoenix']
        self.assertEqual((slot['now']['title'], slot['now']['source']), ('Bundestag', 'ard'))
        self.assertEqual(slot['next']['title'], 'phoenix der tag')
        self.assertNotIn('inside', slot['next'])

    def test_l3_next_inside_umbrella_says_ab(self):
        now = time.time()
        self.put('zdf', 'phoenix', now - 3600, now + 8 * 3600, 'PHOENIX', subtitle='vor ort')
        self.put('zdf', 'phoenix', now + 3600, now + 5400, 'phoenix vor ort', subtitle='110. Sitzung')
        slot = epg.now_next(self.root, now=now)['phoenix']
        self.assertTrue(slot['next']['inside'])
        self.assertIn(' · ab ', epg.line(slot))

    def test_l5_running_number_is_episode(self):
        data = {'channels': [{'id': 'one', 'timeSlots': [[
            {'type': 'epg', 'title': 'Rote Rosen (2019)', 'coreTitle': 'Rote Rosen (2019)', 'duration': 2880,
             'channel': {'name': 'ONE'}, 'broadcastedOn': '2026-11-24T09:00:00+01:00'}]]}]}
        row = epg.parse_ard(data)[0]
        self.assertEqual((row['station'], row['title'], row['episode'], row['subtitle']), ('one', 'Rote Rosen', 2019, ''))

    def test_l2_l4_ard_tagesschau_is_tagesschau24(self):
        self.assertEqual(live_tv.station_key(live_tv.station_name('ARD Tagesschau Livestream')), 'tagesschau24')
        self.assertEqual(live_tv.station_key('ARD-Tagesschau24'), 'tagesschau24')

    def test_l1_two_streams_of_one_provider_are_named(self):
        rows = [{'channel': 'ARTE.DE', 'topic': 'Livestream', 'title': t, 'description': '', 'timestamp': 0, 'duration': 0, 'size': 0,
                 'url_video': 'https://live.example/%d.m3u8' % i, 'url_video_hd': '', 'url_video_low': '', 'url_subtitle': '',
                 'url_website': '', 'geo': ''} for i, t in enumerate(('ARTE.DE Livestream', 'ARTE.FR Livestream'))]
        catalog.ingest(self.c, rows, seen=1)
        st = next(s for s in live_tv.overview(self.c, self.root)['stations'] if s['key'] == 'arte')
        self.assertEqual(sorted(x.get('label') for x in st['sources']), ['ARTE.DE', 'ARTE.FR'])


if __name__ == '__main__':
    unittest.main()
