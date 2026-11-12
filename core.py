"""MediathekAtlas: ArchiveMedia identity/export core with a separate MVW adapter."""
import sys, json, re, hashlib, time, urllib.request, urllib.parse, urllib.error, socket, ipaddress
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'vendor'/'archivemedia'))
from catalog_identity import clean, normalize_title, EPISODE
from external_metadata import title_similarity, omdb_lookup, wikidata_lookup
from package_media import canonical_target, render_nfo, write_atomic, save_poster
from media_probe import parse_streams, resolve_ffprobe

from version import VERSION
UA='MediathekAtlas/'+VERSION

def public_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Keine öffentliche HTTP(S)-Medienadresse')
    # Fixed public metadata endpoints also work behind DNS-resolving HTTPS proxies.
    if p.scheme=='https' and p.hostname in {'liste.mediathekview.de','mediathekviewweb.de','api.themoviedb.org','www.wikidata.org','www.omdbapi.com','datasets.imdbws.com'}:return url
    for x in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(x[4][0]).is_global:raise ValueError('Lokale Netzwerkadressen sind nicht zulässig')
    return url

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def open_url(url,data=None,headers=None,timeout=35):
    public_url(url)
    req=urllib.request.Request(url,data=data,headers={'User-Agent':UA,**(headers or {})})
    return urllib.request.build_opener(Redirect()).open(req,timeout=timeout)

def fetch(url,data=None,headers=None):
    for attempt in range(3):
        try:
            with open_url(url,data,headers) as r: raw=r.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise ValueError('Antwort zu groß')
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or attempt==2:raise ValueError(f'Dienst antwortet mit HTTP {e.code}') from None
            delay=e.headers.get('Retry-After','')
            time.sleep(min(int(delay),20) if delay.isdigit() else 2**attempt)

def search(query,channel='',offset=0):
    clauses=[{'fields':['title','topic'],'query':str(query)[:200]}] if query.strip() else []
    if channel:clauses.append({'fields':['channel'],'query':channel[:60]})
    payload={'queries':clauses,'sortBy':'timestamp','sortOrder':'desc','future':False,'offset':max(0,int(offset)),'size':30}
    result=fetch('https://mediathekviewweb.de/api/query',json.dumps(payload).encode(),{'Content-Type':'text/plain'})
    if result.get('err'):raise ValueError('MediathekViewWeb: '+str(result['err'])[:200])
    return result['result']

def identify(row):
    title=normalize_title(row.get('title')); topic=normalize_title(row.get('topic'))
    desc=clean(row.get('description'))
    # Do not use a broadcast timestamp as a release year; only explicit production clues.
    y=re.search(r'(?i)(?:Deutschland|Österreich|Schweiz|Frankreich|USA|Großbritannien|Produktionsjahr)\s*[:,]?\s*((?:19|20)\d{2})\b',desc[:300])
    e=EPISODE.search(title)
    season=int(e.group('s') or e.group('s2')) if e and (e.group('s') or e.group('s2')) else None
    episode=int(e.group('e') or e.group('e2') or e.group('e3')) if e else None
    kind='series' if e or re.search(r'(?i)\b(?:Fernsehserie|Krimiserie|Zeichentrickserie|Animationsserie|Serie|Staffel)\b',desc[:250]) else 'movie' if re.search(r'(?i)\b(?:Spielfilm|Fernsehfilm|Filmkomödie|Dokumentarfilm)\b',desc[:200]) else 'unknown'
    return {'title':topic if kind=='series' and topic else title,'episode_title':title if kind=='series' else '',
            'kind':kind,'year':int(y.group(1)) if y and kind=='movie' else None,'season':season,'episode':episode,
            'description':desc,'state':'review','provider':'MediathekViewWeb','poster':'','reference_id':None,
            'reason':'Senderangaben; Identität vor Download prüfen. Sendetermin ist kein Erscheinungsjahr.'}

_TMDB_CACHE={}
def tmdb(path,key,params=None):
    params={'language':'de-DE',**(params or {})};headers={}
    if re.fullmatch(r'[a-fA-F0-9]{32}',key):params['api_key']=key
    else:headers['Authorization']='Bearer '+key
    cachekey=hashlib.sha256(json.dumps([path,params,headers],sort_keys=True).encode()).hexdigest()
    cached=_TMDB_CACHE.get(cachekey)
    if cached and time.monotonic()-cached[0]<21600:return cached[1]
    data=fetch('https://api.themoviedb.org/3/'+path+'?'+urllib.parse.urlencode(params),headers=headers)
    if len(_TMDB_CACHE)>=512:_TMDB_CACHE.pop(next(iter(_TMDB_CACHE)),None)
    _TMDB_CACHE[cachekey]=(time.monotonic(),data)
    return data

def candidates(row,meta,settings):
    from metadata import candidates as lookup
    return lookup(row,meta,settings)

def safe_error(e):
    # Provider exception URLs may contain keys. Never forward them.
    if isinstance(e,urllib.error.HTTPError):return 'HTTP '+str(e.code)
    if isinstance(e,(TimeoutError,urllib.error.URLError)):return 'Netzwerk nicht erreichbar oder Zeitüberschreitung'
    return str(e).split('https://')[0][:250]

def validate_meta(m,require_episode=True):
    if m.get('kind') not in ('movie','series'):raise ValueError('Film oder Serie auswählen')
    if not str(m.get('title','')).strip():raise ValueError('Titel fehlt')
    for key,lo,hi in [('year',1880,2100),('season',0,999),('episode',1,9999)]:
        val=m.get(key)
        if val in ('',None):m[key]=None
        else:
            m[key]=int(val)
            if not lo<=m[key]<=hi:raise ValueError(key+': Wert außerhalb des gültigen Bereichs')
    if require_episode and m['kind']=='series' and (m['season'] is None or m['episode'] is None):raise ValueError('Staffel und Folge fehlen; keine Staffel 1 erfinden')
    if m['kind']=='movie':m['season']=m['episode']=None;m['episode_title']=''
    return m

def target(root,meta,source_id):
    """Planned destination of a download (before the file is measured).

    0.5.42 (Björn's library layout): every title has its own folder (Filme/<Titel> (<Jahr>)/,
    Serien/<Serie> (<Jahr>)/Season NN/), file names follow ``<Titel> - (<Jahr>)``; after the
    download the measured resolution and codecs are appended (``final_target``):
    ``Spellbound - (2024) - 1080p - H264 E-AC-3.mkv`` with ``-poster``/``-backdrop`` images and NFO."""
    m=validate_meta(dict(meta))
    g={**m,'match_state':'confirmed'}
    v={'filename':'video.mkv','item_id':source_id,'season':m['season'],'episode':m['episode']}
    dest=canonical_target(root,g,v,{})[0]
    from package_media import clean_path_part
    name=clean_path_part(m['title'])+(' - (%s)'%m['year'] if m.get('year') else '')
    if m['kind']=='series':name+=' - S%02dE%02d'%(m['season'],m['episode'])
    return dest.with_name(clean_path_part(name)+dest.suffix)

VIDEO_CODECS={'h264':'H264','hevc':'HEVC','h265':'HEVC','av1':'AV1','vp9':'VP9','vp8':'VP8','mpeg2video':'MPEG2','mpeg4':'MPEG4','vc1':'VC-1'}
AUDIO_CODECS={'aac':'AAC','ac3':'AC-3','eac3':'E-AC-3','mp2':'MP2','mp3':'MP3','opus':'Opus','vorbis':'Vorbis','flac':'FLAC',
              'dts':'DTS','truehd':'TrueHD','pcm_s16le':'PCM','pcm_s24le':'PCM'}

def resolution_band(width,height):
    try:w=int(width or 0);h=int(height or 0)
    except (TypeError,ValueError):return ''
    if not w and not h:return ''
    # Width first: cinemascope 1920x800 is still a 1080p file.
    if w>=3200 or h>=1800:return '2160p'
    if w>=1800 or h>=1000:return '1080p'
    if w>=1200 or h>=700:return '720p'
    return '%dp'%h if h else ''

def quality_label(details):
    """'1080p - H264 E-AC-3' from an ffprobe result (first video stream, default/first audio stream)."""
    streams=[s for s in (details or {}).get('streams') or [] if isinstance(s,dict)]
    video=next((s for s in streams if s.get('codec_type')=='video' and not (s.get('disposition') or {}).get('attached_pic')),None)
    audios=[s for s in streams if s.get('codec_type')=='audio']
    audio=next((s for s in audios if (s.get('disposition') or {}).get('default')),audios[0] if audios else None)
    band=resolution_band((video or {}).get('width'),(video or {}).get('height'))
    codec=lambda table,s:table.get(str((s or {}).get('codec_name') or '').lower()) or str((s or {}).get('codec_name') or '').upper()[:12]
    codecs=' '.join(x for x in (codec(VIDEO_CODECS,video) if video else '',codec(AUDIO_CODECS,audio) if audio else '') if x)
    return ' - '.join(x for x in (band,re.sub(r'[^A-Za-z0-9 .+-]','',codecs).strip()) if x)

def final_target(planned,details):
    planned=Path(planned);label=quality_label(details)
    return planned.with_name(planned.stem+' - '+label+planned.suffix) if label else planned

def existing_download(planned):
    """A finished file for this planned target: exact name, the measured variant
    ('<name> - 1080p - …') or the layout before 0.5.42 ('<Titel> (<Jahr>).mkv')."""
    planned=Path(planned)
    if planned.exists():return planned
    folder=planned.parent
    if not folder.is_dir():return None
    legacy=planned.stem.replace(' - (',' (',1)
    for f in folder.iterdir():
        if f.suffix.lower() not in ('.mkv','.mp4') or f.name.endswith('.partial'):continue
        if f.stem.startswith(planned.stem+' - ') or f.stem==legacy:return f
    return None

def nfo(meta,streams,duration):
    from xml.etree import ElementTree as ET
    g={**meta,'reference':''}
    root=ET.fromstring(render_nfo(g,{'season':meta.get('season'),'episode':meta.get('episode'),'duration':duration}))
    if meta['kind']=='series':root.find('title').text=meta.get('episode_title') or meta['title']
    # reference_id identifies the show, never an individual episode.
    provider={'TMDB':'tmdb','TVDB':'tvdb','OMDb':'imdb','IMDb Offline':'imdb'}.get(meta.get('provider'))
    if meta['kind']!='series' and provider and meta.get('reference_id'):
        ET.SubElement(root,'uniqueid',{'type':provider,'default':'true'}).text=str(meta['reference_id'])
    elif meta['kind']!='series' and re.fullmatch(r'tt\d{5,10}',str(meta.get('imdb_id') or '')):
        # IMDb id published by the source itself (e.g. JustWatch) when no reference was selected.
        ET.SubElement(root,'uniqueid',{'type':'imdb','default':'true'}).text=meta['imdb_id']
    if meta['kind']=='series' and meta.get('provider')=='IMDb Offline' and meta.get('episode_verified') and meta.get('episode_reference_id'):
        ET.SubElement(root,'uniqueid',{'type':'imdb','default':'true'}).text=str(meta['episode_reference_id'])
    for genre in meta.get('genres',[]):ET.SubElement(root,'genre').text=genre
    if meta.get('rating') is not None and meta.get('provider')=='IMDb Offline' and meta.get('kind')=='movie':
        rating=ET.SubElement(ET.SubElement(root,'ratings'),'rating',{'name':'imdb','max':'10','default':'true'})
        ET.SubElement(rating,'value').text=str(meta['rating'])
        ET.SubElement(rating,'votes').text=str(meta.get('votes') or 0)
    if meta.get('fanart'):ET.SubElement(ET.SubElement(root,'fanart'),'thumb').text=meta['fanart']
    append_credits(root,meta)
    sd=ET.SubElement(ET.SubElement(root,'fileinfo'),'streamdetails')
    for s in streams:
        item=ET.SubElement(sd,s['type'])
        for key in ('codec','language'):
            if s.get(key):ET.SubElement(item,key).text=str(s[key])
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def show_nfo(meta):
    from xml.etree import ElementTree as ET
    root=ET.fromstring(render_nfo({**meta,'reference':''},{},is_show=True))
    provider={'TMDB':'tmdb','TVDB':'tvdb','OMDb':'imdb','IMDb Offline':'imdb'}.get(meta.get('provider'))
    if provider and meta.get('reference_id'):
        ET.SubElement(root,'uniqueid',{'type':provider,'default':'true'}).text=str(meta['reference_id'])
        ET.SubElement(root,'episodeguide').text=json.dumps({provider:str(meta['reference_id'])})
    elif re.fullmatch(r'tt\d{5,10}',str(meta.get('show_imdb_id') or '')):
        ET.SubElement(root,'uniqueid',{'type':'imdb','default':'true'}).text=meta['show_imdb_id']
    for genre in meta.get('genres',[]):ET.SubElement(root,'genre').text=genre
    if meta.get('fanart'):ET.SubElement(ET.SubElement(root,'fanart'),'thumb').text=meta['fanart']
    append_credits(root,meta.get('show_credits') or {})
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def append_credits(root,meta):
    from xml.etree import ElementTree as ET
    for name in meta.get('directors',[]):ET.SubElement(root,'director').text=name
    for name in meta.get('writers',[]):ET.SubElement(root,'credits').text=name
    for actor in meta.get('cast',[]):
        item=ET.SubElement(root,'actor');ET.SubElement(item,'name').text=actor['name']
        if actor.get('role'):ET.SubElement(item,'role').text=actor['role']
