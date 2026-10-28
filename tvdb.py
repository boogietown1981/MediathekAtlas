"""TheTVDB v4 client. Credentials/tokens never form part of URLs or errors."""
import hashlib,json,threading,time
import core,diagnostics
_LOCK=threading.RLock()
_TOKENS={};_CACHE={};_PAUSED={}
class TVDBError(ValueError):
    def __init__(self,status=0):
        self.status=status
        message={401:'Zugang abgelehnt. Projektschlüssel und gegebenenfalls Abonnenten-PIN prüfen.',403:'Zugang nicht freigeschaltet. API-Berechtigung bzw. Abonnement prüfen.',429:'Anfragelimit erreicht; automatische Abfragen werden eine Stunde pausiert.'}.get(status,'Netzwerkfehler oder ungültige API-Antwort.')
        super().__init__('TVDB'+(' HTTP '+str(status) if status else '')+': '+message)
def _json(path,token='',body=None):
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if body is not None:headers['Content-Type']='application/json'
    try:
        with core.open_url('https://api4.thetvdb.com/v4/'+path,json.dumps(body).encode() if body is not None else None,headers) as r:raw=r.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise TVDBError()
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('status')!='success':raise TVDBError()
        return data
    except core.urllib.error.HTTPError as e:
        status=e.code;e.close();raise TVDBError(status) from None
    except (core.urllib.error.URLError,TimeoutError,OSError,UnicodeDecodeError,json.JSONDecodeError):raise TVDBError() from None

def request(path,key,pin='',params=None,force=False):
    credential=hashlib.sha256(json.dumps([key,pin]).encode()).hexdigest()
    if params:path+='?'+core.urllib.parse.urlencode(params)
    ck=(credential,path)
    # Serialise authentication/cache misses to avoid duplicate calls during bulk matching.
    with _LOCK:
        pause=_PAUSED.get(credential)
        if not force and pause and time.monotonic()<pause[0]:raise TVDBError(pause[1])
        cached=_CACHE.get(ck)
        if not force and cached and time.monotonic()-cached[0]<21600:return cached[1]
        try:
            for attempt in range(2):
                token=_TOKENS.get(credential)
                if force or not token or time.monotonic()-token[0]>27*86400:
                    body={'apikey':key}
                    if pin:body['pin']=pin
                    value=_json('login',body=body).get('data',{}).get('token')
                    if not isinstance(value,str) or not value:raise TVDBError()
                    diagnostics.register_secrets(value)
                    token=(time.monotonic(),value);_TOKENS[credential]=token
                try:
                    result=_json(path,token[1]);break
                except TVDBError as e:
                    if e.status==401 and attempt==0:_TOKENS.pop(credential,None);continue
                    raise
        except TVDBError as e:
            if e.status in (401,403,429):_PAUSED[credential]=(time.monotonic()+3600,e.status)
            raise
        _PAUSED.pop(credential,None)
        if len(_CACHE)>=256:_CACHE.pop(next(iter(_CACHE)))
        _CACHE[ck]=(time.monotonic(),result)
        return result

def test_access(key,pin=''):
    if not key:return {'ok':False,'message':'Kein TVDB-Projektschlüssel gespeichert. Zuerst Einstellungen speichern.'}
    try:
        request('search',key,pin,{'query':'Bibi und Tina','type':'series','limit':1},force=True)
        result={'ok':True,'message':'TVDB erreichbar. Anmeldung und Serienabfrage erfolgreich.'}
    except TVDBError as e:result={'ok':False,'message':str(e)}
    diagnostics.event('provider_connection_test',provider='TVDB',**result)
    return result
