import subprocess,sys
import json, os, secrets, signal, socketserver, sqlite3, threading, time, webbrowser, urllib.parse, hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import metadata,provider_stats,imdb_archive,artwork,negative_cache
import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment, netzkino_downloads, ytdl_bridge, pluto, pluto_downloads, pluto_enrichment, portal_reference
from version import VERSION
from contextlib import contextmanager
ROOT=Path(os.environ.get('MEDIATHEKATLAS_HOME',Path.home()/'Library'/'Application Support'/'MediathekAtlas' if __import__('sys').platform=='darwin' else Path.home()/'.mediathekatlas'))
ROOT.mkdir(parents=True,exist_ok=True);os.chmod(ROOT,0o700)
# NAS packages listen on the LAN with a fixed port; that always requires a login.
LISTEN=os.environ.get('MEDIATHEKATLAS_LISTEN','127.0.0.1')
PORT=int(os.environ.get('MEDIATHEKATLAS_PORT','0') or 0)
NETWORK=LISTEN not in ('127.0.0.1','localhost','::1') or os.environ.get('MEDIATHEKATLAS_LOGIN')=='1'
MANAGED=os.environ.get('MEDIATHEKATLAS_MANAGED','')
DEFAULT_DOWNLOAD_DIR=os.environ.get('MEDIATHEKATLAS_DOWNLOAD_DIR') or str(Path.home()/'Movies'/'MediathekAtlas')
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
TOKEN=secrets.token_urlsafe(32);STOP=threading.Event()
diagnostics.register_secrets(TOKEN)

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
    diagnostics.register_secrets(stored.get('tmdb'),stored.get('omdb'),stored.get('tvdb'),stored.get('tvdb_pin'),stored.get('mesh_key'),*[p['key'] for p in meshpeer.peer_list(stored)])
    return {'download_dir':DEFAULT_DOWNLOAD_DIR,'tmdb':'','omdb':'','tvdb':'','tvdb_pin':'','auto_catalog':True,'auto_metadata':True,'scan_priority':'balanced','complete_series':True,'metadata_workers':2,'episode_workers':2,'sender_direct_lookup':False,'library_dirs':[],**stored,'imdb_generation':IMDB.updated if 'IMDB' in globals() else 0}

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
        if j['state']=='done' and not netzkino_downloads.is_portal(j):catalog.mark_downloaded(c,j)

def netzkino_download_summary():
    with db() as c:return {**netzkino_downloads.summary(c),'pluto':netzkino_downloads.summary(c,'pluto')}

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
        with db() as c:
            r=c.execute("SELECT payload FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not r:continue
            j=json.loads(r[0])
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
        if j.get('state')=='done' and not local_only:
            try:SERVICE.mesh_done(j)
            except OSError as e:diagnostics.error('mesh_done_failed',e,job_id=j['id'])
        elif claimed[0]:SERVICE.mesh_release(j)

SERVICE=catalog_service.Service(db,settings,STOP,ROOT)
def imdb_updated():
    with db() as c:
        c.execute("UPDATE works SET next_try=0,state=CASE WHEN state='review' THEN 'retry' ELSE state END WHERE state IN ('pending','retry','identified','review')")
        c.execute('DELETE FROM metadata_cache')
    SERVICE.metadata_wake.set()
IMDB=imdb_archive.Archive(ROOT,STOP,imdb_updated)
imdb_archive.ACTIVE=IMDB
_STATUS_CACHE=(0,{})
_TREE_CACHE=(float('-inf'),[])
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
        return {'tree':_TREE_CACHE[1],'loading':_TREE_BUSY,'error':_TREE_ERROR}
def refresh_tree():
    global _TREE_CACHE,_TREE_BUSY,_TREE_ERROR,_TREE_TTL
    started=time.monotonic()
    try:
        with db() as c:rows=catalog.tree(c)
        seconds=time.monotonic()-started
        # The UI polls every 30 s; a 4 s aggregation every minute kept a core busy. Slow catalogues refresh
        # less often, user edits still invalidate the cache immediately.
        with _TREE_LOCK:_TREE_CACHE=(time.monotonic(),rows);_TREE_ERROR='';_TREE_TTL=max(60,min(900,seconds*60))
        diagnostics.event('catalog_tree_complete',seconds=round(seconds,2),categories=len(rows),next_seconds=round(_TREE_TTL))
    except Exception as e:
        diagnostics.error('catalog_tree_failed',e)
        with _TREE_LOCK:_TREE_ERROR=core.safe_error(e);_TREE_CACHE=(time.monotonic(),_TREE_CACHE[1])
    finally:
        with _TREE_LOCK:_TREE_BUSY=False
_RECOGNITION={'at':float('-inf'),'rows':[],'busy':False,'error':''}
def recognition():
    # Grouping 700k works by channel takes seconds; compute in the background and reuse for 10 minutes.
    with _TREE_LOCK:
        if not _RECOGNITION['busy'] and time.monotonic()-_RECOGNITION['at']>600:
            _RECOGNITION['busy']=True;threading.Thread(target=refresh_recognition,daemon=True,name='catalog_recognition').start()
        return {'channels':_RECOGNITION['rows'],'loading':_RECOGNITION['busy'],'error':_RECOGNITION['error']}
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
    def do_GET(self):
        try:self.get()
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            diagnostics.error('http_get_failed',e,endpoint=urllib.parse.urlsplit(self.path).path)
            try:self.send({'error':core.safe_error(e)},500)
            except (BrokenPipeError,ConnectionResetError):pass
    def get(self):
        if not self.valid_host():return self.send({'error':'Ungültiger Host'},403)
        path=urllib.parse.urlsplit(self.path).path
        if path=='/icon.svg':return self.send((Path(__file__).parent/'assets'/'icon.svg').read_bytes(),ctype='image/svg+xml')
        if path in ('/style.css','/login.js'):
            return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript' if path.endswith('js') else 'text/css')
        if path.startswith('/api/peer/'):return self.peer_get(path)
        if path=='/api/login-state':
            if not NETWORK:return self.send({'required':False})
            return self.send({'required':True,'configured':ACCESS.configured(),'setup_files':ACCESS.ensure_setup_code() if not ACCESS.configured() else []})
        if not self.authorized():
            if path=='/':return self.send((Path(__file__).parent/'web'/'login.html').read_text().replace('__VERSION__',VERSION).encode(),ctype='text/html; charset=utf-8')
            return self.send({'error':'Anmeldung erforderlich','login':True},401)
        if path=='/':
            body=(Path(__file__).parent/'web'/'index.html').read_text().replace('__TOKEN__',TOKEN).replace('__VERSION__',VERSION)
            return self.send(body.encode(),ctype='text/html; charset=utf-8')
        if path in ('/app.js','/player.js','/pluto.js','/portal_categories.js','/netzkino.js','/video_audit.js','/netzkino_detail.js','/netzkino_downloads.js','/unified_catalog.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')
        if path=='/titleview.js':return self.send((Path(__file__).parent/'web'/'titleview.js').read_bytes(),ctype='text/javascript')
        if path=='/api/download-file':return self.download_file(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
        if path=='/api/stream':return self.stream(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Sitzung abgelaufen'},403)
        if path=='/api/video-audit':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:
                video_backfill.initialize(c)
                return self.send(video_backfill.status(c,q.get('offset',['0'])[0]))
        if path=='/api/pluto':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                if q.get('view',[''])[0]=='episodes':data=pluto.episodes(ROOT,q.get('series',[''])[0])
                else:data=pluto.listing(ROOT,view=q.get('view',['movies'])[0],query=q.get('q',[''])[0],
                                        offset=q.get('offset',['0'])[0],limit=q.get('limit',['60'])[0],
                                        genre=q.get('genre',[''])[0][:80],sort=q.get('sort',['title'])[0],
                                        collection=q.get('collection',[''])[0][:20])
            except ValueError as e:return self.send({'error':str(e)},404)
            data['status']=pluto.state(ROOT)
            return self.send(data)
        if path=='/api/netzkino-details':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send(netzkino_details.get(ROOT,q.get('id',[''])[0]))
        if path=='/api/pluto-details':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:return self.send(pluto.item(ROOT,q.get('id',[''])[0]))
            except ValueError as e:return self.send({'error':str(e)},404)
        if path=='/api/pluto-downloads':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:result=netzkino_downloads.listing(c,item_id=q.get('id',[''])[0] or None,origin='pluto')
            result['ffmpeg']=bool(downloads.tool('ffmpeg'))
            return self.send(result)
        if path=='/api/netzkino-downloads':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:result=netzkino_downloads.listing(c,item_id=q.get('id',[''])[0] or None)
            result['ytdl']=ytdl_bridge.status()
            return self.send(result)
        if path=='/api/netzkino-reference-report':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send(netzkino_enrichment.cached(ROOT,q.get('id',[''])[0]))
        if path=='/api/netzkino-grouped':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            data=netzkino.grouped_catalog(ROOT,view=q.get('view',['movies'])[0],
                series_key=q.get('series_key',[''])[0],
                query=q.get('q',[''])[0],origin=q.get('origin',['all'])[0],
                offset=q.get('offset',['0'])[0],limit=q.get('limit',['80'])[0],
                genre=q.get('genre',[''])[0],sort=q.get('sort',['updated'])[0],
                collection=q.get('collection',[''])[0][:20])
            data['status']=netzkino.state(ROOT)
            return self.send(data)
        if path=='/api/netzkino':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0],80,q.get('offset',['0'])[0]),'status':netzkino.state(ROOT),'total':netzkino.count_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0])})
        if path=='/api/play':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);ref={k:q.get(k,[''])[0] for k in ('offer','job','netzkino','pluto')}
            try:
                with db() as c:source=streaming.resolve(c,root=ROOT,**ref)
                info=streaming.plan(source)
            except ValueError as e:return self.send({'error':str(e)},404)
            base='/api/stream?'+urllib.parse.urlencode({k:v for k,v in ref.items() if v})
            if info['origin']=='local':info['src']=base+('&raw=1' if info['mode']=='direct' else '')
            else:info['src']=info.pop('url') if info['mode']=='direct' else base
            info['remux']=base;info['ffmpeg']=bool(downloads.tool('ffmpeg'))
            diagnostics.event('playback_start',mode=info['mode'],origin=info['origin'],hls=info.get('hls',False),provider=info.get('provider','mediathek'))
            return self.send(info)
        if path=='/api/logs':return self.send({'text':diagnostics.tail(),'sync':SERVICE.current})
        if path=='/api/diagnostics':
            # Catalogue counts and the cached recognition per channel make the export evaluable on its own.
            try:overview={'catalog':{k:v for k,v in catalog_status().items() if k!='sync'},'recognition':recognition()}
            except Exception as e:overview={'catalog_error':core.safe_error(e)}
            return self.send(diagnostics.export({**overview,'imdb':IMDB.status(),'provider_statistics':provider_stats.snapshot(),'sync':SERVICE.current,'metadata':SERVICE.metadata_status,'mesh':SERVICE.mesh_status,'providers':[name for name,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if settings().get(k)] or ['Wikidata'],'netzkino_downloads':netzkino_download_summary(),'ytdl_nightly':ytdl_bridge.status(),'pluto':pluto.state(ROOT),'threads':[t.name for t in threading.enumerate()]}),ctype='application/zip')
        if path=='/api/tools':return self.send(runtime_tools.report(refresh=True))
        if path=='/api/provider-stats':return self.send(provider_stats.snapshot())
        if path=='/api/subscriptions':
            with db() as c:return self.send({'items':subscriptions.get_all(c),'device_time':time.time()})
        if path=='/api/review':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:return self.send(catalog.review_listing(c,query=q.get('query',[''])[0],state=q.get('state',['open'])[0],offset=q.get('offset',[0])[0]))
        if path=='/api/archive-companion':
            status=archive_companion.read_status()
            if NETWORK:status['ui_url']=None
            return self.send(status)
        if path=='/api/portal-policy':
            return self.send({'sources':{k:portal_metadata_policy.source_policy(k)
                          for k in portal_metadata_policy.PROVENANCE},
                          'filename':portal_metadata_policy.filename_rules(),
                          'reference_order':portal_metadata_policy.PRIORITY})
        if path=='/api/portals':
            with db() as c:
                result=portal_sources.state(c)
                result['platform_control']=portal_control.source_status(c)
                result['archive_scopes']=portal_control.list_scopes(c)
                offline={name:netzkino_downloads.summary(c,name) for name in ('netzkino','pluto')}
            # Film platforms with own catalogues (dashboard cards): catalogue, IMDb/TVDB check, offline copies.
            nk=netzkino.state(ROOT);pl=pluto.state(ROOT)
            result['film_platforms']=[
                {'source':'netzkino','name':'Netzkino','titles':nk.get('catalog_count',0),'last_success':nk.get('last_success',0),
                 'last_result':nk.get('last_result'),'running':nk.get('running'),'reference':netzkino_enrichment.metrics(ROOT),
                 'offline':offline['netzkino'],'offline_days':netzkino_downloads.OFFLINE_DAYS},
                {'source':'pluto','name':'Pluto TV','titles':(pl.get('movies',0) or 0)+(pl.get('series',0) or 0),
                 'channels':pl.get('channels',0),'last_success':pl.get('last_success',0),'last_result':pl.get('last_result'),
                 'running':pl.get('running'),'reference':pluto_enrichment.metrics(ROOT),
                 'offline':offline['pluto'],'offline_days':pluto_downloads.OFFLINE_DAYS}]
            return self.send(result)
        if path=='/api/portal-items':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:
                result=portal_sources.listing(c,source=q.get('source',[''])[0],
                            query=q.get('query',[''])[0],
                            offset=q.get('offset',['0'])[0],
                            locale=q.get('locale',['all'])[0])
            return self.send(result)
        if path=='/api/portal-archive-detail':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:
                item_id=q.get('id',[''])[0]
                result=portal_sources.archive_saved_detail(c,item_id)
            return self.send(result)
        if path=='/api/catalog':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:result=catalog.listing(c,query=q.get('query',[''])[0],kind=q.get('kind',[''])[0],genre=q.get('genre',[''])[0],show=q.get('show',[''])[0],offset=q.get('offset',[0])[0],archive=q.get('archive',['0'])[0]=='1',state=q.get('state',[''])[0],sort=q.get('sort',['title'])[0],downloaded=q.get('downloaded',['hide'])[0],collection=q.get('collection',[''])[0])
            return self.send(result)
        if path=='/api/catalog-tree':
            return self.send(catalog_tree())
        if path=='/api/recognition':return self.send(recognition())
        if path=='/api/show':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                with db() as c:return self.send(catalog.show_detail(c,q.get('show',[''])[0][:200],archive=q.get('archive',['0'])[0]=='1'))
            except ValueError as e:return self.send({'error':str(e)},404)
        if path=='/api/alternatives':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:return self.send({'items':catalog.alternatives(c,q.get('work_id',[''])[0])})
        if path=='/api/availability':
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
        if path=='/api/state':
            s=settings();return self.send({'artwork_checked':SERVICE.artwork_checked,'imdb':IMDB.status(),'jobs':jobs(),'settings':{'download_dir':s['download_dir'],'tmdb_set':bool(s.get('tmdb')),'omdb_set':bool(s.get('omdb')),'tvdb_set':bool(s.get('tvdb')),'tvdb_pin_set':bool(s.get('tvdb_pin')),'auto_catalog':s['auto_catalog'],'auto_metadata':s['auto_metadata'],'scan_priority':s.get('scan_priority','balanced'),'complete_series':s.get('complete_series',True),'metadata_workers':s.get('metadata_workers',2),'episode_workers':s.get('episode_workers',2),'sender_direct_lookup':s.get('sender_direct_lookup',False),'library_dirs':s.get('library_dirs',[]),'mesh_dir':s.get('mesh_dir',''),'mesh_name':s.get('mesh_name',''),'mesh_peers':[p['url'] for p in meshpeer.peer_list(s)],'mesh_shared':NETWORK and meshpeer.valid_key(s.get('mesh_key'))},'tools':{'ffmpeg':bool(downloads.tool('ffmpeg')),'ffprobe':bool(downloads.tool('ffprobe'))},'runtime':runtime_tools.report(),'catalog':catalog_status(),'metadata':SERVICE.metadata_status,'provider_pauses':{'omdb':metadata.omdb_status(s.get('omdb','')),
                    'tmdb':metadata.network_provider_status('TMDB'),
                    'wikidata':metadata.network_provider_status('Wikidata')},'reclassification':SERVICE.reclassification,'server':{'network':NETWORK,'managed':MANAGED,'version':VERSION},'mesh':SERVICE.mesh_status})
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
                                                  netzkino=q.get('netzkino',[''])[0],pluto=q.get('pluto',[''])[0],root=ROOT)
        except ValueError as e:return self.send({'error':str(e)},404)
        if q.get('raw',['0'])[0]=='1':
            if source['kind']!='file':return self.send({'error':'Nur lokale Dateien können direkt geladen werden'},400)
            return self.send_file(Path(source['path']).resolve(),True)
        if self.command=='HEAD':return self.send(b'',ctype='video/mp4')
        try:start=max(0.0,float(q.get('t',['0'])[0] or 0))
        except ValueError:start=0.0
        try:
            proc=streaming.start(streaming.command(source,start,streaming.audio_copy(source)),q.get('session',[''])[0][:64])
        except RuntimeError as e:return self.send({'error':str(e)},429)
        except (ValueError,OSError) as e:return self.send({'error':core.safe_error(e)},503)
        sent=0
        try:
            first=proc.stdout.read1(65536) if hasattr(proc.stdout,'read1') else proc.stdout.read(65536)
            if not first:
                code,err=streaming.finish(proc)
                diagnostics.event('playback_failed',level='ERROR',origin=source['kind'],code=code,detail=err)
                return self.send({'error':'Wiedergabe konnte nicht gestartet werden. Details im Live-Protokoll.'},502)
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
    def do_POST(self):
        global _TREE_CACHE,_STATUS_CACHE
        if not self.valid_host():return self.send({'error':'Ungültige Sitzung'},403)
        if NETWORK and self.path=='/api/login':return self.login()
        if not self.authorized():return self.send({'error':'Anmeldung erforderlich','login':True},401)
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Ungültige Sitzung'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            # Netzkino recordings arrive in parts of a few MB (answer texts only, no headers).
            if not 0<length<=(8*1024*1024 if self.path=='/api/netzkino-recording' else 100000):raise ValueError('Ungültige Anfragegröße')
            d=json.loads(self.rfile.read(length));path=self.path
            if NETWORK and path=='/api/logout':
                ACCESS.logout(self.session());return self.send({'ok':True},cookies=[self.session_cookie('',0)])
            if NETWORK and path=='/api/password':
                token=ACCESS.change_password(str(d.get('current','')),str(d.get('new','')))
                diagnostics.event('access_password_changed')
                return self.send({'ok':True},cookies=[self.session_cookie(token)])
            if path=='/api/pluto-sync':
                return self.send({'started':pluto.start_sync(ROOT)})
            if path=='/api/pluto-auto':
                return self.send({'status':pluto.set_auto(ROOT,d.get('enabled'))})
            if path=='/api/netzkino-recording':
                return self.send(netzkino.import_recording(ROOT,d.get('entries')))
            if path=='/api/netzkino-add':
                return self.send({'item':netzkino.add(ROOT,d.get('title'),d.get('url'))})
            if path=='/api/netzkino-remove':
                return self.send({'removed':netzkino.remove(ROOT,d.get('id'))})
            if path=='/api/netzkino-sync':
                return self.send({'started':netzkino.start_sync(ROOT)})
            if path=='/api/netzkino-auto':
                return self.send({'status':netzkino.set_auto(ROOT,d.get('enabled'))})
            if path=='/api/shutdown' and MANAGED:raise ValueError('Der Dienst wird vom NAS verwaltet. Bitte im Paket-Zentrum bzw. App Center stoppen.')
            if path=='/api/shutdown':
                self.send({'ok':True});STOP.set()
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path=='/api/test-tvdb':
                import tvdb
                return self.send(tvdb.test_access(settings().get('tvdb',''),settings().get('tvdb_pin','')))
            if path=='/api/test-omdb':return self.send(metadata.test_omdb(settings().get('omdb','')))
            if path=='/api/portal-controls':
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
            if path=='/api/portal-scope-add':
                with db() as c:
                    scope_id=portal_control.add_scope(c,d.get('kind'),d.get('value'),
                                 priority=d.get('priority'),page_budget=d.get('page_budget',8))
                return self.send({'id':scope_id,'ok':True})
            if path=='/api/portal-scope-control':
                with db() as c:
                    portal_control.control_scope(c,d.get('id'),d.get('action'),
                                                 priority=d.get('priority'))
                return self.send({'ok':True})
            if path=='/api/portal-search':
                if d.get('source')!='internet_archive':
                    raise ValueError('Nur Internet Archive bietet hier eine dokumentierte Such-API')
                rows=portal_sources.search_archive(d.get('query',''))
                with db() as c:
                    saved=portal_sources.save(c,rows,query=d.get('query',''))
                diagnostics.event('portal_metadata_import',source='internet_archive',items=len(saved),
                                  mode='user_activated')
                return self.send({'added_or_updated':len(saved),
                                  'access':'official_site_only','download_enabled':False})
            if path=='/api/portal-archive-inspect':
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
            if path=='/api/portal-archive-probe':
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
            if path=='/api/netzkino-download-add':
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
                    else:result=netzkino_downloads.enqueue(c,ROOT,root,item_id)
                diagnostics.event('netzkino_download_enqueued',created=result['created'],licensed_file=bool(d.get('file_url')))
                return self.send(result)
            if path=='/api/pluto-enrich':
                with SERVICE.provider_slots:
                    result=pluto_enrichment.enrich(ROOT,str(d.get('id','')),settings(),force=d.get('force') is True)
                diagnostics.event('pluto_reference_check',status=result['status'],candidates=len(result.get('references',[])))
                return self.send(result)
            if path=='/api/pluto-download-add':
                item_id=str(d.get('id',''))
                # Classification and metadata like an ARD/ZDF download: IMDb/TVDB/TMDB check first
                # (cached when fresh). A provider failure never blocks the download.
                try:
                    with SERVICE.provider_slots:pluto_enrichment.enrich(ROOT,item_id,settings())
                except Exception as e:diagnostics.error('pluto_download_enrich_failed',e)
                with db() as c:result=pluto_downloads.enqueue(c,ROOT,settings()['download_dir'],item_id)
                diagnostics.event('pluto_download_enqueued',created=result['created'])
                return self.send(result)
            if path in ('/api/netzkino-download-action','/api/offline-download-action'):
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
            if path=='/api/netzkino-enrich':
                item_id=str(d.get('id',''))
                with SERVICE.provider_slots:
                    result=netzkino_enrichment.enrich(ROOT,item_id,settings(),
                                                        force=d.get('force') is True)
                diagnostics.event('netzkino_reference_check',status=result['status'],
                    candidates=len(result.get('references',[])),
                    checked_providers=len(result.get('provider_checks',[])))
                return self.send(result)
            if path=='/api/netzkino-metadata-probe':
                item_id=str(d.get('id',''))
                editorial=netzkino_details.get(ROOT,item_id)
                result=yt_dlp_probe.probe(editorial['page_url'],editorial['details'])
                diagnostics.event('netzkino_metadata_validation',status=result['status'],
                                  conflicts=len(result.get('warnings',[])))
                return self.send(result)
            if path=='/api/netzkino-watch':
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
            if path=='/api/portal-netzkino-add':
                item=portal_sources.manual_netzkino(d.get('title',''),
                          d.get('url',''),d.get('year'))
                with db() as c:portal_sources.save(c,[item])
                diagnostics.event('portal_manual_link_added',source='netzkino')
                return self.send({'item':item,'ok':True})
            if path=='/api/search':
                found=core.search(d.get('query',''),d.get('channel',''),d.get('offset',0))
                with db() as c:catalog.ingest(c,found['results'])
                with _TREE_LOCK:_TREE_CACHE=(float('-inf'),_TREE_CACHE[1])
                return self.send({'imported':len(found['results'])})
            if path=='/api/sync':
                SERVICE.restart.set();SERVICE.wake.set();diagnostics.event('sync_requested');return self.send({'ok':True})
            if path in ('/api/library-locate','/api/library-relink'):
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
            if path=='/api/subscription-add':
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    sub_id=subscriptions.add(c,d)
                SERVICE.subscription_wake.set()
                diagnostics.event('subscription_created',id=sub_id,kind=d.get('kind'),
                                  mode=d.get('mode','availability'))
                return self.send({'ok':True,'id':sub_id})
            if path=='/api/subscription-action':
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    subscriptions.change(c,str(d.get('id') or ''),str(d.get('action') or ''))
                SERVICE.subscription_wake.set()
                diagnostics.event('subscription_modified',action=d.get('action'))
                return self.send({'ok':True})
            if path=='/api/subscription-check':
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    results=subscriptions.run_due(c,settings()['download_dir'],
                                                  force_id=str(d.get('id') or '') or None)
                diagnostics.event('subscription_checked',subscriptions=len(results),
                                  queued=sum(x['queued'] for x in results))
                return self.send({'ok':True,'items':results})
            if path=='/api/metadata-priority':
                ids=d.get('ids',[])
                if not isinstance(ids,list) or len(ids)>1000:raise ValueError('Ungültige Auswahl')
                with db() as c:count=catalog.prioritize(c,ids,d.get('show',''))
                SERVICE.metadata_wake.set();return self.send({'queued':count,'enabled':settings()['auto_metadata']})
            if path in ('/api/series-plan','/api/series-download'):
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
            if path=='/api/save-metadata':
                m=core.validate_meta(d['metadata'],require_episode=False);m['state']='user_confirmed'
                with db() as c:
                    o=c.execute('SELECT work_id FROM offers WHERE id=?',(d['id'],)).fetchone()
                    if not o:raise ValueError('Katalogeintrag nicht gefunden')
                    SERVICE.mesh_manual(c,o[0],catalog.save_metadata(c,o[0],m) or o[0],m)
                _TREE_CACHE=(float('-inf'),[]);_STATUS_CACHE=(0,{})
                return self.send({'ok':True})
            if path=='/api/candidates':
                config=settings()
                cachekey=hashlib.sha256(json.dumps(['v045',config.get('imdb_generation'),d['id'],d['metadata'],config.get('tmdb'),config.get('omdb'),config.get('tvdb'),config.get('tvdb_pin')],sort_keys=True).encode()).hexdigest()
                with db() as c:cached=c.execute('SELECT payload FROM metadata_cache WHERE id=? AND checked>?',(cachekey,time.time()-86400)).fetchone()
                # A user-triggered search must bypass old provider results and negative caches.
                # The automatic worker still uses the separate 24h metadata cache.
                result=core.candidates(record(d['id']),d['metadata'],{**config,'_force_provider_refresh':True})
                if not result['warnings'] and not result.get('deferred_providers'):
                    with db() as c:c.execute('INSERT OR REPLACE INTO metadata_cache VALUES(?,?,?)',(cachekey,json.dumps(result),time.time()))
                return self.send(result)
            if path=='/api/preview':return self.send({'path':str(core.target(settings()['download_dir'],d['metadata'],d['id']))})
            if path=='/api/settings':
                s=settings();previous=dict(s)
                if d.get('download_dir'):
                    p=Path(d['download_dir']).expanduser()
                    if not p.is_absolute():raise ValueError('Bitte absoluten Zielpfad angeben')
                    s['download_dir']=str(p)
                for k in ('tmdb','omdb','tvdb','tvdb_pin'):
                    if k in d and d[k].strip():s[k]=d[k].strip()
                    if d.get('clear_'+k):s[k]=''
                for k in ('auto_catalog','auto_metadata','complete_series','sender_direct_lookup'):
                    if k in d:s[k]=bool(d[k])
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
            if path=='/api/mesh-direct':
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
            if path=='/api/download':
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
            if path=='/api/imdb-update':return self.send({'queued':IMDB.request()})
            if path=='/api/artwork-priority':
                ids=d.get('ids',[])
                if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise ValueError('Ungültige Auswahl')
                with db() as c:
                    for wid in ids[:48]:c.execute('INSERT OR IGNORE INTO artwork_checks SELECT id,? FROM works WHERE id=?',(-time.time(),wid))
                return self.send({'ok':True})
            if path=='/api/open-download' and NETWORK:raise ValueError('Die Datei liegt auf dem NAS. Bitte über File Station bzw. die Netzwerkfreigabe öffnen.')
            if path=='/api/open-download':
                with db() as c:row=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(d['id'],)).fetchone()
                if not row:raise ValueError('Nur abgeschlossene Downloads können geöffnet werden')
                job=json.loads(row[0]);target=Path(job.get('path') or job['target']).resolve()
                if not target.is_file():raise ValueError('Datei wurde verschoben oder ist nicht verfügbar')
                if sys.platform=='darwin':subprocess.Popen(['/usr/bin/open',str(target)])
                elif os.name=='nt':os.startfile(str(target))
                else:subprocess.Popen(['xdg-open',str(target)])
                return self.send({'ok':True})
            if path=='/api/cancel':
                with db() as c:c.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('queued','downloading','tagging')",(d['id'],))
                return self.send({'ok':True})
            if path=='/api/retry':
                with db() as c:
                    r=c.execute("SELECT payload FROM jobs WHERE id=? AND state IN ('error','cancelled','interrupted','remote')",(d['id'],)).fetchone()
                if not r:raise ValueError('Auftrag ist nicht wiederholbar')
                j=json.loads(r[0]);j.update(id=secrets.token_hex(8),state='queued',received=0,total=0,error='');put_job(j);return self.send({'ok':True})
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

class Server(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves socket.getfqdn() here; reverse DNS can stall startup for ~30 s on macOS.
        socketserver.TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]

if __name__=='__main__':
    server=Server((LISTEN,PORT),Handler)
    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()
    try:
        with db() as c:moved=netzkino_downloads.migrate_legacy(ROOT,c,settings()['download_dir'])
        if moved:diagnostics.event('netzkino_licensed_jobs_migrated',count=moved)
    except Exception as e:diagnostics.error('netzkino_legacy_migration_failed',e)
    # 30-day offline period: expired Netzkino copies are removed hourly (all platforms).
    threading.Thread(target=netzkino_downloads.loop,args=(db,STOP),daemon=True,name='netzkino_offline_expiry').start()
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        # IMDb/TVDB/TMDB/OMDb/Wikidata for every Netzkino title, automatically and gently.
        threading.Thread(target=netzkino_enrichment.loop,args=(ROOT,settings,SERVICE.provider_slots,STOP),
                         daemon=True,name='netzkino_auto_enrichment').start()
        threading.Thread(target=pluto_enrichment.loop,args=(ROOT,settings,SERVICE.provider_slots,STOP),
                         daemon=True,name='pluto_auto_enrichment').start()
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        threading.Thread(target=netzkino.loop,args=(ROOT,STOP),daemon=True,name='netzkino_catalog_scheduler').start()
        threading.Thread(target=pluto.loop,args=(ROOT,STOP),daemon=True,name='pluto_catalog_scheduler').start()
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        portal_control.Scheduler(db,STOP).start()
        SERVICE.start()
        threading.Thread(target=IMDB.loop,daemon=True,name='imdb_archive').start()
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
