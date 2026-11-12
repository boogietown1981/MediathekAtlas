"""Opt-in, restart-safe auto-download subscriptions for lawfully offered direct media.

Subscriptions never infer episode numbers, bypass DRM, or download uncertain
metadata. All enqueues are atomic and deduplicated by the confirmed media identity.
"""
import datetime
import json
import os
import secrets
import time
from pathlib import Path

import catalog
import core

class AmbiguousTitle(ValueError):
    """A subscription must not pick between two different confirmed productions."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions(
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,show_key TEXT,
 year INTEGER,mode TEXT NOT NULL,weekday INTEGER,hour INTEGER,
 include_existing INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,
 created REAL NOT NULL,next_check REAL NOT NULL,last_check REAL NOT NULL DEFAULT 0,
 queued_count INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS subscriptions_due ON subscriptions(enabled,next_check);
CREATE TABLE IF NOT EXISTS subscription_seen(
 subscription_id TEXT NOT NULL,work_id TEXT NOT NULL,
 PRIMARY KEY(subscription_id,work_id)
);
CREATE TABLE IF NOT EXISTS subscription_jobs(
 subscription_id TEXT NOT NULL,media_key TEXT NOT NULL,job_id TEXT NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(subscription_id,media_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS subscription_jobs_job ON subscription_jobs(job_id);
"""

def initialize(c):
    c.executescript(SCHEMA)

def next_weekly(now, weekday, hour):
    """Next user-local weekday/hour, strictly in the future."""
    dt=datetime.datetime.fromtimestamp(now)
    shift=(weekday-dt.weekday())%7
    due=(dt+datetime.timedelta(days=shift)).replace(hour=hour,minute=0,second=0,microsecond=0)
    if due.timestamp()<=now:due+=datetime.timedelta(days=7)
    return due.timestamp()

def weekly_followup(now,weekday,hour):
    """Keep checking within 48 hours of the scheduled weekly start.

    A release published shortly after a weekly slot must not be missed until
    the next week. The remembered media identity still prevents duplicates.
    """
    dt=datetime.datetime.fromtimestamp(now)
    days=(dt.weekday()-weekday)%7
    anchor=(dt-datetime.timedelta(days=days)).replace(
        hour=hour,minute=0,second=0,microsecond=0)
    if anchor.timestamp()>now:anchor-=datetime.timedelta(days=7)
    if 0<=now-anchor.timestamp()<48*3600:
        return now+15*60
    return next_weekly(now,weekday,hour)

def get_all(c):
    return [dict(r) for r in c.execute(
        "SELECT * FROM subscriptions ORDER BY enabled DESC,created DESC LIMIT 100").fetchall()]

def add(c,data,now=None):
    now=time.time() if now is None else now
    if not data.get('confirmed'):raise ValueError('Automatisches Herunterladen zuerst ausdrücklich bestätigen')
    title=' '.join(str(data.get('title') or '').split())
    if not 2<=len(title)<=140:raise ValueError('Titel muss zwischen 2 und 140 Zeichen haben')
    kind=str(data.get('kind') or '')
    if kind not in ('movie','series'):raise ValueError('Film oder Serie auswählen')
    mode=str(data.get('mode') or 'availability')
    if mode not in ('availability','weekly'):raise ValueError('Unbekannter Abonnement-Rhythmus')
    try:weekday=int(data.get('weekday',0));hour=int(data.get('hour',19))
    except (TypeError,ValueError):raise ValueError('Wochentag und Stunde müssen Zahlen sein') from None
    if not 0<=weekday<=6 or not 0<=hour<=23:raise ValueError('Ungültiger Wochentag oder Stunde')
    year=data.get('year') or None
    if year is not None:
        try:year=int(year)
        except (TypeError,ValueError):raise ValueError('Ungültiges Erscheinungsjahr') from None
        if not 1880<=year<=2100:raise ValueError('Ungültiges Erscheinungsjahr')
    show_key=str(data.get('show_key') or '')
    if show_key and (kind!='series' or len(show_key)!=28 or any(x not in '0123456789abcdef' for x in show_key)):
        raise ValueError('Ungültige Serienkennung')
    include=bool(data.get('include_existing',kind=='movie'))
    sub_id=secrets.token_hex(12)
    due=now if mode=='availability' else next_weekly(now,weekday,hour)
    c.execute("""INSERT INTO subscriptions(id,kind,title,show_key,year,mode,weekday,hour,
        include_existing,enabled,created,next_check)
        VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
        (sub_id,kind,title,show_key,year,mode,weekday,hour,int(include),now,due))
    if not include:
        # Mark only *already active* works at subscription creation.
        # Offers that become available later remain eligible.
        for (wid,) in c.execute("""SELECT DISTINCT w.id FROM works w
            JOIN offers o ON o.work_id=w.id AND o.active=1
            WHERE (w.kind=? OR (w.kind='unknown' AND w.topic=?))
              AND (w.title=? COLLATE NOCASE OR w.topic=? COLLATE NOCASE OR w.show_key=?)""",
                (kind,title,title,title,show_key or '___no_series___')):
            c.execute('INSERT OR IGNORE INTO subscription_seen VALUES(?,?)',(sub_id,wid))
    return sub_id

def change(c,sub_id,action):
    if action not in ('pause','resume','delete'):raise ValueError('Unbekannte Abo-Aktion')
    row=c.execute('SELECT id FROM subscriptions WHERE id=?',(sub_id,)).fetchone()
    if not row:raise ValueError('Abonnement nicht gefunden')
    if action=='delete':
        c.execute('DELETE FROM subscriptions WHERE id=?',(sub_id,))
        c.execute('DELETE FROM subscription_seen WHERE subscription_id=?',(sub_id,))
        # Keep historical subscription_jobs and any already queued/finished downloads.
    else:
        c.execute('UPDATE subscriptions SET enabled=?,next_check=? WHERE id=?',
                  (1 if action=='resume' else 0,time.time(),sub_id))
    return True

def media_key(meta,show_key):
    """No guessed season/episode, and stable across different broadcaster offers."""
    kind=meta.get('kind')
    if kind=='series':
        season,episode=meta.get('season'),meta.get('episode')
        if not isinstance(season,int) or not isinstance(episode,int) or episode<1 or season<0:return None
        if not meta.get('episode_verified') and meta.get('state') not in ('user_confirmed','manual'):return None
        return 'series:'+str(show_key or catalog.key(meta.get('title')))+':%03d:%04d'%(season,episode)
    if kind=='movie':
        ident=meta.get('imdb_id') or (str(meta.get('provider'))+':'+str(meta.get('reference_id'))
                                      if meta.get('reference_id') else '')
        return 'movie:'+(str(ident) if ident else catalog.key(meta.get('title'))+':'+str(meta.get('year') or ''))
    return None

def expired(source,now):
    """Only a verified source expiry is grounds for skipping an offer."""
    raw=source.get('available_until')
    if not raw:return False
    try:
        d=datetime.datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        if len(str(raw))==10:d+=datetime.timedelta(days=1)
        return d.timestamp()<=now
    except (ValueError,TypeError,OverflowError):return False

def due(c,now):
    return [dict(r) for r in c.execute("""SELECT * FROM subscriptions
        WHERE enabled=1 AND next_check<=? ORDER BY next_check LIMIT 20""",(now,))]

def candidates(c,sub):
    """Bound work lookup; never accept only a fuzzy title similarity."""
    if sub['show_key']:
        rows=c.execute("""SELECT * FROM works WHERE kind='series'
            AND show_key=? AND state IN ('matched','manual')
            ORDER BY updated DESC LIMIT 500""",(sub['show_key'],)).fetchall()
    else:
        rows=c.execute("""SELECT * FROM works WHERE kind=? AND state IN ('matched','manual')
            AND title=? COLLATE NOCASE ORDER BY updated DESC LIMIT 500""",
            (sub['kind'],sub['title'])).fetchall()
    verified=[]
    for row in rows:
        meta=json.loads(row['meta'])
        if catalog.key(meta.get('title'))!=catalog.key(sub['title']):continue
        if sub['year'] and meta.get('year')!=sub['year']:continue
        if meta.get('kind')!=sub['kind']:continue
        verified.append((row,meta))
    if sub['kind']=='movie' and not sub['year']:
        years={m.get('year') for _,m in verified}
        if len(years)>1:raise AmbiguousTitle('Gleichnamige Filme: bitte Erscheinungsjahr im Abo angeben')
    if sub['kind']=='series' and not sub['show_key']:
        shows={row['show_key'] for row,_ in verified}
        if len(shows)>1:raise AmbiguousTitle('Mehrere Serien mit diesem Titel: Abo aus dem richtigen Katalogeintrag erstellen')
    yield from verified

def enqueue_due(c,sub,root,now=None,limit=10):
    """Caller runs in one immediate SQLite transaction. No download starts here."""
    now=time.time() if now is None else now
    queued=0
    for row,meta in candidates(c,sub):
        if queued>=limit:break
        seen=c.execute('SELECT 1 FROM subscription_seen WHERE subscription_id=? AND work_id=?',
                      (sub['id'],row['id'])).fetchone()
        if seen:continue
        # The catalogue can change a provisional work ID when metadata is
        # confirmed. Keep future-only subscriptions tied to the original offer.
        if c.execute("""SELECT 1 FROM subscription_seen s
            JOIN work_aliases a ON a.old_id=s.work_id
            WHERE s.subscription_id=? AND a.new_id=? LIMIT 1""",
            (sub['id'],row['id'])).fetchone():continue
        key=media_key(meta,row['show_key'])
        if key is None:continue
        if c.execute('SELECT 1 FROM subscription_jobs WHERE subscription_id=? AND media_key=?',
                     (sub['id'],key)).fetchone():continue
        if c.execute('SELECT 1 FROM downloaded_items WHERE identity=?',(row['id'],)).fetchone():continue
        # Prefer a confirmed direct file from an active, unexpired offer.
        selected=None
        for offer in c.execute("""SELECT * FROM offers WHERE work_id=? AND active=1
            ORDER BY (special='') DESC,rank DESC,seen DESC LIMIT 20""",(row['id'],)).fetchall():
            source=json.loads(offer['payload'])
            source.update(catalog.offer_expiry(c,offer['id']))
            if expired(source,now):continue
            links=[x for x in catalog.links(source) if x.get('supported') and x.get('url')]
            if links:
                selected=(offer,source,links[0]['url'])
                break
        if not selected:continue
        offer,source,url=selected
        try:target=str(core.target(root,meta,offer['id']))
        except (ValueError,TypeError):continue
        if core.existing_download(target):continue
        if c.execute("""SELECT 1 FROM jobs WHERE state IN
            ('queued','downloading','tagging','done') AND json_extract(payload,'$.target')=? LIMIT 1""",
            (target,)).fetchone():continue
        job_id=secrets.token_hex(8)
        j={'id':job_id,'source':{**source,'_id':offer['id'],'_download_url':url},
           'metadata':meta,'root':str(root),'quality':'best','target':target,
           'state':'queued','received':0,'total':0,
           'subscription_id':sub['id'],'subscription_key':key,
           'subscription_created':now}
        # Unique identity constraint prevents duplicate queueing across restart,
        # server threads, changed offers, and parallel subscription checks.
        c.execute('INSERT INTO subscription_jobs VALUES(?,?,?,?)',(sub['id'],key,job_id,now))
        c.execute('INSERT INTO jobs(id,payload,state) VALUES(?,?,?)',(job_id,json.dumps(j),'queued'))
        c.execute('INSERT OR IGNORE INTO subscription_seen VALUES(?,?)',(sub['id'],row['id']))
        queued+=1
    return queued

def run_due(c,root,now=None,force_id=None):
    now=time.time() if now is None else now
    rows=[dict(r) for r in c.execute('SELECT * FROM subscriptions WHERE enabled=1 AND id=?',(force_id,))] if force_id else due(c,now)
    result=[]
    for sub in rows:
        nxt=weekly_followup(now,sub['weekday'],sub['hour']) if sub['mode']=='weekly' else now+15*60
        try:
            c.execute('SAVEPOINT subscription_scan')
            total=enqueue_due(c,sub,root,now)
            c.execute('RELEASE subscription_scan')
            error=''
        except Exception as exc:
            # One malformed offer must not block all other subscriptions or
            # leave half a batch queued. Back off and keep the plan active.
            c.execute('ROLLBACK TO subscription_scan')
            c.execute('RELEASE subscription_scan')
            total=0
            error=(str(exc) if isinstance(exc,AmbiguousTitle)
                   else 'Prüfung fehlgeschlagen; erneuter Versuch beim nächsten Termin')
        c.execute('UPDATE subscriptions SET last_check=?,next_check=?,queued_count=queued_count+?,last_error=? WHERE id=?',
                  (now,nxt,total,error,sub['id']))
        result.append({'id':sub['id'],'title':sub['title'],'queued':total,'next_check':nxt,
                       'error':error or None})
    return result
