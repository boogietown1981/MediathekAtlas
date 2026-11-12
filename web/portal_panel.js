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
  let offline = new Map(), offlineDays = 30, ffmpeg = true, genre = '';
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

  function summary(st) {
    $(P + '-auto').checked = !!st.auto;
    $(P + '-sync').disabled = !!st.running;
    $(P + '-sync').textContent = st.running ? 'Katalog wird geladen …' : '↻ Katalog jetzt laden';
    // The catalogue is stored locally and survives restarts; only a new run replaces it.
    const stored = (st.movies || 0) + (st.series || 0) + (st.channels || 0) > 0;
    const phase = st.running ? 'Läuft' : st.last_result === 'complete' ? 'Aktuell' : st.last_result === 'partial' ? 'Teilweise geladen' :
      st.last_result === 'interrupted' ? (stored ? 'Abruf unterbrochen · gespeicherter Bestand' : 'Abruf unterbrochen') :
      st.last_result === 'failed' ? (stored ? 'Abruf fehlgeschlagen · gespeicherter Bestand' : 'Fehlgeschlagen') :
      stored ? 'Gespeicherter Bestand' : 'Noch nicht geladen';
    $(P + '-summary').textContent = `${st.movies || 0} Filme · ${st.series || 0} Serien · ` +
      (cfg.live ? `${st.channels || 0} Live-Sender · ` : '') +
      (st.playable !== undefined ? `${st.playable || 0} im Player abspielbar · ` : '') + `${phase} · ` +
      `Stand: ${date(st.last_success)}` + (stored ? ' · bleibt nach Neustart erhalten' : '') +
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
    const label = item.kind === 'episode' && item.season !== null && item.episode !== null ?
      `S${String(item.season).padStart(2, '0')}E${String(item.episode).padStart(2, '0')} · ${item.title}` :
      item.kind === 'channel' && item.number ? `${item.number} · ${item.title}` : item.title;
    box.append(make('h3', label));
    const meta = [item.year, minutes(item.duration), item.rating,
      item.kind === 'channel' ? item.genre || item.category : null].filter(Boolean).join(' · ');
    if (meta) box.append(make('small', meta, 'pluto-meta'));
    const stars = item.kind !== 'channel' && cats()?.rating(item.score);
    if (stars) box.append(stars);
    const line = item.kind !== 'channel' && cats()?.categories(item.categories);
    if (line) box.append(line);
    if (item.summary) box.append(make('p', item.summary.length > 260 ? item.summary.slice(0, 257) + '…' : item.summary, 'netzkino-description'));
    const actions = make('div', undefined, 'netzkino-actions');
    if (item.kind !== 'channel') {
      const more = make('button', 'Details'); more.type = 'button';
      more.onclick = () => openDetail(item.id);
      actions.append(more);
    }
    if (item.kind === 'series') {
      const open = make('button', 'Folgen anzeigen', 'primary'); open.type = 'button';
      open.onclick = () => { series = item; view = 'episodes'; offset = 0; refresh(); };
      actions.append(open);
    } else if (!playable(item)) {
      actions.append(externalLink(item));
    } else {
      const play = make('button', item.kind === 'channel' ? '▶ Live ansehen' : '▶ Ansehen', 'primary'); play.type = 'button';
      play.onclick = () => {
        if (typeof cfg.play() !== 'function') { say('Der Player ist nicht geladen; Seite neu laden.', true); return; }
        cfg.play()(item.id, item.kind === 'episode' && series ? series.title + ' · ' + label : label);
      };
      actions.append(play);
      if (item.kind !== 'channel') actions.append(offlineButton(item));
      if (cfg.externalLink && item.web_url) actions.append(externalLink(item));
    }
    box.append(actions);
    if (item.kind !== 'channel' && item.kind !== 'series' && playable(item)) {
      const state = make('small', '', 'pluto-offline-state'); state.dataset.portalId = item.id;
      box.append(state); paintState(state, offline.get(item.id));
    }
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
  function offlineButton(item) {
    const b = make('button', `⬇ Offline speichern (${offlineDays} Tage)`); b.type = 'button'; b.dataset.portalOffline = item.id;
    paintButton(b, offline.get(item.id));
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await window.api(K + '-download-add', {id: item.id});
        say(r.created ? `„${item.title}“ ist eingereiht. Gespeichert wird wie bei Mediathek-Videos; nach ${offlineDays} Tagen wird die Datei entfernt.` :
          `„${item.title}“ ist bereits eingereiht oder offline verfügbar.`);
        await refreshOffline();
      } catch (e) { say('Kein Download gestartet: ' + e.message, true); b.disabled = false; }
    };
    return b;
  }
  function paintButton(b, job) {
    const busy = job && (ACTIVE.includes(job.state) || job.state === 'done');
    b.disabled = !!busy || !ffmpeg;
    b.title = !ffmpeg ? 'ffmpeg fehlt in dieser Installation' : busy ? 'Bereits eingereiht oder offline verfügbar' :
      `${NAME} erlaubt ${offlineDays} Tage Offline-Nutzung; Werbung bleibt enthalten`;
  }
  function paintState(node, job) {
    node.className = 'pluto-offline-state muted';
    if (!job) { node.textContent = ''; return; }
    if (job.state === 'done' && job.offline_until) {
      node.textContent = `Offline bis ${day(job.offline_until)} · ${daysText(job.days_left)}`;
      if (job.days_left <= 3) node.className = 'pluto-offline-state nk-warning';
    } else if (job.state === 'downloading') node.textContent = 'Lädt · ' + mib(job.received);
    else if (ACTIVE.includes(job.state)) node.textContent = LABELS[job.state];
    else if (job.state === 'error') { node.textContent = 'Offline-Speicherung fehlgeschlagen'; node.className = 'pluto-offline-state nk-warning'; }
    else node.textContent = '';
  }
  function jobAction(label, job, action) {
    const b = make('button', label); b.type = 'button';
    b.onclick = async () => {
      b.disabled = true;
      try {
        if (action === 'retry') await window.api('retry', {id: job.id});
        else await window.api('offline-download-action', {id: job.id, action});
        await refreshOffline();
      } catch (e) { say(e.message, true); b.disabled = false; }
    };
    return b;
  }
  async function refreshOffline() {
    let data;
    try { data = await window.api(K + '-downloads'); } catch (e) { return; }
    offlineDays = data.offline_days || offlineDays; ffmpeg = data.ffmpeg !== false;
    const items = data.items || [];
    // Newest job per title decides the card state (listing is newest first).
    offline = new Map();
    for (const job of items) if (job[K + '_id'] && !offline.has(job[K + '_id'])) offline.set(job[K + '_id'], job);
    for (const node of document.querySelectorAll('#' + P + '-items [data-portal-id]')) paintState(node, offline.get(node.dataset.portalId));
    for (const b of document.querySelectorAll('#' + P + '-items [data-portal-offline]')) paintButton(b, offline.get(b.dataset.portalOffline));
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
    refreshOffline();
    const call = ++seq;
    const q = $(P + '-filter').value.trim();
    const params = view === 'episodes' ? {view, series: series?.id || ''} :
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
    for (const [id, v] of [[P + '-view-movies', 'movies'], [P + '-view-series', 'series'], [P + '-view-live', 'live']])
      if ($(id)) $(id).classList.toggle('primary', view === v || (view === 'episodes' && v === 'series'));
    $(P + '-back').hidden = view !== 'episodes';
    $(P + '-heading').textContent = view === 'episodes' ? (data.series?.title || '') + ' · ' + (data.items || []).length + ' Folgen' : '';
    cats()?.render($(P + '-categories'), view === 'live' || view === 'episodes' ? [] : data.genre_counts, genre,
      value => { genre = value; offset = 0; refresh(); });
    let items = data.items || [];
    if (view === 'episodes' && q) items = items.filter(i => i.title.toLowerCase().includes(q.toLowerCase()));
    const host = $(P + '-items'); host.replaceChildren();
    for (const item of items) host.append(card(item));
    const total = view === 'episodes' ? items.length : Number(data.total || 0);
    $(P + '-prev').disabled = view === 'episodes' || offset === 0;
    $(P + '-next').disabled = view === 'episodes' || offset + pageSize >= total;
    $(P + '-page-label').textContent = view === 'episodes' ? '' : `${total ? offset + 1 : 0}–${Math.min(offset + pageSize, total)} von ${total}`;
    const st = data.status || {};
    say(data.error ? 'Folgen konnten nicht aktualisiert werden: ' + data.error :
      !total && !st.last_success ? 'Noch kein ' + SHORT + '-Katalog geladen. „↻ Katalog jetzt laden“ startet den Abruf.' :
      !total ? 'Keine passenden Einträge.' : '', !!data.error);
  }

  for (const [id, v] of [[P + '-view-movies', 'movies'], [P + '-view-series', 'series'], [P + '-view-live', 'live']])
    if ($(id)) $(id).onclick = () => { view = v; series = null; offset = 0; genre = ''; refresh(); };
  $(P + '-back').onclick = () => { view = 'series'; series = null; refresh(); };
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
    try { summary((await window.api(K + '-auto', {enabled: $(P + '-auto').checked})).status || {}); }
    catch (e) { say(e.message, true); }
  };
  // Details (0.5.42): the shared title page (web/portal_title.js), same as in the catalogue.
  const openDetail = id => window.AtlasPortalTitle?.open(K, id);
  return {refresh, openDetail};
};
