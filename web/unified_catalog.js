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
  const VALID_SOURCES = ['all','mediatheken','netzkino','pluto','justwatch','rakuten','youtube','joyn'];
  const PORTALS = {pluto:'Pluto TV',justwatch:'JustWatch TV',rakuten:'Rakuten TV',youtube:'YouTube',joyn:'Joyn'};
  // Player and official-page label per portal (0.5.51: one table instead of per-source branches).
  const PLAY = {pluto:()=>window.playPluto,justwatch:()=>window.playJustWatch,rakuten:()=>window.playRakuten,youtube:()=>window.playYouTube,joyn:()=>null};
  const EXTERNAL = {pluto:'Bei Pluto TV ansehen',justwatch:'Bei JustWatch ansehen',rakuten:'Bei Rakuten TV ansehen',youtube:'Bei YouTube ansehen',joyn:'Bei Joyn ansehen'};
  const TYPES = ['movies','series'];
  let source='all',kind='movies',genre='',sort='title',search='',offset=0,sequence=0;
  let seriesKey='',seriesTitle='';
  let medGenres=[],medTree=[],collection='';
  let pendingTries=0;
  const heading=() => ({all:'Alle Plattformen',mediatheken:'ARD, ZDF & Co.',netzkino:'Netzkino',...PORTALS}[source]);
  const hrefOkay=value=>typeof value==='string' && /^https:\/\/[a-z0-9.-]+\//i.test(value) && !/[\s<>'"]/.test(value);
  function arrangeAdvanced() {
    const discover=$('discover');
    const switcher=discover?.querySelector('.atlas-source-switch');
    const body=$('atlas-source-content');
    if (!discover || !switcher || !body || $('atlas-catalog-advanced')) return;
    // 0.5.55 (Björn, 12.11.2026): the dashboard shows films and series only. The work catalogue
    // with genre tree moves to Verwaltung → Werkkatalog, the scan and recognition boards to
    // Verwaltung → Status & Abgleich. Live nodes are moved, so IDs and handlers stay intact.
    const legacyHost=$('legacy-body'),boards=$('status-boards');
    const workerOverview=dashboard=>{
      const workers=$('metadata-workers-status');
      const statusBottom=dashboard.querySelector('.atlas-status-bottom');
      if(workers && statusBottom && !dashboard.querySelector('.atlas-worker-overview')){
        const overview=el('section',undefined,'atlas-worker-overview');
        overview.append(el('h3','Verarbeitung & Warteschlangen'));
        overview.append(workers);
        statusBottom.insertAdjacentElement('afterend',overview);
        const title=dashboard.querySelector('#metadata-status')?.closest('.atlas-status-panel')?.querySelector('h3');
        if(title)title.textContent='Letzte Erkennung';
      }
    };
    // 0.5.57: both blocks stand in Verwaltung in the HTML itself. On a slow start the page showed
    // them in the dashboard until this script had run (Björn, 12.11.2026).
    if (boards?.querySelector('#atlas-main-dashboard')) {
      const marker=el('div');marker.id='atlas-catalog-advanced';marker.hidden=true;discover.append(marker);
      workerOverview($('atlas-main-dashboard'));
      return;
    }
    if (legacyHost && boards) {
      const marker=el('div');marker.id='atlas-catalog-advanced';marker.hidden=true;discover.append(marker);
      const historic=discover.querySelector('.background-status');
      for (const child of [...discover.children]) {
        if (child!==switcher && child!==body && child!==marker && child!==historic) legacyHost.append(child);
      }
      if (!historic) { console.warn('MediathekAtlas: Scan- und Erkennungsübersicht fehlt'); return; }
      const dashboard=el('section',undefined,'background-status atlas-main-dashboard');
      dashboard.id='atlas-main-dashboard';
      dashboard.setAttribute('aria-label','Mediatheken-Scanner und Metadatenabgleich');
      dashboard.append(el('h2','ARD, ZDF & Co. · Scan & Erkennung','atlas-dashboard-heading'));
      historic.querySelector('summary')?.remove();
      while(historic.firstChild) dashboard.append(historic.firstChild);
      historic.remove();
      boards.append(dashboard);
      workerOverview(dashboard);
      return;
    }
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
  const SYNC={netzkino:'netzkino-sync',pluto:'pluto-sync',justwatch:'justwatch-sync',rakuten:'rakuten-sync',youtube:'youtube-sync',joyn:'joyn-sync'};
  const num=n=>Number(n||0).toLocaleString('de-DE');
  const when=t=>t?new Date(t*1000).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}):'noch nie';
  function portalBoard() {
    let board=$('atlas-portal-dashboard');
    if (!board) {
      board=el('section',undefined,'background-status atlas-portal-dashboard');
      board.id='atlas-portal-dashboard';board.setAttribute('aria-label','Katalog-Übersicht je Plattform');board.hidden=true;
      const body=$('atlas-source-content'),boards=$('status-boards');
      if (boards) boards.append(board);
      else if (typeof body?.parentElement?.insertBefore==='function') body.parentElement.insertBefore(board,body);
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
    if (p.sources!==undefined) tile('Kanäle/Playlists',num(p.sources));
    // 0.5.74: YouTube music videos have their own count (they are no films or series).
    if (p.music!==undefined) tile('Musik-Playlists & -Videos',num(p.music),num(p.tracks||0)+' Musikvideos, im YouTube-Bereich unter „Musikvideos“');
    if (p.key_set===false) tile('API-Schlüssel','fehlt','Im YouTube-Bereich einen Schlüssel für die YouTube Data API v3 eintragen');
    if (p.protected) tile('kopiergeschützt (nur beim Anbieter)',num(p.protected));
    tile('Stand des Katalogs',when(p.last_success));
    tile('eindeutig zugeordnet',num(by.candidate),'Eindeutige IMDb-/TVDB-/TMDB-Referenz');
    tile('zu prüfen',num(by.review),'Widersprüchliche Referenzen, keine automatische Zuordnung');
    tile('ohne Treffer',num(by.no_match));
    if (by.partial) tile('Anbieter nicht erreichbar',num(by.partial),'Wird später automatisch erneut geprüft');
    tile('noch offen',num(Math.max(0,titles-checked)),'Wird im Hintergrund abgeglichen (ein Titel alle 6 s)');
    card.append(tiles);
    if (p.running && p.progress) card.append(el('small','Abruf läuft: '+p.progress,'muted atlas-portal-running'));
    const share=titles?Math.min(100,Math.round(checked*100/titles)):0;
    const bar=el('div',undefined,'atlas-portal-progress');const fill=el('span');fill.style.width=share+'%';bar.append(fill);
    bar.setAttribute('role','progressbar');bar.setAttribute('aria-valuenow',String(share));bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');
    card.append(el('small','Werkzuordnung (IMDb/TVDB/TMDB): '+num(checked)+' von '+num(titles)+' geprüft · '+share+' %'),bar);
    const off=p.offline||{};
    // 0.5.51: Rakuten TV delivers every free film/episode with copy protection – no offline copies there.
    if (p.offline_note) card.append(el('small','Offline: ausgeschaltet – '+(p.source==='youtube'?'im YouTube-Bereich auf eigene Verantwortung einschaltbar (YouTube-Nutzungsbedingungen)':p.offline_note),'muted'));
    else if (p.protected && p.protected>=p.titles) card.append(el('small','Offline: nicht möglich – der Anbieter liefert nur mit Kopierschutz','muted'));
    else card.append(el('small','Offline ('+p.offline_days+' Tage): '+num(off.done)+' verfügbar · '+num((off.queued||0)+(off.downloading||0)+(off.tagging||0))+' in Arbeit'+(off.error?' · '+num(off.error)+' Fehler':''),'muted'));
    const actions=el('div',undefined,'atlas-portal-actions');
    const load=el('button',p.running?'Katalog wird geladen …':'↻ Katalog jetzt laden');load.type='button';load.disabled=!!p.running;
    load.onclick=async()=>{load.disabled=true;try{await window.api(SYNC[p.source],{});}catch(e){load.textContent=e.message;}setTimeout(inTab?()=>mountTabBoard(p.source):refreshPortalBoard,1500);};
    const open=el('button',inTab?'Im Dashboard anzeigen':'Plattform öffnen');open.type='button';
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
  document.addEventListener?.('atlas-view', event => { if (event.detail?.view==='status') refreshPortalBoard().catch(() => {}); });
  async function refreshPortalBoard() {
    clearTimeout(portalTimer);
    const board=portalBoard(),main=$('atlas-main-dashboard');
    const inStatus=!!$('status-boards');
    if (main) main.hidden=inStatus?false:!(source==='mediatheken'||source==='all');
    if (!board) return;
    // 0.5.55: the boards live under Verwaltung → Status & Abgleich and show every platform there;
    // they are only fetched while that view is open.
    if (inStatus ? $('status')?.hidden : (source==='mediatheken' || $('discover')?.hidden)) {if(!inStatus)board.hidden=true;return;}
    const seq=++portalSeq;let data;
    try {data=await window.api('film-platforms');}catch(e){if(seq===portalSeq){board.hidden=false;board.replaceChildren(el('p','Katalog-Übersicht nicht verfügbar: '+e.message,'muted'));}return;}
    if (seq!==portalSeq||(!inStatus&&source==='mediatheken')) return;
    const list=(data.film_platforms||[]).filter(p=>inStatus||source==='all'||p.source===source);
    board.replaceChildren(el('h2',inStatus||source==='all'?'Weitere Kataloge · Bestand & Werkzuordnung':(list[0]?.name||'Katalog')+' · Bestand & Werkzuordnung','atlas-dashboard-heading'));
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
    $('atlas-cross-title').textContent=kind==='music'?'YouTube · Musikvideos':seriesKey?seriesTitle:heading()+' · '+(kind==='movies'?'Filme':'Serien');
    $('atlas-cross-back-series').hidden=!seriesKey;
    $('atlas-cross-open-portal').hidden=source==='mediatheken'||source==='all';
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
  function labelSource(item) {return item.source==='netzkino'?'Netzkino':PORTALS[item.source]||'ARD, ZDF & Co.';}
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
    return {source:src,night:!!item.night,offline:src==='youtube'?!!item.offline:undefined,playable:item.playable!==0&&item.playable!==false,web_url:item.web_url||'',id:item.id||'',raw:item,kind:item.kind==='series'?'series':item.kind==='episode'?'episode':'movie',
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
  // 0.5.55: one tile for every source. The buttons of one offer come from actionNodes(), so a
  // title that several providers offer gets the same buttons per provider inside one tile.
  function canOffline(item) {
    const night=item.source==='justwatch'&&!item.playable&&!!item.night;
    return item.kind!=='series' && !!(item.source==='netzkino'?/^[a-f0-9]{32}$/.test(item.id||''):PORTALS[item.source]&&(item.source==='youtube'?item.offline:(item.playable||night)));
  }
  function actionNodes(item, withDetails=true, siblings=null) {
    const nodes=[];
    if (withDetails) {
      const details=el('button',item.kind==='series'?'Folgen & Details':'Details','atlas-uc-details');
      details.type='button';
      details.onclick=()=>openItem(item);
      nodes.push(details);
    }
    if (item.source==='mediatheken' && !item.series_parent && typeof playMedia==='function' && typeof playable==='function' && playable(item.raw)) {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=()=>playMedia(item.raw);
      nodes.push(watch);
    }
    if (item.source==='netzkino' && item.kind!=='series') {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=async()=>{
        watch.disabled=true;
        try {await window.AtlasNetzkinoDetail.play(item.id,item.title);}
        catch(e){if($('atlas-cross-status'))$('atlas-cross-status').textContent='Integrierte Wiedergabe: '+e.message;}
        finally{watch.disabled=false;}
      };
      nodes.push(watch);
    }
    if (PORTALS[item.source] && item.kind!=='series' && item.playable) {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=()=>{const fn=PLAY[item.source]?.();if(typeof fn==='function')fn(item.id,item.title);else window.notice?.(window.atlasPlayerMissing?.()||'Der Player ist nicht geladen; Seite neu laden.','error');};
      nodes.push(watch);
    }
    if (PORTALS[item.source] && item.kind!=='series' && !item.playable && hrefOkay(item.web_url)) {
      // 0.5.70: the same button shape as "Ansehen" on every tile
      const link=el('a','↗ '+(EXTERNAL[item.source]||'Beim Anbieter ansehen'),'button atlas-uc-external');link.href=item.web_url;link.target='_blank';link.rel='noopener noreferrer';
      nodes.push(link);
    }
    // 0.5.47: 30 days offline directly in the tile, the same control for every film platform.
    // 0.5.48: JustWatch titles released only at night (youth protection) can be reserved.
    // 0.5.52: only with a real time window; other titles without a stream are copy protected.
    const night=item.source==='justwatch'&&!item.playable&&!!item.night;
    // 0.5.70 (Björn, 12.11.2026): a download button wherever a download is possible, otherwise nothing
    // (the copy-protection note stays on the title page).
    if (item.source==='mediatheken' && !item.series_parent && item.raw && typeof edit==='function') {
      const files=(item.raw.links||[]).some(l=>l.supported&&/^https?:\/\//i.test(l.url));
      if (item.raw.downloaded) { const done=el('button','✓ Heruntergeladen','atlas-uc-download atlas-offline-done');done.type='button';done.disabled=true;nodes.push(done); }
      else if (files) { const load=el('button','⬇ Herunterladen','atlas-uc-download');load.type='button';load.title='Fassung wählen, Angaben prüfen und herunterladen';load.onclick=()=>edit(item.raw);nodes.push(load); }
    }
    if (canOffline(item)) {
      // 0.5.63: the other providers of the same title can be chosen in the dialogue before the download
      const alternatives=(siblings||[]).filter(o=>o!==item&&canOffline(o)).map(o=>({source:o.source,id:o.id}));
      const off=window.AtlasOffline?.control(item.source,item.id,item.title,{night,alternatives});
      if (off) nodes.push(off);
    }
    return nodes;
  }
  function makeCard(item) {
    // item.offers: the same title at several providers (dashboard "Alle"), best offer first.
    const offers=item.offers&&item.offers.length?item.offers:[item];
    const main=offers[0];
    const pickFrom=(field,test)=>(offers.find(o=>test(o[field]))||{})[field];
    const poster=(offers.find(o=>o.source!=='youtube'&&hrefOkay(o.poster))||offers.find(o=>hrefOkay(o.poster))||{}).poster;
    const card=el('article',undefined,'atlas-uc-card'+(offers.length>1?' atlas-uc-multi':''));
    const art=el('div',undefined,'atlas-uc-poster');
    if (hrefOkay(poster)) {
      const img=el('img');img.src=poster;img.loading='lazy';img.alt='';img.referrerPolicy='no-referrer';
      art.append(img);
    } else art.append(el('span','Kein Cover','atlas-uc-empty-art'));
    art.classList.add('clickable');art.onclick=()=>openItem(main);
    const text=el('div',undefined,'atlas-uc-body');
    text.append(el('small',offers.map(labelSource).join(' · '),'atlas-uc-source'));
    const title=el('h3',main.title);title.classList.add('clickable');title.onclick=()=>openItem(main);
    text.append(title);
    const genres=genreList(pickFrom('genres',g=>genreList(g).length));
    const year=main.year||pickFrom('year',y=>!!y&&true);
    const facts=[main.kind==='series'||main.series_parent?'Serie':main.kind==='episode'?'Episode':'Film',
      year,(main.kind==='series'||main.series_parent)&&main.episode_count?main.episode_count+' Folgen':null,
      main.kind==='episode'&&main.episode?'S'+(main.season??'?')+' E'+main.episode:null,
      ...genres.slice(0,2)].filter(Boolean).join(' · ');
    text.append(el('small',facts,'atlas-uc-meta'));
    const scored=offers.find(o=>o.score)||main;
    const stars=window.AtlasPortalCategories?.rating(scored.score);
    if (stars) text.append(stars);
    const pick=pickLabel(scored);
    if (pick) text.append(el('div',pick,'pick-badge'));
    const description=pickFrom('description',d=>!!d);
    if (description) text.append(el('p',description.slice(0,220),'atlas-uc-desc'));
    const actions=el('div',undefined,'atlas-uc-actions');
    actions.append(...actionNodes(main,true,offers));
    text.append(actions);
    if (offers.length>1) {
      const more=el('details',undefined,'atlas-uc-more');
      more.append(el('summary','Auch bei '+offers.slice(1).map(labelSource).join(', ')));
      for (const other of offers.slice(1)) {
        const row=el('div',undefined,'atlas-uc-alt');
        const name=el('button',labelSource(other),'atlas-uc-alt-name');name.type='button';name.title='Titelseite bei '+labelSource(other)+' öffnen';
        name.onclick=()=>openItem(other);
        const alt=el('div',undefined,'atlas-uc-actions');alt.append(...actionNodes(other,false,offers));
        row.append(name,alt);more.append(row);
      }
      text.append(more);
    }
    card.append(art,text);
    return card;
  }
  function openItem(item) {
    // 0.5.42: every film portal opens the same title page as the Mediathek works.
    if (PORTALS[item.source]) window.AtlasPortalTitle?.open(item.source,item.id);
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
  function paint(rows,notes,totals,facets,sorted) {
    const host=$('atlas-cross-items');host.replaceChildren();
    if (!sorted) sortRows(rows);
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
    $('atlas-cross-page').textContent=(total?offset+1:0)+'–'+Math.min(offset+48,Math.max(...totals,0))+' von '+num(total);
    $('atlas-cross-prev').disabled=offset===0;
    $('atlas-cross-next').disabled=totals.every(t=>offset+48>=t);
    $('atlas-cross-items').setAttribute('aria-busy','false');
  }
  // 0.5.55: "Alle" reads one merged, globally sorted index from the server (unified_index.py):
  // one request instead of six, the same title of several providers in one tile, and paging over
  // the whole list instead of per source.
  const rowOf=(src,item)=>src==='mediatheken'?medRow(item):src==='netzkino'?nkRow(item):plRow(item,src);
  async function refreshAll(seq) {
    let data;
    try {
      data=await window.api('unified?'+new URLSearchParams({kind,q:search,genre,sort,collection,offset:String(offset)}));
    } catch(e) {
      if (seq!==sequence) return;
      $('atlas-cross-items').replaceChildren(el('p','Die Filme und Serien konnten nicht geladen werden: '+e.message,'empty'));
      $('atlas-cross-status').textContent='Neuer Versuch über „Suchen“ oder einen Wechsel der Quelle.';
      $('atlas-cross-items').setAttribute('aria-busy','false');
      return;
    }
    if (seq!==sequence) return;
    const rows=[];
    for (const entry of data.items||[]) {
      const offers=(entry.offers||[]).map(o=>rowOf(o.source,o.item));
      if (offers.length) rows.push({...offers[0],offers});
    }
    const names=data.names||{};
    const notes=Object.entries(data.counts||{}).filter(([,n])=>n).map(([src,n])=>(names[src]||src)+': '+num(n));
    for (const [src,msg] of Object.entries(data.errors||{})) notes.push((names[src]||src)+' nicht verfügbar: '+msg);
    if (data.merged) notes.push(num(data.merged)+' Titel bei mehreren Anbietern zusammengefasst');
    // 0.5.57: after a start the large catalogue of ARD, ZDF & Co. is grouped in the background.
    // The other platforms are shown at once and the view completes itself.
    const waiting=(data.pending||[]).map(src=>names[src]||src);
    if (waiting.length) {
      notes.push(waiting.join(', ')+' wird noch eingelesen und erscheint gleich von selbst');
      pendingTries+=1;
      if (pendingTries<=90) setTimeout(()=>{ if (seq===sequence && source==='all' && !seriesKey) refreshAll(seq); },pendingTries<5?1500:4000);
    } else pendingTries=0;
    const counts=[...(data.genre_counts||[]),...medTree.filter(r=>r.kind===(kind==='movies'?'movie':'series'))];
    const facets=[...medGenres,...(data.genre_counts||[]).map(g=>g.genre).filter(g=>g!=='Unbekannt')];
    paint(rows,notes,[data.total||0],facets,true);
    paintCategories(counts);
    const total=Number(data.total||0);
    $('atlas-cross-page').textContent=(total?offset+1:0)+'–'+Math.min(offset+48,total)+' von '+num(total);
  }
  /* 0.5.76 (Björn, 13.11.2026): music videos as third entry next to films and series. They come from
     YouTube only (playlists and single videos); a playlist opens in the YouTube area with "play all"
     and "save all / selection". No film references, no genres. */
  function musicCard(item) {
    const card=el('article',undefined,'atlas-uc-card atlas-uc-music');
    const art=el('div',undefined,'atlas-uc-poster clickable');
    if (hrefOkay(item.poster)) {const img=el('img');img.src=item.poster;img.loading='lazy';img.alt='';img.referrerPolicy='no-referrer';art.append(img);}
    else art.append(el('span','Kein Cover','atlas-uc-empty-art'));
    const album=item.kind==='album';
    const open=()=>album?window.MediathekAtlasYouTube?.openAlbum?.(item):window.playYouTube?.(item.id,item.title);
    art.onclick=open;
    const text=el('div',undefined,'atlas-uc-body');
    text.append(el('small','YouTube · '+(album?'Musik-Playlist':'Musikvideo'),'atlas-uc-source'));
    const title=el('h3',item.title);title.classList.add('clickable');title.onclick=open;text.append(title);
    const mins=item.duration?Math.round(item.duration/60)+' min':'';
    text.append(el('small',[item.category,album?num(item.number||0)+' Videos':null,mins].filter(Boolean).join(' · '),'atlas-uc-facts'));
    const actions=el('div',undefined,'atlas-uc-actions');
    const main=el('button',album?'Playlist öffnen':'▶ Ansehen','atlas-uc-play');main.type='button';main.onclick=open;actions.append(main);
    if (!album && item.offline) {const off=window.AtlasOffline?.control('youtube',item.id,item.title);if(off)actions.append(off);}
    if (hrefOkay(item.web_url)) {const a=el('a','Bei YouTube ansehen','button');a.href=item.web_url;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);}
    text.append(actions);card.append(art,text);
    return card;
  }
  async function refreshMusic(seq) {
    const host=$('atlas-cross-items');
    let data;
    try {data=await window.api('youtube?'+new URLSearchParams({view:'music',q:search,sort:sort==='year'?'year':'title',offset:String(offset),limit:'48'}));}
    catch(e){if(seq!==sequence)return;host.replaceChildren(el('p','Musikvideos nicht verfügbar: '+e.message,'empty'));$('atlas-cross-status').textContent='';host.setAttribute('aria-busy','false');return;}
    if (seq!==sequence) return;
    host.replaceChildren();
    const items=data.items||[],total=Number(data.total||0),st=data.status||{};
    for (const item of items) host.append(musicCard(item));
    if (!items.length) host.append(el('p',search?'Keine passenden Musikvideos gefunden.':st.running?'Der YouTube-Abruf läuft – die Musikvideos erscheinen, sobald er fertig ist.':
      'Noch keine Musikvideos. Unter Plattformen → YouTube → „YouTube-Kanäle & API-Schlüssel“ eine Playlist oder ein Video mit der Art „Musikvideos“ eintragen.','empty'));
    $('atlas-cross-status').textContent='YouTube: '+num(total)+' Musik-Playlists und einzelne Videos'+(st.tracks?' · '+num(st.tracks)+' Musikvideos insgesamt':'')+(st.running&&st.progress?' · Abruf läuft: '+st.progress:'');
    $('atlas-cross-page').textContent=(total?offset+1:0)+'–'+Math.min(offset+48,total)+' von '+num(total);
    $('atlas-cross-prev').disabled=offset===0;$('atlas-cross-next').disabled=offset+48>=total;
    paintCategories([]);
    host.setAttribute('aria-busy','false');
  }
  async function refresh() {
    const seq=++sequence;
    updateControls();
    $('atlas-cross-items').setAttribute('aria-busy','true');
    $('atlas-cross-status').textContent=kind==='music'?'Musikvideos werden geladen …':'Filme und Serien werden geladen …';
    if (kind==='music') return refreshMusic(seq);
    if (source==='all' && !seriesKey) return refreshAll(seq);
    const nkNeeded=(source==='all'||source==='netzkino');
    const medNeeded=(source==='all'||source==='mediatheken') && !seriesKey;
    const plNeeded=(source==='all'||source==='pluto') && !seriesKey;
    const jwNeeded=(source==='all'||source==='justwatch') && !seriesKey;
    const rkNeeded=(source==='all'||source==='rakuten') && !seriesKey;
    const ytNeeded=(source==='all'||source==='youtube') && !seriesKey;
    const jyNeeded=(source==='all'||source==='joyn') && !seriesKey;
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
    if (rkNeeded)requests.push({source:'rakuten',req:window.api('rakuten?'+new URLSearchParams({
      view:kind==='movies'?'movies':'series',q:search,genre,sort:sort==='year'?'year':'title',offset:String(offset),limit:'48',collection
    }))});
    if (ytNeeded)requests.push({source:'youtube',req:window.api('youtube?'+new URLSearchParams({
      view:kind==='movies'?'movies':'series',q:search,genre,sort:sort==='year'?'year':'title',offset:String(offset),limit:'48',collection
    }))});
    if (jyNeeded)requests.push({source:'joyn',req:window.api('joyn?'+new URLSearchParams({
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
      const before=medTree.length;
      medTree=(data.tree||[]).filter(entry=>entry&&entry.genre);
      medGenres=medTree.map(entry=>entry.genre);
      // 0.5.55: only repaint when the genre tree arrived; every retry used to reload the catalogue.
      if(medTree.length!==before&&(source==='all'||source==='mediatheken')) refresh();
      if((data.loading||!medTree.length) && attempt<20) setTimeout(()=>loadTree(attempt+1),3000);
    }).catch(()=>{if(attempt<20)setTimeout(()=>loadTree(attempt+1),5000);});
  }
  loadTree();
  window.AtlasUnifiedCatalog={activate,refresh};
  // Shared tile for the platform tabs (web/portal_panel.js, web/netzkino.js) and the preview.
  window.AtlasCards={card:makeCard,portalRow:plRow,netzkinoRow:nkRow,mediathekRow:medRow};
  // Start view from Verwaltung → Darstellung (default: all platforms, films).
  const start=prefs=>{
    if (TYPES.includes(prefs?.start_kind)) kind=prefs.start_kind;
    activate(VALID_SOURCES.includes(prefs?.start_source)?prefs.start_source:'all');
  };
  if (window.AtlasDisplay?.ready) {
    window.AtlasDisplay.ready.then(start,()=>start({}));
    window.AtlasDisplay.onChange((now,before)=>{ if (now.merge_duplicates!==before.merge_duplicates && source==='all') refresh(); });
  } else start({});
})();
