/* Live-TV by station (0.5.50): one tab for the live channels of all sources (live_tv.py).
   ARD, ZDF & Co. come from the film list (topic "Livestream"), Pluto TV from its catalogue,
   Rakuten TV and Joyn (0.5.65, link to joyn.de only) from theirs, Samsung TV Plus (0.5.97) from its channel list.
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

  function clock(sec) {
    return new Date(sec * 1000).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  }

  function episodeText(b) {
    const parts = [];
    if (b.season || b.episode) parts.push((b.season ? 'S' + b.season : '') + (b.episode ? (b.season ? ' ' : '') + 'F' + b.episode : ''));
    if (b.genre) parts.push(b.genre);
    if (b.repeat) parts.push('Wdh.');
    return parts.join(' · ');
  }

  function programme(prog) {
    const box = make('div', undefined, 'livetv-programme');
    const now = prog.now, next = prog.next;
    if (now) {
      const p = make('p', undefined, 'livetv-now');
      p.append(make('strong', 'Jetzt '), make('span', clock(now.start) + '–' + clock(now.stop) + ' ', 'muted'),
               make('span', now.title + (now.subtitle ? ' – ' + now.subtitle : '')));
      const extra = episodeText(now);
      if (extra) p.append(make('small', ' · ' + extra, 'muted'));
      p.title = [now.title, now.subtitle, extra].filter(Boolean).join(' · ');
      box.append(p);
      const span = Math.max(1, now.stop - now.start);
      const done = Math.min(1, Math.max(0, (Date.now() / 1000 - now.start) / span));
      const bar = make('div', undefined, 'livetv-progress');
      const fill = make('span'); fill.style.width = Math.round(done * 100) + '%';
      bar.append(fill); bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-valuenow', String(Math.round(done * 100)));
      bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100');
      box.append(bar);
    }
    if (next) {
      const p = make('p', undefined, 'livetv-next');
      p.append(make('span', (now ? 'Danach ' : 'Ab ') + clock(next.start) + ' ', 'muted'), make('span', next.title + (next.subtitle ? ' – ' + next.subtitle : '')));
      box.append(p);
    }
    return box;
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
    // EPG (Programmführer der Sender): laufende Sendung mit Fortschritt und die nächste, statt des Beschreibungstexts
    const prog = station.programme;
    if (prog && (prog.now || prog.next)) box.append(programme(prog));
    else if (station.summary) box.append(make('p', station.summary.length > 160 ? station.summary.slice(0, 157) + '…' : station.summary, 'livetv-summary'));
    const actions = make('div', undefined, 'netzkino-actions livetv-actions');
    const many = station.sources.length > 1;
    station.sources.forEach((src, i) => {
      // 0.5.65: Joyn channels only open joyn.de (no released stream, see joyn.py).
      if (!src.play) {
        if (!safeImage(src.link)) return;
        // 0.6.47: a station straight from its broadcaster (n-tv) names the station, not "Direkt vom Sender"
        const where = src.provider === 'sender' ? station.name : src.provider_name;
        const a = make('a', '↗ ' + (many ? where : 'Bei ' + where + ' ansehen'), 'button');
        a.href = window.AtlasDirect ? window.AtlasDirect.href(src.provider, src.link) : src.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.title = [src.title, src.provider_name, src.quality].filter(Boolean).join(' · ');
        actions.append(a);
        return;
      }
      const b = make('button', '▶ ' + (many ? src.provider_name : 'Live ansehen'), i === 0 ? 'primary' : '');
      b.type = 'button';
      b.title = [src.title, src.provider_name, src.quality].filter(Boolean).join(' · ');
      b.onclick = () => {
        if (typeof window.playLive !== 'function') { say(window.atlasPlayerMissing?.('live_tv') || 'Der Player ist nicht geladen; Seite neu laden.', true); return; }
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
    // 0.5.97: Samsung TV Plus loads its channel list itself (first start, then every 12 hours).
    const sm = d.samsung || {};
    if (sm.running) out.push('Samsung TV Plus: Senderliste wird geladen …');
    else if (!counts.samsung?.channels && !counts.samsung?.error)
      out.push(sm.last_error ? 'Samsung TV Plus: ' + sm.last_error : 'Samsung TV Plus: Senderliste noch nicht geladen.');
    if (sm.protected) out.push('Samsung TV Plus: ' + sm.protected + ' Sender nur mit Kopierschutz, hier nicht aufgeführt');
    return out;
  }

  // 0.5.97: load the Samsung TV Plus channel list now (otherwise it loads on its own every 12 hours).
  // 0.6.64: also used by the region switch (already started there) and the button in the setup block.
  async function samsungLoad(button, started) {
    if (button) button.disabled = true;
    samsungNote('Senderliste wird geladen …');
    try { if (!started) await window.api('samsung-sync', {}); }
    catch (e) { say('Samsung TV Plus: ' + e.message, true); samsungNote('Laden nicht möglich: ' + e.message, true); if (button) button.disabled = false; return; }
    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 1500));
      let st; try { st = await window.api('samsung'); } catch { break; }
      if (!st.running) break;
    }
    if (button) button.disabled = false;
    refresh();
  }

  // 0.6.64 (Code-Review 21.11., Björn: „ja für Samsung TV“): region and automatic refresh of Samsung TV Plus,
  // until then only reachable through /api/samsung-region and /api/samsung-auto.
  const REGION_NAME = {de: 'Deutschland', at: 'Österreich', ch: 'Schweiz'};
  const stamp = t => t ? new Date(t * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
  function samsungNote(text, error) {
    const n = $('samsung-setup-status'); if (!n) return;
    n.textContent = text || ''; n.classList.toggle('netzkino-error', !!error);
  }
  function samsungSetup(sm) {
    if (!$('samsung-setup') || !sm || !sm.region) return;
    const region = $('samsung-region'), auto = $('samsung-auto');
    if (document.activeElement !== region) region.value = sm.region;
    if (document.activeElement !== auto) auto.checked = !!sm.auto;
    $('samsung-sync').disabled = !!sm.running;
    $('samsung-setup-state').textContent = '· ' + (REGION_NAME[sm.region] || sm.region.toUpperCase()) + ' · Automatik ' + (sm.auto ? 'an' : 'aus');
    const parts = [];
    if (sm.running) parts.push('Senderliste wird geladen …');
    else if (sm.last_success) parts.push((sm.channels || 0) + ' Sender · Stand ' + stamp(sm.last_success));
    else parts.push('Senderliste noch nicht geladen');
    if (!sm.running && sm.auto && sm.next_attempt > Date.now() / 1000) parts.push('nächste Aktualisierung ' + stamp(sm.next_attempt));
    if (sm.protected) parts.push(sm.protected + ' Sender nur mit Kopierschutz, nicht aufgeführt');
    if (sm.last_result === 'error' && sm.last_error) parts.push('letzter Versuch: ' + sm.last_error);
    samsungNote(parts.join(' · '), sm.last_result === 'error' && !sm.running);
  }
  if ($('samsung-setup')) {
    $('samsung-region').onchange = async e => {
      const region = e.target.value;
      e.target.disabled = true;
      try {
        const r = await window.api('samsung-region', {region});
        samsungSetup(r.status);
        if (r.started) await samsungLoad(null, true);
      } catch (err) { samsungNote('Region nicht gespeichert: ' + err.message, true); refresh(); }
      finally { e.target.disabled = false; }
    };
    $('samsung-auto').onchange = async e => {
      const enabled = e.target.checked;
      try { samsungSetup((await window.api('samsung-auto', {enabled})).status); }
      catch (err) { e.target.checked = !enabled; samsungNote('Automatik nicht gespeichert: ' + err.message, true); }
    };
    $('samsung-sync').onclick = e => samsungLoad(e.currentTarget);
  }

  // Programmführer (epg.py): status, automatic switch and load button in the Live-TV tab.
  const EPG_SOURCE = {srf: 'SRF', ard: 'ARD', zdf: 'ZDF'};
  function epgSetup(st) {
    if (!$('epg-setup') || !st || st.auto === undefined) return;
    const auto = $('epg-auto');
    if (document.activeElement !== auto) auto.checked = !!st.auto;
    $('epg-sync').disabled = !!st.running;
    $('epg-setup-state').textContent = '· Automatik ' + (st.auto ? 'an' : 'aus') + (st.broadcasts ? ' · ' + st.broadcasts.toLocaleString('de-DE') + ' Sendungen' : '');
    const parts = [];
    if (st.running) parts.push('Programm wird geladen …');
    else if (st.last_success) parts.push('Stand ' + stamp(st.last_success) + (st.first ? ' · von ' + stamp(st.first) + ' bis ' + stamp(st.last) : ''));
    else parts.push('Programm noch nicht geladen');
    for (const [key, v] of Object.entries(st.sources || {})) if (v && v.error) parts.push((EPG_SOURCE[key] || key) + ': ' + v.error);
    if (!st.running && st.auto && st.next_attempt > Date.now() / 1000) parts.push('nächste Aktualisierung ' + stamp(st.next_attempt));
    const n = $('epg-setup-status'); n.textContent = parts.join(' · '); n.classList.toggle('netzkino-error', st.last_result === 'error' && !st.running);
  }
  if ($('epg-setup')) {
    $('epg-auto').onchange = async e => {
      const enabled = e.target.checked;
      try { epgSetup((await window.api('epg-auto', {enabled})).status); }
      catch (err) { e.target.checked = !enabled; $('epg-setup-status').textContent = 'Automatik nicht gespeichert: ' + err.message; }
    };
    $('epg-sync').onclick = async e => {
      const button = e.currentTarget; button.disabled = true;
      try { epgSetup((await window.api('epg-sync', {})).status); } catch (err) { $('epg-setup-status').textContent = 'Laden nicht möglich: ' + err.message; button.disabled = false; return; }
      for (let i = 0; i < 80; i++) {
        await new Promise(r => setTimeout(r, 3000));
        let st; try { st = await window.api('epg'); } catch { break; }
        epgSetup(st);
        if (!st.running) break;
      }
      button.disabled = false;
      refresh();
    };
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
    samsungSetup(d.samsung);
    epgSetup(d.epg);
    const sm = d.samsung || {}, smCount = (d.providers || []).find(p => p.key === 'samsung')?.channels || 0;
    if (!sm.running && (!smCount || sm.last_result === 'error')) {
      const load = make('button', smCount ? 'Samsung-TV-Plus-Liste neu laden' : 'Samsung-TV-Plus-Sender laden'); load.type = 'button';
      load.onclick = () => samsungLoad(load); $('livetv-status').append(' ', load);
    }
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
  const STRIP = {mediatheken: 'mediathek', pluto: 'pluto', rakuten: 'rakuten', joyn: 'joyn', plex: 'plex', servustv: 'servustv', redbulltv: 'redbulltv'};
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
