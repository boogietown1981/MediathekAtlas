"""One planner for all background work of the platforms (0.6.0, Phase B of the review of 14.11.2026).

Until 0.5.108 every platform started two threads of its own: a loop that asked once a minute whether
its catalogue run was due, and a reference check (IMDb/TVDB/TMDB/OMDb/Wikidata, one title every six
seconds). Twelve platforms plus Archive.org and Samsung TV Plus made 26 mostly sleeping threads, and
the catalogue runs could all start at the same moment (first start, after an update). On a NAS with
512 MB to 2 GB that is the next limit (review: 52 threads, 65 MB when idle).

Now:

- **one catalogue thread** asks every platform once a minute (``should_sync``) and starts at most
  ``max_syncs`` catalogue runs at the same time; the others follow a minute later. A run the user
  starts by hand is never held back.
- **``enrich_workers`` reference-check threads** take the platforms in turn. Each platform still checks
  at most one title every ``gap`` seconds (times the task's priority factor), and every check still
  takes one of the shared provider slots, exactly as before. Pausing a platform's task, the priority
  and the switch "Automatischer Abgleich" behave as before.

Profiles (Verwaltung → System, or ``MEDIATHEKATLAS_PROFILE``):

- ``normal``: 2 catalogue runs, 2 reference-check threads.
- ``low`` ("Schwache Hardware"): 1 and 1.
- ``auto`` (default): ``low`` on systems with at most 2 cores or less than 2 GB of memory.

Standard library only.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

PROFILES = {
    'normal': {'max_syncs': 2, 'enrich_workers': 2, 'label': 'Normal'},
    'low': {'max_syncs': 1, 'enrich_workers': 1, 'label': 'Schwache Hardware'},
}
CHOICES = ('auto', 'normal', 'low')
GB = 1024 ** 3


def detect(cores=None, memory=None):
    """'low' for small machines (at most 2 cores or under 2 GB), else 'normal'."""
    cores = os.cpu_count() if cores is None else cores
    if memory is None:
        try:
            import system_monitor
            memory = system_monitor.memory()[0]
        except Exception:
            memory = None
    if (cores or 1) <= 2 or (memory and memory < 2 * GB):
        return 'low'
    return 'normal'


def profile(settings=None, env=None):
    """The active profile as a dict: key, choice, label, max_syncs, enrich_workers."""
    env = os.environ if env is None else env
    choice = str(env.get('MEDIATHEKATLAS_PROFILE') or (settings or {}).get('background_profile') or 'auto')
    if choice not in CHOICES:
        choice = 'auto'
    key = detect() if choice == 'auto' else choice
    return dict(PROFILES[key], key=key, choice=choice)


@dataclass
class CatalogJob:
    key: str
    module: object               # should_sync(root), start_sync(root), _ACTIVE; optional tick(root)


@dataclass
class EnrichJob:
    name: str                    # task 'enrich:<name>' in task_control
    pending: Callable            # (root, limit=..) -> [item ids]
    enrich: Callable             # (root, item_id, settings) -> result
    next_at: float = 0.0
    busy: bool = False
    failed: set = field(default_factory=set)
    idle_since: float = 0.0
    done: int = 0
    queue: list = field(default_factory=list)   # up to 20 titles, fetched in one go as before


class Planner:
    def __init__(self, root, settings, slots, stop, catalog=(), enrichment=(), *, gap=6.0, idle=1800.0,
                 tick=60.0, first_tick=20.0, clock=time.time, events=None, errors=None):
        self.root, self.settings, self.slots, self.stop = root, settings, slots, stop
        self.catalog = list(catalog)
        self.enrichment = list(enrichment)
        self.gap, self.idle, self.tick, self.first_tick, self.clock = gap, idle, tick, first_tick, clock
        self.lock = threading.Lock()
        self.turn = 0
        self.started = []
        if events is None or errors is None:
            import diagnostics
            events = events or diagnostics.event
            errors = errors or diagnostics.error
        self.events, self.errors = events, errors

    # ------------------------------------------------------------------ catalogue runs

    def profile(self):
        try:
            return profile(self.settings())
        except Exception:
            return profile({})

    def catalog_round(self):
        """One look at every platform; returns the keys whose catalogue run was started."""
        import task_control
        limit = self.profile()['max_syncs']
        busy = sum(1 for job in self.catalog if getattr(job.module, '_ACTIVE', False))
        started = []
        count = len(self.catalog)
        for i in range(count):
            # Start with a different platform each round, so a limit of one does not favour the first.
            job = self.catalog[(self.turn + i) % count]
            try:
                if task_control.paused('catalog:' + job.key):
                    continue
                if busy < limit and job.module.should_sync(self.root):
                    if job.module.start_sync(self.root):
                        busy += 1
                        started.append(job.key)
                    continue
                tick = getattr(job.module, 'tick', None)
                if tick:
                    tick(self.root)
            except Exception as exc:      # one broken platform must not stop the others
                self.errors('planner_catalog_failed', exc)
        self.turn = (self.turn + 1) % max(1, count)
        return started

    def catalog_loop(self):
        if self.stop.wait(self.first_tick):
            return
        while True:
            self.catalog_round()
            if self.stop.wait(self.tick):
                return

    # ------------------------------------------------------------------ reference checks

    def _claim(self, now):
        """The next platform allowed to check a title now, or the time to wait for one."""
        with self.lock:
            soonest = None
            count = len(self.enrichment)
            for i in range(count):
                job = self.enrichment[(self.turn + i) % count]
                if job.busy:
                    continue
                if job.next_at <= now:
                    job.busy = True
                    return job, 0.0
                soonest = job.next_at if soonest is None else min(soonest, job.next_at)
            return None, (max(0.5, soonest - now) if soonest is not None else self.tick)

    def enrich_step(self, job, current, now):
        """Check one title of ``job``; returns the seconds until this platform may check again."""
        import task_control
        task = 'enrich:' + job.name
        if task_control.paused(task):
            task_control.note(task, 'Pausiert')
            return 5.0
        if not job.queue:
            job.queue = [i for i in job.pending(self.root, limit=20) if i not in job.failed]
        if not job.queue:
            task_control.note(task, 'Alle Titel geprüft')
            if not job.idle_since:
                job.idle_since = now
            elif now - job.idle_since >= self.idle:
                job.failed.clear()        # after the idle time, failed titles get another chance
                job.idle_since = now
            if job.done:
                self.events(job.name + '_auto_enrich_batch', checked=job.done)
                job.done = 0
            return 30.0
        job.idle_since = 0.0
        task_control.note(task, 'Prüft Titel')
        item = job.queue.pop(0)
        try:
            with self.slots:
                job.enrich(self.root, item, current)
            job.done += 1
            if job.done >= 20:
                self.events(job.name + '_auto_enrich_batch', checked=job.done)
                job.done = 0
        except Exception as exc:        # one broken title must not stop the worker
            job.failed.add(item)
            self.errors(job.name + '_auto_enrich_failed', exc)
        return self.gap * task_control.factor(task)

    def enrich_loop(self, number):
        import task_control
        while not self.stop.is_set():
            if number > self.profile()['enrich_workers']:
                # Profile "Schwache Hardware": this worker rests; checked again in a minute.
                if self.stop.wait(self.tick):
                    return
                continue
            try:
                current = self.settings()
            except Exception as exc:
                self.errors('planner_settings_failed', exc)
                current = {}
            if not current.get('auto_metadata', True):
                for job in self.enrichment:
                    task_control.note('enrich:' + job.name, 'Automatischer Abgleich ist in den Einstellungen ausgeschaltet')
                if self.stop.wait(300 if self.tick >= 60 else self.tick):
                    return
                continue
            job, wait = self._claim(self.clock())
            if job is None:
                if self.stop.wait(min(wait, self.tick)):
                    return
                continue
            pause = 300.0
            try:
                pause = self.enrich_step(job, current, self.clock())
            except Exception as exc:
                self.errors(job.name + '_auto_enrich_loop', exc)
                pause = 300.0
            finally:
                with self.lock:
                    job.next_at = self.clock() + pause
                    job.busy = False
                    self.turn += 1

    # ------------------------------------------------------------------ start

    def start(self):
        """The catalogue thread and two reference-check threads (the second rests in profile 'low')."""
        threads = [threading.Thread(target=self.catalog_loop, daemon=True, name='planner_catalog')]
        for n in (1, 2):
            threads.append(threading.Thread(target=self.enrich_loop, args=(n,), daemon=True, name='planner_reference_%d' % n))
        for t in threads:
            t.start()
        self.started = threads
        return threads

    def status(self):
        """For Verwaltung → System."""
        p = self.profile()
        return {'profile': p['key'], 'choice': p['choice'], 'label': p['label'], 'max_syncs': p['max_syncs'],
                'enrich_workers': p['enrich_workers'],
                'catalog_running': sorted(job.key for job in self.catalog if getattr(job.module, '_ACTIVE', False)),
                'platforms': len(self.catalog), 'reference_checks': len(self.enrichment)}
