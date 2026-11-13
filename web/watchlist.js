/* 0.5.81: Merkliste and "Weiterschauen" (from HomeTube: favourite, pinned, last watched).
   The server keeps them (watch_state.py), so every browser and device of this MediathekAtlas
   shows the same list. This file
   - adds the "Merken" switch to every film and series tile (window.AtlasWatch.button),
   - shows "Weiterschauen" and "Merkliste" above the dashboard catalogue,
   - hands the positions known to the server to the player (window.AtlasPlayerSync). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = String(value);
    if (cls) n.className = cls;
    return n;
  };
  const KEY = /^[A-Za-z0-9_.:\-]{1,200}$/;
  const SOURCE_LABEL = {mediatheken: 'ARD, ZDF & Co.', netzkino: 'Netzkino', pluto: 'Pluto TV', justwatch: 'JustWatch TV',
    rakuten: 'Rakuten TV', youtube: 'YouTube', joyn: 'Joyn', download: 'Download'};
  const KIND_LABEL = {movie: 'Film', series: 'Serie', episode: 'Folge', music: 'Musik'};
  let state = {continue: [], marked: [], progress: {}, marks: {}};
  const buttons = new Set();   // live "Merken" buttons, repainted when a mark changes
  let timer = 0;
  const fmt = s => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + x : m + ':' + x;
  };
  const posterOkay = v => typeof v === 'string' && /^https:\/\/[a-z0-9.-]+\//i.test(v) && !/[\s<>'"]/.test(v);

  // The same key the player uses for its positions: '<plattform>:<id>', the work id for ARD, ZDF & Co.
  function keyOf(item) {
    if (!item || !item.id) return '';
    const key = item.source === 'mediatheken' ? String(item.id) : item.source + ':' + item.id;
    return KEY.test(key) ? key : '';
  }
  function infoOf(item) {
    const raw = item.raw || {};
    return {title: item.title || '', source: item.source || '',
      kind: item.series_parent || item.kind === 'series' ? 'series' : item.kind === 'episode' ? 'episode' : 'movie',
      year: Number(item.year) || null, poster: posterOkay(item.poster) ? item.poster : '',
      open: {id: String(item.id || ''), series_key: item.series_key || '', show_key: raw.show_key || '',
        work_id: raw.work_id || '', series_parent: !!item.series_parent}};
  }
  const marked = key => !!(state.marks[key] && state.marks[key].favorite);
  function paintButton(b) {
    const on = marked(b.dataset.watchKey);
    b.textContent = on ? '★ Gemerkt' : '☆ Merken';
    b.title = on ? 'Von der Merkliste nehmen' : 'Auf die Merkliste setzen';
    b.setAttribute('aria-pressed', String(on));
    b.classList.toggle('on', on);
  }
  function repaintButtons() {
    for (const b of [...buttons]) { if (!b.isConnected) buttons.delete(b); else paintButton(b); }
  }
  function button(item) {
    const key = keyOf(item);
    if (!key) return null;
    const b = el('button', '', 'atlas-watch-mark');
    b.type = 'button'; b.dataset.watchKey = key;
    paintButton(b);
    b.onclick = async event => {
      event.stopPropagation();
      b.disabled = true;
      try { await setMark(key, {favorite: !marked(key)}, infoOf(item)); }
      catch (e) { window.notice?.('Merkliste: ' + e.message, 'error'); }
      finally { b.disabled = false; }
    };
    buttons.add(b);
    return b;
  }
  async function setMark(key, change, info) {
    const result = await window.api('watch-mark', {key, ...change, info});
    state.marks[key] = {favorite: result.favorite, pinned: result.pinned};
    repaintButtons();
    await load();
    return result;
  }

  // Opens the title page of an entry of the Merkliste.
  async function openEntry(entry) {
    const o = entry.open || {}, id = o.id || entry.key.split(':').slice(1).join(':');
    if (entry.source && entry.source !== 'mediatheken' && entry.source !== 'download') {
      if (!window.AtlasPortalTitle) { window.notice?.('Die Titelseite ist nicht geladen; Seite neu laden.', 'error'); return; }
      window.AtlasPortalTitle.open(entry.source, entry.source === 'netzkino' && entry.kind === 'series' && o.series_key ? o.series_key : id);
      return;
    }
    if (o.series_parent && o.show_key && typeof openShow === 'function') { openShow(o.show_key); return; }
    // ARD, ZDF & Co.: the title page needs the catalogue entry; look it up by title and work id.
    try {
      const data = await window.api('catalog?' + new URLSearchParams({query: entry.title, downloaded: 'all', kind: entry.kind === 'movie' ? 'movie' : entry.kind === 'series' || entry.kind === 'episode' ? 'series' : ''}));
      const hit = (data.items || []).find(x => x.work_id === entry.key || x.work_id === o.work_id);
      if (hit && typeof openTitle === 'function') openTitle(hit);
      else window.notice?.('„' + entry.title + '“ steht derzeit nicht im Katalog der Mediatheken.');
    } catch (e) { window.notice?.('Titel konnte nicht geöffnet werden: ' + e.message, 'error'); }
  }
  function resume(entry) {
    if (typeof window.playRef !== 'function') { window.notice?.(window.atlasPlayerMissing?.() || 'Der Player ist nicht geladen; Seite neu laden.', 'error'); return; }
    if (!entry.ref || !Object.keys(entry.ref).length) { openEntry(entry); return; }
    window.playRef(entry.ref, entry.title, entry.key);
  }

  function tile(entry, mode) {
    const card = el('article', undefined, 'atlas-watch-tile');
    const art = el('div', undefined, 'atlas-watch-art');
    if (posterOkay(entry.poster)) { const img = el('img'); img.src = entry.poster; img.loading = 'lazy'; img.alt = ''; img.referrerPolicy = 'no-referrer'; art.append(img); }
    else art.append(el('span', (entry.title || '?').slice(0, 1).toUpperCase()));
    const text = el('div', undefined, 'atlas-watch-text');
    text.append(el('small', [SOURCE_LABEL[entry.source], KIND_LABEL[entry.kind], entry.year].filter(Boolean).join(' · ')));
    text.append(el('strong', entry.title));
    const actions = el('div', undefined, 'atlas-watch-actions');
    if (mode === 'continue') {
      const share = entry.duration ? Math.min(100, Math.round(entry.pos / entry.duration * 100)) : 0;
      const bar = el('div', undefined, 'atlas-watch-bar'); const fill = el('i'); fill.style.width = share + '%'; bar.append(fill);
      bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100'); bar.setAttribute('aria-valuenow', String(share));
      text.append(bar, el('span', fmt(entry.pos) + (entry.duration ? ' von ' + fmt(entry.duration) : '') + ' gesehen', 'muted'));
      const go = el('button', '▶ Fortsetzen', 'primary'); go.type = 'button'; go.onclick = () => resume(entry);
      const drop = el('button', 'Entfernen'); drop.type = 'button'; drop.title = 'Aus „Weiterschauen“ entfernen; der Titel selbst bleibt';
      drop.onclick = async () => {
        drop.disabled = true;
        try { await window.api('watch-forget', {key: entry.key}); try { localStorage.removeItem('atlas-play:' + entry.key); } catch {} await load(); }
        catch (e) { window.notice?.(e.message, 'error'); drop.disabled = false; }
      };
      actions.append(go, drop);
    } else {
      const open = el('button', 'Öffnen', 'primary'); open.type = 'button'; open.onclick = () => openEntry(entry);
      const drop = el('button', 'Entfernen'); drop.type = 'button'; drop.title = 'Von der Merkliste nehmen';
      drop.onclick = async () => {
        drop.disabled = true;
        try { await setMark(entry.key, {favorite: false}, null); }
        catch (e) { window.notice?.(e.message, 'error'); drop.disabled = false; }
      };
      actions.append(open, drop);
    }
    text.append(actions);
    card.append(art, text);
    return card;
  }

  function host() {
    let box = $('atlas-watch');
    if (box) return box;
    const discover = $('discover');
    if (!discover) return null;
    box = el('section'); box.id = 'atlas-watch'; box.hidden = true; box.setAttribute('aria-label', 'Weiterschauen und Merkliste');
    for (const [id, label] of [['continue', 'Weiterschauen'], ['marked', 'Merkliste']]) {
      const group = el('details', undefined, 'atlas-watch-group'); group.id = 'atlas-watch-' + id;
      let open = id === 'continue';
      try { const saved = localStorage.getItem('atlas-watch-open:' + id); if (saved !== null) open = saved === '1'; } catch {}
      group.open = open;
      group.addEventListener('toggle', () => { try { localStorage.setItem('atlas-watch-open:' + id, group.open ? '1' : '0'); } catch {} });
      const summary = el('summary'); summary.append(el('strong', label), el('span', '', 'atlas-watch-count'));
      group.append(summary, el('div', undefined, 'atlas-watch-row'));
      box.append(group);
    }
    discover.prepend(box);
    return box;
  }
  function render() {
    const box = host();
    if (!box) return;
    let any = false;
    for (const id of ['continue', 'marked']) {
      const group = $('atlas-watch-' + id), rows = state[id] || [];
      group.hidden = !rows.length; any = any || rows.length > 0;
      group.querySelector('.atlas-watch-count').textContent = rows.length ? String(rows.length) : '';
      group.querySelector('.atlas-watch-row').replaceChildren(...rows.map(r => tile(r, id)));
    }
    box.hidden = !any;
  }
  async function load() {
    let data;
    try { data = await window.api('watch'); }
    catch (e) { console.warn('MediathekAtlas: Merkliste nicht geladen', e); return; }
    state = {continue: data.continue || [], marked: data.marked || [], progress: data.progress || {}, marks: data.marks || {}};
    try { window.AtlasPlayerSync?.(state.progress); } catch (e) { console.warn(e); }
    render(); repaintButtons();
  }
  // The player reports every ten seconds; one reload shortly after the last report is enough.
  function changed() { clearTimeout(timer); timer = setTimeout(() => load(), 1500); }

  window.AtlasWatch = {button, changed, reload: load, keyOf, marks: () => state.marks,
    setPinned: (key, pinned, info) => setMark(key, {pinned}, info)};
  document.addEventListener('atlas-view', e => { if (e.detail && e.detail.view === 'discover') load(); });
  load();
})();
