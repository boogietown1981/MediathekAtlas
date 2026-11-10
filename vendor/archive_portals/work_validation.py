"""Conservative work/episode evidence report. No title-only video confirmation.

Evidence is descriptive: metadata matching, duration plausibility and explicit
file-level episode tokens are *not* proof of the real audiovisual content.
"""
from __future__ import annotations
import json
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_validation_reports (
 group_id TEXT PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
 stage TEXT NOT NULL DEFAULT 'unresolved', reason TEXT,
 reference_sources TEXT NOT NULL DEFAULT '[]',
 strong_files INTEGER NOT NULL DEFAULT 0,
 episodes INTEGER NOT NULL DEFAULT 0,
 conflicts TEXT NOT NULL DEFAULT '[]',
 checked TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_work_validation_stage ON work_validation_reports(stage);
"""

# A derivative is an alternate encoding of a source, not independent content proof.
NON_CONTENT={'bdmv_stream','transport_segment','extra_or_clip','short_unknown',
             'archive_derivative','trailer','bonus','clip'}
EXTRAS=re.compile(r'(?i)(?:^|[\s._\-\[\(])(?:trailer|teaser|preview|sample|bonus|clip)(?:$|[\s._\-\]\)])')
EPISODE=re.compile(r'(?i)(?:^|[^a-z0-9])(?:s\d{1,2}[-._ ]*e\d{1,3}|\d{1,2}x\d{1,3}|season[-._ ]*\d{1,2}[-._ ]*episode[-._ ]*\d{1,3}|(?:ep|episode|folge)[-._ ]*\d{1,3})(?:$|[^0-9])')


def _seconds(value):
    try:
        seconds=float(value)
        return seconds if 0<seconds<172800 else None
    except (TypeError,ValueError,OverflowError):return None


def _year(value):
    try:return int(value) if value else None
    except (TypeError,ValueError,OverflowError):return None


def _source_group(provider):
    # Wikipedia results often restate Wikidata, so they are not two independent authorities.
    if provider in ('Wikidata','Wikipedia'):return 'Wikimedia'
    return str(provider or '').strip()


def assessment(group,variants,references=()):
    """Pure, bounded independent-evidence assessment for one work.

    Never change group/variant identities, downloaded content or user decisions.
    `content_supported` means metadata/structure/runtime align, NOT verified video.
    """
    g=dict(group)
    kind=g.get('kind')
    known_ref=bool(g.get('reference_id'))
    provider=g.get('match_provider') or (str(g.get('reference') or '').split(':')[0])
    sources=set([_source_group(provider)]) if known_ref and provider else set()
    conflicts=[]
    expected=_seconds(g.get('expected_runtime'))
    strong_external=[]
    for ref in references:
        row=dict(ref)
        if row.get('confidence')!='high':continue
        src=_source_group(row.get('provider'))
        if row.get('candidate_kind') and row.get('candidate_kind')!=kind:
            conflicts.append('Widersprüchlicher Werktyp: '+src)
            continue
        y1,y2=_year(g.get('year')),_year(row.get('candidate_year'))
        if y1 and y2 and abs(y1-y2)>1:
            conflicts.append('Widersprüchliches Erscheinungsjahr: '+src)
            continue
        sources.add(src)
        strong_external.append(row)
        # OMDb returns a specific title runtime; use only if no prior provider duration.
        if expected is None and row.get('provider')=='OMDb':
            payload=row.get('payload')
            if isinstance(payload,str):
                try:payload=json.loads(payload)
                except (ValueError,TypeError):payload={}
            if not isinstance(payload,dict):payload={}
            mins=_seconds(payload.get('runtime_minutes'))
            if mins and 15<=mins<=300:expected=mins*60
    # Two independent high-confidence references with incompatible years are a conflict.
    dated=[(_source_group(r.get('provider')),_year(r.get('candidate_year'))) for r in strong_external]
    for i,(s1,y1) in enumerate(dated):
        if not y1:continue
        if any(s2!=s1 and y2 and abs(y1-y2)>1 for s2,y2 in dated[i+1:]):
            conflicts.append('Externe Anbieter nennen verschiedene Erscheinungsjahre')
            break
    eligible=[];episodes=set()
    for variant in variants:
        v=dict(variant)
        filename=str(v.get('filename') or '')
        if (v.get('technical_role') or '') in NON_CONTENT or EXTRAS.search(filename):continue
        if str(v.get('validation') or '') in ('clip','too_short','too_long'):continue
        seconds=_seconds(v.get('duration'))
        variant_expected=_seconds(v.get('expected_runtime')) or expected
        if not seconds or not variant_expected:continue
        tol=max(120,variant_expected*.05)
        if abs(seconds-variant_expected)>tol:continue
        if kind=='series':
            if v.get('season') is None or v.get('episode') is None:continue
            # An Archive.org parent title or bare segment number isn't episode evidence.
            if not EPISODE.search(filename) and v.get('identity_origin')!='manual':continue
            if provider=='TVmaze' and v.get('duration_reference')!='TVmaze: episode':continue
            episodes.add((v.get('season'),v.get('episode')))
        elif kind!='movie':continue
        eligible.append(v)
    if conflicts:stage='conflicted';reason='Widersprüchliche Referenzdaten: manuelle Prüfung nötig'
    elif not sources:stage='unresolved';reason='Keine ausreichend verlässliche Werkreferenz'
    elif eligible:
        stage='content_supported'
        reason='Werkreferenz, Dateistruktur und Laufzeit plausibel; Videoinhalt nicht unabhängig verifiziert'
    elif known_ref or strong_external:
        stage='work_matched'
        reason='Werk identifiziert; keine passende vollständige Datei/Folge nachgewiesen'
    else:stage='candidate';reason='Werkhinweis vorhanden, weitere Prüfung erforderlich'
    if g.get('match_provider')=='manuell' and g.get('match_state')=='confirmed':
        stage='manual';reason='Vom Benutzer bestätigte Zuordnung; wird automatisch nicht überschrieben'
    return dict(stage=stage,reason=reason,reference_sources=sorted(s for s in sources if s),
                strong_files=len(eligible),episodes=len(episodes),conflicts=list(dict.fromkeys(conflicts)))


def refresh(c,group_id):
    row=c.execute('SELECT * FROM groups WHERE id=?',(group_id,)).fetchone()
    if not row:return None
    variants=c.execute("""SELECT filename,duration,expected_runtime,duration_reference,technical_role,validation,
          season,episode,identity_origin FROM variants WHERE group_id=?""",(group_id,)).fetchall()
    references=c.execute("""SELECT provider,confidence,candidate_kind,candidate_year,payload
          FROM external_evidence WHERE group_id=?""",(group_id,)).fetchall()
    # Respect per-episode runtime: group average is used only as a fallback.
    g=dict(row)
    if not g.get('expected_runtime') and g.get('kind')=='series':
        pass
    res=assessment(g,variants,references)
    c.execute("""INSERT INTO work_validation_reports
      (group_id,stage,reason,reference_sources,strong_files,episodes,conflicts,checked)
      VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
      ON CONFLICT(group_id) DO UPDATE SET stage=excluded.stage,reason=excluded.reason,
      reference_sources=excluded.reference_sources,strong_files=excluded.strong_files,
      episodes=excluded.episodes,conflicts=excluded.conflicts,checked=CURRENT_TIMESTAMP""",
      (group_id,res['stage'],res['reason'],json.dumps(res['reference_sources']),
       res['strong_files'],res['episodes'],json.dumps(res['conflicts'],ensure_ascii=False)))
    return res


def report(c,group_id):
    row=c.execute('SELECT * FROM work_validation_reports WHERE group_id=?',(group_id,)).fetchone()
    if not row:return refresh(c,group_id)
    r=dict(row)
    for field,default in (('reference_sources',[]),('conflicts',[])):
        try:r[field]=json.loads(r[field])
        except (ValueError,TypeError):r[field]=default
    return r


def backfill(c,limit=60):
    """Incremental rowid checkpoint; safe after crash, no full DB rewrite."""
    last=c.execute("SELECT value FROM catalog_meta WHERE key='work_validation_cursor_v1020'").fetchone()
    cursor=int(last[0]) if last else 0
    rows=c.execute('SELECT rowid,id FROM groups WHERE rowid>? ORDER BY rowid LIMIT ?',
                   (cursor,max(1,min(250,int(limit))))).fetchall()
    for row in rows:refresh(c,row['id'])
    if rows:
        c.execute("INSERT INTO catalog_meta(key,value) VALUES('work_validation_cursor_v1020',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(rows[-1]['rowid']),))
    return len(rows)
