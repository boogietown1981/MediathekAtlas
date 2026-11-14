"""Verified SQLite snapshots of catalog.db (0.5.56, from ArchiveMedia v0.10.53).

Creation uses SQLite's online backup API, so a running app with WAL stays
consistent. Listing and deletion reuse ArchiveMedia's backup_manager unchanged:
fingerprints are checked before deleting, deleted names are remembered and the
filesystem is re-read afterwards.

Rules:
- Manual snapshots are never removed automatically.
- Automatic snapshots (name contains '-auto-') are created at most once per
  AUTO_INTERVAL; only the oldest automatic ones beyond AUTO_KEEP are removed.
- Never touches catalog.db, its WAL/SHM, or anything outside <data>/Backups.
- No restore while the app runs: restoring means quitting the app and copying
  the snapshot over catalog.db (documented in the UI).
"""
import datetime
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from vendor.archive_portals import backup_manager

DB_NAME='catalog.db'
AUTO_INTERVAL=7*86400
AUTO_KEEP=4
RESERVE_BYTES=256*1024*1024
_LOCK=threading.Lock()
_STATE={'phase':'idle','error':'','last':None,'progress':0.0}


def folder(root):
    return Path(root)/'Backups'


def _stamp(now=None):
    return datetime.datetime.fromtimestamp(now or time.time()).strftime('%Y%m%d-%H%M%S')


def status():
    return dict(_STATE)


def listing(root):
    data=backup_manager.list_backups(root)
    for item in data['backups']:item['automatic']='-auto-' in item['name']
    data['state']=status()
    data['interval_days']=AUTO_INTERVAL//86400
    data['auto_keep']=AUTO_KEEP
    return data


def create(root,automatic=False,now=None):
    """Write <Backups>/catalog-<stamp>[-auto].db; return its listing entry."""
    root=Path(root);source=root/DB_NAME
    if not source.is_file():raise ValueError('Keine Datenbank vorhanden')
    target_dir=folder(root)
    if target_dir.is_symlink():raise ValueError('Verknüpfte Backup-Verzeichnisse werden nicht beschrieben')
    target_dir.mkdir(parents=True,exist_ok=True)
    size=source.stat().st_size+(source.with_name(DB_NAME+'-wal').stat().st_size if source.with_name(DB_NAME+'-wal').exists() else 0)
    free=shutil.disk_usage(target_dir).free
    if free<size+RESERVE_BYTES:
        raise ValueError(f'Zu wenig freier Speicher für eine Sicherung: {free//1048576} MB frei, {(size+RESERVE_BYTES)//1048576} MB nötig')
    name=f"catalog-{'auto-' if automatic else ''}{_stamp(now)}.db"
    if backup_manager.was_deleted(root,name):raise ValueError('Diese Sicherung wurde bereits gelöscht und wird nicht erneut angelegt')
    dest=target_dir/name;part=dest.with_name(name+'.part')
    if not _LOCK.acquire(blocking=False):raise ValueError('Es läuft bereits eine Sicherung')
    _STATE.update(phase='running',error='',progress=0.0)
    try:
        if dest.exists():raise ValueError('Sicherung existiert bereits: '+name)
        part.unlink(missing_ok=True)
        src=sqlite3.connect(source,timeout=30);out=sqlite3.connect(part)
        try:
            def progress(_status,remaining,total):
                _STATE['progress']=round(1-remaining/total,3) if total else 1.0
            # Small steps let the app keep writing while the copy runs.
            src.backup(out,pages=2048,progress=progress,sleep=0.01)
            check=out.execute('PRAGMA quick_check').fetchone()[0]
            if check!='ok':raise ValueError('Sicherung fehlerhaft: '+str(check)[:200])
            out.commit()
        finally:
            out.close();src.close()
        with part.open('rb') as f:os.fsync(f.fileno())
        os.chmod(part,0o600)
        try:
            os.link(part,dest);part.unlink()
        except OSError:
            # SMB/exFAT volumes without hard links: atomic rename, never overwrite.
            if dest.exists():raise ValueError('Sicherung existiert bereits: '+name) from None
            os.replace(part,dest)
        entry=next((x for x in backup_manager.list_backups(root)['backups'] if x['name']==name),None)
        _STATE.update(phase='idle',last={'name':name,'at':time.time(),'automatic':automatic},progress=1.0)
        return {'ok':True,'backup':entry}
    except Exception as e:
        part.unlink(missing_ok=True)
        _STATE.update(phase='failed',error=str(e)[:300])
        raise
    finally:
        _LOCK.release()


def start(root,events=None,errors=None):
    """Manual snapshot in the background; the UI polls listing()['state']."""
    if _STATE['phase']=='running':raise ValueError('Es läuft bereits eine Sicherung')
    def run():
        try:
            made=create(root)
            if events:events('db_backup_created',name=(made.get('backup') or {}).get('name'),manual=True)
        except Exception as e:
            if errors:errors('db_backup_failed',e)
    threading.Thread(target=run,daemon=True,name='db_backup').start()
    return {'started':True}


def delete(root,entries,confirm):
    return backup_manager.delete_backups(root,entries,confirm)


def _automatic(root):
    return [x for x in backup_manager.list_backups(root)['backups'] if '-auto-' in x['name']]


def auto_due(root,now=None):
    autos=_automatic(root)
    if not autos:return True
    newest=max(datetime.datetime.fromisoformat(x['modified_utc']).timestamp() for x in autos)
    return (now or time.time())-newest>=AUTO_INTERVAL


def rotate(root):
    """Remove automatic snapshots beyond AUTO_KEEP, oldest first. Manual ones stay."""
    autos=sorted(_automatic(root),key=lambda x:x['modified_utc'],reverse=True)
    old=autos[AUTO_KEEP:]
    if not old:return []
    result=backup_manager.delete_backups(root,[{'name':x['name'],'fingerprint':x['fingerprint']} for x in old],'BACKUP LÖSCHEN')
    return result['deleted']


def auto_tick(root,events=None):
    if not auto_due(root):return None
    made=create(root,automatic=True)
    removed=rotate(root)
    if events:events('db_backup_created',name=made['backup']['name'] if made.get('backup') else None,removed=removed)
    return made


def loop(root,stop,events=None,errors=None,first_delay=600,interval=3600):
    """Background: first check 10 minutes after start, then hourly.

    Pausable and startable under Verwaltung → Aufgaben (task 'backup').
    """
    import task_control
    deadline=time.monotonic()+first_delay
    while not stop.is_set():
        if not task_control.wait_if_paused('backup',stop):return
        forced=task_control.take_request('backup')
        if forced or time.monotonic()>=deadline:
            try:
                task_control.note('backup','Sicherung läuft')
                made=create(root,automatic=True) if forced else auto_tick(root,events)
                if forced:
                    removed=rotate(root)
                    if events:events('db_backup_created',name=(made.get('backup') or {}).get('name'),removed=removed,requested=True)
                last=_STATE.get('last') or {}
                task_control.note('backup','Letzte Sicherung: '+str(last.get('name') or '–'))
            except Exception as e:
                task_control.note('backup','Fehler: '+str(e)[:160])
                if errors:errors('db_backup_failed',e)
            deadline=time.monotonic()+interval
        if stop.wait(5):return
