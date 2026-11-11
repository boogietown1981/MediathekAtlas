"""Explicitly authorised direct-file downloads linked to Netzkino catalogue items.

Netzkino's AVOD/Plus streams are NOT download grants. This module neither
extracts player/manifest URLs nor bypasses ads, DRM, access controls or geo
restrictions. Only a separately licensed, user-supplied HTTPS direct file from
an independent authorised distributor can be queued; rights are user-asserted,
not independently verified. Separate SQLite and output folder; existing
MediathekAtlas/ArchiveMedia queues remain untouched.
"""
from __future__ import annotations

import contextlib
import ipaddress
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_BYTES = 16 * 1024 ** 3  # bounded 16 GiB per permitted direct file
CHUNK = 256 * 1024
EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov'}
MIME_TYPES = {'video/mp4', 'video/x-matroska', 'video/webm', 'video/quicktime',
              'application/octet-stream'}
STATES = {'queued', 'running', 'paused', 'complete', 'error', 'cancelled'}
RIGHTS = {'rights_holder', 'written_permission', 'public_domain'}
ID_RE = re.compile(r'^[0-9a-f]{32}$')
_LOCK = threading.Lock()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS licensed_netzkino_downloads (
 id TEXT PRIMARY KEY, netzkino_id TEXT NOT NULL, title TEXT NOT NULL,
 source_url TEXT NOT NULL, rights_basis TEXT NOT NULL, rights_note TEXT NOT NULL,
 target_name TEXT NOT NULL, state TEXT NOT NULL, bytes_done INTEGER NOT NULL DEFAULT 0,
 bytes_total INTEGER NOT NULL DEFAULT 0, etag TEXT NOT NULL DEFAULT '',
 last_modified TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
 created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_nk_license_state ON licensed_netzkino_downloads(state,created);
'''


def _connect_raw(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'netzkino_licensed_downloads.sqlite3'
    c = sqlite3.connect(str(path), timeout=8)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    if os.name != 'nt':
        try: os.chmod(path, 0o600)
        except OSError: pass
    return c


@contextlib.contextmanager
def _conn(root):
    c=_connect_raw(root)
    try:
        with c:yield c
    finally:c.close()


def initialize(root):
    """Recover a previously interrupted worker without discarding progress."""
    with _conn(root) as c:
        c.execute("UPDATE licensed_netzkino_downloads SET state='queued' WHERE state='running'")


def _safe_host(host):
    h = (host or '').lower().rstrip('.')
    if not h or len(h) > 240 or '.' not in h or h.endswith(('.local', '.internal', '.test', '.localhost')):
        raise ValueError('Nur öffentliche HTTPS-Downloadserver sind erlaubt')
    # Public Netzkino playback/CDN endpoints must not be converted to files.
    if any(h == name or h.endswith('.' + name) for name in
           ('netzkino.de', 'pluto.tv', 'tubitv.com', 'netzkino-seite.netzkino.de')):
        raise ValueError('Streaming-Anbieteradressen sind keine Downloadfreigabe')
    try:
        address = ipaddress.ip_address(h.strip('[]'))
    except ValueError:
        address = None
    if address is not None:
        raise ValueError('Direkte IP-Adressen sind nicht gestattet')
    if not re.fullmatch(r'[a-z0-9.-]+', h) or '..' in h:
        raise ValueError('Ungültiger Downloadserver')
    return h


def direct_url(value):
    if not isinstance(value, str) or not (15 <= len(value) <= 1200):
        raise ValueError('Berechtigten direkten Datei-Link angeben')
    try: p = urllib.parse.urlsplit(value)
    except ValueError: raise ValueError('Ungültige Datei-Adresse') from None
    if (p.scheme != 'https' or p.port not in (None,443) or p.username or p.password
            or p.query or p.fragment or '\\' in p.path or '%' in p.path):
        raise ValueError('Nur HTTPS-Dateilinks ohne Zugangstoken, Parameter oder Umleitungen')
    _safe_host(p.hostname)
    suffix = Path(p.path).suffix.lower()
    if suffix not in EXTENSIONS or not p.path.startswith('/'):
        raise ValueError('Nur explizite MP4/MKV/WebM/MOV-Dateien; keine Streaming-Playlists')
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, '', ''))


def _resolve_public(host):
    """Block local/private DNS destinations. This is an additional, not sole SSRF guard."""
    try: addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError: raise ValueError('Downloadserver kann nicht aufgelöst werden') from None
    if not addresses: raise ValueError('Downloadserver ist nicht erreichbar')
    for entry in addresses:
        ip = ipaddress.ip_address(entry[4][0])
        if not ip.is_global:
            raise ValueError('Private oder reservierte Downloadserver sind gesperrt')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('Weiterleitungen sind nicht freigegeben')


def _open(req):
    _resolve_public(urllib.parse.urlsplit(req.full_url).hostname)
    # No system proxy to private destinations; no cookies/credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(req, timeout=25)


def _safe_title(title):
    value = re.sub(r'[\\/<>:"|?*\x00-\x1f]+', ' ', str(title or 'Netzkino'))
    value = ' '.join(value.split()).strip(' .')[:120]
    return value or 'Netzkino'


def _source_item(root, netzkino_id):
    if not ID_RE.fullmatch(str(netzkino_id or '')):
        raise ValueError('Ungültige Netzkino-Katalogkennung')
    import netzkino
    c=netzkino._connect(root)
    try:
        found=c.execute('SELECT title,year FROM netzkino_catalog WHERE id=?', (netzkino_id,)).fetchone()
        if not found:
            found=c.execute('SELECT title,NULL AS year FROM netzkino_links WHERE id=?', (netzkino_id,)).fetchone()
        if not found: raise ValueError('Netzkino-Titel ist nicht im lokalen Katalog vorhanden')
        return str(found['title']), found['year']
    finally: c.close()


def enqueue(root, netzkino_id, file_url, rights_basis, rights_note, confirmed=False):
    if confirmed is not True:
        raise ValueError('Ausdrückliche Bestätigung der gesonderten Downloadberechtigung erforderlich')
    if rights_basis not in RIGHTS:
        raise ValueError('Art der separaten Downloadberechtigung fehlt')
    note = ' '.join(str(rights_note or '').split())
    if len(note) < 24 or len(note) > 600:
        raise ValueError('Konkrete Rechtequelle/Freigabe dokumentieren (mindestens 24 Zeichen)')
    url = direct_url(file_url)
    title, year = _source_item(root, netzkino_id)
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    filename = f'{_safe_title(title)}{(" (" + str(year) + ")") if year else ""} [NK-{netzkino_id[:10]}]{ext}'
    now = time.time(); job_id = uuid.uuid4().hex
    with _conn(root) as c:
        existing = c.execute('''SELECT id FROM licensed_netzkino_downloads
            WHERE netzkino_id=? AND source_url=? AND state IN ('queued','running','paused','complete')''',
            (netzkino_id,url)).fetchone()
        if existing: return {'id':existing['id'],'created':False}
        c.execute('''INSERT INTO licensed_netzkino_downloads (
            id,netzkino_id,title,source_url,rights_basis,rights_note,target_name,state,created,updated)
            VALUES(?,?,?,?,?,?,?, 'queued',?,?)''',
            (job_id,netzkino_id,title,url,rights_basis,note,filename,now,now))
    return {'id':job_id,'created':True}


def _public(r):
    keys = ('id','netzkino_id','title','target_name','state','bytes_done','bytes_total','error_code','created','updated')
    return {k:r[k] for k in keys}


def listing(root, limit=50):
    with _conn(root) as c:
        rows=c.execute('''SELECT * FROM licensed_netzkino_downloads ORDER BY created DESC LIMIT ?''',
                       (min(100,max(1,int(limit))),)).fetchall()
    return {'items':[_public(r) for r in rows],
            'policy':'Nur separat berechtigte, explizite Direktdateien. Netzkino-Playerstreams sind nicht freigegeben.',
            'automatic_netzkino_downloads':False}


def summary(root):
    with _conn(root) as c:
        counts={str(s):int(n) for s,n in c.execute('''SELECT state,COUNT(*) FROM licensed_netzkino_downloads GROUP BY state''')}
    return {k:counts.get(k,0) for k in ('queued','running','paused','complete','error','cancelled')}


def action(root, job_id, mode, output=None):
    if not ID_RE.fullmatch(str(job_id or '')):
        raise ValueError('Ungültige Auftragskennung')
    now = time.time()
    with _conn(root) as c:
        found=c.execute('SELECT state,target_name FROM licensed_netzkino_downloads WHERE id=?',(job_id,)).fetchone()
        if not found: raise ValueError('Downloadauftrag nicht vorhanden')
        state=found['state']
        if mode=='pause' and state in ('queued','running'):
            c.execute('UPDATE licensed_netzkino_downloads SET state=?,updated=? WHERE id=?',('paused',now,job_id))
        elif mode=='resume' and state in ('paused','error'):
            c.execute('''UPDATE licensed_netzkino_downloads SET state='queued',error_code='',updated=? WHERE id=?''',(now,job_id))
        elif mode=='cancel' and state in ('queued','running','paused','error'):
            c.execute("UPDATE licensed_netzkino_downloads SET state='cancelled',updated=? WHERE id=?",(now,job_id))
            # Running worker closes the file before removal; never unlink it here.
            if output is not None and state!='running':
                part=Path(output)/(found['target_name']+'.part')
                if part.is_file() and not part.is_symlink():part.unlink()
        elif mode=='pause' and state=='paused' or mode=='resume' and state=='queued':pass
        else: raise ValueError('Für diesen Auftrag unzulässige Aktion')
    return {'ok':True,'state':{'pause':'paused','resume':'queued','cancel':'cancelled'}[mode]}


def _state(root, job_id):
    with _conn(root) as c:
        r=c.execute('SELECT state FROM licensed_netzkino_downloads WHERE id=?',(job_id,)).fetchone()
    return r['state'] if r else 'paused'


def _update(root, job_id, **fields):
    allowed={'state','bytes_done','bytes_total','etag','last_modified','error_code'}
    fields={k:v for k,v in fields.items() if k in allowed}
    fields['updated']=time.time()
    with _conn(root) as c:
        c.execute('UPDATE licensed_netzkino_downloads SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',
                  (*fields.values(),job_id))


def _claim(root):
    with _conn(root) as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM licensed_netzkino_downloads WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        if row:c.execute("UPDATE licensed_netzkino_downloads SET state='running',updated=? WHERE id=?",(time.time(),row['id']))
    return dict(row) if row else None


def _download(root, output, job, *, opener=None, progress=None):
    """Download one explicitly permitted file. Caller owns state transitions."""
    path=direct_url(job['source_url'])
    suffix=Path(job['target_name']).suffix.lower()
    if suffix not in EXTENSIONS or Path(job['target_name']).name != job['target_name']:
        raise ValueError('Ungültiger Zieldateiname')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    if output.is_symlink(): raise ValueError('Ausgabeverzeichnis ist ein Symlink')
    final=output/job['target_name'];partial=output/(job['target_name']+'.part')
    if final.exists() or final.is_symlink(): raise FileExistsError('Zieldatei existiert bereits; kein Überschreiben')
    if partial.is_symlink(): raise ValueError('Part-Datei ist ein Symlink')
    current=partial.stat().st_size if partial.exists() else 0
    if current>MAX_BYTES:raise ValueError('Teil-Datei überschreitet das Größenlimit')
    headers={'User-Agent':'MediathekAtlas-LicensedDownload/1', 'Accept':'video/mp4,video/webm,video/*;q=0.5'}
    if current and not (job.get('etag') or job.get('last_modified')):
        raise ValueError('Keine sichere Wiederaufnahme ohne ETag/Last-Modified')
    if current:
        headers['Range']=f'bytes={current}-'
        if job.get('etag'):headers['If-Range']=job['etag']
        elif job.get('last_modified'):headers['If-Range']=job['last_modified']
    req=urllib.request.Request(path,headers=headers)
    opener=opener or _open
    with opener(req) as response:
        status=getattr(response,'status',None)
        if status is None:status=response.getcode()
        if current and status!=206: raise ValueError('Server unterstützt sichere Wiederaufnahme nicht')
        if not current and status!=200:raise ValueError('Unerwartete HTTP-Antwort')
        mime=str(response.headers.get('Content-Type') or '').split(';',1)[0].strip().lower()
        if mime not in MIME_TYPES:raise ValueError('Anbieter liefert keine direkte Videodatei')
        content_length=response.headers.get('Content-Length')
        try:length=int(content_length) if content_length is not None else None
        except (ValueError,TypeError):raise ValueError('Ungültige Content-Length') from None
        if length is None or length < 0 or current+length>MAX_BYTES:
            raise ValueError('Dateigröße unbekannt oder außerhalb des Limits')
        if current:
            cr=str(response.headers.get('Content-Range') or '')
            m=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',cr)
            if not m or int(m[1])!=current or int(m[3])!=current+length:
                raise ValueError('Ungültiger HTTP-Range-Nachweis')
            if job.get('etag') and response.headers.get('ETag') and response.headers.get('ETag')!=job['etag']:
                raise ValueError('Dateiquelle hat sich seit Beginn geändert')
        total=current+length
        _update(root,job['id'],bytes_total=total,etag=response.headers.get('ETag') or job.get('etag') or '',
                last_modified=response.headers.get('Last-Modified') or job.get('last_modified') or '')
        fd=os.open(partial, os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|(os.O_APPEND if current else os.O_TRUNC),0o600)
        written=current;last_report=0;last_state_check=0
        try:
            with os.fdopen(fd,'ab' if current else 'wb') as target:
                while True:
                    if time.monotonic()-last_state_check>.4:
                        if _state(root,job['id'])!='running':return 'paused'
                        last_state_check=time.monotonic()
                    chunk=response.read(min(CHUNK,total-written)) if written<total else b''
                    if not chunk: break
                    target.write(chunk)
                    written+=len(chunk)
                    if written>total:raise ValueError('Antwort länger als gemeldete Dateigröße')
                    if time.monotonic()-last_report>.5:
                        _update(root,job['id'],bytes_done=written)
                        if progress:progress(written,total)
                        last_report=time.monotonic()
                target.flush();os.fsync(target.fileno())
        finally:_update(root,job['id'],bytes_done=written)
        if written!=total:raise IOError('Datei unvollständig; wird fortgesetzt')
        if _state(root,job['id'])!='running':return 'paused'
        # Atomic no-overwrite publish: never replace a pre-existing user's file.
        os.link(partial, final, follow_symlinks=False)
        partial.unlink()
        return 'complete'


def _work_one(root, output, job, *, opener=None):
    try:
        outcome=_download(root,output,job,opener=opener)
        # User may pause during the final write. Never overwrite pause with done.
        if outcome=='complete' and _state(root,job['id'])=='running':
            _update(root,job['id'],state='complete',error_code='')
        if _state(root,job['id'])=='cancelled':
            part=Path(output)/(job['target_name']+'.part')
            if part.is_file() and not part.is_symlink():part.unlink()
    except (ValueError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        # No signed URLs, response bodies or secrets in logs/status.
        code=('target_exists' if isinstance(exc,FileExistsError) else
              'invalid_source' if isinstance(exc,ValueError) else
              'network_or_file_error')
        if _state(root,job['id'])=='running':_update(root,job['id'],state='error',error_code=code)
    return _state(root,job['id'])


def loop(root,output,stop):
    initialize(root)
    while not stop.is_set():
        with _LOCK:job=_claim(root)
        if job:_work_one(root,output,job)
        else:stop.wait(1.5)
