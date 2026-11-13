"""Local work/episode catalogue, alternative offers and conservative matching."""
import hashlib,json,re,sqlite3,threading,time,unicodedata
import core
SCHEMA='''
CREATE TABLE IF NOT EXISTS downloaded_items(identity TEXT PRIMARY KEY,path TEXT,finished REAL);
CREATE TABLE IF NOT EXISTS scan_seen(id TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS format_dirty(work_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS film_hints(work_id TEXT PRIMARY KEY,score INTEGER NOT NULL,reason TEXT);
CREATE TABLE IF NOT EXISTS metadata_leases(work_id TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS metadata_leases_expiry ON metadata_leases(expires);
CREATE INDEX IF NOT EXISTS film_hint_score ON film_hints(score,work_id);
CREATE TABLE IF NOT EXISTS work_aliases(old_id TEXT PRIMARY KEY,new_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offer_availability(offer_id TEXT PRIMARY KEY,available_until TEXT,source TEXT,checked REAL);
CREATE TABLE IF NOT EXISTS artwork_checks(work_id TEXT PRIMARY KEY,next_try REAL);
CREATE TABLE IF NOT EXISTS artwork_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL);
CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY,title TEXT,kind TEXT,year INTEGER,show_key TEXT,meta TEXT,state TEXT DEFAULT 'pending',next_try REAL DEFAULT 0,attempts INTEGER DEFAULT 0,updated REAL,topic TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY,work_id TEXT,payload TEXT,special TEXT,rank INTEGER,seen REAL,active INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS offer_work ON offers(work_id,active,rank DESC);
CREATE TABLE IF NOT EXISTS series_templates(topic TEXT,provider TEXT,reference TEXT,meta TEXT,PRIMARY KEY(topic,provider,reference));
CREATE TABLE IF NOT EXISTS metadata_priority(work_id TEXT PRIMARY KEY,requested REAL);
CREATE TABLE IF NOT EXISTS series_focus(show_key TEXT PRIMARY KEY,until REAL,remaining INTEGER,updated REAL);
CREATE TABLE IF NOT EXISTS episode_queue(work_id TEXT PRIMARY KEY,next_try REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,last_outcome TEXT NOT NULL DEFAULT 'pending',updated REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS episode_queue_due ON episode_queue(next_try,work_id);
-- The work state is the source of truth: manual matches, format classification,
-- merges and deletion automatically remove stale episode tasks.
CREATE TRIGGER IF NOT EXISTS episode_queue_work_insert AFTER INSERT ON works
WHEN NEW.kind='series' AND NEW.state='identified'
 AND NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NOT NULL
 AND json_type(NEW.meta,'$.deferred_providers') IS NULL
 AND COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0
BEGIN
 INSERT INTO episode_queue(work_id) SELECT NEW.id
 WHERE NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS episode_queue_work_update AFTER UPDATE OF id,kind,state,meta ON works
BEGIN
 DELETE FROM episode_queue WHERE work_id=OLD.id AND
    (NEW.id!=OLD.id OR NEW.kind!='series' OR NEW.state!='identified'
     OR NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NULL
     OR json_type(NEW.meta,'$.deferred_providers') IS NOT NULL
     OR COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)!=0
     OR COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)!=0);
 INSERT INTO episode_queue(work_id)
 SELECT NEW.id WHERE NEW.kind='series' AND NEW.state='identified'
  AND NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NOT NULL
  AND json_type(NEW.meta,'$.deferred_providers') IS NULL
  AND COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0
 AND NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS episode_queue_work_delete AFTER DELETE ON works
BEGIN DELETE FROM episode_queue WHERE work_id=OLD.id; END;

CREATE INDEX IF NOT EXISTS work_first_pass ON works(attempts,state,kind,next_try);
CREATE INDEX IF NOT EXISTS work_queue ON works(kind,state,next_try);
CREATE INDEX IF NOT EXISTS work_type ON works(kind,title);
CREATE INDEX IF NOT EXISTS work_retry ON works(state,next_try);
CREATE INDEX IF NOT EXISTS work_show ON works(show_key);
CREATE INDEX IF NOT EXISTS work_listing ON works(kind,show_key,id,title,year,state);
CREATE TABLE IF NOT EXISTS work_genres(work_id TEXT,genre TEXT,PRIMARY KEY(work_id,genre));
CREATE INDEX IF NOT EXISTS genre_index ON work_genres(genre,work_id);
CREATE TABLE IF NOT EXISTS catalog_state(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS mesh_downloads(key TEXT PRIMARY KEY,node TEXT,name TEXT,state TEXT,until REAL,path TEXT,size INTEGER,hlc INTEGER,local TEXT,works TEXT);
CREATE TABLE IF NOT EXISTS mesh_download_works(work_id TEXT PRIMARY KEY,key TEXT);
CREATE TABLE IF NOT EXISTS mesh_results(work_id TEXT PRIMARY KEY,rank INTEGER,providers INTEGER,hlc INTEGER,node TEXT,payload TEXT);
'''
SPECIAL=re.compile(r'(?i)\b(audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung)\b|\((?:AD|DGS)\)')
SUFFIX=re.compile(r'(?i)\s*[([](?:mit\s+)?(?:audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung|AD|DGS|HD|UHD|4K|untertitel(?:n)?|UT|OmU|OV|Originalversion(?:\s+mit\s+Untertitel(?:n)?)?|Originalfassung(?:\s+mit\s+Untertitel(?:n)?)?|Original\s+mit\s+Untertitel(?:n)?|VOST(?:F)?|VO-?ST)[)\]]\s*')
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
    import video_causality
    role=video_causality.explicit_format(row)
    if role:
        # Keep the programme name as a relation, not as a verified full episode.
        if topic:m['related_series_title']=topic
        m.update(role,kind='other',title=title,episode_verified=False,
                 season=None,episode=None,episode_reference_id=None)
    return m

def mark_explicit_extra(c,w,source):
    """Safely repair an earlier automatic series recognition of a trailer/clip.

    Only provisional automatic states may change. Never undo a user decision
    or replace a verified downloaded episode without review.
    """
    if not w or w['state'] in ('manual','matched'):return False
    import video_causality
    role=video_causality.explicit_format(source)
    if not role:return False
    m=json.loads(w['meta'] or '{}')
    if source.get('topic'):m['related_series_title']=source['topic']
    m.update(role,kind='other',title=cleaned(source.get('title')) or m['title'],
             episode_verified=False,season=None,episode=None,episode_reference_id=None,
             reason='Kurzformat ausdrücklich im Sendertitel gekennzeichnet; keine vollständige Folge')
    c.execute("""UPDATE works SET title=?,kind='other',show_key=?,meta=?,state='format',
        next_try=0 WHERE id=?""",(m['title'],showkey(m),json.dumps(m),w['id']))
    return True


def origin_meta(c,row):
    """Seed metadata of an offer as on import (including a unique series template) and the template used."""
    m=seed(row);template=None
    if m['kind'] in ('unknown','series') and 300<=int(row.get('duration') or 0)<=3900:
        options=c.execute('SELECT meta FROM series_templates WHERE topic=? LIMIT 2',(key(row.get('topic')),)).fetchall()
        if len(options)==1:template=json.loads(options[0][0])
    if template and not m.get('video_role'):
        m.update(kind='series',episode_title=m.get('episode_title') or row['title'])
        for k in ('title','year','provider','reference_id','poster','genres','genre_source','reference_runtime_seconds'):m[k]=template.get(k)
        m['genres']=normalized_genres(m.get('genres'))
    return m,template

def series_template_candidate(c,row,source):
    """Get a uniquely verified series identity already learned from another episode.

    Never transfer another episode's season/number, verification flag or description.
    """
    topic=source.get('topic') or ''
    if row['kind'] not in ('unknown','series') or not topic:return None
    import video_causality
    if video_causality.explicit_format(source):return None
    if not 300<=int(source.get('duration') or 0)<=3900:return None
    if key(topic)==key(source.get('title')):return None
    templates=c.execute('SELECT meta FROM series_templates WHERE topic=? LIMIT 2',(key(topic),)).fetchall()
    if len(templates)!=1:return None
    known=json.loads(templates[0][0])
    if known.get('kind')!='series' or key(known.get('title'))!=key(topic):return None
    if not known.get('reference_id') or not known.get('provider'):return None
    own=json.loads(row['meta'])
    if own.get('year') and known.get('year') and own['year']!=known['year']:return None
    for k in ('title','year','provider','reference_id','poster','genres','genre_source','show_description','reference_runtime_seconds'):
        if k in known:own[k]=known[k]
    own['kind']='series'
    own['episode_title']=own.get('episode_title') or source.get('title') or ''
    # Only one known series identity is shared; episode evidence remains offer-specific.
    own['episode_verified']=False
    own.pop('episode_reference_id',None)
    own['reason']='Serienidentität aus bereits bestätigter Folge übernommen; Episode noch zu prüfen'
    return own

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
        if cur.rowcount:update_film_hint(c,wid,m,row)
        c.execute('UPDATE works SET topic=? WHERE id=?',(row.get('topic',''),wid))
        if cur.rowcount:
            if m.get('video_role'):
                # Distinct extra, neither a series episode nor a movie match.
                c.execute("UPDATE works SET state='format' WHERE id=?",(wid,))
            elif template:c.execute("UPDATE works SET state='identified' WHERE id=?",(wid,))
            for genre in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,genre))
        if str(row.get('topic') or '').strip() in LIVE_TOPICS:mark_live(c,wid)
        c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,special=excluded.special,rank=excluded.rank,seen=excluded.seen,active=1',(oid,wid,json.dumps(row),special(row),ranking(row),seen));ids.append(oid)
    return ids

LIVE_TOPICS=('Livestream','Livestreams','livestream','LIVESTREAM','Live-Stream')

def mark_live(c,wid=None):
    """Broadcaster live streams (topic "Livestream", 0.5.50) are no works: shown in the Live-TV tab,
    never sent to TMDB/TVDB/IMDb. Manual and confirmed decisions stay untouched."""
    sql=("UPDATE works SET kind='other',state='format',next_try=0,meta=json_set(COALESCE(NULLIF(meta,''),'{}'),"
         "'$.kind','other','$.live',json('true'),'$.reason','Livestream des Senders; erscheint im Reiter Live-TV und wird nicht abgeglichen.') "
         "WHERE topic IN (%s) AND state NOT IN ('manual','matched','format')"%','.join('?'*len(LIVE_TOPICS)))
    args=list(LIVE_TOPICS)
    if wid is not None:sql+=' AND id=?';args.append(wid)
    return c.execute(sql,args).rowcount

def begin_snapshot(c):
    """Collect feed IDs separately: an interrupted import must never retire existing offers."""
    c.execute('DELETE FROM scan_seen')

def ingest_incremental(c,rows,seen,changes):
    """Only changed/new offers need full seed, classification and payload writes.

    Stable IDs use channel, primary media URL and title exactly as in ingest().
    Identical offers are recorded in scan_seen without rewriting works or offers.
    """
    dirty=get_state(c,'format_cursor')=='complete'
    for row in rows:
        if not links(row) or not row.get('title'):continue
        oid=digest(str(row.get('channel'))+'|'+str(row.get('url_video') or row.get('url_video_hd') or row.get('url_website'))+'|'+row['title'])
        payload=json.dumps({**row,'_id':oid})
        old=c.execute('SELECT payload,active FROM offers WHERE id=?',(oid,)).fetchone()
        c.execute('INSERT OR IGNORE INTO scan_seen VALUES(?)',(oid,))
        if old and old['payload']==payload:
            category='unchanged' if old['active'] else 'reactivated'
            changes[category]=changes.get(category,0)+1
            continue
        if old:category='changed' if old['active'] else 'reactivated'
        else:category='added'
        changes[category]=changes.get(category,0)+1
        ingest(c,[row],seen)
        if dirty:
            c.execute('INSERT OR IGNORE INTO format_dirty SELECT work_id FROM offers WHERE id=?',(oid,))

def finish_snapshot(c,seen,changes):
    """Deactivate missing IDs only after the complete list was parsed successfully."""
    changes=dict(changes)
    retired=c.execute('UPDATE offers SET active=0 WHERE active=1 AND NOT EXISTS(SELECT 1 FROM scan_seen s WHERE s.id=offers.id)')
    changes['removed']=retired.rowcount
    c.execute('UPDATE offers SET active=1,seen=? WHERE active=0 AND EXISTS(SELECT 1 FROM scan_seen s WHERE s.id=offers.id)',(seen,))
    c.execute('DELETE FROM scan_seen')
    set_state(c,'last_import_diff',changes)
    return changes

def offer_expiry(c,oid):
    r=c.execute('SELECT available_until,source,checked FROM offer_availability WHERE offer_id=?',(oid,)).fetchone()
    return {'available_until':r[0],'availability_source':r[1],'availability_checked_at':r[2]} if r and r[0] else {}

def source(c,oid):
    r=c.execute('SELECT payload FROM offers WHERE id=?',(oid,)).fetchone()
    if not r:return None
    row=json.loads(r[0]);row.update(offer_expiry(c,oid));return row

def download_identity(m):
    return canonical(m) or digest(json.dumps([m.get('kind'),key(m.get('title','')),m.get('year'),m.get('season'),m.get('episode')]))

def mark_downloaded(c,job):
    invalidate_listings()
    identities={download_identity(job['metadata'])}
    source_id=job.get('source',{}).get('_id')
    found=c.execute('SELECT work_id FROM offers WHERE id=?',(source_id,)).fetchone()
    if found:identities.add(found[0])
    path=job.get('path') or job.get('target') or ''
    # A stale completed job may be replayed at startup after the user has moved
    # and re-linked the movie. Never replace an existing usable link with an
    # older path that cannot be found. Preserve unavailable references as well
    # until a verified replacement exists.
    from pathlib import Path
    try:valid=bool(path and Path(path).is_file())
    except OSError:valid=False
    for identity in identities:
        previous=c.execute('SELECT path FROM downloaded_items WHERE identity=?',(identity,)).fetchone()
        if previous and previous[0] and previous[0]!=path and not valid:continue
        c.execute('INSERT OR REPLACE INTO downloaded_items VALUES(?,?,?)',(identity,path,time.time()))

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
    # A canonical merge may remove a work between listing and the detail query.
    # Treat that as an absent row, never turn a routine refresh into HTTP 500.
    if w is None:return None
    r=c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC LIMIT 1',(w['id'],)).fetchone()
    if not r:return None
    row=json.loads(r['payload']);row.update(offer_expiry(c,r['id']));count=c.execute('SELECT COUNT(*) FROM offers WHERE work_id=?',(w['id'],)).fetchone()[0]
    saved=c.execute('SELECT path FROM downloaded_items WHERE identity=?',(w['id'],)).fetchone()
    file_state=None
    if saved:
        import local_library
        file_state=local_library.file_state(saved['path'])
    meta=json.loads(w['meta'])
    import categories
    checked=bool(w['attempts']) or w['state'] in ('matched','manual','identified','review','format')
    return {'id':r['id'],'work_id':w['id'],'source':row,'metadata':meta,'categories':categories.classify((),meta.get('genres') or [],checked),'offer_count':count,'available':bool(r['active']),'state':w['state'],'downloaded':bool(saved),'file_state':file_state,'mesh_download':mesh_download(c,json.loads(w['meta']),w['id']),'special':r['special'],'best':links(row)[0] if links(row) else None,'show_key':w['show_key'],'links':links(row)}

def media_equivalence_key(row,special_kind='',active=True):
    """Exact playable media identity; do not strip signed URL query strings.

    Different accessibility editions, subtitles, timing, channel, or any
    playable rendition are never collapsed just because both say 'ARD HD'.
    """
    media=tuple((field,str(row.get(field) or '')) for field in
                ('url_video','url_video_hd','url_video_low','url_subtitle'))
    if not any(value for field,value in media if field!='url_subtitle'):return None
    return (row.get('channel',''),special_kind,active,int(row.get('duration') or 0),
            media)

def alternatives(c,wid):
    w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    if not w:raise ValueError('Werk nicht gefunden')
    out=[];by_media={}
    meta=json.loads(w['meta'])
    for r in c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC',(wid,)):
        row=json.loads(r['payload']);row.update(offer_expiry(c,r['id']))
        active=bool(r['active'])
        key_=media_equivalence_key(row,r['special'],active)
        if key_ is not None and key_ in by_media:
            entry=out[by_media[key_]]
            entry['same_media_count']+=1
            entry['offer_ids'].append(r['id'])
            continue
        entry={'id':r['id'],'work_id':wid,'source':row,'metadata':meta,
               'special':r['special'],'available':active,'links':links(row),
               'same_media_count':1,'offer_ids':[r['id']]}
        if key_ is not None:by_media[key_]=len(out)
        out.append(entry)
    return out

SHOW_FIELDS=('title','year','kind','provider','reference_id','imdb_id','poster','fanart','genres','genre_source','rating','votes','rating_source','ratings','networks','studios','show_credits','artwork_provider','show_description')
STATE_ORDER={'manual':0,'matched':1,'identified':2,'review':3,'retry':4,'pending':5,'format':6}

def show_detail(c,show,archive=False,limit=1000):
    """Series page: show-level metadata assembled from its episodes plus all episodes by season.

    Episode descriptions are never used as series description; only a provider series overview
    (show_description) or, for broadcaster series, the Sendereihe text (series_description).
    """
    if not show:raise ValueError('Serie fehlt')
    where='w.show_key=?'+('' if archive else ' AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)')
    rows=c.execute('SELECT w.* FROM works w WHERE '+where,(show,)).fetchall()
    if not rows:raise ValueError('Serie nicht gefunden')
    metas=[(r,json.loads(r['meta'])) for r in rows]
    ranked=sorted(metas,key=lambda x:(STATE_ORDER.get(x[0]['state'],9),not x[1].get('poster'),not x[1].get('fanart')))
    summary={'show_key':show}
    for field in SHOW_FIELDS:
        for _,m in ranked:
            v=m.get(field)
            if v not in (None,'',[],{}):summary[field]=v;break
    if not summary.get('show_description'):
        # Broadcaster series carry the Sendereihe text on each episode; the most frequent one wins.
        from collections import Counter
        texts=Counter((m.get('series_description') or '').strip() for _,m in metas);texts.pop('',None)
        if texts:summary['show_description']=texts.most_common(1)[0][0]
    def order(x):
        m=x[1];return (m.get('season') if m.get('season') is not None else 99999,m.get('episode') if m.get('episode') is not None else 99999,m.get('episode_title',''))
    episodes=[];seasons={};channels=set()
    for w,m in sorted(metas,key=order)[:limit]:
        entry=item(c,w)
        if not entry:continue
        entry.update(episodes=1,series_parent=False);episodes.append(entry)
        season=m.get('season') if isinstance(m.get('season'),int) else None
        seasons.setdefault(season,0);seasons[season]+=1
    for (payload,) in c.execute('SELECT o.payload FROM offers o JOIN works w ON w.id=o.work_id WHERE '+where+('' if archive else ' AND o.active=1'),(show,)):
        channel=json.loads(payload).get('channel')
        if channel:channels.add(channel)
    summary.update(state=ranked[0][0]['state'],episode_count=len(rows),downloaded=sum(1 for e in episodes if e['downloaded']),available=sum(1 for e in episodes if e['available']),
                   channels=sorted(channels),seasons=[{'season':k,'episodes':v} for k,v in sorted(seasons.items(),key=lambda kv:(kv[0] is None,kv[0] or 0))],truncated=len(rows)>limit)
    return {'show':summary,'episodes':episodes,'work_ids':[w['id'] for w,_ in ranked[:48]]}

# 0.5.55: grouped catalogue pages from memory. Björn's diagnosis (12.11.2026): /api/catalog took
# 7-31 s on every call (239 times in six hours) because each page grouped and sorted all ~680,000
# works again. The grouped order per filter is now computed once, served from memory and renewed
# in the background (stale-while-revalidate), so paging and returning to the view are immediate.
LISTING_DB=None            # set by the server: context-manager factory for background refreshes
LISTING_TTL=600.0
LISTING_SEARCH_TTL=120.0
LISTING_SLOW=1.5             # seconds: from here on an outdated page is served while it is renewed
_LISTING_MAX=32
_LISTING={}                # key -> {'rows':[(id,episodes)],'built':monotonic,'busy':bool,'used':monotonic}
_LISTING_LOCK=threading.Lock()
_LISTING_BUILD=threading.Lock()   # one heavy aggregation at a time
_LISTING_STATS={'hits':0,'builds':0,'background':0,'last_seconds':0.0,'restored':0,'pending':0}
# 0.5.57: the slow aggregations survive a restart. Björn (12.11.2026): after the start the
# catalogues took very long. Every start grouped the whole catalogue again before the first
# page could be shown. The last result is now read from this file, shown at once and renewed
# in the background.
LISTING_FILE=None          # set by the server through load_listings()
LISTING_WAIT=0.6           # seconds a caller with wait=False gives a first aggregation
_LISTING_KEEP=6
_LISTING_QUEUED={}         # key -> Event, first aggregations running in the background
_LISTING_FAILED={}         # key -> (monotonic, exception) of a failed background aggregation

class ListingPending(Exception):
    """The grouped list is being computed in the background; ask again in a moment."""

def _listing_build(c,where,args,grouping,order):
    started=time.monotonic()
    base='SELECT MIN(w.id) AS id,COUNT(*) AS episodes FROM works w WHERE '+where+' GROUP BY '+grouping
    rows=[(r[0],r[1],r[2],r[3]) for r in c.execute('SELECT g.id,g.episodes,w.title,w.year FROM ('+base+') g JOIN works w ON w.id=g.id ORDER BY '+order,args)]
    seconds=time.monotonic()-started
    _LISTING_STATS['builds']+=1;_LISTING_STATS['last_seconds']=round(seconds,2)
    return rows,seconds

def _listing_persist():
    path=LISTING_FILE
    if path is None:return
    with _LISTING_LOCK:
        keep=sorted(((k,e) for k,e in _LISTING.items() if e['seconds']>=LISTING_SLOW and not e.get('search')),key=lambda ke:-ke[1]['used'])[:_LISTING_KEEP]
        data=[{'key':[k[0],list(k[1]),k[2],k[3]],'rows':e['rows'],'seconds':e['seconds']} for k,e in keep]
    try:
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'version':1,'saved':time.time(),'entries':data},separators=(',',':')),encoding='utf-8');tmp.replace(path)
    except OSError:pass   # only the next start is slower

def load_listings(path):
    """Read the lists of the last run. They count as outdated: shown at once, renewed on first use."""
    global LISTING_FILE
    from pathlib import Path
    LISTING_FILE=Path(path)
    try:stored=json.loads(LISTING_FILE.read_text(encoding='utf-8'))
    except (OSError,ValueError):return 0
    count=0;now=time.monotonic()
    if not isinstance(stored,dict) or stored.get('version')!=1:return 0
    with _LISTING_LOCK:
        for entry in stored.get('entries') or []:
            try:
                where,args,grouping,order=entry['key'];rows=[(str(r[0]),int(r[1]),r[2],r[3]) for r in entry['rows']]
                _LISTING[(where,tuple(args),grouping,order)]={'rows':rows,'built':float('-inf'),'busy':False,'used':now,'seconds':max(float(entry.get('seconds') or 0),LISTING_SLOW),'search':False}
                count+=1
            except (KeyError,TypeError,ValueError,IndexError):continue
    _LISTING_STATS['restored']=count
    return count

def _listing_store(key,rows,seconds,search=False):
    now=time.monotonic()
    with _LISTING_LOCK:
        _LISTING[key]={'rows':rows,'built':now,'busy':False,'used':now,'seconds':seconds,'search':search}
        while len(_LISTING)>_LISTING_MAX:
            _LISTING.pop(min(_LISTING,key=lambda k:_LISTING[k]['used']))
    if seconds>=LISTING_SLOW and not search:_listing_persist()

def _listing_refresh(key,where,args,grouping,order,search=False):
    try:
        with _LISTING_BUILD:
            with LISTING_DB() as c:rows,seconds=_listing_build(c,where,args,grouping,order)
        _listing_store(key,rows,seconds,search);_LISTING_STATS['background']+=1
    except Exception as exc:
        with _LISTING_LOCK:
            if key in _LISTING:_LISTING[key]['busy']=False
            _LISTING_FAILED[key]=(time.monotonic(),exc)   # shown to a caller that does not wait
            while len(_LISTING_FAILED)>_LISTING_MAX:_LISTING_FAILED.pop(next(iter(_LISTING_FAILED)))
    finally:
        with _LISTING_LOCK:done=_LISTING_QUEUED.pop(key,None)
        if done:done.set()

def _listing_groups(c,where,args,grouping,order,search=False,wait=True):
    # Without a server (tests, tools) every call reads the database directly.
    if LISTING_DB is None:return _listing_build(c,where,args,grouping,order)[0]
    key=(where,tuple(args),grouping,order);now=time.monotonic()
    with _LISTING_LOCK:
        entry=_LISTING.get(key)
        if entry:
            entry['used']=now;age=now-entry['built']
            if age<=(LISTING_SEARCH_TTL if search else LISTING_TTL):
                _LISTING_STATS['hits']+=1;return entry['rows']
            # Outdated: quick aggregations are simply repeated, slow ones answer from memory
            # at once and are renewed in the background.
            if entry['seconds']>=LISTING_SLOW:
                if not entry['busy']:
                    entry['busy']=True
                    threading.Thread(target=_listing_refresh,args=(key,where,list(args),grouping,order,search),daemon=True,name='catalog_listing_refresh').start()
                _LISTING_STATS['hits']+=1;return entry['rows']
        if not wait:
            failed=_LISTING_FAILED.get(key)
            if failed and now-failed[0]<=30:raise failed[1]   # do not repeat a failing aggregation at once
            # The caller (merged dashboard) shows the other sources first: compute in the
            # background, give a quick aggregation a moment, otherwise report "pending".
            done=_LISTING_QUEUED.get(key)
            if done is None:
                done=_LISTING_QUEUED[key]=threading.Event()
                threading.Thread(target=_listing_refresh,args=(key,where,list(args),grouping,order,search),daemon=True,name='catalog_listing_first').start()
    if not wait:
        done.wait(LISTING_WAIT)
        with _LISTING_LOCK:
            entry=_LISTING.get(key)
            if entry:return entry['rows']   # new, or the outdated one while the new one is computed
            failed=_LISTING_FAILED.get(key)
        if failed and failed[0]>=now:raise failed[1]
        _LISTING_STATS['pending']+=1
        raise ListingPending()
    with _LISTING_BUILD:
        with _LISTING_LOCK:
            entry=_LISTING.get(key)
            if entry and entry['built']>now:return entry['rows']   # built while waiting
        rows,seconds=_listing_build(c,where,args,grouping,order)
    _listing_store(key,rows,seconds,search)
    return rows

def invalidate_listings(drop=False):
    """After an import, a download or a manual change: renew on next use. Slow aggregations keep
    answering from memory while they are renewed in the background."""
    with _LISTING_LOCK:
        _LISTING_FAILED.clear()
        if drop:_LISTING.clear()
        else:
            for entry in _LISTING.values():entry['built']=float('-inf')

def listing_cache_stats():
    with _LISTING_LOCK:return {**_LISTING_STATS,'entries':len(_LISTING)}


def listing(c,query='',kind='',genre='',show='',offset=0,archive=False,state='',sort='title',downloaded='hide',collection='',index_only=False,wait=True):
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
        clause,values=category_clause(c,genre)
        clauses.append(clause);args.extend(values)
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
    order={'title':'w.title COLLATE NOCASE','year':'w.year DESC,w.title COLLATE NOCASE','recognized':"CASE WHEN w.state IN ('manual','matched') THEN 0 WHEN w.state='identified' THEN 1 ELSE 2 END,w.title COLLATE NOCASE"}.get(sort,'w.title COLLATE NOCASE')
    groups=_listing_groups(c,where,args,grouping,order,bool(query),wait)
    if index_only:return groups   # (id, episodes, title, year) of every group, for unified_index
    total=len(groups);rows=[{'id':r[0],'episodes':r[1]} for r in groups[offset:offset+48]];out=[]
    for row in rows:
        w=c.execute('SELECT * FROM works WHERE id=?',(row['id'],)).fetchone()
        if w is None:continue  # merged by another worker after the paged query
        entry=item(c,w)
        if entry:entry.update(episodes=row['episodes'],series_parent=w['kind']=='series' and not show);out.append(entry)
    return {'items':out,'total':total,'offset':offset}

# 0.5.83: a work counts as classified once the reference check ran (attempts) or produced a state.
# Before that it is listed under categories.UNCLASSIFIED, regardless of the broadcaster's labels.
CLASSIFIED_SQL="(w.attempts>0 OR w.state IN ('matched','manual','identified','review','format'))"

def category_labels(c):
    """Fixed category -> raw genres stored in work_genres that name it (genre index, small)."""
    import categories
    out={}
    for (raw,) in c.execute('SELECT DISTINCT genre FROM work_genres'):
        for name in categories.of_label(raw):out.setdefault(name,[]).append(raw)
    return out

def category_clause(c,genre):
    """SQL filter for a fixed category, 'Unklassifiziert', 'Sonstige' or (classic tree in
    Verwaltung → Werkkatalog) one raw genre exactly as stored."""
    import categories
    text=str(genre).strip()
    if text==categories.LEGACY_UNKNOWN:
        return 'NOT EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id)',[]
    if text==categories.UNCLASSIFIED:
        return 'NOT '+CLASSIFIED_SQL,[]
    labels=category_labels(c)
    if text==categories.OTHER:
        known=[raw for names in labels.values() for raw in names]
        if not known:return CLASSIFIED_SQL,[]
        return (CLASSIFIED_SQL+' AND NOT EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))'
                %','.join('?'*len(known))),known
    if text in categories.CATEGORIES:
        raw=labels.get(text) or []
        if not raw:return '0',[]
        return (CLASSIFIED_SQL+' AND EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))'
                %','.join('?'*len(raw))),raw
    return 'EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre=?)',[text]

def category_tree(c):
    """[{kind, genre, n}] with the fixed categories (series counted once per show), like tree()."""
    import categories
    units={}
    rows=c.execute("SELECT w.kind,CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END unit,"+CLASSIFIED_SQL+
                   " classified,g.genre FROM works w LEFT JOIN work_genres g ON g.work_id=w.id"
                   " WHERE w.kind IN ('movie','series') AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)")
    named={};checked={}
    for kind,unit,classified,genre in rows:
        if not classified:names=(categories.UNCLASSIFIED,)
        else:
            checked.setdefault(kind,set()).add(unit)
            names=categories.of_label(genre) if genre else []
            if names:named.setdefault(kind,set()).add(unit)
            else:names=(categories.OTHER,)
        for name in names:units.setdefault((kind,name),set()).add(unit)
    out=[]
    for (kind,name),members in units.items():
        if name==categories.OTHER:members=members-named.get(kind,set())
        elif name==categories.UNCLASSIFIED:members=members-checked.get(kind,set())   # one checked episode classifies the show
        if members:out.append({'kind':kind,'genre':name,'n':len(members)})
    out.sort(key=lambda r:(r['kind'],categories.sort_key(r['genre'])))
    return out

def tree(c):
    return [dict(r) for r in c.execute("SELECT w.kind,COALESCE(g.genre,'Unbekannt') genre,COUNT(DISTINCT CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END) n FROM works w LEFT JOIN work_genres g ON g.work_id=w.id WHERE EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) GROUP BY w.kind,g.genre")]

def stats(c):
    """One indexed classification pass, instead of separate full-work scans for each tile."""
    grouped=c.execute('SELECT kind,state,COUNT(*) n FROM works GROUP BY kind,state').fetchall()
    kinds={};states={}
    pending=0
    for kind,state,n in grouped:
        kinds[kind]=kinds.get(kind,0)+n
        states[state]=states.get(state,0)+n
        if kind!='other' and state in ('pending','retry'):pending+=n
    first=c.execute("""SELECT COUNT(*) FROM works w
        WHERE w.attempts=0 AND w.kind IN ('movie','series','unknown')
          AND w.state IN ('pending','retry','identified')
          AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)
          AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)""").fetchone()[0]
    return {
        'types':kinds,'works':sum(kinds.values()),
        'offers':c.execute('SELECT COUNT(*) FROM offers WHERE active=1').fetchone()[0],
        'last_import_diff':get_state(c,'last_import_diff',{}),
        'movie_duplicates_merged':get_state(c,'movie_dedup_total_v0521',0),
        'film_hints':c.execute("""SELECT COUNT(*) FROM film_hints h JOIN works w ON w.id=h.work_id
            WHERE w.kind='unknown' AND w.state IN ('pending','retry','identified')""").fetchone()[0],
        'first_pass_remaining':first,
        'identified':states.get('identified',0),
        'matched':states.get('matched',0)+states.get('manual',0),
        'pending':pending,
        'review':states.get('review',0),
        'formats':states.get('format',0),
        'sync':get_state(c,'sync',{'phase':'waiting'}),
        'last_complete':get_state(c,'last_complete',0)
    }

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
        for field in ('networks','studios','ratings','imdb_id','discovery_enriched','show_description'):
            if m.get(field)==previous.get(field):m.pop(field,None)
    original_dest=canonical(m) or wid
    alias=c.execute('SELECT new_id FROM work_aliases WHERE old_id=?',(original_dest,)).fetchone()
    dest=alias[0] if alias else original_dest
    old=c.execute('SELECT state,meta,attempts,next_try FROM works WHERE id=?',(dest,)).fetchone()
    if old and old['state']=='manual' and state!='manual':
        m=json.loads(old['meta']);state='manual'
    elif old and old['state']=='matched' and state=='identified':
        # Never downgrade an already confirmed film to a weaker work-only result.
        m=json.loads(old['meta']);state='matched'
    elif old and m.get('kind')=='movie' and state in ('matched','manual','identified'):
        previous_dest=json.loads(old['meta'])
        identity_agrees=(previous_dest.get('kind')=='movie' and (
            (previous_dest.get('provider')==m.get('provider') and
             previous_dest.get('reference_id') and previous_dest.get('reference_id')==m.get('reference_id'))
            or bool(alias and original_dest!=dest)))
        if identity_agrees and state!='manual':
            incoming=normalized_genres(m.get('genres') or [])
            combined=normalized_genres(incoming+list(previous_dest.get('genres') or []))
            m['genres']=combined
            if len(combined)>len(incoming):m['genre_source']='Mehrere bestätigte Quellen'
    # Retain attempt history when a provisional work moves to a canonical ID.
    # Otherwise every merge silently turns a repeat into an apparent first pass.
    seen_attempts=max(int(row['attempts'] or 0),int(old['attempts'] or 0) if old else 0)
    due=max(float(row['next_try'] or 0),float(old['next_try'] or 0) if old else 0)
    c.execute("""INSERT INTO works(id,title,kind,year,show_key,meta,state,updated,attempts,next_try)
        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,kind=excluded.kind,year=excluded.year,show_key=excluded.show_key,
        meta=excluded.meta,state=excluded.state,updated=excluded.updated,
        attempts=MAX(works.attempts,excluded.attempts)""",
        (dest,m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),state,time.time(),seen_attempts,due))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(dest,))
    m['genres']=normalized_genres(m.get('genres'))
    c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),dest))
    for genre in m.get('genres',[]):c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(dest,genre))
    if dest!=wid:
        c.execute('INSERT OR IGNORE INTO downloaded_items SELECT ?,path,finished FROM downloaded_items WHERE identity=?',(dest,wid))
        c.execute('UPDATE offers SET work_id=? WHERE work_id=?',(dest,wid))
        c.execute('INSERT OR REPLACE INTO work_aliases VALUES(?,?)',(wid,dest))
        c.execute('UPDATE work_aliases SET new_id=? WHERE new_id=?',(dest,wid))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(wid,));c.execute('DELETE FROM works WHERE id=?',(wid,))
    if m.get('kind')!='unknown':
        c.execute('DELETE FROM film_hints WHERE work_id IN (?,?)',(wid,dest))
    if m.get('kind')=='movie' and state in ('matched','manual','identified'):
        return reconcile_movie_duplicates(c,dest)
    return dest

def _movie_evidence(c,w):
    """Return per-work evidence, not merely a matching genre or a title string."""
    if not w or w['kind']!='movie' or w['state'] not in ('matched','manual','identified') or not w['year']:
        return None
    m=json.loads(w['meta'] or '{}')
    if m.get('kind')!='movie' or m.get('year')!=w['year']:return None
    durations=[int(r[0]) for r in c.execute(
        "SELECT json_extract(payload,'$.duration') FROM offers WHERE work_id=? AND active=1",
        (w['id'],)) if isinstance(r[0],(float,int)) and r[0]>600]
    imdb=str(m.get('imdb_id') or (m.get('reference_id') if m.get('provider') in ('IMDb Offline','OMDb') else '') or '').strip()
    return {'row':w,'meta':m,'title_key':key(w['title']),'durations':durations,'imdb_id':imdb,
            'ref':str(m.get('reference_id') or ''),'provider':str(m.get('provider') or '')}

def _same_confirmed_movie(a,b):
    """Two entries may merge only with shared film evidence; genres never prove identity."""
    if not a or not b or a['title_key']!=b['title_key'] or a['row']['year']!=b['row']['year']:
        return False
    if a['row']['state']=='manual' and b['row']['state']=='manual':
        # Two separately edited records are kept until the user explicitly resolves them.
        return False
    if a['provider']==b['provider'] and a['ref'] and b['ref'] and a['ref']!=b['ref']:
        return False
    if a['imdb_id'] and b['imdb_id'] and a['imdb_id']!=b['imdb_id']:
        return False
    if a['imdb_id'] and a['imdb_id']==b['imdb_id']:return True
    if a['provider']==b['provider'] and a['ref'] and a['ref']==b['ref']:return True
    # Different verified providers: identical film title, release year and close
    # broadcaster runtimes give independent evidence. Without runtimes, no merge.
    if a['row']['state'] not in ('matched','manual') or b['row']['state'] not in ('matched','manual'):
        return False
    if not a['ref'] or not b['ref'] or not a['durations'] or not b['durations']:
        return False
    return any(abs(x-y)<=min(300,max(x,y)*.05) for x in a['durations'] for y in b['durations'])

def _merge_confirmed_movie(c,a,b):
    """Preserve offers, downloads, manual changes, metadata and genre evidence."""
    def score(v):
        m=v['meta'];w=v['row']
        return (w['state']=='manual',w['id']==canonical(m),w['state']=='matched',
                bool(m.get('poster')),len(m.get('genres') or []))
    keep,other=sorted((a,b),key=score,reverse=True)
    target=keep['row']['id'];old=other['row']['id']
    preferred=dict(keep['meta']);extra=other['meta']
    # Manual genre edits are authoritative. Otherwise a verified provider's
    # smaller genre list must not erase previously verified genres.
    if keep['row']['state']!='manual':
        previous=normalized_genres(preferred.get('genres') or [])
        combined=normalized_genres(previous+list(extra.get('genres') or []))
        preferred['genres']=combined
        if combined!=previous:preferred['genre_source']='Mehrere bestätigte Quellen'
    for field in ('poster','fanart','description','show_description','rating','rating_source',
                  'votes','imdb_id','networks','studios','show_credits','ratings'):
        if preferred.get(field) in (None,'',[],{}):
            if extra.get(field) not in (None,'',[],{}):preferred[field]=extra[field]
    c.execute('UPDATE works SET meta=?,updated=? WHERE id=?',(json.dumps(preferred),time.time(),target))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(target,))
    for genre in normalized_genres(preferred.get('genres') or []):
        c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(target,genre))
    c.execute('UPDATE offers SET work_id=? WHERE work_id=?',(target,old))
    c.execute('INSERT OR IGNORE INTO downloaded_items SELECT ?,path,finished FROM downloaded_items WHERE identity=?',(target,old))
    c.execute('INSERT OR IGNORE INTO artwork_checks SELECT ?,next_try FROM artwork_checks WHERE work_id=?',(target,old))
    c.execute('INSERT OR IGNORE INTO format_dirty SELECT ? FROM format_dirty WHERE work_id=?',(target,old))
    c.execute('INSERT OR REPLACE INTO work_aliases VALUES(?,?)',(old,target))
    c.execute('UPDATE work_aliases SET new_id=? WHERE new_id=?',(target,old))
    set_state(c,'movie_dedup_total_v0521',get_state(c,'movie_dedup_total_v0521',0)+1)
    for table,field in (('work_genres','work_id'),('artwork_checks','work_id'),
                        ('metadata_priority','work_id'),('format_dirty','work_id')):
        c.execute('DELETE FROM '+table+' WHERE '+field+'=?',(old,))
    c.execute('DELETE FROM works WHERE id=?',(old,))
    return target

def reconcile_movie_duplicates(c,wid,max_candidates=40):
    """Merge conservative, independently verified duplicates of one movie.

    Ambiguous films (missing year/runtime, different years, mismatched provider
    references) remain separate. Small indexed candidate lookup, no full scan.
    """
    w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    a=_movie_evidence(c,w)
    if not a:return wid
    rows=c.execute("""SELECT * FROM works
        WHERE kind='movie' AND year=? AND title=? COLLATE NOCASE
          AND state IN ('matched','manual','identified') AND id<>?
        LIMIT ?""",(w['year'],w['title'],wid,max_candidates+1)).fetchall()
    if len(rows)>max_candidates:return wid  # too ambiguous, leave intact
    for other in rows:
        b=_movie_evidence(c,other)
        if _same_confirmed_movie(a,b):
            wid=_merge_confirmed_movie(c,a,b)
            w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
            a=_movie_evidence(c,w)
    return wid

def deduplicate_movie_batch(c,limit=200):
    """Incremental one-time upgrade of older catalogues, bounded per transaction."""
    state='movie_dedup_cursor_v0521';cursor=get_state(c,state,0)
    if cursor=='complete':return 0,0
    rows=c.execute("""SELECT rowid,id FROM works WHERE rowid>? AND kind='movie'
          AND year IS NOT NULL AND state IN ('matched','manual','identified')
          ORDER BY rowid LIMIT ?""",(cursor,limit)).fetchall()
    before=get_state(c,'movie_dedup_total_v0521',0)
    for row in rows:
        cursor=row['rowid']
        if not c.execute('SELECT 1 FROM works WHERE id=?',(row['id'],)).fetchone():continue
        reconcile_movie_duplicates(c,row['id'])
    set_state(c,state,cursor if rows else 'complete')
    return len(rows),get_state(c,'movie_dedup_total_v0521',0)-before

def auto_choice(meta,rows):
    import matching
    return matching.choose(meta,rows)

def work_choice(meta,rows):
    import matching
    return matching.choose(meta,rows,work_only=True)

def propagate_series(c,old_show,m):
    # Transfer work metadata, never a sibling's episode number or episode plot.
    common={k:m[k] for k in ('title','year','provider','reference_id','poster','genres','genre_source','show_description','reference_runtime_seconds') if k in m}
    for row in c.execute("SELECT * FROM works WHERE show_key=? AND state NOT IN ('manual','matched')",(old_show,)).fetchall():
        own=json.loads(row['meta'])
        # Every recognised episode propagates again; rewriting unchanged siblings made this quadratic per series.
        if row['state']=='identified' and all(own.get(k)==v for k,v in common.items()):continue
        own.update(common)
        save_metadata(c,row['id'],own,'identified')

def focus_series(c,show_key,limit=24,cooldown=1800):
    """Boost a *bounded* number of sibling episodes after verified show recognition.

    It does not reset next_try, override user-prioritised work, or force an
    unbounded recheck of an entire long-running show.
    """
    if not show_key:return False
    now=time.time()
    old=c.execute('SELECT until FROM series_focus WHERE show_key=?',(show_key,)).fetchone()
    if old and old[0]>now:return False
    eligible=c.execute("""SELECT 1 FROM works w WHERE w.show_key=?
        AND w.kind='series' AND w.state IN ('pending','retry','identified')
        AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
        LIMIT 1""",(show_key,)).fetchone()
    if not eligible:return False
    c.execute('INSERT OR REPLACE INTO series_focus VALUES(?,?,?,?)',
              (show_key,now+cooldown,int(limit),now))
    return True

def focus_take(c,show_key):
    if not show_key:return
    c.execute('UPDATE series_focus SET remaining=MAX(0,remaining-1) WHERE show_key=?',(show_key,))

def prioritize(c,ids=None,show=''):
    count=0
    if show:ids=[r[0] for r in c.execute('SELECT id FROM works WHERE show_key=?',(show,))]
    for wid in (ids or [])[:1000]:
        row=c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()
        if not row or row[0] in ('manual','matched'):continue
        # An explicit request must never be reclassified by the automatic
        # format scanner while a user is waiting for this particular work.
        m=json.loads(c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()[0])
        if not m.get('scan_requested'):
            m['scan_requested']=True
            c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
        c.execute("UPDATE works SET state=CASE WHEN state='identified' THEN state ELSE 'pending' END,next_try=0 WHERE id=?",(wid,))
        c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(wid,time.time()))
        c.execute("UPDATE episode_queue SET next_try=0 WHERE work_id=?",(wid,))
        count+=1
    return count

# Recurring broadcast formats (news, regional and service magazines). Their single contributions are
# not in any film database; they are grouped under their format and not queried (diagnosis 0.4.7).
FORMAT_WORDS=re.compile(r'(?i)\b(?:nachrichten|tagesschau|tagesthemen|aktuell|journal|heute|wetter|sportschau|sportstudio|magazin|lokalzeit|abendschau|landesschau|hessenschau|regional|drehscheibe|morgenmagazin|mittagsmagazin|pressekonferenz|gottesdienst|podcast|kompakt|update|live)\b')
FORMAT_GENERIC={'film','filme','spielfilm','serien','serie','fernsehfilm','mediathek','zdf','ard','3sat','arte','kika','kino','dokumentation','dokumentationen','doku','dokus','reportage','sonstiges','sonstige','unterhaltung','filme im ersten'}
TRAILER=re.compile(r'(?i)^\s*(?:trailer|teaser|vorschau)\b')

def format_contribution(m,source,topic_works):
    """True for a single contribution of a recurring format, e.g. one edition of "aktuell (16 Uhr)"."""
    topic=cleaned(source.get('topic'));title=cleaned(source.get('title'))
    import metadata
    if m.get('kind') not in ('unknown','other') or m.get('scan_requested') or not topic or key(topic) in FORMAT_GENERIC or metadata.RUBRIC.match(topic):return False
    if TRAILER.search(title):return False
    clip=m.get('kind')=='other';duration=int(source.get('duration') or 0)
    # 0.5.80 (Björn: news and magazine clips belong to their Sendung, not to "Weitere Sendungen"):
    # editions titled like their Sendung ("Landesschau" / "Landesschau") count once there are several,
    # and a clip the import already recognised as news/magazine material ('other') joins its Sendung
    # even as the only edition so far.
    if key(topic)==key(title):return bool(FORMAT_WORDS.search(topic)) and topic_works>=2
    if FORMAT_WORDS.search(topic):return topic_works>=(1 if clip else 2)
    if clip and duration<1200 and topic_works>=2:return True
    return duration<600 and topic_works>=3

def broadcaster_format(m,source,topic_works):
    """True for an episode of a news or magazine Sendung that only the broadcaster's Mediathek identified.

    Diagnosis 0.5.15: 3,215 editions of "Schleswig-Holstein Magazin" were each queried at the ARD
    Mediathek again and took two thirds of the recognition queue without improving any result."""
    import broadcaster
    if m.get('kind')!='series' or m.get('provider') not in broadcaster.PROVIDERS or m.get('scan_requested'):return False
    topic=cleaned(source.get('topic'))
    if not topic or key(topic) in FORMAT_GENERIC or key(topic)!=key(m.get('title')):return False
    return bool(FORMAT_WORDS.search(topic)) and topic_works>=2

# Exact, established news programmes. An approximate title match or a word such
# as "heute" alone is NOT enough to classify a film or a scripted series.
# Keep this list short; each addition needs a positive and negative regression.
NEWS_TOPICS={
    'heute journal','heute in deutschland','heute in europa','hallo deutschland',
    'tagesschau','tagesthemen','heute','zdf heute','zdfheute',
    'nachtmagazin','morgenmagazin','ard morgenmagazin','zdf morgenmagazin',
    'mittagsmagazin','ard mittagsmagazin','zdf mittagsmagazin'
}
FILM_RUBRICS={
    'spielfilm','spielfilme','fernsehfilm','fernsehfilme','kino','großes kino',
    'filme','filme im ersten','film im ersten','filme im mdr','kino kino'
}
FILM_PHRASE=re.compile(
    r'(?i)\b(?:spielfilm|fernsehfilm|kinofilm|filmkomödie|kinodrama|'
    r'filmklassiker|kinoklassiker|dokumentarfilm|literaturverfilmung)\b')

def is_news_contribution(row,source=None):
    """Only explicitly known news programmes; preserve manually verified episodes.

    Run before contacting external APIs and as a format-migration fallback. A
    generic 'heute' inside a film title or synopsis never qualifies.
    """
    if not row or row['state'] in ('manual','matched','format') or row['kind'] not in ('unknown','other','series'):
        return False
    meta=json.loads(row['meta'] or '{}')
    if meta.get('scan_requested') or meta.get('episode_verified'):return False
    if source is None:return False
    topic=key(cleaned(source.get('topic')))
    if topic not in NEWS_TOPICS:return False
    duration=int(source.get('duration') or 0)
    return duration==0 or 60<=duration<=7200

def mark_news_format(c,row,source):
    """Skip pointless movie-API lookups for a specific news programme edition.

    No metadata is discarded: keep the original text, ratings and credits, but
    do not imply that its episode has an external episode ID.
    """
    if not is_news_contribution(row,source):return False
    if c.execute('SELECT 1 FROM metadata_priority WHERE work_id=?',(row['id'],)).fetchone():return False
    m=json.loads(row['meta'] or '{}')
    topic=cleaned(source.get('topic'))
    m['kind']='series';m['title']=topic;m['episode_title']=m.get('episode_title') or cleaned(source.get('title')) or topic
    m['state']='format';m['format_grouping']='news'
    m['reason']='Regelmäßige Nachrichtensendung: kein erneuter Film-/Serienanbieterabgleich erforderlich'
    m.pop('suggestions',None);m.pop('metadata_warnings',None)
    if not m.get('provider'):m['provider']='Sendung'
    m['episode_verified']=False
    m.pop('episode_reference_id',None)
    c.execute("""UPDATE works SET title=?,kind='series',show_key=?,meta=?,state='format',
        next_try=0 WHERE id=?""",(topic,showkey(m),json.dumps(m),row['id']))
    c.execute('DELETE FROM metadata_priority WHERE work_id=?',(row['id'],))
    c.execute('DELETE FROM film_hints WHERE work_id=?',(row['id'],))
    c.execute('DELETE FROM series_focus WHERE show_key=?',(row['show_key'],))
    return True

def film_likelihood(source):
    """Priority hint only, never a proof of film identity or an auto-match."""
    if not source:return 0,''
    topic=key(source.get('topic'))
    if topic in NEWS_TOPICS or FORMAT_WORDS.search(topic):return 0,''
    duration=int(source.get('duration') or 0)
    if not 2400<=duration<=15000:return 0,''
    if topic in FILM_RUBRICS:return 3,'Explizite Filmrubrik'
    if topic in FORMAT_GENERIC:return 0,''
    desc=core.clean(source.get('description',''))[:260]
    if FILM_PHRASE.search(desc):return 2,'Ausdrücklicher Filmhinweis im Sendertext'
    return 0,''

def update_film_hint(c,wid,meta,source):
    if meta.get('kind')!='unknown':return
    score,reason=film_likelihood(source)
    if score>=2:
        c.execute('INSERT OR REPLACE INTO film_hints VALUES(?,?,?)',(wid,score,reason))
    else:c.execute('DELETE FROM film_hints WHERE work_id=?',(wid,))

def backfill_film_hints(c,limit=400):
    """Resume-friendly, bounded upgrade of existing unknown work hints."""
    cursor=get_state(c,'film_hint_cursor_v0524',0)
    if cursor=='complete':return 0
    rows=c.execute("""SELECT rowid AS rid,id,meta FROM works
        WHERE rowid>? AND kind='unknown' ORDER BY rowid LIMIT ?""",(cursor,limit)).fetchall()
    for row in rows:
        cursor=row['rid']
        offer=c.execute('SELECT payload FROM offers WHERE work_id=? AND active=1 ORDER BY rank DESC LIMIT 1',(row['id'],)).fetchone()
        if offer:
            update_film_hint(c,row['id'],json.loads(row['meta']),json.loads(offer[0]))
    set_state(c,'film_hint_cursor_v0524',cursor if rows else 'complete')
    return len(rows)

# Raise when the format rules change: existing catalogues then get one more format pass.
FORMAT_REV=4   # 0.5.80: clips ('other') and editions named like their Sendung
def assign_formats(c,limit=500):
    """Group news and magazine contributions under their format and take them out of the provider scan."""
    import broadcaster
    if get_state(c,'format_rev',0)<FORMAT_REV:set_state(c,'format_cursor',0);set_state(c,'format_rev',FORMAT_REV)
    cursor=get_state(c,'format_cursor',0)
    dirty_mode=cursor=='complete'
    if dirty_mode:
        rows=c.execute('SELECT w.rowid AS rid,w.* FROM format_dirty f JOIN works w ON w.id=f.work_id ORDER BY w.rowid LIMIT ?',(limit,)).fetchall()
        if not rows:
            # Also discard stale dirty references after merged/deleted works.
            c.execute('DELETE FROM format_dirty WHERE NOT EXISTS(SELECT 1 FROM works w WHERE w.id=format_dirty.work_id)')
            return 0,0
    else:
        rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
    counts={};assigned=0
    for row in rows:
        cursor=row['rid']
        if dirty_mode:c.execute('DELETE FROM format_dirty WHERE work_id=?',(row['id'],))
        open_work=row['kind'] in ('unknown','other') and row['state'] in ('pending','retry')
        if not open_work and not (row['kind']=='series' and row['state']=='identified'):continue
        best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not best:continue
        source=json.loads(best[0])
        if mark_news_format(c,row,source):
            assigned+=1
            continue
        m=json.loads(row['meta']);topic=row['topic'] or source.get('topic') or ''
        if topic not in counts:counts[topic]=c.execute('SELECT COUNT(*) FROM works WHERE topic=?',(topic,)).fetchone()[0]
        if not open_work:
            if not broadcaster_format(m,source,counts[topic]):continue
            # Keep the broadcaster's programme data (picture, description, genres); only stop the rechecks.
            m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
            m.update(state='format',reason='Ausgabe der Sendung „'+m['title']+'“ ('+m['provider']+'); wird nicht einzeln abgeglichen.')
            c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=?",(json.dumps(m),row['id']))
            assigned+=1;continue
        if not format_contribution(m,source,counts[topic]):continue
        fmt=cleaned(source.get('topic'));hints=broadcaster.genres(fmt,source.get('title',''))
        m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
        edition=cleaned(source.get('title'))
        if key(edition)==key(fmt) and source.get('timestamp'):
            # Editions named like the Sendung are told apart by their broadcast date.
            try:edition+=' · '+time.strftime('%d.%m.%Y',time.localtime(int(source['timestamp'])))
            except (TypeError,ValueError,OverflowError,OSError):pass
        m.update(kind='series',title=fmt,episode_title=edition,year=None,season=m.get('season'),episode=m.get('episode'),provider='Sendung',reference_id=None,
                 state='format',genres=normalized_genres(hints or m.get('genres')),genre_source='Sender (abgeleitet)' if hints else m.get('genre_source','Unbekannt'),
                 reason='Beitrag der Sendung „'+fmt+'“; wird nicht mit Filmdatenbanken abgeglichen.')
        c.execute("UPDATE works SET title=?,kind='series',year=NULL,show_key=?,meta=?,state='format',next_try=0 WHERE id=?",(fmt,showkey(m),json.dumps(m),row['id']))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(row['id'],))
        for g in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(row['id'],g))
        assigned+=1
    if not dirty_mode:set_state(c,'format_cursor',cursor if rows else 'complete')
    return len(rows),assigned

def restart_formats(c):set_state(c,'format_cursor',0)

KIND_KEYS=('movie','series','unknown','other')
def recognition(c):
    """Recognition per channel and state; formats are counted separately from open works.

    0.5.80 (Björn: "Erkennungsrate je Sender/Medienart"): every channel row also carries ``kinds`` with
    the counters per media type (movie, series, unknown, other). The main counters keep excluding
    'other' (trailers, clips, live streams), which are not meant to be matched; they are listed as ``clips``."""
    try:
        rows=c.execute("SELECT COALESCE(json_extract(o.payload,'$.channel'),'') channel,w.kind,w.state,COUNT(DISTINCT w.id) n FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 GROUP BY channel,w.kind,w.state").fetchall()
    except sqlite3.OperationalError:
        rows=c.execute("SELECT '' channel,w.kind,w.state,COUNT(*) n FROM works w GROUP BY w.kind,w.state").fetchall()
    out={}
    for r in rows:
        d=out.setdefault(r['channel'] or 'Unbekannt',{'channel':r['channel'] or 'Unbekannt','works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0,'clips':0,
                                                      'kinds':{k:{'works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0} for k in KIND_KEYS}})
        state=r['state'];kind=r['kind'] if r['kind'] in KIND_KEYS else 'unknown'
        key_={'matched':'matched','manual':'matched','identified':'identified','format':'format','review':'review'}.get(state,'open')
        k=d['kinds'][kind];k['works']+=r['n'];k[key_]+=r['n']
        if kind=='other':d['clips']+=r['n'];continue
        d['works']+=r['n'];d[key_]+=r['n']
    return sorted((d for d in out.values() if d['works'] or d['clips']),key=lambda d:-d['works'])

def recognition_totals(rows):
    """Sum of the channel rows per media type (table "Nach Medienart")."""
    total={k:{'works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0} for k in KIND_KEYS}
    for r in rows or []:
        for k,v in (r.get('kinds') or {}).items():
            if k in total:
                for f in total[k]:total[k][f]+=v.get(f,0)
    return [{'kind':k,**v} for k,v in total.items() if v['works']]

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

def recover_download_queue(c):
    """Keep untouched queued jobs runnable after a crash; never replay an in-flight job blindly."""
    c.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('downloading','tagging')")
    
def initialize(c):
    c.executescript(SCHEMA)
    # SQLite CREATE TRIGGER IF NOT EXISTS does not replace older definitions.
    # Rebuild once, preserving all queue rows, retries and user choices.
    if not get_state(c,'episode_queue_causality_triggers_v0531',False):
        c.executescript("""DROP TRIGGER IF EXISTS episode_queue_work_insert;
            DROP TRIGGER IF EXISTS episode_queue_work_update;
            DROP TRIGGER IF EXISTS episode_queue_work_delete;""")
        c.executescript(SCHEMA)
        c.execute("""DELETE FROM episode_queue WHERE EXISTS
            (SELECT 1 FROM works w WHERE w.id=episode_queue.work_id
             AND COALESCE(json_extract(w.meta,'$.video_role_needs_review'),0)!=0)""")
        set_state(c,'episode_queue_causality_triggers_v0531',True)
    # Recreate the trigger definitions without altering existing queue rows.
    # Outer UPSERT conflict handling must never override an inner OR IGNORE.
    if not get_state(c,'episode_queue_safe_upsert_v05311',False):
        c.executescript("""DROP TRIGGER IF EXISTS episode_queue_work_insert;
            DROP TRIGGER IF EXISTS episode_queue_work_update;
            DROP TRIGGER IF EXISTS episode_queue_work_delete;""")
        c.executescript(SCHEMA)
        set_state(c,'episode_queue_safe_upsert_v05311',True)
    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:c.execute("ALTER TABLE works ADD COLUMN topic TEXT DEFAULT ''")
    if not get_state(c,'artwork_discovery_refresh_v047',False):
        c.execute('DELETE FROM artwork_checks');c.execute('DELETE FROM artwork_cache');set_state(c,'artwork_discovery_refresh_v047',True)
    c.execute('CREATE INDEX IF NOT EXISTS work_topic ON works(topic)')
    mark_live(c)
    if not get_state(c,'genre_spellings_v053',False):merge_genre_spellings(c);set_state(c,'genre_spellings_v053',True)
    # One-time migration of existing identified episodes; no destructive resets.
    if not get_state(c,'episode_queue_migrated_v0528',False):
        c.execute("""INSERT OR IGNORE INTO episode_queue(work_id)
            SELECT id FROM works WHERE kind='series' AND state='identified'
            AND NULLIF(json_extract(meta,'$.reference_id'),'') IS NOT NULL
            AND json_type(meta,'$.deferred_providers') IS NULL
            AND COALESCE(json_extract(meta,'$.episode_verified'),0)=0
            AND COALESCE(json_extract(meta,'$.video_role_needs_review'),0)=0""")
        set_state(c,'episode_queue_migrated_v0528',True)

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
