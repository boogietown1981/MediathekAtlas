"""Provider metadata and evidence-based episode reconciliation."""
import re,time,threading,hashlib,json
import core,diagnostics,provider_stats
_CACHE={};_WD_CACHE={};_LOCK=threading.Lock()
GENRES={'Comedy':'Komödie','Crime':'Krimi','Documentary':'Dokumentation','Dokumentarfilm':'Dokumentation','Family':'Kinder & Familie','Familienserie':'Kinder & Familie','Familienfilm':'Kinder & Familie','Kids':'Kinder & Familie','Kinder':'Kinder & Familie','Zeichentrickserie':'Animation','animated television series':'Animation','Familie':'Kinder & Familie','Children':'Kinder & Familie','Romance':'Romantik','Liebesfilm':'Romantik','Sci-Fi':'Science-Fiction','Science Fiction':'Science-Fiction','Animation':'Animation','Adventure':'Abenteuer','Action':'Action','History':'Historie','War':'Kriegsfilm','TV Movie':'TV-Film','Music':'Musik','Mystery':'Mystery','Horror':'Horror','Fantasy':'Fantasy','Drama':'Drama','Thriller':'Thriller'}
def genres(values):return sorted(set(GENRES.get(str(g).strip(),str(g).strip()) for g in values if str(g).strip() not in ('','N/A')))
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
        diagnostics.event('provider_access_error',provider='OMDb',reason=e.reason,http_status=e.status)
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
    unique={(e.get('season_number'),e.get('episode_number')):e for e in matches}
    if len(unique)==1:
        ep=next(iter(unique.values()));candidate.update(season=ep['season_number'],episode=ep['episode_number'],episode_title=ep['name'],episode_verified=True,description=ep.get('overview') or candidate['description'])
        runtime=ep.get('runtime');duration=meta.get('_source_duration')
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
            c['episode_title']=meta.get('episode_title') or row['title'];epmeta={**meta,'_source_title':row['title'],'_source_duration':row.get('duration')};episodes=[]
            seasons=d.get('seasons',[])
            if meta.get('season') is not None:seasons=[{'season_number':meta['season']}]
            # Bounded provider requests; unsupported very long series remain reviewable.
            c['episode_scan_complete']=len(seasons)<=24
            for season in seasons[:24]:
                number=season.get('season_number')
                if number is None:continue
                episodes.extend(core.tmdb(f"tv/{d['id']}/season/{number}",key).get('episodes',[]))
            resolve_episode(epmeta,c,episodes)
            if not c['episode_scan_complete'] and meta.get('season') is None:c['episode_verified']=False
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
        sid=str(hit['tvdb_id']);d=get('series/'+sid+'/extended').get('data') or {}
        name=translated or d.get('name') or hit.get('name')
        date=str(d.get('firstAired') or hit.get('year') or '');year=int(date[:4]) if date[:4].isdigit() else None
        c={**meta,'title':name,'kind':'series','year':year,'provider':'TVDB','reference_id':sid,
           'description':(hit.get('overviews') or {}).get('deu') or d.get('overview') or meta.get('description',''),
           'poster':d.get('image') or hit.get('image_url') or '',
           'genres':genres(g['name'] for g in (d.get('genres') or []) if g.get('name')),'genre_source':'TVDB',
           'similarity':score,'year_mismatch':False,'runtime_mismatch':False,'runtime_agrees':False,
           'episode_verified':False,'episode_title':meta.get('episode_title') or row['title'],
           'reason':'TVDB-Serientitel und deutsche Episodentitel; offizielle ausgestrahlte Reihenfolge.'}
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

def wikidata(title,kind,year):
    ck=(title,kind,year)
    with _LOCK:cached=_WD_CACHE.get(ck)
    if cached and time.monotonic()-cached[0]<21600:return cached[1]
    d=core.wikidata_lookup(title,kind,year)
    if d:
        from external_metadata import fetch_json
        try:
            ent=fetch_json('https://www.wikidata.org/w/api.php',{'action':'wbgetentities','ids':d['candidate_id'],'props':'claims','format':'json'}).get('entities',{}).get(d['candidate_id'],{})
            ids=[x.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id') for x in ent.get('claims',{}).get('P136',[]) if x.get('rank')!='deprecated']
            ids=[x for x in ids if x][:8]
            if ids:
                entries=fetch_json('https://www.wikidata.org/w/api.php',{'action':'wbgetentities','ids':'|'.join(ids),'props':'labels','languages':'de|en','format':'json'}).get('entities',{})
                d['genres']=genres((x.get('labels',{}).get('de') or x.get('labels',{}).get('en') or {}).get('value','') for x in entries.values())
        except Exception as e:diagnostics.error('wikidata_genres_failed',e)
    with _LOCK:
        if len(_WD_CACHE)>=2048:_WD_CACHE.pop(next(iter(_WD_CACHE)))
        _WD_CACHE[ck]=(time.monotonic(),d)
    return d

GENERIC={'film','filme','spielfilm','serien','serie','fernsehfilm','mediathek','zdf','ard','3sat','arte','kika','kino','filme im ersten'}
def candidates(row,meta,settings):
    meta={k:v for k,v in meta.items() if k not in ('suggestions','metadata_warnings')};kind=meta['kind'];topic=row.get('topic','');queries=[]
    if kind=='series':queries=[('series',meta['title'])]
    elif kind=='movie':queries=[('movie',meta['title'])]
    else:
        if topic and norm(topic) not in GENERIC and norm(topic)!=norm(row['title']):queries.append(('series',topic))
        queries.append(('movie',meta['title']))
    out=[];warnings=[];deferred=[];checks=[]
    def checked(value):
        checks.append(value);provider_stats.observe(value['provider'],value['status'],value['count'])
    import imdb_archive,matching
    if imdb_archive.ACTIVE and imdb_archive.ACTIVE.updated:
        try:
            local=imdb_archive.ACTIVE.candidates(row,meta)
            if meta.get('kind') not in ('movie','series') and row.get('topic') and row['topic']!=meta.get('title'):
                local.extend(imdb_archive.ACTIVE.candidates(row,{**meta,'kind':'series','title':row['topic']}))
            out.extend(local)
            for c in local:c['plausibility_issues']=matching.issues(meta,c)
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
                if 'OMDb' not in deferred:deferred.append('OMDb')
                checked({'provider':provider,'status':'paused','count':0});break
            start=time.monotonic();diagnostics.event('provider_start',provider=provider,title=title,kind=k)
            try:
                hits=fn(row,meta,(settings[field],settings.get('tvdb_pin','')) if field=='tvdb' else settings[field],k,title);out.extend(hits)
                for c in hits:c['plausibility_issues']=matching.issues(meta,c)
                checked({'provider':provider,'status':'checked','count':len(hits)})
                diagnostics.event('provider_complete',provider=provider,title=title,candidates=len(hits),seconds=round(time.monotonic()-start,2))
            except Exception as e:
                if provider=='OMDb' and isinstance(e,OMDbError) and omdb_status(settings[field])['paused']:
                    if provider not in deferred:deferred.append(provider)
                    checked({'provider':provider,'status':'paused','count':0});break
                checked({'provider':provider,'status':'error','count':0})
                warnings.append(provider+': '+core.safe_error(e));diagnostics.error('provider_failed',e,provider=provider,title=title)
        if matching.sufficient(meta,out):
            return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
    # Free fallback: retain the original cautious Wikidata matching and its evidence.
    if not out:
        for k,title in queries:
            diagnostics.event('provider_start',provider='Wikidata',title=title,kind=k)
            try:
                d=wikidata(title,k,meta.get('year') if k=='movie' else None)
                if d:out.append({**meta,'title':d['candidate_title'],'kind':k,'year':d['candidate_year'],'provider':'Wikidata','reference_id':d['candidate_id'],'reason':d['reason'],'similarity':d['similarity'],'evidence_type':d.get('evidence_type'),'confidence':d.get('confidence'),'genres':d.get('genres') or meta.get('genres',[]),'genre_source':'Wikidata' if d.get('genres') else meta.get('genre_source','Unbekannt'),'episode_title':row['title'] if k=='series' else ''})
                checked({'provider':'Wikidata','status':'checked','count':int(bool(d))})
                diagnostics.event('provider_complete',provider='Wikidata',title=title,candidates=int(bool(d)))
            except Exception as e:checked({'provider':'Wikidata','status':'error','count':0});warnings.append('Wikidata: '+core.safe_error(e));diagnostics.error('provider_failed',e,provider='Wikidata',title=title)
    return {'candidates':out,'warnings':warnings,'deferred_providers':deferred,'provider_checks':checks}
