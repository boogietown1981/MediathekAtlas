"""Stream the public MediathekView snapshot without discarding repeated JSON keys."""
import io,json,lzma,os,time
from pathlib import Path
import core,diagnostics
URL='https://liste.mediathekview.de/Filmliste-akt.xz'

def _download(root,progress,cancelled):
    dest=Path(root)/'filmliste.xz';part=dest.with_suffix('.part');received=0;last=0
    try:
        with core.open_url(URL) as response,part.open('wb') as f:
            total=int(response.headers.get('Content-Length') or 0)
            progress(phase='downloading',received=0,total=total)
            while True:
                if cancelled():raise InterruptedError('Import pausiert')
                chunk=response.read1(64*1024) if hasattr(response,'read1') else response.read(64*1024)
                if not chunk:break
                received+=len(chunk)
                if received>512*1024*1024:raise ValueError('Filmliste über 512 MiB')
                f.write(chunk)
                if time.monotonic()-last>=1:
                    progress(phase='downloading',received=received,total=total);last=time.monotonic()
            if total and received!=total:raise ValueError('Unvollständige Filmliste')
        os.replace(part,dest);return dest
    finally:part.unlink(missing_ok=True)

def download(root,progress,cancelled):
    for attempt in range(1,4):
        try:
            diagnostics.event('feed_download_start',attempt=attempt)
            return _download(root,progress,cancelled)
        except InterruptedError:raise
        except Exception as e:
            diagnostics.error('feed_download_failed',e,attempt=attempt)
            if attempt==3:raise
            progress(phase='retrying',attempt=attempt,error=core.safe_error(e))
            for _ in range(attempt*20):
                if cancelled():raise InterruptedError('Import pausiert')
                time.sleep(.1)

def pairs(stream):
    buf='';pos=0;eof=False;decoder=json.JSONDecoder();total=0
    def more():
        nonlocal buf,pos,eof,total
        data=stream.read(65536);total+=len(data)
        if total>3*1024*1024*1024:raise ValueError('Entpackte Filmliste über 3 GiB')
        buf=buf[pos:]+data;pos=0;eof=not data
        if len(buf)>4*1024*1024:raise ValueError('Einzelner Eintrag über 4 MiB')
    def token():
        nonlocal pos
        while True:
            while pos<len(buf) and buf[pos].isspace():pos+=1
            if pos<len(buf):return buf[pos]
            if eof:raise ValueError('Abgeschnittene Filmliste')
            more()
    def value():
        nonlocal pos
        token()
        while True:
            try:v,pos2=decoder.raw_decode(buf,pos);pos=pos2;return v
            except json.JSONDecodeError:
                if eof:raise ValueError('Ungültige Filmliste')
                more()
    if token()!='{':raise ValueError('Kein Filmlistenobjekt')
    pos+=1
    while True:
        if token()=='}':
            pos+=1
            tail=buf[pos:]
            while True:
                if tail.strip():raise ValueError('Unerwartete Daten nach Filmliste')
                tail=stream.read(65536)
                if not tail:return
        name=value()
        if token()!=':':raise ValueError('Fehlender Feldtrenner')
        pos+=1;yield name,value()
        t=token()
        if t==',':pos+=1
        elif t!='}':raise ValueError('Fehlender Eintragstrenner')

def expand(url,base):
    if not url:return ''
    if '|' in url and url.split('|',1)[0].isdigit():
        n,tail=url.split('|',1);n=int(n)
        if n>len(base):raise ValueError('Ungültige URL-Komprimierung')
        return base[:n]+tail
    return url

def adapt(pairs_):
    header=None;channel='';topic=''
    for name,row in pairs_:
        if name=='Filmliste' and isinstance(row,list) and 'Sender' in row and 'Url' in row:header=row;continue
        if name!='X':continue
        if not header or not isinstance(row,list) or len(row)!=len(header):raise ValueError('Unbekanntes Filmlistenformat')
        d=dict(zip(header,row));channel=d['Sender'] or channel;topic=d.get('Thema') or topic;base=d['Url'];seconds=0
        try:
            for n in d.get('Dauer','').split(':'):seconds=seconds*60+int(n)
        except ValueError:seconds=0
        try:stamp=int(d.get('DatumL') or 0)
        except ValueError:stamp=0
        if stamp>time.time()+3600:continue
        try:size=int(float(d.get('Größe [MB]') or 0)*1000000)
        except (TypeError,ValueError):size=0
        yield {'channel':channel,'topic':topic,'title':d.get('Titel',''),'description':d.get('Beschreibung',''),'timestamp':stamp,'duration':seconds,'size':size,
            'url_video':base,'url_video_hd':expand(d.get('Url HD',''),base),'url_video_low':expand(d.get('Url Klein',''),base),'url_subtitle':d.get('Url Untertitel',''),'url_website':d.get('Website',''),'geo':d.get('Geo',''),'catalog_source':'MediathekView-Filmliste'}

class XZReader(io.RawIOBase):
    def __init__(self,raw):self.raw=raw;self.dec=lzma.LZMADecompressor(memlimit=128*1024*1024)
    def readable(self):return True
    def readinto(self,b):
        while not self.dec.eof:
            data=self.raw.read(65536) if self.dec.needs_input else b''
            if not data and self.dec.needs_input:raise ValueError('Abgeschnittene XZ-Datei')
            chunk=self.dec.decompress(data,max_length=len(b))
            if chunk:b[:len(chunk)]=chunk;return len(chunk)
        return 0

def read_rows(path):
    with open(path,'rb') as raw:
        with io.TextIOWrapper(io.BufferedReader(XZReader(raw)),encoding='utf-8') as text:
            yield from adapt(pairs(text))
