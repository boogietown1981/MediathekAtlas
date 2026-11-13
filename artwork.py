"""Artwork enrichment independent of identity matching; never changes title IDs."""
import json,re,time,urllib.parse,os
from pathlib import Path
import core,diagnostics,metadata
import broadcaster
from vendor.archive_portals import fanart_client
HOSTS={'assets.fanart.tv','image.tmdb.org','artworks.thetvdb.com','www.thetvdb.com','m.media-amazon.com','ia.media-imdb.com','images.justwatch.com'}|broadcaster.IMAGE_HOSTS
# Portal artwork (0.5.42): Pluto TV and Netzkino deliver their covers from these hosts.
PORTAL_HOST=re.compile(r'^(?:[a-z0-9-]+\.)*(?:pluto\.tv|netzkino\.de|cloudfront\.net|rakuten\.tv|wuaki\.tv|ytimg\.com|joyn\.de|toggo\.de|imgix\.net|crunchyroll\.com|plex\.tv)$')
def valid(url):
    p=urllib.parse.urlsplit(str(url or ''))
    return p.scheme=='https' and bool(p.hostname) and (p.hostname in HOSTS or bool(PORTAL_HOST.fullmatch(p.hostname))) and not p.username and p.port in (None,443)
def compatible(m,h):
    title=h.get('title') or h.get('name') or ''
    date=str(h.get('release_date') or h.get('first_air_date') or h.get('year') or '')
    return bool(m.get('year') and date[:4]==str(m['year']) and core.title_similarity(m['title'],title)>=.985)
def lookup(m,s):
    found={};errors=[];tmdb_id=tvdb_id=None;imdb_id=m.get('reference_id') if m.get('provider') in ('OMDb','IMDb Offline') else m.get('imdb_id')
    if s.get('tvdb') and m['kind']=='series':
        try:
            import tvdb
            def get(path,params=None):return tvdb.request(path,s['tvdb'],s.get('tvdb_pin',''),params).get('data') or {}
            sid=m.get('reference_id') if m.get('provider')=='TVDB' else None
            if not sid:
                hits=get('search',{'query':m['title'],'type':'series','language':'deu','limit':10})
                hits=[h for h in hits if compatible(m,h)]
                if len(hits)==1:sid=hits[0].get('tvdb_id')
            if sid:
                tvdb_id=sid
                d=get('series/'+str(sid)+'/extended')
                if valid(d.get('image')):found['poster']=d['image']
                if d.get('overview'):found['show_description']=str(d['overview'])
                types=get('artwork/types');types={t['id']:str(t.get('name','')).lower() for t in types}
                for a in d.get('artworks') or []:
                    name=types.get(a.get('type'),'');url=a.get('image')
                    if valid(url) and ('background' in name or 'fanart' in name):found.setdefault('fanart',url)
                if found:found['artwork_provider']='TVDB'
        except Exception as e:errors.append(core.safe_error(e))
    if s.get('tmdb') and (not m.get('discovery_enriched') or m.get('rating') is None or not all(m.get(k) or found.get(k) for k in ('poster','fanart')) or (m['kind']=='series' and not m.get('show_description'))):
        try:
            kind='tv' if m['kind']=='series' else 'movie';sid=m.get('reference_id') if m.get('provider')=='TMDB' else None
            if not sid and m.get('reference_id') and m.get('provider') in ('OMDb','IMDb Offline','TVDB'):
                source='tvdb_id' if m['provider']=='TVDB' else 'imdb_id'
                hits=core.tmdb('find/'+str(m['reference_id']),s['tmdb'],{'external_source':source}).get(kind+'_results',[])
                if len(hits)==1:sid=hits[0]['id']
            if not sid:
                hits=core.tmdb('search/'+kind,s['tmdb'],{'query':m['title']}).get('results',[])
                hits=[h for h in hits if compatible(m,h)]
                if len(hits)==1:sid=hits[0]['id']
            if sid:
                tmdb_id=sid
                d=core.tmdb(kind+'/'+str(sid),s['tmdb'])
                found['networks']=[x['name'] for x in d.get('networks',[]) if x.get('name')]
                found['studios']=[x['name'] for x in d.get('production_companies',[]) if x.get('name')]
                imdb_id=imdb_id or d.get('imdb_id')
                if not imdb_id and s.get('omdb') and not metadata.omdb_status(s['omdb'])['paused']:
                    imdb_id=core.tmdb(kind+'/'+str(sid)+'/external_ids',s['tmdb']).get('imdb_id')
                if kind=='tv' and d.get('overview'):found['show_description']=str(d['overview'])  # German (de-DE) beats TVDB default language
                if d.get('vote_average') is not None:found.update(rating=d['vote_average'],votes=d.get('vote_count'),rating_source='TMDB')
                for field,key,size in [('poster','poster_path','w500'),('fanart','backdrop_path','w1280')]:
                    if not found.get(field) and str(d.get(key) or '').startswith('/'):
                        found[field]='https://image.tmdb.org/t/p/'+size+d[key]
                found['artwork_provider']=('TVDB + TMDB' if found.get('artwork_provider') else 'TMDB')
        except Exception as e:errors.append(core.safe_error(e))
    if imdb_id:found['imdb_id']=imdb_id
    if fanart_keys(s):
        try:fanart_lookup(m,s,found,imdb_id,tmdb_id,tvdb_id)
        except Exception as e:errors.append(core.safe_error(e))
    if s.get('omdb') and imdb_id and not m.get('ratings') and not metadata.omdb_status(s['omdb'])['paused']:
        try:
            d=metadata.omdb({'i':imdb_id},s['omdb'])
            if d and d.get('imdbID')==imdb_id and d.get('Type')==m['kind']:
                found['ratings']=metadata.parse_ratings(d)
        except Exception as e:errors.append(core.safe_error(e))
    return found,errors

def fanart_keys(s):
    """Fanart.tv (0.5.56, from ArchiveMedia v0.10.53): project key and/or personal client key."""
    return bool(s.get('fanart') or s.get('fanart_personal'))

def _fanart_fetch(request):
    headers={k:v for k,v in request.header_items() if k.lower()!='user-agent'}
    with core.open_url(request.full_url,headers=headers,timeout=12) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname!='webservice.fanart.tv':
            raise ValueError('Fanart.tv: unzulässige Weiterleitung')
        content=response.read(1024*1024+1)
    if len(content)>1024*1024:raise ValueError('Fanart.tv: Antwort zu groß')
    return json.loads(content)

def fanart_lookup(m,s,found,imdb_id=None,tmdb_id=None,tvdb_id=None):
    """Posters, backgrounds and logos for an already identified work.

    Only queried with a known IMDb/TVDB/TMDB ID; Fanart.tv must not contradict
    that ID. Images are reference artwork, never proof of a concrete video file.
    """
    kind=m.get('kind')
    if kind not in ('movie','series'):return None
    if m.get('provider')=='TVDB' and not tvdb_id:tvdb_id=m.get('reference_id')
    if m.get('provider')=='TMDB' and not tmdb_id:tmdb_id=m.get('reference_id')
    ids=[('tvdb',tvdb_id),('imdb',imdb_id),('tmdb',tmdb_id)] if kind=='series' else [('imdb',imdb_id),('tmdb',tmdb_id)]
    for source,ident in ids:
        ident=str(ident or '').strip()
        if not ident:continue
        try:result=fanart_client.lookup(kind,ident,source=source,project_key=s.get('fanart',''),personal_key=s.get('fanart_personal',''),fetch=_fanart_fetch)
        except ValueError as e:
            if 'Ungültig' in str(e):continue
            raise
        found['fanart_checked']=True
        if not result or result.get('confidence')=='conflict':
            if result:found['fanart_conflict']=result.get('reason')
            continue
        images=result.get('images') or {}
        used=False
        for field,key in (('poster','poster'),('fanart','background'),('logo','logo')):
            url=(images.get(key) or {}).get('url')
            if valid(url) and not (m.get(field) or found.get(field)):found[field]=url;used=True
        if used:
            prov=found.get('artwork_provider')
            found['artwork_provider']=prov+' + Fanart.tv' if prov and 'Fanart.tv' not in prov else (prov or 'Fanart.tv')
        return result
    return None

def save_image(url,stem):
    if not valid(url):return False
    stem=Path(stem)
    # Names like 'Mr. Robot - (2015) - …-poster' contain dots: append, never replace a "suffix".
    named=lambda ext:stem.with_name(stem.name+ext)
    if any(named(ext).exists() for ext in ('.jpg','.png')):return True
    try:
        with core.open_url(url) as response:data=response.read(12*1024*1024+1)
        if len(data)>12*1024*1024:return False
        suffix='.jpg' if data.startswith(b'\xff\xd8\xff') else '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else None
        if not suffix:return False
        temp=named(suffix+'.part');dest=named(suffix)
        try:
            with temp.open('xb') as f:f.write(data)
            try:os.link(temp,dest)
            except FileExistsError:pass
        finally:temp.unlink(missing_ok=True)
        return True
    except (OSError,ValueError,TimeoutError):return False

def apply(m,found):
    for field in ('poster','fanart','logo'):
        if found.get(field) and not m.get(field):m[field]=found[field]
    if m.get('rating') is None and found.get('rating') is not None:
        for field in ('rating','votes','rating_source'):m[field]=found.get(field)
    for field in ('networks','studios','ratings','imdb_id','discovery_enriched','fanart_checked'):
        if found.get(field):m[field]=found[field]
    if found.get('show_description') and not m.get('show_description'):m['show_description']=found['show_description']
    m['artwork_provider']=found.get('artwork_provider',m.get('artwork_provider',''))

def share_series(c,row,m,found):
    """Apply one series lookup to all episodes of the same series instead of repeating it per episode."""
    if m.get('kind')!='series' or not row['show_key'] or not m.get('reference_id'):return 0
    count=0;until=time.time()+86400
    for peer in c.execute("SELECT id,meta FROM works WHERE show_key=? AND id!=? AND state IN ('manual','matched','identified')",(row['show_key'],row['id'])).fetchall():
        own=json.loads(peer['meta'])
        if own.get('kind')!='series' or own.get('provider')!=m.get('provider') or own.get('reference_id')!=m.get('reference_id'):continue
        before=json.dumps(own,sort_keys=True);apply(own,found)
        if json.dumps(own,sort_keys=True)!=before:c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(own),peer['id']))
        c.execute('INSERT OR REPLACE INTO artwork_checks VALUES(?,?)',(peer['id'],until));count+=1
    return count

def run_once(service):
    config=service.settings()
    if not config.get('auto_metadata',True) or not (config.get('tvdb') or config.get('tmdb') or config.get('omdb') or fanart_keys(config)):return False
    with service.db() as c:
        row=c.execute("SELECT w.* FROM works w LEFT JOIN artwork_checks a ON a.work_id=w.id WHERE w.state IN ('manual','matched','identified') AND (a.next_try IS NULL OR a.next_try<?) AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) ORDER BY COALESCE(a.next_try,0),w.updated DESC LIMIT 1",(time.time(),)).fetchone()
        if not row:return False
        original=row['meta'];m=json.loads(original)
        # Reserve briefly while lookup runs. A database lock must not make this
        # artwork disappear from the queue for 24 hours.
        c.execute('INSERT OR REPLACE INTO artwork_checks VALUES(?,?)',(row['id'],time.time()+300))
    if m.get('discovery_enriched') and m.get('poster') and m.get('fanart') and m.get('rating') is not None and (not config.get('omdb') or m.get('ratings')) and (m['kind']!='series' or m.get('show_description')) and (not fanart_keys(config) or m.get('fanart_checked') or m.get('logo')):
        with service.db() as c:c.execute('UPDATE artwork_checks SET next_try=? WHERE work_id=?',(time.time()+86400,row['id']))
        return True
    key=core.hashlib.sha256(json.dumps([m.get('provider'),m.get('reference_id'),m['kind'],m['title'],m.get('year'),bool(config.get('tmdb')),bool(config.get('tvdb')),bool(config.get('omdb')),fanart_keys(config),'v0556'],sort_keys=True).encode()).hexdigest()
    with service.db() as c:cache=c.execute('SELECT payload FROM artwork_cache WHERE id=? AND checked>?',(key,time.time()-86400)).fetchone()
    if cache:found,errors=json.loads(cache[0]),[]
    else:
        found,errors=lookup(m,config)
        if not errors and found:found['discovery_enriched']=True
        if not errors:
            with service.db() as c:c.execute('INSERT OR REPLACE INTO artwork_cache VALUES(?,?,?)',(key,json.dumps(found),time.time()))
    shared=0
    with service.db() as c:
        current=c.execute('SELECT meta FROM works WHERE id=?',(row['id'],)).fetchone()
        if current and current[0]==original:
            apply(m,found)
            c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),row['id']))
            if not errors:shared=share_series(c,row,m,found)
    with service.db() as c:
        c.execute('UPDATE artwork_checks SET next_try=? WHERE work_id=?',
                  (time.time()+(3600 if errors else 86400),row['id']))
    service.artwork_checked+=1+shared
    # Cache hits repeat a known result; logging each of them crowded real events out of the rotating log.
    if not cache or errors:diagnostics.event('artwork_checked',title=m['title'],poster=bool(m.get('poster')),fanart=bool(m.get('fanart')),errors=errors,shared=shared)
    return True
