"""0.6.45 (Björn, 20.11.2026): Wiedergabe-Störungen und Speicherbudget für YouTube-Abos.

* ServusTV: in jeder Diagnose vom 16.–20.11. dieselben 15 Seiten mit HTTP 403 (0 erholt). Eine verweigerte
  Seite wird gemerkt und 7 Tage ohne Anfrage übersprungen, danach einmal ohne Pausen erneut geprüft.
* „Der Player ist nicht geladen“: Titel von Joyn, RTL+ und Crunchyroll (nur Anbieter-Player) landeten in dieser
  Meldung; die Meldung selbst geht jetzt mit Befund in die Diagnose.
* YouTube-Abos: Speicherbudget je Abo (GB) und gemeinsame Reserve an freiem Speicher.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import servustv  # noqa: E402
import youtube as yt, youtube_abos as ab, watch_state  # noqa: E402
import portal_title  # noqa: E402
from test_v0601_servustv import Base as ServusBase, FakeServus, NOW as SNOW  # noqa: E402
from test_v0607_youtube_abos import Fixture, KIDS, NOW, vid, video  # noqa: E402

REFUSED = '/products/v5.3/stv/de/de/AA-25RX849FN1W11'


class ServusRefusedPages(ServusBase):
    def run_sync(self, fake, now, waits=(0, 0)):
        return servustv.sync(self.root, opener=fake, now=now, waits=waits)

    def requests_for(self, fake, fragment):
        return sum(1 for c in fake.calls if fragment in c[1])

    def test_refused_page_is_remembered_and_skipped(self):
        fake = FakeServus()
        fake.refuse = {REFUSED: 99}
        self.assertTrue(self.run_sync(fake, SNOW)['ok'])
        self.assertEqual(fake.refuse[REFUSED], 99 - 3)                       # first run: three tries
        db = servustv._connect(self.root)
        try:
            kept = json.loads(servustv._get(db, 'refused_pages'))
        finally:
            db.close()
        self.assertEqual(list(kept), [REFUSED])
        # next day: no request at all for the known page, run still complete
        events = []
        with mock.patch.object(servustv, '_notify', lambda e, **d: events.append((e, d))):
            result = self.run_sync(fake, SNOW + 86400)
        self.assertFalse(result['partial'])
        self.assertEqual(fake.refuse[REFUSED], 96)
        done = dict(events)['servustv_sync_completed']
        self.assertEqual((done['known_skipped'], done['remembered'], done['refused']), (1, 1, 0))
        self.assertEqual(done['unavailable'], {'403': 1})
        self.assertEqual(done['error_texts'], [])
        # after REFUSED_RECHECK: one try without pauses; it still refuses -> remembered again
        self.run_sync(fake, SNOW + servustv.REFUSED_RECHECK + 10, waits=(30, 30))
        self.assertEqual(fake.refuse[REFUSED], 95)

    def test_page_that_answers_again_is_forgotten(self):
        fake = FakeServus()
        fake.refuse = {REFUSED: 3}
        self.run_sync(fake, SNOW)
        self.run_sync(fake, SNOW + servustv.REFUSED_RECHECK + 10)          # answers now
        db = servustv._connect(self.root)
        try:
            self.assertEqual(json.loads(servustv._get(db, 'refused_pages')), {})
        finally:
            db.close()
        self.assertGreater(self.requests_for(fake, 'AA-25RX849FN1W11'), 0)

    def test_burst_403_still_gets_retries(self):
        fake = FakeServus()
        fake.refuse = {REFUSED: 1}                                            # one 403, then fine
        events = []
        with mock.patch.object(servustv, '_notify', lambda e, **d: events.append((e, d))):
            self.run_sync(fake, SNOW)
        done = dict(events)['servustv_sync_completed']
        self.assertEqual((done['recovered'], done['remembered']), (1, 0))


class PlayerOnlyAtProvider(unittest.TestCase):
    def test_provider_player_only_is_never_playable_here(self):
        self.assertEqual(portal_title.PROVIDER_PLAYER_ONLY, {'joyn', 'rtlplus', 'crunchyroll', 'filmfriend', 'dailyme'})   # + 0.6.52, + 0.6.62
        for source in ('joyn', 'rtlplus', 'crunchyroll'):
            self.assertFalse(portal_title._episode(source, {'id': 'x', 'title': 'Folge'})['playable'])
        self.assertTrue(portal_title._episode('servustv', {'id': 'x', 'title': 'Folge'})['playable'])

    def test_web_scripts_tell_missing_player_from_provider_player(self):
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("report('player_missing:", app)
        self.assertIn('window.atlasProviderOnly=', app)
        for name in ('portal_title.js', 'portal_panel.js', 'unified_catalog.js'):
            code = (ROOT / 'web' / name).read_text(encoding='utf-8')
            self.assertIn('atlasProviderOnly', code, name)
        for name in ('live_tv.js', 'watchlist.js', 'watch_mode.js', 'abo_shelf.js', 'netzkino_detail.js', 'unified_catalog.js',
                     'portal_title.js', 'portal_panel.js'):
            code = (ROOT / 'web' / name).read_text(encoding='utf-8')
            self.assertNotIn('atlasPlayerMissing?.()', code, name)            # every caller names itself


class AboBudget(Fixture):
    def finish_all(self, abo, size):
        for j in self.jobs():
            if j['_state'] != 'queued':
                continue
            path = self.downloads / ('%s.mp4' % j['source']['_video_id'])
            path.write_bytes(b'x' * size)
            self.set_job(j['id'], 'done', path=str(path), offline_until=NOW + 86400)
        return {j['source']['_video_id']: j for j in self.jobs()}

    def test_default_budget_and_bounds(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal'}, now=NOW)
        row = ab.overview(self.root)['abos'][0]
        self.assertEqual(row['budget_gb'], ab.BUDGET_DEFAULT_GB)
        ab.change(self.root, abo, {'budget_gb': '2,5'})
        self.assertEqual(ab.overview(self.root)['abos'][0]['budget_gb'], 2.5)
        ab.change(self.root, abo, {'budget_gb': 0})
        self.assertEqual(ab.overview(self.root)['abos'][0]['budget_gb'], 0)
        for bad in ('-1', 'viel', 'nan'):
            with self.assertRaises(ValueError):
                ab.change(self.root, abo, {'budget_gb': bad})

    def test_existing_table_gets_budget_column(self):
        db = yt._connect(self.root)
        try:
            db.executescript(ab.SCHEMA.replace(" budget_gb REAL NOT NULL DEFAULT 10,", ''))
            db.execute("INSERT INTO youtube_abos(ref,added) VALUES('@Alt',1)")
            db.commit()
            self.assertNotIn('budget_gb', {r[1] for r in db.execute('PRAGMA table_info(youtube_abos)')})
        finally:
            db.close()
        db = ab._connect(self.root)
        try:
            self.assertEqual(db.execute("SELECT budget_gb FROM youtube_abos WHERE ref='@Alt'").fetchone()[0], 10)
        finally:
            db.close()

    def test_budget_waits_and_watched_videos_make_room(self):
        # 1 GB budget; each video about 0.45 GB -> two fit, the third waits
        mock.patch.object(ab, 'estimate', lambda v, q='720': 450 * 1000 ** 2).start()
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 3, 'budget_gb': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        states = self.videos(abo)
        self.assertEqual(sorted(r['state'] for r in states.values() if r['state'] != 'old'), ['queued', 'queued', 'wanted'])
        jobs = self.finish_all(abo, 10)
        # files are small on disk now (10 bytes): the real size counts, the third one gets its turn
        ab.check(self.root, abo, now=NOW + 3600, request=self.api)
        self.assertEqual(sum(1 for r in self.videos(abo).values() if r['state'] in ('queued', 'done')), 3)
        self.assertTrue(jobs)

    def test_full_budget_removes_only_watched(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'budget_gb': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = {}
        big = 480 * 1000 ** 2
        for j in self.jobs():
            path = self.downloads / ('%s.mp4' % j['source']['_video_id'])
            with open(path, 'wb') as f:
                f.truncate(big)                                       # sparse file, no real disk use
            self.set_job(j['id'], 'done', path=str(path), offline_until=NOW + 86400)
            jobs[j['source']['_video_id']] = j
        KIDS[42] = video(42, 'Bluey Folge 42', 500, channel='Kinderkanal')
        KIDS[42]['snippet']['publishedAt'] = '2026-11-22T08:00:00Z'
        self.addCleanup(KIDS.pop, 42)
        self.api.order.insert(0, 42)
        ab.check(self.root, abo, now=NOW + 3600, request=self.api)
        self.assertEqual(self.videos(abo)[vid(42)]['state'], 'wanted')        # nothing watched: nothing deleted
        over = ab.overview(self.root, self._conn())
        self.assertTrue(over['abos'][0]['budget_full'])
        self.assertAlmostEqual(over['abos'][0]['used_gb'], 0.96, places=2)
        watch_state.progress(self.root, 'job:' + jobs[vid(37)]['id'], pos=400, duration=427, done=True)
        ab.check(self.root, abo, now=NOW + 7200, request=self.api)
        states = self.videos(abo)
        self.assertEqual(states[vid(42)]['state'], 'queued')
        self.assertEqual(states[vid(37)]['state'], 'expired')
        self.assertEqual(states[vid(38)]['state'], 'done')

    def _conn(self):
        c = sqlite3.connect(self.catalog)
        self.addCleanup(c.close)
        return c

    def test_reserve_blocks_new_and_queued_abo_downloads(self):
        self.assertEqual(ab.reserve_gb(self.root), ab.RESERVE_DEFAULT_GB)
        ab.set_reserve(self.root, 10)
        self.assertEqual(ab.reserve_gb(self.root), 10)
        with self.assertRaises(ValueError):
            ab.set_reserve(self.root, 7)
        mock.patch.object(ab, 'free_bytes', lambda path: 3 * ab.GB).start()
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 3}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        self.assertEqual(self.jobs(), [])
        self.assertTrue(ab.overview(self.root)['storage']['low'])
        job = {'youtube_abo': abo, 'root': str(self.downloads), 'quality': '720', 'source': {'duration': 600}}
        self.assertTrue(ab.pace(self.root, job, now=NOW))
        self.assertEqual(job['not_before'], NOW + ab.RESERVE_RECHECK)
        self.assertIn('Weniger als 10 GB frei', job['note'])
        self.assertFalse(ab.pace(self.root, dict(job), now=NOW, force=True))   # "Jetzt versuchen" still starts

    def test_free_bytes_of_missing_folder_uses_parent(self):
        self.assertIsNotNone(ab.free_bytes(self.downloads / 'gibt' / 'es' / 'nicht'))
        self.assertIsNone(ab.free_bytes(''))

    def test_reserve_route(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("action=='reserve':youtube_abos.set_reserve", server)
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn("action: 'reserve'", js)
        self.assertIn('budget_gb', js)


if __name__ == '__main__':
    unittest.main()
