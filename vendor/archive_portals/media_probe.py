"""ArchiveMedia adaptive remote track inspection.

Container-index first; stage-limited ffprobe fallback. Every request is bounded,
remote downloads are never promoted to a complete-media verification.
Temporary sample bytes are removed after each probe.
"""
from __future__ import annotations
import json, math, os, re, shutil, subprocess, tempfile, threading, time, urllib.request, urllib.error
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit
from vendor.archivemedia.linguistics import normalize_language
from vendor.archive_portals import container_tracks

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_probe_jobs (
 variant_id INTEGER PRIMARY KEY REFERENCES variants(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 bytes_fetched INTEGER NOT NULL DEFAULT 0, method TEXT, detail TEXT,
 completed TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP,
 retry_count INTEGER NOT NULL DEFAULT 0, retry_priority INTEGER NOT NULL DEFAULT 0
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
class ParallelHttpGate:
    """Live-resizable limit for Archive.org range requests; never limits CPU work."""
    def __init__(self, limit=2):
        self._cond=threading.Condition()
        self._limit=int(limit)
        self._active=0
        self._waiting=0
        self._peak=0

    def set_limit(self, limit):
        with self._cond:
            self._limit=max(1,min(4,int(limit)))
            self._cond.notify_all()

    def stats(self):
        with self._cond:
            return {'limit':self._limit,'active':self._active,
                    'waiting':self._waiting,'peak':self._peak}

    def __enter__(self):
        with self._cond:
            self._waiting+=1
            try:
                while self._active>=self._limit:
                    self._cond.wait()
                self._active+=1
                self._peak=max(self._peak,self._active)
            finally:
                self._waiting-=1
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._cond:
            self._active-=1
            self._cond.notify_all()
        return False

NETWORK_SLOTS=ParallelHttpGate(2)
_FFPROBE_LOCK=threading.Lock()
_FFPROBE_ACTIVE=0
_FFPROBE_PEAK=0

def ffprobe_live_stats():
    with _FFPROBE_LOCK:
        return {'active':_FFPROBE_ACTIVE,'peak':_FFPROBE_PEAK}

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



# v0.10.22: retries of legacy failures are not an infinite loop. Existing
# evidence stays untouched; only indeterminate jobs can be scheduled again.
def ensure_retry_schema(c):
    existing={r['name'] if hasattr(r,'keys') else r[1] for r in c.execute('PRAGMA table_info(media_probe_jobs)')}
    if 'retry_count' not in existing:
        c.execute('ALTER TABLE media_probe_jobs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0')
    if 'retry_priority' not in existing:
        c.execute('ALTER TABLE media_probe_jobs ADD COLUMN retry_priority INTEGER NOT NULL DEFAULT 0')
    c.execute('CREATE INDEX IF NOT EXISTS ix_probe_retry ON media_probe_jobs(state,retry_priority,updated)')


def _retryable_sql():
    # 401/403 require external intervention. Re-running the same already
    # adaptive header read wastes user bandwidth and Archive.org resources.
    return """(
      (COALESCE(j.method,'') NOT LIKE '%adaptive%' AND
       (j.detail LIKE 'Kein vollständiger Spurheader%' OR
        j.detail LIKE 'Kein lesbarer Audio-/Untertitelheader%' OR
        j.detail LIKE 'Nur Videostream%'))
      OR j.detail LIKE 'HTTP 429:%' OR j.detail LIKE 'HTTP 500:%'
      OR j.detail LIKE 'HTTP 502:%' OR j.detail LIKE 'HTTP 503:%'
      OR j.detail LIKE 'HTTP 504:%' OR j.detail LIKE '%timed out%'
      OR j.detail LIKE '%TimeoutError%'
    )"""


def retry_failed_jobs(c,max_requeue=4,manual=False):
    """Requeue only historically unresolved, eligible originals.

    Automatic retries: one old-format attempt, or up to two attempts for
    transient HTTP/timeout errors, with a minimum 1-hour cooldown.
    Explicit retries permit up to 3 rechecks and are still bounded.
    Queue priority allows slow background progress even with many new jobs.
    """
    ensure_retry_schema(c)
    limit=max(1,min(250 if manual else 8,int(max_requeue)))
    cooldown='' if manual else "AND j.updated <= datetime('now','-1 hour')"
    manual_errors="""(j.detail LIKE 'Kein vollständiger Spurheader%'
      OR j.detail LIKE 'Kein lesbarer Audio-/Untertitelheader%'
      OR j.detail LIKE 'Nur Videostream%' OR j.detail LIKE '%nach adaptiver Probe%')"""
    policy='AND ('+_retryable_sql()+' OR '+manual_errors+')' if manual else 'AND '+_retryable_sql()
    sql=f"""SELECT j.variant_id FROM media_probe_jobs j
      JOIN variants v ON v.id=j.variant_id
      LEFT JOIN video_triage t ON t.group_id=v.group_id
      WHERE j.state='indeterminate' AND j.retry_count < ? AND j.attempts < 6
        AND COALESCE(t.category,'main')='main'
        AND j.detail NOT LIKE 'HTTP 401:%' AND j.detail NOT LIKE 'HTTP 403:%'
        AND j.detail NOT LIKE '%ignored HTTP Range%'
        AND j.detail NOT LIKE '%Unsafe redirect%'
        AND j.detail NOT LIKE '%file size changed%'
        AND j.detail NOT LIKE 'ffprobe unavailable'
        {cooldown} {policy}
      ORDER BY j.updated,j.variant_id LIMIT ?"""
    max_retries=3 if manual else 2
    ids=[r[0] for r in c.execute(sql,(max_retries,limit)).fetchall()]
    for vid in ids:
        c.execute("""UPDATE media_probe_jobs
          SET state='queued',retry_priority=1,retry_count=retry_count+1,
              updated=CURRENT_TIMESTAMP WHERE variant_id=? AND state='indeterminate' """,(vid,))
    return len(ids)


def retry_metrics(c):
    ensure_retry_schema(c)
    where=_retryable_sql()
    row=c.execute(f"""SELECT COUNT(*) FROM media_probe_jobs j
      JOIN variants v ON v.id=j.variant_id
      LEFT JOIN video_triage t ON t.group_id=v.group_id
      WHERE j.state='indeterminate' AND j.retry_count<2 AND j.attempts<6
        AND COALESCE(t.category,'main')='main' AND {where}""").fetchone()
    priority=c.execute("SELECT COUNT(*) FROM media_probe_jobs WHERE state='queued' AND retry_priority=1").fetchone()[0]
    previously=c.execute('SELECT COUNT(*) FROM media_probe_jobs WHERE retry_count>0').fetchone()[0]
    return {'eligible_failures':row[0], 'priority_queued':priority,'ever_retried':previously}

def can_probe(filename,source,byte_size,role):
    if Path(filename).suffix.lower() not in SUPPORTED:return False
    if str(source).lower() not in ('original',''):return False
    if str(role or '') in ('bdmv_stream','transport_segment','extra_or_clip','short_unknown'):return False
    return bool(byte_size and int(byte_size)>256*1024)


# v0.10.34: reference identity is separate from video validation.  Only
# high-quality work references or a manually confirmed work justify automatic
# paid-range probing. Metadata matching itself does not confirm an episode.
WORK_ELIGIBLE = """(
  COALESCE(g.match_state,'review')='confirmed' OR (
    NULLIF(TRIM(COALESCE(g.reference_id,'')),'') IS NOT NULL
    AND g.match_provider IN ('TMDB','TVmaze','AniList','manuell')
  )
)"""
NOT_OTHER = "COALESCE(t.category,'main')='main'"
DEFERRED_REASON = 'v0.10.34: Werk noch nicht identifiziert; Spuren auf Anfrage'


def _eligible(c,group_id):
    if not group_id:return False
    return bool(c.execute("""SELECT 1 FROM groups g LEFT JOIN video_triage t ON t.group_id=g.id
      WHERE g.id=? AND """+WORK_ELIGIBLE+" AND "+NOT_OTHER,(group_id,)).fetchone())


def schedule(c,item_id,max_per_item=2):
    """Queue a small number of *independent originals* from identified works.

    Technical helpers, huge unrecognized file collections and Archive.org
    transcodes remain indexed, but no network probe is started for them.
    """
    rows=c.execute("""SELECT v.id,v.filename,v.source,v.bytes,v.technical_role,
       v.group_id,COALESCE(v.variant_family,'') AS family
      FROM variants v WHERE v.item_id=? ORDER BY
       CASE WHEN lower(v.source)='original' THEN 0 ELSE 1 END,
       COALESCE(v.bytes,0) DESC LIMIT 250""",(item_id,)).fetchall()
    # Include existing probes: repeated imports must not increase the quota.
    present=c.execute('''SELECT COUNT(*) FROM media_probe_jobs j JOIN variants v
        ON v.id=j.variant_id WHERE v.item_id=? AND j.state IN
        ('queued','running','partial','indeterminate')''',(item_id,)).fetchone()[0]
    if present>=max_per_item:return 0
    added=0;families=set()
    for v in rows:
        if present+added>=max_per_item:break
        if not can_probe(v['filename'],v['source'],v['bytes'],v['technical_role']):continue
        if not _eligible(c,v['group_id']):continue
        family=v['family'] or str(v['id'])
        if family in families:continue
        families.add(family)
        c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES(?)',(v['id'],))
        if c.execute('SELECT changes()').fetchone()[0]:added+=1
        if added>=max_per_item:break
    return added



def schedule_group(c, group_id, max_per_item=2, max_items=24):
    """Schedule a bounded set of originals when a work acquires a real identity.

    Metadata enrichment runs in a single worker thread. Do not iterate the
    potentially unbounded number of uploads belonging to popular film titles
    while holding the SQLite write lock. The existing background backfill
    handles the remaining entries. The operation is idempotent and retains
    the per-upload two-original quota enforced by schedule().
    """
    if not _eligible(c,group_id):
        return 0
    limit=max(1,min(24,int(max_items)))
    item_ids=[row[0] for row in c.execute("SELECT DISTINCT item_id FROM variants WHERE group_id=? ORDER BY item_id LIMIT ?",(group_id,limit))]
    return sum(schedule(c,item_id,max_per_item=max_per_item) for item_id in item_ids)


def schedule_existing(c, batch_size=320, max_new=32):
    """Resume legacy inventory cursor, probing only identified work families."""
    row=c.execute("SELECT value FROM catalog_meta WHERE key='probe_backfill_cursor'").fetchone()
    cursor=int(row[0]) if row and str(row[0]).isdigit() else 0
    sample=c.execute("""SELECT v.id,v.item_id,v.filename,v.source,v.bytes,v.technical_role,v.group_id,
        COALESCE(v.variant_family,'') AS family
        FROM variants v WHERE v.id>? ORDER BY v.id LIMIT ?""",
        (cursor,max(10,min(2000,int(batch_size))))).fetchall()
    if not sample:return {'scanned':0,'enqueued':0,'cursor':cursor,'complete':True}
    added=0;seen=0;last=cursor;families=set();by_item={}
    for v in sample:
        last=int(v['id']);seen+=1
        if v['item_id'] not in by_item:
            by_item[v['item_id']]=c.execute('''SELECT COUNT(*) FROM media_probe_jobs j
                JOIN variants u ON u.id=j.variant_id WHERE u.item_id=? AND j.state IN
                ('queued','running','partial','indeterminate')''',(v['item_id'],)).fetchone()[0]
        if by_item[v['item_id']]>=2:continue
        family=v['family'] or str(v['id'])
        if family not in families and _eligible(c,v['group_id']) and can_probe(v['filename'],v['source'],v['bytes'],v['technical_role']):
            families.add(family)
            c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES(?)',(v['id'],))
            if c.execute('SELECT changes()').fetchone()[0]:
                added+=1;by_item[v['item_id']]+=1
        if added>=max_new:break
    c.execute("""INSERT INTO catalog_meta(key,value) VALUES('probe_backfill_cursor',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(str(last),))
    return {'scanned':seen,'enqueued':added,'cursor':last,'complete':False}


def backfill_identified(c, batch_size=320):
    """One-time historical scan with its own cursor; never rewind older jobs."""
    key='probe_identified_backfill_cursor_v34'
    row=c.execute('SELECT value FROM catalog_meta WHERE key=?',(key,)).fetchone()
    cursor=int(row[0]) if row and str(row[0]).isdigit() else 0
    sample=c.execute('''SELECT v.id,v.item_id,v.filename,v.source,v.bytes,v.technical_role,v.group_id
        FROM variants v WHERE v.id>? ORDER BY v.id LIMIT ?''',
        (cursor,max(20,min(2000,int(batch_size))))).fetchall()
    if not sample:return {'scanned':0,'enqueued':0,'complete':True}
    per_item={};added=0
    for v in sample:
        if _eligible(c,v['group_id']) and can_probe(v['filename'],v['source'],v['bytes'],v['technical_role']):
            item=v['item_id']
            if item not in per_item:
                per_item[item]=c.execute('''SELECT COUNT(*) FROM media_probe_jobs j
                    JOIN variants w ON w.id=j.variant_id
                    WHERE w.item_id=? AND j.state IN ('queued','running','partial','indeterminate')''',(item,)).fetchone()[0]
            if per_item[item]<2:
                c.execute('INSERT OR IGNORE INTO media_probe_jobs(variant_id) VALUES(?)',(v['id'],))
                if c.execute('SELECT changes()').fetchone()[0]:
                    added+=1;per_item[item]+=1
    c.execute('''INSERT INTO catalog_meta(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',(key,str(sample[-1]['id'])))
    return {'scanned':len(sample),'enqueued':added,'complete':False}


def queue_one(c,variant_id):
    """A real user request overrides automatic deferral, not a finished probe."""
    row=c.execute('SELECT id,filename,source,bytes,technical_role FROM variants WHERE id=?',(variant_id,)).fetchone()
    if not row or not can_probe(row['filename'],row['source'],row['bytes'],row['technical_role']):return False
    old=c.execute('SELECT state FROM media_probe_jobs WHERE variant_id=?',(variant_id,)).fetchone()
    if old and old['state'] in ('partial','running'):return False
    c.execute("""INSERT OR IGNORE INTO media_probe_jobs(variant_id,state,retry_priority)
        VALUES (?,'queued',2)""",(variant_id,))
    if old:
        c.execute("""UPDATE media_probe_jobs SET state='queued',retry_priority=2,
            detail='Manuell angefordert',updated=CURRENT_TIMESTAMP
            WHERE variant_id=? AND state IN ('deferred','indeterminate','queued')""",(variant_id,))
    return True


def defer_unidentified(c,limit=300):
    """Convert prior bulk queued jobs into resumable offline status.

    Never touch an active/finished job, manual or explicit retry priority,
    confirmed work, user downloads, original variant records or tracks.
    """
    ids=[r[0] for r in c.execute("""SELECT j.variant_id FROM media_probe_jobs j
        JOIN variants v ON v.id=j.variant_id
        LEFT JOIN groups g ON g.id=v.group_id
        LEFT JOIN video_triage t ON t.group_id=v.group_id
        WHERE j.state='queued' AND j.retry_priority=0
          AND (g.id IS NULL OR NOT """+WORK_ELIGIBLE+" OR NOT "+NOT_OTHER+""" )
        ORDER BY j.updated,j.variant_id LIMIT ?""",(limit,)).fetchall()]
    if ids:
        c.executemany("""UPDATE media_probe_jobs SET state='deferred',detail=?,updated=CURRENT_TIMESTAMP
              WHERE state='queued' AND retry_priority=0 AND variant_id=?""",[(DEFERRED_REASON,i) for i in ids])
    return len(ids)



def defer_excess_identified(c,limit=350):
    """Defer originals beyond two per upload from the legacy queue."""
    ids=[r[0] for r in c.execute("""SELECT variant_id FROM (
          SELECT j.variant_id,ROW_NUMBER() OVER (
             PARTITION BY v.item_id ORDER BY j.updated,j.variant_id) AS rank_in_upload
          FROM media_probe_jobs j JOIN variants v ON v.id=j.variant_id
          WHERE j.state='queued' AND j.retry_priority=0
        ) WHERE rank_in_upload>2 LIMIT ?""",(limit,)).fetchall()]
    if ids:
        c.executemany("""UPDATE media_probe_jobs SET state='deferred',detail=?,updated=CURRENT_TIMESTAMP
            WHERE variant_id=? AND state='queued' AND retry_priority=0""",
            [(DEFERRED_REASON,x) for x in ids])
    return len(ids)


def activate_identified(c,limit=32):
    """Resume only up to 2 automatic probes per upload when identity improves."""
    ids=[r[0] for r in c.execute('''SELECT j.variant_id FROM media_probe_jobs j
        JOIN variants v ON v.id=j.variant_id JOIN groups g ON g.id=v.group_id
        LEFT JOIN video_triage t ON t.group_id=v.group_id
        WHERE j.state='deferred' AND j.detail=? AND '''+WORK_ELIGIBLE+' AND '+NOT_OTHER+'''
        ORDER BY j.updated,j.variant_id LIMIT ?''',(DEFERRED_REASON,max(limit,120))).fetchall()]
    activated=0
    for vid in ids:
        row=c.execute('SELECT item_id FROM variants WHERE id=?',(vid,)).fetchone()
        if not row:continue
        active=c.execute('''SELECT COUNT(*) FROM media_probe_jobs j
          JOIN variants v ON v.id=j.variant_id WHERE v.item_id=?
          AND j.state IN ('queued','running','partial','indeterminate')''',(row['item_id'],)).fetchone()[0]
        if active>=2:continue
        c.execute('''UPDATE media_probe_jobs SET state='queued',detail=NULL,
          updated=CURRENT_TIMESTAMP WHERE variant_id=? AND state='deferred' AND detail=?''',(vid,DEFERRED_REASON))
        activated+=c.execute('SELECT changes()').fetchone()[0]
        if activated>=limit:break
    return activated


def claim(c,prefer_retry=False):
    # Fast manual/explicit retries, then recognised works. Never claim deferred.
    order='retry_priority DESC,updated,variant_id' if prefer_retry else 'retry_priority DESC,updated,variant_id'
    row=c.execute("SELECT variant_id FROM media_probe_jobs WHERE state='queued' ORDER BY "+order+' LIMIT 1').fetchone()
    if not row:return None
    c.execute("UPDATE media_probe_jobs SET state='running',retry_priority=0,attempts=attempts+1,updated=CURRENT_TIMESTAMP WHERE variant_id=?",(row[0],))
    return c.execute('SELECT v.id,v.item_id,v.filename,v.bytes FROM variants v WHERE v.id=?',(row[0],)).fetchone()


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


def fetch_range(url,start,count,fetcher=None,expected_total=None):
    """Fetch only an explicit Archive.org byte range, without full-object fallback.

    Validate the Content-Range and redirected hostname; never trust an unexpected
    200 response or download beyond the requested bytes. Full file size supplied
    by Archive.org must agree before mixing samples from different positions.
    """
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='archive.org':
        raise ValueError('Only HTTPS Archive.org downloads are allowed')
    start=int(start);count=int(count)
    if start<0 or count<=0 or count>2*1024*1024:
        raise ValueError('Invalid bounded range')
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{start+count-1}',
       'Accept-Encoding':'identity', 'User-Agent':'ArchiveMedia/0.10.17 bounded-metadata-probe'})
    opener=fetcher or urllib.request.urlopen
    with NETWORK_SLOTS:
        with opener(req,timeout=30) as resp:
            final=urlsplit(resp.geturl())
            host=(final.hostname or '').lower()
            if final.scheme!='https' or not (host=='archive.org' or host.endswith('.archive.org')):
                raise ValueError('Unsafe redirect host in remote probe')
            if resp.status!=206:raise ValueError('Remote server ignored HTTP Range')
            cr=resp.headers.get('Content-Range','')
            match=re.fullmatch(r'bytes\s+(\d+)-(\d+)/(\d+)',cr.strip())
            if not match:raise ValueError('Unreliable Content-Range')
            lo,hi,total=map(int,match.groups())
            if lo!=start or hi<lo or hi>=total or hi-lo+1>count:
                raise ValueError('Unexpected HTTP byte range')
            if expected_total is not None and total!=int(expected_total):
                raise ValueError('Archive.org file size changed; probe deferred')
            if resp.headers.get('Content-Encoding','identity').lower() not in ('identity',''):
                raise ValueError('Compressed HTTP response cannot be sampled')
            payload=resp.read(count+1)
            if len(payload)!=hi-lo+1:
                raise ValueError('Incomplete HTTP byte range')
            return payload


def fetch_prefix(url,byte_limit,fetcher=None):
    """Backward-compatible entry point for prefix-only inspection."""
    return fetch_range(url,0,byte_limit,fetcher)


def _ffprobe_sample(sample,ffprobe_binary):
    global _FFPROBE_ACTIVE, _FFPROBE_PEAK
    with _FFPROBE_LOCK:
        _FFPROBE_ACTIVE+=1
        _FFPROBE_PEAK=max(_FFPROBE_PEAK,_FFPROBE_ACTIVE)
    try:
        completed=subprocess.run([ffprobe_binary,'-v','error','-show_streams',
      '-probesize','4194304','-analyzeduration','3000000','-of','json',str(sample)],
      timeout=30,capture_output=True,text=True)
    finally:
        with _FFPROBE_LOCK:_FFPROBE_ACTIVE-=1
    tracks=parse_streams(completed.stdout) if completed.stdout.strip() else []
    raw=(completed.stderr or '').strip().splitlines()
    hint=re.sub(r'/[^\s:]+','<Pfad>',raw[-1])[:145] if raw else ''
    return tracks,hint


def progressive_targets(size, suffix, max_total_bytes=8*1024*1024):
    """Bandwidth-conscious progressive budgets, independent of remote file size.

    Prefer a short header first; expand only if no audio/subtitle evidence is
    readable. The last stage stays below the entire object size, and an
    explicit user cap is respected even for extremely large remote files.
    """
    size=int(size)
    if size<=0:raise ValueError('Invalid remote file size')
    cap=max(64*1024,min(16*1024*1024,int(max_total_bytes)))
    ceiling=max(1,min(size-1,cap))
    first=min(ceiling,sample_limit(size,max_bytes=512*1024))
    middle=min(ceiling,max(first,min(2*1024*1024,math.ceil(size*.05))))
    last=min(ceiling,max(middle,min(cap,math.ceil(size*.10))))
    return list(dict.fromkeys((first,middle,last)))


def inspect(url,filename,size,ffprobe_binary=None,fetcher=None,max_total_bytes=8*1024*1024):
    """Inspect up to three increasingly larger samples without redundant reads.

    For MP4/MOV the sample contains a prefix and tail. Each ffprobe run uses
    *local* sparse scratch data; the remote file is never downloaded whole.
    Multiple callers are safe: HTTP sampling uses the configurable network gate while
    separate local ffprobe processes may analyse their own samples in parallel.
    """
    size=int(size)
    if size<=0:raise ValueError('Invalid remote file size')
    suffix=Path(filename).suffix.lower()
    cap=max(64*1024,min(16*1024*1024,int(max_total_bytes)))
    header_bytes=0
    cached_ranges=[]
    def header_fetch(start,count):
        data=fetch_range(url,start,count,fetcher,expected_total=size)
        cached_ranges.append((start,data))
        return data
    def read_cached(start,count):
        """Reuse bytes already downloaded from the header, not bill them twice."""
        fresh=0;parts=[];end=start+count;pos=start
        while pos<end:
            hit=next(((offset,blob) for offset,blob in cached_ranges
                if offset<=pos<offset+len(blob)),None)
            if hit:
                off,blob=hit;n=min(end-pos,off+len(blob)-pos)
                parts.append(blob[pos-off:pos-off+n]);pos+=n
            else:
                upcoming=min((offset for offset,blob in cached_ranges if pos<offset<end),default=end)
                n=min(upcoming-pos,2*1024*1024)
                blob=header_fetch(pos,n)
                parts.append(blob);pos+=len(blob);fresh+=len(blob)
        return b''.join(parts),fresh
    # Container headers often describe every audio/subtitle track without media
    # payload. This path needs no ffprobe binary and costs 32-512 KiB typically.
    # Keep the old staged ffprobe fallback if no usable track header is found.
    if suffix in ('.mp4','.m4v','.mov','.mkv','.webm') and cap>=65536:
        callback=header_fetch
        if suffix in ('.mp4','.m4v','.mov'):
            index,header_bytes=container_tracks.probe_mp4(size,callback,cap)
        else:
            index,header_bytes=container_tracks.probe_mkv(size,callback,cap)
        if index and any(t['type'] in ('audio','subtitle') for t in index.tracks):
            return {'state':'partial','detail':index.detail,'tracks':index.tracks,
                    'bytes':index.bytes_read,'method':index.method,'evidence':index.tracks[0]['evidence'],
                    'probe_stage':1,'probe_stage_count':1}
    ffprobe_binary=resolve_ffprobe(ffprobe_binary)
    if not ffprobe_binary:
        return {'state':'indeterminate','detail':'ffprobe unavailable','bytes':header_bytes,'tracks':[]}
    # The header attempt participates in the *same* per-file byte budget.
    remaining=cap-header_bytes
    if remaining<64*1024:
        return {'state':'indeterminate','detail':'Containerindex unvollständig, Prüfbudget ausgeschöpft',
                'bytes':header_bytes,'tracks':[],'method':'Containerindex nicht lesbar'}
    has_tail=suffix in ('.mp4','.m4v','.mov') and size>256*1024
    total=header_bytes;prefix_done=0;tail_done=0;tracks=[];hint='';method='HTTP Range prefix + ffprobe'
    targets=progressive_targets(size,suffix,max_total_bytes=remaining)
    with tempfile.TemporaryDirectory(prefix='am-probe-') as tmp:
        sample=Path(tmp)/('partial'+(suffix if suffix in SUPPORTED else '.bin'))
        sample.touch()
        for stage,total_target in enumerate(targets,start=1):
            desired_prefix=(total_target+1)//2 if has_tail else total_target
            desired_tail=total_target-desired_prefix if has_tail else 0
            desired_prefix=min(size,desired_prefix)
            desired_tail=min(size-desired_prefix,desired_tail)
            try:
                with sample.open('r+b') as out:
                    while prefix_done<desired_prefix:
                        n=min(2*1024*1024,desired_prefix-prefix_done)
                        chunk,fresh=read_cached(prefix_done,n)
                        out.seek(prefix_done);out.write(chunk)
                        prefix_done+=len(chunk);total+=fresh
                    while tail_done<desired_tail:
                        n=min(2*1024*1024,desired_tail-tail_done)
                        offset=size-tail_done-n
                        chunk,fresh=read_cached(offset,n)
                        out.seek(offset);out.write(chunk)
                        tail_done+=len(chunk);total+=fresh
                    if tail_done:out.truncate(size)
                tracks,hint=_ffprobe_sample(sample,ffprobe_binary)
            except urllib.error.HTTPError:
                raise
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                hint=type(exc).__name__+': '+str(exc)[:110]
                break
            method=('HTTP Range prefix+tail + ffprobe' if tail_done else
                    'HTTP Range prefix + ffprobe')+f' Stufe {stage}/{len(targets)}, {total/1048576:.2f} MiB'
            if any(t.get('type') in ('audio','subtitle') for t in tracks):
                return {'state':'partial',
                    'detail':f'Teilspuren erkannt in Stufe {stage}; weitere Streams unbekannt',
                    'bytes':total,'tracks':tracks,'method':method,
                    'probe_stage':stage,'probe_stage_count':len(targets)}
        if tracks:
            detail='Nur Videostream im Teilbereich; Audio-/Untertitelspuren unbekannt'
        elif hint:
            detail='Kein lesbarer Audio-/Untertitelheader nach adaptiver Probe: '+hint
        else:
            detail='Kein vollständiger Spurheader trotz begrenzter adaptiver Probe'
        return {'state':'indeterminate','detail':detail[:250],'bytes':total,
                'tracks':tracks,'method':method,
                'probe_stage':len(targets),'probe_stage_count':len(targets)}


def save_result(c,vid,result):
    # Never overwrite the stronger ffprobe evidence obtained after full download.
    c.execute('DELETE FROM media_probe_tracks WHERE variant_id=?',(vid,))
    for track in result.get('tracks',[]):
        evidence=track.get('evidence') or result.get('evidence') or 'ffprobe-partial'
        c.execute("""INSERT INTO media_probe_tracks
          (variant_id,stream_index,stream_type,codec,language,title,flags_json,tags_json,evidence)
          VALUES (?,?,?,?,?,?,?,?,?)""",
          (vid,track['index'],track['type'],track['codec'],normalize_language(track['language']),track['title'],
           json.dumps(track['flags']),json.dumps(track['tags']),evidence))
    c.execute("""UPDATE media_probe_jobs SET state=?,detail=?,bytes_fetched=?,method=?,
       completed=CURRENT_TIMESTAMP,updated=CURRENT_TIMESTAMP WHERE variant_id=?""",
       (result['state'],result['detail'][:250],result['bytes'],result.get('method','HTTP Range prefix + ffprobe'),vid))


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
    tail_success=c.execute("SELECT COUNT(*) FROM media_probe_jobs WHERE state='partial' AND method LIKE 'HTTP Range prefix+tail%' ").fetchone()[0]
    container_index_success=c.execute("SELECT COUNT(*) FROM media_probe_jobs WHERE state='partial' AND method LIKE 'Containerindex %'").fetchone()[0]
    return {'states':counts,'retry':retry_metrics(c),'recent_error_reasons':errors,'last_completed':last,'audio_tracks':n,'subtitle_tracks':sub,'bytes_sampled':used,
      'bytes_last_24h':last24,'scheduled_variants':examined,'original_variants':original,
      'tail_success':tail_success,'container_index_success':container_index_success, 'backfill_cursor':int(cursor[0]) if cursor and str(cursor[0]).isdigit() else 0,
      'note':'Nur technische Hinweise aus Teilabrufen; nicht gleichbedeutend mit vollständigem Spurennachweis'}
