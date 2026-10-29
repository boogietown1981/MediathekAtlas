"""Interruptible catalogue refresh and rate-limited metadata queue."""
import hashlib,json,time,threading
import platform
from pathlib import Path
import core,catalog,filmlist,diagnostics,metadata,broadcaster,meshjournal,meshpeer

def retry_delay(attempts,result):
    """Seconds until an unresolved work is checked again."""
    if result['warnings']:return 3600
    # Only a paused provider (OMDb quota) is missing: back off per work instead of re-querying every
    # unresolved work hourly, which used up the quota again right after each pause ended.
    if result.get('deferred_providers'):return min(86400,3600*2**min(max(attempts-1,0),5))
    return 86400

METADATA_PAUSE=.1

class Service:
    def __init__(self,db,settings,stop,root):self.db=db;self.settings=settings;self.stop=stop;self.root=root;self.wake=threading.Event();self.restart=threading.Event();self.current={};self.last_log=0;self.metadata_status={};self.reclassification={};self.turn=0;self.checked=0;self.artwork_checked=0;self.metadata_wake=threading.Event();self.format_wake=threading.Event();self.mesh=None;self.mesh_filter=None;self.mesh_status={'enabled':False};self.mesh_lock=threading.RLock();self.mesh_names={};self.mesh_running=threading.Lock();self.mesh_peer={};self.mesh_backlog={};self.mesh_rate=0.0;self.mesh_mark=(time.monotonic(),0);self.mesh_beat=0;self.mesh_imported=0;self.mesh_invalid=0
    def start(self):
        for fn in (self.sync_loop,self.metadata_loop,self.reclassify_loop,self.artwork_loop,self.mesh_loop):threading.Thread(target=self.supervise,args=(fn,),daemon=True,name=fn.__name__).start()
    def supervise(self,fn):
        while not self.stop.is_set():
            try:
                fn()
                return
            except Exception as e:diagnostics.error('background_worker_failed',e,worker=fn.__name__)
            if self.stop.wait(5):return
    def status(self,**state):
        changed=state.get('phase')!=self.current.get('phase')
        self.current={**state,'updated_at':time.time()}
        if changed or time.monotonic()-self.last_log>15:
            diagnostics.event('catalog_progress',**self.current);self.last_log=time.monotonic()
        with self.db() as c:catalog.set_state(c,'sync',self.current)
    def import_snapshot(self,path,started,cancelled):
        count=0;batch=[]
        for row in filmlist.read_rows(path):
            batch.append(row)
            if len(batch)>=500:
                if cancelled():raise InterruptedError('Import pausiert')
                with self.db() as c:catalog.ingest(c,batch,started)
                count+=len(batch);batch=[];self.status(phase='importing',processed=count)
        if cancelled():raise InterruptedError('Import pausiert')
        with self.db() as c:
            catalog.ingest(c,batch,started);count+=len(batch)
            if count<1:raise ValueError('Leere Filmliste; bisherige Verfügbarkeit bleibt erhalten')
            # Only a completed parse may retire older offers.
            c.execute('UPDATE offers SET active=0 WHERE seen<?',(started,));catalog.set_state(c,'last_complete',time.time());catalog.restart_formats(c)
        self.format_wake.set()
        self.status(phase='complete',processed=count);return count
    def sync_loop(self):
        retry_after=0
        while not self.stop.wait(2):
            config=self.settings();requested=self.wake.is_set()
            if not config.get('auto_catalog',True) and not requested:continue
            with self.db() as c:last=catalog.get_state(c,'last_complete',0)
            if not requested and (time.time()-last<12*3600 or time.time()<retry_after):continue
            self.wake.clear();self.restart.clear();started=time.time()
            def cancelled():return self.stop.is_set() or self.restart.is_set() or (not requested and not self.settings().get('auto_catalog',True))
            try:
                path=filmlist.download(self.root,self.status,cancelled)
                self.import_snapshot(path,started,cancelled)
            except InterruptedError:self.status(phase='paused')
            except Exception as e:
                diagnostics.error('catalog_sync_failed',e)
                self.status(phase='error',error=core.safe_error(e));retry_after=time.time()+300
    def metadata_state(self,**state):
        self.metadata_status={**state,'checked_session':self.checked,'updated_at':time.time()}
        diagnostics.event('metadata_status',**self.metadata_status)
    def pick(self,c):
        row=c.execute("SELECT w.* FROM metadata_priority p JOIN works w ON w.id=p.work_id WHERE w.state NOT IN ('manual','matched') AND w.next_try<=? ORDER BY p.requested LIMIT 1",(time.time(),)).fetchone()
        if row:return row
        parts=self.mesh_filter
        # With a mesh: own partitions first; when idle, help from the tail of the other partitions.
        scopes=[('',(),'ASC')] if parts is None else [(' AND substr(id,1,2) IN (%s)'%','.join('?'*len(parts)),tuple('%02x'%p for p in sorted(parts)),'ASC')]*bool(parts)+[('',(),'DESC')]
        for where,params,direction in scopes:
            kinds=['movie','series','unknown'];start=self.turn%3
            for kind in kinds[start:]+kinds[:start]:
                for state in (('identified','pending','retry') if kind=='series' else ('pending','identified','retry')):
                    row=c.execute("SELECT * FROM works WHERE kind=? AND state=? AND next_try<=?"+where+" AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=works.id AND active=1) ORDER BY next_try "+direction+" LIMIT 1",(kind,state,time.time())+params).fetchone()
                    if row:break
                if row:break
            if row:break
        self.turn+=1
        return row
    def store_outcome(self,c,row,entry,m,recognized,chosen,result,outcome):
        """Persist one recognition result; shared by local checks and mesh results."""
        wid=row['id'];dest=wid
        if recognized:
            outcome='matched' if chosen else 'identified'
            recognized.update(state='auto_matched' if chosen else 'work_identified',reason='Werk und Episode abgeglichen' if chosen else 'Werk erkannt; Dateizuordnung noch zu prüfen')
            dest=catalog.save_metadata(c,wid,recognized,outcome) or wid
            if recognized['kind']=='series':
                if metadata.norm(entry['source'].get('topic'))==metadata.norm(recognized['title']):
                    c.execute('INSERT OR REPLACE INTO series_templates VALUES(?,?,?,?)',(catalog.key(entry['source']['topic']),recognized['provider'],recognized['reference_id'],json.dumps(recognized)))
                if row['show_key']:catalog.propagate_series(c,row['show_key'],recognized)
                elif metadata.norm(entry['source'].get('topic'))==metadata.norm(recognized['title']):
                    peers=c.execute("SELECT * FROM works WHERE topic=? AND kind='unknown' AND state NOT IN ('manual','matched')",(entry['source']['topic'],)).fetchall()
                    for peer in peers:
                        own=json.loads(peer['meta']);own.update(kind='series',episode_title=own['title'])
                        for key in ('title','year','provider','reference_id','poster','genres','genre_source'):own[key]=recognized.get(key)
                        catalog.save_metadata(c,peer['id'],own,'identified')
            # Programme data of a Sendereihe rarely changes; daily rechecks of every episode would only load the Mediathek.
            if outcome=='identified':c.execute('UPDATE works SET next_try=? WHERE id=?',(time.time()+(30*86400 if recognized.get('provider') in broadcaster.PROVIDERS else 86400),dest))
        else:
            m['suggestions']=result['candidates'];m['metadata_warnings']=result['warnings']
            # Keep recognized show metadata if only its episode remains unresolved.
            if row['state']=='identified':outcome='identified'
            c.execute('UPDATE works SET meta=?,state=?,next_try=? WHERE id=?',(json.dumps(m),outcome,time.time()+retry_delay(row['attempts']+1,result),wid))
        return outcome,dest
    def metadata_once(self):
        config=self.settings()
        if not config.get('auto_metadata',True):
            if self.metadata_status.get('phase')!='paused':self.metadata_state(phase='paused')
            return False
        with self.db() as c:
            row=self.pick(c)
            if not row:
                if self.metadata_status.get('phase')!='waiting':self.metadata_state(phase='waiting')
                return False
            wid=row['id'];original=row['meta'];m=json.loads(original);entry=catalog.item(c,row)
            # A result from another instance arrived before this work was imported here.
            if self.mesh_adopt_stored(c,row):return True
            c.execute('UPDATE works SET next_try=?,attempts=attempts+1 WHERE id=?',(time.time()+3600,wid));c.execute('DELETE FROM metadata_priority WHERE work_id=?',(wid,))
        if not entry:return False
        providers=[p for p,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if config.get(k) and (k!='omdb' or not metadata.omdb_status(config[k])['paused'])] or ['Wikidata (ohne API-Schlüssel)']
        self.metadata_state(phase='checking',title=m['title'],work_id=wid,providers=providers)
        started=time.monotonic()
        try:
            ck=catalog.digest(json.dumps(['v044',config.get('imdb_generation'),m['title'],m['kind'],m.get('year'),m.get('season'),m.get('episode'),m.get('episode_title'),entry['source'].get('title'),entry['source'].get('topic'),entry['source'].get('duration'),config.get('tmdb'),config.get('omdb'),config.get('tvdb'),config.get('tvdb_pin')],sort_keys=True))
            with self.db() as c:cached=c.execute('SELECT payload FROM metadata_cache WHERE id=? AND checked>?',(ck,time.time()-86400)).fetchone()
            if cached:result=json.loads(cached[0])
            else:
                result=core.candidates(entry['source'],m,config)
                if not result['warnings'] and not result.get('deferred_providers'):
                    with self.db() as c:c.execute('INSERT OR REPLACE INTO metadata_cache VALUES(?,?,?)',(ck,json.dumps(result),time.time()))
            chosen=catalog.auto_choice(m,result['candidates']);recognized=chosen or catalog.work_choice(m,result['candidates'])
            outcome='retry' if result['warnings'] or result.get('deferred_providers') else 'review'
            with self.db() as c:
                now=c.execute('SELECT meta,state FROM works WHERE id=?',(wid,)).fetchone()
                if not now or now['meta']!=original or now['state']=='manual':return True
                outcome,dest=self.store_outcome(c,row,entry,m,recognized,chosen,result,outcome)
                # Provider errors stay local and are retried; only final results are shared.
                if outcome!='retry':self.mesh_publish(c,'match.result',wid,dest,outcome,recognized or m,providers)
            self.checked+=1;self.metadata_state(phase='result',title=recognized['title'] if recognized else m['title'],outcome=outcome,provider_checks=result.get('provider_checks',[]),from_cache=bool(cached),candidates=len(result['candidates']),warnings=result['warnings'],seconds=round(time.monotonic()-started,2),providers=providers)
        except Exception as e:
            diagnostics.error('metadata_failed',e,work_id=wid)
            with self.db() as c:
                c.execute("UPDATE works SET state='retry',next_try=? WHERE id=?",(time.time()+3600,wid));catalog.set_state(c,'metadata_error',core.safe_error(e))
            self.metadata_state(phase='error',title=m['title'],error=core.safe_error(e),providers=providers)
        return True
    def reclassify_loop(self):
        processed=0
        while not self.stop.is_set():
            with self.db() as c:n=catalog.reclassify_batch(c)
            if not n:break
            processed+=n;self.reclassification={'phase':'running','processed':processed}
            if processed%10000==0:diagnostics.event('catalog_reclassification',processed=processed)
            if self.stop.wait(.05):return
        self.reclassification={'phase':'complete','processed':processed}
        diagnostics.event('catalog_reclassification_complete',processed=processed)
        self.format_loop()
    def format_loop(self):
        # Contributions of news and magazine formats go under their format instead of into the provider queue.
        assigned=0
        while not self.stop.is_set():
            with self.db() as c:n,a=catalog.assign_formats(c)
            assigned+=a
            if n:
                if self.stop.wait(.05):return
                continue
            if assigned:diagnostics.event('catalog_formats_assigned',assigned=assigned);assigned=0
            self.format_wake.wait(3600);self.format_wake.clear()
    def metadata_loop(self):
        while not self.stop.is_set():
            # A fixed 2 s pause after every work capped the queue at ~28.000 works per day (diagnosis 0.4.7).
            # Providers throttle themselves (caches, pauses, HTTP 429 handling); wait only when idle.
            busy=self.metadata_once()
            self.metadata_wake.wait(METADATA_PAUSE if busy else 2);self.metadata_wake.clear()

    def artwork_loop(self):
        import artwork
        while not self.stop.is_set():
            artwork.run_once(self)
            self.stop.wait(3)

    # Mesh: share recognition results between instances through a synced folder (meshjournal).
    def mesh_loop(self):
        while not self.stop.is_set():
            self.mesh_tick()
            if self.stop.wait(30):break
        with self.mesh_lock:
            if self.mesh:
                try:self.mesh.flush(force=True)
                except OSError:pass
    def mesh_off(self,**state):
        with self.mesh_lock:self.mesh=None;self.mesh_filter=None;self.mesh_status={'enabled':False,**state}
    def mesh_tick(self,now=None):
        if not self.mesh_running.acquire(blocking=False):return
        try:self.mesh_round(now)
        finally:self.mesh_running.release()
    def mesh_round(self,now):
        config=self.settings();folder=str(config.get('mesh_dir') or '').strip()
        # Direct connection without a synced folder: the journal lives in the app's data folder.
        direct=not folder and meshpeer.valid_key(config.get('mesh_key'))
        if direct:folder=str(Path(self.root)/'verbund')
        if not folder:return self.mesh_off()
        try:
            with self.mesh_lock:
                if self.mesh is None or self.mesh_status.get('folder')!=folder:
                    if direct:Path(folder).mkdir(mode=0o700,exist_ok=True)
                    root=meshjournal.check_folder(folder,create=direct)
                    with self.db() as c:
                        node=catalog.get_state(c,'mesh_node_id')
                        if not node:node=meshjournal.new_node_id();catalog.set_state(c,'mesh_node_id',node)
                    self.mesh=meshjournal.Journal(root,node,config.get('mesh_name') or platform.node());self.mesh_beat=0
                    diagnostics.event('mesh_opened',node=node)
                journal=self.mesh;journal.name=str(config.get('mesh_name') or platform.node())[:80]
            elapsed=time.monotonic()-self.mesh_mark[0]
            if elapsed>=60:
                rate=(self.checked-self.mesh_mark[1])*60/elapsed;self.mesh_rate=rate if not self.mesh_rate else self.mesh_rate*.7+rate*.3;self.mesh_mark=(time.monotonic(),self.checked)
            recognizing=bool(config.get('auto_metadata',True))
            providers=[p for p,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if config.get(k)]
            if time.time()-self.mesh_beat>=meshjournal.HEARTBEAT:
                journal.heartbeat({'version':core.UA.rsplit('/',1)[-1],'recognizing':recognizing,'rate':round(self.mesh_rate,2),'providers':providers});self.mesh_beat=time.time()
            # Results from before joining the Verbund are shared once, in batches.
            journal.flush(force=self.mesh_backfill(journal)>0)
            self.mesh_peer_sync(config,journal)
            nodes=journal.nodes();members=journal.members(nodes,now)
            if recognizing:members.setdefault(journal.node,self.mesh_rate)
            parts=journal.assignment(members)
            self.mesh_names={n:str(i.get('name') or n[:8])[:80] for n,i in nodes.items()}
            self.mesh_import(journal)
            self.mesh_check_local()
            with self.mesh_lock:
                self.mesh_filter=None if len(parts)==meshjournal.PARTS else parts
                current=time.time() if now is None else now
                self.mesh_status={'enabled':True,'folder':folder,'node':journal.node,'name':journal.name,'partitions':len(parts),'media_shared':bool(meshjournal.sync_root(config.get('download_dir') or '')),'imported':self.mesh_imported,'invalid':self.mesh_invalid,'direct':direct,'peer':self.mesh_peer,'backlog':self.mesh_backlog,
                    'nodes':[{'node':n,'name':str(i.get('name') or n[:8])[:80],'self':n==journal.node,'active':n in members,'recognizing':i.get('recognizing') is True,'rate':i.get('rate'),'version':str(i.get('version',''))[:20],'age':max(0,int(current-float(i.get('time') or 0)))} for n,i in sorted(nodes.items())]}
        except (meshjournal.MeshError,OSError) as e:
            # Standalone fallback: a missing mount never blocks local recognition.
            if self.mesh_status.get('error')!=core.safe_error(e):diagnostics.error('mesh_unavailable',e)
            self.mesh_off(folder=folder,error=core.safe_error(e))
    def mesh_peer_sync(self,config,journal):
        url=str(config.get('mesh_peer') or '').strip();key=config.get('mesh_key')
        if not url or not meshpeer.valid_key(key):self.mesh_peer={};return
        try:
            result=meshpeer.Peer(url,key).sync(journal.root,journal.node)
            if self.mesh_peer.get('error'):diagnostics.event('mesh_peer_connected',seconds=result['seconds'])
            self.mesh_peer={'url':url,**result}
        except (meshpeer.PeerError,OSError) as e:
            if self.mesh_peer.get('error')!=core.safe_error(e):diagnostics.error('mesh_peer_failed',e)
            self.mesh_peer={'url':url,'error':core.safe_error(e),'last':self.mesh_peer.get('time') or self.mesh_peer.get('last'),'peer':self.mesh_peer.get('peer','')}
    def mesh_import(self,journal):
        with self.db() as c:cursors=catalog.get_state(c,'mesh_cursors',{})
        while True:
            events,cursors,invalid=journal.read(cursors)
            with self.db() as c:
                for event in events:
                    if self.mesh_apply(c,event):self.mesh_imported+=1
                catalog.set_state(c,'mesh_cursors',cursors)
            self.mesh_invalid+=invalid
            if len(events)<meshjournal.READ_LIMIT or self.stop.is_set():break
    def mesh_better(self,c,wid,key):
        old=c.execute('SELECT rank,providers,hlc,node FROM mesh_results WHERE work_id=?',(wid,)).fetchone()
        return old is None or key>tuple(old),old is not None
    def mesh_apply(self,c,event):
        if event['type'] in meshjournal.DOWNLOAD_TYPES:return self.mesh_download_apply(c,event)
        d=event['data'];rank=meshjournal.RANK[d['outcome']]
        key=meshjournal.order(rank,d.get('providers'),event['hlc'],event['node'])
        better,known=self.mesh_better(c,d['work'],key)
        if not better:return False
        old=c.execute('SELECT payload FROM mesh_results WHERE work_id=?',(d['work'],)).fetchone()
        c.execute('INSERT OR REPLACE INTO mesh_results VALUES(?,?,?,?,?,?)',(d['work'],*key,json.dumps(event)))
        # The work may already be merged here under its own canonical ID (earlier result for the same origin).
        ids=[d['work'],d.get('dest'),json.loads(old[0])['data'].get('dest') if old else None]
        row=next((r for r in (c.execute('SELECT * FROM works WHERE id=?',(i,)).fetchone() for i in ids if i) if r),None)
        return self.mesh_adopt(c,row,event,known) if row else True
    def mesh_adopt(self,c,row,event,known):
        d=event['data'];rank=meshjournal.RANK[d['outcome']];local=meshjournal.RANK.get(row['state'],0)
        if row['state']=='manual' and d['outcome']!='manual':return False
        # Unknown provenance of an equal local result (from before the mesh): keep it.
        if rank<local or (rank==local and not known):return False
        meta=meshjournal.clean_meta(d['meta'])
        if meta is None:return False
        if d['outcome']=='review':
            # A weaker instance's "nothing found" must not stop a better equipped one.
            config=self.settings();mine={p for p,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if config.get(k)}
            if not mine<=set(d.get('providers') or []):return False
        if d['outcome']=='manual':
            catalog.save_metadata(c,row['id'],{**meta,'state':'user_confirmed'})
        else:
            entry=catalog.item(c,row)
            if not entry:return False
            suggestions=meta.get('suggestions') if isinstance(meta.get('suggestions'),list) else []
            recognized=meta if d['outcome'] in ('matched','identified') else None
            self.store_outcome(c,row,entry,json.loads(row['meta']),recognized,d['outcome']=='matched',{'candidates':suggestions[:10],'warnings':[]},'review')
        c.execute('DELETE FROM metadata_priority WHERE work_id=?',(row['id'],))
        return True
    def mesh_adopt_stored(self,c,row):
        if self.mesh is None:return False
        stored=c.execute('SELECT payload,node FROM mesh_results WHERE work_id=?',(row['id'],)).fetchone()
        if not stored or stored['node']==self.mesh.node:return False
        return self.mesh_adopt(c,row,json.loads(stored['payload']),True)
    def mesh_backfill(self,journal,limit=1000):
        state='mesh_backfill_'+journal.node;published=0
        with self.db() as c:
            cursor=catalog.get_state(c,state,0)
            if cursor=='complete':
                self.mesh_backlog={'done':True,'shared':self.mesh_backlog.get('shared',0)};return 0
            rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? AND state IN ('manual','matched','identified') ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
            for row in rows:
                cursor=row['rid'];meta=json.loads(row['meta'] or '{}')
                origin=c.execute('SELECT node FROM mesh_results WHERE work_id=?',(row['id'],)).fetchone()
                if origin and origin[0]!=journal.node:continue   # came from another system, it shares it itself
                providers=[meta['provider']] if meta.get('provider') in ('TMDB','TVDB','OMDb') else []
                kind='match.manual' if row['state']=='manual' else 'match.result'
                for wid in catalog.origin_ids(c,row['id']):
                    if self.mesh_publish(c,kind,wid,row['id'],row['state'],meta,providers):published+=1
            catalog.set_state(c,state,cursor if rows else 'complete')
            if rows:
                left=c.execute("SELECT COUNT(*) FROM works WHERE rowid>? AND state IN ('manual','matched','identified')",(cursor,)).fetchone()[0]
                self.mesh_backlog={'done':False,'shared':self.mesh_backlog.get('shared',0)+published,'left':left}
            else:self.mesh_backlog={'done':True,'shared':self.mesh_backlog.get('shared',0)}
        if published:diagnostics.event('mesh_backfill',published=published)
        return published
    def mesh_publish(self,c,kind,wid,dest,outcome,meta,providers):
        with self.mesh_lock:journal=self.mesh
        if journal is None:return None
        meta={k:v for k,v in meta.items() if k not in ('metadata_warnings',)}
        if 'suggestions' in meta:meta['suggestions']=meta['suggestions'][:10] if isinstance(meta['suggestions'],list) else []
        data={'work':wid,'dest':dest,'outcome':outcome,'meta':meta,'providers':[p for p in providers if p in ('TMDB','TVDB','OMDb')]}
        try:
            try:event=journal.append(kind,data)
            except ValueError:
                meta.pop('suggestions',None);event=journal.append(kind,data)
        except (OSError,ValueError) as e:
            diagnostics.error('mesh_publish_failed',e,work_id=wid);return None
        key=meshjournal.order(meshjournal.RANK[outcome],data['providers'],event['hlc'],journal.node)
        if self.mesh_better(c,wid,key)[0]:c.execute('INSERT OR REPLACE INTO mesh_results VALUES(?,?,?,?,?,?)',(wid,*key,json.dumps(event)))
        return event
    def mesh_manual(self,c,wid,dest,meta):
        return self.mesh_publish(c,'match.manual',wid,dest,'manual',meta,[])

    # Downloads: one instance loads a title, MeshSync distributes the file, the others only record it.
    def mesh_download_key(self,job):
        works={catalog.download_identity(job['metadata'])}
        found=None
        with self.db() as c:
            found=c.execute('SELECT work_id FROM offers WHERE id=?',(job.get('source',{}).get('_id'),)).fetchone()
        if found:works.add(found[0])
        return catalog.download_identity(job['metadata']),sorted(works)
    def mesh_download_block(self,c,meta,work_id=None):
        """Message if another instance is loading or has shared this title, else None."""
        with self.mesh_lock:journal=self.mesh
        if journal is None:return None
        r=catalog.mesh_download_row(c,meta,work_id)
        if not r or r['node']==journal.node:return None
        if r['state']=='claim' and r['until']>time.time():return 'Wird bereits auf „%s“ geladen.'%r['name']
        if r['state']=='done' and r['path']:
            return 'Bereits auf „%s“ geladen'%r['name']+(' und hier vorhanden.' if r['local'] else '; MeshSync überträgt die Datei.')
        return None
    def mesh_download_publish(self,kind,job,**extra):
        with self.mesh_lock:journal=self.mesh
        if journal is None:return None
        key,works=self.mesh_download_key(job)
        data={'key':key,'works':works,'title':str(job['metadata'].get('episode_title') or job['metadata'].get('title') or '')[:300],**extra}
        try:event=journal.append(kind,data)
        except (OSError,ValueError) as e:
            diagnostics.error('mesh_publish_failed',e,download=key);return None
        with self.db() as c:self.mesh_download_store(c,event,journal.name,local=extra.get('local'))
        if kind!='download.claim':
            try:journal.flush(force=True)  # finished or released downloads matter to the others right away
            except OSError:pass
        return event
    def mesh_claim(self,job):
        return self.mesh_download_publish('download.claim',job,until=int(time.time())+meshjournal.CLAIM_SECONDS)
    def mesh_release(self,job):
        return self.mesh_download_publish('download.release',job)
    def mesh_done(self,job):
        with self.mesh_lock:journal=self.mesh
        if journal is None:return None
        path=Path(job.get('path') or job.get('target') or '')
        root=meshjournal.sync_root(path.parent) if path.is_file() else None
        rel=None
        if root:
            try:rel=meshjournal.safe_relative(path.resolve().relative_to(root).as_posix())
            except ValueError:rel=None
        digest=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
        return self.mesh_download_publish('download.done',job,path=rel,size=path.stat().st_size,sha256=digest.hexdigest(),local=str(path))
    def mesh_download_store(self,c,event,name,local=None):
        d=event['data'];kind=event['type'].split('.',1)[1]
        old=c.execute('SELECT * FROM mesh_downloads WHERE key=?',(d['key'],)).fetchone()
        if old:
            # A finished download stays authoritative; only a newer completion replaces it.
            if old['state']=='done' and kind!='done':return False
            if kind=='release' and old['node']!=event['node']:return False
            if old['hlc']>=event['hlc'] and not (kind=='done' and old['state']!='done'):return False
        c.execute('INSERT OR REPLACE INTO mesh_downloads VALUES(?,?,?,?,?,?,?,?,?,?)',(d['key'],event['node'],name,kind,d.get('until',0),d.get('path'),d.get('size'),event['hlc'],local,json.dumps(d.get('works',[]))))
        for work in d.get('works',[]):c.execute('INSERT OR REPLACE INTO mesh_download_works VALUES(?,?)',(work,d['key']))
        if kind=='done':
            for identity in {d['key'],*d.get('works',[])}:
                c.execute('INSERT OR IGNORE INTO downloaded_items VALUES(?,?,?)',(identity,local or '',time.time()))
        return True
    def mesh_download_apply(self,c,event):
        name=self.mesh_names.get(event['node'],event['node'][:8])
        if not self.mesh_download_store(c,event,name):return False
        if event['type']=='download.done':self.mesh_check_local(event['data']['key'],c)
        return True
    def mesh_check_local(self,key=None,c=None):
        """Mark shared downloads as present once MeshSync has delivered the complete file here."""
        root=meshjournal.sync_root(self.settings().get('download_dir') or '')
        if root is None:return 0
        def run(c):
            found=0
            rows=c.execute("SELECT * FROM mesh_downloads WHERE state='done' AND path IS NOT NULL AND local IS NULL"+(' AND key=?' if key else ' LIMIT 200'),(key,) if key else ()).fetchall()
            for r in rows:
                target=root/r['path']
                try:ok=target.is_file() and not target.is_symlink() and target.stat().st_size==r['size']
                except OSError:ok=False
                if not ok:continue
                c.execute('UPDATE mesh_downloads SET local=? WHERE key=?',(str(target),r['key']))
                for identity in {r['key'],*json.loads(r['works'] or '[]')}:
                    c.execute('INSERT OR REPLACE INTO downloaded_items VALUES(?,?,?)',(identity,str(target),time.time()))
                found+=1
            return found
        if c is not None:return run(c)
        with self.db() as c:return run(c)
