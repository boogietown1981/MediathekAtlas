"""Isolated, opt-in Netzkino catalogue index + official-browser streaming links.

This module indexes public catalogue metadata via observed first-party
GraphQL operations. Legacy sitemap parsing remains available to regression tests.
No video URLs, player tokens, advertisements, protected media, or account data are fetched.
The feed is not assumed to contain playable films: ambiguous entries are rejected,
failures leave the existing catalogue untouched, and no old entry is purged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

_HOSTS = frozenset(('netzkino.de', 'www.netzkino.de'))
_ID_RE = re.compile(r'^[a-f0-9]{32}$')
_MAX_SITEMAP = 8 * 1024 * 1024
_MAX_SITEMAPS = 40
_MAX_ITEMS = 12000
_CATALOG_URL = 'https://www.netzkino.de/api/sitemap'
# Full-catalogue completion: the GraphQL frontpage only lists curated rows
# (~450 of 2.500+ titles). Standard Next.js sitemap locations, tried in order.
_SITEMAP_CANDIDATES = ('https://www.netzkino.de/sitemap.xml',
                       'https://www.netzkino.de/sitemap-index.xml',
                       _CATALOG_URL)
_GRAPHQL_URL = 'https://data.netzkino.de/netzkino/graphql'
_QUERY_HASHES = {
    'AllContent':'51eb32b81108d564d20969692d53311885bc80b2d1a7041ce5cba1398923caa6',
    'CategoryDataBySlug':'5e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8',
    'MovieDetails':'692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97',
}
_MAX_CATEGORIES = 40          # frontpage subcategories taken from AllContent
_MAX_DISCOVERED = 400         # further categories (category tree, movie details, recordings)
# Category tree roots observed in MovieDetails answers (HAR 12.11.2026): parent.slug of the
# categories a film belongs to. Their subcategories list the full genre/partner catalogue;
# the frontpage only shows curated excerpts ("…-frontpage").
_TREE_ROOTS = (('netzkino-genre','Genres'),('themenkino-genre','Themenkino'),('actionkino','Action'),
               ('thrillerkino','Thriller'),('dramakino','Drama'),('spasskino','Komödien'),
               ('kinderkino','Kinder'),('starkino','Starkino'),('joyn','Partnerkatalog'),
               ('waipu','Partnerkatalog'),('funke-fantasja','Partnerkatalog'))
# Full category lists seen in the same recording (category pages are not paginated:
# e.g. "starkino" answered with 214 titles, the frontpage excerpt with about 20).
_KNOWN_LISTS = (('joyn-netzkino','Netzkino (Joyn)'),('waipu-netzkino','Netzkino (waipu)'),
                ('western','Western'),('krimi','Krimi'),('drama-dramakino','Drama'),('sozialdrama','Sozialdrama'),
                ('schwarze-komodien','Schwarze Komödien'),('familienfilme','Familienfilme'),('halloween','Halloween'),
                ('themenkino-top-rated-imdb','Top Rated IMDb'),
                ('themenkino-filme-nach-wahren-begebenheiten','Filme nach wahren Begebenheiten'),
                ('themenkino-made-in-germany-filme-aus-deutschland','Made in Germany'),
                ('joyn-moviedome-family','Moviedome Family'),('waipu-bronco','Bronco'),('ausgezeichnet-2','Ausgezeichnet'))
_ROOT_SLUGS = frozenset(slug for slug,_ in _TREE_ROOTS)
_SEED_CATEGORIES = _TREE_ROOTS + _KNOWN_LISTS
_MAX_KNOWN = 800
_GRAPHQL_LIMIT = 4 * 1024 * 1024
_REQUEST_GAP_SECONDS = 0.7
_SYNC_MAX_SECONDS = 900

class GraphQLCatalogError(ValueError):
    """A provider's public catalog query failed without storing raw responses."""
    def __init__(self, code='UNKNOWN'):
        code=str(code or 'UNKNOWN')
        self.code=code if code in (
            'PERSISTED_QUERY_NOT_FOUND','GRAPHQL_VALIDATION_FAILED','FORBIDDEN',
            'UNAUTHENTICATED','BAD_USER_INPUT','NOT_FOUND','UNKNOWN') else 'UNKNOWN'
        super().__init__('Netzkino-GraphQL-Antwort abgewiesen ('+self.code+').')


def _category_failure_type(exc):
    if isinstance(exc,urllib.error.HTTPError):
        return 'http_'+str(exc.code) if exc.code in (400,401,403,404,408,429,500,502,503,504) else 'http_other'
    if isinstance(exc,GraphQLCatalogError):return 'graphql_'+exc.code.lower()
    if isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError,OSError)):return 'network'
    if isinstance(exc,ValueError):return 'invalid_payload'
    return 'unexpected'

_SYNC_LOCK = threading.Lock()
_ACTIVE = False
_LAST_THREAD = None


def _notify(event, **details):
    """Technical counters only; never log URLs, media titles, GraphQL bodies or secrets."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        # Telemetry may never block catalogue imports, even on a full disk.
        pass



def verified_url(raw, *, movie_required=True):
    if not isinstance(raw, str):
        raise ValueError('Bitte eine Netzkino-Filmadresse eingeben.')
    raw = raw.strip()
    if not raw or len(raw) > 900 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError('Ungültige Netzkino-Adresse.')
    try:
        parts = urllib.parse.urlsplit(raw)
        if (parts.scheme.lower() != 'https' or parts.hostname not in _HOSTS
                or parts.username is not None or parts.password is not None or parts.port is not None):
            raise ValueError('Erlaubt sind nur HTTPS-Filmseiten auf netzkino.de.')
        if re.search(r'(?i)%(?:0[0-9a-f]|1[0-9a-f]|7f)', raw) or parts.path.startswith('//'):
            raise ValueError('Ungültige Steuerzeichen oder Pfade in der Filmadresse.')
    except (TypeError, ValueError) as exc:
        raise ValueError('Erlaubt sind nur HTTPS-Filmseiten auf netzkino.de.') from exc
    if movie_required and parts.path in ('', '/') and not parts.fragment and not parts.query:
        raise ValueError('Bitte den Link zu einem einzelnen Netzkino-Film einfügen, nicht die Startseite.')
    return urllib.parse.urlunsplit(('https', 'www.netzkino.de', parts.path or '/', parts.query, parts.fragment))


def _seed_target(root):
    """Only install a read-only captured snapshot for an actual app data root.

    Unit tests use temporary scratch roots and must remain deterministic.
    """
    root=Path(root).expanduser().resolve()
    custom=os.environ.get('MEDIATHEKATLAS_HOME')
    if custom:return root==Path(custom).expanduser().resolve()
    home=Path.home()
    return root in ((home/'Library'/'Application Support'/'MediathekAtlas').resolve(),
                    (home/'.mediathekatlas').resolve())


def _connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'netzkino_links.sqlite3'
    db = sqlite3.connect(str(path), timeout=5)
    if os.name != 'nt':
        try: os.chmod(path, 0o600)
        except OSError: pass
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('''CREATE TABLE IF NOT EXISTS netzkino_links (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
        created REAL NOT NULL, updated REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS netzkino_catalog (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL DEFAULT 'sitemap', confidence TEXT NOT NULL DEFAULT 'unverified',
        created REAL NOT NULL, updated REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS netzkino_state (
        name TEXT PRIMARY KEY, value TEXT NOT NULL)''')
    extra = {
        'kind':"TEXT NOT NULL DEFAULT 'movie'", 'year':'INTEGER', 'duration':'INTEGER',
        'genres':'TEXT', 'summary':'TEXT', 'poster':'TEXT', 'access_hint':'TEXT',
        'category':'TEXT', 'fsk':'INTEGER', 'content_id':'TEXT',
    }
    columns={row[1] for row in db.execute('PRAGMA table_info(netzkino_catalog)')}
    for column, spec in extra.items():
        if column not in columns:
            db.execute('ALTER TABLE netzkino_catalog ADD COLUMN '+column+' '+spec)
    # Snapshot bootstrap changes only the isolated Netzkino store and only once.
    # The exact HTTP archive is NEVER stored or shipped, only allowlisted film fields.
    if _seed_target(root) and not db.execute("SELECT 1 FROM netzkino_state WHERE name='snapshot_seed_v05312'").fetchone():
        path=Path(__file__).parent/'assets'/'netzkino_seed.json'
        inserted=0
        if path.is_file() and path.stat().st_size < 1024*1024:
            try:
                rows=json.loads(path.read_text('utf-8')).get('items',[])
                for row in rows:
                    entry=_entry_from_node(row, str(row.get('category') or ''), snapshot=True)
                    if entry:
                        fields=_fields(entry)
                        cur=db.execute('''INSERT OR IGNORE INTO netzkino_catalog
                            (id,title,url,source,confidence,created,updated,kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id)
                            VALUES(?,?,?,'har_snapshot','public_catalog_unverified',?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (entry['id'],entry['title'],entry['url'],time.time(),time.time(),*fields))
                        inserted+=cur.rowcount
            except (OSError,ValueError,TypeError,sqlite3.DatabaseError):
                # A missing/invalid bundled snapshot must never block the app.
                inserted=0
        db.execute("INSERT OR REPLACE INTO netzkino_state(name,value) VALUES('snapshot_seed_v05312','1')")
        db.execute("INSERT OR REPLACE INTO netzkino_state(name,value) VALUES('snapshot_seed_count',?)",(str(inserted),))
    db.commit()
    return db


def _set(db, key, value):
    db.execute('INSERT INTO netzkino_state(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (key, str(value)))


def _get(db, key, default=''):
    row = db.execute('SELECT value FROM netzkino_state WHERE name=?', (key,)).fetchone()
    return row['value'] if row else default


def _key(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def add(root, title, url):
    title = ' '.join(str(title or '').split())
    if not 2 <= len(title) <= 180:
        raise ValueError('Der Filmtitel muss 2 bis 180 Zeichen enthalten.')
    url = verified_url(url)
    key, now = _key(url), time.time()
    db = _connect(root)
    try:
        with db:
            db.execute('''INSERT INTO netzkino_links(id,title,url,created,updated)
                VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated=excluded.updated''',
                (key, title, url, now, now))
        return dict(db.execute('SELECT * FROM netzkino_links WHERE id=?', (key,)).fetchone())
    finally: db.close()


def list_links(root, query='', origin='all', limit=300, offset=0):
    query = str(query or '').strip()[:180]
    origin = origin if origin in ('manual', 'catalog', 'all') else 'all'
    limit = max(1, min(int(limit), 500))
    offset = max(0, min(int(offset), 1000000))
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    db = _connect(root)
    try:
        if origin == 'manual':
            sql = "SELECT id,title,url,'manual' AS origin,'user' AS confidence,updated FROM netzkino_links"
        elif origin == 'catalog':
            sql = "SELECT id,title,url,'catalog' AS origin,confidence,updated FROM netzkino_catalog WHERE url NOT IN (SELECT url FROM netzkino_links)"
        else:
            sql = '''SELECT id,title,url,origin,confidence,updated FROM
                (SELECT id,title,url,'manual' AS origin,'user' AS confidence,updated FROM netzkino_links
                 UNION ALL SELECT id,title,url,'catalog' AS origin,confidence,updated
                    FROM netzkino_catalog WHERE url NOT IN (SELECT url FROM netzkino_links))'''
        if query:
            sql = 'SELECT * FROM (' + sql + ") WHERE title LIKE ? ESCAPE '\\'"
            args = ['%' + escaped + '%']
        else: args = []
        sql += ' ORDER BY updated DESC, title COLLATE NOCASE LIMIT ? OFFSET ?'
        result=[dict(row) for row in db.execute(sql, (*args, limit, offset)).fetchall()]
        if result:
            urls=list(dict.fromkeys(row['url'] for row in result))
            marks=','.join('?' for _ in urls)
            metadata={r['url']:dict(r) for r in db.execute(
                'SELECT url,kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id,source FROM netzkino_catalog WHERE url IN ('+marks+')',urls)}
            for row in result:
                extra=metadata.get(row['url'])
                if extra:row.update({k:v for k,v in extra.items() if k!='url'})
        return result
    finally: db.close()


def count_links(root, query='', origin='all'):
    query = str(query or '').strip()[:180]
    db = _connect(root)
    try:
        if origin == 'manual':
            clause = 'SELECT title FROM netzkino_links'
        elif origin == 'catalog':
            clause = 'SELECT title FROM netzkino_catalog WHERE url NOT IN (SELECT url FROM netzkino_links)'
        else:
            clause = '''SELECT title FROM netzkino_links
                        UNION ALL SELECT title FROM netzkino_catalog
                        WHERE url NOT IN (SELECT url FROM netzkino_links)'''
        args = ()
        if query:
            term = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            clause = 'SELECT title FROM (' + clause + ") WHERE title LIKE ? ESCAPE '\\'"
            args = ('%' + term + '%',)
        return int(db.execute('SELECT count(*) FROM (' + clause + ')', args).fetchone()[0])
    finally: db.close()


def remove(root, key):
    if not isinstance(key, str) or not _ID_RE.fullmatch(key):
        raise ValueError('Ungültiger Netzkino-Eintrag.')
    db = _connect(root)
    try:
        with db: result = db.execute('DELETE FROM netzkino_links WHERE id=?', (key,))
        return bool(result.rowcount)
    finally: db.close()


def state(root):
    db = _connect(root)
    try:
        return {
            'auto': _get(db, 'auto', '0') == '1',
            'last_success': float(_get(db, 'last_success', '0')),
            'last_attempt': float(_get(db, 'last_attempt', '0')),
            'next_attempt': float(_get(db, 'next_attempt', '0')),
            'last_error': _get(db, 'last_error'),
            'new': int(_get(db, 'new', '0')),
            'changed': int(_get(db, 'changed', '0')),
            'unchanged': int(_get(db, 'unchanged', '0')),
            'last_entries': int(_get(db, 'last_entries', '0')),
            'catalog_count': db.execute('SELECT count(*) FROM netzkino_catalog').fetchone()[0],
            'manual_count': db.execute('SELECT count(*) FROM netzkino_links').fetchone()[0],
            'running': _ACTIVE,
            'source': _GRAPHQL_URL,
            'snapshot_seed_count':int(_get(db,'snapshot_seed_count','0')),
            'categories_total':int(_get(db,'categories_total','0')),
            'categories_checked':int(_get(db,'categories_checked','0')),
            'category_errors':int(_get(db,'category_errors','0')),
            'last_http_status':int(_get(db,'last_http_status','0')),
            'catalog_scope':('Startseiten-Kategorien plus Netzkino-Sitemap' if int(_get(db,'sitemap_entries','0'))
                             else 'Kuratierte Startseiten-Kategorien, nicht der vollständige Netzkino-Katalog'),
            'coverage_status':'startpage_plus_sitemap' if int(_get(db,'sitemap_entries','0')) else 'startpage_only',
            'sitemap_entries':int(_get(db,'sitemap_entries','0')),
            'sitemap_new':int(_get(db,'sitemap_new','0')),
            'sitemap_checked':float(_get(db,'sitemap_checked','0')),
            'sitemap_errors':json.loads(_get(db,'sitemap_errors','[]')),
            'category_cap_hits':int(_get(db,'category_cap_hits','0')),
            'category_over_20':int(_get(db,'category_over_20','0')),
            'category_max_items':int(_get(db,'category_max_items','0')),
            'categories_empty':int(_get(db,'categories_empty','0')),
            'category_error_types':json.loads(_get(db,'category_error_types','{}')),
            'last_result':_get(db,'last_result','never'),
            'last_complete_success':float(_get(db,'last_complete_success','0')),
            'time_budget_hit':_get(db,'time_budget_hit','0')=='1',
            'categories_discovered':int(_get(db,'categories_discovered','0')),
            'categories_known':len(json.loads(_get(db,'known_category_slugs','[]') or '[]')),
            'category_pagination':json.loads(_get(db,'category_pagination','{}')),
            'category_total_max':int(_get(db,'category_total_max','0')),
            'related_new':int(_get(db,'graphql_related_new','0')),
            'har_import_added':int(_get(db,'har_import_new','0')),
            'har_import_checked':float(_get(db,'har_import_checked','0')),
            'har_operations':json.loads(_get(db,'har_operations','{}')),
            'source_counts':{r[0]:r[1] for r in db.execute('SELECT source,count(*) FROM netzkino_catalog GROUP BY source')},
        }
    finally: db.close()


def set_auto(root, enabled):
    if type(enabled) is not bool:
        raise ValueError('Auto-Abgleich muss ausdrücklich ein- oder ausgeschaltet werden.')
    db = _connect(root)
    try:
        with db: _set(db, 'auto', int(enabled))
    finally: db.close()
    return state(root)


class _NoOffsiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            url = verified_url(newurl, movie_required=False)
        except ValueError as exc:
            raise ValueError('Netzkino hat auf eine unerwartete Adresse umgeleitet.') from exc
        if url != newurl:
            raise ValueError('Nicht-kanonische Umleitung abgewiesen.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_xml(url, opener=None):
    # One same-origin public XML endpoint, never arbitrary URLs or download streams.
    if url != _CATALOG_URL and not (url.startswith('https://www.netzkino.de/') and
              (url.endswith('.xml') or '/api/sitemap' in urllib.parse.urlsplit(url).path)):
        raise ValueError('Unerwartete Sitemap-Adresse.')
    opener = opener or urllib.request.build_opener(_NoOffsiteRedirect())
    req = urllib.request.Request(url, headers={
        'User-Agent': 'MediathekAtlas/NetzkinoCatalog 0.1 (personal non-commercial metadata index)',
        'Accept': 'application/xml,text/xml;q=0.9',
    })
    with opener.open(req, timeout=18) as response:
        length = int(response.headers.get('Content-Length', '0') or 0)
        if length > _MAX_SITEMAP:
            raise ValueError('Sitemap übersteigt die Größenbegrenzung.')
        data = response.read(_MAX_SITEMAP + 1)
        if len(data) > _MAX_SITEMAP:
            raise ValueError('Sitemap übersteigt die Größenbegrenzung.')
        return data


def _movie_from_url(raw, title=''):
    try: url = verified_url(raw)
    except ValueError: return None
    p = urllib.parse.urlsplit(url)
    # Ignore the homepage, legal, catalog category, static and API routes.
    excluded = {'info', 'legal', 'impressum', 'datenschutz', 'kontakt', 'register',
                'login', 'abo', 'about', 'category', 'categories', 'genre', 'genres',
                'search', 'suche', 'api', 'assets', 'static', 'sitemap'}
    path_parts = [urllib.parse.unquote(x) for x in p.path.split('/') if x]
    if path_parts and path_parts[0].lower() in excluded: return None
    # The public site has changed routes over time; only explicitly movie-like
    # paths are considered a catalogue item, never a guessed generic page.
    # 'details' is the current public route (netzkino.de/details/<slug>).
    movie_roots = {'details', 'film', 'filme', 'movie', 'movies', 'video', 'videos', 'watch'}
    if not (len(path_parts) >= 2 and path_parts[0].lower() in movie_roots):
        fragment = p.fragment.lstrip('!/')
        frag_parts = [x for x in fragment.split('/') if x]
        if not (len(frag_parts) >= 2 and frag_parts[0].lower() in movie_roots):
            return None
        slug = frag_parts[-1]
    else: slug = path_parts[-1]
    slug = urllib.parse.unquote(slug).split('?')[0]
    if not slug or len(slug) > 160: return None
    label = ' '.join(str(title or '').split()).strip()[:180]
    if not label:
        label = re.sub(r'[-_]+', ' ', slug).strip().title()
    if path_parts and path_parts[0].lower() == 'details':
        # Canonical form identical to GraphQL entries, so both sources dedupe by id.
        url = verified_url('https://www.netzkino.de/details/' + urllib.parse.quote(slug, safe='-._~'))
    if len(label) < 2: return None
    return {'id': _key(url), 'title': label, 'url': url}


def parse_sitemap(xml_bytes):
    """Only the explicit movie routes, never infer a movie from title alone.

    Returns (entries, child_sitemaps, document_kind). Unknown structures fail
    closed, preserving the local catalogue unchanged.
    """
    if len(xml_bytes) > _MAX_SITEMAP or b'<!DOCTYPE' in xml_bytes.upper() or b'<!ENTITY' in xml_bytes.upper():
        raise ValueError('Unsichere oder zu große Sitemap.')
    try: root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc: raise ValueError('Die Netzkino-Quelle lieferte kein gültiges XML.') from exc
    name = root.tag.rsplit('}', 1)[-1].lower()
    if name not in ('urlset', 'sitemapindex'):
        raise ValueError('Die Quelle enthält kein unterstütztes Sitemap-Format.')
    entries, children = {}, []
    for node in root:
        entry_type = node.tag.rsplit('}', 1)[-1].lower()
        if entry_type not in ('url', 'sitemap'): continue
        loc = ''; title = ''
        for child in node.iter():
            tag = child.tag.rsplit('}', 1)[-1].lower()
            if tag == 'loc' and not loc:
                loc = (child.text or '').strip()
            elif tag == 'title' and not title:
                title = (child.text or '').strip()
        if name == 'sitemapindex':
            if (loc.startswith('https://www.netzkino.de/') and
                    (loc.endswith('.xml') or '/api/sitemap' in urllib.parse.urlsplit(loc).path)):
                children.append(loc)
        else:
            item = _movie_from_url(loc, title)
            if item: entries[item['id']] = item
        if len(entries) > _MAX_ITEMS: raise ValueError('Zu viele Sitemap-Einträge.')
    return list(entries.values()), children, name


# Public catalogue query signatures observed in the user's 2026-11-11 HAR.
# These are query identifiers, not login credentials. No playback queries are made.
class _GraphQLRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if (parts.scheme != 'https' or parts.hostname != 'data.netzkino.de'
                or parts.path != '/netzkino/graphql' or parts.port is not None
                or parts.username or parts.password):
            raise ValueError('GraphQL-Weiterleitung auf unbekanntes Ziel abgewiesen.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def graphql_url(operation, variables):
    """Generate one first-party, unauthenticated, read-only catalogue request."""
    if operation not in _QUERY_HASHES or not isinstance(variables, dict):
        raise ValueError('Nicht unterstützte Netzkino-Katalogabfrage.')
    ext={'persistedQuery':{'version':1,'sha256Hash':_QUERY_HASHES[operation]}}
    return _GRAPHQL_URL+'?'+urllib.parse.urlencode({
        'extensions':json.dumps(ext,separators=(',',':')),
        'variables':json.dumps(variables,ensure_ascii=False,separators=(',',':')),
        'operationName':operation,
    })


def _fetch_graphql(operation, variables):
    url=graphql_url(operation,variables)
    req=urllib.request.Request(url,headers={
        'User-Agent':'MediathekAtlas-Netzkino/0.5.31.2 (private catalogue; no video access)',
        'Accept':'application/json',
    })
    opener=urllib.request.build_opener(_GraphQLRedirect())
    for attempt in range(3):
        try:
            with opener.open(req,timeout=15) as response:
                if int(response.headers.get('Content-Length','0') or 0)>_GRAPHQL_LIMIT:
                    raise ValueError('Netzkino-Katalogantwort zu groß.')
                payload=response.read(_GRAPHQL_LIMIT+1)
            if len(payload)>_GRAPHQL_LIMIT:raise ValueError('Netzkino-Katalogantwort zu groß.')
            parsed=json.loads(payload)
            if not isinstance(parsed,dict):raise ValueError('Netzkino-Katalogantwort ist kein JSON-Objekt.')
            if parsed.get('errors'):
                first=parsed['errors'][0] if isinstance(parsed['errors'],list) and parsed['errors'] else {}
                code=(first.get('extensions') or {}).get('code') if isinstance(first,dict) else ''
                raise GraphQLCatalogError(code)
            data=parsed.get('data')
            if not isinstance(data,dict):raise ValueError('Netzkino antwortet ohne Katalogdaten.')
            return data
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt>=2:raise
            _notify('netzkino_request_retry',operation=operation,
                    attempt=attempt+1,http_status=exc.code)
            delay=min(8,2**attempt*2)
            retry=exc.headers.get('Retry-After','') if exc.headers else ''
            if retry.isdigit():delay=min(30,max(delay,int(retry)))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt>=2:raise
            delay=min(8,2**attempt*2)
        time.sleep(delay)
    raise RuntimeError('GraphQL-Abruf abgebrochen.')


def _entry_from_node(data, category='', snapshot=False, kind=None):
    if not isinstance(data,dict):return None
    content_id=data.get('content_id' if snapshot else 'id')
    slug=str(data.get('slug') or '')
    title=' '.join(str(data.get('title') or '').split())[:180]
    if (not isinstance(content_id,str) or not 2<=len(title)<=180 or
        not re.fullmatch(r'[\w.\-]{1,120}',slug,flags=re.UNICODE) or
        any(c in slug for c in ('..','/','\\'))):return None
    # The website requests MovieDetails by the same slug and displays its
    # movie detail UI at /details/<slug>. Do not open a direct media URL.
    url=verified_url('https://www.netzkino.de/details/'+urllib.parse.quote(slug,safe='-._~'))
    flags=data.get('genre_flags' if snapshot else 'flags') or []
    if not isinstance(flags,list):flags=[]
    flags=[f for f in flags if isinstance(f,str)][:50]
    gen=[f.split(':',1)[1] for f in flags if f.startswith('genres:')]
    if not snapshot and isinstance(data.get('genres'),list):
        for g in data['genres']:
            if isinstance(g,str):gen.append(g)
            elif isinstance(g,dict) and isinstance(g.get('title') or g.get('name'),str):
                gen.append(g.get('title') or g.get('name'))
    gen=list(dict.fromkeys(' '.join(x.split())[:50] for x in gen if x))[:15]
    properties=[f.split(':',1)[1] for f in flags if f.startswith('properties:')]
    access='AVOD und Plus (Hinweis)' if 'avod' in properties and 'svod' in properties else (
        'AVOD (Hinweis)' if 'avod' in properties else
        'NetzkinoPlus (Hinweis)' if 'svod' in properties else 'Zugang beim Anbieter prüfen')
    yr=data.get('year' if snapshot else 'productionYear')
    try:yr=int(yr) if yr is not None else None
    except (ValueError,TypeError):yr=None
    if yr is not None and not 1880<=yr<=2100:yr=None
    runtime=data.get('runtimeInSeconds')
    try:runtime=int(runtime) if runtime is not None else None
    except (ValueError,TypeError):runtime=None
    if runtime is not None and not 0<runtime<=172800:runtime=None
    fsk=data.get('fskRating' if not snapshot else 'fsk')
    try:fsk=int(fsk) if fsk is not None else None
    except (ValueError,TypeError):fsk=None
    if fsk not in (0,6,12,16,18):fsk=None
    synopsis=''
    if not snapshot:
        synopsis=next((str(data[k]).strip() for k in ('longSynopsis','mediumSynopsis','shortSynopsis') if data.get(k)), '')[:750]
    image=data.get('poster') if snapshot else data.get('coverImage') or {}
    if isinstance(image,dict):image=image.get('masterUrl')
    if not isinstance(image,str):image=''
    pu=urllib.parse.urlsplit(image)
    if not (pu.scheme=='https' and pu.hostname and (pu.hostname=='www.netzkino.de' or
        pu.hostname=='netzkino.de' or pu.hostname.endswith('.cloudfront.net')) and len(image)<=600):image=''
    role=kind or ('series' if snapshot and data.get('kind')=='series' else 'movie')
    if role not in ('movie','series'):role='movie'
    return {'id':_key(url),'url':url,'content_id':content_id,'title':title,'kind':role,
            'year':yr,'duration':runtime,'genres':', '.join(gen),'summary':synopsis,
            'poster':image,'access_hint':access,'category':str(category or '')[:120],
            'fsk':fsk}


def _fields(item):
    return tuple(item.get(k) for k in ('kind','year','duration','genres','summary','poster',
                                      'access_hint','category','fsk','content_id'))


def _collect_nodes(content, category, output):
    if not isinstance(content,dict):return 0
    nodes=content.get('nodes')
    if not isinstance(nodes,list):return 0
    seen=0
    for node in nodes[:2000]:
        if not isinstance(node,dict):continue
        m=node.get('contentMovie')
        role='movie'
        if not isinstance(m,dict):m=node.get('contentSeries');role='series'
        if not isinstance(m,dict):continue
        item=_entry_from_node(m,category,kind=role)
        if not item:continue
        old=output.get(item['id'])
        if old:
            if item['summary'] and not old['summary']:old['summary']=item['summary']
            if item['duration'] and not old['duration']:old['duration']=item['duration']
            if item['poster'] and not old['poster']:old['poster']=item['poster']
            if not old['category']:old['category']=category
        else:output[item['id']]=item
        seen+=1
    return seen


_PAGINATION_KEYS=('pageInfo','totalCount','total','hasNextPage','endCursor','nextCursor','offset','count')
_MOVIE_TYPES=('CmsMovie','CmsSeries','CmsEpisode','Movie','Series')


def _walk_movies(obj, category, output, depth=0):
    """Collect film objects anywhere in a GraphQL/Next.js answer (category lists, rows,
    related titles). Only presentation fields are read; the same validation applies."""
    if depth>12:return 0
    seen=0
    if isinstance(obj,list):
        for x in obj[:3000]:seen+=_walk_movies(x,category,output,depth+1)
        return seen
    if not isinstance(obj,dict):return 0
    for key,role in (('contentMovie','movie'),('contentSeries','series')):
        if isinstance(obj.get(key),dict):seen+=_merge(_entry_from_node(obj[key],category,kind=role),output)
    typename=str(obj.get('__typename') or '')
    if typename in _MOVIE_TYPES and obj.get('slug'):
        seen+=_merge(_entry_from_node(obj,category,kind='series' if 'Series' in typename else 'movie'),output)
    for key,value in obj.items():
        if key in ('contentMovie','contentSeries','videoSource','licenses'):continue
        if isinstance(value,(dict,list)):seen+=_walk_movies(value,category,output,depth+1)
    return seen


def _merge(item, output):
    if not item:return 0
    old=output.get(item['id'])
    if old:
        for k in ('summary','duration','poster','year','genres','fsk'):
            if item.get(k) and not old.get(k):old[k]=item[k]
        if not old['category']:old['category']=item['category']
    else:output[item['id']]=item
    return 1


def _discover_categories(obj, depth=0, out=None):
    """Category slugs mentioned inside an answer (subcategories, category references)."""
    out=[] if out is None else out
    if depth>8 or len(out)>500:return out
    if isinstance(obj,list):
        for x in obj[:500]:_discover_categories(x,depth+1,out)
        return out
    if not isinstance(obj,dict):return out
    subs=obj.get('subcategories')
    nodes=subs.get('nodes') if isinstance(subs,dict) else subs if isinstance(subs,list) else []
    for cat in nodes or []:
        if isinstance(cat,dict):_add_slug(cat,out)
    if 'Category' in str(obj.get('__typename') or ''):_add_slug(obj,out)
    for key,value in obj.items():
        if key in ('contentMovie','contentSeries'):continue
        if isinstance(value,(dict,list)):_discover_categories(value,depth+1,out)
    return out


def _add_slug(cat, out):
    slug=cat.get('slug')
    if isinstance(slug,str) and 1<=len(slug)<=140 and re.fullmatch(r'[\w.\-]+',slug):
        out.append((slug,str(cat.get('title') or '')[:120]))


def _pagination(content):
    """Pagination hints of a category list, to learn whether a category has more titles."""
    if not isinstance(content,dict):return {}
    hints={k:content[k] for k in _PAGINATION_KEYS if k in content}
    info=hints.get('pageInfo')
    if isinstance(info,dict):hints['pageInfo']={k:info[k] for k in ('hasNextPage','endCursor','totalCount') if k in info}
    return hints


def add_discovered(db, payload, now, source='graphql_related', category=''):
    """Insert titles found in any public answer (related titles, imported recordings).

    Only new rows are added; existing GraphQL rows keep their data. Returns the count.
    The caller owns the transaction.
    """
    found={}
    _walk_movies(payload,category,found)
    added=0
    for item in list(found.values())[:_MAX_ITEMS]:
        cur=db.execute('''INSERT INTO netzkino_catalog
                (id,title,url,source,confidence,created,updated,kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id)
                VALUES(?,?,?,?,'public_catalog_unverified',?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING''',(item['id'],item['title'],item['url'],source,now,now,*_fields(item)))
        added+=cur.rowcount if cur.rowcount and cur.rowcount>0 else 0
    if added:
        key=source+'_new'
        _set(db,key,int(_get(db,key,'0'))+added)
    return added


_RECORDING_HOSTS=('data.netzkino.de','www.netzkino.de','netzkino.de')
_NEXT_DATA=re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',re.S)


def import_recording(root, entries, now=None):
    """Add titles from a browser network recording (HAR) of netzkino.de.

    The browser extracts only URL and answer text of netzkino.de requests; headers,
    cookies and tokens never leave it. Here only public film fields are read and only
    new titles are added. The observed query names show which catalogue requests the
    website uses (for example for "Alle anzeigen"), without storing variables or values.
    """
    now=time.time() if now is None else float(now)
    if not isinstance(entries,list) or len(entries)>20000:raise ValueError('Mitschnitt nicht lesbar')
    operations={};answers=0;ignored=0
    db=_connect(root)
    try:
        with db:
            added=0
            for entry in entries:
                if not isinstance(entry,dict):ignored+=1;continue
                url=str(entry.get('url') or '')[:4000];text=entry.get('text')
                parts=urllib.parse.urlsplit(url)
                if parts.scheme!='https' or parts.hostname not in _RECORDING_HOSTS or not isinstance(text,str):
                    ignored+=1;continue
                if len(text)>_GRAPHQL_LIMIT*2:ignored+=1;continue
                q=urllib.parse.parse_qs(parts.query)
                op=(q.get('operationName') or [''])[0]
                if op and re.fullmatch(r'[A-Za-z0-9_]{1,80}',op):operations[op]=operations.get(op,0)+1
                payload=None
                stripped=text.lstrip()
                if stripped[:1] in '{[':
                    try:payload=json.loads(text)
                    except ValueError:payload=None
                else:
                    m=_NEXT_DATA.search(text)
                    if m:
                        try:payload=json.loads(m.group(1))
                        except ValueError:payload=None
                if payload is None:ignored+=1;continue
                answers+=1
                added+=add_discovered(db,payload,now,source='har_import')
                remember_categories(db,payload)
            total=db.execute('SELECT COUNT(*) FROM netzkino_catalog').fetchone()[0]
            for key,value in [('har_import_checked',now),('har_import_added',added),
                              ('har_import_answers',answers),('har_operations',json.dumps(operations,sort_keys=True)),
                              ('catalog_total',total)]:
                _set(db,key,value)
    finally:db.close()
    _notify('netzkino_recording_import',answers=answers,added=added,ignored=ignored,operations=len(operations))
    return {'ok':True,'answers':answers,'added':added,'ignored':ignored,'total':total,
            'operations':sorted(operations)}


def remember_categories(db, payload):
    """Keep category slugs seen in any answer (film details, recordings) for the next sync."""
    found=_discover_categories(payload)
    if not found:return 0
    try:known=json.loads(_get(db,'known_category_slugs','[]'))
    except ValueError:known=[]
    if not isinstance(known,list):known=[]
    have={k[0] for k in known if isinstance(k,list) and k}
    added=0
    for slug,title in found:
        if slug not in have and len(known)<_MAX_KNOWN:
            known.append([slug,title]);have.add(slug);added+=1
    if added:_set(db,'known_category_slugs',json.dumps(known,ensure_ascii=False))
    return added


def _known_categories(root):
    db=_connect(root)
    try:
        try:known=json.loads(_get(db,'known_category_slugs','[]'))
        except ValueError:known=[]
    finally:db.close()
    return [(k[0],str(k[1] if len(k)>1 else '')[:120]) for k in known if isinstance(k,list) and k
            and isinstance(k[0],str) and re.fullmatch(r'[\w.\-]{1,140}',k[0])]


def _collect_categories(root, output):
    if not isinstance(root,dict):raise ValueError('Netzkino-Kategoriestruktur fehlt.')
    category=root.get('parentCategory') or root.get('category')
    if not isinstance(category,dict):raise ValueError('Netzkino lieferte keine Startseiten-Kategorien.')
    _collect_nodes(category.get('content'),category.get('title') or '',output)
    categories=[]
    for cat in ((category.get('subcategories') or {}).get('nodes') or [])[:_MAX_CATEGORIES]:
        if not isinstance(cat,dict):continue
        slug=cat.get('slug')
        if isinstance(slug,str) and 1<=len(slug)<=140 and re.fullmatch(r'[\w.\-]+',slug):
            categories.append((slug,str(cat.get('title') or '')[:120]))
            _collect_nodes(cat.get('content'),cat.get('title') or '',output)
    _collect_nodes((root.get('featured') or {}).get('content'), 'Featured', output)
    return list(dict.fromkeys(categories))


def sync_graphql(root, fetch=None, now=None):
    """Merge public catalog data even when individual categories fail.

    A successful frontpage contains independently usable film objects; a partial
    category refresh is marked explicitly, never silently claimed as complete.
    No media requests, playback links, session state or download jobs are used.
    """
    now=time.time() if now is None else float(now)
    fetch=fetch or _fetch_graphql
    _notify('netzkino_sync_started',mode='public_graphql',live=True)
    db=_connect(root)
    try:
        with db:
            for key,value in [('last_attempt',now),('categories_checked',0),
                              ('categories_total',0),('category_errors',0),
                              ('categories_empty',0),('categories_discovered',0),('category_pagination','{}'),('category_total_max',0),('category_cap_hits',0),('category_over_20',0),('category_max_items',0),('category_error_types','{}'),
                              ('last_http_status',0),('last_result','running')]:
                _set(db,key,value)
    finally:db.close()
    found={}
    checked=failures=empty=successful=0
    error_types={}
    cap_hits=0
    over_20=0
    category_max=0
    stopped_for_access=False
    stopped_for_budget=False
    started_mono=time.monotonic()
    last_http=0
    try:
        home=fetch('AllContent',{'categoryConnectionFilter':None,'featuredLimit':10,
                                 'featuredSlug':'featured','parentSlug':'frontpage'})
        if 'data' in home and isinstance(home['data'],dict):home=home['data']
        cats=_collect_categories(home,found)
        if not found:raise ValueError('Netzkino lieferte keine erkennbaren Filmobjekte.')
        db=_connect(root)
        try:
            with db:_set(db,'categories_total',len(cats))
        finally:db.close()
        known={slug for slug,_ in cats};discovered=0;pagination={};total_max=0
        # Full category lists: tree roots and categories remembered from film details/recordings.
        for more in list(_SEED_CATEGORIES)+_known_categories(root):
            if more[0] not in known and discovered<_MAX_DISCOVERED:
                known.add(more[0]);cats.append(more);discovered+=1
        index=0
        while index<len(cats):
            slug,name=cats[index];index+=1
            if time.monotonic()-started_mono>_SYNC_MAX_SECONDS:
                stopped_for_budget=True
                break
            if fetch is _fetch_graphql:time.sleep(_REQUEST_GAP_SECONDS)
            try:
                if slug in _ROOT_SLUGS:
                    # The category page of a tree node lists its subcategories (AllContent).
                    try:
                        tree=fetch('AllContent',{'parentSlug':slug,'featuredSlug':'featured-'+slug})
                        if isinstance(tree,dict) and isinstance(tree.get('data'),dict):tree=tree['data']
                        for more in _discover_categories(tree):
                            if more[0] not in known and discovered<_MAX_DISCOVERED:
                                known.add(more[0]);cats.append(more);discovered+=1
                    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,ValueError):pass
                    if fetch is _fetch_graphql:time.sleep(_REQUEST_GAP_SECONDS)
                page=fetch('CategoryDataBySlug',{'slug':slug})
                if 'data' in page and isinstance(page['data'],dict):page=page['data']
                if not isinstance(page,dict):raise ValueError('Ungültige Kategorieantwort')
                category=page.get('category')
                if category is None:
                    empty+=1
                elif not isinstance(category,dict):
                    raise ValueError('Ungültige Kategoriedaten')
                else:
                    content=category.get('content')
                    # Counts of observed category size, NOT a pagination limit.
                    if isinstance(content,dict) and isinstance(content.get('nodes'),list):
                        count=len(content['nodes'])
                        category_max=max(category_max,count)
                        if count>=20:cap_hits+=1
                        if count>20:over_20+=1
                    if content is None or (isinstance(content,dict) and not content.get('nodes')):
                        empty+=1
                    elif not isinstance(content,dict):
                        raise ValueError('Ungültige Filmübersicht')
                    else:
                        _collect_nodes(content,name,found)
                        successful+=1
                    # Titles outside content.nodes (rows, related lists) and further categories.
                    _walk_movies(category,name,found)
                    hints=_pagination(content)
                    for key in hints:pagination[key]=pagination.get(key,0)+1
                    for key in ('totalCount','total'):
                        value=hints.get(key) if key in hints else (hints.get('pageInfo') or {}).get(key)
                        if isinstance(value,int):total_max=max(total_max,value)
                    for more in _discover_categories(category):
                        if more[0] not in known and discovered<_MAX_DISCOVERED:
                            known.add(more[0]);cats.append(more);discovered+=1
            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
                failures+=1
                kind=_category_failure_type(exc)
                error_types[kind]=error_types.get(kind,0)+1
                status=int(getattr(exc,'code',0) or 0) if isinstance(exc,urllib.error.HTTPError) else 0
                if status:last_http=status
                _notify('netzkino_category_error',error_type=kind,http_status=status,
                        category_errors=failures,checked=checked+1)
                if status in (401,403,429) or kind in ('graphql_forbidden','graphql_unauthenticated'):
                    stopped_for_access=True
            checked+=1
            db=_connect(root)
            try:
                with db:
                    for key,value in [('categories_checked',checked),('category_errors',failures),
                                      ('categories_total',len(cats)),('categories_discovered',discovered),
                                      ('category_pagination',json.dumps(pagination,sort_keys=True)),('category_total_max',total_max),
                                      ('categories_empty',empty),('category_cap_hits',cap_hits),('category_over_20',over_20),('category_max_items',category_max),('category_error_types',json.dumps(error_types,sort_keys=True)),
                                      ('last_http_status',last_http)]:
                        _set(db,key,value)
            finally:db.close()
            if stopped_for_access:break
        db=_connect(root)
        try:
            with db:
                new=changed=unchanged=0
                for item in found.values():
                    old=db.execute('''SELECT title,source,kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id
                                      FROM netzkino_catalog WHERE id=?''',(item['id'],)).fetchone()
                    snapshot=(item['title'],'graphql',*_fields(item))
                    prior=tuple(old) if old else None
                    if old is None:new+=1
                    elif prior!=snapshot:changed+=1
                    else:unchanged+=1
                    db.execute('''INSERT INTO netzkino_catalog
                            (id,title,url,source,confidence,created,updated,kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id)
                            VALUES(?,?,?,'graphql','public_catalog_unverified',?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET title=excluded.title,source=excluded.source,
                             confidence=excluded.confidence,updated=excluded.updated,kind=excluded.kind,
                             year=COALESCE(excluded.year,netzkino_catalog.year),
                             duration=COALESCE(excluded.duration,netzkino_catalog.duration),
                             genres=CASE WHEN excluded.genres!='' THEN excluded.genres ELSE netzkino_catalog.genres END,
                             summary=CASE WHEN excluded.summary!='' THEN excluded.summary ELSE netzkino_catalog.summary END,
                             poster=CASE WHEN excluded.poster!='' THEN excluded.poster ELSE netzkino_catalog.poster END,
                             access_hint=excluded.access_hint,category=excluded.category,
                             fsk=COALESCE(excluded.fsk,netzkino_catalog.fsk),
                             content_id=excluded.content_id''',
                        (item['id'],item['title'],item['url'],now,now,*_fields(item)))
                partial=bool(failures or checked<len(cats))
                _set(db,'last_success',now)
                if not partial:_set(db,'last_complete_success',now)
                _set(db,'last_result','partial' if partial else 'complete')
                _set(db,'time_budget_hit',int(stopped_for_budget))
                _set(db,'last_error', ('Teilabgleich: %d Kategoriefehler, %d leer, %d/%d geprüft. Bestand erhalten.'%(
                    failures,empty,checked,len(cats))) if partial else '')
                for key,value in [('last_entries',len(found)),('new',new),
                                  ('changed',changed),('unchanged',unchanged),
                                  ('next_attempt',now+(24*3600 if not partial else 6*3600 if stopped_for_access else 3*3600))]:
                    _set(db,key,value)
            _notify('netzkino_sync_completed',count=len(found),new=new,changed=changed,
                    unchanged=unchanged,categories=len(cats),categories_checked=checked,
                    categories_empty=empty,category_errors=failures,category_cap_hits=cap_hits,category_over_20=over_20,category_max_items=category_max,partial=partial,coverage_status='startpage_only')
            return {'new':new,'changed':changed,'unchanged':unchanged,'count':len(found),
                    'categories':len(cats),'categories_checked':checked,'categories_discovered':discovered,
                    'category_pagination':pagination,'category_total_max':total_max,
                    'category_errors':failures,'categories_empty':empty,'category_cap_hits':cap_hits,
                    'category_over_20':over_20,'category_max_items':category_max,
                    'coverage_status':'startpage_only','error_types':error_types,'partial':partial,'ok':True}
        finally:db.close()
    except Exception as exc:
        if isinstance(exc,urllib.error.HTTPError):msg='Netzkino-Katalog HTTP '+str(exc.code)
        elif isinstance(exc,(urllib.error.URLError,TimeoutError,OSError)):msg='Netzkino-Katalogserver nicht erreichbar.'
        elif isinstance(exc,ValueError):msg=str(exc)[:240]
        else:msg='GraphQL-Katalogabgleich konnte nicht abgeschlossen werden.'
        db=_connect(root)
        try:
            with db:
                for key,value in [('last_error',msg),('last_result','failed'),
                                  ('last_http_status',getattr(exc,'code',0)),('next_attempt',now+3600)]:
                    _set(db,key,value)
        finally:db.close()
        _notify('netzkino_sync_failed',error_type=_category_failure_type(exc),
                http_status=getattr(exc,'code',0),categories_checked=checked)
        return {'ok':False,'error':msg,'categories_checked':checked}

def _collect_sitemaps(fetcher):
    """All movie routes of the first sitemap location that yields any."""
    errors=[]
    for start in _SITEMAP_CANDIDATES:
        visited,pending,found=set(),[start],{}
        try:
            while pending and len(visited)<_MAX_SITEMAPS:
                url=pending.pop(0)
                if url in visited:continue
                visited.add(url)
                items,children,_kind=parse_sitemap(fetcher(url))
                found.update((x['id'],x) for x in items)
                if len(found)>_MAX_ITEMS:raise ValueError('Zu viele Katalogeinträge.')
                pending.extend(c for c in children if c not in visited and c not in pending)
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
            errors.append(_category_failure_type(exc) if not isinstance(exc,urllib.error.HTTPError) else 'http_%d'%exc.code)
            if not found:continue
        if found:return list(found.values()),start,bool(pending),errors
    return [],None,False,errors


def complete_from_sitemap(root, fetcher=None, now=None):
    """Add titles that the curated GraphQL frontpage does not list.

    Only *new* rows are inserted (source 'sitemap'); GraphQL rows keep their
    richer data. Nothing is deleted. Details (cover, year, description) are
    loaded when a title is opened, exactly like for every other title.
    """
    now=time.time() if now is None else float(now)
    items,used,truncated,errors=_collect_sitemaps(fetcher or _fetch_xml)
    db=_connect(root)
    try:
        with db:
            added=0
            for item in items:
                cur=db.execute("""INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind)
                    VALUES(?,?,?,'sitemap','public_sitemap_unverified',?,?,'movie')
                    ON CONFLICT DO NOTHING""",(item['id'],item['title'],item['url'],now,now))
                added+=cur.rowcount if cur.rowcount and cur.rowcount>0 else 0
            total=db.execute('SELECT COUNT(*) FROM netzkino_catalog').fetchone()[0]
            for key,value in [('sitemap_entries',len(items)),('sitemap_new',added),
                              ('sitemap_source',used or ''),('sitemap_truncated',int(truncated)),
                              ('sitemap_errors',json.dumps(errors)),('sitemap_checked',now),
                              ('catalog_total',total)]:
                _set(db,key,value)
    finally:db.close()
    _notify('netzkino_sitemap_completion',entries=len(items),new=added,
            found=bool(used),truncated=truncated,errors=len(errors))
    return {'ok':bool(items),'entries':len(items),'new':added,'source':used,
            'truncated':truncated,'errors':errors}


def sync(root, fetcher=None, now=None, graphql_fetch=None, sitemap_fetch=None):
    """Atomic successful refresh. No deletion on empty, unavailable, invalid data.

    Tests inject `fetcher` for legacy sitemap parsing; production uses first-party catalogue GraphQL.
    """
    if fetcher is None:
        result=sync_graphql(root, fetch=graphql_fetch, now=now)
        # Tests that inject only graphql_fetch must not reach the network.
        if graphql_fetch is None or sitemap_fetch is not None:
            try:
                extra=complete_from_sitemap(root, fetcher=sitemap_fetch, now=now)
            except Exception as exc:  # completion never breaks the GraphQL result
                extra={'ok':False,'error':_category_failure_type(exc)}
            result['sitemap']=extra
            if extra.get('ok'):result['coverage_status']='startpage_plus_sitemap'
        return result
    now = time.time() if now is None else float(now)
    db = _connect(root)
    try:
        with db: _set(db, 'last_attempt', now)
    finally: db.close()
    visited, pending = set(), [_CATALOG_URL]
    found = {}
    try:
        while pending and len(visited) < _MAX_SITEMAPS:
            url = pending.pop(0)
            if url in visited: continue
            visited.add(url)
            items, children, kind = parse_sitemap(fetcher(url))
            found.update((x['id'], x) for x in items)
            if len(found) > _MAX_ITEMS: raise ValueError('Zu viele Katalogeinträge.')
            pending.extend(child for child in children if child not in visited and child not in pending)
        if pending:
            raise ValueError('Sitemap enthält zu viele Teilkataloge; Vollständigkeit ungeklärt.')
        if not found:
            raise ValueError('Die Sitemap enthält keine eindeutig erkennbaren Filmseiten. Kein Import durchgeführt.')
        db = _connect(root)
        try:
            with db:
                new = changed = unchanged = 0
                for item in found.values():
                    old = db.execute('SELECT title FROM netzkino_catalog WHERE id=?', (item['id'],)).fetchone()
                    if old is None: new += 1
                    elif old['title'] != item['title']: changed += 1
                    else: unchanged += 1
                    db.execute('''INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated)
                        VALUES(?,?,?,'sitemap','unverified',?,?)
                        ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated=excluded.updated''',
                        (item['id'], item['title'], item['url'], now, now))
                _set(db, 'last_success', now)
                _set(db, 'last_error', '')
                _set(db, 'last_entries', len(found))
                _set(db, 'new', new)
                _set(db, 'changed', changed)
                _set(db, 'unchanged', unchanged)
                _set(db, 'next_attempt', now + 24*3600)
            return {'new': new, 'changed': changed, 'unchanged': unchanged, 'count': len(found), 'ok': True}
        finally: db.close()
    except Exception as exc:
        # Keep data and prior success time; report an actionable sanitized reason.
        if isinstance(exc, (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError)):
            message = 'Netzkino-Katalog derzeit nicht erreichbar.'
        elif isinstance(exc, ValueError):
            message = str(exc)[:260]
        else:
            message = 'Unbekannter Katalogfehler.'
        db = _connect(root)
        try:
            with db:
                _set(db, 'last_error', message)
                _set(db, 'next_attempt', now + 60*60)
        finally: db.close()
        return {'ok': False, 'error': message}


def _run_background(root):
    global _ACTIVE
    try: sync(root)
    finally:
        with _SYNC_LOCK: _ACTIVE = False


def start_sync(root):
    global _ACTIVE, _LAST_THREAD
    with _SYNC_LOCK:
        if _ACTIVE: return False
        _ACTIVE = True
        _LAST_THREAD = threading.Thread(target=_run_background, args=(root,), daemon=True,
                                        name='netzkino_catalog_sync')
        _LAST_THREAD.start()
        return True


def loop(root, stop):
    """Runs only while the main MediathekAtlas process is alive."""
    while not stop.wait(60):
        current = state(root)
        if current['auto'] and not current['running'] and time.time() >= current['next_attempt']:
            start_sync(root)


# v0.5.31.5: conservative *derived* episode identity, without rewriting imported offers.
# Provider contentMovie denotes a playable item, not necessarily a feature film.
# Keep original IDs, titles, links, manually saved items and SQLite schema untouched.
import unicodedata as _unicode

_EP_SEASON=re.compile(
    r'(?i)^\s*(?P<show>.+?)\s+(?:staffel|season)\s*(?P<season>\d{1,2})'
    r'\s*[-–—:|]\s*(?:(?:folge|episode|ep\.?|episode\s*nr\.?)\s*)?'
    r'(?P<episode>\d{1,3})\s*\.?\s*(?:[-–—:]\s*)?(?P<label>.*)$')
_EP_FOLGE=re.compile(
    r'(?i)^\s*(?P<show>.+?)\s*[-–—:|]\s*(?:folge|episode|ep\.?)'
    r'\s*(?P<episode>\d{1,3})\s*(?:[:\-–—]\s*)?(?P<label>.*)$')
_EP_SXE=re.compile(
    r'(?i)^\s*(?P<show>.+?)\s*[-–—:| ]+s(?P<season>\d{1,2})'
    r'[. _\-]*e(?P<episode>\d{1,3})\b\s*[:\-–—]?\s*(?P<label>.*)$')
_EP_X=re.compile(
    r'(?i)^\s*(?P<show>.+?)\s*[-–—:| ]+(?P<season>\d{1,2})'
    r'\s*x\s*(?P<episode>\d{1,3})\b\s*[:\-–—]?\s*(?P<label>.*)$')


def _series_normalize(value):
    raw=_unicode.normalize('NFKD',str(value or '').casefold())
    raw=''.join(ch for ch in raw if not _unicode.combining(ch))
    return re.sub(r'[^a-z0-9]+',' ',raw).strip()


def classify_media(item):
    """Identify an *explicit* episode or the provider's native series record.

    Never infer series just from matching title, duration, a film sequel ('Teil'),
    category, or year. This runs for existing and newly imported catalogue rows.
    """
    title=' '.join(str((item or {}).get('title') or '').split())
    if item.get('kind')=='series':
        return {'media_type':'series','series_title':title,'season':None,
                'episode':None,'episode_title':'','evidence':'provider_contentSeries'}
    for pattern in (_EP_SEASON,_EP_FOLGE,_EP_SXE,_EP_X):
        match=pattern.match(title)
        if not match:continue
        show=match.group('show').strip(' \t-–—:|')
        ep=int(match.group('episode'))
        season=int(match.groupdict().get('season') or 0) or None
        if not (2<=len(show)<=150 and 1<=ep<=999 and (season is None or 1<=season<=99)):
            continue
        return {'media_type':'episode','series_title':show,'season':season,
                'episode':ep,'episode_title':(match.group('label') or '').strip(),
                'evidence':'explicit_episode_number_in_provider_title'}
    return {'media_type':'movie','series_title':'','season':None,'episode':None,
            'episode_title':'','evidence':'provider_movie_unverified'}


def _view_rows(root, origin='all'):
    """One local read of the independent Netzkino database, manual links take precedence."""
    origin=origin if origin in ('all','manual','catalog') else 'all'
    db=_connect(root)
    try:
        catalog=[dict(r) for r in db.execute("""SELECT id,title,url,source,confidence,updated,
            kind,year,duration,genres,summary,poster,access_hint,category,fsk,content_id
            FROM netzkino_catalog""")]
        manuals=[dict(r) for r in db.execute('SELECT id,title,url,updated FROM netzkino_links')]
    finally:db.close()
    by_url={r['url']:r for r in catalog}
    out=[]
    if origin in ('all','catalog'):
        manual_urls={r['url'] for r in manuals}
        for r in catalog:
            if r['url'] not in manual_urls:out.append({**r,'origin':'catalog'})
    if origin in ('all','manual'):
        for m in manuals:
            extra=by_url.get(m['url']) or {}
            out.append({**extra,**m,'origin':'manual',
                'confidence':'user' if not extra else extra.get('confidence','user'),
                'kind':extra.get('kind','movie')})
    return out


def grouped_catalog(root, *, view='movies', series_key='',query='',origin='all',limit=80,offset=0,genre='',sort='updated'):
    """Stable film/series/episode view; no changes to actual catalog or downloads.

    series_key is a deterministic ID derived from the normalized provider series
    title. An existing contentSeries record can be shown alongside episode rows.
    """
    if view not in ('movies','series','episodes'):raise ValueError('Ungültige Medienansicht')
    if view=='episodes' and not re.fullmatch(r'series-[a-f0-9]{24}',str(series_key)):
        raise ValueError('Ungültige Serienkennung')
    query=str(query or '').strip().casefold()[:180]
    genre=str(genre or '').strip().casefold()[:80]
    sort=sort if sort in ('title','year','updated','rating') else 'updated'
    def genre_tokens(row):
        value=row.get('genres') or ''
        if isinstance(value,str):
            if value.startswith('['):
                try:value=json.loads(value)
                except (TypeError,ValueError):pass
            if isinstance(value,str):value=re.split(r'[,;|·]',value)
        if not isinstance(value,(list,tuple)):return []
        return [str(v).strip().casefold() for v in value if str(v).strip()]
    import portal_reference, netzkino_enrichment
    reports=netzkino_enrichment.all_cached(root)
    def genre_match(row):
        # Canonical categories (IMDb/TVDB/TMDB genres first) as in the Mediathek catalogue.
        return portal_reference.matches(row,genre)
    limit=max(1,min(100,int(limit)))
    offset=max(0,min(1000000,int(offset)))
    movies=[];series={}
    for row in _view_rows(root,origin):
        classification=classify_media(row)
        enriched={**row,**classification,**portal_reference.summary(row.get('genres'),reports.get(row['id']))}
        if classification['media_type']=='movie':
            movies.append(enriched)
            continue
        normalized=_series_normalize(classification['series_title'])
        if not normalized:continue
        key='series-'+hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]
        group=series.setdefault(key,{'id':key,'series_key':key,'title':classification['series_title'],
            'kind':'series','media_type':'series','episode_count':0,'seasons':[],
            'poster':'','year':None,'genres':row.get('genres') or '',
            'series_url':'','evidence':classification['evidence'],
            'children':[], 'origin':row['origin'],'updated':row.get('updated',0)})
        group['updated']=max(group['updated'],row.get('updated',0))
        if classification['media_type']=='series':
            group['title']=classification['series_title']
            group['series_url']=row['url']
            group['poster']=row.get('poster') or group['poster']
            group['year']=row.get('year') or group['year']
            group['evidence']='provider_contentSeries'
        else:
            group['children'].append({**enriched,'series_key':key})
            if not group.get('score') and enriched.get('score'):group['score']=enriched['score']
            if not group['poster']:group['poster']=row.get('poster') or ''
            if not group['genres']:group['genres']=row.get('genres') or ''
            if not group['year']:group['year']=row.get('year')
    for group in series.values():
        cats=sorted({c for e in group['children'] for c in e['categories']}-{portal_reference.UNKNOWN},key=str.casefold)
        group['categories']=cats or portal_reference.categories(group.get('genres'))
        group.setdefault('score',None)
        group['children'].sort(key=lambda e:(e['season'] or 0,e['episode'] or 0,e['title'].casefold()))
        group['episode_count']=len(group['children'])
        group['seasons']=sorted({r['season'] for r in group['children'] if r['season'] is not None})
        # These are numbering gaps in the currently imported Netzkino sample,
        # *not* proof that Netzkino offers or does not offer those episodes.
        gaps=[]
        for season in group['seasons']:
            present={r['episode'] for r in group['children'] if r['season']==season and r['episode']}
            if len(present)>1:
                missing=sorted(set(range(min(present),max(present)+1))-present)
                if missing:gaps.append({'season':season,'episodes':missing[:60]})
        group['numbering_gaps']=gaps
    if view=='movies':
        rows=[r for r in movies if (not query or query in r['title'].casefold()) and genre_match(r)]
        rows.sort(key=lambda r:(-float(r.get('updated',0)),r['title'].casefold()))
    elif view=='series':
        rows=[{k:v for k,v in group.items() if k!='children'} for group in series.values()
             if (not query or query in group['title'].casefold() or any(query in e['title'].casefold() for e in group['children']))
             and (genre_match(group) or any(genre_match(e) for e in group['children']))]
        rows.sort(key=lambda r:(-float(r.get('updated',0)),r['title'].casefold()))
    else:
        group=series.get(series_key)
        rows=[] if group is None else [r for r in group['children'] if (not query or query in r['title'].casefold()) and genre_match(r)]
    if sort=='rating' and view!='episodes':
        rows.sort(key=lambda r:(-((r.get('score') or {}).get('value',-1)),r['title'].casefold()))
    if sort=='title' and view!='episodes':
        rows.sort(key=lambda r:r['title'].casefold())
    elif sort=='year' and view!='episodes':
        rows.sort(key=lambda r:(-int(r.get('year') or 0),r['title'].casefold()))
    pool=movies if view=='movies' else list(series.values()) if view=='series' else \
        (series[series_key]['children'] if series_key in series else [])
    genre_counts=portal_reference.facets(pool)
    available_genres=[g['genre'] for g in genre_counts]
    counts={'movies':len(movies),'series':len(series),
            'episodes':sum(len(g['children']) for g in series.values())}
    group_header=None
    if view=='episodes' and series_key in series:
        group_header={k:v for k,v in series[series_key].items() if k!='children'}
    return {'items':rows[offset:offset+limit],'total':len(rows),'offset':offset,
            'view':view,'counts':counts,'series':group_header,'genres':available_genres,
            'genre_counts':genre_counts}
