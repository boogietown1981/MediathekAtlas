"""Persistent provider-specific negative results for unchanged title queries.

The cache records only *successful empty results*, never errors/pauses. Tokens
contain digests of provider credentials, not the credentials themselves.
"""
import hashlib,json,sqlite3,threading,time
from pathlib import Path

_PATH=None
_LOCAL=threading.local()
_TTL={'TVDB':7*86400,'TMDB':3*86400,'OMDb':2*86400,'Wikidata':7*86400}

def configure(path):
    global _PATH
    _PATH=Path(path)
    _PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(_PATH),timeout=10) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS misses(token TEXT PRIMARY KEY,provider TEXT,expires REAL)')
        c.execute('DELETE FROM misses WHERE expires<?',(time.time(),))
    if hasattr(_LOCAL,'connection'):
        _LOCAL.connection.close();del _LOCAL.connection

def _db():
    if _PATH is None:return None
    c=getattr(_LOCAL,'connection',None)
    if c is None:
        c=sqlite3.connect(str(_PATH),timeout=10)
        c.execute('PRAGMA busy_timeout=10000')
        _LOCAL.connection=c
    return c

def token(provider,kind,title,year=None,credential=''):
    if provider not in _TTL:return ''
    cred_hash=hashlib.sha256(str(credential or '').encode()).hexdigest()[:16]
    values=['v1',provider,kind,str(title or '').casefold().strip(),int(year) if year else None,cred_hash]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def contains(provider,kind,title,year=None,credential='',force=False):
    if force:return False
    k=token(provider,kind,title,year,credential)
    if not k:return False
    c=_db()
    if c is None:return False
    try:
        row=c.execute('SELECT expires FROM misses WHERE token=?',(k,)).fetchone()
        return bool(row and row[0]>time.time())
    except sqlite3.Error:return False

def remember(provider,kind,title,year=None,credential=''):
    k=token(provider,kind,title,year,credential)
    if not k:return
    c=_db()
    if c is None:return
    try:
        with c:c.execute('INSERT OR REPLACE INTO misses VALUES(?,?,?)',(k,provider,time.time()+_TTL[provider]))
    except sqlite3.Error:pass

def forget_all():
    c=_db()
    if c is not None:
        with c:c.execute('DELETE FROM misses')
