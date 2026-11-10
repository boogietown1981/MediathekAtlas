"""Independent platform scan controls; ArchiveMedia-inspired scoped discovery.

Only the Internet Archive adapter may perform opt-in API discovery. Netzkino is
manual-link-only. This queue is deliberately unrelated to the downloadable
MediathekView work/episode/download queues. No global Archive.org crawl.

An Archive.org collection/uploader scan is paged, bounded and resumable.
A user may pause each scope and prioritize specific archive IDs/uploaders.
"""
import json
import re
import sqlite3
import threading
import time
import urllib.parse
from urllib.error import HTTPError,URLError

import core
import portal_sources as portals

SCHEMA="""
CREATE TABLE IF NOT EXISTS portal_controls(
 source TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
 workers INTEGER NOT NULL DEFAULT 1, locale TEXT NOT NULL DEFAULT 'de',
 updated REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS portal_runtime(
 setting TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS portal_scopes(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source TEXT NOT NULL,
 kind TEXT NOT NULL,
 scope TEXT NOT NULL,
 label TEXT NOT NULL DEFAULT '',
 priority INTEGER NOT NULL DEFAULT 50,
 state TEXT NOT NULL DEFAULT 'paused',
 enabled INTEGER NOT NULL DEFAULT 0,
 next_try REAL NOT NULL DEFAULT 0,
 cursor INTEGER NOT NULL DEFAULT 1,
 pages_done INTEGER NOT NULL DEFAULT 0,
 page_budget INTEGER NOT NULL DEFAULT 8,
 imported INTEGER NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0,
 last_error TEXT NOT NULL DEFAULT '',
 last_success REAL,
 updated REAL NOT NULL,
 UNIQUE(source,kind,scope));
CREATE INDEX IF NOT EXISTS ix_portal_scopes_due
 ON portal_scopes(source,state,enabled,priority,next_try,id);
"""
KINDS={'item','collection','uploader'}
PRIORITY={'item':0,'uploader':10,'collection':20}
DEFAULT_MAX_ACTIVE=3
MAX_ACTIVE=5
MAX_WORKERS=5
MAX_ARCHIVE_WORKERS=2
PER_PAGE=25
MAX_PAGES_PER_START=25
LOCK=threading.Lock()
_ACTIVE={'internet_archive':0}
_LAST_FETCH={'internet_archive':0.0}


def initialize(c):
    c.executescript(SCHEMA)
    for source in portals.SOURCES:
        c.execute("""INSERT OR IGNORE INTO portal_controls(source,enabled,workers,locale,updated)
            VALUES(?,0,1,'de',0)""",(source,))
    c.execute('INSERT OR IGNORE INTO portal_runtime(setting,value) VALUES(?,?)',
              ('max_active',str(DEFAULT_MAX_ACTIVE)))
    # Crash recovery: do not discard cursor or re-queue completed pages.
    c.execute("UPDATE portal_scopes SET state='queued' WHERE state='running' AND enabled=1")
    c.execute("UPDATE portal_scopes SET state='paused' WHERE state='running' AND enabled=0")


def source_status(c):
    limit=int(c.execute("SELECT value FROM portal_runtime WHERE setting='max_active'").fetchone()[0])
    counts={str(r[0]):{'running':0,'queued':0,'paused':0,'complete':0,'error':0}
            for r in c.execute('SELECT source FROM portal_controls')}
    for r in c.execute('SELECT source,state,COUNT(*) FROM portal_scopes GROUP BY source,state'):
        counts.setdefault(r[0],{})[r[1]]=r[2]
    rows=[]
    for r in c.execute('SELECT source,enabled,workers,locale FROM portal_controls ORDER BY source'):
        source=r[0]
        rows.append({'source':source,'name':portals.SOURCES[source]['name'],
                     'enabled':bool(r[1]),'workers':r[2],'locale':r[3],
                     'mode':portals.SOURCES[source]['mode'],
                     'can_scan':source=='internet_archive',
                     'queues':counts.get(source,{})})
    return {'max_active_platforms':limit,
            'active_platforms':sum(1 for p in rows if p['enabled'] and p['can_scan']),
            'platforms':rows,
            'note':'Jede Quelle hat eigene Cursor und Warteschlangen. Netzkino bleibt manuell.'}


def set_controls(c,source=None,enabled=None,workers=None,locale=None,max_active=None):
    if max_active is not None:
        n=int(max_active)
        if not 1<=n<=MAX_ACTIVE:raise ValueError('1 bis 5 parallele Plattformen zulässig')
        c.execute("""UPDATE portal_runtime SET value=? WHERE setting='max_active'""",(str(n),))
    if source is None:return
    if source not in portals.SOURCES:raise ValueError('Unbekannte Plattform')
    if enabled is not None and source!='internet_archive' and enabled:
        raise ValueError('Diese Plattform unterstützt keine automatische Suche')
    current=c.execute('SELECT enabled,workers,locale FROM portal_controls WHERE source=?',
                      (source,)).fetchone()
    new_enabled=bool(current[0]) if enabled is None else enabled is True
    new_workers=int(current[1]) if workers is None else int(workers)
    if not 1<=new_workers<=MAX_WORKERS:raise ValueError('1 bis 5 Worker zulässig')
    new_locale=str(current[2]) if locale is None else str(locale)
    if new_locale not in ('de','all'):raise ValueError('Sprachfilter ungültig')
    c.execute("""UPDATE portal_controls SET enabled=?,workers=?,locale=?,updated=?
        WHERE source=?""",(int(new_enabled),new_workers,new_locale,time.time(),source))


def normalize_scope(kind,value):
    if kind not in KINDS:raise ValueError('Ungültiger ArchiveMedia-Scanmodus')
    value=str(value or '').strip()
    if kind=='item':
        # The UI may accept either an Archive.org item URL or an identifier.
        if value.startswith('https://'):
            p=urllib.parse.urlsplit(value)
            try:port=p.port
            except ValueError:raise ValueError('Ungültige Archive.org-URL') from None
            if (p.hostname!='archive.org' or port not in (None,443)
                    or p.username or p.password or not p.path.startswith('/details/')):
                raise ValueError('Nur direkte Archive.org-Item-URLs zulässig')
            value=urllib.parse.unquote(p.path[len('/details/'):].strip('/'))
        return portals.internet_archive_id(value)
    if kind=='collection':return portals.internet_archive_id(value)
    if not re.fullmatch(r'@[A-Za-z0-9_.-]{2,80}',value):
        raise ValueError('Öffentlicher Uploader muss als @Benutzername angegeben werden')
    return value


def add_scope(c,kind,value,priority=None,page_budget=8):
    scope=normalize_scope(kind,value)
    n=int(page_budget)
    if not 1<=n<=MAX_PAGES_PER_START:raise ValueError('1 bis 25 Seiten pro Scandurchlauf zulässig')
    level=PRIORITY[kind] if priority is None else int(priority)
    if not 0<=level<=90:raise ValueError('Priorität muss zwischen 0 und 90 liegen')
    now=time.time()
    c.execute("""INSERT INTO portal_scopes
        (source,kind,scope,label,priority,state,page_budget,updated)
        VALUES('internet_archive',?,?,? ,?,'paused',?,?)
        ON CONFLICT(source,kind,scope) DO UPDATE SET
           priority=excluded.priority,page_budget=excluded.page_budget,updated=excluded.updated""",
        (kind,scope,scope,level,n,now))
    return c.execute("""SELECT id FROM portal_scopes
      WHERE source='internet_archive' AND kind=? AND scope=?""",(kind,scope)).fetchone()[0]


def list_scopes(c,source='internet_archive'):
    if source!='internet_archive':return []
    return [dict(r) for r in c.execute("""SELECT id,source,kind,scope,label,priority,
       state,enabled,cursor,pages_done,page_budget,imported,failures,last_error,
       last_success,updated FROM portal_scopes WHERE source=?
       ORDER BY priority,id LIMIT 300""",(source,))]


def control_scope(c,scope_id,action,priority=None):
    r=c.execute('SELECT source,state,enabled FROM portal_scopes WHERE id=?',(int(scope_id),)).fetchone()
    if not r:raise ValueError('Scanquelle nicht gefunden')
    if action=='start':
        c.execute("""UPDATE portal_scopes SET enabled=1,state='queued',next_try=0,
          updated=? WHERE id=?""",(time.time(),scope_id))
    elif action=='pause':
        c.execute("""UPDATE portal_scopes SET enabled=0,state='paused',updated=?
            WHERE id=?""",(time.time(),scope_id))
    elif action=='priority':
        level=int(priority)
        if not 0<=level<=90:raise ValueError('Priorität muss 0 bis 90 sein')
        c.execute('UPDATE portal_scopes SET priority=?,updated=? WHERE id=?',
                  (level,time.time(),scope_id))
    elif action=='remove':
        if r['state']=='running':raise ValueError('Laufenden Scan zunächst pausieren')
        c.execute('DELETE FROM portal_scopes WHERE id=?',(scope_id,))
    else:raise ValueError('Unbekannte Scanaktion')


def _claim(c):
    # BEGIN IMMEDIATE provides durable cross-thread claim without worker races.
    c.execute('BEGIN IMMEDIATE')
    r=c.execute("""SELECT id,source,kind,scope,cursor,pages_done,page_budget,
      imported,failures,enabled FROM portal_scopes WHERE enabled=1
      AND state IN ('queued','retry') AND next_try<=?
      AND source IN (SELECT source FROM portal_controls WHERE enabled=1)
      ORDER BY priority,next_try,id LIMIT 1""",(time.time(),)).fetchone()
    if not r:return None
    c.execute("""UPDATE portal_scopes SET state='running',updated=?
        WHERE id=?""",(time.time(),r['id']))
    return dict(r)


def archive_scope_query(scope):
    kind=scope['kind']
    if kind=='collection':return 'mediatype:movies AND collection:"'+scope['scope']+'"'
    if kind=='uploader':return 'mediatype:movies AND _uploader_useritem:"'+scope['scope']+'"'
    raise ValueError('Keine allgemeine unbeschränkte Suchanfrage erlaubt')


def fetch_scope_page(scope):
    if scope['kind']=='item':
        ident=scope['scope']
        detail=portals.fetch_archive_detail(ident)
        item=portals.entry('internet_archive',ident,detail['title'],detail['page_url'],
                           detail.get('year'),detail.get('description',''),
                           detail.get('license_url',''),detail.get('rights',''),
                           evidence='user_selected_archive_item')
        return [item],False,detail
    query=archive_scope_query(scope)
    page=int(scope['cursor'])
    params=[('q',query),('output','json'),('rows',str(PER_PAGE)),('page',str(page))]
    params.extend(('fl[]',field) for field in
                  ('identifier','title','year','date','description','language','licenseurl','rights'))
    url='https://archive.org/advancedsearch.php?'+urllib.parse.urlencode(params)
    with core.open_url(url,timeout=25) as response:
        data=response.read(portals.MAX_RESPONSE_BYTES+1)
    if len(data)>portals.MAX_RESPONSE_BYTES:raise ValueError('Archive.org-Suchantwort zu groß')
    document=json.loads(data)
    rows=portals.archive_document(document)
    raw=document.get('response',{}).get('docs',[])
    total=int(document.get('response',{}).get('numFound') or 0)
    more=page*PER_PAGE<total and len(raw)==PER_PAGE
    return rows,more,None


def finish(c,scope_id,rows,more,detail=None):
    r=c.execute('SELECT * FROM portal_scopes WHERE id=?',(scope_id,)).fetchone()
    if not r:return
    if rows:portals.save(c,rows)
    if detail and rows:portals.save_archive_detail(c,rows[0]['id'],detail)
    pages_done=r['pages_done']+1
    # The scan never runs past the page budget without another manual start.
    stop=(not more or pages_done>=r['page_budget'])
    state='paused' if not r['enabled'] else ('complete' if not more else 'paused' if stop else 'queued')
    c.execute("""UPDATE portal_scopes SET cursor=?,pages_done=?,imported=imported+?,
       state=?,enabled=?,last_success=?,last_error='',next_try=?,updated=?
       WHERE id=?""",(r['cursor']+int(bool(more)),pages_done,len(rows),state,
                      0 if stop else 1,time.time(),time.time()+2,time.time(),scope_id))


def failure(c,scope_id,error):
    r=c.execute('SELECT failures,enabled FROM portal_scopes WHERE id=?',(scope_id,)).fetchone()
    if not r:return
    count=r[0]+1
    pause=min(3600,30*2**min(count,7))
    c.execute("""UPDATE portal_scopes SET failures=?,state=?,
       next_try=?,last_error=?,updated=? WHERE id=?""",
       (count,'retry' if r['enabled'] else 'paused',time.time()+pause,
        type(error).__name__+': '+str(error)[:140],time.time(),scope_id))


class Scheduler:
    def __init__(self,db,stop):
        self.db=db
        self.stop=stop
        self.threads=[]

    def start(self):
        if self.threads:return
        for number in range(MAX_WORKERS):
            t=threading.Thread(target=self.loop,args=(number,),name='portal_metadata_'+str(number),
                               daemon=True)
            t.start();self.threads.append(t)

    def loop(self,number):
        while not self.stop.wait(1):
            with self.db() as c:
                status=source_status(c)
                archive=next((p for p in status['platforms']
                              if p['source']=='internet_archive'),None)
                slots=min(MAX_ARCHIVE_WORKERS,archive['workers'],
                          status['max_active_platforms']) if archive and archive['enabled'] else 0
                if number>=slots:continue
            with LOCK:
                if _ACTIVE['internet_archive']>=slots:continue
                _ACTIVE['internet_archive']+=1
            task=None
            try:
                with self.db() as c:task=_claim(c)
                if not task:continue
                # Cross-worker rate control; HTTPS queries are not concurrent bursts.
                with LOCK:
                    delay=max(0,2-(time.monotonic()-_LAST_FETCH['internet_archive']))
                    _LAST_FETCH['internet_archive']=time.monotonic()+delay
                if self.stop.wait(delay):break
                rows,more,detail=fetch_scope_page(task)
                with self.db() as c:finish(c,task['id'],rows,more,detail)
            except Exception as error:
                if task:
                    with self.db() as c:failure(c,task['id'],error)
            finally:
                with LOCK:_ACTIVE['internet_archive']-=1
