"""Interruptible catalogue refresh and rate-limited metadata queue."""
import json,time,threading
import core,catalog,filmlist,diagnostics,metadata

class Service:
    def __init__(self,db,settings,stop,root):self.db=db;self.settings=settings;self.stop=stop;self.root=root;self.wake=threading.Event();self.restart=threading.Event();self.current={};self.last_log=0;self.metadata_status={};self.reclassification={};self.turn=0;self.checked=0;self.artwork_checked=0;self.metadata_wake=threading.Event()
    def start(self):
        for fn in (self.sync_loop,self.metadata_loop,self.reclassify_loop,self.artwork_loop):threading.Thread(target=self.supervise,args=(fn,),daemon=True,name=fn.__name__).start()
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
            c.execute('UPDATE offers SET active=0 WHERE seen<?',(started,));catalog.set_state(c,'last_complete',time.time())
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
    def metadata_once(self):
        config=self.settings()
        if not config.get('auto_metadata',True):
            if self.metadata_status.get('phase')!='paused':self.metadata_state(phase='paused')
            return False
        with self.db() as c:
            row=c.execute("SELECT w.* FROM metadata_priority p JOIN works w ON w.id=p.work_id WHERE w.state NOT IN ('manual','matched') AND w.next_try<=? ORDER BY p.requested LIMIT 1",(time.time(),)).fetchone()
            if not row:
                kinds=['movie','series','unknown'];start=self.turn%3;self.turn+=1
                for kind in kinds[start:]+kinds[:start]:
                    for state in (('identified','pending','retry') if kind=='series' else ('pending','identified','retry')):
                        row=c.execute("SELECT * FROM works WHERE kind=? AND state=? AND next_try<=? AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=works.id AND active=1) ORDER BY next_try LIMIT 1",(kind,state,time.time())).fetchone()
                        if row:break
                    if row:break
            if not row:
                if self.metadata_status.get('phase')!='waiting':self.metadata_state(phase='waiting')
                return False
            wid=row['id'];original=row['meta'];m=json.loads(original);entry=catalog.item(c,row)
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
                if recognized:
                    outcome='matched' if chosen else 'identified'
                    recognized.update(state='auto_matched' if chosen else 'work_identified',reason='Werk und Episode abgeglichen' if chosen else 'Werk erkannt; Dateizuordnung noch zu prüfen')
                    catalog.save_metadata(c,wid,recognized,outcome)
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
                    if outcome=='identified':c.execute('UPDATE works SET next_try=? WHERE id=?',(time.time()+86400,wid))
                else:
                    m['suggestions']=result['candidates'];m['metadata_warnings']=result['warnings']
                    # Keep recognized show metadata if only its episode remains unresolved.
                    if row['state']=='identified':outcome='identified'
                    c.execute('UPDATE works SET meta=?,state=?,next_try=? WHERE id=?',(json.dumps(m),outcome,time.time()+(3600 if result['warnings'] or result.get('deferred_providers') else 86400),wid))
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
    def metadata_loop(self):
        while not self.stop.is_set():
            self.metadata_once()
            self.metadata_wake.wait(2);self.metadata_wake.clear()

    def artwork_loop(self):
        import artwork
        while not self.stop.is_set():
            artwork.run_once(self)
            self.stop.wait(3)
