"""Conservative metadata-first media identity resolution for Internet Archive items.

Never treat a bare numbered file as a work title or an episode number.
Do not assume that a shared description alone confirms two recordings are identical.
"""
from __future__ import annotations
import html,re,unicodedata
from pathlib import Path

NUMBERED = re.compile(r'(?i)^(?:\d{1,7}|(?:video|movie|film|file|track|clip|part|episode|ep|folge|sample|download)[\s._-]*\d{0,5}|(?:video|movie|film|file|track|clip|part|episode|ep|folge|sample|download))$')
GENERIC = re.compile(r'(?i)^(?:untitled|unknown|unbenannter titel|unbekannt|no title|episode|film|movie|video|tv|anime|animation|full movie|part\s*\d+)$')
EPISODE = re.compile(r'(?i)(?:\bS(?P<s>\d{1,2})[\s._-]*E(?P<e>\d{1,3})\b|\b(?P<s2>\d{1,2})x(?P<e2>\d{1,3})\b|\b(?:episode|ep|folge)[\s._-]*(?P<e3>\d{1,3})\b)')


def clean(value):
    if isinstance(value,list): value=' '.join(str(x) for x in value if x)
    raw=str(value or '')
    raw=re.sub(r'(?is)<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>',' ',raw)
    raw=re.sub(r'(?i)<br\s*/?>|</p>|</div>|</h[1-6]>','\n',raw)
    raw=re.sub(r'<[^>]+>',' ',raw)
    return re.sub(r'\s+',' ',html.unescape(raw)).strip()


def meaning_title(value):
    s=clean(value)
    if not s or len(s)>180 or len(s)<3 or NUMBERED.fullmatch(s) or GENERIC.fullmatch(s):return False
    if not any(ch.isalpha() for ch in s):return False
    if s.lower() in ('this','that','it','these','those','there','here','we','they','he','she','some','many'):return False
    if re.fullmatch(r'(?i)(?:https?://)?[\w.-]+(?:/\S+)?',s) and ('/' in s or '.' in s and not ' ' in s):return False
    return True


def normalize_title(value):
    s=clean(value)
    s=re.sub(r'(?i)^\s*(?:title|film|movie|series|anime|titel)\s*:\s*','',s)
    s=re.sub(r'(?i)\s*(?:[\[(]?(?:1080p|720p|480p|2160p|x264|x265|h264|h265|bluray|dvdrip|vhsrip)[\])]?\s*)+$','',s)
    return re.sub(r'\s+',' ',s.replace('_',' ')).strip(' -.\"\'')[:160]


def description_title(description):
    raw=str(description or '')
    # First media-specific heading or introductory sentence; never scan entire summaries for arbitrary names.
    header=re.search(r'(?is)<h[1-4][^>]*>(.*?)</h[1-4]>',raw)
    if header:
        h=normalize_title(header.group(1))
        if meaning_title(h):return h
    intro=clean(raw)[:520]
    if not intro:return None
    intro=re.sub(r'(?i)^\s*(?:description|synopsis|overview|plot|about)\s*:\s*','',intro)
    # "Blue Thermal: Aonagi Daigaku ... (...) is a Japanese manga series ..."
    # For long secondary romanized subtitles choose the recognizable lead title,
    # but leave ordinary colon-titles such as "Mission: Impossible" intact.
    if not re.search(r'(?i)\bis (?:a|an|the)\b',intro) and not re.search(r'(?i)^.{3,90}[:\n]',raw):return None
    head=re.split(r'(?i)\s+is\s+(?:a|an|the)\s+',intro,maxsplit=1)[0]
    head=re.split(r'\s+[–—]\s+|\s*\([\u3000-\u9fff\u3040-\u30ff]',head,maxsplit=1)[0].strip()
    if ':' in head:
        lead,tail=head.split(':',1)
        if meaning_title(lead) and (len(tail.split())>=6 or (len(tail.split())>=4 and ' is a ' in intro.lower() and '(' in intro)):head=lead
    if len(head)>120 or len(head.split())>11:
        # Long prose is not a title. Do not manufacture identities from generic descriptions.
        return None
    title=normalize_title(head)
    return title if meaning_title(title) else None


def resolve_item(meta,identifier,description=None):
    """Return canonical display candidate, evidence strength and source."""
    original=meta.get('title') or identifier
    for key in ('series','show','program','movie_title','film_title','originaltitle'):
        name=normalize_title(meta.get(key))
        if meaning_title(name):return dict(title=name,origin='archive-field:'+key,confidence='high')
    title=normalize_title(original)
    if meaning_title(title):return dict(title=title,origin='archive-title',confidence='high')
    inferred=description_title(description if description is not None else meta.get('description'))
    if inferred:return dict(title=inferred,origin='archive-description',confidence='tentative')
    # Identifiers that are opaque archive IDs are NOT globally mergeable.
    name=normalize_title(identifier.replace('_',' '))
    if meaning_title(name) and not re.fullmatch(r'[a-f0-9]{16,}',identifier,re.I):
        return dict(title=name,origin='archive-identifier',confidence='low')
    return dict(title='Nicht zugeordnet · '+identifier[:75],origin='unresolved',confidence='unknown')


def resolve_variant(filename,item_title,identity,parsed,meta=None,one_video=False):
    """Resolve file identity and episode using metadata before filename fallback."""
    meta=meta or {}
    raw=Path(filename).stem
    generic=NUMBERED.fullmatch(raw) is not None or not meaning_title(normalize_title(parsed.get('title','')))
    result=dict(parsed)
    # Explicit episode in filename or item title wins; otherwise, metadata episode fields may apply.
    if result.get('episode') is None:
        explicit=EPISODE.search(item_title or '')
        if explicit:
            result['kind']='series';result['season']=int(explicit.group('s') or explicit.group('s2') or 1)
            result['episode']=int(explicit.group('e') or explicit.group('e2') or explicit.group('e3'))
        elif one_video:
            try:
                episode=int(meta.get('episode_number') or meta.get('episode') or 0)
                season=int(meta.get('season_number') or meta.get('season') or 1)
            except (TypeError,ValueError):episode=0;season=1
            if 0<episode<1000 and 0<season<=100:
                result.update(kind='series',episode=episode,season=season)
    title=normalize_title(identity['title'])
    filename_title=normalize_title(parsed.get('title',''))
    if generic or not meaning_title(filename_title):
        if result.get('episode') is not None:
            title=EPISODE.sub('',title).strip(' -._') or title
        result['title']=title
        result['identity_origin']=identity['origin']
        result['identity_confidence']=identity['confidence']
    elif result['kind']=='series' and identity['confidence']=='high' and (not meaning_title(filename_title) or len(filename_title)<3):
        result['title']=title
        result['identity_origin']=identity['origin']
        result['identity_confidence']=identity['confidence']
    else:
        result['title']=filename_title
        result['identity_origin']='filename'
        result['identity_confidence']='medium'
    if result['kind']=='movie' and result['episode'] is not None:result['kind']='series'
    if result['kind']=='movie' and meaning_title(meta.get('series')):
        result['kind']='series'
        result['title']=normalize_title(meta.get('series'))
        if result.get('episode') is None:result['identity_warning']='Serienzugehörigkeit bekannt, Folge jedoch nicht bestimmt'
    result['identity_warning']=result.get('identity_warning','')
    if generic and identity['confidence'] in ('tentative','low','unknown'):
        result['identity_warning']='Titel aus unsicheren Archivangaben; Aufnahme/Folge manuell prüfen'
    if generic and result['episode'] is None:
        result['identity_warning']='Nummerierte Datei: Folge, Segment oder alternative Fassung nicht sicher bestimmbar'
    if result['identity_confidence']=='unknown':
        result['title']='Nicht zugeordnet · '+str(identifier if (identifier:=meta.get('identifier')) else item_title)[:75]
    return result
