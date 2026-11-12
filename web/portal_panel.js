/* Shared platform panel for film portals with own catalogue (0.5.40): Pluto TV (0.5.36–0.5.38) and
   JustWatch TV use the same cards, categories, ratings, detail dialog, playback and offline list.
   cfg: {key, name, short, idPrefix, live, play(), externalLink, notPlayable, offlineNote}. Details: web/portal_title.js (0.5.42). */
window.AtlasPortalPanel = function (cfg) {
  'use strict';
  const K = cfg.key, P = cfg.idPrefix || K, NAME = cfg.name, SHORT = cfg.short || cfg.name;
  const $ = id => document.getElementById(id);
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  if (!$(K)) return null;
  const pageSize = 60;
  let view = 'movies', series = null, offset = 0, seq = 0, timer = 0, poll = 0, offlinePoll = 0;
  // 0.5.71 (cfg.music, YouTube): music videos – playlists ('album') with their videos ('track').
  let album = null, picked = new Set(), offlineOn = false, lastTracks = [];
  const LIST_VIEWS = ['episodes', 'tracks'];
  let genre = '';
  const cats = () => window.AtlasPortalCategories;
  const ACTIVE = ['queued', 'downloading', 'tagging'];
  const LABELS = {queued: 'Vorgemerkt', downloading: 'Lädt', tagging: 'MKV wird erstellt', done: 'Offline verfügbar', error: 'Fehler',
    cancelled: 'Abgebrochen', interrupted: 'Unterbrochen', expired: 'Abgelaufen und entfernt', removed: 'Gelöscht'};
  const day = ts => new Date(ts * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
  const mib = n => (Number(n || 0) / 1048576).toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' MiB';
  const daysText = n => 'noch ' + n + (n === 1 ? ' Tag' : ' Tage');
  const date = v => v ? new Date(v * 1000).toLocaleString('de-DE') : 'noch nie';
  const minutes = s => s ? Math.round(s / 60) + ' min' : '';
  const visible = () => !$('portals').hidden && $('portals').dataset.platform === K;
  const say = (text, error) => { $(P + '-status').textContent = text || ''; $(P + '-status').classList.toggle('netzkino-error', !!error); };

  let autoHold = 0;
  function summary(st) {
    // 0.5.60: an answer that was requested before the click must not undo the switch on screen.
    if (Date.now() > autoHold) $(P + '-auto').checked = !!st.auto;
    $(P + '-sync').disabled = !!st.running;
    $(P + '-sync').textContent = st.running ? 'Katalog wird geladen …' : '↻ Katalog jetzt laden';
    // The catalogue is stored locally and survives restarts; only a new run replaces it.
    const stored = (st.movies || 0) + (st.series || 0) + (st.channels || 0) + (st.music || 0) > 0;
    offlineOn = !!st.offline_enabled;
    const phase = st.running ? 'Läuft' : st.last_result === 'complete' ? 'Aktuell' : st.last_result === 'partial' ? 'Teilweise geladen' :
      st.last_result === 'interrupted' ? (stored ? 'Abruf unterbrochen · gespeicherter Bestand' : 'Abruf unterbrochen') :
      st.last_result === 'failed' ? (stored ? 'Abruf fehlgeschlagen · gespeicherter Bestand' : 'Fehlgeschlagen') :
      stored ? 'Gespeicherter Bestand' : 'Noch nicht geladen';
    $(P + '-summary').textContent = `${st.movies || 0} Filme · ${st.series || 0} Serien · ` +
      (cfg.live ? `${st.channels || 0} Live-Sender · ` : '') +
      (cfg.music ? `${st.music || 0} Musik-Playlists/-Videos (${st.tracks || 0} Videos) · ` : '') +
      (st.playable !== undefined ? `${st.playable || 0} im Player abspielbar · ` : '') + `${phase} · ` +
      `Stand: ${date(st.last_success)}` + (stored ? ' · bleibt nach Neustart erhalten' : '') +
      (st.running && st.progress ? ` · ${st.progress}` : '') +
      (st.last_error ? ` · Hinweis: ${st.last_error}` : '');
    $(P + '-summary').dataset.phase = st.last_result || 'never';
    clearTimeout(poll);
    if (st.running && visible()) poll = setTimeout(refresh, 4000);
  }

  function card(item) {
    const box = make('article', undefined, 'netzkino-item pluto-item');
    if (item.poster) {
      const img = make('img', undefined, 'netzkino-poster' + (item.kind === 'channel' ? ' pluto-logo' : ''));
      img.src = item.poster; img.alt = ''; img.loading = 'lazy'; box.append(img);
    }
    const label = item.kind === 'track' && view === 'tracks' && item.number !== null && item.number !== undefined ? `${item.number + 1}. ${item.title}` :
      item.kind === 'episode' && item.season !== null && item.episode !== null ?
      `S${String(item.season).padStart(2, '0')}E${String(item.episode).padStart(2, '0')} · ${item.title}` :
      item.kind === 'channel' && item.number ? `${item.number} · ${item.title}` : item.title;
    box.append(make('h3', label));
    const music = item.kind === 'album' || item.kind === 'track';
    const meta = (music ? [item.category, item.kind === 'album' ? item.number + ' Videos' : null, minutes(item.duration), item.rating] :
      [item.year, minutes(item.duration), item.rating, item.kind === 'channel' ? item.genre || item.category : null]).filter(Boolean).join(' · ');
    if (meta) box.append(make('small', meta, 'pluto-meta'));
    const stars = item.kind !== 'channel' && cats()?.rating(item.score);
    if (stars) box.append(stars);
    const line = item.kind !== 'channel' && cats()?.categories(item.categories);
    if (line) box.append(line);
    if (item.summary) box.append(make('p', item.summary.length > 260 ? item.summary.slice(0, 257) + '…' : item.summary, 'netzkino-description'));
    const actions = make('div', undefined, 'netzkino-actions');
    if (item.kind === 'track' && view === 'tracks' && item.offline) {
      const pick = make('label', undefined, 'check atlas-music-pick'), box2 = make('input');
      box2.type = 'checkbox'; box2.checked = picked.has(item.id);
      box2.onchange = () => { box2.checked ? picked.add(item.id) : picked.delete(item.id); musicTools(); };
      pick.append(box2, ' Auswählen'); actions.append(pick);
    }
    if (item.kind === 'album') {
      const open = make('button', 'Playlist öffnen', 'primary'); open.type = 'button';
      open.onclick = () => { album = item; picked.clear(); view = 'tracks'; offset = 0; refresh(); };
      actions.append(open);
      if (offlineOn) {
        const all = make('button', '⬇ Ganze Playlist offline'); all.type = 'button';
        all.onclick = () => saveMany({album: item.id}, item.title, all);
        actions.append(all);
      }
      if (cfg.externalLink && item.web_url) actions.append(externalLink(item));
      box.append(actions);
      return box;
    }
    if (item.kind !== 'channel' && !music) {
      const more = make('button', 'Details'); more.type = 'button';
      more.onclick = () => openDetail(item.id);
      actions.append(more);
    }
    if (item.kind === 'series') {
      const open = make('button', 'Folgen anzeigen', 'primary'); open.type = 'button';
      // 0.5.45: the series opens its title page with all episodes, as in the catalogue.
      open.onclick = () => openDetail(item.id) || (() => { series = item; view = 'episodes'; offset = 0; refresh(); })();
      actions.append(open);
    } else if (!playable(item)) {
      actions.append(externalLink(item));
      // 0.5.48: released by the provider only at night (youth protection) -> reserve the download.
      // 0.5.52: only with a real time window (item.night); otherwise the title is copy protected.
      const night = cfg.nightOffline && item.kind !== 'channel' && (item.night ? window.AtlasOffline?.control(K, item.id, label, {night: true}) : window.AtlasOffline?.protectedNote());
      if (night) actions.append(night);
      // 0.5.53: YouTube videos that refuse embedding can still be saved (opt-in switch).
      const keep = cfg.offlineFlag && item.offline && window.AtlasOffline?.control(K, item.id, label);
      if (keep) actions.append(keep);
    } else {
      const play = make('button', item.kind === 'channel' ? '▶ Live ansehen' : '▶ Ansehen', 'primary'); play.type = 'button';
      play.onclick = () => {
        if (typeof cfg.play() !== 'function') { say('Der Player ist nicht geladen; Seite neu laden.', true); return; }
        if (item.kind === 'track' && view === 'tracks' && window.playYouTubeList) {
          const list = lastTracks.filter(playable), at = list.findIndex(t => t.id === item.id);
          window.playYouTubeList(list.map(t => ({id: t.id, label: t.title})), Math.max(0, at));
          return;
        }
        cfg.play()(item.id, item.kind === 'episode' && series ? series.title + ' · ' + label : label);
      };
      actions.append(play);
      const off = item.kind !== 'channel' && (!cfg.offlineFlag || item.offline) && window.AtlasOffline?.control(K, item.id, label);
      if (off) actions.append(off);
      if (cfg.externalLink && item.web_url) actions.append(externalLink(item));
    }
    box.append(actions);
    return box;
  }

  // Titles without a stream for external players (JustWatch) only get the official page.
  const playable = item => item.playable !== false && item.playable !== 0;
  const safeLink = v => typeof v === 'string' && /^https:\/\/[a-z0-9.-]+\//i.test(v) && !/[\s<>'"]/.test(v);
  function externalLink(item) {
    const a = make('a', cfg.externalLink || ('Bei ' + NAME + ' ansehen'), 'button');
    if (safeLink(item.web_url)) { a.href = item.web_url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    else a.setAttribute('aria-disabled', 'true');
    return a;
  }
  function jobAction(label, job, action) {
    const b = make('button', label); b.type = 'button';
    b.onclick = async () => {
      b.disabled = true;
      try {
        if (action === 'retry') await window.api('retry', {id: job.id});
        else await window.api('offline-download-action', {id: job.id, action});
        await refreshOffline(); window.AtlasOffline?.refresh(K);
      } catch (e) { say(e.message, true); b.disabled = false; }
    };
    return b;
  }
  /* 0.5.71: whole playlist or the ticked videos in one click; each video becomes its own job. */
  function quality() { const v = $(P + '-music-quality')?.value || (() => { try { return localStorage.getItem('atlas-download-quality'); } catch (e) { return ''; } })(); return /^(best|\d{3,4})$/.test(v || '') ? v : 'best'; }
  async function saveMany(body, title, button) {
    if (button) button.disabled = true;
    try {
      const q = quality(); try { localStorage.setItem('atlas-download-quality', q); } catch (e) { /* private mode */ }
      const r = await window.api(K + '-download-add', {...body, quality: q});
      const text = `${r.created} Videos werden offline gespeichert` + (r.existing ? `, ${r.existing} schon gespeichert oder eingereiht` : '') +
        (r.failed ? `, ${r.failed} nicht möglich (${(r.errors || [])[0] || 'Fehler'})` : '') + '.';
      say(text, !r.created && !!r.failed); window.notice?.('„' + (title || 'Playlist') + '“: ' + text);
      picked.clear(); musicTools(); refreshOffline(); window.AtlasOffline?.refresh(K);
      $(P + '-items').querySelectorAll('.atlas-music-pick input').forEach(i => { i.checked = false; });
    } catch (e) { say('Kein Download gestartet: ' + e.message, true); }
    if (button) button.disabled = false;
  }
  function musicTools() {
    const host = $(P + '-music-tools'); if (!host) return;
    host.hidden = view !== 'tracks';
    if (host.hidden) return;
    const savable = lastTracks.filter(t => t.offline);
    $(P + '-music-play').disabled = !lastTracks.some(playable);
    for (const id of [P + '-music-all', P + '-music-pick', P + '-music-toggle', P + '-music-quality']) if ($(id)) $(id).hidden = !offlineOn || !savable.length;
    $(P + '-music-pick').disabled = !picked.size;
    $(P + '-music-pick').textContent = `⬇ Auswahl offline speichern (${picked.size})`;
    $(P + '-music-toggle').textContent = picked.size && picked.size === savable.length ? 'Auswahl aufheben' : 'Alle auswählen';
    $(P + '-music-hint').textContent = offlineOn ? (savable.length ? '' : 'Keine Videos dieser Playlist sind speicherbar (z. B. altersbeschränkt).') :
      'Offline-Speichern ist ausgeschaltet. Einschalten unter „YouTube-Kanäle & API-Schlüssel“.';
  }
  async function refreshOffline() {
    let data;
    try { data = await window.api(K + '-downloads'); } catch (e) { return; }
    const items = data.items || [];
    const shown = items.filter(j => !['expired', 'removed'].includes(j.state));
    $(P + '-offline-count').textContent = shown.length ? `· ${shown.filter(j => j.state === 'done').length} verfügbar, ${shown.filter(j => ACTIVE.includes(j.state)).length} in Arbeit` : '· keine';
    const host = $(P + '-offline-jobs'); host.replaceChildren();
    for (const job of shown) {
      const row = make('div', undefined, 'nk-offline-job nk-offline-' + job.state);
      row.append(make('strong', (LABELS[job.state] || job.state) + ' · ' + (job.target_name || job.title || '')));
      if (job.state === 'downloading') row.append(make('small', mib(job.received) + (job.total ? ' / ca. ' + mib(job.total) : '')));
      if (job.state === 'done' && job.offline_until)
        row.append(make('small', `Offline nutzbar bis ${day(job.offline_until)} · ${daysText(job.days_left)}`, job.days_left <= 3 ? 'nk-warning' : 'muted'));
      if (job.error) row.append(make('small', 'Fehler: ' + job.error, 'nk-warning'));
      if (ACTIVE.includes(job.state)) row.append(jobAction('Abbrechen', job, 'cancel'));
      if (['error', 'cancelled', 'interrupted'].includes(job.state)) row.append(jobAction('Erneut versuchen', job, 'retry'));
      if (job.state === 'done') row.append(jobAction('Jetzt löschen', job, 'delete'));
      host.append(row);
    }
    clearTimeout(offlinePoll);
    if (items.some(j => ACTIVE.includes(j.state)) && visible()) offlinePoll = setTimeout(refreshOffline, 3000);
  }

  async function refresh() {
    window.AtlasPlatformBoard?.mount(K);   // same overview as in the catalogue (0.5.50)
    refreshOffline();
    const call = ++seq;
    const q = $(P + '-filter').value.trim();
    const params = view === 'tracks' ? {view, album: album?.id || ''} : view === 'episodes' ? {view, series: series?.id || ''} :
      {view, q, offset, limit: pageSize, genre: view === 'live' ? '' : genre, sort: $(P + '-sort')?.value || 'title'};
    let data;
    // 0.5.41: a slow answer is shown with its waiting time; an error also replaces the status line.
    const waiting = window.atlasWaiting?.($(P + '-summary'), 'Katalogstatus wird geladen');
    try { data = await window.api(K + '?' + new URLSearchParams(params)); }
    catch (e) {
      waiting?.();
      if (call !== seq) return;
      const text = SHORT + '-Katalog nicht verfügbar: ' + e.message;
      say(text, true); $(P + '-summary').textContent = text + ' · neuer Versuch in 15 s'; $(P + '-summary').dataset.phase = 'ui-error';
      clearTimeout(poll); poll = setTimeout(() => { if (visible()) refresh(); }, 15000);
      return;
    }
    waiting?.();
    if (call !== seq) return;
    summary(data.status || {});
    for (const [id, v] of [[P + '-view-movies', 'movies'], [P + '-view-series', 'series'], [P + '-view-live', 'live'], [P + '-view-music', 'music']])
      if ($(id)) $(id).classList.toggle('primary', view === v || (view === 'episodes' && v === 'series') || (view === 'tracks' && v === 'music'));
    $(P + '-back').hidden = !LIST_VIEWS.includes(view);
    $(P + '-back').textContent = view === 'tracks' ? '← Zur Musikübersicht' : '← Zur Serienübersicht';
    if ($(P + '-live-all')) $(P + '-live-all').hidden = view !== 'live';  // 0.5.50: Live-TV tab by station
    $(P + '-heading').textContent = LIST_VIEWS.includes(view) ? (data.series?.title || '') + ' · ' + (data.items || []).length + (view === 'tracks' ? ' Videos' : ' Folgen') : '';
    cats()?.render($(P + '-categories'), ['live', 'music', ...LIST_VIEWS].includes(view) ? [] : data.genre_counts, genre,
      value => { genre = value; offset = 0; refresh(); });
    let items = data.items || [];
    if (view === 'tracks') lastTracks = data.items || [];
    if (LIST_VIEWS.includes(view) && q) items = items.filter(i => (i.title + ' ' + (i.category || '')).toLowerCase().includes(q.toLowerCase()));
    musicTools();
    const host = $(P + '-items'); host.replaceChildren();
    // 0.5.55: films and series use the same tile as the dashboard (web/unified_catalog.js), so
    // presentation and buttons are identical everywhere. Live channels and the episode list of the
    // tab keep their compact cards.
    const shared = (view === 'movies' || view === 'series') && window.AtlasCards;
    host.classList.toggle('atlas-uc-grid', !!shared);
    for (const item of items) host.append(shared ? shared.card(shared.portalRow(item, K)) : card(item));
    const listed = LIST_VIEWS.includes(view);
    const total = listed ? items.length : Number(data.total || 0);
    $(P + '-prev').disabled = listed || offset === 0;
    $(P + '-next').disabled = listed || offset + pageSize >= total;
    $(P + '-page-label').textContent = listed ? '' : `${total ? offset + 1 : 0}–${Math.min(offset + pageSize, total)} von ${total}`;
    const st = data.status || {};
    say(data.error ? 'Folgen konnten nicht aktualisiert werden: ' + data.error :
      !total && !st.last_success ? 'Noch kein ' + SHORT + '-Katalog geladen. „↻ Katalog jetzt laden“ startet den Abruf.' :
      !total ? 'Keine passenden Einträge.' : '', !!data.error);
  }

  for (const [id, v] of [[P + '-view-movies', 'movies'], [P + '-view-series', 'series'], [P + '-view-live', 'live'], [P + '-view-music', 'music']])
    if ($(id)) $(id).onclick = () => { view = v; series = null; album = null; offset = 0; genre = ''; refresh(); };
  $(P + '-back').onclick = () => { view = view === 'tracks' ? 'music' : 'series'; series = null; album = null; refresh(); };
  if ($(P + '-music-tools')) {
    $(P + '-music-play').onclick = () => {
      const list = lastTracks.filter(playable);
      if (list.length && window.playYouTubeList) window.playYouTubeList(list.map(t => ({id: t.id, label: t.title})), 0);
    };
    $(P + '-music-all').onclick = ev => saveMany({album: album?.id || ''}, album?.title, ev.target);
    $(P + '-music-pick').onclick = ev => saveMany({album: album?.id || '', ids: [...picked]}, album?.title, ev.target);
    $(P + '-music-toggle').onclick = () => {
      const savable = lastTracks.filter(t => t.offline);
      if (picked.size === savable.length) picked.clear(); else savable.forEach(t => picked.add(t.id));
      $(P + '-items').querySelectorAll('.atlas-music-pick input').forEach(i => { i.checked = picked.size > 0; });
      musicTools();
    };
    try { const v = localStorage.getItem('atlas-download-quality'); if (v && [...$(P + '-music-quality').options].some(o => o.value === v)) $(P + '-music-quality').value = v; } catch (e) { /* private mode */ }
  }
  $(P + '-filter').oninput = () => { offset = 0; clearTimeout(timer); timer = setTimeout(refresh, 250); };
  if ($(P + '-sort')) $(P + '-sort').onchange = () => { offset = 0; refresh(); };
  $(P + '-prev').onclick = () => { offset = Math.max(0, offset - pageSize); refresh(); };
  $(P + '-next').onclick = () => { offset += pageSize; refresh(); };
  $(P + '-sync').onclick = async () => {
    $(P + '-sync').disabled = true;
    try { await window.api(K + '-sync', {}); say('Katalog wird geladen …'); setTimeout(refresh, 1500); }
    catch (e) { say('Abruf nicht gestartet: ' + e.message, true); $(P + '-sync').disabled = false; }
  };
  $(P + '-auto').onchange = async () => {
    const box = $(P + '-auto'), wanted = box.checked;
    autoHold = Date.now() + 60000; box.disabled = true;
    try {
      const st = (await window.api(K + '-auto', {enabled: wanted})).status || {};
      autoHold = 0; summary(st);
      if (!!st.auto !== wanted) throw Error('Die Einstellung wurde nicht übernommen.');
      say(wanted ? 'Gespeichert: Der Katalog wird alle 24 Stunden automatisch aktualisiert.'
                 : 'Gespeichert: Der Katalog wird nur noch auf Knopfdruck aktualisiert.');
    } catch (e) { autoHold = 0; box.checked = !wanted; say('Nicht gespeichert: ' + e.message, true); }
    finally { box.disabled = false; }
  };
  // Details (0.5.42): the shared title page (web/portal_title.js), same as in the catalogue.
  // A tile started or finished a copy: keep the list "Offline gespeichert" in step.
  window.AtlasOffline?.onChange(K, () => { if (visible()) refreshOffline(); });
  const openDetail = id => window.AtlasPortalTitle?.open(K, id);
  return {refresh, openDetail};
};
