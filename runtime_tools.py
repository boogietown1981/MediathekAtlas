"""Resolve media tools for Finder launches, including keg-only Homebrew installs."""
import os, re, shutil, subprocess, sys, time
from pathlib import Path
_CACHE = {}

def candidates(name, explicit=None, prefixes=None):
    if name not in ('ffmpeg', 'ffprobe'):raise ValueError('Unbekanntes Werkzeug')
    out=[]
    if explicit:out.append(str(Path(explicit).expanduser()))
    override=os.environ.get('MEDIATHEKATLAS_'+name.upper())
    if override:out.append(str(Path(override).expanduser()))
    prefixes=prefixes if prefixes is not None else ('/opt/homebrew','/usr/local','/opt/local','/home/linuxbrew/.linuxbrew')
    for prefix in prefixes:
        for sub in ('opt/ffmpeg-full/bin','opt/ffmpeg/bin','bin'):
            out.append(str(Path(prefix)/sub/name))
    normal=shutil.which(name)
    if normal:out.append(normal)
    for prefix in prefixes:
        for formula in ('ffmpeg-full','ffmpeg'):
            folder=Path(prefix)/'Cellar'/formula
            if folder.is_dir():
                for p in sorted(folder.glob('*/bin/'+name),reverse=True):out.append(str(p))
    return list(dict.fromkeys(out))

def inspect_tool(path, name):
    try:
        if not Path(path).is_file() or not os.access(path,os.X_OK):return None
        result=subprocess.run([path,'-version'],capture_output=True,text=True,timeout=5)
        first=(result.stdout or result.stderr).splitlines()
        line=first[0] if first else ''
        if result.returncode or not re.match(re.escape(name)+r' version\s',line):
            return {'path':path,'ok':False,'error':'Vorhanden, aber nicht ausführbar oder falsches Programm'}
        return {'path':str(Path(path).resolve()),'ok':True,'version':line[:180]}
    except (OSError,subprocess.SubprocessError):
        return {'path':path,'ok':False,'error':'Start fehlgeschlagen (Architektur, Bibliotheken oder Ausführungsrechte prüfen)'}

def status(name,explicit=None,refresh=False):
    key=(name,explicit,os.environ.get('PATH'),os.environ.get('MEDIATHEKATLAS_'+name.upper()))
    now=time.monotonic()
    if not refresh and key in _CACHE and now-_CACHE[key][0]<30:return _CACHE[key][1]
    tried=[];failed=[]
    for path in candidates(name,explicit):
        tried.append(path);result=inspect_tool(path,name)
        if result and result['ok']:
            result['failed_candidates']=failed;_CACHE[key]=(now,result);return result
        if result:failed.append(result)
    # Support a custom Homebrew prefix when its brew is visible in PATH.
    brew=shutil.which('brew')
    if brew:
        for formula in ('ffmpeg-full','ffmpeg'):
            try:
                r=subprocess.run([brew,'--prefix',formula],capture_output=True,text=True,timeout=3)
                if r.returncode==0 and Path(r.stdout.strip()).is_absolute():
                    path=str(Path(r.stdout.strip())/'bin'/name)
                    if path not in tried:
                        tried.append(path);result=inspect_tool(path,name)
                        if result and result['ok']:
                            result['failed_candidates']=failed;_CACHE[key]=(now,result);return result
                        if result:failed.append(result)
            except (OSError,subprocess.SubprocessError):pass
    result={'ok':False,'path':None,'error':('Gefunden, aber nicht startbar' if failed else 'In den geprüften Pfaden nicht gefunden'),'failed_candidates':failed,'searched':tried}
    _CACHE[key]=(now,result);return result

def resolve(name):return status(name).get('path')

def report(refresh=False):
    return {'python':{'ok':True,'path':sys.executable,'version':sys.version.split()[0]},
            'ffmpeg':status('ffmpeg',refresh=refresh),'ffprobe':status('ffprobe',refresh=refresh)}
