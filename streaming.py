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
import json,os,re,secrets,subprocess,threading,time
from pathlib import Path
import catalog,hls_variants
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
    import downloads
    return {'kind':'url','url':downloads.safe_url(found['url']),'hls':False,'quality':'Netzkino MP4','title':title,
            'duration':row.get('duration') or found.get('duration') or 0,'provider':'netzkino'}

def resolve(c,offer='',job='',netzkino='',root=None,resolver=None,pluto='',justwatch='',rakuten='',joyn='',quality='auto',youtube='',toggo=''):
    """Best playable source: a finished local download wins over the online stream."""
    if youtube:
        # 0.5.78: YouTube video in the own player (only after the opt-in, see youtube_downloads.play_source)
        if root is None:raise ValueError('YouTube-Katalog nicht verfügbar')
        import youtube_downloads
        return youtube_downloads.play_source(root,youtube,quality)
    if toggo:
        # 0.5.79: TOGGO episode, only if TOGGO lists a stream without copy protection (toggo.py)
        if root is None:raise ValueError('TOGGO-Katalog nicht verfügbar')
        import toggo as toggo_tv
        return toggo_tv.play_source(root,toggo)
    if joyn:
        # 0.5.65: Joyn playback is not released (copy protection, see joyn.py) -> clear refusal.
        if root is None:raise ValueError('Joyn-Katalog nicht verfügbar')
        import joyn as joyn_tv
        return joyn_tv.play_source(root,joyn)
    if rakuten:
        if root is None:raise ValueError('Rakuten-Katalog nicht verfügbar')
        import rakuten as rakuten_tv
        return rakuten_tv.play_source(root,rakuten)
    if justwatch:
        if root is None:raise ValueError('JustWatch-Katalog nicht verfügbar')
        import justwatch as justwatch_tv
        return justwatch_tv.play_source(root,justwatch)
    if pluto:
        if root is None:raise ValueError('Pluto-Katalog nicht verfügbar')
        import pluto as pluto_tv
        return pluto_tv.play_source(root,pluto)
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
    # 0.5.63: the wish of the player decides ('max' = up to 1080p as before, 'auto' = up to 720p, or a height).
    limit=quality_limit(quality)
    best=(sorted(direct,key=lambda l:(0<(l['height_hint'] or 720)<=limit,l['score'] if (l['height_hint'] or 720)<=limit else -(l['height_hint'] or 720)),reverse=True) or usable)[0]
    out={'kind':'url','url':best['url'],'hls':bool(HLS.search(best['url'])),'quality':best['quality'],'title':title,'duration':duration}
    out['files']=sorted({int(l['height_hint']) for l in direct if l.get('height_hint')},reverse=True)   # resolutions offered as files
    # Broadcaster live streams (0.5.50): no length, no resume position, title = station.
    if str(row.get('topic') or '').strip() in catalog.LIVE_TOPICS:
        import live_tv
        out.update(live=True,duration=0,title=live_tv.station_name(row.get('title'),row.get('channel')),quality='Live · '+best['quality'],provider='mediathek')
    return out

def quality_limit(quality):
    """Largest picture height for a wish of the player: 'max', 'auto' or a number such as '480'."""
    wish=str(quality or 'auto').strip().lower()
    if wish=='max':return 1080
    try:return max(144,min(int(wish),4320))
    except ValueError:return hls_variants.AUTO_HEIGHT

def hls_levels(source,fetch=None):
    """Quality levels of an online HLS source for the player; [] when there is nothing to choose
    (media playlist, provider not reachable). Never raises: without levels ffmpeg gets the address as before."""
    if source.get('kind')!='url' or not source.get('hls'):return []
    try:return hls_variants.levels(hls_variants.load(source['url'],fetch)[2])
    except Exception:return []

def prepare(source,quality='auto',folder=None,fetch=None):
    """One quality level as a local playlist for ffmpeg. Returns (path or None, chosen level or None).

    ffmpeg opens every level of a master playlist before it starts and plays the largest one. With a
    playlist that holds one level it starts sooner and loads what the connection can carry."""
    if source.get('kind')!='url' or not source.get('hls') or folder is None:return None,None
    try:
        text,final,variants=hls_variants.load(source['url'],fetch)
        chosen=hls_variants.choose(variants,quality)
        if not chosen:return None,None
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for old in folder.glob('hls-*.m3u8'):
            # left over after a crash: nothing references a list older than a day
            try:
                if time.time()-old.stat().st_mtime>86400:old.unlink()
            except OSError:pass
        path=folder/('hls-%s.m3u8'%secrets.token_hex(8))
        path.write_text(hls_variants.single(text,final,chosen),encoding='utf-8')
        try:os.chmod(path,0o600)
        except OSError:pass
        return path,{'label':hls_variants.label(chosen),'height':chosen['height'],'bandwidth':chosen['bandwidth'],'levels':len(variants)}
    except Exception:
        return None,None

def probe(path):
    binary=tool('ffprobe')
    if not binary:return {}
    try:
        r=subprocess.run([binary,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30)
        return json.loads(r.stdout) if not r.returncode else {}
    except (OSError,ValueError,subprocess.TimeoutExpired):return {}

def plan(source,info=None,levels=True):
    """What the browser should do: 'direct' (play the source itself) or 'remux' (via /api/stream)."""
    out={'title':source['title'],'duration':float(source.get('duration') or 0)}
    if source['kind']=='url':
        # 'remux' (0.5.78): addresses only the server may fetch (bound to its IP, picture and sound separate)
        out.update(mode='remux' if source['hls'] or source.get('remux') else 'direct',url=source['url'],hls=source['hls'],quality=source.get('quality'),origin='online')
        if source.get('remux') and not source['hls']:out.pop('url')
        if source.get('provider'):out['provider']=source['provider']
        if source.get('live'):out['live']=True
        # 0.5.63: what the player can offer under "Qualität" (HLS levels or the broadcaster's files)
        # 0.5.72: levels=False skips the provider request; the browser reads the levels itself (hls.js)
        out['levels']=(hls_levels(source) if levels else []) if source['hls'] else [{'id':str(h),'label':'%dp'%h,'height':h,'bandwidth':0} for h in source.get('files') or []]
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

def command(source,start=0.0,audio_copy=True,playlist=None):
    ffmpeg=tool('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg konnte nicht gestartet werden. Unter Einstellungen die Werkzeugprüfung öffnen.')
    args=[ffmpeg,'-nostdin','-v','error']
    if source['kind']=='url':
        audio_copy='aac'
        # A local one-level playlist (prepare) is a file: the HTTP options belong to addresses only.
        if playlist:args+=['-protocol_whitelist','file,http,https,tcp,tls,crypto']
        else:args+=['-reconnect','1','-reconnect_streamed','1','-reconnect_delay_max','5']
        # Live: keep asking when the provider's list is late (ffmpeg gives up after 3 tries otherwise).
        if source.get('hls') and source.get('live'):args+=['-max_reload','60']
    if start>0:args+=['-ss','%.3f'%start]
    args+=['-i',source['path'] if source['kind']=='file' else str(playlist) if playlist else source['url']]
    # 0.5.78: picture and sound from two addresses (YouTube): second input with the same options, joined while playing
    second=source['kind']=='url' and not playlist and source.get('audio_url')
    if second:
        args+=['-reconnect','1','-reconnect_streamed','1','-reconnect_delay_max','5']
        if start>0:args+=['-ss','%.3f'%start]
        args+=['-i',second,'-map','0:v:0','-map','1:a:0']
    # HLS seeks land on the segment before the position; stream copy would keep that pre-roll and the
    # player's clock would run seconds ahead. An output start of 0 drops it (copy starts on a keyframe).
    if start>0:args+=['-ss','0']
    # Default stream selection takes the highest resolution video and the richest audio track,
    # which also picks the best variant of an HLS master playlist.
    # Broadcaster HLS carries ADTS AAC in MPEG-TS; MP4 needs it converted (older ffmpeg does not do this itself).
    audio=['-c:a','copy','-bsf:a','aac_adtstoasc'] if audio_copy=='aac' else ['-c:a','copy'] if audio_copy else ['-c:a','aac','-b:a','192k','-ac','2']
    args+=['-sn','-dn','-c:v','copy']+audio
    # 0.5.63 (Björn, 12.11.2026: picture and sound out of step with every provider): with
    # 'empty_moov' the file header is written before the first packet, and a track that starts later
    # than the other (audio 0.8 s after the picture in a live stream, the picture up to one keyframe
    # interval after the sound when resuming) was moved to zero - the offset was lost. 'delay_moov'
    # writes the header with the first fragment and keeps the offset (measured: 0.778 s kept instead of 0).
    args+=['-movflags','frag_keyframe+delay_moov+default_base_moof']
    # 0.5.55: online streams arrive in real time. With one fragment per keyframe interval (often 6-10 s
    # for Pluto TV and other HLS sources) the browser got the picture in bursts and ran dry in between
    # (Björn, 12.11.2026: streams stutter). One fragment per second keeps the delivery even.
    if source['kind']=='url':args+=['-frag_duration','1000000','-flush_packets','1']
    args+=['-f','mp4','pipe:1']
    return args

def audio_copy(source,info=None):
    """'aac' (copy with ADTS fix), True (copy), False (convert to AAC)."""
    if source['kind']=='url':return 'aac'
    info=probe(source['path']) if info is None else info
    audio=next((s.get('codec_name') for s in info.get('streams',[]) if s.get('codec_type')=='audio'),None)
    return 'aac' if audio=='aac' else not audio or audio in BROWSER_AUDIO

def start(args,session='',cleanup=None):
    """Start ffmpeg; a new request of the same player session replaces its previous stream (seeking)."""
    with _LOCK:
        old=_RUNNING.pop(session,None) if session else None
        if old:_stop(old)
        for key,proc in list(_RUNNING.items()):
            if proc.poll() is not None:_RUNNING.pop(key,None)
        if len(_RUNNING)>=MAX_STREAMS:raise RuntimeError('Es laufen bereits %d Wiedergaben. Bitte eine beenden und erneut versuchen.'%MAX_STREAMS)
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL)
        proc.atlas_cleanup=cleanup   # one-level playlist of this stream
        _RUNNING[session or str(id(proc))]=proc
    return proc

def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(3)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()

def finish(proc):
    cleanup=getattr(proc,'atlas_cleanup',None)
    if cleanup:
        try:Path(cleanup).unlink()
        except OSError:pass
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
