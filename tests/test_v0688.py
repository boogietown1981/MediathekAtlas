"""0.6.88: Folgensuche nach neuem IMDb-Stand, Sendungsvorschläge als Folge, täglicher Plattform-Abgleich.

Diagnosen 22.11.2026 (Pro 0.6.87: 121.780 Einträge, 0 fällig; Air 0.6.85: 116.533 / 0): jede Folgensuche ohne
Treffer ruht 30 Tage, Geschwister ohne IMDb-Folgenliste 30–37 Tage. Neue Daten bringt nur das wöchentliche
IMDb-Archiv → was gegen ein älteres Archiv geprüft wurde, wird verteilt wieder fällig. 4.692 Werke ohne Art
warten auf einen Vorschlag, der die Sendung selbst ist (exakter Name) → Folge dieser Serie. Pluto, Joyn, Rakuten,
RTL+, TOGGO und JustWatch hatten den täglichen Abgleich nie an (Standard '0') → einmalig einschalten (Björn: „ja“).
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
import imdb_archive  # noqa: E402
import platform_registry  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402
from test_v0649_unknown_rest import offer, series, movie  # noqa: E402


def src(sendung='Arena'):
    return {'duration': 4200, 'timestamp': 1795100000, 'title': 'Streit um die Rente', 'topic': sendung}


class SuggestionRuleTests(unittest.TestCase):
    def test_exact_series_is_chosen_imdb_first(self):
        m = {'suggestions': [dict(series('Arena', ref='777', year=2019), provider='TVDB'), series('Arena', ref='tt9', year=2020)]}
        self.assertEqual(catalog.sendung_suggestion(m, src(), 'Arena')['reference_id'], 'tt9')

    def test_doubtful_cases_stay_open(self):
        cases = {
            'namesakes': [series('Arena', ref='tt1', year=2019), series('Arena', ref='tt2', year=2021)],
            'film': [series('Arena', ref='tt1', year=2019), movie('Streit um die Rente')],
            'fuzzy': [series('Arenas', similarity=.99, ref='tt1', year=2019)],
            'no_ref': [series('Arena', ref='', year=2019)],
            'none': [],
        }
        for name, suggestions in cases.items():
            with self.subTest(name):
                self.assertIsNone(catalog.sendung_suggestion({'suggestions': suggestions}, src(), 'Arena'))
        # a subject word or portal is no Sendung (0.6.84/0.6.87)
        self.assertIsNone(catalog.sendung_suggestion({'suggestions': [series('Doku', year=2020)]}, src('Doku'), 'Doku'))
        self.assertIsNone(catalog.sendung_suggestion({'suggestions': [series('planet schule', year=2020)]}, src('planet schule'), 'planet schule'))

    def test_weak_suggestions_beside_it_do_not_matter(self):
        m = {'suggestions': [series('Arena', ref='tt9', year=2020), series('Arena', ref='tt3', year=1960),
                             movie('Streit um die Rente', runtime_mismatch=True)]}
        self.assertEqual(catalog.sendung_suggestion(m, src(), 'Arena')['reference_id'], 'tt9')


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Streit um die Rente', 'Arena', n=1, duration=4200), offer('Wohnungsnot', 'Arena', n=2, duration=4200),
                offer('Zuwanderung', 'Arena', n=3, duration=4200), offer('Namensvetter', 'Club', n=4), offer('Zwei', 'Club', n=5),
                offer('Drei', 'Club', n=6)]
        setup = {'Streit um die Rente': [series('Arena', ref='tt9', year=2020, poster='p.jpg', genres=['Talk'])],
                 'Wohnungsnot': [series('Arena', ref='tt9', year=2020)],
                 'Namensvetter': [series('Club', ref='tt1', year=2019), series('Club', ref='tt2', year=2021)]}
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
                m = json.loads(meta)
                if m['title'] in setup:m['suggestions'] = setup[m['title']]
                c.execute("UPDATE works SET state='review', attempts=2, meta=? WHERE id=?", (json.dumps(m), wid))
        self.service = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def works(self):
        with self.db() as c:
            out = {}
            for r in c.execute('SELECT * FROM works'):
                m = json.loads(r['meta'])
                out[m.get('episode_title') or (m.get('unknown_before') or {}).get('title') or r['title']] = dict(r, meta=m)
            return out

    def test_works_with_the_sendung_as_suggestion_become_its_episodes(self):
        events = []
        archive = SimpleNamespace(updated=1, series_has_episodes=lambda m: True)      # 0.6.92: IMDb lists episodes
        with patch.object(diagnostics, 'event', lambda name, **kw: events.append((name, kw))), patch.object(imdb_archive, 'ACTIVE', archive):
            self.service.unknown_sweep(force=True)
        info = [kw for name, kw in events if name == 'unknown_classified'][0]
        w = self.works()
        for title in ('Streit um die Rente', 'Wohnungsnot'):
            r = w[title]
            self.assertEqual((r['kind'], r['state'], r['title']), ('series', 'identified', 'Arena'), title)
            self.assertEqual((r['meta']['provider'], r['meta']['reference_id'], r['meta']['episode_verified']), ('IMDb Offline', 'tt9', False))
            self.assertIn('laut IMDb Offline', r['meta']['reason'])
            self.assertEqual(r['meta']['unknown_before']['kind'], 'unknown')
            self.assertGreater(r['next_try'], time.time() + 20 * 86400)
        self.assertEqual(w['Streit um die Rente']['meta']['poster'], 'p.jpg')
        with self.db() as c:
            queued = {r[0] for r in c.execute('SELECT work_id FROM episode_queue')}
        self.assertEqual(queued, {w['Streit um die Rente']['id'], w['Wohnungsnot']['id']})
        self.assertEqual(w['Zuwanderung']['meta'].get('format_grouping'), 'contribution')   # no suggestion: as before
        self.assertEqual(w['Namensvetter']['kind'], 'unknown')                              # two series named Club
        self.assertEqual(info['classified']['sendung_suggestion'], 2)
        self.assertEqual(info['channels']['SRF']['sendung_suggestion'], 2)
        # „Erneut prüfen“ makes it an open work with its suggestions again
        restored = catalog.restore_unknown(w['Wohnungsnot']['meta'])
        self.assertEqual(restored[1], 'unknown');self.assertEqual(restored[2]['suggestions'][0]['reference_id'], 'tt9')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        self.now = time.time();self.archive = self.now - 86400       # new archive yesterday
        rows = [offer('Folge %d' % i, 'Magazin' if i < 4 else 'Andere', channel='NDR', n=i) for i in range(7)]
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            ids = [r[0] for r in c.execute('SELECT id FROM works ORDER BY id')]
            self.ids = ids
            for i, wid in enumerate(ids):
                show = 'show-a' if i < 4 else 'show-b'
                meta = {'title': 'Magazin' if i < 4 else 'Andere', 'kind': 'series', 'provider': 'IMDb Offline',
                        'reference_id': 'tt300' if i < 4 else 'tt400', 'episode_verified': False}
                c.execute("UPDATE works SET kind='series',show_key=?,state='identified',meta=? WHERE id=?", (show, json.dumps(meta), wid))
            c.execute('DELETE FROM episode_queue')
            old, new, later = self.archive - 5 * 86400, self.now - 3600, self.now + 25 * 86400
            plan = [  # (outcome, updated, next_try)
                ('unresolved', old, later), ('no_imdb_episodes', old, later), ('no_imdb_episodes', old, later),
                ('unresolved', new, later),                                       # checked against the new archive
                ('no_imdb_episodes', old, later), ('no_imdb_episodes', old, later),
                ('pending', 0, 0)]
            for wid, (outcome, updated, nxt) in zip(ids, plan):
                c.execute('INSERT INTO episode_queue(work_id,next_try,last_outcome,updated) VALUES(?,?,?,?)', (wid, nxt, outcome, updated))

    def test_only_what_an_older_archive_answered_comes_back_once_per_series(self):
        with self.db() as c:
            ids = catalog.archive_recheck_ids(c, self.archive, self.now)
        # show-a: its unresolved entry decides for the siblings; show-b: one representative; pending/new: not
        self.assertEqual(ids, [self.ids[0], self.ids[4]] if self.ids[0] < self.ids[4] else ids)
        self.assertEqual(set(ids), {self.ids[0], self.ids[4]})

    def test_service_spreads_and_remembers_the_archive(self):
        events = []
        fake = SimpleNamespace(updated=self.archive)
        with patch.object(imdb_archive, 'ACTIVE', fake), patch.object(diagnostics, 'event', lambda n, **kw: events.append((n, kw))):
            self.assertEqual(self.service().requeue_after_archive(force=True), 2)
            self.assertEqual(self.service().requeue_after_archive(force=True), 0)     # same archive: nothing again
        with self.db() as c:
            due = dict(c.execute('SELECT work_id,next_try FROM episode_queue').fetchall())
            state = catalog.get_state(c, 'episode_archive_recheck', {})
        for wid in (self.ids[0], self.ids[4]):
            self.assertLessEqual(due[wid], time.time() + catalog.ARCHIVE_RECHECK_SPREAD)
        self.assertGreater(due[self.ids[1]], time.time() + 20 * 86400)
        self.assertEqual((state['works'], state['archive']), (2, self.archive))
        self.assertIn(('episode_archive_recheck', {'works': 2, 'archive': int(self.archive), 'spread_hours': 72}), events)

    def service(self):
        return catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def test_siblings_come_back_when_imdb_lists_episodes(self):
        with self.db() as c:
            n = catalog.release_no_episode_siblings(c, 'show-a', 'IMDb Offline', 'tt300', self.now)
            due = dict(c.execute('SELECT work_id,next_try FROM episode_queue').fetchall())
        self.assertEqual(n, 2)
        self.assertLessEqual(max(due[self.ids[1]], due[self.ids[2]]), self.now + 6 * 3600)

    def test_siblings_answered_by_an_older_archive_take_the_new_answer(self):
        svc = self.service()
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=?,last_outcome=?,updated=? WHERE work_id=?',
                      (self.now + 3600, 'unresolved', self.archive - 86400, self.ids[3]))   # requeued by the recheck
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (self.ids[0],)).fetchone()[0])
            n = svc.defer_series_without_episodes(c, 'show-a', m, self.ids[0], {}, self.archive)
            row = c.execute('SELECT last_outcome,next_try FROM episode_queue WHERE work_id=?', (self.ids[3],)).fetchone()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(row[0], 'no_imdb_episodes');self.assertGreater(row[1], self.now + 29 * 86400)

    def test_overview_says_why_the_queue_rests(self):
        with self.db() as c:
            c.execute("UPDATE episode_queue SET next_try=? WHERE last_outcome='pending'", (self.now + 99,))
            info = catalog.episode_queue_overview(c, self.now)
        self.assertEqual(info['waiting'], {'unresolved': 2, 'no_imdb_episodes': 4, 'pending': 1})
        self.assertAlmostEqual(info['next_due'], self.now + 99, places=3)


class DailyPlatformTests(unittest.TestCase):
    def test_switched_on_once_and_a_later_off_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import pluto, joyn
            db = pluto._connect(root)
            with db:pluto._set(db, 'auto', 0)
            db.close()
            switched = platform_registry.enable_daily_once(root)
            self.assertEqual(sorted(switched), sorted(platform_registry.DAILY_V0688))
            self.assertTrue(pluto.state(root)['auto']);self.assertTrue(joyn.state(root)['auto'])
            pluto.set_auto(root, False)
            self.assertEqual(platform_registry.enable_daily_once(root), [])
            self.assertFalse(pluto.state(root)['auto'])
            import dmax                                       # 0.6.117: own switch (DAILY_V06117)
            self.assertFalse(dmax.state(root)['auto'])

    def test_v06117_filmfriend_dmax_redbull_dailyme_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import filmfriend, dmax, redbulltv, dailyme
            switched = platform_registry.enable_daily_once(root, platform_registry.DAILY_V06117, platform_registry.DAILY_MARK_V06117)
            self.assertEqual(sorted(switched), sorted(platform_registry.DAILY_V06117))
            for m in (filmfriend, dmax, redbulltv, dailyme):self.assertTrue(m.state(root)['auto'], m.__name__)
            filmfriend.set_auto(root, False)
            self.assertEqual(platform_registry.enable_daily_once(root, platform_registry.DAILY_V06117, platform_registry.DAILY_MARK_V06117), [])
            self.assertFalse(filmfriend.state(root)['auto'])   # a later „aus“ stays


if __name__ == '__main__':
    unittest.main()
