"""Bounded local event log; exports exclude settings, database and media URLs."""
from version import VERSION
import io,json,logging,logging.handlers,platform,re,threading,time,traceback,zipfile
from pathlib import Path
_lock=threading.RLock();_root=None;_secrets=set()
logger=logging.getLogger('atlas');logger.setLevel(logging.INFO);logger.propagate=False;logger.addHandler(logging.NullHandler())

def register_secrets(*values):
    with _lock:_secrets.update(str(v) for v in values if v)

def clean(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if re.search(r'(?i)token|password|secret|api.?key|authorization|tmdb|omdb|tvdb',k) else clean(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if not isinstance(value,str):return value
    with _lock:
        for secret in _secrets:value=value.replace(secret,'[REDACTED]')
    value=value.replace(str(Path.home()),'~')
    value=re.sub(r'https?://[^\s\"\'<>]+','[URL]',value)
    value=re.sub(r'(?i)((?:api.?key|token|password|authorization)\s*[=:]\s*)\S+',r'\1[REDACTED]',value)
    return value[:12000]
def setup(root):
    global _root
    _root=Path(root);_root.mkdir(parents=True,exist_ok=True)
    for h in list(logger.handlers):logger.removeHandler(h);h.close()
    h=logging.handlers.RotatingFileHandler(_root/'diagnostic.jsonl',maxBytes=2*1024*1024,backupCount=3,encoding='utf-8');logger.addHandler(h)
def event(name,level='INFO',**fields):
    with _lock:logger.log(getattr(logging,level),json.dumps(clean({'time':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'level':level,'event':name,**fields}),ensure_ascii=False))
def error(name,exc,**fields):
    event(name,'ERROR',error_type=type(exc).__name__,error=str(exc),traceback=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)),**fields)
def tail():
    if not _root:return ''
    with _lock:
        p=_root/'diagnostic.jsonl'
        if not p.exists():return ''
        with p.open('rb') as f:
            f.seek(max(0,p.stat().st_size-128*1024));data=f.read()
        return '\n'.join(data.decode('utf-8',errors='replace').splitlines()[-400:])
def export(snapshot):
    out=io.BytesIO()
    with _lock,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('status.json',json.dumps(clean({'version':VERSION,'system':platform.system(),'machine':platform.machine(),'python':platform.python_version(),**snapshot}),ensure_ascii=False,indent=2))
        if _root:
            for p in sorted(_root.glob('diagnostic.jsonl*')):z.writestr(p.name,p.read_bytes())
            startup=_root/'startup.log'
            if startup.exists():
                with startup.open('rb') as f:
                    f.seek(max(0,startup.stat().st_size-128*1024));z.writestr('startup.txt',clean(f.read().decode('utf-8',errors='replace')))
        z.writestr('README.txt','Diagnose MediathekAtlas. Enthält Ereignisse und technischen Status. Keine Datenbank, Einstellungen, API-Schlüssel oder Medien. Protokoll vor Weitergabe bei Bedarf prüfen. Zeitangaben UTC.\n')
    return out.getvalue()
