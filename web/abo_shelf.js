/* 0.6.27/0.6.37 · YouTube-Abos im Dashboard (Björn, 19.11.2026): die abonnierten Videos, gegliedert je Kanal.
   0.6.37: kein eigener Bereich mehr, sondern Unteransicht „Abos“ der Quelle YouTube (neben Filme, Serien,
   Musikvideos), so wie Live-TV bei den Plattformen. Je Kanal: Stand der letzten Prüfung, Warteschlange,
   Fehler; Filter nach Profil, „nur neue“ und Suche.
   Daten: /api/youtube-abo-videos (youtube_abos.library), Bilder lokal über /api/kids-image,
   Wiedergabe im gemeinsamen Player (window.playRef, Abspielstand „job:<id>“ wie Kinderecke und
   Ansehen-Modus). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const discover = $('discover'), content = $('atlas-source-content');
  if (!discover || !content) return;
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined && text !== null) n.textContent = text; if (cls) n.className = cls; return n; };
  const pageToken = () => (typeof token === 'string' ? token : document.querySelector('meta[name=atlas-token]')?.content || '');
  const image = job => '/api/kids-image?' + new URLSearchParams({job, token: pageToken()});
  const avatar = abo => '/api/kids-image?' + new URLSearchParams({abo, token: pageToken()});
  const num = n => Number(n || 0).toLocaleString('de-DE');
  const when = t => t ? new Date(t * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
  const day = iso => { const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(iso || ''); return m ? m[3] + '.' + m[2] + '.' + m[1] : ''; };
  const clock = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60; return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0') : m + ':' + String(r).padStart(2, '0'); };

  const host = make('section', undefined, 'abs-shelf');
  host.id = 'atlas-abo-shelf'; host.hidden = true; host.setAttribute('aria-label', 'Videos aus deinen YouTube-Abos');
  const anchor = $('atlas-cross-categories');
  if (anchor && anchor.parentElement === content) content.insertBefore(host, anchor); else content.append(host);

  let mode = 'off', data = null, timer = 0, seq = 0, profile = 'all', onlyNew = false, query = '';

  function play(v) {
    if (typeof window.playRef !== 'function') { window.notice?.(window.atlasPlayerMissing?.('abo_shelf') || 'Der Player ist nicht geladen; Seite neu laden.', 'error'); return; }
    window.playRef({job: v.job}, v.title || 'Video', 'job:' + v.job);
  }
  function tile(v) {
    const b = make('button', undefined, 'abs-tile' + (v.done ? ' is-done' : ''));
    b.type = 'button';
    b.title = v.title + (v.published ? ' · ' + day(v.published) : '');
    const art = make('span', undefined, 'abs-art'), fallback = make('span', (v.title || '?').slice(0, 60), 'abs-fallback');
    art.append(fallback);
    if (v.poster) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; img.src = image(v.job); img.onload = () => fallback.remove(); img.onerror = () => img.remove(); art.append(img); }
    if (v.new) art.append(make('span', 'NEU', 'abs-new'));
    if (v.duration) art.append(make('span', clock(v.duration), 'abs-time'));
    if (v.progress > 0) { const bar = make('span', undefined, 'abs-progress'), f = make('i'); f.style.width = Math.round(Math.min(1, v.progress) * 100) + '%'; bar.append(f); art.append(bar); }
    const sub = [day(v.published), v.done ? 'gesehen' : ''].filter(Boolean).join(' · ');
    b.append(art, make('span', v.title, 'abs-name'));
    if (sub) b.append(make('span', sub, 'abs-sub'));
    b.onclick = () => play(v);
    return b;
  }
  function channelFacts(ch, full) {
    const facts = [num(ch.videos) + ' offline'];
    if (ch.new) facts.unshift(num(ch.new) + ' neu');
    if (ch.queued) facts.push(num(ch.queued) + ' in der Warteschlange' + (ch.retry ? ' (' + num(ch.retry) + ' mit neuem Versuch)' : ''));
    if (ch.failed) facts.push(num(ch.failed) + ' fehlgeschlagen');
    if (full) {
      facts.push(ch.checked ? 'zuletzt geprüft ' + when(ch.checked) : 'noch nicht geprüft');
      if (ch.enabled && ch.next_check) facts.push('nächste Prüfung ' + when(ch.next_check));
      if (!ch.enabled) facts.push('pausiert');
    }
    return facts.join(' · ');
  }
  function channelHead(ch, full) {
    const head = make('div', undefined, 'abs-channel-head');
    const pic = make('span', (ch.name || '?').slice(0, 1).toUpperCase(), 'abs-avatar');
    if (ch.avatar) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.src = avatar(ch.id); img.onerror = () => img.remove(); pic.append(img); }
    const text = make('div', undefined, 'abs-channel-text');
    const name = make('h3', ch.name);
    if (ch.kids) name.append(make('span', 'Kinderecke', 'abs-chip'));
    text.append(name, make('small', channelFacts(ch, full), 'muted'));
    if (full && ch.error) text.append(make('small', 'Letzte Prüfung: ' + ch.error, 'abs-error'));
    head.append(pic, text);
    if (full && /^https:\/\/www\.youtube\.com\//.test(ch.url || '')) {
      const a = make('a', 'Kanal auf YouTube ↗', 'button-link'); a.href = ch.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; head.append(a);
    }
    return head;
  }
  function manage() {
    window.atlasShowView?.('portals');
    document.querySelector('.platform-tab[data-platform="youtube"]')?.click();
    setTimeout(() => { window.AtlasPlatformLayout?.open('youtube'); const d = $('youtube-abos'); if (d) { d.open = true; d.scrollIntoView({behavior: 'smooth', block: 'start'}); } }, 50);
  }
  function pauseLine() {
    const p = data?.pause || {};
    if (p.until && p.until * 1000 > Date.now()) return 'YouTube-Downloads pausieren bis ' + when(p.until) + (p.reason ? ' (' + p.reason + ')' : '') + '.';
    return '';
  }

  function renderFull() {
    const wrap = make('div', undefined, 'abs-full');
    const bar = make('div', undefined, 'abs-toolbar');
    const pick = make('select'); pick.setAttribute('aria-label', 'Profil');
    for (const [v, l] of [['all', 'Alle Profile'], ['erwachsene', 'Für mich'], ['kinder', 'Kinderecke']]) { const o = make('option', l); o.value = v; pick.append(o); }
    pick.value = profile; pick.onchange = () => { profile = pick.value; render(); };
    const fresh = make('label', undefined, 'check'), box = make('input'); box.type = 'checkbox'; box.checked = onlyNew;
    box.onchange = () => { onlyNew = box.checked; render(); };
    fresh.append(box, document.createTextNode(' Nur neue'));
    const find = make('input'); find.type = 'search'; find.placeholder = 'Video oder Kanal suchen'; find.value = query; find.setAttribute('aria-label', 'Abo-Videos durchsuchen');
    find.oninput = () => { query = find.value; clearTimeout(find.t); find.t = setTimeout(() => { render(); const again = host.querySelector('.abs-toolbar input[type=search]'); if (again) { again.focus(); again.setSelectionRange(query.length, query.length); } }, 250); };
    const admin = make('button', 'Abos verwalten'); admin.type = 'button'; admin.onclick = manage;
    bar.append(pick, fresh, find, admin);
    wrap.append(bar);
    const pause = pauseLine();
    if (pause) wrap.append(make('p', pause, 'abs-error'));
    const needle = query.trim().toLowerCase();
    const channels = (data.channels || []).filter(ch => profile === 'all' || ch.profile === profile);
    if (!channels.length) wrap.append(make('div', (data.channels || []).length ? 'Keine Abos in diesem Profil.' : 'Noch keine YouTube-Abos. Unter Plattformen → YouTube → „Kanal-Abos“ einen Kanal abonnieren.', 'empty'));
    let shown = 0;
    for (const ch of channels) {
      const nameHit = needle && ch.name.toLowerCase().includes(needle);
      const own = data.videos.filter(v => v.abo === ch.id && (!onlyNew || v.new) && (!needle || nameHit || (v.title || '').toLowerCase().includes(needle)));
      if ((onlyNew || needle) && !own.length) continue;
      const sec = make('section', undefined, 'abs-channel');
      sec.append(channelHead(ch, true));
      if (own.length) { const grid = make('div', undefined, 'abs-grid'); for (const v of own) grid.append(tile(v)); sec.append(grid); }
      else sec.append(make('p', ch.queued ? 'Noch nichts offline; die Videos stehen in der Downloadwarteschlange.' : 'Noch keine Videos offline.', 'muted'));
      wrap.append(sec); shown++;
    }
    if (channels.length && !shown) wrap.append(make('div', 'Keine Videos zu diesem Filter.', 'empty'));
    host.replaceChildren(wrap);
    host.hidden = false;
  }

  function render() {
    if (mode === 'off') { host.hidden = true; return; }
    if (!data) return;
    renderFull();
  }
  async function load() {
    clearTimeout(timer);
    if (mode === 'off' || discover.hidden) return;
    const mine = ++seq;
    if (mode === 'full' && !data) { host.hidden = false; host.replaceChildren(make('p', 'Abo-Videos werden geladen …', 'muted')); }
    try {
      const d = await window.api('youtube-abo-videos');
      if (mine !== seq) return;
      data = d;
      // Während jemand im Suchfeld tippt, nicht neu zeichnen.
      if (!(mode === 'full' && host.contains(document.activeElement) && document.activeElement.tagName === 'INPUT')) render();
    } catch (e) {
      if (mine !== seq) return;
      if (mode === 'full') { host.hidden = false; host.replaceChildren(make('p', 'Abo-Videos nicht verfügbar: ' + e.message, 'abs-error')); }
      else host.hidden = true;
    }
    timer = setTimeout(load, 60000);
  }
  function setSource(source, kind) {
    mode = source === 'youtube' && kind === 'abos' ? 'full' : 'off';
    if (mode === 'off') { clearTimeout(timer); host.hidden = true; return; }
    if (data) render();
    load();
  }
  document.addEventListener('atlas-source', e => setSource(e.detail?.source, e.detail?.kind));
  document.addEventListener('atlas-view', e => { if (e.detail?.view === 'discover') load(); else clearTimeout(timer); });
  // Nach dem Abspielen stimmt „neu/gesehen“ erst mit dem nächsten Abruf; der Player meldet sein Schließen nicht,
  // daher beim Zurückkehren in das Fenster neu laden.
  window.addEventListener('focus', () => { if (mode !== 'off' && !discover.hidden) load(); });
  const now = window.AtlasUnifiedCatalog?.source?.();
  if (now) setSource(now, window.AtlasUnifiedCatalog?.kind?.());
  window.AtlasAboShelf = {reload: load};
})();
