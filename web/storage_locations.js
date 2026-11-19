// 0.6.20: Einstellungen → Speicherorte. Downloads, Zwischenspeicher (YouTube-Abos) sowie System und Datenbank
// einzeln festlegen; vorhandene Daten werden kopiert, geprüft und erst dann umgestellt. Löschen nur auf Wunsch.
(function(){
const box=$('storage-locations-panel');if(!box)return;
const list=$('storage-locations-list'),moveBox=$('storage-locations-move'),problemsBox=$('storage-locations-problems'),volumesBox=$('storage-locations-volumes');
let timer=null,lastInput=null,inputs={},checks={},data=null,restarting=false;
const PHASE={preparing:'Wird vorbereitet',waiting:'Wartet auf laufenden Download',copying:'Kopiert',verifying:'Prüft die Kopie',switching:'Stellt um',ready:'Kopie fertig',done:'Fertig',failed:'Fehlgeschlagen',cancelled:'Abgebrochen'};
function gb(n){n=Number(n||0);return n>=1e9?(n/1e9).toLocaleString('de-DE',{maximumFractionDigits:1})+' GB':(n/1e6).toLocaleString('de-DE',{maximumFractionDigits:0})+' MB';}
function joinPath(base,leaf){const sep=base.includes('\\')&&!base.includes('/')?'\\':'/';return base.replace(/[\\/]+$/,'')+sep+leaf;}
function line(text,cls){return el('p',text,cls||'muted');}
function running(m){return ['preparing','waiting','copying','verifying','switching'].includes(m?.phase);}
async function load(){
 data=await api('storage-locations');render();
 clearTimeout(timer);if(box.open&&!restarting)timer=setTimeout(()=>load().catch(()=>{}),running(data.move)?1500:15000);
}
function renderMove(){
 const m=data.move||{},p=data.pending;moveBox.replaceChildren();
 if(p&&p.state==='copied'){
  moveBox.hidden=false;moveBox.append(el('strong','System und Datenbank: Kopie fertig und geprüft'),line('Neuer Ort: '+p.target+'.'+(data.move?.changed_since_copy?' '+data.move.changed_since_copy+' Dateien (z. B. Protokolle) hat die App seit der Kopie geändert; sie werden beim Neustart nachgezogen und dann geprüft.':'')+' Der Umzug wird beim nächsten Start abgeschlossen: Änderungen seit der Kopie werden nachgezogen, danach arbeitet MediathekAtlas am neuen Ort. Der alte Ort bleibt erhalten.'));
  const row=el('div',undefined,'loc-actions');
  if(data.restart_supported&&!data.managed){const b=el('button','Jetzt neu starten','primary');b.type='button';b.onclick=()=>restart(b);row.append(b);}
  else row.append(line(data.managed?'Neustart über das Paket-Zentrum bzw. App Center (Paket stoppen und starten).':'Bitte MediathekAtlas beenden und neu starten.'));
  const d=el('button','Umzug verwerfen');d.type='button';d.onclick=()=>busy(d,async()=>{await api('storage-locations',{action:'discard'});notice('Umzug verworfen. Die Kopie am Ziel bleibt liegen und kann gelöscht werden.');await load();});row.append(d);
  moveBox.append(row);return;
 }
 if(p&&p.state==='failed'){
  moveBox.hidden=false;moveBox.append(el('strong','Umzug von System und Datenbank nicht abgeschlossen','loc-bad'),line(p.error||''),line('MediathekAtlas arbeitet weiter am bisherigen Ort: '+p.source));
  const d=el('button','Hinweis ausblenden');d.type='button';d.onclick=()=>busy(d,async()=>{await api('storage-locations',{action:'dismiss',kind:'system'});await load();});moveBox.append(d);return;
 }
 if(!m.phase||m.phase==='idle'||(m.phase==='done'&&Date.now()/1000-(m.finished||0)>600)){moveBox.hidden=true;return;}
 moveBox.hidden=false;
 const title=(m.label||'Umzug')+': '+(PHASE[m.phase]||m.phase);
 moveBox.append(el('strong',title,m.phase==='failed'?'loc-bad':m.phase==='done'?'loc-good':''));
 if(m.source||m.target)moveBox.append(line((m.source||'–')+' → '+(m.target||'–')));
 if(running(m)){
  const bar=el('progress');bar.max=Math.max(1,m.bytes_total||0);bar.value=Math.min(bar.max,m.bytes_done||0);moveBox.append(bar);
  moveBox.append(line(gb(m.bytes_done)+' von '+gb(m.bytes_total)+' · '+(m.files_done||0)+' von '+(m.files_total||0)+' Dateien'+(m.kind!=='system'?' · Downloads warten so lange':'')));
  if(m.current)moveBox.append(el('div',m.current,'loc-current'));
  // 0.6.22: Fortschritt der aktuellen Datei (große Datenbanken: kopieren, prüfen, auf das Laufwerk schreiben)
  if(m.current&&m.file_total>0&&m.phase==='copying'){const step={copy:'wird kopiert',check:'wird geprüft',sync:'wird auf das Laufwerk geschrieben'}[m.step]||'wird kopiert';const mins=m.file_started?Math.floor((Date.now()/1000-m.file_started)/60):0;moveBox.append(line(m.current.split(/[\\/]/).pop()+' '+step+(m.step==='copy'?': '+gb(m.file_done)+' von '+gb(m.file_total):'')+(mins>=1?' · seit '+mins+' min':'')));}
  const c=el('button','Umzug abbrechen');c.type='button';c.onclick=()=>busy(c,async()=>{await api('storage-locations',{action:'cancel'});await load();});moveBox.append(c);
 }
 if(m.error)moveBox.append(line(m.error,m.phase==='failed'?'loc-bad':'muted'));
 if(m.phase==='done')moveBox.append(line('Umgestellt. Der alte Ort ist unverändert; löschen kannst du ihn unten beim jeweiligen Speicherort.'));
}
function renderCheck(kind,host){
 const r=checks[kind];host.replaceChildren();if(!r)return;
 if(r.error){host.append(line(r.error,'loc-bad'));return;}
 const facts=[];
 if(r.mode==='copy'&&r.files)facts.push(r.files+' Dateien · '+gb(r.bytes_total)+(r.bytes_present?' · davon '+gb(r.bytes_present)+' schon am Ziel':'')+(r.free?' · frei am Ziel: '+gb(r.free):''));
 if(facts.length)host.append(line(facts.join(''),'muted'));
 if(r.problems.length){const ul=el('ul');for(const p of r.problems)ul.append(el('li',p,'loc-bad'));host.append(ul);}
 if(r.warnings.length){const ul=el('ul');for(const w of r.warnings)ul.append(el('li',w,'loc-warn'));host.append(ul);}
 if(!r.ok)return;
 host.append(line('Ziel geprüft: '+r.target,'loc-good'));
 const row=el('div',undefined,'loc-actions');
 const go=(label,mode,primary)=>{const b=el('button',label,primary?'primary':'');b.type='button';b.onclick=()=>start(kind,mode,b);row.append(b);};
 if(r.mode==='copy')go('Umziehen: kopieren, prüfen, umstellen','copy',true);
 if(kind!=='system'&&(r.mode==='copy'||r.mode==='switch'))go(r.mode==='switch'?'Umstellen':'Nur umstellen (vorhandene Dateien bleiben am alten Ort)','switch',r.mode==='switch');
 if(kind==='system'&&r.existing_data)go('Vorhandene MediathekAtlas-Daten am Ziel verwenden','adopt',false);
 if(kind==='imdb'&&r.existing_data)go('Vorhandenes Archiv am Ziel verwenden'+(r.existing_stand?' (Stand '+r.existing_stand+')':''),'adopt',true);
 host.append(row);
}
function render(){
 problemsBox.replaceChildren();
 for(const row of data.locations)if(row.problem)problemsBox.append(el('p',row.problem,'notice-error'));
 renderMove();
 list.replaceChildren();inputs={};
 const busyMove=running(data.move);
 for(const row of data.locations){
  const card=el('div',undefined,'loc-location');
  card.append(el('h4',row.label));
  const hint={downloads:'Fertige Filme und Folgen, auch zeitlich begrenzte Offline-Kopien von Netzkino, Pluto & Co.',cache:'Videos der YouTube-Abos. Ohne eigenen Ort liegen sie im Downloadordner (Unterordner „YouTube-Abos“).',system:'Katalogdatenbank, Sicherungen, Protokolle und Einstellungen'+(data.locations.find(x=>x.kind==='imdb')?.is_default?', dazu das IMDb-Archiv.':'.'),imdb:'Lokales IMDb-Archiv (rund 20 GB). Die Erkennung fragt es bei fast jedem Abgleich ab: auf einem langsamen Laufwerk wird sie langsamer, auf einer SSD kaum.'}[row.kind];
  card.append(line(hint));
  card.append(el('div',row.path||'–','loc-path'));
  const facts=[];
  if(row.total)facts.push('frei: '+gb(row.free)+' von '+gb(row.total));
  if(row.kind==='cache'&&row.shared_with_downloads)facts.push('liegt im Downloadordner');
  if(row.kind==='system')facts.push(row.is_default?'Standardort':'Standardort wäre: '+row.default);
  if(row.kind==='imdb'){facts.push(row.is_default?'im Datenordner':'eigener Ort');if(row.timing?.queries)facts.push('Abfrage im Mittel '+row.timing.average_ms+' ms, langsamste '+row.timing.slowest_ms+' ms ('+row.timing.queries+' Abfragen)');}
  if(facts.length)card.append(el('div',facts.join(' · '),'loc-facts'));
  if(row.problem)card.append(line(row.problem,'loc-bad'));
  const form=el('div',undefined,'loc-form'),input=el('input');
  input.placeholder=row.kind==='cache'?'Neuer Ordner, z. B. /Volumes/Laufwerk/MediathekAtlas/Zwischenspeicher':'Neuer Ordner, z. B. /Volumes/Laufwerk/MediathekAtlas/'+row.suggest;
  input.autocomplete='off';input.spellcheck=false;input.value=checks[row.kind]?.typed||'';
  input.onfocus=()=>{lastInput={kind:row.kind,input};};
  const check=el('button','Ziel prüfen');check.type='button';check.disabled=busyMove;
  const result=el('div',undefined,'loc-check');
  check.onclick=()=>busy(check,async()=>{const typed=input.value.trim();try{const r=await api('storage-locations',{action:'inspect',kind:row.kind,target:typed});checks[row.kind]={...r,typed};}catch(e){checks[row.kind]={error:e.message,typed};}renderCheck(row.kind,result);});
  input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();check.click();}};
  form.append(input,check);card.append(form,result);
  inputs[row.kind]=input;renderCheck(row.kind,result);
  if(row.kind==='cache'&&!row.shared_with_downloads){
   const back=el('button','Zurück in den Downloadordner');back.type='button';back.disabled=busyMove;
   back.onclick=()=>{const dl=data.locations.find(x=>x.kind==='downloads');input.value=dl?.path||'';check.click();};
   const r=el('div',undefined,'loc-actions');r.append(back);card.append(r);
  }
  if(row.kind==='system'&&data.revert){
   // 0.6.25: sicherer Rückweg – nur umstellen, nichts kopieren oder löschen (Björn, 19.11.2026).
   const rv=data.revert,box2=el('div',undefined,'loc-check');
   box2.append(line('Bisheriger Ort mit vollständigem Datenstand: '+rv.path+(rv.stand?' (Stand '+rv.stand+')':'')+'. Zurückstellen kopiert und löscht nichts; '+rv.current+' bleibt unverändert liegen. Änderungen seit dem Umzug sind dann nicht enthalten.'));
   const rr=el('div',undefined,'loc-actions'),b=el('button','Bisherigen Ort wieder verwenden');b.type='button';b.disabled=busyMove;
   b.onclick=()=>{if(!confirm('MediathekAtlas arbeitet nach dem Neustart wieder mit '+rv.path+(rv.stand?' (Stand '+rv.stand+')':'')+'. Die Daten in '+rv.current+' bleiben unverändert liegen. Fortfahren?'))return;busy(b,async()=>{await api('storage-locations',{action:'revert'});await load();if(data.restart_supported&&!data.managed)await restart(b,true);else notice('Umgestellt. Bitte MediathekAtlas neu starten.');});};
   rr.append(b);box2.append(rr);card.append(box2);
  }
  if(row.kind==='system'&&data.abandoned?.path){
   const ab=el('div',undefined,'loc-check');ab.append(line('Nicht mehr benutzte Kopie: '+data.abandoned.path+'. Sie wird nicht automatisch gelöscht; nach einer Prüfung des Laufwerks lässt sie sich im Finder entfernen.'));
   const ar=el('div',undefined,'loc-actions'),h=el('button','Hinweis ausblenden');h.type='button';h.onclick=()=>busy(h,async()=>{await api('storage-locations',{action:'dismiss',kind:'system'});await load();});ar.append(h);ab.append(ar);card.append(ab);
  }
  if(row.kind==='imdb'&&!row.is_default){
   const back=el('button','Zurück in den Datenordner');back.type='button';back.disabled=busyMove;
   back.onclick=()=>{input.value=row.default;check.click();};
   const r=el('div',undefined,'loc-actions');r.append(back);card.append(r);
  }
  if(row.kind==='system'&&!row.is_default){
   const back=el('button','Zurück an den Standardort');back.type='button';back.disabled=busyMove;
   back.onclick=()=>{input.value=row.default;check.click();};
   const r=el('div',undefined,'loc-actions');r.append(back);card.append(r);
  }
  const prev=(data.previous||{})[row.kind];
  if(prev&&prev.source){
   const old=el('div',undefined,'loc-check');
   old.append(line('Alte Daten am bisherigen Ort: '+prev.source+(prev.left?' ('+prev.left+' Dateien ohne gleiche Kopie bleiben)':'')+'. Sie werden nicht automatisch gelöscht.'));
   const rowB=el('div',undefined,'loc-actions');
   const del=el('button','Alte Daten löschen');del.type='button';del.disabled=busyMove;
   del.onclick=()=>{const typed=prompt('Gelöscht werden nur Dateien, die am neuen Ort ('+prev.target+') gleich vorliegen. Zum Bestätigen bitte '+data.confirm+' eingeben.');if(typed!==data.confirm){notice('Nichts gelöscht: Bestätigung fehlt.');return;}busy(del,async()=>{const r=await api('storage-locations',{action:'cleanup',kind:row.kind,confirm:typed});notice(r.removed+' Dateien gelöscht, '+gb(r.freed)+' frei'+(r.kept?' · '+r.kept+' Dateien behalten (keine gleiche Kopie am neuen Ort)':'')+'.');await load();});};
   const hide=el('button','Hinweis ausblenden');hide.type='button';hide.onclick=()=>busy(hide,async()=>{await api('storage-locations',{action:'dismiss',kind:row.kind});await load();});
   rowB.append(del,hide);old.append(rowB);card.append(old);
  }
  list.append(card);
 }
 volumesBox.replaceChildren();
 if(!data.volumes?.length)volumesBox.append(line('Keine weiteren Laufwerke gefunden. Ein Pfad lässt sich auch direkt eintragen.'));
 else volumesBox.append(line('Klick übernimmt das Laufwerk in das zuletzt gewählte Feld (sonst System und Datenbank).'));
 for(const v of data.volumes||[]){
  const b=el('button',v.name+' · '+gb(v.free)+' frei'+(v.network?' · Netzwerk':''));b.type='button';b.title=v.path;
  b.onclick=()=>{const target=lastInput||{kind:'system',input:inputs.system};if(!target.input)return;const leaf={downloads:'Downloads',cache:'Zwischenspeicher',system:'System',imdb:'IMDb'}[target.kind];target.input.value=joinPath(joinPath(v.path,'MediathekAtlas'),leaf);target.input.focus();};
  volumesBox.append(b);
 }
}
async function start(kind,mode,button){
 const r=checks[kind];if(!r)return;
 const text={copy:'Alle Daten werden nach '+r.target+' kopiert und geprüft, erst dann wird umgestellt'+(kind==='system'?' (Abschluss beim nächsten Start)':'')+'. Der alte Ort bleibt erhalten. Starten?',switch:'Nur umstellen: neue Dateien landen in '+r.target+', vorhandene bleiben am alten Ort. Fortfahren?',adopt:kind==='imdb'?'Die Erkennung nutzt ab sofort das vorhandene IMDb-Archiv in '+r.target+(r.existing_stand?' (Stand '+r.existing_stand+')':'')+'. Das bisherige Archiv bleibt unverändert liegen. Fortfahren?':'Beim nächsten Start werden die vorhandenen Daten in '+r.target+' verwendet. Der aktuelle Stand wird dabei nicht übernommen. Fortfahren?'}[mode];
 if(!confirm(text))return;
 await busy(button,async()=>{await api('storage-locations',{action:'start',kind,target:r.target,mode});delete checks[kind];notice(mode==='copy'?'Umzug gestartet. Die App bleibt nutzbar.':'Umgestellt.');await load();});
}
async function restart(button,quiet){
 if(!quiet&&!confirm('MediathekAtlas startet neu und schließt den Umzug ab. Das kann je nach Datenmenge einige Minuten dauern. Jetzt neu starten?'))return;
 await busy(button,async()=>{await api('storage-locations',{action:'restart'});});
 restarting=true;clearTimeout(timer);moveBox.hidden=false;moveBox.replaceChildren(el('strong','Neustart läuft …'),line('Der Umzug wird abgeschlossen. Diese Seite lädt sich neu, sobald MediathekAtlas wieder bereit ist.'));
 const started=Date.now();
 const poll=async()=>{try{const r=await fetch('/',{cache:'no-store'});if(r.ok){location.reload();return;}}catch{}const secs=Math.round((Date.now()-started)/1000);moveBox.lastChild.textContent='Der Umzug wird abgeschlossen ('+secs+' s). Diese Seite lädt sich neu, sobald MediathekAtlas wieder bereit ist.'+(secs>600?' Dauert ungewöhnlich lange: Startprotokoll prüfen.':'');setTimeout(poll,2000);};
 setTimeout(poll,2500);
}
box.addEventListener('toggle',()=>{if(box.open)load().catch(e=>problemsBox.replaceChildren(el('p',e.message,'notice-error')));else clearTimeout(timer);});
const link=$('storage-locations-link');if(link)link.onclick=e=>{e.preventDefault();box.open=true;box.scrollIntoView({behavior:'smooth',block:'start'});};
})();
