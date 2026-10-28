"""Additional reference evidence for media works (not proof of file identity).

Wikidata is available without a secret, and supplies Wikipedia links and IMDb IDs.
OMDb is strictly opt-in with a legitimate user API key. IMDb's optional local
non-commercial TSV dataset is queried offline; this module never scrapes IMDb
or Google and never promotes a filename-only match to a confirmed work.
"""
from __future__ import annotations
import csv, difflib, gzip, json, re, time, unicodedata, urllib.error, urllib.parse, urllib.request
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS external_evidence(
 group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, candidate_id TEXT, candidate_title TEXT,
 candidate_year INTEGER, candidate_kind TEXT, confidence TEXT NOT NULL,
 reason TEXT, imdb_id TEXT, url TEXT, payload TEXT,
 checked TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(group_id,provider));
CREATE TABLE IF NOT EXISTS external_research(
 group_id TEXT PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER DEFAULT 0,
 checked TEXT, retry_after TEXT, last_error TEXT);
CREATE INDEX IF NOT EXISTS ix_external_research_state ON external_research(state,retry_after);
CREATE TABLE IF NOT EXISTS imdb_offline_titles(
 imdb_id TEXT PRIMARY KEY, title TEXT, original_title TEXT, kind TEXT,
 year INTEGER, duration_minutes INTEGER, title_key TEXT);
CREATE INDEX IF NOT EXISTS ix_imdb_offline_title ON imdb_offline_titles(title_key,kind);
CREATE TABLE IF NOT EXISTS external_catalog_state(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS external_title_cache(cache_key TEXT PRIMARY KEY,payload TEXT,checked TEXT DEFAULT CURRENT_TIMESTAMP);
'''

UA='ArchiveMedia/0.10.12 (https://github.com/boogietown1981/ArchiveMedia; local personal media catalog)'
WD='https://www.wikidata.org/w/api.php'
FILM={'Q11424','Q932586','Q24869','Q202866'}
SERIES={'Q5398426','Q15416','Q21191270','Q1259759','Q117467246','Q11266439','Q581714'}


def normalize(value):
    s=unicodedata.normalize('NFKD',str(value or '').casefold())
    s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^\w]+',' ',s,flags=re.UNICODE).strip()


def title_similarity(a,b):
    aa,bb=normalize(a),normalize(b)
    return difflib.SequenceMatcher(None,aa,bb).ratio() if aa and bb else 0


def safe_year(value):
    m=re.search(r'(?<!\d)(18\d\d|19\d\d|20\d\d|210\d)(?!\d)',str(value or ''))
    return int(m.group(1)) if m else None


def fetch_json(url,params=None,timeout=15):
    if params:url+='?'+urllib.parse.urlencode(params)
    host=urllib.parse.urlparse(url).hostname
    if host not in ('www.wikidata.org','www.omdbapi.com') or not url.startswith('https://'):
        raise ValueError('Nicht erlaubter Metadatenserver')
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        if urllib.parse.urlparse(response.geturl()).hostname != host:
            raise ValueError('Metadaten-Redirect auf fremde Domain')
        data=response.read(512*1024+1)
    if len(data)>512*1024:raise ValueError('Metadatenantwort zu groß')
    return json.loads(data)


def _entity_year(entity):
    claims=entity.get('claims') or {}
    for key in ('P577','P580'):
        for statement in claims.get(key,[]):
            val=((statement.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {}
            year=safe_year(val.get('time') if isinstance(val,dict) else val)
            if year:return year
    return None


def _claim_ids(entity,prop):
    out=[]
    for item in (entity.get('claims') or {}).get(prop,[]):
        value=((item.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(value,dict) and value.get('id'):out.append(value['id'])
        elif isinstance(value,str):out.append(value)
    return out


def _entity_names(entity):
    names=[]
    for block in (entity.get('labels') or {}).values():
        if isinstance(block,dict):names.append(block.get('value',''))
    for blocks in (entity.get('aliases') or {}).values():
        for b in blocks:
            if isinstance(b,dict):names.append(b.get('value',''))
    return names


def classify_entity(entity,kind):
    classes=set(_claim_ids(entity,'P31'))
    known=FILM if kind=='movie' else SERIES
    incompatible=SERIES if kind=='movie' else FILM
    if classes & incompatible and not classes & known:return 'wrong_type'
    if classes & known:return 'correct_type'
    descriptions=' '.join(str(b.get('value','')) for b in (entity.get('descriptions') or {}).values() if isinstance(b,dict)).casefold()
    if kind=='movie' and any(k in descriptions for k in ('film','movie','motion picture')):return 'text_type'
    if kind=='series' and any(k in descriptions for k in ('television series','tv series','anime series','animated series','fernsehserie')):return 'text_type'
    return 'unknown_type'


def wikidata_lookup(title,kind,year=None,fetch=fetch_json):
    """Find cautious candidate only; never call it confirmed media or stream."""
    term=str(title or '').strip()[:150]
    if len(term)<4:return None
    found=[]
    for lang in ('en','de'):
        data=fetch(WD,{'action':'wbsearchentities','search':term,'language':lang,'format':'json','limit':7,'type':'item'})
        found.extend([x.get('id') for x in (data.get('search') or []) if re.fullmatch(r'Q\d+',str(x.get('id','')))])
        if found:break
    ids=list(dict.fromkeys(found))[:7]
    if not ids:return None
    entities=fetch(WD,{'action':'wbgetentities','ids':'|'.join(ids),'props':'labels|aliases|descriptions|claims|sitelinks','languages':'en|de|ja','format':'json'}).get('entities') or {}
    candidates=[]
    for eid in ids:
        ent=entities.get(eid) or {}
        names=_entity_names(ent)
        scores=[(title_similarity(title,n),n) for n in names if n]
        if not scores:continue
        sim,label=max(scores)
        if sim<.90:continue
        ty=classify_entity(ent,kind)
        if ty=='wrong_type':continue
        release=_entity_year(ent)
        if year and release and abs(year-release)>1:continue
        # Inexact spellings can be evidence, never strong enough to become a match.
        score=sim + (.025 if ty=='correct_type' else .005 if ty=='text_type' else -.05)
        if year and release and abs(year-release)<=1:score+=.01
        sitelinks=ent.get('sitelinks') or {}
        wiki=next((sitelinks.get(k,{}).get('title') for k in ('dewiki','enwiki') if sitelinks.get(k,{}).get('title')),None)
        lang='de' if 'dewiki' in sitelinks else 'en'
        wikipedia_url='https://'+lang+'.wikipedia.org/wiki/'+urllib.parse.quote(wiki.replace(' ','_')) if wiki else None
        imdb=next((x for x in _claim_ids(ent,'P345') if re.fullmatch(r'tt\d{5,12}',x)),None)
        candidates.append((score,{'provider':'Wikidata','candidate_id':eid,'candidate_title':label,
            'candidate_year':release,'candidate_kind':kind,'imdb_id':imdb,
            'url':'https://www.wikidata.org/wiki/'+eid,'wikipedia_url':wikipedia_url,
            'evidence_type':ty,'similarity':round(sim,4)}))
    if not candidates:return None
    candidates.sort(key=lambda x:x[0],reverse=True)
    score,top=candidates[0]
    margin=score-candidates[1][0] if len(candidates)>1 else 1
    strong=top['similarity']>=.985 and top['evidence_type'] in ('correct_type','text_type') and margin>=.04
    top['confidence']='high' if strong else 'possible'
    top['reason']='Titel/Typ eindeutig; weiterhin kein Nachweis der Videodatei' if strong else 'Mehrdeutige oder unvollständige Titel-/Typbelege'
    top['alternatives']=len(candidates)-1
    return top


def omdb_lookup(title,kind,api_key,year=None,fetch=fetch_json):
    if not api_key:return None
    params={'apikey':api_key,'t':str(title)[:150],'type':'series' if kind=='series' else 'movie'}
    if year:params['y']=int(year)
    d=fetch('https://www.omdbapi.com/',params)
    if d.get('Response')=='False' or not d.get('Title'):return None
    sim=title_similarity(title,d['Title'])
    found_year=safe_year(d.get('Year'))
    if sim<.94 or year and found_year and abs(year-found_year)>1:return None
    kind_value='series' if d.get('Type')=='series' else 'movie' if d.get('Type')=='movie' else 'unknown'
    if kind_value!=kind:return None
    iid=str(d.get('imdbID') or '')
    return {'provider':'OMDb','candidate_id':iid if re.fullmatch(r'tt\d{5,12}',iid) else None,
            'candidate_title':d['Title'],'candidate_year':found_year,'candidate_kind':kind,
            'imdb_id':iid if iid.startswith('tt') else None,
            'url':'https://www.imdb.com/title/'+iid+'/' if re.fullmatch(r'tt\d{5,12}',iid) else None,
            'confidence':'high' if sim>=.985 else 'possible',
            'reason':'OMDb-Titel und Medienart stimmen überein; Medieninhalt nicht verifiziert','similarity':round(sim,4),
            'runtime_minutes':int(re.search(r'\d+',str(d.get('Runtime') or '0')).group()) if re.search(r'\d+',str(d.get('Runtime') or '')) else None}


def imdb_local_candidates(c,title,kind,year=None):
    candidates=c.execute('''SELECT * FROM imdb_offline_titles WHERE title_key=? AND kind=? LIMIT 12''',(normalize(title),kind)).fetchall()
    out=[]
    for row in candidates:
        r=dict(row)
        if year and r['year'] and abs(r['year']-year)>1:continue
        out.append({'provider':'IMDb lokal','candidate_id':r['imdb_id'],'candidate_title':r['title'],
            'candidate_year':r['year'],'candidate_kind':r['kind'],'imdb_id':r['imdb_id'],
            'url':'https://www.imdb.com/title/'+r['imdb_id']+'/',
            'confidence':'high' if len(candidates)==1 else 'possible',
            'reason':'Offizieller IMDb-TSV-Titelvergleich; keine Dateiidentifikation'})
    return out[:4]


def imdb_import(path,eligible_titles,commit_batch):
    """Read official personal-use title.basics.tsv(.gz); retain only catalogue matches.

    Does not download or republish IMDb data, never reads the entire file into RAM.
    Callable asynchronously; commit_batch is a callback processing bounded batches.
    """
    filename=Path(path).expanduser()
    if filename.name not in ('title.basics.tsv.gz','title.basics.tsv') or not filename.is_file():
        raise ValueError('Nur eine vorhandene IMDb-Datei title.basics.tsv.gz oder .tsv zulässig')
    keys={normalize(t) for t in eligible_titles if t}
    counter=0;rows=[]
    opener=gzip.open if filename.suffix=='.gz' else open
    with opener(filename,'rt',encoding='utf-8',errors='replace',newline='') as f:
        for item in csv.DictReader(f,delimiter='\t'):
            if item.get('titleType') not in ('movie','tvMovie','tvSeries','tvMiniSeries'):continue
            title=item.get('primaryTitle','')
            original=item.get('originalTitle','')
            key=normalize(title);key2=normalize(original)
            if key not in keys and key2 not in keys:continue
            yy=safe_year(item.get('startYear'))
            runtime=item.get('runtimeMinutes')
            rows.append((item.get('tconst'),title,original,'series' if item['titleType'] in ('tvSeries','tvMiniSeries') else 'movie',yy,int(runtime) if str(runtime).isdigit() else None,key if key in keys else key2))
            if len(rows)>=250:
                commit_batch(rows);counter+=len(rows);rows=[]
    if rows:commit_batch(rows);counter+=len(rows)
    return counter


def research_links(title,kind):
    query=(str(title)[:140]+' '+('TV series' if kind=='series' else 'film')).strip()
    return {'google':'https://www.google.com/search?q='+urllib.parse.quote(query),
            'wikipedia':'https://en.wikipedia.org/w/index.php?search='+urllib.parse.quote(query),
            'imdb':'https://www.imdb.com/find/?q='+urllib.parse.quote(query)}


def store(c,group_id,row):
    c.execute('''INSERT INTO external_evidence(group_id,provider,candidate_id,candidate_title,candidate_year,candidate_kind,confidence,reason,imdb_id,url,payload,checked)
       VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
       ON CONFLICT(group_id,provider) DO UPDATE SET candidate_id=excluded.candidate_id,candidate_title=excluded.candidate_title,
       candidate_year=excluded.candidate_year,candidate_kind=excluded.candidate_kind,confidence=excluded.confidence,
       reason=excluded.reason,imdb_id=excluded.imdb_id,url=excluded.url,payload=excluded.payload,checked=CURRENT_TIMESTAMP''',
       (group_id,row['provider'],row.get('candidate_id'),row.get('candidate_title'),row.get('candidate_year'),row.get('candidate_kind'),row.get('confidence','possible'),row.get('reason'),row.get('imdb_id'),row.get('url'),json.dumps(row,ensure_ascii=False)[:6000]))
