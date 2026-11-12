"""Download queue housekeeping shared by all sources (0.5.43).

Björn (12.11.2026): failed downloads stayed in the queue without a way to delete them, and the
same title appeared several times ("006 am Wolfgangsee" twice). Causes: "Erneut versuchen"
inserted a new job and kept the failed one, and a new order for the same file did not replace an
earlier failed one. Now:

* ``retry`` re-queues the same job (same id, one card);
* ``supersede`` removes earlier failed/cancelled/interrupted jobs for the same target file when a
  job for it is (re)queued, ``dedupe`` cleans up existing duplicates once at start;
* ``remove`` deletes a failed/cancelled/interrupted job from the list (no media files are touched;
  unfinished downloads only ever exist as ``.partial`` staging that is already gone).
"""
from __future__ import annotations

import json
import time

RETRYABLE = ('error', 'cancelled', 'interrupted', 'remote')
_FAILED = "('error','cancelled','interrupted','remote')"


def supersede(c, job):
    """Delete earlier unsuccessful jobs for the same target file. Returns the number removed."""
    target = job.get('target')
    if not target:
        return 0
    return c.execute("DELETE FROM jobs WHERE id<>? AND state IN " + _FAILED +
                     " AND json_extract(payload,'$.target')=?", (job['id'], target)).rowcount


def dedupe(c):
    """Keep one card per target: drop unsuccessful jobs that have a newer or a successful/active twin."""
    return c.execute("DELETE FROM jobs WHERE state IN " + _FAILED + " AND json_extract(payload,'$.target') IS NOT NULL "
                     "AND EXISTS (SELECT 1 FROM jobs o WHERE o.rowid<>jobs.rowid AND "
                     "json_extract(o.payload,'$.target')=json_extract(jobs.payload,'$.target') AND "
                     "(o.state NOT IN " + _FAILED + " OR o.rowid>jobs.rowid))").rowcount


def retry(c, job_id):
    row = c.execute("SELECT payload FROM jobs WHERE id=? AND state IN " + _FAILED, (job_id,)).fetchone()
    if not row:
        raise ValueError('Auftrag ist nicht wiederholbar')
    job = json.loads(row[0])
    job.update(state='queued', received=0, total=0, error='', note='', speed=0, eta=None)
    c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'queued', job_id))
    supersede(c, job)
    return job


def remove(c, job_id):
    n = c.execute("DELETE FROM jobs WHERE id=? AND state IN " + _FAILED, (job_id,)).rowcount
    if not n:
        raise ValueError('Nur fehlgeschlagene, abgebrochene oder unterbrochene Aufträge können entfernt werden')
    return n


def next_job(c, now=None):
    """Oldest queued job that may start now. Jobs with ``not_before`` in the future (0.5.48:
    JustWatch titles that the provider only releases at night) wait without blocking the others."""
    now = time.time() if now is None else float(now)
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='queued' ORDER BY rowid"):
        job = json.loads(payload)
        if float(job.get('not_before') or 0) <= now:
            return job
    return None
