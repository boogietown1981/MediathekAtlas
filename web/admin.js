/* 0.5.55 · Verwaltung (Björn, 12.11.2026): the dashboard shows films and series only; everything
   that manages the app lives here.
   - Aufgaben: every background task with its state; pause, continue, start now, priority.
   - Darstellung: what tiles and title pages show (web/display.js applies the choices).
   - Platform tabs: catalogue first, the administration of the platform (catalogue run, stock and
     work assignment, sources) collapsed below it. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  const num = n => Number(n || 0).toLocaleString('de-DE');
  const when = t => t ? new Date(t * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';

  // ---------------------------------------------------------------- platform tabs
  const PLATFORMS = {netzkino: 'Netzkino', pluto: 'Pluto TV', justwatch: 'JustWatch TV', rakuten: 'Rakuten TV', youtube: 'YouTube', joyn: 'Joyn'};
  function arrangePlatform(key) {
    const section = $(key);
    if (!section || $(key + '-admin')) return;
    const admin = make('details', undefined, 'panel platform-admin');
    admin.id = key + '-admin';
    admin.append(make('summary', '⚙ ' + PLATFORMS[key] + ' verwalten · Katalogabruf, Bestand und Werkzuordnung'));
    // Panels (catalogue run, sources, manual links) move as live nodes: IDs and handlers stay.
    for (const child of [...section.children])
      if (child.classList.contains('panel') || (key === 'netzkino' && child.matches('p.muted'))) admin.append(child);
    section.append(admin);
    // 0.5.60 (Björn, 12.11.2026): the daily refresh looked "not saved" because its switch sits in
    // the closed block. One line above the catalogue says whether it is on and when the
    // catalogue was loaded; "Verwalten" opens the block.
    const brief = make('p', undefined, 'platform-brief'), text = make('span'), open = make('button', 'Verwalten');
    brief.id = key + '-brief'; open.type = 'button';
    open.onclick = () => { admin.open = true; admin.scrollIntoView({behavior: 'smooth', block: 'start'}); };
    brief.append(text, open);
    section.prepend(brief);
    const source = $(key === 'netzkino' ? 'netzkino-sync-summary' : key + '-summary'), auto = $(key + '-auto');
    const paint = () => {
      const state = (source?.textContent || '').trim();
      text.textContent = 'Automatische Aktualisierung alle 24 Stunden: ' + (auto?.checked ? 'an' : 'aus') + (state ? ' · ' + state : '');
    };
    if (source) new MutationObserver(paint).observe(source, {childList: true, characterData: true, subtree: true});
    auto?.addEventListener('change', paint);
    paint();
    // YouTube without a key or a source: the setup is the first thing to do, so it stays open.
    admin.addEventListener('toggle', () => { if (admin.open) window.AtlasPlatformBoard?.mount(key); });
  }
  for (const key of Object.keys(PLATFORMS)) arrangePlatform(key);
  window.AtlasPlatformLayout = {arrange: arrangePlatform, open: key => { const d = $(key + '-admin'); if (d) d.open = true; }};

  // ---------------------------------------------------------------- tasks
  let taskTimer = 0, taskSeq = 0;
  const visible = id => $(id) && !$(id).hidden;
  const say = (id, text, error) => { const n = $(id); if (n) { n.textContent = text || ''; n.classList.toggle('netzkino-error', !!error); } };

  function stateOf(task) {
    const d = task.detail || {};
    if (d.error) return ['error', 'Fehler', d.error];
    if (task.paused) return ['paused', 'Pausiert', ''];
    if (d.running) return ['running', 'Läuft', ''];
    if (d.auto === false && !task.id.startsWith('catalog:')) return ['off', 'Aus', 'In den Einstellungen ausgeschaltet'];
    if (task.id.startsWith('catalog:') && d.auto === false) return ['manual', 'Nur von Hand', 'Automatischer Abruf ist auf der Plattform ausgeschaltet'];
    if (task.id.startsWith('enrich:') && d.total && d.checked >= d.total) return ['done', 'Fertig', ''];
    return ['ready', 'Aktiv', ''];
  }
  function describe(task) {
    const d = task.detail || {}, out = [];
    if (task.id === 'filmlist') {
      const phase = {waiting: 'wartet auf den nächsten Abgleich', complete: 'Katalog aktuell', importing: 'Katalog wird eingelesen', paused: 'Abgleich angehalten', error: 'letzter Abgleich fehlgeschlagen'}[d.phase] || d.phase;
      if (phase) out.push(phase);
      if (d.last_complete) out.push('zuletzt ' + when(d.last_complete));
    } else if (task.id === 'recognition') {
      out.push(num(d.workers) + ' Worker');
      if (d.checked_session) out.push(num(d.checked_session) + ' Abgleiche seit Start');
      if (d.last_title) out.push('zuletzt: ' + d.last_title);
    } else if (task.id === 'episodes') out.push(num(d.workers) + ' Worker');
    else if (task.id === 'imdb') {
      if (d.phase) out.push(({ready: 'Archiv bereit', downloading: 'Datensätze werden geladen', importing: 'Archiv wird aufgebaut', indexing: 'Index wird erstellt'})[d.phase] || d.phase);
      if (d.updated) out.push('Stand ' + when(d.updated));
      if (d.next_update) out.push('nächster Abruf ' + when(d.next_update));
    } else if (task.id === 'downloads') {
      out.push(num(d.active) + ' laufen', num(d.queued) + ' warten');
      if (d.held) out.push(num(d.held) + ' zurückgestellt');
      if (d.night) out.push(num(d.night) + ' für die Nacht vorgemerkt');
      if (d.failed) out.push(num(d.failed) + ' fehlgeschlagen');
    } else if (task.id.startsWith('catalog:')) {
      out.push(num(d.titles) + ' Titel');
      if (d.last_success) out.push('Stand ' + when(d.last_success));
      if (d.auto && d.next_attempt && !d.running) out.push('nächster Abruf ' + when(d.next_attempt));
      if (d.last_error) out.push('Hinweis: ' + d.last_error);
    } else if (task.id.startsWith('enrich:')) {
      out.push(num(d.checked) + ' von ' + num(d.total) + ' Titeln geprüft');
    }
    if (task.note && Date.now() / 1000 - task.note_at < 90 && !task.paused) out.push(task.note);
    return out.filter(Boolean).join(' · ');
  }
  async function act(task, action, value, button) {
    if (button) button.disabled = true;
    try { renderTasks(await window.api('task-action', {task, action, value})); say('tasks-status', ''); }
    catch (e) { say('tasks-status', e.message, true); if (button) button.disabled = false; }
  }
  function renderTasks(data) {
    const host = $('tasks-list');
    if (!host) return;
    // Keep the focus of a select while the list refreshes.
    if (host.contains(document.activeElement) && document.activeElement.tagName === 'SELECT') return;
    host.replaceChildren();
    const groups = new Map();
    for (const t of data.tasks || []) { if (!groups.has(t.group)) groups.set(t.group, []); groups.get(t.group).push(t); }
    for (const [group, tasks] of groups) {
      const box = make('section', undefined, 'tasks-group');
      const head = make('div', undefined, 'tasks-group-head');
      head.append(make('h3', group));
      const pausable = tasks.filter(t => t.can.includes('pause'));
      if (pausable.length > 1) {
        const all = pausable.every(t => t.paused);
        const b = make('button', all ? 'Gruppe fortsetzen' : 'Gruppe pausieren'); b.type = 'button';
        b.onclick = () => act('', all ? 'resume_all' : 'pause_all', group, b);
        head.append(b);
      }
      box.append(head);
      for (const t of tasks) {
        const row = make('article', undefined, 'task-row');
        const [state, label, hint] = stateOf(t);
        row.dataset.state = state;
        const info = make('div', undefined, 'task-info');
        const title = make('div', undefined, 'task-title');
        title.append(make('strong', t.label), make('span', label, 'task-state task-state-' + state));
        if (hint) title.lastChild.title = hint;
        info.append(title, make('small', describe(t) || t.hint, 'task-detail'));
        info.title = t.hint;
        if (t.id.startsWith('enrich:') && t.detail?.total) {
          const bar = make('div', undefined, 'atlas-portal-progress'), fill = make('span');
          fill.style.width = Math.min(100, Math.round(100 * (t.detail.checked || 0) / t.detail.total)) + '%';
          bar.append(fill); info.append(bar);
        }
        const actions = make('div', undefined, 'task-actions');
        if (t.can.includes('priority')) {
          const label = make('label', 'Priorität ', 'task-priority');
          const select = make('select');
          for (const p of data.priorities || []) { const o = make('option', p.label); o.value = p.key; select.append(o); }
          select.value = t.priority;
          select.title = 'Hoch prüft schneller, Niedrig schont Leitung und Anbieter-Kontingent';
          select.onchange = () => { select.blur(); act(t.id, 'priority', select.value); };
          label.append(select); actions.append(label);
        }
        if (t.can.includes('start')) {
          const b = make('button', t.detail?.running ? 'Läuft …' : 'Jetzt starten'); b.type = 'button';
          b.disabled = !!t.detail?.running;
          b.onclick = () => act(t.id, 'start', null, b);
          actions.append(b);
        }
        if (t.can.includes('pause')) {
          const b = make('button', t.paused ? 'Fortsetzen' : 'Pausieren', t.paused ? 'primary' : ''); b.type = 'button';
          b.onclick = () => act(t.id, t.paused ? 'resume' : 'pause', null, b);
          actions.append(b);
        }
        if (t.id === 'downloads') {
          const open = make('button', 'Warteschlange öffnen'); open.type = 'button';
          open.onclick = () => window.atlasShowView?.('queue');
          actions.append(open);
        }
        if (t.portal) {
          const open = make('button', 'Plattform'); open.type = 'button';
          open.title = 'Plattform-Reiter öffnen';
          open.onclick = () => { window.atlasShowView?.('portals'); document.querySelector('.platform-tab[data-platform="' + t.portal + '"]')?.click(); };
          actions.append(open);
        }
        row.append(info, actions); box.append(row);
      }
      host.append(box);
    }
    if (data.background === false) say('tasks-status', 'Hintergrundaufgaben sind für diesen Start abgeschaltet (Testmodus).');
  }
  async function loadTasks() {
    clearTimeout(taskTimer);
    if (!visible('admin')) return;
    const seq = ++taskSeq;
    try { const data = await window.api('tasks'); if (seq === taskSeq) renderTasks(data); }
    catch (e) { say('tasks-status', 'Aufgaben nicht verfügbar: ' + e.message, true); }
    taskTimer = setTimeout(loadTasks, 4000);
  }
  if ($('tasks-pause-all')) $('tasks-pause-all').onclick = e => act('', 'pause_all', '', null).then(() => e.target.blur());
  if ($('tasks-resume-all')) $('tasks-resume-all').onclick = e => act('', 'resume_all', '', null).then(() => e.target.blur());

  // ---------------------------------------------------------------- presentation
  const SAMPLE = {source: 'netzkino', id: '', kind: 'movie', title: 'Beispielfilm', year: 2019, poster: '',
    description: 'So sieht eine Kachel mit der aktuellen Auswahl aus. Die Einstellungen gelten für das Dashboard und alle Plattform-Reiter.',
    genres: ['Komödie', 'Drama'], score: {value: 7.8, source: 'IMDb', votes: 15400}, playable: true, web_url: ''};
  function preview() {
    const host = $('display-preview');
    if (!host || !window.AtlasCards) return;
    const card = window.AtlasCards.card({...SAMPLE, offers: [SAMPLE, {...SAMPLE, source: 'pluto', id: 'beispiel0000', playable: true}]});
    for (const b of card.querySelectorAll('button')) { b.onclick = null; b.disabled = false; b.type = 'button'; }
    for (const n of card.querySelectorAll('.clickable')) n.onclick = null;
    // A sample has no real id, so the offline control is drawn as a plain button.
    if (!card.querySelector('.atlas-offline')) {
      const off = make('button', '⬇ Offline speichern (30 Tage)', 'atlas-offline-button'); off.type = 'button';
      const wrap = make('span', undefined, 'atlas-offline'); wrap.append(off);
      card.querySelector('.atlas-uc-actions')?.append(wrap);
    }
    host.replaceChildren(card);
  }
  function renderDisplay() {
    const form = $('display-form'), D = window.AtlasDisplay;
    if (!form || !D) return;
    const prefs = D.get(), meta = D.meta();
    form.replaceChildren();
    const change = async patch => {
      try { await D.save(patch); say('display-status', 'Gespeichert.'); renderDisplay(); }
      catch (e) { say('display-status', e.message, true); }
    };
    const field = (title, node) => { const l = make('label', undefined, 'display-field'); l.append(make('span', title), node); return l; };
    const choice = (key, options) => {
      const s = make('select');
      for (const [value, label] of options) { const o = make('option', label); o.value = value; s.append(o); }
      s.value = prefs[key]; s.onchange = () => change({[key]: s.value});
      return s;
    };
    const general = make('fieldset'); general.append(make('legend', 'Dashboard'));
    general.append(
      field('Startansicht', choice('start_source', [['all', 'Alle Plattformen'], ['mediatheken', 'ARD, ZDF & Co.'], ['netzkino', 'Netzkino'], ['pluto', 'Pluto TV'], ['justwatch', 'JustWatch TV'], ['rakuten', 'Rakuten TV'], ['joyn', 'Joyn'], ['youtube', 'YouTube']])),
      field('Zuerst zeigen', choice('start_kind', [['movies', 'Filme'], ['series', 'Serien']])),
      field('Kachelgröße', choice('card_size', (meta.sizes || []).map(s => [s.key, s.label]))));
    form.append(general);
    const groups = new Map();
    for (const sw of meta.switches || []) { if (!groups.has(sw.group)) groups.set(sw.group, []); groups.get(sw.group).push(sw); }
    for (const [group, list] of groups) {
      const set = make('fieldset'); set.append(make('legend', group === 'Kachel' ? 'Jede Film- und Serienkachel zeigt' : group === 'Titelseite' ? 'Die Titelseite zeigt' : group));
      for (const sw of list) {
        const l = make('label', undefined, 'check'), box = make('input');
        box.type = 'checkbox'; box.checked = prefs[sw.key] !== false;
        box.onchange = () => change({[sw.key]: box.checked});
        l.append(box, document.createTextNode(' ' + sw.label)); set.append(l);
      }
      form.append(set);
    }
    preview();
  }
  if ($('display-reset')) $('display-reset').onclick = async () => {
    const D = window.AtlasDisplay; if (!D) return;
    const reset = {card_size: 'normal', start_source: 'all', start_kind: 'movies'};
    for (const sw of D.meta().switches || []) reset[sw.key] = true;
    try { await D.save(reset); say('display-status', 'Standard wiederhergestellt.'); renderDisplay(); }
    catch (e) { say('display-status', e.message, true); }
  };

  document.addEventListener('atlas-view', event => {
    const view = event.detail?.view;
    if (view === 'admin') loadTasks(); else clearTimeout(taskTimer);
    if (view === 'display') (window.AtlasDisplay?.ready || Promise.resolve()).then(renderDisplay);
  });
  window.AtlasAdmin = {loadTasks, renderDisplay};
})();
