/* One "30 Tage offline speichern" control for every tile (0.5.47).
   Björn (12.11.2026): the download of Pluto TV and JustWatch TV was not shown consistently; the
   30-day offline copy belongs into the tile view, the same on every platform. Netzkino, Pluto TV and
   JustWatch TV, catalogue tiles, platform tiles and episode rows all use this control: one button
   and one status line (queued, progress, available until, failed with reason and retry). */
(() => {
  'use strict';
  const SOURCES = {netzkino: {name: 'Netzkino', action: 'netzkino-download-action'},
    pluto: {name: 'Pluto TV', action: 'offline-download-action'},
    justwatch: {name: 'JustWatch TV', action: 'offline-download-action'},
    rakuten: {name: 'Rakuten TV', action: 'offline-download-action'}};
  const ACTIVE = ['queued', 'downloading', 'tagging'], FAILED = ['error', 'cancelled', 'interrupted'];
  const LABELS = {queued: 'Vorgemerkt', downloading: 'Lädt', tagging: 'MKV wird erstellt', done: 'Offline verfügbar',
    error: 'Fehlgeschlagen', cancelled: 'Abgebrochen', interrupted: 'Unterbrochen'};
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const day = ts => new Date(ts * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
  const clock = ts => new Date(ts * 1000).toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});
  const NIGHT = 'Jugendschutz: JustWatch gibt diesen Titel nur von 0 bis 6 Uhr frei.';
  const mib = n => (Number(n || 0) / 1048576).toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' MiB';
  // Per source: live controls, newest job per title, tool state, poll timer.
  const state = {};
  for (const key of Object.keys(SOURCES)) state[key] = {controls: new Set(), jobs: new Map(), days: 30, tool: '', timer: 0, pending: 0, listeners: new Set()};

  function paint(ctl) {
    const st = state[ctl.source], job = st.jobs.get(ctl.id), {button, cancel, note} = ctl;
    const s = job?.state;
    cancel.hidden = !ACTIVE.includes(s);
    note.className = 'atlas-offline-note muted'; button.classList.remove('atlas-offline-done');
    if (s === 'queued' && job.not_before) {
      button.disabled = true; button.textContent = '🌙 Vorgemerkt für ' + clock(job.not_before) + ' Uhr';
      note.textContent = NIGHT + ' Der Download startet dann von selbst, wenn MediathekAtlas läuft.';
    } else if (ACTIVE.includes(s)) {
      button.disabled = true;
      button.textContent = s === 'downloading' ? '⬇ Lädt · ' + mib(job.received) + (job.total ? ' / ' + mib(job.total) : '') : '⬇ ' + LABELS[s];
      note.textContent = 'Wird gespeichert · ' + st.days + ' Tage offline nutzbar';
    } else if (s === 'done') {
      button.disabled = true; button.classList.add('atlas-offline-done'); button.textContent = '✓ Offline verfügbar';
      note.textContent = job.offline_until ? 'bis ' + day(job.offline_until) + ' · noch ' + job.days_left + (job.days_left === 1 ? ' Tag' : ' Tage') : 'ohne Ablauf';
      if (job.offline_until && job.days_left <= 3) note.className = 'atlas-offline-note nk-warning';
    } else if (FAILED.includes(s)) {
      button.disabled = !!st.tool; button.textContent = '↻ Erneut offline speichern';
      note.textContent = LABELS[s] + (job.error ? ': ' + job.error : ''); note.className = 'atlas-offline-note nk-warning';
    } else {
      button.disabled = !!st.tool;
      button.textContent = ctl.night ? '🌙 Heute Nacht offline speichern (' + st.days + ' Tage)' : '⬇ Offline speichern (' + st.days + ' Tage)';
      note.textContent = ctl.message || (ctl.night ? NIGHT : '');
    }
    button.title = st.tool || (s === 'done' || ACTIVE.includes(s) ? 'Bereits eingereiht oder offline verfügbar' :
      SOURCES[ctl.source].name + ' erlaubt ' + st.days + ' Tage Offline-Nutzung; danach wird die Datei automatisch entfernt');
  }

  async function refresh(source) {
    const st = state[source]; if (!st) return;
    for (const c of [...st.controls]) if (!c.node.isConnected) st.controls.delete(c);
    clearTimeout(st.timer);
    if (!st.controls.size) return;
    const ids = [...new Set([...st.controls].map(c => c.id))].slice(0, 1000), token = ++st.pending;
    let data;
    try { data = await window.api(source + '-downloads?' + new URLSearchParams({ids: ids.join(',')})); }
    catch (e) { return; }
    if (token !== st.pending) return;
    st.days = data.offline_days || st.days;
    st.tool = data.ffmpeg === false ? 'ffmpeg fehlt in dieser Installation' : data.ytdl?.ok === false ? 'ytdl-nightly fehlt in dieser Installation' : '';
    st.jobs = new Map();
    const key = source + '_id';
    // Newest job per title decides (listing is newest first); expired/removed copies can be saved again.
    for (const j of data.items || []) if (j[key] && !st.jobs.has(j[key]) && !['expired', 'removed'].includes(j.state)) st.jobs.set(j[key], j);
    for (const c of st.controls) paint(c);
    // A listener that returns false (its view is gone) is dropped.
    for (const fn of [...st.listeners]) { try { if (fn() === false) st.listeners.delete(fn); } catch (e) { /* listener errors never stop the status */ } }
    const running = [...st.jobs.values()].filter(j => ACTIVE.includes(j.state));
    // Reserved for the night: nothing changes for hours, so look once a minute only.
    if (running.length) st.timer = setTimeout(() => refresh(source), running.every(j => j.not_before) ? 60000 : 3000);
  }
  const soon = {};
  function schedule(source) { clearTimeout(soon[source]); soon[source] = setTimeout(() => refresh(source), 60); }

  /* One control per tile or episode row; the node unregisters itself when it leaves the page. */
  function control(source, id, title, opts) {
    const st = state[source]; if (!st || !id) return null;
    const node = make('div', undefined, 'atlas-offline'); node.dataset.offlineSource = source; node.dataset.offlineId = id;
    const button = make('button', '⬇ Offline speichern (' + st.days + ' Tage)', 'atlas-offline-button'); button.type = 'button';
    const cancel = make('button', 'Abbrechen', 'atlas-offline-cancel'); cancel.type = 'button'; cancel.hidden = true;
    const note = make('small', '', 'atlas-offline-note muted');
    const ctl = {source, id, node, button, cancel, note, message: '', night: !!opts?.night};
    button.onclick = async ev => {
      ev.stopPropagation(); button.disabled = true;
      const job = st.jobs.get(id);
      try {
        if (job && FAILED.includes(job.state)) await window.api('retry', {id: job.id});
        else {
          const r = await window.api(source + '-download-add', {id});
          ctl.message = r.created ? '' : 'Bereits eingereiht oder offline verfügbar';
          if (r.created) window.notice?.('„' + (title || 'Titel') + '“ ' + (ctl.night ? 'ist für heute Nacht vorgemerkt.' : 'wird offline gespeichert (' + st.days + ' Tage).'));
        }
      } catch (e) { ctl.message = 'Kein Download gestartet: ' + e.message; note.textContent = ctl.message; note.className = 'atlas-offline-note nk-warning'; button.disabled = false; return; }
      await refresh(source);
    };
    cancel.onclick = async ev => {
      ev.stopPropagation(); const job = st.jobs.get(id); if (!job) return;
      cancel.disabled = true;
      try { await window.api(SOURCES[source].action, {id: job.id, action: 'cancel'}); } catch (e) { note.textContent = e.message; }
      cancel.disabled = false; await refresh(source);
    };
    node.append(button, cancel, note); st.controls.add(ctl); paint(ctl); schedule(source);
    return node;
  }
  window.AtlasOffline = {control, refresh, job: (source, id) => state[source]?.jobs.get(id),
    onChange: (source, fn) => state[source]?.listeners.add(fn)};
})();
