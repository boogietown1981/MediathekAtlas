"""0.6.0 (Phase B): shared platform frame (provider_base) and one planner instead of two threads per
platform, with the profile "Schwache Hardware"."""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import planner  # noqa: E402
import provider_base  # noqa: E402
import task_control  # noqa: E402

PLATFORMS = ('netzkino', 'pluto', 'justwatch', 'rakuten', 'joyn', 'toggo', 'crunchyroll', 'plex', 'servustv',
             'rtlplus', 'youtube')


class ProfileTests(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(planner.detect(cores=2, memory=16 * planner.GB), 'low')
        self.assertEqual(planner.detect(cores=8, memory=1 * planner.GB), 'low')
        self.assertEqual(planner.detect(cores=4, memory=8 * planner.GB), 'normal')
        self.assertEqual(planner.detect(cores=4, memory=None), 'normal')     # memory unknown: by cores

    def test_choice_setting_and_environment(self):
        self.assertEqual(planner.profile({'background_profile': 'low'}, env={})['max_syncs'], 1)
        self.assertEqual(planner.profile({'background_profile': 'normal'}, env={})['enrich_workers'], 2)
        self.assertEqual(planner.profile({'background_profile': 'normal'}, env={'MEDIATHEKATLAS_PROFILE': 'low'})['key'], 'low')
        self.assertEqual(planner.profile({'background_profile': 'nonsense'}, env={})['choice'], 'auto')
        with mock.patch.object(planner, 'detect', lambda: 'low'):
            self.assertEqual(planner.profile({}, env={})['label'], 'Schwache Hardware')


def fake_platform(name, due=True, calls=None):
    calls = calls if calls is not None else []
    module = types.SimpleNamespace(_ACTIVE=False)

    def start(root):
        calls.append(('start', name))
        module._ACTIVE = True
        return True
    module.should_sync = lambda root: due
    module.start_sync = start
    module.tick = lambda root: calls.append(('tick', name))
    return module


class CatalogTests(unittest.TestCase):
    def plan(self, modules, choice='low'):
        return planner.Planner('/r', lambda: {'background_profile': choice}, threading.BoundedSemaphore(2), threading.Event(),
                               [planner.CatalogJob(k, m) for k, m in modules], [], events=lambda *a, **k: None,
                               errors=lambda *a: None)

    def test_limit_and_rotation(self):
        calls = []
        mods = [(k, fake_platform(k, calls=calls)) for k in ('a', 'b', 'c')]
        plan = self.plan(mods, 'low')
        with mock.patch.dict(os.environ, {'MEDIATHEKATLAS_PROFILE': ''}):
            self.assertEqual(plan.catalog_round(), ['a'])       # one at a time on weak hardware
            self.assertEqual(plan.catalog_round(), [])          # 'a' still runs
            mods[0][1]._ACTIVE = False
            self.assertEqual(plan.catalog_round(), ['c'])       # next round starts with the next platform
        self.assertIn(('tick', 'b'), calls)                     # not started: its small regular work runs

    def test_normal_profile_runs_two(self):
        mods = [(k, fake_platform(k)) for k in ('a', 'b', 'c')]
        with mock.patch.dict(os.environ, {'MEDIATHEKATLAS_PROFILE': ''}):
            self.assertEqual(self.plan(mods, 'normal').catalog_round(), ['a', 'b'])

    def test_paused_and_broken_platforms(self):
        calls = []
        broken = fake_platform('x', calls=calls)
        broken.should_sync = lambda root: (_ for _ in ()).throw(OSError('database locked'))
        mods = [('pluto', fake_platform('pluto', calls=calls)), ('x', broken), ('joyn', fake_platform('joyn', calls=calls))]
        errors = []
        plan = self.plan(mods, 'normal')
        plan.errors = lambda name, exc: errors.append(name)
        with mock.patch.object(task_control, 'paused', lambda task: task == 'catalog:pluto'), \
                mock.patch.dict(os.environ, {'MEDIATHEKATLAS_PROFILE': ''}):
            self.assertEqual(plan.catalog_round(), ['joyn'])
        self.assertEqual(errors, ['planner_catalog_failed'])
        self.assertNotIn(('start', 'pluto'), calls)


class EnrichTests(unittest.TestCase):
    def job(self, name, items, log, fail=()):
        pending_calls = []

        def pending(root, limit=10):
            pending_calls.append(limit)
            return [i for i in items if i not in log]

        def enrich(root, item_id, settings):
            if item_id in fail:
                raise OSError('provider down')
            log.append(item_id)
        job = planner.EnrichJob(name, pending, enrich)
        job.pending_calls = pending_calls
        return job

    def test_batch_failure_idle_and_gap(self):
        log, events, errors = [], [], []
        job = self.job('pluto', ['a', 'b', 'c'], log, fail=('b',))
        plan = planner.Planner('/r', dict, threading.BoundedSemaphore(1), threading.Event(), [], [job], gap=6.0, idle=100.0,
                               events=lambda n, **k: events.append((n, k)), errors=lambda n, e: errors.append(n))
        self.assertEqual(plan.enrich_step(job, {}, 0), 6.0 * task_control.factor('enrich:pluto'))
        plan.enrich_step(job, {}, 1)
        plan.enrich_step(job, {}, 2)
        self.assertEqual(log, ['a', 'c'])
        self.assertEqual(job.pending_calls, [20])          # one list of up to 20 titles, as before
        self.assertEqual(errors, ['pluto_auto_enrich_failed'])
        self.assertEqual(plan.enrich_step(job, {}, 3), 30.0)   # 'b' failed: nothing left for now
        self.assertEqual(events, [('pluto_auto_enrich_batch', {'checked': 2})])
        plan.enrich_step(job, {}, 200)                     # after the idle time 'b' gets another chance
        self.assertEqual(job.failed, set())

    def test_paused_task(self):
        log = []
        job = self.job('plex', ['a'], log)
        plan = planner.Planner('/r', dict, threading.BoundedSemaphore(1), threading.Event(), [], [job],
                               events=lambda *a, **k: None, errors=lambda *a: None)
        with mock.patch.object(task_control, 'paused', lambda task: task == 'enrich:plex'):
            self.assertEqual(plan.enrich_step(job, {}, 0), 5.0)
        self.assertEqual(log, [])

    def test_workers_share_platforms_without_overlap(self):
        log, active, overlap = [], {}, []
        lock = threading.Lock()

        def make(name, items):
            def enrich(root, item_id, settings):
                with lock:
                    if active.get(name):
                        overlap.append(name)
                    active[name] = True
                time.sleep(0.01)
                log.append((name, item_id))
                with lock:
                    active[name] = False
            return planner.EnrichJob(name, lambda root, limit=10: [i for i in items if (name, i) not in log], enrich)
        jobs = [make('a', ['1', '2', '3']), make('b', ['1', '2']), make('c', [])]
        stop = threading.Event()
        plan = planner.Planner('/r', lambda: {'background_profile': 'normal'}, threading.BoundedSemaphore(2), stop, [], jobs,
                               gap=0.001, tick=0.05, first_tick=5, events=lambda *a, **k: None, errors=lambda *a: None)
        with mock.patch.dict(os.environ, {'MEDIATHEKATLAS_PROFILE': ''}):
            workers = [threading.Thread(target=plan.enrich_loop, args=(n,)) for n in (1, 2)]
            for w in workers:
                w.start()
            deadline = time.time() + 5
            while len(log) < 5 and time.time() < deadline:
                time.sleep(0.01)
            stop.set()
            for w in workers:
                w.join(2)
        self.assertEqual(sorted(log), [('a', '1'), ('a', '2'), ('a', '3'), ('b', '1'), ('b', '2')])
        self.assertEqual(overlap, [])

    def test_switched_off_metadata_checks_nothing(self):
        log = []
        stop = threading.Event()
        plan = planner.Planner('/r', lambda: {'auto_metadata': False}, threading.BoundedSemaphore(1), stop, [],
                               [self.job('a', ['1'], log)], tick=0.02, events=lambda *a, **k: None, errors=lambda *a: None)
        t = threading.Thread(target=plan.enrich_loop, args=(1,))
        t.start()
        time.sleep(0.1)
        stop.set()
        t.join(2)
        self.assertEqual(log, [])

    def test_second_worker_rests_on_weak_hardware(self):
        log = []
        stop = threading.Event()
        plan = planner.Planner('/r', lambda: {'background_profile': 'low'}, threading.BoundedSemaphore(1), stop, [],
                               [self.job('a', ['1'], log)], tick=0.02, events=lambda *a, **k: None, errors=lambda *a: None)
        with mock.patch.dict(os.environ, {'MEDIATHEKATLAS_PROFILE': ''}):
            t = threading.Thread(target=plan.enrich_loop, args=(2,))
            t.start()
            time.sleep(0.1)
            stop.set()
            t.join(2)
        self.assertEqual(log, [])


class ProviderBaseTests(unittest.TestCase):
    def test_connect_uses_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = provider_base.connect(tmp, 'x.sqlite3', private=True)
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 5000)
            self.assertIs(db.row_factory, sqlite3.Row)
            db.close()
            if os.name != 'nt':
                self.assertEqual(os.stat(Path(tmp) / 'x.sqlite3').st_mode & 0o777, 0o600)

    def test_wal_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'MEDIATHEKATLAS_NO_WAL': '1'}):
            db = provider_base.connect(tmp, 'y.sqlite3')
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            db.close()

    def test_due_rule(self):
        module = types.SimpleNamespace(_connect=None)
        with mock.patch('portal_reference.retry_after_update', lambda root, m, c: False):
            self.assertTrue(provider_base.catalog_due('/r', module, {'last_success': 0, 'last_attempt': 0}))
            self.assertFalse(provider_base.catalog_due('/r', module, {'running': True, 'last_success': 0, 'last_attempt': 0}))
            self.assertTrue(provider_base.catalog_due('/r', module, {'last_attempt': 5, 'auto': True, 'next_attempt': 10}, now=11))
            self.assertFalse(provider_base.catalog_due('/r', module, {'last_attempt': 5, 'auto': False, 'next_attempt': 10}, now=11))

    def test_every_platform_uses_the_frame(self):
        import importlib
        import platform_registry
        self.assertEqual(sorted(p.key for p in platform_registry.PLATFORMS), sorted(PLATFORMS))
        for name in PLATFORMS:
            module = importlib.import_module(name)
            source = (ROOT / (name + '.py')).read_text(encoding='utf-8')
            self.assertIn('provider_base.connect(root, ', source, name)
            self.assertTrue(callable(module.should_sync), name)
            with tempfile.TemporaryDirectory() as tmp:
                db = module._connect(tmp)
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal', name)
                db.close()
        import samsung_tvplus
        self.assertTrue(callable(samsung_tvplus.should_sync))

    def test_server_starts_one_planner(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn('target=samsung_tvplus.loop', server)
        self.assertNotIn('target=archive_recognition.loop', server)
        self.assertIn("planner.CatalogJob('samsung',samsung_tvplus)", server)
        self.assertIn("planner.EnrichJob('archive',archive_recognition.background_pending(db),archive_recognition.enrich)", server)


if __name__ == '__main__':
    unittest.main()
