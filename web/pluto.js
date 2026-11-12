/* Pluto TV (0.5.36): public catalogue (films, series, live channels), playback in the in-app player.
   0.5.37: films and episodes can be stored offline for 20 days through the shared download queue. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  if (!$('pluto')) return;
  const pageSize = 60;
  let view = 'movies', series = null, offset = 0, seq = 0, timer = 0, poll = 0, offlinePoll = 0;
  let offline = new Map(), offlineDays = 20, ffmpeg = true;
  const ACTIVE = ['queued', 'downloading', 'tagging'];
  const LABELS = {queued: 'Vorgemerkt', downloading: 'Lädt', tagging: 'MKV wird erstellt', done: 'Offline verfügbar', error: 'Fehler',
    cancelled: 'Abgebrochen', interrupted: 'Unterbrochen', expired: 'Abgelaufen und entfernt', removed: 'Gelöscht'};
  const day = ts => new Date(ts * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
  const mib = n => (Number(n || 0) / 1048576).toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' MiB';
  const daysText = n => 'noch ' + n + (n === 1 ? ' Tag' : ' Tage');
  const date = v => v ? new Date(v * 1000).toLocaleString('de-DE') : 'noch nie';
  const minutes = s => s ? Math.round(s / 60) + ' min' : '';
  const visible = () => !$('portals').hidden && $('portals').dataset.platform === 'pluto';
  const say = (text, error) => { $('pluto-status').textContent = text || ''; $('pluto-status').classList.toggle('netzkino-error', !!error); };

  function summary(st) {
    $('pluto-auto').checked = !!st.auto;
    $('pluto-sync').disabled = !!st.running;
    $('pluto-sync').textContent = st.running ? 'Katalog wird geladen …' : '↻ Katalog jetzt laden';
    const phase = st.running ? 'Läuft' : st.last_result === 'complete' ? 'Aktuell' : st.last_result === 'partial' ? 'Teilweise geladen' :
      st.last_result === 'failed' ? 'Fehlgeschlagen' : 'Noch nicht geladen';
    $('pluto-summary').textContent = `${st.movies || 0} Filme · ${st.series || 0} Serien · ${st.channels || 0} Live-Sender · ${phase} · ` +
      `Letzter Abruf: ${date(st.last_success)}` + (st.last_error ? ` · Hinweis: ${st.last_error}` : '');
    $('pluto-summary').dataset.phase = st.last_result || 'never';
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
    const meta = [item.year, minutes(item.duration), item.rating, item.genre || item.category].filter(Boolean).join(' · ');
    if (meta) box.append(make('small', meta, 'pluto-meta'));
    if (item.summary) box.append(make('p', item.summary.length > 260 ? item.summary.slice(0, 257) + '…' : item.summary, 'netzkino-description'));
    const actions = make('div', undefined, 'netzkino-actions');
    if (item.kind === 'series') {
      const open = make('button', 'Folgen anzeigen', 'primary'); open.type = 'button';
      open.onclick = () => { series = item; view = 'episodes'; offset = 0; refresh(); };
      actions.append(open);
    } else {
      const play = make('button', item.kind === 'channel' ? '▶ Live ansehen' : '▶ Ansehen', 'primary'); play.type = 'button';
      play.onclick = () => {
        if (typeof window.playPluto !== 'function') { say('Der Player ist nicht geladen; Seite neu laden.', true); return; }
        window.playPluto(item.id, item.kind === 'episode' && series ? series.title + ' · ' + label : label);
      };
      actions.append(play);
      if (item.kind !== 'channel') actions.append(offlineButton(item));
    }
    box.append(actions);
    if (item.kind !== 'channel' && item.kind !== 'series') {
      const state = make('small', '', 'pluto-offline-state'); state.dataset.plutoId = item.id;
      box.append(state); paintState(state, offline.get(item.id));
    }
    return box;
  }

  function offlineButton(item) {
    const b = make('button', `⬇ Offline speichern (${offlineDays} Tage)`); b.type = 'button'; b.dataset.plutoOffline = item.id;
    paintButton(b, offline.get(item.id));
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await window.api('pluto-download-add', {id: item.id});
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
      `Pluto TV erlaubt ${offlineDays} Tage Offline-Nutzung; Werbung bleibt enthalten`;
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
    try { data = await window.api('pluto-downloads'); } catch (e) { return; }
    offlineDays = data.offline_days || offlineDays; ffmpeg = data.ffmpeg !== false;
    const items = data.items || [];
    // Newest job per title decides the card state (listing is newest first).
    offline = new Map();
    for (const job of items) if (job.pluto_id && !offline.has(job.pluto_id)) offline.set(job.pluto_id, job);
    for (const node of document.querySelectorAll('#pluto-items [data-pluto-id]')) paintState(node, offline.get(node.dataset.plutoId));
    for (const b of document.querySelectorAll('#pluto-items [data-pluto-offline]')) paintButton(b, offline.get(b.dataset.plutoOffline));
    const shown = items.filter(j => !['expired', 'removed'].includes(j.state));
    $('pluto-offline-count').textContent = shown.length ? `· ${shown.filter(j => j.state === 'done').length} verfügbar, ${shown.filter(j => ACTIVE.includes(j.state)).length} in Arbeit` : '· keine';
    const host = $('pluto-offline-jobs'); host.replaceChildren();
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
    const q = $('pluto-filter').value.trim();
    const params = view === 'episodes' ? {view, series: series?.id || ''} : {view, q, offset, limit: pageSize};
    let data;
    try { data = await window.api('pluto?' + new URLSearchParams(params)); }
    catch (e) { if (call === seq) say('Pluto-Katalog nicht verfügbar: ' + e.message, true); return; }
    if (call !== seq) return;
    summary(data.status || {});
    for (const [id, v] of [['pluto-view-movies', 'movies'], ['pluto-view-series', 'series'], ['pluto-view-live', 'live']])
      $(id).classList.toggle('primary', view === v || (view === 'episodes' && v === 'series'));
    $('pluto-back').hidden = view !== 'episodes';
    $('pluto-heading').textContent = view === 'episodes' ? (data.series?.title || '') + ' · ' + (data.items || []).length + ' Folgen' : '';
    let items = data.items || [];
    if (view === 'episodes' && q) items = items.filter(i => i.title.toLowerCase().includes(q.toLowerCase()));
    const host = $('pluto-items'); host.replaceChildren();
    for (const item of items) host.append(card(item));
    const total = view === 'episodes' ? items.length : Number(data.total || 0);
    $('pluto-prev').disabled = view === 'episodes' || offset === 0;
    $('pluto-next').disabled = view === 'episodes' || offset + pageSize >= total;
    $('pluto-page-label').textContent = view === 'episodes' ? '' : `${total ? offset + 1 : 0}–${Math.min(offset + pageSize, total)} von ${total}`;
    const st = data.status || {};
    say(data.error ? 'Folgen konnten nicht aktualisiert werden: ' + data.error :
      !total && !st.last_success ? 'Noch kein Pluto-Katalog geladen. „↻ Katalog jetzt laden“ startet den Abruf.' :
      !total ? 'Keine passenden Einträge.' : '', !!data.error);
  }

  for (const [id, v] of [['pluto-view-movies', 'movies'], ['pluto-view-series', 'series'], ['pluto-view-live', 'live']])
    $(id).onclick = () => { view = v; series = null; offset = 0; refresh(); };
  $('pluto-back').onclick = () => { view = 'series'; series = null; refresh(); };
  $('pluto-filter').oninput = () => { offset = 0; clearTimeout(timer); timer = setTimeout(refresh, 250); };
  $('pluto-prev').onclick = () => { offset = Math.max(0, offset - pageSize); refresh(); };
  $('pluto-next').onclick = () => { offset += pageSize; refresh(); };
  $('pluto-sync').onclick = async () => {
    $('pluto-sync').disabled = true;
    try { await window.api('pluto-sync', {}); say('Katalog wird geladen …'); setTimeout(refresh, 1500); }
    catch (e) { say('Abruf nicht gestartet: ' + e.message, true); $('pluto-sync').disabled = false; }
  };
  $('pluto-auto').onchange = async () => {
    try { summary((await window.api('pluto-auto', {enabled: $('pluto-auto').checked})).status || {}); }
    catch (e) { say(e.message, true); }
  };
  window.MediathekAtlasPluto = {refresh};
})();
