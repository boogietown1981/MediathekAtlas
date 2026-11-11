"""On-demand public Netzkino metadata details.

Independent Netzkino cache: only public editorial fields; never store player URLs,
DRM manifests, account data, GraphQL response blobs or cookies. No background
prefetch, no changes to MediathekView work/offer/download tables.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
from pathlib import Path

import netzkino

SCHEMA = '''
CREATE TABLE IF NOT EXISTS netzkino_public_details (
 item_id TEXT PRIMARY KEY, payload TEXT NOT NULL, checked REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS netzkino_detail_failures (
 item_id TEXT PRIMARY KEY, next_attempt REAL NOT NULL, reason TEXT NOT NULL,
 checked REAL NOT NULL
);
'''
TTL_SECONDS = 7 * 86400
MAX_CAST = 16
MAX_CREW = 12
VALID_ID = re.compile(r'^[0-9a-f]{32}$')
SAFE_IMAGE_HOST = re.compile(r'^(?:[a-z0-9-]+\.)?cloudfront\.net$')


def _trim(value, limit=300):
    return ' '.join(str(value or '').split())[:limit]


def _image(value):
    if isinstance(value, dict): value = value.get('masterUrl')
    if not isinstance(value, str) or len(value)>800: return ''
    p=urllib.parse.urlsplit(value)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None,443):return ''
    if not (p.hostname in ('netzkino.de','www.netzkino.de') or
            (p.hostname and SAFE_IMAGE_HOST.fullmatch(p.hostname))):return ''
    return value


def _people(node, limit=MAX_CAST):
    if not isinstance(node, dict):return []
    rows=node.get('nodes')
    if not isinstance(rows,list):return []
    result=[]
    for row in rows[:50]:
        if not isinstance(row,dict):continue
        person=row.get('person') or {}
        if not isinstance(person,dict):continue
        name=_trim(person.get('name'),120)
        if name and name not in result:result.append(name)
        if len(result)>=limit:break
    return result


def normalize(node):
    """Permit only presentation data from MovieDetails. Ignore videoSource, DRM, licenses."""
    if not isinstance(node,dict):raise ValueError('Netzkino-Filmdetails nicht vorhanden')
    content_id=_trim(node.get('id'),80)
    if not re.fullmatch(r'[A-Za-z0-9_\-]{3,80}',content_id):
        raise ValueError('Netzkino-Filmkennung fehlt')
    synopsis=next((_trim(node.get(key),3200) for key in
                   ('longSynopsis','mediumSynopsis','shortSynopsis') if node.get(key)), '')
    flags=node.get('flags') if isinstance(node.get('flags'),list) else []
    genres=[]
    for flag in flags[:70]:
        if isinstance(flag,str) and flag.startswith('genres:'):
            genre=_trim(flag.split(':',1)[1],50)
            if genre and genre not in genres:genres.append(genre)
    year=node.get('productionYear')
    try:year=int(year) if year is not None else None
    except (TypeError,ValueError):year=None
    if year is not None and not 1880<=year<=2100:year=None
    duration=node.get('runtimeInSeconds')
    try:duration=int(duration) if duration is not None else None
    except (TypeError,ValueError):duration=None
    if duration is not None and not 0<duration<=86400:duration=None
    fsk=node.get('fskRating')
    try:fsk=int(fsk) if fsk is not None else None
    except (TypeError,ValueError):fsk=None
    if fsk not in (0,6,12,16,18):fsk=None
    access=['AVOD' if 'properties:avod' in flags else None,
            'Plus' if 'properties:svod' in flags else None]
    return {
        'content_id':content_id,'title':_trim(node.get('title'),180),
        'original_title':_trim(node.get('originalTitle'),220),
        'year':year,'duration_seconds':duration,'fsk':fsk,
        'description':synopsis,'short_description':_trim(node.get('shortSynopsis'),800),
        'genres':genres[:18],
        'country':_trim(node.get('productionCountry'),80),
        'original_language':_trim(node.get('originalLanguage'),180),
        'cast':_people(node.get('cast')),
        'directors':_people(node.get('directors'),MAX_CREW),
        'writers':_people(node.get('writers'),MAX_CREW),
        'poster':_image(node.get('coverImage')),
        'backdrop':_image(node.get('widescreenImage') or node.get('headerImage')),
        'access_types':[x for x in access if x],
        'source':'netzkino_graphql_movie_details',
        'identity_verified':False, 'availability_verified':False,
    }


def seed_lookup(content_id):
    """Small, sanitized, user-supplied HAR samples for offline testing."""
    p=Path(__file__).resolve().parent/'assets'/'netzkino_details_seed.json'
    try:
        if p.stat().st_size>180000:return None
        data=json.loads(p.read_text('utf-8'))
        value=data.get(content_id)
        return value if isinstance(value,dict) else None
    except (OSError,ValueError,TypeError):return None


def _connect(root):
    db=netzkino._connect(root)
    db.executescript(SCHEMA)
    return db


def _find(db, item_id):
    if not VALID_ID.fullmatch(str(item_id)):
        raise ValueError('Ungültige lokale Netzkino-Kennung')
    row=db.execute('''SELECT id,title,url,content_id,kind,year,duration,genres,summary,
                      poster,access_hint,category,fsk FROM netzkino_catalog WHERE id=?''',(item_id,)).fetchone()
    if row is None:
        manual=db.execute('SELECT id,title,url FROM netzkino_links WHERE id=?',(item_id,)).fetchone()
        if manual is None:raise ValueError('Netzkino-Titel nicht gespeichert')
        return {'id':manual['id'],'title':manual['title'],
                'url':netzkino.verified_url(manual['url']),'content_id':'',
                'kind':'movie','year':None,'duration':None,'genres':'',
                'summary':'','poster':'','access_hint':'','category':'','fsk':None}
    result=dict(row)
    result['url']=netzkino.verified_url(result['url'])
    return result


def find_page(root,item_id):
    db=_connect(root)
    try:return _find(db,item_id)['url']
    finally:db.close()


def _fallback(row):
    return {'content_id':row.get('content_id') or '', 'title':row['title'],
            'original_title':'','year':row.get('year'),
            'duration_seconds':row.get('duration'),'fsk':row.get('fsk'),
            'description':row.get('summary') or '', 'short_description':'',
            'genres':[g.strip() for g in (row.get('genres') or '').split(',') if g.strip()][:18],
            'country':'','original_language':'','cast':[],'directors':[],'writers':[],
            'poster':row.get('poster') or '','backdrop':'',
            'access_types':[], 'source':'netzkino_catalog',
            'identity_verified':False,'availability_verified':False}


def get(root,item_id,*,fetch=None,now=None):
    """Return saved fields; load optional detail once per user-open, never mass-scan."""
    now=time.time() if now is None else float(now)
    db=_connect(root)
    try:
        row=_find(db,item_id)
        fallback=_fallback(row)
        cached=db.execute('SELECT payload,checked FROM netzkino_public_details WHERE item_id=?',(item_id,)).fetchone()
        if cached:
            try:stored=json.loads(cached['payload'])
            except (TypeError,ValueError):stored=None
            if isinstance(stored,dict):
                fallback={**fallback,**stored}
                if now-cached['checked']<TTL_SECONDS:
                    return {'details':fallback,'page_url':row['url'],'cached':True,'error_type':None}
        content_id=row['content_id']
        # Sitemap-only titles (0.5.32) have no GraphQL id yet: the website itself
        # requests MovieDetails by the page slug, so use that and learn the id.
        by_slug=False
        if not content_id:
            slug=urllib.parse.unquote(urllib.parse.urlsplit(row['url']).path.rsplit('/',1)[-1])
            if not re.fullmatch(r'[A-Za-z0-9._~-]{2,150}',slug):
                return {'details':fallback,'page_url':row['url'],
                        'cached':bool(cached),'error_type':'no_provider_content_id'}
            content_id=slug;by_slug=True
        delay=db.execute('SELECT next_attempt,reason FROM netzkino_detail_failures WHERE item_id=?',(item_id,)).fetchone()
        if delay and now<delay['next_attempt']:
            return {'details':fallback,'page_url':row['url'],'cached':bool(cached),
                    'error_type':delay['reason'],'retry_after':delay['next_attempt']}
        variables={'movieId':content_id,'externalId':content_id,
                   'slug':content_id,'potentialMovieId':content_id}
        try:
            payload=(fetch or netzkino._fetch_graphql)('MovieDetails',variables)
            if not isinstance(payload,dict):raise ValueError('Netzkino antwortet ohne Filmdetails')
            movie=payload.get('movie') or payload.get('series')
            detail=normalize(movie)
            if not by_slug and detail['content_id']!=content_id:
                raise ValueError('Netzkino-Filmkennung stimmt nicht mit Katalog überein')
            # Preserve an existing known title when MovieDetails is absent/empty.
            detail['title']=detail['title'] or row['title']
            with db:
                db.execute('''INSERT INTO netzkino_public_details(item_id,payload,checked)
                    VALUES(?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                    payload=excluded.payload,checked=excluded.checked''',
                    (item_id,json.dumps(detail,ensure_ascii=False),now))
                db.execute('DELETE FROM netzkino_detail_failures WHERE item_id=?',(item_id,))
                if by_slug:
                    db.execute("""UPDATE netzkino_catalog SET content_id=?,
                        year=COALESCE(year,?),duration=COALESCE(duration,?),
                        poster=CASE WHEN COALESCE(poster,'')='' THEN ? ELSE poster END,
                        fsk=COALESCE(fsk,?) WHERE id=? AND COALESCE(content_id,'')=''""",
                        (detail['content_id'],detail['year'],detail['duration_seconds'],
                         detail['poster'] or '',detail['fsk'],item_id))
            return {'details':{**fallback,**detail},'page_url':row['url'],
                    'cached':False,'error_type':None}
        except Exception as exc:
            http=getattr(exc,'code',None)
            reason=('http_'+str(http) if http in (401,403,429,500,502,503,504)
                    else 'invalid_details' if isinstance(exc,ValueError) else 'network')
            retry=(12*3600 if http in (401,403,429) else 15*60)
            with db:
                db.execute('''INSERT INTO netzkino_detail_failures(item_id,next_attempt,reason,checked)
                    VALUES(?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                    next_attempt=excluded.next_attempt,reason=excluded.reason,checked=excluded.checked''',
                    (item_id,now+retry,reason,now))
            # Never export a raw exception which could include a URL or token.
            netzkino._notify('netzkino_public_detail_unavailable',reason=reason)
            seed=seed_lookup(content_id)
            if seed:fallback={**fallback,**seed}
            return {'details':fallback,'page_url':row['url'],
                    'cached':bool(cached or seed),'error_type':reason,'retry_after':now+retry}
    finally:db.close()


def stats(root):
    p=Path(root)/'netzkino_links.sqlite3'
    if not p.is_file():return {'cached_details':0,'detail_errors':0}
    db=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {'cached_details':db.execute('SELECT COUNT(*) FROM netzkino_public_details').fetchone()[0]
                    if 'netzkino_public_details' in names else 0,
                'detail_errors':db.execute('SELECT COUNT(*) FROM netzkino_detail_failures').fetchone()[0]
                    if 'netzkino_detail_failures' in names else 0}
    finally:db.close()
