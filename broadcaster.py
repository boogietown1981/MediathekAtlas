"""Programme data from the ARD and ZDF Mediatheken for the broadcasters' own productions.

The film list links every offer to its Mediathek page. The JSON behind that page names the show
(Sendereihe), episode numbers, synopsis and images, which TMDB, TVDB and IMDb usually lack for
magazines, news and documentaries. Endpoints follow the public web/app clients (reference: yt-dlp
ard.py/zdf.py, MediathekView MServer); they are undocumented and may change, so every field is optional.
"""
import json,re,threading,time,urllib.parse
import core,diagnostics
PROVIDERS=('ARD Mediathek','ZDF Mediathek')
IMAGE_HOSTS={'api.ardmediathek.de','img.ardmediathek.de','www.zdf.de','epg-image.zdf.de','www.zdfheute.de'}
ARD_ITEM='https://api.ardmediathek.de/page-gateway/pages/ard/item/'
ZDF_TOKEN='https://zdf-prod-futura.zdf.de/mediathekV2/token'
ZDF_GRAPHQL='https://api.zdf.de/graphql'
ZDF_QUERY='''query VideoByCanonical($canonical: String!) {
  videoByCanonical(canonical: $canonical) {
    canonical title leadParagraph editorialDate
    teaser { description image { list } }
    episodeInfo { episodeNumber seasonNumber }
    smartCollection { canonical title }
    currentMedia { nodes { ... on VodMedia { duration } } }
  }
}'''
# Containers of unrelated films are no Sendereihe ("Filme im MDR", "Spielfilme", "Dokus").
CONTAINER=re.compile(r'(?i)^(?:(?:spiel)?filme?|dokus?|dokumentation(?:en)?|serien?|reportagen?|kino|mediathek)\b|\bfilme im\b|\bfilm-?highlights?\b')
GENRE_HINTS=[(re.compile(r'(?i)\b(?:tagesschau|tagesthemen|nachrichten|aktuell|heute(?:[- ]journal)?|journal|wetter)\b'),'Nachrichten'),
             (re.compile(r'(?i)\b(?:doku\w*|dokumentation\w*|reportage\w*|terra x|planet e)\b'),'Dokumentation'),
             (re.compile(r'(?i)\b(?:magazin\w*|servicezeit|ratgeber|verbraucher\w*|markt)\b'),'Magazin'),
             (re.compile(r'(?i)\b(?:talk\w*|gespräch\w*|interview\w*|stöckl|lanz|maischberger|illner)\b'),'Talk'),
             (re.compile(r'(?i)\b(?:kinder\w*|kika|logo!|sendung mit der maus)\b'),'Kinder & Familie'),
             (re.compile(r'(?i)\b(?:kultur\w*|literatur\w*|philosophie|scobel|musik\w*|konzert\w*)\b'),'Kultur')]
_CACHE={};_LOCK=threading.Lock();_REQUEST_LOCK=threading.Lock();_PAUSED={};_TOKEN={};_LAST=[0.0]
CACHE_SECONDS=86400;PAUSE_SECONDS=900;MIN_INTERVAL=.5

class Unavailable(RuntimeError):
    """Mediathek temporarily unreachable; the work is retried later instead of being marked unknown."""

def reference(row):
    """Return (provider, id) for an offer whose website is an ARD or ZDF Mediathek video page."""
    url=str(row.get('url_website') or '')
    try:p=urllib.parse.urlsplit(url)
    except ValueError:return None
    host=(p.hostname or '').lower();path=[x for x in p.path.split('/') if x]
    if p.scheme!='https' or not path:return None
    if host in ('www.ardmediathek.de','ardmediathek.de') and ('video' in path or 'player' in path):
        ident=path[-1]
        return ('ARD Mediathek',ident) if re.fullmatch(r'[A-Za-z0-9]{8,200}',ident) else None
    if host in ('www.zdf.de','zdf.de'):
        ident=path[-1][:-5] if path[-1].endswith('.html') else path[-1]
        if path[0] in ('video','play') or path[-1].endswith('.html'):
            return ('ZDF Mediathek',ident) if re.fullmatch(r'[a-z0-9][a-z0-9-]{2,200}',ident) else None
    return None

def status(provider):
    with _LOCK:until=_PAUSED.get(provider,0)
    return {'paused':until>time.time(),'retry_at':until if until>time.time() else None}

def _request(provider,url,data=None,headers=None):
    if status(provider)['paused']:raise Unavailable(provider+' pausiert')
    with _REQUEST_LOCK:
        # Be a polite client of a public service: at most two requests per second in total.
        wait=_LAST[0]+MIN_INTERVAL-time.monotonic()
        if wait>0:time.sleep(wait)
        _LAST[0]=time.monotonic()
        try:
            with core.open_url(url,data,{'Accept':'application/json',**(headers or {})}) as r:raw=r.read(4*1024*1024+1)
        except core.urllib.error.HTTPError as e:
            e.close()
            if e.code==404:return None
            if e.code in (401,403,429) or e.code>=500:_pause(provider,'HTTP '+str(e.code))
            raise Unavailable(provider+': HTTP '+str(e.code)) from None
        except (core.urllib.error.URLError,TimeoutError,OSError):
            _pause(provider,'network');raise Unavailable(provider+': Netzwerkfehler') from None
    if len(raw)>4*1024*1024:raise ValueError(provider+': Antwort zu groß')
    try:return json.loads(raw)
    except (ValueError,UnicodeDecodeError):raise ValueError(provider+': keine gültige Antwort') from None

def _pause(provider,reason):
    with _LOCK:_PAUSED[provider]=time.time()+PAUSE_SECONDS
    diagnostics.event('provider_access_error','WARNING',provider=provider,reason=reason)

def _text(value):
    return core.clean(value) if isinstance(value,str) else ''

def _image(url):
    url=str(url or '').replace('{width}','1280')
    p=urllib.parse.urlsplit(url)
    return url if p.scheme=='https' and p.hostname in IMAGE_HOSTS and not p.username and p.port in (None,443) else ''

def _episode_numbers(title):
    m=re.search(r'\(S(\d+)/E(\d+)\)',title)
    if m:return int(m[1]),int(m[2])
    m=re.search(r'\((?:Folge |Teil )?(\d+)(?:/\d+)?\)|\bFolge (\d+)(?:/\d+)?(?::| -|) ',title)
    return (None,int(m[1] or m[2])) if m else (None,None)

def parse_ard(page):
    """Normalise an ARD page-gateway item (embedded=false, mcV6=true)."""
    widgets=page.get('widgets') if isinstance(page,dict) else None
    player=next((w for w in widgets or [] if isinstance(w,dict) and w.get('type') in ('player_ondemand','player_live')),None)
    if not player:return None
    media=((player.get('mediaCollection') or {}).get('embedded') or {});meta=media.get('meta') or {}
    show=player.get('show') if isinstance(player.get('show'),dict) else {}
    title=_text(meta.get('title') or player.get('title') or page.get('title'))
    series=_text(meta.get('seriesTitle') or show.get('title'))
    season,episode=_episode_numbers(_text(page.get('title') or title))
    images=meta.get('images') if isinstance(meta.get('images'),list) else []
    show_image=(show.get('image') or {}).get('src') if isinstance(show.get('image'),dict) else ''
    duration=meta.get('durationSeconds')
    return {'provider':'ARD Mediathek','title':title,'series':series,'series_id':_text(show.get('id')),
            'description':_text(meta.get('synopsis') or player.get('synopsis')),'season':season,'episode':episode,
            'image':_image(images[0].get('url') if images and isinstance(images[0],dict) else ''),'series_image':_image(show_image),
            'duration':duration if isinstance(duration,int) and duration>0 else None,'channel':_text(meta.get('clipSourceName')),
            'broadcast':_text(meta.get('broadcastedOnDateTime') or player.get('broadcastedOn'))}

def parse_zdf(data):
    """Normalise a ZDF GraphQL videoByCanonical node."""
    video=((data or {}).get('data') or {}).get('videoByCanonical') if isinstance(data,dict) else None
    if not isinstance(video,dict):return None
    images=((video.get('teaser') or {}).get('image') or {}).get('list') or {}
    def width(item):
        m=re.match(r'(\d+)x',str(item[0]));return 10**6 if item[0]=='original' else int(m[1]) if m else 0
    image=next((_image(u) for _,u in sorted(images.items(),key=width,reverse=True) if _image(u)),'') if isinstance(images,dict) else ''
    info=video.get('episodeInfo') or {};collection=video.get('smartCollection') or {}
    nodes=(video.get('currentMedia') or {}).get('nodes') or [];duration=next((n.get('duration') for n in nodes if isinstance(n,dict) and isinstance(n.get('duration'),int)),None)
    def number(v):return v if isinstance(v,int) and v>=0 else None
    return {'provider':'ZDF Mediathek','title':_text(video.get('title')),'series':_text(collection.get('title')),'series_id':_text(collection.get('canonical')),
            'description':_text(video.get('leadParagraph') or (video.get('teaser') or {}).get('description')),
            'season':number(info.get('seasonNumber')),'episode':number(info.get('episodeNumber')) or None,'image':image,'series_image':'',
            'duration':duration if duration and duration>0 else None,'channel':'ZDF','broadcast':_text(video.get('editorialDate'))}

def _zdf_token():
    with _LOCK:token=dict(_TOKEN)
    if not token or token.get('expires',0)<time.time()+60:
        data=_request('ZDF Mediathek',ZDF_TOKEN) or {}
        if not isinstance(data.get('token'),str):raise Unavailable('ZDF Mediathek: kein API-Token')
        expires=data.get('expires') if isinstance(data.get('expires'),(int,float)) else time.time()+3600
        token={'value':str(data.get('type') or 'Bearer')+' '+data['token'],'expires':expires}
        diagnostics.register_secrets(data['token'])
        with _LOCK:_TOKEN.clear();_TOKEN.update(token)
    return token['value']

def lookup(row):
    """Programme data for one offer, or None when its page is not an ARD/ZDF video or unknown there."""
    ref=reference(row)
    if not ref:return None
    with _LOCK:cached=_CACHE.get(ref)
    if cached and time.time()-cached[0]<CACHE_SECONDS:return cached[1]
    provider,ident=ref
    if provider=='ARD Mediathek':
        result=parse_ard(_request(provider,ARD_ITEM+urllib.parse.quote(ident)+'?embedded=false&mcV6=true') or {})
    else:
        body=json.dumps({'operationName':'VideoByCanonical','query':ZDF_QUERY,'variables':{'canonical':ident}}).encode()
        result=parse_zdf(_request(provider,ZDF_GRAPHQL,body,{'Api-Auth':_zdf_token(),'Apollo-Require-Preflight':'true','Content-Type':'application/json'}))
    if result:result['reference_id']=ident
    with _LOCK:
        if len(_CACHE)>=4096:_CACHE.pop(next(iter(_CACHE)))
        _CACHE[ref]=(time.time(),result)
    return result

def genres(*texts):
    text=' '.join(t for t in texts if t)
    return [genre for pattern,genre in GENRE_HINTS if pattern.search(text)][:2]

def candidate(row,meta,info):
    """Turn programme data into a conservative catalogue candidate.

    The data describes exactly this offer, so a matching Sendereihe identifies the work with high
    confidence. Broadcast dates are never used as release years.
    """
    if not info:return None
    series=info.get('series') or ''
    topic=row.get('topic') or ''
    own_series=bool(series and not CONTAINER.search(series) and core.title_similarity(series,topic or series)>=.985 and core.title_similarity(series,info.get('title') or '')<.985)
    hints=genres(series,topic,info.get('description','')[:300])
    base={**meta,'provider':info['provider'],'description':info.get('description') or meta.get('description',''),'genres':hints,'genre_source':'Sender (abgeleitet)' if hints else meta.get('genre_source','Unbekannt'),
          'poster':info.get('series_image') or info.get('image') or meta.get('poster',''),'year_mismatch':False,'evidence_type':'broadcaster_page','confidence':'high',
          'broadcast':info.get('broadcast',''),'channel_source':info.get('channel','')}
    duration=info.get('duration');own=row.get('duration')
    runtime_agrees=bool(duration and own and abs(duration-own)<=max(120,own*.05))
    if own_series:
        title=series if core.title_similarity(series,meta.get('title') or '')<.985 else meta.get('title') or series
        c={**base,'title':title,'kind':'series','year':None,'reference_id':info.get('series_id') or 'reihe:'+core.hashlib.sha256(series.casefold().encode()).hexdigest()[:16],
           'episode_title':info.get('title') or meta.get('episode_title') or row.get('title',''),'similarity':max(core.title_similarity(meta.get('title') or '',series),core.title_similarity(topic,series)),
           'season':info.get('season') if info.get('season') is not None else meta.get('season'),'episode':info.get('episode') if info.get('episode') is not None else meta.get('episode'),
           'runtime_agrees':runtime_agrees,'runtime_mismatch':bool(duration and own and not runtime_agrees),'episode_scan_complete':True,
           'reason':'Sendereihe laut '+info['provider']+'; Angaben zu genau diesem Angebot.'}
        # The page is this very episode: its own numbering counts as verified episode evidence.
        c['episode_verified']=bool(runtime_agrees and isinstance(c['season'],int) and isinstance(c['episode'],int) and c['episode']>0)
        return c
    # Only enrich offers already classified as films; a single news or magazine clip is no film.
    if meta.get('kind')!='movie':return None
    return {**base,'title':info.get('title') or meta.get('title'),'kind':'movie','year':None,'reference_id':info.get('reference_id'),
            'similarity':core.title_similarity(meta.get('title') or '',info.get('title') or ''),'runtime_agrees':runtime_agrees,
            'runtime_mismatch':bool(duration and own and not runtime_agrees),'episode_verified':False,'episode_title':'',
            'reason':'Einzelsendung laut '+info['provider']+'; Angaben zu genau diesem Angebot.'}
