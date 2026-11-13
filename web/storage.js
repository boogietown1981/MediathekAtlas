/* 0.5.81: Verwaltung → Speicher (0.5.94: plus Umwandeln). Used space of the downloads, a budget and a cleanup suggestion
   after the rules taken from HomeTube (storage_policy.py). MediathekAtlas deletes nothing by itself
   here: a file goes only after "Löschen" for exactly that file and a confirmation. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const box = $('storage');
  if (!box) return;
  const el = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = String(value);
    if (cls) n.className = cls;
    return n;
  };
  const size = n => {
    n = Number(n || 0);
    return n >= 1073741824 ? (n / 1073741824).toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' GB'
      : (n / 1048576).toLocaleString('de-DE', {maximumFractionDigits: n >= 104857600 ? 0 : 1}) + ' MB';
  };
  const day = t => t ? new Date(t * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'}) : '';
  const WHY = {pinned: 'Angeheftet', favorite: 'Auf der Merkliste', watched: 'Kürzlich gesehen', 'new': 'Neu geladen'};
  let data = null;

  function metric(label, value, note) {
    const card = el('div', undefined, 'storage-metric');
    card.append(el('span', label), el('strong', value));
    if (note) card.append(el('small', note));
    return card;
  }
  function paint(d) {
    data = d;
    const s = d.settings || {};
    $('storage-budget').value = s.budget_gb ? String(s.budget_gb).replace('.', ',') : '';
    $('storage-days').value = String(s.protect_days || 90);
    const disk = d.disk || {};
    $('storage-metrics').replaceChildren(
      metric('Belegt durch Downloads', size(d.used_bytes), d.files + (d.files === 1 ? ' Datei' : ' Dateien')),
      metric('Frei auf dem Laufwerk', disk.total_bytes ? size(disk.free_bytes) : 'unbekannt', disk.total_bytes ? 'von ' + size(disk.total_bytes) : d.download_dir),
      metric('Platzbudget', d.budget_bytes ? size(d.budget_bytes) : 'keins', d.budget_bytes ? (d.over_budget_bytes ? size(d.over_budget_bytes) + ' darüber' : size(d.budget_bytes - d.used_bytes) + ' frei im Budget') : 'ohne Budget gibt es keinen Vorschlag'),
      metric('Vorschlag zum Aufräumen', d.suggested ? size(d.suggested_bytes) : '–', d.suggested ? d.suggested + (d.suggested === 1 ? ' Datei' : ' Dateien') : 'nichts vorgeschlagen'));
    const status = $('storage-status');
    status.className = 'muted';
    if (!d.budget_bytes) status.textContent = 'Kein Platzbudget gesetzt. Die Liste zeigt die größten Dateien zuerst.';
    else if (!d.over_budget_bytes) status.textContent = 'Die Downloads liegen im Budget. Es gibt nichts aufzuräumen.';
    else if (d.blocked) { status.textContent = 'Über dem Budget um ' + size(d.over_budget_bytes) + '. Der Vorschlag reicht nicht aus, weil die übrigen Dateien geschützt sind (Merkliste, angeheftet, kürzlich gesehen oder neu).'; status.className = 'notice-error'; }
    else status.textContent = 'Über dem Budget um ' + size(d.over_budget_bytes) + (d.suggested === 1 ? '. Die markierte Datei würde genügen.' : '. Die ' + d.suggested + ' markierten Dateien würden genügen.') + ' Gelöscht wird nur, was du selbst löschst.';
    if (d.missing) status.textContent += ' ' + d.missing + ' fertige Downloads liegen nicht mehr am gespeicherten Ort und zählen nicht mit.';
    const top = Math.max(1, ...(d.sources || []).map(g => g.bytes));
    $('storage-sources').replaceChildren(...(d.sources || []).map(g => {
      const row = el('div', undefined, 'storage-source'), bar = el('div', undefined, 'storage-bar'), fill = el('i');
      fill.style.width = Math.max(2, Math.round(g.bytes / top * 100)) + '%'; bar.append(fill);
      row.append(el('span', g.source), bar, el('strong', size(g.bytes)), el('small', g.files + (g.files === 1 ? ' Datei' : ' Dateien')));
      return row;
    }));
    const body = $('storage-rows');
    body.replaceChildren();
    if (!(d.items || []).length) { const tr = el('tr'), td = el('td', 'Noch keine fertigen Downloads.'); td.colSpan = 7; td.className = 'muted'; tr.append(td); body.append(tr); }
    for (const item of d.items || []) body.append(line(item));
    $('storage-more').textContent = d.files > d.shown ? 'Angezeigt werden ' + d.shown + ' von ' + d.files + ' Dateien (Vorschläge und die größten zuerst).' : '';
  }
  function line(item) {
    const tr = el('tr'); if (item.suggested) tr.className = 'storage-suggested';
    const name = el('td'); name.append(el('strong', item.title + (item.year ? ' (' + item.year + ')' : '')), el('small', item.file)); name.title = item.folder;
    const state = el('td');
    state.append(el('span', item.suggested ? 'Vorschlag' : WHY[item.protection] || 'Kein Schutz', 'storage-tag' + (item.suggested ? ' suggest' : item.protection ? ' safe' : '')));
    if (item.offline_until) state.append(el('small', 'läuft ab am ' + day(item.offline_until)));
    const actions = el('td', undefined, 'storage-actions');
    const pin = el('button', item.pinned ? 'Lösen' : 'Anheften'); pin.type = 'button';
    pin.title = item.pinned ? 'Anheftung lösen; die Datei darf wieder vorgeschlagen werden' : 'Anheften: nie zum Löschen vorschlagen, Löschen hier gesperrt';
    pin.onclick = () => window.busy(pin, async () => {
      await window.api('watch-mark', {key: item.watch_key, pinned: !item.pinned, info: {title: item.title, year: item.year, source: 'download', ref: {job: item.id}}});
      await load();
    });
    const del = el('button', 'Löschen', 'danger'); del.type = 'button'; del.disabled = !!item.pinned;
    del.title = item.pinned ? 'Angeheftet: erst lösen' : 'Diese Datei samt Begleitdateien (NFO, Bilder) löschen';
    del.onclick = () => {
      if (!confirm('„' + item.title + '“ (' + size(item.size_bytes) + ') endgültig löschen?\n\n' + item.file + '\n\nDie Datei wird vom Laufwerk entfernt, nicht in den Papierkorb gelegt.')) return;
      window.busy(del, async () => {
        const r = await window.api('storage-delete', {id: item.id, confirm: true});
        window.notice?.('Gelöscht, ' + size(r.freed_bytes) + ' frei.');
        paint(r.storage);
      });
    };
    const enc = el('button', 'Umwandeln'); enc.type = 'button';
    enc.title = 'Auf eine kleinere Bildgröße umrechnen (ffmpeg). Das Original bleibt, wenn du es nicht ausdrücklich ersetzen lässt.';
    enc.onclick = () => askEncode(item);
    actions.append(enc, pin, del);
    tr.append(name, el('td', item.source), el('td', size(item.size_bytes), 'num'), el('td', day(item.stored_at)),
      el('td', item.watched_done ? 'zu Ende, ' + day(item.last_watched) : item.last_watched ? day(item.last_watched) : 'noch nie'), state, actions);
    return tr;
  }
  /* 0.5.94: Umwandeln (encoder.py). One conversion at a time on the server; this block only shows the queue. */
  const STATE = {queued: 'wartet', running: 'läuft', done: 'fertig', error: 'fehlgeschlagen', cancelled: 'abgebrochen'};
  let encoder = null, encTimer = 0, encItem = null;
  function paintEncoder(d) {
    const wasActive = encoder && encoder.active > 0;
    encoder = d;
    const status = $('encoder-status');
    status.className = d.available ? 'muted' : 'notice-error';
    status.textContent = !d.available ? 'ffmpeg oder ffprobe fehlt auf diesem System. Ohne beide ist keine Umwandlung möglich (siehe Verwaltung → Diagnose, Werkzeuge).'
      : d.active ? d.active + (d.active === 1 ? ' Umwandlung' : ' Umwandlungen') + ' in Arbeit oder in der Warteschlange.' : d.jobs.length ? 'Keine Umwandlung in Arbeit.' : 'Noch keine Umwandlung gestartet.';
    $('encoder-clear').hidden = !d.jobs.some(j => !['queued', 'running'].includes(j.state));
    $('encoder-jobs').replaceChildren(...d.jobs.map(job => {
      const row = el('div', undefined, 'encoder-job ' + job.state), text = el('div');
      text.append(el('strong', job.title || job.file), el('small', job.file + ' → ' + job.target + (job.replace ? ' (ersetzt das Original)' : '')));
      const bar = el('div', undefined, 'storage-bar'), fill = el('i');
      const percent = job.state === 'done' ? 100 : Math.round((job.progress || 0) * 100);
      fill.style.width = percent + '%'; bar.append(fill);
      let note = STATE[job.state] || job.state;
      if (job.state === 'running') note += ' · ' + percent + ' %';
      if (job.state === 'done' && job.result_bytes) note += ' · ' + size(job.source_bytes) + ' → ' + size(job.result_bytes);
      if (job.state === 'error' && job.error) note += ': ' + job.error;
      row.append(text, el('span', job.label, 'storage-tag'), bar, el('span', note, 'encoder-note'));
      if (job.state === 'queued' || job.state === 'running') {
        const stop = el('button', 'Abbrechen'); stop.type = 'button'; stop.title = 'Umwandlung beenden. Das Original bleibt unberührt.';
        stop.onclick = () => window.busy(stop, async () => paintEncoder(await window.api('encoder-cancel', {id: job.id})));
        row.append(stop);
      } else row.append(el('span'));
      return row;
    }));
    clearTimeout(encTimer);
    if (d.active > 0 && !box.hidden) encTimer = setTimeout(loadEncoder, 3000);
    if (wasActive && !d.active) load();
  }
  async function loadEncoder() {
    try { paintEncoder(await window.api('encoder')); }
    catch (e) { $('encoder-status').textContent = 'Umwandlungen konnten nicht gelesen werden: ' + e.message; $('encoder-status').className = 'notice-error'; }
  }
  function askEncode(item) {
    if (!encoder || !encoder.available) { window.notice?.('ffmpeg oder ffprobe fehlt auf diesem System.', 'error'); return; }
    encItem = item;
    const fill = (select, list, keep) => { select.replaceChildren(...list.map(o => { const n = el('option', o.label); n.value = o.id; return n; })); if (keep) select.value = keep; };
    fill($('encoder-profile'), encoder.profiles, '720'); fill($('encoder-speed'), encoder.speeds, 'fast');
    $('encoder-replace').checked = false;
    $('encoder-what').textContent = '„' + item.title + '“ · ' + item.file + ' · ' + size(item.size_bytes);
    $('encoder-dialog').showModal();
  }
  $('encoder-close').onclick = () => $('encoder-dialog').close();
  $('encoder-form').addEventListener('submit', event => {
    event.preventDefault();
    const item = encItem, replace = $('encoder-replace').checked;
    if (!item) return;
    if (replace && !confirm('„' + item.title + '“ nach der Umwandlung ersetzen?\n\n' + item.file + '\n\nDas Original wird entfernt, sobald das Ergebnis geprüft ist (Bildgröße, Laufzeit, Tonspuren). Schlägt die Prüfung fehl, bleibt es erhalten.')) return;
    window.busy($('encoder-submit'), async () => {
      const r = await window.api('encoder-add', {id: item.id, profile: $('encoder-profile').value, speed: $('encoder-speed').value, replace, confirm: replace});
      $('encoder-dialog').close();
      window.notice?.('Umwandlung vorgemerkt.');
      paintEncoder(r.encoder);
    });
  });
  $('encoder-clear').onclick = () => window.busy($('encoder-clear'), async () => paintEncoder(await window.api('encoder-clear', {})));
  async function load() {
    loadEncoder();
    $('storage-status').textContent = 'Speicher wird gemessen …';
    try { paint(await window.api('storage')); }
    catch (e) { $('storage-status').textContent = 'Speicher konnte nicht gemessen werden: ' + e.message; $('storage-status').className = 'notice-error'; }
  }
  $('storage-form').addEventListener('submit', event => {
    event.preventDefault();
    const budget = $('storage-budget').value.trim().replace(',', '.');
    if (budget !== '' && !(Number(budget) >= 0)) { window.notice?.('Das Platzbudget muss eine Zahl in GB sein, z. B. 500.', 'error'); return; }
    window.busy($('storage-save'), async () => {
      paint(await window.api('storage-settings', {budget_gb: budget === '' ? 0 : Number(budget), protect_days: Number($('storage-days').value)}));
      window.notice?.('Speicherregeln gespeichert.');
    });
  });
  $('storage-refresh').onclick = () => load();
  document.addEventListener('atlas-view', e => { if (e.detail && e.detail.view === 'storage') load(); });
})();
