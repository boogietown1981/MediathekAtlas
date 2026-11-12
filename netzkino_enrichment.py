"""On-demand, conservative enrichment of Netzkino titles via MediathekAtlas providers.

Reuses the ARD/ZDF ``core.candidates -> metadata.candidates`` provider chain
(IMDb Offline, TVDB, TMDB, OMDb, Wikidata), with explicit caller action only.
Never writes broadcaster works/offers/queues or treats extractor information as
permission to download. Results live exclusively in Netzkino's local SQLite.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import netzkino
import netzkino_details

SCHEMA = '''
CREATE TABLE IF NOT EXISTS netzkino_reference_checks (
  item_id TEXT PRIMARY KEY,
  identity_hash TEXT NOT NULL,
  checked REAL NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nk_ref_checked ON netzkino_reference_checks(checked);
'''
PROVIDER_ORDER = ('IMDb Offline', 'TVDB', 'TMDB', 'OMDb', 'Wikidata')
PROVIDERS = frozenset(PROVIDER_ORDER)
STATUSES = frozenset(('checked','paused','error','not_configured','negative_cache'))
GOOD_TTL = 7 * 86400
# 0.5.43: version of the evaluation rules in analyze(). Reports in 'review' made by an older
# version are checked again automatically (year preference, one-year tolerance).
ANALYSIS = 2
STALE_REVIEW = ("(json_extract(r.payload,'$.status')='review' AND "
                "IFNULL(json_extract(r.payload,'$.analysis'),1)<%d)" % ANALYSIS)


def stale_review(payload):
    try:
        r = json.loads(payload) if isinstance(payload, str) else payload
        return r.get('status') == 'review' and int(r.get('analysis') or 1) < ANALYSIS
    except (TypeError, ValueError, AttributeError):
        return False
RETRY_TTL = 3600
MAX_REFERENCES = 8
MAX_STRING = 1800


def _str(value, limit=240):
    if not isinstance(value, str):return ''
    return ' '.join(value.split())[:limit]


def _integer(value, minimum=0, maximum=100000):
    try:
        if isinstance(value,bool):return None
        val=int(value)
        return val if minimum <= val <= maximum else None
    except (ValueError,TypeError,OverflowError):return None


def _list(value, maximum=20):
    if not isinstance(value,(list,tuple)):return []
    out=[]
    for val in value[:75]:
        name=_str(val,130)
        if name and name not in out:out.append(name)
        if len(out)>=maximum:break
    return out


def _image(url):
    # Provider artwork only, not arbitrary signed or authenticated URLs.
    if not isinstance(url,str) or len(url)>450:return ''
    try:
        p=urlsplit(url)
        if (p.scheme!='https' or p.username or p.password or p.port not in (None,443)
                or p.query or p.fragment):return ''
        if p.hostname not in ('image.tmdb.org','artworks.thetvdb.com','m.media-amazon.com'):
            return ''
        return url
    except ValueError:return ''


def _ref_id(provider, value):
    val=_str(value,60)
    if provider in ('IMDb Offline','OMDb'):
        return val if re.fullmatch(r'tt\d{5,12}',val) else ''
    if provider in ('TMDB','TVDB'):
        return val if re.fullmatch(r'\d{1,12}',val) else ''
    if provider=='Wikidata':
        return val if re.fullmatch(r'Q\d{1,13}',val) else ''
    return ''


def _rating(value):
    try:
        score=float(value)
        return round(score,2) if 0<=score<=10 else None
    except (TypeError,ValueError,OverflowError):return None


def _candidate(src, meta, *, match_issues=None):
    if not isinstance(src,dict):return None
    provider=_str(src.get('provider'),40)
    if provider not in PROVIDERS:return None
    reference=_ref_id(provider,src.get('reference_id'))
    score=src.get('similarity',0)
    try:score=float(score)
    except (TypeError,ValueError):score=0.0
    score=max(0.0,min(1.0,score))
    kind=src.get('kind') if src.get('kind') in ('movie','series') else ''
    title=_str(src.get('title'),240)
    if not title or not reference or not kind:return None
    # ARD/ZDF's conservative checks are reused when the source module is available.
    if match_issues is None:
        try:
            import matching
            issues=matching.issues(meta,src,work_only=True)
        except ImportError:
            issues=[]
    else:issues=match_issues(meta,src)
    problems=[]
    if kind!=meta['kind']:problems.append('Medienart widerspricht dem Netzkino-Eintrag')
    if score < .985:problems.append('Titelähnlichkeit nicht eindeutig')
    source_year=meta.get('year')
    year=_integer(src.get('year'),1880,2100)
    # One year apart is common (festival vs. cinema release, German release); analyze()
    # still prefers an exact year.
    if source_year and year and abs(source_year-year)>1:
        problems.append('Erscheinungsjahr widersprüchlich')
    if src.get('runtime_mismatch'):problems.append('Laufzeit widersprüchlich')
    for reason in issues:
        note=_str(reason,110)
        if note and note not in problems:problems.append(note)
    # A known series is NOT automatically a verified episode.
    episode_verified=bool(src.get('episode_verified'))
    season=_integer(src.get('season'),0,999)
    episode=_integer(src.get('episode'),1,9999)
    if meta['kind']=='series' and meta.get('episode') is not None:
        episode_verified=bool(episode_verified and season is not None and episode is not None
                              and season==meta.get('season') and episode==meta['episode'])
    result={
        'provider':provider,'reference_id':reference,'title':title,'kind':kind,
        'year':year,'similarity':round(score,4),
        'issues':problems[:6], 'episode_verified':episode_verified,
        'season':season if episode_verified else None,
        'episode':episode if episode_verified else None,
        'genres':_list(src.get('genres'),15),
        'description':_str(src.get('description'),2600),
        'show_description':_str(src.get('show_description'),2600),
        'cast':_list(src.get('cast'),16),
        'directors':_list(src.get('directors'),12),
        'writers':_list(src.get('writers'),12),
        'poster':_image(src.get('poster')),
        'rating':_rating(src.get('rating')),
        'votes':_integer(src.get('votes'),0,1000000000),
    }
    # Reference identity is used solely as an evidence suggestion.
    result['eligible']=bool(not problems)
    return result


def _identity(row, editorial, classification):
    source=editorial or {}
    label=classification.get('series_title') if classification.get('media_type')!='movie' else source.get('title') or row.get('title')
    year=source.get('year') or row.get('year')
    # Netzkino's productionYear may refer to a particular episode, not series premiere.
    if classification.get('media_type')=='episode':year=None
    return {'kind':'series' if classification.get('media_type')!='movie' else 'movie',
            'title':_str(label or row.get('title'),240),
            'year':_integer(year,1880,2100),
            'season':classification.get('season'),
            'episode':classification.get('episode'),
            'episode_title':_str(classification.get('episode_title'),220)}


def _merge(editorial, selected, *, episode_mode=False):
    # An independent reference can fill holes only; original provider fields win.
    original={key:editorial.get(key) for key in ('title','original_title','year','duration_seconds','fsk',
        'description','short_description','genres','country','original_language',
        'cast','directors','writers','poster','backdrop','access_types')}
    output=dict(original)
    provenance={k:'Netzkino' for k,v in output.items() if v not in ('',None,[],{})}
    if selected:
        for field in ('description','genres','cast','directors','writers','poster'):
            if output.get(field):continue
            if field=='description' and episode_mode and not selected['episode_verified']:
                continue  # a series summary never masquerades as an episode synopsis
            value=selected.get(field)
            if value:
                output[field]=value;provenance[field]=selected['provider']
        if (output.get('description') and selected.get('description') and
                not episode_mode and len(selected['description']) >= len(output['description']) + 140):
            # Keep Netzkino's editorial synopsis; show additional provider detail separately.
            output['reference_description']=selected['description']
            provenance['reference_description']=selected['provider']
        if episode_mode and not selected['episode_verified'] and not output.get('description'):
            # Clearly separated informational parent-show description.
            show=selected.get('show_description') or selected.get('description')
            if show:output['series_description']=show;provenance['series_description']=selected['provider']
        if selected.get('rating') is not None:
            output['rating']=selected['rating'];provenance['rating']=selected['provider']
            if selected.get('votes') is not None:
                output['votes']=selected['votes'];provenance['votes']=selected['provider']
    return output,provenance


def _safe_checks(checks):
    result=[]
    for row in checks[:25] if isinstance(checks,list) else []:
        if not isinstance(row,dict):continue
        provider=row.get('provider');status=row.get('status')
        if provider not in PROVIDERS or status not in STATUSES:continue
        result.append({'provider':provider,'status':status,'candidates':_integer(row.get('count'),0,1000) or 0})
    return result


def analyze(meta,editorial,results,*,match_issues=None):
    """Pure evaluation of the existing ARD provider results; never auto-assign."""
    entries=[]
    checks=[]
    paused=False
    for data in results:
        if not isinstance(data,dict):continue
        checks.extend(_safe_checks(data.get('provider_checks',[])))
        paused=paused or bool(data.get('warnings') or data.get('deferred_providers'))
        for src in data.get('candidates',[])[:70]:
            cand=_candidate(src,meta,match_issues=match_issues)
            if cand and not any(x['provider']==cand['provider'] and x['reference_id']==cand['reference_id'] for x in entries):
                entries.append(cand)
    entries.sort(key=lambda c:(0 if c['eligible'] else 1,
              PROVIDER_ORDER.index(c['provider']), -c['similarity']))
    good=[x for x in entries if x['eligible']]
    # 0.5.43 (Björn: "#Roxy" 2018 had six IMDb hits of the same name and stayed unassigned):
    # when the provider publishes a year, a candidate of exactly that year beats candidates
    # of the same database without a year, and years one apart (TMDB/IMDb release dates)
    # do not count as a contradiction.
    year=meta.get('year') if isinstance(meta.get('year'),int) else None
    if year:
        tier=lambda x:0 if x['year']==year else 1 if x['year'] is not None else 2
        best={}
        for x in good:best[x['provider']]=min(best.get(x['provider'],3),tier(x))
        for x in good:
            if tier(x)>best[x['provider']]:
                x['eligible']=False
                x['issues']=list(x.get('issues') or [])+['Anderer Treffer passt genauer zum Erscheinungsjahr']
        good=[x for x in good if x['eligible']]
    # Multiple plausible IDs from the same provider or incompatible release years
    # mean 'review', not a silent arbitrary selection.
    provider_ids={}
    for x in good:provider_ids.setdefault(x['provider'],set()).add(x['reference_id'])
    ambiguous=any(len(ids)>1 for ids in provider_ids.values())
    years={x['year'] for x in good if x['year'] is not None}
    ambiguous=ambiguous or (max(years)-min(years)>1 if years else False)
    selected=good[0] if good and not ambiguous else None
    status=('review' if ambiguous or (entries and not good) else
            'candidate' if selected else 'partial' if paused else 'no_match')
    merged,sources=_merge(editorial or {},selected,episode_mode=meta['kind']=='series' and meta.get('episode') is not None)
    return {
        'status':status,'metadata':merged,'field_sources':sources,
        'references':[{k:v for k,v in cand.items() if k in (
            'provider','reference_id','title','kind','year','similarity','issues',
            'episode_verified','season','episode','rating','votes','eligible')}
            for cand in entries[:MAX_REFERENCES]],
        'provider_checks':checks[:25],
        'warnings':(['Mehrere widersprüchliche Referenzen; keine automatische Zuordnung.'] if ambiguous else [])+
            (['Einzelne Metadatenanbieter waren vorübergehend nicht verfügbar.'] if paused else []),
        # Genres of the unique reference (IMDb/TVDB …): the catalogue categories use them first.
        'reference_genres':list(selected['genres']) if selected else [],
        'identity_verified':False,
        'episode_verified':bool(selected and selected['episode_verified']),
        'download_authorized':False,
        'from_reference':bool(selected),
        'analysis':ANALYSIS,
    }


def _conn(root):
    db=netzkino_details._connect(root)
    db.executescript(SCHEMA)
    return db


def _load(root,item_id,now):
    db=_conn(root)
    try:
        row=netzkino_details._find(db,item_id)
        classification=netzkino.classify_media(row)
        return row,classification
    finally:db.close()


def _hash(row,editorial,meta):
    raw=json.dumps([row.get('title'),row.get('content_id'),editorial.get('original_title'),
        meta.get('title'),meta.get('kind'),meta.get('year'),meta.get('season'),meta.get('episode')],
        ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def cached(root,item_id,now=None):
    """Read a cached reference report without generating any provider requests."""
    if not netzkino_details.VALID_ID.fullmatch(str(item_id)):
        raise ValueError('Ungültige lokale Netzkino-Kennung')
    db=_conn(root)
    try:
        row=netzkino_details._find(db,item_id)
        found=db.execute('SELECT payload,checked,identity_hash FROM netzkino_reference_checks WHERE item_id=?',(item_id,)).fetchone()
        if not found:return {'status':'unchecked','metadata':{},'references':[], 'cached':False}
        try:r=json.loads(found['payload'])
        except (TypeError,ValueError):return {'status':'unchecked','metadata':{},'references':[], 'cached':False}
        if not isinstance(r,dict):return {'status':'unchecked','metadata':{},'references':[], 'cached':False}
        editorial=netzkino_details._fallback(row)
        original=db.execute('SELECT payload FROM netzkino_public_details WHERE item_id=?',(item_id,)).fetchone()
        if original:
            try:
                stored=json.loads(original['payload'])
                if isinstance(stored,dict):editorial.update(stored)
            except (TypeError,ValueError):pass
        meta=_identity(row,editorial,netzkino.classify_media(row))
        if _hash(row,editorial,meta)!=found['identity_hash']:
            return {'status':'unchecked','metadata':{},'references':[], 'cached':False}
        return {**r,'cached':True,'checked_at':found['checked']}
    finally:db.close()


def enrich(root,item_id,settings,*,lookup=None,fetch=None,now=None,force=False):
    """One explicitly requested, cached provider check per Netzkino title.

    No file, player, manifest, queue or MediathekView table is modified.
    ``lookup`` is an optional injectable ARD-compatible provider function.
    """
    if not netzkino_details.VALID_ID.fullmatch(str(item_id)):
        raise ValueError('Ungültige lokale Netzkino-Kennung')
    now=time.time() if now is None else float(now)
    row,classification=_load(root,item_id,now)
    info=netzkino_details.get(root,item_id,fetch=fetch,now=now)
    editorial=info['details']
    meta=_identity(row,editorial,classification)
    fingerprint=_hash(row,editorial,meta)
    db=_conn(root)
    try:
        found=db.execute('SELECT identity_hash,checked,payload FROM netzkino_reference_checks WHERE item_id=?',(item_id,)).fetchone()
        if found and not force and found['identity_hash']==fingerprint:
            try:prev=json.loads(found['payload'])
            except (TypeError,ValueError):prev={}
            if isinstance(prev,dict) and not stale_review(prev) and now-found['checked']<(RETRY_TTL if prev.get('status')=='partial' else GOOD_TTL):
                return {**prev,'cached':True,'checked_at':found['checked']}
    finally:db.close() # provider traffic never holds a SQLite connection
    if not meta['title']:
        raise ValueError('Netzkino-Titel fehlt')
    if lookup is None:
        import core
        lookup=core.candidates
    # 0.5.49: a work already checked for another platform is not asked again.
    import reference_share
    lookup=reference_share.wrap(root,lookup,'Netzkino',now=now,fresh=force)
    row_arg={'title':row['title'],'topic':meta['title'] if meta['kind']=='series' else '',
             'duration':row.get('duration') or editorial.get('duration_seconds'),
             'channel':'Netzkino'}
    input_meta={'kind':meta['kind'],'title':meta['title'],'year':meta['year'],
                'season':meta['season'],'episode':meta['episode'],
                'episode_title':meta['episode_title'],'genres':editorial.get('genres') or [],
                'description':editorial.get('description') or ''}
    results=[]
    # A single original-language fallback only if the primary title produced no
    # eligible candidate; never launch a whole-catalogue provider scan.
    try:
        first=lookup(row_arg,dict(input_meta),{**dict(settings),'_external_reference_validation':True})
        results.append(first)
        if not any(_candidate(c,meta) and _candidate(c,meta)['eligible']
                   for c in first.get('candidates',[])[:30]):
            alternate=_str(editorial.get('original_title'),220)
            if (alternate and meta['kind']=='movie' and
                netzkino._series_normalize(alternate)!=netzkino._series_normalize(meta['title'])):
                results.append(lookup(row_arg,{**input_meta,'title':alternate},{**dict(settings),'_external_reference_validation':True}))
    except Exception:
        # Never log API tokens, full provider exception, titles or URLs.
        results.append({'candidates':[],'warnings':['provider_unavailable'],
                        'provider_checks':[],'deferred_providers':['provider_unavailable']})
    report=analyze(meta,editorial,results)
    report['media_type']=classification['media_type']
    report['title']=meta['title']
    report['status_source']='local_optional_provider_check'
    report['checked_at']=now
    report['cached']=False
    db=_conn(root)
    try:
        with db:
            db.execute('''INSERT INTO netzkino_reference_checks(item_id,identity_hash,checked,payload)
               VALUES(?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
               identity_hash=excluded.identity_hash,checked=excluded.checked,payload=excluded.payload''',
               (item_id,fingerprint,now,json.dumps({k:v for k,v in report.items() if k!='cached'},ensure_ascii=False)))
    finally:db.close()
    return report


def all_cached(root):
    """{item_id: report} of all stored checks, one read for catalogue views (no identity check)."""
    path=Path(root)/'netzkino_links.sqlite3'
    if not path.is_file():return {}
    db=_conn(root)
    try:
        out={}
        for item_id,payload in db.execute('SELECT item_id,payload FROM netzkino_reference_checks'):
            try:report=json.loads(payload)
            except (TypeError,ValueError):continue
            if isinstance(report,dict):out[item_id]=report
        return out
    finally:db.close()


def metrics(root):
    """Read-only aggregate counts suitable for privacy-preserving diagnostics."""
    path=Path(root)/'netzkino_links.sqlite3'
    if not path.is_file():return {'checked':0,'by_status':{}}
    import sqlite3
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='netzkino_reference_checks'").fetchone()
        if not exists:return {'checked':0,'by_status':{}}
        counts={}
        for payload, in db.execute('SELECT payload FROM netzkino_reference_checks'):
            try:status=json.loads(payload).get('status')
            except (ValueError,AttributeError):status='invalid'
            if status not in ('review','candidate','no_match','partial'):status='invalid'
            counts[status]=counts.get(status,0)+1
        return {'checked':sum(counts.values()),'by_status':counts}
    finally:db.close()


# ------------------------------------------------------------------ 0.5.32
# Automatic background enrichment. Until 0.5.31.11 the provider check (IMDb
# offline, TVDB, TMDB, OMDb, Wikidata) only ran when a title was opened and
# "Referenzen prüfen" was clicked, so Netzkino titles stayed without metadata.
def pending(root, limit=10, now=None):
    """Titles that have never been checked, then stale/partial checks."""
    now=time.time() if now is None else float(now)
    db=_conn(root)
    try:
        rows=db.execute('''SELECT c.id, r.checked, r.payload FROM netzkino_catalog c
            LEFT JOIN netzkino_reference_checks r ON r.item_id=c.id
            WHERE r.item_id IS NULL OR r.checked < ? OR '''+STALE_REVIEW+'''
            ORDER BY (r.item_id IS NOT NULL), NOT IFNULL('''+STALE_REVIEW+''',0), c.updated DESC LIMIT ?''',
            (now-RETRY_TTL, max(1,int(limit))*4)).fetchall()
    finally:db.close()
    out=[]
    for item_id,checked,payload in rows:
        if checked is not None:
            try:status=json.loads(payload).get('status')
            except (TypeError,ValueError,AttributeError):status=None
            if status!='partial' and now-checked<GOOD_TTL and not stale_review(payload):continue
        out.append(item_id)
        if len(out)>=limit:break
    return out


def loop(root, settings, slots, stop, *, gap=6.0, idle=1800.0, enrich_one=None, pending_fn=None, name='netzkino'):
    """Low-priority worker: one title every `gap` seconds, never parallel to
    the user's own provider requests (shared `slots`), pauses when automatic
    metadata is switched off in the settings."""
    import diagnostics,task_control
    task='enrich:'+name
    enrich_one=enrich_one or enrich
    pending_fn=pending_fn or pending
    failed=set()
    while not stop.is_set():
        try:
            current=settings()
            if not current.get('auto_metadata',True):
                task_control.note(task,'Automatischer Abgleich ist in den Einstellungen ausgeschaltet')
                stop.wait(300);continue
            if not task_control.wait_if_paused(task,stop):return
            todo=[i for i in pending_fn(root,limit=20) if i not in failed]
            if not todo:
                task_control.note(task,'Alle Titel geprüft')
                # Short steps so that a pause or a new catalogue is noticed without waiting half an hour.
                waited=0.0
                while waited<idle and not stop.wait(30):
                    waited+=30
                    if task_control.paused(task) or pending_fn(root,limit=1):break
                failed.clear();continue
            done=0
            for item_id in todo:
                if stop.is_set():return
                if task_control.paused(task):break
                task_control.note(task,'Prüft Titel')
                try:
                    with slots:enrich_one(root,item_id,current)
                    done+=1
                except Exception as exc:  # one broken title must not stop the worker
                    failed.add(item_id)
                    diagnostics.error(name+'_auto_enrich_failed',exc)
                stop.wait(gap*task_control.factor(task))
            if done:diagnostics.event(name+'_auto_enrich_batch',checked=done)
        except Exception as exc:
            diagnostics.error(name+'_auto_enrich_loop',exc)
            stop.wait(300)
