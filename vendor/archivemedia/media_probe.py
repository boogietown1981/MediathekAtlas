"""ArchiveMedia bounded remote track inspection.

Only a small prefix is fetched via HTTP Range. An incomplete sample can identify
positive stream-header tags, but cannot establish that tracks are absent.
No media bytes are kept after each attempt. Source-specific 429/503 pauses.
"""
from __future__ import annotations
import json, math, os, re, shutil, subprocess, tempfile, threading, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlsplit
from linguistics import normalize_language

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_probe_jobs (
 variant_id INTEGER PRIMARY KEY REFERENCES variants(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 bytes_fetched INTEGER NOT NULL DEFAULT 0, method TEXT, detail TEXT,
 completed TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_probe_state ON media_probe_jobs(state,updated);
CREATE TABLE IF NOT EXISTS media_probe_tracks (
 variant_id INTEGER NOT NULL REFERENCES variants(id) ON DELETE CASCADE,
 stream_index INTEGER NOT NULL, stream_type TEXT NOT NULL,
 codec TEXT, language TEXT, title TEXT,
 flags_json TEXT, tags_json TEXT, evidence TEXT NOT NULL DEFAULT 'ffprobe-partial',
 PRIMARY KEY(variant_id,stream_index)
);
"""
SUPPORTED={'.mkv','.mp4','.m4v','.mov','.webm','.avi','.mpg','.mpeg','.ogv','.ts','.m2ts','.flv'}
NETWORK_SLOTS=threading.BoundedSemaphore(2)
VALID_CODES=re.compile(r'^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8}){0,3}$')


def resolve_ffprobe(explicit=None):
    """Locate ffprobe in macOS GUI apps and Homebrew's keg-only ffmpeg-full.

    Do not change the global PATH, require manual symlinks, or invoke a shell.
    Returns an absolute executable path (or None). Recheck when called so an
    installation made after app startup is picked up automatically.
    """
    candidates=[]
    if explicit:candidates.append(os.path.expanduser(str(explicit)))
    if os.environ.get('ARCHIVEMEDIA_FFPROBE'):
        candidates.append(os.path.expanduser(os.environ['ARCHIVEMEDIA_FFPROBE']))
    for prefix in ('/opt/homebrew','/usr/local','/home/linuxbrew/.linuxbrew'):
        candidates.extend((prefix+'/opt/ffmpeg-full/bin/ffprobe',
                           prefix+'/opt/ffmpeg/bin/ffprobe',
                           prefix+'/bin/ffprobe'))
    normal=shutil.which('ffprobe')
    if normal:candidates.append(normal)
    # The usual paths are fast; only ask Homebrew when none is executable.
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate,os.X_OK):
            return str(Path(candidate).resolve())
    # Allow a custom Homebrew installation without relying on Finder's PATH.
    for brew in ('/opt/homebrew/bin/brew','/usr/local/bin/brew',shutil.which('brew')):
        if not brew or not os.path.isfile(brew):continue
        for formula in ('ffmpeg-full','ffmpeg'):
            try:
                out=subprocess.run([brew,'--prefix',formula],capture_output=True,
                      text=True,timeout=3)
                if out.returncode==0 and out.stdout.strip():
                    candidates.append(str(Path(out.stdout.strip())/'bin'/'ffprobe'))
            except (OSError,subprocess.TimeoutExpired):pass
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate,os.X_OK):
            return str(Path(candidate).resolve())
    return None


def tool_status():
    path=resolve_ffprobe()
    return {'available':bool(path),'path':path or '',
       'source':'Homebrew ffmpeg-full' if path and '/ffmpeg-full/' in path else ('ffprobe' if path else 'Nicht gefunden'),
       'suggestion':'' if path else 'Auf dem Mac ffprobe prüfen: "$(brew --prefix ffmpeg-full)/bin/ffprobe" -version'}


def retry_missing_tool_jobs(c,max_requeue=200):
    """Only release jobs that were skipped when ffprobe was unavailable."""
    if not resolve_ffprobe():return 0
    ids=[row[0] for row in c.execute("""SELECT variant_id FROM media_probe_jobs
       WHERE state='indeterminate' AND detail='ffprobe unavailable'
       ORDER BY updated LIMIT ?""",(max_requeue,))]
    for vid in ids:
        c.execute("UPDATE media_probe_jobs SET state='queued',detail='ffprobe now available',updated=CURRENT_TIMESTAMP WHERE variant_id=?",(vid,))
    return len(ids)


def can_probe(filename,source,byte_size,role):
    if Path(filename).suffix.lower() not in SUPPORTED:return False
    if str(source).lower() not in ('original',''):return False
    if str(role or '') in ('bdmv_stream','transport_segment','extra_or_clip','short_unknown'):return False
    return bool(byte_size and int(byte_size)>256*1024)


def schedule(c,item_id,max_per_item=24):
    # Prefer original source; no series/episode identity is inferred here.
    rows=c.execute("""SELECT v.id,v.filename,v.source,v.bytes,v.technical_role
      FROM variants v WHERE v.item_id=? ORDER BY
        CASE WHEN lower(v.source)='original' THEN 0 ELSE 1 END,
        COALESCE(v.bytes,0) DESC LIMIT 100""",(item_id,)).fetchall()
    count=0
    for v in rows:
        if not can_probe(v['filename'],v['source'],v['bytes'],v['technical_role']):continue
        c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES(?)',(v['id'],))
        count+=1
        if count>=max_per_item:break
    return count


def schedule_existing(c, batch_size=320, max_new=32):
    """Revisit older variant IDs once, without re-fetching their Archive.org upload.

    Cursor is persistent. New imports continue to be scheduled by schedule().
    A missing tool is handled by the caller; no items are downloaded here.
    """
    row=c.execute("SELECT value FROM catalog_meta WHERE key='probe_backfill_cursor'").fetchone()
    cursor=int(row[0]) if row and str(row[0]).isdigit() else 0
    sample=c.execute("""SELECT id,item_id,filename,source,bytes,technical_role
        FROM variants WHERE id>? ORDER BY id LIMIT ?""",(cursor,max(10,min(2000,int(batch_size))))).fetchall()
    if not sample:
        # End of historic inventory: future imports enqueue themselves.
        return {'scanned':0,'enqueued':0,'cursor':cursor,'complete':True}
    added=0;seen=0;last=cursor
    for v in sample:
        last=int(v['id']);seen+=1
        if can_probe(v['filename'],v['source'],v['bytes'],v['technical_role']):
            c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES (?)',(v['id'],))
            if c.execute('SELECT changes()').fetchone()[0]:added+=1
        if added>=max_new:break
    c.execute("""INSERT INTO catalog_meta(key,value) VALUES('probe_backfill_cursor',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(str(last),))
    return {'scanned':seen,'enqueued':added,'cursor':last,'complete':False}


def queue_one(c,variant_id):
    row=c.execute('SELECT id,filename,source,bytes,technical_role FROM variants WHERE id=?',(variant_id,)).fetchone()
    if not row or not can_probe(row['filename'],row['source'],row['bytes'],row['technical_role']):
        return False
    c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES(?)',(variant_id,))
    return True


def claim(c):
    # Recover interrupted jobs on startup separately, not inside each claim.
    row=c.execute("SELECT variant_id FROM media_probe_jobs WHERE state='queued' ORDER BY updated,variant_id LIMIT 1").fetchone()
    if not row:return None
    c.execute("UPDATE media_probe_jobs SET state='running',attempts=attempts+1,updated=CURRENT_TIMESTAMP WHERE variant_id=?",(row[0],))
    return c.execute("""SELECT v.id,v.item_id,v.filename,v.bytes FROM variants v WHERE v.id=?""",(row[0],)).fetchone()


def parse_streams(payload):
    parsed=json.loads(payload) if isinstance(payload,(bytes,str)) else payload
    if not isinstance(parsed,dict):raise ValueError('invalid ffprobe response')
    result=[]
    for stream in parsed.get('streams') or []:
        if not isinstance(stream,dict):continue
        typ=str(stream.get('codec_type') or '')
        if typ not in ('audio','subtitle','video'):continue
        tags=stream.get('tags') or {}
        if not isinstance(tags,dict):tags={}
        # Preserve all streams, even those without language labels.
        lang=str(next((v for k,v in tags.items() if k.casefold()=='language'),'') or '').strip().lower()
        if not VALID_CODES.fullmatch(lang) or lang in ('und','unk','mul','zxx'):
            lang=None
        lang=normalize_language(lang) if lang else None
        title=str(next((v for k,v in tags.items() if k.casefold() in ('title','handler_name')), '') or '')[:180]
        flags=stream.get('disposition') or {}
        if not isinstance(flags,dict):flags={}
        result.append({'index':int(stream.get('index',len(result))),'type':typ,
            'codec':str(stream.get('codec_name') or '')[:70], 'language':lang,'title':title,
            'flags':{k:bool(v) for k,v in flags.items() if v and k in ('default','forced','comment','hearing_impaired','visual_impaired','original','dub')},
            'tags':{k:str(v)[:180] for k,v in tags.items() if k.lower() in ('language','title','handler_name','language-ietf')}})
    return result


def sample_limit(size,max_bytes=2*1024*1024):
    # Roughly 2%, but small enough to keep the default low-bandwidth budget.
    return min(max_bytes,max(128*1024,int(int(size)*.02)))


def fetch_prefix(url,byte_limit,fetcher=None):
    """Require a valid 206 Partial Content response; reject 200 whole-object fallback."""
    if not urlsplit(url).hostname or urlsplit(url).hostname!='archive.org':
        raise ValueError('Only Archive.org downloads are allowed')
    req=urllib.request.Request(url,headers={'Range':f'bytes=0-{byte_limit-1}',
       'User-Agent':'ArchiveMedia/0.10.9 bounded-metadata-probe'})
    op=fetcher or urllib.request.urlopen
    with NETWORK_SLOTS:
        with op(req,timeout=30) as resp:
            final=urlsplit(resp.geturl())
            host=(final.hostname or '').lower()
            if final.scheme!='https' or not (host=='archive.org' or host.endswith('.archive.org')):
                raise ValueError('Unsafe redirect host in remote probe')
            if resp.status!=206:raise ValueError('Remote server ignored HTTP Range')
            cr=resp.headers.get('Content-Range','')
            if not re.match(r'^bytes 0-\d+/\d+$',cr):raise ValueError('Unreliable Content-Range')
            data=resp.read(byte_limit+1)
            if len(data)>byte_limit:raise ValueError('Range response larger than limit')
            return data


def inspect(url,filename,size,ffprobe_binary=None,fetcher=None):
    ffprobe_binary=resolve_ffprobe(ffprobe_binary)
    if not ffprobe_binary:
        return {'state':'indeterminate','detail':'ffprobe unavailable','bytes':0,'tracks':[]}
    limit=sample_limit(size)
    data=fetch_prefix(url,limit,fetcher=fetcher)
    # Suffix matters for FFmpeg demuxer probing; temporary sample never persistent.
    suffix=Path(filename).suffix.lower()
    with tempfile.TemporaryDirectory(prefix='am-probe-') as tmp:
        sample=Path(tmp)/('partial'+(suffix if suffix in SUPPORTED else '.bin'))
        sample.write_bytes(data)
        try:
            result=subprocess.run([ffprobe_binary,'-v','error','-show_streams',
              '-probesize',str(min(max(1048576,len(data)),4194304)),
              '-analyzeduration','3000000','-of','json',str(sample)],
              timeout=30,capture_output=True,text=True)
            tracks=parse_streams(result.stdout) if result.stdout.strip() else []
            useful=sum(t['type'] in ('audio','subtitle') for t in tracks)
            # A visible video track alone is not useful evidence of Dub/Sub.
            if useful:
                detail='Audio-/Untertitel-Streamheader aus Dateianfang; weitere Spuren nicht ausgeschlossen'
            elif tracks:
                detail='Nur Videostream im Teilausschnitt; Audio-/Untertitelspuren weiterhin unbekannt'
            else:
                raw=(result.stderr or '').strip().splitlines()
                hint=re.sub(r'/[^\s:]+','<Pfad>',raw[-1])[:145] if raw else ''
                detail='Kein lesbarer Audio-/Untertitelheader'+(': '+hint if hint else '')
            return {'state':'partial' if useful else 'indeterminate',
              'detail':detail,'bytes':len(data),'tracks':tracks}
        except (ValueError,subprocess.TimeoutExpired,OSError) as ex:
            return {'state':'indeterminate','detail':type(ex).__name__, 'bytes':len(data),'tracks':[]}


def save_result(c,vid,result):
    # Never overwrite the stronger ffprobe evidence obtained after full download.
    c.execute('DELETE FROM media_probe_tracks WHERE variant_id=?',(vid,))
    for track in result.get('tracks',[]):
        c.execute("""INSERT INTO media_probe_tracks
          (variant_id,stream_index,stream_type,codec,language,title,flags_json,tags_json)
          VALUES (?,?,?,?,?,?,?,?)""",
          (vid,track['index'],track['type'],track['codec'],normalize_language(track['language']),track['title'],
           json.dumps(track['flags']),json.dumps(track['tags'])))
    c.execute("""UPDATE media_probe_jobs SET state=?,detail=?,bytes_fetched=?,method='HTTP Range + ffprobe',
       completed=CURRENT_TIMESTAMP,updated=CURRENT_TIMESTAMP WHERE variant_id=?""",
       (result['state'],result['detail'][:250],result['bytes'],vid))


def metrics(c):
    counts={r[0]:r[1] for r in c.execute('SELECT state,COUNT(*) FROM media_probe_jobs GROUP BY state')}
    n=c.execute("SELECT COUNT(*) FROM media_probe_tracks WHERE stream_type='audio'").fetchone()[0]
    sub=c.execute("SELECT COUNT(*) FROM media_probe_tracks WHERE stream_type='subtitle'").fetchone()[0]
    used=c.execute("SELECT COALESCE(SUM(bytes_fetched),0) FROM media_probe_jobs").fetchone()[0]
    last24=c.execute("SELECT COALESCE(SUM(bytes_fetched),0) FROM media_probe_jobs WHERE completed>=datetime('now','-1 day')").fetchone()[0]
    cursor=c.execute("SELECT value FROM catalog_meta WHERE key='probe_backfill_cursor'").fetchone()
    original=c.execute("SELECT COUNT(*) FROM variants WHERE lower(COALESCE(source,''))='original'").fetchone()[0]
    examined=c.execute("SELECT COUNT(*) FROM media_probe_jobs").fetchone()[0]
    errors={r[0] or 'Unbekannt':r[1] for r in c.execute("SELECT COALESCE(detail,'Unbekannt'),COUNT(*) FROM media_probe_jobs WHERE state='indeterminate' GROUP BY COALESCE(detail,'Unbekannt') ORDER BY COUNT(*) DESC LIMIT 6")}
    last=c.execute("SELECT MAX(completed) FROM media_probe_jobs WHERE state IN ('partial','indeterminate')").fetchone()[0]
    return {'states':counts,'recent_error_reasons':errors,'last_completed':last,'audio_tracks':n,'subtitle_tracks':sub,'bytes_sampled':used,
      'bytes_last_24h':last24,'scheduled_variants':examined,'original_variants':original,
      'backfill_cursor':int(cursor[0]) if cursor and str(cursor[0]).isdigit() else 0,
      'note':'Nur technische Hinweise aus Teilabrufen; nicht gleichbedeutend mit vollständigem Spurennachweis'}
