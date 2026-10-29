"""Direct connection between MediathekAtlas instances, e.g. over Tailscale.

Instead of a synced folder, one instance (usually the NAS) serves the journal
files of its Verbund folder over HTTP and another one mirrors them. Because
published segments are immutable and every node writes only its own directory,
mirroring is a simple "copy what is missing" in both directions; the journal
logic in meshjournal stays unchanged. Access requires the shared Verbund key.
"""
import json, os, re, secrets, socket, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import meshjournal

KEY_HEADER = 'X-Atlas-Mesh-Key'
MAX_FILE = meshjournal.SEGMENT_BYTES + 2 * meshjournal.MAX_LINE
MAX_INDEX = 8 * 1024 * 1024
TIMEOUT = 60
_PATH = re.compile(r'^nodes/([0-9a-f]{32})/(events-\d{6}\.jsonl|node\.json)$')
_KEY = re.compile(r'^[A-Za-z0-9_-]{32,64}$')


class PeerError(ValueError):
    """Peer unreachable, wrong key or unusable answer."""


def new_key():
    return secrets.token_urlsafe(32)


def valid_key(key):
    return bool(_KEY.match(str(key or '')))


def parse_code(text):
    """'http://host:8730#KEY' (as shown on the other system) -> (url, key)."""
    text = str(text or '').strip()
    if not text: return '', ''
    url, _, key = text.partition('#')
    if '://' not in url: url = 'http://' + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise PeerError('Adresse der Gegenstelle ist ungültig, z. B. http://synology:8730')
    if key and not valid_key(key): raise PeerError('Verbund-Schlüssel ist ungültig')
    return '%s://%s' % (parts.scheme, parts.netloc), key


def tailscale_address():
    """This machine's Tailscale IPv4 (100.64.0.0/10) if Tailscale routes its service address; no packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('100.100.100.100', 53)); ip = s.getsockname()[0]
    except OSError: return ''
    a, b = (int(x) for x in ip.split('.')[:2])
    return ip if a == 100 and 64 <= b <= 127 else ''


def safe_path(text):
    m = _PATH.match(str(text or ''))
    return m and m.group(0)


def index(root):
    """Published journal files below nodes/ as {path: [size, mtime]}."""
    out = {}
    base = Path(root) / 'nodes'
    if not base.is_dir(): return out
    for d in base.iterdir():
        if d.is_symlink() or not d.is_dir(): continue
        for f in d.iterdir():
            rel = 'nodes/%s/%s' % (d.name, f.name)
            if not safe_path(rel) or f.is_symlink(): continue
            try: st = f.stat()
            except OSError: continue
            out[rel] = [st.st_size, int(st.st_mtime)]
    return out


def store(root, own_node, rel, data, mtime=None):
    """Write one mirrored file. Segments are immutable; node.json only moves forward in time."""
    m = _PATH.match(str(rel or ''))
    if not m: raise PeerError('Ungültiger Pfad')
    if m.group(1) == own_node: return False          # never let anybody write into our own directory
    if len(data) > MAX_FILE: raise PeerError('Datei zu groß')
    target = Path(root) / rel
    if target.exists():
        if m.group(2) != 'node.json': return False
        if mtime is not None and int(target.stat().st_mtime) >= int(mtime): return False
    target.parent.mkdir(parents=True, exist_ok=True)
    meshjournal._write_atomic(target, data)
    if mtime is not None: os.utime(target, (int(mtime), int(mtime)))
    return True


class Peer:
    def __init__(self, url, key):
        self.url = url.rstrip('/'); self.key = key
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # LAN/Tailscale, never via a proxy

    def _call(self, method, path, query=None, body=None, limit=MAX_FILE):
        url = self.url + path + ('?' + urllib.parse.urlencode(query) if query else '')
        req = urllib.request.Request(url, data=body, method=method, headers={KEY_HEADER: self.key, 'Content-Type': 'application/octet-stream'})
        try:
            with self.opener.open(req, timeout=TIMEOUT) as r:
                data = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            try: detail = str(json.loads(e.read(65536)).get('error') or '')[:300]
            except (ValueError, AttributeError, OSError): detail = ''
            if e.code == 403: raise PeerError('Gegenstelle lehnt den Verbund-Schlüssel ab. Verbindungscode dort neu anzeigen und hier erneut einfügen.')
            if e.code == 401: raise PeerError('Gegenstelle kennt die Direktverbindung nicht. Bitte dort MediathekAtlas ab 0.5.5 installieren.')
            if e.code == 503: raise PeerError(detail or 'Verbund ist auf der Gegenstelle nicht aktiv')
            raise PeerError('Gegenstelle antwortet mit HTTP %d%s' % (e.code, ': ' + detail if detail else ''))
        except (urllib.error.URLError, OSError) as e:
            raise PeerError('Gegenstelle nicht erreichbar (%s)' % getattr(e, 'reason', e))
        if len(data) > limit: raise PeerError('Antwort der Gegenstelle zu groß')
        return data

    def hello(self):
        raw = self._call('GET', '/api/peer/index', limit=MAX_INDEX)
        try: info = json.loads(raw)
        except ValueError: raise PeerError('Gegenstelle ist kein MediathekAtlas (unerwartete Antwort)')
        if not isinstance(info, dict) or info.get('format') != meshjournal.FORMAT or not isinstance(info.get('files'), dict):
            raise PeerError('Gegenstelle nutzt ein anderes Verbundformat')
        return info

    def sync(self, root, own_node):
        """One mirror round in both directions. Returns counts for the status line."""
        started = time.monotonic(); info = self.hello(); remote = info['files']; local = index(root)
        got = sent = 0
        for rel, meta in sorted(remote.items()):
            if not safe_path(rel) or rel.split('/')[1] == own_node: continue
            have = local.get(rel)
            if rel.endswith('.jsonl') and have: continue
            if rel.endswith('node.json') and have and have[1] >= int(meta[1]): continue
            data = self._call('GET', '/api/peer/file', {'path': rel})
            got += store(root, own_node, rel, data, int(meta[1]))
        peer_node = str(info.get('node') or '')
        for rel, meta in sorted(local.items()):
            if rel.split('/')[1] == peer_node: continue
            theirs = remote.get(rel)
            if rel.endswith('.jsonl') and theirs: continue
            if rel.endswith('node.json') and theirs and int(theirs[1]) >= meta[1]: continue
            try: data = (Path(root) / rel).read_bytes()
            except OSError: continue
            self._call('PUT', '/api/peer/file', {'path': rel, 'mtime': meta[1]}, data, limit=4096); sent += 1
        return {'peer': str(info.get('name') or peer_node[:8])[:80], 'peer_version': str(info.get('version', ''))[:20],
                'received': got, 'sent': sent, 'seconds': round(time.monotonic() - started, 2), 'time': int(time.time())}
