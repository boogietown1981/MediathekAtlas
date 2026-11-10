"""Explicit, rights-aware third-party *catalogue* sources.

Internet Archive: documented, user-triggered metadata search.
Netzkino: manually supplied film page links ONLY. No scraping, API calls,
stream extraction or advertising bypass. Every imported offer is view-only;
metadata on its own never grants redistribution or offline-download rights.

The table is intentionally separate from downloadable MediathekView offers.
No portal item can accidentally enter a local download or stream queue.
"""
import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
from urllib.error import HTTPError, URLError

import core

MAX_SEARCH_RESULTS=30
MAX_RESPONSE_BYTES=2*1024*1024
SOURCES={
    'internet_archive':{
        'name':'Internet Archive','mode':'official_metadata_api',
        'automatic_download':False,
        'description':'Dokumentierte Metadaten-Suche. Rechte jedes Werks separat prüfen.'},
    'netzkino':{
        'name':'Netzkino','mode':'manual_links_only',
        'automatic_download':False,
        'description':'Nur selbst eingegebene Filmseiten; keine automatische Portalsuche.'}
}
SCHEMA="""
CREATE TABLE IF NOT EXISTS portal_items (
 id TEXT PRIMARY KEY,
 source TEXT NOT NULL,
 external_id TEXT NOT NULL,
 title TEXT NOT NULL,
 title_key TEXT NOT NULL,
 year INTEGER,
 page_url TEXT NOT NULL,
 metadata TEXT NOT NULL,
 discovered REAL NOT NULL,
 updated REAL NOT NULL,
 UNIQUE(source,external_id)
);
CREATE INDEX IF NOT EXISTS portal_items_source_updated ON portal_items(source,updated DESC);
CREATE INDEX IF NOT EXISTS portal_items_title ON portal_items(title_key,year);
CREATE TABLE IF NOT EXISTS portal_source_state (
 source TEXT PRIMARY KEY,
 last_query TEXT,
 last_success REAL,
 last_count INTEGER NOT NULL DEFAULT 0
);
"""


def initialize(c):
    c.executescript(SCHEMA)


def text(value,limit=300):
    if isinstance(value,list):value=next((v for v in value if isinstance(v,str) and v.strip()),'')
    if not isinstance(value,(str,int,float)):return ''
    value=re.sub(r'\s+',' ',str(value)).strip()
    return value[:limit]


def year_number(value):
    m=re.search(r'(?<!\d)(18\d{2}|19\d{2}|20\d{2})(?!\d)',text(value,64))
    return int(m.group(1)) if m else None


def title_key(value):
    normal=unicodedata.normalize('NFKD',text(value,300).casefold())
    return re.sub(r'[^\w]+',' ',''.join(ch for ch in normal if not unicodedata.combining(ch))).strip()


def netzkino_page(url):
    """No arbitrary destination, redirect or streaming URL is accepted."""
    try:
        p=urllib.parse.urlsplit(text(url,1500))
        port=p.port
        host=(p.hostname or '').lower()
    except ValueError:
        raise ValueError('Ungültiger Netzkino-Link') from None
    if (p.scheme!='https' or host not in ('netzkino.de','www.netzkino.de')
            or port not in (None,443) or p.username or p.password):
        raise ValueError('Nur öffentliche HTTPS-Filmseiten von netzkino.de zulässig')
    if len(p.path.strip('/'))<4 or p.path in ('/filme','/film','/movies','/'):
        raise ValueError('Bitte eine konkrete Netzkino-Filmseite angeben')
    # Never keep tracking parameters, tokens, fragments or arbitrary redirects.
    return urllib.parse.urlunsplit(('https','www.netzkino.de',p.path.rstrip('/'),'',''))


def internet_archive_id(value):
    ident=text(value,120)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,119}',ident):
        raise ValueError('Ungültiger Internet-Archive-Identifier')
    return ident


def entry(source,external_id,title,page_url,year=None,description='',
          license_url='',rights='',evidence=''):
    if source not in SOURCES:raise ValueError('Unbekannte Quelle')
    title=text(title,240)
    if len(title)<2:raise ValueError('Filmtitel fehlt')
    external_id=text(external_id,150)
    if not external_id:raise ValueError('Anbieterkennung fehlt')
    return {
        'id':hashlib.sha256((source+'\x00'+external_id).encode()).hexdigest()[:28],
        'source':source,'source_name':SOURCES[source]['name'],
        'external_id':external_id,'title':title,'year':year_number(year),
        'page_url':page_url,'description':text(description,2000),
        'license_url':text(license_url,500),'rights':text(rights,500),
        'evidence':evidence,'access':'official_site_only',
        'download_allowed':False,'available_until':None,
        'availability':'unverified','rights_verified':False,
    }


def manual_netzkino(title,url,year=None):
    page=netzkino_page(url)
    # ID based on canonical film page URL: re-import updates, not duplicates.
    external_id=hashlib.sha256(page.encode()).hexdigest()[:32]
    return entry('netzkino',external_id,title,page,year,
                 evidence='manually_entered_film_link')


def archive_query(query,rows=20):
    raw=text(query,120)
    words=re.findall(r'[\w-]{2,}',raw,flags=re.UNICODE)
    if not words:raise ValueError('Suchbegriff benötigt mindestens zwei Zeichen')
    words=words[:8]
    # Construct the query from safe tokens: never accept arbitrary Solr syntax.
    term=' '.join(words)
    clause='mediatype:movies AND (title:"'+term+'" OR description:"'+term+'")'
    n=max(1,min(MAX_SEARCH_RESULTS,int(rows)))
    params=[('q',clause),('output','json'),('rows',str(n)),('page','1')]
    params.extend(('fl[]',field) for field in (
        'identifier','title','year','date','description','licenseurl','rights'))
    return 'https://archive.org/advancedsearch.php?'+urllib.parse.urlencode(params)


def archive_document(doc):
    if not isinstance(doc,dict):raise ValueError('Ungültige Antwort von Internet Archive')
    response=doc.get('response')
    if not isinstance(response,dict) or not isinstance(response.get('docs'),list):
        raise ValueError('Internet Archive liefert keine Dokumentliste')
    results=[];seen=set()
    for raw in response['docs'][:MAX_SEARCH_RESULTS]:
        if not isinstance(raw,dict):continue
        try:ident=internet_archive_id(raw.get('identifier'))
        except ValueError:continue
        if ident in seen:continue
        name=text(raw.get('title'),240)
        if len(name)<2:continue
        seen.add(ident)
        url='https://archive.org/details/'+urllib.parse.quote(ident,safe='')
        results.append(entry('internet_archive',ident,name,url,
                             raw.get('year') or raw.get('date'),
                             raw.get('description'),raw.get('licenseurl'),
                             raw.get('rights'),evidence='official_archive_search_metadata'))
    return results


def search_archive(query,rows=20):
    """One user-triggered API request. No mass sync, no hidden follow-up calls."""
    url=archive_query(query,rows)
    try:
        with core.open_url(url,timeout=20) as response:
            data=response.read(MAX_RESPONSE_BYTES+1)
    except (HTTPError,URLError,TimeoutError) as exc:
        raise ValueError('Internet Archive derzeit nicht erreichbar') from exc
    if len(data)>MAX_RESPONSE_BYTES:raise ValueError('Internet Archive: Antwort zu groß')
    try:doc=json.loads(data)
    except (ValueError,UnicodeDecodeError):
        raise ValueError('Internet Archive: ungültige Metadatenantwort') from None
    return archive_document(doc)


def save(c,rows,query=None):
    """Atomic upsert. Never retire previously saved offers on partial failure."""
    now=time.time()
    ids=[]
    for row in rows:
        if row.get('source') not in SOURCES:raise ValueError('Unbekannte Quelle')
        if row.get('download_allowed') is not False:raise ValueError('Portalimporte dürfen keine Downloads freigeben')
        if len(row.get('title',''))<2:raise ValueError('Titel fehlt')
        ids.append(row['id'])
        c.execute("""INSERT INTO portal_items
            (id,source,external_id,title,title_key,year,page_url,metadata,discovered,updated)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,title_key=excluded.title_key,
                year=excluded.year,page_url=excluded.page_url,
                metadata=excluded.metadata,updated=excluded.updated""",
                (row['id'],row['source'],row['external_id'],row['title'],
                 title_key(row['title']),row.get('year'),row['page_url'],
                 json.dumps(row,ensure_ascii=False),now,now))
    if query and rows:
        c.execute("""INSERT INTO portal_source_state(source,last_query,last_success,last_count)
            VALUES (?,?,?,?) ON CONFLICT(source) DO UPDATE SET
              last_query=excluded.last_query,last_success=excluded.last_success,
              last_count=excluded.last_count""",
                  (rows[0]['source'],text(query),now,len(ids)))
    return ids


def listing(c,source='',query='',offset=0,limit=40):
    if source and source not in SOURCES:raise ValueError('Unbekannte Quelle')
    offset=max(0,min(int(offset),100000))
    limit=max(1,min(int(limit),60))
    where=[];params=[]
    if source:
        where.append('source=?');params.append(source)
    if text(query):
        where.append('title_key LIKE ?')
        fragment=title_key(query)[:90].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        params.append('%'+fragment+'%')
    clause=' WHERE '+' AND '.join(where) if where else ''
    count=c.execute('SELECT COUNT(*) FROM portal_items'+clause,params).fetchone()[0]
    rows=c.execute('SELECT metadata FROM portal_items'+clause+
                   ' ORDER BY updated DESC,title COLLATE NOCASE,id LIMIT ? OFFSET ?',
                   (*params,limit,offset)).fetchall()
    return {'total':count,'offset':offset,'items':[json.loads(r[0]) for r in rows]}


def state(c):
    count={s:0 for s in SOURCES}
    for name,num in c.execute('SELECT source,COUNT(*) FROM portal_items GROUP BY source'):
        if name in count:count[name]=num
    last={}
    for row in c.execute('SELECT source,last_query,last_success,last_count FROM portal_source_state'):
        last[row[0]]={'query':row[1],'checked':row[2],'count':row[3]}
    return {'sources':[{**info,'id':name,'items':count[name],
                        'last_search':last.get(name)} for name,info in SOURCES.items()],
            'total':sum(count.values()),'download_enabled':False}
