"""Conservative, explicitly requested metadata lookup with identifiers, not fuzzy title matches.

No automatic bulk scraping of Open Library or MusicBrainz. Only use documented
public endpoints and already supplied, valid book ISBN or MusicBrainz release UUID.
"""
import json,re,urllib.request,urllib.error
from urllib.parse import quote

ISBN=re.compile(r'^(?:97[89]\d{10}|\d{9}[\dXx])$')
MBID=re.compile(r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')

def identifier(metadata, category):
    if category=='documents':
        for k in ('isbn','isbn13','isbn_13','isbn10','isbn_10'):
            x=str(metadata.get(k) or '').replace('-','').replace(' ','')
            if ISBN.fullmatch(x):return 'openlibrary',x
    if category=='audio':
        for k in ('musicbrainz_releaseid','musicbrainz_release_id','musicbrainzreleaseid'):
            x=str(metadata.get(k) or '').strip()
            if MBID.fullmatch(x):return 'musicbrainz',x.lower()
    return None,None

def request_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'ArchiveMedia/0.9.8 (personal media catalog; https://github.com/boogietown1981/ArchiveMedia)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=12) as response:
        if response.geturl().split('/')[2].lower() not in ('openlibrary.org','musicbrainz.org'):
            raise ValueError('Externer Redirect nicht erlaubt')
        data=response.read(384*1024)
    return json.loads(data)

def lookup(provider, id_value, fetch=request_json):
    if provider=='openlibrary' and ISBN.fullmatch(id_value):
        obj=fetch('https://openlibrary.org/isbn/'+quote(id_value)+'.json')
        if not isinstance(obj,dict) or not obj.get('title'):return None
        return {'provider':'Open Library','id':id_value,'title':obj['title'],
                'publish_date':obj.get('publish_date'),'number_of_pages':obj.get('number_of_pages'),
                'publishers':[p for p in obj.get('publishers',[]) if isinstance(p,str)][:8],
                'languages':[x.get('key','') for x in obj.get('languages',[]) if isinstance(x,dict)][:8]}
    if provider=='musicbrainz' and MBID.fullmatch(id_value):
        obj=fetch('https://musicbrainz.org/ws/2/release/'+quote(id_value)+'?fmt=json')
        if not isinstance(obj,dict) or obj.get('id','').lower()!=id_value.lower():return None
        return {'provider':'MusicBrainz','id':id_value,'title':obj.get('title'),
                'date':obj.get('date'),'country':obj.get('country'),
                'artist_credit':obj.get('artist-credit'), 'status':obj.get('status')}
    raise ValueError('Keine sichere externe Kennung vorhanden')
