/* 0.6.8 Ansehen-Modus für Erwachsene (Björn, 15.11.2026: „Bitte auch einen Erwachsenen-Modus“).

   /ansehen ist dieselbe Seite wie „/“ mit <html data-mode="watch">: ohne Seitenleiste und Verwaltung,
   großformatig wie bei einem Streamingdienst. Alles Bestehende wird wiederverwendet:
   - Titelseite, Merken, Offline-Knöpfe: window.AtlasCards.open (web/unified_catalog.js) → AtlasPortalTitle
   - Player: playRef / playJob / playLive (web/player.js), Weiterschauen und Merkliste: /api/watch
   - Kataloge: /api/unified (alle freien Dienste zusammen), Live-TV: /api/live-tv
   - Offline-Kopien und YouTube-Abos: /api/watch-home (watch_home.py)
   In der normalen Ansicht führt „Ansehen-Modus“ in der Seitenleiste hierher, „Verwaltung“ oben zurück. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = String(text); return n; };
  const root = $('watch');
  if (!root) return;
  const MODE = document.documentElement.dataset.mode === 'watch';
  const pageToken = () => (typeof token === 'string' ? token : document.querySelector('meta[name=atlas-token]')?.content || '');
  const call = path => window.api(path);
  const posterOkay = v => typeof v === 'string' && /^https:\/\/[a-z0-9.-]+\//i.test(v) && !/[\s<>'"]/.test(v);
  const local = (kind, id) => '/api/kids-image?' + new URLSearchParams({[kind]: id, token: pageToken()});
  const clock = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? h + ' Std. ' + m + ' Min.' : m ? m + ' Min.' : ''; };
  const NAMES = {mediatheken: 'ARD, ZDF & Co.', netzkino: 'Netzkino', pluto: 'Pluto TV', justwatch: 'JustWatch TV', rakuten: 'Rakuten TV',
    youtube: 'YouTube', joyn: 'Joyn', toggo: 'TOGGO', crunchyroll: 'Crunchyroll', plex: 'Plex', servustv: 'ServusTV', redbulltv: 'Red Bull TV', dmax: 'DMAX, TLC & HGTV', rtlplus: 'RTL+', download: 'Offline'};
  const TABS = [['start', 'Startseite'], ['movies', 'Filme'], ['series', 'Serien'], ['live', 'Live-TV'], ['offline', 'Offline'], ['marked', 'Merkliste']];
  const PAGE = 48;
  const S = {tab: 'start', query: '', genre: '', home: null, watch: null, start: null, stations: null, grid: null, seq: 0, built: false, timer: 0};

  // ------------------------------------------------------------------ Vollbild
  // Im Ansehen-Modus geht beim ersten Abspielen die ganze Seite ins Vollbild (eine Geste des Nutzers ist
  // nötig, deshalb hier im Klick und nicht im Player). Der Player liegt darüber.
  const fullOn = () => !!(document.fullscreenElement || document.webkitFullscreenElement);
  // Gibt ein Promise zurück: erst nach dem Wechsel ins Vollbild öffnen, sonst legt sich die Seite
  // (Vollbild-Element) im Browser über den gerade geöffneten Player.
  function fullscreen(force) {
    if ((!MODE && !force) || fullOn()) return Promise.resolve();
    const el = document.documentElement, fn = el.requestFullscreen || el.webkitRequestFullscreen;
    if (!fn) return Promise.resolve();
    try {
      const p = fn.call(el);
      return p && p.then ? Promise.race([p.catch(() => {}), new Promise(r => setTimeout(r, 1500))]) : new Promise(r => setTimeout(r, 300));
    } catch (e) { return Promise.resolve(); }   // Safari auf dem iPhone kennt es nur für Videos
  }
  function toggleFull() {
    if (fullOn()) { const ex = document.exitFullscreen || document.webkitExitFullscreen; try { const p = ex && ex.call(document); if (p && p.catch) p.catch(() => {}); } catch (e) { /* egal */ } }
    else fullscreen(true);
  }
  const playerMissing = () => window.notice?.(window.atlasPlayerMissing?.('watch_mode') || 'Der Player ist nicht geladen; Seite neu laden.', 'error');

  // ------------------------------------------------------------------ Aktionen
  function openCatalog(item) {
    if (!window.AtlasCards?.open) { window.notice?.('Die Titelseite ist nicht geladen; Seite neu laden.', 'error'); return; }
    window.AtlasCards.open(item);
  }
  function resume(entry) {
    if (typeof window.playRef !== 'function') return playerMissing();
    if (!entry.ref || !Object.keys(entry.ref).length) { openEntry(entry); return; }
    fullscreen().then(() => window.playRef(entry.ref, entry.title, entry.key));
  }
  function openEntry(entry) {
    const o = entry.open || {}, id = o.id || String(entry.key || '').split(':').slice(1).join(':');
    if (entry.source && entry.source !== 'mediatheken' && entry.source !== 'download' && window.AtlasPortalTitle) {
      window.AtlasPortalTitle.open(entry.source, entry.source === 'netzkino' && entry.kind === 'series' && o.series_key ? o.series_key : id);
      return;
    }
    if (entry.ref && entry.ref.job) { playJobId(entry.ref.job, entry.title); return; }
    window.notice?.('„' + entry.title + '“ lässt sich hier nicht direkt öffnen; in der normalen Ansicht unter Dashboard → Merkliste.');
  }
  function playJobId(job, title) {
    if (typeof window.playRef !== 'function') return playerMissing();
    fullscreen().then(() => window.playRef({job}, title || 'Video', 'job:' + job));
  }
  function playStation(st) {
    const src = (st.sources || []).find(x => x.play);
    if (!src) { const link = (st.sources || [])[0]?.link; if (posterOkay(link)) window.open(window.AtlasDirect ? window.AtlasDirect.href(st.sources[0].provider, link) : link, '_blank', 'noopener'); return; }
    if (typeof window.playLive !== 'function') return playerMissing();
    fullscreen().then(() => window.playLive(src.play, st.name + ' · ' + src.provider_name));
  }

  // ------------------------------------------------------------------ Kacheln
  // shape: 'poster' (2:3, Filme/Serien) oder 'wide' (16:9, Videos, Sender, Offline)
  function tile(o) {
    const b = make('button', 'wm-tile wm-' + (o.shape || 'poster') + (o.done ? ' is-done' : ''));
    b.type = 'button';
    b.setAttribute('aria-label', [o.badge === 'NEU' ? 'Neu' : '', o.title, o.sub].filter(Boolean).join(', '));
    const art = make('span', 'wm-art');
    const fallback = make('span', 'wm-fallback', (o.title || '?').trim().slice(0, 40));
    art.append(fallback);
    if (o.image) {
      const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; img.referrerPolicy = 'no-referrer'; img.src = o.image;
      img.onload = () => fallback.remove(); img.onerror = () => img.remove(); art.append(img);
    }
    if (o.badge) art.append(make('span', 'wm-badge' + (o.badge === 'NEU' ? ' wm-new' : o.badge === 'LIVE' ? ' wm-live' : ''), o.badge));
    if (o.time) art.append(make('span', 'wm-time', o.time));
    if (o.progress > 0) { const bar = make('span', 'wm-progress'); const f = make('i'); f.style.width = Math.round(Math.min(1, o.progress) * 100) + '%'; bar.append(f); art.append(bar); }
    art.append(make('span', 'wm-hover', o.hover || '▶'));
    b.append(art, make('span', 'wm-name', o.title));
    if (o.sub) b.append(make('span', 'wm-sub', o.sub));
    b.onclick = o.action;
    return b;
  }
  const fromCatalog = item => tile({
    title: item.title, image: posterOkay(item.poster) ? item.poster : '', shape: 'poster', hover: 'ℹ',
    sub: [NAMES[item.source] || item.source, item.year, item.kind === 'series' || item.series_parent ? 'Serie' : null].filter(Boolean).join(' · '),
    action: () => openCatalog(item)});
  const fromContinue = e => tile({
    title: e.title, shape: 'wide', image: posterOkay(e.poster) ? e.poster : e.ref?.job ? local('job', e.ref.job) : '',
    sub: [NAMES[e.source] || '', e.duration ? 'noch ' + clock(e.duration - e.pos) : ''].filter(Boolean).join(' · '),
    progress: e.duration ? e.pos / e.duration : 0, action: () => resume(e)});
  const fromMarked = e => tile({
    title: e.title, shape: 'poster', image: posterOkay(e.poster) ? e.poster : '', hover: 'ℹ',
    sub: [NAMES[e.source] || '', e.year].filter(Boolean).join(' · '), action: () => openEntry(e)});
  const fromOffline = v => tile({
    title: v.title, shape: 'wide', image: v.local_poster ? local('job', v.job) : v.poster, badge: v.new ? 'NEU' : '',
    time: v.duration ? clock(v.duration) : '', done: v.done, progress: v.progress,
    sub: [NAMES[v.provider] || v.provider || 'Offline', v.year].filter(Boolean).join(' · '), action: () => playJobId(v.job, v.title)});
  const fromAbo = (v, channels) => tile({
    title: v.title, shape: 'wide', image: v.poster ? local('job', v.job) : '', badge: v.new ? 'NEU' : '',
    time: v.duration ? clock(v.duration) : '', done: v.done, progress: v.progress,
    sub: (channels.find(c => c.id === v.abo) || {}).name || 'YouTube-Abo', action: () => playJobId(v.job, v.title)});
  const fromStation = st => tile({
    title: st.name, shape: 'wide wm-station', image: posterOkay(st.logo) ? st.logo : '', badge: 'LIVE',
    sub: [st.group, (st.sources || []).map(s => s.provider_name).filter(Boolean).slice(0, 2).join(', ')].filter(Boolean).join(' · '),
    hover: (st.sources || []).some(s => s.play) ? '▶' : '↗', action: () => playStation(st)});

  // ------------------------------------------------------------------ Reihen und Raster
  function row(title, tiles, more) {
    if (!tiles.length) return null;
    const sec = make('section', 'wm-row');
    const head = make('div', 'wm-row-head');
    head.append(make('h2', '', title));
    if (more) { const m = make('button', 'wm-more', 'Alle ansehen ›'); m.type = 'button'; m.onclick = more; head.append(m); }
    const wrap = make('div', 'wm-strip-wrap');
    const strip = make('div', 'wm-strip'); strip.append(...tiles);
    const left = make('button', 'wm-arrow wm-left', '‹'), right = make('button', 'wm-arrow wm-right', '›');
    left.type = right.type = 'button'; left.setAttribute('aria-label', 'Zurückblättern'); right.setAttribute('aria-label', 'Weiterblättern');
    left.tabIndex = right.tabIndex = -1;
    left.onclick = () => strip.scrollBy({left: -strip.clientWidth * 0.85, behavior: 'smooth'});
    right.onclick = () => strip.scrollBy({left: strip.clientWidth * 0.85, behavior: 'smooth'});
    wrap.append(left, strip, right);
    sec.append(head, wrap);
    return sec;
  }
  function grid(title, tiles, note) {
    const sec = make('section', 'wm-grid-section');
    const h = make('h2', '', title); if (note) h.append(make('small', '', note));
    const g = make('div', 'wm-grid'); g.append(...tiles);
    sec.append(h, g);
    return sec;
  }
  function empty(text, hint) {
    const box = make('div', 'wm-empty'); box.append(make('p', '', text)); if (hint) box.append(make('small', '', hint)); return box;
  }

  // ------------------------------------------------------------------ Daten
  async function unified(kind, extra) {
    const q = new URLSearchParams({kind, sort: 'year', offset: '0', ...(extra || {})});
    const data = await call('unified?' + q);
    const rows = [];
    for (const entry of data.items || []) {
      const offers = (entry.offers || []).map(o => window.AtlasCards.rowOf(o.source, o.item));
      if (offers.length) rows.push({...offers[0], offers});
    }
    return {rows, data};
  }
  async function loadPersonal() {
    const [home, watch] = await Promise.all([call('watch-home').catch(() => null), call('watch').catch(() => null)]);
    if (home) S.home = home;
    if (watch) { S.watch = watch; try { window.AtlasPlayerSync?.(watch.progress); } catch (e) { /* egal */ } }
  }
  async function loadStations() {
    if (S.stations) return S.stations;
    try { const d = await call('live-tv'); S.stations = d.stations || []; } catch (e) { S.stations = []; }
    return S.stations;
  }
  function liveFavourites(list) {
    let favs = new Set();
    try { favs = new Set(JSON.parse(localStorage.getItem('atlas-live-favourites') || '[]')); } catch (e) { /* egal */ }
    return [...list.filter(s => favs.has(s.key)), ...list.filter(s => !favs.has(s.key))];
  }

  // ------------------------------------------------------------------ Kopf
  function header() {
    const top = make('header', 'wm-top');
    const brand = make('a', 'wm-brand'); brand.href = MODE ? '/ansehen' : '#';
    const icon = make('img'); icon.src = '/icon.svg'; icon.alt = ''; icon.width = 30; icon.height = 30;
    brand.append(icon, make('span', '', 'MediathekAtlas'));
    brand.onclick = e => { e.preventDefault(); setTab('start'); };
    const tabs = make('nav', 'wm-tabs'); tabs.setAttribute('aria-label', 'Bereiche');
    for (const [key, label] of TABS) {
      const b = make('button', 'wm-tab', label); b.type = 'button'; b.dataset.tab = key;
      b.setAttribute('aria-pressed', String(S.tab === key && !S.query));
      b.onclick = () => { S.query = ''; const f = $('wm-search'); if (f) f.value = ''; setTab(key); };
      tabs.append(b);
    }
    const tools = make('div', 'wm-tools');
    const search = make('input', 'wm-search'); search.id = 'wm-search'; search.type = 'search'; search.placeholder = 'Titel suchen'; search.value = S.query;
    search.setAttribute('aria-label', 'Filme und Serien suchen');
    search.oninput = () => { clearTimeout(S.timer); S.timer = setTimeout(() => { S.query = search.value.trim(); render(); }, 400); };
    const full = make('button', 'wm-icon', '⛶'); full.type = 'button'; full.title = 'Vollbild an/aus'; full.setAttribute('aria-label', 'Vollbild');
    full.onclick = toggleFull;
    const kids = make('a', 'wm-link', 'Kinderecke'); kids.href = '/kinder';
    const admin = make('a', 'wm-link wm-admin', 'Verwaltung'); admin.href = '/'; admin.title = 'Zur normalen Ansicht mit Plattformen, Downloads und Einstellungen';
    if (!MODE) { admin.removeAttribute('href'); admin.onclick = () => window.atlasShowView?.('discover'); admin.textContent = 'Dashboard'; }
    tools.append(search, full, kids, admin);
    top.append(brand, tabs, tools);
    return top;
  }
  function markTabs() {
    root.querySelectorAll('.wm-tab').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === S.tab && !S.query)));
  }

  // ------------------------------------------------------------------ Hero
  function hero(pick) {
    if (!pick) return null;
    const box = make('section', 'wm-hero');
    if (pick.image) { const bg = make('div', 'wm-hero-bg'); bg.style.backgroundImage = 'url("' + pick.image.replace(/"/g, '%22') + '")'; box.append(bg); }
    const text = make('div', 'wm-hero-text');
    text.append(make('p', 'wm-eyebrow', pick.eyebrow));
    text.append(make('h1', '', pick.title));
    if (pick.facts) text.append(make('p', 'wm-facts', pick.facts));
    if (pick.text) text.append(make('p', 'wm-plot', pick.text.length > 260 ? pick.text.slice(0, 257) + '…' : pick.text));
    if (pick.progress) { const bar = make('span', 'wm-progress wm-hero-progress'); const f = make('i'); f.style.width = Math.round(pick.progress * 100) + '%'; bar.append(f); text.append(bar); }
    const actions = make('div', 'wm-hero-actions');
    const play = make('button', 'wm-play', pick.playLabel || '▶ Abspielen'); play.type = 'button'; play.onclick = pick.play;
    actions.append(play);
    if (pick.info) { const info = make('button', 'wm-secondary', 'ℹ Mehr Infos'); info.type = 'button'; info.onclick = pick.info; actions.append(info); }
    text.append(actions);
    if (pick.image) { const art = make('img', 'wm-hero-poster'); art.alt = ''; art.src = pick.image; art.referrerPolicy = 'no-referrer'; art.onerror = () => art.remove(); box.append(art); }
    box.append(text);
    return box;
  }
  function heroPick(start) {
    const cont = (S.watch?.continue || [])[0];
    if (cont) return {eyebrow: 'Weiterschauen', title: cont.title, image: posterOkay(cont.poster) ? cont.poster : cont.ref?.job ? local('job', cont.ref.job) : '',
      facts: [NAMES[cont.source], cont.duration ? 'noch ' + clock(cont.duration - cont.pos) : ''].filter(Boolean).join(' · '),
      progress: cont.duration ? cont.pos / cont.duration : 0, playLabel: '▶ Fortsetzen', play: () => resume(cont), info: cont.source && cont.source !== 'download' ? () => openEntry(cont) : null};
    const abos = S.home?.abos || {videos: [], channels: []};
    const fresh = abos.videos.find(v => v.new);
    if (fresh) return {eyebrow: 'Neu aus deinen Abos · ' + ((abos.channels.find(c => c.id === fresh.abo) || {}).name || 'YouTube'), title: fresh.title,
      image: fresh.poster ? local('job', fresh.job) : '', facts: [clock(fresh.duration), 'offline gespeichert'].filter(Boolean).join(' · '), play: () => playJobId(fresh.job, fresh.title)};
    const film = (start?.movies || []).find(r => posterOkay(r.poster)) || (start?.movies || [])[0];
    if (film) return {eyebrow: 'Neu im Katalog · ' + (NAMES[film.source] || film.source), title: film.title, image: posterOkay(film.poster) ? film.poster : '',
      facts: [film.year, (film.genres || []).slice(0, 2).join(', '), film.offers && film.offers.length > 1 ? 'bei ' + film.offers.length + ' Anbietern' : NAMES[film.source]].filter(Boolean).join(' · '),
      text: film.description, playLabel: '▶ Ansehen', play: () => openCatalog(film), info: () => openCatalog(film)};
    return null;
  }

  // ------------------------------------------------------------------ Ansichten
  async function viewStart(main, seq) {
    if (!S.start) {
      const [movies, series] = await Promise.all([unified('movies').catch(() => null), unified('series').catch(() => null)]);
      S.start = {movies: movies?.rows || [], series: series?.rows || [], counts: movies?.data?.counts || {}, names: movies?.data?.names || {}, perSource: {}};
      // Je Anbieter mit Titeln eine eigene Reihe (höchstens acht, die größten zuerst).
      const sources = Object.entries(S.start.counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 8);
      await Promise.all(sources.map(async ([src]) => {
        try { S.start.perSource[src] = (await unified('movies', {only: src})).rows.slice(0, 30); } catch (e) { /* Reihe entfällt */ }
      }));
    }
    const stations = await loadStations();
    if (seq !== S.seq) return;
    const parts = [];
    parts.push(hero(heroPick(S.start)));
    const cont = S.watch?.continue || [];
    parts.push(row('Weiterschauen', cont.map(fromContinue)));
    const abos = S.home?.abos || {videos: [], channels: []};
    const fresh = abos.videos.filter(v => v.new);
    parts.push(row('Neu aus deinen Abos', fresh.slice(0, 30).map(v => fromAbo(v, abos.channels)), () => setTab('offline')));
    parts.push(row('Meine Merkliste', (S.watch?.marked || []).map(fromMarked), () => setTab('marked')));
    parts.push(row('Offline gespeichert', (S.home?.offline || []).slice(0, 30).map(fromOffline), () => setTab('offline')));
    parts.push(row('Live-TV', liveFavourites(stations).slice(0, 30).map(fromStation), () => setTab('live')));
    parts.push(row('Neue Filme', S.start.movies.slice(0, 30).map(fromCatalog), () => setTab('movies')));
    parts.push(row('Neue Serien', S.start.series.slice(0, 30).map(fromCatalog), () => setTab('series')));
    for (const [src, rows] of Object.entries(S.start.perSource)) parts.push(row('Filme bei ' + (S.start.names[src] || NAMES[src] || src), rows.map(fromCatalog), () => { S.genre = ''; S.only = src; setTab('movies'); }));
    for (const c of abos.channels.filter(c => c.videos)) {
      const own = abos.videos.filter(v => v.abo === c.id);
      parts.push(row(c.name, own.slice(0, 30).map(v => fromAbo(v, abos.channels))));
    }
    const shown = parts.filter(Boolean);
    if (shown.length < 2) shown.push(empty('Noch nichts zum Anschauen da.',
      'In der Verwaltung lassen sich die Kataloge der freien Dienste laden (Plattformen → Anbieter → „Jetzt laden“), YouTube-Kanäle abonnieren oder Titel offline speichern.'));
    main.replaceChildren(...shown);
  }
  async function viewCatalog(main, seq, kind) {
    const key = kind + '|' + (S.genre || '') + '|' + (S.only || '');
    if (!S.grid || S.grid.key !== key) {
      const extra = {}; if (S.genre) extra.genre = S.genre; if (S.only) extra.only = S.only;
      const res = await unified(kind, extra);
      S.grid = {key, rows: res.rows, total: Number(res.data.total || 0), offset: 0, genres: res.data.genre_counts || [], extra};
    }
    if (seq !== S.seq) return;
    const g = S.grid;
    const chips = make('div', 'wm-chips');
    const chip = (label, on, fn) => { const b = make('button', 'wm-chip', label); b.type = 'button'; b.setAttribute('aria-pressed', String(on)); b.onclick = fn; chips.append(b); };
    if (S.only) chip('Nur ' + (NAMES[S.only] || S.only) + ' ✕', true, () => { S.only = ''; render(); });
    chip('Alle Genres', !S.genre, () => { S.genre = ''; render(); });
    const genres = new Map();
    for (const c of g.genres) { const n = String(c.genre || '').trim(); if (n && !['Unklassifiziert', 'Sonstige', 'Unbekannt'].includes(n)) genres.set(n, (genres.get(n) || 0) + (Number(c.n) || 0)); }
    [...genres].sort((a, b) => b[1] - a[1]).slice(0, 18).forEach(([name]) => chip(name, S.genre === name, () => { S.genre = S.genre === name ? '' : name; render(); }));
    const title = (kind === 'series' ? 'Serien' : 'Filme') + (S.genre ? ' · ' + S.genre : '');
    const parts = [chips, g.rows.length ? grid(title, g.rows.map(fromCatalog), g.total + ' Titel, neueste zuerst') : empty('Keine Titel gefunden.', 'Die Kataloge der Anbieter werden in der Verwaltung geladen.')];
    if (g.offset + PAGE < g.total) {
      const more = make('button', 'wm-load', 'Mehr laden'); more.type = 'button';
      more.onclick = async () => {
        more.disabled = true; more.textContent = 'Wird geladen …';
        try {
          const res = await unified(kind, {...g.extra, offset: String(g.offset + PAGE)});
          g.offset += PAGE; g.rows.push(...res.rows); render();
        } catch (e) { more.disabled = false; more.textContent = 'Erneut versuchen'; }
      };
      parts.push(more);
    }
    main.replaceChildren(...parts);
  }
  async function viewLive(main, seq) {
    const stations = liveFavourites(await loadStations());
    if (seq !== S.seq) return;
    if (!stations.length) { main.replaceChildren(empty('Keine Live-Sender geladen.', 'In der normalen Ansicht unter Live-TV → „Aktualisieren“ bzw. „Samsung-TV-Plus-Sender laden“.')); return; }
    const groups = new Map();
    for (const st of stations) { const g = st.group || 'Weitere Sender'; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(st); }
    const parts = [grid('Live-TV', stations.slice(0, 24).map(fromStation), stations.length + ' Sender · Favoriten zuerst')];
    if (groups.size > 1) for (const [g, list] of groups) parts.push(row(g, list.map(fromStation)));
    main.replaceChildren(...parts.filter(Boolean));
  }
  function viewOffline(main) {
    const abos = S.home?.abos || {videos: [], channels: []};
    const parts = [
      (S.home?.offline || []).length ? grid('Offline gespeichert', S.home.offline.map(fromOffline), 'läuft auch ohne Internet') : null,
      abos.videos.length ? grid('Aus deinen YouTube-Abos', abos.videos.map(v => fromAbo(v, abos.channels)), abos.videos.filter(v => v.new).length + ' neu') : null].filter(Boolean);
    main.replaceChildren(...(parts.length ? parts : [empty('Noch keine Offline-Kopien.', 'Auf einer Titelseite „Offline speichern“ wählen oder unter Plattformen → YouTube einen Kanal abonnieren.')]));
  }
  function viewMarked(main) {
    const list = S.watch?.marked || [];
    main.replaceChildren(list.length ? grid('Meine Merkliste', list.map(fromMarked)) : empty('Die Merkliste ist leer.', 'Auf einer Titelseite „☆ Merken“ wählen.'));
  }
  async function viewSearch(main, seq) {
    const [m, s] = await Promise.all([unified('movies', {q: S.query, sort: 'title'}).catch(() => null), unified('series', {q: S.query, sort: 'title'}).catch(() => null)]);
    if (seq !== S.seq) return;
    const stations = (S.stations || []).filter(st => st.name.toLowerCase().includes(S.query.toLowerCase()));
    const parts = [m?.rows.length ? grid('Filme', m.rows.map(fromCatalog), m.data.total + ' Treffer') : null,
      s?.rows.length ? grid('Serien', s.rows.map(fromCatalog), s.data.total + ' Treffer') : null,
      stations.length ? grid('Live-Sender', stations.slice(0, 12).map(fromStation)) : null].filter(Boolean);
    main.replaceChildren(...(parts.length ? parts : [empty('Nichts gefunden für „' + S.query + '“.')]));
  }

  // ------------------------------------------------------------------ Aufbau
  function setTab(tab) {
    if (tab !== 'movies' && tab !== 'series') S.only = '';
    if (tab !== S.tab) S.genre = '';
    S.tab = tab; render(); window.scrollTo({top: 0});
  }
  async function render() {
    if (!S.built) { root.replaceChildren(header(), make('div', 'wm-main')); root.lastChild.id = 'wm-main'; S.built = true; }
    markTabs();
    const main = $('wm-main'), seq = ++S.seq;
    main.setAttribute('aria-busy', 'true');
    if (!main.childElementCount) main.append(make('p', 'wm-loading', 'Wird geladen …'));
    try {
      if (!S.home || !S.watch) await loadPersonal();
      if (seq !== S.seq) return;
      if (S.query) await viewSearch(main, seq);
      else if (S.tab === 'movies' || S.tab === 'series') await viewCatalog(main, seq, S.tab);
      else if (S.tab === 'live') await viewLive(main, seq);
      else if (S.tab === 'offline') viewOffline(main);
      else if (S.tab === 'marked') viewMarked(main);
      else await viewStart(main, seq);
    } catch (e) {
      if (seq === S.seq) main.replaceChildren(empty('Konnte nicht geladen werden: ' + e.message, 'Gleich noch einmal versuchen.'));
    } finally { if (seq === S.seq) main.setAttribute('aria-busy', 'false'); }
  }
  // Nach dem Schließen des Players (Fortschritt, „NEU“) die persönlichen Reihen auffrischen.
  async function refreshPersonal() {
    if (root.hidden) return;
    await loadPersonal();
    if (S.tab === 'start' || S.tab === 'offline' || S.tab === 'marked') render();
  }
  $('player')?.addEventListener('close', () => setTimeout(refreshPersonal, 800));

  function show() { if (!S.built || !$('wm-main')?.childElementCount) render(); else refreshPersonal(); }
  window.AtlasWatchMode = {show, refresh: () => { S.start = null; S.stations = null; S.grid = null; render(); }};

  if (MODE) {
    document.body.classList.add('watch-mode');
    window.atlasShowView?.('watch');
    setInterval(() => { if (!document.hidden && !root.hidden && !$('player')?.open) refreshPersonal(); }, 120000);
  }
})();
