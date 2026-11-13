"""Archivnachweise für Archive.org-Downloads im Verbund (0.5.95), nach dem Vorbild von HomeTube.

What a receipt says: "this system holds the file ``<file>`` of the upload ``<identifier>``; the
bytes loaded from Archive.org had this SHA-256 (and matched the checksum Archive.org publishes,
if one was known); the stored file has this size and SHA-256", signed with the Ed25519 key of
the system (``ed25519_lite``). Every system publishes its receipts in the Verbund journal
(``archive.receipt``); the others check the signature and remember the key of the system the
first time they see it. A later receipt of the same system under another key is shown as
"Schlüssel geändert" and does not count as a proven copy.

What it does not say: that the file is still there today. A receipt is a statement with a date.
A system withdraws its receipt when the file is deleted there or a re-check finds it missing.

Nothing here deletes or moves a file, and no rule of ``storage_policy`` changes: the proven
second copy is shown, the decision stays with the user.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

import ed25519_lite

ORIGIN = 'internet_archive'
SELF = 'self'
HEX32 = re.compile(r'[0-9a-f]{32}')
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
HEX128 = re.compile(r'[0-9a-f]{128}')
IDENT = re.compile(r'[A-Za-z0-9_.-]{1,130}')
CHECKS = ('md5', 'sha1', '')
FIELDS = ('identifier', 'file', 'stored_size', 'stored_sha256', 'source_size', 'source_sha256', 'source_check', 'converted', 'withdrawn', 'at')
SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts(node TEXT NOT NULL, identifier TEXT NOT NULL, file TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '', stored_size INTEGER NOT NULL DEFAULT 0, stored_sha256 TEXT NOT NULL DEFAULT '',
  source_size INTEGER NOT NULL DEFAULT 0, source_sha256 TEXT NOT NULL DEFAULT '', source_check TEXT NOT NULL DEFAULT '',
  converted INTEGER NOT NULL DEFAULT 0, withdrawn INTEGER NOT NULL DEFAULT 0, at INTEGER NOT NULL, pub TEXT NOT NULL, sig TEXT NOT NULL,
  trust TEXT NOT NULL DEFAULT 'valid', published INTEGER NOT NULL DEFAULT 0, checked REAL, check_state TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(node, identifier, file));
CREATE TABLE IF NOT EXISTS receipt_keys(node TEXT PRIMARY KEY, pub TEXT NOT NULL, first_seen REAL NOT NULL);
"""


def connect(root):
    db = sqlite3.connect(Path(root) / 'archive_receipts.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def keypair(root):
    """(secret seed, public key hex) of this system; created on first use, readable by the owner only."""
    path = Path(root) / 'receipt_key.json'
    try:
        seed = bytes.fromhex(json.loads(path.read_text())['seed'])
        if len(seed) == 32:
            return seed, ed25519_lite.public_key(seed).hex()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    seed = secrets.token_bytes(32)
    temp = path.with_suffix('.json.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'seed': seed.hex(), 'created': int(time.time()), 'note': 'Geheimer Schlüssel der Archivnachweise dieses Systems. Nicht weitergeben.'}, stream)
    os.replace(temp, path)
    return seed, ed25519_lite.public_key(seed).hex()


def digest(path, cancelled=None):
    """(sha256 hex, size) of a file, read in pieces so a NAS stays responsive."""
    h, size = hashlib.sha256(), 0
    with open(path, 'rb') as stream:
        while True:
            if cancelled and cancelled():
                raise ValueError('Prüfung abgebrochen')
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return h.hexdigest(), size
            h.update(chunk)
            size += len(chunk)


def hashers():
    return {name: hashlib.new(name) for name in ('md5', 'sha1', 'sha256')}


def expectation(variant):
    """Checksums Archive.org publishes for one file of the manifest, as far as they are well-formed."""
    out = {}
    for name, shape in (('md5', HEX32), ('sha1', HEX40)):
        value = str((variant or {}).get(name) or '').strip().lower()
        if shape.fullmatch(value):
            out[name] = value
    return out


def source_check(expect, digests, size):
    """Compare the loaded bytes with the published checksums. Raises on a mismatch; returns what is proven."""
    expect = expect if isinstance(expect, dict) else {}
    matched = ''
    for name in ('sha1', 'md5'):
        wanted = str(expect.get(name) or '').lower()
        if not wanted:
            continue
        if digests[name].hexdigest() != wanted:
            raise ValueError('Die geladene Datei stimmt nicht mit der Prüfsumme von Archive.org überein (%s). Sie wurde verworfen. '
                             'Bitte den Dateibestand des Uploads neu lesen und erneut laden.' % name.upper())
        matched = matched or name
    return {'sha256': digests['sha256'].hexdigest(), 'size': int(size), 'matched': matched}


def statement(data):
    """The exact bytes a receipt signs."""
    return json.dumps({'v': 1, **{key: data[key] for key in FIELDS}}, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def valid_data(data):
    """Shape of a receipt from another system (used by meshjournal before anything is stored)."""
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get('identifier'), str) or not IDENT.fullmatch(data['identifier']):
        return False
    name = data.get('file')
    if not isinstance(name, str) or not 0 < len(name) <= 1200 or '\x00' in name or name.startswith('/') or '..' in name.split('/'):
        return False
    for key in ('stored_size', 'source_size', 'at'):
        if type(data.get(key)) is not int or not 0 <= data[key] < 10 ** 15:
            return False
    for key in ('converted', 'withdrawn'):
        if type(data.get(key)) is not bool:
            return False
    if data.get('source_check') not in CHECKS:
        return False
    for key in ('stored_sha256', 'source_sha256'):
        if data.get(key) != '' and not (isinstance(data.get(key), str) and HEX64.fullmatch(data[key])):
            return False
    if not data['withdrawn'] and not data['stored_sha256']:
        return False
    if not isinstance(data.get('title', ''), str) or len(data.get('title', '')) > 300:
        return False
    return isinstance(data.get('pub'), str) and bool(HEX64.fullmatch(data['pub'])) and isinstance(data.get('sig'), str) and bool(HEX128.fullmatch(data['sig']))


def _job_file(job):
    path = Path(str(job.get('path') or job.get('target') or ''))
    return path if path.is_file() and not path.is_symlink() else None


def _sign(root, data):
    seed, pub = keypair(root)
    return {**data, 'pub': pub, 'sig': ed25519_lite.sign(seed, statement(data)).hex()}


def _store_own(db, data, title, job_id, path):
    db.execute("""INSERT OR REPLACE INTO receipts(node,identifier,file,title,job_id,path,stored_size,stored_sha256,source_size,source_sha256,source_check,
        converted,withdrawn,at,pub,sig,trust,published,checked,check_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'own',0,?,?)""",
               (SELF, data['identifier'], data['file'], title[:300], job_id, path, data['stored_size'], data['stored_sha256'], data['source_size'],
                data['source_sha256'], data['source_check'], int(data['converted']), int(data['withdrawn']), data['at'], data['pub'], data['sig'],
                None if data['withdrawn'] else float(data['at']), 'withdrawn' if data['withdrawn'] else 'ok'))


def issue(root, job, now=None, converted=False, cancelled=None):
    """Measure the finished file of one Archive.org download and store this system's signed receipt."""
    if job.get('origin') != ORIGIN or not job.get('archive_identifier') or not job.get('archive_file'):
        raise ValueError('Nachweise gibt es nur für Archive.org-Downloads')
    path = _job_file(job)
    if not path:
        raise ValueError('Die Datei des Downloads wurde nicht gefunden')
    sha, size = digest(path, cancelled)
    check = job.get('source_check') if isinstance(job.get('source_check'), dict) else {}
    source_sha = str(check.get('sha256') or '')
    data = {'identifier': str(job['archive_identifier']), 'file': str(job['archive_file']), 'stored_size': size, 'stored_sha256': sha,
            'source_size': int(check.get('size') or 0) if HEX64.fullmatch(source_sha) else 0,
            'source_sha256': source_sha if HEX64.fullmatch(source_sha) else '',
            'source_check': check.get('matched') if check.get('matched') in CHECKS and HEX64.fullmatch(source_sha) else '',
            'converted': bool(converted or job.get('encoded')), 'withdrawn': False, 'at': int(time.time() if now is None else now)}
    data = _sign(root, data)
    meta = job.get('metadata') or {}
    title = str(meta.get('episode_title') or meta.get('title') or path.stem)
    db = connect(root)
    try:
        with db:
            _store_own(db, data, title, str(job.get('id') or ''), str(path))
    finally:
        db.close()
    return data


def withdraw(root, identifier, file, now=None):
    """This system no longer vouches for the file (deleted or missing). Returns the signed withdrawal or None."""
    db = connect(root)
    try:
        with db:
            row = db.execute('SELECT * FROM receipts WHERE node=? AND identifier=? AND file=?', (SELF, identifier, file)).fetchone()
            if not row or row['withdrawn']:
                return None
            data = _sign(root, {'identifier': identifier, 'file': file, 'stored_size': 0, 'stored_sha256': '', 'source_size': 0, 'source_sha256': '',
                                'source_check': '', 'converted': False, 'withdrawn': True, 'at': max(int(time.time() if now is None else now), row['at'] + 1)})
            _store_own(db, data, row['title'], row['job_id'], '')
            return data
    finally:
        db.close()


def withdraw_job(root, job, now=None):
    if isinstance(job, dict) and job.get('origin') == ORIGIN and job.get('archive_identifier') and job.get('archive_file'):
        return withdraw(root, str(job['archive_identifier']), str(job['archive_file']), now)
    return None


def unpublished(root, limit=200):
    """Own receipts the Verbund has not seen yet, as journal data."""
    db = connect(root)
    try:
        rows = db.execute('SELECT * FROM receipts WHERE node=? AND published=0 ORDER BY at LIMIT ?', (SELF, int(limit))).fetchall()
    finally:
        db.close()
    return [{**{key: (bool(r[key]) if key in ('converted', 'withdrawn') else r[key]) for key in FIELDS}, 'title': r['title'], 'pub': r['pub'], 'sig': r['sig']} for r in rows]


def mark_published(root, items):
    db = connect(root)
    try:
        with db:
            for data in items:
                db.execute('UPDATE receipts SET published=1 WHERE node=? AND identifier=? AND file=? AND at=?', (SELF, data['identifier'], data['file'], data['at']))
    finally:
        db.close()


def republish(root):
    """After joining another Verbund folder every own receipt is announced again."""
    db = connect(root)
    try:
        with db:
            db.execute('UPDATE receipts SET published=0 WHERE node=?', (SELF,))
    finally:
        db.close()


def accept(root, node, data, now=None):
    """Store the receipt of another system after checking its signature. False if it is not usable or not newer."""
    if node == SELF or not valid_data(data):
        return False
    if not ed25519_lite.verify(bytes.fromhex(data['pub']), statement(data), bytes.fromhex(data['sig'])):
        return False
    db = connect(root)
    try:
        with db:
            known = db.execute('SELECT pub FROM receipt_keys WHERE node=?', (node,)).fetchone()
            if not known:
                db.execute('INSERT INTO receipt_keys VALUES(?,?,?)', (node, data['pub'], time.time() if now is None else now))
            trust = 'valid' if not known or known['pub'] == data['pub'] else 'key_changed'
            old = db.execute('SELECT at FROM receipts WHERE node=? AND identifier=? AND file=?', (node, data['identifier'], data['file'])).fetchone()
            if old and old['at'] >= data['at']:
                return False
            db.execute("""INSERT OR REPLACE INTO receipts(node,identifier,file,title,stored_size,stored_sha256,source_size,source_sha256,source_check,
                converted,withdrawn,at,pub,sig,trust,published) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                       (node, data['identifier'], data['file'], str(data.get('title') or '')[:300], data['stored_size'], data['stored_sha256'],
                        data['source_size'], data['source_sha256'], data['source_check'], int(data['converted']), int(data['withdrawn']),
                        data['at'], data['pub'], data['sig'], trust))
            return True
    finally:
        db.close()


def recheck(root, identifier, file, now=None, cancelled=None):
    """Read this system's file again and compare it with its receipt. A missing file withdraws the receipt."""
    db = connect(root)
    try:
        row = db.execute('SELECT * FROM receipts WHERE node=? AND identifier=? AND file=? AND withdrawn=0', (SELF, identifier, file)).fetchone()
    finally:
        db.close()
    if not row:
        raise ValueError('Für diese Datei gibt es hier keinen Nachweis')
    path = Path(row['path'])
    if not path.is_file() or path.is_symlink():
        withdraw(root, identifier, file, now)
        return {'state': 'missing', 'message': 'Die Datei liegt nicht mehr am gespeicherten Ort. Der Nachweis wurde zurückgezogen.'}
    sha, size = digest(path, cancelled)
    state = 'ok' if sha == row['stored_sha256'] and size == row['stored_size'] else 'changed'
    db = connect(root)
    try:
        with db:
            db.execute('UPDATE receipts SET checked=?,check_state=? WHERE node=? AND identifier=? AND file=?',
                       (time.time() if now is None else now, state, SELF, identifier, file))
    finally:
        db.close()
    return {'state': state, 'message': 'Die Datei ist unverändert.' if state == 'ok' else
            'Die Datei weicht von ihrem Nachweis ab (verändert oder beschädigt). Bitte prüfen und bei Bedarf neu laden.'}


def missing(c, root):
    """Finished Archive.org downloads of this system without a current receipt."""
    db = connect(root)
    try:
        have = {(r['identifier'], r['file']) for r in db.execute('SELECT identifier,file FROM receipts WHERE node=? AND withdrawn=0', (SELF,))}
    finally:
        db.close()
    out = []
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='done'").fetchall():
        try:
            job = json.loads(payload)
        except ValueError:
            continue
        if job.get('origin') == ORIGIN and job.get('archive_identifier') and job.get('archive_file') \
                and (job['archive_identifier'], job['archive_file']) not in have and _job_file(job):
            out.append(job)
    return out


def remote(root, identifier, file):
    """A valid, current receipt of another system for this file, or None."""
    db = connect(root)
    try:
        return db.execute("SELECT * FROM receipts WHERE node!=? AND identifier=? AND file=? AND withdrawn=0 AND trust='valid' ORDER BY at DESC",
                          (SELF, identifier, file)).fetchone()
    finally:
        db.close()


def overview(root, names=None, pending=0, verbund=False):
    """Every file with a receipt: this system's copy, the copies other systems vouch for, and what follows from both."""
    names = names or {}
    db = connect(root)
    try:
        rows = db.execute('SELECT * FROM receipts ORDER BY identifier,file').fetchall()
    finally:
        db.close()
    files = {}
    for r in rows:
        entry = files.setdefault((r['identifier'], r['file']), {'identifier': r['identifier'], 'file': r['file'], 'title': '', 'own': None, 'copies': []})
        entry['title'] = entry['title'] or r['title']
        if r['node'] == SELF:
            if not r['withdrawn']:
                entry['own'] = {'at': r['at'], 'stored_size': r['stored_size'], 'source_check': r['source_check'], 'source_known': bool(r['source_sha256']),
                                'converted': bool(r['converted']), 'checked': r['checked'], 'check_state': r['check_state'], 'published': bool(r['published']),
                                'source_sha256': r['source_sha256']}
        elif not r['withdrawn']:
            entry['copies'].append({'node': r['node'], 'name': str(names.get(r['node']) or r['node'][:8]), 'at': r['at'], 'stored_size': r['stored_size'],
                                    'source_check': r['source_check'], 'converted': bool(r['converted']), 'trust': r['trust'], 'source_sha256': r['source_sha256']})
    out = []
    counts = {'own': 0, 'second_copy': 0, 'single': 0, 'remote_only': 0, 'attention': 0}
    for entry in files.values():
        own = entry['own']
        proven = [c for c in entry['copies'] if c['trust'] == 'valid']
        for copy in entry['copies']:
            mine, theirs = (own or {}).get('source_sha256'), copy.pop('source_sha256')
            copy['same_source'] = None if not mine or not theirs else mine == theirs
        if not own and not entry['copies']:
            continue
        if own:
            own.pop('source_sha256')
            counts['own'] += 1
            entry['status'] = 'second_copy' if proven else 'single'
            if own['check_state'] == 'changed' or any(c['same_source'] is False or c['trust'] != 'valid' for c in entry['copies']):
                counts['attention'] += 1
        else:
            entry['status'] = 'remote_only'
        counts[entry['status']] += 1
        out.append(entry)
    out.sort(key=lambda e: ({'single': 0, 'second_copy': 1, 'remote_only': 2}[e['status']], (e['title'] or e['file']).casefold()))
    return {'files': out[:500], 'total': len(out), 'counts': counts, 'pending': int(pending), 'verbund': bool(verbund),
            'key': keypair(root)[1][:16],
            'note': 'Ein Nachweis ist eine signierte Aussage mit Datum, keine laufende Überwachung. Gelöscht wird hier nichts.'}
