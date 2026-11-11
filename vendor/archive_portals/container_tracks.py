"""Small, bounded, read-only container-index probes for remote media.

Never download or decode media frames. Every callback fetches a strict HTTP Range;
callers enforce the archive.org URL/redirect and Content-Range policy.
Results identify *declared* tracks, not decoded speech or burned-in captions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class IndexResult:
    tracks: list
    bytes_read: int
    method: str
    detail: str


def _atoms(data: bytes, start=0, end=None):
    end=len(data) if end is None else min(end,len(data))
    at=start
    while at+8<=end:
        size=int.from_bytes(data[at:at+4],'big')
        kind=data[at+4:at+8]
        header=8
        if size==1:
            if at+16>end:return
            size=int.from_bytes(data[at+8:at+16],'big');header=16
        elif size==0:size=end-at
        if size<header or at+size>end:return
        yield kind,data[at+header:at+size]
        at+=size


def _first_atom(data,kind):
    return next((payload for typ,payload in _atoms(data) if typ==kind),None)


def _mp4_language(payload):
    if len(payload)<24:return None
    offset=32 if payload[0]==1 else 20
    if len(payload)<offset+2:return None
    code=int.from_bytes(payload[offset:offset+2],'big')
    if not code or code==0x7fff:return None
    chars=[(code>>shift)&31 for shift in (10,5,0)]
    if any(not 1<=x<=26 for x in chars):return None
    lang=''.join(chr(96+x) for x in chars)
    # ISO-639-2 language in mdhd. Canonicalise through app's existing table.
    from linguistics import normalize_language
    result=normalize_language(lang)
    return result if result not in ('und','unk','mul','zxx') else None


def mp4_tracks(moov:bytes):
    """Read sample-entry codecs and per-track language from one complete moov.

    moov here is the *payload* of the atom, not an arbitrary sparse MP4 chunk.
    """
    tracks=[]
    for trak in (p for k,p in _atoms(moov) if k==b'trak'):
        mdia=_first_atom(trak,b'mdia')
        if mdia is None:continue
        hdlr=_first_atom(mdia,b'hdlr')
        if not hdlr or len(hdlr)<12:continue
        handler=hdlr[8:12]
        typ={b'soun':'audio',b'vide':'video',b'text':'subtitle',
             b'subt':'subtitle',b'sbtl':'subtitle',b'clcp':'subtitle'}.get(handler)
        if not typ:continue
        mdhd=_first_atom(mdia,b'mdhd') or b''
        minf=_first_atom(mdia,b'minf')
        stbl=_first_atom(minf,b'stbl') if minf is not None else None
        stsd=_first_atom(stbl,b'stsd') if stbl is not None else None
        codec=''
        if stsd is not None and len(stsd)>=16 and int.from_bytes(stsd[4:8],'big')>0:
            codec=stsd[12:16].decode('ascii','replace').strip()
        tracks.append({'index':len(tracks),'type':typ,'codec':codec,
                       'language':_mp4_language(mdhd),'title':'','flags':{},'tags':{},
                       'evidence':'container-index/mp4'})
    return tracks


def probe_mp4(size:int,fetch:Callable[[int,int],bytes],max_bytes:int):
    """Seek straight over an mdat atom to its moov, even for tail-indexed MP4s.

    Network cost: one small header read and at most one bounded moov read,
    plus <=16-byte reads if the next top-level atom is outside the prefix.
    """
    if size<32 or max_bytes<96:return None,0
    total=0
    def take(offset,length):
        nonlocal total
        if offset<0 or length<=0 or offset+length>size or total+length>max_bytes:return b''
        data=fetch(offset,length)
        total+=len(data)
        return data
    prefix=take(0,min(32*1024,max(16,size//4),max_bytes//2))
    if len(prefix)<16:return None,total
    offset=0
    for _ in range(48):
        header=prefix[offset:offset+16] if offset+16<=len(prefix) else take(offset,min(16,size-offset))
        if len(header)<8:break
        length=int.from_bytes(header[:4],'big');kind=header[4:8];header_len=8
        if length==1:
            if len(header)<16:break
            length=int.from_bytes(header[8:16],'big');header_len=16
        elif length==0:length=size-offset
        if length<header_len or offset+length>size:break
        if kind==b'moov':
            # If full header is already cached, do not download it again.
            if offset+length<=len(prefix):blob=prefix[offset:offset+length]
            elif length<=max_bytes-total:blob=take(offset,length)
            else:break
            if len(blob)!=length:break
            tracks=mp4_tracks(blob[header_len:])
            if tracks:
                return IndexResult(tracks,total,'Containerindex MP4/MOV (HTTP Range)',
                    'Vollständiger moov-Trackindex; Dekodierbarkeit und eingebrannte Untertitel nicht geprüft'),total
            break
        offset+=length
        if offset>=size:break
    return None,total


def _vint(data,at,identifier=False):
    if at>=len(data):return None
    byte=data[at];mask=128;width=1
    while width<=8 and not byte&mask:
        mask>>=1;width+=1
    if width>8 or (identifier and width>4) or at+width>len(data):return None
    value=int.from_bytes(data[at:at+width],'big')
    if not identifier:
        value &= (1<<(7*width))-1
        if value==(1<<(7*width))-1:value=None # unknown-size segment
    return value,width


def _elements(data,start=0,end=None):
    end=len(data) if end is None else min(end,len(data));at=start
    while at<end:
        ident=_vint(data,at,True)
        if not ident:break
        ident_val,iw=ident
        sz=_vint(data,at+iw)
        if not sz:break
        length,sw=sz;begin=at+iw+sw
        if length is None:length=end-begin
        if length<0:break
        if begin+length>end:
            # Top-level Segment can span gigabytes; only its *available* prefix
            # is inspected, never claim a complete Tracks element from truncation.
            if ident_val==0x18538067:length=end-begin
            else:break
        yield ident_val,data[begin:begin+length]
        at=begin+length


def _element(data,kind):
    return next((p for k,p in _elements(data) if k==kind),None)


def _uint(data):return int.from_bytes(data,'big') if data else 0


def mkv_tracks(data:bytes):
    """Read Matroska TrackEntry elements that fit entirely in an early header."""
    segment=_element(data,0x18538067)
    if segment is None:return []
    entries=_element(segment,0x1654AE6B)
    if entries is None:return []
    from linguistics import normalize_language
    tracks=[]
    for kind,entry in _elements(entries):
        if kind!=0xAE:continue
        t={kind:val for kind,val in _elements(entry)}
        typ={1:'video',2:'audio',17:'subtitle'}.get(_uint(t.get(0x83,b'')))
        if not typ:continue
        code=(t.get(0x22B59D) or t.get(0x22B59C) or b'').decode('utf-8','replace').strip()
        lang=normalize_language(code) if code else None
        # 'und' and 'unk' don't establish the spoken language.
        if lang in ('und','unk','mul','zxx'):lang=None
        title=t.get(0x536E,b'').decode('utf-8','replace')[:180]
        codec=t.get(0x86,b'').decode('ascii','replace')[:70]
        flags={}
        if 0x88 in t and _uint(t[0x88]):flags['default']=True
        if 0x55AA in t and _uint(t[0x55AA]):flags['forced']=True
        tracks.append({'index':len(tracks),'type':typ,'codec':codec,
            'language':lang,'title':title,'flags':flags,'tags':{},
            'evidence':'container-index/matroska'})
    return tracks


def probe_mkv(size:int,fetch:Callable[[int,int],bytes],max_bytes:int):
    """Try only one small prefix for Matroska's early Tracks header."""
    if size<64 or max_bytes<4096:return None,0
    length=min(max(4096,size//4),128*1024,max_bytes//2,size-1)
    payload=fetch(0,length)
    tracks=mkv_tracks(payload)
    if tracks:
        return IndexResult(tracks,len(payload),'Containerindex Matroska (HTTP Range)',
            'TrackEntry-Header erkannt; spätere zusätzliche Tracks nicht ausgeschlossen'),len(payload)
    return None,len(payload)
