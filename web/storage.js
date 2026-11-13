/* 0.5.81: Verwaltung → Speicher. Used space of the downloads, a budget and a cleanup suggestion
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
    actions.append(pin, del);
    tr.append(name, el('td', item.source), el('td', size(item.size_bytes), 'num'), el('td', day(item.stored_at)),
      el('td', item.watched_done ? 'zu Ende, ' + day(item.last_watched) : item.last_watched ? day(item.last_watched) : 'noch nie'), state, actions);
    return tr;
  }
  async function load() {
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
