"""Read-only supplemental diagnostics for Netzkino, video audit and external portals.

Deliberately does not initialize services or databases, perform network IO,
include catalogue titles/film URLs or expose user configuration/secrets.
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path

_SAFE_ERROR=re.compile(r'(?i)https?://\S+|(?:api.?key|token|authorization|cookie|password)\s*[:=]\s*\S+')


def _ro(path):
    p=Path(path)
    if not p.is_file():return None
    db=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=1.5)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=1500')
    return db


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _state(db,keys):
    if 'netzkino_state' not in _tables(db):return {}
    rows=db.execute('SELECT name,value FROM netzkino_state WHERE name IN ('+
        ','.join('?' for _ in keys)+')',tuple(keys)).fetchall()
    return {r[0]:r[1] for r in rows}


def _int(value):
    try:return int(float(value))
    except (ValueError,TypeError,OverflowError):return 0


def _float(value):
    try:return float(value)
    except (ValueError,TypeError,OverflowError):return 0.0


def netzkino(root):
    result={'available':False,'catalog_count':0,'manual_count':0,'offline':True}
    db=_ro(Path(root)/'netzkino_links.sqlite3')
    if db is None:return result
    try:
        with db:
            tables=_tables(db)
            if 'netzkino_catalog' not in tables:return result
            keys=('auto','last_success','last_attempt','next_attempt','last_error','new','changed',
                  'unchanged','last_entries','snapshot_seed_count','categories_checked',
                  'categories_total','category_errors','last_http_status',
                  'categories_empty','category_cap_hits','category_over_20','category_max_items','category_error_types','last_result','last_complete_success',
                  'time_budget_hit')
            values=_state(db,keys)
            result.update(available=True,offline=True,
                          catalog_count=int(db.execute('SELECT COUNT(*) FROM netzkino_catalog').fetchone()[0]),
                          manual_count=int(db.execute('SELECT COUNT(*) FROM netzkino_links').fetchone()[0]) if 'netzkino_links' in tables else 0,
                          auto=values.get('auto')=='1',
                          last_attempt=_float(values.get('last_attempt')),
                          last_success=_float(values.get('last_success')),
                          next_attempt=_float(values.get('next_attempt')),
                          last_entries=_int(values.get('last_entries')),
                          snapshot_seed_count=_int(values.get('snapshot_seed_count')),
                          new=_int(values.get('new')),changed=_int(values.get('changed')),
                          unchanged=_int(values.get('unchanged')),
                          categories_checked=_int(values.get('categories_checked')),
                          categories_total=_int(values.get('categories_total')),
                          category_errors=_int(values.get('category_errors')),
                          last_http_status=_int(values.get('last_http_status')),
                          categories_empty=_int(values.get('categories_empty')),
                          category_cap_hits=_int(values.get('category_cap_hits')),
                          category_over_20=_int(values.get('category_over_20')),
                          category_max_items=_int(values.get('category_max_items')),
                          coverage_status='startpage_only',
                          time_budget_hit=values.get('time_budget_hit')=='1',
                          last_complete_success=_float(values.get('last_complete_success')),
                          last_result=values.get('last_result','never') if values.get('last_result') in
                                      ('running','partial','complete','failed','never') else 'unknown')
            try:
                raw_types=json.loads(values.get('category_error_types') or '{}')
                result['category_error_types']={str(k)[:50]:_int(v) for k,v in raw_types.items()
                                                if re.fullmatch(r'[a-z_0-9]{1,50}',str(k))} if isinstance(raw_types,dict) else {}
            except (TypeError,ValueError):result['category_error_types']={}
            err=values.get('last_error','')
            # The error is diagnostic, never a source URL, JSON payload or token.
            result['last_error']=_SAFE_ERROR.sub('[REDACTED]',err)[:220]
            cols={r[1] for r in db.execute('PRAGMA table_info(netzkino_catalog)')}
            if 'source' in cols:
                result['by_source']={str(r[0]):int(r[1]) for r in db.execute('SELECT source,COUNT(*) FROM netzkino_catalog GROUP BY source')}
            if 'kind' in cols:
                result['by_kind']={str(r[0]):int(r[1]) for r in db.execute('SELECT kind,COUNT(*) FROM netzkino_catalog GROUP BY kind')}
            # Derived presentation classification, computed read-only from existing titles.
            # No raw film titles or media links are included in the exported ZIP.
            if 'kind' in cols and 'title' in cols:
                import netzkino as _nk
                movie_count=episode_count=0; group_keys=set()
                for raw_kind, raw_title in db.execute('SELECT kind,title FROM netzkino_catalog'):
                    media=_nk.classify_media({'kind':raw_kind,'title':raw_title})
                    if media['media_type']=='movie':movie_count+=1
                    else:
                        normalized=_nk._series_normalize(media['series_title'])
                        if normalized:group_keys.add(normalized)
                        if media['media_type']=='episode':episode_count+=1
                result['media_classification']={
                    'movies':movie_count,'series_groups':len(group_keys),
                    'episodes':episode_count,'evidence':'explicit_episode_patterns_and_contentSeries',
                    'source':'local_read_only_reclassification',
                    'database_modified':False}
            if 'access_hint' in cols:
                result['by_access']={str(r[0] or 'unknown')[:36]:int(r[1]) for r in db.execute('SELECT access_hint,COUNT(*) FROM netzkino_catalog GROUP BY access_hint')}
            quality={}
            for field in ('year','poster','genres','summary','fsk','content_id'):
                if field in cols:
                    quality[field]=int(db.execute('SELECT COUNT(*) FROM netzkino_catalog WHERE '+field+' IS NOT NULL AND TRIM(CAST('+field+' AS TEXT)) != \'\'').fetchone()[0])
            if 'netzkino_public_details' in tables:
                result['detail_cache_count']=int(db.execute('SELECT COUNT(*) FROM netzkino_public_details').fetchone()[0])
            else:result['detail_cache_count']=0
            if 'netzkino_detail_failures' in tables:
                result['detail_retries_deferred']=int(db.execute('SELECT COUNT(*) FROM netzkino_detail_failures').fetchone()[0])
            else:result['detail_retries_deferred']=0
            if 'netzkino_reference_checks' in tables:
                statuses={}
                for (payload,) in db.execute('SELECT payload FROM netzkino_reference_checks'):
                    try:state=json.loads(payload).get('status')
                    except (ValueError,TypeError,AttributeError):state='invalid'
                    if state not in ('candidate','review','no_match','partial'):state='invalid'
                    statuses[state]=statuses.get(state,0)+1
                result['external_references']={'checked':sum(statuses.values()),
                                                'by_status':statuses}
            else:result['external_references']={'checked':0,'by_status':{}}
            result['metadata_coverage']=quality
            return result
    except sqlite3.Error as exc:
        return {'available':False,'offline':True,'error_type':type(exc).__name__}
    finally:db.close()


def _catalog_state(db,keys):
    if 'catalog_state' not in _tables(db):return {}
    rows=db.execute('SELECT key,value FROM catalog_state WHERE key IN ('+
        ','.join('?' for _ in keys)+')',tuple(keys)).fetchall()
    out={}
    for key, value in rows:
        try:out[key]=json.loads(value)
        except (TypeError,ValueError):out[key]=None
    return out


def work_and_portals(root):
    db=_ro(Path(root)/'catalog.db')
    if db is None:return {'video_audit':{'available':False},'portals':{'available':False}}
    try:
        tables=_tables(db)
        video={'available':'video_role_audit' in tables}
        if video['available']:
            keys=['video_role_audit_cursor_v05311','video_role_audit_total_v05311',
                  'video_role_audit_checked_v05311','video_role_audit_skipped_v05311',
                  'video_role_audit_flagged_v05311','video_role_audit_manual_v05311',
                  'video_role_audit_last_v05311']
            s=_catalog_state(db,keys)
            for key,field in [('cursor','cursor'),('total','total_at_start'),('checked','checked'),
                              ('skipped','skipped'),('flagged','flagged'),('manual','manual_flags'),('last','last_updated')]:
                v=s.get('video_role_audit_'+key+'_v05311')
                video[field]=v if key in ('cursor','last') else _int(v)
            video['processed']=video['checked']+video['skipped']
            video['findings_count']=int(db.execute('SELECT COUNT(*) FROM video_role_audit').fetchone()[0])
            video['by_role']={str(r[0]):int(r[1]) for r in db.execute('SELECT video_role,COUNT(*) FROM video_role_audit GROUP BY video_role')}
        portals={'available':'portal_items' in tables,
                 'archive_companion_mode':'external_read_only',
                 'archive_companion_network_check':'not_performed_during_diagnostics'}
        if 'portal_items' in tables:
            portals['by_source']={str(r[0]):int(r[1]) for r in db.execute('SELECT source,COUNT(*) FROM portal_items GROUP BY source')}
        if 'portal_scopes' in tables:
            portals['scan_scopes']={str(r[0]):int(r[1]) for r in db.execute('SELECT state,COUNT(*) FROM portal_scopes GROUP BY state')}
        return {'video_audit':video,'portals':portals}
    except sqlite3.Error as exc:
        return {'video_audit':{'available':False,'error_type':type(exc).__name__},
                'portals':{'available':False,'error_type':type(exc).__name__}}
    finally:db.close()


def collect(root):
    if root is None:return {'netzkino':{'available':False,'offline':True},
                            'video_audit':{'available':False},'portals':{'available':False}}
    p=Path(root)
    return {'netzkino':netzkino(p),**work_and_portals(p)}
