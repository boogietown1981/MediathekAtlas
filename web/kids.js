/* 0.6.7 Kinderecke: fertig geladene Videos der YouTube-Abos (youtube_abos.kids), neue zuerst und mit
   „NEU“ markiert. Ein Tipp startet das Video im Vollbild; am Ende kommt nach 6 Sekunden das nächste
   Video desselben Kanals. Bilder liegen auf dem Server, die Seite braucht also kein Internet.
   Der Abspielstand geht wie im großen Player an /api/watch-progress (Schlüssel job:<id>).
   0.6.46: dazu Kinderfilme und Kinderserien aus dem Katalog (kids_catalog.py, nur Kategorie „Kinder“,
   nur ohne Kopierschutz im eigenen Player). Serien öffnen ihre Folgen in der Kinderecke; abgespielt
   wird über /api/kids-play, das nur Einträge dieser Liste annimmt.
   0.6.93: Gruppen (Märchen, Zeichentrick, Tiere & Natur, Wissen, Abenteuer, Lustiges, Noch mehr) als Reihen
   und als Bild-Chips oben.
   0.6.91: Pfeilknöpfe zum Blättern der Reihen, „Alle …“-Kachel am Ende gekürzter Reihen. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name=atlas-token]').content;
  const make = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const COLORS = ['#ff5d8f', '#ff9a3f', '#ffd23f', '#45d483', '#3fc4ff', '#6c5ce7', '#c56cf0', '#20bf6b', '#fd7272', '#4b7bec'];
  const state = {channels: [], videos: [], movies: [], series: [], groups: [], filter: 'all', show: null, episodes: [], current: null, list: [],
    nextTimer: 0, lastSent: 0, offset: 0, hls: null};

  async function api(path, data) {
    const r = await fetch('/api/' + path, data === undefined ? {headers: {'X-Atlas-Token': token}} :
      {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Atlas-Token': token}, body: JSON.stringify(data)});
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && d.login) { location.reload(); throw Error('Anmeldung abgelaufen'); }
    if (!r.ok) throw Error(d.error || 'Anfrage fehlgeschlagen');
    return d;
  }
  const image = (kind, id) => '/api/kids-image?' + new URLSearchParams({[kind]: id, token});
  const hash = text => { let h = 0; for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) | 0; return Math.abs(h); };
  const color = id => COLORS[(Number.isFinite(Number(id)) ? Math.abs(Number(id)) : hash(id)) % COLORS.length];
  const clock = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + x : m + ':' + x; };
  const channelOf = v => state.channels.find(c => c.id === v.abo) || {};
  // Ein Abo-Video wird zu einem abspielbaren Eintrag wie Filme und Folgen (ref, key, Bild).
  const fromAbo = v => Object.assign(v, {type: 'abo', ref: {job: v.job}, key: 'job:' + v.job, picture: v.poster ? image('job', v.job) : '', group: v.abo});
  // 0.6.93: die Gruppe des Servers (Märchen …) heißt hier theme; group bleibt die Abspielreihe (nextOf)
  const fromCatalog = (t, type) => Object.assign(t, {type, picture: t.poster || '', theme: t.group || 'mehr', group: type});

  // ------------------------------------------------------------ Auswahl oben
  function chip(id, name, opts) {
    const b = make('button', 'kids-chip'); b.type = 'button';
    b.setAttribute('aria-pressed', String(state.filter === id && !state.show));
    const face = make('span', 'kids-chip-face'); face.style.setProperty('--chip', opts.color);
    if (opts.avatar) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.src = opts.avatar; img.onerror = () => { img.remove(); face.textContent = opts.letter; }; face.append(img); }
    else face.textContent = opts.letter;
    if (opts.badge) face.append(make('span', 'kids-dot', String(opts.badge)));
    b.append(face, make('span', 'kids-chip-name', name));
    b.onclick = () => { state.filter = id; state.show = null; render(); window.scrollTo({top: 0, behavior: 'smooth'}); };
    return b;
  }
  let chipsWrapped = false;
  function renderChannels() {
    const host = $('kids-channels');
    if (!chipsWrapped) { chipsWrapped = true; const parent = host.parentNode, after = host.nextSibling; parent.insertBefore(scroller(host, 'kids-chips-scroller'), after); }
    host.replaceChildren();
    if (!state.videos.length && !state.movies.length && !state.series.length) return;
    const fresh = state.videos.filter(v => v.new).length;
    host.append(chip('all', 'Alle', {color: '#6c5ce7', letter: '★'}));
    if (fresh) host.append(chip('new', 'Neu', {color: '#ffd23f', letter: '✨', badge: fresh}));
    if (state.movies.length) host.append(chip('movies', 'Filme', {color: '#ff9a3f', letter: '🎬'}));
    if (state.series.length) host.append(chip('series', 'Serien', {color: '#3fc4ff', letter: '📺'}));
    // 0.6.93: Gruppen mit Bild-Symbol (Märchen, Zeichentrick, Tiere …), auch für Kinder, die noch nicht lesen
    for (const g of state.groups) host.append(chip('g:' + g.id, g.name, {color: color(g.id), letter: g.icon}));
    for (const c of state.channels.filter(c => c.videos))
      host.append(chip(c.id, c.name, {color: color(c.id), letter: (c.name || '?').trim().charAt(0).toUpperCase(), avatar: c.avatar ? image('abo', c.id) : '', badge: c.new}));
    if (host.kidsUpdate) requestAnimationFrame(host.kidsUpdate);
  }

  // ------------------------------------------------------------ Kacheln
  function thumb(v, tall) {
    const t = make('span', 'kids-thumb');
    if (v.picture) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = v.picture;
      img.onerror = () => { img.remove(); t.classList.add('no-picture'); }; t.append(img); }
    else t.classList.add('no-picture');
    if (tall && !v.picture) t.append(make('span', 'kids-letter', (v.title || '?').trim().charAt(0).toUpperCase()));
    return t;
  }
  function tile(v, list) {
    const tall = v.type === 'movie' || v.type === 'series';
    const b = make('button', 'kids-tile' + (tall ? ' is-poster' : '') + (v.done ? ' is-done' : '')); b.type = 'button';
    b.style.setProperty('--chip', color(v.type === 'abo' ? v.abo : v.id || v.title));
    const where = v.type === 'abo' ? channelOf(v).name || '' : v.type === 'series' ? 'Serie' : v.type === 'movie' ? 'Film' : '';
    b.setAttribute('aria-label', (v.new ? 'Neu: ' : '') + v.title + (where ? ', ' + where : ''));
    b.dataset.kind = v.type;
    const th = thumb(v, tall);
    th.append(make('span', 'kids-play', v.type === 'series' ? '☰' : '▶'));
    if (v.new) th.append(make('span', 'kids-new', 'NEU'));
    else if (v.done) th.append(make('span', 'kids-seen', '✓'));
    if (v.duration && v.type !== 'series') th.append(make('span', 'kids-time', clock(v.duration)));
    if (v.progress > 0) { const p = make('span', 'kids-progress'); const f = make('span'); f.style.width = Math.round(v.progress * 100) + '%'; p.append(f); th.append(p); }
    let label = v.title;
    if (v.type === 'episode' && v.episode != null) label = (v.season != null ? 'Staffel ' + v.season + ' · ' : '') + 'Folge ' + v.episode + ': ' + v.title;
    b.append(th, make('span', 'kids-title', label));
    b.onclick = () => (v.type === 'series' ? openSeries(v) : play(v, list));
    return b;
  }
  // 0.6.91 (Björn, 22.11.2026: „kann nicht weiter nach rechts scrollen“): Reihen lassen sich mit großen
  // Pfeilknöpfen blättern (Maus ohne Seitwärtsrad, Tastatur); am Ende einer gekürzten Reihe führt eine
  // „Alle …“-Kachel zur ganzen Liste.
  function scroller(box, cls) {
    const wrap = make('div', 'kids-scroller' + (cls ? ' ' + cls : ''));
    const arrow = (dir, label) => {
      const b = make('button', 'kids-arrow kids-arrow-' + (dir < 0 ? 'prev' : 'next'), dir < 0 ? '‹' : '›');
      b.type = 'button'; b.setAttribute('aria-label', label); b.tabIndex = -1;
      b.onclick = () => box.scrollBy({left: dir * Math.max(200, box.clientWidth * 0.85), behavior: 'smooth'});
      return b;
    };
    const prev = arrow(-1, 'Zurück blättern'), next = arrow(1, 'Weiter blättern');
    const update = () => {
      const max = box.scrollWidth - box.clientWidth;
      prev.hidden = box.scrollLeft <= 4; next.hidden = box.scrollLeft >= max - 4;
    };
    box.addEventListener('scroll', update, {passive: true});
    if (window.ResizeObserver) new ResizeObserver(update).observe(box); else window.addEventListener('resize', update);
    requestAnimationFrame(update); box.kidsUpdate = update;
    wrap.append(prev, box, next); return wrap;
  }
  function moreTile(n, filter, name) {
    const b = make('button', 'kids-tile kids-more is-poster'); b.type = 'button';
    b.setAttribute('aria-label', 'Alle ' + n + ' ' + name + ' anzeigen');
    const th = make('span', 'kids-thumb no-picture'); th.append(make('span', 'kids-letter', '→'));
    b.append(th, make('span', 'kids-title', 'Alle ' + n + ' ' + name));
    b.onclick = () => { state.filter = filter; state.show = null; render(); window.scrollTo({top: 0, behavior: 'smooth'}); };
    return b;
  }
  function row(title, note, list, grid, all, more) {
    const sec = make('section', 'kids-row'); const h = make('h2', '', title);
    if (note) h.append(make('small', '', note));
    const box = make('div', grid ? 'kids-grid' : 'kids-strip');
    if (list.some(v => v.type === 'movie' || v.type === 'series')) box.classList.add('is-posters');
    for (const v of list) box.append(tile(v, all || list));
    if (more) box.append(moreTile(more.n, more.filter, more.name));
    sec.append(h, grid ? box : scroller(box)); return sec;
  }
  const STRIP = 40;          // Kacheln je Reihe in „Alle“; der Rest über „Alle …“ bzw. die Auswahl oben
  const count = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  // 0.6.93: Filme und Serien in wenigen Gruppen statt einer langen Reihe (kids_catalog.GROUPS). Ohne Gruppen
  // (ältere Server) bleibt es bei einer Reihe „Filme“ bzw. „Serien“.
  const byTitle = list => list.sort((a, b) => String(a.title).localeCompare(String(b.title), 'de', {sensitivity: 'base'}));
  const inGroup = (list, id) => list.filter(v => (v.theme || 'mehr') === id);
  function grouped(main, list, what) {
    const cut = (n, filter) => (n > STRIP ? {n, filter, name: 'Titel'} : null);
    const groups = state.groups.length ? state.groups : [{id: 'mehr', name: what || 'Filme und Serien', icon: ''}];
    for (const g of groups) {
      const own = state.groups.length ? inGroup(list, g.id) : list;
      if (!own.length) continue;
      const title = (g.icon ? g.icon + ' ' : '') + g.name + (what && state.groups.length ? ' · ' + what : '');
      main.append(row(title, count(own.length, 'Titel', 'Titel'), own.slice(0, STRIP), false, own,
        state.groups.length ? cut(own.length, 'g:' + g.id) : cut(own.length, what === 'Serien' ? 'series' : 'movies')));
    }
  }
  function render() {
    renderChannels();
    const main = $('kids-main'); main.replaceChildren();
    if (state.show) { renderSeries(main); return; }
    if (!state.videos.length && !state.movies.length && !state.series.length) {
      const p = make('div', 'kids-empty'); p.append(make('span', 'big', '📺'), document.createTextNode('Hier ist noch nichts zum Anschauen.'));
      p.append(make('small', '', 'Für Eltern: In MediathekAtlas unter Plattformen → YouTube → „Kanal-Abos“ einen Kanal abonnieren. Fertig geladene Videos erscheinen dann hier, auch ohne Internet. Kinderfilme und Kinderserien aus dem Katalog erscheinen, sobald sie nach dem Abgleich eindeutig als „Kinder“ eingeordnet sind.'));
      main.append(p); return;
    }
    if (state.filter === 'new') { main.append(row('Neu für dich', '', state.videos.filter(v => v.new), true)); return; }
    if (state.filter === 'movies') { grouped(main, state.movies, 'Filme'); return; }
    if (state.filter === 'series') { grouped(main, state.series, 'Serien'); return; }
    if (state.filter.startsWith('g:')) {
      const g = state.groups.find(x => 'g:' + x.id === state.filter) || {name: '', icon: ''};
      const list = inGroup(byTitle([...state.movies, ...state.series]), g.id);
      main.append(row(g.icon + ' ' + g.name, count(list.length, 'Titel', 'Titel'), list, true)); return;
    }
    if (state.filter !== 'all') {
      const c = state.channels.find(x => x.id === state.filter);
      main.append(row(c ? c.name : 'Kanal', '', state.videos.filter(v => v.abo === state.filter), true)); return;
    }
    const fresh = state.videos.filter(v => v.new);
    if (fresh.length) main.append(row('Neu für dich', count(fresh.length, 'Video', 'Videos'), fresh.slice(0, 30)));
    const started = [...state.videos, ...state.movies].filter(v => v.progress > 0);
    if (started.length) main.append(row('Weiterschauen', '', started.slice(0, 20)));
    const cut = (n, filter, name) => (n > STRIP ? {n, filter, name} : null);
    grouped(main, byTitle([...state.movies, ...state.series]), '');
    for (const c of state.channels) {
      const own = state.videos.filter(v => v.abo === c.id);
      if (own.length) main.append(row(c.name, own.length + ' Videos', own.slice(0, STRIP), false, own, cut(own.length, c.id, 'Videos')));
    }
  }

  // ------------------------------------------------------------ Serie: Folgen in der Kinderecke
  async function openSeries(s) {
    state.show = s; state.episodes = []; render();
    window.scrollTo({top: 0, behavior: 'smooth'});
    try {
      const d = await api('kids-episodes?' + new URLSearchParams({source: s.source, series: (s.series || {}).show || (s.series || {}).id || ''}));
      if (state.show !== s) return;
      state.episodes = (d.episodes || []).map(e => fromCatalog(e, 'episode'));
      s.loaded = true;
    } catch (e) { if (state.show === s) { s.failed = e.message || 'Folgen lassen sich gerade nicht laden.'; } }
    if (state.show === s && $('kids-stage').hidden) render();
  }
  function renderSeries(main) {
    const s = state.show;
    const head = make('div', 'kids-series-head');
    const back = make('button', 'kids-round kids-back', '← Zurück'); back.type = 'button';
    back.onclick = () => { state.show = null; render(); };
    head.append(back, make('h2', '', s.title));
    main.append(head);
    if (s.failed && !state.episodes.length) { main.append(make('p', 'kids-empty', s.failed)); s.failed = ''; return; }
    if (!s.loaded) { main.append(make('p', 'kids-empty', 'Folgen werden geladen …')); return; }
    if (!state.episodes.length) { main.append(make('p', 'kids-empty', 'Gerade gibt es keine Folgen zum Anschauen.')); return; }
    main.append(row('Folgen', count(state.episodes.length, 'Folge', 'Folgen'), state.episodes, true));
  }

  async function load() {
    try {
      const d = await api('kids');
      state.channels = d.channels || []; state.videos = (d.videos || []).map(fromAbo);
      const cat = d.catalog || {};
      state.movies = (cat.movies || []).map(t => fromCatalog(t, 'movie'));
      state.series = (cat.series || []).map(t => fromCatalog(t, 'series'));
      state.groups = Array.isArray(cat.groups) ? cat.groups : [];
      if (cat.pending) setTimeout(load, 8000);   // der Katalog wird nach dem Start noch zusammengestellt
    }
    catch (e) { if (!state.videos.length && !state.movies.length) { $('kids-main').replaceChildren(make('p', 'kids-empty', 'Gerade nicht erreichbar. Gleich nochmal versuchen.')); } return; }
    if (!$('kids-stage').hidden) return;      // nicht während des Abspielens umbauen
    if (state.show && !state.series.some(s => s.id === state.show.id)) state.show = null;
    if (!['all', 'new', 'movies', 'series'].includes(state.filter) && !state.channels.some(c => c.id === state.filter)
        && !state.groups.some(g => 'g:' + g.id === state.filter)) state.filter = 'all';
    render();
  }

  // ------------------------------------------------------------ Abspielen im Vollbild
  const stage = $('kids-stage'), video = $('kids-video');
  function say(text) { const m = $('kids-stage-msg'); m.hidden = !text; m.textContent = text || ''; }
  function fullscreen() {
    const fs = stage.requestFullscreen || stage.webkitRequestFullscreen;
    if (fs) { try { const p = fs.call(stage); if (p && p.catch) p.catch(() => {}); return; } catch (e) { /* weiter unten */ } }
    if (video.webkitEnterFullscreen) { try { video.webkitEnterFullscreen(); } catch (e) { /* iPhone: erst nach dem Start */ } }
  }
  const position = () => state.offset + (video.currentTime || 0);
  function report(done) {
    const v = state.current; if (!v || !v.key) return;
    const total = v.duration || (Number.isFinite(video.duration) ? video.duration : 0);
    if (!total) return;
    state.lastSent = Date.now();
    const pos = position();
    api('watch-progress', {key: v.key, pos, duration: total, done: !!done,
      info: {title: v.title, source: v.type === 'abo' ? 'download' : v.source, kind: v.type === 'episode' ? 'episode' : 'movie', ref: v.ref}}).then(r => {
      if (r && r.stored) { v.new = false; v.done = !!r.done; v.progress = r.done ? 0 : pos / total; v.pos = r.done ? 0 : pos; }
    }).catch(() => {});
  }
  function stopHls() { if (state.hls) { try { state.hls.destroy(); } catch (e) { /* egal */ } state.hls = null; } }
  function loadHls() {
    if (window.Hls) return Promise.resolve(window.Hls);
    return new Promise(resolve => { const s = document.createElement('script'); s.src = '/hls.min.js'; s.onload = () => resolve(window.Hls || null); s.onerror = () => resolve(null); document.head.append(s); });
  }
  async function play(v, list) {
    clearNext(); stopHls();
    state.current = v; state.list = list || state.list || []; state.offset = 0;
    stage.hidden = false; say('Wird geladen …'); fullscreen();
    document.body.style.overflow = 'hidden';
    const resume = v.pos > 20 && !v.done ? v.pos : 0;
    try {
      const info = await api('kids-play?' + new URLSearchParams(v.ref));
      if (state.current !== v) return;
      if (!v.duration && info.duration) v.duration = Math.round(info.duration);
      const remux = t => { state.offset = t; video.src = info.remux + '&' + new URLSearchParams({t: String(Math.floor(t)), session: Math.random().toString(36).slice(2), token}); };
      const seekTo = t => { if (t) video.addEventListener('loadedmetadata', () => { try { video.currentTime = t; } catch (e) { /* egal */ } }, {once: true}); };
      if (info.mode === 'direct') {
        // eigene Adressen brauchen den Seitenschlüssel, Dateien des Senders nicht
        video.src = info.src.startsWith('/') ? info.src + '&token=' + encodeURIComponent(token) : info.src; seekTo(resume);
      } else if (info.hls && info.url) {
        const H = await loadHls();
        if (state.current !== v) return;
        if (H && H.isSupported()) {
          const hls = new H({startPosition: resume || -1}); state.hls = hls;
          hls.on(H.Events.ERROR, (e, d) => { if (state.hls === hls && d && d.fatal) { stopHls(); if (info.ffmpeg) { remux(position()); video.play().catch(() => {}); } else say('Dieses Video lässt sich gerade nicht abspielen.'); } });
          hls.loadSource(info.url); hls.attachMedia(video);
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) { video.src = info.url; seekTo(resume); }
        else if (info.ffmpeg) remux(resume);
        else throw Error('Dieses Video lässt sich hier nicht abspielen.');
      } else if (info.remux) remux(resume);
      else throw Error('Dieses Video lässt sich gerade nicht abspielen.');
      await video.play().catch(() => say('Zum Starten auf ▶ tippen'));
    } catch (e) { say(e.message || 'Video lässt sich gerade nicht abspielen'); }
  }
  function close() {
    if (state.current && video.currentTime > 0) report(video.ended);
    clearNext(); stopHls(); video.pause(); video.removeAttribute('src'); video.load();
    stage.hidden = true; state.current = null; state.offset = 0; document.body.style.overflow = '';
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if ((document.fullscreenElement || document.webkitFullscreenElement) && exit) { try { const p = exit.call(document); if (p && p.catch) p.catch(() => {}); } catch (e) { /* egal */ } }
    render(); load();
  }
  function nextOf(v) {
    if (v.type === 'movie') return null;        // nach einem Film geht es zurück zur Übersicht
    const list = (state.list || []).filter(x => x.type === v.type && x.group === v.group);
    const i = list.findIndex(x => x === v || (x.key && x.key === v.key));
    if (v.type === 'episode') return list[i + 1] || null;
    // erst ungesehene desselben Kanals, sonst das nächste in der Liste
    return list.slice(i + 1).find(x => !x.done) || list.slice(0, i).find(x => !x.done && x.new) || list[i + 1] || null;
  }
  function clearNext() { clearTimeout(state.nextTimer); $('kids-next').hidden = true; $('kids-next-fill').classList.remove('run'); }
  function offerNext() {
    const n = state.current && nextOf(state.current);
    if (!n) { setTimeout(close, 1500); return; }
    $('kids-next-title').textContent = n.title;
    const img = $('kids-next-img'); if (n.picture) img.src = n.picture; else img.removeAttribute('src');
    $('kids-next').hidden = false;
    const fill = $('kids-next-fill'); fill.classList.remove('run'); void fill.offsetWidth; fill.classList.add('run');
    $('kids-next-play').onclick = () => play(n, state.list);
    $('kids-next-play').focus();
    state.nextTimer = setTimeout(() => play(n, state.list), 6000);
  }
  video.addEventListener('playing', () => say(''));
  video.addEventListener('waiting', () => say('Lädt …'));
  video.addEventListener('timeupdate', () => { if (Date.now() - state.lastSent > 10000 && position() > 20) report(false); });
  video.addEventListener('pause', () => { if (!video.ended && position() > 20) report(false); });
  video.addEventListener('ended', () => { report(true); offerNext(); });
  video.addEventListener('error', () => { if (video.getAttribute('src') && !state.hls) say('Dieses Video lässt sich nicht abspielen.'); });
  $('kids-close').onclick = close;
  $('kids-next-stop').onclick = close;
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !stage.hidden) close(); });
  // Verlässt das Gerät den Vollbildmodus (Wischgeste, Esc), bleibt das Video im Fenster; „✕“ schließt.
  let idle = 0;
  const wake = () => { stage.classList.remove('idle'); clearTimeout(idle); idle = setTimeout(() => { if (!video.paused) stage.classList.add('idle'); }, 3000); };
  ['mousemove', 'touchstart', 'click'].forEach(ev => stage.addEventListener(ev, wake, {passive: true}));
  video.addEventListener('play', wake);

  // ------------------------------------------------------------ Elternbereich: 2 Sekunden halten
  const parents = $('kids-parents'); let hold = 0;
  const start = e => { e.preventDefault(); parents.classList.add('holding'); hold = setTimeout(() => { location.href = '/'; }, 2000); };
  const stop = () => { parents.classList.remove('holding'); clearTimeout(hold); };
  parents.addEventListener('pointerdown', start); ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => parents.addEventListener(ev, stop));
  parents.addEventListener('click', e => e.preventDefault());
  parents.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { if (!hold || !parents.classList.contains('holding')) start(e); } });
  parents.addEventListener('keyup', stop);

  load();
  setInterval(load, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
})();
