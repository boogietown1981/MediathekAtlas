"""Personal IMDb dataset snapshot: bounded imports and atomic publication."""
import csv,gzip,io,json,os,re,shutil,sqlite3,threading,time,unicodedata
from pathlib import Path
import core,diagnostics
WEEK=7*86400
BASE='https://datasets.imdbws.com/'
HEADERS={
 'basics':['tconst','titleType','primaryTitle','originalTitle','isAdult','startYear','endYear','runtimeMinutes','genres'],
 'ratings':['tconst','averageRating','numVotes'],
 'episode':['tconst','parentTconst','seasonNumber','episodeNumber'],
 'akas':['titleId','ordering','title','region','language','types','attributes','isOriginalTitle'],
 'crew':['tconst','directors','writers'],
 'principals':['tconst','ordering','nconst','category','job','characters'],
 'people':['nconst','primaryName','birthYear','deathYear','primaryProfession','knownForTitles']}
FILES={k:('name.basics' if k=='people' else 'title.'+k)+'.tsv.gz' for k in HEADERS}
VERSION=2
ACTIVE=None

def norm(s):
    return ' '.join(re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKC',s or '').casefold().replace('&',' und ')).split())
def number(s):return None if s in (None,'\\N','') else int(s)

def build(path,files,progress=lambda **k:None,cancelled=lambda:False):
    c=sqlite3.connect(path)
    try:
        c.executescript('PRAGMA journal_mode=DELETE; PRAGMA temp_store=FILE; PRAGMA cache_size=-32768; CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,primaryTitle TEXT,originalTitle TEXT,isAdult INTEGER,startYear INTEGER,endYear INTEGER,runtimeMinutes INTEGER,genres TEXT); CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER); CREATE TABLE title_episode(tconst TEXT PRIMARY KEY,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER); CREATE TABLE names(name TEXT,tconst TEXT,title TEXT,localized INTEGER); CREATE TABLE title_akas(titleId TEXT,ordering INTEGER,title TEXT,region TEXT,language TEXT,types TEXT,attributes TEXT,isOriginalTitle INTEGER); CREATE TABLE title_crew(tconst TEXT PRIMARY KEY,directors TEXT,writers TEXT); CREATE TABLE title_principals(tconst TEXT,ordering INTEGER,nconst TEXT,category TEXT,job TEXT,characters TEXT); CREATE TABLE name_basics(nconst TEXT PRIMARY KEY,primaryName TEXT,birthYear INTEGER,deathYear INTEGER,primaryProfession TEXT,knownForTitles TEXT); CREATE TABLE snapshot(updated REAL); PRAGMA user_version=2;')
        counts={}
        for kind in HEADERS:
            rows=[];names=[];count=0
            with gzip.open(files[kind],'rt',encoding='utf-8',newline='') as f:
                reader=csv.reader(f,delimiter='\t',quoting=csv.QUOTE_NONE)
                if next(reader,None)!=HEADERS[kind]:raise ValueError('IMDb: unerwartetes Dateiformat '+kind)
                for r in reader:
                    if len(r)!=len(HEADERS[kind]):raise ValueError('IMDb: beschädigte Datenzeile '+kind)
                    count+=1
                    if kind=='basics':
                        rows.append((r[0],r[1],r[2],r[3],number(r[4]),number(r[5]),number(r[6]),number(r[7]),None if r[8]=='\\N' else r[8]))
                        names.extend((norm(t),r[0],t,0) for t in set(r[2:4]) if t!='\\N')
                    elif kind=='ratings':rows.append((r[0],float(r[1]),int(r[2])))
                    elif kind=='episode':rows.append((r[0],r[1],number(r[2]),number(r[3])))
                    elif kind=='akas':
                        rows.append(tuple(None if x=='\\N' else x for x in r));names.append((norm(r[2]),r[0],r[2],1))
                    elif kind=='people':rows.append((r[0],r[1],number(r[2]),number(r[3]),None if r[4]=='\\N' else r[4],None if r[5]=='\\N' else r[5]))
                    else:rows.append(tuple(None if x=='\\N' else x for x in r))
                    if count%5000==0:
                        flush(c,kind,rows,names);progress(phase='importing',dataset=kind,rows=count)
                        if cancelled():raise InterruptedError('IMDb-Import beendet')
                        if shutil.disk_usage(Path(path).parent).free<512*1024**2:raise OSError('IMDb: weniger als 512 MiB freier Speicher; bitte Speicher freigeben, das bisherige Archiv bleibt nutzbar')
                flush(c,kind,rows,names)
            if not count:raise ValueError('IMDb: leerer Datensatz '+kind)
            counts[kind]=count
        progress(phase='indexing',dataset='',rows=0)
        c.set_progress_handler(lambda:int(cancelled()),10000)
        c.executescript('CREATE INDEX principals_title ON title_principals(tconst,ordering); CREATE INDEX name_lookup ON names(name); CREATE INDEX episode_parent ON title_episode(parentTconst,seasonNumber,episodeNumber);')
        if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('IMDb-Datenbankprüfung fehlgeschlagen')
        c.execute('INSERT INTO snapshot VALUES(?)',(time.time(),));c.commit()
        return counts
    finally:c.close()

def flush(c,kind,rows,names):
    if rows:c.executemany('INSERT INTO '+('name_basics' if kind=='people' else 'title_'+kind)+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
    if names:c.executemany('INSERT INTO names VALUES(?,?,?,?)',names)
    c.commit();rows.clear();names.clear()

class Archive:
    def __init__(self,root,stop,on_update=lambda:None):
        self.root=Path(root)/'imdb';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'imdb_archive.db';self.stop=stop;self.on_update=on_update
        self._reader_local=threading.local()  # one read-only connection and bounded caches per worker
        self._metrics_lock=threading.Lock();self._metrics={'reader_opens':0,'query_hits':0,'query_misses':0,'credits_hits':0,'credits_misses':0}
        self.lock=threading.Lock();self.wake=threading.Event();self.state={'phase':'waiting'};self.retry_at=0;self.updated=0;self.version=0;self.failures=0
        if self.path.exists():
            try:
                with sqlite3.connect(self.path) as c:self.updated=c.execute('SELECT updated FROM snapshot').fetchone()[0];self.state={'phase':'ready'};self.version=c.execute('PRAGMA user_version').fetchone()[0]
            except sqlite3.Error:self.state={'phase':'error','error':'Vorhandenes IMDb-Archiv nicht lesbar'}
    def _count(self,kind):
        with self._metrics_lock:self._metrics[kind]+=1
    def status(self):
        with self._metrics_lock:performance=dict(self._metrics)
        with self.lock:return {**self.state,'updated':self.updated,'next_update':max(self.updated+WEEK if self.version==VERSION else 0,self.retry_at) if self.updated or self.retry_at else None,'ready':bool(self.updated),'path':str(self.path),'performance':performance}
    def progress(self,**kw):
        with self.lock:self.state.update(kw)
    def request(self):
        with self.lock:
            if self.state.get('phase') in ('downloading','importing','indexing'):return False
            self.wake.set();return True
    def due(self,now=None):
        return (time.time() if now is None else now)>=max(self.updated+WEEK if self.version==VERSION else 0,self.retry_at)
    def loop(self):
        while not self.stop.is_set():
            requested=self.wake.is_set();self.wake.clear()
            if requested or self.due():self.update()
            self.wake.wait(30)
    def fetch(self,kind,path):
        """Download one dataset; resume an interrupted transfer and reuse a fresh complete file.

        Diagnosis 0.5.15: a read timeout after 334 of 521 MB discarded every file of the round,
        and the next hourly attempt started all seven downloads again."""
        if path.exists() and time.time()-path.stat().st_mtime<2*86400:return
        part=path.with_name(path.name+'.part');have=part.stat().st_size if part.exists() else 0
        self.progress(phase='downloading',dataset=kind,received=have,total=0,error='',rows=0)
        with core.open_url(BASE+FILES[kind],**({'headers':{'Range':'bytes=%d-'%have}} if have else {})) as response:
            resumed=have and getattr(response,'status',200)==206
            if not resumed:have=0
            length=int(response.headers.get('Content-Length') or 0);total=have+length if length else 0
            # Reject a transfer before writing when it would consume the remaining disk reserve.
            if length and shutil.disk_usage(self.root).free<length+512*1024**2:
                raise OSError('IMDb: zu wenig freier Speicher für restlichen Download und 512 MiB Reserve; bisheriges Archiv bleibt nutzbar')
            with part.open('ab' if resumed else 'wb') as f:
                received=have;last=0
                while True:
                    if self.stop.is_set():raise InterruptedError('IMDb-Import beendet')
                    block=response.read(1024*1024)
                    if not block:break
                    if shutil.disk_usage(self.root).free<len(block)+512*1024**2:raise OSError('IMDb: zu wenig freier Speicher (mindestens 512 MiB frei lassen); das bisherige Archiv bleibt nutzbar')
                    f.write(block);received+=len(block)
                    if time.monotonic()-last>.5:self.progress(received=received,total=total);last=time.monotonic()
        if total and received!=total:raise ValueError('IMDb-Download unvollständig')
        os.replace(part,path)
    def update(self):
        staging=self.root/'building.db';files={};done=False
        try:
            staging.unlink(missing_ok=True)
            staging.with_name(staging.name+'-journal').unlink(missing_ok=True)
            for kind in HEADERS:
                if self.stop.is_set():raise InterruptedError('IMDb-Import beendet')
                path=self.root/(kind+'.tsv.gz');files[kind]=path
                self.fetch(kind,path)
            counts=build(staging,files,self.progress,self.stop.is_set)
            if self.stop.is_set():raise InterruptedError('IMDb-Import beendet')
            with staging.open('rb') as f:os.fsync(f.fileno())
            os.replace(staging,self.path)
            with sqlite3.connect(self.path) as c:self.updated=c.execute('SELECT updated FROM snapshot').fetchone()[0]
            self.version=VERSION;self.retry_at=0;self.failures=0;done=True;self.progress(phase='ready',counts=counts,error='')
            diagnostics.event('imdb_archive_updated',counts=counts)
            self.on_update()
        except Exception as e:
            # Back off 1 h, 2 h, 4 h … up to a day instead of downloading 1 GB again every hour.
            self.failures+=1
            self.retry_at=time.time()+min(86400,3600*2**(self.failures-1));self.progress(phase='error',error=core.safe_error(e),retry_at=self.retry_at)
            diagnostics.error('imdb_archive_failed',e,attempt=self.failures)
            # Without free space, keeping the downloads would only make it worse.
            if isinstance(e,OSError) and 'Speicher' in str(e):done=True
        finally:
            staging.unlink(missing_ok=True)
            staging.with_name(staging.name+'-journal').unlink(missing_ok=True)
            if done:
                for p in files.values():p.unlink(missing_ok=True);p.with_name(p.name+'.part').unlink(missing_ok=True)
    def _reader(self):
        """Reuse a read-only SQLite handle per worker; reopen after atomic snapshot replacement."""
        st=self.path.stat()
        identity=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        opened=getattr(self._reader_local,'opened',None)
        if opened and opened[0]==identity:return opened[1]
        if opened:opened[1].close()
        c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
        c.row_factory=sqlite3.Row
        self._reader_local.opened=(identity,c)
        self._count('reader_opens')
        self._reader_local.queries={}
        self._reader_local.credits={}
        return c
    def _lookup(self,sql,params,key):
        """Cache raw exact-match rows, never episode-specific final decisions."""
        cache=self._reader_local.queries
        if key in cache:
            self._count('query_hits');return cache[key]
        self._count('query_misses')
        hits=self._reader_local.opened[1].execute(sql,params).fetchall()
        if len(cache)>=1024:cache.clear()
        cache[key]=hits
        return hits
    def _credits(self,c,tconst):
        """Reuse series credits without sharing mutable lists across candidates."""
        from copy import deepcopy
        cache=self._reader_local.credits
        if tconst not in cache:
            self._count('credits_misses')
            if len(cache)>=256:cache.clear()
            cache[tconst]=credits(c,tconst)
        else:self._count('credits_hits')
        return deepcopy(cache[tconst])
    def candidates(self,row,meta):
        if not self.updated:return []
        c=self._reader()
        title=meta.get('title') or row.get('topic') or row.get('title');types=('tvSeries','tvMiniSeries') if meta.get('kind')=='series' else ('movie','tvMovie') if meta.get('kind')=='movie' else ('tvSeries','tvMiniSeries','movie','tvMovie')
        hits=self._lookup('SELECT DISTINCT b.*,r.averageRating,r.numVotes FROM names n JOIN title_basics b ON b.tconst=n.tconst LEFT JOIN title_ratings r ON r.tconst=b.tconst WHERE n.name=? AND b.titleType IN ('+','.join('?' for _ in types)+') LIMIT 21', (norm(title),*types),('title',norm(title),types))
        if len(hits)>20:return []
        out=[]
        for h in hits:
            kind='series' if h['titleType'] in ('tvSeries','tvMiniSeries') else 'movie'
            m={**meta,'title':title,'kind':kind,'year':h['startYear'],'provider':'IMDb Offline','reference_id':h['tconst'],'genres':(h['genres'] or '').split(',') if h['genres'] else [],'genre_source':'IMDb Offline','similarity':1.0,'confidence':'high','year_mismatch':bool(meta.get('year') and h['startYear'] and meta['year']!=h['startYear']),'episode_verified':False,'runtime_agrees':False,'runtime_mismatch':False,'rating':h['averageRating'],'votes':h['numVotes'],'reason':'Exakter Titel im lokalen IMDb-Archiv','season':None,'episode':None,'poster':'','episode_reference_id':None}
            if kind=='movie' and h['runtimeMinutes'] and row.get('duration'):
                delta=abs(h['runtimeMinutes']*60-row['duration']);m['runtime_agrees']=delta<=max(300,h['runtimeMinutes']*6);m['runtime_mismatch']=not m['runtime_agrees']
            if kind=='series':
                epname=norm(meta.get('episode_title') or row.get('title'))
                eps=self._lookup('SELECT DISTINCT e.*,b.primaryTitle,b.runtimeMinutes FROM names n JOIN title_episode e ON e.tconst=n.tconst JOIN title_basics b ON b.tconst=e.tconst WHERE e.parentTconst=? AND n.name=? LIMIT 2', (h['tconst'],epname),('episode',h['tconst'],epname))
                number_fallback=False
                # SxxExx from the offer can identify the canonical episode even if
                # the broadcaster does not provide its official episode title.
                if len(eps)!=1 and isinstance(meta.get('season'),int) and isinstance(meta.get('episode'),int) and meta['season']>=0 and meta['episode']>0:
                    eps=self._lookup('SELECT e.*,b.primaryTitle,b.runtimeMinutes FROM title_episode e JOIN title_basics b ON b.tconst=e.tconst WHERE e.parentTconst=? AND e.seasonNumber=? AND e.episodeNumber=? LIMIT 2',
                                     (h['tconst'],meta['season'],meta['episode']),('episode_numbers',h['tconst'],meta['season'],meta['episode']))
                    number_fallback=len(eps)==1
                if len(eps)==1:
                    e=eps[0];season=e['seasonNumber'];episode=e['episodeNumber']
                    if e['runtimeMinutes'] and row.get('duration'):
                        m['runtime_mismatch']=abs(e['runtimeMinutes']*60-row['duration'])>max(300,e['runtimeMinutes']*6)
                        m['runtime_agrees']=not m['runtime_mismatch']
                    if season is not None and episode and (meta.get('season') in (None,season)) and (meta.get('episode') in (None,episode)):
                        m.update(season=season,episode=episode,episode_verified=True,episode_title=(e['primaryTitle'] if number_fallback else meta.get('episode_title') or row['title']),episode_reference_id=e['tconst'],reason='IMDb-Episode anhand eindeutiger Staffel-/Folgenummer bestätigt' if number_fallback else 'Serien- und Episodentitel im IMDb-Archiv eindeutig zugeordnet')
            if self.version>=2:
                m['show_credits']=self._credits(c,h['tconst']) if kind=='series' else {}
                m.update(self._credits(c,m.get('episode_reference_id') or h['tconst']) if kind=='movie' or m.get('episode_verified') else {})
            out.append(m)
        return out


def credits(c,tconst):
    result={'cast':[],'directors':[],'writers':[]}
    for r in c.execute("SELECT p.*,n.primaryName FROM title_principals p JOIN name_basics n ON n.nconst=p.nconst WHERE p.tconst=? ORDER BY p.ordering",(tconst,)):
        if r['category'] in ('actor','actress','self'):
            try:roles=json.loads(r['characters'] or '[]')
            except (ValueError,TypeError):roles=[]
            result['cast'].append({'name':r['primaryName'],'role':', '.join(roles) if isinstance(roles,list) else '', 'imdb_id':r['nconst']})
    crew=c.execute('SELECT directors,writers FROM title_crew WHERE tconst=?',(tconst,)).fetchone()
    if crew:
        for field in ('directors','writers'):
            for person in (crew[field] or '').split(','):
                name=c.execute('SELECT primaryName FROM name_basics WHERE nconst=?',(person,)).fetchone()
                if name:result[field].append(name[0])
    return result
