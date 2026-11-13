"""Conservative AniList title lookup; no audio-language claims from the title.

The Internet Archive page title, filename and description are only *hints*.
Only a unique, strong result in AniList can turn an anime into a confirmed work.
"""
import difflib, json, re, unicodedata, urllib.request, urllib.error

QUERY='''query($search:String!){Page(page:1,perPage:12){media(search:$search,type:ANIME,isAdult:false){id title{romaji english native} synonyms format episodes duration seasonYear startDate{year} description(asHtml:false) coverImage{large} isAdult}}}'''

def folded(value):
    s=unicodedata.normalize('NFKC',str(value or '')).casefold()
    s=unicodedata.normalize('NFKD',s)
    s=''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(re.findall(r'[^\W_]+',s,re.UNICODE))

def script_hint(value):
    """Return original *title writing system* only; not proof of audio."""
    s=str(value or '')
    if re.search('[\u3040-\u30ff]',s):return ('ja','japanische Schrift', 'high')
    if re.search('[\uac00-\ud7af]',s):return ('ko','koreanische Schrift','high')
    if re.search('[\u4e00-\u9fff]',s):return ('und','Han-Zeichen: Japanisch oder Chinesisch','low')
    if re.search('[\u0400-\u052f]',s):return ('ru','kyrillische Schrift: Sprache unbestätigt','low')
    if re.search('[\u0600-\u06ff]',s):return ('und','arabische Schrift: Sprache unbestätigt','low')
    # Strong *orthographic* clues only. A short name such as "Blue Thermal" is
    # not sufficient to assert English audio or even the language of the title.
    words=set(re.findall(r'[^\W_]+',s.casefold(),re.UNICODE))
    hints={
      'de':{'der','die','das','und','eine','eines','einer','für','über','mit','auf','vom','zum','nicht','geschichte'},
      'en':{'the','and','with','from','into','about','story','of','without','world'},
      'es':{'las','los','del','una','unos','sin','para','con','aventuras','historia','secreto'},
      'fr':{'les','une','avec','pour','sans','dans','histoire','monde'},
      'it':{'gli','della','delle','senza','nella','storia','avventura'},
      'pt':{'dos','das','uma','uma','sem','história','historia','aventura'}}
    scores={code:len(words & markers) for code,markers in hints.items()}
    best=sorted(scores,key=lambda x:scores[x],reverse=True)
    if best and scores[best[0]]>=2 and scores[best[0]]>=scores[best[1]]+1:
        return (best[0],'Indizien aus Wörtern des Titels (keine Dub-Bestätigung)','low')
    return (None,'Lateinschrift: Sprache nicht zuverlässig bestimmbar','unknown')

def compare_aliases(candidate,media):
    title=media.get('title') or {}
    aliases=list(title.values()) + list(media.get('synonyms') or [])
    needle=folded(candidate)
    ranked=[]
    for alias in aliases:
        x=folded(alias)
        if not x:continue
        similarity=difflib.SequenceMatcher(None,needle,x).ratio()
        if needle==x:similarity=1.0
        ranked.append((similarity,alias))
    return max(ranked,key=lambda item:item[0],default=(0.0,''))

def choose(candidate,year,results):
    """Only a unique near-exact title match. Return None on ambiguous matches."""
    ranked=[]
    for media in results:
        if not isinstance(media,dict) or media.get('isAdult'):continue
        ratio,alias=compare_aliases(candidate,media)
        sy=media.get('seasonYear')
        if sy and year and abs(int(sy)-int(year))>1:continue
        ranked.append((ratio,media,alias))
    ranked.sort(key=lambda x:x[0],reverse=True)
    if not ranked or ranked[0][0]<.94:return None
    if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.07:return None
    score,media,alias=ranked[0]
    if not isinstance(media.get('id'),int):return None
    return {'id':media['id'],'score':round(score,3),'alias':alias,'media':media}

def query_anilist(title,timeout=25):
    req=urllib.request.Request('https://graphql.anilist.co',data=json.dumps({'query':QUERY,'variables':{'search':title}}).encode(),headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'MediathekAtlas'},method='POST')
    with urllib.request.urlopen(req,timeout=timeout) as r:data=json.load(r)
    if data.get('errors'):raise ValueError('AniList: '+str(data['errors'][0].get('message','Unbekannter Fehler'))[:100])
    return (((data.get('data') or {}).get('Page') or {}).get('media') or [])

def lookup_anime(candidate,year=None,query_fn=query_anilist):
    results=query_fn(candidate)
    return choose(candidate,year,results)

def title_languages(media,matched_alias):
    title=media.get('title') or {}
    found=[]
    for kind,code in [('native','ja'),('english','en')]:
        if title.get(kind) and folded(title[kind])==folded(matched_alias):found.append(code)
    if title.get('romaji') and folded(title['romaji'])==folded(matched_alias):found.append('ja-romaji')
    return found
