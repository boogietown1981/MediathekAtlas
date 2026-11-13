"""Conservative Blu-ray MPLS manifest parser and bounded archive retrieval.

PlayItems establish clip ordering and authored in/out times but do NOT prove
movie, series episode, audio language, or completeness. No DRM bypass.
"""
from __future__ import annotations
import re, struct, urllib.parse, urllib.request

MAX_PLAYLIST_BYTES=256*1024

class PlaylistError(ValueError):pass

def _u16(data,off):
    if off < 0 or off+2>len(data):raise PlaylistError('Truncated MPLS uint16')
    return struct.unpack_from('>H',data,off)[0]
def _u32(data,off):
    if off < 0 or off+4>len(data):raise PlaylistError('Truncated MPLS uint32')
    return struct.unpack_from('>I',data,off)[0]

def parse_mpls(data):
    if not isinstance(data,bytes) or len(data)>MAX_PLAYLIST_BYTES or len(data)<40:
        raise PlaylistError('MPLS-Datei zu groß, zu klein oder ungültig')
    if data[:4]!=b'MPLS' or data[4:8] not in (b'0100',b'0200',b'0240',b'0300'):
        raise PlaylistError('Kein unterstützter Blu-ray-MPLS-Header')
    start=_u32(data,8)
    if start<40 or start+10>len(data):raise PlaylistError('Ungültige Playlist-Adresse')
    section_length=_u32(data,start)
    end=start+4+section_length
    if end>len(data) or section_length<6:raise PlaylistError('Ungültige Playlist-Länge')
    number=_u16(data,start+6)
    if number>4096:raise PlaylistError('Zu viele Playlist-Einträge')
    pos=start+10
    clips=[]
    for _ in range(number):
        if pos+2>end:raise PlaylistError('PlayItem abgeschnitten')
        n=_u16(data,pos)
        pos+=2
        if n<20 or pos+n>end:raise PlaylistError('Ungültige PlayItem-Länge')
        block=data[pos:pos+n]
        pos+=n
        clip=block[:5].decode('ascii','replace')
        codec=block[5:9]
        if not re.fullmatch(r'[0-9]{5}',clip) or codec!=b'M2TS':
            raise PlaylistError('Ungültiger Clip-Identifier oder Codec')
        # Item offsets are relative to the bytes AFTER the u16 length field.
        start_tick=_u32(block,12)
        end_tick=_u32(block,16)
        if end_tick<start_tick:raise PlaylistError('Playlist enthält negative Laufzeit')
        seconds=(end_tick-start_tick)/45000.0
        if seconds>86400:raise PlaylistError('Unplausibel langer PlayItem')
        clips.append({'clip_id':clip,'filename':clip+'.m2ts',
                      'start_seconds':round(start_tick/45000,3),
                      'end_seconds':round(end_tick/45000,3),
                      'duration_seconds':round(seconds,3)})
    return {'format':'MPLS','version':data[4:8].decode('ascii'),
            'clips':clips,'play_items':len(clips),
            'duration_seconds':round(sum(c['duration_seconds'] for c in clips),3),
            'is_multi_clip':len(clips)>1,
            'warning':'Eine Blu-ray-Playlist ist keine bestätigte Serie/Folge oder Sprachfassung.'}

class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u=urllib.parse.urlparse(newurl)
        if u.scheme!='https' or not (u.hostname=='archive.org' or (u.hostname or '').endswith('.archive.org')):
            raise PlaylistError('Weiterleitung außerhalb Archive.org abgelehnt')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def get_archive_playlist(identifier,filename,declared_size=None,timeout=18):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,130}',str(identifier)):
        raise PlaylistError('Ungültiger Archive-Identifier')
    filename=str(filename).replace('\\','/')
    if not filename.lower().endswith('.mpls') or '\x00' in filename or any(p in ('','..','.') for p in filename.split('/')):
        raise PlaylistError('Unsicherer Playlist-Dateipfad')
    if declared_size is not None and int(declared_size)>MAX_PLAYLIST_BYTES:
        raise PlaylistError('Playlist über Downloadlimit')
    url='https://archive.org/download/'+urllib.parse.quote(identifier,safe='')+'/'+urllib.parse.quote(filename,safe='/')
    opener=urllib.request.build_opener(_RestrictedRedirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'ArchiveMedia/0.9.5 (playlist metadata only)'}),timeout=timeout) as stream:
        raw=stream.read(MAX_PLAYLIST_BYTES+1)
    return parse_mpls(raw)
