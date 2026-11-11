"""Conservative, reversible classification of video uploads outside movie/series discovery.

Classifies *format* rather than religious belief. Religious feature films and
narrative series are deliberately not inferred from broad keywords like Bible,
Jesus, Islam or Christian. A user override always wins over automatic guesses.
"""
from __future__ import annotations
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_triage (
 group_id TEXT PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
 category TEXT NOT NULL CHECK(category IN ('main','religious','podcast','clip')),
 origin TEXT NOT NULL CHECK(origin IN ('auto','manual')),
 reason TEXT NOT NULL DEFAULT '',
 updated TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_video_triage_category ON video_triage(category,origin);
CREATE TABLE IF NOT EXISTS video_triage_progress (
 id INTEGER PRIMARY KEY CHECK(id=1), cursor TEXT NOT NULL DEFAULT '',
 scanned INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO video_triage_progress(id) VALUES(1);
"""
CATEGORIES=('religious','podcast','clip')
# Explicit content formats, rather than mere topics. Films about religious
# subjects remain eligible for normal movie/series recognition.
RELIGIOUS = re.compile(
 r'\b(?:predigt(?:en)?|gottesdienst(?:e)?|andacht(?:en)?|gebetsstunde|'
 r'bibelstunde|bibelstudium|gebetskreis|sonntagsmesse|kirchenmesse|'
 r'freitagsgebet|koranrezitation|koranlesung|'
 r'sermons?|church\s+service|sunday\s+worship|worship\s+service|'
 r'prayer\s+(?:meeting|service|livestream|session)|bible\s+study|'
 r'quran\s+(?:recitation|reading)|koran\s+(?:rezitation|lesung)|'
 r'quran\s+recitation|qur.?an\s+recitation|khutbah|jummah\s+prayer|'
 r'mass\s+livestream|islamic\s+lecture|religious\s+lecture|'
 r'serm[oó]n\s+(?:dominical|religioso)|misa\s+(?:dominical|en\s+vivo)|'
 r'culto\s+(?:dominical|religioso)|recitaci[oó]n\s+del\s+cor[aá]n)\b',re.I)
PODCAST = re.compile(r'\b(?:podcasts?|video[ -]?podcasts?|vodcasts?|video[ -]?casts?|podcast[ -]?folge)\b',re.I)
CLIP = re.compile(r'\b(?:clips?|trailers?|teasers?|shorts|reels?|outtakes?|'
 r'preview|promo\s+video|behind\s+the\s+scenes)\b',re.I)
# A full film/series is not automatically excluded for this vocabulary.
FEATURE = re.compile(r'\b(?:film\s*:|feature[ -]?film|feature[ -]?length|spielfilm|'
 r'documentary\s+film|dokumentarfilm|full\s+movie|ganzer\s+film|'
 r'(?:s\d{1,2}e\d{1,3})|season\s+\d+|staffel\s+\d+|'
 r'pel[ií]cula\s+(?:completa|documental)|serie\s+de\s+televisi[oó]n)\b|'
 r'(?:فيلم\s+(?:كامل|وثائقي)|مسلسل|художественный\s+фильм)',re.I)

# Arabic uses word boundaries reliably with Python Unicode regexes, but Quran
# recitation and commentary formats deserve specific patterns rather than a broad
# religious-keyword filter.  'Islam', 'Bible', 'Jesus' alone are never exclusionary.
RELIGIOUS_AR = re.compile(
    r'(?:\b(?:تلاوة|تجويد|تفسير\s+سورة|سورة\s+[\u0621-\u064a]|خطبة\s+(?:الجمعة|دينية)|'
    r'صلاة\s+(?:الجمعة|التراويح)|محاضرة\s+دينية|درس\s+ديني|'
    r'الشيخ\s+[^\n]{3,65}\s+تفسير)\b)', re.I)
RELIGIOUS_AR_ALT = re.compile(r'(?:\b(?:تلاوة|تجويد|تفسير\s+سورة|خطبة\s+الجمعة|سورة\s+[\u0621-\u064a]))',re.I)
CLIP_AR = re.compile(r'(?:مقطع\s+(?:فيديو|قصير)|مقاطع\s+(?:فيديو|قصيرة))',re.I)
PODCAST_PATH = re.compile(r'(?i)(?:feeds?[._ /~:-]*[^ ]{0,55}?(?:podcasts?|rpodcasts)|rpodcasts?)')

def classify(title, item_titles=(), filenames=(), *, confirmed=False):
    """Return (category, reason), where 'main' stays in recognition."""
    if confirmed:return 'main','Bereits als Film oder Serie bestätigt'
    name=' '.join(str(title or '').replace('_',' ').replace('.',' ').split())[:250]
    protected=bool(FEATURE.search(name) or re.match(r'(?i)^film\s*:',name))
    sources=[name]+[str(t or '')[:250] for t in item_titles if t]
    # Additional script-aware format evidence; never decide from faith/topic alone.
    if not protected:
        if RELIGIOUS_AR_ALT.search(name):
            return 'religious','Arabisch: Rezitation/Predigt/Surenauslegung als Format gekennzeichnet'
        if CLIP_AR.search(name):
            return 'clip','Arabisch: Videoclip als Format gekennzeichnet'
        if PODCAST_PATH.search(name):
            return 'podcast','Podcast-Feed-/Uploadkennung im Titel'
    # When one group combines unrelated Archive uploads, require strong evidence
    # from the group title or agreement in the majority of the upload titles.
    for kind,pattern,reason in (
        ('podcast',PODCAST,'Podcast-/Videocast-Kennzeichnung im Titel'),
        ('religious',RELIGIOUS,'Religiöses Einzel-/Gottesdienstformat im Titel'),
        ('clip',CLIP,'Clip-/Trailer-/Kurzvideo-Kennzeichnung im Titel')):
        if pattern.search(name) and not protected:
            return kind,reason
        candidates=sources[1:]
        if candidates and sum(bool(pattern.search(t) and not FEATURE.search(t)) for t in candidates)>len(candidates)//2:
            return kind,'Kennzeichnung in überwiegenden Archive.org-Uploadtiteln'
    # Distinctive clip filename can identify standalone clip if it is the
    # dominant video type. Never demote a whole film for one bonus/trailer.
    filelist=list(filenames)
    if filelist and not protected:
        labeled=sum(bool(CLIP.search(str(f))) for f in filelist)
        if labeled>=2 and labeled>=max(2,(len(filelist)*3+3)//4):
            return 'clip','Überwiegend ausdrücklich als Clip/Trailer benannte Dateien'
    return 'main','Keine eindeutige Sonderformat-Kennzeichnung'

def inspect(c,group_id):
    g=c.execute('SELECT title,match_state FROM groups WHERE id=?',(group_id,)).fetchone()
    if not g:return None
    titles=[r[0] for r in c.execute("""SELECT DISTINCT i.title FROM items i
      JOIN variants v ON v.item_id=i.id WHERE v.group_id=? AND i.title IS NOT NULL LIMIT 15""",(group_id,))]
    names=[r[0] for r in c.execute('SELECT filename FROM variants WHERE group_id=? LIMIT 15',(group_id,))]
    return classify(g['title'],titles,names,confirmed=g['match_state']=='confirmed')

def update(c,group_id):
    existing=c.execute('SELECT origin FROM video_triage WHERE group_id=?',(group_id,)).fetchone()
    if existing and existing[0]=='manual':return None
    result=inspect(c,group_id)
    if not result:return None
    category,reason=result
    c.execute("""INSERT INTO video_triage(group_id,category,origin,reason) VALUES(?,?,'auto',?)
      ON CONFLICT(group_id) DO UPDATE SET category=excluded.category,reason=excluded.reason,origin='auto',
      updated=CURRENT_TIMESTAMP WHERE video_triage.origin='auto' AND
      (video_triage.category!=excluded.category OR video_triage.reason!=excluded.reason)""",
      (group_id,category,reason))
    sync_probes(c,group_id,category)
    return category

def sync_probes(c,group_id,category):
    if category in CATEGORIES:
        c.execute("""UPDATE media_probe_jobs SET state='deferred',detail='Sonstige Videos: nur auf Anforderung prüfen',
            updated=CURRENT_TIMESTAMP WHERE state='queued' AND variant_id IN
            (SELECT id FROM variants WHERE group_id=?)""",(group_id,))
    else:
        c.execute("""UPDATE media_probe_jobs SET state='queued',detail=NULL,updated=CURRENT_TIMESTAMP
          WHERE state='deferred' AND COALESCE(detail,'') NOT LIKE 'v0.10.34:%' AND variant_id IN (SELECT id FROM variants WHERE group_id=?)""",(group_id,))

def override(c,group_id,category):
    if category not in CATEGORIES+('main','auto'):
        raise ValueError('Ungültige Videokategorie')
    g=c.execute('SELECT id,match_state FROM groups WHERE id=?',(group_id,)).fetchone()
    if not g:raise ValueError('Titelgruppe nicht gefunden')
    if category=='auto':
        c.execute('DELETE FROM video_triage WHERE group_id=?',(group_id,))
        return update(c,group_id)
    if category!='main' and g['match_state']=='confirmed':
        raise ValueError('Bestätigte Filme/Serien bleiben im Hauptkatalog; zuerst Werkzuordnung prüfen')
    c.execute("""INSERT INTO video_triage(group_id,category,origin,reason) VALUES(?,?,'manual','Manuell zugeordnet')
      ON CONFLICT(group_id) DO UPDATE SET category=excluded.category,origin='manual',
      reason='Manuell zugeordnet',updated=CURRENT_TIMESTAMP""",(group_id,category))
    sync_probes(c,group_id,category)
    return category

def backfill(c,batch_size=100):
    state=c.execute('SELECT cursor,scanned,completed FROM video_triage_progress WHERE id=1').fetchone()
    if state['completed']:return 0
    rows=c.execute('SELECT id FROM groups WHERE id>? ORDER BY id LIMIT ?',
                   (state['cursor'],batch_size)).fetchall()
    for row in rows:update(c,row['id'])
    if rows:
        c.execute('UPDATE video_triage_progress SET cursor=?,scanned=scanned+? WHERE id=1',
                  (rows[-1]['id'],len(rows)))
    if len(rows)<batch_size:
        c.execute('UPDATE video_triage_progress SET completed=1 WHERE id=1')
    return len(rows)

def status(c):
    counts={r['category']:r['n'] for r in c.execute("""SELECT t.category,COUNT(*) n FROM video_triage t
        JOIN groups g ON g.id=t.group_id WHERE COALESCE(g.match_state,'review')!='confirmed'
        GROUP BY t.category""")}
    progress=c.execute('SELECT scanned,completed FROM video_triage_progress WHERE id=1').fetchone()
    total=c.execute('SELECT COUNT(*) FROM groups').fetchone()[0]
    return {'categories':{x:counts.get(x,0) for x in CATEGORIES},
            'total':sum(counts.get(x,0) for x in CATEGORIES),
            'scanned':progress['scanned'],'catalog_groups':total,
            'backfill_completed':bool(progress['completed'])}
