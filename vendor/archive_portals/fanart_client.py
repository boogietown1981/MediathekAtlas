"""Fanart.tv v3.2 artwork and cross-ID evidence. Never proves file identity."""
from __future__ import annotations
import json, re, urllib.error, urllib.parse, urllib.request

BASE='https://webservice.fanart.tv/v3.2'
_ALLOWED={'assets.fanart.tv','fanart.tv'}


def safe_image(url):
    if not isinstance(url,str) or len(url)>600:return None
    p=urllib.parse.urlparse(url)
    return url if p.scheme=='https' and p.hostname in _ALLOWED and not p.username and not p.password else None


def _images(data, kind):
    keys=(('movieposter','poster'),('moviebackground','background'),('hdmovielogo','logo'),('movielogo','logo')) if kind=='movie' else (
        ('tvposter','poster'),('showbackground','background'),('hdtvlogo','logo'),('clearlogo','logo'))
    result={}
    for source,dest in keys:
        choices=[]
        for item in data.get(source,[])[:30] if isinstance(data.get(source),list) else []:
            if not isinstance(item,dict):continue
            url=safe_image(item.get('url'))
            if not url:continue
            lang=str(item.get('lang') or '').lower()
            try:likes=int(item.get('likes') or 0)
            except (TypeError,ValueError):likes=0
            choices.append((int(lang in ('de','en','00')),likes,url,lang))
        if choices and dest not in result:
            _,_,url,lang=max(choices,key=lambda x:(x[0],x[1]))
            result[dest]={'url':url,'language':lang}
    return result


def lookup(kind, reference_id, *, source, project_key='', personal_key='', fetch=None):
    """Only lookup a previously identified work ID. The result is image evidence, not content proof."""
    if kind not in ('movie','series'):raise ValueError('Unbekannter Werktyp')
    allowed={'imdb','tmdb'} if kind=='movie' else {'imdb','tvdb','tmdb'}
    if source not in allowed:raise ValueError('Unbekannte Werkkennung')
    reference_id=str(reference_id or '')
    if source=='imdb' and not re.fullmatch(r'tt\d{5,12}',reference_id):raise ValueError('Ungültige IMDb-ID')
    if source!='imdb' and not re.fullmatch(r'\d{1,12}',reference_id):raise ValueError('Ungültige externe ID')
    if not project_key and not personal_key:return None
    path='movies' if kind=='movie' else 'tv'
    params={'source':source}
    # Credentials go into headers, not URLs, errors or logs.
    url=BASE+'/'+path+'/'+urllib.parse.quote(reference_id)+'?'+urllib.parse.urlencode(params)
    headers={'Accept':'application/json','User-Agent':'ArchiveMedia/0.10.51 (personal media catalogue)'}
    if project_key:headers['api-key']=project_key
    if personal_key:headers['client-key']=personal_key
    if fetch is None:
        def fetch(request):
            with urllib.request.urlopen(request,timeout=12) as response:
                if urllib.parse.urlparse(response.geturl()).hostname!='webservice.fanart.tv':
                    raise ValueError('Fanart.tv: unzulässige Weiterleitung')
                content=response.read(1024*1024+1)
                if len(content)>1024*1024:raise ValueError('Fanart.tv: Antwort zu groß')
                return json.loads(content)
    try:
        data=fetch(urllib.request.Request(url,headers=headers))
    except urllib.error.HTTPError as ex:
        # Do not show request URL containing credentials.
        if ex.code==404:return None
        if ex.code in (401,403):raise ValueError('Fanart.tv: API-Schlüssel abgelehnt') from None
        if ex.code==429:raise ValueError('Fanart.tv: Anfragelimit erreicht') from None
        raise ValueError('Fanart.tv: HTTP '+str(ex.code)) from None
    if not isinstance(data,dict):return None
    expected_field={'imdb':'imdb_id','tmdb':'tmdb_id','tvdb':'thetvdb_id'}[source]
    observed=str(data.get(expected_field) or '')
    # A returned different identifier is a conflict. Never offer its artwork.
    if observed and observed!=reference_id:
        return {'provider':'Fanart.tv','candidate_id':None,'candidate_kind':kind,
                'confidence':'conflict','reason':'Externe Werk-ID widerspricht der Referenz; Bilder gesperrt',
                'source_id':reference_id,'source_type':source,'images':{}}
    images=_images(data,kind)
    if not images:return None
    return {'provider':'Fanart.tv','candidate_id':reference_id,'candidate_kind':kind,
            'confidence':'possible','reason':'Bilder zu einer bestehenden Werk-ID, kein Beweis für Videoinhalt',
            'source_id':reference_id,'source_type':source,'id_corroborated':bool(observed),
            'images':images,'imdb_id':str(data.get('imdb_id') or '') or None}
