"""Shared conservative evidence gates for provider fallback and catalogue writes."""
ORDER=('IMDb Offline','TVDB','TMDB','OMDb','Wikidata')
def issues(meta,c,work_only=False):
    errors=[]
    if meta.get('kind') in ('movie','series') and c.get('kind')!=meta['kind']:errors.append('Medienart widerspricht der Quelle')
    if c.get('similarity',0)<.985:errors.append('Titel nicht eindeutig genug')
    if (c.get('year_mismatch') or (meta.get('year') and c.get('year') and meta['year']!=c['year'])) and not year_close(meta,c):
        errors.append('Erscheinungsjahr widersprüchlich')
    # Short clips may share a valid *show* title. They can receive the series
    # identity, but never a verified full-episode identity.
    suspicious=bool(c.get('video_role_needs_review'))
    if suspicious and not work_only:errors.append('Video ist vermutlich Trailer/Ausschnitt, nicht vollständige Folge')
    if c.get('identity_contradicted'):errors.append('Gleichnamige alte Miniserie, keine bestätigte Folge')
    if c.get('runtime_mismatch') and not (work_only and suspicious and c.get('kind')=='series'):
        errors.append('Laufzeit widersprüchlich')
    if c.get('kind')=='series':
        for field in ('season','episode'):
            if meta.get(field) is not None and c.get(field) is not None and meta[field]!=c[field]:errors.append('Staffel/Folge widersprüchlich')
        if c.get('episode_scan_complete') is False and c.get('episode_verified'):errors.append('Episodenprüfung unvollständig')
    return errors

def year_close(meta,c):
    """0.6.97 (Mac-Abfrage Runde 6: 113+20 IMDb- und 145 TMDB-Filme „prüfen“ nur wegen des Jahres): the broadcaster
    names the production year („Spielfilm Deutschland 2015“), IMDb the release year (2016, „Im Zweifel“). One year
    apart with an exact title and an agreeing running time is the same film."""
    try:a=int(meta.get('year'));b=int(c.get('year'))
    except (TypeError,ValueError):return False
    # 0.6.108 (Mac-Prüfung 0.6.97 B5: „Sport“ 9 min und „Moda“ 10 min aus SRF „Dai, domanda!“ wurden TMDB-Filme von
    # 1999/1996): only a feature-length video, with its running time known, is a film one year apart.
    try:duration=float(c.get('source_duration_seconds') or 0)
    except (TypeError,ValueError):duration=0
    # 0.6.135 (Prüfvermerk 0.6.134: „More than Honey – Dokumentarfilm …, Schweiz 2010“, IMDb 2012, Titel exakt,
    # Laufzeit passt): two years apart only with the exact title and a feature-length video.
    # 0.6.136 (Mac-Prüfung 0.6.135: „Black Box - Spielfilm, Deutschland 2022“, 115 min, wurde TMDB „Black Box“ USA
    # 2020, 100 min – TMDB's own runtime tolerance of 15 % let it agree): two years apart also need the local IMDb
    # archive and a running time within YEAR_TWO_RUNTIME of the IMDb runtime (More than Honey 95/88 min).
    gap=abs(a-b);similarity=float(c.get('similarity') or 0)
    near=gap==1 and similarity>=.985 and duration>=YEAR_CLOSE_MIN_SECONDS or gap==2 and similarity>=.999 and duration>=YEAR_TWO_MIN_SECONDS and year_two_runtime(c,duration)
    return bool(c.get('kind')=='movie' and near and c.get('runtime_agrees') and not c.get('runtime_mismatch'))

YEAR_CLOSE_MIN_SECONDS=40*60
YEAR_TWO_MIN_SECONDS=60*60
YEAR_TWO_RUNTIME=.08

def year_two_runtime(c,duration):
    if c.get('provider')!='IMDb Offline':return False
    # 0.6.138 (Mac-Prüfung 0.6.136): IMDb Offline film candidates carry imdb_runtime_seconds, not reference_runtime_seconds
    try:ref=float(c.get('imdb_runtime_seconds') or c.get('reference_runtime_seconds') or 0)
    except (TypeError,ValueError):return False
    return bool(ref and abs(ref-duration)<=max(300,ref*YEAR_TWO_RUNTIME))

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
    good=[c for c in rows if not issues(meta,c,work_only=work_only) and ((work_only and (c.get('provider') in ORDER[:-1] or c.get('confidence')=='high')) or verified(meta,c))]
    if good and any(conflict(a,b) for i,a in enumerate(good) for b in good[i+1:]):
        # 0.6.128 (Diagnose Pro 0.6.127: „Terrified – Spielfilm, Argentinien 2017“ mit 8 Kandidaten „prüfen“): among
        # films that disagree, those with the title year and an agreeing running time decide – if they agree.
        good=[c for c in good if c.get('kind')=='movie' and meta.get('year') and str(c.get('year'))==str(meta['year'])
              and c.get('runtime_agrees') and not c.get('runtime_mismatch')]
        if any(conflict(a,b) for i,a in enumerate(good) for b in good[i+1:]):return None
    if not good:return None
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
    """Stop expensive fallback requests after a safely verified local result.

    Genre enrichment can run later; never skip corroboration for a title-only match.
    """
    c=choose(meta,rows)
    if not c or not c.get('year'):return False
    # 0.6.97: a year-close film (±1) may be chosen, but still gets online corroboration.
    if meta.get('year') and str(meta['year'])!=str(c['year']):return False
    if c.get('genres'):return True
    return bool(c.get('provider')=='IMDb Offline' and (
        c.get('kind')=='movie' and c.get('runtime_agrees') or
        c.get('kind')=='series' and c.get('episode_verified')))
