"""Shared recognition results between MediathekAtlas instances via a synced folder.

Each instance writes only below nodes/<node-id>/ and reads the other node
directories. No file is ever written by two devices, so MeshSync (or any other
folder sync) never produces conflict copies. The SQLite catalog stays local.

Segments are appended as events-NNNNNN.jsonl.partial (skipped by MeshSync) and
published by an atomic rename. Published segments are immutable.
"""
import hashlib, json, math, os, re, secrets, threading, time
from pathlib import Path

FORMAT = 'mediathekatlas-events-v1'
FORMAT_FILE = 'mediathekatlas-sync.json'
MESHSYNC_MARKER = '.meshsync-folder'
PARTS = 256
STALE = 900                 # a node without heartbeat for 15 min loses its partitions
SEGMENT_BYTES = 2 * 1024 * 1024
SEGMENT_AGE = 300           # bounded file count for MeshSync: at most 288 segments per node and day
MAX_LINE = 256 * 1024
READ_LIMIT = 5000           # events per import round, keeps weak NAS responsive
HEARTBEAT = 300
TYPES = ('match.result', 'match.manual', 'download.claim', 'download.done', 'download.release')
DOWNLOAD_TYPES = TYPES[2:]
CLAIM_SECONDS = 7200          # a claim expires unless renewed, so a crashed node never blocks a title for long
CLAIM_RENEW = 1800
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
RANK = {'manual': 4, 'matched': 3, 'identified': 2, 'review': 1}
_NODE = re.compile(r'^[0-9a-f]{32}$')
_SEGMENT = re.compile(r'^events-(\d{6})\.jsonl$')


class MeshError(ValueError):
    """Sync folder missing, offline or not prepared."""


def new_node_id():
    return secrets.token_hex(16)


def _write_atomic(path, data):
    temp = path.with_name(path.name + '.' + secrets.token_hex(4) + '.partial')
    with temp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def check_folder(path, create=False):
    """Validate the sync folder. Never creates the folder itself: a missing
    mount must not turn into an empty local directory that then gets synced."""
    text = str(path or '').strip()
    if not text: raise MeshError('Kein Verbundordner angegeben')
    p = Path(text).expanduser()
    if not p.is_absolute(): raise MeshError('Bitte einen absoluten Pfad für den Verbundordner angeben')
    if p.is_symlink(): raise MeshError('Der Verbundordner darf kein symbolischer Link sein')
    if not p.is_dir(): raise MeshError('Verbundordner fehlt oder Laufwerk ist nicht verbunden')
    if not os.access(p, os.R_OK | os.W_OK | os.X_OK): raise MeshError('Keine Schreibrechte im Verbundordner')
    info = p / FORMAT_FILE
    if info.is_file():
        try: fmt = json.loads(info.read_text(encoding='utf-8')).get('format', '')
        except (OSError, ValueError, AttributeError): raise MeshError('Formatdatei im Verbundordner ist beschädigt')
        if fmt.rsplit('-v', 1)[-1] != FORMAT.rsplit('-v', 1)[-1]:
            raise MeshError('Verbundordner nutzt ein anderes Format (%s)' % str(fmt)[:60])
    elif (p / MESHSYNC_MARKER).is_file() or create:
        _write_atomic(info, json.dumps({'format': FORMAT, 'created': int(time.time())}).encode())
    else:
        raise MeshError('Ordner ist kein MeshSync-Ordner. Ordner zuerst in MeshSync verbinden oder ausdrücklich als Verbundordner einrichten.')
    (p / 'nodes').mkdir(exist_ok=True)
    return p.resolve()


def partition(work_id):
    head = str(work_id)[:2]
    if re.fullmatch(r'[0-9a-f]{2}', head): return int(head, 16)
    return hashlib.sha256(str(work_id).encode()).digest()[0]


def _rate(value):
    try: n = float(value)
    except (TypeError, ValueError): return 0.0
    return min(1e6, max(0.0, n)) if math.isfinite(n) else 0.0


def owners(members):
    """Partition owners, same method as MeshSync hubwork.owners(): at least one
    partition per participant, the remainder by measured rate."""
    ids = sorted(members)[:64]
    if not ids: return []
    measured = sorted(_rate(members[i]) for i in ids if _rate(members[i]) > 0)
    initial = measured[len(measured) // 2] if measured else 1.0
    weights = {i: max(initial / 16, _rate(members[i]) or initial) for i in ids}
    total = sum(weights.values()); remaining = PARTS - len(ids)
    quota = {i: 1 + int(remaining * weights[i] / total) for i in ids}
    for i in sorted(ids, key=lambda i: (-(remaining * weights[i] / total % 1), i))[:PARTS - sum(quota.values())]: quota[i] += 1
    return [i for i in ids for _ in range(quota[i])]


def order(rank, providers, hlc, node):
    """Total order of competing results; every node converges to the maximum."""
    return (int(rank), len(providers or []), int(hlc), str(node))


def _plain(value, depth=0):
    if value is None or isinstance(value, (bool, int, float)): return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, str): return len(value) <= 20000
    if depth > 6: return False
    if isinstance(value, list): return len(value) <= 200 and all(_plain(v, depth + 1) for v in value)
    if isinstance(value, dict): return len(value) <= 200 and all(isinstance(k, str) and len(k) <= 64 and _plain(v, depth + 1) for k, v in value.items())
    return False


def clean_meta(meta):
    """Remote metadata is data only: plain JSON, known kinds, bounded size."""
    if not isinstance(meta, dict) or not _plain(meta): return None
    if meta.get('kind') not in ('movie', 'series', 'unknown', 'other') or not isinstance(meta.get('title'), str) or not meta['title'].strip(): return None
    for key in ('year', 'season', 'episode'):
        if meta.get(key) is not None and (isinstance(meta[key], bool) or not isinstance(meta[key], int)): return None
    return dict(meta)


def safe_relative(text):
    """Relative POSIX path inside a sync folder, or None."""
    if not isinstance(text, str) or not 0 < len(text) <= 1024 or '\\' in text or text.startswith('/'): return None
    parts = text.split('/')
    if any(p in ('', '.', '..') or any(ord(ch) < 32 for ch in p) for p in parts): return None
    return text


def valid_download(kind, d):
    if not isinstance(d.get('key'), str) or not 0 < len(d['key']) <= 64: return False
    works = d.get('works', [])
    if not isinstance(works, list) or len(works) > 8 or not all(isinstance(w, str) and 0 < len(w) <= 64 for w in works): return False
    if not isinstance(d.get('title', ''), str) or len(d.get('title', '')) > 300: return False
    if kind == 'download.claim': return isinstance(d.get('until'), int) and not isinstance(d['until'], bool)
    if kind == 'download.done':
        if d.get('path') is not None and safe_relative(d['path']) is None: return False
        if d.get('sha256') is not None and not (isinstance(d['sha256'], str) and _HEX64.match(d['sha256'])): return False
        return isinstance(d.get('size'), int) and not isinstance(d['size'], bool) and d['size'] >= 0
    return True


def sync_root(path):
    """Nearest enclosing MeshSync folder (directory with a marker), or None."""
    try: p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError): return None
    for d in (p, *p.parents):
        marker = d / MESHSYNC_MARKER
        try:
            if marker.is_file() and not marker.is_symlink(): return d
        except OSError: return None
    return None


def valid_event(event, node):
    if not isinstance(event, dict) or event.get('v') != 1 or event.get('node') != node: return False
    if event.get('type') not in TYPES or not isinstance(event.get('data'), dict): return False
    if not isinstance(event.get('seq'), int) or not isinstance(event.get('hlc'), int): return False
    d = event['data']
    if event['type'] in DOWNLOAD_TYPES: return valid_download(event['type'], d)
    if not isinstance(d.get('work'), str) or not 0 < len(d['work']) <= 64: return False
    if d.get('outcome') not in RANK or clean_meta(d.get('meta')) is None: return False
    if d.get('dest') is not None and (not isinstance(d['dest'], str) or len(d['dest']) > 64): return False
    return isinstance(d.get('providers', []), list)


class Journal:
    def __init__(self, root, node_id, name=''):
        if not _NODE.match(node_id): raise MeshError('Ungültige Knotenkennung')
        self.root = Path(root); self.node = node_id; self.name = str(name or '')[:80]
        self.dir = self.root / 'nodes' / node_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock(); self.seq = 0; self.hlc = 0; self.opened = 0
        self.segment = 1; self.size = 0
        self._recover()

    def _recover(self):
        published = sorted(int(m.group(1)) for m in map(_SEGMENT.match, os.listdir(self.dir)) if m)
        partial = sorted(int(p.name[7:13]) for p in self.dir.glob('events-??????.jsonl.partial'))
        last = None
        if partial:
            self.segment = partial[-1]; path = self._partial()
            data = path.read_bytes()
            if data and not data.endswith(b'\n'):           # crash mid-line: drop the torn tail
                data = data[:data.rfind(b'\n') + 1]
                with path.open('r+b') as f: f.truncate(len(data))
            self.size = len(data); self.opened = time.time() if data else 0
            last = data.splitlines()[-1] if data.strip() else None
        elif published:
            self.segment = published[-1] + 1
        if last is None and published:
            lines = (self.dir / ('events-%06d.jsonl' % published[-1])).read_bytes().splitlines()
            last = lines[-1] if lines else None
        if last:
            try: event = json.loads(last); self.seq = int(event['seq']); self.hlc = int(event['hlc'])
            except (ValueError, KeyError, TypeError): pass

    def _partial(self):
        return self.dir / ('events-%06d.jsonl.partial' % self.segment)

    def tick(self, seen=0):
        """Hybrid logical clock in milliseconds."""
        self.hlc = max(int(time.time() * 1000), self.hlc + 1, int(seen) + 1)
        return self.hlc

    def append(self, kind, data):
        if kind not in TYPES: raise ValueError('Unbekannter Ereignistyp')
        with self.lock:
            self.seq += 1
            event = {'v': 1, 'id': '%s:%d' % (self.node, self.seq), 'node': self.node, 'seq': self.seq,
                     'hlc': self.tick(), 'type': kind, 'data': data}
            line = (json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
            if len(line) > MAX_LINE: self.seq -= 1; raise ValueError('Ereignis zu groß')
            with self._partial().open('ab') as f:
                f.write(line); f.flush(); os.fsync(f.fileno())
            self.size += len(line); self.opened = self.opened or time.time()
            return event

    def flush(self, force=False):
        """Publish the open segment once it is large or old enough."""
        with self.lock:
            if not self.size: return False
            if not force and self.size < SEGMENT_BYTES and time.time() - self.opened < SEGMENT_AGE: return False
            os.replace(self._partial(), self.dir / ('events-%06d.jsonl' % self.segment))
            self.segment += 1; self.size = 0; self.opened = 0
            return True

    def heartbeat(self, info):
        node = {'format': FORMAT, 'node': self.node, 'name': self.name, 'time': int(time.time()), 'seq': self.seq, **info}
        _write_atomic(self.dir / 'node.json', json.dumps(node, ensure_ascii=False).encode())

    def nodes(self):
        out = {}
        for d in sorted((self.root / 'nodes').iterdir()):
            if not _NODE.match(d.name) or d.is_symlink() or not d.is_dir(): continue
            try:
                info = json.loads((d / 'node.json').read_text(encoding='utf-8'))
                if isinstance(info, dict) and info.get('node') == d.name and info.get('format') == FORMAT: out[d.name] = info
            except (OSError, ValueError): continue
        return out

    def members(self, nodes=None, now=None):
        """Recognizing nodes with a recent heartbeat, mapped to their measured rate."""
        now = time.time() if now is None else now
        nodes = self.nodes() if nodes is None else nodes
        out = {}
        for nid, info in nodes.items():
            try: fresh = abs(now - float(info.get('time', 0))) < STALE
            except (TypeError, ValueError): fresh = False
            if (fresh or nid == self.node) and info.get('recognizing') is True: out[nid] = _rate(info.get('rate'))
        return out

    def assignment(self, members):
        """Partitions this node owns. Alone (or before peers are visible) it owns all."""
        if not members or self.node not in members: return set() if members else set(range(PARTS))
        return {i for i, owner in enumerate(owners(members)) if owner == self.node}

    def read(self, cursors, limit=READ_LIMIT):
        """New events of other nodes after cursors {node: [segment, line]}."""
        events = []; cursors = {k: list(v) for k, v in (cursors or {}).items()}; invalid = 0; seen = 0
        for d in sorted((self.root / 'nodes').iterdir()):
            nid = d.name
            if nid == self.node or not _NODE.match(nid) or d.is_symlink() or not d.is_dir(): continue
            seg, line = cursors.get(nid, [0, 0])
            for number in sorted(int(m.group(1)) for m in map(_SEGMENT.match, os.listdir(d)) if m):
                if number < seg: continue
                if number > seg: seg, line = number, 0
                try: rows = (d / ('events-%06d.jsonl' % number)).read_bytes().splitlines()
                except OSError: break
                for raw in rows[line:]:
                    line += 1
                    try: event = json.loads(raw) if len(raw) <= MAX_LINE else None
                    except ValueError: event = None
                    if valid_event(event, nid): events.append(event); seen = max(seen, event['hlc'])
                    else: invalid += 1
                    if len(events) >= limit: break
                cursors[nid] = [seg, line]
                if len(events) >= limit: break
            if len(events) >= limit: break
        if seen:
            with self.lock: self.tick(seen)
        return events, cursors, invalid
