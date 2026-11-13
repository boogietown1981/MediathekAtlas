"""Resumable, local, revisioned video-role audit for existing MediathekAtlas works.

Never changes work identity, manual decisions, download records or retry timestamps.
Only adds evidence to already automatically classified works. No network/ffprobe.
"""
from __future__ import annotations
import json
import time
import catalog
import video_causality

REVISION='v05311'
CURSOR='video_role_audit_cursor_'+REVISION
TOTAL='video_role_audit_total_'+REVISION
AUDITED='video_role_audit_checked_'+REVISION
SKIPPED='video_role_audit_skipped_'+REVISION
FLAGGED='video_role_audit_flagged_'+REVISION
MANUAL='video_role_audit_manual_'+REVISION
LAST='video_role_audit_last_'+REVISION

DDL='''CREATE TABLE IF NOT EXISTS video_role_audit (
 work_id TEXT PRIMARY KEY, previous_state TEXT NOT NULL,
 video_role TEXT NOT NULL, reason TEXT NOT NULL, evidence TEXT,
 actual_seconds REAL, expected_seconds REAL, checked REAL NOT NULL);
CREATE INDEX IF NOT EXISTS video_role_audit_checked ON video_role_audit(checked DESC);
'''

def initialize(c):
    c.executescript(DDL)
    if catalog.get_state(c,TOTAL,None) is None:
        catalog.set_state(c,TOTAL,c.execute('SELECT COUNT(*) FROM works').fetchone()[0])
        catalog.set_state(c,AUDITED,0)
        catalog.set_state(c,SKIPPED,0)
        catalog.set_state(c,FLAGGED,0)
        catalog.set_state(c,MANUAL,0)
        catalog.set_state(c,LAST,time.time())


def _best_source(c,work_id):
    row=c.execute('''SELECT payload FROM offers WHERE work_id=? AND active=1
        ORDER BY rank DESC, seen DESC LIMIT 1''',(work_id,)).fetchone()
    try:return json.loads(row[0]) if row else None
    except (TypeError,ValueError):return None


def _candidate(c,row,m,source):
    # Prefer provider episode/runtime evidence. A robust series median is a
    # weaker signal usable *only* to request review, never to auto-confirm.
    if video_causality.expected_seconds(m):return m
    if row['kind']!='series' or not row['show_key']:return m
    try:duration=float(source.get('duration') or 0)
    except (TypeError,ValueError):return m
    # Avoid costly history sampling for every regular-length episode.
    if duration<=0 or 600<duration<3600:return m
    typical=video_causality.sample_series_runtime(c,row['show_key'],row['id'])
    if not typical:return m
    return {**m,'reference_runtime_seconds':typical,
            'reference_runtime_source':'Serien-Katalogmedian (mind. 5 Vergleichsangebote)'}


def audit_batch(c,limit=200):
    """Process one bounded batch; return number of considered works.

    Caller wraps this in its regular SQLite transaction. The progress marker is
    stored with mutations so a crash cannot skip unfinished work.
    """
    cursor=catalog.get_state(c,CURSOR,0)
    if cursor=='complete':return 0
    limit=max(1,min(500,int(limit)))
    rows=c.execute('SELECT rowid AS rid,id,kind,state,meta,show_key FROM works WHERE rowid>? ORDER BY rowid LIMIT ?',
                   (int(cursor),limit)).fetchall()
    if not rows:
        catalog.set_state(c,CURSOR,'complete')
        catalog.set_state(c,LAST,time.time())
        return 0
    checked=skipped=flagged=manual=0
    for row in rows:
        cursor=row['rid']
        if row['state'] not in ('manual','matched','identified','format') or row['kind'] not in ('series','movie'):
            skipped+=1;continue
        source=_best_source(c,row['id'])
        if not source:
            skipped+=1;continue
        try:m=json.loads(row['meta'] or '{}')
        except (TypeError,ValueError):
            skipped+=1;continue
        if not isinstance(m,dict):
            skipped+=1;continue
        checked+=1
        result=video_causality.evaluate(source,_candidate(c,row,m,source))
        if not result:continue
        flagged+=1
        if row['state']=='manual':manual+=1
        c.execute('''INSERT INTO video_role_audit
            (work_id,previous_state,video_role,reason,evidence,actual_seconds,expected_seconds,checked)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(work_id) DO UPDATE SET
            previous_state=excluded.previous_state,video_role=excluded.video_role,
            reason=excluded.reason,evidence=excluded.evidence,
            actual_seconds=excluded.actual_seconds,expected_seconds=excluded.expected_seconds,
            checked=excluded.checked''',
            (row['id'],row['state'],result['video_role'],result.get('video_role_reason',''),
             result.get('video_role_evidence',''),result.get('source_duration_seconds'),
             result.get('expected_runtime_seconds'),time.time()))
        # Keep human-reviewed records *byte-for-byte unchanged*. Automatic
        # matched records keep their state and verified episode identity; the
        # review flag is descriptive, not an automatic downgrade.
        if row['state']=='manual':continue
        changed=False
        for field in ('video_role','video_role_reason','video_role_evidence',
                      'source_duration_seconds','source_runtime_source',
                      'expected_runtime_seconds','expected_runtime_source'):
            if result.get(field) is not None and m.get(field)!=result[field]:
                m[field]=result[field];changed=True
        if not m.get('video_role_needs_review'):
            m['video_role_needs_review']=True;changed=True
        if row['state']=='identified' and m.get('episode_verified'):
            # Identified is provisional. Do not imply this is a complete episode.
            m['episode_verified']=False;changed=True
        if changed:
            c.execute('UPDATE works SET meta=?,updated=? WHERE id=? AND meta=?',
                      (json.dumps(m,ensure_ascii=False),time.time(),row['id'],row['meta']))
    catalog.set_state(c,CURSOR,cursor)
    for key,delta in ((AUDITED,checked),(SKIPPED,skipped),(FLAGGED,flagged),(MANUAL,manual)):
        if delta:catalog.set_state(c,key,int(catalog.get_state(c,key,0))+delta)
    catalog.set_state(c,LAST,time.time())
    return len(rows)


def status(c,offset=0,limit=20):
    cursor=catalog.get_state(c,CURSOR,0)
    offset=max(0,min(int(offset),1000000))
    limit=max(1,min(int(limit),50))
    findings=c.execute('''SELECT a.work_id,a.previous_state,a.video_role,a.reason,
        a.actual_seconds,a.expected_seconds,a.checked,w.title,w.kind,w.state
        FROM video_role_audit a LEFT JOIN works w ON w.id=a.work_id
        ORDER BY a.checked DESC LIMIT ? OFFSET ?''',(limit,offset)).fetchall()
    return {'phase':'complete' if cursor=='complete' else 'running',
            'cursor':cursor,'total_at_start':catalog.get_state(c,TOTAL,0),
            'processed':int(catalog.get_state(c,AUDITED,0))+int(catalog.get_state(c,SKIPPED,0)),
            'checked':catalog.get_state(c,AUDITED,0),
            'skipped':catalog.get_state(c,SKIPPED,0),
            'flagged':catalog.get_state(c,FLAGGED,0),
            'manual_flags':catalog.get_state(c,MANUAL,0),
            'last_updated':catalog.get_state(c,LAST,0),
            'findings':[dict(row) for row in findings],
            'finding_count':c.execute('SELECT COUNT(*) FROM video_role_audit').fetchone()[0]}
