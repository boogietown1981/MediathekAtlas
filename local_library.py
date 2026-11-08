"""Resolve moved downloads without losing history or serving arbitrary NAS files.

No automatic deletion. Paths can be recovered only within configured library roots.
Never traverse symlinked directories or infer identity from titles alone.
"""
import json,os,time,threading
from pathlib import Path

MEDIA={'.mkv','.mp4','.m4v','.webm','.mov','.avi','.mp3','.m4a'}
_LOCK=threading.Lock()
_STATUS={}
TTL=15

def file_state(path):
    """Cheap cached existence status for dashboard polling (does not mutate jobs)."""
    if not path:return 'missing'
    path=str(path);now=time.monotonic()
    with _LOCK:
        previous=_STATUS.get(path)
        if previous and now-previous[0]<TTL:return previous[1]
    try:good=Path(path).is_file()
    except OSError:good=False
    state='available' if good else 'missing'
    with _LOCK:
        if len(_STATUS)>4096:_STATUS.clear()
        _STATUS[path]=(now,state)
    return state

def invalidate(*paths):
    with _LOCK:
        for path in paths:_STATUS.pop(str(path),None)

def roots(settings):
    folders=[settings.get('download_dir','')]+list(settings.get('library_dirs') or [])
    output=[];seen=set()
    for value in folders[:9]:
        try:
            p=Path(value).expanduser()
            if not p.is_absolute():continue
            p=p.resolve()
            if p==Path(p.anchor) or p in seen:continue
        except (OSError,ValueError,RuntimeError):continue
        seen.add(p);output.append(p)
    return output

def inside(p,root):
    try:return os.path.commonpath((str(p),str(root)))==str(root)
    except ValueError:return False

def validated_path(value,allowed):
    p=Path(str(value)).expanduser()
    if not p.is_absolute():raise ValueError('Bitte einen absoluten Dateipfad angeben')
    try:p=p.resolve(strict=True)
    except (OSError,RuntimeError):raise ValueError('Datei am angegebenen Pfad nicht gefunden') from None
    if not any(inside(p,root) for root in allowed):
        raise ValueError('Speicherort nicht freigegeben. Ordner zuerst unter Einstellungen hinzufügen.')
    if not p.is_file() or p.suffix.lower() not in MEDIA:
        raise ValueError('Bitte eine vorhandene Video- oder Audiodatei wählen')
    return p

def check_identity(job,path):
    size=job.get('size_bytes')
    if isinstance(size,(int,float)) and size>0:
        if path.stat().st_size!=int(size):
            raise ValueError('Dateigröße weicht vom ursprünglichen Download ab – keine automatische Verknüpfung')
    elif path.name!=(Path(job.get('path') or job.get('target') or '').name):
        raise ValueError('Dateiname stimmt nicht überein und die Originalgröße ist unbekannt')
    return True

def missing_job(c,job_id):
    row=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(job_id,)).fetchone()
    if not row:raise ValueError('Abgeschlossener Download nicht gefunden')
    j=json.loads(row[0])
    old=j.get('path') or j.get('target') or ''
    return j,old

def relink(c,job_id,target,allowed):
    j,old=missing_job(c,job_id)
    p=validated_path(target,allowed)
    check_identity(j,p)
    old=str(old)
    j['path']=str(p);j['target']=str(p)
    if old!=str(p):
        history=j.get('previous_paths') or []
        j['previous_paths']=(history+[old])[-8:]
    j['relinked_at']=time.time()
    c.execute("UPDATE jobs SET payload=? WHERE id=? AND state='done'",(json.dumps(j),job_id))
    # Downloaded identities remain linked even if a work was merged later.
    c.execute("UPDATE downloaded_items SET path=? WHERE path=?",(str(p),old))
    invalidate(old,p)
    return {'ok':True,'path':str(p),'job':job_id}

def candidates(job,allowed,max_files=25000,seconds=3):
    """Bounded library search, never recursive into symlinked directories."""
    original=Path(job.get('path') or job.get('target') or '')
    if not original.name:return {'matches':[],'incomplete':False,'scanned':0}
    expected=job.get('size_bytes')
    start=time.monotonic();found=[];count=0;incomplete=False
    for base in allowed:
        if not base.is_dir():continue
        for folder,dirs,files in os.walk(str(base),followlinks=False):
            dirs[:]=[d for d in dirs if not d.startswith('.') and not Path(folder,d).is_symlink()]
            if time.monotonic()-start>=seconds or count>=max_files:
                incomplete=True;break
            for name in files:
                count+=1
                if count>=max_files or time.monotonic()-start>=seconds:
                    incomplete=True;break
                if name!=original.name:continue
                path=Path(folder,name)
                try:
                    path=validated_path(path,allowed)
                    if expected and path.stat().st_size!=expected:continue
                except (OSError,ValueError):continue
                found.append(str(path))
                if len(found)>=20:return {'matches':found,'incomplete':True,'scanned':count}
            if incomplete:break
        if incomplete:break
    return {'matches':found,'incomplete':incomplete,'scanned':count}
