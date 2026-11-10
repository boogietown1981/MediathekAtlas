"""Conservative media causality checks: series identity is not full-episode proof.

Only an explicit trailer/clip marker proves the extra's *format*. A very short
video relative to independently sourced episode/series runtime is a conflict
that requires review, not a claim that the content was visually inspected.
Mirrors ArchiveMedia's video_triage/work_validation principles. No network I/O.
"""
import re
from statistics import median

# Require explicit editorial separators so proper names like "Trailer Park Boys"
# and unrelated mentions of trailers in a synopsis remain untouched.
_SUFFIX=re.compile(
    r'(?i)(?:\s*(?:[-–—|:]\s+|[([]\s*))'
    r'(?:offiziell(?:er|es)?\s+|official\s+)?'
    r'(trailer|teaser|vorschau|preview|clip|ausschnitt|'
    r'opening|ending|intro|outro|promo|making[ -]?of|bonus(?:material)?|'
    r'highlights?|best[ -]?of|shorts?|kurzclip)'
    r'\b(?:\s*\d+|\s*[:\-–—]\s*[^)]{0,90})?\s*[)\]]?\s*$',re.I)
_PREFIX=re.compile(
    r'(?i)^\s*(trailer|teaser|vorschau|preview|clip|ausschnitt|'
    r'opening|ending|intro|outro|promo|making[ -]?of|bonus(?:material)?|kurzclip)'
    r'\s*(?:(?:[:\-–—|]\s*)|(?:zu|zum|zur|für|for)\s+|(?:\d+\s*$)|$)')
_NAMES={'trailer':'trailer','teaser':'trailer','vorschau':'trailer','preview':'trailer',
        'promo':'trailer','clip':'clip','ausschnitt':'clip','kurzclip':'clip',
        'opening':'extra','ending':'extra','intro':'extra','outro':'extra',
        'making of':'extra','making-of':'extra','bonus':'extra','bonusmaterial':'extra',
        'highlight':'clip','highlights':'clip','best of':'extra','best-of':'extra',
        'short':'clip','shorts':'clip'}


def seconds(value):
    try:
        n=float(value)
        if 0<n<172800:return n
    except (TypeError,ValueError,OverflowError):pass
    return None


def explicit_format(source):
    """Identify explicitly labelled extras; do not infer solely from length."""
    name=str((source or {}).get('title') or '').strip()[:300]
    match=_PREFIX.search(name) or _SUFFIX.search(name)
    if not match:return None
    token=match.group(1).lower()
    kind=_NAMES.get(token,'clip')
    return {'video_role':kind,'video_role_reason':'Videotitel kennzeichnet '+token+' ausdrücklich',
            'video_role_evidence':'explicit_title'}


def expected_seconds(candidate):
    """Prefer episode-specific, then independent show's reference duration."""
    for field in ('episode_runtime_seconds','reference_runtime_seconds'):
        v=seconds((candidate or {}).get(field))
        if v:return v
    return None


def evaluate(source,candidate=None):
    """Describe source-role plausibility against a provider runtime if available.

    Important: a 2–4 minute real anime episode is not demoted just because it is
    short. Expected runtime must come from an independent source, and the
    mismatch must be very large.
    """
    explicit=explicit_format(source)
    actual=seconds((source or {}).get('duration'))
    expected=expected_seconds(candidate)
    # Trace the evidence back to the origin; a catalogue-derived median must
    # remain visibly different from a provider's episode-specific runtime.
    candidate=candidate or {}
    if seconds(candidate.get('episode_runtime_seconds')):
        origin=candidate.get('episode_runtime_source') or (
            str(candidate.get('provider') or 'Metadatenanbieter')+' · Episodenlaufzeit')
    else:
        origin=candidate.get('reference_runtime_source') or (
            str(candidate.get('provider') or 'Metadatenanbieter')+' · Serienlaufzeit')
    runtime_evidence={'source_duration_seconds':actual,
                      'source_runtime_source':'Sender-Katalogimport',
                      'expected_runtime_seconds':expected,
                      'expected_runtime_source':origin if expected else None}
    if explicit:
        return {**explicit,**runtime_evidence}
    if expected and expected>=600 and actual:
        if actual<=min(600,expected*.4) and actual<expected*.45:
            return {'video_role':'short_excerpt_suspected',
                    'video_role_reason':'Laufzeit unplausibel: %.0f s statt etwa %.0f s'%(actual,expected),
                    'video_role_evidence':'independent_runtime',**runtime_evidence}
        if actual>expected*1.85 and actual-expected>=900:
            return {'video_role':'compilation_suspected',
                    'video_role_reason':'Laufzeit wesentlich länger als eine reguläre Folge',
                    'video_role_evidence':'independent_runtime',**runtime_evidence}
    return None


def annotate(source,candidate):
    """Annotate a candidate before any auto-match/early provider exit."""
    if not isinstance(candidate,dict):return candidate
    result=evaluate(source,candidate)
    if result and candidate.get('kind') in ('series','movie'):
        candidate.update(result)
        candidate['runtime_mismatch']=True
        candidate['episode_verified']=False
        candidate['video_role_needs_review']=True
    return candidate


def sample_series_runtime(c,show_key,exclude_work='',limit=48):
    """Bounded, indexed sample of other active series offers.

    A show median is weaker than a reference episode runtime: it can flag
    a discrepancy for review but never confirm a full episode automatically.
    """
    if not show_key:return None
    rows=c.execute("""SELECT CAST(json_extract(o.payload,'$.duration') AS INTEGER) d
        FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1
        WHERE w.show_key=? AND w.id!=? AND w.kind='series'
          AND w.state IN ('identified','matched','manual')
        LIMIT ?""",(show_key,exclude_work,min(max(6,int(limit)),64))).fetchall()
    values=[float(r[0]) for r in rows if r[0] and 600<=r[0]<=7200]
    if len(values)<5:return None
    typical=median(values)
    return typical if sum(abs(v-typical)<=typical*.4 for v in values)>=5 else None
