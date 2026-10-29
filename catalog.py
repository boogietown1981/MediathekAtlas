"""Local work/episode catalogue, alternative offers and conservative matching."""
import hashlib,json,re,sqlite3,time,unicodedata
import core
SCHEMA='''
CREATE TABLE IF NOT EXISTS downloaded_items(identity TEXT PRIMARY KEY,path TEXT,finished REAL);
CREATE TABLE IF NOT EXISTS artwork_checks(work_id TEXT PRIMARY KEY,next_try REAL);
CREATE TABLE IF NOT EXISTS artwork_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL);
CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY,title TEXT,kind TEXT,year INTEGER,show_key TEXT,meta TEXT,state TEXT DEFAULT 'pending',next_try REAL DEFAULT 0,attempts INTEGER DEFAULT 0,updated REAL,topic TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY,work_id TEXT,payload TEXT,special TEXT,rank INTEGER,seen REAL,active INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS offer_work ON offers(work_id,active,rank DESC);
CREATE TABLE IF NOT EXISTS series_templates(topic TEXT,provider TEXT,reference TEXT,meta TEXT,PRIMARY KEY(topic,provider,reference));
CREATE TABLE IF NOT EXISTS metadata_priority(work_id TEXT PRIMARY KEY,requested REAL);
CREATE INDEX IF NOT EXISTS work_queue ON works(kind,state,next_try);
CREATE INDEX IF NOT EXISTS work_type ON works(kind,title);
CREATE INDEX IF NOT EXISTS work_retry ON works(state,next_try);
CREATE INDEX IF NOT EXISTS work_show ON works(show_key);
CREATE TABLE IF NOT EXISTS work_genres(work_id TEXT,genre TEXT,PRIMARY KEY(work_id,genre));
CREATE INDEX IF NOT EXISTS genre_index ON work_genres(genre,work_id);
CREATE TABLE IF NOT EXISTS catalog_state(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS mesh_downloads(key TEXT PRIMARY KEY,node TEXT,name TEXT,state TEXT,until REAL,path TEXT,size INTEGER,hlc INTEGER,local TEXT,works TEXT);
CREATE TABLE IF NOT EXISTS mesh_download_works(work_id TEXT PRIMARY KEY,key TEXT);
CREATE TABLE IF NOT EXISTS mesh_results(work_id TEXT PRIMARY KEY,rank INTEGER,providers INTEGER,hlc INTEGER,node TEXT,payload TEXT);
'''
SPECIAL=re.compile(r'(?i)\b(audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung)\b|\((?:AD|DGS)\)')
SUFFIX=re.compile(r'(?i)\s*[([](?:mit\s+)?(?:audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung|AD|DGS|HD|UHD|4K)[)\]]\s*')
EP=re.compile(r'(?i)\bS(\d{1,2})[\s/._-]*E(\d{1,4})\b|\b(\d{1,2})x(\d{1,4})\b|\bStaffel\s*(\d+)\D{1,20}Folge\s*(\d+)\b')
GENRES={'Krimi':r'\b(?:krimi|kriminalfilm|krimiserie|tatort|polizeiruf)\b','Komödie':r'\b(?:komödie|comedy|sitcom)\b','Drama':r'\b(?:drama|melodram)\b','Thriller':r'\bthriller\b','Science-Fiction':r'\b(?:science.fiction|sci.fi)\b','Fantasy':r'\bfantasy\b','Animation':r'\b(?:animation|zeichentrick|anime)\b','Dokumentation':r'\b(?:dokumentation|dokumentarfilm|dokumentarserie|doku)\b','Kinder & Familie':r'\b(?:kinderfilm|kinderserie|familienfilm)\b','Romantik':r'\b(?:liebesfilm|romantik|romantische komödie)\b'}

def key(s):
    s=unicodedata.normalize('NFKD',str(s or '').casefold())
    return re.sub(r'[^\w]+',' ',''.join(c for c in s if not unicodedata.combining(c))).strip()
def digest(s):return hashlib.sha256(s.encode()).hexdigest()[:28]
def cleaned(s):return re.sub(r'\s+',' ',SUFFIX.sub('',core.clean(s))).strip(' -')
def special(row):
    m=SPECIAL.search(str(row.get('title',''))+' '+str(row.get('topic','')))
    return ('Gebärdensprache' if m and re.search(r'(?i)gebär|DGS',m.group()) else 'Audiodeskription') if m else ''
def links(row):
    out=[]
    for field,label,q in [('url_video_hd','HD',720),('url_video','Standard',480),('url_video_low','Klein',240)]:
        url=row.get(field)
        if url and url not in [x['url'] for x in out]:
            match=re.search(r'(?i)(2160|1080|720|480|360)p\b',url);height=int(match.group(1)) if match else 0
            out.append({'url':url,'quality':label,'height_hint':height,'supported':not re.search(r'(?i)\.(?:m3u8|mpd)(?:\?|$)',url),'score':height or q})
    return sorted(out,key=lambda x:(x['supported'],x['score']),reverse=True)
def ranking(row):
    l=links(row)
    return (0 if special(row) else 1000000)+(100000 if l and l[0]['supported'] else 0)+(l[0]['score'] if l else 0)

def seed(row):
    title=cleaned(row.get('title'));topic=cleaned(row.get('topic'));desc=core.clean(row.get('description',''));m=core.identify({**row,'title':title})
    ep=EP.search(title)
    if ep:
        nums=[int(x) for x in ep.groups() if x is not None]
        m.update(kind='series',year=None,season=nums[0],episode=nums[1],title=topic or EP.sub('',title).strip(' ()-'),episode_title=title)
    elif key(topic) in ('tatort','polizeiruf 110'):m.update(kind='series',title=topic,episode_title=title,year=None)
    if m['kind']=='unknown':
        intro=topic+' '+re.sub(r'(?i)\b(?:drama|thriller|western)\b','',desc[:220])
        if re.search(r'(?i)\b(?:spielfilm|fernsehfilm|komödie|thriller|drama|western|liebesfilm|dokumentarfilm)\b',intro):m['kind']='movie'
        elif re.search(r'(?i)\b(?:serie|serien|sitcom|dokumentarserie|fernsehserie|krimiserie)\b',intro):m.update(kind='series',title=topic or title,episode_title=title)
        elif re.search(r'(?i)\b(?:nachrichten|tagesschau|wetter|sportstudio|trailer|teaser|podcast|pressekonferenz|tagesthemen|gottesdienst|magazin)\b',topic+' '+title):m['kind']='other'
    if re.search(r'(?i)^\s*(?:trailer|teaser|vorschau)\b',title):m.update(kind='other',title=title,year=None,season=None,episode=None)
    if m['kind']=='movie' and not m.get('year'):
        y=re.search(r'\((19\d{2}|20\d{2})\)$',title)
        if y:m.update(year=int(y.group(1)),title=title[:y.start()].strip())
    genre_hint=topic
    # Narrative words such as 'Drama beim Fußball' are not genre labels.
    if re.match(r'(?i)^(?:Drama|Thriller|Komödie|Dokumentarfilm|Krimi|Science-Fiction|Fantasy|Animation)\s*(?:[.,|:·]|(?:Deutschland|Frankreich|USA|Großbritannien|Österreich|Schweiz)\b|(?:19|20)\d{2}\b)',desc):genre_hint+=' '+desc[:100]
    m['genres']=[g for g,rx in GENRES.items() if re.search(rx,genre_hint,re.I)]
    m.update(genre_source='Senderhinweis' if m['genres'] else 'Unbekannt',title=cleaned(m['title']),episode_title=cleaned(m.get('episode_title','')))
    return m

def origin_meta(c,row):
    """Seed metadata of an offer as on import (including a unique series template) and the template used."""
    m=seed(row);template=None
    if m['kind'] in ('unknown','series') and 300<=int(row.get('duration') or 0)<=3900:
        options=c.execute('SELECT meta FROM series_templates WHERE topic=? LIMIT 2',(key(row.get('topic')),)).fetchall()
        if len(options)==1:template=json.loads(options[0][0])
    if template:
        m.update(kind='series',episode_title=m.get('episode_title') or row['title'])
        for k in ('title','year','provider','reference_id','poster','genres','genre_source'):m[k]=template.get(k)
        m['genres']=normalized_genres(m.get('genres'))
    return m,template

def origin_ids(c,work_id):
    """Work IDs the offers of a (possibly merged) work had on import; the same on every instance."""
    out=set()
    for (payload,) in c.execute('SELECT payload FROM offers WHERE work_id=?',(work_id,)).fetchall():
        row=json.loads(payload)
        try:out.add(identity(row,origin_meta(c,row)[0]))
        except (KeyError,TypeError,ValueError):continue
    return sorted(out) or [work_id]

def identity(row,m):
    base=m['kind']+'|'+key(m['title'])+'|'+str(m.get('year') or '?')
    if m['kind']=='series':
        ep='s%s-e%s'%(m['season'],m['episode']) if m.get('season') is not None and m.get('episode') is not None else key(m.get('episode_title') or row['title'])
        return digest(base+'|'+ep)
    if m.get('year'):return digest(base)
    desc=key(row.get('description'))[:180]
    evidence=desc if len(desc)>45 else str(row.get('url_website') or row.get('url_video') or row.get('_id'))
    return digest(base+'|'+evidence)
def showkey(m):return digest(key(m['title'])+'|'+str(m.get('year') or '?')) if m['kind']=='series' else ''
def set_state(c,k,v):c.execute('INSERT OR REPLACE INTO catalog_state VALUES(?,?)',(k,json.dumps(v)))
def get_state(c,k,default=None):
    r=c.execute('SELECT value FROM catalog_state WHERE key=?',(k,)).fetchone();return json.loads(r[0]) if r else default

def ingest(c,rows,seen=None):
    seen=time.time() if seen is None else seen;ids=[]
    for raw in rows:
        row=dict(raw)
        if not links(row) or not row.get('title'):continue
        oid=digest(str(row.get('channel'))+'|'+str(row.get('url_video') or row.get('url_video_hd') or row.get('url_website'))+'|'+row['title']);row['_id']=oid
        m,template=origin_meta(c,row)
        wid=identity(row,m)
        old=c.execute('SELECT work_id FROM offers WHERE id=?',(oid,)).fetchone()
        if old:wid=old[0]
        cur=c.execute('INSERT OR IGNORE INTO works(id,title,kind,year,show_key,meta,updated) VALUES(?,?,?,?,?,?,?)',(wid,m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),seen))
        c.execute('UPDATE works SET topic=? WHERE id=?',(row.get('topic',''),wid))
        if cur.rowcount:
            if template:c.execute("UPDATE works SET state='identified' WHERE id=?",(wid,))
            for genre in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,genre))
        c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,special=excluded.special,rank=excluded.rank,seen=excluded.seen,active=1',(oid,wid,json.dumps(row),special(row),ranking(row),seen));ids.append(oid)
    return ids

def source(c,oid):
    r=c.execute('SELECT payload FROM offers WHERE id=?',(oid,)).fetchone();return json.loads(r[0]) if r else None

def download_identity(m):
    return canonical(m) or digest(json.dumps([m.get('kind'),key(m.get('title','')),m.get('year'),m.get('season'),m.get('episode')]))

def mark_downloaded(c,job):
    identities={download_identity(job['metadata'])}
    source_id=job.get('source',{}).get('_id')
    found=c.execute('SELECT work_id FROM offers WHERE id=?',(source_id,)).fetchone()
    if found:identities.add(found[0])
    for identity in identities:c.execute('INSERT OR REPLACE INTO downloaded_items VALUES(?,?,?)',(identity,job.get('path') or job.get('target'),time.time()))

def mesh_download_row(c,meta,work_id=None):
    """Latest Verbund download record for a title: by download identity, else by the sender's work IDs."""
    r=c.execute('SELECT * FROM mesh_downloads WHERE key=?',(download_identity(meta),)).fetchone()
    if not r and work_id:r=c.execute('SELECT d.* FROM mesh_download_works w JOIN mesh_downloads d ON d.key=w.key WHERE w.work_id=?',(work_id,)).fetchone()
    return r

def mesh_download(c,meta,work_id=None):
    """Download state of this title on another instance of the Verbund, or None."""
    r=mesh_download_row(c,meta,work_id)
    r=r and (r['node'],r['name'],r['state'],r['until'],r['path'],r['local'])
    if not r or r[0]==get_state(c,'mesh_node_id') or r[2]=='release' or (r[2]=='claim' and r[3]<time.time()):return None
    return {'name':r[1],'state':'loading' if r[2]=='claim' else 'local' if r[5] else 'transfer' if r[4] else 'remote'}

def item(c,w):
    r=c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC LIMIT 1',(w['id'],)).fetchone()
    if not r:return None
    row=json.loads(r['payload']);count=c.execute('SELECT COUNT(*) FROM offers WHERE work_id=?',(w['id'],)).fetchone()[0]
    return {'id':r['id'],'work_id':w['id'],'source':row,'metadata':json.loads(w['meta']),'offer_count':count,'available':bool(r['active']),'state':w['state'],'downloaded':bool(c.execute('SELECT 1 FROM downloaded_items WHERE identity=?',(w['id'],)).fetchone()),'mesh_download':mesh_download(c,json.loads(w['meta']),w['id']),'special':r['special'],'best':links(row)[0] if links(row) else None,'show_key':w['show_key'],'links':links(row)}

def alternatives(c,wid):
    w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    if not w:raise ValueError('Werk nicht gefunden')
    out=[]
    for r in c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC',(wid,)):
        row=json.loads(r['payload']);out.append({'id':r['id'],'work_id':wid,'source':row,'metadata':json.loads(w['meta']),'special':r['special'],'available':bool(r['active']),'links':links(row)})
    return out

def listing(c,query='',kind='',genre='',show='',offset=0,archive=False,state='',sort='title',downloaded='hide',collection=''):
    clauses=[];args=[]
    if downloaded=='hide':clauses.append('NOT EXISTS(SELECT 1 FROM downloaded_items di WHERE di.identity=w.id)')
    elif downloaded=='only':clauses.append('EXISTS(SELECT 1 FROM downloaded_items di WHERE di.identity=w.id)')
    if not archive:clauses.append('EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)')
    if collection in ('cinema','series'):
        clauses.append("w.kind=? AND w.state IN ('matched','manual','identified') AND CAST(json_extract(w.meta,'$.rating') AS REAL)>=7.5 AND CAST(json_extract(w.meta,'$.rating') AS REAL)<=10 AND ((COALESCE(json_extract(w.meta,'$.rating_source'),json_extract(w.meta,'$.provider')) IN ('IMDb','IMDb Offline','OMDb') AND CAST(json_extract(w.meta,'$.votes') AS INTEGER)>=10000) OR (json_extract(w.meta,'$.rating_source')='TMDB' AND CAST(json_extract(w.meta,'$.votes') AS INTEGER)>=1000))")
        args.append('movie' if collection=='cinema' else 'series')
    if kind:clauses.append('w.kind=?');args.append(kind)
    elif not query and not state:clauses.append("w.kind IN ('movie','series')")
    if state=='recognized':clauses.append("w.state IN ('matched','manual','identified')")
    elif state=='pending':clauses.append("w.state IN ('pending','retry')")
    elif state=='review':clauses.append("w.state='review'")
    elif state=='format':clauses.append("w.state='format'")
    if query:clauses.append('(w.title LIKE ? OR w.topic LIKE ?)');args.extend(['%'+query[:150]+'%']*2)
    if genre:
        if genre=='Unbekannt':clauses.append('NOT EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id)')
        else:clauses.append('EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre=?)');args.append(genre)
    if show:clauses.append('w.show_key=?');args.append(show)
    where=' AND '.join(clauses);offset=max(0,int(offset));grouping="CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END" if not show else 'w.id'
    if show:
        rows=c.execute('SELECT w.* FROM works w WHERE '+where,args).fetchall()
        def episode_order(w):
            m=json.loads(w['meta']);return (m.get('season') if m.get('season') is not None else 99999,m.get('episode') if m.get('episode') is not None else 99999,m.get('episode_title',''))
        rows.sort(key=episode_order);out=[]
        for w in rows[offset:offset+48]:
            entry=item(c,w)
            if entry:entry.update(episodes=1,series_parent=False);out.append(entry)
        return {'items':out,'total':len(rows),'offset':offset}
    base='SELECT MIN(w.id) AS id,COUNT(*) AS episodes FROM works w WHERE '+where+' GROUP BY '+grouping
    total=c.execute('SELECT COUNT(*) FROM ('+base+')',args).fetchone()[0]
    rows=c.execute('SELECT g.*,w.title FROM ('+base+') g JOIN works w ON w.id=g.id ORDER BY '+({'title':'w.title COLLATE NOCASE','year':'w.year DESC,w.title COLLATE NOCASE','recognized':"CASE WHEN w.state IN ('manual','matched') THEN 0 WHEN w.state='identified' THEN 1 ELSE 2 END,w.title COLLATE NOCASE"}.get(sort,'w.title COLLATE NOCASE'))+' LIMIT 48 OFFSET ?',args+[offset]).fetchall();out=[]
    for row in rows:
        w=c.execute('SELECT * FROM works WHERE id=?',(row['id'],)).fetchone();entry=item(c,w)
        if entry:entry.update(episodes=row['episodes'],series_parent=w['kind']=='series' and not show);out.append(entry)
    return {'items':out,'total':total,'offset':offset}

def tree(c):
    return [dict(r) for r in c.execute("SELECT w.kind,COALESCE(g.genre,'Unbekannt') genre,COUNT(DISTINCT CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END) n FROM works w LEFT JOIN work_genres g ON g.work_id=w.id WHERE EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) GROUP BY w.kind,g.genre")]

def stats(c):
    counts={r[0]:r[1] for r in c.execute('SELECT kind,COUNT(*) FROM works GROUP BY kind')}
    return {'types':counts,'works':sum(counts.values()),'offers':c.execute('SELECT COUNT(*) FROM offers WHERE active=1').fetchone()[0],
       'identified':c.execute("SELECT COUNT(*) FROM works WHERE state='identified'").fetchone()[0],
       'matched':c.execute("SELECT COUNT(*) FROM works WHERE state IN ('matched','manual')").fetchone()[0],
       'pending':c.execute("SELECT COUNT(*) FROM works WHERE kind!='other' AND state IN ('pending','retry')").fetchone()[0],
       'review':c.execute("SELECT COUNT(*) FROM works WHERE state='review'").fetchone()[0],
       'formats':c.execute("SELECT COUNT(*) FROM works WHERE state='format'").fetchone()[0],
       'sync':get_state(c,'sync',{'phase':'waiting'}),'last_complete':get_state(c,'last_complete',0)}

def canonical(m):
    if m.get('state')=='work_identified':return None
    if m.get('kind')=='series' and not m.get('episode_verified') and m.get('state')!='user_confirmed':return None
    if not m.get('reference_id') or m.get('provider') not in ('TMDB','OMDb','TVDB','IMDb Offline'):return None
    base=('OMDb' if m['provider']=='IMDb Offline' else m['provider'])+'|'+m['kind']+'|'+str(m['reference_id'])
    if m['kind']=='series':
        if m.get('season') is None or m.get('episode') is None:return None
        base+='|s%s-e%s'%(m['season'],m['episode'])
    return digest(base)

def save_metadata(c,wid,m,state='manual'):
    m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
    row=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    if not row:return
    previous=json.loads(row['meta'])
    if any(previous.get(k)!=m.get(k) for k in ('title','kind','year','reference_id','provider')):
        c.execute('DELETE FROM artwork_checks WHERE work_id=?',(wid,))
        m.pop('fanart',None);m.pop('artwork_provider',None)
        for field in ('networks','studios','ratings','imdb_id','discovery_enriched'):
            if m.get(field)==previous.get(field):m.pop(field,None)
    dest=canonical(m) or wid;old=c.execute('SELECT state,meta FROM works WHERE id=?',(dest,)).fetchone()
    if old and old['state']=='manual' and state!='manual':m=json.loads(old['meta']);state='manual'
    c.execute('INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,kind=excluded.kind,year=excluded.year,show_key=excluded.show_key,meta=excluded.meta,state=excluded.state,updated=excluded.updated',(dest,m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),state,time.time()))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(dest,))
    m['genres']=normalized_genres(m.get('genres'))
    c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),dest))
    for genre in m.get('genres',[]):c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(dest,genre))
    if dest!=wid:
        c.execute('INSERT OR IGNORE INTO downloaded_items SELECT ?,path,finished FROM downloaded_items WHERE identity=?',(dest,wid))
        c.execute('UPDATE offers SET work_id=? WHERE work_id=?',(dest,wid));c.execute('DELETE FROM work_genres WHERE work_id=?',(wid,));c.execute('DELETE FROM works WHERE id=?',(wid,))
    return dest

def auto_choice(meta,rows):
    import matching
    return matching.choose(meta,rows)

def work_choice(meta,rows):
    import matching
    return matching.choose(meta,rows,work_only=True)

def propagate_series(c,old_show,m):
    # Transfer work metadata, never a sibling's episode number or episode plot.
    common={k:m[k] for k in ('title','year','provider','reference_id','poster','genres','genre_source') if k in m}
    for row in c.execute("SELECT * FROM works WHERE show_key=? AND state NOT IN ('manual','matched')",(old_show,)).fetchall():
        own=json.loads(row['meta'])
        # Every recognised episode propagates again; rewriting unchanged siblings made this quadratic per series.
        if row['state']=='identified' and all(own.get(k)==v for k,v in common.items()):continue
        own.update(common)
        save_metadata(c,row['id'],own,'identified')

def prioritize(c,ids=None,show=''):
    count=0
    if show:ids=[r[0] for r in c.execute('SELECT id FROM works WHERE show_key=?',(show,))]
    for wid in (ids or [])[:1000]:
        row=c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()
        if not row or row[0] in ('manual','matched'):continue
        if row[0]=='format':
            # An explicit request scans a format contribution once and keeps it out of the format pass.
            m=json.loads(c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()[0]);m['scan_requested']=True
            c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
        c.execute("UPDATE works SET state=CASE WHEN state='identified' THEN state ELSE 'pending' END,next_try=0 WHERE id=?",(wid,))
        c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(wid,time.time()));count+=1
    return count

# Recurring broadcast formats (news, regional and service magazines). Their single contributions are
# not in any film database; they are grouped under their format and not queried (diagnosis 0.4.7).
FORMAT_WORDS=re.compile(r'(?i)\b(?:nachrichten|tagesschau|tagesthemen|aktuell|journal|heute|wetter|sportschau|sportstudio|magazin|lokalzeit|abendschau|landesschau|hessenschau|regional|drehscheibe|morgenmagazin|mittagsmagazin|pressekonferenz|gottesdienst|podcast|kompakt|update|live)\b')
FORMAT_GENERIC={'film','filme','spielfilm','serien','serie','fernsehfilm','mediathek','zdf','ard','3sat','arte','kika','kino','dokumentation','dokumentationen','doku','dokus','reportage','sonstiges','sonstige','unterhaltung','filme im ersten'}
TRAILER=re.compile(r'(?i)^\s*(?:trailer|teaser|vorschau)\b')

def format_contribution(m,source,topic_works):
    """True for a single contribution of a recurring format, e.g. one edition of "aktuell (16 Uhr)"."""
    topic=cleaned(source.get('topic'));title=cleaned(source.get('title'))
    if m.get('kind') not in ('unknown','other') or m.get('scan_requested') or not topic or key(topic) in FORMAT_GENERIC or key(topic)==key(title):return False
    if TRAILER.search(title):return False
    if FORMAT_WORDS.search(topic):return topic_works>=2
    return int(source.get('duration') or 0)<600 and topic_works>=3

def assign_formats(c,limit=500):
    """Group news and magazine contributions under their format and take them out of the provider scan."""
    import broadcaster
    cursor=get_state(c,'format_cursor',0)
    if cursor=='complete':return 0,0
    rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
    counts={};assigned=0
    for row in rows:
        cursor=row['rid']
        if row['kind'] not in ('unknown','other') or row['state'] not in ('pending','retry'):continue
        best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not best:continue
        source=json.loads(best[0]);m=json.loads(row['meta']);topic=row['topic'] or source.get('topic') or ''
        if topic not in counts:counts[topic]=c.execute('SELECT COUNT(*) FROM works WHERE topic=?',(topic,)).fetchone()[0]
        if not format_contribution(m,source,counts[topic]):continue
        fmt=cleaned(source.get('topic'));hints=broadcaster.genres(fmt,source.get('title',''))
        m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
        m.update(kind='series',title=fmt,episode_title=cleaned(source.get('title')),year=None,season=m.get('season'),episode=m.get('episode'),provider='Sendung',reference_id=None,
                 state='format',genres=normalized_genres(hints or m.get('genres')),genre_source='Sender (abgeleitet)' if hints else m.get('genre_source','Unbekannt'),
                 reason='Beitrag der Sendung „'+fmt+'“; wird nicht mit Filmdatenbanken abgeglichen.')
        c.execute("UPDATE works SET title=?,kind='series',year=NULL,show_key=?,meta=?,state='format',next_try=0 WHERE id=?",(fmt,showkey(m),json.dumps(m),row['id']))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(row['id'],))
        for g in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(row['id'],g))
        assigned+=1
    set_state(c,'format_cursor',cursor if rows else 'complete')
    return len(rows),assigned

def restart_formats(c):set_state(c,'format_cursor',0)

def recognition(c):
    """Recognition per channel and state; formats are counted separately from open works."""
    try:
        rows=c.execute("SELECT COALESCE(json_extract(o.payload,'$.channel'),'') channel,w.state,COUNT(DISTINCT w.id) n FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 WHERE w.kind!='other' GROUP BY channel,w.state").fetchall()
    except sqlite3.OperationalError:
        rows=c.execute("SELECT '' channel,w.state,COUNT(*) n FROM works w WHERE w.kind!='other' GROUP BY w.state").fetchall()
    out={}
    for r in rows:
        d=out.setdefault(r['channel'] or 'Unbekannt',{'channel':r['channel'] or 'Unbekannt','works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0})
        state=r['state'];d['works']+=r['n']
        key_={'matched':'matched','manual':'matched','identified':'identified','format':'format','review':'review'}.get(state,'open');d[key_]+=r['n']
    return sorted(out.values(),key=lambda d:-d['works'])

def reclassify_batch(c,limit=500):
    cursor=get_state(c,'reclassify_cursor_v030',0)
    if cursor=='complete':return 0
    rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
    for row in rows:
        cursor=row['rid']
        if row['state'] in ('manual','matched','identified'):continue
        best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not best:continue
        source=json.loads(best[0]);m=seed(source)
        c.execute("UPDATE works SET title=?,kind=?,year=?,show_key=?,meta=?,state='pending',next_try=0,topic=? WHERE id=?",(m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),source.get('topic',''),row['id']))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(row['id'],))
        for g in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(row['id'],g))
    set_state(c,'reclassify_cursor_v030',cursor if rows else 'complete')
    return len(rows)

def normalized_genres(values):
    from metadata import genres
    return genres(values or [])

def merge_genre_spellings(c):
    """Fold genres stored under older or provider-specific spellings into one canonical name."""
    from metadata import genre_names
    changes={}
    for (genre,) in c.execute('SELECT DISTINCT genre FROM work_genres').fetchall():
        names=genre_names(genre)
        if names!=[genre]:changes[genre]=names
    touched=set()
    for genre,names in changes.items():
        ids=[r[0] for r in c.execute('SELECT work_id FROM work_genres WHERE genre=?',(genre,))]
        for wid in ids:
            for name in names:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,name))
        c.execute('DELETE FROM work_genres WHERE genre=?',(genre,));touched.update(ids)
    for wid in touched:
        row=c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()
        if not row:continue
        m=json.loads(row[0] or '{}');m['genres']=normalized_genres(m.get('genres'))
        c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
    for topic,provider,ref,meta in c.execute('SELECT topic,provider,reference,meta FROM series_templates').fetchall():
        m=json.loads(meta or '{}');g=normalized_genres(m.get('genres'))
        if g!=m.get('genres'):m['genres']=g;c.execute('UPDATE series_templates SET meta=? WHERE topic=? AND provider=? AND reference=?',(json.dumps(m),topic,provider,ref))
    return len(changes)

def initialize(c):
    c.executescript(SCHEMA)
    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:c.execute("ALTER TABLE works ADD COLUMN topic TEXT DEFAULT ''")
    if not get_state(c,'artwork_discovery_refresh_v047',False):
        c.execute('DELETE FROM artwork_checks');c.execute('DELETE FROM artwork_cache');set_state(c,'artwork_discovery_refresh_v047',True)
    c.execute('CREATE INDEX IF NOT EXISTS work_topic ON works(topic)')
    if not get_state(c,'genre_spellings_v053',False):merge_genre_spellings(c);set_state(c,'genre_spellings_v053',True)

def review_listing(c,query='',state='open',offset=0):
    """Flat work/episode list: do not hide unresolved episodes behind a series parent."""
    clauses=['EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)'];args=[]
    if state=='open':clauses.append("w.state IN ('pending','retry','review','identified')")
    elif state in ('pending','retry','review','identified','manual','matched','format'):clauses.append('w.state=?');args.append(state)
    if query:clauses.append('(w.title LIKE ? OR w.topic LIKE ?)');args.extend(['%'+query[:150]+'%']*2)
    where=' AND '.join(clauses);offset=max(0,int(offset))
    total=c.execute('SELECT COUNT(*) FROM works w WHERE '+where,args).fetchone()[0]
    rows=c.execute('SELECT w.* FROM works w WHERE '+where+' ORDER BY w.title COLLATE NOCASE,w.id LIMIT 48 OFFSET ?',args+[offset]).fetchall()
    return {'items':[entry for w in rows for entry in [item(c,w)] if entry],'total':total,'offset':offset}
