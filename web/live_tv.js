/* Live-TV by station (0.5.50): one tab for the live channels of all sources (live_tv.py).
   ARD, ZDF & Co. come from the film list (topic "Livestream"), Pluto TV from its catalogue,
   Rakuten TV and Joyn (0.5.65, link to joyn.de only) from theirs.
   A station offered by several providers is listed once with one play button per provider.
   Favourites are kept per device (localStorage) and shown first. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('livetv')) return;
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  const FAV = 'atlas-live-favourites';
  const favourites = () => { try { return new Set(JSON.parse(localStorage.getItem(FAV) || '[]')); } catch { return new Set(); } };
  const setFavourites = set => { try { localStorage.setItem(FAV, JSON.stringify([...set])); } catch {} };
  const safeImage = v => typeof v === 'string' && /^https:\/\/[a-z0-9.-]+\//i.test(v) && !/[\s<>'"]/.test(v);
  let provider = '', group = '', seq = 0, timer = 0, data = null;

  function say(text, error) { $('livetv-status').textContent = text || ''; $('livetv-status').classList.toggle('netzkino-error', !!error); }

  function chip(host, label, active, pick) {
    const b = make('button', label, 'portal-category' + (active ? ' primary' : ''));
    b.type = 'button'; b.setAttribute('aria-pressed', String(active)); b.onclick = pick;
    host.append(b);
  }

  function filters(d) {
    const ph = $('livetv-providers'); ph.replaceChildren(make('strong', 'Anbieter'));
    const all = (d.providers || []).reduce((n, p) => n + (p.channels || 0), 0);
    chip(ph, 'Alle · ' + all, !provider, () => { provider = ''; group = ''; refresh(); });
    for (const p of d.providers || [])
      chip(ph, p.name + ' · ' + (p.channels || 0), provider === p.key, () => { provider = provider === p.key ? '' : p.key; group = ''; refresh(); });
    const gh = $('livetv-groups'); gh.replaceChildren();
    const groups = d.groups || [];
    gh.hidden = groups.length < 2 && !group;
    if (gh.hidden) return;
    gh.append(make('strong', 'Gruppen'));
    chip(gh, 'Alle', !group, () => { group = ''; refresh(); });
    for (const g of groups) chip(gh, g.name + ' · ' + g.count, group === g.name, () => { group = group === g.name ? '' : g.name; refresh(); });
    if (group && !groups.some(g => g.name === group)) chip(gh, group + ' · 0', true, () => { group = ''; refresh(); });
  }

  function badge(station) {
    if (safeImage(station.logo)) {
      const img = make('img', undefined, 'livetv-logo'); img.src = station.logo; img.alt = ''; img.loading = 'lazy';
      return img;
    }
    const short = station.name.replace(/[^\p{L}\p{N} ]/gu, '').split(/\s+/).filter(Boolean).map(w => /^\d/.test(w) ? w : w[0]).join('').slice(0, 4);
    return make('span', station.name.length <= 5 ? station.name : short || '▶', 'livetv-logo livetv-initials');
  }

  function tile(station, favs) {
    const box = make('article', undefined, 'livetv-station');
    box.dataset.key = station.key;
    const head = make('div', undefined, 'livetv-head');
    head.append(badge(station));
    const name = make('div', undefined, 'livetv-name');
    name.append(make('h3', (station.number ? station.number + ' · ' : '') + station.name));
    name.append(make('small', station.group, 'muted'));
    head.append(name);
    const fav = make('button', favs.has(station.key) ? '★' : '☆', 'livetv-fav');
    fav.type = 'button'; fav.title = favs.has(station.key) ? 'Aus Favoriten entfernen' : 'Als Favorit oben anzeigen';
    fav.setAttribute('aria-pressed', String(favs.has(station.key)));
    fav.onclick = () => { const f = favourites(); f.has(station.key) ? f.delete(station.key) : f.add(station.key); setFavourites(f); render(); };
    head.append(fav);
    box.append(head);
    if (station.summary) box.append(make('p', station.summary.length > 160 ? station.summary.slice(0, 157) + '…' : station.summary, 'livetv-summary'));
    const actions = make('div', undefined, 'netzkino-actions livetv-actions');
    const many = station.sources.length > 1;
    station.sources.forEach((src, i) => {
      // 0.5.65: Joyn channels only open joyn.de (no released stream, see joyn.py).
      if (!src.play) {
        if (!safeImage(src.link)) return;
        const a = make('a', '↗ ' + (many ? src.provider_name : 'Bei ' + src.provider_name + ' ansehen'), 'button');
        a.href = window.AtlasDirect ? window.AtlasDirect.href(src.provider, src.link) : src.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.title = [src.title, src.provider_name, src.quality].filter(Boolean).join(' · ');
        actions.append(a);
        return;
      }
      const b = make('button', '▶ ' + (many ? src.provider_name : 'Live ansehen'), i === 0 ? 'primary' : '');
      b.type = 'button';
      b.title = [src.title, src.provider_name, src.quality].filter(Boolean).join(' · ');
      b.onclick = () => {
        if (typeof window.playLive !== 'function') { say(window.atlasPlayerMissing?.() || 'Der Player ist nicht geladen; Seite neu laden.', true); return; }
        window.playLive(src.play, station.name + ' · ' + src.provider_name);
      };
      actions.append(b);
    });
    if (!many) actions.append(make('small', station.sources[0].provider_name + (station.sources[0].quality ? ' · ' + station.sources[0].quality : ''), 'muted livetv-source'));
    box.append(actions);
    return box;
  }

  function section(title, stations, favs) {
    const wrap = make('section', undefined, 'livetv-group');
    wrap.append(make('h3', title + ' · ' + stations.length, 'livetv-group-title'));
    const grid = make('div', undefined, 'livetv-grid');
    for (const s of stations) {
      try { grid.append(tile(s, favs)); }
      catch (e) { window.atlasReportError?.('live-tv Sender: ' + e.message); }   // 0.5.63: the other stations stay
    }
    wrap.append(grid);
    return wrap;
  }

  function render() {
    if (!data) return;
    const host = $('livetv-list'); host.replaceChildren();
    const favs = favourites();
    const stations = data.stations || [];
    const top = stations.filter(s => favs.has(s.key));
    if (top.length) host.append(section('★ Favoriten', top, favs));
    const order = [], byGroup = {};
    for (const s of stations) {
      if (!byGroup[s.group]) { byGroup[s.group] = []; order.push(s.group); }
      byGroup[s.group].push(s);
    }
    for (const g of order) host.append(section(g, byGroup[g], favs));
  }

  function hints(d) {
    const out = [];
    const counts = Object.fromEntries((d.providers || []).map(p => [p.key, p]));
    for (const p of d.providers || []) if (p.error) out.push(p.name + ': ' + p.error);
    if (!counts.mediathek?.channels && !counts.mediathek?.error)
      out.push('ARD/ZDF: keine Livestreams in der Filmliste gefunden – nach dem nächsten Filmlisten-Abgleich erneut prüfen.');
    if (!counts.pluto?.channels && !counts.pluto?.error)
      out.push(d.pluto?.last_success ? 'Pluto TV lieferte zuletzt keine Live-Sender.' : 'Pluto TV: Katalog noch nicht geladen (Plattformen → Pluto TV → „↻ Katalog jetzt laden“).');
    return out;
  }

  async function refresh() {
    const call = ++seq;
    const params = {q: $('livetv-filter').value.trim(), provider, group};
    let d;
    const waiting = window.atlasWaiting?.($('livetv-status'), 'Live-Sender werden geladen');
    try { d = await window.api('live-tv?' + new URLSearchParams(params)); }
    catch (e) {
      waiting?.(); if (call !== seq) return;
      // 0.5.67: the stations already shown stay; the reason and a retry are offered.
      say('Live-Sender nicht ' + (data ? 'aktualisiert' : 'verfügbar') + ': ' + e.message, true);
      const again = make('button', 'Erneut versuchen'); again.type = 'button'; again.onclick = refresh; $('livetv-status').append(' ', again);
      return;
    }
    waiting?.();
    if (call !== seq) return;
    data = d;
    // 0.5.63: one faulty station entry must not empty the whole tab; the reason is shown and reported.
    try { filters(d); render(); }
    catch (e) { say('Live-Sender konnten nicht dargestellt werden: ' + e.message, true); window.atlasReportError?.('live-tv: ' + e.message); return; }
    const extra = hints(d);
    const all = (d.providers || []).reduce((n, p) => n + (p.channels || 0), 0);
    // A filter that hides everything is named, with one click back to all stations.
    const narrowed = !d.total && all > 0 && (params.q || provider || group);
    say((d.total ? d.total + ' Sender' : narrowed ? 'Keine Sender für diese Auswahl (' + [params.q && 'Suche „' + params.q + '“', provider && 'Anbieter', group && 'Gruppe „' + group + '“'].filter(Boolean).join(', ') + ').' : 'Keine Sender gefunden.') + (extra.length ? ' · ' + extra.join(' · ') : ''),
      (d.providers || []).some(p => p.error));
    if (narrowed) { const reset = make('button', 'Alle Sender zeigen'); reset.type = 'button'; reset.onclick = () => { $('livetv-filter').value = ''; provider = ''; group = ''; refresh(); }; $('livetv-status').append(' ', reset); }
  }

  $('livetv-filter').oninput = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
  $('livetv-reload').onclick = refresh;
  // Open the tab from elsewhere, e.g. Plattformen → Pluto TV → Live-TV, optionally filtered to one provider.
  function show(only) {
    provider = only || ''; group = '';
    document.querySelector('.nav[data-view="livetv"]')?.click();
  }
  if ($('pluto-live-all')) $('pluto-live-all').onclick = () => show('pluto');

  // Live strip at the provider (0.5.50): the catalogue source "ARD, ZDF & Co." and "Pluto TV" show their
  // live stations above the search, collapsed by default. Sources without live channels show nothing.
  const STRIP = {mediatheken: 'mediathek', pluto: 'pluto', rakuten: 'rakuten', joyn: 'joyn'};
  let stripSeq = 0;
  async function strip() {
    const discover = $('discover'), anchor = $('atlas-cross-search');
    if (!discover || !anchor) return;
    let box = $('livetv-strip');
    const only = STRIP[discover.dataset.source];
    if (!only || discover.hidden) { if (box) box.hidden = true; return; }
    if (!box) {
      box = make('details', undefined, 'livetv-strip'); box.id = 'livetv-strip';
      box.append(make('summary'), make('div', undefined, 'livetv-strip-row'));
      anchor.before(box);
    }
    const call = ++stripSeq;
    let d;
    try { d = await window.api('live-tv?' + new URLSearchParams({provider: only})); } catch { box.hidden = true; return; }
    if (call !== stripSeq || STRIP[discover.dataset.source] !== only) return;
    const stations = d.stations || [];
    box.hidden = !stations.length;
    if (!stations.length) return;
    const name = (d.providers || []).find(p => p.key === only)?.name || '';
    box.querySelector('summary').textContent = '◉ Live-TV · ' + name + ' · ' + stations.length + ' Sender';
    const row = box.querySelector('.livetv-strip-row'); row.replaceChildren();
    for (const st of stations.slice(0, 40)) {
      const src = st.sources.find(x => x.provider === only) || st.sources[0];
      if (!src.play) {
        if (!safeImage(src.link)) continue;
        const a = make('a', '↗ ' + st.name, 'livetv-strip-button button');
        a.href = window.AtlasDirect ? window.AtlasDirect.href(src.provider, src.link) : src.link; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = src.title + ' · bei ' + src.provider_name + ' ansehen';
        row.append(a);
        continue;
      }
      const b = make('button', '▶ ' + st.name, 'livetv-strip-button'); b.type = 'button';
      b.title = src.title + ' · ' + src.provider_name;
      b.onclick = () => window.playLive?.(src.play, st.name + ' · ' + src.provider_name);
      row.append(b);
    }
    const all = make('button', 'Alle Sender im Reiter Live-TV →'); all.type = 'button';
    all.onclick = () => show(only);
    row.append(all);
  }
  if ($('discover')) {
    new MutationObserver(() => strip()).observe($('discover'), {attributes: true, attributeFilter: ['data-source', 'hidden']});
    strip();
  }
  window.AtlasLiveTV = {refresh, show, strip};
})();
