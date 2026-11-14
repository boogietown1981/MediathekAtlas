"""Safe, verifiable management of inactive SQLite snapshots in ArchiveMedia/Backups.

Never touch archive.sqlite3, WAL/SHM, part files or any arbitrary paths.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import re
from pathlib import Path

SUFFIXES={'.sqlite3','.db','.sqlite'}
VALID_NAME=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_. -]{0,220}$')
AUDIT='.backup_deletions.json'
TOMBSTONES='.backup_deleted_names.json'


def _folder(root):
    folder=Path(root)/'Backups'
    if folder.is_symlink():
        raise ValueError('Verknüpfte Backup-Verzeichnisse dürfen nicht bearbeitet werden')
    return folder


def _safe_name(name):
    if not isinstance(name,str) or not VALID_NAME.fullmatch(name) or '/' in name or '\\' in name:
        raise ValueError('Ungültiger Sicherungsname')
    if name in {'.','..','archive.sqlite3','archive.sqlite3-wal','archive.sqlite3-shm'}:
        raise ValueError('Die aktive Datenbank kann hier nicht gelöscht werden')
    if Path(name).suffix.lower() not in SUFFIXES:
        raise ValueError('Nur eigenständige SQLite-Sicherungen werden verwaltet')
    return name


def _candidate(root,name):
    folder=_folder(root)
    name=_safe_name(name)
    target=folder/name
    if target.is_symlink() or not target.is_file():
        raise ValueError('Sicherung nicht mehr vorhanden oder keine reguläre Datei: '+name)
    return target


def _identity(path,st=None):
    st=st or path.stat()
    return hashlib.sha256(f'{path.name}:{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}'.encode()).hexdigest()[:24]


def _audit_path(root):
    return Path(root)/AUDIT


def _audit_records(root):
    p=_audit_path(root)
    try:
        if p.is_symlink():return []
        data=json.loads(p.read_text(encoding='utf-8'))
        return data[-100:] if isinstance(data,list) else []
    except (OSError,ValueError,TypeError):return []


def _tombstones(root):
    path=Path(root)/TOMBSTONES
    try:
        if path.is_symlink():return set()
        names=json.loads(path.read_text(encoding='utf-8'))
        return set(n for n in names if isinstance(n,str) and VALID_NAME.fullmatch(n)) if isinstance(names,list) else set()
    except (OSError,ValueError,TypeError):return set()


def _record_tombstones(root,deleted):
    if not deleted:return None
    path=Path(root)/TOMBSTONES
    if path.is_symlink():return 'Löschvermerk ist verknüpft; erneute Sicherungen könnten nicht verhindert werden'
    names=_tombstones(root)
    names.update(item['name'] for item in deleted)
    temp=path.with_name(path.name+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            json.dump(sorted(names),f,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600)
        temp.replace(path)
        return None
    except OSError as exc:
        temp.unlink(missing_ok=True)
        return 'Löschvermerk konnte nicht gespeichert werden: '+type(exc).__name__


def _append_audit(root,deleted):
    """Best effort local audit for diagnosing snapshots that later reappear."""
    if not deleted:return None
    policy_warning=_record_tombstones(root,deleted)
    path=_audit_path(root)
    if path.is_symlink():return 'Auditdatei ist verknüpft; Löschung selbst war erfolgreich'
    stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    old=_audit_records(root)
    old.extend({'name':item['name'],'deleted_utc':stamp,'size_bytes':item['size_bytes']} for item in deleted)
    tmp=path.with_name(path.name+'.tmp')
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(old[-100:],f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        tmp.replace(path)
        return policy_warning
    except OSError as e:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass
        return 'Löschung erfolgt, Audit konnte nicht gespeichert werden: '+type(e).__name__


def was_deleted(root, name):
    """Honor the user's explicit removal of an automatic backup name.

    Never infer it from whether a file exists. Historical backup creators must
    consult this durable on-disk audit before attempting to recreate a filename.
    """
    name=_safe_name(name)
    return name in _tombstones(root) or any(
        isinstance(record,dict) and record.get('name')==name
        for record in _audit_records(root))


def list_backups(root):
    folder=_folder(root)
    backups=[]
    if folder.is_dir():
        for p in folder.iterdir():
            try:
                if p.is_symlink() or not p.is_file() or p.suffix.lower() not in SUFFIXES:continue
                _safe_name(p.name)
                st=p.stat()
                backups.append({'name':p.name,'size_bytes':st.st_size,'fingerprint':_identity(p,st),
                    'modified_utc':datetime.datetime.fromtimestamp(st.st_mtime,datetime.timezone.utc).isoformat()})
            except (OSError,ValueError):continue
    backups.sort(key=lambda x:x['modified_utc'],reverse=True)
    previous={r.get('name'):r for r in _audit_records(root) if isinstance(r,dict)}
    # A name previously deleted and now present again is recreated/restored, even
    # if the restored file preserved its original mtime.
    reappeared=[x['name'] for x in backups if x['name'] in previous]
    return {'backups':backups,'total_bytes':sum(x['size_bytes'] for x in backups),
        'count':len(backups),'directory':str(folder),
        'last_deletions':list(reversed(_audit_records(root)[-10:])),
        'reappeared':reappeared}


def delete_backups(root, entries, confirm):
    """Verify all selected files before removing any, and reread disk after deletion.

    Each file can carry the fingerprint presented in the current UI. Reject
    changed/replaced files rather than deleting a newer snapshot accidentally.
    """
    if confirm!='BACKUP LÖSCHEN':
        raise ValueError('Bitte das Löschen ausdrücklich bestätigen')
    if not isinstance(entries,list) or not 1<=len(entries)<=500:
        raise ValueError('1 bis 500 Sicherungen auswählen')
    checked=[];seen=set()
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Ungültige Sicherungsauswahl')
        name=_safe_name(entry.get('name'))
        if name in seen:raise ValueError('Doppelte Sicherungsauswahl')
        seen.add(name)
        path=_candidate(root,name)
        st=path.stat()
        fingerprint=entry.get('fingerprint')
        if fingerprint is not None and fingerprint!=_identity(path,st):
            raise ValueError('Sicherung wurde zwischenzeitlich verändert: '+name+' – bitte neu laden')
        # SQLite snapshots can still be under construction as .part: never
        # interfere with an active backup producer.
        if path.with_name(name+'.part').exists():
            raise ValueError('Sicherung wird noch erstellt: '+name)
        checked.append((path,st))
    deleted=[]
    for path,st in checked:
        try:
            current=path.stat()
            if _identity(path,current)!=_identity(path,st) or path.is_symlink():
                raise ValueError('Sicherung wurde zwischenzeitlich verändert: '+path.name)
            path.unlink()
            deleted.append({'name':path.name,'size_bytes':st.st_size})
        except (OSError,ValueError) as exc:
            error=ValueError('Nur '+str(len(deleted))+' Sicherungen entfernt; bei '+path.name+': '+str(exc))
            _append_audit(root,deleted)
            raise error from exc
    # Re-read authoritative filesystem. Never report success from UI state alone.
    remaining=list_backups(root)
    survivors=[x['name'] for x in deleted if any(y['name']==x['name'] for y in remaining['backups'])]
    warning=_append_audit(root,deleted)
    if survivors:
        raise ValueError('Sicherung nach Löschen erneut vorhanden: '+', '.join(survivors))
    return {'ok':True,'deleted':[d['name'] for d in deleted],
        'deleted_count':len(deleted),'freed_bytes':sum(x['size_bytes'] for x in deleted),
        'remaining_count':remaining['count'],'remaining_bytes':remaining['total_bytes'],
        'warning':warning}


def delete_backup(root,name,confirm,fingerprint=None):
    """Backward-compatible endpoint for clients upgrading from v0.10.42."""
    result=delete_backups(root,[{'name':name,'fingerprint':fingerprint}],confirm)
    return {'ok':True,'deleted':name,'freed_bytes':result['freed_bytes'],
        'remaining_count':result['remaining_count'],'warning':result['warning']}
