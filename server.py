import subprocess,sys
import json, os, secrets, signal, sqlite3, threading, time, webbrowser, urllib.parse, hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import metadata,provider_stats,imdb_archive,artwork
import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal
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
diagnostics.event('application_start',version=VERSION,network=NETWORK,managed=MANAGED or None)
ACCESS=access.Access(ROOT,[DEFAULT_DOWNLOAD_DIR]) if NETWORK else None
TOKEN=secrets.token_urlsafe(32);STOP=threading.Event()
diagnostics.register_secrets(TOKEN)

@contextmanager
def db():
    c=sqlite3.connect(ROOT/'catalog.db',timeout=20);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()
with db() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT);CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT);CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,payload TEXT);CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL);')
    catalog.initialize(c)
    if not catalog.get_state(c,'legacy_imported',False):
        catalog.ingest(c,[json.loads(r[0]) for r in c.execute('SELECT payload FROM records').fetchall()])
        catalog.set_state(c,'legacy_imported',True)
    for completed in c.execute("SELECT payload FROM jobs WHERE state='done'").fetchall():catalog.mark_downloaded(c,json.loads(completed[0]))
    c.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('queued','downloading','tagging')")

def settings():
    with db() as c:r=c.execute('SELECT payload FROM settings WHERE id=1').fetchone()
    stored=json.loads(r[0]) if r else {}
    diagnostics.register_secrets(stored.get('tmdb'),stored.get('omdb'),stored.get('tvdb'),stored.get('tvdb_pin'))
    return {'download_dir':DEFAULT_DOWNLOAD_DIR,'tmdb':'','omdb':'','tvdb':'','tvdb_pin':'','auto_catalog':True,'auto_metadata':True,**stored,'imdb_generation':IMDB.updated if 'IMDB' in globals() else 0}

def record(i):
    with db() as c:
        found=catalog.source(c,i)
        if found:return found
        r=c.execute('SELECT payload FROM records WHERE id=?',(i,)).fetchone()
    if not r:raise ValueError('Eintrag nicht gefunden; Suche wiederholen')
    return json.loads(r[0])

def put_job(j):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(j['id'],json.dumps(j),j['state']))
        if j['state']=='done':catalog.mark_downloaded(c,j)

def jobs():
    with db() as c:rows=c.execute('SELECT payload,state FROM jobs ORDER BY rowid DESC LIMIT 100').fetchall()
    return [{**json.loads(r[0]),'state':r[1]} for r in rows]

def worker():
    while not STOP.wait(.5):
        with db() as c:
            r=c.execute("SELECT payload FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not r:continue
            j=json.loads(r[0]);c.execute("UPDATE jobs SET state='downloading' WHERE id=?",(j['id'],))
        def cancelled():
            with db() as c:x=c.execute('SELECT state FROM jobs WHERE id=?',(j['id'],)).fetchone()
            return not x or x[0]=='cancelled'
        def update(state,received=0,total=0,**kw):
            if cancelled():return
            j.update(state=state,received=received,total=total,**kw);put_job(j)
        try:
            if not all(j['metadata'].get(k) for k in ('poster','fanart')):
                pictures,errors=artwork.lookup(j['metadata'],settings())
                for field in ('poster','fanart','artwork_provider'):
                    if pictures.get(field) and not j['metadata'].get(field):j['metadata'][field]=pictures[field]
                if errors:diagnostics.event('download_artwork_warning',errors=errors)
            if not cancelled():downloads.run(j['source'],j['metadata'],j['root'],j['quality'],update,cancelled)
        except Exception as e:
            diagnostics.error('download_failed',e,job_id=j['id'])
            if not cancelled():j.update(state='error',error=core.safe_error(e));put_job(j)

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
def catalog_status():
    global _STATUS_CACHE
    snapshot=_STATUS_CACHE
    if not snapshot[1] or time.monotonic()-snapshot[0]>10:
        with db() as c:snapshot=(time.monotonic(),catalog.stats(c))
        _STATUS_CACHE=snapshot
    # A concurrent metadata save can invalidate the shared cache at any point.
    # Return our complete local snapshot, never the newly emptied shared cache.
    return {**snapshot[1],'sync':SERVICE.current or snapshot[1].get('sync',{})}

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
        if path=='/api/login-state':
            if not NETWORK:return self.send({'required':False})
            return self.send({'required':True,'configured':ACCESS.configured(),'setup_files':ACCESS.ensure_setup_code() if not ACCESS.configured() else []})
        if not self.authorized():
            if path=='/':return self.send((Path(__file__).parent/'web'/'login.html').read_text().replace('__VERSION__',VERSION).encode(),ctype='text/html; charset=utf-8')
            return self.send({'error':'Anmeldung erforderlich','login':True},401)
        if path=='/':
            body=(Path(__file__).parent/'web'/'index.html').read_text().replace('__TOKEN__',TOKEN).replace('__VERSION__',VERSION)
            return self.send(body.encode(),ctype='text/html; charset=utf-8')
        if path=='/app.js':return self.send((Path(__file__).parent/'web'/'app.js').read_bytes(),ctype='text/javascript')
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Sitzung abgelaufen'},403)
        if path=='/api/logs':return self.send({'text':diagnostics.tail(),'sync':SERVICE.current})
        if path=='/api/diagnostics':
            return self.send(diagnostics.export({'imdb':IMDB.status(),'provider_statistics':provider_stats.snapshot(),'sync':SERVICE.current,'metadata':SERVICE.metadata_status,'mesh':SERVICE.mesh_status,'providers':[name for name,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if settings().get(k)] or ['Wikidata'],'threads':[t.name for t in threading.enumerate()]}),ctype='application/zip')
        if path=='/api/tools':return self.send(runtime_tools.report(refresh=True))
        if path=='/api/provider-stats':return self.send(provider_stats.snapshot())
        if path=='/api/review':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:return self.send(catalog.review_listing(c,query=q.get('query',[''])[0],state=q.get('state',['open'])[0],offset=q.get('offset',[0])[0]))
        if path=='/api/catalog':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:result=catalog.listing(c,query=q.get('query',[''])[0],kind=q.get('kind',[''])[0],genre=q.get('genre',[''])[0],show=q.get('show',[''])[0],offset=q.get('offset',[0])[0],archive=q.get('archive',['0'])[0]=='1',state=q.get('state',[''])[0],sort=q.get('sort',['title'])[0],downloaded=q.get('downloaded',['hide'])[0],collection=q.get('collection',[''])[0])
            return self.send(result)
        if path=='/api/catalog-tree':
            return self.send(catalog_tree())
        if path=='/api/alternatives':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with db() as c:return self.send({'items':catalog.alternatives(c,q.get('work_id',[''])[0])})
        if path=='/api/state':
            s=settings();return self.send({'artwork_checked':SERVICE.artwork_checked,'imdb':IMDB.status(),'jobs':jobs(),'settings':{'download_dir':s['download_dir'],'tmdb_set':bool(s.get('tmdb')),'omdb_set':bool(s.get('omdb')),'tvdb_set':bool(s.get('tvdb')),'tvdb_pin_set':bool(s.get('tvdb_pin')),'auto_catalog':s['auto_catalog'],'auto_metadata':s['auto_metadata'],'mesh_dir':s.get('mesh_dir',''),'mesh_name':s.get('mesh_name','')},'tools':{'ffmpeg':bool(downloads.tool('ffmpeg')),'ffprobe':bool(downloads.tool('ffprobe'))},'runtime':runtime_tools.report(),'catalog':catalog_status(),'metadata':SERVICE.metadata_status,'provider_pauses':{'omdb':metadata.omdb_status(s.get('omdb',''))},'reclassification':SERVICE.reclassification,'server':{'network':NETWORK,'managed':MANAGED,'version':VERSION},'mesh':SERVICE.mesh_status})
        self.send({'error':'Nicht gefunden'},404)
    def do_POST(self):
        global _TREE_CACHE,_STATUS_CACHE
        if not self.valid_host():return self.send({'error':'Ungültige Sitzung'},403)
        if NETWORK and self.path=='/api/login':return self.login()
        if not self.authorized():return self.send({'error':'Anmeldung erforderlich','login':True},401)
        if self.headers.get('X-Atlas-Token')!=TOKEN:return self.send({'error':'Ungültige Sitzung'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=100000:raise ValueError('Ungültige Anfragegröße')
            d=json.loads(self.rfile.read(length));path=self.path
            if NETWORK and path=='/api/logout':
                ACCESS.logout(self.session());return self.send({'ok':True},cookies=[self.session_cookie('',0)])
            if NETWORK and path=='/api/password':
                token=ACCESS.change_password(str(d.get('current','')),str(d.get('new','')))
                diagnostics.event('access_password_changed')
                return self.send({'ok':True},cookies=[self.session_cookie(token)])
            if path=='/api/shutdown' and MANAGED:raise ValueError('Der Dienst wird vom NAS verwaltet. Bitte im Paket-Zentrum bzw. App Center stoppen.')
            if path=='/api/shutdown':
                self.send({'ok':True});STOP.set()
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path=='/api/test-tvdb':
                import tvdb
                return self.send(tvdb.test_access(settings().get('tvdb',''),settings().get('tvdb_pin','')))
            if path=='/api/test-omdb':return self.send(metadata.test_omdb(settings().get('omdb','')))
            if path=='/api/search':
                found=core.search(d.get('query',''),d.get('channel',''),d.get('offset',0))
                with db() as c:catalog.ingest(c,found['results'])
                with _TREE_LOCK:_TREE_CACHE=(float('-inf'),_TREE_CACHE[1])
                return self.send({'imported':len(found['results'])})
            if path=='/api/sync':
                SERVICE.restart.set();SERVICE.wake.set();diagnostics.event('sync_requested');return self.send({'ok':True})
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
                if cached:return self.send(json.loads(cached[0]))
                result=core.candidates(record(d['id']),d['metadata'],config)
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
                for k in ('auto_catalog','auto_metadata'):
                    if k in d:s[k]=bool(d[k])
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
            if path=='/api/download':
                if d.get('confirmed') is not True:raise ValueError('Metadaten zuerst prüfen und bestätigen')
                m=core.validate_meta(d['metadata']);m['state']='user_confirmed';m['confirmed_at']=time.time()
                row=record(d['id'])
                choices=catalog.links(row)
                if d.get('quality','best')=='best' and choices:row['_download_url']=choices[0]['url']
                with db() as c:
                    o=c.execute('SELECT work_id FROM offers WHERE id=?',(d['id'],)).fetchone()
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
                    r=c.execute("SELECT payload FROM jobs WHERE id=? AND state IN ('error','cancelled','interrupted')",(d['id'],)).fetchone()
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

if __name__=='__main__':
    server=ThreadingHTTPServer((LISTEN,PORT),Handler)
    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()
    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
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
