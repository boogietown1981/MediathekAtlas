"""Speicherübersicht mit Aufräum-Vorschlag (0.5.81), nach den Regeln aus HomeTube.

Source: hometube/policy.py ("Pure retention decisions. This pilot NEVER deletes files."). The
rules were written for an archive with proven second copies; MediathekAtlas has no such proof
yet (planned with the signed Verbund receipts), so the adaptation is deliberately cautious:

* MediathekAtlas never deletes a download on its own because of this module. It only lists
  candidates; a file goes when the user clicks "Löschen" for exactly that file and confirms.
  (The 30-day period of the platform copies is a different rule and stays as it is.)
* Never a candidate: titles on the Merkliste, pinned titles, titles watched within the
  protection period (90 days by default) and downloads younger than that period which were
  not watched to the end.
* Order of the candidates: watched to the end first, then the longest untouched.
* Only as many candidates as are needed to get back under the budget; without a budget none.

``can_free`` and ``cleanup_plan`` are pure functions (no file system, no clock of their own).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

CONFIG = 'storage.json'
DEFAULTS = {'budget_gb': 0.0, 'protect_days': 90}
MAX_BUDGET_GB = 1_000_000
MAX_ROWS = 400
GIB = 1024 ** 3
ORIGIN_LABEL = {'': 'ARD, ZDF & Co.', 'netzkino': 'Netzkino', 'pluto': 'Pluto TV', 'justwatch': 'JustWatch TV',
                'rakuten': 'Rakuten TV', 'youtube': 'YouTube', 'joyn': 'Joyn', 'internet_archive': 'Archive.org'}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class StoredFile:
    job_id: str
    size_bytes: int
    stored_at: float = 0.0            # when the download finished (file time)
    favorite: bool = False
    pinned: bool = False
    watched_done: bool = False
    last_watched: float = 0.0         # 0 = never


def protection(f: StoredFile, now: float, days: int = 90) -> str:
    """Why a file is not suggested: 'pinned', 'favorite', 'watched', 'new' or '' (may be suggested)."""
    span = max(0, int(days)) * 86400
    if f.pinned:
        return 'pinned'
    if f.favorite:
        return 'favorite'
    if f.last_watched and now - f.last_watched < span:
        return 'watched'
    if not f.watched_done and f.stored_at and now - f.stored_at < span:
        return 'new'
    return ''


def can_free(f: StoredFile, now: float, days: int = 90) -> bool:
    return not protection(f, now, days)


def cleanup_plan(files: list[StoredFile], budget: int, now: float, days: int = 90) -> dict:
    """Recommendations only, never a deletion. ``budget`` in bytes; 0 means no budget."""
    if budget < 0:
        raise ValueError('budget must be non-negative')
    total = sum(f.size_bytes for f in files)
    if not budget or total <= budget:
        return {'used_bytes': total, 'over_budget_bytes': 0, 'candidates': [], 'blocked': False}
    eligible = [f for f in files if can_free(f, now, days)]
    # watched to the end first, then the longest untouched; the id keeps the order stable
    eligible.sort(key=lambda f: (not f.watched_done, max(f.last_watched, f.stored_at), f.job_id))
    candidates, remaining = [], total
    for f in eligible:
        if remaining <= budget:
            break
        candidates.append(f.job_id)
        remaining -= f.size_bytes
    return {'used_bytes': total, 'over_budget_bytes': total - budget, 'candidates': candidates,
            'blocked': remaining > budget}


def load(root) -> dict:
    try:
        stored = json.loads((Path(root) / CONFIG).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stored = {}
    return _clean({**DEFAULTS, **(stored if isinstance(stored, dict) else {})})


def _clean(values) -> dict:
    try:
        budget = float(values.get('budget_gb') or 0)
    except (TypeError, ValueError):
        raise ValueError('Das Platzbudget muss eine Zahl in GB sein') from None
    try:
        days = int(values.get('protect_days'))
    except (TypeError, ValueError):
        raise ValueError('Die Schutzfrist muss eine ganze Zahl von Tagen sein') from None
    if not 0 <= budget <= MAX_BUDGET_GB:        # NaN fails as well
        raise ValueError('Das Platzbudget muss zwischen 0 und %d GB liegen' % MAX_BUDGET_GB)
    if not 7 <= days <= 3650:
        raise ValueError('Die Schutzfrist muss zwischen 7 und 3650 Tagen liegen')
    return {'budget_gb': round(budget, 2), 'protect_days': days}


def save(root, change) -> dict:
    if not isinstance(change, dict):
        raise ValueError('Ungültige Einstellungen')
    with _LOCK:
        values = _clean({**load(root), **{k: change[k] for k in DEFAULTS if k in change}})
        path = Path(root) / CONFIG
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(values), encoding='utf-8')
        temp.replace(path)
    return values


def watch_keys(job, work_id=None) -> list[str]:
    """The player keys under which this download may have been watched or marked."""
    keys = ['job:' + str(job.get('id') or '')]
    origin = job.get('origin') or ''
    item = job.get(origin + '_id') if origin else None
    if origin and item:
        keys.append('%s:%s' % (origin, item))
    if work_id:
        keys.append(str(work_id))
    return keys


def _file(job):
    path = Path(job.get('path') or job.get('target') or '')
    try:
        info = path.stat()
    except OSError:
        return None
    return (path, info.st_size, info.st_mtime) if path.is_file() else None


def _disk(folder):
    probe = Path(folder).expanduser()
    for candidate in (probe, *probe.parents):
        try:
            usage = shutil.disk_usage(candidate)
            return {'total_bytes': usage.total, 'free_bytes': usage.free}
        except OSError:
            continue
    return {'total_bytes': 0, 'free_bytes': 0}


def overview(c, root, download_dir, watch=None, now=None) -> dict:
    """Used space of all finished downloads, per source, with the cleanup suggestion."""
    now = time.time() if now is None else float(now)
    config = load(root)
    watch = watch or {}
    rows, files, missing = [], [], 0
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='done'").fetchall():
        job = json.loads(payload)
        found = _file(job)
        if not found:
            missing += 1
            continue
        path, size, mtime = found
        work = None
        if not job.get('origin'):
            hit = c.execute('SELECT work_id FROM offers WHERE id=?', ((job.get('source') or {}).get('_id'),)).fetchone()
            work = hit[0] if hit else None
        states = [watch[k] for k in watch_keys(job, work) if k in watch]
        f = StoredFile(job_id=str(job['id']), size_bytes=size, stored_at=mtime,
                       favorite=any(s.get('favorite') for s in states), pinned=any(s.get('pinned') for s in states),
                       watched_done=any(s.get('done') for s in states),
                       last_watched=max([float(s.get('watched_at') or 0) for s in states] or [0.0]))
        files.append(f)
        meta = job.get('metadata') or {}
        title = meta.get('title') or path.stem
        if meta.get('kind') == 'series' and isinstance(meta.get('season'), int) and isinstance(meta.get('episode'), int):
            title += ' · S%02dE%02d' % (meta['season'], meta['episode'])
        rows.append({'id': f.job_id, 'title': title, 'year': meta.get('year'), 'kind': meta.get('kind') or '',
                     'origin': job.get('origin') or '', 'source': ORIGIN_LABEL.get(job.get('origin') or '', job.get('origin') or ''),
                     'file': path.name, 'folder': str(path.parent), 'size_bytes': size, 'stored_at': mtime,
                     'last_watched': f.last_watched, 'watched_done': f.watched_done,
                     'favorite': f.favorite, 'pinned': f.pinned, 'watch_key': watch_keys(job, work)[-1],
                     'offline_until': job.get('offline_until') or None,
                     'protection': protection(f, now, config['protect_days'])})
    plan = cleanup_plan(files, int(config['budget_gb'] * GIB), now, config['protect_days'])
    order = {job_id: i for i, job_id in enumerate(plan['candidates'])}
    by_source = {}
    for row in rows:
        row['suggested'] = row['id'] in order
        group = by_source.setdefault(row['source'], {'source': row['source'], 'files': 0, 'bytes': 0})
        group['files'] += 1
        group['bytes'] += row['size_bytes']
    # suggestions first (in the order of the plan), then the largest files
    rows.sort(key=lambda r: (0, order[r['id']]) if r['suggested'] else (1, -r['size_bytes']))
    return {'settings': config, 'used_bytes': plan['used_bytes'], 'budget_bytes': int(config['budget_gb'] * GIB),
            'over_budget_bytes': plan['over_budget_bytes'], 'blocked': plan['blocked'],
            'suggested_bytes': sum(r['size_bytes'] for r in rows if r['suggested']),
            'suggested': len(order), 'files': len(rows), 'missing': missing, 'shown': min(len(rows), MAX_ROWS),
            'sources': sorted(by_source.values(), key=lambda g: -g['bytes']), 'items': rows[:MAX_ROWS],
            'disk': _disk(download_dir), 'download_dir': str(download_dir),
            'rules': {'protect_days': config['protect_days'], 'automatic_deletion': False}}


def delete(c, job_id, watch=None, remove_files=None) -> dict:
    """The user deletes one finished download. Pinned titles are refused; nothing else is touched."""
    row = c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'", (str(job_id),)).fetchone()
    if not row:
        raise ValueError('Nur fertige Downloads können hier gelöscht werden')
    job = json.loads(row[0])
    work = None
    if not job.get('origin'):
        hit = c.execute('SELECT work_id FROM offers WHERE id=?', ((job.get('source') or {}).get('_id'),)).fetchone()
        work = hit[0] if hit else None
    if any((watch or {}).get(k, {}).get('pinned') for k in watch_keys(job, work)):
        raise ValueError('Dieser Titel ist angeheftet. Erst die Anheftung lösen, dann löschen.')
    found = _file(job)
    freed = found[1] if found else 0
    path = str(found[0]) if found else str(job.get('path') or job.get('target') or '')
    removed = remove_files(job) if remove_files else []
    if found and os.path.exists(path):
        raise ValueError('Die Datei liegt außerhalb des Download-Ordners dieses Auftrags und wurde nicht gelöscht.')
    job.update(state='removed', expired_at=time.time(), file_state='removed')
    c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(job), 'removed', job['id']))
    # The catalogue offers the title for download again.
    try:
        c.execute('DELETE FROM downloaded_items WHERE path=?', (path,))
    except sqlite3.OperationalError:   # table of the Mediathek catalogue; absent in isolated tests
        pass
    return {'ok': True, 'freed_bytes': freed, 'removed_files': len(removed)}
