"""Shared factual evidence contract; source-specific matching, not one giant pool.

A strong work identity is distinct from an episode and from the content of a
downloaded video. ArchiveMedia's canonical assessment is used for Archive.org.
Netzkino's link metadata never supplies independent content verification.
MediathekView broadcaster evidence is treated as a different source domain.
"""
from vendor.archive_portals import reference_pipeline,work_validation

PRIORITY=reference_pipeline.PRIORITY
PROVENANCE={
    "mediathekview":{"canonical":"MediathekAtlas","supports_episode_feed":True,
                     "supports_technical_tracks":True,"rights":"source_specific"},
    "internet_archive":{"canonical":"ArchiveMedia","supports_episode_feed":False,
                        "supports_technical_tracks":True,"rights":"per_item"},
    "netzkino":{"canonical":"Originalseite","supports_episode_feed":False,
               "supports_technical_tracks":False,"rights":"view_only"},
}
KNOWN={'IMDb Offline','TheTVDB','TVDB','TMDB','OMDb','Wikidata','Wikipedia',
       'AniList','TVmaze','ARD','ZDF','Netzkino'}
INDEPENDENCE={'Wikipedia':'Wikimedia','Wikidata':'Wikimedia',
              'TheTVDB':'TVDB','TVDB':'TVDB',
              'IMDb Offline':'IMDb','OMDb':'OMDb',
              'TMDB':'TMDB','TVmaze':'TVmaze',
              'AniList':'AniList','ARD':'ARD','ZDF':'ZDF'}


def _identifier(row):
    return str(row.get('imdb_id') or row.get('reference_id')
               or row.get('candidate_id') or '').strip()


def assess_references(references,kind,year=None):
    """Conservative independent-authority summary; evidence remains inspectable.

    Conflicting strong source IDs or years block automatic confirmation.
    Different provider-specific IDs do not on their own prove different works.
    """
    references=[dict(r) for r in (references or []) if isinstance(r,dict)]
    strong=[]
    for r in references:
        if r.get('confidence')!='high':continue
        provider=r.get('provider')
        if provider not in KNOWN:continue
        if r.get('candidate_kind') and r['candidate_kind']!=kind:continue
        group=INDEPENDENCE.get(provider,provider)
        strong.append((group,r))
    conflicts=[]
    years={}
    imdb_ids=set()
    groups=set()
    for group,row in strong:
        groups.add(group)
        yr=row.get('candidate_year')
        try:yr=int(yr) if yr else None
        except (ValueError,TypeError):yr=None
        if yr and year and abs(yr-int(year))>1:
            conflicts.append("Erscheinungsjahr unterscheidet sich von Referenz: "+group)
        if yr:years.setdefault(group,set()).add(yr)
        iid=row.get('imdb_id')
        if isinstance(iid,str) and iid.startswith('tt'):imdb_ids.add(iid)
    for group,ys in years.items():
        if len(ys)>1:conflicts.append("Interne Jahresabweichung bei "+group)
    flat=[y for ys in years.values() for y in ys]
    if flat and max(flat)-min(flat)>1:
        conflicts.append("Unabhängige Anbieter nennen unterschiedliche Erscheinungsjahre")
    if len(imdb_ids)>1:
        conflicts.append("Widersprüchliche IMDb-Werkkennungen")
    return {"independent_sources":sorted(groups),
            "strong_references":len(strong),
            "conflicts":list(dict.fromkeys(conflicts)),
            "identity_supported":bool(strong) and not conflicts,
            "verified_video":False}


def assess_archive(upload,external_references=()):
    """Apply ArchiveMedia's canonical content assessment on read-only metadata.

    The result is a *hypothesis*. Container probes can verify encoded tracks,
    but cannot prove the audiovisual work or actual spoken language.
    """
    variants=[]
    for v in upload.get('video_variants',[]):
        variants.append({
            'filename':v.get('filename'),
            'technical_role':v.get('technical_role'),
            'duration':v.get('duration_seconds'),
            'expected_runtime':v.get('expected_runtime_seconds'),
            'validation':v.get('runtime_validation') or 'unknown',
            'season':v.get('season'),'episode':v.get('episode'),
            'identity_origin':v.get('identity_origin'),
        })
    references=list(external_references or [])
    ref_assessment=assess_references(references,upload.get('kind') or 'movie',upload.get('year'))
    group={
        'kind':upload.get('kind') or 'movie',
        'title':upload.get('normalized_title') or upload.get('title'),
        'year':upload.get('year'),
        'reference_id':upload.get('reference_id'),
        'reference':upload.get('reference'),
        'match_provider':upload.get('match_provider'),
        'expected_runtime':upload.get('expected_runtime_seconds'),
        'match_state':upload.get('match_state')
    }
    validation=work_validation.assessment(group,variants,references)
    if ref_assessment['conflicts'] and validation['stage'] not in ('conflicted','manual'):
        validation.update(stage='conflicted',
                          reason='Konflikt in unabhängigen externen Referenzen',
                          conflicts=list(dict.fromkeys(validation['conflicts']+
                                 ref_assessment['conflicts'])))
    return {**validation,
            "independent_references":ref_assessment,
            "technical_track_evidence":"separate_probe_only",
            "video_content_verified":False}


def filename_rules():
    """Stable policy: all platforms use the existing ArchiveMedia canonical target."""
    return {"engine":"vendor.archivemedia.package_media.canonical_target",
            "movie":"Filme",
            "series":"Serien",
            "uses_technical_audio_proof":True,
            "guesses_used_as_verified_languages":False}


def source_policy(source):
    if source not in PROVENANCE:raise ValueError("Unbekannte Plattform")
    return dict(PROVENANCE[source])
