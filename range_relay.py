"""Loopback relay that loads a long online file in ranged pieces (0.5.86).

Björn (13.11.2026, MacBook Air M3, Chrome): YouTube videos in the own player stutter, picture and
sound drift apart, while the same video plays smoothly on youtube.com. His diagnosis showed the
cause: ffmpeg fetched picture and sound with one open-ended request each, and YouTube's servers
deliver such a request only at about playback speed (8.4 MB in 38.6 s = 1.8 Mbit/s, first data
after 8 s, after a seek nothing for 20 s). youtube.com and yt-dlp load the same files in pieces of
at most 10 MB, which arrive at full line speed.

This module does the same for ffmpeg: it registers an online address under a random token and
serves it on 127.0.0.1 with Range support. Every request of ffmpeg is answered from pieces of
PIECE bytes, AHEAD of them loaded at the same time, so the data arrive as fast as the connection
allows and seeking is a short ranged request instead of a new throttled download.

Only code of MediathekAtlas registers addresses (never a browser request), the server listens on
the loopback interface only and the tokens are unguessable. Python standard library only.
"""
import http.server,re,secrets,socketserver,threading,time,urllib.error,urllib.request
from concurrent.futures import ThreadPoolExecutor

PIECE=4*1024*1024      # well below YouTube's 10 MB limit for unthrottled ranges
AHEAD=3                # pieces loaded at the same time per stream
TRIES=3
TIMEOUT=20
TTL=6*3600             # YouTube addresses expire after about six hours
MAX_ENTRIES=64
_RANGE=re.compile(r'^bytes=(\d*)-(\d*)$')
_TOTAL=re.compile(r'/(\d+)\s*$')


class UpstreamError(Exception):
    pass


class _Entry:
    __slots__=('url','headers','size','ctype','used')

    def __init__(self,url,headers):
        self.url=url;self.headers=dict(headers or {});self.size=None;self.ctype='application/octet-stream';self.used=time.time()


def _open(entry,start,end,opener=None):
    headers={'User-Agent':'Mozilla/5.0','Accept':'*/*',**entry.headers,'Range':'bytes=%d-%d'%(start,end)}
    req=urllib.request.Request(entry.url,headers=headers)
    return (opener or urllib.request.urlopen)(req,timeout=TIMEOUT)


def fetch(entry,start,end,opener=None,sleep=time.sleep):
    """Bytes start..end (inclusive) of the entry; a few retries for short network hiccups."""
    last=None
    for attempt in range(TRIES):
        try:
            with _open(entry,start,end,opener) as r:
                status=getattr(r,'status',200)
                if status==200 and start>0:raise UpstreamError('Anbieter unterstützt keine Teilabrufe')
                data=r.read(end-start+1) if status==200 else r.read()
                if status==206 or start==0:
                    if entry.size is None:
                        m=_TOTAL.search(r.headers.get('Content-Range','') or '')
                        if m:entry.size=int(m.group(1))
                        elif status==200 and r.headers.get('Content-Length'):entry.size=int(r.headers['Content-Length'])
                    ctype=r.headers.get('Content-Type')
                    if ctype:entry.ctype=ctype
                want=end-start+1 if entry.size is None else min(end,entry.size-1)-start+1
                if len(data)<want:raise UpstreamError('Teilabruf unvollständig (%d von %d Bytes)'%(len(data),want))
                return data[:want]
        except urllib.error.HTTPError as e:
            last=e
            if e.code in (401,403,404,410,416):break   # expired or forbidden address: retrying does not help
        except (OSError,UpstreamError) as e:
            last=e
        if attempt<TRIES-1:sleep(0.5*(attempt+1))
    raise UpstreamError(str(last) if last else 'Abruf fehlgeschlagen')


def size_of(entry,opener=None):
    if entry.size is None:fetch(entry,0,0,opener)
    if entry.size is None:raise UpstreamError('Anbieter nennt keine Dateigröße')
    return entry.size


def pieces(start,end,piece=PIECE):
    """(a, b) inclusive ranges covering start..end; the first piece is short for a quick start."""
    out=[];pos=start;first=min(piece,1024*1024)
    while pos<=end:
        b=min(end,pos+(first if not out else piece)-1);out.append((pos,b));pos=b+1
    return out


def stream(entry,start,end,write,pool,opener=None,ahead=AHEAD):
    """Load start..end in pieces, AHEAD of them at the same time, and write them in order.
    Returns the number of bytes written; a failed write (player gone) stops the remaining pieces."""
    todo=pieces(start,end);running=[];sent=0
    try:
        while todo or running:
            while todo and len(running)<ahead:
                a,b=todo.pop(0);running.append(pool.submit(fetch,entry,a,b,opener))
            data=running.pop(0).result()
            write(data);sent+=len(data)
    finally:
        for f in running:f.cancel()
    return sent


class Relay:
    def __init__(self,opener=None):
        self._lock=threading.Lock();self._entries={};self._by_url={};self._server=None;self.port=0
        self._opener=opener;self._pool=None

    def local(self,url,headers=None):
        """Loopback address for an online address (same token for the same address and headers)."""
        key=(url,tuple(sorted((headers or {}).items())))
        with self._lock:
            self._start()
            now=time.time()
            for token,e in list(self._entries.items()):
                if now-e.used>TTL:self._entries.pop(token,None);self._by_url.pop((e.url,tuple(sorted(e.headers.items()))),None)
            token=self._by_url.get(key)
            if token not in self._entries:
                if len(self._entries)>=MAX_ENTRIES:
                    oldest=min(self._entries,key=lambda t:self._entries[t].used)
                    e=self._entries.pop(oldest);self._by_url.pop((e.url,tuple(sorted(e.headers.items()))),None)
                token=secrets.token_urlsafe(18);self._entries[token]=_Entry(url,headers);self._by_url[key]=token
            self._entries[token].used=now
            return 'http://127.0.0.1:%d/r/%s'%(self.port,token)

    def entry(self,token):
        with self._lock:
            e=self._entries.get(token)
            if e:e.used=time.time()
            return e

    def _start(self):
        if self._server:return
        relay=self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*a):pass
            def do_HEAD(self):self._answer(False)
            def do_GET(self):self._answer(True)

            def _answer(self,body):
                m=re.fullmatch(r'/r/([A-Za-z0-9_-]{20,40})',self.path.split('?')[0])
                e=relay.entry(m.group(1)) if m and self.client_address[0]=='127.0.0.1' else None
                if not e:return self._fail(404)
                try:size=size_of(e,relay._opener)
                except UpstreamError:return self._fail(502)
                start,end,partial=0,size-1,False
                spec=self.headers.get('Range')
                if spec:
                    r=_RANGE.match(spec.strip())
                    if not r or not (r.group(1) or r.group(2)):return self._fail(416,size)
                    if r.group(1):start=int(r.group(1));end=min(size-1,int(r.group(2))) if r.group(2) else size-1
                    else:start=max(0,size-int(r.group(2)))
                    if start>=size or start>end:return self._fail(416,size)
                    partial=True
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type',e.ctype);self.send_header('Accept-Ranges','bytes')
                self.send_header('Content-Length',str(end-start+1))
                if partial:self.send_header('Content-Range','bytes %d-%d/%d'%(start,end,size))
                self.end_headers()
                if not body:return
                try:stream(e,start,end,self.wfile.write,relay._pool,relay._opener)
                except (BrokenPipeError,ConnectionResetError,UpstreamError):self.close_connection=True

            def _fail(self,code,size=None):
                self.send_response(code)
                if size is not None:self.send_header('Content-Range','bytes */%d'%size)
                self.send_header('Content-Length','0');self.end_headers()

        class Server(socketserver.ThreadingMixIn,http.server.HTTPServer):
            daemon_threads=True;allow_reuse_address=True

        self._pool=ThreadPoolExecutor(max_workers=12,thread_name_prefix='range_relay')
        self._server=Server(('127.0.0.1',0),Handler);self.port=self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever,daemon=True,name='range_relay').start()

    def close(self):
        with self._lock:
            if self._server:self._server.shutdown();self._server.server_close();self._server=None
            if self._pool:self._pool.shutdown(wait=False,cancel_futures=True);self._pool=None
            self._entries.clear();self._by_url.clear()


RELAY=Relay()


def local(url,headers=None):
    return RELAY.local(url,headers)
