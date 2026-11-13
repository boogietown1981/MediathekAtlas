"""Uploader erkannter Werke vormerken (0.5.88), aus Archive Media.

ArchiveMedia ``uploader_priority``: who uploaded one recognised film or series has often uploaded
more of them. For every work with a unique reference the public Archive.org account of its
uploads is noted once as a scan source. It is added *paused*: the user decides whether the
account is searched. An account the user removed is not added a second time.

Only the public ``@account`` Archive.org itself publishes is used. The uploader's e-mail address
and names guessed from other fields are never read, stored or queried.
"""
from __future__ import annotations

import json
import time

import archive_recognition
import portal_control
import portal_sources

MAX_NEW = 25                         # accounts noted per run; the rest follows in the next one
EVERY = 900.0                        # the background run looks at most every 15 minutes
SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_uploader_follow(
 handle TEXT PRIMARY KEY,
 account TEXT NOT NULL,
 item_id TEXT NOT NULL DEFAULT '',
 work_id TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL DEFAULT '',
 added REAL NOT NULL);
"""
_last = {'at': 0.0}


def ensure(c):
    c.executescript(SCHEMA)


def account(value):
    """The public account as '@name', or '' when the value is anything else (an e-mail, a name)."""
    return portal_sources.uploader_account(value)


def accounts_of(c, item_ids):
    """item id -> public account, from the stored search row or the stored file manifest."""
    out = {}
    ids = [str(i) for i in item_ids][:2000]
    for start in range(0, len(ids), 400):
        part = ids[start:start + 400]
        marks = ','.join('?' * len(part))
        for table, column in (('portal_archive_details', 'payload'), ('portal_items', 'metadata')):
            key = 'item_id' if table == 'portal_archive_details' else 'id'
            for item_id, payload in c.execute('SELECT %s,%s FROM %s WHERE %s IN (%s)' % (key, column, table, key, marks), part):
                try:
                    found = account(json.loads(payload).get('uploader_account'))
                except (ValueError, AttributeError):
                    found = ''
                if found:
                    out[item_id] = found
    return out


def recognised(root):
    """Works with a unique reference: [(group id, title, [upload ids])]."""
    works, members, reports, anime = archive_recognition._load(root)
    group = archive_recognition._groups(works, reports, anime)
    out = {}
    for wid, work in works.items():
        ref = archive_recognition.selected(reports.get(wid))
        if ref:
            out.setdefault(group.get(wid, wid), [ref.get('title') or work['title'], []])
    for item_id, member in members.items():
        gid = group.get(member['work_id'], member['work_id'])
        if gid in out:
            out[gid][1].append(item_id)
    return [(gid, title, sorted(ids)) for gid, (title, ids) in sorted(out.items())]


def follow(root, c, limit=MAX_NEW, now=None):
    """Note the accounts of recognised works as paused scan sources. Returns what happened."""
    ensure(c)
    now = time.time() if now is None else now
    known = {r[0] for r in c.execute('SELECT handle FROM archive_uploader_follow')}
    works = recognised(root)
    new, without, pending = [], 0, 0
    for gid, title, item_ids in works:
        found = accounts_of(c, item_ids)
        if not found:
            without += 1
            continue
        for item_id in item_ids:
            name = found.get(item_id)
            if not name or name.casefold() in known:
                continue
            if len(new) >= limit:
                pending += 1
                continue
            known.add(name.casefold())
            # A source the user already entered keeps its priority and state.
            exists = c.execute("SELECT 1 FROM portal_scopes WHERE source='internet_archive' AND kind='uploader' AND scope=?",
                               (name,)).fetchone()
            if not exists:
                scope_id = portal_control.add_scope(c, 'uploader', name)
                c.execute('UPDATE portal_scopes SET label=? WHERE id=?', (('Uploader von „%s“' % title)[:200], scope_id))
            c.execute('INSERT INTO archive_uploader_follow(handle,account,item_id,work_id,title,added) VALUES(?,?,?,?,?,?)',
                      (name.casefold(), name, item_id, gid, str(title)[:240], now))
            if not exists:
                new.append(name)
    return {'works': len(works), 'new': len(new), 'accounts': new, 'without_account': without, 'pending': pending,
            'followed': len(known)}


def background(root, c, now=None):
    """Called from the recognition run; cheap, and at most every quarter of an hour."""
    now = time.time() if now is None else now
    if now - _last['at'] < EVERY:
        return None
    _last['at'] = now
    return follow(root, c, now=now)


def listing(c):
    ensure(c)
    rows = [dict(zip(('account', 'item_id', 'work_id', 'title', 'added', 'state', 'imported'), r)) for r in c.execute(
        """SELECT f.account,f.item_id,f.work_id,f.title,f.added,s.state,s.imported FROM archive_uploader_follow f
           LEFT JOIN portal_scopes s ON s.source='internet_archive' AND s.kind='uploader' AND s.scope=f.account
           ORDER BY f.added DESC,f.account LIMIT 300""")]
    for r in rows:
        r['removed'] = r['state'] is None     # the user took the source away; it is not added again
    return {'items': rows, 'note': 'Vorgemerkte Uploader sind pausiert. Durchsucht werden sie erst, wenn du sie startest.'}
