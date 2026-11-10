"""Interruptible catalogue refresh and rate-limited metadata queue."""
import hashlib,json,time,threading,secrets,sqlite3
from collections import deque
import platform
from pathlib import Path
import core,catalog,filmlist,diagnostics,metadata,broadcaster,meshjournal,meshpeer

def retry_delay(attempts,result):
    """Back off stable non-matches; retry genuine network failures sooner."""
    if result['warnings']:return min(6*3600,900*2**min(max(attempts-1,0),4))
    # Only a paused provider (OMDb quota) is missing: back off per work instead of re-querying every
    # unresolved work hourly, which used up the quota again right after each pause ended.
    if result.get('deferred_providers'):return min(86400,3600*2**min(max(attempts-1,0),5))
    # A stable not-found verdict does not need daily full-provider queries.
    # Rechecks remain possible (new evidence/API updates) and manual priority bypasses the delay.
    return min(30*86400,3*86400*2**min(max(attempts-1,0),4))

METADATA_PAUSE=.1
MAX_RECOGNITION_WORKERS=8
MAX_EPISODE_WORKERS=4

def sqlite_busy(exc):
    return isinstance(exc,sqlite3.OperationalError) and any(
        x in str(exc).lower() for x in ('database is locked','database table is locked','database is busy','database snapshot is busy'))

class Service:
    def __init__(self,db,settings,stop,root):self.db=db;self.settings=settings;self.stop=stop;self.root=root;self.wake=threading.Event();self.restart=threading.Event();self.current={};self.last_log=0;self.metadata_status={};self.reclassification={};self.turn=0;self.checked=0;self.artwork_checked=0;self.metadata_wake=threading.Event();self.format_wake=threading.Event();self.mesh=None;self.mesh_filter=None;self.mesh_status={'enabled':False};self.mesh_lock=threading.RLock();self.mesh_names={};self.mesh_running=threading.Lock();self.mesh_peers={};self.mesh_backlog={};self.mesh_pending=False;self.mesh_backfill_at=0.0;self.mesh_rate=0.0;self.mesh_mark=(time.monotonic(),0);self.mesh_beat=0;self.mesh_imported=0;self.mesh_invalid=0;self.first_pass_checks=0;self.repeat_checks=0;self.template_hits=0;self.news_shortcuts=0;self.recent_first=deque();self.started_at=time.monotonic();self.worker_lock=threading.RLock();self.active_checks=0;self.active_work={};self.provider_slots=threading.BoundedSemaphore(2);self.quality_counts={'matched':0,'identified':0,'review':0,'retry':0};self.sqlite_busy_count=0;self.subscription_wake=threading.Event();self.lease_gc_at=0;self.episode_checked=0;self.episode_matched=0;self.episode_unresolved=0;self.episode_suspected=0;self.episode_extras=0;self.episode_retried=0;self.episode_resets=0;self.episode_active=0;self.episode_last_count=(0,0,0);self.episode_sender_imported=0;self.episode_sender_items=0;self.episode_sender_matched=0;self.episode_sender_deferred=0
    def start(self):
        for fn in (self.sync_loop,self.reclassify_loop,self.artwork_loop,self.mesh_loop,self.movie_dedup_loop,self.film_hint_loop,self.subscription_loop):
            threading.Thread(target=self.supervise,args=(fn,),daemon=True,name=fn.__name__).start()
        # Eight long-lived workers are cheap while idle; actual concurrency is configurable.
        # Provider concurrency remains limited independently to two.
        for index in range(MAX_RECOGNITION_WORKERS):
            fn=lambda index=index:self.metadata_loop(index)
            threading.Thread(target=self.supervise,args=(fn,),daemon=True,name='recognition_worker_%d'%(index+1)).start()
        for index in range(MAX_EPISODE_WORKERS):
            fn=lambda index=index:self.episode_loop(index)
            threading.Thread(target=self.supervise,args=(fn,),daemon=True,name='episode_worker_%d'%(index+1)).start()
    def supervise(self,fn):
        while not self.stop.is_set():
            try:
                fn()
                return
            except Exception as e:diagnostics.error('background_worker_failed',e,worker=fn.__name__)
            if self.stop.wait(5):return
    def movie_dedup_loop(self):
        """Reconcile historical confirmed movie duplicates in small persisted batches."""
        scanned=0;merged=0
        while not self.stop.is_set():
            with self.db() as c:
                n,changed=catalog.deduplicate_movie_batch(c,limit=120)
            scanned+=n;merged+=changed
            if changed:diagnostics.event('movie_duplicates_merged',merged=changed,session_merged=merged,scanned=scanned)
            if n==0:
                diagnostics.event('movie_dedup_complete',scanned=scanned,merged=merged)
                return
            if self.stop.wait(.35):return

    def film_hint_loop(self):
        """Classify existing unknown works in small resumable batches without API requests."""
        processed=0
        while not self.stop.is_set():
            with self.db() as c:n=catalog.backfill_film_hints(c,limit=400)
            processed+=n
            if not n:
                diagnostics.event('film_hint_backfill_complete',scanned=processed)
                return
            if self.stop.wait(.04):return
    def status(self,**state):
        changed=state.get('phase')!=self.current.get('phase')
        self.current={**state,'updated_at':time.time()}
        if changed or time.monotonic()-self.last_log>15:
            diagnostics.event('catalog_progress',**self.current);self.last_log=time.monotonic()
        with self.db() as c:catalog.set_state(c,'sync',self.current)
    def import_snapshot(self,path,started,cancelled):
        """Stream a full official snapshot, but only reprocess changed/new rows."""
        import_started=time.monotonic()
        count=0;batch=[];changes={'added':0,'changed':0,'unchanged':0,'reactivated':0}
        with self.db() as c:catalog.begin_snapshot(c)
        for row in filmlist.read_rows(path):
            batch.append(row)
            if len(batch)>=500:
                if cancelled():raise InterruptedError('Import pausiert')
                with self.db() as c:catalog.ingest_incremental(c,batch,started,changes)
                count+=len(batch);batch=[]
                self.status(phase='importing',processed=count)
        if cancelled():raise InterruptedError('Import pausiert')
        with self.db() as c:
            catalog.ingest_incremental(c,batch,started,changes);count+=len(batch)
            if count<1:raise ValueError('Leere Filmliste; bisherige Verfügbarkeit bleibt erhalten')
            changes=catalog.finish_snapshot(c,started,changes)
            catalog.set_state(c,'last_complete',time.time())
        self.format_wake.set();self.subscription_wake.set()
        diagnostics.event('catalog_snapshot_diff',**changes,processed=count,import_seconds=round(time.monotonic()-import_started,2))
        self.status(phase='complete',processed=count,changes=changes);return count
    def sync_loop(self):
        retry_after=0
        while not self.stop.wait(2):
            config=self.settings();requested=self.wake.is_set()
            if not config.get('auto_catalog',True) and not requested:continue
            with self.db() as c:
                last=catalog.get_state(c,'last_complete',0)
                try:has_subscriptions=bool(c.execute('SELECT 1 FROM subscriptions WHERE enabled=1 LIMIT 1').fetchone())
                except sqlite3.OperationalError:has_subscriptions=False
            # Active subscriptions need fresh offers; hourly-ish feed import is
            # still bounded, cancellable and uses the incremental diff.
            interval=2*3600 if has_subscriptions else 12*3600
            if not requested and (time.time()-last<interval or time.time()<retry_after):continue
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
    def subscription_loop(self):
        """Create queued download jobs from user-approved subscriptions."""
        import subscriptions
        while not self.stop.is_set():
            try:
                with self.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    result=subscriptions.run_due(c,self.settings()['download_dir'])
                for row in result:
                    if row['queued']:
                        diagnostics.event('subscription_jobs_queued',id=row['id'],
                                          queued=row['queued'],title=row['title'])
            except Exception as e:diagnostics.error('subscription_scheduler_failed',e)
            self.subscription_wake.wait(60);self.subscription_wake.clear()

    def lease_work(self,queue='identity'):
        """Claim atomically, but never hold a writer lock during catalogue selection.

        Read the candidate before BEGIN IMMEDIATE; verify it is still eligible
        when the short write lock is held. Under eight workers a lost race just
        picks a different candidate. Busy databases yield instead of killing a
        worker or permanently losing its progress.
        """
        for attempt in range(12):
            now=time.time()
            try:
                with self.db() as c:
                    row=self.pick_episode(c) if queue=='episode' else self.pick(c)
                    if row is None:return None
                    c.execute('BEGIN IMMEDIATE')
                    active=c.execute('SELECT state,next_try FROM works WHERE id=?',(row['id'],)).fetchone()
                    episode=c.execute('SELECT next_try FROM episode_queue WHERE work_id=?',(row['id'],)).fetchone()
                    leased=c.execute('SELECT expires FROM metadata_leases WHERE work_id=?',(row['id'],)).fetchone()
                    if (not active or active['state']!=row['state'] or active['state'] in ('manual','matched','format')
                            or (episode is None if queue=='episode' else episode is not None)
                            or (episode['next_try']>now if queue=='episode' and episode else active['next_try']>now)
                            or leased and leased['expires']>now):
                        continue
                    if now>=self.lease_gc_at:
                        c.execute('DELETE FROM metadata_leases WHERE expires<=?',(now,))
                        self.lease_gc_at=now+60
                    owner=secrets.token_hex(12)
                    added=c.execute("""INSERT INTO metadata_leases(work_id,owner,expires)
                        VALUES(?,?,?) ON CONFLICT(work_id) DO UPDATE SET
                          owner=excluded.owner,expires=excluded.expires
                        WHERE metadata_leases.expires<=?""",
                        (row['id'],owner,now+1800,now)).rowcount
                    if added:return (row['id'],owner)
            except sqlite3.OperationalError as e:
                if not sqlite_busy(e):raise
                self.sqlite_busy_count+=1
                if self.stop.wait(min(.75,.04*(attempt+1))):return None
        return None

    def metadata_once(self,queue='identity'):
        if not self.settings().get('auto_metadata',True):return False
        claim=self.lease_work('episode') if queue=='episode' else self.lease_work()
        if claim is None:
            with self.worker_lock:active=max(0,self.active_checks-self.episode_active)
            if queue=='identity' and not active and self.metadata_status.get('phase')!='waiting':
                self.metadata_state(phase='waiting')
            return False
        wid,owner=claim
        thread=threading.current_thread().name
        with self.worker_lock:
            self.active_checks+=1;self.active_work[thread]=wid
            if queue=='episode':self.episode_active+=1
        try:
            return self._episode_once_claimed(wid) if queue=='episode' else self._metadata_once_claimed(wid)
        finally:
            try:
                for attempt in range(4):
                    try:
                        with self.db() as c:
                            c.execute('DELETE FROM metadata_leases WHERE work_id=? AND owner=?',(wid,owner))
                        break
                    except sqlite3.OperationalError as e:
                        if not sqlite_busy(e):raise
                        self.sqlite_busy_count+=1
                        if self.stop.wait(.1*(attempt+1)):break
            finally:
                with self.worker_lock:
                    self.active_checks=max(0,self.active_checks-1);self.active_work.pop(thread,None)
                    if queue=='episode':self.episode_active=max(0,self.episode_active-1)

    def pick_episode(self,c):
        """Select only recognised series awaiting a separate episode match."""
        now=time.time()
        parts=self.mesh_filter
        if parts is not None and not parts:return None
        scope=(' AND substr(w.id,1,2) IN (%s)'%','.join('?'*len(parts))) if parts else ''
        params=tuple('%02x'%p for p in sorted(parts)) if parts else ()
        query='''SELECT w.* FROM episode_queue q JOIN works w ON w.id=q.work_id
             WHERE w.kind='series' AND w.state='identified' AND q.next_try<=?
             AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
             AND NOT EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?)'''
        row=c.execute(query+scope+''' AND EXISTS(SELECT 1 FROM metadata_priority p WHERE p.work_id=w.id)
             ORDER BY q.next_try ASC LIMIT 1''',(now,now)+params).fetchone()
        if row:return row
        return c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 1",
                         (now,now)+params).fetchone()

    def pick(self,c):
        """User priority, bounded show completion, new work, then due retries.

        The selector never resets cooldowns just to finish a show. In movie-first
        mode, film first passes always win over automatic series focus.
        """
        now=time.time()
        row=c.execute("""SELECT w.* FROM metadata_priority p JOIN works w ON w.id=p.work_id
            WHERE w.state NOT IN ('manual','matched','format') AND w.next_try<=?
              AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)
              AND NOT EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?)
            ORDER BY p.requested LIMIT 1""",(now,now)).fetchone()
        if row:return row
        config=self.settings()
        mode=config.get('scan_priority','balanced')
        if mode not in ('balanced','movies_first','series_first'):mode='balanced'
        kinds={'movies_first':['movie','series','unknown'],
               'series_first':['series','movie','unknown']}.get(mode,['movie','series','unknown'])
        if mode=='balanced':
            start=self.turn%3;kinds=kinds[start:]+kinds[:start]
        self.turn+=1
        parts=self.mesh_filter
        scopes=[('',(),'ASC')] if parts is None else (
            ([(' AND substr(w.id,1,2) IN (%s)'%','.join('?'*len(parts)),
               tuple('%02x'%p for p in sorted(parts)),'ASC')] if parts else [])
            +[('',(),'DESC')])
        def choose(fresh,kind):
            for where,params,direction in scopes:
                states=('pending','retry','identified') if fresh else ('retry','pending','identified')
                for state in states:
                    predicate=' AND w.attempts=0' if fresh else ' AND w.attempts>0'
                    row=c.execute("""SELECT w.* FROM works w WHERE w.kind=? AND w.state=?
                        AND w.next_try<=?
                        AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)"""+predicate+where+"""
                        AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
                        AND NOT EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?)
                        ORDER BY w.next_try """+direction+""" LIMIT 1""",(kind,state,now)+params+(now,)).fetchone()
                    if row:return row
            return None
        def focused():
            if not config.get('complete_series',True):return None
            for where,params,_ in scopes:
                row=c.execute("""SELECT w.* FROM series_focus f JOIN works w ON w.show_key=f.show_key
                    WHERE f.until>? AND f.remaining>0 AND w.kind='series'
                      AND w.state IN ('pending','retry','identified') AND w.next_try<=?
                      AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)
                      AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
                      AND NOT EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?)
                    """+where+""" ORDER BY f.updated DESC,w.attempts ASC,w.next_try ASC LIMIT 1""",
                    (now,now,now)+params).fetchone()
                if row:return row
            return None
        if mode=='movies_first':
            row=choose(True,'movie')
            if row:return row
            # Unknown works with *explicit* film rubrics/production cues go before
            # generic series. A hint changes scheduling only, never metadata.
            for where,params,_ in scopes:
                row=c.execute("""SELECT w.* FROM film_hints h JOIN works w ON w.id=h.work_id
                    WHERE h.score>=2 AND w.kind='unknown' AND w.attempts=0
                      AND w.state IN ('pending','retry','identified') AND w.next_try<=?
                      AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)
                      AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
                      AND NOT EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?)
                    """+where+""" ORDER BY h.score DESC,w.next_try ASC LIMIT 1""",
                    (now,now)+params).fetchone()
                if row:return row
        elif mode=='series_first':
            row=focused()
            if row:return row
            row=choose(True,'series')
            if row:return row
        else:
            row=focused()
            if row:return row
        for kind in kinds:
            row=choose(True,kind)
            if row:return row
        if mode=='movies_first':
            row=focused()
            if row:return row
        for kind in kinds:
            row=choose(False,kind)
            if row:return row
        return None
    def scan_rate(self):
        now=time.monotonic()
        while self.recent_first and now-self.recent_first[0]>600:self.recent_first.popleft()
        duration=min(600,now-self.started_at)
        # At least one minute of measurements for a useful ETA.
        if duration<60 or len(self.recent_first)<20:return 0.0
        return len(self.recent_first)*60/max(60,duration)
    def record_check(self,was_first,from_template=False,outcome=None):
        with self.worker_lock:
            self.checked+=1
            if was_first:
                self.first_pass_checks+=1;self.recent_first.append(time.monotonic())
            else:self.repeat_checks+=1
            if from_template:self.template_hits+=1
            if outcome in self.quality_counts:self.quality_counts[outcome]+=1
    def scan_progress(self):
        with self.worker_lock:
            rate=self.scan_rate()
            active=max(0,self.active_checks-self.episode_active);running=dict(self.active_work)
            counts=dict(self.quality_counts)
            first=self.first_pass_checks;repeat=self.repeat_checks;template=self.template_hits
        total=sum(counts.values());elapsed=max(1,time.monotonic()-self.started_at)
        now=time.monotonic()
        if self.db is not None and now-self.episode_last_count[0]>=30:
            try:
                with self.db() as c:
                    total_ep=c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0]
                    due_ep=c.execute('SELECT COUNT(*) FROM episode_queue WHERE next_try<=?',(time.time(),)).fetchone()[0]
                self.episode_last_count=(now,total_ep,due_ep)
            except sqlite3.OperationalError as e:
                if not sqlite_busy(e):raise
                self.sqlite_busy_count+=1
        _,ep_total,ep_due=self.episode_last_count
        return {'episode_queue_total':ep_total,'episode_queue_due':ep_due,
                'episode_workers_active':self.episode_active,
                'episode_workers_configured':max(1,min(MAX_EPISODE_WORKERS,int(self.settings().get('episode_workers',2)))),
                'episode_checked_session':self.episode_checked,
                'episode_matched_session':self.episode_matched,
                'episode_unresolved_session':self.episode_unresolved,
                'episode_suspected_session':self.episode_suspected,
                'episode_extras_session':self.episode_extras,
                'episode_retried_session':self.episode_retried,
                'episode_reset_session':self.episode_resets,
                'episode_sender_imported_session':self.episode_sender_imported,
                'episode_sender_items_session':self.episode_sender_items,
                'episode_sender_matched_session':self.episode_sender_matched,
                'episode_sender_deferred_session':self.episode_sender_deferred,
                'first_pass_session':first,'repeat_session':repeat,
                'series_template_session':template,
                'news_format_shortcuts_session':self.news_shortcuts,
                'first_pass_per_minute':round(rate,2),
                'quality_session':counts,
                'match_rate_session':round(100*counts['matched']/total,1) if total else 0.0,
                'identified_rate_session':round(100*(counts['matched']+counts['identified'])/total,1) if total else 0.0,
                'matched_per_hour_session':round(counts['matched']*3600/elapsed,1),
                'sqlite_busy_retries_session':self.sqlite_busy_count,
                'recognition_workers_active':active,
                'recognition_workers_configured':max(1,min(MAX_RECOGNITION_WORKERS,int(self.settings().get('metadata_workers',2)))),
                'recognition_worker_ids':running}
    def store_outcome(self,c,row,entry,m,recognized,chosen,result,outcome):
        """Persist one recognition result; shared by local checks and mesh results."""
        wid=row['id'];dest=wid
        if recognized:
            # A successful fallback is valuable even if an optional provider
            # is temporarily unavailable. Keep the missing providers as a
            # resumable per-work marker, not as a failed recognition.
            recognized.pop('deferred_providers',None)
            if result.get('deferred_providers'):
                recognized['deferred_providers']=list(dict.fromkeys(result['deferred_providers']))
            outcome='matched' if chosen else 'identified'
            recognized.update(state='auto_matched' if chosen else 'work_identified',reason='Werk und Episode abgeglichen' if chosen else 'Werk erkannt; Dateizuordnung noch zu prüfen')
            dest=catalog.save_metadata(c,wid,recognized,outcome) or wid
            if recognized['kind']=='series' and not recognized.get('video_role_needs_review'):
                if metadata.norm(entry['source'].get('topic'))==metadata.norm(recognized['title']):
                    c.execute('INSERT OR REPLACE INTO series_templates VALUES(?,?,?,?)',(catalog.key(entry['source']['topic']),recognized['provider'],recognized['reference_id'],json.dumps(recognized)))
                if row['show_key']:catalog.propagate_series(c,row['show_key'],recognized)
                elif metadata.norm(entry['source'].get('topic'))==metadata.norm(recognized['title']):
                    peers=c.execute("SELECT * FROM works WHERE topic=? AND kind='unknown' AND state NOT IN ('manual','matched')",(entry['source']['topic'],)).fetchall()
                    for peer in peers:
                        own=json.loads(peer['meta']);own.update(kind='series',episode_title=own['title'])
                        for key in ('title','year','provider','reference_id','poster','genres','genre_source','reference_runtime_seconds'):own[key]=recognized.get(key)
                        catalog.save_metadata(c,peer['id'],own,'identified')
            # Boost siblings only once their work identities have been propagated.
            if (recognized['kind']=='series' and not recognized.get('video_role_needs_review')
                and self.settings().get('complete_series',True) and
                recognized.get('reference_id') and
                metadata.norm(entry['source'].get('topic'))==metadata.norm(recognized['title'])):
                show=catalog.showkey(recognized)
                if catalog.focus_series(c,show):
                    diagnostics.event('series_completion_queued',show_key=show,limit=24)
            # Programme data of a Sendereihe rarely changes; daily rechecks of every episode would only load the Mediathek.
            if outcome=='identified':
                delay=(retry_delay(row['attempts']+1,result) if result.get('deferred_providers')
                       else 30*86400 if recognized.get('provider') in broadcaster.PROVIDERS else 86400)
                c.execute('UPDATE works SET next_try=? WHERE id=?',(time.time()+delay,dest))
        else:
            m['suggestions']=result['candidates'];m['metadata_warnings']=result['warnings']
            if result.get('deferred_providers'):
                m['deferred_providers']=list(dict.fromkeys(result['deferred_providers']))
            else:
                m.pop('deferred_providers',None)
            # Keep recognized show metadata if only its episode remains unresolved.
            if row['state']=='identified':outcome='identified'
            c.execute('UPDATE works SET meta=?,state=?,next_try=? WHERE id=?',(json.dumps(m),outcome,time.time()+retry_delay(row['attempts']+1,result),wid))
        return outcome,dest
    def record_episode_result(self,outcome,imported=False,sender_verified=False,
                              sender_item=False,sender_deferred=False,
                              sender_status='not_checked'):
        """Count each committed episode claim exactly once, including early exits.

        A short excerpt is *processed*, but neither matched nor unresolved.
        Persisted work metadata remains the source of truth across restarts;
        these counters explicitly describe only this app session.
        """
        with self.worker_lock:
            self.episode_checked+=1
            if outcome=='matched':self.episode_matched+=1
            elif outcome=='unresolved':self.episode_unresolved+=1
            elif outcome=='suspected':self.episode_suspected+=1
            elif outcome=='extra':self.episode_extras+=1
            elif outcome=='retry':self.episode_retried+=1
            elif outcome=='reset':self.episode_resets+=1
            if imported:
                self.episode_sender_imported+=1
                if sender_verified:self.episode_sender_matched+=1
                if sender_item:self.episode_sender_items+=1
                if sender_deferred:self.episode_sender_deferred+=1
            n=self.episode_checked
            matched=self.episode_matched
            unresolved=self.episode_unresolved
            suspect=self.episode_suspected
            extras=self.episode_extras
            items=self.episode_sender_items
            sender_matches=self.episode_sender_matched
        if outcome in ('matched','suspected','extra') or n==1 or n%100==0:
            diagnostics.event('episode_worker_progress',outcome=outcome,
                              checks=n,matched=matched,unresolved=unresolved,
                              suspected=suspect,extras=extras,
                              sender_items=items,sender_matched=sender_matches,
                              sender_status=sender_status)

    def _episode_once_claimed(self,selected_id):
        """Resolve a known show's episode from imported sender evidence first.

        Automatic original-page requests require explicit permission. A sender
        page confirms a distinct video even when there is no season/episode
        number; it must NOT be counted as a complete episode match.
        """
        # Finish the SQLite transaction before recording a session counter.
        # Early exits are real completed queue claims, not invisible work.
        preflight=None
        with self.db() as c:
            row=c.execute('SELECT * FROM works WHERE id=?',(selected_id,)).fetchone()
            task=c.execute('SELECT * FROM episode_queue WHERE work_id=?',(selected_id,)).fetchone()
            if not row or not task or row['state']!='identified':return False
            m=json.loads(row['meta']);original=row['meta'];entry=catalog.item(c,row)
            if entry:
                import video_causality
                if catalog.mark_explicit_extra(c,row,entry['source']):
                    diagnostics.event('video_extra_classified',work_id=selected_id,
                                      title=entry['source'].get('title',''),reason='explicit_title')
                    preflight='extra'
                else:
                    runtime_meta=dict(m)
                    if not runtime_meta.get('reference_runtime_seconds'):
                        typical=video_causality.sample_series_runtime(c,row['show_key'],selected_id)
                        if typical:
                            runtime_meta['reference_runtime_seconds']=typical
                            runtime_meta['reference_runtime_source']='Serien-Katalogmedian (mind. 5 Vergleichsangebote)'
                    causality=video_causality.evaluate(entry['source'],runtime_meta)
                    if causality:
                        m.update(causality,video_role_needs_review=True,episode_verified=False,
                                 reason='Serienidentität bekannt, Videolaufzeit passt nicht zur ganzen Folge')
                        c.execute('UPDATE works SET meta=?,updated=? WHERE id=?',
                                  (json.dumps(m),time.time(),selected_id))
                        diagnostics.event('episode_runtime_suspect',work_id=selected_id,
                                          actual=causality.get('source_duration_seconds'),
                                          expected=causality.get('expected_runtime_seconds'),
                                          source=causality.get('expected_runtime_source'),
                                          role=causality['video_role'])
                        preflight='suspected'
            if preflight is None and (not m.get('provider') or not m.get('reference_id')):
                c.execute("UPDATE works SET state='pending',next_try=0 WHERE id=?",(selected_id,))
                preflight='reset'
            if preflight is None:
                c.execute('DELETE FROM metadata_priority WHERE work_id=?',(selected_id,))

        if preflight is not None:
            self.record_episode_result(preflight,sender_status='offline_preflight')
            return True

        source=entry['source'] if entry else {}
        imported=broadcaster.imported_episode_evidence(source,m) if entry else None
        sender_candidate=None
        sender_verified=None
        sender_error=False
        sender_deferred=False
        sender_status='no_sender_link' if not imported else 'imported'
        suspicion=None
        config=self.settings()
        if imported and broadcaster.reference(source) and config.get('sender_direct_lookup',False):
            try:
                info=broadcaster.lookup_limited(source)
                if info:
                    candidate=broadcaster.candidate(source,m,info)
                    import matching,video_causality
                    if candidate:
                        video_causality.annotate(source,candidate)
                        if candidate.get('video_role_needs_review'):suspicion=candidate
                    if candidate and not matching.issues(m,candidate):
                        sender_candidate=candidate
                        sender_status='sender_item' if candidate.get('sender_item_verified') else 'sender_series'
                        if candidate.get('sender_item_verified') and candidate.get('episode_verified'):
                            sender_verified=catalog.auto_choice(m,[candidate])
                    else:sender_status='sender_conflict'
                else:sender_status='sender_not_found'
            except broadcaster.Unavailable:
                sender_deferred=True
                sender_status='sender_deferred'
            except Exception as exc:
                diagnostics.error('episode_sender_lookup_failed',exc,work_id=selected_id)
                sender_error=True
                sender_status='sender_error'

        import imdb_archive
        archive=imdb_archive.ACTIVE
        imdb_verified=None;imdb_error=False
        if not sender_verified and entry and archive and archive.updated:
            try:
                candidates=archive.candidates(source,m)
                import video_causality
                for candidate in candidates:
                    video_causality.annotate(source,candidate)
                    if candidate.get('video_role_needs_review'):suspicion=candidate
                if not suspicion:imdb_verified=catalog.auto_choice(m,candidates)
            except Exception as exc:
                diagnostics.error('episode_local_lookup_failed',exc,work_id=selected_id)
                imdb_error=True
        verified=None if suspicion else (sender_verified or imdb_verified)
        with self.db() as c:
            current=c.execute('SELECT meta,state FROM works WHERE id=?',(selected_id,)).fetchone()
            if not current or current['state']!='identified' or current['meta']!=original:return True
            if verified and verified.get('episode_verified'):
                verified.update(state='auto_matched',
                    reason='Originalsender: Folge eindeutig bestätigt' if sender_verified
                           else 'IMDb-Episode eindeutig bestätigt')
                catalog.save_metadata(c,selected_id,verified,'matched')
                outcome='matched'
            else:
                enriched=dict(m)
                if suspicion:
                    for key in ('video_role','video_role_reason','video_role_evidence',
                                'source_duration_seconds','expected_runtime_seconds'):
                        if suspicion.get(key) is not None:enriched[key]=suspicion[key]
                    enriched['video_role_needs_review']=True
                    enriched['episode_verified']=False
                    enriched['reason']='Serie erkannt, diese Videodatei ist möglicherweise nur ein Kurzformat'
                    diagnostics.event('episode_runtime_suspect',work_id=selected_id,
                                      actual=enriched.get('source_duration_seconds'),
                                      expected=enriched.get('expected_runtime_seconds'),
                                      role=enriched.get('video_role'))
                if imported:
                    # Offer identity is NOT a verified episode number.
                    for field in ('sender_provider','sender_page_id','sender_evidence','sender_episode_title'):
                        if imported.get(field):enriched[field]=imported[field]
                if sender_candidate and sender_candidate.get('sender_item_verified'):
                    enriched.update(sender_item_verified=True,sender_evidence='original_sender_page')
                    for field in ('broadcast','series_description'):
                        if sender_candidate.get(field):enriched[field]=sender_candidate[field]
                    if not enriched.get('description') and sender_candidate.get('description'):
                        enriched['description']=sender_candidate['description']
                    sender_status='sender_item'
                if enriched!=m:
                    c.execute('UPDATE works SET meta=?,updated=? WHERE id=?',
                              (json.dumps(enriched),time.time(),selected_id))
                if suspicion:
                    outcome='suspected'
                    delay=0
                elif sender_deferred or sender_error or imdb_error or not (archive and archive.updated):
                    outcome='retry'
                    delay=3600
                    if sender_deferred and imported:
                        delay=max(delay,broadcaster.automated_retry_at(imported['sender_provider'])-time.time())
                    delay=max(60,min(6*3600,delay))
                else:
                    outcome='unresolved'
                    delay=30*86400
                c.execute("""UPDATE episode_queue SET attempts=attempts+1,
                    last_outcome=?,next_try=?,updated=? WHERE work_id=?""",
                    (outcome,time.time()+delay,time.time(),selected_id))
        self.record_episode_result(outcome,imported=bool(imported),
                                   sender_verified=bool(sender_verified),
                                   sender_item=bool(sender_candidate and sender_candidate.get('sender_item_verified')),
                                   sender_deferred=sender_deferred,
                                   sender_status=sender_status)
        return True

    def _metadata_once_claimed(self,selected_id):
        config=self.settings()
        if not config.get('auto_metadata',True):return False
        with self.db() as c:
            row=c.execute('SELECT * FROM works WHERE id=?',(selected_id,)).fetchone()
            if not row or row['state'] in ('manual','matched','format'):return False
            wid=row['id'];original=row['meta'];m=json.loads(original);entry=catalog.item(c,row)
            catalog.focus_take(c,row['show_key'])
            # A result from another instance arrived before this work was imported here.
            if self.mesh_adopt_stored(c,row):return True
            # Explicit user priority is stronger than automatic broadcaster
            # categorization, even when this is a known daily news programme.
            priority=c.execute('SELECT 1 FROM metadata_priority WHERE work_id=?',(wid,)).fetchone()
            if entry and not priority and catalog.mark_explicit_extra(c,row,entry['source']):
                diagnostics.event('video_extra_classified',work_id=wid,title=entry['source'].get('title',''),
                                  reason='explicit_title')
                self.metadata_state(phase='result',title=entry['source'].get('title',''),
                                    outcome='format',from_cache=True,seconds=0)
                return True
            if entry and not priority and catalog.mark_news_format(c,row,entry['source']):
                self.news_shortcuts+=1
                if self.news_shortcuts==1 or self.news_shortcuts%250==0:
                    diagnostics.event('news_format_shortcut',total=self.news_shortcuts,
                                      title=m.get('title',''),providers_skipped=True)
                # This is NOT a provider check; never inflate real recognition
                # throughput or the first-pass ETA with format classifications.
                if self.news_shortcuts==1 or self.news_shortcuts%50==0:
                    self.metadata_state(phase='result',title=entry['source'].get('topic') or m['title'],
                                        outcome='format',from_cache=True,
                                        providers=[],provider_checks=[],seconds=0)
                return True
            # A uniquely identified series is already stored locally. Reuse its
            # identity for the next unnumbered episode, and ask IMDb Offline only
            # for explicit episode evidence. Manually prioritized works still
            # run the normal full provider chain.
            numbered=isinstance(m.get('season'),int) and isinstance(m.get('episode'),int)
            if entry and not priority and not numbered and not m.get('deferred_providers') and row['state'] in ('pending','retry','review','identified'):
                known=catalog.series_template_candidate(c,row,entry['source'])
                if known:
                    import imdb_archive
                    verified=None
                    if imdb_archive.ACTIVE and imdb_archive.ACTIVE.updated:
                        try:
                            local=imdb_archive.ACTIVE.candidates(entry['source'],known)
                            verified=catalog.auto_choice(known,local)
                        except Exception as e:diagnostics.error('series_template_imdb_failed',e,work_id=wid)
                    if verified:
                        verified.update(state='auto_matched',reason='Serienvorlage und IMDb-Episode eindeutig bestätigt')
                        dest=catalog.save_metadata(c,wid,verified,'matched')
                        outcome='matched'
                    elif row['state']=='identified' and m.get('provider')==known.get('provider') and m.get('reference_id')==known.get('reference_id'):
                        dest=wid;outcome='identified'
                    else:
                        dest=catalog.save_metadata(c,wid,known,'identified') or wid
                        outcome='identified'
                    if outcome=='identified':
                        c.execute('UPDATE works SET next_try=? WHERE id=?',(time.time()+30*86400,dest))
                    c.execute('UPDATE works SET attempts=MAX(attempts,1) WHERE id=?',(dest,))
                    self.record_check(row['attempts']==0,from_template=True,outcome=outcome)
                    self.metadata_state(phase='result',title=known['title'],outcome=outcome,
                                        provider_checks=[],from_cache=True,series_template=True,
                                        candidates=1 if verified else 0,warnings=[],seconds=0)
                    return True
            c.execute('UPDATE works SET next_try=?,attempts=attempts+1 WHERE id=?',(time.time()+3600,wid));c.execute('DELETE FROM metadata_priority WHERE work_id=?',(wid,))
        if not entry:return False
        providers=[p for p,k in [('TMDB','tmdb'),('TVDB','tvdb'),('OMDb','omdb')] if config.get(k) and (k!='omdb' or not metadata.omdb_status(config[k])['paused'])] or ['Wikidata (ohne API-Schlüssel)']
        self.metadata_state(phase='checking',title=m['title'],work_id=wid,providers=providers)
        started=time.monotonic()
        try:
            ck=catalog.digest(json.dumps(['v0531',config.get('imdb_generation'),m['title'],m['kind'],m.get('year'),m.get('season'),m.get('episode'),m.get('episode_title'),entry['source'].get('title'),entry['source'].get('topic'),entry['source'].get('duration'),config.get('tmdb'),config.get('omdb'),config.get('tvdb'),config.get('tvdb_pin')],sort_keys=True))
            with self.db() as c:cached=c.execute('SELECT payload FROM metadata_cache WHERE id=? AND checked>?',(ck,time.time()-86400)).fetchone()
            if cached and not priority:result=json.loads(cached[0])
            else:
                # Shared provider concurrency cap avoids overwhelming sender APIs.
                with self.provider_slots:
                    result=core.candidates(entry['source'],m,{**config,'_force_provider_refresh':bool(priority)})
                if not result['warnings'] and not result.get('deferred_providers'):
                    with self.db() as c:c.execute('INSERT OR REPLACE INTO metadata_cache VALUES(?,?,?)',(ck,json.dumps(result),time.time()))
            chosen=catalog.auto_choice(m,result['candidates']);recognized=chosen or catalog.work_choice(m,result['candidates'])
            outcome='retry' if result['warnings'] or result.get('deferred_providers') else 'review'
            for write_attempt in range(4):
                try:
                    with self.db() as c:
                        now=c.execute('SELECT meta,state FROM works WHERE id=?',(wid,)).fetchone()
                        if not now or now['meta']!=original or now['state']=='manual':return True
                        outcome,dest=self.store_outcome(c,row,entry,m,recognized,chosen,result,outcome)
                        # Only final provider results may be shared; transient errors stay local.
                        if outcome!='retry' and (recognized or not (result['warnings'] or result.get('deferred_providers'))):self.mesh_publish(c,'match.result',wid,dest,outcome,recognized or m,providers)
                    break
                except sqlite3.OperationalError as e:
                    if not sqlite_busy(e) or write_attempt==3:raise
                    self.sqlite_busy_count+=1
                    if self.stop.wait(.15*(write_attempt+1)):raise InterruptedError('Erkennung beendet') from None
            self.record_check(row['attempts']==0,outcome=outcome);self.metadata_state(phase='result',title=recognized['title'] if recognized else m['title'],outcome=outcome,provider_checks=result.get('provider_checks',[]),from_cache=bool(cached),candidates=len(result['candidates']),warnings=result['warnings'],seconds=round(time.monotonic()-started,2),providers=providers)
        except Exception as e:
            diagnostics.error('metadata_failed',e,work_id=wid)
            # A local SQLite lock must not defer an otherwise valid work for an hour.
            delay=30 if sqlite_busy(e) else 3600
            try:
                with self.db() as c:
                    c.execute("UPDATE works SET state='retry',next_try=? WHERE id=?",(time.time()+delay,wid))
                    catalog.set_state(c,'metadata_error',core.safe_error(e))
            except sqlite3.OperationalError as db_error:
                if not sqlite_busy(db_error):raise
                self.sqlite_busy_count+=1
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
    def metadata_loop(self,index=0):
        while not self.stop.is_set():
            requested=max(1,min(MAX_RECOGNITION_WORKERS,int(self.settings().get('metadata_workers',2))))
            if index>=requested or not self.settings().get('auto_metadata',True):
                self.stop.wait(2);continue
            try:busy=self.metadata_once()
            except sqlite3.OperationalError as e:
                if not sqlite_busy(e):raise
                self.sqlite_busy_count+=1
                busy=False  # Recheck promptly; do not restart or lose the worker.
            # Preserve the existing wake/idle contract for UI priorities and
            # immediate interruption, also with more than one worker.
            self.metadata_wake.wait(METADATA_PAUSE if busy else 2)
            self.metadata_wake.clear()

    def episode_loop(self,index=0):
        while not self.stop.is_set():
            requested=max(1,min(MAX_EPISODE_WORKERS,int(self.settings().get('episode_workers',2))))
            if index>=requested or not self.settings().get('auto_metadata',True):
                self.stop.wait(2);continue
            try:busy=self.metadata_once('episode')
            except sqlite3.OperationalError as exc:
                if not sqlite_busy(exc):raise
                self.sqlite_busy_count+=1;busy=False
            self.metadata_wake.wait(METADATA_PAUSE if busy else 2)
            self.metadata_wake.clear()

    def artwork_loop(self):
        import artwork
        while not self.stop.is_set():
            try:artwork.run_once(self)
            except sqlite3.OperationalError as e:
                if not sqlite_busy(e):raise
                # Only the short artwork claim is postponed; keep this worker alive.
                self.sqlite_busy_count+=1
            self.stop.wait(3)

    # Mesh: share recognition results between instances through a synced folder (meshjournal).
    def mesh_loop(self):
        while not self.stop.is_set():
            self.mesh_tick()
            if self.stop.wait(2 if self.mesh_pending or self.mesh_backlog.get('done') is False else 30):break
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
        direct=not folder and (meshpeer.valid_key(config.get('mesh_key')) or bool(meshpeer.peer_list(config)))
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
                self.mesh_status={'enabled':True,'folder':folder,'node':journal.node,'name':journal.name,'partitions':len(parts),'media_shared':bool(meshjournal.sync_root(config.get('download_dir') or '')),'imported':self.mesh_imported,'invalid':self.mesh_invalid,'direct':direct,'peers':list(self.mesh_peers.values()),'backlog':self.mesh_backlog,'importing':self.mesh_pending,
                    'nodes':[{'node':n,'name':str(i.get('name') or n[:8])[:80],'self':n==journal.node,'active':n in members,'recognizing':i.get('recognizing') is True,'rate':i.get('rate'),'version':str(i.get('version',''))[:20],'age':max(0,int(current-float(i.get('time') or 0)))} for n,i in sorted(nodes.items())]}
        except (meshjournal.MeshError,OSError) as e:
            # Standalone fallback: a missing mount never blocks local recognition.
            if self.mesh_status.get('error')!=core.safe_error(e):diagnostics.error('mesh_unavailable',e)
            self.mesh_off(folder=folder,error=core.safe_error(e))
    def mesh_peer_sync(self,config,journal):
        # Every configured connection is mirrored in turn; several connections (also both
        # directions or a full mesh) are fine because files are only copied when missing.
        previous=self.mesh_peers;current={}
        for peer in meshpeer.peer_list(config):
            url=peer['url'];old=previous.get(url,{})
            try:
                result=meshpeer.Peer(url,peer['key']).sync(journal.root,journal.node)
                if old.get('error'):diagnostics.event('mesh_peer_connected',seconds=result['seconds'])
                current[url]={'url':url,**result}
            except (meshpeer.PeerError,OSError) as e:
                if old.get('error')!=core.safe_error(e):diagnostics.error('mesh_peer_failed',e)
                current[url]={'url':url,'error':core.safe_error(e),'last':old.get('time') or old.get('last'),'peer':old.get('peer','')}
            if self.stop.is_set():break
        self.mesh_peers=current
    MESH_IMPORT_BATCH=250;MESH_IMPORT_SECONDS=20;MESH_BACKFILL_PAUSE=20
    def mesh_import(self,journal):
        # Small transactions and a time budget per round: a large backlog from another system
        # (e.g. tens of thousands of earlier results) must not starve the web UI, the
        # heartbeat or the direct connection on a weak NAS. The rest follows next round.
        with self.db() as c:cursors=catalog.get_state(c,'mesh_cursors',{})
        started=time.monotonic();self.mesh_pending=False
        while not self.stop.is_set():
            events,cursors,invalid=journal.read(cursors,limit=self.MESH_IMPORT_BATCH)
            with self.db() as c:
                for event in events:
                    if self.mesh_apply(c,event):self.mesh_imported+=1
                catalog.set_state(c,'mesh_cursors',cursors)
            self.mesh_invalid+=invalid
            if len(events)<self.MESH_IMPORT_BATCH:break
            if time.monotonic()-started>=self.MESH_IMPORT_SECONDS:self.mesh_pending=True;break
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
    def mesh_backfill(self,journal,limit=500):
        state='mesh_backfill_'+journal.node;published=0
        # Pace with the other side: nothing new while the connection fails, at most one batch per 20 s.
        if (self.mesh_peers and all(p.get('error') for p in self.mesh_peers.values())) or time.monotonic()-self.mesh_backfill_at<self.MESH_BACKFILL_PAUSE:return 0
        self.mesh_backfill_at=time.monotonic()
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
