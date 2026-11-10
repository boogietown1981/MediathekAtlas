"""Stable reference order: local IMDb > TheTVDB > TMDB > OMDb.

Fanart.tv is ancillary ID/artwork evidence, not a fifth identity authority.
Errors and missing credentials cannot silently skip earlier sources in favour
of weaker automatic confirmations. This module performs no DB writes.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

PRIORITY=('IMDb Offline','TheTVDB','TMDB','OMDb')


def best_strong(candidates):
    strong=[row for row in (candidates or []) if row and row.get('confidence')=='high']
    ids={str(row.get('imdb_id') or row.get('candidate_id') or '') for row in strong}
    return strong[0] if len(strong)==1 or len(ids)==1 and strong else None


def validate(*, offline, tvdb, tmdb, omdb, fanart=None, need_additional=False):
    """Providers are zero-argument callables. Record each attempt and its outcome.

    Once a strong identity is found, later sources are skipped unless an
    explicit supplementary request needs more data. Fanart begins in an
    independent worker as soon as a reliable ID is available.
    """
    matches=[];trail=[];errors=[];best=None
    providers=[('IMDb Offline',offline),('TheTVDB',tvdb),('TMDB',tmdb),('OMDb',omdb)]
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='fanart-artwork') as pool:
        art=None
        for label,provider in providers:
            if best is not None and not need_additional:
                trail.append({'provider':label,'state':'skipped_sufficient'})
                continue
            if provider is None:
                trail.append({'provider':label,'state':'not_configured'})
                continue
            try:
                result=provider()
                candidates=result if isinstance(result,list) else [result] if result else []
                candidates=[dict(m) for m in candidates if isinstance(m,dict)]
                matches.extend(candidates)
                trail.append({'provider':label,'state':'matched' if candidates else 'no_match'})
                strong=best_strong(candidates)
                if strong:
                    if best and str(best.get('imdb_id') or best.get('candidate_id')) != str(strong.get('imdb_id') or strong.get('candidate_id')):
                        trail[-1]['state']='conflict';errors.append(label+': Abweichende Werkkennung')
                    elif not best:best=strong
                if art is None and best and fanart is not None:
                    art=pool.submit(fanart,best)
            except Exception as ex:
                # Safe for log/diagnostics: provider name and exception class only.
                errors.append(label+': '+type(ex).__name__)
                trail.append({'provider':label,'state':'error','kind':type(ex).__name__})
        if art is not None:
            try:
                artwork=art.result(timeout=15)
                if artwork:matches.append(artwork);trail.append({'provider':'Fanart.tv','state':'matched'})
                else:trail.append({'provider':'Fanart.tv','state':'no_match'})
            except Exception as ex:
                errors.append('Fanart.tv: '+type(ex).__name__)
                trail.append({'provider':'Fanart.tv','state':'error','kind':type(ex).__name__})
        else:trail.append({'provider':'Fanart.tv','state':'skipped_no_verified_id_or_key'})
    return {'candidates':matches,'primary':best,'trail':trail,'errors':errors}
