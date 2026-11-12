/* 0.5.31.8: one catalogue presentation, isolated sources and rights. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, value, cls) => {
    const n=document.createElement(tag);
    if (value !== undefined) n.textContent=String(value);
    if (cls) n.className=cls;
    return n;
  };
  const VALID_SOURCES = ['all','mediatheken','netzkino','pluto','justwatch'];
  const PORTALS = {pluto:'Pluto TV',justwatch:'JustWatch TV'};
  const TYPES = ['movies','series'];
  let source='mediatheken',kind='series',genre='',sort='title',search='',offset=0,sequence=0;
  let seriesKey='',seriesTitle='';
  let medGenres=[],medTree=[],collection='';
  const heading=() => ({all:'Gesamtkatalog',mediatheken:'ARD, ZDF & Co.',netzkino:'Netzkino',...PORTALS}[source]);
  const hrefOkay=value=>typeof value==='string' && /^https:\/\/[a-z0-9.-]+\//i.test(value) && !/[\s<>'"]/.test(value);
  function arrangeAdvanced() {
    const discover=$('discover');
    const switcher=discover?.querySelector('.atlas-source-switch');
    const body=$('atlas-source-content');
    if (!discover || !switcher || !body || $('atlas-catalog-advanced')) return;
    const advanced=el('details',undefined,'atlas-catalog-advanced');
    advanced.id='atlas-catalog-advanced';
    const summary=el('summary','Klassische Katalogansicht (Genre-Baum, Zuordnung, Großes Kino), Scanner und Diagnose');
    advanced.append(summary);
    // Move existing nodes, never clone/remove listeners or rewrite historic functions.
    for (const child of [...discover.children]) {
      if (child!==switcher && child!==body) advanced.append(child);
    }
    discover.append(advanced);
    // Restore the actual historic mediatheken status board *above* the shared
    // catalogue. Move live nodes with IDs; do not clone elements or handlers.
    const historic=advanced.querySelector('.background-status');
    // A missing status board must not break the whole catalogue (0.5.31.11 threw here).
    if (!historic) { console.warn('MediathekAtlas: Scan- und Erkennungsübersicht fehlt'); return; }
    const dashboard=el('section',undefined,'background-status atlas-main-dashboard');
    dashboard.id='atlas-main-dashboard';
    dashboard.setAttribute('aria-label','Mediatheken-Scanner und Metadatenabgleich');
    dashboard.append(el('h2','ARD, ZDF & Co. · Scan & Erkennung','atlas-dashboard-heading'));
    const oldSummary=historic.querySelector('summary');
    if(oldSummary) oldSummary.remove();
    while(historic.firstChild) dashboard.append(historic.firstChild);
    historic.remove();
    discover.insertBefore(dashboard,body);
    // Keep the existing last-recognition and provider panels side by side,
    // but place worker/queue statistics in their own full-width responsive row.
    const workers=$('metadata-workers-status');
    const statusBottom=dashboard.querySelector('.atlas-status-bottom');
    if(workers && statusBottom){
      const overview=el('section',undefined,'atlas-worker-overview');
      overview.append(el('h3','Verarbeitung & Warteschlangen'));
      overview.append(workers);
      statusBottom.insertAdjacentElement('afterend',overview);
      const recognition=dashboard.querySelector('#metadata-status')?.closest('.atlas-status-panel');
      const title=recognition?.querySelector('h3');
      if(title)title.textContent='Letzte Erkennung';
    }
  }
  // Per-source overview in the catalogue header (0.5.41): Mediatheken keep the ARD/ZDF scan and
  // recognition board; Netzkino, Pluto TV and JustWatch TV get their own catalogue, scan and
  // work-assignment progress; "Gesamt" shows the ARD/ZDF board plus all portal catalogues.
  let portalTimer=0,portalSeq=0;
  const SYNC={netzkino:'netzkino-sync',pluto:'pluto-sync',justwatch:'justwatch-sync'};
  const num=n=>Number(n||0).toLocaleString('de-DE');
  const when=t=>t?new Date(t*1000).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}):'noch nie';
  function portalBoard() {
    let board=$('atlas-portal-dashboard');
    if (!board) {
      board=el('section',undefined,'background-status atlas-portal-dashboard');
      board.id='atlas-portal-dashboard';board.setAttribute('aria-label','Katalog-Übersicht je Plattform');board.hidden=true;
      const body=$('atlas-source-content');
      if (typeof body?.parentElement?.insertBefore==='function') body.parentElement.insertBefore(board,body);
    }
    return board;
  }
  function portalCard(p, inTab) {
    const card=el('article',undefined,'atlas-portal-card');
    const phase=p.running?'Abruf läuft':p.last_result==='complete'?'Aktuell':p.last_result==='partial'?'Teilweise geladen':
      p.last_result==='interrupted'?(p.titles?'Abruf unterbrochen · gespeicherter Bestand':'Abruf unterbrochen'):
      p.last_result==='failed'?(p.titles?'Abruf fehlgeschlagen · gespeicherter Bestand':'Abruf fehlgeschlagen'):
      p.titles?'Gespeicherter Bestand':'Noch nicht geladen';
    card.append(el('h3',p.name+' · '+phase));
    const tiles=el('div',undefined,'atlas-status-grid');
    const tile=(label,value,hint)=>{const t=el('div',undefined,'atlas-portal-tile');t.append(el('strong',value),el('small',label));if(hint)t.title=hint;tiles.append(t);};
    const ref=p.reference||{},by=ref.by_status||{},checked=Number(ref.checked||0),titles=Number(p.titles||0);
    tile('Filme & Serien im Katalog',num(titles));
    if (p.channels) tile('Live-Sender',num(p.channels));
    if (p.playable!==undefined) tile('im Player abspielbar',num(p.playable));
    tile('Stand des Katalogs',when(p.last_success));
    tile('eindeutig zugeordnet',num(by.candidate),'Eindeutige IMDb-/TVDB-/TMDB-Referenz');
    tile('zu prüfen',num(by.review),'Widersprüchliche Referenzen, keine automatische Zuordnung');
    tile('ohne Treffer',num(by.no_match));
    if (by.partial) tile('Anbieter nicht erreichbar',num(by.partial),'Wird später automatisch erneut geprüft');
    tile('noch offen',num(Math.max(0,titles-checked)),'Wird im Hintergrund abgeglichen (ein Titel alle 6 s)');
    card.append(tiles);
    const share=titles?Math.min(100,Math.round(checked*100/titles)):0;
    const bar=el('div',undefined,'atlas-portal-progress');const fill=el('span');fill.style.width=share+'%';bar.append(fill);
    bar.setAttribute('role','progressbar');bar.setAttribute('aria-valuenow',String(share));bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');
    card.append(el('small','Werkzuordnung (IMDb/TVDB/TMDB): '+num(checked)+' von '+num(titles)+' geprüft · '+share+' %'),bar);
    const off=p.offline||{};
    card.append(el('small','Offline ('+p.offline_days+' Tage): '+num(off.done)+' verfügbar · '+num((off.queued||0)+(off.downloading||0)+(off.tagging||0))+' in Arbeit'+(off.error?' · '+num(off.error)+' Fehler':''),'muted'));
    const actions=el('div',undefined,'atlas-portal-actions');
    const load=el('button',p.running?'Katalog wird geladen …':'↻ Katalog jetzt laden');load.type='button';load.disabled=!!p.running;
    load.onclick=async()=>{load.disabled=true;try{await window.api(SYNC[p.source],{});}catch(e){load.textContent=e.message;}setTimeout(inTab?()=>mountTabBoard(p.source):refreshPortalBoard,1500);};
    const open=el('button',inTab?'Im Katalog anzeigen':'Plattform öffnen');open.type='button';
    open.onclick=inTab?()=>{document.querySelector('[data-view="discover"]')?.click();document.querySelector('[data-catalog-source="'+p.source+'"]')?.click();}:
      ()=>{document.querySelector('[data-view="portals"]')?.click();document.querySelector('.platform-tab[data-platform="'+p.source+'"]')?.click();};
    actions.append(load,open);card.append(actions);
    return card;
  }
  // 0.5.49 (Björn, 12.11.2026): the platform tabs show the same overview as the catalogue (stock,
  // recognised, to check, open, offline copies), so both views read alike and the stored stock is
  // visible there too. One card implementation for both places.
  const tabTimers={};
  async function mountTabBoard(src) {
    clearTimeout(tabTimers[src]);
    const anchor=$(src==='netzkino'?'netzkino-sync-summary':src+'-summary')?.parentElement;
    if (!anchor?.parentElement) return;
    let host=$('atlas-tab-board-'+src);
    if (!host) {host=el('section',undefined,'background-status atlas-portal-dashboard atlas-tab-board');host.id='atlas-tab-board-'+src;anchor.parentElement.insertBefore(host,anchor);}
    let data;
    try {data=await window.api('film-platforms');}catch(e){if(!host.childElementCount)host.replaceChildren(el('p','Übersicht nicht verfügbar: '+e.message,'muted'));return;}
    const p=(data.film_platforms||[]).find(x=>x.source===src);
    if (!p) return;
    const grid=el('div',undefined,'atlas-portal-grid');grid.append(portalCard(p,true));
    host.replaceChildren(el('h2',p.name+' · Bestand & Werkzuordnung','atlas-dashboard-heading'),grid);
    const visible=!$('portals')?.hidden&&$('portals')?.dataset.platform===src;
    if (visible) tabTimers[src]=setTimeout(()=>mountTabBoard(src),p.running?4000:15000);
  }
  window.AtlasPlatformBoard={mount:mountTabBoard};
  // Returning to the catalogue restarts the overview polling (it pauses while the view is hidden).
  document.querySelector('[data-view="discover"]')?.addEventListener?.('click', () => setTimeout(() => refreshPortalBoard().catch(() => {}), 0));
  async function refreshPortalBoard() {
    clearTimeout(portalTimer);
    const board=portalBoard(),main=$('atlas-main-dashboard');
    if (main) main.hidden=!(source==='mediatheken'||source==='all');
    if (!board) return;
    if (source==='mediatheken' || $('discover')?.hidden) {board.hidden=true;return;}
    const seq=++portalSeq;let data;
    try {data=await window.api('film-platforms');}catch(e){if(seq===portalSeq){board.hidden=false;board.replaceChildren(el('p','Katalog-Übersicht nicht verfügbar: '+e.message,'muted'));}return;}
    if (seq!==portalSeq||source==='mediatheken') return;
    const list=(data.film_platforms||[]).filter(p=>source==='all'||p.source===source);
    board.replaceChildren(el('h2',source==='all'?'Weitere Kataloge · Bestand & Werkzuordnung':(list[0]?.name||'Katalog')+' · Bestand & Werkzuordnung','atlas-dashboard-heading'));
    const grid=el('div',undefined,'atlas-portal-grid');for(const p of list)grid.append(portalCard(p));board.append(grid);
    board.hidden=false;
    portalTimer=setTimeout(refreshPortalBoard,list.some(p=>p.running)?4000:15000);
  }
  function updateControls() {
    for (const b of document.querySelectorAll('[data-catalog-source]')) {
      const active=b.dataset.catalogSource===source;
      b.classList.toggle('primary',active);b.setAttribute('aria-pressed',String(active));
    }
    for (const b of document.querySelectorAll('[data-cross-kind]')) {
      const active=b.dataset.crossKind===kind;
      b.classList.toggle('primary',active);b.setAttribute('aria-pressed',String(active));
    }
    $('atlas-cross-title').textContent=seriesKey?seriesTitle:heading()+' · '+(kind==='movies'?'Filme':'Serien');
    $('atlas-cross-back-series').hidden=!seriesKey;
    $('atlas-cross-open-portal').hidden=source==='mediatheken';
  }
  function activate(name) {
    if (!VALID_SOURCES.includes(name)) return;
    source=name;seriesKey='';seriesTitle='';offset=0;sequence++;
    $('discover').dataset.source=name;
    $('atlas-source-content').hidden=false;
    updateControls();refresh();
    // The overview must never block the catalogue itself.
    refreshPortalBoard().catch(e=>console.warn('MediathekAtlas: Katalog-Übersicht',e));
  }
  function labelSource(item) {return item.source==='netzkino'?'Netzkino':PORTALS[item.source]||'Mediathek';}
  function medRow(item) {
    const m=item.metadata||{},r=item.source||{};
    return {source:'mediatheken',id:item.work_id||'',raw:item,kind:m.kind||'',
      title:m.title||r.title||'Ohne Titel',year:m.year||null,
      poster:m.poster||'',description:m.description||m.show_description||r.description||'',
      genres:m.genres||[],duration:m.source_duration_seconds||r.duration||null,
      score:medScore(m),pick:['matched','manual','identified'].includes(item.state),
      state:item.state,series_parent:!!item.series_parent,
      episode_count:item.episodes||0,available:!!item.available};
  }
  // Mediathek rating in the same shape as the portal score (portal_reference.rating).
  function medScore(m) {
    const value=Number(m.rating);
    if (m.rating==null || !Number.isFinite(value) || value<0 || value>10) return null;
    const src=m.rating_source||(['OMDb','IMDb Offline'].includes(m.provider)?'IMDb':m.provider||'');
    return {value:Math.round(value*10)/10,source:src==='IMDb Offline'||src==='OMDb'?'IMDb':src,votes:m.votes||null};
  }
  // Same rule as the Mediathek catalogue ("Entdecken"): ≥ 7.5 with 10,000 IMDb or 1,000 TMDB votes.
  function pickLabel(item) {
    const s=item.score;if (!s || item.pick===false) return '';
    const need={IMDb:10000,TMDB:1000}[s.source];
    if (!need || !(s.value>=7.5 && s.value<=10) || !(Number(s.votes)>=need)) return '';
    return item.kind==='movie'?'Großes Kino':item.kind==='series'?'Serienfavorit':'';
  }
  function nkRow(item) {
    return {source:'netzkino',id:item.id||'',raw:item,kind:item.media_type||'movie',
      title:item.title||'Ohne Titel',year:item.year||null,poster:item.poster||'',
      description:item.summary||'',genres:(item.categories||[]).filter(c=>c!=='Unbekannt').length?item.categories.filter(c=>c!=='Unbekannt'):item.genres||'',
      score:item.score||null,duration:item.duration||null,
      episode_count:item.episode_count||0,access_hint:item.access_hint||'',
      season:item.season,episode:item.episode,series_key:item.series_key};
  }
  // Pluto TV and JustWatch TV deliver the same row shape (shared portal panel).
  function plRow(item,src='pluto') {
    return {source:src,playable:item.playable!==0&&item.playable!==false,web_url:item.web_url||'',id:item.id||'',raw:item,kind:item.kind==='series'?'series':item.kind==='episode'?'episode':'movie',
      title:item.title||'Ohne Titel',year:item.year||null,poster:item.poster||'',description:item.summary||'',
      genres:(item.categories||[]).filter(c=>c!=='Unbekannt'),score:item.score||null,duration:item.duration||null,
      season:item.season,episode:item.episode};
  }
  function genreList(value) {
    if (Array.isArray(value)) return value.filter(v=>typeof v==='string');
    if (typeof value==='string') {
      try { const parsed=JSON.parse(value); if(Array.isArray(parsed))return genreList(parsed); }
      catch(_){}
      return value.split(/[,;·|]/).map(v=>v.trim()).filter(Boolean);
    }
    return [];
  }
  function makeCard(item) {
    const card=el('article',undefined,'atlas-uc-card');
    const art=el('div',undefined,'atlas-uc-poster');
    if (hrefOkay(item.poster)) {
      const img=el('img');img.src=item.poster;img.loading='lazy';img.alt='';img.referrerPolicy='no-referrer';
      art.append(img);
    } else art.append(el('span','Kein Cover','atlas-uc-empty-art'));
    const text=el('div',undefined,'atlas-uc-body');
    text.append(el('small',labelSource(item),'atlas-uc-source'));
    const title=el('h3',item.title);
    text.append(title);
    const facts=[item.kind==='series'||item.series_parent?'Serie':item.kind==='episode'?'Episode':'Film',
      item.year,item.kind==='series'&&item.episode_count?item.episode_count+' Folgen':null,
      item.kind==='episode'&&item.episode?'S'+(item.season??'?')+' E'+item.episode:null,
      ...genreList(item.genres).slice(0,2)].filter(Boolean).join(' · ');
    text.append(el('small',facts,'atlas-uc-meta'));
    const stars=window.AtlasPortalCategories?.rating(item.score);
    if (stars) text.append(stars);
    const pick=pickLabel(item);
    if (pick) text.append(el('div',pick,'pick-badge'));
    if (item.description) text.append(el('p',item.description.slice(0,220),'atlas-uc-desc'));
    const actions=el('div',undefined,'atlas-uc-actions');
    const details=el('button',item.kind==='series'&&item.source==='netzkino'?'Folgen anzeigen':PORTALS[item.source]?'Details':'Details & Angebote','atlas-uc-details');
    details.type='button';
    details.onclick=()=>openItem(item);
    actions.append(details);
    if (item.source==='netzkino' && item.kind!=='series') {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=async()=>{
        watch.disabled=true;
        try {await window.AtlasNetzkinoDetail.play(item.id,item.title);}
        catch(e){$('atlas-cross-status').textContent='Integrierte Wiedergabe: '+e.message;}
        finally{watch.disabled=false;}
      };
      actions.append(watch);
    }
    if (PORTALS[item.source] && item.kind!=='series' && item.playable) {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=()=>(item.source==='justwatch'?window.playJustWatch:window.playPluto)?.(item.id,item.title);
      actions.append(watch);
    }
    if (PORTALS[item.source] && item.kind!=='series' && !item.playable && hrefOkay(item.web_url)) {
      const link=el('a','Bei JustWatch ansehen','button');link.href=item.web_url;link.target='_blank';link.rel='noopener noreferrer';
      actions.append(link);
    }
    // 0.5.47: 30 days offline directly in the tile, the same control for every film platform.
    // 0.5.48: JustWatch titles released only at night (youth protection) can be reserved.
    const night=item.source==='justwatch'&&!item.playable;
    if (item.kind!=='series' && (item.source==='netzkino'?/^[a-f0-9]{32}$/.test(item.id||''):PORTALS[item.source]&&(item.playable||night))) {
      const off=window.AtlasOffline?.control(item.source,item.id,item.title,{night});
      if (off) actions.append(off);
    }
    text.append(actions);card.append(art,text);
    return card;
  }
  function openItem(item) {
    // 0.5.42: every film portal opens the same title page as the Mediathek works.
    if (item.source==='pluto'||item.source==='justwatch') window.AtlasPortalTitle?.open(item.source,item.id);
    else if (item.source==='netzkino') {
      if (item.kind==='series' && window.AtlasPortalTitle && /^series-[a-f0-9]{24}$/.test(item.series_key||'')) window.AtlasPortalTitle.open('netzkino',item.series_key);
      else if (item.kind==='series') {
        // Fallback without the shared title page (older layout).
        if (!$('atlas-cross-items') && window.MediathekAtlasNetzkino?.openSeries) {
          window.MediathekAtlasNetzkino.openSeries(item.series_key);
        } else {seriesKey=item.series_key;seriesTitle=item.title;offset=0;refresh();}
      } else if (window.AtlasPortalTitle) window.AtlasPortalTitle.open('netzkino',item.id);
      else window.AtlasNetzkinoDetail?.open(item.id);
    } else if (item.series_parent && typeof openShow==='function') {
      openShow(item.raw.show_key);
    } else if (typeof openTitle==='function') openTitle(item.raw);
    else $('atlas-cross-status').textContent='Detailansicht momentan nicht verfügbar.';
  }
  function sortRows(rows) {
    rows.sort((a,b)=>sort==='year' ? ((Number(b.year)||0)-(Number(a.year)||0) || a.title.localeCompare(b.title,'de')):
      a.title.localeCompare(b.title,'de'));
  }
  // Genre bar with counts like the original "Filme, Serien & Genres" tree: Mediatheken from
  // the catalogue tree (per media kind), portals from their canonical categories.
  function paintCategories(counts) {
    const merged=new Map();
    for (const c of counts) {
      const name=String(c.genre||'').trim();if(!name) continue;
      merged.set(name,(merged.get(name)||0)+(Number(c.n)||0));
    }
    const list=[...merged].map(([g,n])=>({genre:g,n})).sort((a,b)=>(a.genre==='Unbekannt')-(b.genre==='Unbekannt')||a.genre.localeCompare(b.genre,'de'));
    window.AtlasPortalCategories?.render($('atlas-cross-categories'),seriesKey?[]:list,genre,value=>{
      genre=value;offset=0;$('atlas-cross-genre').value=value;refresh();
    });
  }
  function paint(rows,notes,totals,facets) {
    const host=$('atlas-cross-items');host.replaceChildren();
    sortRows(rows);
    const genreSelect=$('atlas-cross-genre'),previous=genreSelect.value;
    const labels=new Map();
    for(const raw of facets){
      const label=String(raw).trim(), key=label.toLocaleLowerCase('de');
      if(label && (!labels.has(key) || labels.get(key)===key)) labels.set(key,label);
    }
    const options=['',...labels.values()].sort((a,b)=>a.localeCompare(b,'de'));
    genreSelect.replaceChildren();
    for (const name of options) {
      const option=el('option',name||'Alle Genres');option.value=name;genreSelect.append(option);
    }
    if (options.some(x=>x.toLowerCase()===genre.toLowerCase())) genreSelect.value=options.find(x=>x.toLowerCase()===genre.toLowerCase());
    else if (genre) {const option=el('option',genre);option.value=genre;genreSelect.append(option);genreSelect.value=genre;}
    else genreSelect.value=previous&&options.includes(previous)?previous:'';
    for (const item of rows)host.append(makeCard(item));
    if (!rows.length)host.append(el('p','Keine passenden Werke gefunden.','empty'));
    $('atlas-cross-status').textContent=notes.join(' · ');
    const total=totals.reduce((a,b)=>a+b,0);
    $('atlas-cross-page').textContent=(total?offset+1:0)+'–'+Math.min(offset+48,Math.max(...totals,0))+' je Quelle · '+total+' Treffer insgesamt';
    $('atlas-cross-prev').disabled=offset===0;
    $('atlas-cross-next').disabled=totals.every(t=>offset+48>=t);
    $('atlas-cross-items').setAttribute('aria-busy','false');
  }
  async function refresh() {
    const seq=++sequence;
    updateControls();
    $('atlas-cross-items').setAttribute('aria-busy','true');
    $('atlas-cross-status').textContent='Katalog wird gelesen …';
    const nkNeeded=(source==='all'||source==='netzkino');
    const medNeeded=(source==='all'||source==='mediatheken') && !seriesKey;
    const plNeeded=(source==='all'||source==='pluto') && !seriesKey;
    const jwNeeded=(source==='all'||source==='justwatch') && !seriesKey;
    const nkView=seriesKey?'episodes':kind;
    const requests=[];
    if (medNeeded)requests.push({source:'mediatheken',req:window.api('catalog?'+new URLSearchParams({
      query:search,kind:kind==='movies'?'movie':'series',genre,sort,
      downloaded:'all',offset:String(offset),collection
    }))});
    if (nkNeeded)requests.push({source:'netzkino',req:window.api('netzkino-grouped?'+new URLSearchParams({
      view:nkView,series_key:seriesKey,q:search,genre,sort,offset:String(offset),limit:'48',collection:seriesKey?'':collection
    }))});
    if (plNeeded)requests.push({source:'pluto',req:window.api('pluto?'+new URLSearchParams({
      view:kind==='movies'?'movies':'series',q:search,genre,sort:sort==='year'?'year':'title',offset:String(offset),limit:'48',collection
    }))});
    if (jwNeeded)requests.push({source:'justwatch',req:window.api('justwatch?'+new URLSearchParams({
      view:kind==='movies'?'movies':'series',q:search,genre,sort:sort==='year'?'year':'title',offset:String(offset),limit:'48',collection
    }))});
    const responses=await Promise.allSettled(requests.map(x=>x.req));
    if (seq!==sequence) return;
    const rows=[],notes=[],totals=[],facets=[],counts=[];
    for(let i=0;i<requests.length;i++) {
      const request=requests[i],result=responses[i];
      if(result.status!=='fulfilled') {
        notes.push(({netzkino:'Netzkino',...PORTALS}[request.source]||'ARD, ZDF & Co.')+' nicht verfügbar: '+result.reason.message);
        continue;
      }
      const data=result.value;
      totals.push(data.total||0);
      if (request.source==='mediatheken') {
        rows.push(...(data.items||[]).map(medRow));
        // Existing Mediathek genre tree is reused, not rebuilt by the external source.
        facets.push(...medGenres);
        counts.push(...medTree.filter(r=>r.kind===(kind==='movies'?'movie':'series')));
        for (const item of data.items||[]) facets.push(...genreList(item.metadata?.genres));
        notes.push('ARD, ZDF & Co.: '+data.total+' Treffer');
      } else if (PORTALS[request.source]) {
        rows.push(...(data.items||[]).map(item=>plRow(item,request.source)));
        facets.push(...(data.genre_counts||[]).map(g=>g.genre).filter(g=>g!=='Unbekannt'));
        counts.push(...(data.genre_counts||[]));
        notes.push(PORTALS[request.source]+': '+data.total+' Treffer');
      } else {
        rows.push(...(data.items||[]).map(nkRow));
        facets.push(...(data.genres||[]).filter(g=>g!=='Unbekannt'));
        counts.push(...(data.genre_counts||[]));
        notes.push('Netzkino: '+data.total+' Treffer · Startseitenindex, kein vollständiger Gesamtkatalog'+(seriesKey?' · '+seriesTitle:''));
      }
    }
    if(seq===sequence){paint(rows,notes,totals,facets);paintCategories(counts);}
  }
  for (const b of document.querySelectorAll('[data-catalog-source]')) b.onclick=()=>activate(b.dataset.catalogSource);
  for (const b of document.querySelectorAll('[data-cross-kind]')) b.onclick=()=>{
    kind=b.dataset.crossKind;seriesKey='';seriesTitle='';offset=0;
    if (collection && (collection==='cinema')!==(kind==='movies')) {collection='';$('atlas-cross-collection').value='';}
    refresh();
  };
  $('atlas-cross-search')?.addEventListener('submit',event=>{
    event.preventDefault();search=$('atlas-cross-query').value.trim().slice(0,180);offset=0;refresh();
  });
  $('atlas-cross-genre')?.addEventListener('change',event=>{genre=event.target.value;offset=0;refresh();});
  $('atlas-cross-collection')?.addEventListener('change',event=>{
    collection=event.target.value;
    // Großes Kino = films, Serienfavoriten = series (as in the Mediathek catalogue).
    if (collection) kind=collection==='cinema'?'movies':'series';
    seriesKey='';seriesTitle='';offset=0;refresh();
  });
  $('atlas-cross-sort')?.addEventListener('change',event=>{sort=event.target.value;offset=0;refresh();});
  $('atlas-cross-reset')?.addEventListener('click',()=>{
    search='';genre='';sort='title';offset=0;seriesKey='';seriesTitle='';collection='';
    if ($('atlas-cross-collection')) $('atlas-cross-collection').value='';
    $('atlas-cross-query').value='';$('atlas-cross-genre').value='';$('atlas-cross-sort').value='title';refresh();
  });
  $('atlas-cross-back-series')?.addEventListener('click',()=>{seriesKey='';seriesTitle='';offset=0;refresh();});
  $('atlas-cross-prev')?.addEventListener('click',()=>{offset=Math.max(0,offset-48);refresh();});
  $('atlas-cross-next')?.addEventListener('click',()=>{offset+=48;refresh();});
  $('atlas-cross-open-portal')?.addEventListener('click',()=>{
    document.querySelector('[data-view="portals"]')?.click();
    document.querySelector('.platform-tab[data-platform="'+(PORTALS[source]?source:'netzkino')+'"]')?.click();
  });
  arrangeAdvanced();
  // The category tree is computed in the background after start; ask again until it is there.
  function loadTree(attempt=0) {
    window.api('catalog-tree').then(data => {
      medTree=(data.tree||[]).filter(entry=>entry&&entry.genre);
      medGenres=medTree.map(entry=>entry.genre);
      if(source==='all'||source==='mediatheken') refresh();
      if((data.loading||!medTree.length) && attempt<20) setTimeout(()=>loadTree(attempt+1),3000);
    }).catch(()=>{if(attempt<20)setTimeout(()=>loadTree(attempt+1),5000);});
  }
  loadTree();
  window.AtlasUnifiedCatalog={activate,refresh};
  activate('mediatheken');
})();
