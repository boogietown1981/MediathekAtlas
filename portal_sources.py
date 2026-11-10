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
from pathlib import PurePosixPath

import core
# ArchiveMedia v0.10.53 helpers, vendored with original MIT license.
from vendor.archive_portals import catalog_identity as archive_identity
from vendor.archive_portals import item_language_hints as archive_languages
from vendor.archive_portals import unified_inventory as archive_inventory
from vendor.archive_portals import video_triage as archive_triage
from vendor.archivemedia import linguistics as archive_tracks

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
CREATE TABLE IF NOT EXISTS portal_archive_details (
 item_id TEXT PRIMARY KEY REFERENCES portal_items(id) ON DELETE CASCADE,
 payload TEXT NOT NULL,
 checked REAL NOT NULL
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


MAX_ARCHIVE_FILES=350
MAX_VISIBLE_VARIANTS=150


def _file_size(value):
    try:
        number=int(value)
        return number if 0<=number<2**63 else None
    except (TypeError,ValueError,OverflowError):return None


def _episode_fields(name):
    """Only explicitly labelled episode tokens are eligible for episode hints."""
    match=archive_identity.EPISODE.search(name)
    if not match:return {'kind':'movie','season':None,'episode':None}
    try:
        return {'kind':'series',
                'season':int(match.group('s') or match.group('s2') or 1),
                'episode':int(match.group('e') or match.group('e2') or match.group('e3'))}
    except (TypeError,ValueError):return {'kind':'movie','season':None,'episode':None}


def archive_detail_document(identifier,doc):
    """Reuse ArchiveMedia recognition to distinguish items and file variants.

    An Archive.org item is one *upload*, not necessarily one movie or series.
    A filename is a claim, not proof of language or episode identity.
    """
    identifier=internet_archive_id(identifier)
    if not isinstance(doc,dict) or not isinstance(doc.get('metadata'),dict):
        raise ValueError('Internet Archive: Metadaten des Eintrags fehlen')
    meta=doc['metadata']
    raw_files=doc.get('files')
    if not isinstance(raw_files,list):raw_files=[]
    identity=archive_identity.resolve_item(meta,identifier)
    item_title=text(meta.get('title') or identity['title'],240)
    hints=archive_languages.infer(meta)
    candidates=[]
    subtitles=[]
    for raw in raw_files[:MAX_ARCHIVE_FILES]:
        if not isinstance(raw,dict) or not isinstance(raw.get('name'),str):continue
        filename=text(raw['name'],900)
        if not filename:continue
        category,role,reason=archive_inventory.classify(filename,raw)
        if category=='video':candidates.append((filename,raw,role,reason))
        elif role=='sidecar':subtitles.append({'name':filename,'size':_file_size(raw.get('size'))})
    one_video=len(candidates)==1 and len(raw_files)<=MAX_ARCHIVE_FILES
    variants=[]
    for filename,raw,role,reason in candidates[:MAX_VISIBLE_VARIANTS]:
        parsed=_episode_fields(filename)
        parsed['title']=PurePosixPath(filename).stem
        resolved=archive_identity.resolve_variant(
            filename,item_title,identity,parsed,meta,one_video=one_video)
        track_hints=archive_tracks.parse_filename_tracks(filename)
        sidecars=archive_tracks.match_sidecar_subtitles(
            filename,subtitles) if subtitles else []
        # These languages are only declared in titles/filenames, NOT verified
        # codec/track metadata. No FFprobe and no video bytes are requested.
        variants.append({
            'filename':filename,'title':text(resolved.get('title'),240),
            'identity_origin':text(resolved.get('identity_origin'),90),
            'identity_confidence':text(resolved.get('identity_confidence'),30),
            'identity_warning':text(resolved.get('identity_warning'),350),
            'kind':resolved.get('kind') if resolved.get('kind') in ('movie','series') else 'unknown',
            'season':resolved.get('season'),'episode':resolved.get('episode'),
            'file_role':role,'file_role_reason':reason,
            'format':text(raw.get('format'),100),
            'size_bytes':_file_size(raw.get('size')),
            'length_claim':text(raw.get('length'),32),
            'source':text(raw.get('source'),30),
            'original':text(raw.get('original'),400),
            'audio_hint_languages':track_hints['audio'],
            'audio_hint_origin':track_hints['audio_origin'],
            'subtitle_hint_languages':track_hints['subtitles'],
            'subtitle_hint_origin':track_hints['subtitle_origin'],
            'sidecar_subtitles':sidecars[:12],
            'languages_verified':False,
        })
    group_format,format_reason=archive_triage.classify(
        item_title,filenames=[v[0] for v in candidates[:50]])
    result={
        'source':'internet_archive','external_id':identifier,
        'page_url':'https://archive.org/details/'+urllib.parse.quote(identifier,safe=''),
        'title':item_title,'normalized_title':identity['title'],
        'identity_origin':identity['origin'],
        'identity_confidence':identity['confidence'],
        'year':year_number(meta.get('year') or meta.get('date')),
        'description':archive_identity.clean(meta.get('description'))[:2000],
        'license_url':text(meta.get('licenseurl'),500),
        'rights':text(meta.get('rights'),500),
        'upload_language_codes':hints['archive_language_codes'].split(',') if hints['archive_language_codes'] else [],
        'upload_audio_hint_languages':hints['audio_hint_languages'].split(',') if hints['audio_hint_languages'] else [],
        'upload_subtitle_hint_languages':hints['subtitle_hint_languages'].split(',') if hints['subtitle_hint_languages'] else [],
        'upload_language_evidence':{
            'audio':hints['audio_hint_source'],
            'reason':hints['audio_hint_reason'],
            'subtitle':hints['subtitle_hint_source']},
        'content_format_hint':group_format,
        'content_format_reason':format_reason,
        'video_variants':variants,
        'video_files_found':len(candidates),
        'files_in_manifest':len(raw_files),
        'files_inspected':min(len(raw_files),MAX_ARCHIVE_FILES),
        'variants_displayed':len(variants),
        'inventory_complete':len(raw_files)<=MAX_ARCHIVE_FILES and len(candidates)<=MAX_VISIBLE_VARIANTS,
        'download_allowed':False,'rights_verified':False,
        'availability':'unverified',
        'evidence':'ArchiveMedia v0.10.53 / Internet Archive metadata; keine Inhaltsprüfung',
    }
    # A collection of separate episodes is not one confirmed "movie" even if
    # IA's top-level mediatype happens to be movies.
    if any(v['kind']=='series' for v in variants):
        result['content_format_hint']='series_or_mixed_upload'
        result['content_format_reason']='Mindestens ein Dateiname mit expliziter Episodenkennung'
    return result


def fetch_archive_detail(identifier):
    """One user-requested call to the official Archive metadata endpoint."""
    identifier=internet_archive_id(identifier)
    url='https://archive.org/metadata/'+urllib.parse.quote(identifier,safe='')
    try:
        with core.open_url(url,timeout=25) as response:
            raw=response.read(MAX_RESPONSE_BYTES+1)
    except (HTTPError,URLError,TimeoutError) as exc:
        raise ValueError('Internet Archive: Details derzeit nicht erreichbar') from exc
    if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('Internet Archive: Manifest zu groß (nicht importiert)')
    try:doc=json.loads(raw)
    except (ValueError,UnicodeDecodeError):
        raise ValueError('Internet Archive: ungültiges Manifest') from None
    return archive_detail_document(identifier,doc)


def save_archive_detail(c,item_id,detail):
    """Preserve other variants/metadata and never touch video download queue."""
    row=c.execute('SELECT source,external_id FROM portal_items WHERE id=?',(item_id,)).fetchone()
    if not row or row[0]!='internet_archive' or row[1]!=detail.get('external_id'):
        raise ValueError('Internet-Archive-Katalogeintrag nicht gefunden')
    c.execute("""INSERT INTO portal_archive_details(item_id,payload,checked) VALUES(?,?,?)
        ON CONFLICT(item_id) DO UPDATE SET payload=excluded.payload,checked=excluded.checked""",
        (item_id,json.dumps(detail,ensure_ascii=False),time.time()))


def archive_saved_detail(c,item_id):
    row=c.execute('SELECT payload,checked FROM portal_archive_details WHERE item_id=?',(item_id,)).fetchone()
    return {'detail':json.loads(row[0]),'checked':row[1]} if row else {'detail':None,'checked':None}


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
    items=[json.loads(r[0]) for r in rows]
    # Safe, read-only hint: only exact movie title PLUS exact known year.
    # A hint is never an automatic metadata merge or download permission.
    names=sorted({x['title'] for x in items if x.get('year')})
    if names and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='works'").fetchone():
        placeholders=','.join('?' for _ in names)
        matches=c.execute("SELECT id,title,year FROM works WHERE kind='movie' AND title IN ("+
                          placeholders+") LIMIT 200",names).fetchall()
        indexed={(r[1],r[2]):r[0] for r in matches}
        for item in items:
            item['local_work_id']=indexed.get((item['title'],item.get('year')))
    return {'total':count,'offset':offset,'items':items}


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
