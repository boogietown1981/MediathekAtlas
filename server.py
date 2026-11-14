import subprocess,sys,tempfile,types
import json, os, secrets, signal, socketserver, sqlite3, threading, time, webbrowser, urllib.parse, hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import metadata,provider_stats,imdb_archive,artwork,negative_cache,http_timing,portal_title,job_queue,netcheck,task_control,ui_prefs,unified_index,portal_snapshot,download_quality,categories
import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment, netzkino_downloads, ytdl_bridge, pluto, pluto_downloads, pluto_enrichment, justwatch, justwatch_downloads, justwatch_enrichment, rakuten, rakuten_downloads, rakuten_enrichment, youtube, youtube_downloads, youtube_enrichment, live_tv, db_backup, archive_downloads, joyn, joyn_enrichment, toggo, toggo_enrichment,crunchyroll,crunchyroll_enrichment,samsung_tvplus, plex, plex_enrichment, servustv, servustv_enrichment, rtlplus, rtlplus_enrichment
import page_scripts,watch_state,storage_policy,archive_recognition,platform_registry,archive_selection,archive_uploaders,archive_transfer,archive_extras,encoder,archive_receipts,light_theme,system_monitor,planner,routing
from version import VERSION
from contextlib import contextmanager
ROOT=Path(os.environ.get('MEDIATHEKATLAS_HOME',Path.home()/'Library'/'Application Support'/'MediathekAtlas' if __import__('sys').platform=='darwin' else Path.home()/'.mediathekatlas'))
ROOT.mkdir(parents=True,exist_ok=True);os.chmod(ROOT,0o700)
# NAS packages listen on the LAN with a fixed port; that always requires a login.
LISTEN=os.environ.get('MEDIATHEKATLAS_LISTEN','127.0.0.1')
PORT=int(os.environ.get('MEDIATHEKATLAS_PORT','0') or 0)
NETWORK=LISTEN not in ('127.0.0.1','localhost','::1') or os.environ.get('MEDIATHEKATLAS_LOGIN')=='1'
MANAGED=os.environ.get('MEDIATHEKATLAS_MANAGED','')
def _default_download_dir():
    # 0.5.80: Windows and Linux name the video folder "Videos"; an existing ~/Movies keeps its role.
    home=Path.home()
    if __import__('sys').platform!='darwin' and not (home/'Movies').is_dir():return str(home/'Videos'/'MediathekAtlas')
    return str(home/'Movies'/'MediathekAtlas')
DEFAULT_DOWNLOAD_DIR=os.environ.get('MEDIATHEKATLAS_DOWNLOAD_DIR') or _default_download_dir()
SESSION_COOKIE='mediathekatlas_session'
INSTANCE=None
if __name__=='__main__':
    from instance import Instance
    INSTANCE=Instance(ROOT)
    if not INSTANCE.acquire():
        existing=INSTANCE.existing()
        if existing.get('url') and '--no-browser' not in __import__('sys').argv:webbrowser.open(existing['url'])
        print('MediathekAtlas läuft bereits. Bestehende Instanz verwenden bzw. dort „App beenden“ wählen.',flush=True)
        raise SystemExit(0)
diagnostics.setup(ROOT)
metadata.configure_provider_state(ROOT/'provider-pauses.json')
negative_cache.configure(ROOT/'provider-negative.sqlite')
diagnostics.event('application_start',version=VERSION,network=NETWORK,managed=MANAGED or None)
ACCESS=access.Access(ROOT,[DEFAULT_DOWNLOAD_DIR]) if NETWORK else None
TOKEN=secrets.token_urlsafe(32);STOP=threading.Event();PLANNER=[None]   # 0.6.0: the running planner (planner.py)
ROUTES=routing.Table()   # 0.6.1: every address with a fixed path (see the route table below Handler)
diagnostics.register_secrets(TOKEN)

def job_ids(q):
    """?id=<one> or ?ids=<a>,<b>,… (0.5.45 series pages, at most 1000 ids)."""
    ids=[x for x in ','.join(q.get('ids',[])).split(',') if x][:1000]
    return ids or q.get('id',[''])[0] or None


@contextmanager
def db():
    c=sqlite3.connect(ROOT/'catalog.db',timeout=30);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()
with db() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT);CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT);CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,payload TEXT);CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL);')
    catalog.initialize(c)
    subscriptions.initialize(c)
    portal_sources.initialize(c)
    portal_control.initialize(c)
    if not catalog.get_state(c,'legacy_imported',False):
        catalog.ingest(c,[json.loads(r[0]) for r in c.execute('SELECT payload FROM records').fetchall()])
        catalog.set_state(c,'legacy_imported',True)
    for completed in c.execute("SELECT payload FROM jobs WHERE state='done'").fetchall():
        done_job=json.loads(completed[0])
        # Time-limited Netzkino copies never mark Mediathek works as downloaded.
        if not netzkino_downloads.is_portal(done_job):catalog.mark_downloaded(c,done_job)
    catalog.recover_download_queue(c)

def settings():
    with db() as c:r=c.execute('SELECT payload FROM settings WHERE id=1').fetchone()
    stored=json.loads(r[0]) if r else {}
    diagnostics.register_secrets(stored.get('tmdb'),stored.get('omdb'),stored.get('youtube'),stored.get('tvdb'),stored.get('tvdb_pin'),stored.get('fanart'),stored.get('fanart_personal'),stored.get('mesh_key'),*[p['key'] for p in meshpeer.peer_list(stored)])
    return {'download_dir':DEFAULT_DOWNLOAD_DIR,'tmdb':'','omdb':'','youtube':'','tvdb':'','tvdb_pin':'','fanart':'','fanart_personal':'','auto_catalog':True,'auto_metadata':True,'scan_priority':'balanced','complete_series':True,'metadata_workers':2,'episode_workers':2,'sender_direct_lookup':False,'library_dirs':[],**stored,'imdb_generation':IMDB.updated if 'IMDB' in globals() else 0}

# 0.5.53: the YouTube catalogue reads the API key from the settings on each run (never cached on disk elsewhere).
youtube.configure(lambda:settings().get('youtube',''))

def record(i):
    with db() as c:
        found=catalog.source(c,i)
        if found:return found
        r=c.execute('SELECT payload FROM records WHERE id=?',(i,)).fetchone()
    if not r:raise ValueError('Eintrag nicht gefunden; Suche wiederholen')
    return json.loads(r[0])

def put_job(j):
    if j['state']=='done':netzkino_downloads.stamp(j)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(j['id'],json.dumps(j),j['state']))
        if j['state']=='queued':job_queue.supersede(c,j)
        if j['state']=='done' and not netzkino_downloads.is_portal(j):catalog.mark_downloaded(c,j)
    # 0.5.61: subtitle files listed in the Archive.org manifest go next to the finished video.
    if j['state']=='done' and j.get('origin')==archive_downloads.ORIGIN and j.get('sidecars') and not j.get('sidecars_fetched'):
        def subtitles(job=dict(j)):
            try:
                names=archive_downloads.fetch_sidecars(job)
                if names:diagnostics.event('archive_sidecars_saved',count=len(names))
            except Exception as e:diagnostics.error('archive_sidecars_failed',e)
        threading.Thread(target=subtitles,daemon=True,name='archive_sidecars').start()

def film_platforms(offline):
    # Film platforms with own catalogues (dashboard cards): catalogue, IMDb/TVDB check, offline copies.
    nk=netzkino.state(ROOT);pl=pluto.state(ROOT);jw=justwatch.state(ROOT);rk=rakuten.state(ROOT);yt=youtube.state(ROOT);jy=joyn.state(ROOT);tg=toggo.state(ROOT);cr=crunchyroll.state(ROOT);px=plex.state(ROOT);sv=servustv.state(ROOT);rp=rtlplus.state(ROOT)
    return [
        {'source':'netzkino','name':'Netzkino','titles':nk.get('catalog_count',0),'last_success':nk.get('last_success',0),
         'last_result':nk.get('last_result'),'running':nk.get('running'),'reference':netzkino_enrichment.metrics(ROOT),
         'offline':offline['netzkino'],'offline_days':netzkino_downloads.OFFLINE_DAYS},
        {'source':'pluto','name':'Pluto TV','titles':(pl.get('movies',0) or 0)+(pl.get('series',0) or 0),
         'channels':pl.get('channels',0),'last_success':pl.get('last_success',0),'last_result':pl.get('last_result'),
         'running':pl.get('running'),'reference':pluto_enrichment.metrics(ROOT),
         'offline':offline['pluto'],'offline_days':pluto_downloads.OFFLINE_DAYS},
        {'source':'justwatch','name':'JustWatch TV','titles':(jw.get('movies',0) or 0)+(jw.get('series',0) or 0),
         'playable':jw.get('playable',0),'last_success':jw.get('last_success',0),'last_result':jw.get('last_result'),
         'running':jw.get('running'),'reference':justwatch_enrichment.metrics(ROOT),
         'offline':offline['justwatch'],'offline_days':justwatch_downloads.OFFLINE_DAYS},
        {'source':'rakuten','name':'Rakuten TV','titles':(rk.get('movies',0) or 0)+(rk.get('series',0) or 0),
         'channels':rk.get('channels',0),'protected':rk.get('protected',0),'last_success':rk.get('last_success',0),'last_result':rk.get('last_result'),
         'running':rk.get('running'),'reference':rakuten_enrichment.metrics(ROOT),
         'offline':offline['rakuten'],'offline_days':rakuten_downloads.OFFLINE_DAYS},
        {'source':'joyn','name':'Joyn','titles':(jy.get('movies',0) or 0)+(jy.get('series',0) or 0),
         'channels':jy.get('channels',0),'plus':jy.get('plus',0),'protected':jy.get('protected',0),'last_success':jy.get('last_success',0),
         'last_result':jy.get('last_result'),'running':jy.get('running'),'reference':joyn_enrichment.metrics(ROOT),
         'offline':offline.get('joyn',{}),'offline_days':0},
        {'source':'toggo','name':'TOGGO','titles':(tg.get('movies',0) or 0)+(tg.get('series',0) or 0),'plus':tg.get('plus',0),
         'protected':tg.get('protected',0),'protection':tg.get('protection'),'last_success':tg.get('last_success',0),
         'last_result':tg.get('last_result'),'running':tg.get('running'),'reference':toggo_enrichment.metrics(ROOT),
         'offline':offline.get('toggo',{}),'offline_days':0,'offline_note':'TOGGO-Titel werden nicht offline gespeichert'},
        {'source':'crunchyroll','name':'Crunchyroll','titles':(cr.get('movies',0) or 0)+(cr.get('series',0) or 0),'plus':cr.get('plus',0),
         'protected':cr.get('protected',0),'protection':'drm','last_success':cr.get('last_success',0),
         'last_result':cr.get('last_result'),'running':cr.get('running'),'progress':cr.get('progress',''),'reference':crunchyroll_enrichment.metrics(ROOT),
         'offline':offline.get('crunchyroll',{}),'offline_days':0,'offline_note':'Crunchyroll-Titel werden nicht offline gespeichert (Kopierschutz, nur mit Abo)'},
        {'source':'plex','name':'Plex','titles':(px.get('movies',0) or 0)+(px.get('series',0) or 0),'channels':px.get('channels',0),
         'protected':px.get('protected',0),'last_success':px.get('last_success',0),'last_result':px.get('last_result'),
         'running':px.get('running'),'reference':plex_enrichment.metrics(ROOT),
         'offline':offline.get('plex',{}),'offline_days':0,'offline_note':'Plex-Titel werden nicht offline gespeichert'},
        {'source':'servustv','name':'ServusTV','titles':(sv.get('movies',0) or 0)+(sv.get('series',0) or 0),'channels':sv.get('channels',0),
         'last_success':sv.get('last_success',0),'last_result':sv.get('last_result'),
         'running':sv.get('running'),'reference':servustv_enrichment.metrics(ROOT),
         'offline':offline.get('servustv',{}),'offline_days':0,'offline_note':'ServusTV erlaubt Downloads nur in der eigenen App'},
        {'source':'rtlplus','name':'RTL+','titles':(rp.get('movies',0) or 0)+(rp.get('series',0) or 0),
         'protected':(rp.get('movies',0) or 0)+(rp.get('series',0) or 0),'protection':'drm','last_success':rp.get('last_success',0),
         'last_result':rp.get('last_result'),'running':rp.get('running'),'reference':rtlplus_enrichment.metrics(ROOT),
         'offline':offline.get('rtlplus',{}),'offline_days':0,'offline_note':'RTL+-Titel werden nicht offline gespeichert (Kopierschutz)'},
        {'source':'youtube','name':'YouTube','titles':(yt.get('movies',0) or 0)+(yt.get('series',0) or 0),
         'playable':yt.get('playable',0),'sources':yt.get('sources',0),'last_success':yt.get('last_success',0),
         'last_result':yt.get('last_result'),'running':yt.get('running'),'reference':youtube_enrichment.metrics(ROOT),
         'offline':offline['youtube'],'offline_days':youtube_downloads.OFFLINE_DAYS,
         'offline_note':yt.get('offline_note',''),'key_set':yt.get('key_set'),
         'music':yt.get('music',0),'tracks':yt.get('tracks',0),'progress':yt.get('progress','')}]

# 0.5.55: Verwaltung → Aufgaben. One list of all background tasks with what they are doing.
_PORTAL_MODULES=platform_registry.MODULES
_TASKS_CACHE=(float('-inf'),{})
def _portal_titles(key,state):
    if key=='netzkino':return int(state.get('catalog_count') or 0)
    return int(state.get('movies') or 0)+int(state.get('series') or 0)
def task_details():
    """Slow-ish numbers (one SQLite read per platform), cached for a few seconds."""
    global _TASKS_CACHE
    if time.monotonic()-_TASKS_CACHE[0]<4:return _TASKS_CACHE[1]
    out={}
    for key,(module,enrichment) in _PORTAL_MODULES.items():
        try:
            st=module.state(ROOT);titles=_portal_titles(key,st)
            out['catalog:'+key]={'running':bool(st.get('running')),'auto':bool(st.get('auto')),'titles':titles,
                'last_success':st.get('last_success') or 0,'next_attempt':st.get('next_attempt') or 0,
                'last_result':st.get('last_result') or '','last_error':st.get('last_error') or ''}
            checked=int((enrichment.metrics(ROOT) or {}).get('checked') or 0)
            out['enrich:'+key]={'checked':min(checked,titles) if titles else checked,'total':titles}
        except Exception as e:
            out['catalog:'+key]={'error':core.safe_error(e)}
    try:
        st=samsung_tvplus.state(ROOT)
        out['catalog:samsung']={'running':st['running'],'auto':st['auto'],'titles':st['channels'],'last_success':st['last_success'],
            'next_attempt':st['next_attempt'],'last_result':st['last_result'],'last_error':st['last_error']}
    except Exception as e:out['catalog:samsung']={'error':core.safe_error(e)}
    try:
        aw=archive_recognition.summary(ROOT);out['enrich:archive']={'checked':min(aw['checked'],aw['works']),'total':aw['works']}
    except Exception as e:out['enrich:archive']={'error':core.safe_error(e)}
    try:
        with db() as c:
            out['downloads']=job_queue.summary(c)
            out['filmlist']={'last_complete':catalog.get_state(c,'last_complete',0)}
    except Exception as e:out['downloads']={'error':core.safe_error(e)}
    _TASKS_CACHE=(time.monotonic(),out)
    return out
def tasks_overview():
    details=task_details();s=settings();current=SERVICE.current or {};rows=[]
    recognition=SERVICE.metadata_status or {}
    for row in task_control.overview():
        key=row['id'];d=dict(details.get(key) or {})
        if key=='filmlist':
            d.update(phase=current.get('phase') or 'waiting',auto=bool(s.get('auto_catalog',True)),
                     running=current.get('phase') in ('downloading','importing','reading','comparing'))
        elif key=='recognition':
            d.update(auto=bool(s.get('auto_metadata',True)),workers=int(s.get('metadata_workers',2) or 0),
                     last_title=recognition.get('title') or '',checked_session=recognition.get('checked_session') or 0)
        elif key=='episodes':
            d.update(auto=bool(s.get('auto_metadata',True)),workers=int(s.get('episode_workers',2) or 0))
        elif key=='imdb':
            st=IMDB.status();d.update(phase=st.get('phase') or '',updated=st.get('updated') or 0,next_update=st.get('next_update') or 0,
                                      running=st.get('phase') in ('downloading','importing','indexing'))
        elif key.startswith('enrich:'):
            d['auto']=bool(s.get('auto_metadata',True))
        row['detail']=d;rows.append(row)
    return {'tasks':rows,'priorities':[{'key':k,'label':task_control.PRIORITY_LABEL[k]} for k in task_control.PRIORITIES],
            'background':not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND')}
def task_action(task,action,value=None):
    global _TASKS_CACHE
    if action in ('pause_all','resume_all'):
        task_control.pause_all(action=='pause_all',str(value or '')[:40])
    elif action=='pause':task_control.set_paused(task,True)
    elif action=='resume':task_control.set_paused(task,False)
    elif action=='priority':task_control.set_priority(task,str(value or ''))
    elif action=='start':
        spec=task_control.TASKS.get(task)
        if not spec or 'start' not in spec['can']:raise ValueError('Diese Aufgabe lässt sich nicht von Hand starten')
        task_control.set_paused(task,False)   # an explicit start lifts the pause
        if task=='filmlist':SERVICE.restart.set();SERVICE.wake.set()
        elif task=='imdb':IMDB.request()
        elif spec.get('portal')=='samsung':samsung_tvplus.start_sync(ROOT)
        else:_PORTAL_MODULES[spec['portal']][0].start_sync(ROOT)
    else:raise ValueError('Unbekannte Aktion')
    if action in ('resume','resume_all','start'):
        for wake in ('metadata_wake','subscription_wake'):
            event=getattr(SERVICE,wake,None)
            if event is not None:event.set()
    _TASKS_CACHE=(float('-inf'),{})
    diagnostics.event('task_control',task=task if task in task_control.TASKS else '',action=action,value=str(value or '')[:20])
    return tasks_overview()
def live_tv_summary():
    try:
        with db() as c:return live_tv.summary(c,ROOT)
    except Exception as e:return {'error':core.safe_error(e)}

def netzkino_download_summary():
    with db() as c:return {**netzkino_downloads.summary(c),'pluto':netzkino_downloads.summary(c,'pluto'),'justwatch':netzkino_downloads.summary(c,'justwatch'),'rakuten':netzkino_downloads.summary(c,'rakuten'),'youtube':netzkino_downloads.summary(c,'youtube')}

def jobs():
    with db() as c:rows=c.execute('SELECT payload,state FROM jobs ORDER BY rowid DESC LIMIT 100').fetchall()
    result=[]
    for payload,state in rows:
        item={**json.loads(payload),'state':state}
        if state=='done':
            item['file_state']=local_library.file_state(item.get('path') or item.get('target'))
        result.append(item)
    return result

def worker():
    while not STOP.wait(.5):
        # 0.5.55: Verwaltung → Aufgaben can hold the queue; a running download is finished first.
        if task_control.paused('downloads'):continue
        with db() as c:
            j=job_queue.next_job(c)   # skips jobs reserved for later (not_before)
            if not j:continue
            if j.get('night'):
                # Night-only JustWatch title started outside 0-6 h (retry, Mac asleep at night): wait for the next window.
                later=justwatch.night_start()
                if later>time.time() and not justwatch_downloads.released(j):   # 0.5.76: released already (22/23 h) -> start now
                    j['not_before']=later;c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(j),j['id']));continue
            # Netzkino/Pluto offline copies are per device (time-limited licence): no Verbund claim/sharing.
            local_only=netzkino_downloads.is_portal(j)
            o=None if local_only else c.execute('SELECT work_id FROM offers WHERE id=?',(j.get('source',{}).get('_id'),)).fetchone()
            blocked=None if local_only else SERVICE.mesh_download_block(c,j['metadata'],o and o[0])
            if blocked:
                # Queued before the other instance's claim arrived (e.g. series packages).
                j.update(state='remote',note=blocked);c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?',(json.dumps(j),'remote',j['id']));continue
            c.execute("UPDATE jobs SET state='downloading' WHERE id=?",(j['id'],))
        def cancelled():
            with db() as c:x=c.execute('SELECT state FROM jobs WHERE id=?',(j['id'],)).fetchone()
            return not x or x[0]=='cancelled'
        claimed=[0.0]
        def update(state,received=0,total=0,**kw):
            if cancelled():return
            j.update(state=state,received=received,total=total,**kw);put_job(j)
            if not local_only and state!='done' and time.time()-claimed[0]>meshjournal.CLAIM_RENEW:
                claimed[0]=time.time();SERVICE.mesh_claim(j)
        try:
            if not local_only:claimed[0]=time.time();SERVICE.mesh_claim(j)
            if not all(j['metadata'].get(k) for k in ('poster','fanart')):
                pictures,errors=artwork.lookup(j['metadata'],settings())
                for field in ('poster','fanart','artwork_provider'):
                    if pictures.get(field) and not j['metadata'].get(field):j['metadata'][field]=pictures[field]
                if errors:diagnostics.event('download_artwork_warning',errors=errors)
            if not cancelled():downloads.run(j['source'],j['metadata'],j['root'],j['quality'],update,cancelled)
        except Exception as e:
            diagnostics.error('download_failed',e,job_id=j['id'])
            if not cancelled():j.update(state='error',error=core.safe_error(e));put_job(j)
        if j.get('state')=='done' and j.get('origin')==archive_downloads.ORIGIN:
            # 0.5.95: signed receipt with checksum for the Verbund; runs beside the queue, a large file takes a while to read.
            threading.Thread(target=archive_receipt,args=(dict(j),),daemon=True,name='archive_receipt').start()
        if j.get('state')=='done' and not local_only:
            try:SERVICE.mesh_done(j)
            except OSError as e:diagnostics.error('mesh_done_failed',e,job_id=j['id'])
        elif claimed[0]:SERVICE.mesh_release(j)

SERVICE=catalog_service.Service(db,settings,STOP,ROOT)
def encoder_tools():return {'ffmpeg':runtime_tools.resolve('ffmpeg'),'ffprobe':runtime_tools.resolve('ffprobe')}
RECEIPT_TASK={'running':False,'label':'','done':0,'total':0,'result':None}
RECEIPT_LOCK=threading.Lock()
def archive_receipt(job,converted=False):
    """0.5.95: measure a finished Archive.org download, sign its receipt and announce it to the Verbund."""
    try:
        data=archive_receipts.issue(ROOT,job,converted=converted,cancelled=STOP.is_set);SERVICE.mesh_receipts()
        diagnostics.event('archive_receipt_issued',source_check=data['source_check'] or 'none',converted=data['converted'],size_mb=round(data['stored_size']/1048576))
        return True
    except Exception as e:
        diagnostics.error('archive_receipt_failed',e);return False
def receipt_task(label,total,work):
    """One reading job at a time (creating missing receipts, re-checking a file): large files take minutes on a NAS."""
    with RECEIPT_LOCK:
        if RECEIPT_TASK['running']:raise ValueError('Es läuft bereits eine Prüfung. Bitte warten, bis sie fertig ist.')
        RECEIPT_TASK.update(running=True,label=label,done=0,total=total,result=None)
    def run():
        try:RECEIPT_TASK['result']=work(lambda:RECEIPT_TASK.__setitem__('done',RECEIPT_TASK['done']+1))
        except Exception as e:
            diagnostics.error('archive_receipt_task_failed',e);RECEIPT_TASK['result']={'state':'error','message':core.safe_error(e)}
        finally:RECEIPT_TASK['running']=False
    threading.Thread(target=run,daemon=True,name='archive_receipt_task').start()
def receipts_overview():
    with db() as c:pending=len(archive_receipts.missing(c,ROOT))
    return {**archive_receipts.overview(ROOT,SERVICE.mesh_names,pending,SERVICE.mesh_status.get('enabled') is True),'task':dict(RECEIPT_TASK)}
def encoder_replaced(job_id,old,new):
    """0.5.94: after a checked conversion replaced the original, the download points to the new file."""
    with db() as c:
        row=c.execute('SELECT payload FROM jobs WHERE id=?',(str(job_id),)).fetchone()
        if row:
            job=json.loads(row[0])
            for key in ('path','target'):
                if job.get(key)==old:job[key]=new
            job['encoded']={'at':time.time(),'from':Path(old).name}
            c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(job,ensure_ascii=False),str(job_id)))
            # 0.5.95: the receipt described the original; the converted file gets a new one, marked as converted.
            if job.get('origin')==archive_downloads.ORIGIN:threading.Thread(target=archive_receipt,args=(dict(job),True),daemon=True,name='archive_receipt').start()
    local_library.invalidate(old,new);catalog.invalidate_listings(drop=True);unified_index.invalidate()
ENCODER=encoder.Worker(ROOT,encoder_tools,encoder_replaced,diagnostics.event,diagnostics.error)
catalog.LISTING_DB=db
catalog.load_listings(ROOT/'listing-cache.json')   # 0.5.57: grouped lists of the last run, shown at once after a start
def _unified_built(key,index,seconds):
    # Only slow builds are worth a line; the per-source seconds show which source held it up.
    if seconds>=1.0 or index.get('errors'):
        diagnostics.event('unified_index_built',kind=key[1],search=bool(key[2]),seconds=round(seconds,2),sources=index.get('seconds'),
                          counts=index.get('counts'),pending=index.get('pending'),errors=index.get('errors'))
unified_index.ON_BUILD=_unified_built
portal_snapshot.configure(ROOT/'snapshots')
def _snapshot_stamp(status):
    # Changes when a catalogue run starts or ends; then the stored view is built anew.
    # 0.5.107: "Meine Abos" changes what RTL+ lists and how Crunchyroll labels it.
    prefs=ui_prefs.load(ROOT)
    return '|'.join(str(status.get(k) or '') for k in ('last_success','last_loaded','last_attempt','running'))+'|abo:%d%d'%(bool(prefs.get('abo_rtlplus')),bool(prefs.get('abo_crunchyroll')))
def platform_context():
    """What platform_registry needs from the running server (read at call time, tests swap ROOT)."""
    return types.SimpleNamespace(root=ROOT,db=db,settings=settings,slots=SERVICE.provider_slots,portal_page=portal_page,job_ids=job_ids)
def portal_page(source,module,q):
    """One catalogue page of a platform from its stored view (0.5.60, portal_snapshot)."""
    view=q.get('view',['movies'])[0][:20];args=dict(query=q.get('q',[''])[0],genre=q.get('genre',[''])[0][:80],
        sort=q.get('sort',['title'])[0],collection=q.get('collection',[''])[0][:20])
    status=portal_snapshot.status(source,lambda:module.state(ROOT))
    if view not in ('movies','series'):   # live channels and anything else: read directly
        data=module.listing(ROOT,view=view,offset=q.get('offset',['0'])[0],limit=q.get('limit',['60'])[0],**args)
    else:
        data=portal_snapshot.page(source,view,lambda:module.listing(ROOT,view=view,offset=0,limit='all',**args),
            stamp=_snapshot_stamp(status),offset=q.get('offset',['0'])[0],limit=q.get('limit',['60'])[0],**args)
    data['status']=status
    return data
class _SnapshotSource:
    """The merged dashboard index reads the platforms through their stored views as well."""
    def __init__(self,source,module):self.source=source;self.module=module
    def _stamp(self):
        try:return _snapshot_stamp(portal_snapshot.status(self.source,lambda:self.module.state(ROOT)))
        except Exception:return ''
    def listing(self,root,view='movies',query='',offset=0,limit='all',genre='',sort='title',collection=''):
        return portal_snapshot.page(self.source,view,lambda:self.module.listing(ROOT,view=view,query=query,offset=0,limit='all',genre=genre,sort=sort,collection=collection),
            stamp=self._stamp(),query=query,genre=genre,sort=sort,collection=collection,offset=0,limit='all')
    def grouped_catalog(self,root,view='movies',series_key='',query='',origin='all',offset=0,limit='all',genre='',sort='title',collection=''):
        return portal_snapshot.page(self.source,view,lambda:self.module.grouped_catalog(ROOT,view=view,series_key='',query=query,origin='all',offset=0,limit='all',genre=genre,sort=sort,collection=collection),
            stamp=self._stamp(),query=query,genre=genre,sort=sort,collection=collection,offset=0,limit='all')
_CLIENT_ERRORS=[0]
_PLAYBACK_STATS=[0]
task_control.configure(ROOT/'task-control.json')
def imdb_updated():
    with db() as c:
        c.execute("UPDATE works SET next_try=0,state=CASE WHEN state='review' THEN 'retry' ELSE state END WHERE state IN ('pending','retry','identified','review')")
        c.execute('DELETE FROM metadata_cache')
    SERVICE.metadata_wake.set()
IMDB=imdb_archive.Archive(ROOT,STOP,imdb_updated)
imdb_archive.ACTIVE=IMDB
_UNIFIED_SOURCES={k:_SnapshotSource(k,m[0]) for k,m in _PORTAL_MODULES.items()}
_STATUS_CACHE=(0,{})
_TREE_CACHE=(float('-inf'),[],[])
_TREE_TTL=60
_TREE_LOCK=threading.Lock()
_TREE_BUSY=False
_TREE_ERROR=''
def catalog_tree():
    global _TREE_BUSY
    with _TREE_LOCK:
        if not _TREE_BUSY and time.monotonic()-_TREE_CACHE[0]>_TREE_TTL:
            _TREE_BUSY=True
            threading.Thread(target=refresh_tree,daemon=True,name='catalog_categories').start()
        # 0.5.83: 'categories' = fixed German categories for the shared catalogue; 'tree' = raw genres
        # for Verwaltung → Werkkatalog (classic tree in the fold-out area).
        return {'tree':_TREE_CACHE[1],'categories':_TREE_CACHE[2],'loading':_TREE_BUSY,'error':_TREE_ERROR,
                **categories.describe()}
def refresh_tree():
    global _TREE_CACHE,_TREE_BUSY,_TREE_ERROR,_TREE_TTL
    started=time.monotonic()
    try:
        with db() as c:rows=catalog.tree(c);fixed=catalog.category_tree(c)
        seconds=time.monotonic()-started
        # The UI polls every 30 s; a 4 s aggregation every minute kept a core busy. Slow catalogues refresh
        # less often, user edits still invalidate the cache immediately.
        with _TREE_LOCK:_TREE_CACHE=(time.monotonic(),rows,fixed);_TREE_ERROR='';_TREE_TTL=max(60,min(900,seconds*60))
        diagnostics.event('catalog_tree_complete',seconds=round(seconds,2),categories=len(rows),next_seconds=round(_TREE_TTL))
    except Exception as e:
        diagnostics.error('catalog_tree_failed',e)
        with _TREE_LOCK:_TREE_ERROR=core.safe_error(e);_TREE_CACHE=(time.monotonic(),_TREE_CACHE[1],_TREE_CACHE[2])
    finally:
        with _TREE_LOCK:_TREE_BUSY=False
_RECOGNITION={'at':float('-inf'),'rows':[],'busy':False,'error':''}
def recognition():
    # Grouping 700k works by channel takes seconds; compute in the background and reuse for 10 minutes.
    with _TREE_LOCK:
        if not _RECOGNITION['busy'] and time.monotonic()-_RECOGNITION['at']>600:
            _RECOGNITION['busy']=True;threading.Thread(target=refresh_recognition,daemon=True,name='catalog_recognition').start()
        return {'channels':_RECOGNITION['rows'],'kinds':catalog.recognition_totals(_RECOGNITION['rows']),'loading':_RECOGNITION['busy'],'error':_RECOGNITION['error']}
def refresh_recognition():
    try:
        with db() as c:rows=catalog.recognition(c)
        with _TREE_LOCK:_RECOGNITION.update(at=time.monotonic(),rows=rows,error='')
    except Exception as e:
        diagnostics.error('catalog_recognition_failed',e)
        with _TREE_LOCK:_RECOGNITION.update(at=time.monotonic(),error=core.safe_error(e))
    finally:
        with _TREE_LOCK:_RECOGNITION['busy']=False
def catalog_status():
    global _STATUS_CACHE
    snapshot=_STATUS_CACHE
    if not snapshot[1] or time.monotonic()-snapshot[0]>10:
        with db() as c:snapshot=(time.monotonic(),catalog.stats(c))
        _STATUS_CACHE=snapshot
    # A concurrent metadata save can invalidate the shared cache at any point.
    # Return our complete local snapshot, never the newly emptied shared cache.
    scan=SERVICE.scan_progress() if hasattr(SERVICE,'scan_progress') else {}
    left=snapshot[1].get('first_pass_remaining',0)
    rpm=scan.get('first_pass_per_minute',0)
    return {**snapshot[1],**scan,'first_pass_eta_hours':round(left/rpm/60,1) if rpm>0 else None,
            'sync':SERVICE.current or snapshot[1].get('sync',{})}

def downloads_range(header,size):
    """Single byte range from a Range header: None for the whole file, 'invalid' when unsatisfiable."""
    if not header:return None
    unit,_,spec=header.partition('=')
    if unit.strip().lower()!='bytes' or ',' in spec or '-' not in spec:return None
    first,_,last=spec.strip().partition('-')
    try:
        if not first:
            n=int(last)
            if n<=0:return 'invalid'
            return (max(0,size-n),size-1)
        start=int(first);end=int(last) if last else size-1
    except ValueError:return None
    if start>=size or end<start:return 'invalid'
    return (start,min(end,size-1))

def _play_quality(q):
    """Quality wish of the player from the query: 'auto', 'max' or a picture height."""
    wish=str((q.get('q') or q.get('quality') or ['auto'])[0] or 'auto').strip().lower()
    return wish if wish in ('auto','max') or (wish.isdigit() and len(wish)<=4) else 'auto'
def _unlink(path):
    if path:
        try:Path(path).unlink()
        except OSError:pass

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,data,status=200,ctype='application/json',cookies=()):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
        for header in cookies:self.send_header('Set-Cookie',header)
        self.end_headers();self.wfile.write(body)
    # Desktop mode trusts only its loopback Host (DNS-rebinding guard). Network mode
    # accepts any NAS name or address but requires a session cookie instead.
    def valid_host(self):return NETWORK or self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def session(self):return access.cookie_token(self.headers.get('Cookie'),SESSION_COOKIE)
    def authorized(self):return not NETWORK or ACCESS.valid(self.session())
    def session_cookie(self,token,seconds=access.SESSION_SECONDS):
        return f'{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={seconds}'
    def timed(self,method,run):
        # 0.5.41: running and slow requests become visible in the diagnostics export.
        key=http_timing.start(method,self.path)
        try:return run()
        finally:http_timing.finish(key,log=lambda path,seconds,m:diagnostics.event('http_slow_request',endpoint=path,seconds=seconds,method=m))
    def do_GET(self):return self.timed('GET',self.get_guarded)
    def do_POST(self):return self.timed('POST',self.post)
    def get_guarded(self):
        try:self.get()
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            diagnostics.error('http_get_failed',e,endpoint=urllib.parse.urlsplit(self.path).path)
            try:self.send({'error':core.safe_error(e)},500)
            except (BrokenPipeError,ConnectionResetError):pass
    def get(self):
        if not self.valid_host():return self.send({'error':'Ungültiger Host'},403)
        path=urllib.parse.urlsplit(self.path).path
        # 0.6.1: routes with a fixed address live in the route table below (routing.py); stage 'open'
        handler=ROUTES.find('GET',path,'open')
        if handler:return handler(self,path)
        if path.startswith('/api/peer/'):return self.peer_get(path)
        if not self.authorized():
            if path=='/':return self.send((Path(__file__).parent/'web'/'login.html').read_text().replace('__VERSION__',VERSION).encode(),ctype='text/html; charset=utf-8')
            return self.send({'error':'Anmeldung erforderlich','login':True},401)
        # 0.6.1: routes with a fixed address live in the route table below (routing.py); stage 'signed'
        handler=ROUTES.find('GET',path,'signed')
        if handler:return handler(self,path)
        if path in SCRIPTS:return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')
        # 0.5.73: second address for the page's own scripts; app.js reloads a script here when its first request failed
        if path.startswith('/code/'):
            # '~' + the name backwards: an address without the file's name, for filters that block by name
            name=path[7:][::-1] if path[6:7]=='~' else path[6:]
            if '/'+name+'.js' in SCRIPTS:return self.send((Path(__file__).parent/'web'/(name+'.js')).read_bytes(),ctype='text/javascript')
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Sitzung abgelaufen'},403)
        # 0.6.1: routes with a fixed address live in the route table below (routing.py); stage 'api'
        handler=ROUTES.find('GET',path,'api')
        if handler:return handler(self,path)
        if path.startswith('/api/'):
            # 0.5.84: catalogue page, details and offline list of every film platform (platform_registry).
            hit=platform_registry.handle_get(platform_context(),path,urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            if hit is not None:return self.send(*hit)
        self.send({'error':'Nicht gefunden'},404)
    # Finished downloads are served over HTTP so a browser on another device can fetch them;
    # on a NAS the local "open" action cannot reach the viewer's computer. Links carry the page
    # token in the query because a plain <a download> cannot send headers.
    def download_file(self,q):
        if not secrets.compare_digest(q.get('token',[''])[0],TOKEN):return self.send({'error':'Sitzung abgelaufen'},403)
        with db() as c:row=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(q.get('id',[''])[0],)).fetchone()
        if not row:return self.send({'error':'Nur abgeschlossene Downloads können geladen werden'},404)
        job=json.loads(row[0]);target=Path(job.get('path') or job['target']).resolve()
        if not target.is_file():return self.send({'error':'Datei wurde verschoben oder ist nicht verfügbar'},404)
        inline=q.get('inline',['0'])[0]=='1'
        # 30-day Netzkino copies: playback yes, copying to other devices no (expiry could not follow).
        if not inline and netzkino_downloads.is_offline(job):return self.send({'error':'Netzkino- und Pluto-Offlinekopien können nur in MediathekAtlas abgespielt werden'},403)
        self.send_file(target,inline)
    def send_file(self,target,inline):
        size=target.stat().st_size;start,end=0,size-1;status=200
        span=downloads_range(self.headers.get('Range'),size)
        if span=='invalid':
            self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
        if span:start,end=span;status=206
        ctype={'.mkv':'video/x-matroska','.mp4':'video/mp4','.m4v':'video/mp4','.webm':'video/webm','.mp3':'audio/mpeg','.m4a':'audio/mp4'}.get(target.suffix.lower(),'application/octet-stream')
        ascii_name=''.join(ch if 32<=ord(ch)<127 and ch not in '"\\' else '_' for ch in target.name)
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Disposition',f'{"inline" if inline else "attachment"}; filename="{ascii_name}"; filename*=UTF-8\'\'{urllib.parse.quote(target.name)}')
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.end_headers()
        if self.command=='HEAD':return
        with target.open('rb') as f:
            f.seek(start);left=end-start+1
            while left>0:
                chunk=f.read(min(1048576,left))
                if not chunk:break
                self.wfile.write(chunk);left-=len(chunk)
    # Playback for the in-app player. Like download-file, the page token travels in the query
    # because a <video> element cannot send headers. Sources come from the database only.
    def stream(self,q):
        if not secrets.compare_digest(q.get('token',[''])[0],TOKEN):return self.send({'error':'Sitzung abgelaufen'},403)
        try:
            with db() as c:source=streaming.resolve(c,offer=q.get('offer',[''])[0],job=q.get('job',[''])[0],
                                                  netzkino=q.get('netzkino',[''])[0],pluto=q.get('pluto',[''])[0],
                                                  justwatch=q.get('justwatch',[''])[0],rakuten=q.get('rakuten',[''])[0],joyn=q.get('joyn',[''])[0],toggo=q.get('toggo',[''])[0],crunchyroll=q.get('crunchyroll',[''])[0],samsung=q.get('samsung',[''])[0],plex=q.get('plex',[''])[0],servustv=q.get('servustv',[''])[0],rtlplus=q.get('rtlplus',[''])[0],root=ROOT,quality=_play_quality(q),
                                                  youtube=q.get('youtube',[''])[0])
        except ValueError as e:return self.send({'error':str(e)},404)
        if q.get('raw',['0'])[0]=='1':
            if source['kind']!='file':return self.send({'error':'Nur lokale Dateien können direkt geladen werden'},400)
            return self.send_file(Path(source['path']).resolve(),True)
        if self.command=='HEAD':return self.send(b'',ctype='video/mp4')
        try:start=max(0.0,float(q.get('t',['0'])[0] or 0))
        except ValueError:start=0.0
        # 0.5.63: ffmpeg gets one quality level instead of the whole master playlist (starts sooner,
        # loads what the connection carries). Without a list (no levels, provider not reachable) as before.
        began=time.monotonic();playlist,level=streaming.prepare(source,_play_quality(q),ROOT/'runtime'/'streams')
        try:
            proc=streaming.start(streaming.command(source,start,streaming.audio_copy(source),playlist=playlist),q.get('session',[''])[0][:64],cleanup=playlist)
        except RuntimeError as e:
            _unlink(playlist);return self.send({'error':str(e)},429)
        except (ValueError,OSError) as e:
            _unlink(playlist);return self.send({'error':core.safe_error(e)},503)
        sent=0;first_after=None
        try:
            first=proc.stdout.read1(65536) if hasattr(proc.stdout,'read1') else proc.stdout.read(65536)
            if not first:
                code,err=streaming.finish(proc)
                diagnostics.event('playback_failed',level='ERROR',origin=source['kind'],code=code,detail=err)
                return self.send({'error':'Wiedergabe konnte nicht gestartet werden. Details im Live-Protokoll.'},502)
            first_after=round(time.monotonic()-began,2)
            self.send_response(200);self.send_header('Content-Type','video/mp4');self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close');self.end_headers()
            chunk=first
            while chunk:
                self.wfile.write(chunk);sent+=len(chunk)
                chunk=proc.stdout.read1(65536) if hasattr(proc.stdout,'read1') else proc.stdout.read(65536)
        except (BrokenPipeError,ConnectionResetError):pass
        finally:
            if proc.poll() is None:streaming.finish(proc)
            else:
                code,err=streaming.finish(proc)
                if code:diagnostics.event('playback_interrupted',level='WARNING',origin=source['kind'],code=code,sent=sent,detail=err)
            if first_after is not None:
                seconds=round(time.monotonic()-began,1)
                # one line per stream for the diagnosis: how long until the first data, how much, at which level
                diagnostics.event('playback_stream',origin=source['kind'],provider=source.get('provider','mediathek'),live=bool(source.get('live')),
                                  start_at=round(start,1),first_data_seconds=first_after,seconds=seconds,megabytes=round(sent/1048576,1),
                                  kbit=round(sent*8/1000/seconds) if seconds>=1 else 0,quality_level=(level or {}).get('label',''),levels=(level or {}).get('levels',0))
    def do_HEAD(self):
        path=urllib.parse.urlsplit(self.path).path
        if path!='/api/download-file' or not self.valid_host() or not self.authorized():return self.send({'error':'Nicht gefunden'},404)
        try:self.download_file(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
        except (BrokenPipeError,ConnectionResetError):pass
    # Direct Verbund connection (meshpeer): another instance mirrors the journal files.
    # Authenticated by the shared Verbund key instead of a browser session.
    def peer_journal(self):
        key=settings().get('mesh_key')
        if not meshpeer.valid_key(key) or not secrets.compare_digest(self.headers.get(meshpeer.KEY_HEADER,''),key):
            self.send({'error':'Verbund-Schlüssel ungültig'},403);return None
        journal=SERVICE.mesh
        if journal is None:
            reason=SERVICE.mesh_status.get('error')
            self.send({'error':'Verbund auf der Gegenstelle nicht aktiv: '+reason+' (dort unter Verbund den Verbundordner leeren oder korrigieren)' if reason else 'Verbund auf der Gegenstelle startet gerade, bitte kurz warten'},503);return None
        return journal
    def peer_get(self,path):
        journal=self.peer_journal()
        if journal is None:return
        if path=='/api/peer/index':
            return self.send({'format':meshjournal.FORMAT,'node':journal.node,'name':journal.name,'version':VERSION,'files':meshpeer.index(journal.root)})
        if path=='/api/peer/file':
            rel=meshpeer.safe_path(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('path',[''])[0])
            target=Path(journal.root)/rel if rel else None
            if not target or not target.is_file():return self.send({'error':'Nicht gefunden'},404)
            return self.send(target.read_bytes(),ctype='application/octet-stream')
        self.send({'error':'Nicht gefunden'},404)
    def do_PUT(self):
        try:
            path=urllib.parse.urlsplit(self.path).path
            if path!='/api/peer/file' or not self.valid_host():return self.send({'error':'Nicht gefunden'},404)
            journal=self.peer_journal()
            if journal is None:return
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=meshpeer.MAX_FILE:return self.send({'error':'Ungültige Größe'},413)
            data=self.rfile.read(length)
            try:mtime=int(q.get('mtime',['0'])[0]) or None
            except ValueError:mtime=None
            stored=meshpeer.store(journal.root,journal.node,q.get('path',[''])[0],data,mtime)
            return self.send({'ok':True,'stored':bool(stored)})
        except meshpeer.PeerError as e:return self.send({'error':str(e)},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            diagnostics.error('peer_put_failed',e)
            try:self.send({'error':core.safe_error(e)},500)
            except (BrokenPipeError,ConnectionResetError):pass
    def archive_list_import(self):
        """0.5.92: a list file of another installation (ZIP body, not JSON). Adds unknown uploads only."""
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=archive_transfer.MAX_UPLOAD:raise ValueError('Die Liste ist leer oder zu groß')
            with tempfile.TemporaryDirectory(prefix='atlas-list-') as folder:
                target=Path(folder)/'liste.zip';left=length
                with target.open('wb') as out:
                    while left>0:
                        part=self.rfile.read(min(1048576,left))
                        if not part:raise ValueError('Die Übertragung der Liste wurde unterbrochen')
                        out.write(part);left-=len(part)
                with db() as c:result=archive_transfer.load(c,target)
            diagnostics.event('archive_list_imported',items=result['items'],added=result['added'])
            return self.send(result)
        except ValueError as e:return self.send({'error':str(e)},400)
        except Exception as e:
            diagnostics.error('archive_list_import_failed',e)
            return self.send({'error':core.safe_error(e)},500)
    def post(self):
        global _TREE_CACHE,_STATUS_CACHE
        if not self.valid_host():return self.send({'error':'Ungültige Sitzung'},403)
        if NETWORK and self.path=='/api/login':return self.login()
        if not self.authorized():return self.send({'error':'Anmeldung erforderlich','login':True},401)
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Ungültige Sitzung'},403)
        if self.path=='/api/archive-list-import':return self.archive_list_import()
        try:
            length=int(self.headers.get('Content-Length','0'))
            # Netzkino recordings arrive in parts of a few MB (answer texts only, no headers).
            if not 0<length<=(8*1024*1024 if self.path=='/api/netzkino-recording' else 100000):raise ValueError('Ungültige Anfragegröße')
            d=json.loads(self.rfile.read(length));path=self.path
            for source in platform_registry.KEYS:
                # 0.5.60: a change of the user is visible at once; otherwise the stored view answers.
                if path.startswith('/api/'+source+'-'):portal_snapshot.invalidate(source);break
            if path in ('/api/save-metadata','/api/review','/api/search'):
                # 0.5.55: manual changes must show at once; grouped pages are otherwise served from memory.
                catalog.invalidate_listings(drop=True);unified_index.invalidate()
            if NETWORK and path=='/api/logout':
                ACCESS.logout(self.session());return self.send({'ok':True},cookies=[self.session_cookie('',0)])
            if NETWORK and path=='/api/password':
                token=ACCESS.change_password(str(d.get('current','')),str(d.get('new','')))
                diagnostics.event('access_password_changed')
                return self.send({'ok':True},cookies=[self.session_cookie(token)])
            # 0.5.84: catalogue run, daily switch, reference check and offline download of every film platform.
            hit=platform_registry.handle_post(platform_context(),path,d)
            if hit is not None:return self.send(hit)
            # 0.6.1: routes with a fixed address live in the route table below (routing.py); stage 'api'
            handler=ROUTES.find('POST',path,'api')
            if handler:return handler(self,path,d)
            self.send({'error':'Nicht gefunden'},404)
        except Exception as e:
            diagnostics.error('http_post_failed',e,endpoint=urllib.parse.urlsplit(self.path).path)
            self.send({'error':core.safe_error(e)},400)

    def login(self):
        client=self.client_address[0]
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=10000:raise ValueError('Ungültige Anfragegröße')
            d=json.loads(self.rfile.read(length))
            token=ACCESS.login(client,str(d.get('password','')),str(d.get('setup_code','')),str(d.get('new_password','')))
        except PermissionError as e:
            diagnostics.event('access_login_blocked');return self.send({'error':str(e)},429)
        except (ValueError,TypeError,AttributeError) as e:
            diagnostics.event('access_login_failed');return self.send({'error':str(e) if isinstance(e,ValueError) else 'Ungültige Anfrage'},403)
        diagnostics.event('access_login');return self.send({'ok':True},cookies=[self.session_cookie(token)])

# ----------------------------------------------------------------------------------------------------
# 0.6.1: route table. Every address with a fixed path is one function, registered with its method and
# stage ('open' = before the login, 'signed' = after the login without the page token in a header,
# 'api' = with the page token). Handler.get/post look the path up at the place where the chain of
# `if path==...` used to stand for that stage; prefixes, the platform registry and requests that
# need the raw body stay in Handler. GET handlers take (self,path), POST handlers (self,path,d).
# ----------------------------------------------------------------------------------------------------

@ROUTES.get('/icon.svg',stage='open')
def get_icon_svg(self,path):
    return self.send((Path(__file__).parent/'assets'/'icon.svg').read_bytes(),ctype='image/svg+xml')

@ROUTES.get('/theme-light.css',stage='open')
def get_theme_light_css(self,path):
    # 0.5.99: the light design, computed from style.css (light_theme.py); applies only with data-theme="light"
    return self.send(light_theme.sheet(Path(__file__).parent/'web'/'style.css'),ctype='text/css')

@ROUTES.get('/style.css','/login.js',stage='open')
def get_style_css(self,path):
    return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript' if path.endswith('js') else 'text/css')

@ROUTES.get('/api/login-state',stage='open')
def get_login_state(self,path):
    if not NETWORK:return self.send({'required':False})
    return self.send({'required':True,'configured':ACCESS.configured(),'setup_files':ACCESS.ensure_setup_code() if not ACCESS.configured() else []})

@ROUTES.get('/',stage='signed')
def get_index(self,path):
    body=page_scripts.inline_scripts((Path(__file__).parent/'web'/'index.html').read_text(encoding='utf-8'),Path(__file__).parent/'web',SCRIPTS).replace('__TOKEN__',TOKEN).replace('__VERSION__',VERSION)
    return self.send(body.encode(),ctype='text/html; charset=utf-8')

# 0.5.68: hls.js (Apache-2.0, web/hls.LICENSE.txt) plays HLS in the browser the way the providers' own sites do
@ROUTES.get('/hls.min.js',stage='signed')
def get_hls_min_js(self,path):
    return self.send((Path(__file__).parent/'web'/'hls.min.js').read_bytes(),ctype='text/javascript')

@ROUTES.get('/titleview.js',stage='signed')
def get_titleview_js(self,path):
    return self.send((Path(__file__).parent/'web'/'titleview.js').read_bytes(),ctype='text/javascript')

@ROUTES.get('/api/download-file',stage='signed')
def get_download_file(self,path):
    return self.download_file(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))

@ROUTES.get('/api/stream',stage='signed')
def get_stream(self,path):
    return self.stream(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))

@ROUTES.get('/api/video-audit')
def get_video_audit(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:
        video_backfill.initialize(c)
        return self.send(video_backfill.status(c,q.get('offset',['0'])[0]))

# 0.5.91: optionale Chrome-Erweiterung für den Videostart bei Anbietern mit Kopierschutz
@ROUTES.get('/api/browser-extension')
def get_browser_extension(self,path):
    return self.send(__import__('browser_extension').package(VERSION),ctype='application/zip')

@ROUTES.get('/api/live-tv')
def get_live_tv(self,path):
    # 0.5.50: live channels of all sources, merged by station (web/live_tv.js).
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    began=time.monotonic()
    with db() as c:data=live_tv.overview(c,ROOT,query=q.get('q',[''])[0][:100],
                                         provider=q.get('provider',[''])[0][:20],group=q.get('group',[''])[0][:120])
    try:data['pluto']=pluto.state(ROOT)
    except Exception:data['pluto']={}   # 0.5.67: a busy Pluto database must not hold back the stations
    try:data['samsung']=samsung_tvplus.state(ROOT)   # 0.5.97: hint and load button in the tab
    except Exception:data['samsung']={}
    # 0.5.63 (Björn, 12.11.2026: the Live-TV tab showed no stations with 0.5.61 although the
    # platforms still played them): an empty or slow answer leaves a line in the diagnosis.
    took=round(time.monotonic()-began,2)
    # 0.5.80 (Björn's diagnosis 0.5.72: dozens of "total 0, filtered" warnings): the live strip of a
    # platform asks for its own provider, and a provider without channels (Joyn before its first
    # complete catalogue run) correctly answers 0. Only a real problem is reported now.
    if live_tv.overview_problem(data,took,query=q.get('q',[''])[0],provider=q.get('provider',[''])[0],group=q.get('group',[''])[0]):
        diagnostics.event('live_tv_overview',level='WARNING',total=data['total'],seconds=took,filtered=bool(q.get('q',[''])[0] or q.get('provider',[''])[0] or q.get('group',[''])[0]),
                          provider=q.get('provider',[''])[0][:20],group_set=bool(q.get('group',[''])[0]),query_set=bool(q.get('q',[''])[0]),
                          providers={p['key']:p['channels'] for p in data['providers']},errors={p['key']:p['error'] for p in data['providers'] if p['error']})
    return self.send(data)

@ROUTES.get('/api/samsung')
def get_samsung(self,path):
    return self.send(samsung_tvplus.state(ROOT))   # 0.5.97: live channels only

@ROUTES.get('/api/netzkino-details')
def get_netzkino_details(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    return self.send(netzkino_details.get(ROOT,q.get('id',[''])[0]))

@ROUTES.get('/api/youtube')
def get_youtube(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    try:
        if q.get('view',[''])[0]=='episodes':data=youtube.episodes(ROOT,q.get('series',[''])[0])
        elif q.get('view',[''])[0]=='tracks':data=youtube.tracks(ROOT,q.get('album',[''])[0])   # 0.5.71 music playlist
        elif q.get('doubtful',['0'])[0]=='1':
            # YouTube thread: uploads sorted out as advertising can be shown on request (read directly).
            data=youtube.listing(ROOT,view=q.get('view',['movies'])[0],query=q.get('q',[''])[0],
                                  offset=q.get('offset',['0'])[0],limit=q.get('limit',['60'])[0],
                                  genre=q.get('genre',[''])[0][:80],sort=q.get('sort',['title'])[0],
                                  collection=q.get('collection',[''])[0][:20],show_doubtful=True)
        else:return self.send(portal_page('youtube',youtube,q))
    except ValueError as e:return self.send({'error':str(e)},404)
    data['status']=portal_snapshot.status('youtube',lambda:youtube.state(ROOT))
    return self.send(data)

@ROUTES.get('/api/youtube-sources')
def get_youtube_sources(self,path):
    return self.send({'sources':youtube.sources(ROOT),'status':youtube.state(ROOT),'offline':youtube_downloads.status(ROOT)})

@ROUTES.get('/api/portal-title')
def get_portal_title(self,path):
    # 0.5.42: one title page model for Netzkino, Pluto TV and JustWatch TV.
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    try:return self.send(portal_title.model(ROOT,q.get('source',[''])[0],q.get('id',[''])[0]))
    except ValueError as e:return self.send({'error':str(e)},404)

@ROUTES.get('/api/netzkino-downloads')
def get_netzkino_downloads(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:result=netzkino_downloads.listing(c,item_id=job_ids(q))
    result['ytdl']=ytdl_bridge.status()
    return self.send(result)

@ROUTES.get('/api/netzkino-reference-report')
def get_netzkino_reference_report(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    return self.send(netzkino_enrichment.cached(ROOT,q.get('id',[''])[0]))

@ROUTES.get('/api/netzkino-grouped')
def get_netzkino_grouped(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    view=q.get('view',['movies'])[0];series_key=q.get('series_key',[''])[0];origin=q.get('origin',['all'])[0]
    args=dict(query=q.get('q',[''])[0],genre=q.get('genre',[''])[0],sort=q.get('sort',['updated'])[0],collection=q.get('collection',[''])[0][:20])
    if series_key or origin!='all' or view not in ('movies','series'):
        data=netzkino.grouped_catalog(ROOT,view=view,series_key=series_key,origin=origin,
            offset=q.get('offset',['0'])[0],limit=q.get('limit',['80'])[0],**args)
        data['status']=portal_snapshot.status('netzkino',lambda:netzkino.state(ROOT))
        return self.send(data)
    # 0.5.60: films and series come from the stored view (portal_snapshot).
    status=portal_snapshot.status('netzkino',lambda:netzkino.state(ROOT))
    try:limit=max(1,min(100,int(q.get('limit',['80'])[0])))
    except ValueError:limit=80
    data=portal_snapshot.page('netzkino',view,lambda:netzkino.grouped_catalog(ROOT,view=view,series_key='',origin='all',offset=0,limit='all',**args),
        stamp=_snapshot_stamp(status),offset=q.get('offset',['0'])[0],limit=limit,**args)
    data['limit']=limit
    data['status']=status
    return self.send(data)

@ROUTES.get('/api/netzkino')
def get_netzkino(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0],80,q.get('offset',['0'])[0]),'status':netzkino.state(ROOT),'total':netzkino.count_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0])})

@ROUTES.get('/api/download-options')
def get_download_options(self,path):
    # 0.5.63: quality levels of one offer for the dialogue before an offline copy
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);source=q.get('source',[''])[0][:20];item=q.get('id',[''])[0][:80]
    module={'pluto':pluto,'justwatch':justwatch,'rakuten':rakuten}.get(source)
    return self.send({**download_quality.options(source,(lambda:module.play_source(ROOT,item)) if module else None),'heights':list(download_quality.HEIGHTS)})

@ROUTES.get('/api/play')
def get_play(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);ref={k:q.get(k,[''])[0] for k in ('offer','job','netzkino','pluto','justwatch','rakuten','joyn','toggo','crunchyroll','samsung','plex','servustv','rtlplus')}
    direct_youtube=q.get('direct',[''])[0]=='1'
    yt_id=q.get('youtube',[''])[0]
    if yt_id:
        # 0.5.53: a finished offline copy plays locally; otherwise the official embedded player.
        with db() as c:done=[j for j in netzkino_downloads.listing(c,item_id=yt_id,origin='youtube')['items'] if j['state']=='done']
        if done:ref['job']=done[0]['id']
        elif direct_youtube:ref['youtube']=yt_id   # 0.5.78: own player, stream resolved by yt-dlp (opt-in switch)
        else:
            try:info=youtube.play_info(ROOT,yt_id)
            except ValueError as e:return self.send({'error':str(e)},404)
            diagnostics.event('playback_start',mode='embed',origin='online',hls=False,provider='youtube')
            return self.send(info)
    # 0.5.63: the player's wish for the picture size ('auto', 'max' or a height such as '480')
    quality=_play_quality(q)
    try:
        with db() as c:source=streaming.resolve(c,root=ROOT,quality=quality,**ref)
        info=streaming.plan(source,levels=q.get('levels',[''])[0]!='0')
    except ValueError as e:return self.send({'error':str(e)},404)
    if q.get('probe',[''])[0]=='1':return self.send({'levels':info.get('levels') or []})  # 0.5.72: levels only, for the ffmpeg fallback
    base='/api/stream?'+urllib.parse.urlencode({k:v for k,v in ref.items() if v})
    if info['origin']=='local':info['src']=base+('&raw=1' if info['mode']=='direct' else '')
    else:info['src']=info.pop('url') if info['mode']=='direct' else base
    info['remux']=base;info['ffmpeg']=bool(downloads.tool('ffmpeg'))
    info['wish']=quality
    diagnostics.event('playback_start',mode=info['mode'],origin=info['origin'],hls=info.get('hls',False),provider=info.get('provider','mediathek'),
                      live=bool(info.get('live')),wish=quality,levels=[l['id'] for l in info.get('levels') or []])
    return self.send(info)

@ROUTES.get('/api/logs')
def get_logs(self,path):
    return self.send({'text':diagnostics.tail(),'sync':SERVICE.current})

@ROUTES.get('/api/diagnostics')
def get_diagnostics(self,path):
    # Catalogue counts and the cached recognition per channel make the export evaluable on its own.
    try:overview={'catalog':{k:v for k,v in catalog_status().items() if k!='sync'},'recognition':recognition()}
    except Exception as e:overview={'catalog_error':core.safe_error(e)}
    return self.send(diagnostics.export({**overview,'imdb':IMDB.status(),'provider_statistics':provider_stats.snapshot(),'sync':SERVICE.current,'metadata':SERVICE.metadata_status,'mesh':SERVICE.mesh_status,'providers':[name for name,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if settings().get(k)] or ['Wikidata'],'netzkino_downloads':netzkino_download_summary(),'ytdl_nightly':ytdl_bridge.status(),'pluto':pluto.state(ROOT),'justwatch':justwatch.state(ROOT),'rakuten':rakuten.state(ROOT),'joyn':joyn.state(ROOT),'toggo':toggo.state(ROOT),'crunchyroll':crunchyroll.state(ROOT),'samsung':samsung_tvplus.summary(ROOT),'plex':plex.state(ROOT),'servustv':servustv.state(ROOT),'rtlplus':rtlplus.state(ROOT),'youtube':{**youtube.state(ROOT),'offline_switch':youtube_downloads.status(ROOT)},'live_tv':live_tv_summary(),'watch':watch_state.summary(ROOT),'archive_works':archive_recognition.summary(ROOT),'threads':[t.name for t in threading.enumerate()],'http':http_timing.snapshot(),'network':{'trust_store':netcheck.ensure_trust_store(),'hosts':netcheck.probe()},'reference_share':__import__('reference_share').stats(ROOT)}),ctype='application/zip')

@ROUTES.get('/api/tools')
def get_tools(self,path):
    return self.send(runtime_tools.report(refresh=True))

@ROUTES.get('/api/provider-stats')
def get_provider_stats(self,path):
    return self.send(provider_stats.snapshot())

@ROUTES.get('/api/subscriptions')
def get_subscriptions(self,path):
    with db() as c:return self.send({'items':subscriptions.get_all(c),'device_time':time.time()})

@ROUTES.get('/api/review')
def get_review(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:return self.send(catalog.review_listing(c,query=q.get('query',[''])[0],state=q.get('state',['open'])[0],offset=q.get('offset',[0])[0]))

@ROUTES.get('/api/backups')
def get_backups(self,path):
    return self.send(db_backup.listing(ROOT))

@ROUTES.get('/api/archive-list-export')
def get_archive_list_export(self,path):
    # 0.5.92 (ArchiveMedia catalog_transfer): the known uploads as one file for another installation.
    with db() as c:body,facts=archive_transfer.export_bytes(c)
    diagnostics.event('archive_list_exported',items=facts['items'],files=facts['files'])
    return self.send(body,ctype='application/zip')

@ROUTES.get('/api/archive-uploaders')
def get_archive_uploaders(self,path):
    with db() as c:return self.send(archive_uploaders.listing(c))

@ROUTES.get('/api/archive-downloads')
def get_archive_downloads(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:return self.send(archive_downloads.listing(c,item_id=q.get('id',[None])[0]))

@ROUTES.get('/api/archive-companion')
def get_archive_companion(self,path):
    status=archive_companion.read_status()
    if NETWORK:status['ui_url']=None
    return self.send(status)

@ROUTES.get('/api/portal-policy')
def get_portal_policy(self,path):
    return self.send({'sources':{k:portal_metadata_policy.source_policy(k)
                  for k in portal_metadata_policy.PROVENANCE},
                  'filename':portal_metadata_policy.filename_rules(),
                  'reference_order':portal_metadata_policy.PRIORITY})

@ROUTES.get('/api/watch')
def get_watch(self,path):
    # 0.5.81: Merkliste, Weiterschauen and playback positions, kept on the server (watch_state).
    return self.send(watch_state.overview(ROOT))

@ROUTES.get('/api/archive-receipts')
def get_archive_receipts(self,path):
    return self.send(receipts_overview())

@ROUTES.get('/api/system-monitor')
def get_system_monitor(self,path):
    # 0.5.99: one reading of the machine on request (system_monitor); nothing runs while nobody looks.
    with db() as c:states=dict(c.execute("SELECT state,COUNT(*) FROM jobs WHERE state IN ('queued','downloading','tagging') GROUP BY state").fetchall())
    mesh=SERVICE.mesh_status
    return self.send(system_monitor.snapshot(ROOT,settings().get('download_dir'),{
        'downloads_running':states.get('downloading',0)+states.get('tagging',0),'downloads_waiting':states.get('queued',0),
        'encoder_active':encoder.listing(ROOT)['active'],'receipt_task':RECEIPT_TASK['running'],
        'verbund':mesh.get('enabled') is True,'verbund_systems':len(mesh.get('nodes') or []),'background':not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'),
        # 0.6.0: planner profile (Normal / Schwache Hardware) and running catalogue runs
        'planner':PLANNER[0].status() if PLANNER[0] else dict(planner.profile(settings()),catalog_running=[])}))

@ROUTES.get('/api/encoder')
def get_encoder(self,path):
    return self.send(encoder.listing(ROOT,encoder_tools()))

@ROUTES.get('/api/storage')
def get_storage(self,path):
    # 0.5.81: used space of the downloads with a cleanup suggestion (storage_policy); nothing is deleted here.
    with db() as c:return self.send(storage_policy.overview(c,ROOT,settings()['download_dir'],watch_state.states(ROOT)))

@ROUTES.get('/api/tasks')
def get_tasks(self,path):
    return self.send(tasks_overview())

@ROUTES.get('/api/unified')
def get_unified(self,path):
    # 0.5.55: dashboard "Alle" – one merged, globally sorted index of all sources.
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    return self.send(unified_index.page(ROOT,db,kind=q.get('kind',['movies'])[0],query=q.get('q',[''])[0],
        genre=q.get('genre',[''])[0],sort=q.get('sort',['title'])[0],collection=q.get('collection',[''])[0],
        offset=q.get('offset',['0'])[0],merge_duplicates=ui_prefs.load(ROOT)['merge_duplicates'],modules=_UNIFIED_SOURCES))

@ROUTES.get('/api/display')
def get_display(self,path):
    return self.send({'display':ui_prefs.load(ROOT),**ui_prefs.describe()})

@ROUTES.get('/api/film-platforms')
def get_film_platforms(self,path):
    # Light endpoint for the catalogue header (per-source overview), no portal_sources scan.
    with db() as c:offline={name:netzkino_downloads.summary(c,name) for name in platform_registry.KEYS}
    return self.send({'film_platforms':film_platforms(offline)})

@ROUTES.get('/api/portals')
def get_portals(self,path):
    with db() as c:
        result=portal_sources.state(c)
        result['platform_control']=portal_control.source_status(c)
        result['archive_scopes']=portal_control.list_scopes(c)
        offline={name:netzkino_downloads.summary(c,name) for name in platform_registry.KEYS}
    result['film_platforms']=film_platforms(offline)
    return self.send(result)

@ROUTES.get('/api/portal-items')
def get_portal_items(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    work=q.get('work',[''])[0]
    with db() as c:
        # 0.5.82: works on top of the Archive.org uploads (archive_recognition); ``work`` lists the uploads of one work.
        try:archive_recognition.sync(ROOT,c)
        except Exception as e:diagnostics.error('archive_work_sync_failed',e)
        result=portal_sources.listing(c,source=q.get('source',[''])[0],
                    query=q.get('query',[''])[0],
                    offset=q.get('offset',['0'])[0],
                    locale=q.get('locale',['all'])[0],
                    ids=archive_recognition.members_of(ROOT,work) if work else None)
    try:archive_recognition.annotate(ROOT,result['items'])
    except Exception as e:diagnostics.error('archive_work_annotate_failed',e)
    return self.send(result)

@ROUTES.get('/api/archive-works')
def get_archive_works(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:archive_recognition.sync(ROOT,c)
    result=archive_recognition.overview(ROOT,query=q.get('query',[''])[0],offset=q.get('offset',['0'])[0])
    result['summary']=archive_recognition.summary(ROOT);result['auto']=bool(settings().get('auto_metadata',True))
    return self.send(result)

@ROUTES.get('/api/portal-archive-detail')
def get_portal_archive_detail(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:
        item_id=q.get('id',[''])[0]
        result=portal_sources.archive_saved_detail(c,item_id)
    return self.send(result)

@ROUTES.get('/api/catalog')
def get_catalog(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:result=catalog.listing(c,query=q.get('query',[''])[0],kind=q.get('kind',[''])[0],genre=q.get('genre',[''])[0],show=q.get('show',[''])[0],offset=q.get('offset',[0])[0],archive=q.get('archive',['0'])[0]=='1',state=q.get('state',[''])[0],sort=q.get('sort',['title'])[0],downloaded=q.get('downloaded',['hide'])[0],collection=q.get('collection',[''])[0])
    return self.send(result)

@ROUTES.get('/api/catalog-tree')
def get_catalog_tree(self,path):
    return self.send(catalog_tree())

@ROUTES.get('/api/recognition')
def get_recognition(self,path):
    return self.send(recognition())

@ROUTES.get('/api/show')
def get_show(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    try:
        with db() as c:return self.send(catalog.show_detail(c,q.get('show',[''])[0][:200],archive=q.get('archive',['0'])[0]=='1'))
    except ValueError as e:return self.send({'error':str(e)},404)

@ROUTES.get('/api/alternatives')
def get_alternatives(self,path):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    with db() as c:return self.send({'items':catalog.alternatives(c,q.get('work_id',[''])[0])})

@ROUTES.get('/api/availability')
def get_availability(self,path):
    import broadcaster
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    oid=q.get('id',[''])[0][:128]
    if not oid:return self.send({'error':'Angebot fehlt'},400)
    with db() as c:
        raw=c.execute('SELECT payload FROM offers WHERE id=?',(oid,)).fetchone()
        cached=c.execute('SELECT available_until,source,checked FROM offer_availability WHERE offer_id=?',(oid,)).fetchone()
    if not raw:return self.send({'error':'Angebot nicht gefunden'},404)
    row=json.loads(raw[0]);now=time.time()
    if row.get('available_until'):
        return self.send({'available_until':row['available_until'],'source':row.get('availability_source','Filmliste'),'known':True,'checked_at':now})
    if cached and now-cached[2]<(86400 if cached[0] else 21600):
        return self.send({'available_until':cached[0] or None,'source':cached[1] or None,'known':bool(cached[0]),'checked_at':cached[2]})
    info=None;error=''
    try:
        info=broadcaster.lookup(row)
    except Exception as e:
        error=core.safe_error(e)
    until=info.get('available_until') if info else None
    # Failed requests are not negative evidence and must not overwrite a known expiry.
    if not error:
        with db() as c:c.execute('INSERT OR REPLACE INTO offer_availability VALUES(?,?,?,?)',(oid,until or None,(info or {}).get('provider',''),now))
    diagnostics.event('offer_availability_checked',provider=(info or {}).get('provider',''),known=bool(until),error=bool(error))
    return self.send({'available_until':until or (cached[0] if cached else None),'source':(info or {}).get('provider') or (cached[1] if cached else None),
                      'known':bool(until or cached and cached[0]),'checked_at':now,'error':error or None})

@ROUTES.get('/api/state')
def get_state(self,path):
    s=settings();return self.send({'artwork_checked':SERVICE.artwork_checked,'imdb':IMDB.status(),'jobs':jobs(),'settings':{'download_dir':s['download_dir'],'tmdb_set':bool(s.get('tmdb')),'omdb_set':bool(s.get('omdb')),'tvdb_set':bool(s.get('tvdb')),'tvdb_pin_set':bool(s.get('tvdb_pin')),'fanart_set':bool(s.get('fanart') or s.get('fanart_personal')),'youtube_set':bool(s.get('youtube')),'auto_catalog':s['auto_catalog'],'auto_metadata':s['auto_metadata'],'scan_priority':s.get('scan_priority','balanced'),'complete_series':s.get('complete_series',True),'metadata_workers':s.get('metadata_workers',2),'episode_workers':s.get('episode_workers',2),'sender_direct_lookup':s.get('sender_direct_lookup',False),'library_dirs':s.get('library_dirs',[]),'mesh_dir':s.get('mesh_dir',''),'mesh_name':s.get('mesh_name',''),'mesh_peers':[p['url'] for p in meshpeer.peer_list(s)],'mesh_shared':NETWORK and meshpeer.valid_key(s.get('mesh_key'))},'tools':{'ffmpeg':bool(downloads.tool('ffmpeg')),'ffprobe':bool(downloads.tool('ffprobe'))},'runtime':runtime_tools.report(),'catalog':catalog_status(),'metadata':SERVICE.metadata_status,'provider_pauses':{'omdb':metadata.omdb_status(s.get('omdb','')),
            'tmdb':metadata.network_provider_status('TMDB'),
            'wikidata':metadata.network_provider_status('Wikidata')},'reclassification':SERVICE.reclassification,'server':{'network':NETWORK,'managed':MANAGED,'version':VERSION},'mesh':SERVICE.mesh_status})

# 0.5.97: Samsung TV Plus has live channels only (no catalogue page, see samsung_tvplus.py)
@ROUTES.post('/api/samsung-sync')
def post_samsung_sync(self,path,d):
    return self.send({'started':samsung_tvplus.start_sync(ROOT),'status':samsung_tvplus.state(ROOT)})

@ROUTES.post('/api/samsung-auto')
def post_samsung_auto(self,path,d):
    return self.send({'status':samsung_tvplus.set_auto(ROOT,d.get('enabled'))})

@ROUTES.post('/api/samsung-region')
def post_samsung_region(self,path,d):
    return self.send({'status':samsung_tvplus.set_region(ROOT,d.get('region'))})

@ROUTES.post('/api/youtube-sources')
def post_youtube_sources(self,path,d):
    action=str(d.get('action',''))
    if action=='add':result=youtube.add_source(ROOT,d.get('url',''),str(d.get('kind','movies')),str(d.get('label',''))[:120],d.get('min_minutes'))
    else:result=youtube.update_source(ROOT,d.get('id'),action)
    diagnostics.event('youtube_sources_changed',action=action[:10],count=len(result))
    # 0.5.74 (Björn: added a playlist and nothing appeared): a new or re-enabled source is read
    # right away when a key is set; a run already going picks it up next time.
    started=action in ('add','enable') and bool(str(settings().get('youtube','')).strip()) and youtube.start_sync(ROOT,queue=True)
    return self.send({'sources':result,'status':youtube.state(ROOT),'started':bool(started)})

@ROUTES.post('/api/youtube-key')
def post_youtube_key(self,path,d):
    s=settings();key=str(d.get('key','')).strip()
    if d.get('clear') is True:s['youtube']=''
    elif key:
        if not __import__('re').fullmatch(r'[A-Za-z0-9_\-]{20,80}',key):raise ValueError('Das sieht nicht wie ein Google-API-Schlüssel aus')
        s['youtube']=key
    with db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(s),))
    started=bool(s.get('youtube')) and youtube.start_sync(ROOT)
    return self.send({'status':youtube.state(ROOT),'started':started})

@ROUTES.post('/api/youtube-offline')
def post_youtube_offline(self,path,d):
    return self.send(youtube_downloads.set_enabled(ROOT,d.get('enabled'),d.get('confirmed') is True))

@ROUTES.post('/api/youtube-ytdlp-install')
def post_youtube_ytdlp_install(self,path,d):
    try:return self.send(youtube_downloads.install_tool(ROOT))
    except (OSError,ValueError) as e:return self.send({'error':'yt-dlp konnte nicht eingerichtet werden: '+core.safe_error(e)},502)

@ROUTES.post('/api/youtube-download-add')
def post_youtube_download_add(self,path,d):
    if d.get('album') or isinstance(d.get('ids'),list):
        # 0.5.71: a whole music playlist ('album') or a selection of its videos ('ids') in one click.
        album=str(d.get('album') or '')
        ids=[str(x) for x in d.get('ids')][:youtube.MAX_BATCH] if isinstance(d.get('ids'),list) else None
        if album:ids=youtube.album_track_ids(ROOT,album,ids)
        elif any(not youtube.VALID_ID.fullmatch(i) or not i.startswith('t.') for i in ids):raise ValueError('Ungültige Auswahl')
        if not ids:raise ValueError('Keine speicherbaren Videos ausgewählt')
        with db() as c:
            result=youtube_downloads.enqueue_many(c,ROOT,settings()['download_dir'],ids)
            for job_id in result['jobs']:download_quality.set_job(c,{'id':job_id,'created':True},d.get('quality'))
        diagnostics.event('youtube_download_batch',created=result['created'],existing=result['existing'],failed=result['failed'])
        return self.send(result)
    item_id=str(d.get('id',''))
    try:
        if not item_id.startswith('t.'):   # music videos have no film references
            with SERVICE.provider_slots:youtube_enrichment.enrich(ROOT,item_id,settings())
    except Exception as e:diagnostics.error('youtube_download_enrich_failed',e)
    with db() as c:result=youtube_downloads.enqueue(c,ROOT,settings()['download_dir'],item_id);download_quality.set_job(c,result,d.get('quality'))
    diagnostics.event('youtube_download_enqueued',created=result['created'])
    return self.send(result)

@ROUTES.post('/api/netzkino-recording')
def post_netzkino_recording(self,path,d):
    return self.send(netzkino.import_recording(ROOT,d.get('entries')))

@ROUTES.post('/api/netzkino-add')
def post_netzkino_add(self,path,d):
    return self.send({'item':netzkino.add(ROOT,d.get('title'),d.get('url'))})

@ROUTES.post('/api/netzkino-remove')
def post_netzkino_remove(self,path,d):
    return self.send({'removed':netzkino.remove(ROOT,d.get('id'))})

@ROUTES.post('/api/netzkino-sync')
def post_netzkino_sync(self,path,d):
    return self.send({'started':netzkino.start_sync(ROOT)})

@ROUTES.post('/api/netzkino-auto')
def post_netzkino_auto(self,path,d):
    return self.send({'status':netzkino.set_auto(ROOT,d.get('enabled'))})

@ROUTES.post('/api/shutdown')
def post_shutdown(self,path,d):
    if MANAGED:raise ValueError('Der Dienst wird vom NAS verwaltet. Bitte im Paket-Zentrum bzw. App Center stoppen.')
    self.send({'ok':True});STOP.set()
    threading.Thread(target=self.server.shutdown,daemon=True).start()
    return

@ROUTES.post('/api/test-tvdb')
def post_test_tvdb(self,path,d):
    import tvdb
    return self.send(tvdb.test_access(settings().get('tvdb',''),settings().get('tvdb_pin','')))

@ROUTES.post('/api/backup-create')
def post_backup_create(self,path,d):
    return self.send(db_backup.start(ROOT,diagnostics.event,diagnostics.error))

@ROUTES.post('/api/backup-delete')
def post_backup_delete(self,path,d):
    return self.send(db_backup.delete(ROOT,d.get('backups'),d.get('confirm')))

@ROUTES.post('/api/test-omdb')
def post_test_omdb(self,path,d):
    return self.send(metadata.test_omdb(settings().get('omdb','')))

@ROUTES.post('/api/portal-controls')
def post_portal_controls(self,path,d):
    source=d.get('source')
    if source is not None:source=str(source)
    with db() as c:
        portal_control.set_controls(c,source=source,
            enabled=d.get('enabled'),
            workers=d.get('workers'),
            locale=d.get('locale'),
            max_active=d.get('max_active'))
        result=portal_control.source_status(c)
    diagnostics.event('portal_controls_updated',source=source,
                      enabled=d.get('enabled'),workers=d.get('workers'))
    return self.send(result)

@ROUTES.post('/api/portal-scope-add')
def post_portal_scope_add(self,path,d):
    with db() as c:
        scope_id=portal_control.add_scope(c,d.get('kind'),d.get('value'),
                     priority=d.get('priority'),page_budget=d.get('page_budget',8))
    return self.send({'id':scope_id,'ok':True})

@ROUTES.post('/api/portal-scope-control')
def post_portal_scope_control(self,path,d):
    with db() as c:
        portal_control.control_scope(c,d.get('id'),d.get('action'),
                                     priority=d.get('priority'))
    return self.send({'ok':True})

@ROUTES.post('/api/portal-search')
def post_portal_search(self,path,d):
    if d.get('source')!='internet_archive':
        raise ValueError('Nur Internet Archive bietet hier eine dokumentierte Such-API')
    rows=portal_sources.search_archive(d.get('query',''))
    with db() as c:
        saved=portal_sources.save(c,rows,query=d.get('query',''))
    diagnostics.event('portal_metadata_import',source='internet_archive',items=len(saved),
                      mode='user_activated')
    return self.send({'added_or_updated':len(saved),
                      'access':'official_site_only','download_enabled':False})

@ROUTES.post('/api/portal-archive-inspect')
def post_portal_archive_inspect(self,path,d):
    item_id=str(d.get('id') or '')
    with db() as c:
        row=c.execute('SELECT source,external_id FROM portal_items WHERE id=?',
                      (item_id,)).fetchone()
    if not row or row['source']!='internet_archive':
        raise ValueError('Gespeicherter Internet-Archive-Eintrag fehlt')
    detail=portal_sources.fetch_archive_detail(row['external_id'])
    with db() as c:portal_sources.save_archive_detail(c,item_id,detail)
    diagnostics.event('portal_archive_manifest_inspected',files=detail['files_in_manifest'],
                      variants=detail['variants_displayed'],
                      complete=detail['inventory_complete'])
    return self.send({'detail':detail,'ok':True})

@ROUTES.post('/api/archive-bluray-playlist','/api/archive-external-id')
def post_archive_bluray_playlist(self,path,d):
    # 0.5.92 (ArchiveMedia bluray_playlist, catalog_enrichment): one small look-up on request, stored with the manifest.
    item_id=str(d.get('id') or '')
    with db() as c:saved=portal_sources.archive_saved_detail(c,item_id)
    detail=saved.get('detail')
    if not detail:raise ValueError('Bitte erst den Archiv-Dateibestand prüfen')
    if path=='/api/archive-bluray-playlist':
        result=archive_extras.read_playlist(detail,str(d.get('filename') or ''))
        result['main']=archive_extras.main_playlist(detail)
    else:
        result=archive_extras.lookup(detail,str(d.get('provider') or ''))
        detail.setdefault('external_lookups',{})[str(d.get('provider'))]=result
    with db() as c:portal_sources.save_archive_detail(c,item_id,detail)
    return self.send(result)

@ROUTES.post('/api/archive-selection')
def post_archive_selection(self,path,d):
    # 0.5.88 (ArchiveMedia selection_matrix): which file of every episode fits the wishes; nothing is fetched or queued.
    with db() as c:saved=portal_sources.archive_saved_detail(c,str(d.get('id') or ''))
    if not saved.get('detail'):raise ValueError('Bitte erst den Archiv-Dateibestand prüfen')
    return self.send(archive_selection.matrix(saved['detail'],saved.get('probes'),d.get('criteria')))

@ROUTES.post('/api/archive-selection-download')
def post_archive_selection_download(self,path,d):
    with db() as c:result=archive_selection.enqueue(c,settings()['download_dir'],str(d.get('id') or ''),d.get('criteria'),d.get('picks'))
    diagnostics.event('archive_selection_queued',created=result['created'],existing=result['existing'],failed=len(result['failed']))
    return self.send(result)

@ROUTES.post('/api/archive-uploaders-follow')
def post_archive_uploaders_follow(self,path,d):
    with db() as c:result=archive_uploaders.follow(ROOT,c)
    diagnostics.event('archive_uploaders_noted',new=result['new'],works=result['works'])
    return self.send(result)

@ROUTES.post('/api/archive-download')
def post_archive_download(self,path,d):
    with db() as c:
        if not c.execute("SELECT 1 FROM portal_items WHERE id=? AND source='internet_archive'",(str(d.get('id') or ''),)).fetchone():
            raise ValueError('Archive.org-Eintrag nicht gefunden')
        result=archive_downloads.enqueue(c,settings()['download_dir'],d['id'],d.get('filename'),d.get('metadata'))
    diagnostics.event('archive_download_queued',created=result.get('created'))
    return self.send(result)

@ROUTES.post('/api/portal-archive-probe')
def post_portal_archive_probe(self,path,d):
    if d.get('acknowledged') is not True:
        raise ValueError('Nur nach bestätigter Berechtigung zur technischen Teilprüfung')
    item_id=str(d.get('id') or '')
    filename=str(d.get('filename') or '')
    # Save the result only after a bounded, user-initiated probe.
    # This route does not enqueue downloads or enumerate an archive.
    with db() as c:
        report=portal_sources.probe_archive_variant(
            c,item_id,filename,acknowledged=True)
    diagnostics.event('portal_video_technical_probe',
                      state=report['state'],
                      bytes=report['bytes_sampled'],
                      audio_tracks=sum(t['type']=='audio' for t in report['tracks']),
                      subtitle_tracks=sum(t['type']=='subtitle' for t in report['tracks']))
    return self.send({'probe':report})

@ROUTES.post('/api/netzkino-download-add')
def post_netzkino_download_add(self,path,d):
    # One queue for everything: same worker, folders and names as Mediathek videos.
    item_id=str(d.get('id',''));root=settings()['download_dir']
    if not d.get('file_url'):
        # Classification and metadata like an ARD/ZDF download: IMDb/TVDB/TMDB check first
        # (cached when fresh), outside any database connection. Failures never block.
        try:
            with SERVICE.provider_slots:netzkino_enrichment.enrich(ROOT,item_id,settings())
        except Exception as e:diagnostics.error('netzkino_download_enrich_failed',e)
    with db() as c:
        if d.get('file_url'):
            result=netzkino_downloads.enqueue_file(c,ROOT,root,item_id,d.get('file_url',''),
                d.get('rights_basis',''),d.get('rights_note',''),confirmed=d.get('confirmed') is True)
        else:result=netzkino_downloads.enqueue(c,ROOT,root,item_id);download_quality.set_job(c,result,d.get('quality'))
    diagnostics.event('netzkino_download_enqueued',created=result['created'],licensed_file=bool(d.get('file_url')))
    return self.send(result)

@ROUTES.post('/api/archive-work-check')
def post_archive_work_check(self,path,d):
    with SERVICE.provider_slots:
        result=archive_recognition.enrich(ROOT,str(d.get('id','')),settings(),force=d.get('force') is True)
    diagnostics.event('archive_reference_check',status=result['status'],candidates=len(result.get('references',[])))
    return self.send({'status':result['status'],'ok':True})

@ROUTES.post('/api/netzkino-download-action','/api/offline-download-action')
def post_netzkino_download_action(self,path,d):
    action=d.get('action','');job_id=str(d.get('id',''))
    with db() as c:
        row=c.execute('SELECT payload FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row or not netzkino_downloads.is_portal(json.loads(row[0])):raise ValueError('Offline-Download nicht gefunden')
        if action=='cancel':
            c.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('queued','downloading','tagging')",(job_id,));result={'ok':True,'state':'cancelled'}
        elif action=='delete':result=netzkino_downloads.delete_now(c,job_id)
        else:raise ValueError('Für diesen Auftrag unzulässige Aktion')
    diagnostics.event('netzkino_download_control',action=action)
    return self.send(result)

@ROUTES.post('/api/netzkino-enrich')
def post_netzkino_enrich(self,path,d):
    item_id=str(d.get('id',''))
    with SERVICE.provider_slots:
        result=netzkino_enrichment.enrich(ROOT,item_id,settings(),
                                            force=d.get('force') is True)
    diagnostics.event('netzkino_reference_check',status=result['status'],
        candidates=len(result.get('references',[])),
        checked_providers=len(result.get('provider_checks',[])))
    return self.send(result)

@ROUTES.post('/api/netzkino-metadata-probe')
def post_netzkino_metadata_probe(self,path,d):
    item_id=str(d.get('id',''))
    editorial=netzkino_details.get(ROOT,item_id)
    result=yt_dlp_probe.probe(editorial['page_url'],editorial['details'])
    diagnostics.event('netzkino_metadata_validation',status=result['status'],
                      conflicts=len(result.get('warnings',[])))
    return self.send(result)

@ROUTES.post('/api/netzkino-watch')
def post_netzkino_watch(self,path,d):
    item_id=str(d.get('id',''))
    page=netzkino_details.find_page(ROOT,item_id)
    helper=Path(__file__).with_name('netzkino_webplayer')
    if sys.platform=='darwin' and helper.is_file() and os.access(helper,os.X_OK) and not NETWORK:
        subprocess.Popen([str(helper),page],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
        diagnostics.event('netzkino_official_player',mode='native_webkit')
        return self.send({'mode':'native_webkit'})
    diagnostics.event('netzkino_official_player',mode='native_unavailable')
    return self.send({'mode':'native_unavailable'})

@ROUTES.post('/api/portal-netzkino-add')
def post_portal_netzkino_add(self,path,d):
    item=portal_sources.manual_netzkino(d.get('title',''),
              d.get('url',''),d.get('year'))
    with db() as c:portal_sources.save(c,[item])
    diagnostics.event('portal_manual_link_added',source='netzkino')
    return self.send({'item':item,'ok':True})

@ROUTES.post('/api/search')
def post_search(self,path,d):
    global _TREE_CACHE
    found=core.search(d.get('query',''),d.get('channel',''),d.get('offset',0))
    with db() as c:catalog.ingest(c,found['results'])
    with _TREE_LOCK:_TREE_CACHE=(float("-inf"),_TREE_CACHE[1],_TREE_CACHE[2])
    return self.send({'imported':len(found['results'])})

@ROUTES.post('/api/sync')
def post_sync(self,path,d):
    SERVICE.restart.set();SERVICE.wake.set();diagnostics.event('sync_requested');return self.send({'ok':True})

@ROUTES.post('/api/library-locate','/api/library-relink')
def post_library_locate(self,path,d):
    job_id=str(d.get('id') or '')[:128]
    if not job_id:raise ValueError('Download-ID fehlt')
    approved=local_library.roots(settings())
    if path.endswith('library-locate'):
        with db() as c:job,_=local_library.missing_job(c,job_id)
        found=local_library.candidates(job,approved)
        diagnostics.event('library_relink_search',matches=len(found['matches']),scanned=found['scanned'],incomplete=found['incomplete'])
        if len(found['matches'])==1 and job.get('size_bytes'):
            with db() as c:result=local_library.relink(c,job_id,found['matches'][0],approved)
            diagnostics.event('library_relinked',job_id=job_id,automatic=True)
            return self.send({**result,'found':1,'automatic':True})
        return self.send({**found,'ok':False,'requires_selection':True})
    with db() as c:result=local_library.relink(c,job_id,d.get('path') or '',approved)
    diagnostics.event('library_relinked',job_id=job_id,automatic=False)
    return self.send(result)

@ROUTES.post('/api/subscription-add')
def post_subscription_add(self,path,d):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        sub_id=subscriptions.add(c,d)
    SERVICE.subscription_wake.set()
    diagnostics.event('subscription_created',id=sub_id,kind=d.get('kind'),
                      mode=d.get('mode','availability'))
    return self.send({'ok':True,'id':sub_id})

@ROUTES.post('/api/subscription-action')
def post_subscription_action(self,path,d):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        subscriptions.change(c,str(d.get('id') or ''),str(d.get('action') or ''))
    SERVICE.subscription_wake.set()
    diagnostics.event('subscription_modified',action=d.get('action'))
    return self.send({'ok':True})

@ROUTES.post('/api/subscription-check')
def post_subscription_check(self,path,d):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        results=subscriptions.run_due(c,settings()['download_dir'],
                                      force_id=str(d.get('id') or '') or None)
    diagnostics.event('subscription_checked',subscriptions=len(results),
                      queued=sum(x['queued'] for x in results))
    return self.send({'ok':True,'items':results})

@ROUTES.post('/api/metadata-priority')
def post_metadata_priority(self,path,d):
    ids=d.get('ids',[])
    if not isinstance(ids,list) or len(ids)>1000:raise ValueError('Ungültige Auswahl')
    with db() as c:count=catalog.prioritize(c,ids,d.get('show',''))
    SERVICE.metadata_wake.set();return self.send({'queued':count,'enabled':settings()['auto_metadata']})

@ROUTES.post('/api/series-plan','/api/series-download')
def post_series_plan(self,path,d):
    root=settings()['download_dir']
    with db() as c:
        if path.endswith('series-download'):
            if d.get('confirmed') is not True:raise ValueError('Serienvorschau zuerst bestätigen')
            c.execute('BEGIN IMMEDIATE')
            result=series_download.enqueue(c,d.get('show',''),root,d.get('fingerprint',''),d.get('ids'))
            diagnostics.event('series_download_queued',**result)
        else:
            result=series_download.plan(c,d.get('show',''),root)
            result['eligible']=[{'id':x['id'],'title':x['metadata'].get('episode_title') or x['metadata']['title'],'season':x['metadata']['season'],'episode':x['metadata']['episode'],'target':x['target']} for x in result['eligible']]
    return self.send(result)

@ROUTES.post('/api/save-metadata')
def post_save_metadata(self,path,d):
    global _STATUS_CACHE,_TREE_CACHE
    m=core.validate_meta(d['metadata'],require_episode=False);m['state']='user_confirmed'
    with db() as c:
        o=c.execute('SELECT work_id FROM offers WHERE id=?',(d['id'],)).fetchone()
        if not o:raise ValueError('Katalogeintrag nicht gefunden')
        SERVICE.mesh_manual(c,o[0],catalog.save_metadata(c,o[0],m) or o[0],m)
    _TREE_CACHE=(float("-inf"),[],[]);_STATUS_CACHE=(0,{})
    return self.send({'ok':True})

@ROUTES.post('/api/candidates')
def post_candidates(self,path,d):
    config=settings()
    cachekey=hashlib.sha256(json.dumps(['v045',config.get('imdb_generation'),d['id'],d['metadata'],config.get('tmdb'),config.get('omdb'),config.get('tvdb'),config.get('tvdb_pin')],sort_keys=True).encode()).hexdigest()
    # A user-triggered search must bypass old provider results and negative caches.
    # The automatic worker still uses the separate 24h metadata cache.
    result=core.candidates(record(d['id']),d['metadata'],{**config,'_force_provider_refresh':True})
    if not result['warnings'] and not result.get('deferred_providers'):
        with db() as c:c.execute('INSERT OR REPLACE INTO metadata_cache VALUES(?,?,?)',(cachekey,json.dumps(result),time.time()))
    return self.send(result)

@ROUTES.post('/api/preview')
def post_preview(self,path,d):
    return self.send({'path':str(core.target(settings()['download_dir'],d['metadata'],d['id']))})

@ROUTES.post('/api/settings')
def post_settings(self,path,d):
    s=settings();previous=dict(s)
    if d.get('download_dir'):
        p=Path(d['download_dir']).expanduser()
        if not p.is_absolute():raise ValueError('Bitte absoluten Zielpfad angeben')
        s['download_dir']=str(p)
    for k in ('tmdb','omdb','tvdb','tvdb_pin','youtube','fanart','fanart_personal'):
        if k in d and str(d[k] or '').strip():s[k]=str(d[k]).strip()
        if d.get('clear_'+k):s[k]=''
    for k in ('auto_catalog','auto_metadata','complete_series','sender_direct_lookup'):
        if k in d:s[k]=bool(d[k])
    if 'background_profile' in d:
        # 0.6.0: planner profile (Verwaltung → System); auto = by cores and memory
        if d['background_profile'] not in planner.CHOICES:raise ValueError('Unbekanntes Profil')
        s['background_profile']=d['background_profile']
    if 'metadata_workers' in d:
        try:n=int(d['metadata_workers'])
        except (ValueError,TypeError):raise ValueError('Ungültige Workerzahl') from None
        if n not in (1,2,4,8):raise ValueError('Erlaubt sind 1, 2, 4 oder 8 Worker')
        s['metadata_workers']=n
    if 'episode_workers' in d:
        try:n=int(d['episode_workers'])
        except (ValueError,TypeError):raise ValueError('Ungültige Episoden-Workerzahl') from None
        if n not in (1,2,4):raise ValueError('Erlaubt sind 1, 2 oder 4 Episoden-Worker')
        s['episode_workers']=n
    if 'library_dirs' in d:
        paths=d['library_dirs']
        if isinstance(paths,str):paths=paths.splitlines()
        if not isinstance(paths,list) or len(paths)>8:raise ValueError('Maximal acht zusätzliche Bibliotheksordner')
        cleaned=[]
        for value in paths:
            p=Path(str(value).strip()).expanduser()
            if not str(value).strip():continue
            if not p.is_absolute() or p.resolve()==Path(p.anchor):
                raise ValueError('Bibliotheksordner müssen absolute Unterordner sein')
            cleaned.append(str(p))
        s['library_dirs']=cleaned
    if 'scan_priority' in d:
        if d['scan_priority'] not in ('balanced','movies_first','series_first'):
            raise ValueError('Unbekannte Scan-Priorität')
        s['scan_priority']=d['scan_priority']
    if 'mesh_dir' in d:
        folder=str(d['mesh_dir'] or '').strip()
        # Validates mount and marker; only an explicit request prepares a non-MeshSync folder.
        if folder:folder=str(meshjournal.check_folder(folder,create=d.get('mesh_init') is True))
        s['mesh_dir']=folder
    if 'mesh_name' in d:s['mesh_name']=str(d['mesh_name'] or '').strip()[:80]
    with db() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(s),))
        if any(s.get(k)!=previous.get(k) for k in ('tmdb','omdb','tvdb','tvdb_pin')):
            c.execute("UPDATE works SET state=CASE WHEN state='identified' THEN state ELSE 'pending' END,next_try=0 WHERE state IN ('review','retry','identified')")
    if any(s.get(k)!=previous.get(k) for k in ('mesh_dir','mesh_name','auto_metadata')):threading.Thread(target=SERVICE.mesh_tick,daemon=True,name='mesh_apply').start()
    return self.send({'ok':True})

@ROUTES.post('/api/mesh-direct')
def post_mesh_direct(self,path,d):
    s=settings();action=d.get('action')
    if action=='share':
        if not NETWORK:raise ValueError('Die Mac-/Desktop-App ist nur auf diesem Rechner erreichbar und kann nicht freigegeben werden. Bitte auf dem NAS „Dieses System freigeben“ wählen und den Code hier einfügen.')
        if not meshpeer.valid_key(s.get('mesh_key')):s['mesh_key']=meshpeer.new_key()
    elif action=='rotate':
        if not NETWORK:
            raise ValueError('Ein neuer Verbund-Schlüssel kann nur auf einem erreichbaren NAS-Dienst erzeugt werden.')
        if d.get('confirmed') is not True:
            raise ValueError('Schlüsselwechsel bestätigen: Alle bisher verbundenen Clients benötigen danach den neuen Verbindungscode.')
        # Rotation changes inbound access only; outbound peer codes
        # and the existing journal/counters must remain untouched.
        s['mesh_key']=meshpeer.new_key()
        diagnostics.event('mesh_key_rotated',outgoing_peers=len(meshpeer.peer_list(s)))
    elif action=='connect':
        url,key=meshpeer.parse_code(d.get('code'))
        if not key:raise ValueError('Bitte den vollständigen Verbindungscode der Gegenstelle einfügen (Adresse#Schlüssel)')
        if key==s.get('mesh_key'):raise ValueError('Das ist der Verbindungscode dieses Systems selbst. Bitte den Code eines anderen Systems einfügen.')
        info=meshpeer.Peer(url,key).hello()
        if SERVICE.mesh is not None and info.get('node')==SERVICE.mesh.node:raise ValueError('Das ist der Verbindungscode dieses Systems selbst. Bitte den Code eines anderen Systems einfügen.')
        peers=[p for p in meshpeer.peer_list(s) if p['url']!=url]+[{'url':url,'key':key}]
        s['mesh_peers']=peers;s.pop('mesh_peer',None)
    elif action=='remove':
        url=str(d.get('url') or '').rstrip('/')
        s['mesh_peers']=[p for p in meshpeer.peer_list(s) if p['url']!=url];s.pop('mesh_peer',None)
    elif action=='unshare':s['mesh_peers']=meshpeer.peer_list(s);s.pop('mesh_peer',None);s.pop('mesh_key',None)
    elif action=='off':s.pop('mesh_peer',None);s.pop('mesh_key',None);s.pop('mesh_peers',None)
    else:raise ValueError('Unbekannte Aktion')
    with db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(s),))
    diagnostics.register_secrets(s.get('mesh_key'),*[p['key'] for p in meshpeer.peer_list(s)])
    threading.Thread(target=SERVICE.mesh_tick,daemon=True,name='mesh_apply').start()
    out={'ok':True,'key':s.get('mesh_key',''),'tailscale':meshpeer.tailscale_address(),'network':NETWORK,'port':self.server.server_port}
    if action=='connect':out['peer']=str(info.get('name') or '')[:80]
    return self.send(out)

@ROUTES.post('/api/download')
def post_download(self,path,d):
    if d.get('confirmed') is not True:raise ValueError('Metadaten zuerst prüfen und bestätigen')
    m=core.validate_meta(d['metadata']);m['state']='user_confirmed';m['confirmed_at']=time.time()
    row=record(d['id'])
    choices=catalog.links(row)
    if d.get('quality','best')=='best' and choices:row['_download_url']=choices[0]['url']
    with db() as c:
        # Another instance of the Verbund loads or already shared this title: no second download.
        o=c.execute('SELECT work_id FROM offers WHERE id=?',(d['id'],)).fetchone()
        blocked=SERVICE.mesh_download_block(c,m,o and o[0])
        if blocked:raise ValueError(blocked)
        if o:SERVICE.mesh_manual(c,o[0],catalog.save_metadata(c,o[0],m) or o[0],m)
    dest=str(core.target(settings()['download_dir'],m,d['id']))
    with db() as c:duplicate=c.execute("SELECT 1 FROM jobs WHERE state IN ('queued','downloading','tagging','done') AND json_extract(payload,'$.target')=? LIMIT 1",(dest,)).fetchone()
    if duplicate:raise ValueError('Dieses Ziel ist bereits in der Warteschlange oder fertig')
    j={'id':secrets.token_hex(8),'source':row,'metadata':m,'root':settings()['download_dir'],'quality':d.get('quality','best'),'target':dest,'state':'queued','received':0,'total':0}
    put_job(j);return self.send({'ok':True})

@ROUTES.post('/api/imdb-update')
def post_imdb_update(self,path,d):
    return self.send({'queued':IMDB.request()})

@ROUTES.post('/api/cast-photos')
def post_cast_photos(self,path,d):
    # 0.5.80: photos for the cast row of a title page (TMDB only, see cast_photos.py).
    import cast_photos
    people=d.get('people',[]);context=d.get('context',{})
    if not isinstance(people,list) or not isinstance(context,dict):raise ValueError('Ungültige Besetzung')
    return self.send(cast_photos.lookup(ROOT,settings().get('tmdb',''),people[:cast_photos.MAX_PEOPLE],context))

@ROUTES.post('/api/artwork-priority')
def post_artwork_priority(self,path,d):
    ids=d.get('ids',[])
    if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise ValueError('Ungültige Auswahl')
    with db() as c:
        for wid in ids[:48]:c.execute('INSERT OR IGNORE INTO artwork_checks SELECT id,? FROM works WHERE id=?',(-time.time(),wid))
    return self.send({'ok':True})

@ROUTES.post('/api/open-download')
def post_open_download(self,path,d):
    if NETWORK:raise ValueError('Die Datei liegt auf dem NAS. Bitte über File Station bzw. die Netzwerkfreigabe öffnen.')
    with db() as c:row=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(d['id'],)).fetchone()
    if not row:raise ValueError('Nur abgeschlossene Downloads können geöffnet werden')
    job=json.loads(row[0]);target=Path(job.get('path') or job['target']).resolve()
    if not target.is_file():raise ValueError('Datei wurde verschoben oder ist nicht verfügbar')
    if sys.platform=='darwin':subprocess.Popen(['/usr/bin/open',str(target)])
    elif os.name=='nt':os.startfile(str(target))
    else:subprocess.Popen(['xdg-open',str(target)])
    return self.send({'ok':True})

@ROUTES.post('/api/cancel')
def post_cancel(self,path,d):
    with db() as c:c.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('queued','downloading','tagging')",(d['id'],))
    return self.send({'ok':True})

@ROUTES.post('/api/task-action')
def post_task_action(self,path,d):
    return self.send(task_action(str(d.get('task',''))[:40],str(d.get('action',''))[:20],d.get('value')))

@ROUTES.post('/api/playback-stats')
def post_playback_stats(self,path,d):
    # 0.5.63: what the player saw (waiting pauses, chosen level) for the diagnosis; numbers only.
    def num(key,top):
        try:return max(0,min(round(float(d.get(key) or 0),1),top))
        except (TypeError,ValueError):return 0
    if _PLAYBACK_STATS[0]<200:
        _PLAYBACK_STATS[0]+=1
        diagnostics.event('playback_stats',mode=str(d.get('mode',''))[:10],provider=str(d.get('provider',''))[:20],live=bool(d.get('live')),
                          wish=str(d.get('wish',''))[:6],quality_level=str(d.get('level',''))[:6],native=bool(d.get('native')),fallback=str(d.get('fallback',''))[:60],switches=int(num('switches',9999)),
                          watched_seconds=num('watched',86400),first_picture_seconds=num('first',600),stalls=int(num('stalls',9999)),
                          stall_seconds=num('stall_seconds',86400),reduced=int(num('reduced',20)),
                          frames=int(num('frames',10**7)),dropped_frames=int(num('dropped',10**7)),gates=int(num('gates',9999)),agent=str(self.headers.get('User-Agent',''))[:160])
    return self.send({'ok':True})

@ROUTES.post('/api/client-error')
def post_client_error(self,path,d):
    # 0.5.57: script errors of the web interface reach the diagnosis (at most 40 per run).
    if _CLIENT_ERRORS[0]<40:
        _CLIENT_ERRORS[0]+=1
        diagnostics.event('client_error',message=str(d.get('message',''))[:300],source=str(d.get('source',''))[:120],
                          line=str(d.get('line',''))[:12],view=str(d.get('view',''))[:30],agent=str(self.headers.get('User-Agent',''))[:160])
    return self.send({'ok':True})

@ROUTES.post('/api/display')
def post_display(self,path,d):
    value=ui_prefs.save(ROOT,d.get('display'));unified_index.invalidate();diagnostics.event('display_settings_changed')
    return self.send({'display':value})

@ROUTES.post('/api/job-control')
def post_job_control(self,path,d):
    with db() as c:job=job_queue.control(c,str(d.get('id',''))[:128],str(d.get('action',''))[:20])
    diagnostics.event('download_queue_control',action=str(d.get('action',''))[:20])
    return self.send({'ok':True,'priority':job.get('priority',0),'hold':bool(job.get('hold'))})

@ROUTES.post('/api/retry')
def post_retry(self,path,d):
    # 0.5.43: same job again (one card), earlier failed twins disappear.
    with db() as c:job_queue.retry(c,str(d.get('id','')))
    return self.send({'ok':True})

@ROUTES.post('/api/watch-progress')
def post_watch_progress(self,path,d):
    return self.send(watch_state.progress(ROOT,d.get('key'),d.get('pos'),d.get('duration'),d.get('done') is True,d.get('info')))

@ROUTES.post('/api/watch-mark')
def post_watch_mark(self,path,d):
    result=watch_state.mark(ROOT,d.get('key'),d.get('favorite') if isinstance(d.get('favorite'),bool) else None,
                            d.get('pinned') if isinstance(d.get('pinned'),bool) else None,d.get('info'))
    diagnostics.event('watch_mark',favorite=result['favorite'],pinned=result['pinned'])
    return self.send(result)

@ROUTES.post('/api/watch-forget')
def post_watch_forget(self,path,d):
    return self.send(watch_state.forget(ROOT,d.get('key')))

@ROUTES.post('/api/storage-settings')
def post_storage_settings(self,path,d):
    values=storage_policy.save(ROOT,d)
    diagnostics.event('storage_settings',budget_gb=values['budget_gb'],protect_days=values['protect_days'])
    with db() as c:return self.send(storage_policy.overview(c,ROOT,settings()['download_dir'],watch_state.states(ROOT)))

@ROUTES.post('/api/archive-receipts-create')
def post_archive_receipts_create(self,path,d):
    # 0.5.95: receipts for Archive.org downloads from before this version (stored file only; the loaded bytes are gone).
    with db() as c:jobs_missing=archive_receipts.missing(c,ROOT)
    if not jobs_missing:raise ValueError('Alle Archive.org-Downloads haben bereits einen Nachweis')
    def create(step):
        made=0
        for job in jobs_missing:
            if STOP.is_set():break
            made+=1 if archive_receipt(job) else 0;step()
        return {'state':'ok','message':'%d von %d Nachweisen erstellt.'%(made,len(jobs_missing))}
    receipt_task('Nachweise erstellen',len(jobs_missing),create)
    return self.send(receipts_overview())

@ROUTES.post('/api/archive-receipt-check')
def post_archive_receipt_check(self,path,d):
    identifier,name=str(d.get('identifier') or ''),str(d.get('file') or '')
    def check(step):
        result=archive_receipts.recheck(ROOT,identifier,name,cancelled=STOP.is_set)
        if result['state']=='missing':SERVICE.mesh_receipts()
        diagnostics.event('archive_receipt_checked',state=result['state']);step()
        return result
    receipt_task('Datei erneut prüfen',1,check)
    return self.send(receipts_overview())

@ROUTES.post('/api/archive-receipt-fetch')
def post_archive_receipt_fetch(self,path,d):
    # 0.5.95: load the file another system vouches for from Archive.org here as well (a second copy). Only known receipts.
    identifier,name=str(d.get('identifier') or ''),str(d.get('file') or '')
    proof=archive_receipts.remote(ROOT,identifier,name)
    if not proof:raise ValueError('Für diese Datei liegt kein gültiger Nachweis eines anderen Systems vor')
    row=portal_sources.entry('internet_archive',identifier,proof['title'] or identifier,'https://archive.org/details/'+urllib.parse.quote(identifier,safe=''),evidence='verbund_receipt')
    with db() as c:
        c.execute('INSERT OR IGNORE INTO portal_items(id,source,external_id,title,title_key,year,page_url,metadata,discovered,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (row['id'],row['source'],row['external_id'],row['title'],portal_sources.title_key(row['title']),None,row['page_url'],json.dumps(row,ensure_ascii=False),time.time(),time.time()))
        saved=portal_sources.archive_saved_detail(c,row['id']).get('detail')
    if not saved or not any(v.get('filename')==name for v in saved.get('video_variants') or []):
        try:detail=portal_sources.fetch_archive_detail(identifier)
        except OSError as e:raise ValueError('Archive.org ist gerade nicht erreichbar; der Dateibestand des Uploads konnte nicht gelesen werden ('+core.safe_error(e)+'). Bitte später erneut versuchen.') from None
        with db() as c:portal_sources.save_archive_detail(c,row['id'],detail)
    with db() as c:result=archive_downloads.enqueue(c,settings()['download_dir'],row['id'],name)
    diagnostics.event('archive_receipt_fetch_queued',created=result.get('created'))
    return self.send({**result,'receipts':receipts_overview()})

@ROUTES.post('/api/encoder-add')
def post_encoder_add(self,path,d):
    # 0.5.94: convert one finished download to a smaller picture (encoder.py). Replacing the original needs the confirmation.
    replace=d.get('replace') is True
    if replace and d.get('confirm') is not True:raise ValueError('Original ersetzen nur nach Bestätigung')
    with db() as c:row=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(str(d.get('id','')),)).fetchone()
    if not row:raise ValueError('Nur fertige Downloads können umgewandelt werden')
    result=encoder.add(ROOT,json.loads(row[0]),str(d.get('profile','')),encoder_tools(),speed=str(d.get('speed') or 'fast'),replace=replace)
    diagnostics.event('encoder_queued',profile=str(d.get('profile','')),replace=replace,source_height=result['source_height'])
    return self.send({**result,'encoder':encoder.listing(ROOT,encoder_tools())})

@ROUTES.post('/api/encoder-cancel')
def post_encoder_cancel(self,path,d):
    encoder.cancel(ROOT,d.get('id'));return self.send(encoder.listing(ROOT,encoder_tools()))

@ROUTES.post('/api/encoder-clear')
def post_encoder_clear(self,path,d):
    encoder.clear(ROOT);return self.send(encoder.listing(ROOT,encoder_tools()))

@ROUTES.post('/api/storage-delete')
def post_storage_delete(self,path,d):
    # One file per request, only after the user's confirmation in the page; pinned titles are refused.
    if d.get('confirm') is not True:raise ValueError('Löschen nur nach Bestätigung')
    with db() as c:
        gone=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(str(d.get('id','')),)).fetchone()
        result=storage_policy.delete(c,str(d.get('id','')),watch_state.states(ROOT),netzkino_downloads.remove_files)
    # 0.5.95: this system no longer vouches for the deleted file; the Verbund learns it at once.
    if gone and archive_receipts.withdraw_job(ROOT,json.loads(gone[0])):SERVICE.mesh_receipts()
    catalog.invalidate_listings(drop=True);unified_index.invalidate()
    diagnostics.event('storage_delete',freed_mb=round(result['freed_bytes']/1048576),files=result['removed_files'])
    with db() as c:return self.send({**result,'storage':storage_policy.overview(c,ROOT,settings()['download_dir'],watch_state.states(ROOT))})

@ROUTES.post('/api/job-remove')
def post_job_remove(self,path,d):
    with db() as c:job_queue.remove(c,str(d.get('id','')))
    return self.send({'ok':True})

# 0.5.73: the page's own scripts, also reachable as /code/<name> (see web/app.js)
SCRIPTS=('/app.js','/direct_start.js','/player.js','/pluto.js','/portal_categories.js','/portal_panel.js','/admin.js','/display.js','/justwatch.js','/rakuten.js','/joyn.js','/toggo.js','/plex.js','/servustv.js','/rtlplus.js','/youtube.js','/netzkino.js','/video_audit.js','/netzkino_detail.js','/netzkino_downloads.js','/unified_catalog.js','/portal_title.js','/offline_button.js','/live_tv.js','/backups.js','/titleview.js','/watchlist.js','/storage.js','/system.js','/crunchyroll.js')

class Server(ThreadingHTTPServer):
    # 0.5.73: the page opens some twenty connections at once (one per script, HTTP/1.0). With the default
    # backlog of 5 the system refuses the surplus while the server is busy, and single scripts such as
    # player.js never arrive (Björn, 12.11.2026: "Skript nicht ladbar (player.js)").
    request_queue_size=128
    daemon_threads=True
    def server_bind(self):
        # HTTPServer resolves socket.getfqdn() here; reverse DNS can stall startup for ~30 s on macOS.
        socketserver.TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]

if __name__=='__main__':
    server=Server((LISTEN,PORT),Handler)
    try:
        trust=netcheck.ensure_trust_store()
        if trust.get('source')!='system':diagnostics.event('tls_trust_store_fallback',source=trust.get('source'),ca_certs=trust.get('ca_certs'))
    except Exception as e:diagnostics.error('tls_trust_store_check_failed',e)
    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()
    try:
        with db() as c:removed=job_queue.dedupe(c)
        if removed:diagnostics.event('download_queue_deduplicated',count=removed)
    except Exception as e:diagnostics.error('download_queue_dedupe_failed',e)
    try:
        with db() as c:moved=netzkino_downloads.migrate_legacy(ROOT,c,settings()['download_dir'])
        if moved:diagnostics.event('netzkino_licensed_jobs_migrated',count=moved)
    except Exception as e:diagnostics.error('netzkino_legacy_migration_failed',e)
    # 30-day offline period: expired Netzkino copies are removed hourly (all platforms).
    threading.Thread(target=netzkino_downloads.loop,args=(db,STOP),daemon=True,name='netzkino_offline_expiry').start()
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        # Reference check and daily catalogue run of every film platform (0.5.84: platform_registry).
        # 0.6.0: one planner (planner.py) instead of two threads per platform; Samsung TV Plus and
        # the Archive.org recognition join it (formerly samsung_tvplus.loop, archive_recognition.loop).
        PLANNER[0]=platform_registry.start_background(platform_context(),STOP,
            extra_catalog=[planner.CatalogJob('samsung',samsung_tvplus)],
            extra_enrichment=[planner.EnrichJob('archive',archive_recognition.background_pending(db),archive_recognition.enrich)])
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        portal_control.Scheduler(db,STOP).start()
        SERVICE.start()
        def prewarm_listing():
            # 0.5.55: the first dashboard page must not wait for the grouping of the whole catalogue.
            for kind in ('movie','series'):
                try:
                    started=time.monotonic()
                    with db() as c:catalog.listing(c,kind=kind,downloaded='all')
                    diagnostics.event('catalog_listing_prewarmed',kind=kind,seconds=round(time.monotonic()-started,2))
                except Exception as e:diagnostics.error('catalog_listing_prewarm_failed',e)
        threading.Thread(target=prewarm_listing,daemon=True,name='catalog_listing_prewarm').start()
        threading.Thread(target=IMDB.loop,daemon=True,name='imdb_archive').start()
        # Weekly verified catalog.db snapshot, 4 automatic ones kept (0.5.56).
        threading.Thread(target=db_backup.loop,args=(ROOT,STOP,diagnostics.event,diagnostics.error),daemon=True,name='db_backup').start()
        threading.Thread(target=ENCODER.loop,args=(STOP,),daemon=True,name='encoder').start()
    url=f'http://127.0.0.1:{server.server_port}';print(url,flush=True)
    if NETWORK:
        print(f'Netzwerkmodus: {LISTEN}:{server.server_port}, Anmeldung erforderlich',flush=True)
        if not ACCESS.configured():print('Einrichtungscode liegt in: '+', '.join(ACCESS.ensure_setup_code()),flush=True)
    INSTANCE.publish(url,VERSION)
    if '--no-browser' not in __import__('sys').argv:webbrowser.open(url)
    def terminate(*_):raise KeyboardInterrupt
    # NAS service scripts stop with SIGTERM; close the server and lock cleanly.
    signal.signal(signal.SIGTERM,terminate)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:STOP.set();server.server_close();INSTANCE.close()
