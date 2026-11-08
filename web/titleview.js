// playMedia(item[,list]) comes from web/player.js; list = following episodes for "Nächste Folge".
// Title pages for series and films, laid out like a media server: backdrop, poster, overview,
// facts, cast, then seasons with episodes (series) or versions (films). Uses helpers of app.js.
'use strict';
let titleState=null,titleScroll=0,titleSequence=0;
const SEASON_ALL='all';
function canPlay(){return typeof playMedia==='function';}
function epCode(m){return Number.isInteger(m.season)&&Number.isInteger(m.episode)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0'):Number.isInteger(m.episode)?'Folge '+m.episode:'';}
function minutes(sec){return sec?Math.round(sec/60)+' Min.':'';}
function seasonLabel(s){return s===null||s===undefined?'Ohne Staffelangabe':s===0?'Specials':'Staffel '+s;}
function stateLabel(state){return ({identified:'◐ Werk erkannt · Folge offen',matched:'✓ Zugeordnet',manual:'✓ Manuell geprüft',review:'◌ Zuordnung prüfen',pending:'◌ Vorgemerkt',retry:'◌ Wird wiederholt',format:'◇ Sendungsbeitrag'})[state]||'◌ Offen';}
function playButton(item,label,primary,list){const b=el('button','▶ '+(label||'Abspielen'),(primary?'primary ':'')+'play-button');b.title='Im Browser abspielen';b.onclick=e=>{e.stopPropagation();list?playMedia(item,list):playMedia(item);};return b;}
function artImage(url,alt,cls){if(!safeArt(url))return null;const img=el('img',undefined,cls);img.src=url;img.alt=alt||'';img.loading='lazy';img.decoding='async';img.onerror=()=>img.remove();return img;}

function showTitleView(){titleScroll=window.scrollY;$('discover').hidden=true;$('title-view').hidden=false;document.body.classList.add('title-open');window.scrollTo(0,0);}
function closeTitleView(fromHistory){if($('title-view').hidden)return;$('title-view').hidden=true;$('title-view').replaceChildren();titleState=null;document.body.classList.remove('title-open');$('discover').hidden=false;window.scrollTo(0,titleScroll);if(!fromHistory&&history.state&&history.state.atlasTitle)history.back();}
window.addEventListener('popstate',()=>{if(!$('title-view').hidden)closeTitleView(true);});
function pushTitle(){if(!(history.state&&history.state.atlasTitle))history.pushState({atlasTitle:1},'');}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('title-view').hidden&&!document.querySelector('dialog[open]'))closeTitleView();});

// Entry point from catalogue cards: series (or one of its episodes) open the series page, everything else the film page.
function openTitle(item){if(item.series_parent||(item.metadata?.kind==='series'&&item.show_key))return openShow(item.show_key,item.series_parent?null:item.work_id);return openMovie(item);}

function hero({meta,type,facts,overview,overviewHint,poster,actions,info,cast}){
 const wrap=el('div',undefined,'tv-hero'),back=el('div',undefined,'tv-backdrop'),bg=artImage(meta.fanart||meta.poster,'');
 if(bg){if(!meta.fanart)back.classList.add('blurred');back.append(bg);}wrap.append(back);
 const top=el('div',undefined,'tv-topbar'),close=el('button','← Zurück zum Katalog','tv-back');close.onclick=()=>closeTitleView();top.append(close);wrap.append(top);
 const body=el('div',undefined,'tv-herobody'),cover=el('div',undefined,'tv-poster'),img=artImage(poster||meta.poster,'Poster: '+(meta.title||''));
 if(img)cover.append(img);else cover.append(el('span',type==='Serie'?'SERIE':'FILM'));
 const text=el('div',undefined,'tv-herotext');text.append(el('p',type,'eyebrow'),el('h1',meta.title||'Ohne Titel'));
 const line=el('div',undefined,'tv-facts');for(const f of facts.filter(Boolean)){line.append(typeof f==='string'?el('span',f):f);}text.append(line);
 const buttons=el('div',undefined,'tv-actions');buttons.append(...actions.filter(Boolean));text.append(buttons);
 const plot=el('p',overview||overviewHint,'tv-overview'+(overview?'':' muted'));text.append(plot);
 if(overview&&overview.length>420){plot.classList.add('clamped');const more=el('button','Mehr anzeigen','tv-more');more.onclick=()=>{const open=plot.classList.toggle('clamped');more.textContent=open?'Mehr anzeigen':'Weniger anzeigen';};text.append(more);}
 const dl=el('dl',undefined,'tv-info');for(const [k,v] of info){if(v)dl.append(el('dt',k),el('dd',v));}if(dl.childElementCount)text.append(dl);
 body.append(cover,text);wrap.append(body);
 const out=[wrap];
 if(cast?.length){const sec=el('section',undefined,'tv-section');sec.append(el('h2','Besetzung'));const row=el('div',undefined,'tv-cast');for(const p of cast.slice(0,24)){const c=el('div',undefined,'tv-person');c.append(el('span',(p.name||'?').split(/\s+/).map(x=>x[0]).slice(0,2).join(''),'tv-avatar'),el('strong',p.name),p.role?el('small',p.role):'');row.append(c);}sec.append(row);out.push(sec);}
 return out;
}
function ratingFact(m){const r=Number(m.rating);if(m.rating==null||m.rating===''||!Number.isFinite(r))return null;const s=el('span','★ '+r.toLocaleString('de-DE',{maximumFractionDigits:1}),'tv-rating');s.title=ratingSource(m)+(m.votes!=null?' · '+countLabel(Number(m.votes))+' Stimmen':'');return s;}
function extraRatings(m){return (m.ratings||[]).filter(r=>r.source&&r.value).map(r=>{const s=el('span',r.source.replace('Internet Movie Database','IMDb')+' '+r.value,'tv-chip');s.title='via OMDb';return s;});}
function creditInfo(credits){return [['Regie',(credits.directors||[]).join(', ')],['Drehbuch',(credits.writers||[]).join(', ')]];}

async function openShow(show,focusWork){
 if(!show)return;const seq=++titleSequence;showTitleView();pushTitle();const host=$('title-view');host.replaceChildren(el('p','Serie wird geladen …','muted tv-loading'));
 // Opening a series page never queues hundreds of automatic rechecks.
 let d;try{d=await api('show?'+new URLSearchParams({show,archive:filters.archive?'1':'0'}));}catch(e){if(seq===titleSequence){host.replaceChildren(el('p','Serie konnte nicht geladen werden: '+e.message,'empty'));const b=el('button','← Zurück zum Katalog');b.onclick=()=>closeTitleView();host.append(b);}return;}
 if(seq!==titleSequence)return;
 const s=d.show;if((!s.show_description||!s.fanart)&&d.work_ids.length)api('artwork-priority',{ids:d.work_ids.slice(0,3)}).catch(()=>{});
 const focus=focusWork&&d.episodes.find(e=>e.work_id===focusWork);
 const seasons=s.seasons.map(x=>x.season);let current=focus?focus.metadata.season??null:seasons.find(x=>x!==0&&x!==null)??seasons[0];if(seasons.length>1&&d.episodes.length<=24&&!focus)current=SEASON_ALL;
 titleState={kind:'series',show,data:d,season:current,focus:focusWork};renderShow();
}
function nextEpisode(eps){return eps.find(e=>e.available&&!e.downloaded)||eps.find(e=>e.available)||eps[0];}
function renderShow(){
 const {data:d}=titleState,s=d.show,host=$('title-view'),credits=s.show_credits||{};
 const eps=d.episodes,next=nextEpisode(eps),actions=[];
 if(next&&canPlay())actions.push(playButton(next,(epCode(next.metadata)?epCode(next.metadata)+' ':'')+'abspielen',true,eps.filter(e=>e.available)));
 const dl=el('button','↓ Folgen auswählen & herunterladen',canPlay()?'':'primary');dl.onclick=()=>openSeries(s.show_key);actions.push(dl);
 const sync=el('button','↻ Metadaten abgleichen');sync.title='Diese Serie bevorzugt mit TMDB, TVDB, IMDb und den Mediatheken abgleichen';sync.onclick=e=>busy(e.target,async()=>{await api('metadata-priority',{show:s.show_key});if(d.work_ids.length)await api('artwork-priority',{ids:d.work_ids.slice(0,3)});notice('Abgleich vorgemerkt. Die Seite zeigt neue Daten beim nächsten Öffnen.');});actions.push(sync);
 const years=s.year?String(s.year):'';const nSeasons=s.seasons.filter(x=>x.season!==null).length;
 const facts=[years,ratingFact(s),...extraRatings(s),nSeasons?nSeasons+(nSeasons===1?' Staffel':' Staffeln'):'',s.episode_count+(s.episode_count===1?' Folge':' Folgen')+' verfügbar',s.downloaded?s.downloaded+' heruntergeladen':'',(s.genres||[]).slice(0,3).join(' · ')];
 const hint=s.state==='format'?'Sendung mit einzelnen Beiträgen. Sendungsbeiträge werden nicht mit Filmdatenbanken abgeglichen.':!latestSettings.tmdb_set&&!latestSettings.tvdb_set?'Noch keine Serienbeschreibung. Mit einem TMDB- oder TVDB-Zugang in den Einstellungen werden Beschreibung und Hintergrundbild ergänzt.':'Serienbeschreibung wird beim nächsten Abgleich ergänzt.';
 const info=[['Genres',(s.genres||[]).join(', ')],['Sender',s.channels.join(', ')],['Netzwerk',(s.networks||[]).join(', ')],['Studios',(s.studios||[]).join(', ')],...creditInfo(credits),['Zuordnung',stateLabel(s.state)+(s.provider?' · '+s.provider+(s.reference_id?' '+s.reference_id:''):'')]];
 host.replaceChildren(...hero({meta:s,type:'Serie',facts,overview:s.show_description,overviewHint:hint,actions,info,cast:credits.cast}));
 const sec=el('section',undefined,'tv-section');const head=el('div',undefined,'tv-sectionhead');head.append(el('h2','Staffeln & Folgen'));
 const tabs=el('div',undefined,'tv-tabs');tabs.setAttribute('role','tablist');
 const options=s.seasons.length>1?[{season:SEASON_ALL,episodes:eps.length},...s.seasons]:s.seasons;
 for(const x of options){const t=el('button',(x.season===SEASON_ALL?'Alle':seasonLabel(x.season))+' · '+x.episodes,'tv-tab'+(x.season===titleState.season?' active':''));t.setAttribute('role','tab');t.setAttribute('aria-selected',String(x.season===titleState.season));t.onclick=()=>{titleState.season=x.season;titleState.focus=null;renderShow();};tabs.append(t);}
 head.append(tabs);sec.append(head);
 if(s.truncated)sec.append(el('p','Sehr viele Folgen: angezeigt werden die ersten 1.000.','muted'));
 const list=el('div',undefined,'tv-episodes');let shown=0;
 for(const e of eps){const season=e.metadata.season??null;if(titleState.season!==SEASON_ALL&&season!==titleState.season)continue;list.append(episodeRow(e,s));shown++;}
 if(!shown)list.append(el('p','Keine Folgen in dieser Auswahl.','empty'));sec.append(list);host.append(sec);
 if(titleState.focus){const row=host.querySelector('[data-work="'+CSS.escape(titleState.focus)+'"]');if(row){row.classList.add('focused');row.scrollIntoView({block:'center'});}}
}
function episodeRow(e,s){
 const m=e.metadata,r=e.source,row=el('article',undefined,'tv-episode');row.dataset.work=e.work_id;
 const thumb=el('div',undefined,'tv-thumb'),img=artImage(m.still||s.fanart||m.poster||s.poster,'');if(img)thumb.append(img);thumb.append(el('span',epCode(m)||'Folge','tv-code'));
 if(canPlay()&&e.available)thumb.append(playButton(e,'',false,titleState.data.episodes.filter(x=>x.available)));row.append(thumb);
 const body=el('div',undefined,'tv-epbody'),title=m.episode_title||r.title;
 body.append(el('h3',(Number.isInteger(m.episode)?m.episode+'. ':'')+title));
 const meta=[minutes(r.duration),r.channel,e.best?.quality?e.best.quality+(e.best.height_hint?' '+e.best.height_hint+'p':''):'',e.special||'',r.timestamp?new Date(r.timestamp*1000).toLocaleDateString('de-DE'):''].filter(Boolean).join(' · ');
 body.append(el('p',meta,'tv-epmeta'));
 const status=el('p',meshDownloadLabel(e.mesh_download)+(e.downloaded&&!e.mesh_download?'✓ Heruntergeladen · ':'')+stateLabel(e.state)+(e.available?'':' · nicht mehr gelistet'),'badge');body.append(status);
 const desc=m.description||r.description||'';if(desc&&desc!==s.show_description)body.append(el('p',desc,'tv-epdesc'));
 const actions=el('div',undefined,'tv-epactions'),load=el('button',e.available?'↓ Prüfen & laden':'Metadaten ansehen');load.onclick=()=>edit(e);actions.append(load);
 if((e.offer_count||1)>1)actions.append(versionsDetails(e));
 const files=el('details',undefined,'file-details');files.append(el('summary','Dateien & Qualität'),sourceLinks(e.links));actions.append(files);
 body.append(actions);row.append(body);return row;
}
// Further versions (other channels, Audiodeskription, Gebärdensprache) load on demand.
function versionsDetails(item,onPick){
 const box=el('details',undefined,'alternatives tv-versions');box.append(el('summary','Weitere Fassungen ('+(item.offer_count||1)+')'));
 box.ontoggle=async()=>{if(!box.open||box.dataset.loaded||box.dataset.loading)return;box.dataset.loading='1';try{const d=await api('alternatives?work_id='+encodeURIComponent(item.work_id));for(const a of d.items){box.append(versionRow(a,onPick));}box.dataset.loaded='1';}catch(e){box.append(el('p',e.message,'muted'));}finally{delete box.dataset.loading;}};
 return box;
}
function versionLabel(a){const best=(a.links||[])[0];return [(a.source.channel||'Quelle'),a.special||'Regulär',best?best.quality+(best.height_hint?' '+best.height_hint+'p':''):'',a.available?'':'nicht mehr gelistet'].filter(Boolean).join(' · ');}
function versionRow(a,onPick){
 const box=el('div',undefined,'alternative tv-version');box.append(el('strong',versionLabel(a)));
 if(a.source.duration)box.append(el('small',minutes(a.source.duration)));
 const actions=el('div',undefined,'tv-epactions');
 if(canPlay()&&a.available)actions.append(playButton(a,'Abspielen',false));
 const load=el('button','↓ Diese Fassung prüfen & laden');load.onclick=()=>edit(a);actions.append(load);
 if(onPick){const pick=el('button','Als Hauptfassung wählen');pick.onclick=()=>onPick(a);actions.append(pick);}else if(titleState?.kind==='movie'&&titleState.selected?.id===a.id){box.classList.add('selected');box.querySelector('strong').append(el('span',' · Gewählt','tv-selected'));}
 box.append(actions,sourceLinks(a.links));return box;
}

async function openMovie(item){
 const seq=++titleSequence;showTitleView();pushTitle();titleState={kind:'movie',item,selected:item,versions:null};renderMovie();
 if((item.offer_count||1)>1){try{const d=await api('alternatives?work_id='+encodeURIComponent(item.work_id));if(seq!==titleSequence||!titleState)return;titleState.versions=d.items;titleState.selected=d.items.find(a=>a.id===item.id)||d.items[0]||item;renderMovie();}catch(e){notice(e.message,'error');}}
 const m=item.metadata;if(!m.fanart||!m.poster)api('artwork-priority',{ids:[item.work_id]}).catch(()=>{});
}
function renderMovie(){
 const {item,selected,versions}=titleState,m=item.metadata,r=selected.source||item.source,host=$('title-view');
 const actions=[];if(canPlay()&&selected.available!==false)actions.push(playButton({...item,...selected,metadata:m},'Abspielen',true));
 const load=el('button',selected.available===false?'Metadaten ansehen':'↓ Prüfen & herunterladen',canPlay()?'':'primary');load.onclick=()=>edit({...item,...selected,metadata:m});actions.push(load);
 if(versions&&versions.length>1){const label=el('label',undefined,'tv-select');label.append('Fassung ');const sel=el('select');sel.setAttribute('aria-label','Fassung wählen');versions.forEach((a,i)=>{const o=el('option',versionLabel(a));o.value=String(i);if(a.id===selected.id)o.selected=true;sel.append(o);});sel.onchange=()=>{titleState.selected=versions[Number(sel.value)];renderMovie();};label.append(sel);actions.push(label);}
 const facts=[m.year?String(m.year):'',minutes(r.duration),ratingFact(m),...extraRatings(m),(m.genres||[]).slice(0,3).join(' · '),item.downloaded?'✓ Heruntergeladen':'',pickLabel(m,item.state)?pickLabel(m,item.state):''];
 const hint=item.state==='format'?'Beitrag einer Sendung.':(r.description?'':'Noch keine Beschreibung vorhanden.');
 const info=[['Genres',(m.genres||[]).join(', ')],...creditInfo(m),['Studios',(m.studios||[]).join(', ')],['Sender',r.channel],['Fassung',(selected.special||'Regulär')+(selected.available===false?' · nicht mehr gelistet':'')],['Zuordnung',stateLabel(item.state)+(m.provider?' · '+m.provider+(m.reference_id?' '+m.reference_id:''):'')]];
 host.replaceChildren(...hero({meta:m,type:'Film',facts,overview:m.description||r.description||'',overviewHint:hint,actions,info,cast:m.cast}));
 const sec=el('section',undefined,'tv-section');sec.append(el('h2','Fassungen & Dateien'));
 if(versions){const list=el('div',undefined,'tv-versionlist');for(const a of versions)list.append(versionRow(a,a.id===selected.id?null:x=>{titleState.selected=x;renderMovie();window.scrollTo(0,0);}));sec.append(list);}
 else sec.append(sourceLinks(selected.links||item.links),el('p',(item.offer_count||1)>1?'Weitere Fassungen werden geladen …':'Nur eine Fassung im Katalog.','muted'));
 sec.append(el('p','Quelllinks öffnen die Originaldatei. Für saubere Dateinamen, NFO und eingebettete Metadaten den Download über die App starten.','muted'));
 host.append(sec);
}
