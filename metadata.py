"""Provider metadata and evidence-based episode reconciliation."""
import re,time,threading,hashlib,json,socket,ssl,http.client,urllib.error
import core,diagnostics,provider_stats,negative_cache
_CACHE={};_WD_CACHE={};_LOCK=threading.Lock()
# Short provider-scoped outage circuit: network failures must not repeatedly
# occupy all metadata workers. This is strictly in-memory; work-level retry
# dates and matching evidence remain durable in SQLite.
_OUTAGE_LOCK=threading.Lock()
_OUTAGES={}
_OUTAGE_THRESHOLD=2
_OUTAGE_WINDOW=180.0
_OUTAGE_BASE_PAUSE=180.0
_OUTAGE_MAX_PAUSE=900.0

def _network_failure(exc):
    """Only transport failures trigger a circuit; a normal 404 is not an outage."""
    return isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError,
          socket.timeout,socket.gaierror,ssl.SSLError,http.client.RemoteDisconnected,
          ConnectionResetError,ConnectionAbortedError,ConnectionRefusedError,
          BrokenPipeError)) and not isinstance(exc,urllib.error.HTTPError)

def provider_pause(provider):
    """Return remaining seconds for provider; zero means the provider may run."""
    with _OUTAGE_LOCK:
        state=_OUTAGES.get(provider)
        return max(0.0,state['until']-time.monotonic()) if state else 0.0

def network_provider_status(provider):
    seconds=provider_pause(provider)
    return {'paused':bool(seconds),'remaining_seconds':int(seconds+0.999),
            'reason':'transient_network' if seconds else None}

def provider_success(provider):
    """A successful request ends a transient outage without touching other providers."""
    with _OUTAGE_LOCK:_OUTAGES.pop(provider,None)

RATE_LIMIT_DEFAULT=300.0;RATE_LIMIT_MIN=60.0
def _rate_limited(exc):
    """0.6.58: seconds to wait after HTTP 429/503 (Retry-After, 60 s to 15 min), else 0."""
    if not isinstance(exc,urllib.error.HTTPError) or exc.code not in (429,503):return 0.0
    try:wait=float((exc.headers or {}).get('Retry-After') or RATE_LIMIT_DEFAULT)
    except (TypeError,ValueError):wait=RATE_LIMIT_DEFAULT
    return max(RATE_LIMIT_MIN,min(_OUTAGE_MAX_PAUSE,wait))

def provider_failure(provider,exc):
    """After repeated transport errors, cool down that provider only.

    0.6.58 (Diagnose 20.11. nachts: 78× „HTTP 429 Too Many Requests“ von Wikidata in einer Stunde): a provider
    that asks us to slow down pauses at once, for as long as it asks; its works wait instead of failing.
    """
    limited=_rate_limited(exc)
    if limited:
        now=time.monotonic()
        with _OUTAGE_LOCK:
            old=_OUTAGES.get(provider) or {'first':now,'last':now,'count':0,'until':0.0,'opens':0}
            old['last']=now;old['count']+=1
            if now+limited>old['until']:
                old['until']=now+limited
                diagnostics.event('provider_rate_limited',provider=provider,seconds=round(limited),status=exc.code)
            _OUTAGES[provider]=old
        return True
    if not _network_failure(exc):return False
    now=time.monotonic()
    with _OUTAGE_LOCK:
        old=_OUTAGES.get(provider)
        if not old or (now-old.get('last',now)>3600 and now>=old['until']):
            old={'first':now,'last':now,'count':0,'until':0.0,'opens':0}
        elif now-old['first']>_OUTAGE_WINDOW:
            # Reset short-window failures, but remember repeated outages for
            # exponential cooldowns after the previous pause has expired.
            old['first']=now
            old['count']=0
        old['count']+=1
        old['last']=now
        if old['count']>=_OUTAGE_THRESHOLD and now>=old['until']:
            old['opens']+=1
            old['until']=now+min(_OUTAGE_MAX_PAUSE,_OUTAGE_BASE_PAUSE*(2**min(old['opens']-1,3)))
            diagnostics.event('provider_transient_pause',provider=provider,
                              seconds=round(old['until']-now),
                              failures=old['count'])
        _OUTAGES[provider]=old
        return old['until']>now


GENRES={'Kinder & Familie':'Familie','Comedy':'Komödie','Crime':'Krimi','Documentary':'Dokumentation','Dokumentarfilm':'Dokumentation','Family':'Familie','Familienserie':'Familie','Familienfilm':'Familie','Kids':'Kinder','Kinder':'Kinder','Zeichentrickserie':'Animation','animated television series':'Animation','Familie':'Familie','Children':'Kinder','Romance':'Romantik','Liebesfilm':'Romantik','Sci-Fi':'Science-Fiction','Science Fiction':'Science-Fiction','Animation':'Animation','Adventure':'Abenteuer','Action':'Action','History':'Historie','War':'Kriegsfilm','Krieg & Militär':'Kriegsfilm','Militär':'Kriegsfilm','TV Movie':'TV-Film','Music':'Musik','Mystery':'Mystery','Horror':'Horror','Fantasy':'Fantasy','Drama':'Drama','Thriller':'Thriller',
        'Biography':'Biografie','Biographie':'Biografie','Biopic':'Biografie','Historisch':'Historie','Historien':'Historie','Geschichte':'Historie','Krieg':'Kriegsfilm','Kriminal':'Krimi','Kriminalität':'Krimi','Dokumentar':'Dokumentation','Doku':'Dokumentation','Liebe':'Romantik','Romanze':'Romantik','Romantisch':'Romantik','Komödien':'Komödie','Comedy Serie':'Komödie','Sitcom':'Komödie','Zeichentrick':'Animation','Anime':'Animation','Animiert':'Animation','Trickfilm':'Animation','Fernsehfilm':'TV-Film','Fernseh':'TV-Film','TV':'TV-Film','Musikfilm':'Musik','Musical':'Musical','Musicalfilm':'Musical','Sport':'Sport','Sports':'Sport','Western':'Western','Abenteuer':'Abenteuer','Mysteryfilm':'Mystery','Suspense':'Thriller','Psychothriller':'Thriller','Kinderfilm':'Kinder','Kinderserie':'Kinder','Talk':'Talk','Talk Show':'Talk','Talkshow':'Talk','News':'Nachrichten','Reality':'Reality-TV','Reality TV':'Reality-TV','Game Show':'Spielshow','Gameshow':'Spielshow','Quiz':'Spielshow','Quizshow':'Spielshow','Soap':'Seifenoper','Short':'Kurzfilm','Kurz':'Kurzfilm','Film Noir':'Film noir','Politics':'Politik','Martial Arts':'Martial Arts','Science':'Wissenschaft','Wissen':'Wissenschaft','Satire':'Satire','Kabarett':'Kabarett','Erotik':'Erotik','Erotic':'Erotik','Mini Series':'Miniserie','Miniseries':'Miniserie','Travel':'Reise','Food':'Kochen','Cooking':'Kochen'}
# Words that only name the medium; a genre made of nothing else carries no information.
GENRE_NOISE={'film','spielfilm','serie','fernsehserie','tv serie','tv series','series','movie','fernsehsendung','sendung','webserie','tv show'}
GENRE_AFFIX=re.compile(r'^(?:film|fernseh|tv)\s*|\s*(?:film|filme|serie|fernsehserie|tv serie|series|movie|reihe|sendung|show)$')
def genre_key(value):
    """Spelling-insensitive key: case, hyphens, '&'/'und'/'and' and spacing do not matter."""
    text=str(value).casefold().replace('ß','ss').replace('&',' ')
    return ' '.join(w for w in re.split(r'[^\w]+',text) if w and w not in ('und','and'))
_GENRE_KEYS={genre_key(k):v for k,v in GENRES.items()}
_GENRE_KEYS.update({genre_key(v):v for v in GENRES.values()})
def genre_names(value):
    """Canonical German genre names for one provider label (empty when it names no genre)."""
    raw=str(value).strip()
    if raw in ('','N/A'):return []
    k=genre_key(raw)
    if not k or k in GENRE_NOISE:return []
    for probe in (k,k.replace(' ',''),GENRE_AFFIX.sub('',k).strip(),GENRE_AFFIX.sub('',k.replace(' ','')).strip()):
        if probe in _GENRE_KEYS:return [_GENRE_KEYS[probe]]
        if probe.endswith('s') and probe[:-1] in _GENRE_KEYS:return [_GENRE_KEYS[probe[:-1]]]
    parts=[p for p in re.split(r'\s*(?:&|/|,|\+|\bund\b|\band\b)\s*',raw) if p.strip()]
    if len(parts)>1:
        names=[_GENRE_KEYS.get(genre_key(p)) for p in parts]
        if all(names):return names
    return [raw[:1].upper()+raw[1:]]
def genres(values):return sorted({name for g in values for name in genre_names(g)})
def norm(s):
    return re.sub(r'[^\w]+',' ',str(s).casefold().replace('&',' und ')).strip()
def episode_title(title,show):
    title=re.sub(r'(?i)\bS\d+[ /._-]*E\d+\b|\b\d+x\d+\b|\b(?:Staffel\s*\d+\W*)?Folge\s*\d+\b','',title)
    if norm(title).startswith(norm(show)):
        title=re.sub(re.escape(show)+r'\s*[:\-–]?\s*','',title,count=1,flags=re.I)
    return title.strip(' ()-:')
_OMDB_PAUSED={}
_OMDB_FILE=None
_OMDB_REQUEST_LOCK=threading.Lock()
def configure_provider_state(path):
    global _OMDB_FILE
    from pathlib import Path
    _OMDB_FILE=Path(path)
    try:
        data=json.loads(_OMDB_FILE.read_text())
        with _LOCK:
            for key,value in data.items():
                if re.fullmatch(r'[a-f0-9]{64}',key) and isinstance(value,list) and len(value)==3 and isinstance(value[0],(int,float)) and value[0]>time.time() and value[1] in ('limit','inactive','key','auth','response'):_OMDB_PAUSED[key]=tuple(value)
    except (OSError,ValueError,TypeError,AttributeError):pass

def save_provider_state():
    if _OMDB_FILE is None:return
    try:
        with _LOCK:data={k:v for k,v in _OMDB_PAUSED.items() if v[0]>time.time()}
        tmp=_OMDB_FILE.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(_OMDB_FILE)
    except OSError as e:diagnostics.error('provider_pause_save_failed',e)

def omdb_status(key):
    with _LOCK:paused=_OMDB_PAUSED.get(hashlib.sha256(key.encode()).hexdigest())
    remaining=max(0,int(paused[0]-time.time()+.999)) if paused else 0
    return {'paused':bool(remaining),'remaining_seconds':remaining,'retry_at':paused[0] if remaining else None,'reason':paused[1] if remaining else None}

class OMDbError(ValueError):
    def __init__(self,reason,status=0):
        self.reason=reason;self.status=status
        messages={'limit':'Anfragelimit erreicht. OMDb-Abfragen werden eine Stunde pausiert.',
                  'inactive':'Schlüssel laut OMDb noch nicht aktiviert.',
                  'key':'Schlüssel von OMDb abgelehnt.',
                  'auth':'Zugriff von OMDb abgelehnt; die Antwort nennt keinen eindeutigen Grund.',
                  'network':'Netzwerkfehler oder Zeitüberschreitung.',
                  'response':'OMDb lieferte keine gültige API-Antwort.'}
        super().__init__('OMDb'+(' HTTP '+str(status) if status else '')+': '+messages[reason])
def omdb_failure(data,status):
    # Never expose arbitrary provider text, which could echo a credential or URL.
    message=str(data.get('Error','')).casefold()
    if 'limit' in message or 'quota' in message or status==429:return OMDbError('limit',status)
    if 'activat' in message:return OMDbError('inactive',status)
    if 'key' in message:return OMDbError('key',status)
    if status in (401,403):return OMDbError('auth',status)
    return OMDbError('response',status)
def omdb(params,key,force=False):
    # Serialise requests so only one request can test an expired cooldown.
    with _OMDB_REQUEST_LOCK:return _omdb(params,key,force)
def _omdb(params,key,force=False):
    credential=hashlib.sha256(key.encode()).hexdigest()
    ck=hashlib.sha256(json.dumps([params,key],sort_keys=True).encode()).hexdigest()
    with _LOCK:cached=_CACHE.get(ck);paused=_OMDB_PAUSED.get(credential)
    if not force:
        if paused and time.time()<paused[0]:raise OMDbError(paused[1],paused[2])
        if cached and time.monotonic()-cached[0]<21600:return cached[1]
    try:
        status=200
        try:
            with core.open_url('https://www.omdbapi.com/?'+core.urllib.parse.urlencode({'apikey':key,**params})) as response:raw=response.read(65537)
        except core.urllib.error.HTTPError as e:
            status=e.code
            try:raw=e.read(65537)
            finally:e.close()
        if len(raw)>65536:raise OMDbError('response',status)
        try:data=json.loads(raw)
        except (ValueError,UnicodeDecodeError):data={}
        if not isinstance(data,dict):data={}
        if status>=400 or data.get('Response')=='False':
            if status==200 and re.search(r'(?i)not found|incorrect imdb',str(data.get('Error',''))):return {}
            raise omdb_failure(data,status)
        if not data:raise OMDbError('response',status)
    except (core.urllib.error.URLError,TimeoutError,OSError) as e:
        raise OMDbError('network') from None
    except OMDbError as e:
        with _LOCK:_OMDB_PAUSED[credential]=(time.time()+3600,e.reason,e.status)
        save_provider_state()
        diagnostics.event('provider_access_error','WARNING',provider='OMDb',reason=e.reason,http_status=e.status)
        raise
    with _LOCK:
        _OMDB_PAUSED.pop(credential,None)
        if len(_CACHE)>=2048:_CACHE.pop(next(iter(_CACHE)))
        _CACHE[ck]=(time.monotonic(),data)
    if paused:save_provider_state()
    return data

def test_omdb(key):
    if not key:return {'ok':False,'reason':'missing','message':'Kein OMDb-Schlüssel gespeichert. Zuerst Einstellungen speichern.'}
    try:
        data=omdb({'i':'tt0133093','plot':'short'},key,force=True)
        if data.get('imdbID')!='tt0133093':raise OMDbError('response',200)
        result={'ok':True,'reason':'ok','http_status':200,'message':'OMDb erreichbar. Gespeicherter Schlüssel akzeptiert; Testtitel erfolgreich gelesen.'}
    except OMDbError as e:result={'ok':False,'reason':e.reason,'http_status':e.status,'message':str(e)}
    diagnostics.event('provider_connection_test',provider='OMDb',**result)
    return result

def resolve_episode(meta,candidate,episodes):
    wanted=episode_title(meta.get('episode_title') or meta.get('_source_title',''),candidate['title'])
    matches=[]
    for ep in episodes:
        if not wanted or norm(wanted)!=norm(ep.get('name','')):continue
        # Existing season/episode evidence must not conflict with provider numbering.
        if meta.get('season') is not None and int(ep.get('season_number',-1))!=meta['season']:continue
        if meta.get('episode') is not None and int(ep.get('episode_number',-1))!=meta['episode']:continue
        matches.append(ep)
    # Broadcaster labels often contain only "S02E03" or "Staffel 2 Folge 3".
    # Numeric evidence is safe only with an explicit season+episode and a complete
    # provider listing. Never infer episode numbers from list position or dates.
    if not matches and candidate.get('episode_scan_complete') is True and (
        isinstance(meta.get('season'),int) and isinstance(meta.get('episode'),int)
        and meta['season']>=0 and meta['episode']>0):
        matches=[ep for ep in episodes if ep.get('season_number')==meta['season'] and ep.get('episode_number')==meta['episode']]
    unique={(e.get('season_number'),e.get('episode_number')):e for e in matches}
    if len(matches)==1 and len(unique)==1:
        ep=next(iter(unique.values()));candidate.update(season=ep['season_number'],episode=ep['episode_number'],episode_title=ep['name'],episode_verified=True,description=ep.get('overview') or candidate['description'])
        runtime=ep.get('runtime');duration=meta.get('_source_duration')
        if isinstance(runtime,(int,float)) and runtime>0:
            candidate['episode_runtime_seconds']=runtime*60
        if isinstance(runtime,(int,float)) and runtime>0 and duration:
            candidate['runtime_mismatch']=abs(runtime*60-duration)>max(300,runtime*6)
            candidate['runtime_agrees']=not candidate['runtime_mismatch']
    return candidate

def tmdb_candidates(row,meta,key,kind,title):
    endpoint='tv' if kind=='series' else 'movie';hits=core.tmdb('search/'+endpoint,key,{'query':title}).get('results',[])
    out=[]
    for hit in sorted(hits,key=lambda h:core.title_similarity(title,h.get('title') or h.get('name')),reverse=True)[:3]:
        score=max(core.title_similarity(title,hit.get('title') or hit.get('name')),1 if norm(title)==norm(hit.get('title') or hit.get('name')) else 0)
        if score<.85:continue
        d=core.tmdb(endpoint+'/'+str(hit['id']),key);date=d.get('release_date') or d.get('first_air_date') or ''
        year=int(date[:4]) if date[:4].isdigit() else None;runtime=d.get('runtime') if kind=='movie' else None
        mismatch=bool(runtime and row.get('duration') and abs(row['duration']/60-runtime)>max(8,runtime*.15))
        c={**meta,'title':d.get('title') or d.get('name'),'kind':kind,'year':year,'provider':'TMDB','reference_id':str(d['id']),
           'description':d.get('overview') or meta.get('description',''),'poster':'https://image.tmdb.org/t/p/w500'+d['poster_path'] if d.get('poster_path') else '',
           'genres':genres(g['name'] for g in d.get('genres',[]) if g.get('name')),'genre_source':'TMDB','rating':d.get('vote_average'),'votes':d.get('vote_count'),'rating_source':'TMDB','similarity':score,
           'year_mismatch':bool(kind=='movie' and meta.get('year') and year!=meta['year']),'runtime_mismatch':mismatch,'runtime_agrees':bool(runtime and row.get('duration') and not mismatch),
           'episode_verified':False,'reason':'Titel, Medienart und zusätzliche Quellenbelege werden verglichen.'}
        if kind=='series':
            # Only a stable typical TV runtime qualifies; mixed-duration
            # series keep the expected duration unknown rather than guessed.
            durations=[x for x in (d.get('episode_run_time') or [])
                       if isinstance(x,(int,float)) and 1<=x<=240]
            if durations and max(durations)-min(durations)<=max(3,min(durations)*.2):
                c['reference_runtime_seconds']=round(sum(durations)/len(durations)*60)
            # Series overview kept apart: resolve_episode replaces description with the episode plot.
            c['show_description']=d.get('overview') or ''
            c['episode_title']=meta.get('episode_title') or row['title'];epmeta={**meta,'_source_title':row['title'],'_source_duration':row.get('duration')};episodes=[]
            seasons=d.get('seasons',[])
            if meta.get('season') is not None:seasons=[{'season_number':meta['season']}]
            # Bounded provider requests; unsupported very long series remain reviewable.
            c['episode_scan_complete']=len(seasons)<=24
            for season in seasons[:24]:
                number=season.get('season_number')
                if number is None:continue
                try:
                    season_data=core.tmdb(f"tv/{d['id']}/season/{number}",key)
                except ValueError as exc:
                    # One unavailable/missing season is not a failure of the
                    # series identity. Never claim a complete episode scan.
                    if 'HTTP 404' not in str(exc):raise
                    c['episode_scan_complete']=False
                    diagnostics.event('tmdb_season_unavailable',provider='TMDB',season=number,
                                      series_id=str(d['id'])[:32])
                    continue
                episodes.extend(season_data.get('episodes',[]))
            if c['episode_scan_complete']:
                resolve_episode(epmeta,c,episodes)
            else:
                c['episode_verified']=False
                c['reason']='Serienmetadaten erkannt; mindestens eine Staffel konnte nicht vollständig geprüft werden.' 
        out.append(c)
    return out

def parse_ratings(data):
    """Preserve source scales; RT percentage is not a star rating."""
    out=[]
    for r in data.get('Ratings') or []:
        if not isinstance(r,dict):continue
        source,value=r.get('Source'),str(r.get('Value',''))
        patterns={'Internet Movie Database':(r'(\d+(?:\.\d+)?)/10',10),'Rotten Tomatoes':(r'(\d+)%',100),'Metacritic':(r'(\d+)/100',100)}
        if source not in patterns:continue
        pattern,maximum=patterns[source];match=re.fullmatch(pattern,value)
        if match and 0<=float(match[1])<=maximum and not any(x['source']==source for x in out):
            out.append({'source':source,'value':value,'via':'OMDb'})
    return out

def omdb_candidates(row,meta,key,kind,title):
    params={'t':title,'type':kind,'plot':'full'}
    if kind=='movie' and meta.get('year'):params['y']=meta['year']
    d=omdb(params,key)
    if not d or d.get('Type')!=kind:return []
    score=max(core.title_similarity(title,d.get('Title','')),1 if norm(title)==norm(d.get('Title','')) else 0)
    if score<.85:return []
    y=re.match(r'\d{4}',d.get('Year',''));year=int(y[0]) if y else None
    rt=re.search(r'\d+',d.get('Runtime',''));runtime=int(rt[0]) if rt else 0
    mismatch=bool(kind=='movie' and runtime and row.get('duration') and abs(row['duration']/60-runtime)>max(8,runtime*.15))
    c={**meta,'title':d['Title'],'kind':kind,'year':year,'provider':'OMDb','reference_id':d.get('imdbID'),'description':d.get('Plot') if d.get('Plot') not in ('',None,'N/A') else meta.get('description',''),
       'genres':genres(d.get('Genre','').split(',')),'genre_source':'OMDb','poster':d.get('Poster') if str(d.get('Poster','')).startswith('https://') else '',
       'rating':float(d['imdbRating']) if str(d.get('imdbRating','')).replace('.','',1).isdigit() else None,'votes':int(str(d['imdbVotes']).replace(',','')) if str(d.get('imdbVotes','')).replace(',','').isdigit() else None,'rating_source':'IMDb','ratings':parse_ratings(d),'similarity':score,'year_mismatch':bool(kind=='movie' and meta.get('year') and year!=meta['year']),'runtime_mismatch':mismatch,
       'runtime_agrees':bool(kind=='movie' and runtime and row.get('duration') and not mismatch),'episode_verified':False,'reason':'OMDb-Titel, Medienart, Laufzeit und Episodendaten.'}
    if kind=='series':
        if 1<=runtime<=240:c['reference_runtime_seconds']=runtime*60
        c['episode_title']=meta.get('episode_title') or row['title'];episodes=[]
        count=int(d.get('totalSeasons','0')) if str(d.get('totalSeasons','')).isdigit() else 0
        seasons=[meta['season']] if meta.get('season') is not None else list(range(1,min(count,24)+1))
        for season in seasons:
            season_data=omdb({'i':d['imdbID'],'Season':season},key)
            for ep in season_data.get('Episodes',[]):
                if str(ep.get('Episode','')).isdigit():episodes.append({'name':ep.get('Title',''),'season_number':season,'episode_number':int(ep['Episode'])})
        resolve_episode({**meta,'_source_title':row['title'],'_source_duration':row.get('duration')},c,episodes)
        if count>24 and meta.get('season') is None:c['episode_verified']=False
    return [c]

def tvdb_candidates(row,meta,credential,kind,title):
    if kind!='series':return []
    import tvdb
    key,pin=credential
    def get(path,params=None):return tvdb.request(path,key,pin,params)
    hits=get('search',{'query':title,'type':'series','language':'deu','limit':10}).get('data') or []
    out=[]
    for hit in hits:
        translated=(hit.get('translations') or {}).get('deu')
        names=[hit.get('name',''),translated or '']+(hit.get('aliases') or [])
        score=max((1 if norm(title)==norm(n) else core.title_similarity(title,n)) for n in names if isinstance(n,str))
        if score<.85 or not str(hit.get('tvdb_id','')).isdigit():continue
        sid=str(hit['tvdb_id'])
        try:d=get('series/'+sid+'/extended').get('data') or {}
        except tvdb.TVDBError as e:
            # 0.6.49: the search index still lists removed series ("TVDB HTTP 404" on the record). That is no
            # outage: skip the stale hit instead of turning the whole check into a provider error, which kept
            # the work in "Wiederholung" and blocked its classification for good.
            if getattr(e,'status',0)!=404:raise
            diagnostics.event('tvdb_stale_search_hit',series_id=sid[:16],title=str(title)[:80])
            continue
        name=translated or d.get('name') or hit.get('name')
        date=str(d.get('firstAired') or hit.get('year') or '');year=int(date[:4]) if date[:4].isdigit() else None
        c={**meta,'title':name,'kind':'series','year':year,'provider':'TVDB','reference_id':sid,
           'description':(hit.get('overviews') or {}).get('deu') or d.get('overview') or meta.get('description',''),
           'show_description':(hit.get('overviews') or {}).get('deu') or d.get('overview') or '',
           'poster':d.get('image') or hit.get('image_url') or '',
           'genres':genres(g['name'] for g in (d.get('genres') or []) if g.get('name')),'genre_source':'TVDB',
           'similarity':score,'year_mismatch':False,'runtime_mismatch':False,'runtime_agrees':False,
           'episode_verified':False,'episode_title':meta.get('episode_title') or row['title'],
           'reason':'TVDB-Serientitel und deutsche Episodentitel; offizielle ausgestrahlte Reihenfolge.'}
        avg=d.get('averageRuntime')
        if isinstance(avg,(int,float)) and 1<=avg<=240:
            c['reference_runtime_seconds']=avg*60
        episodes=[];complete=False
        for page in range(20):
            result=get('series/'+sid+'/episodes/official/deu',{'page':page})
            for ep in (result.get('data') or {}).get('episodes') or []:
                season,number=ep.get('seasonNumber'),ep.get('number')
                if isinstance(season,int) and isinstance(number,int) and season>=0 and number>0:
                    episodes.append({'name':ep.get('name') or '', 'overview':ep.get('overview') or '', 'season_number':season,'episode_number':number,'runtime':ep.get('runtime')})
            if not (result.get('links') or {}).get('next'):complete=True;break
        c['episode_scan_complete']=complete
        if complete:resolve_episode({**meta,'_source_title':row['title'],'_source_duration':row.get('duration')},c,episodes)
        out.append(c)
        if len(out)>=3:break
    return out

# 0.6.58 (Björns Diagnose 20.11. nachts): Wikidata answered "Rainhard Fendrich", "Midge Ure" (people),
# "Allesfresser" and "Großkatzen" (concepts, taxa) as films with similarity 1.0. These suggestions held 5,584
# works without a kind. A candidate must be a film or a programme: an item whose classes (P31) name something
# else is no candidate; neither is any person, taxon, band, album, place or organisation, whatever its
# description says ("German film director" reads like a film).
WIKIDATA_NOT_MEDIA={'Q5','Q16521','Q55983715','Q23038290','Q215380','Q5741069','Q2088357','Q482994','Q134556',
                    'Q7366','Q105543609','Q571','Q7725634','Q4167410','Q13406463','Q43229','Q4830453','Q783794',
                    'Q515','Q486972','Q532','Q3957','Q6256','Q3624078','Q35657','Q1549591','Q15632617','Q95074',
                    'Q13442814','Q732577','Q11344','Q4936952','Q8502','Q4022','Q23397','Q39614','Q16970','Q41176'}
def _wikidata_classes(ent):
    out=[]
    for x in (ent or {}).get('claims',{}).get('P31',[]):
        if x.get('rank')=='deprecated':continue
        value=((x.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(value,dict) and value.get('id'):out.append(value['id'])
    return out
def wikidata_media(ent,candidate):
    """False for a Wikidata candidate that is plainly no film or programme (see WIKIDATA_NOT_MEDIA)."""
    classes=set(_wikidata_classes(ent))
    if classes & WIKIDATA_NOT_MEDIA:return False
    # Classes, but none of the film/series classes and no film words in the description: a concept –
    # unless the item carries what only films and programmes carry (0.6.65, Mac-Gegenprüfung 0.6.58: the
    # film „Der Baum“ and the series „100% Wolf“ are filed under classes outside the film/series list).
    if candidate.get('evidence_type')=='unknown_type' and classes and not _wikidata_media_claims(ent):return False
    return True
# Director, cast, screenwriter, producer, composer, duration, number of episodes/seasons, TMDB/fernsehserien.de IDs.
# 0.6.77: stamp of suggestions that passed wikidata_media (0.6.58/0.6.65). Unstamped "unknown_type" suggestions
# were stored before the filter and may be people, bands or concepts (Nachtdiagnose 21.11.: „Malik Harris“).
WIKIDATA_REV=2
WIKIDATA_MEDIA_PROPS=('P57','P161','P58','P162','P86','P2047','P1113','P2437','P4947','P4983','P5327','P1874','P1258')
def _wikidata_media_claims(ent):
    claims=(ent or {}).get('claims',{})
    if any(claims.get(p) for p in WIKIDATA_MEDIA_PROPS):return True
    for x in claims.get('P345',[]):           # IMDb: only a title ID (tt…), people have nm…
        value=((x.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(value,str) and value.startswith('tt'):return True
    return False

def wikidata(title,kind,year):
    ck=(title,kind,year)
    with _LOCK:cached=_WD_CACHE.get(ck)
    if cached and time.monotonic()-cached[0]<21600:return cached[1]
    try:d=core.wikidata_lookup(title,kind,year)
    except ValueError as e:
        # Very general titles ("Tiere") match so many items that the answer exceeds the size limit.
        # That is a definite "not identifiable", not a provider error that should be retried hourly.
        if 'zu groß' not in str(e):raise
        diagnostics.event('wikidata_too_many_hits',title=title,kind=kind);d=None
    if d:
        from external_metadata import fetch_json
        try:
            ent=fetch_json('https://www.wikidata.org/w/api.php',{'action':'wbgetentities','ids':d['candidate_id'],'props':'claims','format':'json'}).get('entities',{}).get(d['candidate_id'],{})
            if not wikidata_media(ent,d):
                diagnostics.event('wikidata_not_media',title=title,kind=kind,reference_id=d.get('candidate_id'),
                                  classes=_wikidata_classes(ent)[:4])
                ent={};d=None
            ids=[x.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id') for x in ent.get('claims',{}).get('P136',[]) if x.get('rank')!='deprecated']
            ids=[x for x in ids if x][:8]
            if ids:
                entries=fetch_json('https://www.wikidata.org/w/api.php',{'action':'wbgetentities','ids':'|'.join(ids),'props':'labels','languages':'de|en','format':'json'}).get('entities',{})
                d['genres']=genres((x.get('labels',{}).get('de') or x.get('labels',{}).get('en') or {}).get('value','') for x in entries.values())
        except Exception as e:
            if _rate_limited(e):raise          # 0.6.58: the caller pauses Wikidata; nothing is cached
            diagnostics.error('wikidata_genres_failed',e)
    with _LOCK:
        if len(_WD_CACHE)>=2048:_WD_CACHE.pop(next(iter(_WD_CACHE)))
        _WD_CACHE[ck]=(time.monotonic(),d)
    return d

GENERIC={'film','filme','spielfilm','serien','serie','fernsehfilm','mediathek','zdf','ard','3sat','arte','kika','kino','filme im ersten',
         'planet schule'}   # 0.6.78: portal topic, the series is in the title (catalog.portal_series)
# 0.6.49 (third Gegenprobe, 20.11.2026): 3sat/ZDF/ARD file programmes under subject rubrics; Wikidata answered
# "Reise" and "Musik" with the concepts themselves. They name no Sendung (866 works "Reise", 411 "Musik").
GENERIC|={'reise','musik','politik','tiere','natur','wintersport','doku und reportage','dokumentationen und reportagen',
          'filme dokus kabarett','dokumentation und reportage'}
# 0.6.87 (Bewertung Erkennung Air 22.11.2026): the ZDF topic „Doku“ was searched as a series and IMDb's series „Doku“
# taken for 93 works; „Sport“ and „Masterclass“ alike. Subject words name no Sendung (see catalog.TEMPLATE_GENERIC).
GENERIC|={'sport','sports','masterclass','doku','dokus','dokumentation','dokumentationen','reportage','reportagen',
          'kultur','wissen','geschichte','gesellschaft','unterhaltung','comedy','kabarett','satire','konzert','konzerte',
          'wissenschaft','technik','umwelt','klima','literatur','theater','oper','tanz','kunst','architektur',
          'kurzfilm','kurzfilme','spielfilme','fernsehfilme','dokumentarfilm','dokumentarfilme','gesundheit',
          'wirtschaft','religion','essen','kochen','garten','reisen','digital',
          'europa'}   # 0.6.92 (Zwischendiagnose Pro 0.6.91: DW „Europa“ ↔ IMDb-Serie „Europa“ tt14808162)
# 0.6.117 (Langzeitdiagnose Air 23.11.2026: Wikidata kannte „Schwimmen“ als Serie, 1.144 Werke): sports name a subject,
# never a Sendung. One list for the series search, the topic rules and catalog.TEMPLATE_GENERIC.
SPORT_WORDS={'schwimmen','wasserspringen','biathlon','skispringen','ski alpin','ski nordisch','langlauf','skilanglauf',
             'nordische kombination','rodeln','bob','skeleton','eiskunstlauf','eisschnelllauf','shorttrack','snowboard',
             'freestyle','leichtathletik','fußball','fussball','frauenfußball','handball','basketball','volleyball',
             'beachvolleyball','eishockey','hockey','radsport','rad','bahnrad','mountainbike','tennis','tischtennis',
             'badminton','turnen','gerätturnen','formel 1','formel e','motorsport','motorrad','boxen','golf','reiten',
             'pferdesport','segeln','rudern','kanu','triathlon','ringen','judo','fechten','darts','snooker','schach',
             'klettern','sportklettern','wintersport','sommersport','sportschießen','gewichtheben','rugby','american football',
             'baseball','curling','squash','surfen','e-sport','esport'}
GENERIC|=SPORT_WORDS
# arte files its programmes under a section ("Politics and society - Insights", "Kultur - Pop-Kultur").
# Such a topic names no Sendung; diagnosis 0.5.15 queried "Politics and society - Insights" 232 times.
# 0.6.49 (Diagnose 20.11.2026 abends): the French, Italian, Spanish and Polish ARTE sections
# ("Serie e fiction - Serie", "Séries et fictions - Séries", "Series y ficciones - Webseries", "Scienze - In
# pillole", "Historia - Civilizaciones") were taken for Sendungen; 0.6.43 filed hundreds of works under them.
RUBRIC=re.compile(r'(?i)^\s*(?:politics and society|culture|history|discovery|sciences?|cinema|series and fiction|news|politik und gesellschaft|kultur|geschichte|entdeckung der welt|wissenschaft|kino|fernsehfilme und serien|aktuelles und gesellschaft|info und gesellschaft'
                  r'|travel and discovery|culture and pop|news and society'
                  r'|politique et société|culture et pop|histoire|cinéma|séries et fictions|voyages et découvertes|info et société|actualités et société'
                  r'|politica e società|cultura e pop|cultura|storia|scienze|serie e fiction|viaggi e scoperte|attualità e società|informazione e società'
                  r'|política y sociedad|cultura y pop|historia|ciencias|cine|series y ficciones|viajes y descubrimientos|actualidad y sociedad|información y sociedad'
                  r'|polityka i społeczeństwo|kultura i pop|kultura|nauka|seriale i fikcja|seriale|podróże i odkrycia|aktualności i społeczeństwo|informacje i społeczeństwo)\s+-\s+\S')
# Sections that hold episodes of drama series: their works are no Einzelsendungen even without a Sendung name.
RUBRIC_SERIES=re.compile(r'(?i)^\s*(?:series and fiction|fernsehfilme und serien|séries et fictions|serie e fiction|series y ficciones|seriale i fikcja|seriale)\s+-\s+.*\b(?:serie|series|séries|seriale|webseries|serien)\b')
def generic_topic(topic):return not topic or norm(topic) in GENERIC or bool(RUBRIC.match(topic))
# 0.6.39 (Björn, 19.11.2026: still many unrecognised films and series at ARD/ZDF). Diagnosis sample of
# 1,922 failed lookups: the broadcasters' titles carry episode counters and labels no film database
# uses – "Donna Leon (12) – Das Gesetz der Lagune", "Gladbeck (2/2) - Audiodeskription",
# "Küssen verboten (5) · NEU", "Hungry - Season 1 (2/6)". They are left out of the search title only;
# the work's own title and identity stay as the broadcaster wrote them.
QUERY_NOISE=(
    re.compile(r'(?i)\s*[-–·|:]\s*(?:mit\s+)?(?:audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung)\s*$'),
    re.compile(r'(?i)^\s*neu\s*[·|:-]\s*|\s*[·|-]\s*neu\s*$'),
    re.compile(r'(?i)\s*[-–,]?\s*\b(?:season|saison|staffel|temporada|sezon|stagione)\s*\d{1,2}\b'),
    re.compile(r'\s*\(\d{1,3}(?:\s*/\s*\d{1,3})?\)'),
)
# 0.6.97 (Mac-Abfrage Runde 6, 22.11.2026: 1.012 3sat-Filme „prüfen“, fast alle ohne jeden Vorschlag): 3sat schreibt
# Gattung, Länder und Jahr in den Titel – „Der Schut - Spielfilm, BRD/Frankreich/Italien 1964“, „Danowski - Blutapfel -
# Fernsehfilm, Deutschland 2019“, „Helge Schneider - The Klimperclown - Dokumentarfilm von Helge Schneider, Deutschland
# 2025“. Gesucht wird ohne diesen Zusatz, das Jahr gilt als Erscheinungsjahr.
FILM_SUFFIX=re.compile(r'(?i)\s+[-–]\s+(?:spielfilm|fernsehfilm|dokumentarfilm|kurzfilm|animationsfilm|trickfilm|fernsehspiel|stummfilm|musikfilm|kinofilm)'
                       r'(?:\s+von\s+[^,]{2,80})?,\s*[^,]{2,80}?\s+((?:18|19|20)\d{2})\s*$')
QUERY_NOISE=(FILM_SUFFIX,)+QUERY_NOISE
# 0.6.121 (Langzeitdiagnose Air 23.11.2026, N-D): the broadcaster cuts long titles after 80 characters, so a version
# note loses its closing bracket („… Simone de Beauvoir (Originalversion“) and stayed in the search title (TMDB
# similarity 0.88, no kind). An unclosed bracket at the end that starts like a version/accessibility note goes, also
# cut inside the word („(Originalvers“, „(mit Untert“). Search title only – work identities are unchanged.
TRUNCATED_NOTE=re.compile(r'(?i)\s*[([]\s*(?:mit\s+)?(?:orig\w*|untert\w*|hörf\w*|hörfilm|audio\w*|gebärd\w*|omu\b|ov\b|vost\w*|dgs\b|ad\b)[^)\]]*$')
QUERY_NOISE=QUERY_NOISE+(TRUNCATED_NOTE,)
# 0.6.124 (Diagnose Air 0.6.120, N-D): the result cache (catalog_service, 24 h) was keyed by the stored title only, so
# requeued works got the answer of the old search („from_cache“) after a change of the search. The revision and the
# search title are part of the key now; raise SEARCH_REV whenever the queries change.
SEARCH_REV='v06132'
def film_title_parts(title):
    """0.6.124 (Diagnose Air 0.6.120, 3sat-Filme „prüfen“ ohne IMDb-Treffer): 3sat joins series/author and film
    title or original and German title – „The Pledge - Das Versprechen“, „Jussi Adler-Olsen: Erlösung“. The local
    IMDb archive only knows exact names, so each part (and the rest after each separator) is a further query."""
    text=str(title or '').strip()
    pieces=[x.strip() for x in re.split(r'\s+[-–]\s+|:\s+',text) if x.strip()]
    if len(pieces)<2:return []
    out=[]
    for i,x in enumerate(pieces):
        rest=text[text.find(x):].strip() if i else ''
        for v in (x,rest):
            if v and v!=text and len(v)>=4 and not generic_topic(v) and v not in out:out.append(v)
    # 0.6.132 (Diagnose Air 0.6.131: „Mankells Wallander – Eiskalt wie der Tod“): an author's possessive in front of
    # the series name („Mankells“, „Rosamunde Pilchers“ has two words and stays) is not part of the database title.
    m=POSSESSIVE.match(text)
    if m:
        rest=text[m.end():].strip()
        if len(rest)>=4 and rest not in out:out.insert(0,rest)
    return out[:6]
POSSESSIVE=re.compile(r'^[A-ZÄÖÜ][a-zäöüß]{2,}s\s+(?=\S+\s+[-–:]\s|\S+:\s)')
def raise_part_similarity(meta,c,parts):
    """0.6.132 (Diagnose Air 0.6.131: 3sat-Filme mit einem Kandidaten bleiben „prüfen“): a film found under the whole
    3sat title whose database title equals one part of it („Wallander – Eiskalt wie der Tod“) counts as an exact title
    – only with the title year and an agreeing running time, like film_part_candidates."""
    if c.get('kind')!='movie' or float(c.get('similarity') or 0)>=.985 or not parts:return c
    if not (meta.get('year') and str(c.get('year'))==str(meta['year']) and c.get('runtime_agrees') and not c.get('runtime_mismatch')):return c
    score,part=max((core.title_similarity(p,c.get('title') or ''),p) for p in parts)
    if score>=.985:c.update(similarity=score,title_part=part,reason=(c.get('reason') or '')+f' Titelteil „{part}“, Jahr und Laufzeit passen.')
    return c
ROMAN={'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}
FILM_NUMBER=re.compile(r'^(.{2,}?)\s*(?:[-–:]\s*)?(?:Teil\s+)?(X|IX|VIII|VII|VI|V|IV|III|II|\d{1,2})\s*$')
def film_number_variants(title):
    """0.6.128 (Diagnose Pro 0.6.127: „Der Pate II – Spielfilm, USA 1974“ ohne Kandidaten; IMDb führt „Der Pate –
    Teil II“): the numbered sequel in the other usual spellings – arabic/roman, with and without „Teil“."""
    m=FILM_NUMBER.match(str(title or '').strip())
    if not m:return []
    base,num=m.group(1).strip(' -–:'),m.group(2)
    n=ROMAN.get(num) or (int(num) if num.isdigit() else 0)
    if not 2<=n<=10 or len(base)<2:return []
    roman=[k for k,v in ROMAN.items() if v==n][0]
    out=[]
    for v in (f'{base} {n}',f'{base} {roman}',f'{base} - Teil {roman}',f'{base} - Teil {n}'):
        if norm(v)!=norm(title) and v not in out:out.append(v)
    return out
def film_suffix_year(title):
    """Year of a 3sat film title „… - Spielfilm, USA 1993“, else None."""
    m=FILM_SUFFIX.search(str(title or ''))
    return int(m.group(1)) if m else None
PART=re.compile(r'\s*\(\d{1,3}\s*/\s*\d{1,3}\)')
def query_title(title):
    """Title without language-version or accessibility suffixes such as "(Originalversion mit Untertitel)",
    episode counters "(12)", "(2/6)", season labels and "NEU" (0.6.39)."""
    import catalog
    base=catalog.cleaned(title) or str(title or '')
    text=base
    for rx in QUERY_NOISE:text=rx.sub('',text)
    text=re.sub(r'\s+([:–-])',r' \1',re.sub(r'\s+',' ',text)).strip(' -–·|:,')
    text=re.sub(r'\s+[-–]\s*$','',re.sub(r'^[-–:]\s*','',text)).strip()
    return text if len(text)>=2 else base
def part_series(title):
    """'Die Rosenheim-Cops (13/20): Leben vergeht' -> 'Die Rosenheim-Cops' (a numbered part of a series)."""
    m=PART.search(str(title or ''))
    if not m:return ''
    prefix=query_title(str(title)[:m.start()])
    return prefix if 3<=len(prefix)<=80 else ''
# 0.6.44 (Diagnose 20.11.2026 abends): one event per provider answer filled 96 % of the 32 MB protocol, so a
# diagnosis covered only three hours. Counts and hit rates per provider stay in status.json
# (provider_statistics); the protocol keeps only slow answers, which are the ones worth a look.
PROVIDER_SLOW_SECONDS=1.0
def provider_complete(start,**fields):
    seconds=round(time.monotonic()-start,2)
    if seconds>=PROVIDER_SLOW_SECONDS:diagnostics.event('provider_complete',seconds=seconds,**fields)

def film_part_candidates(row,meta,year):
    """0.6.124: IMDb films named by one part of a 3sat title. Same year as the title suffix (or one apart); a part
    is no exact title, so the hit is only verified with an agreeing running time, else it stays a suggestion."""
    import imdb_archive
    found={}
    for part in film_title_parts(meta['title'])+film_number_variants(meta['title']):
        for h in imdb_archive.ACTIVE.candidates(row,{**meta,'kind':'movie','title':part}):
            if not h.get('year') or abs(int(h['year'])-int(year))>1:continue
            h=dict(h,reason=f'Titelteil „{part}“ im lokalen IMDb-Archiv, Jahr aus dem Titelzusatz',title_part=part)
            if not (h.get('runtime_agrees') and int(h['year'])==int(year)):h.update(similarity=.9,confidence='possible')
            found.setdefault(h['reference_id'],h)
    return list(found.values())
def candidates(row,meta,settings):
    meta={k:v for k,v in meta.items() if k not in ('suggestions','metadata_warnings','deferred_providers')};kind=meta['kind'];topic=row.get('topic','');queries=[]
    suffix_year=film_suffix_year(meta['title']) or film_suffix_year(row.get('title'))
    meta['title']=query_title(meta['title'])
    if suffix_year and kind in ('movie','unknown') and not meta.get('year'):meta['year']=suffix_year
    if kind=='series':queries=[('series',meta['title'])]
    elif kind=='movie':queries=[('movie',meta['title'])]
    else:
        part=part_series(row.get('title'))
        if not generic_topic(topic) and norm(topic)!=norm(row['title']):queries.append(('series',topic))
        elif part and not generic_topic(part):queries.append(('series',part))
        elif ' - ' in meta['title']:
            # "Mapping the World - Cyprus: A Divided Island": without a usable topic the series is the prefix.
            prefix=meta['title'].split(' - ',1)[0].strip()
            if 3<=len(prefix)<=60 and not generic_topic(prefix):queries.append(('series',prefix))
        queries.append(('movie',meta['title']))
    out=[];warnings=[];deferred=[];checks=[]
    def checked(value):
        checks.append(value)
        if not settings.get('_external_reference_validation',False):
            provider_stats.observe(value['provider'],value['status'],value['count'])
    import broadcaster,video_causality
    def from_broadcaster():
        ref=broadcaster.reference(row)
        # Undocumented web endpoints are never polled in the background by
        # default. The existing import remains usable without direct access.
        if not ref or not settings.get('sender_direct_lookup',False):return None
        start=time.monotonic()
        try:
            c=broadcaster.candidate(row,meta,broadcaster.lookup_limited(row))
            if c:
                video_causality.annotate(row,c)
                c['plausibility_issues']=matching.issues(meta,c);out.append(c)
            checked({'provider':ref[0],'status':'checked','count':int(bool(c))})
            provider_complete(start,provider=ref[0],title=row.get('title',''),candidates=int(bool(c)))
        except broadcaster.Unavailable:
            if ref[0] not in deferred:deferred.append(ref[0])
            checked({'provider':ref[0],'status':'paused','count':0})
        except Exception as e:
            checked({'provider':ref[0],'status':'error','count':0});warnings.append(ref[0]+': '+core.safe_error(e));diagnostics.error('provider_failed',e,provider=ref[0],title=row.get('title',''))
        return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
    import imdb_archive,matching
    # OMDb serves IMDb data. Once the offline IMDb snapshot answered, an exhausted OMDb quota is no
    # reason to keep the work in the retry queue (diagnosis 0.5.15: 82 % of open works were retried
    # only because of the OMDb pause and queried TMDB, TVDB and Wikidata again every few hours).
    def imdb_checked():return any(x['provider']=='IMDb Offline' and x['status']=='checked' for x in checks)
    # A work already identified as a broadcaster's own Sendereihe is unknown to the film databases;
    # asking them again for every episode only cost requests and quota.
    sender_first=bool(settings.get('sender_direct_lookup',False) and kind!='movie' and broadcaster.reference(row))
    if sender_first:
        direct=from_broadcaster()
        if direct and direct['candidates']:return direct
    if imdb_archive.ACTIVE and imdb_archive.ACTIVE.updated:
        try:
            local=imdb_archive.ACTIVE.candidates(row,meta)
            if suffix_year and kind in ('movie','unknown') and not any(x.get('kind')=='movie' for x in local):
                local.extend(film_part_candidates(row,meta,suffix_year))
            if meta.get('kind') not in ('movie','series') and row.get('topic') and row['topic']!=meta.get('title'):
                local.extend(imdb_archive.ACTIVE.candidates(row,{**meta,'kind':'series','title':row['topic']}))
            out.extend(local)
            for c in local:
                video_causality.annotate(row,c)
                c['plausibility_issues']=matching.issues(meta,c)
            checked({'provider':'IMDb Offline','status':'checked','count':len(local)})
            if matching.sufficient(meta,out):
                return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
        except Exception as e:
            checked({'provider':'IMDb Offline','status':'error','count':0});warnings.append('IMDb Offline: '+core.safe_error(e))
    for provider,field,fn in [('TVDB','tvdb',tvdb_candidates),('TMDB','tmdb',tmdb_candidates),('OMDb','omdb',omdb_candidates)]:
        if not settings.get(field):
            checked({'provider':provider,'status':'not_configured','count':0});continue
        for k,title in queries:
            if field=='tvdb' and k!='series':continue
            if field=='omdb' and omdb_status(settings[field])['paused']:
                if 'OMDb' not in deferred and not imdb_checked():deferred.append('OMDb')
                checked({'provider':provider,'status':'paused','count':0});break
            if provider_pause(provider) and not settings.get('_force_provider_refresh',False):
                if provider not in deferred:deferred.append(provider)
                checked({'provider':provider,'status':'paused','count':0})
                break
            # Reuse a confirmed no-result for the same provider query. Errors,
            # expired tokens and rate limits are never negative evidence.
            credential=settings.get(field,'')
            if field=='tvdb':credential=str(credential)+':'+str(settings.get('tvdb_pin',''))
            year=meta.get('year') if k=='movie' else None
            if negative_cache.contains(provider,k,title,year,credential,
                                      force=settings.get('_force_provider_refresh',False)):
                checked({'provider':provider,'status':'negative_cache','count':0})
                continue
            # One event per finished check; a separate start event doubled the log and shortened its history.
            start=time.monotonic()
            try:
                hits=fn(row,meta,(settings[field],settings.get('tvdb_pin','')) if field=='tvdb' else settings[field],k,title);out.extend(hits)
                for c in hits:
                    video_causality.annotate(row,c)
                    if suffix_year:raise_part_similarity(meta,c,film_title_parts(meta['title']))
                    c['plausibility_issues']=matching.issues(meta,c)
                provider_success(provider)
                if not hits:negative_cache.remember(provider,k,title,year,credential)
                checked({'provider':provider,'status':'checked','count':len(hits)})
                provider_complete(start,provider=provider,title=title,kind=k,candidates=len(hits))
            except Exception as e:
                if provider=='TVDB':
                    import tvdb
                    if isinstance(e,tvdb.TVDBError) and e.paused:
                        # A credential-scoped circuit is already open. Retain
                        # other providers' evidence and schedule a later retry
                        # rather than writing thousands of identical tracebacks.
                        if provider not in deferred:deferred.append(provider)
                        checked({'provider':provider,'status':'paused','count':0})
                        break
                if provider=='OMDb' and isinstance(e,OMDbError) and omdb_status(settings[field])['paused']:
                    if provider not in deferred and not imdb_checked():deferred.append(provider)
                    checked({'provider':provider,'status':'paused','count':0});break
                if _rate_limited(e):
                    # 0.6.58: "too many requests" is no failed check: pause, keep the work for later.
                    provider_failure(provider,e)
                    if provider not in deferred:deferred.append(provider)
                    checked({'provider':provider,'status':'paused','count':0})
                    break
                provider_failure(provider,e)
                checked({'provider':provider,'status':'error','count':0})
                warnings.append(provider+': '+core.safe_error(e));diagnostics.error('provider_failed',e,provider=provider,title=title)
        if matching.sufficient(meta,out):
            return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
    # Own productions: the offer's own Mediathek page, then the free Wikidata fallback.
    if not out and not sender_first:from_broadcaster()
    # Free fallback: retain the original cautious Wikidata matching and its evidence.
    if not out:
        for k,title in queries:
            if provider_pause('Wikidata') and not settings.get('_force_provider_refresh',False):
                if 'Wikidata' not in deferred:deferred.append('Wikidata')
                checked({'provider':'Wikidata','status':'paused','count':0})
                break
            year=meta.get('year') if k=='movie' else None
            if negative_cache.contains('Wikidata',k,title,year,
                                      force=settings.get('_force_provider_refresh',False)):
                checked({'provider':'Wikidata','status':'negative_cache','count':0})
                continue
            start=time.monotonic()
            try:
                d=wikidata(title,k,year)
                provider_success('Wikidata')
                if not d:negative_cache.remember('Wikidata',k,title,year)
                if d:out.append({**meta,'title':d['candidate_title'],'kind':k,'year':d['candidate_year'],'provider':'Wikidata','reference_id':d['candidate_id'],'reason':d['reason'],'similarity':d['similarity'],'evidence_type':d.get('evidence_type'),'wikidata_rev':WIKIDATA_REV,'confidence':d.get('confidence'),'genres':d.get('genres') or meta.get('genres',[]),'genre_source':'Wikidata' if d.get('genres') else meta.get('genre_source','Unbekannt'),'episode_title':row['title'] if k=='series' else ''})
                checked({'provider':'Wikidata','status':'checked','count':int(bool(d))})
                provider_complete(start,provider='Wikidata',title=title,kind=k,candidates=int(bool(d)))
            except Exception as e:
                if _rate_limited(e):
                    provider_failure('Wikidata',e)
                    if 'Wikidata' not in deferred:deferred.append('Wikidata')
                    checked({'provider':'Wikidata','status':'paused','count':0})
                    break
                provider_failure('Wikidata',e)
                checked({'provider':'Wikidata','status':'error','count':0})
                warnings.append('Wikidata: '+core.safe_error(e))
                diagnostics.error('provider_failed',e,provider='Wikidata',title=title)
    return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
