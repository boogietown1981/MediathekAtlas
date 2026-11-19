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
    folders=[settings.get('download_dir',''),settings.get('cache_dir') or '']+list(settings.get('library_dirs') or [])   # 0.6.20: Zwischenspeicher (YouTube-Abos)
    output=[];seen=set()
    for value in folders[:10]:
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


# 0.6.37 (Björn, 19.11.2026): „bei Videos, die nicht mehr gefunden werden, steht nur Pfad verknüpfen …
# hier sollten lieber die Standardpfade geprüft werden, und dann auch die Einträge gelöscht werden können.“
def _missing_jobs(c):
    out=[]
    for job_id,payload in c.execute("SELECT id,payload FROM jobs WHERE state='done'").fetchall():
        try:j=json.loads(payload)
        except (TypeError,ValueError):continue
        path=j.get('path') or j.get('target') or ''
        try:good=bool(path) and Path(path).is_file()
        except OSError:good=False
        if not good:out.append((job_id,j,str(path)))
    return out

def _relative_guesses(old,old_roots,new_roots):
    """Same relative path below another known storage location (e.g. Downloads after a move)."""
    old=Path(old)
    for root in old_roots:
        try:rel=old.relative_to(root)
        except ValueError:continue
        for base in new_roots:
            yield Path(base)/rel
    # Without a known old root: the last two parts (folder/file) and the file name directly below each root.
    if len(old.parts)>=2:
        for base in new_roots:
            yield Path(base)/old.parent.name/old.name
    for base in new_roots:
        yield Path(base)/old.name

def repair_missing(c,allowed,old_roots=(),seconds=20,max_files=200000):
    """Looks for every finished download whose file is missing: first at the same relative path below
    the current and earlier storage locations, then by file name (and size, if known) in all approved
    folders. Exactly one hit is linked again; nothing is moved or deleted."""
    missing=_missing_jobs(c)
    result={'checked':len(missing),'relinked':0,'ambiguous':0,'missing':0,'incomplete':False,'relinked_ids':[]}
    if not missing:return result
    allowed=[Path(p) for p in allowed if Path(p).is_dir()]
    olds=[]
    for value in list(old_roots)+[str(p) for p in allowed]:
        try:p=Path(str(value)).expanduser()
        except (TypeError,ValueError):continue
        if p.is_absolute() and p not in olds:olds.append(p)
    olds.sort(key=lambda p:-len(str(p)))   # longest (most specific) first
    def accept(j,p):
        try:
            p=validated_path(p,allowed);check_identity(j,p);return p
        except (OSError,ValueError,RuntimeError):return None
    open_jobs=[]
    for job_id,j,old in missing:
        hit=None
        if old:
            for guess in _relative_guesses(old,olds,allowed):
                try:
                    if guess.is_file():hit=accept(j,guess)
                except OSError:hit=None
                if hit:break
        if hit:
            relink(c,job_id,str(hit),allowed);result['relinked']+=1;result['relinked_ids'].append(job_id)
        else:open_jobs.append((job_id,j,old))
    if open_jobs:
        # One bounded walk over all approved folders, indexed by file name.
        wanted={Path(old).name for _,_,old in open_jobs if old}
        index={};count=0;start=time.monotonic()
        for base in allowed:
            for folder,dirs,files in os.walk(str(base),followlinks=False):
                dirs[:]=[d for d in dirs if not d.startswith('.') and not Path(folder,d).is_symlink()]
                for name in files:
                    count+=1
                    if name in wanted:index.setdefault(name,[]).append(Path(folder,name))
                if count>=max_files or time.monotonic()-start>=seconds:
                    result['incomplete']=True;break
            if result['incomplete']:break
        for job_id,j,old in open_jobs:
            hits=[p for p in (accept(j,x) for x in index.get(Path(old).name if old else '',[])) if p]
            hits=list(dict.fromkeys(hits))
            if len(hits)==1:
                relink(c,job_id,str(hits[0]),allowed);result['relinked']+=1;result['relinked_ids'].append(job_id)
            elif len(hits)>1:result['ambiguous']+=1
            else:result['missing']+=1
    return result

def remove_missing(c,job_ids=None):
    """Removes finished downloads whose file is missing (checked again here). Files are never touched;
    the "already downloaded" mark of the catalogue goes with the entry."""
    wanted=set(job_ids) if job_ids else None
    removed=0
    for job_id,j,old in _missing_jobs(c):
        if wanted is not None and job_id not in wanted:continue
        c.execute("DELETE FROM jobs WHERE id=? AND state='done'",(job_id,))
        if old:c.execute("DELETE FROM downloaded_items WHERE path=?",(old,)) if _has_table(c,'downloaded_items') else None
        invalidate(old);removed+=1
    return removed

def _has_table(c,name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())
