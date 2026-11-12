"""Play catalogue entries and finished downloads in the browser.

Sources are only ever looked up in the local database (offer, record or job id),
never taken from the request, so the stream endpoint cannot be used to fetch
arbitrary URLs or files.

Direct MP4 links from the broadcasters are played by the browser itself. MKV
downloads and HLS streams are remuxed on the fly by ffmpeg into fragmented MP4
(video copied, audio copied or converted to AAC), which every current browser
plays. That costs little CPU and also works on older NAS models. Seeking in a
remuxed stream restarts ffmpeg at the requested position (-ss before -i).
"""
import json,re,subprocess,threading,time
from pathlib import Path
import catalog
from runtime_tools import resolve as tool

BROWSER_FILES={'.mp4':'video/mp4','.m4v':'video/mp4','.webm':'video/webm'}
BROWSER_VIDEO={'h264','hevc','vp9','av1'}
BROWSER_AUDIO={'aac','mp3','opus'}
HLS=re.compile(r'(?i)\.m3u8(?:\?|$)')
DASH=re.compile(r'(?i)\.mpd(?:\?|$)')
MAX_STREAMS=3
_LOCK=threading.Lock();_RUNNING={}

def _http(url):return isinstance(url,str) and re.match(r'(?i)^https?://',url) is not None

def _title(meta,row):
    meta=meta or {};row=row or {}
    name=meta.get('title') or row.get('topic') or row.get('title') or 'Video'
    if meta.get('kind')=='series' and meta.get('episode'):
        name+=' · S%02dE%02d'%(int(meta.get('season') or 0),int(meta['episode']))
        if meta.get('episode_title'):name+=' · '+meta['episode_title']
    elif meta.get('year'):name+=' (%s)'%meta['year']
    return name

NETZKINO_TTL=900
_NK_CACHE={}

def _netzkino_local(c,item_id):
    """Finished offline copy of a Netzkino title (shared download queue), if the file still exists."""
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='done' AND payload LIKE ?",('%'+item_id+'%',)):
        try:j=json.loads(payload)
        except ValueError:continue
        if j.get('netzkino_id')!=item_id:continue
        path=Path(j.get('path') or j.get('target') or '')
        if path.is_file():return j,path
    return None,None

def resolve_netzkino(c,root,item_id,resolver=None,now=None):
    """Netzkino film: the local offline copy wins, otherwise ytdl-nightly resolves the MP4 file.

    The page address comes from the local Netzkino catalogue (never from the request). Resolved
    file addresses are cached briefly so that seeking in a remuxed stream does not query Netzkino again.
    """
    import netzkino_details
    item_id=str(item_id or '')
    db=netzkino_details._connect(root)
    try:row=netzkino_details._find(db,item_id)
    finally:db.close()
    title=row['title']+(' (%s)'%row['year'] if row.get('year') else '')
    job,path=_netzkino_local(c,item_id)
    if path:return {'kind':'file','path':str(path),'title':title,'duration':row.get('duration') or 0,'provider':'netzkino'}
    now=time.time() if now is None else now
    hit=_NK_CACHE.get(item_id)
    if hit and hit[0]>now:found=hit[1]
    else:
        if resolver is None:
            import ytdl_bridge;resolver=ytdl_bridge.resolve
        try:found=resolver(row['url'])
        except Exception as e:raise ValueError(str(e) or 'Netzkino-Adresse konnte nicht aufgelöst werden') from None
        _NK_CACHE[item_id]=(now+NETZKINO_TTL,found)
    return {'kind':'url','url':found['url'],'hls':False,'quality':'Netzkino MP4','title':title,
            'duration':row.get('duration') or found.get('duration') or 0,'provider':'netzkino'}

def resolve(c,offer='',job='',netzkino='',root=None,resolver=None):
    """Best playable source: a finished local download wins over the online stream."""
    if netzkino:
        if root is None:raise ValueError('Netzkino-Katalog nicht verfügbar')
        return resolve_netzkino(c,root,netzkino,resolver)
    if job:
        r=c.execute("SELECT payload FROM jobs WHERE id=? AND state='done'",(job,)).fetchone()
        if not r:raise ValueError('Nur abgeschlossene Downloads können abgespielt werden')
        j=json.loads(r[0]);path=Path(j.get('path') or j.get('target') or '')
        if not path.is_file():raise ValueError('Datei wurde verschoben oder ist nicht verfügbar')
        return {'kind':'file','path':str(path),'title':_title(j.get('metadata'),j.get('source')),'duration':(j.get('source') or {}).get('duration') or 0}
    if not offer:raise ValueError('Kein Eintrag zum Abspielen angegeben')
    r=c.execute('SELECT o.payload,o.work_id,w.meta FROM offers o LEFT JOIN works w ON w.id=o.work_id WHERE o.id=?',(offer,)).fetchone()
    if r:row,meta=json.loads(r[0]),json.loads(r[2] or '{}')
    else:
        r=c.execute('SELECT payload FROM records WHERE id=?',(offer,)).fetchone()
        if not r:raise ValueError('Eintrag nicht gefunden; Ansicht neu laden')
        row,meta=json.loads(r[0]),{}
    title=_title(meta,row);duration=row.get('duration') or 0
    if r and len(r)>1 and r[1]:
        local=c.execute('SELECT path FROM downloaded_items WHERE identity=?',(r[1],)).fetchone()
        if local and local[0] and Path(local[0]).is_file():return {'kind':'file','path':local[0],'title':title,'duration':duration}
    usable=[l for l in catalog.links(row) if _http(l['url']) and not DASH.search(l['url'])]
    if not usable:raise ValueError('Für diesen Eintrag gibt es keinen abspielbaren Stream')
    # Prefer a direct file up to 1080p for smooth playback, then HLS.
    direct=[l for l in usable if l['supported']]
    best=(sorted(direct,key=lambda l:(0<(l['height_hint'] or 720)<=1080,l['score']),reverse=True) or usable)[0]
    return {'kind':'url','url':best['url'],'hls':bool(HLS.search(best['url'])),'quality':best['quality'],'title':title,'duration':duration}

def probe(path):
    binary=tool('ffprobe')
    if not binary:return {}
    try:
        r=subprocess.run([binary,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30)
        return json.loads(r.stdout) if not r.returncode else {}
    except (OSError,ValueError,subprocess.TimeoutExpired):return {}

def plan(source,info=None):
    """What the browser should do: 'direct' (play the source itself) or 'remux' (via /api/stream)."""
    out={'title':source['title'],'duration':float(source.get('duration') or 0)}
    if source['kind']=='url':
        out.update(mode='remux' if source['hls'] else 'direct',url=source['url'],hls=source['hls'],quality=source.get('quality'),origin='online')
        if source.get('provider'):out['provider']=source['provider']
        return out
    out['origin']='local';path=Path(source['path'])
    info=probe(path) if info is None else info
    streams=info.get('streams',[])
    video=next((s.get('codec_name') for s in streams if s.get('codec_type')=='video'),None)
    audio=next((s.get('codec_name') for s in streams if s.get('codec_type')=='audio'),None)
    if info.get('format',{}).get('duration'):out['duration']=float(info['format']['duration'])
    if video and video not in BROWSER_VIDEO:raise ValueError('Das Videoformat %s kann der Browser nicht abspielen. Datei bitte mit einem Player wie VLC öffnen.'%video)
    direct=path.suffix.lower() in BROWSER_FILES and (not audio or audio in BROWSER_AUDIO)
    out.update(mode='direct' if direct else 'remux',file=path.name)
    return out

def command(source,start=0.0,audio_copy=True):
    ffmpeg=tool('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg konnte nicht gestartet werden. Unter Einstellungen die Werkzeugprüfung öffnen.')
    args=[ffmpeg,'-nostdin','-v','error']
    if source['kind']=='url':audio_copy='aac';args+=['-reconnect','1','-reconnect_streamed','1','-reconnect_delay_max','5']
    if start>0:args+=['-ss','%.3f'%start]
    args+=['-i',source['path'] if source['kind']=='file' else source['url']]
    # HLS seeks land on the segment before the position; stream copy would keep that pre-roll and the
    # player's clock would run seconds ahead. An output start of 0 drops it (copy starts on a keyframe).
    if start>0:args+=['-ss','0']
    # Default stream selection takes the highest resolution video and the richest audio track,
    # which also picks the best variant of an HLS master playlist.
    # Broadcaster HLS carries ADTS AAC in MPEG-TS; MP4 needs it converted (older ffmpeg does not do this itself).
    audio=['-c:a','copy','-bsf:a','aac_adtstoasc'] if audio_copy=='aac' else ['-c:a','copy'] if audio_copy else ['-c:a','aac','-b:a','192k','-ac','2']
    args+=['-sn','-dn','-c:v','copy']+audio
    args+=['-movflags','frag_keyframe+empty_moov+default_base_moof','-f','mp4','pipe:1']
    return args

def audio_copy(source,info=None):
    """'aac' (copy with ADTS fix), True (copy), False (convert to AAC)."""
    if source['kind']=='url':return 'aac'
    info=probe(source['path']) if info is None else info
    audio=next((s.get('codec_name') for s in info.get('streams',[]) if s.get('codec_type')=='audio'),None)
    return 'aac' if audio=='aac' else not audio or audio in BROWSER_AUDIO

def start(args,session=''):
    """Start ffmpeg; a new request of the same player session replaces its previous stream (seeking)."""
    with _LOCK:
        old=_RUNNING.pop(session,None) if session else None
        if old:_stop(old)
        for key,proc in list(_RUNNING.items()):
            if proc.poll() is not None:_RUNNING.pop(key,None)
        if len(_RUNNING)>=MAX_STREAMS:raise RuntimeError('Es laufen bereits %d Wiedergaben. Bitte eine beenden und erneut versuchen.'%MAX_STREAMS)
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL)
        _RUNNING[session or str(id(proc))]=proc
    return proc

def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(3)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()

def finish(proc):
    with _LOCK:
        for key,p in list(_RUNNING.items()):
            if p is proc:_RUNNING.pop(key,None)
    _stop(proc)
    err=b''
    try:err=proc.stderr.read()[-400:]
    except (OSError,ValueError):pass
    return proc.returncode,err.decode(errors='replace')

def running():
    with _LOCK:return sum(1 for p in _RUNNING.values() if p.poll() is None)
