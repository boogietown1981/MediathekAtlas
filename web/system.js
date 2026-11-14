/* 0.5.99: Verwaltung → System. One reading of the machine per request (system_monitor.py); the page asks
   every five seconds only while this view is open, so a NAS or an old Mac pays nothing otherwise. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const box = $('system');
  if (!box) return;
  const el = (tag, value, cls) => { const n = document.createElement(tag); if (value !== undefined) n.textContent = String(value); if (cls) n.className = cls; return n; };
  const num = (v, digits) => Number(v).toLocaleString('de-DE', {maximumFractionDigits: digits === undefined ? 1 : digits});
  const size = n => n === null || n === undefined ? 'unbekannt' : n >= 1073741824 ? num(n / 1073741824) + ' GB' : n >= 1048576 ? num(n / 1048576, 0) + ' MB' : num(n / 1024, 0) + ' KB';
  const span = s => s >= 86400 ? Math.floor(s / 86400) + ' T ' + Math.floor(s % 86400 / 3600) + ' h' : s >= 3600 ? Math.floor(s / 3600) + ' h ' + Math.floor(s % 3600 / 60) + ' min' : Math.max(1, Math.floor(s / 60)) + ' min';
  let timer = 0;
  function metric(label, value, note) {
    const card = el('div', undefined, 'storage-metric');
    card.append(el('span', label), el('strong', value));
    if (note) card.append(el('small', note));
    return card;
  }
  function list(node, rows) {
    node.replaceChildren();
    for (const [name, value] of rows) node.append(el('dt', name), el('dd', value));
  }
  function paint(d) {
    $('system-hints').replaceChildren(...(d.hints || []).map(h => el('p', h.text, 'system-hint' + (h.level === 'error' ? ' error' : ''))));
    const perCore = d.load ? d.load[0] / d.cores : null;
    const used = d.memory_total && d.memory_available !== null ? d.memory_total - d.memory_available : null;
    $('system-metrics').replaceChildren(
      metric('Prozessorlast', d.load ? num(d.load[0], 2) : 'unbekannt', d.load ? d.cores + (d.cores === 1 ? ' Kern' : ' Kerne') + ' · ' + num(perCore * 100, 0) + ' % je Kern · 5 min: ' + num(d.load[1], 2) : 'dieses System nennt keine Last'),
      metric('Arbeitsspeicher frei', d.memory_available === null || d.memory_available === undefined ? 'unbekannt' : size(d.memory_available), d.memory_total ? 'von ' + size(d.memory_total) + (used !== null ? ' · ' + num(used / d.memory_total * 100, 0) + ' % belegt' : '') : ''),
      metric('MediathekAtlas belegt', size(d.process_memory), d.threads + ' Threads · läuft seit ' + span(d.uptime_seconds)),
      metric('Temperatur', d.temperature === null || d.temperature === undefined ? 'unbekannt' : num(d.temperature, 0) + ' °C', d.temperature === null || d.temperature === undefined ? 'dieses System meldet keinen Fühler' : 'höchster gemeldeter Fühler'));
    $('system-drives').replaceChildren(...(d.drives || []).map(g => {
      const row = el('div', undefined, 'storage-source'), bar = el('div', undefined, 'storage-bar used'), fill = el('i');
      const share = g.total_bytes ? 1 - g.free_bytes / g.total_bytes : 0;
      fill.style.width = Math.max(2, Math.round(share * 100)) + '%';
      if (share > 0.95) bar.className = 'storage-bar full'; else if (share > 0.85) bar.className = 'storage-bar tight';
      bar.append(fill); row.title = g.path;
      row.append(el('span', g.label), bar, el('strong', g.total_bytes ? size(g.free_bytes) + ' frei' : 'unbekannt'), el('small', g.total_bytes ? 'von ' + size(g.total_bytes) : ''));
      return row;
    }));
    const a = d.activity || {};
    list($('system-activity'), [
      ['Downloads laufen', a.downloads_running || 0], ['Downloads warten', a.downloads_waiting || 0], ['Umwandlungen', a.encoder_active || 0],
      ['Dateiprüfung (Archivnachweise)', a.receipt_task ? 'läuft' : 'nein'], ['Verbund', a.verbund ? a.verbund_systems + (a.verbund_systems === 1 ? ' System' : ' Systeme') : 'aus'],
      ['Hintergrundaufgaben', a.background === false ? 'abgeschaltet' : 'aktiv'],
      ['Katalogabrufe laufen', a.planner && a.planner.catalog_running && a.planner.catalog_running.length ? a.planner.catalog_running.join(', ') : 'keine']]);
    // 0.6.0: planner profile (planner.py)
    const p = a.planner || {};
    const pick = $('system-profile');
    if (pick && document.activeElement !== pick) pick.value = p.choice || 'auto';
    if ($('system-profile-note')) $('system-profile-note').textContent = p.label
      ? 'Aktiv: ' + p.label + ' · höchstens ' + p.max_syncs + (p.max_syncs === 1 ? ' Katalogabruf' : ' Katalogabrufe') + ' und ' + p.enrich_workers + (p.enrich_workers === 1 ? ' Abgleich' : ' Abgleiche') + ' gleichzeitig. Von Hand gestartete Abrufe laufen immer sofort.'
      : '';
    list($('system-facts'), [['Betriebssystem', d.system + ' ' + d.release], ['Bauart', d.machine || 'unbekannt'], ['Python', d.python], ['Prozessorkerne', d.cores]]);
    const db = d.databases || {files: []};
    list($('system-databases'), [['Zusammen (' + (db.count || 0) + ')', size(db.total_bytes || 0)], ...db.files.map(f => [f.name, size(f.bytes)])]);
    $('system-status').className = 'muted';
    $('system-status').textContent = 'Gemessen um ' + new Date(d.time * 1000).toLocaleTimeString('de-DE') + '. Aktualisiert sich alle fünf Sekunden, solange diese Ansicht offen ist.';
  }
  async function load() {
    clearTimeout(timer);
    if (box.hidden) return;
    try { paint(await window.api('system-monitor')); }
    catch (e) { $('system-status').textContent = 'Systemwerte konnten nicht gelesen werden: ' + e.message; $('system-status').className = 'notice-error'; }
    if (!box.hidden && !document.hidden) timer = setTimeout(load, 5000);
  }
  // 0.6.2: device keys for API v1 (api_keys.py); read when the view opens, not with every measurement
  const keyStatus = (text, bad) => { const n = $('system-key-status'); if (n) { n.textContent = text; n.className = bad ? 'notice-error' : 'muted'; } };
  function paintKeys(d) {
    const node = $('system-key-list');
    if (!node) return;
    const day = t => t ? new Date(t * 1000).toLocaleDateString('de-DE') : 'noch nie';
    node.replaceChildren(...(d.items || []).map(k => {
      const row = el('div', undefined, 'system-key-row'), del = el('button', 'Löschen');
      del.type = 'button'; del.title = 'Schlüssel zurückziehen: Das Gerät hat sofort keinen Zugriff mehr';
      del.onclick = async () => {
        if (del.dataset.sure !== '1') { del.dataset.sure = '1'; del.textContent = 'Wirklich löschen?'; setTimeout(() => { del.dataset.sure = ''; del.textContent = 'Löschen'; }, 4000); return; }
        try { paintKeys(await window.api('api-key-revoke', {id: k.id})); keyStatus('Schlüssel „' + k.name + '“ gelöscht.'); }
        catch (e) { keyStatus('Löschen fehlgeschlagen: ' + e.message, true); }
      };
      row.append(el('strong', k.name), el('small', 'erstellt ' + day(k.created) + ' · zuletzt benutzt ' + day(k.last_used)), del);
      return row;
    }));
    if (!(d.items || []).length) node.append(el('p', 'Noch kein Geräteschlüssel. Die Schnittstelle ist von außen geschlossen.', 'muted'));
  }
  async function loadKeys() {
    if (!$('system-keys')) return;
    try { paintKeys(await window.api('api-keys')); }
    catch (e) { keyStatus('Geräteschlüssel konnten nicht gelesen werden: ' + e.message, true); }
  }
  if ($('system-key-form')) $('system-key-form').onsubmit = async e => {
    e.preventDefault();
    const name = $('system-key-name').value.trim();
    if (!name) { keyStatus('Bitte einen Namen für das Gerät angeben.', true); return; }
    try {
      const d = await window.api('api-key-create', {name});
      $('system-key-value').textContent = d.created.key; $('system-key-new').hidden = false; $('system-key-name').value = '';
      paintKeys(d); keyStatus('Schlüssel für „' + d.created.name + '“ erstellt. Jetzt im Gerät eintragen; später ist er nicht mehr sichtbar.');
    } catch (err) { keyStatus('Schlüssel konnte nicht erstellt werden: ' + err.message, true); }
  };
  if ($('system-key-copy')) $('system-key-copy').onclick = async () => {
    try { await navigator.clipboard.writeText($('system-key-value').textContent); keyStatus('Schlüssel kopiert.'); }
    catch (e) { keyStatus('Kopieren nicht möglich. Bitte den Schlüssel markieren und von Hand kopieren.', true); }
  };
  $('system-refresh').onclick = () => load();
  if ($('system-profile')) $('system-profile').onchange = async e => {
    try { await window.api('settings', {background_profile: e.target.value}); load(); }
    catch (err) { $('system-status').textContent = 'Profil konnte nicht gespeichert werden: ' + err.message; $('system-status').className = 'notice-error'; }
  };
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  document.addEventListener('atlas-view', e => { if (e.detail && e.detail.view === 'system') { load(); loadKeys(); $('system-key-new').hidden = true; } else clearTimeout(timer); });
})();
