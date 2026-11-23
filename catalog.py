"""Local work/episode catalogue, alternative offers and conservative matching."""
import hashlib,json,re,sqlite3,threading,time,unicodedata
import core
SCHEMA='''
CREATE TABLE IF NOT EXISTS downloaded_items(identity TEXT PRIMARY KEY,path TEXT,finished REAL);
CREATE TABLE IF NOT EXISTS scan_seen(id TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS format_dirty(work_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS film_hints(work_id TEXT PRIMARY KEY,score INTEGER NOT NULL,reason TEXT);
CREATE TABLE IF NOT EXISTS metadata_leases(work_id TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS metadata_leases_expiry ON metadata_leases(expires);
CREATE INDEX IF NOT EXISTS film_hint_score ON film_hints(score,work_id);
CREATE TABLE IF NOT EXISTS work_aliases(old_id TEXT PRIMARY KEY,new_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offer_availability(offer_id TEXT PRIMARY KEY,available_until TEXT,source TEXT,checked REAL);
CREATE TABLE IF NOT EXISTS artwork_checks(work_id TEXT PRIMARY KEY,next_try REAL);
CREATE TABLE IF NOT EXISTS artwork_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL);
CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY,title TEXT,kind TEXT,year INTEGER,show_key TEXT,meta TEXT,state TEXT DEFAULT 'pending',next_try REAL DEFAULT 0,attempts INTEGER DEFAULT 0,updated REAL,topic TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY,work_id TEXT,payload TEXT,special TEXT,rank INTEGER,seen REAL,active INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS offer_work ON offers(work_id,active,rank DESC);
CREATE TABLE IF NOT EXISTS series_templates(topic TEXT,provider TEXT,reference TEXT,meta TEXT,PRIMARY KEY(topic,provider,reference));
CREATE TABLE IF NOT EXISTS metadata_priority(work_id TEXT PRIMARY KEY,requested REAL);
CREATE TABLE IF NOT EXISTS series_focus(show_key TEXT PRIMARY KEY,until REAL,remaining INTEGER,updated REAL);
CREATE TABLE IF NOT EXISTS episode_queue(work_id TEXT PRIMARY KEY,next_try REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,last_outcome TEXT NOT NULL DEFAULT 'pending',updated REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS episode_queue_due ON episode_queue(next_try,work_id);
-- The work state is the source of truth: manual matches, format classification,
-- merges and deletion automatically remove stale episode tasks.
CREATE TRIGGER IF NOT EXISTS episode_queue_work_insert AFTER INSERT ON works
WHEN NEW.kind='series' AND NEW.state='identified'
 AND NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NOT NULL
 AND json_type(NEW.meta,'$.deferred_providers') IS NULL
 AND COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0
BEGIN
 INSERT INTO episode_queue(work_id) SELECT NEW.id
 WHERE NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS episode_queue_work_update AFTER UPDATE OF id,kind,state,meta ON works
BEGIN
 DELETE FROM episode_queue WHERE work_id=OLD.id AND
    (NEW.id!=OLD.id OR NEW.kind!='series' OR NEW.state!='identified'
     OR NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NULL
     OR json_type(NEW.meta,'$.deferred_providers') IS NOT NULL
     OR COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)!=0
     OR COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)!=0);
 INSERT INTO episode_queue(work_id)
 SELECT NEW.id WHERE NEW.kind='series' AND NEW.state='identified'
  AND NULLIF(json_extract(NEW.meta,'$.reference_id'),'') IS NOT NULL
  AND json_type(NEW.meta,'$.deferred_providers') IS NULL
  AND COALESCE(json_extract(NEW.meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0
 AND NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS episode_queue_work_delete AFTER DELETE ON works
BEGIN DELETE FROM episode_queue WHERE work_id=OLD.id; END;

CREATE INDEX IF NOT EXISTS work_first_pass ON works(attempts,state,kind,next_try);
-- 0.6.35: work_identity_recheck (0.6.29/0.6.31) is no longer part of SCHEMA, see IDENTITY_INDEX_SQL.
CREATE INDEX IF NOT EXISTS work_queue ON works(kind,state,next_try);
CREATE INDEX IF NOT EXISTS work_type ON works(kind,title);
CREATE INDEX IF NOT EXISTS work_retry ON works(state,next_try);
CREATE INDEX IF NOT EXISTS work_show ON works(show_key);
CREATE INDEX IF NOT EXISTS work_listing ON works(kind,show_key,id,title,year,state);
CREATE TABLE IF NOT EXISTS work_genres(work_id TEXT,genre TEXT,PRIMARY KEY(work_id,genre));
CREATE INDEX IF NOT EXISTS genre_index ON work_genres(genre,work_id);
CREATE TABLE IF NOT EXISTS catalog_state(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS mesh_downloads(key TEXT PRIMARY KEY,node TEXT,name TEXT,state TEXT,until REAL,path TEXT,size INTEGER,hlc INTEGER,local TEXT,works TEXT);
CREATE TABLE IF NOT EXISTS mesh_download_works(work_id TEXT PRIMARY KEY,key TEXT);
CREATE TABLE IF NOT EXISTS mesh_results(work_id TEXT PRIMARY KEY,rank INTEGER,providers INTEGER,hlc INTEGER,node TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS mesh_episodes(work_id TEXT PRIMARY KEY,until INTEGER NOT NULL,archive INTEGER NOT NULL,sender INTEGER NOT NULL DEFAULT 0,node TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mesh_conflicts(work_id TEXT PRIMARY KEY,node TEXT NOT NULL,name TEXT NOT NULL,payload TEXT NOT NULL,seen REAL NOT NULL);
'''
SPECIAL=re.compile(r'(?i)\b(audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung)\b|\((?:AD|DGS)\)')
SUFFIX=re.compile(r'(?i)\s*[([](?:mit\s+)?(?:audiodeskription|audio[- ]?description|hörfassung|hörfilm|gebärdensprache|gebärdenfassung|AD|DGS|HD|UHD|4K|untertitel(?:n)?|UT|OmU|OV|Originalversion(?:\s+mit\s+Untertitel(?:n)?)?|Originalfassung(?:\s+mit\s+Untertitel(?:n)?)?|Original\s+mit\s+Untertitel(?:n)?|VOST(?:F)?|VO-?ST)[)\]]\s*')
EP=re.compile(r'(?i)\bS(\d{1,2})[\s/._-]*E(\d{1,4})\b|\b(\d{1,2})x(\d{1,4})\b|\bStaffel\s*(\d+)\D{1,20}Folge\s*(\d+)\b')
GENRES={'Krimi':r'\b(?:krimi|kriminalfilm|krimiserie|tatort|polizeiruf)\b','Komödie':r'\b(?:komödie|comedy|sitcom)\b','Drama':r'\b(?:drama|melodram)\b','Thriller':r'\bthriller\b','Science-Fiction':r'\b(?:science.fiction|sci.fi)\b','Fantasy':r'\bfantasy\b','Animation':r'\b(?:animation|zeichentrick|anime)\b','Dokumentation':r'\b(?:dokumentation|dokumentarfilm|dokumentarserie|doku)\b','Kinder':r'\b(?:kinderfilm|kinderserie)\b','Familie':r'\bfamilienfilm\b','Romantik':r'\b(?:liebesfilm|romantik|romantische komödie)\b'}

def key(s):
    s=unicodedata.normalize('NFKD',str(s or '').casefold())
    return re.sub(r'[^\w]+',' ',''.join(c for c in s if not unicodedata.combining(c))).strip()
def digest(s):return hashlib.sha256(s.encode()).hexdigest()[:28]
def cleaned(s):return re.sub(r'\s+',' ',SUFFIX.sub('',core.clean(s))).strip(' -')
def special(row):
    m=SPECIAL.search(str(row.get('title',''))+' '+str(row.get('topic','')))
    return ('Gebärdensprache' if m and re.search(r'(?i)gebär|DGS',m.group()) else 'Audiodeskription') if m else ''
def links(row):
    out=[]
    for field,label,q in [('url_video_hd','HD',720),('url_video','Standard',480),('url_video_low','Klein',240)]:
        url=row.get(field)
        if url and url not in [x['url'] for x in out]:
            match=re.search(r'(?i)(2160|1080|720|480|360)p\b',url);height=int(match.group(1)) if match else 0
            out.append({'url':url,'quality':label,'height_hint':height,'supported':not re.search(r'(?i)\.(?:m3u8|mpd)(?:\?|$)',url),'score':height or q})
    return sorted(out,key=lambda x:(x['supported'],x['score']),reverse=True)
def ranking(row):
    l=links(row)
    return (0 if special(row) else 1000000)+(100000 if l and l[0]['supported'] else 0)+(l[0]['score'] if l else 0)

# 0.6.78 (Mac-Abfrage K12, 21.11.2026): SWR/WDR „Planet Schule“ files every programme under the portal topic
# "planet schule"; the title is "<Folgentitel> · <Reihe>" (also "⋅"). 182 of 200 sampled offers carry the series
# that way ("Achtung! Experiment", "Big Cities", "total phänomenal", "Knietzsche, der kleinste Philosoph der Welt").
PORTAL_TOPICS={'planet schule'}
PORTAL_SEPARATOR=re.compile(r'\s+[·⋅•]\s+')
def portal_series(topic,title):
    """(episode title, series) for an offer of a school/education portal titled "<Folge> · <Reihe>", else None."""
    if key(topic) not in PORTAL_TOPICS:return None
    parts=PORTAL_SEPARATOR.split(str(title or ''))
    if len(parts)<2:return None
    series=parts[-1].strip(' -');episode=' · '.join(parts[:-1]).strip(' -')
    if not (2<=len(series)<=80) or not episode or key(series)==key(topic):return None
    return episode,series

def portal_identity(m,topic=''):
    """0.6.84: a series identity that is only the portal („planet schule“ ARD Mediathek, TVDB „Planet Schule“).
    0.6.87: or a subject word that is the offer's topic (IMDb series „Doku“ for the ZDF topic „Doku“)."""
    if not m or m.get('kind')!='series':return False
    name=key(m.get('title'))
    if name in PORTAL_TOPICS:return True
    if name not in TEMPLATE_GENERIC:return False
    # 0.6.118 (Mac-Prüfung 0.6.117: 1.045 Fußball-/Skibeiträge mit der ZDF-Seite „Schwimmen“ als Serie): a subject
    # word is no programme identity under any topic unless IMDb or TVDB know it as a series. A sport may be a real
    # series („Formel 1“, TVDB 387219); a subject word named like the topic stays excluded even then (IMDb „Doku“, 0.6.87).
    if not database_series(m):return True
    return name not in _metadata.SPORT_WORDS and bool(topic) and name==key(topic)

def database_series(m):
    """0.6.118: True if IMDb or TVDB know the identity as a series (an IMDb tt-ID or a TVDB reference)."""
    m=m or {}
    if str(m.get('imdb_id') or '').startswith('tt'):return True
    if m.get('provider') in ('TVDB','OMDb','IMDb Offline') and m.get('reference_id'):return True
    return bool(m.get('tvdb_id'))

def template_topic(topic,title=''):
    """0.6.84: True if a series template may be learned or used for this topic.

    Mac-Prüfung 0.6.82: the template learned for the topic „planet schule“ (ARD Mediathek, the portal) gave every
    re-recognised work under that topic the portal identity again within seconds (series_template_candidate), and
    propagate_series carried it to all works of the Reihe („Natur nah“: 99 works). A portal or section topic
    names no series; an offer titled „<Folge> · <Reihe>“ names its own."""
    import metadata
    if not topic or key(topic) in PORTAL_TOPICS or key(topic) in TEMPLATE_GENERIC or metadata.generic_topic(topic):return False
    return not portal_series(topic,title)

# 0.6.86 (Diagnose MacBook Air 22.11.2026, 0.6.85): templates „Sport“ and „Masterclass“ – subjects, not series
# („Lisy Christl – Masterclass Kostümbild …“ belongs to the film). Single words naming a subject or a kind of
# programme are never learned as a series template; real one-word Sendungen („Puls“, „Bounce“) stay possible.
TEMPLATE_GENERIC={'sport','sports','masterclass','kultur','wissen','geschichte','gesellschaft','unterhaltung','comedy',
    'kabarett','satire','konzert','konzerte','interview','interviews','talk','doku','dokus','dokumentation','dokumentationen',
    'reportage','reportagen','nachrichten','news','magazin','magazine','kinder','familie','ratgeber','verbraucher',
    'gesundheit','wirtschaft','religion','sendungen','videos','clips','highlights','extras','bonus','trailer','shorts',
    'wissenschaft','technik','digital','umwelt','klima','literatur','theater','oper','tanz','kunst','architektur','essen',
    'kochen','garten','reisen','dokumentarfilm','dokumentarfilme','kurzfilm','kurzfilme','spielfilme','fernsehfilme','europa'}
import metadata as _metadata
TEMPLATE_GENERIC|=_metadata.SPORT_WORDS   # 0.6.117: „Schwimmen“ (Air 23.11.2026, 1.144 Werke)

def generic_identity_works(c,after='',limit=500):
    """0.6.86: identified works whose series identity is a subject word (template „Sport“).
    0.6.118 (Mac-Prüfung 0.6.117): whatever their topic („Schwimmen“ on Fußball/Ski offers), but never an identity
    IMDb or TVDB know as a series („Formel 1“, TVDB 387219) – those rows are left out.
    0.6.117 also reset Wikidata-only Sendungen named like their topic (Tell-Star, Cinema Strikes Back, Berichte vom Tage):
    that pass is gone, they are real programmes. Read only; (rows with best offer payload, last id or None)."""
    marks=','.join('?'*len(TEMPLATE_GENERIC))
    rows=c.execute("""SELECT w.*,(SELECT o.payload FROM offers o WHERE o.work_id=w.id AND o.active=1 ORDER BY o.rank DESC LIMIT 1) payload
        FROM works w WHERE w.id>? AND w.state='identified' AND w.kind='series' AND lower(w.title) IN (%s)
        ORDER BY w.id LIMIT ?"""%marks,(after,*sorted(TEMPLATE_GENERIC),limit)).fetchall()
    last=rows[-1]['id'] if rows else None
    keep=[]
    for row in rows:
        try:m=json.loads(row['meta'] or '{}')
        except (TypeError,ValueError):continue
        if portal_identity(dict(m,kind='series',title=row['title']),row['topic']):keep.append(row)
    return keep,last

UNDO_GENERIC_REASON='Thema ist keine Serie (%s); neu erkennen (0.6.87)'
def undo_generic_reset_works(c,shows,after=0,limit=500):
    """0.6.118: works 0.6.117 reset as „Thema ist keine Serie“ although their name is a real programme (Tell-Star,
    Formel 1, Sonntagsmärchen; generic_templates_v06117 'shows'). Read only; (rows, last id or None)."""
    titles=[t for t in shows if key(t) not in TEMPLATE_GENERIC or key(t) in REAL_SPORT_SERIES]
    if not titles:return [],None
    reasons=[UNDO_GENERIC_REASON%t for t in titles]
    marks=','.join('?'*len(reasons))
    rows=c.execute("""SELECT id,state,meta FROM works WHERE id>? AND state IN ('pending','retry','review','format')
        AND json_extract(meta,'$.reason') IN (%s) ORDER BY id LIMIT ?"""%marks,(after,*reasons,limit)).fetchall()
    return rows,(rows[-1]['id'] if rows else None)
# Sports words that are also real series at IMDb/TVDB; a reset under such a name is undone (it is recognised again).
REAL_SPORT_SERIES={'formel 1','formel e'}

def drop_portal_templates(c):
    """0.6.84: forget templates learned for a portal/section topic or with a portal identity (returns count)."""
    gone=0
    for topic,provider,ref,meta in c.execute('SELECT topic,provider,reference,meta FROM series_templates').fetchall():
        try:m=json.loads(meta or '{}')
        except (TypeError,ValueError):m={}
        if not template_topic(topic) or portal_identity(m,topic):
            gone+=c.execute('DELETE FROM series_templates WHERE topic=? AND provider=? AND reference=?',(topic,provider,ref)).rowcount
    return gone

def portal_reseed(c,limit=500,after=''):
    """0.6.78, once (see PORTAL_TOPICS): automatic works of a portal topic whose series is in the title are
    recognised again from the sender data. User decisions, matches and confirmed episodes stay.
    Returns (changed, last id or None)."""
    # 0.6.85 (Mac-Prüfung 0.6.84): also works whose identity is the portal under another or an empty topic
    # („Sarah Baatout … · Women of Science“ TVDB 461332 matched, „Rafik Schami · Der Erzähler“ ARD „Planet Schule“).
    marks=','.join('?'*len(PORTAL_TOPICS))
    rows=c.execute("""SELECT * FROM works WHERE id>? AND (lower(topic) IN (%s) OR lower(title) IN (%s)) ORDER BY id LIMIT ?"""
                   %(marks,marks),(after,*sorted(PORTAL_TOPICS),*sorted(PORTAL_TOPICS),limit)).fetchall()
    changed=0
    for row in rows:
        # 0.6.81 (Mac-Prüfung 0.6.78: 15 Werke „Das kleine 1x1 der Artenkunde“ blieben „Planet Schule“): an automatic
        # match whose identity is the portal itself is no match of the programme; a user's choice ('manual') stays.
        portal=key(row['title']) in PORTAL_TOPICS
        if row['state']=='matched' and portal:pass
        elif row['state'] not in ('pending','retry','review','identified','format'):continue
        try:m=json.loads(row['meta'] or '{}')
        except (TypeError,ValueError):continue
        if m.get('scan_requested'):continue
        # 0.6.82 (Mac-Prüfung 0.6.81): an episode "confirmed" against the portal itself (TVDB „Planet Schule“) or a
        # contribution of the Sendung „planet schule“ (ARD Mediathek) is no evidence for the programme.
        if m.get('episode_verified') and not portal:continue
        if row['state']=='format' and not portal and m.get('format_grouping') not in ('single','contribution','part',None):continue
        source=best_source(c,row['id'])
        if not source:continue
        if portal and key(source.get('topic') or row['topic']) not in PORTAL_TOPICS:
            source=dict(source,topic=next(iter(PORTAL_TOPICS)))      # read the title as the portal names it
        if not portal_series(source.get('topic') or row['topic'],cleaned(source.get('title'))):
            # 0.6.92 (Mac-Prüfung 0.6.87, echter Bestand): „Religionen der Welt: …“ without „·“ stayed a contribution
            # of the Sendung „planet schule“. Such a filing is recognised again from the work's own title; an ARD
            # identification without a series in the title stays (0.6.85, Mac-Prüfung 0.6.87: 113 such, accepted).
            if not portal or row['state']!='format':continue
        fresh=seed(source)
        if key(fresh.get('title')) in PORTAL_TOPICS:
            fresh.update(kind='unknown',title=cleaned(source.get('title')) or row['title'],episode_title='')
        if row['kind']=='series' and key(row['title'])==key(fresh['title']):continue
        fresh['reason']='Reihe aus dem Titel (Planet Schule); neu erkennen'
        changed+=c.execute("UPDATE works SET title=?,kind=?,show_key=?,meta=?,state='pending',next_try=0,attempts=0 WHERE id=?",
                           (fresh['title'],fresh['kind'],showkey(fresh),json.dumps(fresh),row['id'])).rowcount
    return changed,(rows[-1]['id'] if rows else None)

def seed(row):
    title=cleaned(row.get('title'));topic=cleaned(row.get('topic'));desc=core.clean(row.get('description',''));m=core.identify({**row,'title':title})
    ep=EP.search(title);reihe=portal_series(topic,title)
    if m['kind']=='series' and topic and not ep and key(m['title'])==key(topic):
        # 0.6.87: core.identify names the topic as series when the text says „Serie“; a subject or section topic
        # („Doku“, „Sport“, „Serien“) is no series – the numbered part of the title may be one.
        import metadata
        if metadata.generic_topic(topic):
            part=metadata.part_series(title)
            if part and not metadata.generic_topic(part):m.update(title=part)
            else:m.update(kind='unknown',title=title,episode_title='')
    if reihe:
        # 0.6.78: Planet Schule names the series after the dot ("Das schnelle Pendel · Achtung! Experiment").
        m.update(kind='series',year=None,title=reihe[1],episode_title=reihe[0])
        if ep:
            nums=[int(x) for x in ep.groups() if x is not None]
            m.update(season=nums[0],episode=nums[1])
    elif ep:
        nums=[int(x) for x in ep.groups() if x is not None]
        m.update(kind='series',year=None,season=nums[0],episode=nums[1],title=topic or EP.sub('',title).strip(' ()-'),episode_title=title)
    elif key(topic) in ('tatort','polizeiruf 110'):m.update(kind='series',title=topic,episode_title=title,year=None)
    if m['kind']=='unknown':
        intro=topic+' '+re.sub(r'(?i)\b(?:drama|thriller|western)\b','',desc[:220])
        if re.search(r'(?i)\b(?:spielfilm|fernsehfilm|komödie|thriller|drama|western|liebesfilm|dokumentarfilm)\b',intro):m['kind']='movie'
        elif re.search(r'(?i)\b(?:serie|serien|sitcom|dokumentarserie|fernsehserie|krimiserie)\b',intro):
            import metadata
            if topic and metadata.generic_topic(topic):
                # 0.6.49: "Fernsehfilme und Serien - Serien" (SRF, 830 works), "Serie e fiction - Serie" (ARTE) name
                # a section, not the series: 4,600 checks in one afternoon for the section name found nothing.
                part=metadata.part_series(title)
                if part and not metadata.generic_topic(part):m.update(kind='series',title=part,episode_title=title)
            else:m.update(kind='series',title=topic or title,episode_title=title)
        elif re.search(r'(?i)\b(?:nachrichten|tagesschau|wetter|sportstudio|trailer|teaser|podcast|pressekonferenz|tagesthemen|gottesdienst|magazin)\b',topic+' '+title):m['kind']='other'
    if re.search(r'(?i)^\s*(?:trailer|teaser|vorschau)\b',title):m.update(kind='other',title=title,year=None,season=None,episode=None)
    if m['kind']=='movie' and not m.get('year'):
        y=re.search(r'\((19\d{2}|20\d{2})\)$',title)
        if y:m.update(year=int(y.group(1)),title=title[:y.start()].strip())
    genre_hint=topic
    # Narrative words such as 'Drama beim Fußball' are not genre labels.
    if re.match(r'(?i)^(?:Drama|Thriller|Komödie|Dokumentarfilm|Krimi|Science-Fiction|Fantasy|Animation)\s*(?:[.,|:·]|(?:Deutschland|Frankreich|USA|Großbritannien|Österreich|Schweiz)\b|(?:19|20)\d{2}\b)',desc):genre_hint+=' '+desc[:100]
    m['genres']=[g for g,rx in GENRES.items() if re.search(rx,genre_hint,re.I)]
    m.update(genre_source='Senderhinweis' if m['genres'] else 'Unbekannt',title=cleaned(m['title']),episode_title=cleaned(m.get('episode_title','')))
    import video_causality
    role=video_causality.explicit_format(row)
    if role:
        # Keep the programme name as a relation, not as a verified full episode.
        if topic:m['related_series_title']=topic
        m.update(role,kind='other',title=title,episode_verified=False,
                 season=None,episode=None,episode_reference_id=None)
    return m

def mark_explicit_extra(c,w,source):
    """Safely repair an earlier automatic series recognition of a trailer/clip.

    Only provisional automatic states may change. Never undo a user decision
    or replace a verified downloaded episode without review.
    """
    if not w or w['state'] in ('manual','matched'):return False
    import video_causality
    role=video_causality.explicit_format(source)
    if not role:return False
    m=json.loads(w['meta'] or '{}')
    if source.get('topic'):m['related_series_title']=source['topic']
    m.update(role,kind='other',title=cleaned(source.get('title')) or m['title'],
             episode_verified=False,season=None,episode=None,episode_reference_id=None,
             reason='Kurzformat ausdrücklich im Sendertitel gekennzeichnet; keine vollständige Folge')
    c.execute("""UPDATE works SET title=?,kind='other',show_key=?,meta=?,state='format',
        next_try=0 WHERE id=?""",(m['title'],showkey(m),json.dumps(m),w['id']))
    return True


def origin_meta(c,row):
    """Seed metadata of an offer as on import (including a unique series template) and the template used."""
    m=seed(row);template=None
    if m['kind'] in ('unknown','series') and 300<=int(row.get('duration') or 0)<=3900 and template_topic(row.get('topic'),cleaned(row.get('title'))):
        options=c.execute('SELECT meta FROM series_templates WHERE topic=? LIMIT 2',(key(row.get('topic')),)).fetchall()
        if len(options)==1:template=json.loads(options[0][0])
    if template and not m.get('video_role'):
        m.update(kind='series',episode_title=m.get('episode_title') or row['title'])
        for k in ('title','year','provider','reference_id','poster','genres','genre_source','reference_runtime_seconds'):m[k]=template.get(k)
        m['genres']=normalized_genres(m.get('genres'))
    return m,template

def heal_missing_topics(c,limit=2000):
    """Once (merker topic_heal_v0692): works that lost their topic on a move to the canonical ID take it back
    from their best offer. One batch per call, cursor in topic_heal_cursor. Returns (healed, done)."""
    if get_state(c,'topic_heal_v0692',False):return 0,True
    after=int(get_state(c,'topic_heal_cursor',0) or 0)
    rows=c.execute("""SELECT w.rowid,w.id,(SELECT json_extract(o.payload,'$.topic') FROM offers o WHERE o.work_id=w.id
          ORDER BY o.active DESC,o.rank DESC LIMIT 1) t FROM works w
        WHERE w.rowid>? AND COALESCE(w.topic,'')='' ORDER BY w.rowid LIMIT ?""",(after,limit)).fetchall()
    todo=[(r[2],r[1]) for r in rows if r[2]]
    c.executemany('UPDATE works SET topic=? WHERE id=?',todo)
    if len(rows)<limit:
        set_state(c,'topic_heal_v0692',{'at':time.time()});return len(todo),True
    set_state(c,'topic_heal_cursor',rows[-1][0])
    return len(todo),False

def defer_sender_siblings(c,topic,work_id,providers,until):
    """0.6.89: works of the same Reihe (topic) that wait only for the same broadcaster wait until its allowance
    renews (``until``, spread over 30 min) instead of asking again one by one. Works never checked and works
    with other open providers stay as they are. Returns the number postponed."""
    if not topic or not providers:return 0
    marks=','.join('?'*len(providers))
    return max(0,c.execute("""UPDATE works SET next_try=?+abs(random())%1800 WHERE topic=? AND id!=? AND state='retry' AND next_try<?
        AND json_type(meta,'$.deferred_providers')='array'
        AND NOT EXISTS(SELECT 1 FROM json_each(works.meta,'$.deferred_providers') d WHERE d.value NOT IN ("""+marks+"""))
        AND COALESCE(json_array_length(meta,'$.metadata_warnings'),0)=0""",
        (float(until),topic,work_id,float(until),*providers)).rowcount)

def series_template_candidate(c,row,source):
    """Get a uniquely verified series identity already learned from another episode.

    Never transfer another episode's season/number, verification flag or description.
    """
    topic=source.get('topic') or ''
    if row['kind'] not in ('unknown','series') or not topic:return None
    import video_causality
    if video_causality.explicit_format(source):return None
    if not 300<=int(source.get('duration') or 0)<=3900:return None
    if key(topic)==key(source.get('title')):return None
    if not template_topic(topic,cleaned(source.get('title'))):return None
    templates=c.execute('SELECT meta FROM series_templates WHERE topic=? LIMIT 2',(key(topic),)).fetchall()
    if len(templates)!=1:return None
    known=json.loads(templates[0][0])
    if known.get('kind')!='series' or key(known.get('title'))!=key(topic):return None
    if not known.get('reference_id') or not known.get('provider'):return None
    own=json.loads(row['meta'])
    if own.get('year') and known.get('year') and own['year']!=known['year']:return None
    for k in ('title','year','provider','reference_id','poster','genres','genre_source','show_description','reference_runtime_seconds'):
        if k in known:own[k]=known[k]
    own['kind']='series'
    own['episode_title']=own.get('episode_title') or source.get('title') or ''
    # Only one known series identity is shared; episode evidence remains offer-specific.
    own['episode_verified']=False
    own.pop('episode_reference_id',None)
    own['reason']='Serienidentität aus bereits bestätigter Folge übernommen; Episode noch zu prüfen'
    return own

def origin_ids(c,work_id):
    """Work IDs the offers of a (possibly merged) work had on import; the same on every instance."""
    out=set()
    for (payload,) in c.execute('SELECT payload FROM offers WHERE work_id=?',(work_id,)).fetchall():
        row=json.loads(payload)
        try:out.add(identity(row,origin_meta(c,row)[0]))
        except (KeyError,TypeError,ValueError):continue
    return sorted(out) or [work_id]

def identity(row,m):
    base=m['kind']+'|'+key(m['title'])+'|'+str(m.get('year') or '?')
    if m['kind']=='series':
        ep='s%s-e%s'%(m['season'],m['episode']) if m.get('season') is not None and m.get('episode') is not None else key(m.get('episode_title') or row['title'])
        return digest(base+'|'+ep)
    if m.get('year'):return digest(base)
    desc=key(row.get('description'))[:180]
    evidence=desc if len(desc)>45 else str(row.get('url_website') or row.get('url_video') or row.get('_id'))
    return digest(base+'|'+evidence)
def showkey(m):return digest(key(m['title'])+'|'+str(m.get('year') or '?')) if m['kind']=='series' else ''
def set_state(c,k,v):c.execute('INSERT OR REPLACE INTO catalog_state VALUES(?,?)',(k,json.dumps(v)))
def get_state(c,k,default=None):
    r=c.execute('SELECT value FROM catalog_state WHERE key=?',(k,)).fetchone();return json.loads(r[0]) if r else default

def ingest(c,rows,seen=None):
    seen=time.time() if seen is None else seen;ids=[]
    for raw in rows:
        row=dict(raw)
        if not links(row) or not row.get('title'):continue
        oid=digest(str(row.get('channel'))+'|'+str(row.get('url_video') or row.get('url_video_hd') or row.get('url_website'))+'|'+row['title']);row['_id']=oid
        m,template=origin_meta(c,row)
        wid=identity(row,m)
        old=c.execute('SELECT work_id FROM offers WHERE id=?',(oid,)).fetchone()
        if old:wid=old[0]
        cur=c.execute('INSERT OR IGNORE INTO works(id,title,kind,year,show_key,meta,updated) VALUES(?,?,?,?,?,?,?)',(wid,m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),seen))
        if cur.rowcount:update_film_hint(c,wid,m,row)
        c.execute('UPDATE works SET topic=? WHERE id=?',(row.get('topic',''),wid))
        if cur.rowcount:
            if m.get('video_role'):
                # Distinct extra, neither a series episode nor a movie match.
                c.execute("UPDATE works SET state='format' WHERE id=?",(wid,))
            elif template:c.execute("UPDATE works SET state='identified' WHERE id=?",(wid,))
            for genre in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,genre))
        if str(row.get('topic') or '').strip() in LIVE_TOPICS:mark_live(c,wid)
        c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,special=excluded.special,rank=excluded.rank,seen=excluded.seen,active=1',(oid,wid,json.dumps(row),special(row),ranking(row),seen));ids.append(oid)
    return ids

LIVE_TOPICS=('Livestream','Livestreams','livestream','LIVESTREAM','Live-Stream')

def mark_live(c,wid=None):
    """Broadcaster live streams (topic "Livestream", 0.5.50) are no works: shown in the Live-TV tab,
    never sent to TMDB/TVDB/IMDb. Manual and confirmed decisions stay untouched."""
    sql=("UPDATE works SET kind='other',state='format',next_try=0,meta=json_set(COALESCE(NULLIF(meta,''),'{}'),"
         "'$.kind','other','$.live',json('true'),'$.reason','Livestream des Senders; erscheint im Reiter Live-TV und wird nicht abgeglichen.') "
         "WHERE topic IN (%s) AND state NOT IN ('manual','matched','format')"%','.join('?'*len(LIVE_TOPICS)))
    args=list(LIVE_TOPICS)
    if wid is not None:sql+=' AND id=?';args.append(wid)
    return c.execute(sql,args).rowcount

def begin_snapshot(c):
    """Collect feed IDs separately: an interrupted import must never retire existing offers."""
    c.execute('DELETE FROM scan_seen')

def ingest_incremental(c,rows,seen,changes):
    """Only changed/new offers need full seed, classification and payload writes.

    Stable IDs use channel, primary media URL and title exactly as in ingest().
    Identical offers are recorded in scan_seen without rewriting works or offers.
    """
    dirty=get_state(c,'format_cursor')=='complete'
    for row in rows:
        if not links(row) or not row.get('title'):continue
        oid=digest(str(row.get('channel'))+'|'+str(row.get('url_video') or row.get('url_video_hd') or row.get('url_website'))+'|'+row['title'])
        payload=json.dumps({**row,'_id':oid})
        old=c.execute('SELECT payload,active FROM offers WHERE id=?',(oid,)).fetchone()
        c.execute('INSERT OR IGNORE INTO scan_seen VALUES(?)',(oid,))
        if old and old['payload']==payload:
            category='unchanged' if old['active'] else 'reactivated'
            changes[category]=changes.get(category,0)+1
            continue
        if old:category='changed' if old['active'] else 'reactivated'
        else:category='added'
        changes[category]=changes.get(category,0)+1
        ingest(c,[row],seen)
        if dirty:
            c.execute('INSERT OR IGNORE INTO format_dirty SELECT work_id FROM offers WHERE id=?',(oid,))

def finish_snapshot(c,seen,changes):
    """Deactivate missing IDs only after the complete list was parsed successfully."""
    changes=dict(changes)
    retired=c.execute('UPDATE offers SET active=0 WHERE active=1 AND NOT EXISTS(SELECT 1 FROM scan_seen s WHERE s.id=offers.id)')
    changes['removed']=retired.rowcount
    c.execute('UPDATE offers SET active=1,seen=? WHERE active=0 AND EXISTS(SELECT 1 FROM scan_seen s WHERE s.id=offers.id)',(seen,))
    c.execute('DELETE FROM scan_seen')
    set_state(c,'last_import_diff',changes)
    return changes

def offer_expiry(c,oid):
    r=c.execute('SELECT available_until,source,checked FROM offer_availability WHERE offer_id=?',(oid,)).fetchone()
    return {'available_until':r[0],'availability_source':r[1],'availability_checked_at':r[2]} if r and r[0] else {}

def source(c,oid):
    r=c.execute('SELECT payload FROM offers WHERE id=?',(oid,)).fetchone()
    if not r:return None
    row=json.loads(r[0]);row.update(offer_expiry(c,oid));return row

def download_identity(m):
    return canonical(m) or digest(json.dumps([m.get('kind'),key(m.get('title','')),m.get('year'),m.get('season'),m.get('episode')]))

def mark_downloaded(c,job):
    invalidate_listings()
    identities={download_identity(job['metadata'])}
    source_id=job.get('source',{}).get('_id')
    found=c.execute('SELECT work_id FROM offers WHERE id=?',(source_id,)).fetchone()
    if found:identities.add(found[0])
    path=job.get('path') or job.get('target') or ''
    # A stale completed job may be replayed at startup after the user has moved
    # and re-linked the movie. Never replace an existing usable link with an
    # older path that cannot be found. Preserve unavailable references as well
    # until a verified replacement exists.
    from pathlib import Path
    try:valid=bool(path and Path(path).is_file())
    except OSError:valid=False
    for identity in identities:
        previous=c.execute('SELECT path FROM downloaded_items WHERE identity=?',(identity,)).fetchone()
        if previous and previous[0] and previous[0]!=path and not valid:continue
        c.execute('INSERT OR REPLACE INTO downloaded_items VALUES(?,?,?)',(identity,path,time.time()))

def mesh_download_row(c,meta,work_id=None):
    """Latest Verbund download record for a title: by download identity, else by the sender's work IDs."""
    r=c.execute('SELECT * FROM mesh_downloads WHERE key=?',(download_identity(meta),)).fetchone()
    if not r and work_id:r=c.execute('SELECT d.* FROM mesh_download_works w JOIN mesh_downloads d ON d.key=w.key WHERE w.work_id=?',(work_id,)).fetchone()
    return r

def mesh_download(c,meta,work_id=None):
    """Download state of this title on another instance of the Verbund, or None."""
    r=mesh_download_row(c,meta,work_id)
    r=r and (r['node'],r['name'],r['state'],r['until'],r['path'],r['local'])
    if not r or r[0]==get_state(c,'mesh_node_id') or r[2]=='release' or (r[2]=='claim' and r[3]<time.time()):return None
    return {'name':r[1],'state':'loading' if r[2]=='claim' else 'local' if r[5] else 'transfer' if r[4] else 'remote'}

def item(c,w):
    # A canonical merge may remove a work between listing and the detail query.
    # Treat that as an absent row, never turn a routine refresh into HTTP 500.
    if w is None:return None
    r=c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC LIMIT 1',(w['id'],)).fetchone()
    if not r:return None
    row=json.loads(r['payload']);row.update(offer_expiry(c,r['id']));count=c.execute('SELECT COUNT(*) FROM offers WHERE work_id=?',(w['id'],)).fetchone()[0]
    saved=c.execute('SELECT path FROM downloaded_items WHERE identity=?',(w['id'],)).fetchone()
    file_state=None
    if saved:
        import local_library
        file_state=local_library.file_state(saved['path'])
    meta=json.loads(w['meta'])
    import categories
    checked=bool(w['attempts']) or w['state'] in ('matched','manual','identified','review','format')
    # 0.6.5: audio/subtitle languages of all listed versions (regular, OmU, ARTE.FR …) of this work
    versions=[(o['id'],json.loads(o['payload'])) for o in c.execute('SELECT id,payload FROM offers WHERE work_id=? AND active=1 LIMIT 40',(w['id'],))] or [(r['id'],row)]
    import languages
    try:langs=languages.for_mediathek(None,versions,meta)
    except Exception:langs=None
    return {'id':r['id'],'work_id':w['id'],'source':row,'metadata':meta,'categories':categories.classify((),meta.get('genres') or [],checked),'offer_count':count,'languages':langs,'available':bool(r['active']),'state':w['state'],'downloaded':bool(saved),'file_state':file_state,'mesh_download':mesh_download(c,json.loads(w['meta']),w['id']),'special':r['special'],'best':links(row)[0] if links(row) else None,'show_key':w['show_key'],'links':links(row)}

def media_equivalence_key(row,special_kind='',active=True):
    """Exact playable media identity; do not strip signed URL query strings.

    Different accessibility editions, subtitles, timing, channel, or any
    playable rendition are never collapsed just because both say 'ARD HD'.
    """
    media=tuple((field,str(row.get(field) or '')) for field in
                ('url_video','url_video_hd','url_video_low','url_subtitle'))
    if not any(value for field,value in media if field!='url_subtitle'):return None
    return (row.get('channel',''),special_kind,active,int(row.get('duration') or 0),
            media)

def alternatives(c,wid):
    w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    if not w:raise ValueError('Werk nicht gefunden')
    out=[];by_media={}
    meta=json.loads(w['meta'])
    for r in c.execute('SELECT * FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC,seen DESC',(wid,)):
        row=json.loads(r['payload']);row.update(offer_expiry(c,r['id']))
        active=bool(r['active'])
        key_=media_equivalence_key(row,r['special'],active)
        if key_ is not None and key_ in by_media:
            entry=out[by_media[key_]]
            entry['same_media_count']+=1
            entry['offer_ids'].append(r['id'])
            continue
        entry={'id':r['id'],'work_id':wid,'source':row,'metadata':meta,
               'special':r['special'],'available':active,'links':links(row),
               'same_media_count':1,'offer_ids':[r['id']]}
        if key_ is not None:by_media[key_]=len(out)
        out.append(entry)
    return out

SHOW_FIELDS=('title','year','kind','provider','reference_id','imdb_id','poster','fanart','genres','genre_source','rating','votes','rating_source','ratings','networks','studios','show_credits','artwork_provider','show_description')
STATE_ORDER={'manual':0,'matched':1,'identified':2,'review':3,'retry':4,'pending':5,'format':6}

def series_credits_from_works(metas,limit=40):
    """Series credits assembled from the works' own cast/directors/writers (0.6.57)."""
    from collections import Counter
    out={}
    for field,cap in (('cast',limit),('directors',8),('writers',8)):
        count=Counter();first={}
        for i,m in enumerate(metas):
            seen=set()
            for p in m.get(field) or []:
                name=' '.join(str((p.get('name') if isinstance(p,dict) else p) or '').split())[:120]
                if not name or name in seen:continue
                seen.add(name);count[name]+=1
                if name not in first:first[name]=(i,{})
                if isinstance(p,dict):
                    for k in ('role','imdb_id'):
                        if isinstance(p.get(k),str) and p[k] and k not in first[name][1]:first[name][1][k]=p[k]
        names=sorted(count,key=lambda n:(-count[n],first[n][0]))[:cap]
        if not names:continue
        if field=='cast':
            out[field]=[{'name':n,**first[n][1]} for n in names]
        else:out[field]=names
    if out:out['source']='works'
    return out

def show_detail(c,show,archive=False,limit=1000):
    """Series page: show-level metadata assembled from its episodes plus all episodes by season.

    Episode descriptions are never used as series description; only a provider series overview
    (show_description) or, for broadcaster series, the Sendereihe text (series_description).
    """
    if not show:raise ValueError('Serie fehlt')
    where='w.show_key=?'+('' if archive else ' AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)')
    rows=c.execute('SELECT w.* FROM works w WHERE '+where,(show,)).fetchall()
    if not rows:raise ValueError('Serie nicht gefunden')
    metas=[(r,json.loads(r['meta'])) for r in rows]
    ranked=sorted(metas,key=lambda x:(STATE_ORDER.get(x[0]['state'],9),not x[1].get('poster'),not x[1].get('fanart')))
    summary={'show_key':show}
    for field in SHOW_FIELDS:
        for _,m in ranked:
            v=m.get(field)
            if v not in (None,'',[],{}):summary[field]=v;break
    credits=summary.get('show_credits')
    if not isinstance(credits,dict) or not (credits.get('cast') or credits.get('directors')):
        # 0.6.57 (Mac check of 0.6.55, "Der Pass", TMDB 85526): without series credits the page fell silent although
        # the works carry cast and directors. People named in most works come first (regulars before guests).
        fallback=series_credits_from_works([m for _,m in ranked])
        if fallback:summary['show_credits']=fallback
    if not summary.get('show_description'):
        # Broadcaster series carry the Sendereihe text on each episode; the most frequent one wins.
        from collections import Counter
        texts=Counter((m.get('series_description') or '').strip() for _,m in metas);texts.pop('',None)
        if texts:summary['show_description']=texts.most_common(1)[0][0]
    def order(x):
        m=x[1];return (m.get('season') if m.get('season') is not None else 99999,m.get('episode') if m.get('episode') is not None else 99999,m.get('episode_title',''))
    episodes=[];seasons={};channels=set()
    for w,m in sorted(metas,key=order)[:limit]:
        entry=item(c,w)
        if not entry:continue
        entry.update(episodes=1,series_parent=False);episodes.append(entry)
        season=m.get('season') if isinstance(m.get('season'),int) else None
        seasons.setdefault(season,0);seasons[season]+=1
    for (payload,) in c.execute('SELECT o.payload FROM offers o JOIN works w ON w.id=o.work_id WHERE '+where+('' if archive else ' AND o.active=1'),(show,)):
        channel=json.loads(payload).get('channel')
        if channel:channels.add(channel)
    import languages
    summary['languages']=languages.combine([e.get('languages') for e in episodes])   # 0.6.5
    summary.update(state=ranked[0][0]['state'],episode_count=len(rows),downloaded=sum(1 for e in episodes if e['downloaded']),available=sum(1 for e in episodes if e['available']),
                   channels=sorted(channels),seasons=[{'season':k,'episodes':v} for k,v in sorted(seasons.items(),key=lambda kv:(kv[0] is None,kv[0] or 0))],truncated=len(rows)>limit)
    return {'show':summary,'episodes':episodes,'work_ids':[w['id'] for w,_ in ranked[:48]]}

# 0.5.55: grouped catalogue pages from memory. Björn's diagnosis (12.11.2026): /api/catalog took
# 7-31 s on every call (239 times in six hours) because each page grouped and sorted all ~680,000
# works again. The grouped order per filter is now computed once, served from memory and renewed
# in the background (stale-while-revalidate), so paging and returning to the view are immediate.
LISTING_DB=None            # set by the server: context-manager factory for background refreshes
LISTING_TTL=600.0
LISTING_SEARCH_TTL=120.0
LISTING_SLOW=1.5             # seconds: from here on an outdated page is served while it is renewed
_LISTING_MAX=32
_LISTING={}                # key -> {'rows':[(id,episodes)],'built':monotonic,'busy':bool,'used':monotonic}
_LISTING_LOCK=threading.Lock()
_LISTING_BUILD=threading.Lock()   # one heavy aggregation at a time
_LISTING_STATS={'hits':0,'builds':0,'background':0,'last_seconds':0.0,'restored':0,'pending':0}
# 0.5.57: the slow aggregations survive a restart. Björn (12.11.2026): after the start the
# catalogues took very long. Every start grouped the whole catalogue again before the first
# page could be shown. The last result is now read from this file, shown at once and renewed
# in the background.
LISTING_FILE=None          # set by the server through load_listings()
LISTING_WAIT=0.6           # seconds a caller with wait=False gives a first aggregation
_LISTING_KEEP=6
_LISTING_QUEUED={}         # key -> Event, first aggregations running in the background
_LISTING_FAILED={}         # key -> (monotonic, exception) of a failed background aggregation

class ListingPending(Exception):
    """The grouped list is being computed in the background; ask again in a moment."""

def _listing_build(c,where,args,grouping,order):
    started=time.monotonic()
    base='SELECT MIN(w.id) AS id,COUNT(*) AS episodes FROM works w WHERE '+where+' GROUP BY '+grouping
    rows=[(r[0],r[1],r[2],r[3]) for r in c.execute('SELECT g.id,g.episodes,w.title,w.year FROM ('+base+') g JOIN works w ON w.id=g.id ORDER BY '+order,args)]
    seconds=time.monotonic()-started
    _LISTING_STATS['builds']+=1;_LISTING_STATS['last_seconds']=round(seconds,2)
    return rows,seconds

def _listing_persist():
    path=LISTING_FILE
    if path is None:return
    with _LISTING_LOCK:
        keep=sorted(((k,e) for k,e in _LISTING.items() if e['seconds']>=LISTING_SLOW and not e.get('search')),key=lambda ke:-ke[1]['used'])[:_LISTING_KEEP]
        data=[{'key':[k[0],list(k[1]),k[2],k[3]],'rows':e['rows'],'seconds':e['seconds']} for k,e in keep]
    try:
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'version':1,'saved':time.time(),'entries':data},separators=(',',':')),encoding='utf-8');tmp.replace(path)
    except OSError:pass   # only the next start is slower

def load_listings(path):
    """Read the lists of the last run. They count as outdated: shown at once, renewed on first use."""
    global LISTING_FILE
    from pathlib import Path
    LISTING_FILE=Path(path)
    try:stored=json.loads(LISTING_FILE.read_text(encoding='utf-8'))
    except (OSError,ValueError):return 0
    count=0;now=time.monotonic()
    if not isinstance(stored,dict) or stored.get('version')!=1:return 0
    with _LISTING_LOCK:
        for entry in stored.get('entries') or []:
            try:
                where,args,grouping,order=entry['key'];rows=[(str(r[0]),int(r[1]),r[2],r[3]) for r in entry['rows']]
                _LISTING[(where,tuple(args),grouping,order)]={'rows':rows,'built':float('-inf'),'busy':False,'used':now,'seconds':max(float(entry.get('seconds') or 0),LISTING_SLOW),'search':False}
                count+=1
            except (KeyError,TypeError,ValueError,IndexError):continue
    _LISTING_STATS['restored']=count
    return count

def _listing_store(key,rows,seconds,search=False):
    now=time.monotonic()
    with _LISTING_LOCK:
        _LISTING[key]={'rows':rows,'built':now,'busy':False,'used':now,'seconds':seconds,'search':search}
        while len(_LISTING)>_LISTING_MAX:
            _LISTING.pop(min(_LISTING,key=lambda k:_LISTING[k]['used']))
    if seconds>=LISTING_SLOW and not search:_listing_persist()

def _listing_refresh(key,where,args,grouping,order,search=False):
    try:
        with _LISTING_BUILD:
            with LISTING_DB() as c:rows,seconds=_listing_build(c,where,args,grouping,order)
        _listing_store(key,rows,seconds,search);_LISTING_STATS['background']+=1
    except Exception as exc:
        with _LISTING_LOCK:
            if key in _LISTING:_LISTING[key]['busy']=False
            _LISTING_FAILED[key]=(time.monotonic(),exc)   # shown to a caller that does not wait
            while len(_LISTING_FAILED)>_LISTING_MAX:_LISTING_FAILED.pop(next(iter(_LISTING_FAILED)))
    finally:
        with _LISTING_LOCK:done=_LISTING_QUEUED.pop(key,None)
        if done:done.set()

def _listing_groups(c,where,args,grouping,order,search=False,wait=True):
    # Without a server (tests, tools) every call reads the database directly.
    if LISTING_DB is None:return _listing_build(c,where,args,grouping,order)[0]
    key=(where,tuple(args),grouping,order);now=time.monotonic()
    with _LISTING_LOCK:
        entry=_LISTING.get(key)
        if entry:
            entry['used']=now;age=now-entry['built']
            if age<=(LISTING_SEARCH_TTL if search else LISTING_TTL):
                _LISTING_STATS['hits']+=1;return entry['rows']
            # Outdated: quick aggregations are simply repeated, slow ones answer from memory
            # at once and are renewed in the background.
            if entry['seconds']>=LISTING_SLOW:
                if not entry['busy']:
                    entry['busy']=True
                    threading.Thread(target=_listing_refresh,args=(key,where,list(args),grouping,order,search),daemon=True,name='catalog_listing_refresh').start()
                _LISTING_STATS['hits']+=1;return entry['rows']
        if not wait:
            failed=_LISTING_FAILED.get(key)
            if failed and now-failed[0]<=30:raise failed[1]   # do not repeat a failing aggregation at once
            # The caller (merged dashboard) shows the other sources first: compute in the
            # background, give a quick aggregation a moment, otherwise report "pending".
            done=_LISTING_QUEUED.get(key)
            if done is None:
                done=_LISTING_QUEUED[key]=threading.Event()
                threading.Thread(target=_listing_refresh,args=(key,where,list(args),grouping,order,search),daemon=True,name='catalog_listing_first').start()
    if not wait:
        done.wait(LISTING_WAIT)
        with _LISTING_LOCK:
            entry=_LISTING.get(key)
            if entry:return entry['rows']   # new, or the outdated one while the new one is computed
            failed=_LISTING_FAILED.get(key)
        if failed and failed[0]>=now:raise failed[1]
        _LISTING_STATS['pending']+=1
        raise ListingPending()
    with _LISTING_BUILD:
        with _LISTING_LOCK:
            entry=_LISTING.get(key)
            if entry and entry['built']>now:return entry['rows']   # built while waiting
        rows,seconds=_listing_build(c,where,args,grouping,order)
    _listing_store(key,rows,seconds,search)
    return rows

def invalidate_listings(drop=False):
    """After an import, a download or a manual change: renew on next use. Slow aggregations keep
    answering from memory while they are renewed in the background."""
    if drop:
        import languages
        languages.forget_filters()   # 0.6.5: language filter of the unified catalogue
    with _LISTING_LOCK:
        _LISTING_FAILED.clear()
        if drop:_LISTING.clear()
        else:
            for entry in _LISTING.values():entry['built']=float('-inf')

def listing_cache_stats():
    with _LISTING_LOCK:return {**_LISTING_STATS,'entries':len(_LISTING)}


def listing(c,query='',kind='',genre='',show='',offset=0,archive=False,state='',sort='title',downloaded='hide',collection='',index_only=False,wait=True):
    clauses=[];args=[]
    if downloaded=='hide':clauses.append('NOT EXISTS(SELECT 1 FROM downloaded_items di WHERE di.identity=w.id)')
    elif downloaded=='only':clauses.append('EXISTS(SELECT 1 FROM downloaded_items di WHERE di.identity=w.id)')
    if not archive:clauses.append('EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)')
    if collection in ('cinema','series'):
        clauses.append("w.kind=? AND w.state IN ('matched','manual','identified') AND CAST(json_extract(w.meta,'$.rating') AS REAL)>=7.5 AND CAST(json_extract(w.meta,'$.rating') AS REAL)<=10 AND ((COALESCE(json_extract(w.meta,'$.rating_source'),json_extract(w.meta,'$.provider')) IN ('IMDb','IMDb Offline','OMDb') AND CAST(json_extract(w.meta,'$.votes') AS INTEGER)>=10000) OR (json_extract(w.meta,'$.rating_source')='TMDB' AND CAST(json_extract(w.meta,'$.votes') AS INTEGER)>=1000))")
        args.append('movie' if collection=='cinema' else 'series')
    if kind:clauses.append('w.kind=?');args.append(kind)
    elif not query and not state:clauses.append("w.kind IN ('movie','series')")
    if state=='recognized':clauses.append("w.state IN ('matched','manual','identified')")
    elif state=='pending':clauses.append("w.state IN ('pending','retry')")
    elif state=='review':clauses.append("w.state='review'")
    elif state=='format':clauses.append("w.state='format'")
    if query:clauses.append('(w.title LIKE ? OR w.topic LIKE ?)');args.extend(['%'+query[:150]+'%']*2)
    if genre:
        clause,values=category_clause(c,genre)
        clauses.append(clause);args.extend(values)
    if show:clauses.append('w.show_key=?');args.append(show)
    where=' AND '.join(clauses);offset=max(0,int(offset));grouping="CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END" if not show else 'w.id'
    if show:
        rows=c.execute('SELECT w.* FROM works w WHERE '+where,args).fetchall()
        def episode_order(w):
            m=json.loads(w['meta']);return (m.get('season') if m.get('season') is not None else 99999,m.get('episode') if m.get('episode') is not None else 99999,m.get('episode_title',''))
        rows.sort(key=episode_order);out=[]
        for w in rows[offset:offset+48]:
            entry=item(c,w)
            if entry:entry.update(episodes=1,series_parent=False);out.append(entry)
        return {'items':out,'total':len(rows),'offset':offset}
    order={'title':'w.title COLLATE NOCASE','year':'w.year DESC,w.title COLLATE NOCASE','recognized':"CASE WHEN w.state IN ('manual','matched') THEN 0 WHEN w.state='identified' THEN 1 ELSE 2 END,w.title COLLATE NOCASE"}.get(sort,'w.title COLLATE NOCASE')
    groups=_listing_groups(c,where,args,grouping,order,bool(query),wait)
    if index_only:return groups   # (id, episodes, title, year) of every group, for unified_index
    total=len(groups);rows=[{'id':r[0],'episodes':r[1]} for r in groups[offset:offset+48]];out=[]
    for row in rows:
        w=c.execute('SELECT * FROM works WHERE id=?',(row['id'],)).fetchone()
        if w is None:continue  # merged by another worker after the paged query
        entry=item(c,w)
        if entry:entry.update(episodes=row['episodes'],series_parent=w['kind']=='series' and not show);out.append(entry)
    return {'items':out,'total':total,'offset':offset}

# 0.5.83: a work counts as classified once the reference check ran (attempts) or produced a state.
# Before that it is listed under categories.UNCLASSIFIED, regardless of the broadcaster's labels.
CLASSIFIED_SQL="(w.attempts>0 OR w.state IN ('matched','manual','identified','review','format'))"

# 0.6.91 (Björn, 22.11.2026: „ich sehe keine Märchen etc. die schon erkannt wurden“): a recognized film carries
# only the reference genres. IMDb has no „Kinder“ genre – a Märchenfilm of „Sechs auf einen Streich“ is
# „Family, Fantasy“ there – so it never reached the Kinder category although the broadcaster files it as
# children's programme. The kids channel or a kids/Märchen topic of an active offer now counts as a clear signal.
# Merged works lose works.topic (a new id), so the signal is read from the offers, which move with the work.
# 0.6.106 (Mac-Prüfung 0.6.105: „Generation Porno - Was unsere Kinder online sehen“, „Die Kinder von Lügde“, „Geheimsache
# Doping: Kinder“, „Ein Herz für Kinder“ in der Kinderecke): das Wort „Kinder“ oder „für Kinder“ in einem Reihen- oder
# Themennamen ist nie ein Signal, auch kein allgemeines „Märchen“. Nur die gepflegte Liste bekannter Kinderreihen
# (categories.KNOWN_KIDS_SERIES, eine Liste für Sender-Genre, Themensignal und Kinderecke) und die Kindersender zählen.
import categories as _categories
KIDS_SHOWS=_categories.KNOWN_KIDS_SERIES
KIDS_TOPIC=re.compile(r'(?i)'+KIDS_SHOWS)
KIDS_SIGNAL_TTL=3600.0
_KIDS_SIGNAL={}            # database file -> (monotonic, topics)
_KIDS_SIGNAL_LOCK=threading.Lock()

def kids_topics(c):
    """Topics (Sendereihen) of active offers that name children's programme (cached one hour)."""
    try:path=c.execute('PRAGMA database_list').fetchone()[2] or ':memory:'
    except Exception:path=':memory:'
    now=time.monotonic()
    with _KIDS_SIGNAL_LOCK:
        hit=_KIDS_SIGNAL.get(path)
        if hit and now-hit[0]<=KIDS_SIGNAL_TTL and path!=':memory:':return hit[1]
    # The offers, not works.topic: a recognized work moved to its canonical id keeps no topic, and a Reihe whose films
    # are all recognized (Sechs auf einen Streich) would vanish. One read of the offers per hour (~1 s per 600,000).
    topics=sorted({t for (t,) in c.execute("SELECT DISTINCT json_extract(payload,'$.topic') FROM offers WHERE active=1")
                   if isinstance(t,str) and t and len(t)<=200 and KIDS_TOPIC.search(t)})[:5000]
    with _KIDS_SIGNAL_LOCK:_KIDS_SIGNAL[path]=(now,topics)
    return topics

# 0.6.106 (Durchsicht Kinderecke 22.11.): Sendungs-Ablagen (state 'format') zählen nur über das Angebot – Kindersender
# oder ein Thema aus dieser schmalen Liste –, nie über ein abgeleitetes Genre oder „… für Kinder“ im Namen.
FORMAT_KIDS_TOPIC=KIDS_TOPIC     # seit der gemeinsamen Liste dieselbe Menge (kein allgemeines „Märchen“)

def format_kids_signal_clause(c):
    """SQL (on works w): an active offer from a kids channel or with a topic of FORMAT_KIDS_TOPIC (subset of KIDS_TOPIC)."""
    topics=[t for t in kids_topics(c) if FORMAT_KIDS_TOPIC.search(t)];channels=sorted(KIDS_CHANNELS)
    cond="lower(json_extract(k.payload,'$.channel')) IN (%s)"%','.join('?'*len(channels))
    if topics:cond="(%s OR json_extract(k.payload,'$.topic') IN (%s))"%(cond,','.join('?'*len(topics)))
    return 'EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 AND %s)'%cond,channels+topics

def kids_signal_invalidate():
    with _KIDS_SIGNAL_LOCK:_KIDS_SIGNAL.clear()

def kids_signal_clause(c):
    """0.6.91: SQL (on works w) – an active offer comes from a kids channel or a kids/Märchen topic."""
    topics=kids_topics(c);channels=sorted(KIDS_CHANNELS)
    cond="lower(json_extract(k.payload,'$.channel')) IN (%s)"%','.join('?'*len(channels))
    if topics:cond='(%s OR json_extract(k.payload,\'$.topic\') IN (%s))'%(cond,','.join('?'*len(topics)))
    return 'EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 AND %s)'%cond,channels+topics

def category_labels(c):
    """Fixed category -> raw genres stored in work_genres that name it (genre index, small)."""
    import categories
    out={}
    for (raw,) in c.execute('SELECT DISTINCT genre FROM work_genres'):
        for name in categories.of_label(raw):out.setdefault(name,[]).append(raw)
    return out

def category_clause(c,genre):
    """SQL filter for a fixed category, 'Unklassifiziert', 'Sonstige' or (classic tree in
    Verwaltung → Werkkatalog) one raw genre exactly as stored."""
    import categories
    text=str(genre).strip()
    if text==categories.LEGACY_UNKNOWN:
        return 'NOT EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id)',[]
    if text==categories.UNCLASSIFIED:
        return 'NOT '+CLASSIFIED_SQL,[]
    labels=category_labels(c)
    if text==categories.OTHER:
        known=[raw for names in labels.values() for raw in names]
        if not known:return CLASSIFIED_SQL,[]
        return (CLASSIFIED_SQL+' AND NOT EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))'
                %','.join('?'*len(known))),known
    def has(names):
        raw=[r for n in names for r in labels.get(n) or []]
        if not raw:return '0',[]
        return 'EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))'%','.join('?'*len(raw)),raw
    if text in ('Kinder','Familie'):
        # 0.5.103: same rules as categories.refine (Kinder also for Familie + Animation; never next to
        # Horror/Thriller/Krimi/Erotik/Krieg, Familie never next to Horror/Erotik).
        own,own_args=has([text])
        if text=='Kinder':
            fam,fam_args=has(['Familie']);ani,ani_args=has(['Animation'])
            # 0.6.91: the broadcaster's own kids signal (KiKA, Märchen-Reihen, Kinderfilme) also counts, read from
            # the offers because a recognized work keeps only the reference genres (IMDb knows no „Kinder“).
            sig,sig_args=kids_signal_clause(c)
            own='(%s OR (%s AND %s) OR %s)'%(own,fam,ani,sig);own_args=own_args+fam_args+ani_args+sig_args
            # 0.6.99 (Björn: „im Zweifel nicht, ich gebe dann manuell frei“): only recognized works, by kids signal or by
            # a proven age rating up to the parents' limit (any category); parents' release/block on top (kids_rules).
            import kids_rules
            return kids_rules.kids_clause(c,own,own_args,has)
        bad,bad_args=has(categories.NOT_FOR_KIDS if text=='Kinder' else categories.NOT_FOR_FAMILY)
        return CLASSIFIED_SQL+' AND '+own+' AND NOT '+bad,own_args+bad_args
    if text in categories.CATEGORIES:
        clause,raw=has([text])
        if not raw:return '0',[]
        return CLASSIFIED_SQL+' AND '+clause,raw
    return 'EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre=?)',[text]

def category_tree(c):
    """[{kind, genre, n}] with the fixed categories (series counted once per show), like tree().
    0.5.103: the rules over the whole title (categories.refine: no 'Kinder' next to Horror/Krimi …)
    apply to the union of all labels of a film or show."""
    import categories
    rows=c.execute("SELECT w.kind,CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END unit,"+CLASSIFIED_SQL+
                   " classified,g.genre FROM works w LEFT JOIN work_genres g ON g.work_id=w.id"
                   " WHERE w.kind IN ('movie','series') AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)")
    found={}
    for kind,unit,classified,genre in rows:
        entry=found.setdefault((kind,unit),[False,set()])
        if classified:
            entry[0]=True
            if genre:entry[1].update(categories.of_label(genre))
    counts={}
    for (kind,unit),(checked,names) in found.items():
        names=categories.refine(names) if checked else [categories.UNCLASSIFIED]
        for name in names or [categories.OTHER]:counts[(kind,name)]=counts.get((kind,name),0)+1
    out=[{'kind':kind,'genre':name,'n':n} for (kind,name),n in counts.items()]
    out.sort(key=lambda r:(r['kind'],categories.sort_key(r['genre'])))
    return out

def tree(c):
    return [dict(r) for r in c.execute("SELECT w.kind,COALESCE(g.genre,'Unbekannt') genre,COUNT(DISTINCT CASE WHEN w.kind='series' THEN w.show_key ELSE w.id END) n FROM works w LEFT JOIN work_genres g ON g.work_id=w.id WHERE EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) GROUP BY w.kind,g.genre")]

def queue_blockers(c,now=None):
    """0.6.113 (Mac-Prüfung 0.6.108: Arbeiter „waiting“ bei 4.854 pending): open works (pending/retry) per kind and the
    first reason the recognition selection (CatalogService.pick) leaves them out, in its order. 'other' is never
    selected by design (clips go through the Sendung pass). Uses the index work_retry(state,next_try)."""
    now=time.time() if now is None else now
    out={}
    for kind,reason,n in c.execute("""SELECT w.kind,
            CASE WHEN w.kind NOT IN ('movie','series','unknown') THEN 'not_selected_kind'
                 WHEN w.next_try>? THEN 'not_due'
                 WHEN EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id) THEN 'episode_queue'
                 WHEN NOT EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1) THEN 'no_active_offer'
                 WHEN EXISTS(SELECT 1 FROM metadata_leases l WHERE l.work_id=w.id AND l.expires>?) THEN 'leased'
                 ELSE 'selectable' END,COUNT(*)
            FROM works w WHERE w.state IN ('pending','retry') GROUP BY 1,2""",(now,now)):
        out.setdefault(kind,{})[reason]=n
    return out

def stats(c):
    """One indexed classification pass, instead of separate full-work scans for each tile."""
    grouped=c.execute('SELECT kind,state,COUNT(*) n FROM works GROUP BY kind,state').fetchall()
    kinds={};states={}
    pending=0
    for kind,state,n in grouped:
        kinds[kind]=kinds.get(kind,0)+n
        states[state]=states.get(state,0)+n
        if kind!='other' and state in ('pending','retry'):pending+=n
    first=c.execute("""SELECT COUNT(*) FROM works w
        WHERE w.attempts=0 AND w.kind IN ('movie','series','unknown')
          AND w.state IN ('pending','retry','identified')
          AND NOT EXISTS(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id)
          AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)""").fetchone()[0]
    return {
        'types':kinds,'works':sum(kinds.values()),
        'offers':c.execute('SELECT COUNT(*) FROM offers WHERE active=1').fetchone()[0],
        'last_import_diff':get_state(c,'last_import_diff',{}),
        'movie_duplicates_merged':get_state(c,'movie_dedup_total_v0521',0),
        'film_hints':c.execute("""SELECT COUNT(*) FROM film_hints h JOIN works w ON w.id=h.work_id
            WHERE w.kind='unknown' AND w.state IN ('pending','retry','identified')""").fetchone()[0],
        'first_pass_remaining':first,
        'identified':states.get('identified',0),
        'matched':states.get('matched',0)+states.get('manual',0),
        'pending':pending,
        'review':states.get('review',0),
        'formats':states.get('format',0),
        'sync':get_state(c,'sync',{'phase':'waiting'}),
        'last_complete':get_state(c,'last_complete',0),
        'unknown_sweep':get_state(c,'unknown_sweep',{})
    }

def canonical(m):
    if m.get('state')=='work_identified':return None
    if m.get('kind')=='series' and not m.get('episode_verified') and m.get('state')!='user_confirmed':return None
    if not m.get('reference_id') or m.get('provider') not in ('TMDB','OMDb','TVDB','IMDb Offline'):return None
    base=('OMDb' if m['provider']=='IMDb Offline' else m['provider'])+'|'+m['kind']+'|'+str(m['reference_id'])
    if m['kind']=='series':
        if m.get('season') is None or m.get('episode') is None:return None
        base+='|s%s-e%s'%(m['season'],m['episode'])
    return digest(base)

def _letters(text):return [ch for ch in str(text or '') if ch.isalpha()]
def _all_upper(text):
    letters=_letters(text);return bool(letters) and all(ch.isupper() for ch in letters)
def _all_lower(text):
    letters=_letters(text);return bool(letters) and all(ch.islower() for ch in letters)
def _camel(text):
    """A stylised brand spelling: a lower-case letter followed by a capital inside one word (KiKA, ZDFinfo, iPad)."""
    return bool(re.search(r'[a-zäöüß][A-ZÄÖÜ]',str(text or '')))

def broadcaster_spelling(title,topic):
    """0.6.106/0.6.109: TMDB „KIKA LIVE“, KiKA „KiKA LIVE“ – a series named like the broadcaster's Reihe except for
    upper/lower case may take the broadcaster's spelling. None if nothing to change.

    0.6.109 (Mac-Prüfung A1 an 0.6.106: 29.878 Werke, 137 Namen, rund die Hälfte schlechter – „MDR SACHSENSPIEGEL“,
    „PRESSECLUB“, „ZDFinfo doku“, „Wims“): only an unstyled name (ganz groß oder ganz klein) becomes a mixed spelling,
    never the other way round; from ganz groß only to a stylised brand spelling (KiKA), not to plain title case
    („UNBUBBLE“ bleibt). kulturzeit → Kulturzeit, scobel → Scobel, maischberger → Maischberger, KIKA LIVE → KiKA LIVE."""
    title=str(title or '');topic=str(topic or '').strip()
    if not title or not topic or title==topic or title.casefold()!=topic.casefold():return None
    if _all_upper(topic) or _all_lower(topic):return None
    if _all_lower(title):
        # Mac-Prüfung S an 0.6.109: „rbb aktuell“ → „rbb AKTUELL“ ist keine bessere Schreibweise – aus ganz klein nur,
        # wenn dabei kein Wort ganz in Großbuchstaben entsteht (Abkürzungen bis 3 Buchstaben wie „SWR“ erlaubt)
        if any(len(w)>3 and _all_upper(w) for w in re.findall(r'\w+',topic)):return None
        return topic
    if _all_upper(title) and _camel(topic):return topic
    return None

def save_metadata(c,wid,m,state='manual'):
    m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
    row=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    if not row:return
    previous=json.loads(row['meta'])
    if any(previous.get(k)!=m.get(k) for k in ('title','kind','year','reference_id','provider')):
        c.execute('DELETE FROM artwork_checks WHERE work_id=?',(wid,))
        m.pop('fanart',None);m.pop('artwork_provider',None)
        for field in ('networks','studios','ratings','imdb_id','discovery_enriched','show_description'):
            if m.get(field)==previous.get(field):m.pop(field,None)
    spelled=broadcaster_spelling(m.get('title'),row['topic'] if 'topic' in row.keys() else '') if m.get('kind')=='series' else None
    if spelled:m['title']=spelled
    original_dest=canonical(m) or wid
    alias=c.execute('SELECT new_id FROM work_aliases WHERE old_id=?',(original_dest,)).fetchone()
    dest=alias[0] if alias else original_dest
    old=c.execute('SELECT state,meta,attempts,next_try FROM works WHERE id=?',(dest,)).fetchone()
    if old and old['state']=='manual' and state!='manual':
        m=json.loads(old['meta']);state='manual'
    elif old and old['state']=='matched' and state=='identified':
        # Never downgrade an already confirmed film to a weaker work-only result.
        m=json.loads(old['meta']);state='matched'
    elif old and m.get('kind')=='movie' and state in ('matched','manual','identified'):
        previous_dest=json.loads(old['meta'])
        identity_agrees=(previous_dest.get('kind')=='movie' and (
            (previous_dest.get('provider')==m.get('provider') and
             previous_dest.get('reference_id') and previous_dest.get('reference_id')==m.get('reference_id'))
            or bool(alias and original_dest!=dest)))
        if identity_agrees and state!='manual':
            incoming=normalized_genres(m.get('genres') or [])
            combined=normalized_genres(incoming+list(previous_dest.get('genres') or []))
            m['genres']=combined
            if len(combined)>len(incoming):m['genre_source']='Mehrere bestätigte Quellen'
    # Retain attempt history when a provisional work moves to a canonical ID.
    # Otherwise every merge silently turns a repeat into an apparent first pass.
    seen_attempts=max(int(row['attempts'] or 0),int(old['attempts'] or 0) if old else 0)
    due=max(float(row['next_try'] or 0),float(old['next_try'] or 0) if old else 0)
    # 0.6.92 (Befund Kinderecke-Thread 22.11.2026): a move to the canonical ID created the new row without the
    # offer topic (works.topic ''), so topic rules (Reihe, Kinderecke, Sendung) no longer saw the work.
    c.execute("""INSERT INTO works(id,title,kind,year,show_key,meta,state,updated,attempts,next_try,topic)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,kind=excluded.kind,year=excluded.year,show_key=excluded.show_key,
        meta=excluded.meta,state=excluded.state,updated=excluded.updated,
        attempts=MAX(works.attempts,excluded.attempts),
        topic=CASE WHEN COALESCE(works.topic,'')='' THEN excluded.topic ELSE works.topic END""",
        (dest,m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),state,time.time(),seen_attempts,due,row['topic'] or ''))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(dest,))
    m['genres']=normalized_genres(m.get('genres'))
    c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),dest))
    for genre in m.get('genres',[]):c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(dest,genre))
    if dest!=wid:
        c.execute('INSERT OR IGNORE INTO downloaded_items SELECT ?,path,finished FROM downloaded_items WHERE identity=?',(dest,wid))
        c.execute('UPDATE offers SET work_id=? WHERE work_id=?',(dest,wid))
        c.execute('INSERT OR REPLACE INTO work_aliases VALUES(?,?)',(wid,dest))
        c.execute('UPDATE work_aliases SET new_id=? WHERE new_id=?',(dest,wid))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(wid,));c.execute('DELETE FROM works WHERE id=?',(wid,))
    if m.get('kind')!='unknown':
        c.execute('DELETE FROM film_hints WHERE work_id IN (?,?)',(wid,dest))
    if m.get('kind')=='movie' and state in ('matched','manual','identified'):
        return reconcile_movie_duplicates(c,dest)
    return dest

def _movie_evidence(c,w):
    """Return per-work evidence, not merely a matching genre or a title string."""
    if not w or w['kind']!='movie' or w['state'] not in ('matched','manual','identified') or not w['year']:
        return None
    m=json.loads(w['meta'] or '{}')
    if m.get('kind')!='movie' or m.get('year')!=w['year']:return None
    durations=[int(r[0]) for r in c.execute(
        "SELECT json_extract(payload,'$.duration') FROM offers WHERE work_id=? AND active=1",
        (w['id'],)) if isinstance(r[0],(float,int)) and r[0]>600]
    imdb=str(m.get('imdb_id') or (m.get('reference_id') if m.get('provider') in ('IMDb Offline','OMDb') else '') or '').strip()
    return {'row':w,'meta':m,'title_key':key(w['title']),'durations':durations,'imdb_id':imdb,
            'ref':str(m.get('reference_id') or ''),'provider':str(m.get('provider') or '')}

def _same_confirmed_movie(a,b):
    """Two entries may merge only with shared film evidence; genres never prove identity."""
    if not a or not b or a['title_key']!=b['title_key'] or a['row']['year']!=b['row']['year']:
        return False
    if a['row']['state']=='manual' and b['row']['state']=='manual':
        # Two separately edited records are kept until the user explicitly resolves them.
        return False
    if a['provider']==b['provider'] and a['ref'] and b['ref'] and a['ref']!=b['ref']:
        return False
    if a['imdb_id'] and b['imdb_id'] and a['imdb_id']!=b['imdb_id']:
        return False
    if a['imdb_id'] and a['imdb_id']==b['imdb_id']:return True
    if a['provider']==b['provider'] and a['ref'] and a['ref']==b['ref']:return True
    # Different verified providers: identical film title, release year and close
    # broadcaster runtimes give independent evidence. Without runtimes, no merge.
    if a['row']['state'] not in ('matched','manual') or b['row']['state'] not in ('matched','manual'):
        return False
    if not a['ref'] or not b['ref'] or not a['durations'] or not b['durations']:
        return False
    return any(abs(x-y)<=min(300,max(x,y)*.05) for x in a['durations'] for y in b['durations'])

def _merge_confirmed_movie(c,a,b):
    """Preserve offers, downloads, manual changes, metadata and genre evidence."""
    def score(v):
        m=v['meta'];w=v['row']
        return (w['state']=='manual',w['id']==canonical(m),w['state']=='matched',
                bool(m.get('poster')),len(m.get('genres') or []))
    keep,other=sorted((a,b),key=score,reverse=True)
    target=keep['row']['id'];old=other['row']['id']
    preferred=dict(keep['meta']);extra=other['meta']
    # Manual genre edits are authoritative. Otherwise a verified provider's
    # smaller genre list must not erase previously verified genres.
    if keep['row']['state']!='manual':
        previous=normalized_genres(preferred.get('genres') or [])
        combined=normalized_genres(previous+list(extra.get('genres') or []))
        preferred['genres']=combined
        if combined!=previous:preferred['genre_source']='Mehrere bestätigte Quellen'
    for field in ('poster','fanart','description','show_description','rating','rating_source',
                  'votes','imdb_id','networks','studios','show_credits','ratings'):
        if preferred.get(field) in (None,'',[],{}):
            if extra.get(field) not in (None,'',[],{}):preferred[field]=extra[field]
    c.execute('UPDATE works SET meta=?,updated=? WHERE id=?',(json.dumps(preferred),time.time(),target))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(target,))
    for genre in normalized_genres(preferred.get('genres') or []):
        c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(target,genre))
    c.execute('UPDATE offers SET work_id=? WHERE work_id=?',(target,old))
    c.execute('INSERT OR IGNORE INTO downloaded_items SELECT ?,path,finished FROM downloaded_items WHERE identity=?',(target,old))
    c.execute('INSERT OR IGNORE INTO artwork_checks SELECT ?,next_try FROM artwork_checks WHERE work_id=?',(target,old))
    c.execute('INSERT OR IGNORE INTO format_dirty SELECT ? FROM format_dirty WHERE work_id=?',(target,old))
    c.execute('INSERT OR REPLACE INTO work_aliases VALUES(?,?)',(old,target))
    c.execute('UPDATE work_aliases SET new_id=? WHERE new_id=?',(target,old))
    set_state(c,'movie_dedup_total_v0521',get_state(c,'movie_dedup_total_v0521',0)+1)
    for table,field in (('work_genres','work_id'),('artwork_checks','work_id'),
                        ('metadata_priority','work_id'),('format_dirty','work_id')):
        c.execute('DELETE FROM '+table+' WHERE '+field+'=?',(old,))
    c.execute('DELETE FROM works WHERE id=?',(old,))
    return target

def reconcile_movie_duplicates(c,wid,max_candidates=40):
    """Merge conservative, independently verified duplicates of one movie.

    Ambiguous films (missing year/runtime, different years, mismatched provider
    references) remain separate. Small indexed candidate lookup, no full scan.
    """
    w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
    a=_movie_evidence(c,w)
    if not a:return wid
    rows=c.execute("""SELECT * FROM works
        WHERE kind='movie' AND year=? AND title=? COLLATE NOCASE
          AND state IN ('matched','manual','identified') AND id<>?
        LIMIT ?""",(w['year'],w['title'],wid,max_candidates+1)).fetchall()
    if len(rows)>max_candidates:return wid  # too ambiguous, leave intact
    for other in rows:
        b=_movie_evidence(c,other)
        if _same_confirmed_movie(a,b):
            wid=_merge_confirmed_movie(c,a,b)
            w=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
            a=_movie_evidence(c,w)
    return wid

def deduplicate_movie_batch(c,limit=200):
    """Incremental one-time upgrade of older catalogues, bounded per transaction."""
    state='movie_dedup_cursor_v0521';cursor=get_state(c,state,0)
    if cursor=='complete':return 0,0
    rows=c.execute("""SELECT rowid,id FROM works WHERE rowid>? AND kind='movie'
          AND year IS NOT NULL AND state IN ('matched','manual','identified')
          ORDER BY rowid LIMIT ?""",(cursor,limit)).fetchall()
    before=get_state(c,'movie_dedup_total_v0521',0)
    for row in rows:
        cursor=row['rowid']
        if not c.execute('SELECT 1 FROM works WHERE id=?',(row['id'],)).fetchone():continue
        reconcile_movie_duplicates(c,row['id'])
    set_state(c,state,cursor if rows else 'complete')
    return len(rows),get_state(c,'movie_dedup_total_v0521',0)-before

def match_meta(meta,source=None):
    """Diagnose Air 23.11.2026 (0.6.116: 18 von 18 3sat-Filmen mit Titelzusatz „prüfen“): the work's own meta has no
    year – only the search copy took the year from „… - Spielfilm, USA 1993“ (0.6.97). Without it a film is matched
    only when the running time agrees (8 Mile on the Pro did, „Lauf Junge lauf“ on the Air did not). Matching uses the
    title year like a broadcaster year; ±1 still needs the running time (matching.year_close)."""
    if not meta or meta.get('year') or meta.get('kind') not in ('movie','unknown'):return meta
    import metadata
    year=metadata.film_suffix_year(meta.get('title')) or metadata.film_suffix_year((source or {}).get('title'))
    return dict(meta,year=year) if year else meta

def auto_choice(meta,rows):
    import matching
    return matching.choose(meta,rows)

def work_choice(meta,rows):
    import matching
    return matching.choose(meta,rows,work_only=True)

def propagate_series(c,old_show,m):
    # Transfer work metadata, never a sibling's episode number or episode plot.
    common={k:m[k] for k in ('title','year','provider','reference_id','poster','genres','genre_source','show_description','reference_runtime_seconds') if k in m}
    for row in c.execute("SELECT * FROM works WHERE show_key=? AND state NOT IN ('manual','matched')",(old_show,)).fetchall():
        own=json.loads(row['meta'])
        # Every recognised episode propagates again; rewriting unchanged siblings made this quadratic per series.
        unchanged=all(own.get(k)==v for k,v in common.items())
        # 0.6.58 (Björns Diagnose 20.11. nachts: „BR retro“ 399-mal in 4,5 min neu eingeordnet, 165.000
        # gezählte Beiträge): an edition, contribution or extra already filed with its Sendung ('format') was
        # set back to 'identified' by every further recognition in the same series. It returned to the
        # episode queue and was filed again a few seconds later. Such a work keeps its filing; only the
        # shared series data follow.
        if row['state'] in ('identified','format') and unchanged:continue
        own.update(common)
        save_metadata(c,row['id'],own,'format' if row['state']=='format' else 'identified')

def focus_series(c,show_key,limit=24,cooldown=1800):
    """Boost a *bounded* number of sibling episodes after verified show recognition.

    It does not reset next_try, override user-prioritised work, or force an
    unbounded recheck of an entire long-running show.
    """
    if not show_key:return False
    now=time.time()
    old=c.execute('SELECT until FROM series_focus WHERE show_key=?',(show_key,)).fetchone()
    if old and old[0]>now:return False
    eligible=c.execute("""SELECT 1 FROM works w WHERE w.show_key=?
        AND w.kind='series' AND w.state IN ('pending','retry','identified')
        AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
        LIMIT 1""",(show_key,)).fetchone()
    if not eligible:return False
    c.execute('INSERT OR REPLACE INTO series_focus VALUES(?,?,?,?)',
              (show_key,now+cooldown,int(limit),now))
    return True

def focus_take(c,show_key):
    if not show_key:return
    c.execute('UPDATE series_focus SET remaining=MAX(0,remaining-1) WHERE show_key=?',(show_key,))

def prioritize(c,ids=None,show=''):
    count=0
    if show:ids=[r[0] for r in c.execute('SELECT id FROM works WHERE show_key=?',(show,))]
    for wid in (ids or [])[:1000]:
        row=c.execute('SELECT state FROM works WHERE id=?',(wid,)).fetchone()
        if not row or row[0] in ('manual','matched'):continue
        # An explicit request must never be reclassified by the automatic
        # format scanner while a user is waiting for this particular work.
        m=json.loads(c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()[0])
        # 0.6.49: a sweep decision (Sendungsbeitrag, Einzelsendung) is undone; set-aside suggestions return.
        restored=restore_unknown(m)
        if restored:
            title,kind,m=restored
            c.execute("UPDATE works SET title=?,kind=?,show_key='',state='pending' WHERE id=?",(title,kind,wid))
            c.execute('DELETE FROM episode_queue WHERE work_id=?',(wid,))
        if not m.get('scan_requested') or restored:
            m['scan_requested']=True
            c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
        c.execute("UPDATE works SET state=CASE WHEN state='identified' THEN state ELSE 'pending' END,next_try=0 WHERE id=?",(wid,))
        c.execute('INSERT OR IGNORE INTO metadata_priority VALUES(?,?)',(wid,time.time()))
        c.execute("UPDATE episode_queue SET next_try=0 WHERE work_id=?",(wid,))
        count+=1
    return count

# Recurring broadcast formats (news, regional and service magazines). Their single contributions are
# not in any film database; they are grouped under their format and not queried (diagnosis 0.4.7).
FORMAT_WORDS=re.compile(r'(?i)\b(?:nachrichten|tagesschau|tagesthemen|aktuell|journal|heute|wetter|sportschau|sportstudio|magazin|lokalzeit|abendschau|landesschau|hessenschau|regional|drehscheibe|morgenmagazin|mittagsmagazin|pressekonferenz|gottesdienst|podcast|kompakt|update|live)\b')
FORMAT_GENERIC={'film','filme','spielfilm','serien','serie','fernsehfilm','mediathek','zdf','ard','3sat','arte','kika','kino','dokumentation','dokumentationen','doku','dokus','reportage','sonstiges','sonstige','unterhaltung','filme im ersten'}
TRAILER=re.compile(r'(?i)^\s*(?:trailer|teaser|vorschau)\b')
# 0.6.39 (Björn, 19.11.2026, diagnosis sample): dated editions of magazines were queried as films at
# IMDb, TMDB, TVDB and Wikidata and ended "ohne Treffer" – "28 minutes - … (13/11/2026)", "ttt vom
# 2. Februar 2025", "Studio 2 vom 16.11.2026", "Hier und heute | 12.08.2025", "Invitation au voyage -
# 04/11/2026". A full calendar date in the title marks one edition of a recurring Sendung; a film or a
# drama episode is not titled with its broadcast date.
# 0.6.44 (Diagnose 20.11.2026 abends): Austrian month names ("erLesen – Sendung vom 26. Jänner 2025") and a
# weekday after "vom" ("logo! vom Montag, 16. Februar 2026") were not read as a date.
MONTHS='januar|jänner|februar|feber|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember'
WEEKDAY=r'(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag),?\s+)?'
DATED=re.compile(r'(?i)(?<![\w/.])(?:[0-3]?\d[./][01]?\d[./](?:19|20)\d{2}|vom\s+'+WEEKDAY+r'[0-3]?\d\.\s*(?:'+MONTHS+r')\s+(?:19|20)\d{2})(?![\w/]|\.\d)')
# "hallo hessen – Teil 1 vom 15.04.2026": the part number belongs to the dated edition, it is no episode number.
EDITION_PART=re.compile(r'(?i)\b(?:teil|part)\s*\d{1,2}\s+(?=vom\s)')

def foreign_version(source):
    """True for an ARTE language version other than German (ARTE.FR, ARTE.ES, ARTE.IT, ARTE.PL, ARTE.EN)."""
    import languages
    if source.get('_foreign_only') is False:return False
    return languages.CHANNEL_LANGUAGE.get(str(source.get('channel') or '').strip().upper(),'de')!='de'

# 0.6.41 (Björn, 19.11.2026: Episodensuche 2,4 % zugeordnet, 66 % ohne Treffer, 32 % unsicher). The 6,104
# series identified in the diagnosis window were 82 % editions of news and regional magazines ("SWR Aktuell
# Rheinland-Pfalz" 1,795, "buten un binnen | regionalmagazin" 1,211, "MDR Sachsenspiegel" 901, "DER TAG in
# Berlin & Brandenburg" 746, …); 91 % of the runtime suspicions were 1–6 minute clips of 28-minute
# Sendungen. Neither has an episode of its own in any database. They are filed as edition or contribution
# of their (already identified) Sendung once the IMDb probe found nothing, never as a matched episode.
FORMAT_SERIES=re.compile(r'(?i)magazin|nachrichten|\b(?:vor ort|der tag|infos?|spezial|extra|report|reportage)\b')
# 0.6.75: also the ZDF year count "(S2026/E38)" (Forum am Freitag); a numbered offer is never a contribution.
EDITION_NUMBERING=re.compile(r'(?i)\b(?:folge|episode|teil|part)\s*\d+|\(\s*\d{1,3}\s*(?:/\s*\d{1,3}\s*)?\)|\bS\d{1,4}\s*[/._-]?\s*E\d{1,4}\b')

def format_series(name):
    """True for the title of a recurring news, regional or service programme (not a scripted series)."""
    k=key(cleaned(name))
    if not k or k in FORMAT_GENERIC:return False
    return k in NEWS_TOPICS or bool(FORMAT_WORDS.search(k) or FORMAT_SERIES.search(k))

def sendung_with_editions(c,show_key,minimum=3):
    """True once a series has several works filed as editions of a Sendung (cheap, uses work_show)."""
    if not show_key:return False
    return len(c.execute("SELECT 1 FROM works WHERE show_key=? AND state='format' LIMIT ?",(show_key,minimum)).fetchall())>=minimum

def broadcast_day(title,source):
    """True if the date named in the title is the offer's broadcast date (within three days)."""
    import imdb_archive
    date=imdb_archive.title_date(title)
    try:stamp=int(source.get('timestamp') or 0)
    except (TypeError,ValueError):return False
    if not date or stamp<=0:return False
    try:named=time.mktime((date[1],date[2],date[3],12,0,0,0,0,-1))
    except (OverflowError,ValueError):return False
    return abs(named-stamp)<=3*86400

# 0.6.68 (Mac-Gegenprüfung 0.6.65, 21.11.2026): regional magazines name the day without the year
# ("buten un binnen vom 23. Oktober", "… vom 23.10."). Only with the offer's own broadcast day (±3 days).
DATED_DAY=re.compile(r'(?i)(?<![\w/.])vom\s+'+WEEKDAY+r'(?:([0-3]?\d)\.\s*('+MONTHS+r')|([0-3]?\d)\.([01]?\d)\.)(?!\s*(?:19|20)?\d{2}\b)(?![\w/])')
# Talk shows named by their guest ("THADEUSZ lang & breit - Gast: Dr. Emily Haber", "… – Zu Gast: …",
# "THADEUSZ lang & breit: Britische Autorin Jacinta Nandi ist zu Gast"): 39 of 39 unresolved samples.
GUEST=re.compile(r'(?i)^(.+?)\s*[-–—:|]\s*(?:(?:zu\s+)?gast\s*:\s*\S|.{3,160}\bist\s+zu\s+gast\s*$)')

def broadcast_day_short(title,source):
    """True if a day named without year ("vom 23. Oktober", "vom 23.10.") is the offer's broadcast day (±3 days)."""
    m=DATED_DAY.search(str(title or ''))
    try:stamp=int(source.get('timestamp') or 0)
    except (TypeError,ValueError):return False
    if not m or stamp<=0:return False
    import imdb_archive
    day=int(m.group(1) or m.group(3));month=imdb_archive.MONTH_NUMBERS.get((m.group(2) or '').lower()) or int(m.group(4) or 0)
    if not 1<=month<=12 or not 1<=day<=31:return False
    year=time.localtime(stamp).tm_year
    for y in (year-1,year,year+1):                     # "vom 31. Dezember" shown on 2 January
        try:named=time.mktime((y,month,day,12,0,0,0,0,-1))
        except (OverflowError,ValueError):continue
        if abs(named-stamp)<=3*86400:return True
    return False

def guest_edition(title,series,topic):
    """True for "<Sendung> - (Zu) Gast: …" / "<Sendung>: … ist zu Gast" of exactly this Sendung."""
    m=GUEST.match(str(title or ''))
    return bool(m) and key(cleaned(m.group(1))) in {key(cleaned(series)),key(cleaned(topic))}-{''}

def recurring_edition(meta,source,sendung=False,clip_limit=600):
    """'edition', 'segment' or None for an identified series work without an episode of its own.

    edition: the offer names a calendar date ("Sachsenspiegel vom 19.11.2026"; a drama episode is not
    titled with its broadcast date, see DATED) or only repeats the name of a news/magazine Sendung.
    segment: a clip shorter than 10 minutes of a news/magazine Sendung ("buten un binnen": 2-4 minute
    contributions next to the 28-minute edition). Numbered offers (S01E02, Folge 3, (2/6)) never qualify;
    neither does a work the user asked to check, a verified episode or a trailer. sendung=True: the
    series is known to publish dated editions ("MDR Sachsenspiegel" has no format word in its name).
    clip_limit (0.6.75): longer bound for a contribution when IMDb lists the Sendung only as dated editions
    (Kaffee oder Tee?: 8–17-minute recipe clips next to the two-hour edition).
    """
    if not source or meta.get('kind')!='series' or meta.get('scan_requested') or meta.get('episode_verified'):return None
    if isinstance(meta.get('episode'),int) and not isinstance(meta.get('episode'),bool) and meta['episode']>0:return None
    title=cleaned(source.get('title'))
    if not title or TRAILER.search(title):return None
    if DATED.search(title) or DATED_DAY.search(title):title=EDITION_PART.sub('',title)
    if EDITION_NUMBERING.search(title) or EP.search(title):return None
    series=meta.get('title') or '';topic=source.get('topic') or ''
    recurring=sendung or format_series(series) or format_series(topic)
    if not DATED.search(title) and DATED_DAY.search(title) and broadcast_day_short(title,source):
        # 0.6.68: day without year – the Sendung's name must lead the title, or the Sendung is a known format
        named=any(key(title).startswith(k) for k in {key(cleaned(series)),key(cleaned(topic))}-{''})
        if recurring or named:return 'edition'
    if guest_edition(title,series,topic):return 'edition'
    if DATED.search(title):
        # A scripted episode may carry a historic date ("Die Nacht vom 9. November 1989"); outside a known
        # news/magazine Sendung the date must be the offer's own broadcast day (±3 days).
        return 'edition' if recurring or broadcast_day(title,source) else None
    if not recurring:return None
    if key(title) in {key(cleaned(series)),key(cleaned(topic))}:return 'edition'
    duration=int(source.get('duration') or 0)
    if 0<duration<clip_limit:return 'segment'
    return None

def dated_rule(role,source,clip_limit):
    """0.6.76: 'imdb_dated_v0677' if only the longer bound of a dated IMDb Sendung made the offer a contribution."""
    try:duration=int(source.get('duration') or 0)
    except (TypeError,ValueError):duration=0
    return 'imdb_dated_v0677' if role=='segment' and clip_limit and duration>=600 else None

DATED_SEGMENT_RULES=('imdb_dated_v0676','imdb_dated_v0677')
def dated_segments(c,after='',limit=500):
    """0.6.78: contributions filed by the longer bound of 0.6.75/0.6.76/0.6.77 for a re-check: rows
    (work, best active offer payload). 0.6.75 set no format_rule; its contributions are the IMDb-identified ones
    of at least 10 minutes (the ordinary bound is 600 s). Read only."""
    return c.execute("""SELECT w.*,(SELECT o.payload FROM offers o WHERE o.work_id=w.id AND o.active=1
            ORDER BY o.rank DESC LIMIT 1) payload FROM works w
        WHERE w.id>? AND w.state='format' AND w.kind='series' AND json_extract(w.meta,'$.format_grouping')='segment'
          AND (json_extract(w.meta,'$.format_rule') IN (?,?)
               OR (json_extract(w.meta,'$.format_rule') IS NULL AND json_extract(w.meta,'$.provider')='IMDb Offline'
                   AND json_extract(w.meta,'$.reference_id') LIKE 'tt%'))
        ORDER BY w.id LIMIT ?""",(after,*DATED_SEGMENT_RULES,limit)).fetchall()

def has_episode(m):
    """0.6.79: a work with a concrete or confirmed episode (season/episode number, provider episode id)."""
    e=m.get('episode')
    return bool(m.get('episode_verified') or m.get('episode_reference_id')
                or (isinstance(e,int) and not isinstance(e,bool) and e>0))

def clip_episodes(c,after='',limit=500):
    """0.6.79: works filed by the clip rule of 0.6.77 that carry an episode number (Mac-Prüfung 0.6.78: Moin Piet 11,
    Doc Fischer 6, automatically confirmed via TMDB). Read only."""
    return c.execute("""SELECT * FROM works WHERE id>? AND state='format' AND json_extract(meta,'$.format_rule')='clip_show_v0677'
        AND CAST(COALESCE(json_extract(meta,'$.episode'),0) AS INTEGER)>0 ORDER BY id LIMIT ?""",(after,limit)).fetchall()

def undo_segment(c,row,reason,mark='v0678'):
    """0.6.78: take back an automatic contribution filing; the work is an identified series work again and
    the episode queue (trigger) checks it with the current rules. User decisions are never touched."""
    if row['state']!='format':return False
    try:m=json.loads(row['meta'] or '{}')
    except (TypeError,ValueError):return False
    if m.get('scan_requested') or m.get('episode_verified') or m.get('format_grouping')!='segment':return False
    for k in ('format_grouping','format_rule'):m.pop(k,None)
    m.update(state='identified',reason=reason,format_undone=mark)
    return c.execute("UPDATE works SET meta=?,state='identified',next_try=0 WHERE id=? AND state='format'",
                     (json.dumps(m),row['id'])).rowcount>0

def relabel_segment(c,row,rule):
    try:m=json.loads(row['meta'] or '{}')
    except (TypeError,ValueError):return False
    if m.get('format_rule')==rule:return False
    m['format_rule']=rule
    return c.execute("UPDATE works SET meta=? WHERE id=? AND state='format'",(json.dumps(m),row['id'])).rowcount>0

def mark_recurring_edition(c,row,meta,source,role,rule=None):
    """File an identified series work as edition/contribution of its Sendung (state 'format').

    The series identity (title, year, provider, reference) stays; the work leaves the episode queue
    through its trigger. Only provisional 'identified' works change, never a user decision.
    """
    m={k:v for k,v in meta.items() if k not in ('suggestions','metadata_warnings')}
    series=m.get('title') or cleaned(source.get('topic'))
    edition=cleaned(source.get('title'))
    if key(edition)==key(series) and source.get('timestamp'):
        try:edition+=' · '+time.strftime('%d.%m.%Y',time.localtime(int(source['timestamp'])))
        except (TypeError,ValueError,OverflowError,OSError):pass
    m.update(state='format',format_grouping='edition' if role=='edition' else 'segment',
             episode_title=edition or m.get('episode_title'),episode_verified=False,
             episode_reference_id=None,video_role_needs_review=False,
             reason=('Ausgabe der Sendung „%s“; Sendungsausgaben haben keine eigene Episodenkennung.' if role=='edition'
                     else 'Beitrag der Sendung „%s“; keine eigene Folge.')%series)
    # 0.6.76: which rule filed it, so a diagnosis can tell the new bound from earlier filing (Mac-Prüfung K5)
    if rule:m['format_rule']=rule
    else:m.pop('format_rule',None)
    return c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=? AND state='identified'",
                     (json.dumps(m),row['id'])).rowcount>0

def refile_reset_edition(c,row,meta):
    """0.6.58: 'edition'/'segment' for an identified work that still carries its earlier filing, else None.

    Up to 0.6.55 every further recognition in a series set the editions and contributions already filed with
    their Sendung back to 'identified' (propagate_series). Their metadata kept the filing (state 'format',
    format_grouping); the episode queue files them again at once instead of checking IMDb and the sender.
    A user's rescan (scan_requested) or a confirmed episode is never undone.
    """
    role=meta.get('format_grouping')
    if role not in ('edition','segment') or meta.get('state')!='format':return None
    # 0.6.68: a filed contribution later flagged as a short clip (18 BR24 works in the Mac check) is still
    # the contribution it was filed as; mark_recurring_edition clears the flag.
    if meta.get('scan_requested') or meta.get('episode_verified'):return None
    if row['state']!='identified':return None
    if meta.get('video_role_needs_review'):
        meta=dict(meta,video_role_needs_review=False)
        done=c.execute("UPDATE works SET state='format',next_try=0,meta=? WHERE id=? AND state='identified'",
                       (json.dumps(meta),row['id'])).rowcount
        return role if done else None
    done=c.execute("UPDATE works SET state='format',next_try=0 WHERE id=? AND state='identified'",(row['id'],)).rowcount
    return role if done else None

def reset_editions(c,limit=5000):
    """0.6.65: ids of identified works that still carry their earlier filing (see refile_reset_edition).

    Read only. Reset editions are often old news editions whose offers have expired; the episode queue never
    takes a work without an active offer, so they waited there for ever (Mac-Gegenprüfung 0.6.58: 777 stayed).
    """
    return [r[0] for r in c.execute("""SELECT w.id FROM works w
        WHERE w.kind='series' AND w.state='identified' AND json_extract(w.meta,'$.state')='format'
          AND json_extract(w.meta,'$.format_grouping') IN ('edition','segment')
          AND COALESCE(json_extract(w.meta,'$.scan_requested'),0)=0 LIMIT ?""",(limit,))]

def editions_waiting(c,limit=5000,after='',refs=()):
    """0.6.68: queued works checked before the new edition rules (DATED_DAY, GUEST) that they now cover.

    Read only; returns (ids, last id). They waited 7–31 days as "ohne Treffer" (Mac check: THADEUSZ, buten un
    binnen); the episode queue files them on its next turn once they are due again."""
    rows=c.execute("""SELECT q.work_id,w.meta,(SELECT o.payload FROM offers o WHERE o.work_id=q.work_id AND o.active=1
            ORDER BY o.rank DESC LIMIT 1) payload
        FROM episode_queue q JOIN works w ON w.id=q.work_id
        WHERE q.work_id>? AND q.last_outcome='unresolved' ORDER BY q.work_id LIMIT ?""",(after,limit)).fetchall()
    out=[]
    for row in rows:
        if not row[2]:continue
        try:meta=json.loads(row[1] or '{}');source=json.loads(row[2])
        except (TypeError,ValueError):continue
        title=str(source.get('title') or '')
        # 0.6.70: daily soaps with an absolute number („Folge 4556“) of an IMDb-identified series
        import imdb_archive
        if str(meta.get('reference_id') or '').startswith('tt') and imdb_archive.ABSOLUTE_NUMBER.search(title):
            out.append(row[0]);continue
        # 0.6.75: series whose IMDb listing the new rules cover (dated Sendung, running-numbered titles)
        if refs and str(meta.get('reference_id') or '') in refs:
            out.append(row[0]);continue
        if not (DATED_DAY.search(title) or GUEST.match(title)):continue
        if recurring_edition(meta,source)=='edition':out.append(row[0])
    return out,(rows[-1][0] if rows else None)

# 0.6.83 (Mac-Abfrage Runde 4, 21.11.2026): „Hallo Niedersachsen“ 4.442 Beiträge von 1–4 Minuten waren „ohne
# Treffer“: no format word in the name, no IMDb episode list, no runtime to compare. Kids' short series (5–7-minute
# cartoons) look the same by length, so kids channels and genres never qualify, and the rule applies only after
# IMDb listed no episode for the series.
KIDS_CHANNELS={'kika','kika.de','zdf-tivi','zdftivi','toggo','super rtl'}
KIDS_GENRES=('kinder','kids','children','family','familie','animation','zeichentrick')
FICTION_TOPIC=re.compile(r'(?i)serie|fiktion|fiction|kurz und witzig|kinder|kids|zeichentrick|animation|comedy|sketch')
def clip_sendung_show(c,show_key,exclude_work='',limit=128):
    """0.6.83: True if a Sendung publishes almost only short clips: at least 20 active offers, at least 90 % shorter
    than 10 minutes, median below 5 minutes (bounded, indexed sample; read only).

    0.6.85 (Mac-Prüfung 0.6.84): a series of short episodes looks the same by length – JoNaLu-Minis (pre-school
    cartoon, channel „ZDF“, no genre), ARTE „Alte Schachteln aus Belgien“/„Bilder allein zuhaus“ (rubric „Kurz und
    witzig“), „Erklär’s mir“ (Planet Schule). A contribution belongs to a Sendung that also broadcasts whole
    editions (Hallo Niedersachsen): at least one active offer of 20 minutes or more is required."""
    if not show_key:return False
    if not c.execute("""SELECT 1 FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1
        WHERE w.show_key=? AND CAST(json_extract(o.payload,'$.duration') AS INTEGER)>=1200 LIMIT 1""",(show_key,)).fetchone():return False
    rows=c.execute("""SELECT CAST(json_extract(o.payload,'$.duration') AS INTEGER) d
        FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1
        WHERE w.show_key=? AND w.id!=? LIMIT ?""",(show_key,exclude_work,min(max(20,int(limit)),256))).fetchall()
    values=sorted(float(r[0]) for r in rows if r[0] and r[0]>0)
    if len(values)<20:return False
    short=sum(1 for v in values if v<600)
    return short*10>=len(values)*9 and values[len(values)//2]<300

def clip_sendung_offer(meta,source):
    """0.6.83: the offer itself may be a contribution of a clip Sendung (short, no number, no kids programme)."""
    if not source or meta.get('kind')!='series' or meta.get('scan_requested') or has_episode(meta):return False
    if str(source.get('channel') or '').strip().lower() in KIDS_CHANNELS:return False
    # 0.6.85: fiction and kids rubrics, portals and sections name no news/magazine Sendung
    topic=str(source.get('topic') or '')
    if not template_topic(topic) or FICTION_TOPIC.search(topic):return False
    genres=' '.join(str(g) for g in (meta.get('genres') or [])).lower()
    if any(w in genres for w in KIDS_GENRES):return False
    title=cleaned(source.get('title'))
    if not title or TRAILER.search(title) or EDITION_NUMBERING.search(title) or EP.search(title):return False
    try:duration=int(source.get('duration') or 0)
    except (TypeError,ValueError):return False
    return 0<duration<600

def clip_sendung_filed(c,after='',limit=200):
    """0.6.85: show keys of works filed by clip_sendung_v0683, in id order (read only); (keys, last id or None)."""
    rows=c.execute("""SELECT id,show_key FROM works WHERE id>? AND state='format'
        AND json_extract(meta,'$.format_rule')='clip_sendung_v0683' ORDER BY id LIMIT ?""",(after,limit)).fetchall()
    return sorted({r[1] for r in rows if r[1]}),(rows[-1][0] if rows else None)

def undo_clip_sendung(c,show_key):
    """0.6.85: take back all clip_sendung_v0683 filings of a Sendung the rule no longer covers (one transaction, so
    no sibling is filed again by the „Sendung with editions“ rule meanwhile). Returns the number taken back."""
    if clip_sendung_show(c,show_key):
        rows=c.execute("""SELECT w.*,(SELECT o.payload FROM offers o WHERE o.work_id=w.id AND o.active=1 ORDER BY o.rank DESC LIMIT 1) payload
            FROM works w WHERE w.show_key=? AND w.state='format' AND json_extract(w.meta,'$.format_rule')='clip_sendung_v0683'""",(show_key,)).fetchall()
        rows=[r for r in rows if not (r['payload'] and clip_sendung_offer(dict(json.loads(r['meta'] or '{}'),state=None),json.loads(r['payload'])))]
    else:
        rows=c.execute("""SELECT * FROM works WHERE show_key=? AND state='format'
            AND json_extract(meta,'$.format_rule')='clip_sendung_v0683'""",(show_key,)).fetchall()
    return sum(1 for r in rows if undo_segment(c,r,'Kurzserie oder Kinderprogramm; Beitrags-Einordnung zurückgenommen (0.6.85)','v0685'))

def parked_refilable(c,limit=2000,after=''):
    """0.6.83: queue entries parked as „ohne Treffer“ (up to 30 days) that the current rules file as edition or
    contribution. Read only; returns (ids, last id or None).

    Mac-Abfrage Runde 4: 99.533 entries "unresolved", only 72 of them due – most were checked by an older version
    (logo! „vom Donnerstag, 4. Juni 2026“ is an edition today). The episode queue decides again with today's rules."""
    rows=c.execute("""SELECT q.work_id,w.meta,w.show_key,(SELECT o.payload FROM offers o WHERE o.work_id=q.work_id
            AND o.active=1 ORDER BY o.rank DESC LIMIT 1) payload
        FROM episode_queue q JOIN works w ON w.id=q.work_id
        WHERE q.work_id>? AND q.last_outcome IN ('unresolved','no_imdb_episodes') AND q.next_try>?
          AND w.state='identified' ORDER BY q.work_id LIMIT ?""",(after,time.time(),limit)).fetchall()
    out=[];sendung={};clips={}
    for wid,raw,show,payload in rows:
        if not payload:continue
        try:meta=json.loads(raw or '{}');source=json.loads(payload)
        except (TypeError,ValueError):continue
        if show not in sendung:sendung[show]=sendung_with_editions(c,show)
        if recurring_edition(meta,source,sendung[show]):out.append(wid);continue
        if clip_sendung_offer(meta,source):
            if show not in clips:clips[show]=clip_sendung_show(c,show)
            if clips[show]:out.append(wid)
    return out,(rows[-1][0] if rows else None)

def unresolved_imdb_series(c):
    """0.6.75: IMDb series IDs of queue entries without a result (read only, one pass over the queue)."""
    return [r[0] for r in c.execute("""SELECT DISTINCT json_extract(w.meta,'$.reference_id') FROM episode_queue q
        JOIN works w ON w.id=q.work_id WHERE q.last_outcome='unresolved'
        AND json_extract(w.meta,'$.provider')='IMDb Offline' AND json_extract(w.meta,'$.reference_id') LIKE 'tt%'""")]

def reset_identity(c,row,source,reason):
    """0.6.77: forget a provisional automatic series identity; the work is recognised again from the sender data.

    Only 'identified' works without a confirmed episode change; user decisions and matches stay."""
    if row['state']!='identified':return False
    m=json.loads(row['meta'] or '{}')
    if m.get('episode_verified') or m.get('scan_requested'):return False
    fresh=seed(source);fresh['reason']=reason
    return c.execute("UPDATE works SET title=?,kind=?,show_key=?,meta=?,state='pending',next_try=0 WHERE id=? AND state='identified'",
                     (fresh['title'],fresh['kind'],showkey(fresh),json.dumps(fresh),row['id'])).rowcount>0

def requeue_from_source(c,row,source,reason):
    """0.6.118: undo of an automatic reset – the work is recognised again from the sender data, with a fresh attempt
    count (also when a format rule filed it meanwhile). User decisions and matches are never touched."""
    if row['state'] not in ('pending','retry','review','format'):return False
    fresh=seed(source);fresh['reason']=reason
    return c.execute("""UPDATE works SET title=?,kind=?,show_key=?,meta=?,state='pending',attempts=0,next_try=0
        WHERE id=? AND state IN ('pending','retry','review','format')""",
                     (fresh['title'],fresh['kind'],showkey(fresh),json.dumps(fresh),row['id'])).rowcount>0

def refile_reset_editions(c,ids):
    """File the given works again (one short write transaction); returns {'edition': n, 'segment': n}."""
    done={'edition':0,'segment':0}
    for wid in ids:
        row=c.execute('SELECT id,state,meta FROM works WHERE id=?',(wid,)).fetchone()
        if not row:continue
        try:meta=json.loads(row['meta'] or '{}')
        except (TypeError,ValueError):continue
        role=refile_reset_edition(c,row,meta)
        if role:done[role]+=1
    return done

def format_contribution(m,source,topic_works):
    """True for a single contribution of a recurring format, e.g. one edition of "aktuell (16 Uhr)"."""
    topic=cleaned(source.get('topic'));title=cleaned(source.get('title'))
    import metadata
    if m.get('kind') not in ('unknown','other') or m.get('scan_requested') or not topic or key(topic) in FORMAT_GENERIC or metadata.RUBRIC.match(topic):return False
    if TRAILER.search(title):return False
    if DATED.search(title) and topic_works>=2:return True
    # 0.6.39: 41 % of the failed checks in Björn's diagnosis were ARTE's French, Spanish, Italian, Polish
    # and English versions ("Le dessous des images - …", "ARTE Reportaje - …", "Green, ma non troppo - …").
    # The German version of the same programme is its own work and is checked; the foreign versions of
    # a recurring Sendung (three or more works, shorter than a feature film) join it instead.
    if foreign_version(source) and topic_works>=3 and 0<int(source.get('duration') or 0)<3600:return True
    clip=m.get('kind')=='other';duration=int(source.get('duration') or 0)
    # 0.5.80 (Björn: news and magazine clips belong to their Sendung, not to "Weitere Sendungen"):
    # editions titled like their Sendung ("Landesschau" / "Landesschau") count once there are several,
    # and a clip the import already recognised as news/magazine material ('other') joins its Sendung
    # even as the only edition so far.
    if key(topic)==key(title):return bool(FORMAT_WORDS.search(topic)) and topic_works>=2
    if FORMAT_WORDS.search(topic):return topic_works>=(1 if clip else 2)
    if clip and duration<1200 and topic_works>=2:return True
    return duration<600 and topic_works>=3

def broadcaster_format(m,source,topic_works):
    """True for an episode of a news or magazine Sendung that only the broadcaster's Mediathek identified.

    Diagnosis 0.5.15: 3,215 editions of "Schleswig-Holstein Magazin" were each queried at the ARD
    Mediathek again and took two thirds of the recognition queue without improving any result."""
    import broadcaster
    if m.get('kind')!='series' or m.get('provider') not in broadcaster.PROVIDERS or m.get('scan_requested'):return False
    topic=cleaned(source.get('topic'))
    if not topic or key(topic) in FORMAT_GENERIC or key(topic)!=key(m.get('title')):return False
    return bool(FORMAT_WORDS.search(topic)) and topic_works>=2

# Exact, established news programmes. An approximate title match or a word such
# as "heute" alone is NOT enough to classify a film or a scripted series.
# Keep this list short; each addition needs a positive and negative regression.
NEWS_TOPICS={
    'heute journal','heute in deutschland','heute in europa','hallo deutschland',
    'tagesschau','tagesthemen','heute','zdf heute','zdfheute',
    'nachtmagazin','morgenmagazin','ard morgenmagazin','zdf morgenmagazin',
    'mittagsmagazin','ard mittagsmagazin','zdf mittagsmagazin'
}
FILM_RUBRICS={
    'spielfilm','spielfilme','fernsehfilm','fernsehfilme','kino','großes kino',
    'filme','filme im ersten','film im ersten','filme im mdr','kino kino'
}
FILM_PHRASE=re.compile(
    r'(?i)\b(?:spielfilm|fernsehfilm|kinofilm|filmkomödie|kinodrama|'
    r'filmklassiker|kinoklassiker|dokumentarfilm|literaturverfilmung)\b')

def is_news_contribution(row,source=None):
    """Only explicitly known news programmes; preserve manually verified episodes.

    Run before contacting external APIs and as a format-migration fallback. A
    generic 'heute' inside a film title or synopsis never qualifies.
    """
    if not row or row['state'] in ('manual','matched','format') or row['kind'] not in ('unknown','other','series'):
        return False
    meta=json.loads(row['meta'] or '{}')
    if meta.get('scan_requested') or meta.get('episode_verified'):return False
    if source is None:return False
    topic=key(cleaned(source.get('topic')))
    if topic not in NEWS_TOPICS:return False
    duration=int(source.get('duration') or 0)
    return duration==0 or 60<=duration<=7200

def mark_news_format(c,row,source):
    """Skip pointless movie-API lookups for a specific news programme edition.

    No metadata is discarded: keep the original text, ratings and credits, but
    do not imply that its episode has an external episode ID.
    """
    if not is_news_contribution(row,source):return False
    if c.execute('SELECT 1 FROM metadata_priority WHERE work_id=?',(row['id'],)).fetchone():return False
    m=json.loads(row['meta'] or '{}')
    topic=cleaned(source.get('topic'))
    m['kind']='series';m['title']=topic;m['episode_title']=m.get('episode_title') or cleaned(source.get('title')) or topic
    m['state']='format';m['format_grouping']='news'
    m['reason']='Regelmäßige Nachrichtensendung: kein erneuter Film-/Serienanbieterabgleich erforderlich'
    m.pop('suggestions',None);m.pop('metadata_warnings',None)
    if not m.get('provider'):m['provider']='Sendung'
    m['episode_verified']=False
    m.pop('episode_reference_id',None)
    c.execute("""UPDATE works SET title=?,kind='series',show_key=?,meta=?,state='format',
        next_try=0 WHERE id=?""",(topic,showkey(m),json.dumps(m),row['id']))
    c.execute('DELETE FROM metadata_priority WHERE work_id=?',(row['id'],))
    c.execute('DELETE FROM film_hints WHERE work_id=?',(row['id'],))
    c.execute('DELETE FROM series_focus WHERE show_key=?',(row['show_key'],))
    return True

def film_likelihood(source):
    """Priority hint only, never a proof of film identity or an auto-match."""
    if not source:return 0,''
    topic=key(source.get('topic'))
    if topic in NEWS_TOPICS or FORMAT_WORDS.search(topic):return 0,''
    duration=int(source.get('duration') or 0)
    if not 2400<=duration<=15000:return 0,''
    if topic in FILM_RUBRICS:return 3,'Explizite Filmrubrik'
    if topic in FORMAT_GENERIC:return 0,''
    desc=core.clean(source.get('description',''))[:260]
    if FILM_PHRASE.search(desc):return 2,'Ausdrücklicher Filmhinweis im Sendertext'
    return 0,''

def update_film_hint(c,wid,meta,source):
    if meta.get('kind')!='unknown':return
    score,reason=film_likelihood(source)
    if score>=2:
        c.execute('INSERT OR REPLACE INTO film_hints VALUES(?,?,?)',(wid,score,reason))
    else:c.execute('DELETE FROM film_hints WHERE work_id=?',(wid,))

def backfill_film_hints(c,limit=400):
    """Resume-friendly, bounded upgrade of existing unknown work hints."""
    cursor=get_state(c,'film_hint_cursor_v0524',0)
    if cursor=='complete':return 0
    rows=c.execute("""SELECT rowid AS rid,id,meta FROM works
        WHERE rowid>? AND kind='unknown' ORDER BY rowid LIMIT ?""",(cursor,limit)).fetchall()
    for row in rows:
        cursor=row['rid']
        offer=c.execute('SELECT payload FROM offers WHERE work_id=? AND active=1 ORDER BY rank DESC LIMIT 1',(row['id'],)).fetchone()
        if offer:
            update_film_hint(c,row['id'],json.loads(row['meta']),json.loads(offer[0]))
    set_state(c,'film_hint_cursor_v0524',cursor if rows else 'complete')
    return len(rows)

# 0.6.106 (Mac-Abfrage Kinderreihen 22.11.2026): KiKA führt Ableger einer Reihe unter eigenem Thema – „KiKA LIVE fordert
# heraus“, „KiKA LIVE präsentiert“, „KiKA LIVE #ZuHauseUmDieWelt“, „KiKA LIVE - Fragen an die Astronautinnen“ (11 Reihen
# mit 2–9 Werken neben der Hauptreihe mit 641). Auf Kindersendern laufen sie unter der Hauptreihe, wenn es sie mit
# mindestens SPIN_OFF_MIN Werken gibt; der Ableger bleibt im Folgentitel sichtbar.
SPIN_OFF_MIN=20
def parent_sendung(c,fmt,source):
    """(show_key, title) of the main Reihe a kids-channel spin-off „<Reihe> <Zusatz>“ belongs to, else None."""
    if str((source or {}).get('channel') or '').strip().lower() not in KIDS_CHANNELS:return None
    import metadata
    words=str(fmt or '').split()
    for n in range(len(words)-1,1,-1):
        prefix=' '.join(words[:n]).rstrip(' -–:#·|').strip()
        if len(prefix.split())<2 or len(prefix)<5 or key(prefix)==key(fmt) or metadata.generic_topic(prefix):continue
        r=c.execute("SELECT show_key,title,COUNT(*) FROM works WHERE topic=? AND kind='series' AND COALESCE(show_key,'')!='' "
                    "GROUP BY show_key ORDER BY 3 DESC LIMIT 1",(prefix,)).fetchone()
        if r and r[2]>=SPIN_OFF_MIN:return r[0],r[1]
    return None

def file_under_sendung(c,row,m,source,fmt,grouping=None,reason=None):
    """File one offer's work as contribution of the Sendung ``fmt`` (state 'format', provider 'Sendung')."""
    import broadcaster
    hints=broadcaster.genres(fmt,source.get('title',''),names=(fmt,))
    m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings','deferred_providers')}
    edition=cleaned(source.get('title'))
    if key(edition)==key(fmt) and source.get('timestamp'):
        # Editions named like the Sendung are told apart by their broadcast date.
        try:edition+=' · '+time.strftime('%d.%m.%Y',time.localtime(int(source['timestamp'])))
        except (TypeError,ValueError,OverflowError,OSError):pass
    parent=parent_sendung(c,fmt,source)
    if parent:
        m['sendung_name']=fmt
        if not key(edition).startswith(key(fmt)):edition=fmt+': '+edition
        fmt=parent[1]
    m.update(kind='series',title=fmt,episode_title=edition,year=None,season=m.get('season'),episode=m.get('episode'),provider='Sendung',reference_id=None,
             state='format',genres=normalized_genres(hints or m.get('genres')),genre_source='Sender (abgeleitet)' if hints else m.get('genre_source','Unbekannt'),
             reason=reason or 'Beitrag der Sendung „'+fmt+'“; wird nicht mit Filmdatenbanken abgeglichen.')
    if grouping:m['format_grouping']=grouping
    c.execute("UPDATE works SET title=?,kind='series',year=NULL,show_key=?,meta=?,state='format',next_try=0 WHERE id=?",(fmt,parent[0] if parent else showkey(m),json.dumps(m),row['id']))
    c.execute('DELETE FROM work_genres WHERE work_id=?',(row['id'],))
    for g in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(row['id'],g))
    c.execute('DELETE FROM film_hints WHERE work_id=?',(row['id'],))
    return m

# Raise when the format rules change: existing catalogues then get one more format pass.
FORMAT_REV=6   # 0.6.113: clips ('other') never end open (file_open_clip); 0.5.80: clips ('other') and editions named like their Sendung; 0.6.39: dated editions (also after a check without hit)
def assign_formats(c,limit=500):
    """Group news and magazine contributions under their format and take them out of the provider scan."""
    import broadcaster
    if get_state(c,'format_rev',0)<FORMAT_REV:set_state(c,'format_cursor',0);set_state(c,'format_rev',FORMAT_REV)
    cursor=get_state(c,'format_cursor',0)
    dirty_mode=cursor=='complete'
    if dirty_mode:
        rows=c.execute('SELECT w.rowid AS rid,w.* FROM format_dirty f JOIN works w ON w.id=f.work_id ORDER BY w.rowid LIMIT ?',(limit,)).fetchall()
        if not rows:
            # Also discard stale dirty references after merged/deleted works.
            c.execute('DELETE FROM format_dirty WHERE NOT EXISTS(SELECT 1 FROM works w WHERE w.id=format_dirty.work_id)')
            return 0,0
    else:
        rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
    counts={};assigned=0
    for row in rows:
        cursor=row['rid']
        if dirty_mode:c.execute('DELETE FROM format_dirty WHERE work_id=?',(row['id'],))
        # 0.6.39: a check without any hit ('review' without suggestions) may still be a Sendung's edition.
        open_work=row['kind'] in ('unknown','other') and row['state'] in ('pending','retry','review')
        if not open_work and not (row['kind']=='series' and row['state']=='identified'):continue
        best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not best:continue
        source=json.loads(best[0])
        if foreign_version(source):
            # Only when no German version of the same work is listed.
            channels={str(x[0] or '').strip().upper() for x in c.execute("SELECT json_extract(payload,'$.channel') FROM offers WHERE work_id=?",(row['id'],))}
            source['_foreign_only']=all(foreign_version({'channel':ch}) for ch in channels)
        if open_work and row['state']=='review':
            # A check found nothing usable; only the 0.6.39 rules (dated edition, foreign ARTE version) apply.
            meta=json.loads(row['meta'] or '{}')
            if meta.get('suggestions') or meta.get('scan_requested') or not (DATED.search(cleaned(source.get('title'))) or foreign_version(source)):continue
        if mark_news_format(c,row,source):
            assigned+=1
            continue
        m=json.loads(row['meta']);topic=row['topic'] or source.get('topic') or ''
        if topic not in counts:counts[topic]=c.execute('SELECT COUNT(*) FROM works WHERE topic=?',(topic,)).fetchone()[0]
        if not open_work:
            if not broadcaster_format(m,source,counts[topic]):continue
            # Keep the broadcaster's programme data (picture, description, genres); only stop the rechecks.
            m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings')}
            m.update(state='format',reason='Ausgabe der Sendung „'+m['title']+'“ ('+m['provider']+'); wird nicht einzeln abgeglichen.')
            c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=?",(json.dumps(m),row['id']))
            assigned+=1;continue
        if row['kind']=='other' and NUMBERED_PART.search(cleaned(source.get('title'))) and open_full_programme(c,row,m,source):
            # 0.6.116: a numbered whole programme („Wetter extrem (1/3)“) is an episode, before any Sendung rule
            assigned+=1;continue
        if row['kind']=='other' and programme_extra(c,row,m,source):
            assigned+=1;continue
        if not format_contribution(m,source,counts[topic]):
            if row['kind']=='other' and (open_full_programme(c,row,m,source) or file_open_clip(c,row,m,source)):assigned+=1
            continue
        file_under_sendung(c,row,m,source,cleaned(source.get('topic')))
        assigned+=1
    if not dirty_mode:set_state(c,'format_cursor',cursor if rows else 'complete')
    return len(rows),assigned

# 0.6.116 (Mac-Prüfung 0.6.114: 128 von 900 „Extra zu …“ waren 25 min oder länger, meist ganze Sendungen –
# „Brombeerland (9/14) – Die Pressekonferenz“ 39 min, „Wetter extrem (1/3)“, Terra Xpress XXL, „27 – Das europäische
# Magazin“): the import's clip words („Pressekonferenz“, „Podcast“, „Magazin“) do not make a whole programme a clip.
FULL_PROGRAMME_SECONDS=25*60
NUMBERED_PART=re.compile(r'\(\s*\d{1,3}\s*/\s*\d{1,3}\s*\)')
AUDIO_CLIP=re.compile(r'(?i)podcast|\baudio\b|hörspiel')
PRESS_CLIP=re.compile(r'(?i)pressekonferenz|pressestatement|\bstatement\b')
def full_programme(source):
    """True for an offer that is a whole programme: ≥ 25 min, or numbered „(n/m)“ and ≥ 10 min. Never a trailer or a
    podcast („Podcast mit Nachklang (4316)“ of „Rote Rosen“ must not become a Folge); a press conference only numbered."""
    title=cleaned(source.get('title'))
    try:duration=int(source.get('duration') or 0)
    except (TypeError,ValueError):duration=0
    # 0.6.117 (Mac-Prüfung 0.6.116: „Trailer Park“, 55 min, lag als Extra unter „Theater und Tanz“): a title that only
    # begins with „Trailer“ is a trailer when it is short.
    if (TRAILER.search(title) and duration<FULL_PROGRAMME_SECONDS) or AUDIO_CLIP.search(title):return False
    numbered=bool(NUMBERED_PART.search(title))
    if PRESS_CLIP.search(title) and not numbered:return False
    return duration>=FULL_PROGRAMME_SECONDS or (duration>=600 and numbered)

def open_full_programme(c,row,m,source):
    """A whole programme the import took for a clip is recognised like any work of unknown kind (pending, first pass);
    a Sendung rule (format_contribution) still files it first. Returns True when reopened."""
    if row['kind']!='other' or row['state'] not in ('pending','format') or m.get('scan_requested') or not full_programme(source):return False
    m={k:v for k,v in m.items() if k not in ('format_grouping','related_series_title','state','reason')}
    m.update(kind='unknown',full_programme_v06116=True,reason='Ganze Sendung (nicht nur ein Clip); wird erkannt.')
    c.execute("UPDATE works SET kind='unknown',state='pending',attempts=0,next_try=0,meta=? WHERE id=?",(json.dumps(m),row['id']))
    return True

def restore_sendung_spelling(c):
    """0.6.117, once: Sendung filings with a database identity (sendung_identity, B2 since 0.6.113) named in the
    database's spelling get the broadcaster's spelling of their topic back („Kikaninchen“ → „KiKANiNCHEN“).
    show_key is unchanged (it is built from the normalised name). Returns {old: new}."""
    out={}
    for row in c.execute("""SELECT id,title,topic,meta FROM works WHERE state='format' AND kind='series'
            AND json_type(meta,'$.sendung_identity')='object' AND COALESCE(topic,'')!=''""").fetchall():
        topic=cleaned(row['topic'])
        if not topic or row['title']==topic or key(row['title'])!=key(topic):continue
        m=json.loads(row['meta'] or '{}');m['title']=topic
        reason=str(m.get('reason') or '')
        if reason:m['reason']=reason.replace('„'+str(row['title'])+'“','„'+topic+'“')
        c.execute('UPDATE works SET title=?,meta=? WHERE id=?',(topic,json.dumps(m),row['id']))
        out[row['title']]=topic
    return out

BRAND_CASE=re.compile(r'[a-zäöüß][A-ZÄÖÜ]')
def brand_spelling(t):
    """0.6.119: a deliberate brand spelling – a capital after a small letter inside a word („KiKANiNCHEN“, „kulturMATINEE“)."""
    return bool(BRAND_CASE.search(str(t or '')))

def unify_show_spelling(c):
    """0.6.118 (Mac-Prüfung 0.6.117: „KiKANiNCHEN“ 50 and „Kikaninchen“ 368 works under one show_key).
    0.6.119 (Mac-Prüfung 0.6.118: the majority rule turned it the wrong way round – „Kikaninchen“ 418, „Reporter“ →
    „reporter“, „FORUM WIRTSCHAFT“ → „forum wirtschaft“, „Trailer: SAARTHEMA“): only towards a deliberate brand spelling.
    A Reihe whose titles or topics carry exactly one brand spelling (brand_spelling) gets it for its plainly written
    variants; every other case difference stays as it is. User decisions stay. Idempotent; returns {old: new}.
    0.6.120 (Mac-Prüfung 0.6.119: ARD/MDR „Mittagsmagazin“ 289 works took SRF's „MittagsMagazin“ – one show_key over
    several senders): only works of a sender that itself writes the brand spelling (title or topic) are renamed; also
    clips and extras under the Reihe (3 „Kikaninchen“ of kind 'other' were left)."""
    shows={}
    for show,title,n in c.execute("""SELECT show_key,title,COUNT(*) FROM works WHERE COALESCE(show_key,'')!=''
            AND state!='manual' GROUP BY show_key,title"""):
        shows.setdefault(show,[]).append((title,n))
    topic_brands={}
    for show,topic in c.execute("""SELECT show_key,topic FROM works WHERE COALESCE(show_key,'')!=''
            AND COALESCE(topic,'')!='' GROUP BY show_key,topic"""):
        if brand_spelling(topic):topic_brands.setdefault(show,[]).append(cleaned(topic))
    out={}
    for show,titles in shows.items():
        by_key={}
        for title,n in titles:by_key.setdefault(key(title),[]).append(title)
        for k,variants in by_key.items():
            plain=[t for t in variants if not brand_spelling(t)]
            if not plain:continue
            brands={t for t in variants+[t for t in topic_brands.get(show,()) if key(t)==k] if brand_spelling(t)}
            if len(brands)!=1:continue
            target=brands.pop()
            channels={}
            for w in c.execute("""SELECT w.id,w.title,w.topic,(SELECT lower(trim(json_extract(o.payload,'$.channel'))) FROM offers o
                    WHERE o.work_id=w.id ORDER BY o.active DESC,o.rank DESC LIMIT 1) channel FROM works w WHERE w.show_key=?""",(show,)):
                channels[w['id']]=(w['channel'] or '',w['title']==target or cleaned(w['topic'])==target)
            brand_senders={ch for ch,brand in channels.values() if brand and ch}
            if not brand_senders:continue
            for title in plain:
                changed=False
                for w in c.execute("SELECT id,meta FROM works WHERE show_key=? AND title=? AND state!='manual'",(show,title)).fetchall():
                    if channels.get(w['id'],('',False))[0] not in brand_senders:continue
                    changed=True
                    try:m=json.loads(w['meta'] or '{}')
                    except (TypeError,ValueError):continue
                    m['title']=target
                    reason=str(m.get('reason') or '')
                    if reason:m['reason']=reason.replace('„'+str(title)+'“','„'+target+'“')
                    c.execute('UPDATE works SET title=?,meta=? WHERE id=?',(target,json.dumps(m),w['id']))
                if changed:out[title]=target
    return out

def reopen_full_programmes(c,limit=100000):
    """0.6.116, once: whole programmes 0.6.113/0.6.114 filed as „Extra zu …“ or clip are reopened. Returns (n, samples)."""
    rows=c.execute("""SELECT * FROM works WHERE kind='other' AND state='format'
        AND (json_extract(meta,'$.format_grouping')='clip' OR json_extract(meta,'$.reason') LIKE 'Extra zu „%'
             OR json_extract(meta,'$.reason') LIKE 'Trailer/Vorschau%') LIMIT ?""",(limit,)).fetchall()
    n=0;samples=[]
    for row in rows:
        m=json.loads(row['meta'] or '{}')
        if m.get('scan_requested'):continue
        source=best_source(c,row['id'])
        if not source or not open_full_programme(c,row,m,source):continue
        n+=1
        if len(samples)<20:samples.append({'title':str(source.get('title') or '')[:80],'duration':int(source.get('duration') or 0)})
    return n,samples

def programme_extra(c,row,m,source):
    """0.6.114 (Mac-Prüfung 0.6.113 E2: „Extra: Interview mit Lucia Chiarla“ wurde Beitrag einer Sendung „Es geht um
    Luis“ – so heißt ein Film): a clip whose topic is the topic of a recognised film or series (not a Sendung) is an
    extra of that programme, never a new Sendung of the same name."""
    if row['kind']!='other' or row['state']!='pending' or m.get('scan_requested'):return False
    if full_programme(source):return False     # 0.6.116: a whole programme is no extra
    topic=row['topic'] or source.get('topic') or ''
    # news/magazine clips keep joining their Sendung (0.5.80), even when a database knows the Sendung as series
    if not topic or FORMAT_WORDS.search(cleaned(topic)) or key(topic) in FORMAT_GENERIC:return False
    real=c.execute("""SELECT 1 FROM works WHERE topic=? AND id!=? AND state IN ('matched','manual')
        AND (kind='movie' OR (kind='series' AND json_extract(meta,'$.provider') IN ('TMDB','TVDB','IMDb Offline','OMDb'))) LIMIT 1""",
        (topic,row['id'])).fetchone()
    if not real:return False
    name=cleaned(source.get('topic')) or topic
    m.update(kind='other',state='format',episode_verified=False,related_series_title=name,
             reason='Extra zu „'+name+'“ (Interview, Ausschnitt, Trailer); keine vollständige Sendung, wird nicht abgeglichen.')
    c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=?",(json.dumps(m),row['id']))
    return True

def file_open_clip(c,row,m,source):
    """0.6.113 (Mac-Prüfung 0.6.108, Rückstau-Abfrage: 2.414 Werke der Art 'other' pending mit 0 Versuchen – Trailer,
    Vorschauen, Podcasts, Pressekonferenzen): the recognition never selects clips (CatalogService.pick), so a clip the
    Sendung rules (format_contribution) leave out stayed open for good. Now it ends as extra (trailer/preview) or clip
    (format_grouping 'clip', not 'single': the Einzelsendung recheck must not file it as Folge of a real series).
    Never a user decision or a requested check; „Erneut prüfen“ (prioritize) still checks it on request."""
    if row['kind']!='other' or row['state']!='pending' or m.get('scan_requested'):return False
    title=cleaned(source.get('title'));topic=cleaned(source.get('topic'))
    if TRAILER.search(title) and not full_programme(source):
        if topic:m['related_series_title']=topic
        m.update(kind='other',state='format',episode_verified=False,
                 reason='Trailer/Vorschau'+(' zu „'+topic+'“' if topic else '')+'; keine vollständige Sendung, wird nicht abgeglichen.')
        c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=?",(json.dumps(m),row['id']))
        return True
    # 0.6.113: not under the Sendung – a podcast of „Rote Rosen“ (1.056 works) would turn into a Folge of the series.
    if topic:m['related_series_title']=topic
    m.update(kind='other',state='format',format_grouping='clip',episode_verified=False,
             reason='Clip (Podcast, Pressekonferenz, Ausschnitt); keine vollständige Sendung, wird nicht abgeglichen.')
    c.execute("UPDATE works SET meta=?,state='format',next_try=0 WHERE id=?",(json.dumps(m),row['id']))
    return True

def restart_formats(c):set_state(c,'format_cursor',0)

# 0.6.43 (Björn, 20.11.2026, Nachtdiagnose 0.6.40 auf dem MacBook Air): 38,727 offene Werke blieben
# „Noch zuordnen“ (Art unbekannt), 95 % davon Einzelbeiträge von SRF, ARTE, ORF und 3Sat. Der Import
# erkennt die Art nur an Wörtern wie „Spielfilm“, „Serie“ oder „Nachrichten“; die Anbieter (IMDb, TMDB,
# TVDB, Wikidata) kennen Magazinbeiträge, Reportagen und Einzelsendungen nicht. Bisher galten die
# Sendungsregeln nur für Nachrichten-/Magazinwörter, Beiträge unter 10 Minuten und datierte Ausgaben –
# und nur beim Import, wenn die Sendung schon genug Werke hatte. Nach einem Abgleich ohne Treffer wird
# die Art jetzt aus der Sendung bestimmt:
#   Sendung mit mehreren Werken → Ausgabe, Beitrag (< 10 Min.), Teil (nummeriert) oder Folge der Sendung
#   Sendung nur mit diesem Werk oder Sammelrubrik („Dokumentation“, „Kultur - …“) → Einzelsendung
#   ausdrücklicher Filmhinweis (Filmrubrik, „Spielfilm“ im Sendertext, 40–250 Min.) → Film
# Nur Werke, die schon geprüft wurden (attempts>0) und weder Vorschläge noch Anbieterfehler haben;
# nie Benutzerentscheidungen oder angeforderte Prüfungen. „Erneut prüfen“ hebt die Einordnung auf.
UNKNOWN_SWEEP_INTERVAL=6*3600
UNKNOWN_DEFERRABLE={'ARD Mediathek','ZDF Mediathek','OMDb'}
FILM_TOPIC=re.compile(r'(?i)\b(?:film|filme|spielfilm|spielfilme|fernsehfilm|fernsehfilme|kinofilm|kino|cinema|cinéma|movie|movies)\b')
UNKNOWN_GROUPINGS={'edition':'Ausgabe','segment':'Beitrag','part':'Teil','contribution':'Folge','single':'Einzelsendung','movie':'Film'}

def unknown_open_reason(row,m):
    """None if a work of unknown kind may be classified locally, else the reason it waits."""
    hard=unknown_hard_reason(row,m)
    if hard:return hard
    if m.get('suggestions'):return 'suggestions'
    if m.get('metadata_warnings'):return 'warnings'
    return None

def unknown_hard_reason(row,m):
    """Reasons no rule may override: user decision, user request, unchecked, provider still to come."""
    if row['state'] in ('manual','matched','format','identified'):return 'state'
    if m.get('scan_requested') or m.get('live'):return 'requested'
    if not int(row['attempts'] or 0):return 'unchecked'
    if set(m.get('deferred_providers') or [])-UNKNOWN_DEFERRABLE:return 'deferred'
    return None

# 0.6.49 (Diagnose 20.11.2026 abends, M3 Pro): after the 0.6.43 sweep 21,189 works stayed "Art unbekannt",
# 19,113 of them only because of film database suggestions (14,270) or an old provider error (4,756).
# Most suggestions of a magazine contribution are no evidence against its Sendung: a feature film of the
# same name that is 80 minutes longer, a fuzzy title, or the Sendung itself listed several times at IMDb
# ("DOK", "Forum", "Talkabout" – three series of that name, so no automatic choice). Such suggestions are
# set aside, not deleted: they stay in the work (unknown_before) and "Erneut prüfen" brings them back.
# A suggestion that could be right (same title as a film of matching length, another series of exactly
# this title) keeps the work open. Einzelsendungen and films are never decided against a suggestion.
# 0.6.78 (Mac-Prüfung 0.6.77): rev 6 for the Wikidata rule of 0.6.77; without the raise the sweep waited up to
# UNKNOWN_SWEEP_INTERVAL (6 h) after the update, so the check saw no effect within 30 minutes.
UNKNOWN_RULES_REV=8              # 0.6.108: re-pass for 0.6.97 rules (Mac-Prüfung B2: never ran on existing works); 0.6.88: Sendungsvorschlag → Folge; raise when the rules change: the next sweep then runs at once
SENDUNG_GROUPINGS=('edition','segment','part','contribution')
UNKNOWN_SUGGESTION_MIN_WORKS=3   # a Sendung with at least this many works outweighs weak suggestions
UNKNOWN_WARNING_ATTEMPTS=3       # a provider error that came back on this many checks no longer blocks

# 0.6.49 correction (Gegenprobe an einer Kopie von Björns Datenbank, 20.11.2026): "the Sendung itself" set aside
# 5,561 works whose suggestion was the right series – NACHTCAFÉ (IMDb tt0862613), 1 gegen 100, Sag die Wahrheit
# (TVDB with matching episode titles), Teletubbies, frontal. A series suggestion of the Sendung's name is evidence
# for the work, not against it. Only an old namesake whose start lies decades before the broadcast (Top Secret
# 1954, Made in Germany 1963, Arena 1975) or after it is no evidence. In doubt the work stays open.
UNKNOWN_NAMESAKE_YEARS=50

def broadcast_year(source):
    try:return time.localtime(int(source.get('timestamp') or 0)).tm_year if int(source.get('timestamp') or 0)>0 else None
    except (TypeError,ValueError,OverflowError,OSError):return None

def _year(value):
    m=re.search(r'(?<!\d)(18\d\d|19\d\d|20\d\d|210\d)(?!\d)',str(value or ''))
    return int(m.group(1)) if m else None

def suggestion_brief(s):
    """The fields of a suggestion that decide the rule, for the diagnosis (no descriptions or pictures)."""
    if not isinstance(s,dict):return {'invalid':True}
    out={k:s.get(k) for k in ('provider','kind','title','year','reference_id','similarity','confidence','runtime_mismatch',
                               'year_mismatch','episode_verified','season','episode') if s.get(k) not in (None,'',False)}
    if 'title' in out:out['title']=str(out['title'])[:80]
    return out

def old_wikidata_suggestion(s):
    """0.6.77 (Nachtdiagnose 21.11.2026): Wikidata suggestions stored before the film/programme filter of 0.6.58
    ("Malik Harris", "Midge Ure", "Sophie & The Giants", "Großkatzen" as kind movie) held 6.121 works without a
    kind. Without the filter's stamp an "unknown_type" item with only possible confidence is no evidence."""
    return (isinstance(s,dict) and s.get('provider')=='Wikidata' and s.get('evidence_type')=='unknown_type'
            and s.get('confidence')!='high' and not s.get('wikidata_rev'))

def suggestion_weak(s,source,sendung,work_title=''):
    """True if a film database suggestion is no evidence against filing the work under ``sendung``."""
    if not isinstance(s,dict):return True
    if old_wikidata_suggestion(s):return True
    kind=s.get('kind')
    try:similarity=float(s.get('similarity') or 0)
    except (TypeError,ValueError):similarity=0.0
    if kind=='movie' and sendung and work_title and key(s.get('title'))==key(sendung) and key(work_title)!=key(sendung):
        # A film named like the Sendung ("Top Secret!" 1984 for the episodes of "Top Secret"): one film cannot
        # be each of the Sendung's differently titled episodes.
        return True
    if kind=='series':
        # Episode evidence (TVDB/IMDb episode titles, season and episode) is never weak.
        if s.get('episode_verified') or (s.get('season') is not None and s.get('episode') is not None):return False
        # Third Gegenprobe (20.11.2026): Wikidata answers a generic Sendung name with the concept itself
        # ("Reise" Q36875808, "Musik" Q638 for 1,277 works of 3sat), confidence "possible" and no year.
        if s.get('provider')=='Wikidata' and s.get('confidence')!='high' and not _year(s.get('year')):return True
        # Only the Sendung's exact name counts as the Sendung; a fuzzy match is no evidence ("...von oben" →
        # TMDB "3 von oben", similarity 0.889, held 3sat's 2023–2025 "… von oben" films open).
        same=bool(sendung) and key(s.get('title'))==key(sendung)
        if same or similarity>=.985:
            # The Sendung's own name: only a namesake far outside the broadcast period is no evidence.
            year=_year(s.get('year'));aired=broadcast_year(source)
            if year and aired and (year>aired+1 or aired-year>=UNKNOWN_NAMESAKE_YEARS):return True
            return False
        return True
    if kind=='movie':
        if s.get('runtime_mismatch') or s.get('year_mismatch'):return True
        duration=int(source.get('duration') or 0)
        return similarity<.985 and 0<duration<2400
    return similarity<.985

def unknown_recheck_set_aside(c):
    """Once after the 0.6.49 correction: works the first 0.6.49 sweep filed against a suggestion that is no
    longer weak are open again, with their suggestions and their earlier state. Returns the number reopened."""
    if get_state(c,'unknown_set_aside_fix_v0649b'):return 0
    reopened=0;kept=[]
    rows=c.execute("""SELECT * FROM works WHERE state='format' AND kind IN ('series','other')
        AND json_extract(meta,'$.unknown_before.rev')=2 AND json_extract(meta,'$.unknown_before.suggestions') IS NOT NULL""").fetchall()
    for row in rows:
        m=json.loads(row['meta'] or '{}');before=m.get('unknown_before') or {}
        source=best_source(c,row['id']) or {}
        name=m.get('title') if row['kind']=='series' else ''
        work_title=cleaned(source.get('title'))
        weak=[suggestion_weak(x,source,name,work_title) for x in before.get('suggestions') or []]
        if all(weak):
            if len(kept)<25:kept.append({'title':work_title[:80],'sendung':str(name)[:80],'duration':int(source.get('duration') or 0),
                                         'year_aired':broadcast_year(source),'suggestions':[suggestion_brief(x) for x in (before.get('suggestions') or [])[:3]]})
            continue
        restored=restore_unknown(m)
        if not restored:continue
        title,kind,meta=restored
        c.execute("UPDATE works SET title=?,kind=?,show_key='',meta=?,state=?,next_try=0 WHERE id=?",
                  (title,kind,json.dumps(meta),before.get('state') or ('retry' if before.get('metadata_warnings') else 'review'),row['id']))
        c.execute('DELETE FROM episode_queue WHERE work_id=?',(row['id'],))
        reopened+=1
    set_state(c,'unknown_set_aside_fix_v0649b',{'reopened':reopened,'checked':len(rows),'kept':len(rows)-reopened,
                                                 'kept_samples':kept,'at':time.time()})
    return reopened

def unknown_soft_check(row,m,source,grouping,name,topic_works):
    """None if suggestions/provider errors do not stand against ``grouping``, else the reason to wait."""
    suggestions=[x for x in (m.get('suggestions') or []) if x]
    if suggestions:
        if grouping not in SENDUNG_GROUPINGS:
            # Analyse der Datenbankkopie (20.11.2026, 13,004 open works): under a rubric the series lookup asks for
            # the rubric name; Wikidata answers with the concept ("Reise", "Musik", "Wirtschaft", hr-Sinfonieorchester,
            # 4,684 works) and TVDB/TMDB with fuzzy names ("Politik" → "POLITI", "Politika"). Series hits of that
            # kind say nothing about the work itself; an Einzelsendung may be decided against them. A film
            # suggestion still keeps it open (it may be the programme itself).
            if grouping=='single' and all(isinstance(x,dict) and x.get('kind')=='series' and suggestion_weak(x,source,'',cleaned(source.get('title')))
                                          for x in suggestions):
                pass
            else:return 'suggestions_no_sendung'
        elif topic_works<UNKNOWN_SUGGESTION_MIN_WORKS:return 'suggestions_small_sendung'
        elif not all(suggestion_weak(x,source,name,cleaned(source.get('title'))) for x in suggestions):return 'suggestions'
    if m.get('metadata_warnings') and int(row['attempts'] or 0)<UNKNOWN_WARNING_ATTEMPTS and not wikidata_only_warnings(m):return 'warnings'
    return None

def wikidata_only_warnings(m):
    """0.6.89 (Diagnose Pro 22.11.2026: 4.177 ARD works held as „warnings“, the warnings in the log only
    „Wikidata: HTTP 429“ from the rate-limit series of 21.11.): a Wikidata error alone does not hold a work open;
    IMDb Offline, TMDB and TVDB answered, and Wikidata alone never decides a kind."""
    warnings=[str(w) for w in (m.get('metadata_warnings') or [])]
    return bool(warnings) and all(w.startswith('Wikidata:') for w in warnings)

# 0.6.88 (Diagnose Pro 22.11.2026: 4.692 Werke ohne Art „mit Sendungsvorschlag“, SRF 2.215, ARTE.DE 1.451):
# the suggestion that holds the work open is the Sendung itself (exact name, broadcast period). Then the work is a
# Folge of that series: identified with the series' identity, the episode queue looks for the episode.
SENDUNG_SUGGESTION_ORDER=('IMDb Offline','TVDB','TMDB','OMDb','Wikidata')

# 0.6.97 (Mac-Prüfung 0.6.88, nicht bestanden: 74 von 1.223 Werken falsch): Wikidata nannte einzelne Folgen fremder
# Serien („Wahrheit oder Pflicht“ Q50386201, „Zurück zur Natur“ Q62122968, „Verkehrte Welt“, „Die Bruderschaft“,
# „Das Tribunal“ – 61 Werke), IMDb Namensvettern ohne Jahr („Headhunter“ tt24510162, „Lipstick“ tt14445290) und unter
# dem Thema „3sat“ (nur der Sender) einen Namensvetter („Entführt“ tt3625998). Keine dieser Quellen genügt allein.
SENDER_TOPICS={'3sat','ard','zdf','arte','kika','srf','orf','phoenix','dw','br','hr','mdr','ndr','rbb','sr','swr','wdr','one',
               'zdfneo','zdfinfo','tagesschau24','ard-alpha','mediathek','ard mediathek','zdf mediathek','filme im ersten'}

def sender_topic(source):
    """True if the offer's topic only names the broadcaster or its Mediathek (no Sendung)."""
    topic=key(cleaned(source.get('topic')))
    return bool(topic) and (topic in SENDER_TOPICS or topic in PORTAL_TOPICS or topic==key(source.get('channel')))

def sendung_suggestion_ok(x,source):
    """The rules 0.6.97 adds for the chosen suggestion: no Wikidata, a year, a topic that is more than the sender."""
    return (x.get('provider')!='Wikidata' and _year(x.get('year')) is not None and not sender_topic(source))

def sendung_suggestion(m,source,sendung):
    """The series suggestion to identify a work of unknown kind with, or None.

    Only when every suggestion that is no weak evidence (suggestion_weak) is a series with exactly the Sendung's
    name and with a reference, and no database names two different series of that name (namesakes stay open).
    0.6.97: Wikidata suggestions never decide (they stay evidence), the chosen one needs a year, and an offer filed
    only under its sender („3sat“) is never identified this way."""
    if not sendung or not template_topic(sendung) or sender_topic(source):return None
    work_title=cleaned(source.get('title'))
    strong=[x for x in (m.get('suggestions') or []) if isinstance(x,dict) and not suggestion_weak(x,source,sendung,work_title)]
    if not strong:return None
    refs={}
    for x in strong:
        if x.get('kind')!='series' or key(x.get('title'))!=key(sendung) or not x.get('reference_id') or not x.get('provider'):return None
        refs.setdefault(x['provider'],set()).add(str(x['reference_id']))
    if any(len(v)>1 for v in refs.values()):return None
    usable=[x for x in strong if sendung_suggestion_ok(x,source)]
    if not usable:return None
    rank={p:i for i,p in enumerate(SENDUNG_SUGGESTION_ORDER)}
    return sorted(usable,key=lambda x:rank.get(x.get('provider'),len(rank)))[0]

YEAR_CLOSE_REASON='Film: Titel und Laufzeit stimmen, Jahr ein Jahr versetzt (Produktions-/Erscheinungsjahr)'
def undo_short_year_close(c):
    """0.6.108, once: films matched by the 0.6.97 year rule from a clip (< matching.YEAR_CLOSE_MIN_SECONDS: SRF „Dai,
    domanda!“ „Sport“ 9 min, „Moda“ 10 min) are recognised again from the sender data. Returns [(id,title)]."""
    import matching
    out=[]
    for row in c.execute("SELECT * FROM works WHERE kind='movie' AND state='matched' AND json_extract(meta,'$.reason')=?",(YEAR_CLOSE_REASON,)).fetchall():
        offer=c.execute('SELECT payload FROM offers WHERE work_id=? AND active=1 ORDER BY rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not offer:continue
        source=json.loads(offer[0] or '{}')
        try:duration=float(source.get('duration') or 0)
        except (TypeError,ValueError):duration=0
        if duration>=matching.YEAR_CLOSE_MIN_SECONDS:continue
        fresh=seed(source);fresh['reason']='0.6.108: Kurzclip, kein Film (Jahr-±1-Regel zurückgenommen)';fresh['year_close_undone_v06108']=True
        c.execute("UPDATE works SET title=?,kind=?,year=?,show_key=?,meta=?,state='pending',next_try=0 WHERE id=?",
                  (fresh['title'],fresh['kind'],fresh.get('year'),showkey(fresh),json.dumps(fresh),row['id']))
        out.append((row['id'],row['title']))
    return out

def rematch_movie_suggestions(c,after='',limit=500):
    """0.6.97, once: films „prüfen“ whose stored suggestions the year rule (matching.year_close) now accepts are
    matched. Returns (matched, last id or None)."""
    rows=c.execute("""SELECT * FROM works WHERE id>? AND kind='movie' AND state='review'
        AND json_array_length(meta,'$.suggestions')>0 ORDER BY id LIMIT ?""",(after,limit)).fetchall()
    done=0
    for row in rows:
        m=json.loads(row['meta'] or '{}')
        if m.get('scan_requested'):continue
        offer=c.execute("SELECT json_extract(payload,'$.duration') FROM offers WHERE work_id=? AND active=1 ORDER BY rank DESC LIMIT 1",(row['id'],)).fetchone()
        try:duration=float(offer[0]) if offer and offer[0] else 0
        except (TypeError,ValueError):duration=0
        usable=[dict(x,source_duration_seconds=x.get('source_duration_seconds') or duration) for x in m.get('suggestions') or []
                if isinstance(x,dict) and x.get('kind')=='movie']
        judged=match_meta(m,{'title':row['title']})
        chosen=auto_choice(judged,usable)
        if not chosen or chosen.get('kind')!='movie':continue
        if str(chosen.get('year'))==str(judged.get('year')):chosen.update(state='auto_matched',reason='Titel und Jahr aus dem Sendertitel stimmen überein')
        else:chosen.update(state='auto_matched',year_close=True,reason=YEAR_CLOSE_REASON)
        save_metadata(c,row['id'],chosen,'matched');done+=1
    return done,(rows[-1]['id'] if rows else None)

def film_suffix_works(c):
    """0.6.97: ids of open films/unknown works whose title carries 3sat's „- Spielfilm, Land Jahr“ (searched again)."""
    import metadata
    rows=c.execute("""SELECT id,title FROM works WHERE kind IN ('movie','unknown') AND state IN ('review','retry','pending')
        AND (title LIKE '% - Spielfilm,%' OR title LIKE '% - Fernsehfilm,%' OR title LIKE '% - Dokumentarfilm%' OR title LIKE '% - Kurzfilm,%'
             OR title LIKE '% - Animationsfilm,%' OR title LIKE '% - Fernsehspiel,%' OR title LIKE '% - Stummfilm,%' OR title LIKE '% - Musikfilm,%')""").fetchall()
    return [r[0] for r in rows if metadata.film_suffix_year(r[1])]

def heal_series_spelling(c):
    """Once (0.6.109): series named like their Reihe except for case take the broadcaster's spelling where
    broadcaster_spelling allows it (most offers). Returns (works, {new name: works}, [(show_key, old, new)]) – the
    pairs are kept in catalog_state so that a later version can undo them exactly."""
    best={}
    for show,title,topic,n in c.execute("SELECT show_key,title,topic,COUNT(*) FROM works WHERE kind='series' AND COALESCE(show_key,'')!='' "
                                        "AND COALESCE(topic,'')!='' AND lower(title)=lower(topic) GROUP BY 1,2,3"):
        if n>best.get((show,title),(0,''))[0]:best[(show,title)]=(n,topic)
    done=0;shows={};pairs=[]
    for (show,title),(n,topic) in best.items():
        if topic==title or not broadcaster_spelling(title,topic):continue      # the most frequent spelling decides, not any spelling
        k=c.execute("UPDATE works SET title=?,meta=json_set(meta,'$.title',?) WHERE show_key=? AND title=?",(topic,topic,show,title)).rowcount
        done+=k;shows[topic]=shows.get(topic,0)+k;pairs.append((show,title,topic))
    return done,shows,pairs

def old_spelling_rule_ran(c):
    """The 0.6.106 spelling rule (Mac-Prüfung A1: rund 15.000 Titel schlechter) ran on this catalogue: its merker
    stored 'spelled' (0.6.109 stores only 'moved' there)."""
    st=get_state(c,'series_names_v06106',None)
    return isinstance(st,dict) and 'spelled' in st

def restore_unstyled_series_titles(c):
    """Once (0.6.109), only where the 0.6.106 rule ran: a series title in ganz groß/ganz klein goes back to a mixed
    spelling found in the work's own offers (Thema oder Titel), the most frequent one. Never anything else: on a
    catalogue without the old rule nothing changes. Returns (works, [(show_key, old, new)])."""
    if not old_spelling_rule_ran(c):return 0,[]
    shows={}
    for show,title in c.execute("SELECT DISTINCT show_key,title FROM works WHERE kind='series' AND COALESCE(show_key,'')!=''"):
        if _all_upper(title) or _all_lower(title):shows[(show,title)]={}
    for (show,title),seen in shows.items():
        for topic,name in c.execute("""SELECT json_extract(o.payload,'$.topic'),json_extract(o.payload,'$.title') FROM works w
                JOIN offers o ON o.work_id=w.id WHERE w.show_key=? AND w.title=?""",(show,title)):
            for text in (topic,name):
                text=str(text or '').strip()
                if text and text.casefold()==title.casefold() and not _all_upper(text) and not _all_lower(text):
                    seen[text]=seen.get(text,0)+1
    done=0;pairs=[]
    for (show,title),seen in shows.items():
        if not seen:continue
        best=max(sorted(seen),key=lambda t:seen[t])
        done+=c.execute("UPDATE works SET title=?,meta=json_set(meta,'$.title',?) WHERE show_key=? AND title=?",(best,best,show,title)).rowcount
        pairs.append((show,title,best))
    return done,pairs

# 0.6.117 (Mac-Prüfung 0.6.115/0.6.116: „Dein Song 2023“, „Dein Song 2024“, „Dein Song 2025“ als eigene Kacheln):
# a broadcaster topic „<Reihe> <Jahr>“ names a Staffel/Jahrgang of the Reihe. Sendung filings of several such years
# with the same stem and sender become one Reihe; the year stays in the Folgentitel. Not for films or database
# identities (only provider 'Sendung'), not for single years („Berlin 1945“), not for events whose year is the
# event („Olympia 2024“, „Fußball-EM 2021“, „Bundestagswahl 2025“), not for years outside 2000..next year.
YEAR_EDITION=re.compile(r'^(?P<stem>.*?\S)[\s\-–:·|,(]+(?P<year>20\d{2})\)?$')
YEAR_EVENT=re.compile(r'(?i)\b(?:olympia\w*|olympische|paralympics|wm|em|weltmeisterschaft\w*|europameisterschaft\w*|'
                      r'world cup|euro|tour de france|wahl\w*|\w*wahl|wahlen|jahresrückblick\w*|rückblick|silvester\w*|'
                      r'neujahr\w*|karneval\w*|fastnacht\w*|fasching\w*|festival\w*|gipfel|spiele)\b')
YEAR_EDITION_MIN_WORKS=2
def year_edition(title):
    """(stem, year) when ``title`` is „<Reihe> <Jahr>“ with a usable stem, else None."""
    import metadata
    mt=YEAR_EDITION.match(str(title or '').strip())
    if not mt:return None
    stem=mt.group('stem').rstrip(' -–:·|,(').strip();year=int(mt.group('year'))
    if not 2000<=year<=time.localtime().tm_year+1:return None
    if len(key(stem))<3 or not re.search(r'[^\W\d_]',stem) or metadata.generic_topic(stem) or YEAR_EVENT.search(stem):return None
    if key(stem) in FORMAT_GENERIC:return None
    return stem,year

def merge_year_editions(c):
    """Idempotent (every format pass): Sendung filings „<Reihe> <Jahr>“ of at least two years (0.6.118: together more than
    YEAR_EDITION_MIN_WORKS works) go under one Reihe „<Reihe>“. Returns (moved, {Reihe: [years]})."""
    groups={}
    for show,title,n in c.execute("""SELECT show_key,title,COUNT(*) FROM works WHERE kind='series' AND state='format'
            AND json_extract(meta,'$.provider')='Sendung' AND title GLOB '*20[0-9][0-9]*' GROUP BY show_key,title"""):
        hit=year_edition(title)
        if not hit:continue
        ch=c.execute("""SELECT lower(trim(json_extract(o.payload,'$.channel'))) FROM works w JOIN offers o ON o.work_id=w.id
            WHERE w.show_key=? AND w.title=? ORDER BY o.active DESC LIMIT 1""",(show,title)).fetchone()
        groups.setdefault(key(hit[0]),[]).append((show,title,hit[0],hit[1],n,ch[0] if ch else ''))
    moved=0;merged={}
    for stem_key,found in groups.items():
        # 0.6.118 (Mac-Prüfung 0.6.117: „Dein Song 2022“–„2026“ with 1–6 works each stayed apart): one work per year is
        # enough when the Reihe has YEAR_EDITION_MIN_WORKS+1 works over at least two years; editions of different
        # senders (ZDF/KiKA) are one Reihe from three years on, otherwise the sender with most works decides.
        years={x[3] for x in found}
        if len(years)<2 or sum(x[4] for x in found)<=YEAR_EDITION_MIN_WORKS:continue
        if len(years)<3:
            senders={}
            for x in found:senders[x[5]]=senders.get(x[5],0)+x[4]
            main=max(senders,key=senders.get)
            found=[x for x in found if x[5] in (main,'')]
            if len({x[3] for x in found})<2:continue
        items=[x[:4] for x in found]
        stem=sorted((x[2] for x in items),key=len)[0]
        own=c.execute("""SELECT show_key,title FROM works WHERE kind='series' AND state='format' AND json_extract(meta,'$.provider')='Sendung'
            AND title=? AND COALESCE(show_key,'')!='' LIMIT 1""",(stem,)).fetchone()
        # 0.6.118: „Dein Song“ appeared twice in the Kinderecke – the Reihe may already be known under its database identity
        own=own or c.execute("""SELECT show_key,title FROM works WHERE kind='series' AND state IN ('identified','matched','format')
            AND lower(title)=lower(?) AND COALESCE(show_key,'')!='' GROUP BY show_key ORDER BY COUNT(*) DESC LIMIT 1""",(stem,)).fetchone()
        target=own[0] if own else showkey({'kind':'series','title':stem})
        if own and key(own[1])==key(stem):stem=own[1]
        for show,title,_,year in items:
            for w in c.execute("SELECT id,meta FROM works WHERE show_key=? AND title=?",(show,title)).fetchall():
                m=json.loads(w['meta'] or '{}')
                if m.get('provider')!='Sendung':continue
                ep=str(m.get('episode_title') or '')
                if not key(ep).startswith(key(title)):ep=title+': '+ep if ep else title
                m.update(title=stem,episode_title=ep,sendung_name=title,year_edition_v06117=year)
                c.execute("UPDATE works SET title=?,show_key=?,meta=? WHERE id=?",(stem,target,json.dumps(m),w['id']));moved+=1
        merged[stem]=sorted({y for *_,y in items})
    n,opened=merge_open_year_editions(c)
    moved+=n
    for stem,years in opened.items():merged[stem]=sorted(set(merged.get(stem,[]))|set(years))
    return moved,merged

YEAR_EDITION_REIHE_MIN=10
def merge_open_year_editions(c):
    """0.6.119 (Mac-Prüfung 0.6.118: „Dein Song 2022“–„2026“, 17 works, all „prüfen“ – merge_year_editions only saw
    filed Sendungen): open works („prüfen“/retry) named „<Reihe> <Jahr>“ are filed as contributions of that Reihe when
    it is known with at least YEAR_EDITION_REIHE_MIN works (any identity), or – without such a Reihe – when they span
    two years with more than YEAR_EDITION_MIN_WORKS works. Returns (moved, {Reihe: [years]})."""
    groups={}
    for row in c.execute("""SELECT * FROM works WHERE state IN ('review','retry') AND kind IN ('series','unknown')
            AND title GLOB '*20[0-9][0-9]*'""").fetchall():
        hit=year_edition(row['title'])
        if hit:groups.setdefault(key(hit[0]),[]).append((row,hit[0],hit[1]))
    moved=0;merged={}
    for stem_key,items in groups.items():
        stem=sorted((x[1] for x in items),key=len)[0]
        known=[r for r in c.execute("""SELECT show_key,title,COUNT(*) n FROM works WHERE kind='series' AND state IN ('identified','matched','format')
                AND title=? COLLATE NOCASE AND COALESCE(show_key,'')!='' GROUP BY show_key ORDER BY n DESC""",(stem,)).fetchall()
               if key(r['title'])==stem_key]
        target=known[0] if known and known[0]['n']>=YEAR_EDITION_REIHE_MIN else None
        if not target and (len({y for *_,y in items})<2 or len(items)<=YEAR_EDITION_MIN_WORKS):continue
        name=target['title'] if target else stem
        for row,_,year in items:
            try:m=json.loads(row['meta'] or '{}')
            except (TypeError,ValueError):continue
            if m.get('scan_requested'):continue
            source=best_source(c,row['id'])
            if not source:continue
            filed=file_under_sendung(c,row,m,source,name,'contribution',
                                     reason='Jahrgang %d der Sendung „%s“; wird nicht mit Filmdatenbanken abgeglichen.'%(year,name))
            ep=str(filed.get('episode_title') or '')
            if not key(ep).startswith(key(row['title'])):ep=row['title']+': '+ep if ep else row['title']
            filed.update(episode_title=ep,sendung_name=row['title'],year_edition_v06119=year)
            show=target['show_key'] if target else showkey({'kind':'series','title':name})
            c.execute("UPDATE works SET title=?,show_key=?,meta=? WHERE id=?",(name,show,json.dumps(filed),row['id']));moved+=1
            merged.setdefault(name,set()).add(year)
    return moved,{k:sorted(v) for k,v in merged.items()}

def heal_kids_spinoffs(c):
    """Once (0.6.106): Sendung filings of kids-channel spin-offs („KiKA LIVE fordert heraus“) move under the main Reihe."""
    moved=0;shows={}
    rows=c.execute("SELECT show_key,title,MIN(id) FROM works WHERE kind='series' AND state='format' AND COALESCE(show_key,'')!='' "
                   "AND json_extract(meta,'$.provider')='Sendung' GROUP BY show_key,title").fetchall()
    for show,title,wid in rows:
        if len(str(title or '').split())<3:continue
        ch=c.execute("SELECT json_extract(o.payload,'$.channel') FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 "
                     "WHERE w.show_key=? LIMIT 1",(show,)).fetchone()
        parent=parent_sendung(c,title,{'channel':ch[0] if ch else ''})
        if not parent or parent[0]==show:continue
        for w in c.execute("SELECT id,meta FROM works WHERE show_key=? AND title=?",(show,title)).fetchall():
            m=json.loads(w['meta'])
            if m.get('provider')!='Sendung':continue
            ep=str(m.get('episode_title') or '')
            if not key(ep).startswith(key(title)):ep=title+': '+ep if ep else title
            m.update(title=parent[1],episode_title=ep,sendung_name=title,spin_off_v06106=True)
            c.execute("UPDATE works SET title=?,show_key=?,meta=? WHERE id=?",(parent[1],parent[0],json.dumps(m),w['id']));moved+=1
        shows[title]=parent[1]
    return moved,shows

def heal_sendung_suggestions(c,after='',limit=500):
    """0.6.97, once: works 0.6.88–0.6.98 identified or filed from a suggestion the 0.6.97 rules no longer accept are
    open works of unknown kind again (with their suggestions; the next sweep decides with the new rules).
    Returns (reopened, shows {title: n}, last id or None)."""
    rows=c.execute("""SELECT * FROM works WHERE id>? AND (json_extract(meta,'$.sendung_suggestion_v0688')=1
        OR json_type(meta,'$.sendung_identity')='object') ORDER BY id LIMIT ?""",(after,limit)).fetchall()
    reopened=0;shows={}
    for row in rows:
        if row['state'] in ('manual','matched'):continue
        m=json.loads(row['meta'] or '{}')
        if m.get('episode_verified'):continue
        identity=m.get('sendung_identity') if isinstance(m.get('sendung_identity'),dict) else {k:m.get(k) for k in ('provider','reference_id','year')}
        source=best_source(c,row['id']) or {}
        if sendung_suggestion_ok(identity,source):continue
        restored=restore_unknown(m)
        if not restored:continue
        title,kind,meta=restored
        for k in ('sendung_suggestion_v0688','sendung_identity','sendung_grouping'):meta.pop(k,None)
        meta['sendung_suggestion_undone_v0697']=True
        c.execute("UPDATE works SET title=?,kind=?,show_key='',meta=?,state='review',next_try=0 WHERE id=?",(title,kind,json.dumps(meta),row['id']))
        c.execute('DELETE FROM episode_queue WHERE work_id=?',(row['id'],))
        reopened+=1;name=str(m.get('title') or row['title'])[:80];shows[name]=shows.get(name,0)+1
    return reopened,shows,(rows[-1]['id'] if rows else None)

def sendung_has_episodes(suggestion):
    """Whether IMDb lists single episodes for the suggested series (None while the archive is not ready: then the
    work waits, as before 0.6.88). A Wikidata identity without IMDb ID has none to search."""
    import imdb_archive
    archive=imdb_archive.ACTIVE
    if not archive or not getattr(archive,'updated',0):return None
    if suggestion.get('provider')=='Wikidata' and not imdb_archive.series_reference(suggestion):return False
    try:return bool(archive.series_has_episodes({**suggestion,'kind':'series'}))
    except Exception as exc:
        # 0.6.114: never silent – a failing lookup looked like "archive not ready" (Mac-Prüfung 0.6.113 E3)
        global _HAS_EPISODES_LOGGED
        if time.time()-_HAS_EPISODES_LOGGED>600:
            _HAS_EPISODES_LOGGED=time.time()
            import diagnostics
            diagnostics.error('sendung_has_episodes_failed',exc,title=str(suggestion.get('title') or '')[:80])
        return None
_HAS_EPISODES_LOGGED=0

def file_sendung_without_episodes(c,row,m,source,suggestion,sendung,grouping):
    """File ``row`` under the Sendung (state 'format') and keep the Sendung's database identity as a note."""
    # 0.6.117 (Mac-Prüfung 0.6.116: „KiKANiNCHEN“ landete unter „Kikaninchen“): the Sendung keeps the broadcaster's
    # spelling of its name; the database spelling stays in sendung_identity.
    topic=cleaned((source or {}).get('topic'))
    if topic and key(topic)==key(sendung):sendung=topic
    own=dict(m);own['unknown_before']=unknown_before(row,m)
    own['sendung_identity']={k:suggestion.get(k) for k in ('provider','reference_id','title','year') if suggestion.get(k) not in (None,'')}
    label=UNKNOWN_GROUPINGS.get(grouping,'Folge')
    return file_under_sendung(c,row,own,source,sendung,grouping,
        reason=label+' der Sendung „'+sendung+'“ ('+str(suggestion.get('provider'))+' kennt die Sendung, aber keine Einzelfolgen); '
               'wird deshalb nicht einzeln abgeglichen.')

def refile_sendung_suggestions(c,show_key,provider,reference,limit=2000):
    """0.6.92: works 0.6.88 identified as Folge of a suggested Sendung whose series IMDb lists without episodes are
    filed under the Sendung (all of the series at once). Returns the number filed."""
    if not show_key or not provider or not reference:return 0
    rows=c.execute("""SELECT * FROM works WHERE show_key=? AND state='identified' AND json_extract(meta,'$.sendung_suggestion_v0688')=1
        AND json_extract(meta,'$.provider')=? AND CAST(json_extract(meta,'$.reference_id') AS TEXT)=? LIMIT ?""",
        (show_key,provider,str(reference),limit)).fetchall()
    done=0
    for row in rows:
        m=json.loads(row['meta'] or '{}');source=best_source(c,row['id'])
        if not source:continue
        before=m.get('unknown_before') or {}
        identity={k:m.get(k) for k in ('provider','reference_id','title','year') if m.get(k) not in (None,'')}
        base={k:v for k,v in m.items() if k not in ('provider','reference_id','sendung_suggestion_v0688','state')}
        base['unknown_before']=before
        sendung=m.get('title') or row['title']
        file_sendung_without_episodes(c,row,base,source,identity,sendung,m.get('sendung_grouping') or 'contribution')
        done+=1
    return done

def refile_suggested_sendungen(c,after='',limit=5000):
    """0.6.113 (Mac-Prüfung 0.6.108, B2 nicht nachweisbar): the works 0.6.88 identified as Folge of a suggested
    Sendung rest 30 days in the episode queue after their first search (and siblings without the marker park them
    again), so a Sendung without IMDb episodes was never filed. Every such Sendung is decided here at once from the
    local IMDb archive, page by page (show_key > ``after``).
    Returns (refiled works, {Sendung: works}, kept Sendungen, last show_key or None when done; False = archive not ready)."""
    groups=c.execute("""SELECT show_key,json_extract(meta,'$.provider') provider,CAST(json_extract(meta,'$.reference_id') AS TEXT) ref,
            MAX(json_extract(meta,'$.title')) title,MAX(json_extract(meta,'$.year')) year,MAX(json_extract(meta,'$.imdb_id')) imdb_id
        FROM works WHERE state='identified' AND json_extract(meta,'$.sendung_suggestion_v0688')=1 AND show_key>?
        GROUP BY 1,2,3 ORDER BY 1 LIMIT ?""",(after,limit)).fetchall()
    refiled=0;shows={};kept=0
    for g in groups:
        identity={'provider':g['provider'],'reference_id':g['ref'],'title':g['title'],'year':g['year'],'imdb_id':g['imdb_id']}
        episodes=sendung_has_episodes({k:v for k,v in identity.items() if v not in (None,'')})
        if episodes is None:return refiled,shows,kept,False
        if episodes:
            kept+=1;continue
        n=refile_sendung_suggestions(c,g['show_key'],g['provider'],g['ref'],limit=100000)
        refiled+=n
        if n:shows[str(g['title'] or g['show_key'])[:80]]=n
    return refiled,shows,kept,(groups[-1]['show_key'] if len(groups)==limit else None)

def identify_by_sendung(c,row,m,source,suggestion,sendung,grouping):
    """Identify ``row`` as Folge of the suggested series (state 'identified', episode not yet verified)."""
    own={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings','deferred_providers','format_grouping')}
    own['unknown_before']=unknown_before(row,m)
    for field in ('title','year','provider','reference_id','poster','genres','genre_source','reference_runtime_seconds',
                  'imdb_id','networks','show_description'):
        if suggestion.get(field) not in (None,'',[]):own[field]=suggestion[field]
    label=UNKNOWN_GROUPINGS.get(grouping,'Folge')
    own.update(kind='series',episode_title=cleaned(source.get('title')) or str(row['title'] or ''),season=None,episode=None,
               episode_verified=False,state='work_identified',sendung_suggestion_v0688=True,sendung_grouping=grouping,
               reason=label+' der Sendung „'+str(own.get('title') or sendung)+'“ laut '+str(suggestion.get('provider'))+
                      ' (gleicher Name, passender Zeitraum); die Folge selbst wird noch gesucht.')
    dest=save_metadata(c,row['id'],own,'identified') or row['id']
    # the series identity is settled; the episode queue (not the recognition) works on the Folge
    c.execute('UPDATE works SET next_try=? WHERE id=?',(time.time()+30*86400,dest))
    c.execute('DELETE FROM film_hints WHERE work_id=?',(dest,))
    return dest

def unknown_role(source,topic_works):
    """(grouping, Sendung name) for a checked work of unknown kind; grouping is one of UNKNOWN_GROUPINGS.

    topic_works counts all works under the offer's topic (this one included)."""
    import metadata
    title=cleaned(source.get('title'));topic=cleaned(source.get('topic'))
    duration=int(source.get('duration') or 0)
    sendung=bool(topic) and key(topic) not in FORMAT_GENERIC and not metadata.generic_topic(topic)
    score,_=film_likelihood(source)
    feature=2400<=duration<=15000
    # Explicit film evidence: film rubric/film word in the topic or "Spielfilm" in the broadcaster's text.
    if feature and (score>=2 or (FILM_TOPIC.search(topic) and duration>=3600)) and not DATED.search(title):
        return 'movie',''
    if sendung and topic_works>=2:
        if key(title)==key(topic):
            return ('edition',topic) if topic_works>=3 or format_series(topic) else ('single','')
        if DATED.search(title):return 'edition',topic
        if 0<duration<600:return 'segment',topic
        if EDITION_NUMBERING.search(title) or metadata.PART.search(title):return 'part',topic
        return 'contribution',topic
    # No usable topic: a numbered part names its series ("Österreich - Die ganze Geschichte (7/10): …").
    part=metadata.part_series(title)
    if part and not metadata.generic_topic(part):return 'part',part
    # 0.6.49: an episode from ARTE's/SRF's series section ("Serie e fiction - Serie") is no Einzelsendung.
    if metadata.RUBRIC_SERIES.match(topic):return 'series_rubric',''
    return 'single',''

def unknown_candidates(c):
    """IDs of unknown works that may get a kind, and earlier Einzelsendungen whose Sendung may have grown."""
    rows=c.execute("""SELECT id FROM works WHERE kind='unknown' AND state IN ('pending','retry','review') AND attempts>0""").fetchall()
    singles=c.execute("""SELECT id FROM works WHERE kind='other' AND state='format'
        AND json_extract(meta,'$.format_grouping')='single'""").fetchall()
    return [r[0] for r in rows],[r[0] for r in singles]

def topic_counts(c,topics):
    """Works per raw topic for the given topics: one read pass instead of a table scan per topic."""
    wanted=set(topics);out={}
    if not wanted:return out
    for topic,n in c.execute('SELECT topic,COUNT(*) FROM works GROUP BY topic'):
        if topic in wanted:out[topic]=n
    return out

def best_source(c,wid):
    best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(wid,)).fetchone()
    return json.loads(best[0]) if best else None

def unknown_before(row,m):
    """What the sweep replaces, so that "Erneut prüfen" can restore the open work (0.6.49)."""
    before={'title':row['title'],'kind':row['kind'],'state':row['state'],'rev':UNKNOWN_RULES_REV}
    if m.get('suggestions'):before['suggestions']=list(m['suggestions'])[:10]
    if m.get('metadata_warnings'):before['metadata_warnings']=list(m['metadata_warnings'])[:5]
    return before

def _count(summary,reason,channel,topic=''):
    left=summary.setdefault('remaining',{});left[reason]=left.get(reason,0)+1
    per=summary.setdefault('remaining_channels',{}).setdefault(channel,{});per[reason]=per.get(reason,0)+1
    if topic:
        topics=summary.setdefault('_topics',{});k=(channel,topic,reason);topics[k]=topics.get(k,0)+1

def finish_summary(summary,top=40):
    """Turn the per-topic counters into a short list of the Sendungen with most open works."""
    topics=summary.pop('_topics',{}) or {}
    summary['remaining_topics']=[{'channel':ch,'topic':t[:80],'reason':r,'works':n}
                                 for (ch,t,r),n in sorted(topics.items(),key=lambda x:-x[1])[:top]]
    return summary

def classify_unknown(c,ids,counts,summary=None,singles=False):
    """Give each listed work of unknown kind its kind; returns the number of changed works.

    ``summary`` (dict) collects counts per grouping/channel, remaining reasons per channel and Sendung and a
    few samples (0.6.49: also the works filed despite set-aside suggestions or old provider errors)."""
    summary=summary if summary is not None else {}
    done=summary.setdefault('classified',{});summary.setdefault('remaining',{})
    channels=summary.setdefault('channels',{});samples=summary.setdefault('samples',{})
    aside=summary.setdefault('set_aside',{})
    changed=0
    for wid in ids:
        row=c.execute('SELECT * FROM works WHERE id=?',(wid,)).fetchone()
        if not row:continue
        m=json.loads(row['meta'] or '{}')
        if singles:
            if row['kind']!='other' or row['state']!='format' or m.get('format_grouping')!='single':continue
        else:
            if row['kind']!='unknown':continue
            hard=unknown_hard_reason(row,m)
            if hard:
                _count(summary,hard,'Unbekannt');continue
        source=best_source(c,wid)
        if not source:
            _count(summary,'no_offer','Unbekannt');continue
        ch=str(source.get('channel') or 'Unbekannt')
        topic=row['topic'] or source.get('topic') or ''
        grouping,name=unknown_role(source,counts.get(topic,1))
        if singles and grouping in ('single','movie','series_rubric'):continue
        if grouping=='series_rubric':
            _count(summary,'series_rubric',ch,cleaned(topic));continue
        soft=None if singles else unknown_soft_check(row,m,source,grouping,name,counts.get(topic,1))
        if soft=='suggestions':
            chosen=sendung_suggestion(m,source,name)
            episodes=sendung_has_episodes(chosen) if chosen else None
            if chosen and episodes is not None:
                # 0.6.92 (Zwischendiagnose Pro 0.6.91: 1.100 Folgensuchen, 2 Treffer – Sportpanorama, NZZ Standpunkte,
                # Euromaxx …): a Sendung without single episodes at IMDb has no episode to find; the work is its
                # contribution, filed under the Sendung with the series identity kept as note.
                outcome='sendung_suggestion' if episodes else 'sendung_without_episodes'
                if episodes:identify_by_sendung(c,row,m,source,chosen,name,grouping)
                else:file_sendung_without_episodes(c,row,m,source,chosen,name,grouping)
                changed+=1;done[outcome]=done.get(outcome,0)+1
                channels.setdefault(ch,{});channels[ch][outcome]=channels[ch].get(outcome,0)+1
                bucket=samples.setdefault(outcome,[])
                if len(bucket)<5:bucket.append({'title':str(source.get('title') or '')[:120],'topic':str(source.get('topic') or '')[:80],
                                                 'channel':ch,'suggestion':suggestion_brief(chosen)})
                continue
        if soft:
            _count(summary,soft,ch,cleaned(topic))
            if soft=='suggestions':
                # 0.6.49: which suggestion keeps the work open, so that the diagnosis shows the evidence.
                blocking=summary.setdefault('blocking_samples',[])
                if len(blocking)<25:
                    first=next((x for x in m.get('suggestions') or [] if not suggestion_weak(x,source,name,cleaned(source.get('title')))),None)
                    blocking.append({'title':str(source.get('title') or '')[:80],'topic':cleaned(topic)[:80],'channel':ch,
                                     'duration':int(source.get('duration') or 0),'year_aired':broadcast_year(source),
                                     'suggestion':suggestion_brief(first)})
            continue
        if not singles:
            if m.get('suggestions') or m.get('metadata_warnings'):
                why='suggestions' if m.get('suggestions') else 'warnings'
                aside[why]=aside.get(why,0)+1
                # 0.6.78: measurable effect of the 0.6.77 Wikidata rule (Mac-Prüfung: works no longer held by it)
                if any(old_wikidata_suggestion(x) for x in m.get('suggestions') or []):
                    summary['wikidata_old_set_aside']=summary.get('wikidata_old_set_aside',0)+1
            if grouping!='movie':m['unknown_before']=unknown_before(row,m)
        if grouping=='movie':
            m.update(kind='movie',season=None,episode=None,episode_title='',
                     reason='Film laut Sender (Filmrubrik oder Filmhinweis); in den Filmdatenbanken noch nicht gefunden')
            m.pop('format_grouping',None)
            c.execute("UPDATE works SET kind='movie',show_key='',meta=? WHERE id=?",(json.dumps(m),wid))
            c.execute('DELETE FROM film_hints WHERE work_id=?',(wid,))
        elif grouping=='single':
            m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings','deferred_providers')}
            m.update(kind='other',state='format',format_grouping='single',title=cleaned(source.get('title')) or m.get('title'),
                     season=None,episode=None,episode_title='',episode_verified=False,
                     reason='Einzelsendung'+(' aus „'+cleaned(source.get('topic'))+'“' if cleaned(source.get('topic')) else '')+
                            '; in den Filmdatenbanken nicht gefunden und keine wiederkehrende Sendung.')
            c.execute("UPDATE works SET title=?,kind='other',show_key='',meta=?,state='format',next_try=0 WHERE id=?",(m['title'],json.dumps(m),wid))
            c.execute('DELETE FROM film_hints WHERE work_id=?',(wid,))
        else:
            label={'edition':'Ausgabe','segment':'Beitrag','part':'Teil','contribution':'Folge'}[grouping]
            if singles:m.pop('format_grouping',None)
            note=''
            before=m.get('unknown_before') or {}
            if not singles and before.get('suggestions'):
                note=' '+str(len(before['suggestions']))+' Vorschläge der Filmdatenbanken passten nicht (andere Laufzeit, ungenauer Titel oder die Sendung selbst); „Erneut prüfen“ zeigt sie wieder.'
            file_under_sendung(c,row,m,source,name,grouping,
                               reason=label+' der Sendung „'+name+'“; die Sendung ist in den Filmdatenbanken nicht verzeichnet, '
                                      'deshalb wird sie nicht einzeln abgeglichen.'+note)
        changed+=1;done[grouping]=done.get(grouping,0)+1
        channels.setdefault(ch,{});channels[ch][grouping]=channels[ch].get(grouping,0)+1
        bucket=samples.setdefault(grouping,[])
        if len(bucket)<5:bucket.append({'title':str(source.get('title') or '')[:120],'topic':str(source.get('topic') or '')[:80],
                                         'channel':ch,'duration':int(source.get('duration') or 0)})
    return changed

def restore_unknown(m):
    """Undo a sweep decision for "Erneut prüfen": the work is open again with its earlier suggestions.

    Returns (title, kind, meta) or None for works the sweep did not decide."""
    before=m.get('unknown_before')
    if not isinstance(before,dict) or before.get('kind')!='unknown':return None
    out={k:v for k,v in m.items() if k not in ('unknown_before','format_grouping','provider','reference_id','state','reason')}
    title=before.get('title') or m.get('episode_title') or m.get('title')
    out.update(kind='unknown',title=title,episode_title='',season=None,episode=None,episode_verified=False)
    for k in ('suggestions','metadata_warnings'):
        if before.get(k):out[k]=before[k]
    return title,'unknown',out

def unknown_rubric_fix(c,limit=5000):
    """0.6.49, once: works 0.6.43 filed under an ARTE section as if it were a Sendung, or as Einzelsendung
    from a series section, become open works of unknown kind again; the next sweep decides with the new rules.

    Returns the number of reopened works."""
    if get_state(c,'unknown_rubric_fix_v0649c'):return 0
    import metadata
    names=[r[0] for r in c.execute("SELECT DISTINCT title FROM works WHERE kind='series' AND state='format'") if metadata.generic_topic(r[0]) and r[0]]
    reopened=0
    for name in names:
        for row in c.execute("SELECT * FROM works WHERE kind='series' AND title=? AND state='format'",(name,)).fetchall():
            m=json.loads(row['meta'] or '{}')
            if m.get('provider')!='Sendung' or m.get('format_grouping') not in SENDUNG_GROUPINGS:continue
            reopened+=_reopen(c,row,m)
    for row in c.execute("SELECT * FROM works WHERE kind='other' AND state='format' AND json_extract(meta,'$.format_grouping')='single'").fetchall():
        if not metadata.RUBRIC_SERIES.match(cleaned(row['topic'] or '')):continue
        reopened+=_reopen(c,row,json.loads(row['meta'] or '{}'))
    # Series works named after a section (seed before 0.6.49): checked again under their own title.
    names=[r[0] for r in c.execute("SELECT DISTINCT title FROM works WHERE kind='series' AND state IN ('pending','retry','review')") if r[0] and metadata.generic_topic(r[0])]
    for name in names:
        for row in c.execute("SELECT * FROM works WHERE kind='series' AND title=? AND state IN ('pending','retry','review')",(name,)).fetchall():
            m=json.loads(row['meta'] or '{}')
            if m.get('reference_id') or m.get('scan_requested'):continue
            reopened+=_reopen(c,row,m)
    set_state(c,'unknown_rubric_fix_v0649c',{'reopened':reopened,'at':time.time()})
    return reopened

def _reopen(c,row,m):
    title=m.get('episode_title') if row['kind']=='series' else row['title']
    source=best_source(c,row['id']) or {}
    title=cleaned(source.get('title')) or title or row['title']
    m={k:v for k,v in m.items() if k not in ('format_grouping','provider','reference_id','state','reason','unknown_before')}
    m.update(kind='unknown',title=title,episode_title='',season=None,episode=None,episode_verified=False)
    m={k:v for k,v in m.items() if k not in ('suggestions','metadata_warnings','deferred_providers')}
    # Unchecked again: recognition first asks the film databases under the real title (part/prefix series),
    # only then may the sweep decide.
    c.execute("UPDATE works SET title=?,kind='unknown',show_key='',meta=?,state='pending',attempts=0,next_try=0 WHERE id=?",(title,json.dumps(m),row['id']))
    c.execute('DELETE FROM episode_queue WHERE work_id=?',(row['id'],))
    update_film_hint(c,row['id'],m,source)
    return 1

def unknown_overview(c):
    """Works of unknown kind by state (also those the sweep never sees: unchecked, user decisions)."""
    out={}
    for state,checked,n in c.execute("SELECT state,attempts>0,COUNT(*) FROM works WHERE kind='unknown' GROUP BY state,attempts>0"):
        k=str(state)+('' if checked else ' (ungeprüft)');out[k]=out.get(k,0)+n
    return out

KIND_KEYS=('movie','series','unknown','other')
def recognition(c):
    """Recognition per channel and state; formats are counted separately from open works.

    0.5.80 (Björn: "Erkennungsrate je Sender/Medienart"): every channel row also carries ``kinds`` with
    the counters per media type (movie, series, unknown, other). The main counters keep excluding
    'other' (trailers, clips, live streams), which are not meant to be matched; they are listed as ``clips``."""
    try:
        rows=c.execute("SELECT COALESCE(json_extract(o.payload,'$.channel'),'') channel,w.kind,w.state,COUNT(DISTINCT w.id) n FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 GROUP BY channel,w.kind,w.state").fetchall()
    except sqlite3.OperationalError:
        rows=c.execute("SELECT '' channel,w.kind,w.state,COUNT(*) n FROM works w GROUP BY w.kind,w.state").fetchall()
    out={}
    for r in rows:
        d=out.setdefault(r['channel'] or 'Unbekannt',{'channel':r['channel'] or 'Unbekannt','works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0,'clips':0,
                                                      'kinds':{k:{'works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0} for k in KIND_KEYS}})
        state=r['state'];kind=r['kind'] if r['kind'] in KIND_KEYS else 'unknown'
        key_={'matched':'matched','manual':'matched','identified':'identified','format':'format','review':'review'}.get(state,'open')
        k=d['kinds'][kind];k['works']+=r['n'];k[key_]+=r['n']
        if kind=='other':d['clips']+=r['n'];continue
        d['works']+=r['n'];d[key_]+=r['n']
    return sorted((d for d in out.values() if d['works'] or d['clips']),key=lambda d:-d['works'])

def recognition_totals(rows):
    """Sum of the channel rows per media type (table "Nach Medienart")."""
    total={k:{'works':0,'matched':0,'identified':0,'format':0,'open':0,'review':0} for k in KIND_KEYS}
    for r in rows or []:
        for k,v in (r.get('kinds') or {}).items():
            if k in total:
                for f in total[k]:total[k][f]+=v.get(f,0)
    return [{'kind':k,**v} for k,v in total.items() if v['works']]

def reclassify_batch(c,limit=500):
    cursor=get_state(c,'reclassify_cursor_v030',0)
    if cursor=='complete':return 0
    rows=c.execute("SELECT rowid AS rid,* FROM works WHERE rowid>? ORDER BY rowid LIMIT ?",(cursor,limit)).fetchall()
    for row in rows:
        cursor=row['rid']
        if row['state'] in ('manual','matched','identified'):continue
        best=c.execute('SELECT payload FROM offers WHERE work_id=? ORDER BY active DESC,rank DESC LIMIT 1',(row['id'],)).fetchone()
        if not best:continue
        source=json.loads(best[0]);m=seed(source)
        c.execute("UPDATE works SET title=?,kind=?,year=?,show_key=?,meta=?,state='pending',next_try=0,topic=? WHERE id=?",(m['title'],m['kind'],m.get('year'),showkey(m),json.dumps(m),source.get('topic',''),row['id']))
        c.execute('DELETE FROM work_genres WHERE work_id=?',(row['id'],))
        for g in m['genres']:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(row['id'],g))
    set_state(c,'reclassify_cursor_v030',cursor if rows else 'complete')
    return len(rows)

def normalized_genres(values):
    from metadata import genres
    return genres(values or [])

def split_kids_family(c):
    """0.5.103 (Björn): the stored label 'Kinder & Familie' mixed TMDB 'Family' with real children's
    programmes. Labels derived from the broadcaster (KiKA, 'Kinderfilm', 'Kinderserie') become 'Kinder',
    everything else (reference genres such as TMDB 'Family') 'Familie'. Runs once."""
    old='Kinder & Familie'
    ids=[r[0] for r in c.execute('SELECT work_id FROM work_genres WHERE genre=?',(old,))]
    for wid in ids:
        row=c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()
        m=json.loads(row[0] or '{}') if row else {}
        kids=m.get('genre_source') in ('Senderhinweis','Sender (abgeleitet)')
        new='Kinder' if kids else 'Familie'
        c.execute('DELETE FROM work_genres WHERE work_id=? AND genre=?',(wid,old))
        c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,new))
        if row:
            m['genres']=sorted({new if g==old else g for g in (m.get('genres') or [])})
            c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
    return len(ids)

def merge_genre_spellings(c):
    """Fold genres stored under older or provider-specific spellings into one canonical name."""
    from metadata import genre_names
    changes={}
    for (genre,) in c.execute('SELECT DISTINCT genre FROM work_genres').fetchall():
        names=genre_names(genre)
        if names!=[genre]:changes[genre]=names
    touched=set()
    for genre,names in changes.items():
        ids=[r[0] for r in c.execute('SELECT work_id FROM work_genres WHERE genre=?',(genre,))]
        for wid in ids:
            for name in names:c.execute('INSERT OR IGNORE INTO work_genres VALUES(?,?)',(wid,name))
        c.execute('DELETE FROM work_genres WHERE genre=?',(genre,));touched.update(ids)
    for wid in touched:
        row=c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()
        if not row:continue
        m=json.loads(row[0] or '{}');m['genres']=normalized_genres(m.get('genres'))
        c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
    for topic,provider,ref,meta in c.execute('SELECT topic,provider,reference,meta FROM series_templates').fetchall():
        m=json.loads(meta or '{}');g=normalized_genres(m.get('genres'))
        if g!=m.get('genres'):m['genres']=g;c.execute('UPDATE series_templates SET meta=? WHERE topic=? AND provider=? AND reference=?',(json.dumps(m),topic,provider,ref))
    return len(changes)

def recover_download_queue(c):
    """Keep untouched queued jobs runnable after a crash; never replay an in-flight job blindly."""
    c.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('downloading','tagging')")
    
# Same rule as the episode_queue triggers and work_identity_recheck: an identified work outside
# the episode queue. Must stay textually identical to the index so SQLite can use it.
IDENTITY_RECHECK="""w.state='identified' AND NOT (
 w.kind='series' AND NULLIF(json_extract(w.meta,'$.reference_id'),'') IS NOT NULL
 AND json_type(w.meta,'$.deferred_providers') IS NULL
 AND COALESCE(json_extract(w.meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(w.meta,'$.video_role_needs_review'),0)=0)"""

# 0.6.29 (Björn, Datenbank auf USB-Laufwerk): identified works that are NOT in the episode queue.
# The identity selector used to walk all ~220,000 queued series row by row before finding none.
# 0.6.35: Building this index reads every work once. On Björn's 5.5 GB catalog.db on a USB drive
# that took many minutes *before* the web server started, so 0.6.34 looked hung ("Programm
# reagiert nicht"). The server now builds it in the background after start (build_deferred_indexes);
# until then Service.pick leaves out the identified re-checks.
IDENTITY_INDEX='work_identity_recheck'
IDENTITY_INDEX_SQL="""CREATE INDEX IF NOT EXISTS work_identity_recheck ON works(kind,next_try) WHERE state='identified' AND NOT (
 kind='series' AND NULLIF(json_extract(meta,'$.reference_id'),'') IS NOT NULL
 AND json_type(meta,'$.deferred_providers') IS NULL
 AND COALESCE(json_extract(meta,'$.episode_verified'),0)=0
 AND COALESCE(json_extract(meta,'$.video_role_needs_review'),0)=0);"""
# Visible state of the one-time background maintenance (shown in /api/state and the UI).
MAINTENANCE={'phase':'idle'}

def index_ready(c,name=IDENTITY_INDEX):
    """True when the deferred index exists in this database (sqlite_master is small and cached)."""
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",(name,)).fetchone() is not None

def recheck_episode_queue_v0641(c,event=None):
    """Make earlier "ohne Treffer" episode checks due once more (0.6.41 rules: editions, dated IMDb
    episodes, cleaned titles). Runs after the server start: it walks the whole queue table once."""
    if get_state(c,'episode_queue_recheck_v0641',False):return 0
    n=c.execute("UPDATE episode_queue SET next_try=0 WHERE last_outcome IN ('unresolved','no_imdb_episodes')").rowcount
    set_state(c,'episode_queue_recheck_v0641',True)
    if event and n:event('episode_queue_recheck',version='0.6.41',works=n)
    return n

def heal_derived_kids_v0696(c,event=None,merker='kids_genre_heal_v0696',version='0.6.98'):
    """0.6.98 (Mac-Prüfung 0.6.91): „Kinder“ that the broadcaster rule took from a description or an edition title
    (NACHTCAFÉ 302 of 302 works, Politik 11, heute 16, Abendschau 2) is removed again. Kept when the programme's
    own name (series or Sendung title, offer topic) names children's programme or an offer comes from a kids
    channel. Only genre_source „Sender (abgeleitet)“; reference genres and the user's own choices stay. Runs once,
    after the server start (genre index, only works labelled „Kinder“)."""
    if get_state(c,merker,False):return 0
    import broadcaster
    ids=[r[0] for r in c.execute("SELECT work_id FROM work_genres WHERE genre='Kinder'")]
    fixed=0
    for wid in ids:
        row=c.execute('SELECT meta FROM works WHERE id=?',(wid,)).fetchone()
        if not row:continue
        try:m=json.loads(row[0] or '{}')
        except ValueError:continue
        if m.get('genre_source')!='Sender (abgeleitet)':continue
        names=[str(m.get('title') or '')]
        kids_channel=False
        for (payload,) in c.execute('SELECT payload FROM offers WHERE work_id=? AND active=1',(wid,)):
            try:o=json.loads(payload or '{}')
            except ValueError:continue
            names.append(str(o.get('topic') or ''))
            kids_channel=kids_channel or str(o.get('channel') or '').strip().lower() in KIDS_CHANNELS
        if kids_channel or broadcaster.KIDS_HINT.search(' '.join(names)):continue
        c.execute("DELETE FROM work_genres WHERE work_id=? AND genre='Kinder'",(wid,))
        m['genres']=[g for g in (m.get('genres') or []) if g!='Kinder']
        if not m['genres']:m['genre_source']='Unbekannt'
        c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),wid))
        fixed+=1
    set_state(c,merker,True)
    if event and ids:event('kids_genre_heal',version=version,checked=len(ids),removed=fixed)
    return fixed

def heal_derived_kids_v06106(c,event=None):
    """0.6.106 (Mac-Prüfung 0.6.105): the name rule itself was too wide (kinder\\w*: „Die Kinder von Lügde“,
    „Kinderärzte im Einsatz“, „Geheimsache Doping: Kinder“). Same pass as 0.6.98 with the narrowed rule, once."""
    if not get_state(c,'kids_genre_heal_v0696',False):set_state(c,'kids_genre_heal_v0696',True)   # one pass covers both
    return heal_derived_kids_v0696(c,event,'kids_genre_heal_v06106','0.6.106')

# 0.6.88 (Diagnosen 22.11.2026: Pro 121.780 / Air 116.533 Einträge, 0 fällig): an episode search without a hit
# rests 30 days (7 with spent sender allowance), its siblings without IMDb episode list 30–37 days. Asking again
# before new data only repeats the answer. New data is the weekly IMDb archive: what was checked against an
# older archive becomes due again, spread over ARCHIVE_RECHECK_SPREAD so that new works keep their place.
ARCHIVE_RECHECK_SPREAD=3*86400
ARCHIVE_RECHECK_OUTCOMES=('unresolved','unresolved_remote')

def archive_recheck_ids(c,archive_updated,now=None):
    """Queue entries checked against an IMDb archive older than ``archive_updated`` that rest beyond now.

    Every entry „ohne Treffer“ comes back; of a series whose siblings rest as 'no_imdb_episodes' only one entry
    per series (the first) when none of its entries comes back anyway: its answer decides for the siblings
    (CatalogService.release_siblings / defer_series_without_episodes). Ordered oldest check first."""
    now=time.time() if now is None else now
    if not archive_updated:return []
    rows=c.execute("""SELECT q.work_id,q.last_outcome,w.show_key FROM episode_queue q JOIN works w ON w.id=q.work_id
        WHERE q.updated>0 AND q.updated<? AND q.next_try>?
          AND q.last_outcome IN ('unresolved','unresolved_remote','no_imdb_episodes')
        ORDER BY q.updated,q.work_id""",(float(archive_updated),now)).fetchall()
    shows={r['show_key'] for r in rows if r['last_outcome'] in ARCHIVE_RECHECK_OUTCOMES and r['show_key']}
    out=[]
    for r in rows:
        if r['last_outcome'] in ARCHIVE_RECHECK_OUTCOMES:out.append(r['work_id'])
        elif r['show_key'] and r['show_key'] not in shows:
            shows.add(r['show_key']);out.append(r['work_id'])
    return out

def release_no_episode_siblings(c,show_key,provider,reference,now=None,spread=6*3600):
    """IMDb now lists episodes for this series: its siblings that rest as 'no_imdb_episodes' are due again
    (spread over ``spread`` seconds). Returns the number released."""
    if not show_key or not provider or not reference:return 0
    now=time.time() if now is None else now
    ids=[r[0] for r in c.execute("""SELECT q.work_id FROM episode_queue q JOIN works w ON w.id=q.work_id
        WHERE q.last_outcome='no_imdb_episodes' AND q.next_try>? AND w.show_key=?
          AND json_extract(w.meta,'$.provider')=? AND CAST(json_extract(w.meta,'$.reference_id') AS TEXT)=?""",
        (now,show_key,provider,str(reference)))]
    c.executemany('UPDATE episode_queue SET next_try=? WHERE work_id=?',
                  [(now+(i*spread/max(1,len(ids)) if len(ids)>1 else 0),w) for i,w in enumerate(ids)])
    return len(ids)

def episode_queue_overview(c,now=None):
    """Why the episode queue rests (0.6.88): entries per last outcome and the next due time."""
    now=time.time() if now is None else now
    waiting={str(o or 'pending'):n for o,n in c.execute('SELECT last_outcome,COUNT(*) FROM episode_queue WHERE next_try>? GROUP BY last_outcome',(now,))}
    nxt=c.execute('SELECT MIN(next_try) FROM episode_queue WHERE next_try>?',(now,)).fetchone()[0]
    return {'waiting':waiting,'next_due':float(nxt) if nxt else None}

def build_deferred_indexes(connect,event=None,error=None):
    """Create indexes that need a full table pass, after the server is reachable.
    connect() returns a context-managed connection. Readers keep working (WAL); writers wait."""
    with connect() as c:
        recheck_episode_queue_v0641(c,event)
    try:
        with connect() as c:
            if heal_derived_kids_v0696(c,event) | heal_derived_kids_v06106(c,event):
                import kids_catalog,unified_index;invalidate_listings(drop=True);unified_index.invalidate();kids_catalog.invalidate()
    except Exception as e:
        if error:error('kids_genre_heal_failed',e)
    with connect() as c:
        if index_ready(c):MAINTENANCE.update(phase='done');return True
    started=time.time();MAINTENANCE.clear()
    MAINTENANCE.update(phase='running',started=started,
        text='Datenbank wird einmalig für die schnellere Erkennung vorbereitet (neuer Index). '
             'Auf externen Laufwerken kann das einige Minuten dauern; die Oberfläche bleibt bedienbar, '
             'Erkennung und Speichern können solange warten.')
    if event:event('catalog_index_build_started',index=IDENTITY_INDEX)
    try:
        with connect() as c:c.execute(IDENTITY_INDEX_SQL)
    except Exception as e:
        MAINTENANCE.update(phase='failed',seconds=round(time.time()-started,1),
            text='Datenbank-Index konnte nicht angelegt werden; die Erkennung läuft ohne ihn langsamer weiter. Details im Protokoll.')
        if error:error('catalog_index_build_failed',e,index=IDENTITY_INDEX)
        return False
    MAINTENANCE.update(phase='done',seconds=round(time.time()-started,1),text='')
    if event:event('catalog_index_build_finished',index=IDENTITY_INDEX,seconds=MAINTENANCE['seconds'])
    return True

def initialize(c,defer_heavy=False):
    # defer_heavy=False (tests, tools): build the identity index at once; the server defers it.
    _initialize(c)
    if not defer_heavy:
        c.execute(IDENTITY_INDEX_SQL)

def _initialize(c):
    c.executescript(SCHEMA)
    # SQLite CREATE TRIGGER IF NOT EXISTS does not replace older definitions.
    # Rebuild once, preserving all queue rows, retries and user choices.
    if not get_state(c,'episode_queue_causality_triggers_v0531',False):
        c.executescript("""DROP TRIGGER IF EXISTS episode_queue_work_insert;
            DROP TRIGGER IF EXISTS episode_queue_work_update;
            DROP TRIGGER IF EXISTS episode_queue_work_delete;""")
        c.executescript(SCHEMA)
        c.execute("""DELETE FROM episode_queue WHERE EXISTS
            (SELECT 1 FROM works w WHERE w.id=episode_queue.work_id
             AND COALESCE(json_extract(w.meta,'$.video_role_needs_review'),0)!=0)""")
        set_state(c,'episode_queue_causality_triggers_v0531',True)
    # Recreate the trigger definitions without altering existing queue rows.
    # Outer UPSERT conflict handling must never override an inner OR IGNORE.
    if not get_state(c,'episode_queue_safe_upsert_v05311',False):
        c.executescript("""DROP TRIGGER IF EXISTS episode_queue_work_insert;
            DROP TRIGGER IF EXISTS episode_queue_work_update;
            DROP TRIGGER IF EXISTS episode_queue_work_delete;""")
        c.executescript(SCHEMA)
        set_state(c,'episode_queue_safe_upsert_v05311',True)
    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:c.execute("ALTER TABLE works ADD COLUMN topic TEXT DEFAULT ''")
    if not get_state(c,'artwork_discovery_refresh_v047',False):
        c.execute('DELETE FROM artwork_checks');c.execute('DELETE FROM artwork_cache');set_state(c,'artwork_discovery_refresh_v047',True)
    c.execute('CREATE INDEX IF NOT EXISTS work_topic ON works(topic)')
    mark_live(c)
    if not get_state(c,'genre_spellings_v053',False):merge_genre_spellings(c);set_state(c,'genre_spellings_v053',True)
    if not get_state(c,'kids_family_split_v0103',False):split_kids_family(c);set_state(c,'kids_family_split_v0103',True)
    # One-time migration of existing identified episodes; no destructive resets.
    if not get_state(c,'episode_queue_migrated_v0528',False):
        c.execute("""INSERT OR IGNORE INTO episode_queue(work_id)
            SELECT id FROM works WHERE kind='series' AND state='identified'
            AND NULLIF(json_extract(meta,'$.reference_id'),'') IS NOT NULL
            AND json_type(meta,'$.deferred_providers') IS NULL
            AND COALESCE(json_extract(meta,'$.episode_verified'),0)=0
            AND COALESCE(json_extract(meta,'$.video_role_needs_review'),0)=0""")
        set_state(c,'episode_queue_migrated_v0528',True)
    # 0.6.24: the episode search now finds episodes it rejected before (provider
    # year vs. IMDb start year, numbering in the title). Re-check the earlier
    # "unresolved" results once instead of waiting 30 days; their attempt
    # history stays. Magazine editions are postponed per series in one step.
    if not get_state(c,'episode_queue_recheck_v0624',False):
        c.execute("UPDATE episode_queue SET next_try=0 WHERE last_outcome IN ('unresolved','retry')")
        set_state(c,'episode_queue_recheck_v0624',True)

def review_listing(c,query='',state='open',offset=0):
    """Flat work/episode list: do not hide unresolved episodes behind a series parent."""
    clauses=['EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)'];args=[]
    if state=='open':clauses.append("w.state IN ('pending','retry','review','identified')")
    elif state in ('pending','retry','review','identified','manual','matched','format'):clauses.append('w.state=?');args.append(state)
    if query:clauses.append('(w.title LIKE ? OR w.topic LIKE ?)');args.extend(['%'+query[:150]+'%']*2)
    where=' AND '.join(clauses);offset=max(0,int(offset))
    total=c.execute('SELECT COUNT(*) FROM works w WHERE '+where,args).fetchone()[0]
    rows=c.execute('SELECT w.* FROM works w WHERE '+where+' ORDER BY w.title COLLATE NOCASE,w.id LIMIT 48 OFFSET ?',args+[offset]).fetchall()
    return {'items':[entry for w in rows for entry in [item(c,w)] if entry],'total':total,'offset':offset}
