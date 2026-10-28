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

def remux(source,dest,meta):
    ffmpeg=tool('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg konnte nicht gestartet werden. Unter Einstellungen die Werkzeugprüfung öffnen.')
    tags={'title':meta.get('episode_title') or meta['title'],'date':str(meta.get('year') or ''),'description':meta.get('description',''),
          'comment':'MediathekAtlas · '+meta.get('provider','manuell')}
    if meta.get('genres'):tags['genre']='; '.join(meta['genres'])
    if meta.get('reference_id'):tags['external_id']=meta.get('provider','')+':'+str(meta['reference_id'])
    if meta['kind']=='series':tags.update(show=meta['title'],season_number=str(meta['season']),episode_id=str(meta['episode']))
    args=[ffmpeg,'-nostdin','-v','error','-n','-i',str(source),'-map','0:v','-map','0:a?','-map','0:s?','-c','copy','-map_metadata','0']
    for k,v in tags.items():args+=['-metadata',k+'='+v]
    args += [str(dest)]
    r=subprocess.run(args,capture_output=True,timeout=7200)
    if r.returncode:raise ValueError('MKV-Erstellung fehlgeschlagen: '+r.stderr.decode(errors='replace')[-250:])
    original=probe(source);final=probe(dest)
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

def run(row,meta,root,quality,update,cancelled):
    if not tool('ffmpeg') or not tool('ffprobe'):raise ValueError('ffmpeg oder ffprobe ist nicht startbar. Unter Einstellungen die gefundenen Pfade prüfen.')
    keys={'hd':['url_video_hd','url_video','url_video_low'],'standard':['url_video','url_video_hd','url_video_low'],'low':['url_video_low','url_video','url_video_hd']}
    url=row.get('_download_url') or next((row.get(k) for k in keys.get(quality,keys['hd']) if row.get(k)),None)
    if not url:raise ValueError('Keine Downloadadresse vorhanden')
    if '.m3u8' in url.lower() or '.mpd' in url.lower():raise ValueError('HLS/DASH ist in v0.1 noch nicht implementiert; bitte MP4-Fassung wählen')
    dest=core.target(root,meta,row['_id'])
    dest.parent.mkdir(parents=True,exist_ok=True)
    if any(p.exists() for p in (dest,dest.with_suffix('.nfo'),dest.with_suffix('.metadata.json'))):raise FileExistsError('Zieldatei oder Metadaten existieren bereits – nichts überschrieben')
    lock=dest.with_suffix('.lock')
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='.mediathekatlas-',dir=dest.parent) as work:
            src=Path(work)/'original.bin';out=Path(work)/'tagged.mkv'
            with core.open_url(url) as response,src.open('wb') as f:
                ctype=response.headers.get('Content-Type','').lower()
                if any(x in ctype for x in ('text/html','mpegurl','dash+xml')):raise ValueError('Server liefert keine direkte Videodatei')
                total=max(0,int(response.headers.get('Content-Length') or 0));received=0;last=0
                started=time.monotonic();reserve=256*1024*1024
                require_space(dest.parent,2*total+reserve)
                update('downloading',0,total,speed=0,eta=None)
                while True:
                    if cancelled():raise ValueError('Download abgebrochen')
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    f.write(chunk);received+=len(chunk)
                    if time.monotonic()-last>.5:
                        speed=received/max(.001,time.monotonic()-started)
                        require_space(dest.parent,max(0,2*total-received)+reserve if total else received+reserve)
                        update('downloading',received,total,speed=speed,eta=max(0,(total-received)/speed) if total and speed else None);last=time.monotonic()
                if total and received!=total:raise ValueError('Download unvollständig')
            require_space(dest.parent,int(received*1.05)+reserve)
            update('tagging',received,total,speed=0,eta=None)
            if cancelled():raise ValueError('Download abgebrochen')
            details=remux(src,out,meta)
            if cancelled():raise ValueError('Download abgebrochen')
            streams=core.parse_streams(details);duration=float(details.get('format',{}).get('duration') or 0)
            # Stage all mandatory sidecars before publishing any file.
            nfo=Path(work)/'video.nfo';nfo.write_bytes(core.nfo(meta,streams,duration))
            metadata=Path(work)/'video.json';metadata.write_text(json.dumps({'schema':'MediathekAtlas/1','metadata':meta,'source':row,'streams':streams,'duration':duration,'download_url':url},ensure_ascii=False,indent=2))
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
            image_root=dest.parent.parent if meta['kind']=='series' else dest.parent
            missing=[field for field in ('poster','fanart') if meta.get(field) and not artwork.save_image(meta[field],image_root/field)]
            update('done',received,total,path=str(dest),measured=quality_summary(details),size_bytes=dest.stat().st_size,speed=0,eta=None,note='Video fertig; Bilder nicht abrufbar: '+', '.join(missing) if missing else '')

    finally:lock.unlink(missing_ok=True)
