"""Stream the public MediathekView snapshot without discarding repeated JSON keys."""
import io,json,lzma,os,time
from pathlib import Path
import core,diagnostics
URL='https://liste.mediathekview.de/Filmliste-akt.xz'

XZ_MAGIC=b'\xfd7zXZ\x00'
LIMIT=512*1024*1024

class Truncated(ConnectionError):
    """0.6.143: Verbindung endet vor Content-Length (M1-Air-Diagnose 26.11.2026: 9× nach 7.881 Byte über Mobilfunk) –
    ein Netzfehler, kein Datenfehler; der Teil-Download bleibt für die Fortsetzung liegen."""

def _validator(response):
    return response.headers.get('ETag') or response.headers.get('Last-Modified') or ''

def _download(root,progress,cancelled):
    """Lädt die Filmliste; 0.6.143: ein Teil-Download wird mit Range/If-Range fortgesetzt, solange der Server dieselbe
    Datei liefert (ETag/Last-Modified in filmliste.part.tag). Liefert er 200 statt 206, beginnt der Download neu."""
    dest=Path(root)/'filmliste.xz';part=dest.with_suffix('.part');tag=dest.with_suffix('.part.tag')
    have=part.stat().st_size if part.exists() else 0
    old=tag.read_text(encoding='utf-8').strip() if have and tag.exists() else ''
    if have and not old:have=0
    headers={'Range':'bytes=%d-'%have,'If-Range':old} if have else {}
    keep=False
    try:
        with core.open_url(URL,headers=headers) as response:
            resumed=bool(have and getattr(response,'status',200)==206)
            if not resumed:have=0
            length=int(response.headers.get('Content-Length') or 0)
            total=have+length if length else 0
            validator=_validator(response)
            if validator:tag.write_text(validator,encoding='utf-8')
            else:tag.unlink(missing_ok=True)
            received=have;last=0;head=b''
            if resumed:diagnostics.event('feed_download_resumed',offset=have,total=total)
            progress(phase='downloading',received=received,total=total,resumed=resumed)
            with part.open('ab' if resumed else 'wb') as f:
                while True:
                    if cancelled():
                        keep=bool(validator);raise InterruptedError('Import pausiert')
                    chunk=response.read1(64*1024) if hasattr(response,'read1') else response.read(64*1024)
                    if not chunk:break
                    if not resumed and len(head)<6:
                        head+=chunk[:6-len(head)]
                        if len(head)>=6 and head!=XZ_MAGIC:
                            raise ValueError('Antwort ist keine Filmliste (%s) – Anmeldeseite eines WLAN/Hotspots?'%
                                             (response.headers.get('Content-Type') or 'unbekannter Typ')[:60])
                    received+=len(chunk)
                    if received>LIMIT:raise ValueError('Filmliste über 512 MiB')
                    f.write(chunk)
                    if time.monotonic()-last>=1:
                        progress(phase='downloading',received=received,total=total);last=time.monotonic()
            if total and received!=total:
                keep=bool(validator)
                raise Truncated('Unvollständige Filmliste (%d von %d Byte, Verbindung abgebrochen; wird fortgesetzt)'%(received,total))
        os.replace(part,dest);tag.unlink(missing_ok=True);return dest
    except (OSError,TimeoutError) as e:
        # Netzabbruch mitten im Lesen: Teil behalten, wenn der Server ihn wiedererkennt (HTTP-Fehler wie 416: neu beginnen)
        import urllib.error
        if not isinstance(e,(FileNotFoundError,urllib.error.HTTPError)) and part.exists() and tag.exists():keep=True
        raise
    finally:
        if not keep:
            part.unlink(missing_ok=True);tag.unlink(missing_ok=True)

def download(root,progress,cancelled):
    for attempt in range(1,4):
        try:
            diagnostics.event('feed_download_start',attempt=attempt)
            return _download(root,progress,cancelled)
        except InterruptedError:raise
        except Exception as e:
            part=Path(root)/'filmliste.part'
            diagnostics.error('feed_download_failed',e,attempt=attempt,network=network_error(e),
                              kept_bytes=part.stat().st_size if part.exists() else 0)
            if attempt==3:raise
            progress(phase='retrying',attempt=attempt,error=core.safe_error(e))
            for _ in range(attempt*20):
                if cancelled():raise InterruptedError('Import pausiert')
                time.sleep(.1)

def network_error(e):
    """Verbindungsfehler (DNS, Abbruch, Zeitüberschreitung, Teil-Download) – für die wachsende Wartezeit."""
    import urllib.error,provider_base
    if isinstance(e,urllib.error.HTTPError):return e.code in (408,429,500,502,503,504)
    return isinstance(e,EOFError) or provider_base.network_failure(e)

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
        offer={'channel':channel,'topic':topic,'title':d.get('Titel',''),'description':d.get('Beschreibung',''),'timestamp':stamp,'duration':seconds,'size':size,
            'url_video':base,'url_video_hd':expand(d.get('Url HD',''),base),'url_video_low':expand(d.get('Url Klein',''),base),'url_subtitle':d.get('Url Untertitel',''),'url_website':d.get('Website',''),'geo':d.get('Geo',''),'catalog_source':'MediathekView-Filmliste'}
        # The standard public film list does not include expiry. Honour optional
        # explicit columns if a compatible feed ever provides them; do not infer.
        for label in ('Verfügbar bis','Verfuegbar bis','Ablaufdatum','availableUntil'):
            if label in d:
                import broadcaster
                until=broadcaster.expiry_iso(d[label])
                if until:offer.update(available_until=until,availability_source='Filmliste')
                break
        yield offer

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
