let providerPauses={},lastArtwork=-1;const artworkRequested=new Set();
function visibleWarnings(warnings){return (warnings||[]).filter(w=>!(providerPauses.omdb?.paused&&/^OMDb(?::| HTTP)/i.test(w)));}
function countLabel(value){return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('de-DE'):'–';}
const $=id=>document.getElementById(id), token=document.querySelector('meta[name=atlas-token]').content;
let items=[],active=null,meta=null,offset=0,lastSearch=null;
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
// Confirmations disappear on their own; errors stay until closed or the cause is gone.
let noticeTimer=0,noticeSource='';
function notice(s,kind='info',source=''){clearTimeout(noticeTimer);const box=$('notice');box.replaceChildren();noticeSource=s?source:'';box.hidden=!s;if(!s)return;box.className=kind==='error'?'notice-error':'';box.append(el('span',s));const close=el('button','×','notice-close');close.type='button';close.title='Hinweis schließen';close.setAttribute('aria-label','Hinweis schließen');close.onclick=()=>notice('');box.append(close);if(kind!=='error')noticeTimer=setTimeout(()=>notice(''),7000);}
async function request(path,data){const control=new AbortController(),timer=setTimeout(()=>control.abort(),60000);try{return await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Atlas-Token':token},body:data?JSON.stringify(data):undefined,signal:control.signal});}catch(e){throw Error(e.name==='AbortError'?'Der lokale Dienst antwortet seit 60 Sekunden nicht. Erneuter Versuch folgt.':'Verbindung zum lokalen Dienst unterbrochen. Falls sie nicht zurückkehrt: MediathekAtlas erneut öffnen.');}finally{clearTimeout(timer);}}
async function api(path,data){const r=await request(path,data);const d=await r.json();if(r.status===401&&d.login){location.reload();throw Error('Anmeldung abgelaufen. Bitte erneut anmelden.');}if(!r.ok)throw Error(d.error||'Anfrage fehlgeschlagen');return d;}
async function busy(button,fn){const old=button.textContent;button.disabled=true;button.textContent='Bitte warten …';try{await fn();}catch(e){notice(e.message,'error');if($('editor').open)$('lookup-status').textContent=e.message;}finally{button.disabled=false;button.textContent=old;}}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{for(const v of ['discover','review','queue','subscriptions','settings','logs'])$(v).hidden=v!==b.dataset.view;$('title-view').hidden=true;$('title-view').replaceChildren();document.body.classList.remove('title-open');document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n===b));if(b.dataset.view==='review'){loadReview();loadProviderStats();loadRecognition();}if(b.dataset.view==='subscriptions')loadSubscriptions();};
function openSubscriptionView(){
 const tab=document.querySelector('[data-view="subscriptions"]');
 if(tab)tab.click();
}
function updateSubscriptionSchedule(){
 const weekly=$('subscription-mode').value==='weekly';
 for(const el of document.querySelectorAll('.subscription-weekday,.subscription-hour'))el.hidden=!weekly;
}
$('subscription-mode').onchange=updateSubscriptionSchedule;
$('subscription-kind').onchange=()=>{
 $('subscription-show-key').value='';
 if($('subscription-kind').value!=='movie')$('subscription-year').value='';
 $('subscription-existing').checked=$('subscription-kind').value==='movie';
};
updateSubscriptionSchedule();
function subscriptionDate(ts){
 return ts?new Date(ts*1000).toLocaleString('de-DE'):'–';
}
async function loadSubscriptions(){
 if(appStopped||$('subscriptions').hidden)return;
 try{
   const response=await api('subscriptions'),host=$('subscription-list');
   host.replaceChildren();
   if(!response.items.length){host.append(el('p','Noch keine Abos. Titel oben eingeben und automatischen Download ausdrücklich bestätigen.','empty'));return;}
   for(const sub of response.items){
     const card=el('article',undefined,'atlas-subscription'),
           title=el('h3',sub.title+' · '+(sub.kind==='series'?'Serie':'Film')),
           status=el('p',sub.enabled?'● Aktiv':'○ Pausiert','atlas-subscription-state'),
           when=el('small',(sub.mode==='weekly'?'Wöchentliche Prüfung':'Bei Verfügbarkeit')+
             ' · nächster Check: '+subscriptionDate(sub.next_check)),
           details=el('small','Bereits automatisch eingereiht: '+countLabel(sub.queued_count||0)+
             (sub.last_check?' · zuletzt geprüft: '+subscriptionDate(sub.last_check):'')),
           actions=el('div',undefined,'atlas-subscription-buttons');
     for(const [label,action] of [[sub.enabled?'Pausieren':'Fortsetzen',sub.enabled?'pause':'resume'],['Löschen','delete']]){
       const button=el('button',label);
       button.onclick=e=>busy(e.target,async()=>{
         if(action==='delete'&&!confirm('Abo „'+sub.title+'“ entfernen? Bereits angelegte Downloadaufträge bleiben erhalten.'))return;
         await api('subscription-action',{id:sub.id,action});await loadSubscriptions();
       });
       actions.append(button);
     }
     if(sub.enabled){
       const run=el('button','Jetzt prüfen');run.onclick=e=>busy(e.target,async()=>{
         const r=await api('subscription-check',{id:sub.id});
         notice((r.items||[]).reduce((n,x)=>n+x.queued,0)+' geprüfte Direktdownloads neu eingereiht.');
         await loadSubscriptions();await refresh();
       });actions.prepend(run);
     }
     card.append(title,status,when,details);
     if(sub.last_error)card.append(el('small','Letzter Fehler: '+sub.last_error,'atlas-subscription-error'));
     card.append(actions);host.append(card);
   }
 }catch(e){notice('Abos konnten nicht geladen werden: '+e.message,'error');}
}
$('subscription-refresh').onclick=()=>loadSubscriptions();
$('subscription-form').onsubmit=e=>{
 e.preventDefault();
 busy(e.submitter,async()=>{
   await api('subscription-add',{
     title:$('subscription-title').value.trim(),kind:$('subscription-kind').value,
     year:$('subscription-year').value||null,
     show_key:$('subscription-show-key').value,mode:$('subscription-mode').value,
     weekday:Number($('subscription-weekday').value),hour:Number($('subscription-hour').value),
     include_existing:$('subscription-existing').checked,
     confirmed:$('subscription-consent').checked
   });
   $('subscription-consent').checked=false;
   $('subscription-show-key').value='';
   notice('Download-Abo angelegt. Nur bestätigte, verfügbare Direktdateien werden eingereiht.');
   await loadSubscriptions();
 });
};
setInterval(()=>{if(!$('subscriptions').hidden)loadSubscriptions();},30000);

let catalogRetry=0;let filters={kind:'series',genre:'',show:'',archive:false},catalogRevision='',catalogBusy=false,lastMetadataChecks=-1,catalogSequence=0,catalogKey='';
const kindLabels={movie:'Filme',series:'Serien',unknown:'Noch zuordnen',other:'Weitere Sendungen'};
function selectFilter(change){$('collection-filter').value='';filters={kind:'',genre:'',show:'',archive:false,...change};offset=0;loadCatalog().catch(e=>notice(e.message,'error'));}
function availabilityLabel(source){
 const value=source?.available_until;
 if(!value)return 'Ablaufdatum nicht angegeben – bei der Senderseite prüfen';
 const dayOnly=/^\d{4}-\d{2}-\d{2}$/.test(value);
 const date=new Date(dayOnly?value+'T23:59:59':value);
 if(!Number.isFinite(date.getTime()))return 'Ablaufdatum nicht angegeben – bei der Senderseite prüfen';
 const label=date.toLocaleDateString('de-DE',dayOnly?{day:'2-digit',month:'2-digit',year:'numeric'}:{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
 const provenance=source.availability_source?' · '+source.availability_source:'';
 if(date.getTime()<Date.now())return 'Laut Quelle abgelaufen: '+label+provenance+' · Direktlink prüfen';
 return (date.getTime()-Date.now()<=3*86400000?'Bald nicht mehr verfügbar · bis ':'Verfügbar bis ')+label+provenance;
}
function linkQuality(link){return link.quality+' (Senderangabe)'+(link.height_hint?' · '+link.height_hint+'p laut Dateiname':' · Pixelauflösung nicht angegeben');}
function sourceLinks(links){const box=el('div',undefined,'source-links');box.append(el('strong','Verfügbare Dateien'));
 for(const link of links||[]){if(!/^https?:\/\//.test(link.url))continue;
 const row=el('div',undefined,'source-link'),a=el('a',linkQuality(link));a.href=link.url;a.target='_blank';a.rel='noopener noreferrer';a.title=link.url;
 row.append(a,el('small',link.supported?'Direktdatei · Quelllink öffnen':'HLS/DASH-Stream · App-Download noch nicht unterstützt'));box.append(row);}
 if(!(links||[]).length)box.append(el('small','Keine Dateilinks vorhanden.'));return box;}
function render(){const host=$('results');host.classList.toggle('episode-list',!!filters.show);host.replaceChildren();if(!items.length){host.append(el('div','Keine Treffer für diese Auswahl. Filter zurücksetzen oder eine andere Kategorie wählen. Der Import läuft im Hintergrund weiter.','empty'));return;}
for(const item of items){const r=item.source,m=item.metadata,card=el('article',undefined,'card'),art=el('div',undefined,'art');
if(safeArt(m.poster)){const img=el('img');img.src=m.poster;img.loading='lazy';img.alt='Poster: '+m.title;img.onerror=()=>img.remove();art.append(img);}
art.append(el('strong',m.kind==='series'?'SERIE':m.kind==='movie'?'FILM':'ZUORDNUNG OFFEN'),el('span',item.series_parent?item.episodes+' Folgen':Math.round(r.duration/60)+' Min.'));
const body=el('div',undefined,'cardbody'),displayTitle=m.title||r.title,heading=el('h3',displayTitle+(m.year&&m.kind==='movie'?' ('+m.year+')':''));heading.title=heading.textContent;
if(m.kind==='series'&&m.networks?.length)body.append(el('small',m.networks.join(' · ')));const pick=pickLabel(m,item.state);if(pick){const badge=el('div',pick,'pick-badge');badge.title=pickReason(m);body.append(badge);}if(m.rating!=null&&Number.isFinite(Number(m.rating)))body.append(el('small','★ '+m.rating+' / 10 · '+ratingSource(m)));
body.append(el('span',(m.genres||[]).slice(0,2).join(' · ')||'Genre offen','eyebrow'),heading,el('p',((item.series_parent?m.show_description:'')||m.description||r.description||'').slice(0,110),'synopsis'));
if(m.kind==='series'&&!item.series_parent){const number=Number.isInteger(m.season)&&Number.isInteger(m.episode)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0')+' · ':'';body.append(el('p',number+(m.episode_title||r.title),'episode-heading'));}
body.append(el('p',meshDownloadLabel(item.mesh_download)+(item.downloaded&&!item.mesh_download?(item.file_state==='missing'?'⚠ Datei am bisherigen Pfad nicht gefunden · ':'✓ Heruntergeladen · '):'')+({identified:'◐ Werk erkannt · Datei noch prüfen',matched:'✓ Metadaten zugeordnet',manual:'✓ Manuell geprüft',review:'◌ Zuordnung prüfen',pending:'◌ Metadaten vorgemerkt',retry:'◌ Abgleich wird wiederholt',format:'◇ Beitrag einer Sendung · nicht abgeglichen'}[item.state]||'◌ Metadaten prüfen')+(m.year?' · '+m.year:''),'badge'));
if(item.series_parent){const b=el('button','Serie öffnen · '+item.episodes+' Folgen');b.onclick=()=>openShow(item.show_key);const bulk=el('button','Serie gesammelt laden');bulk.onclick=()=>openSeries(item.show_key);body.append(b,bulk);}
else{const files=el('details',undefined,'file-details');files.append(el('summary','Dateien & Qualität'),sourceLinks(item.links));body.append(files);body.append(el('p',(item.available?'Bevorzugt: ':'Archiviert: ')+(item.special||'Reguläre Fassung')+' · '+r.channel+' · '+(item.best?.quality||'?')+' (Senderangabe)','qualityline'));if(r.available_until)body.append(el('p',availabilityLabel(r),'availability-line'));const b=el('button',item.available?'Beste Fassung prüfen & laden':'Metadaten ansehen');b.onclick=()=>edit(item);body.append(b);
const details=el('details',undefined,'alternatives');details.append(el('summary','Weitere Fassungen ('+item.offer_count+')'));details.ontoggle=async()=>{if(!details.open||details.dataset.loaded)return;try{const d=await api('alternatives?work_id='+encodeURIComponent(item.work_id));for(const a of d.items){const box=el('div',undefined,'alternative');box.append(el('strong',a.source.channel+' · '+(a.special||'Regulär')+(a.available?'':' · nicht mehr gelistet')+(a.same_media_count>1?' · '+a.same_media_count+' identische Einträge gebündelt':'')));if(a.source.available_until)box.append(el('small',availabilityLabel(a.source)));for(const l of a.links){const line=el('p',linkQuality(l)+' · '+(l.supported?'Direktdatei':'Stream, derzeit kein Download'));if(/^https?:\/\//.test(l.url)){const link=el('a','Quelllink');link.href=l.url;link.target='_blank';link.rel='noopener noreferrer';line.append(' · ',link);}box.append(line);}const choose=el('button','Diese Fassung prüfen');choose.onclick=()=>edit(a);box.append(choose);details.append(box);}details.dataset.loaded='1';}catch(e){notice(e.message,'error');}};body.append(details);}
if(playable(item)){const play=el('button',item.series_parent?'▶ Serie abspielen':'▶ Abspielen','play-button');play.title=item.downloaded&&item.file_state!=='missing'?'Lokale Datei abspielen':'Online-Stream des Senders abspielen';play.onclick=()=>playMedia(item,filters.show?items:null);body.append(play);}
const detail=el('button',item.series_parent?'Serienseite':'Details & Bilder','detail-link');detail.onclick=()=>openTitle(item);body.append(detail);art.classList.add('clickable');art.title='Titelseite öffnen';art.onclick=()=>openTitle(item);heading.classList.add('clickable');heading.onclick=()=>openTitle(item);card.append(art,body);host.append(card);}}
async function loadCatalog(){
 const snapshot={...filters},pageOffset=offset;
 const q=new URLSearchParams({query:$('query').value,kind:snapshot.kind,genre:snapshot.genre,show:snapshot.show,archive:snapshot.archive?'1':'0',state:$('state-filter').value,sort:$('sort-filter').value,collection:$('collection-filter').value,downloaded:$('download-filter').value,offset:pageOffset});
 const key=q.toString();if(catalogBusy&&catalogKey===key)return;
 catalogBusy=true;catalogKey=key;const sequence=++catalogSequence;
 $('results').setAttribute('aria-busy','true');$('results-title').textContent='Auswahl wird geladen …';
 try{const d=await api('catalog?'+key);if(sequence!==catalogSequence)return;
 items=d.items;render();const artIds=items.map(x=>x.work_id).filter(id=>id&&!artworkRequested.has(id));if(artIds.length){artIds.forEach(id=>artworkRequested.add(id));api('artwork-priority',{ids:artIds}).catch(()=>{});}$('results-title').textContent=(snapshot.show&&items.length?items[0].metadata.title+' · ':'')+d.total+' '+(snapshot.show?'Folgen':'Werke')+' · Seite '+(Math.floor(pageOffset/48)+1);
 $('browse-series').classList.toggle('primary',snapshot.kind==='series');$('browse-movies').classList.toggle('primary',snapshot.kind==='movie');$('series-actions').hidden=!snapshot.show;
 $('more').disabled=pageOffset+48>=d.total;$('back').disabled=pageOffset===0;
 $('filter-label').textContent=[snapshot.archive?'Auch nicht mehr gelistete Angebote':'Aktuell gelistet',kindLabels[snapshot.kind]||(q.get('state')?'Alle Medienarten':'Filme & Serien'),snapshot.genre,$('collection-filter').value?$('collection-filter').selectedOptions[0].textContent:'',$('state-filter').selectedOptions[0].textContent].filter(Boolean).join(' › ');
 if(noticeSource==='catalog')notice('');catalogRetry=0;
 }catch(e){if(sequence===catalogSequence){catalogRevision='';if(catalogRetry++<2){$('results-title').textContent='Auswahl wird erneut geladen …';setTimeout(()=>{catalogKey='';loadCatalog().catch(()=>{});},3000*catalogRetry);}else{$('results-title').textContent='Katalog konnte nicht geladen werden';notice('Katalog konnte nicht geladen werden: '+e.message,'error','catalog');}}}
 finally{if(sequence===catalogSequence){catalogBusy=false;$('results').setAttribute('aria-busy','false');}}
}
let treeBusy=false,treeRows=[],treeRetry=null,treeSignature='';
function renderTree(rows){const host=$('catalog-tree');const opened=new Set([...host.querySelectorAll('details[open]')].map(x=>x.dataset.kind));host.replaceChildren();const all=el('button','Alle Werke');all.onclick=resetFilters;host.append(all);for(const kind of ['movie','series','unknown','other']){const rows=treeRows.filter(r=>r.kind===kind),branch=el('details');branch.dataset.kind=kind;branch.open=opened.has(kind);branch.append(el('summary',kindLabels[kind]));const b=el('button','Alle '+kindLabels[kind]);b.onclick=()=>selectFilter({kind});branch.append(b);for(const r of rows){const b=el('button',r.genre+' · '+r.n);b.onclick=()=>selectFilter({kind,genre:r.genre});branch.append(b);}host.append(branch);}const archived=el('button','Archiv inkl. nicht mehr gelistet');archived.onclick=()=>selectFilter({archive:true});host.append(archived);}
async function loadTree(){if(appStopped||treeBusy)return;treeBusy=true;clearTimeout(treeRetry);try{
 const d=await api('catalog-tree');const signature=JSON.stringify(d.tree);
 if(signature!==treeSignature){treeRows=d.tree;renderTree(treeRows);treeSignature=signature;}
 $('tree-status').textContent=d.loading?'Genres werden im Hintergrund ermittelt …':d.error?'Genre-Abfrage fehlgeschlagen: '+d.error:'';
 if(d.loading)treeRetry=setTimeout(loadTree,2500);
 }catch(e){$('tree-status').textContent='Genres konnten nicht geladen werden: '+e.message;}finally{treeBusy=false;}}
function resetFilters(){$('query').value='';$('state-filter').value='';$('sort-filter').value='title';$('download-filter').value='hide';$('collection-filter').value='';selectFilter({});}
$('browse-series').onclick=()=>selectFilter({kind:'series'});$('browse-movies').onclick=()=>selectFilter({kind:'movie'});$('series-pick').onclick=()=>openSeries(filters.show);
$('reset-filters').onclick=resetFilters;
$('tree-retry').onclick=()=>loadTree();
$('search').onsubmit=e=>{e.preventDefault();offset=0;busy(e.submitter,loadCatalog);};
$('more').onclick=e=>{offset+=48;busy(e.target,loadCatalog);};$('back').onclick=e=>{offset=Math.max(0,offset-48);busy(e.target,loadCatalog);};
$('catalog').onclick=resetFilters;
$('remote-search').onclick=e=>busy(e.target,async()=>{const d=await api('search',{query:$('query').value});notice(d.imported+' Online-Angebote in den Katalog übernommen.');offset=0;await loadCatalog();await loadTree();});
$('sync-now').onclick=e=>busy(e.target,async()=>{await api('sync',{});notice('Aktualisierung angefordert. Fortschritt erscheint über dem Katalog.');});
const atlasStatusFields=[
 ['offers','Angebote','Aktive Senderangebote'],
 ['matched','Vollständig zugeordnet','Film oder Episode bestätigt'],
 ['identified','Werke erkannt','Folge ggf. noch offen'],
 ['pending','Vorgemerkt','Prüfung oder Wiederholung'],
 ['review','Zu prüfen','Weitere Belege erforderlich'],
 ['formats','Sendungsbeiträge','Kein Filmabgleich nötig'],
 ['first_pass_remaining','Erstprüfung offen','Noch nie geprüft'],
 ['first_pass_per_minute','Erstprüfungen / Min.','Tatsächlicher Nettofortschritt'],
 ['match_rate_session','Vollständige Trefferquote','Seit App-Start · ohne Sendungsformate'],
 ['matched_per_hour_session','Bestätigte Werke / Std.','Seit App-Start · hochgerechnet']
];
function catalogProgress(c){
 if(!c)return;
 const sync=c.sync||{},phase={waiting:'Wartet auf Import',downloading:'Filmliste wird geladen',importing:'Angebote werden einsortiert',complete:'Katalog aktuell',paused:'Import pausiert',error:'Import unterbrochen',retrying:'Download wird erneut versucht'}[sync.phase]||sync.phase||'Katalog aktuell';
 $('catalog-phase').textContent=phase;
 $('catalog-progress-text').textContent=(sync.phase==='downloading'?'Geladen: '+((sync.received||0)/1048576).toFixed(1)+' / '+((sync.total||0)/1048576).toFixed(1)+' MiB':sync.processed?'Letzter Import: '+countLabel(sync.processed)+' Einträge':'')+(sync.error?' · '+sync.error:'')+(sync.updated_at&&Date.now()/1000-sync.updated_at>50&&['downloading','importing'].includes(sync.phase)?' · Seit über 50 Sekunden kein Fortschritt':'');
 const board=$('catalog-status');
 if(!board.dataset.ready){
   for(const [key,label,description] of atlasStatusFields){
     const card=el('div',undefined,'atlas-metric'),cap=el('span',label,'atlas-metric-label'),value=el('strong','–','atlas-metric-value'),foot=el('small',description,'atlas-metric-foot');
     card.dataset.metric=key;value.dataset.value=key;foot.dataset.foot=key;card.append(cap,value,foot);board.append(card);
   }
   board.dataset.ready='1';
 }
 for(const [key] of atlasStatusFields){
   const value=board.querySelector('[data-value="'+key+'"]');
   if(value)value.textContent=key==='first_pass_per_minute'||key==='matched_per_hour_session'?(Number(c[key])>0?Number(c[key]).toLocaleString('de-DE',{maximumFractionDigits:1}):'–'):key==='match_rate_session'?Number(c[key]||0).toLocaleString('de-DE',{maximumFractionDigits:1})+' %':countLabel(c[key]||0);
 }
 const eta=board.querySelector('[data-foot="first_pass_remaining"]');
 if(eta){
   eta.textContent=c.first_pass_eta_hours!=null?'Ca. '+(c.first_pass_eta_hours<24?c.first_pass_eta_hours.toLocaleString('de-DE',{maximumFractionDigits:1})+' Std.':(c.first_pass_eta_hours/24).toLocaleString('de-DE',{maximumFractionDigits:1})+' Tage'):'Messung läuft';
   eta.title='Schätzung aus dem Netto-Durchsatz der Erstprüfungen. Neue oder intern umklassifizierte Werke können den Restbestand verändern.';
 }
 const importBox=$('catalog-import-summary'),diff=c.last_import_diff||{};
 if(Object.keys(diff).length){
   const values=[['Neu',diff.added,'added'],['Geändert',diff.changed,'changed'],['Wieder verfügbar',diff.reactivated,'reactivated'],['Entfallen',diff.removed,'removed'],['Unverändert',diff.unchanged,'unchanged']];
   if(!importBox.dataset.ready){importBox.append(el('span','Letzter Abgleich','atlas-import-caption'));for(const [label,,key] of values){const tag=el('span',undefined,'atlas-import-chip');tag.dataset.importKey=key;importBox.append(tag);}importBox.dataset.ready='1';}
   for(const [label,count,key] of values){const tag=importBox.querySelector('[data-import-key="'+key+'"]');if(tag)tag.textContent=label+' · '+countLabel(count||0);}
 }else importBox.replaceChildren();
 const rev=[c.offers,c.matched,c.identified,c.review,c.works,c.formats].join(':');
 if(rev!==catalogRevision&&!$('editor').open&&!document.querySelector('.alternatives[open]')){catalogRevision=rev;loadCatalog().catch(()=>{});loadTree().catch(()=>{});}
 const workers=$('metadata-workers-status');
 if(workers)workers.textContent='Parallele Erkennung: '+countLabel(c.recognition_workers_active||0)+
   ' von '+countLabel(c.recognition_workers_configured||2)+' Workern aktiv. Externe Anbieteranfragen bleiben auf zwei gleichzeitig begrenzt.'+
   ' · '+countLabel(c.quality_session?.identified||0)+' Werke erkannt, Folge offen'+
   ' · '+countLabel(c.quality_session?.matched||0)+' vollständig bestätigt'+
   ' · Episoden-Queue: '+countLabel(c.episode_queue_total||0)+' offen ('+countLabel(c.episode_queue_due||0)+' bereit)' +
   ' · Episodenworker: '+countLabel(c.episode_workers_active||0)+'/'+countLabel(c.episode_workers_configured||2)+
   ' · '+countLabel(c.episode_matched_session||0)+' Folgen bestätigt'+
   (c.sqlite_busy_retries_session?' · '+countLabel(c.sqlite_busy_retries_session)+' SQLite-Wiederholungen':'');
}
const fields=['title','kind','year','season','episode','episode_title','description'];
function fill(){$('genres').value=(meta.genres||[]).join(', ');for(const f of fields)$(f).value=meta[f]??'';$('confirmed').checked=false;$('preview').textContent='Bitte Zielnamen prüfen.';}
function readMeta(){const out={...meta};for(const f of fields)out[f]=$(f).value;for(const f of ['year','season','episode'])out[f]=out[f]===''?null:Number(out[f]);out.genres=$('genres').value.split(',').map(x=>x.trim()).filter(Boolean);return out;}
function edit(item){active=item;meta={...item.metadata};fill();$('source').textContent=[item.source.channel,item.source.topic,item.source.title,item.source.description].filter(Boolean).join(' · ');
 const expire=$('availability-before-download');expire.textContent='Ablaufdatum wird, soweit verfügbar, beim Sender geprüft …';
 api('availability?id='+encodeURIComponent(item.id)).then(d=>{
   if(active!==item||!$('editor').open)return;
   item.source={...item.source,available_until:d.available_until,availability_source:d.source};
   expire.textContent=availabilityLabel(item.source)+(d.error?' · Abfrage derzeit nicht möglich':'');
 }).catch(()=>{if(active===item&&$('editor').open)expire.textContent='Ablaufdatum konnte nicht abgefragt werden – Senderseite prüfen';});$('candidates').replaceChildren();$('lookup-status').textContent=visibleWarnings(item.metadata.metadata_warnings).join(' ');showCandidates(item.metadata.suggestions||[]);$('editor').showModal();const editing=active,previewMeta=JSON.stringify(readMeta());api('preview',{id:item.id,metadata:meta}).then(d=>{if(active===editing&&$('editor').open&&JSON.stringify(readMeta())===previewMeta)$('preview').textContent=d.path;}).catch(()=>{});}
$('close').onclick=()=>$('editor').close();
for(const f of fields)$(f).addEventListener('input',()=>{$('confirmed').checked=false;$('preview').textContent='Metadaten geändert – Zielnamen erneut prüfen.';if(['title','kind','year','season','episode'].includes(f)){meta.provider='manuell';meta.reference_id=null;meta.poster='';meta.fanart='';meta.artwork_provider='';for(const key of ['ratings','rating','rating_source','votes','networks','studios','imdb_id','discovery_enriched'])delete meta[key];}});
function showCandidates(rows){$('candidates').replaceChildren();for(const c of rows){const n=el('div',undefined,'candidate');n.append(el('strong',c.title+' '+(c.year?'('+c.year+')':'')),el('p',c.provider+' · '+(c.kind==='series'?'Serie':'Film')+' · '+c.reason),el('p',evidence(c)+(c.plausibility_issues?.length?' · Prüfung: '+c.plausibility_issues.join('; '):''),'muted'));const b=el('button','Angaben übernehmen');b.onclick=()=>{meta={...c};fill();};n.append(b);$('candidates').append(n);}}
$('lookup').onclick=e=>busy(e.target,async()=>{$('lookup-status').textContent='Anbieter werden abgefragt …';const d=await api('candidates',{id:active.id,metadata:readMeta()});$('lookup-status').textContent=d.candidates.length+' Kandidaten. '+visibleWarnings(d.warnings).join(' ');showCandidates(d.candidates);});
$('save-metadata').onclick=e=>busy(e.target,async()=>{await api('save-metadata',{id:active.id,metadata:readMeta()});$('lookup-status').textContent='Metadaten dauerhaft im Katalog gespeichert.';await loadCatalog();await loadTree();if(!$('review').hidden)await loadReview();});
$('preview-button').onclick=e=>busy(e.target,async()=>{$('preview').textContent=(await api('preview',{id:active.id,metadata:readMeta()})).path;});
$('metadata').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{await api('download',{id:active.id,metadata:readMeta(),quality:$('quality').value,confirmed:$('confirmed').checked});$('editor').close();notice('Download hinzugefügt. Fortschritt unter Downloads.');await refresh();});};
$('config').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{await api('settings',{download_dir:$('download_dir').value,tmdb:$('tmdb').value,omdb:$('omdb').value,tvdb:$('tvdb').value,tvdb_pin:$('tvdb_pin').value,auto_catalog:$('auto_catalog').checked,auto_metadata:$('auto_metadata').checked,scan_priority:$('scan_priority').value,complete_series:$('complete_series').checked,metadata_workers:Number($('metadata_workers').value),episode_workers:Number($('episode_workers').value),library_dirs:$('library_dirs').value});$('tmdb').value=$('omdb').value=$('tvdb').value=$('tvdb_pin').value='';notice('Einstellungen gespeichert.');await refresh();});};
$('clear-keys').onclick=e=>busy(e.target,async()=>{await api('settings',{clear_tmdb:true,clear_omdb:true,clear_tvdb:true,clear_tvdb_pin:true});await refresh();});
const labels={queued:'Wartet',downloading:'Wird heruntergeladen',tagging:'Spuren prüfen & Metadaten einbetten',done:'Fertig',error:'Fehler',cancelled:'Abgebrochen',interrupted:'Durch Neustart unterbrochen',remote:'Auf anderem System'};
function renderRuntime(r){const host=$('runtime-details');host.replaceChildren();for(const k of ['python','ffmpeg','ffprobe']){const t=r[k],box=el('div',undefined,'runtime-item');box.append(el('strong',k+' · '+(t.ok?'Bereit':t.error)),el('p',t.path||'Kein verwendbarer Pfad'),el('small',t.version||''));if(t.failed_candidates?.length)box.append(el('p','Nicht startbar: '+t.failed_candidates.map(x=>x.path).join(', ')));host.append(box);}}
$('recheck-tools').onclick=e=>busy(e.target,async()=>renderRuntime(await api('tools')));
let refreshing=false,appStopped=false;
async function refresh(){if(refreshing||appStopped)return;refreshing=true;try{const d=await api('state');const finished=d.jobs.filter(j=>j.state==='done').map(j=>j.id).join(':');if(finished!==completedRevision){completedRevision=finished;catalogRevision='';}latestSettings=d.settings;renderServer(d.server||{});if(lastArtwork!==(d.artwork_checked||0)){lastArtwork=d.artwork_checked||0;catalogRevision='';}renderImdb(d.imdb);providerPauses=d.provider_pauses||{};renderMetadata(d.metadata,d.settings,providerPauses);if((d.metadata?.checked_session||0)!==lastMetadataChecks){lastMetadataChecks=d.metadata?.checked_session||0;catalogRevision='';}if(d.reclassification?.phase==='running')$('metadata-status').append(el('small','Neuklassifizierung läuft · '+countLabel(d.reclassification.processed)+' Werke verarbeitet. Die Restlaufzeit kann vorübergehend schwanken.','atlas-current-warning'));$('connection-status').hidden=true;catalogProgress(d.catalog);if(!$('config').contains(document.activeElement)){$('auto_catalog').checked=d.settings.auto_catalog;$('auto_metadata').checked=d.settings.auto_metadata;$('scan_priority').value=d.settings.scan_priority||'balanced';$('complete_series').checked=d.settings.complete_series!==false;$('metadata_workers').value=String(d.settings.metadata_workers||2);$('episode_workers').value=String(d.settings.episode_workers||2);}renderRuntime(d.runtime);renderMesh(d.mesh,d.settings);$('tools').textContent=d.tools.ffmpeg&&d.tools.ffprobe?'● FFmpeg & ffprobe bereit':'○ Werkzeugprüfung: Einstellungen öffnen';$('jobcount').textContent=d.jobs.filter(j=>['queued','downloading','tagging'].includes(j.state)).length;if(document.activeElement!==$('download_dir'))$('download_dir').value=d.settings.download_dir;if(document.activeElement!==$('library_dirs'))$('library_dirs').value=(d.settings.library_dirs||[]).join('\n');$('key-state').textContent='TMDB: '+(d.settings.tmdb_set?'hinterlegt':'nicht eingerichtet')+' · OMDb: '+(d.settings.omdb_set?'hinterlegt':'nicht eingerichtet')+' · TVDB: '+(d.settings.tvdb_set?'hinterlegt':'nicht eingerichtet')+' · TVDB-PIN: '+(d.settings.tvdb_pin_set?'hinterlegt':'nicht hinterlegt');const host=$('jobs');host.className='grid job-grid';if(document.activeElement?.closest('.job-file-missing'))return;host.replaceChildren();if(!d.jobs.length)host.append(el('div','Noch keine Downloads. Wähle einen Suchtreffer und prüfe seine Metadaten.','empty'));for(const j of d.jobs)host.append(jobCard(j,d.server||{}));}finally{refreshing=false;}}
function connectionError(e){$('connection-status').textContent=e.message+' Letzter Versuch: '+new Date().toLocaleTimeString('de-DE');$('connection-status').hidden=false;}
let logPaused=false,logBusy=false;
async function refreshLog(){if(appStopped||logBusy||logPaused||$('logs').hidden)return;logBusy=true;try{const d=await api('logs');const box=$('live-log'),atEnd=box.scrollTop+box.clientHeight>=box.scrollHeight-40;box.textContent=d.text?d.text.split('\n').map(line=>{try{const r=JSON.parse(line),{time,level,event,traceback,...details}=r;return time+'  '+level+'  '+event+'\n'+JSON.stringify(details,null,2)+(traceback?'\n'+traceback:'');}catch{return line;}}).join('\n\n'):'Noch keine Ereignisse.';if(atEnd)box.scrollTop=box.scrollHeight;$('log-status').textContent='Aktualisiert: '+new Date().toLocaleTimeString('de-DE')+' · letzte 400 Zeilen · Zeitstempel im Log: UTC';}catch(e){$('log-status').textContent=e.message;}finally{logBusy=false;}}
$('pause-log').onclick=()=>{logPaused=!logPaused;$('pause-log').textContent=logPaused?'Live-Ansicht fortsetzen':'Ansicht pausieren';if(!logPaused)refreshLog();};
$('export-log').onclick=e=>busy(e.target,async()=>{const r=await request('diagnostics');if(!r.ok)throw Error('Diagnoseexport fehlgeschlagen');const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='MediathekAtlas_Diagnose_'+new Date().toISOString().replace(/[:.]/g,'-')+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
renderTree([]);loadCatalog();loadTree();refresh().catch(connectionError);setInterval(()=>{refresh().catch(connectionError);refreshLog();},2500);

function renderMetadata(m={},settings={},pauses={}){
 const labels={checking:'Prüft gerade',result:'Letztes Ergebnis',waiting:'Wartet auf fällige Einträge',paused:'Pausiert',error:'Abgleichfehler'};
 const outcomes={matched:'Vollständig zugeordnet',identified:'Werk erkannt – Folge offen',review:'Zuordnung prüfen',retry:'Wiederholung vorgesehen'};
 const current=$('metadata-status');
 current.replaceChildren();
 const name=el('strong',(labels[m.phase]||'Wird gestartet')+(m.title?' · '+m.title:''),'atlas-current-title');
 const summary=el('small',(m.outcome?outcomes[m.outcome]+' · ':'')+countLabel(m.checked_session||0)+' Abgleiche seit Start');
 current.append(name,summary);
 const warnings=visibleWarnings(m.warnings);
 if(warnings.length||m.error)current.append(el('small',warnings.join(' ')+' '+(m.error||''),'atlas-current-warning'));
 const host=$('provider-status');host.replaceChildren();host.className='atlas-provider-grid';
 const providers=[
  ['TMDB',settings.tmdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.tmdb_set],
  ['TVDB',settings.tvdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.tvdb_set],
  ['OMDb',pauses.omdb?.paused?'Pausiert · '+Math.ceil(pauses.omdb.remaining_seconds/60)+' Min.':settings.omdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.omdb_set&&!pauses.omdb?.paused],
  ['Wikidata','Kostenlose Rückfallquelle',true],
  ['IMDb Offline',imdbReady?'Lokales Archiv bereit':'Archiv nicht bereit',imdbReady]
 ];
 for(const [label,status,good] of providers){
   const cell=el('span',undefined,'atlas-provider'+(good?' enabled':''));
   cell.append(el('strong',label),el('small',status));host.append(cell);
 }
 const checked=(m.provider_checks||[]).filter(x=>x.status!=='not_configured'&&x.status!=='paused').map(x=>x.provider+': '+(x.status==='error'?'Fehler':x.status==='negative_cache'?'Nichttreffer-Cache':x.count+' Treffer'));
 if(checked.length)host.append(el('small','Letzte Abfragen'+(m.from_cache?' · Cache':'')+': '+checked.join(' · '),'atlas-provider-last'));
 if(!settings.auto_metadata)host.append(el('small','Automatischer Abgleich ausgeschaltet','atlas-provider-last'));
}
$('collection-filter').onchange=()=>{filters.kind=$('collection-filter').value==='cinema'?'movie':$('collection-filter').value==='series'?'series':filters.kind;filters.show='';filters.genre='';offset=0;loadCatalog().catch(e=>notice(e.message,'error'));};
$('download-filter').onchange=$('state-filter').onchange=$('sort-filter').onchange=()=>{offset=0;loadCatalog().catch(e=>notice(e.message,'error'));};
$('priority-metadata').onclick=e=>busy(e.target,async()=>{const d=await api('metadata-priority',{ids:items.map(x=>x.work_id),show:filters.show});notice(d.queued+' Einträge priorisiert.'+(d.enabled?'':' Bitte automatischen Metadatenabgleich in Einstellungen einschalten.'));});
let seriesPlan=null,seriesShow='';
async function openSeries(show){try{seriesShow=show;seriesPlan=await api('series-plan',{show});$('series-confirmed').checked=false;$('series-summary').textContent=seriesPlan.eligible.length+' Folgen ladbar · '+seriesPlan.skipped.length+' ausgelassen';const host=$('series-plan');host.replaceChildren();for(const x of seriesPlan.eligible){const n=el('div',undefined,'batch-row'),check=el('input');check.type='checkbox';check.checked=true;check.value=x.id;check.setAttribute('aria-label','S'+x.season+'E'+x.episode+' auswählen');check.onchange=updateSeriesSelection;n.append(check);n.append(el('strong','S'+String(x.season).padStart(2,'0')+'E'+String(x.episode).padStart(2,'0')+' · '+x.title),el('p',x.target));if(x.source?.available_until)n.append(el('small',availabilityLabel(x.source)));host.append(n);}if(seriesPlan.skipped.length){const details=el('details');details.append(el('summary','Ausgelassene Folgen anzeigen'));for(const x of seriesPlan.skipped)details.append(el('p',x.title+' · '+x.reason));host.append(details);}$('series-all').checked=!!seriesPlan.eligible.length;updateSeriesSelection();$('series-dialog').showModal();}catch(e){notice(e.message,'error');}}
$('series-close').onclick=()=>$('series-dialog').close();
$('series-submit').onclick=e=>busy(e.target,async()=>{if(!$('series-confirmed').checked)throw Error('Bitte Folgen und Zielnamen zuerst prüfen und bestätigen.');const d=await api('series-download',{show:seriesShow,fingerprint:seriesPlan.fingerprint,ids:[...document.querySelectorAll('#series-plan input:checked')].map(x=>x.value),confirmed:true});$('series-dialog').close();notice(d.queued+' Folgen in die Downloadwarteschlange aufgenommen.');await refresh();});

setInterval(()=>{if(!appStopped&&!$('discover').hidden)loadTree().catch(()=>{});},30000);

$('mesh-config').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{await api('settings',{mesh_dir:$('mesh_dir').value.trim(),mesh_name:$('mesh_name').value.trim(),mesh_init:$('mesh_init').checked});$('mesh_init').checked=false;notice($('mesh_dir').value.trim()?'Verbund gespeichert. Der Ordner wird geprüft.':'Verbund ausgeschaltet.');await refresh();});};
let meshServer={};
let meshShareKey='',meshServicePort=0,meshTailscale='';
function meshAddress(){
 const text=$('mesh-address').value.trim();
 let u;
 try{u=new URL(text);}catch{throw Error('Bitte eine gültige NAS-Dienstadresse angeben (z. B. http://192.168.1.10:8730).');}
 if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password||u.search||u.hash||u.pathname!=='/')
    throw Error('Nur eine HTTP(S)-Basisadresse ohne Pfad, Login-Daten oder Schlüssel eingeben.');
 return u.origin;
}
function updateMeshCode(){
 if(!meshShareKey)return;
 try{
   const address=meshAddress();
   $('mesh-code').value=address+'#'+meshShareKey;
   $('mesh-code-hint').textContent='Diesen vollständigen Code im anderen MediathekAtlas einfügen.'+
     (meshTailscale?' Tailscale-Alternative: http://'+meshTailscale+':'+meshServicePort+' (bei Bedarf oben eintragen).':'');
 }catch(e){$('mesh-code').value='';$('mesh-code-hint').textContent=e.message;}
}
function showMeshCode(d){
 meshShareKey=d.key||'';meshServicePort=d.port;meshTailscale=d.tailscale||'';
 // Never use location.origin: when opened through DSM/QTS (5001/8080)
 // that port is often NOT the MediathekAtlas HTTP endpoint.
 if(!$('mesh-address').value.trim()){
   const host=location.hostname.includes(':')?'['+location.hostname+']':location.hostname;
   $('mesh-address').value='http://'+host+':'+d.port;
 }
 $('mesh-code-box').hidden=false;updateMeshCode();
}
$('mesh-address').oninput=updateMeshCode;
$('mesh-share').onclick=e=>busy(e.target,async()=>{const d=await api('mesh-direct',{action:'share'});showMeshCode(d);await refresh();});
$('mesh-rotate').onclick=e=>busy(e.target,async()=>{
 if(!confirm('Wirklich einen neuen Verbundschlüssel erzeugen? Alle bisher verbundenen Mac-/NAS-Geräte müssen anschließend den neuen Verbindungscode erhalten. Die Verbunddaten bleiben erhalten.'))return;
 const d=await api('mesh-direct',{action:'rotate',confirmed:true});
 showMeshCode(d);notice('Neuer Verbundschlüssel erstellt. Bitte den neuen Code auf allen anderen Geräten erneut einfügen.');await refresh();
});
$('mesh-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('mesh-code').value);notice('Verbindungscode kopiert.');}catch{$('mesh-code').select();notice('Bitte mit Cmd/Strg+C kopieren.');}};
$('mesh-connect').onclick=e=>busy(e.target,async()=>{const d=await api('mesh-direct',{action:'connect',code:$('mesh-peer-code').value.trim()});$('mesh-peer-code').value='';notice('Verbunden mit „'+(d.peer||'Gegenstelle')+'“. Der Abgleich läuft alle 30 Sekunden. Weitere Systeme lassen sich genauso hinzufügen.');await refresh();});
$('mesh-off').onclick=e=>busy(e.target,async()=>{await api('mesh-direct',{action:'unshare'});$('mesh-code-box').hidden=true;notice('Freigabe beendet. Andere Systeme können sich nicht mehr mit diesem System verbinden.');await refresh();});
function renderPeer(m={},settings={}){$('mesh-off').hidden=!settings.mesh_shared;$('mesh-rotate').hidden=!settings.mesh_shared||!meshServer.network;$('mesh-share').textContent=settings.mesh_shared?'Verbindungscode anzeigen':'Dieses System freigeben';const host=$('peer-status');host.replaceChildren();
const states={};for(const p of m.peers||[])states[p.url]=p;
if(settings.mesh_shared)host.append(el('p','● Freigegeben: Andere Systeme können sich mit dem Verbindungscode dieses Systems verbinden.'));
for(const url of settings.mesh_peers||[]){const p=states[url]||{};const row=el('div',undefined,'peer-row');const when=t=>new Date(t*1000).toLocaleTimeString('de-DE');
 row.append(el('span',p.error?'⚠ '+url+': '+p.error+(p.last?' · zuletzt erfolgreich '+when(p.last):''):p.time?'● Verbunden mit „'+p.peer+'“ ('+url+') · Version '+(p.peer_version||'?')+' · letzter Abgleich '+when(p.time)+' · '+p.received+' empfangen, '+p.sent+' gesendet':'◌ Verbindung zu '+url+' wird aufgebaut …'));
 const rm=el('button','Entfernen');rm.type='button';rm.onclick=()=>busy(rm,async()=>{await api('mesh-direct',{action:'remove',url});notice('Verbindung zu '+url+' entfernt.');await refresh();});row.append(rm);host.append(row);}}
function meshDownloadLabel(m){if(!m)return '';return ({loading:'↓ Wird auf „'+m.name+'“ geladen · ',local:'✓ Auf „'+m.name+'“ geladen, hier vorhanden · ',transfer:'✓ Auf „'+m.name+'“ geladen, MeshSync überträgt · ',remote:'✓ Auf „'+m.name+'“ geladen (Downloadordner dort nicht geteilt) · '})[m.state]||'';}
function renderMesh(m={},settings={}){renderPeer(m,settings);if(!$('mesh-config').contains(document.activeElement)){$('mesh_dir').value=settings.mesh_dir||'';$('mesh_name').value=settings.mesh_name||'';}const host=$('mesh-nodes');host.replaceChildren();if(!m.enabled){$('mesh-status').textContent=m.error?'Verbund nicht verfügbar: '+m.error+' Dieses System erkennt bis dahin alle Titel allein.':(settings.mesh_dir||settings.mesh_shared||(settings.mesh_peers||[]).length?'Verbund wird eingerichtet …':'Verbund ist ausgeschaltet.');return;}$('mesh-status').textContent='Verbund aktiv · dieses System bearbeitet '+m.partitions+' von 256 Bereichen · '+countLabel(m.imported||0)+' Ergebnisse anderer Systeme übernommen'+(m.media_shared?' · Downloadordner liegt in einem MeshSync-Ordner und wird verteilt':' · Downloadordner liegt nicht in einem MeshSync-Ordner, Downloads bleiben auf diesem System')+(m.invalid?' · '+m.invalid+' ungültige Einträge übersprungen':'')+(m.importing?' · Übernahme läuft, weitere Ergebnisse folgen':'')+(m.backlog&&m.backlog.done===false?' · Bisherige Ergebnisse werden geteilt: '+countLabel(m.backlog.shared||0)+' übertragen, noch '+countLabel(m.backlog.left||0)+' Werke':'');for(const n of m.nodes||[]){const age=n.age<120?'gerade eben':n.age<7200?'vor '+Math.round(n.age/60)+' Min.':'vor '+Math.round(n.age/3600)+' Std.';host.append(el('p',(n.self?'● ':n.active?'● ':'○ ')+n.name+(n.self?' (dieses System)':'')+' · '+(n.recognizing?(n.active?'erkennt mit':'nicht erreichbar, Bereiche verteilt'):'Erkennung ausgeschaltet')+(n.rate?' · '+n.rate+' Titel/Min.':'')+' · Version '+(n.version||'?')+' · Lebenszeichen '+age,'muted'));}}
$('test-omdb').onclick=e=>busy(e.target,async()=>{$('omdb-test-result').textContent='OMDb wird direkt abgefragt …';try{const d=await api('test-omdb',{});$('omdb-test-result').textContent=d.message;}catch(error){$('omdb-test-result').textContent=error.message;}});

$('test-tvdb').onclick=e=>busy(e.target,async()=>{$('tvdb-test-result').textContent='TVDB wird direkt abgefragt …';try{const d=await api('test-tvdb',{});$('tvdb-test-result').textContent=d.message;}catch(error){$('tvdb-test-result').textContent=error.message;}});

$('quit-app').onclick=e=>busy(e.target,async()=>{await api('shutdown',{});appStopped=true;clearTimeout(treeRetry);notice('MediathekAtlas wurde beendet. Dieses Browserfenster kann geschlossen werden.');});

let reviewRows=[],reviewOffset=0,reviewSequence=0,reviewSelection=new Set(),latestSettings={};
const reviewLabels={pending:'Vorgemerkt',retry:'Wiederholung',review:'Zu prüfen',identified:'Werk erkannt · Folge offen',matched:'Automatisch zugeordnet',manual:'Manuell bestätigt',format:'Beitrag einer Sendung · nicht abgeglichen'};
function selectionStatus(){$('review-selected').textContent=reviewSelection.size+' ausgewählt';$('review-priority').disabled=!reviewSelection.size;}
function evidence(m){const values=[];if(m.provider)values.push('Quelle: '+m.provider);if(m.reference_id)values.push('ID: '+m.reference_id);if(Number.isFinite(m.similarity))values.push('Titelähnlichkeit: '+Math.round(m.similarity*100)+' % (keine Trefferwahrscheinlichkeit)');if(m.episode_verified)values.push('Episode abgeglichen');if(m.year_mismatch)values.push('Erscheinungsjahr widerspricht');if(m.runtime_mismatch)values.push('Laufzeit widerspricht');if(m.reason)values.push(m.reason);return values.join(' · ')||'Noch keine externen Belege.';}
async function loadReview(){const sequence=++reviewSequence;try{const d=await api('review?'+new URLSearchParams({query:$('review-query').value,state:$('review-state').value,offset:reviewOffset}));if(sequence!==reviewSequence)return;reviewRows=d.items;reviewSelection.clear();$('review-all').checked=false;selectionStatus();$('review-count').textContent=d.total+' Einträge · Seite '+(Math.floor(reviewOffset/48)+1);$('review-prev').disabled=reviewOffset===0;$('review-next').disabled=reviewOffset+48>=d.total;const host=$('review-list');host.replaceChildren();if(!reviewRows.length)host.append(el('p','Keine Einträge für diese Auswahl.','empty'));
for(const item of reviewRows){const row=el('article',undefined,'review-row'),check=el('input');check.type='checkbox';check.setAttribute('aria-label','Auswählen: '+item.metadata.title);check.dataset.work=item.work_id;check.onchange=()=>{if(check.checked)reviewSelection.add(item.work_id);else reviewSelection.delete(item.work_id);selectionStatus();};const source=el('div'),target=el('div'),action=el('div');source.append(el('small','QUELLE'),el('h3',item.source.title),el('p',[item.source.topic,item.source.channel].filter(Boolean).join(' · ')));target.append(el('small','KATALOG'),el('h3',item.metadata.title),el('p',(kindLabels[item.metadata.kind]||'Noch unklar')+' · '+(item.metadata.year||'Jahr offen')+' · '+reviewLabels[item.state]),el('p',evidence(item.metadata),'muted'));if(item.metadata.kind==='series')target.append(el('p',item.metadata.episode_title||'Episode offen'));const suggestions=item.metadata.suggestions||[];if(suggestions.length)target.append(el('small',suggestions.length+' Vorschläge im Prüfdialog'));const button=el('button','Vergleichen & korrigieren');button.onclick=()=>edit(item);action.append(button);row.append(check,source,target,action);host.append(row);}}
catch(e){if(sequence===reviewSequence)$('review-count').textContent=e.message;}}
async function loadRecognition(){if(appStopped||$('review').hidden)return;try{const d=await api('recognition'),host=$('recognition-table'),total={channel:'Gesamt',works:0,matched:0,identified:0,format:0,review:0,open:0};host.replaceChildren();const pct=(n,of)=>of?(100*n/of).toLocaleString('de-DE',{maximumFractionDigits:1})+' %':'–';for(const r of d.channels)for(const k of ['works','matched','identified','format','review','open'])total[k]+=r[k];for(const r of d.channels.length?[total,...d.channels]:[]){const tr=el('tr',undefined,r===total?'total':''),scan=r.works-r.format;for(const value of [r.channel,countLabel(r.works),countLabel(r.matched),countLabel(r.identified),countLabel(r.format),countLabel(r.review),countLabel(r.open),pct(r.matched+r.identified,scan)])tr.append(el('td',String(value)));host.append(tr);}$('recognition-status').textContent=d.error?'Auswertung fehlgeschlagen: '+d.error:d.loading?(d.channels.length?'Wird aktualisiert …':'Auswertung wird berechnet. Bei großen Katalogen dauert das einige Sekunden.'):'Stand der letzten Auswertung; aktualisiert höchstens alle 10 Minuten.';if(d.loading)setTimeout(loadRecognition,5000);}catch(e){notice(e.message,'error');}}
async function loadProviderStats(){if(appStopped||$('review').hidden)return;try{const d=await api('provider-stats'),host=$('provider-table');host.replaceChildren();for(const r of d.rows){const tr=el('tr'),field=r.provider.toLowerCase(),sender=/Mediathek$/.test(r.provider),configured=r.provider==='IMDb Offline'?imdbReady:r.provider==='Wikidata'||sender||latestSettings[field+'_set'],paused=field==='omdb'&&providerPauses.omdb?.paused;for(const value of [r.provider,paused?'Pause · '+Math.ceil(providerPauses.omdb.remaining_seconds/60)+' Min.':configured?(r.provider==='Wikidata'?'Rückfallquelle':sender?'Senderdaten · ohne Schlüssel':'Eingerichtet'):'Kein Zugang',r.checks,r.with_hits,r.candidates,r.errors,r.paused_skips,r.cached_skips||0,r.last_success?new Date(r.last_success*1000).toLocaleTimeString('de-DE'):'–'])tr.append(el('td',String(value)));host.append(tr);}}catch(e){notice(e.message,'error');}}
$('review-search').onsubmit=e=>{e.preventDefault();reviewOffset=0;loadReview();};$('review-state').onchange=()=>{reviewOffset=0;loadReview();};$('review-prev').onclick=()=>{reviewOffset=Math.max(0,reviewOffset-48);loadReview();};$('review-next').onclick=()=>{reviewOffset+=48;loadReview();};$('review-all').onchange=()=>{reviewSelection=new Set($('review-all').checked?reviewRows.map(x=>x.work_id):[]);for(const c of $('review-list').querySelectorAll('input[type=checkbox]'))c.checked=$('review-all').checked;selectionStatus();};$('review-priority').onclick=e=>busy(e.target,async()=>{const d=await api('metadata-priority',{ids:[...reviewSelection]});notice(d.queued+' Einträge für den Abgleich priorisiert.'+(d.enabled?'':' Automatischen Abgleich in Einstellungen einschalten.'));});
setInterval(loadProviderStats,5000);

function updateSeriesSelection(){const boxes=[...document.querySelectorAll('#series-plan input[type=checkbox]')],n=boxes.filter(x=>x.checked).length;$('series-submit').disabled=!n;$('series-submit').textContent=n+' Folgen herunterladen';$('series-all').checked=!!boxes.length&&n===boxes.length;$('series-all').indeterminate=n>0&&n<boxes.length;$('series-confirmed').checked=false;}
$('series-all').onchange=()=>{document.querySelectorAll('#series-plan input').forEach(x=>x.checked=$('series-all').checked);updateSeriesSelection();};

let imdbReady=false;
function imdbDate(seconds){return seconds&&Number.isFinite(Number(seconds))?new Date(Number(seconds)*1000).toLocaleString('de-DE'):'nicht gespeichert';}
function renderImdb(s={}){
 imdbReady=!!s.ready;
 const phases={waiting:'Erstimport steht an',downloading:'Datensatz wird geladen',
   importing:'SQLite-Import',indexing:'Suchindizes werden erstellt',retrying:'Wiederhole unterbrochenen Download',ready:'Archiv bereit',
   error:'Aktualisierung fehlgeschlagen'};
 const phase=phases[s.phase]||'Nicht gestartet',last=imdbDate(s.updated),next=imdbDate(s.next_update);
 const busy=['downloading','retrying','importing','indexing'].includes(s.phase);
 const size=s.archive_bytes>0?(s.archive_bytes/1073741824).toLocaleString('de-DE',{maximumFractionDigits:2})+' GiB':'–';
 const staged=Array.isArray(s.staged_downloads)?s.staged_downloads:[];
 const cachedBytes=staged.reduce((n,x)=>n+(x.downloaded_bytes||0)+(x.partial_bytes||0),0);
 const cachedCount=staged.filter(x=>x.downloaded_bytes>0).length;
 const cachedInfo=cachedBytes?' · Zwischendaten '+(cachedBytes/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MiB ('+cachedCount+'/7 Dateien vollständig)':'';
 const status=phase+(s.dataset?' · '+s.dataset:'')+
  (['downloading','retrying'].includes(s.phase)?' · '+((s.received||0)/1048576).toFixed(1)+' MiB'+(s.total?' / '+(s.total/1048576).toFixed(1)+' MiB':''):'')+
  (s.phase==='importing'?' · '+countLabel(s.rows||0)+' Zeilen':'')+
  (s.updated?' · Letzter erfolgreicher Archivaufbau: '+last:' · Noch kein fertiges Archiv')+
  (s.next_update?' · Nächster Versuch: '+next:'')+
  (s.error?' · '+s.error:'')+cachedInfo;
 $('imdb-status').textContent=status;
 $('imdb-update').disabled=busy;
 const quick=$('imdb-dashboard-summary');
 if(quick)quick.textContent=s.updated?'Stand: '+last+(s.phase==='error'?' · Update fehlgeschlagen':''):'Noch kein fertiges Archiv';
 const info=$('imdb-dashboard-info');
 if(info){
   const paragraphs=[
     'Status: '+phase,
     s.updated?'Zuletzt erfolgreich erstellt: '+last:'Noch kein erfolgreicher Import',
     s.next_update?'Nächste Prüfung: '+next:'',
     s.archive_bytes?'Archivdatei: '+size:'',
     cachedInfo?'Gespeicherte Download-Zwischenstände: '+cachedInfo.replace(/^ · /,''):'',
     s.error?'Letzter Fehler: '+s.error:''
   ].filter(Boolean);
   info.replaceChildren(...paragraphs.map(line=>el('div',line,'atlas-imdb-info-line')));
 }
 const settings=$('imdb-settings-summary');
 if(settings)settings.textContent=(s.ready?'7 IMDb-Datenarten · zuletzt aufgebaut '+last+' · '+size:'Noch kein vollständiges IMDb-Archiv')+
    (s.next_update?' · nächster Versuch '+next:'')+
    (s.phase==='error'?' · letzter Aktualisierungsversuch fehlgeschlagen':'');
 const entries=Array.isArray(s.datasets)?s.datasets:[];
 const signature=JSON.stringify([entries,staged]);
 for(const id of ['imdb-dataset-grid','imdb-settings-datasets']){
   const host=$(id);
   if(!host||host.dataset.signature===signature)continue;
   host.dataset.signature=signature;
   host.replaceChildren();
   if(!entries.length){host.append(el('small','Datensatzliste wird geladen …'));continue;}
   for(const dataset of entries){
     const pending=staged.find(x=>x.key===dataset.key)||{},
           row=el('div',undefined,'atlas-imdb-dataset'),
           label=el('strong',dataset.label||dataset.key||'Datensatz'),
           file=el('small',dataset.file||dataset.key,'atlas-imdb-file'),
           number=dataset.available?(dataset.rows!=null?countLabel(dataset.rows)+' Einträge':'Im Archiv vorhanden · Umfang nicht protokolliert'):'Noch nicht importiert',
           updated=dataset.retrieved_at?'Datei übernommen: '+imdbDate(dataset.retrieved_at):'Einzelzeitpunkt nicht gespeichert',
           downloading=(pending.downloaded_bytes?'Datei gespeichert: '+(pending.downloaded_bytes/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MiB':'')+
             (pending.partial_bytes?' · Teil-Download: '+(pending.partial_bytes/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MiB':'');
     row.append(label,file,el('small',number,'atlas-imdb-count'),el('small',updated,'atlas-imdb-stamp'));
     if(downloading)row.append(el('small',downloading,'atlas-imdb-count'));
     host.append(row);
   }
 }
}
$('imdb-update').onclick=e=>busy(e.target,async()=>{const d=await api('imdb-update',{});notice(d.queued?'IMDb-Aktualisierung angefordert.':'IMDb-Aktualisierung läuft bereits.');await refresh();});

function safeArt(url){try{const u=new URL(url);return u.protocol==='https:'&&['image.tmdb.org','artworks.thetvdb.com','www.thetvdb.com','m.media-amazon.com','ia.media-imdb.com','api.ardmediathek.de','img.ardmediathek.de','www.zdf.de','epg-image.zdf.de','www.zdfheute.de'].includes(u.hostname);}catch{return false;}}
function openDetail(item){const m=item.metadata;$('detail-title').textContent=m.title||item.source.title;$('detail-type').textContent=m.kind==='series'?'Serie':'Film';$('detail-facts').textContent=[m.year,(m.genres||[]).join(' · '),'',item.series_parent?item.episodes+' angebotene Folgen':''].filter(Boolean).join(' · ');$('detail-plot').textContent=m.description||item.source.description||'Noch keine Beschreibung vorhanden.';const credits=m.show_credits||m;$('detail-credits').textContent=[credits.directors?.length?'Regie: '+credits.directors.join(', '):'',credits.cast?.length?'Besetzung: '+credits.cast.slice(0,8).map(x=>x.name).join(', '):''].filter(Boolean).join(' · ');$('detail-art-status').textContent=(m.artwork_provider?'Bilder: '+m.artwork_provider:(!latestSettings.tmdb_set&&!latestSettings.tvdb_set?'Für zusätzliche Bilder einen TMDB- oder TVDB-Zugang in Einstellungen hinterlegen.':latestSettings.auto_metadata===false?'Automatische Bildergänzung ist mit dem Metadatenabgleich pausiert.':'Bilder werden bei eindeutiger Zuordnung ergänzt.'))+(!m.poster||!m.fanart?' · Noch nicht alle Bildtypen vorhanden.':'');for(const [id,url] of [['detail-cover',m.poster],['detail-backdrop',m.fanart]]){const box=$(id);box.replaceChildren();if(safeArt(url)){const img=el('img');img.src=url;img.alt=id==='detail-cover'?'Cover: '+m.title:'';img.onerror=()=>{img.remove();$('detail-art-status').textContent='Bild derzeit nicht abrufbar. Metadaten bleiben verfügbar.';};box.append(img);}else if(id==='detail-cover')box.append(el('span','Cover folgt'));}const subscribe=$('detail-subscribe');
 subscribe.onclick=()=>{
   $('media-detail').close();
   $('subscription-title').value=m.title||item.source.title||'';
   $('subscription-kind').value=m.kind==='movie'?'movie':'series';
   $('subscription-year').value=m.kind==='movie'?(m.year||''):'';
   $('subscription-show-key').value=m.kind==='series'?item.show_key||'':'';
   $('subscription-existing').checked=m.kind==='movie';
   $('subscription-consent').checked=false;
   openSubscriptionView();
 };
 const action=$('detail-action');action.textContent=item.series_parent?'Folgen ansehen':'Metadaten prüfen & herunterladen';action.onclick=()=>{$('media-detail').close();if(item.series_parent)selectFilter({kind:'series',show:item.show_key});else edit(item);};renderDetailExtras(item);$('media-detail').showModal();}
$('detail-close').onclick=()=>$('media-detail').close();

function renderDetailExtras(item){
 const m=item.metadata,r=item.source,credits=item.series_parent?(m.show_credits||m):m;
 const rating=Number(m.rating);$('detail-rating').textContent=m.rating!=null&&m.rating!==''&&Number.isFinite(rating)?'★ '+rating.toLocaleString('de-DE')+' / 10 · '+(m.rating_source||(['OMDb','IMDb Offline'].includes(m.provider)?'IMDb':m.provider||'Quelle unbekannt'))+(m.votes!=null?' · '+countLabel(Number(m.votes))+' Stimmen':''):'Bewertung noch nicht vorhanden';
 renderRatings(m);
 const data=$('detail-data');data.replaceChildren();const add=(k,v)=>{if(v!==undefined&&v!==null&&v!==''){data.append(el('dt',k),el('dd',String(v)));}};
 add('Empfehlung',pickLabel(m,item.state)?pickReason(m):null);add('Originalsender / Netzwerk',(m.networks||[]).join(', '));add('Produktionsfirmen',(m.studios||[]).join(', '));add('Metadatenquelle',m.provider);add('Anbieter-ID',m.reference_id);add('Zuordnung',({manual:'Manuell bestätigt',matched:'Automatisch bestätigt',identified:'Werk erkannt · Folge noch prüfen',pending:'Noch offen',review:'Prüfung erforderlich',retry:'Abgleich vorgemerkt',format:'Beitrag einer Sendung · nicht mit Filmdatenbanken abgeglichen'})[item.state]||item.state);
 if(!item.series_parent){add('Laufzeit des Angebots',r.duration?Math.round(r.duration/60)+' Minuten':null);add('Sender',r.channel);add('Fassung',item.special||'Regulär');add('Verfügbarkeit',item.available?'Aktuell gelistet':'Nicht mehr gelistet');add('Ablaufdatum',availabilityLabel(r));if(m.kind==='series'){add('Staffel / Folge',Number.isInteger(m.season)&&Number.isInteger(m.episode)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0'):'Noch nicht bestätigt');add('Episodentitel',m.episode_title);}}
 add('Drehbuch',(credits.writers||[]).join(', '));
 $('detail-credits').textContent=[credits.directors?.length?'Regie: '+credits.directors.join(', '):'',credits.cast?.length?'Besetzung: '+credits.cast.map(x=>x.name+(x.role?' ('+x.role+')':'')).join(', '):''].filter(Boolean).join(' · ');
 renderPlaySlot(item);
 const host=$('detail-downloads');host.replaceChildren();
 if(item.series_parent){const b=el('button','Folgen auswählen & herunterladen');b.onclick=()=>{$('media-detail').close();openSeries(item.show_key);};host.append(b);return;}
 host.append(el('h3','Downloadlinks & Qualität'),sourceLinks(item.links),el('p','Quelllinks öffnen die Originaldatei. Für saubere Dateinamen, NFO und eingebettete Metadaten den Download über die App starten.','muted'));
 const alternatives=el('details',undefined,'alternatives');alternatives.append(el('summary','Weitere Angebote / Fassungen ('+(item.offer_count||1)+')'));host.append(alternatives);
 alternatives.ontoggle=async()=>{if(!alternatives.open||alternatives.dataset.loading||alternatives.dataset.loaded)return;alternatives.dataset.loading='1';try{const d=await api('alternatives?work_id='+encodeURIComponent(item.work_id));for(const a of d.items){const box=el('div',undefined,'alternative');box.append(el('strong',(a.source.channel||'Quelle')+' · '+(a.special||'Regulär')+(a.available?'':' · nicht mehr gelistet')),sourceLinks(a.links));const b=el('button','Diese Fassung prüfen & laden');b.onclick=()=>{$('media-detail').close();edit(a);};box.append(b);alternatives.append(box);}alternatives.dataset.loaded='1';}catch(e){alternatives.append(el('p',e.message,'muted'));}finally{delete alternatives.dataset.loading;}};
}

// Play button above the download actions of the detail view (film, episode or whole series).
function renderPlaySlot(item){const slot=$('detail-play');slot.replaceChildren();if(!playable(item))return;const b=el('button',item.series_parent?'▶ Serie abspielen':'▶ Abspielen','play-button');b.onclick=()=>{$('media-detail').close();playMedia(item);};slot.append(b);}
let completedRevision='';
const openJobDetails=new Set();
function fileUrl(j,inline){return '/api/download-file?'+new URLSearchParams({id:j.id,token,inline:inline?'1':'0'});}
// Download cards follow the catalogue cards: cover on top, the essentials below, file details folded away.
function jobCard(j,server){const m=j.metadata||{},card=el('article',undefined,'card job job-'+j.state),art=el('div',undefined,'art');
if(safeArt(m.poster)){const img=el('img');img.src=m.poster;img.alt='Cover: '+(m.title||'');img.loading='lazy';img.onerror=()=>img.remove();art.append(img);}
art.append(el('strong',m.kind==='series'?'SERIE':m.kind==='movie'?'FILM':'DOWNLOAD'));if(j.state==='done'&&j.size_bytes)art.append(el('span',(j.size_bytes/1073741824>=1?(j.size_bytes/1073741824).toFixed(1)+' GB':Math.round(j.size_bytes/1048576)+' MB')));
const body=el('div',undefined,'cardbody'),episode=m.kind==='series'&&Number.isInteger(m.season)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0')+(m.episode_title?' · '+m.episode_title:''):'';
const heading=el('h3',(m.title||j.source?.title||'Download')+(m.year&&m.kind==='movie'?' ('+m.year+')':''));heading.title=heading.textContent;
body.append(el('span',(m.genres||[]).slice(0,2).join(' · ')||'Genre offen','eyebrow'),heading);if(episode)body.append(el('p',episode,'episode-heading'));
body.append(el('p',(j.state==='done'?(j.file_state==='missing'?'⚠ ':'✓ '):j.state==='error'?'⚠ ':'◌ ')+(j.state==='done'&&j.file_state==='missing'?'Datei verschoben / derzeit nicht erreichbar':(labels[j.state]||j.state))+(m.provider?' · '+m.provider:''),'badge'));
if(j.state==='downloading'){const p=el('progress');p.max=j.total||1;if(j.total)p.value=j.received||0;body.append(p,el('small',((j.received||0)/1048576).toFixed(1)+' MiB'+(j.total?' / '+(j.total/1048576).toFixed(1)+' MiB':'')+' · '+(Number(j.speed)>0?(j.speed/1048576).toFixed(1)+' MiB/s':'Geschwindigkeit wird ermittelt')+(Number.isFinite(j.eta)?' · ca. '+Math.ceil(j.eta/60)+' Min.':'')));}
if(j.error||j.note)body.append(el('small',j.error||j.note,'job-note'));
const details=el('details',undefined,'file-details');details.open=openJobDetails.has(j.id);details.ontoggle=()=>details.open?openJobDetails.add(j.id):openJobDetails.delete(j.id);details.append(el('summary',j.state==='done'&&j.size_bytes?'Datei & Qualität · '+(j.size_bytes/1048576).toFixed(0)+' MiB':'Datei & Speicherort'));
if(j.state==='done'&&j.measured){for(const track of j.measured)details.append(el('p',(track.type==='video'?'Video: '+(track.width||'?')+' × '+(track.height||'?'):track.type==='audio'?'Audio'+(track.channels?' · '+track.channels+' Kanäle':''):'Untertitel')+' · '+(track.codec||'unbekannter Codec')+(track.language?' · '+track.language:'')));}
const where=el('p',j.path||j.target||'','job-path');where.title=where.textContent;details.append(where);if(server.network&&j.state==='done')details.append(el('small','Liegt auf dem NAS. Über „Herunterladen“ im Browser laden oder per File Station bzw. Netzwerkfreigabe öffnen.'));
const url=j.source?._download_url||j.source?.url_video_hd||j.source?.url_video;if(url&&/^https?:\/\//.test(url)){const a=el('a','Originalquelle öffnen');a.href=url;a.target='_blank';a.rel='noopener noreferrer';details.append(a);}
body.append(details);
if(j.state==='done'&&j.file_state==='missing'){
 const missing=el('div',undefined,'job-file-missing');
 missing.append(el('p','Datei am gespeicherten Pfad nicht gefunden. Die Downloadhistorie bleibt erhalten; eventuell ist ein Laufwerk gerade nicht verbunden.'));
 const input=el('input');input.type='text';input.placeholder='Neuer vollständiger Dateipfad';input.autocomplete='off';input.setAttribute('aria-label','Neuer Dateipfad für '+(m.title||j.id));
 const actions=el('div',undefined,'job-file-actions');
 const search=el('button','In Bibliothek suchen');
 search.onclick=e=>busy(e.target,async()=>{
    const r=await api('library-locate',{id:j.id});
    if(r.ok){notice('Datei gefunden und wieder verknüpft.');document.activeElement?.blur();await refresh();return;}
    if(r.matches?.length===1){input.value=r.matches[0];notice('Eine mögliche Datei gefunden. Bitte den Pfad bestätigen.');}
    else if(r.matches?.length>1){input.value=r.matches[0];notice(r.matches.length+' mögliche Dateien gefunden. Ersten Pfad eingesetzt – vor dem Verknüpfen prüfen.');}
    else notice('In den freigegebenen Bibliotheksordnern keine passende Datei gefunden.'+(r.incomplete?' Die Suche wurde zeitlich begrenzt.':'')+' Prüfe die Ordner in den Einstellungen.');
 });
 const bind=el('button','Pfad verknüpfen');bind.onclick=e=>busy(e.target,async()=>{
    await api('library-relink',{id:j.id,path:input.value.trim()});
    notice('Neue Datei erfolgreich verknüpft. Metadaten und Downloadhistorie bleiben erhalten.');document.activeElement?.blur();await refresh();
 });
 actions.append(search,bind);missing.append(input,actions);body.append(missing);
}
if(j.state==='done'&&j.file_state!=='missing'){const save=el('a','Herunterladen','button-link primary');save.href=fileUrl(j,false);save.setAttribute('download','');save.title='Datei über den Browser auf dieses Gerät laden';body.append(save);
 if(!server.network){const b=el('button','Filmdatei öffnen');b.onclick=()=>busy(b,async()=>{await api('open-download',{id:j.id});});body.append(b);}
 const play=el('button','▶ Abspielen','play-button');play.title='Im Browser abspielen';play.onclick=()=>playJob(j);body.insertBefore(play,save);}
const action=['error','cancelled','interrupted','remote'].includes(j.state)?'retry':['queued','downloading','tagging'].includes(j.state)?'cancel':null;if(action){const b=el('button',action==='retry'?'Erneut versuchen':'Abbrechen');b.onclick=()=>busy(b,async()=>{await api(action,{id:j.id});await refresh();});body.append(b);}
card.append(art,body);return card;}

function ratingSource(m){return m.rating_source||(['OMDb','IMDb Offline'].includes(m.provider)?'IMDb':m.provider||'Quelle unbekannt');}
function pickLabel(m,state){const source=ratingSource(m),threshold=source==='IMDb'?10000:source==='TMDB'?1000:Infinity;return ['matched','manual','identified'].includes(state)&&Number(m.rating)>=7.5&&Number(m.rating)<=10&&Number(m.votes)>=threshold?(m.kind==='movie'?'Großes Kino':m.kind==='series'?'Serienfavorit':''):'';}
function pickReason(m){return 'Automatische Auswahl: mindestens 7,5 / 10 bei IMDb (10.000 Stimmen) oder TMDB (1.000 Stimmen). Hier: '+m.rating+' / 10 · '+ratingSource(m)+' · '+countLabel(Number(m.votes))+' Stimmen. Kein Nachweis für Kino-Umsatz oder Exklusivrechte.';}
function renderRatings(m){const host=$('detail-rating'),chips=el('div',undefined,'rating-chips');for(const r of m.ratings||[]){if(!r.source||!r.value)continue;chips.append(el('span',r.source+' · '+r.value+' (via OMDb)','rating-chip'));}if(chips.childElementCount)host.append(chips);else host.append(el('p','Weitere Kritikerwertungen sind noch nicht verfügbar. Rotten Tomatoes und Metacritic werden ergänzt, wenn OMDb sie liefert und das Kontingent verfügbar ist.','muted'));}
function renderServer(server){meshServer=server||{};$('mesh-share').hidden=!meshServer.network;$('mesh-share-hint').hidden=!!meshServer.network;$('access-panel').hidden=$('logout').hidden=!server.network;$('quit-app').hidden=!!server.managed;if(server.network){$('edition').textContent='v'+server.version+' · NAS-Dienst';$('location-pill').textContent='● Auf dem NAS · Anmeldung aktiv';}}
$('logout').onclick=e=>busy(e.target,async()=>{await api('logout',{});location.reload();});
$('access-panel').onsubmit=e=>{e.preventDefault();busy(e.submitter,async()=>{try{await api('password',{current:$('access-current').value,new:$('access-new').value});$('access-result').textContent='Passwort geändert.';$('access-current').value=$('access-new').value='';}catch(err){$('access-result').textContent=err.message;}});};
