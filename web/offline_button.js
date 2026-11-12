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
    rakuten: {name: 'Rakuten TV', action: 'offline-download-action'},
    youtube: {name: 'YouTube', action: 'offline-download-action'}};
  const ACTIVE = ['queued', 'downloading', 'tagging'], FAILED = ['error', 'cancelled', 'interrupted'];
  const LABELS = {queued: 'Vorgemerkt', downloading: 'Lädt', tagging: 'MKV wird erstellt', done: 'Offline verfügbar',
    error: 'Fehlgeschlagen', cancelled: 'Abgebrochen', interrupted: 'Unterbrochen'};
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const day = ts => new Date(ts * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
  const clock = ts => new Date(ts * 1000).toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});
  const PROTECTED = 'Kopiergeschützt (DRM): nur im JustWatch-Player, keine Offline-Kopie möglich.';
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
    st.tool = data.tool_hint ? data.tool_hint : data.ffmpeg === false ? 'ffmpeg fehlt in dieser Installation' : data.ytdl?.ok === false ? 'ytdl-nightly fehlt in dieser Installation' : '';
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

  /* 0.5.63 (Björn, 12.11.2026): before an offline copy the resolution and - when a title is offered
     by several providers - the provider can be chosen. One small dialogue for every platform; the
     last resolution is remembered on this device. Resolves to {source, id, quality} or null. */
  const HEIGHT_HINT = {2160: '4K, sehr große Datei', 1080: 'Full HD', 720: 'HD', 480: 'kleine Datei, für langsames Internet', 360: 'sehr kleine Datei'};
  function lastQuality() { try { const v = localStorage.getItem('atlas-download-quality') || 'best'; return /^(best|\d{3,4})$/.test(v) ? v : 'best'; } catch (e) { return 'best'; } }
  function choose(ctl, title, alternatives) {
    return new Promise(done => {
      const offers = [{source: ctl.source, id: ctl.id}, ...(alternatives || []).filter(o => state[o.source] && o.id && !(o.source === ctl.source && o.id === ctl.id))];
      const box = make('dialog', undefined, 'atlas-offline-choice'); box.setAttribute('aria-label', 'Offline speichern: Auflösung und Anbieter');
      const form = make('form'); form.method = 'dialog';
      form.append(make('h3', 'Offline speichern'), make('p', title || 'Titel', 'atlas-offline-choice-title'));
      let chosen = offers[0];
      const info = make('small', '', 'muted atlas-offline-choice-info');
      const select = make('select'); select.setAttribute('aria-label', 'Auflösung');
      const fill = heights => {
        const keep = select.value || lastQuality();
        select.replaceChildren(new Option('Beste verfügbare', 'best'), ...heights.map(h => new Option('höchstens ' + h + 'p' + (HEIGHT_HINT[h] ? ' (' + HEIGHT_HINT[h] + ')' : ''), String(h))));
        select.value = [...select.options].some(o => o.value === keep) ? keep : 'best';
      };
      fill([2160, 1080, 720, 480, 360]);
      let asked = 0;
      const loadLevels = async () => {
        const mine = ++asked; info.textContent = 'Verfügbare Stufen bei ' + SOURCES[chosen.source].name + ' werden abgefragt …';
        try {
          const d = await window.api('download-options?' + new URLSearchParams({source: chosen.source, id: chosen.id}));
          if (mine !== asked || !box.isConnected) return;
          const levels = (d.levels || []).filter(l => l.height > 0);
          info.textContent = levels.length ? 'Bei ' + SOURCES[chosen.source].name + ' verfügbar: ' + levels.map(l => l.height + 'p' + (l.bandwidth ? ' (' + (l.bandwidth / 1e6).toFixed(1).replace('.', ',') + ' Mbit/s)' : '')).join(' · ') + '. Gibt es die gewählte Stufe nicht, wird die nächstkleinere geladen.' : (d.note || '');
        } catch (e) { if (mine === asked) info.textContent = 'Stufen nicht abfragbar: ' + e.message; }
      };
      if (offers.length > 1) {
        const group = make('fieldset', undefined, 'atlas-offline-choice-providers'); group.append(make('legend', 'Anbieter'));
        offers.forEach((o, i) => {
          const label = make('label'), radio = make('input'); radio.type = 'radio'; radio.name = 'atlas-offline-provider'; radio.checked = i === 0;
          const job = state[o.source].jobs.get(o.id), busy = job && (ACTIVE.includes(job.state) || job.state === 'done');
          radio.disabled = !!busy || !!state[o.source].tool;
          radio.onchange = () => { chosen = o; loadLevels(); };
          label.append(radio, ' ' + SOURCES[o.source].name + (busy ? ' · ' + LABELS[job.state] : state[o.source].tool ? ' · ' + state[o.source].tool : ''));
          group.append(label);
        });
        form.append(group);
      }
      const row = make('label', 'Auflösung ', 'atlas-offline-choice-quality'); row.append(select);
      const buttons = make('div', undefined, 'atlas-offline-choice-buttons');
      const ok = make('button', '⬇ Speichern', 'primary'); ok.type = 'submit'; ok.value = 'ok';
      const no = make('button', 'Abbrechen'); no.type = 'button'; no.onclick = () => box.close('');
      buttons.append(ok, no);
      form.append(row, info, make('small', 'Die Kopie ist ' + state[chosen.source].days + ' Tage offline nutzbar. Die Auswahl gilt für diesen Titel; die Auflösung wird für das nächste Mal gemerkt.', 'muted'), buttons);
      box.append(form);
      box.addEventListener('click', ev => ev.stopPropagation());
      box.addEventListener('close', () => {
        const result = box.returnValue === 'ok' ? {source: chosen.source, id: chosen.id, quality: select.value} : null;
        if (result) { try { localStorage.setItem('atlas-download-quality', result.quality); } catch (e) { /* private mode */ } }
        box.remove(); done(result);
      });
      // Inside an open dialogue (title page) the new one must be its child to lie on top in every browser.
      (ctl.node.closest('dialog[open]') || document.body).append(box);
      box.showModal(); ok.focus(); loadLevels();
    });
  }

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
          const pick = await choose(ctl, title, typeof opts?.alternatives === 'function' ? opts.alternatives() : opts?.alternatives);
          if (!pick) { button.disabled = false; paint(ctl); return; }
          const r = await window.api(pick.source + '-download-add', {id: pick.id, quality: pick.quality});
          const other = pick.source !== source || pick.id !== id, how = pick.quality === 'best' ? 'beste verfügbare Auflösung' : 'höchstens ' + pick.quality + 'p';
          ctl.message = r.created ? (other ? 'Wird von ' + SOURCES[pick.source].name + ' gespeichert.' : '') : 'Bereits eingereiht oder offline verfügbar';
          if (r.created) window.notice?.('„' + (title || 'Titel') + '“ ' + (ctl.night && !other ? 'ist für heute Nacht vorgemerkt' : 'wird offline gespeichert') + ' (' + SOURCES[pick.source].name + ', ' + how + ', ' + state[pick.source].days + ' Tage).');
          if (other) refresh(pick.source);
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
  /* 0.5.70 (Björn, 12.11.2026): on the page of a film the possible versions are offered directly,
     one click each. The provider's own levels when it names them, otherwise the usual limits. */
  function versions(source, id, title) {
    const st = state[source]; if (!st || !id) return null;
    const box = make('div', undefined, 'atlas-offline-versions'), row = make('div', undefined, 'atlas-offline-version-row'), note = make('small', 'Fassungen werden abgefragt …', 'muted');
    box.append(row, note);
    const add = (label, quality, hint) => {
      const b = make('button', '⬇ ' + label, 'atlas-offline-version'); b.type = 'button'; if (hint) b.title = hint;
      b.onclick = async () => {
        for (const x of row.querySelectorAll('button')) x.disabled = true;
        try {
          const r = await window.api(source + '-download-add', {id, quality});
          note.textContent = r.created ? '„' + label + '“ wird gespeichert (' + st.days + ' Tage offline nutzbar).' : 'Dieser Titel ist bereits eingereiht oder offline verfügbar.';
          if (r.created) window.notice?.('„' + (title || 'Titel') + '“ wird offline gespeichert (' + SOURCES[source].name + ', ' + label + ').');
          refresh(source);
        } catch (e) { note.textContent = 'Kein Download gestartet: ' + e.message; note.className = 'nk-warning'; for (const x of row.querySelectorAll('button')) x.disabled = false; }
      };
      row.append(b);
    };
    const fill = (levels, text) => {
      row.replaceChildren(); add('Beste verfügbare', 'best');
      if (levels.length) for (const l of levels) add(l.height + 'p' + (l.bandwidth ? ' · ' + (l.bandwidth / 1e6).toFixed(1).replace('.', ',') + ' Mbit/s' : ''), String(l.height), HEIGHT_HINT[l.height] || '');
      else for (const h of [1080, 720, 480, 360]) add('höchstens ' + h + 'p', String(h), HEIGHT_HINT[h]);
      note.textContent = text;
      const job = st.jobs.get(id);
      if (st.tool || (job && (ACTIVE.includes(job.state) || job.state === 'done'))) { for (const x of row.querySelectorAll('button')) x.disabled = true; note.textContent = st.tool || 'Bereits eingereiht oder offline verfügbar.'; }
    };
    fill([], 'Fassungen werden abgefragt …');
    window.api('download-options?' + new URLSearchParams({source, id})).then(d => { if (!box.isConnected) return; const levels = (d.levels || []).filter(l => l.height > 0);
      fill(levels, levels.length ? 'Fassungen von ' + SOURCES[source].name + '. Ein Klick speichert die Fassung ' + st.days + ' Tage offline.' : (d.note || '')); })
      .catch(e => { if (box.isConnected) note.textContent = 'Fassungen nicht abfragbar: ' + e.message; });
    return box;
  }
  /* 0.5.52: the same short reason wherever a title cannot be saved because it is copy protected. */
  function protectedNote() { const n = make('small', '🔒 ' + PROTECTED, 'atlas-offline-note atlas-offline-protected muted'); n.title = 'JustWatch liefert diesen Titel nur verschlüsselt (Widevine/PlayReady/FairPlay) an den eigenen Player.'; return n; }
  window.AtlasOffline = {control, refresh, protectedNote, versions, job: (source, id) => state[source]?.jobs.get(id),
    onChange: (source, fn) => state[source]?.listeners.add(fn)};
})();
