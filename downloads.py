import json, os, shutil, subprocess, tempfile, time
from pathlib import Path
import core,artwork

from runtime_tools import resolve as tool

def probe(path):
    binary=tool('ffprobe')
    if not binary:raise ValueError('ffprobe konnte nicht gestartet werden. Unter Einstellungen die Werkzeugprüfung öffnen.')
    r=subprocess.run([binary,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=120)
    if r.returncode:raise ValueError('Mediendatei kann nicht vollständig gelesen werden')
    d=json.loads(r.stdout)
    if not any(s.get('codec_type')=='video' for s in d.get('streams',[])):raise ValueError('Datei enthält keine Videospur')
    return d

def check_episode_runtime(row,meta,measured_seconds=None):
    """Use catalog duration first, then a locally measured duration if present.

    No network probing is ever triggered here. The requirement for independent
    expected runtimes avoids discarding legitimate two-minute anime episodes.
    """
    import video_causality
    source=dict(row)
    if measured_seconds is not None and measured_seconds>0:
        source['duration']=measured_seconds
    evidence=video_causality.evaluate(source,meta)
    if meta.get('video_role_needs_review') or evidence:
        role=evidence.get('video_role') if evidence else meta.get('video_role')
        if role in ('trailer','clip','extra','short_excerpt_suspected','compilation_suspected'):
            reason=evidence.get('video_role_reason') if evidence else meta.get('video_role_reason')
            raise ValueError('Video ist möglicherweise keine vollständige Folge: '+
                             (reason or 'Kurzformat markiert')+
                             '. Bitte Zuordnung vor dem Download prüfen.')
    return True


def remux(source,dest,meta,original=None):
    ffmpeg=tool('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg konnte nicht gestartet werden. Unter Einstellungen die Werkzeugprüfung öffnen.')
    tags={'title':meta.get('episode_title') or meta['title'],'date':str(meta.get('year') or ''),'description':meta.get('description',''),
          'comment':'MediathekAtlas · '+meta.get('provider','manuell')}
    if meta.get('genres'):tags['genre']='; '.join(meta['genres'])
    if meta.get('reference_id'):tags['external_id']=meta.get('provider','')+':'+str(meta['reference_id'])
    if meta['kind']=='series':tags.update(show=meta['title'],season_number=str(meta['season']),episode_id=str(meta['episode']))
    args=[ffmpeg,'-nostdin','-v','error','-n','-i',str(source),'-map','0:v','-map','0:a?','-map','0:s?','-c','copy','-map_metadata','0']
    for k,v in tags.items():args+=['-metadata',k+'='+v]
    # Explicit container: staged outputs end in .partial so sync tools skip them.
    args += ['-f','matroska',str(dest)]
    r=subprocess.run(args,capture_output=True,timeout=7200)
    if r.returncode:raise ValueError('MKV-Erstellung fehlgeschlagen: '+r.stderr.decode(errors='replace')[-250:])
    original=original if original is not None else probe(source)
    final=probe(dest)
    a=float(original.get('format',{}).get('duration') or 0);b=float(final.get('format',{}).get('duration') or 0)
    if a and abs(a-b)>max(2,a*.01):raise ValueError('Laufzeit nach MKV-Erstellung weicht ab')
    return final

def require_space(directory, required):
    free=shutil.disk_usage(directory).free
    if free < required:
        raise ValueError('Zu wenig freier Speicher am Downloadziel: %.1f GiB frei, mindestens %.1f GiB benötigt' % (free/2**30,required/2**30))
    return free

def quality_summary(details):
    return [{'type':s.get('codec_type'), 'codec':s.get('codec_name'),
             'width':s.get('width'), 'height':s.get('height'),
             'channels':s.get('channels'), 'language':s.get('tags',{}).get('language')}
            for s in details.get('streams',[]) if s.get('codec_type') in ('video','audio','subtitle')]

QUALITY_KEYS={'hd':['url_video_hd','url_video','url_video_low'],'standard':['url_video','url_video_hd','url_video_low'],'low':['url_video_low','url_video','url_video_hd']}

def safe_url(url):
    """Percent-encode characters an HTTP request line cannot carry (spaces, control characters).
    Netzkino's CDN delivers paths like '/YFEN/Die_verwegenen_Vier_reissen_aus_-_Teil 1.mp4' (0.5.42);
    existing %-escapes and reserved characters stay as they are."""
    if not url:return url
    import urllib.parse
    parts=urllib.parse.urlsplit(str(url).strip())
    keep="/%:@!$&'()*+,;=-._~"
    return urllib.parse.urlunsplit((parts.scheme,parts.netloc,urllib.parse.quote(parts.path,safe=keep),
                                    urllib.parse.quote(parts.query,safe=keep+'?'),urllib.parse.quote(parts.fragment,safe=keep+'?')))

def source_url(row,quality='best'):
    return safe_url(_source_url(row,quality))

def _source_url(row,quality='best'):
    """Direct file address for one job. Sources without a stable file address
    (Netzkino pages) carry a resolver and are resolved right before download,
    so the rest of the pipeline (MKV, NFO, naming, .partial staging) is shared."""
    if row.get('_resolver')=='netzkino':
        import ytdl_bridge
        import download_quality
        # 0.5.63: only a chosen picture height is passed on; "best" resolves exactly as before
        wish=download_quality.normalize(quality)
        return (ytdl_bridge.resolve(row.get('_page_url'),quality=wish) if wish.isdigit() else ytdl_bridge.resolve(row.get('_page_url')))['url']
    if row.get('_resolver')=='pluto':
        import pluto_downloads
        return pluto_downloads.resolve(row)
    if row.get('_resolver')=='justwatch':
        import justwatch_downloads
        return justwatch_downloads.resolve(row)
    if row.get('_resolver')=='rakuten':
        import rakuten_downloads
        return rakuten_downloads.resolve(row)
    if row.get('_resolver')=='plex':
        # 0.6.3: Plex film or episode without copy protection (HLS or DASH, both copied by ffmpeg)
        import plex_downloads
        return plex_downloads.resolve(row)
    if row.get('_resolver')=='youtube':return row.get('url')
    if row.get('_resolver'):raise ValueError('Unbekannte Downloadquelle')
    keys=QUALITY_KEYS
    import download_quality
    return row.get('_download_url') or next((row.get(k) for k in keys.get(download_quality.mediathek_key(quality),keys['hd']) if row.get(k)),None)

HLS_RESOLVERS={'pluto','justwatch','rakuten','plex'}

def public_url(row,url):
    """Address written to metadata.json. Session-bound HLS addresses carry a token in the
    query string; only scheme, host and path are kept so no token ends up on disk."""
    if row.get('_resolver') in HLS_RESOLVERS:return str(url).split('?',1)[0]
    return url

def fetch_hls(url,src,directory,expected,update,cancelled,reserve=256*1024*1024,min_share=.85,playlist=None):
    """Copy an HLS stream (best variant, ffmpeg default selection) into a staged Matroska file.
    Progress comes from ffmpeg's -progress output; a cancel stops ffmpeg at once."""
    ffmpeg=tool('ffmpeg')
    # 0.5.63: with a chosen resolution ffmpeg reads a local list that holds this one level (download_quality)
    args=[ffmpeg,'-nostdin','-v','error']+(['-protocol_whitelist','file,http,https,tcp,tls,crypto','-i',str(playlist)] if playlist else
          ['-reconnect','1','-reconnect_streamed','1','-reconnect_delay_max','5','-i',url])+['-sn','-dn','-c','copy','-bsf:a','aac_adtstoasc','-f','matroska','-progress','pipe:1','-nostats','-y',str(src)]
    require_space(directory,reserve)
    update('downloading',0,0,speed=0,eta=None)
    import threading
    log=tempfile.TemporaryFile(mode='w+',encoding='utf-8',errors='replace')
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=log,stdin=subprocess.DEVNULL,text=True)
    started=time.monotonic();last=0;position=0.0;received=0;stop=threading.Event()
    def watch():
        # A stalled network leaves ffmpeg silent; cancelling must still end it promptly.
        while not stop.wait(1):
            if cancelled():
                proc.kill();return
    threading.Thread(target=watch,name='hls-cancel',daemon=True).start()
    try:
        for line in proc.stdout:
            if cancelled():raise ValueError('Download abgebrochen')
            key,_,value=line.strip().partition('=')
            if key in ('out_time_us','out_time_ms'):
                try:position=max(position,int(value)/1e6)
                except ValueError:pass
            elif key=='total_size':
                try:received=max(received,int(value))
                except ValueError:pass
            if key=='progress' and time.monotonic()-last>.5:
                elapsed=max(.001,time.monotonic()-started);speed=received/elapsed
                rate=position/elapsed
                total=int(received*expected/position) if expected and position>5 else 0
                require_space(directory,max(0,2*total-received)+reserve if total else received+reserve)
                update('downloading',received,total,speed=speed,eta=max(0,(expected-position)/rate) if expected and rate>0 else None)
                last=time.monotonic()
        code=proc.wait()
        if cancelled():raise ValueError('Download abgebrochen')
        log.seek(0);error=log.read()[-4000:]
        if code!=0:
            detail=' '.join(error.split())[-300:]
            raise ValueError('HLS-Download fehlgeschlagen'+(': '+detail.split('?',1)[0] if detail else ''))
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill();proc.wait()
        proc.stdout.close();log.close()
    received=src.stat().st_size if src.exists() else 0
    if not received:raise ValueError('HLS-Download lieferte keine Daten')
    # Ad-supported streams (Pluto, JustWatch): catalogue runtimes can include ad breaks that are
    # not delivered; Björn's Pluto copy had 86 of 98 minutes. Allow 85 %, still refuse real cuts.
    if expected and position and position<expected*min_share:
        raise ValueError('Download unvollständig: %d von %d Minuten'%(position//60,expected//60))
    return received

def run(row,meta,root,quality,update,cancelled):
    # The catalogue already records most offer runtimes. Reject obvious extras
    # before any download or FFmpeg process; FFprobe is not a catalog scanner.
    if meta.get('kind')=='series':check_episode_runtime(row,meta)
    if not tool('ffmpeg') or not tool('ffprobe'):raise ValueError('ffmpeg oder ffprobe ist nicht startbar. Unter Einstellungen die gefundenen Pfade prüfen.')
    # 0.5.53: YouTube (opt-in) is fetched by yt-dlp into the staged file; no address leaves the module.
    fetcher=row.get('_resolver')=='youtube'
    url=row.get('url') if fetcher else source_url(row,quality)
    if not url:raise ValueError('Keine Downloadadresse vorhanden')
    hls=row.get('_resolver') in HLS_RESOLVERS
    if not hls and ('.m3u8' in url.lower() or '.mpd' in url.lower()):raise ValueError('HLS/DASH ist in v0.1 noch nicht implementiert; bitte MP4-Fassung wählen')
    dest=core.target(root,meta,row['_id'])
    dest.parent.mkdir(parents=True,exist_ok=True)
    if core.existing_download(dest) or any(p.exists() for p in (dest.with_suffix('.nfo'),dest.with_suffix('.metadata.json'))):raise FileExistsError('Zieldatei oder Metadaten existieren bereits – nichts überschrieben')
    # Every staged name ends in .partial: MeshSync and similar tools skip these until publication.
    lock=dest.with_suffix('.lock.partial')
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='.mediathekatlas-',suffix='.partial',dir=dest.parent) as work:
            src=Path(work)/'original.bin.partial';out=Path(work)/'tagged.mkv.partial';checked={}
            reserve=256*1024*1024
            if fetcher:
                import youtube_downloads
                received=youtube_downloads.fetch({**row,'_quality':quality},src,dest.parent,update,cancelled);total=0
            elif hls:
                try:expected=float(row.get('duration') or 0)
                except (TypeError,ValueError):expected=0
                import download_quality
                try:playlist,_level=download_quality.hls_playlist(url,quality,work)
                except Exception:playlist,_level=None,None   # no levels readable: best level as before
                received=fetch_hls(url,src,dest.parent,expected,update,cancelled,reserve,playlist=playlist);total=0
            else:
                with core.open_url(url) as response,src.open('wb') as f:
                    ctype=response.headers.get('Content-Type','').lower()
                    if any(x in ctype for x in ('text/html','mpegurl','dash+xml')):raise ValueError('Server liefert keine direkte Videodatei')
                    total=max(0,int(response.headers.get('Content-Length') or 0));received=0;last=0
                    # 0.5.95: Archive.org downloads are hashed while they arrive and compared with the published checksum.
                    expect=row.get('_expect') if isinstance(row.get('_expect'),dict) else None
                    if expect is not None:
                        import archive_receipts
                        digests=archive_receipts.hashers()
                    started=time.monotonic();reserve=256*1024*1024
                    require_space(dest.parent,2*total+reserve)
                    update('downloading',0,total,speed=0,eta=None)
                    while True:
                        if cancelled():raise ValueError('Download abgebrochen')
                        chunk=response.read(1024*1024)
                        if not chunk:break
                        f.write(chunk);received+=len(chunk)
                        if expect is not None:
                            for digest in digests.values():digest.update(chunk)
                        if time.monotonic()-last>.5:
                            speed=received/max(.001,time.monotonic()-started)
                            require_space(dest.parent,max(0,2*total-received)+reserve if total else received+reserve)
                            update('downloading',received,total,speed=speed,eta=max(0,(total-received)/speed) if total and speed else None);last=time.monotonic()
                    if total and received!=total:raise ValueError('Download unvollständig')
                    if expect is not None:checked['source_check']=archive_receipts.source_check(expect,digests,received)
            require_space(dest.parent,int(received*1.05)+reserve)
            update('tagging',received,total,speed=0,eta=None,**checked)
            if cancelled():raise ValueError('Download abgebrochen')
            original_probe=probe(src)
            if meta.get('kind')=='series':
                try:actual=float(original_probe.get('format',{}).get('duration') or 0)
                except (TypeError,ValueError,OverflowError):actual=0
                check_episode_runtime(row,meta,actual if actual>0 else None)
            details=remux(src,out,meta,original=original_probe)
            if cancelled():raise ValueError('Download abgebrochen')
            streams=core.parse_streams(details);duration=float(details.get('format',{}).get('duration') or 0)
            # 0.5.42: the published name carries the measured resolution and codecs.
            dest=core.final_target(dest,details)
            if any(p.exists() for p in (dest,dest.with_suffix('.nfo'),dest.with_suffix('.metadata.json'))):raise FileExistsError('Zieldatei oder Metadaten existieren bereits – nichts überschrieben')
            # Stage all mandatory sidecars before publishing any file.
            nfo=Path(work)/'video.nfo.partial';nfo.write_bytes(core.nfo(meta,streams,duration))
            metadata=Path(work)/'video.json.partial';metadata.write_text(json.dumps({'schema':'MediathekAtlas/1','metadata':meta,'source':row,'streams':streams,'duration':duration,'download_url':public_url(row,url)},ensure_ascii=False,indent=2))
            published=[]
            try:
                for a,b in [(nfo,dest.with_suffix('.nfo')),(metadata,dest.with_suffix('.metadata.json')),(out,dest)]:
                    os.link(a,b);published.append(b) # exclusive creation, same filesystem
            except Exception:
                for p in published:p.unlink(missing_ok=True)
                raise
            if meta['kind']=='series':
                show=dest.parent.parent/'tvshow.nfo'
                if not show.exists():
                    try:
                        with show.open('xb') as f:f.write(core.show_nfo(meta))
                    except FileExistsError:pass
            # Films: '<Datei>-poster' / '<Datei>-backdrop' next to the video (Kodi, Jellyfin, Plex);
            # series: poster/fanart once in the show folder for tvshow.nfo.
            # Fanart.tv logos (0.5.56): 'clearlogo' / '<Datei>-clearlogo' as Jellyfin and Kodi expect.
            if meta['kind']=='series':images=[('poster',dest.parent.parent/'poster'),('fanart',dest.parent.parent/'fanart'),('logo',dest.parent.parent/'clearlogo')]
            else:images=[('poster',dest.with_name(dest.stem+'-poster')),('fanart',dest.with_name(dest.stem+'-backdrop')),('logo',dest.with_name(dest.stem+'-clearlogo'))]
            missing=[field for field,stem in images if meta.get(field) and not artwork.save_image(meta[field],stem)]
            update('done',received,total,path=str(dest),measured=quality_summary(details),size_bytes=dest.stat().st_size,speed=0,eta=None,note='Video fertig; Bilder nicht abrufbar: '+', '.join(missing) if missing else '')

    finally:lock.unlink(missing_ok=True)
