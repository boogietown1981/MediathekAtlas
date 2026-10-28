"""Shared conservative evidence gates for provider fallback and catalogue writes."""
ORDER=('IMDb Offline','TVDB','TMDB','OMDb','Wikidata')
def issues(meta,c):
    errors=[]
    if meta.get('kind') in ('movie','series') and c.get('kind')!=meta['kind']:errors.append('Medienart widerspricht der Quelle')
    if c.get('similarity',0)<.985:errors.append('Titel nicht eindeutig genug')
    if c.get('year_mismatch') or (meta.get('year') and c.get('year') and meta['year']!=c['year']):errors.append('Erscheinungsjahr widersprüchlich')
    if c.get('runtime_mismatch'):errors.append('Laufzeit widersprüchlich')
    if c.get('kind')=='series':
        for field in ('season','episode'):
            if meta.get(field) is not None and c.get(field) is not None and meta[field]!=c[field]:errors.append('Staffel/Folge widersprüchlich')
        if c.get('episode_scan_complete') is False and c.get('episode_verified'):errors.append('Episodenprüfung unvollständig')
    return errors

def verified(meta,c):
    if issues(meta,c):return False
    if c.get('kind')=='series':return bool(c.get('episode_verified') and isinstance(c.get('season'),int) and c['season']>=0 and isinstance(c.get('episode'),int) and c['episode']>0)
    return bool(c.get('kind')=='movie' and (c.get('runtime_agrees') or meta.get('year') and c.get('year')==meta['year']))

def conflict(a,b):
    if a.get('kind')!=b.get('kind'):return True
    if a.get('year') and b.get('year') and a['year']!=b['year']:return True
    if a.get('provider')==b.get('provider') and a.get('reference_id')!=b.get('reference_id'):return True
    if {a.get('provider'),b.get('provider')}<= {'OMDb','IMDb Offline'} and a.get('reference_id')!=b.get('reference_id'):return True
    if a.get('kind')=='series' and a.get('episode_verified') and b.get('episode_verified'):
        return (a.get('season'),a.get('episode'))!=(b.get('season'),b.get('episode'))
    return False

def choose(meta,rows,work_only=False):
    good=[c for c in rows if not issues(meta,c) and ((work_only and (c.get('provider') in ORDER[:-1] or c.get('confidence')=='high')) or verified(meta,c))]
    if not good or any(conflict(a,b) for i,a in enumerate(good) for b in good[i+1:]):return None
    good.sort(key=lambda c:ORDER.index(c.get('provider')) if c.get('provider') in ORDER else 99)
    chosen=dict(good[0]);sources=dict(chosen.get('field_sources') or {})
    # Never mix provider IDs or episode evidence. Supplement only compatible titles.
    import core
    for c in good[1:]:
        if core.title_similarity(chosen.get('title',''),c.get('title',''))<.985:continue
        for key in ('genres','description','poster','cast','directors','writers'):
            if not chosen.get(key) and c.get(key):chosen[key]=c[key];sources[key]=c.get('provider')
    if sources:chosen['field_sources']=sources
    return chosen

def sufficient(meta,rows):
    c=choose(meta,rows)
    return bool(c and c.get('year') and c.get('genres'))
