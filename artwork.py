"""Artwork enrichment independent of identity matching; never changes title IDs."""
import json,time,urllib.parse,os
from pathlib import Path
import core,diagnostics,metadata
import broadcaster
HOSTS={'image.tmdb.org','artworks.thetvdb.com','www.thetvdb.com','m.media-amazon.com','ia.media-imdb.com'}|broadcaster.IMAGE_HOSTS
def valid(url):
    p=urllib.parse.urlsplit(str(url or ''))
    return p.scheme=='https' and p.hostname in HOSTS and not p.username and p.port in (None,443)
def compatible(m,h):
    title=h.get('title') or h.get('name') or ''
    date=str(h.get('release_date') or h.get('first_air_date') or h.get('year') or '')
    return bool(m.get('year') and date[:4]==str(m['year']) and core.title_similarity(m['title'],title)>=.985)
def lookup(m,s):
    found={};errors=[];imdb_id=m.get('reference_id') if m.get('provider') in ('OMDb','IMDb Offline') else m.get('imdb_id')
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
                d=get('series/'+str(sid)+'/extended')
                if valid(d.get('image')):found['poster']=d['image']
                types=get('artwork/types');types={t['id']:str(t.get('name','')).lower() for t in types}
                for a in d.get('artworks') or []:
                    name=types.get(a.get('type'),'');url=a.get('image')
                    if valid(url) and ('background' in name or 'fanart' in name):found.setdefault('fanart',url)
                if found:found['artwork_provider']='TVDB'
        except Exception as e:errors.append(core.safe_error(e))
    if s.get('tmdb') and (not m.get('discovery_enriched') or m.get('rating') is None or not all(m.get(k) or found.get(k) for k in ('poster','fanart'))):
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
                d=core.tmdb(kind+'/'+str(sid),s['tmdb'])
                found['networks']=[x['name'] for x in d.get('networks',[]) if x.get('name')]
                found['studios']=[x['name'] for x in d.get('production_companies',[]) if x.get('name')]
                imdb_id=imdb_id or d.get('imdb_id')
                if not imdb_id and s.get('omdb') and not metadata.omdb_status(s['omdb'])['paused']:
                    imdb_id=core.tmdb(kind+'/'+str(sid)+'/external_ids',s['tmdb']).get('imdb_id')
                if d.get('vote_average') is not None:found.update(rating=d['vote_average'],votes=d.get('vote_count'),rating_source='TMDB')
                for field,key,size in [('poster','poster_path','w500'),('fanart','backdrop_path','w1280')]:
                    if not found.get(field) and str(d.get(key) or '').startswith('/'):
                        found[field]='https://image.tmdb.org/t/p/'+size+d[key]
                found['artwork_provider']=('TVDB + TMDB' if found.get('artwork_provider') else 'TMDB')
        except Exception as e:errors.append(core.safe_error(e))
    if imdb_id:found['imdb_id']=imdb_id
    if s.get('omdb') and imdb_id and not m.get('ratings') and not metadata.omdb_status(s['omdb'])['paused']:
        try:
            d=metadata.omdb({'i':imdb_id},s['omdb'])
            if d and d.get('imdbID')==imdb_id and d.get('Type')==m['kind']:
                found['ratings']=metadata.parse_ratings(d)
        except Exception as e:errors.append(core.safe_error(e))
    return found,errors

def save_image(url,stem):
    if not valid(url):return False
    stem=Path(stem)
    if any(stem.with_suffix(ext).exists() for ext in ('.jpg','.png')):return True
    try:
        with core.open_url(url) as response:data=response.read(12*1024*1024+1)
        if len(data)>12*1024*1024:return False
        suffix='.jpg' if data.startswith(b'\xff\xd8\xff') else '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else None
        if not suffix:return False
        temp=stem.with_suffix(suffix+'.part');dest=stem.with_suffix(suffix)
        try:
            with temp.open('xb') as f:f.write(data)
            try:os.link(temp,dest)
            except FileExistsError:pass
        finally:temp.unlink(missing_ok=True)
        return True
    except (OSError,ValueError,TimeoutError):return False

def apply(m,found):
    for field in ('poster','fanart'):
        if found.get(field) and not m.get(field):m[field]=found[field]
    if m.get('rating') is None and found.get('rating') is not None:
        for field in ('rating','votes','rating_source'):m[field]=found.get(field)
    for field in ('networks','studios','ratings','imdb_id','discovery_enriched'):
        if found.get(field):m[field]=found[field]
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
    if not config.get('auto_metadata',True) or not (config.get('tvdb') or config.get('tmdb') or config.get('omdb')):return False
    with service.db() as c:
        row=c.execute("SELECT w.* FROM works w LEFT JOIN artwork_checks a ON a.work_id=w.id WHERE w.state IN ('manual','matched','identified') AND (a.next_try IS NULL OR a.next_try<?) AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) ORDER BY COALESCE(a.next_try,0),w.updated DESC LIMIT 1",(time.time(),)).fetchone()
        if not row:return False
        original=row['meta'];m=json.loads(original)
        c.execute('INSERT OR REPLACE INTO artwork_checks VALUES(?,?)',(row['id'],time.time()+86400))
    if m.get('discovery_enriched') and m.get('poster') and m.get('fanart') and m.get('rating') is not None and (not config.get('omdb') or m.get('ratings')):return True
    key=core.hashlib.sha256(json.dumps([m.get('provider'),m.get('reference_id'),m['kind'],m['title'],m.get('year'),bool(config.get('tmdb')),bool(config.get('tvdb')),bool(config.get('omdb')),'v047'],sort_keys=True).encode()).hexdigest()
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
    service.artwork_checked+=1+shared
    # Cache hits repeat a known result; logging each of them crowded real events out of the rotating log.
    if not cache or errors:diagnostics.event('artwork_checked',title=m['title'],poster=bool(m.get('poster')),fanart=bool(m.get('fanart')),errors=errors,shared=shared)
    return True
