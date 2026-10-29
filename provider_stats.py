"""Session counters for provider title checks (not individual HTTP requests)."""
import threading,time
_LOCK=threading.Lock();_STARTED=time.time();_ROWS={}
def observe(provider,status,count=0):
    if status=='not_configured':return
    with _LOCK:
        r=_ROWS.setdefault(provider,{'provider':provider,'checks':0,'with_hits':0,'candidates':0,'errors':0,'paused_skips':0,'last_success':None})
        if status=='paused':r['paused_skips']+=1;return
        r['checks']+=1
        if status=='error':r['errors']+=1
        else:
            r['last_success']=time.time();r['candidates']+=count;r['with_hits']+=int(count>0)
def snapshot():
    with _LOCK:return {'since':_STARTED,'rows':[dict(_ROWS.get(p,{'provider':p,'checks':0,'with_hits':0,'candidates':0,'errors':0,'paused_skips':0,'last_success':None})) for p in ('TMDB','TVDB','OMDb','Wikidata','IMDb Offline','ARD Mediathek','ZDF Mediathek')]}
