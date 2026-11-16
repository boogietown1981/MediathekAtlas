/* 0.6.7 Kinderecke: fertig geladene Videos der YouTube-Abos (youtube_abos.kids), neue zuerst und mit
   „NEU“ markiert. Ein Tipp startet das Video im Vollbild; am Ende kommt nach 6 Sekunden das nächste
   Video desselben Kanals. Bilder liegen auf dem Server, die Seite braucht also kein Internet.
   Der Abspielstand geht wie im großen Player an /api/watch-progress (Schlüssel job:<id>). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name=atlas-token]').content;
  const make = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const COLORS = ['#ff5d8f', '#ff9a3f', '#ffd23f', '#45d483', '#3fc4ff', '#6c5ce7', '#c56cf0', '#20bf6b', '#fd7272', '#4b7bec'];
  const state = {channels: [], videos: [], filter: 'all', current: null, timer: 0, nextTimer: 0, lastSent: 0};

  async function api(path, data) {
    const r = await fetch('/api/' + path, data === undefined ? {headers: {'X-Atlas-Token': token}} :
      {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Atlas-Token': token}, body: JSON.stringify(data)});
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && d.login) { location.reload(); throw Error('Anmeldung abgelaufen'); }
    if (!r.ok) throw Error(d.error || 'Anfrage fehlgeschlagen');
    return d;
  }
  const image = (kind, id) => '/api/kids-image?' + new URLSearchParams({[kind]: id, token});
  const color = id => COLORS[Math.abs(Number(id) || 0) % COLORS.length];
  const clock = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + x : m + ':' + x; };
  const channelOf = v => state.channels.find(c => c.id === v.abo) || {};

  // ------------------------------------------------------------ Kanäle oben
  function chip(id, name, opts) {
    const b = make('button', 'kids-chip'); b.type = 'button';
    b.setAttribute('aria-pressed', String(state.filter === id));
    const face = make('span', 'kids-chip-face'); face.style.setProperty('--chip', opts.color);
    if (opts.avatar) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.src = opts.avatar; img.onerror = () => { img.remove(); face.textContent = opts.letter; }; face.append(img); }
    else face.textContent = opts.letter;
    if (opts.badge) face.append(make('span', 'kids-dot', String(opts.badge)));
    b.append(face, make('span', 'kids-chip-name', name));
    b.onclick = () => { state.filter = id; render(); window.scrollTo({top: 0, behavior: 'smooth'}); };
    return b;
  }
  function renderChannels() {
    const host = $('kids-channels'); host.replaceChildren();
    if (!state.videos.length) return;
    const fresh = state.videos.filter(v => v.new).length;
    host.append(chip('all', 'Alle', {color: '#6c5ce7', letter: '★'}));
    if (fresh) host.append(chip('new', 'Neu', {color: '#ffd23f', letter: '✨', badge: fresh}));
    for (const c of state.channels.filter(c => c.videos))
      host.append(chip(c.id, c.name, {color: color(c.id), letter: (c.name || '?').trim().charAt(0).toUpperCase(), avatar: c.avatar ? image('abo', c.id) : '', badge: c.new}));
  }

  // ------------------------------------------------------------ Kacheln
  function tile(v) {
    const b = make('button', 'kids-tile' + (v.done ? ' is-done' : '')); b.type = 'button';
    b.style.setProperty('--chip', color(v.abo));
    b.setAttribute('aria-label', (v.new ? 'Neu: ' : '') + v.title + ', ' + (channelOf(v).name || ''));
    const thumb = make('span', 'kids-thumb');
    if (v.poster) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.src = image('job', v.job); img.onerror = () => img.remove(); thumb.append(img); }
    thumb.append(make('span', 'kids-play', '▶'));
    if (v.new) thumb.append(make('span', 'kids-new', 'NEU'));
    else if (v.done) thumb.append(make('span', 'kids-seen', '✓'));
    if (v.duration) thumb.append(make('span', 'kids-time', clock(v.duration)));
    if (v.progress > 0) { const p = make('span', 'kids-progress'); const f = make('span'); f.style.width = Math.round(v.progress * 100) + '%'; p.append(f); thumb.append(p); }
    b.append(thumb, make('span', 'kids-title', v.title));
    b.onclick = () => play(v);
    return b;
  }
  function row(title, note, list, grid) {
    const sec = make('section', 'kids-row'); const h = make('h2', '', title);
    if (note) h.append(make('small', '', note));
    const box = make('div', grid ? 'kids-grid' : 'kids-strip');
    for (const v of list) box.append(tile(v));
    sec.append(h, box); return sec;
  }
  function render() {
    renderChannels();
    const main = $('kids-main'); main.replaceChildren();
    if (!state.videos.length) {
      const p = make('div', 'kids-empty'); p.append(make('span', 'big', '📺'), document.createTextNode('Hier ist noch nichts zum Anschauen.'));
      p.append(make('small', '', 'Für Eltern: In MediathekAtlas unter Plattformen → YouTube → „Kanal-Abos“ einen Kanal abonnieren. Fertig geladene Videos erscheinen dann hier, auch ohne Internet.'));
      main.append(p); return;
    }
    if (state.filter === 'new') { main.append(row('Neu für dich', '', state.videos.filter(v => v.new), true)); return; }
    if (state.filter !== 'all') {
      const c = state.channels.find(x => x.id === state.filter);
      main.append(row(c ? c.name : 'Kanal', '', state.videos.filter(v => v.abo === state.filter), true)); return;
    }
    const fresh = state.videos.filter(v => v.new);
    if (fresh.length) main.append(row('Neu für dich', fresh.length + (fresh.length === 1 ? ' Video' : ' Videos'), fresh.slice(0, 30)));
    const started = state.videos.filter(v => v.progress > 0);
    if (started.length) main.append(row('Weiterschauen', '', started.slice(0, 20)));
    for (const c of state.channels) {
      const own = state.videos.filter(v => v.abo === c.id);
      if (own.length) main.append(row(c.name, own.length + ' Videos', own.slice(0, 40)));
    }
  }
  async function load() {
    try { const d = await api('kids'); state.channels = d.channels || []; state.videos = d.videos || []; }
    catch (e) { if (!state.videos.length) { $('kids-main').replaceChildren(make('p', 'kids-empty', 'Gerade nicht erreichbar. Gleich nochmal versuchen.')); } return; }
    if (!$('kids-stage').hidden) return;      // nicht während des Abspielens umbauen
    if (state.filter !== 'all' && state.filter !== 'new' && !state.channels.some(c => c.id === state.filter)) state.filter = 'all';
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
  function report(done) {
    const v = state.current; if (!v || !video.duration) return;
    state.lastSent = Date.now();
    api('watch-progress', {key: 'job:' + v.job, pos: video.currentTime, duration: video.duration, done: !!done,
      info: {title: v.title, source: 'download', kind: 'movie', ref: {job: v.job}}}).then(r => {
      if (r && r.stored) { v.new = false; v.done = !!r.done; v.progress = r.done ? 0 : video.currentTime / video.duration; v.pos = r.done ? 0 : video.currentTime; }
    }).catch(() => {});
  }
  async function play(v) {
    clearNext();
    state.current = v; stage.hidden = false; say('Wird geladen …'); fullscreen();
    document.body.style.overflow = 'hidden';
    try {
      const info = await api('play?' + new URLSearchParams({job: v.job}));
      if (state.current !== v) return;
      const src = info.mode === 'direct' ? info.src + '&token=' + encodeURIComponent(token)
        : info.remux + '&' + new URLSearchParams({t: '0', session: Math.random().toString(36).slice(2), token});
      video.src = src;
      if (info.mode === 'direct' && v.pos > 20 && !v.done) video.addEventListener('loadedmetadata', () => { try { video.currentTime = v.pos; } catch (e) { /* egal */ } }, {once: true});
      await video.play().catch(() => say('Zum Starten auf ▶ tippen'));
    } catch (e) { say(e.message || 'Video lässt sich gerade nicht abspielen'); }
  }
  function close() {
    if (state.current && video.currentTime > 0) report(video.ended);
    clearNext(); video.pause(); video.removeAttribute('src'); video.load();
    stage.hidden = true; state.current = null; document.body.style.overflow = '';
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if ((document.fullscreenElement || document.webkitFullscreenElement) && exit) { try { const p = exit.call(document); if (p && p.catch) p.catch(() => {}); } catch (e) { /* egal */ } }
    render(); load();
  }
  function nextOf(v) {
    const list = state.videos.filter(x => x.abo === v.abo);
    const i = list.findIndex(x => x.job === v.job);
    // erst ungesehene desselben Kanals, sonst das nächste in der Liste
    return list.slice(i + 1).find(x => !x.done) || list.slice(0, i).find(x => !x.done && x.new) || list[i + 1] || null;
  }
  function clearNext() { clearTimeout(state.nextTimer); $('kids-next').hidden = true; $('kids-next-fill').classList.remove('run'); }
  function offerNext() {
    const n = state.current && nextOf(state.current);
    if (!n) { setTimeout(close, 1500); return; }
    $('kids-next-title').textContent = n.title;
    $('kids-next-img').src = n.poster ? image('job', n.job) : '';
    $('kids-next').hidden = false;
    const fill = $('kids-next-fill'); fill.classList.remove('run'); void fill.offsetWidth; fill.classList.add('run');
    $('kids-next-play').onclick = () => play(n);
    $('kids-next-play').focus();
    state.nextTimer = setTimeout(() => play(n), 6000);
  }
  video.addEventListener('playing', () => say(''));
  video.addEventListener('waiting', () => say('Lädt …'));
  video.addEventListener('timeupdate', () => { if (Date.now() - state.lastSent > 10000 && video.currentTime > 20) report(false); });
  video.addEventListener('pause', () => { if (!video.ended && video.currentTime > 20) report(false); });
  video.addEventListener('ended', () => { report(true); offerNext(); });
  video.addEventListener('error', () => { if (video.getAttribute('src')) say('Dieses Video lässt sich nicht abspielen.'); });
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
