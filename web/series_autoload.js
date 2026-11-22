// 0.6.94: Angefangene Serien automatisch offline laden (series_autoload.py).
// Björn (22.11.2026): ist eine Folge zu Ende gesehen, lädt MediathekAtlas die übrigen Folgen der Serie.
// Downloads → Kasten „Angefangene Serien“ (Schalter, Grenzen, Liste mit Beenden/Wieder an);
// Einstellungen → gleicher Schalter. Die einzelnen Aufträge stehen in der Liste darunter unter
// „Angefangene Serie · <Titel>“ mit Fortschritt und „Abbrechen“.
(function(){
const panel=$('series-autoload-panel'),card=$('series-autoload-settings');
if(!panel&&!card)return;
let last=null,timer=0;
const gb=n=>(Number(n||0)/1073741824).toLocaleString('de-DE',{maximumFractionDigits:1})+' GB';
function controls(d,host){
 const s=d.settings,box=el('div',undefined,'sal-controls');
 const on=el('label',undefined,'check');const cb=el('input');cb.type='checkbox';cb.checked=s.enabled;cb.className='sal-enabled';
 on.append(cb,' Nach einer zu Ende gesehenen Folge die übrigen Folgen der Serie automatisch offline laden');
 const fl=el('label',undefined,'check');const fb=el('input');fb.type='checkbox';fb.checked=s.films;fb.className='sal-films';
 fl.append(fb,' Zu Ende gesehene Filme dauerhaft offline behalten (zum Nochmal-Ansehen)');
 const pick=(label,cls,value,choices,unit)=>{const l=el('label',label,'sal-pick');const sel=el('select');sel.className=cls;
  for(const c of choices)sel.append(new Option(c+' '+unit,String(c)));sel.value=String(value);l.append(sel);return [l,sel];};
 const [lm,max]=pick('Höchstens ungesehen je Serie ','sal-max',s.max,s.max_choices,'Folgen');
 const [lg,size]=pick('Platz je Serie ','sal-gb',s.gb,s.gb_choices,'GB');
 const save=()=>busy(cb,async()=>{render(await api('series-autoload',{action:'settings',enabled:cb.checked,films:fb.checked,max:Number(max.value),gb:Number(size.value)}));notice('Einstellung für angefangene Serien gespeichert.');});
 cb.onchange=fb.onchange=max.onchange=size.onchange=save;
 max.disabled=size.disabled=fb.disabled=!s.enabled;
 box.append(on,fl,el('div',undefined,'sal-row'));box.lastChild.append(lm,lg);
 box.append(el('p','Nur ARD, ZDF & Co. mit direkter Videodatei und bestätigter Staffel/Folge, wie bei „Ganze Serie laden“. Kurze Serien werden komplett geladen, lange und tägliche Sendungen nur bis zur Grenze; jede gesehene Folge macht Platz für die nächste. Ist am Downloadordner weniger als die Reserve frei (YouTube → Abos, Standard 5 GB, dazu Platz für das IMDb-Update), wird nichts nachgeladen. Filme kommen in den normalen Downloadordner (ohne 30-Tage-Frist, außerhalb der Abo-Budgets), ihre Sendereihe wird nicht mitgeladen. Anbieter mit Kopierschutz oder nur Link (Joyn, RTL+, filmfriend …) werden nie geladen.','muted'));
 host.append(box);}
function row(r){
 const li=el('li',undefined,'sal-item sal-'+r.state);
 const head=el('div',undefined,'sal-head');head.append(el('strong',(r.kind==='movie'?'Film · ':'')+r.title));
 if(r.kind==='movie'){head.append(el('span',' · '+(r.ready?'offline gespeichert':r.waiting?'wird geladen':r.state==='done'?'erledigt':'vorgemerkt'),'muted'));li.append(head);
  if(r.note)li.append(el('small',r.note,'sal-note'));const actions=el('div',undefined,'sal-actions');const b=el('button','Aus der Liste nehmen');b.type='button';b.title='Eintrag entfernen; ein noch wartender Download wird abgebrochen, eine fertige Datei bleibt';
  b.onclick=()=>busy(b,async()=>{render(await api('series-autoload',{action:'forget',show:r.show}));if(typeof refresh==='function')refresh();});actions.append(b);li.append(actions);return li;}
 const facts=[r.last?'zuletzt gesehen '+r.last:'',r.ready?r.ready+' bereit':'',r.waiting?r.waiting+' in Warteschlange':'',r.unseen?'ungesehen '+gb(r.bytes):'',r.more?r.more+' weitere verfügbar':'',r.unconfirmed?r.unconfirmed+' ohne bestätigte Folgennummer':'',r.failed?r.failed+' abgebrochen/fehlgeschlagen':''].filter(Boolean);
 head.append(el('span',' · '+(r.state==='stopped'?'beendet':'aktiv')+(facts.length?' · '+facts.join(' · '):''),'muted'));
 li.append(head);if(r.note)li.append(el('small',r.note,'sal-note'));
 const actions=el('div',undefined,'sal-actions');
 const act=(label,action,title)=>{const b=el('button',label);b.type='button';b.title=title;b.onclick=()=>busy(b,async()=>{render(await api('series-autoload',{action,show:r.show}));if(typeof refresh==='function')refresh();});actions.append(b);};
 if(r.state==='stopped')act('Wieder automatisch laden','resume','Die Serie wieder automatisch nachladen');
 else act('Automatik beenden','stop','Für diese Serie nichts mehr automatisch laden; wartende Aufträge werden abgebrochen, fertige Dateien bleiben');
 act('Aus der Liste nehmen','forget','Eintrag entfernen und wartende Aufträge abbrechen. Wird später eine Folge zu Ende gesehen, startet die Automatik erneut.');
 li.append(actions);return li;}
function render(d){
 last=d;
 if(card){const body=$('series-autoload-settings-body');body.replaceChildren();controls(d,body);}
 if(!panel)return;
 const active=d.series.filter(r=>r.state==='active'&&r.kind!=='movie'),films=d.series.filter(r=>r.kind==='movie');
 $('series-autoload-summary').textContent=d.settings.enabled?[active.length?active.length+(active.length===1?' Serie wird':' Serien werden')+' nachgeladen':'an · noch keine Serie angefangen',films.length?films.length+(films.length===1?' Film':' Filme')+' behalten':''].filter(Boolean).join(' · '):'aus';
 const body=$('series-autoload-body');body.replaceChildren();controls(d,body);
 if(d.series.length){const ul=el('ul',undefined,'sal-list');for(const r of d.series)ul.append(row(r));body.append(ul);}
 else body.append(el('p',d.settings.enabled?'Noch keine Serie angefangen. Sobald eine Folge bis zum Ende läuft (Player oder Kinderecke), erscheint die Serie hier.':'Ausgeschaltet.','muted'));}
async function load(){try{render(await api('series-autoload'));}catch(e){const b=$('series-autoload-body');if(b)b.textContent=e.message;}}
function tick(){clearTimeout(timer);if(panel&&!panel.closest('section')?.hidden&&panel.open)load().finally(()=>{timer=setTimeout(tick,15000);});else timer=setTimeout(tick,15000);}
panel?.addEventListener('toggle',()=>{if(panel.open)load();});
card?.addEventListener('toggle',()=>{if(card.open)load();});
load();tick();
window.AtlasSeriesAutoload={reload:load,last:()=>last};
})();
