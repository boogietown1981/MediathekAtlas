"""Reviewable, atomic batch queueing for recognized series episodes."""
import json,hashlib,secrets,time
import core,catalog

MAX_ROWS=1000;WINDOW_AFTER=300;WINDOW_BEFORE=100

def plan(c,show,root,around=None):
    """``around`` (Staffel, Folge): automatisches Nachladen (series_autoload) bei sehr langen Serien. Statt der
    1.000er-Sperre nur ein Ausschnitt: bis WINDOW_AFTER Folgen danach und WINDOW_BEFORE davor (Mac-Prüfung 23.11.2026:
    „Sturm der Liebe“, „In aller Freundschaft“ bekamen sonst nie einen Auftrag)."""
    if not show:raise ValueError('Serie fehlt')
    rows=c.execute("SELECT * FROM works WHERE show_key=? AND kind='series'",(show,)).fetchall()
    if len(rows)>MAX_ROWS:
        if around is None:raise ValueError('Mehr als 1.000 Folgen: bitte einzelne Folgen auswählen')
        def pos(w):
            try:m=json.loads(w['meta'])
            except ValueError:return None
            s,e=m.get('season'),m.get('episode')
            return (s,e) if isinstance(s,int) and isinstance(e,int) else None
        last=(around[0] if around[0] is not None else -1,around[1] or 0)
        numbered=sorted(((pos(w),w) for w in rows if pos(w)),key=lambda x:x[0])
        rows=[w for p,w in numbered if p>last][:WINDOW_AFTER]+[w for p,w in numbered if p<=last][-WINDOW_BEFORE:]
    existing=set()
    for j in c.execute("SELECT payload FROM jobs WHERE state IN ('queued','downloading','tagging','done')"):
        existing.add(json.loads(j[0]).get('target'))
    eligible=[];skipped=[];seen=set()
    for w in rows:
        item=catalog.item(c,w)
        if not item:continue
        m=item['metadata'];reason='';target=''
        if w['state'] not in ('matched','manual'):reason='Werk erkannt, Episode noch nicht bestätigt' if w['state']=='identified' else 'Metadaten noch ungeprüft'
        elif item.get('downloaded'):reason='Bereits heruntergeladen'
        elif not item['available']:reason='Nicht mehr verfügbar'
        elif not item['best'] or not item['best']['supported']:reason='Kein unterstützter Direktdownload'
        else:
            try:target=str(core.target(root,m,item['id']))
            except ValueError as e:reason=str(e)
        episode=(m.get('season'),m.get('episode'))
        if not reason and (episode in seen or target in existing or core.existing_for(root,m,item['id'])):reason='Bereits vorhanden, eingereiht oder doppelte Folge'
        if reason:skipped.append({'title':m.get('episode_title') or m['title'],'reason':reason});continue
        seen.add(episode);eligible.append({'id':item['id'],'metadata':m,'source':{**item['source'],'_download_url':item['best']['url']},'target':target,'quality':'best','root':str(root)})
    eligible.sort(key=lambda i:(i['metadata']['season'],i['metadata']['episode']))
    fingerprint=hashlib.sha256(json.dumps(eligible,sort_keys=True).encode()).hexdigest()
    return {'eligible':eligible,'skipped':skipped,'fingerprint':fingerprint,'total':len(rows)}

def enqueue(c,show,root,fingerprint,ids=None):
    result=plan(c,show,root)
    if result['fingerprint']!=fingerprint:raise ValueError('Serienauswahl wurde inzwischen geändert. Vorschau erneut öffnen.')
    selected=result['eligible']
    if ids is not None:
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids):raise ValueError('Bitte mindestens eine Folge auswählen')
        valid={x['id'] for x in selected}
        if not set(ids)<=valid:raise ValueError('Ungültige Folge in der Auswahl')
        selected=[x for x in selected if x['id'] in set(ids)]
    for item in selected:
        j={**item,'id':secrets.token_hex(8),'state':'queued','received':0,'total':0,'batch_confirmed_at':time.time()}
        c.execute('INSERT INTO jobs VALUES(?,?,?)',(j['id'],json.dumps(j),'queued'))
    return {'queued':len(selected),'skipped':len(result['skipped'])}
