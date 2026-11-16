/* YouTube-Kanal-Abos (youtube_abos.py), Verwaltung im YouTube-Bereich.
   0.6.7: abonnieren und je Abo einstellen, was automatisch offline geladen wird.
   0.6.11 (Björn, 16.11.2026: „Darstellung nicht sauber“, getrennte Abos für Tochter und mich):
   Reiter je Profil (Kinderecke / Für mich), kompakte Karten mit Kanalbild, Zahlen als Chips und
   kleinen Knöpfen; ein gemeinsames Formular für „Abonnieren“ und „Einstellungen“, Seltenes eingeklappt. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('youtube-abos')) return;
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined && text !== null) n.textContent = text; if (cls) n.className = cls; return n; };
  const token = () => document.querySelector('meta[name=atlas-token]')?.content || '';
  const say = (text, error) => { const s = $('youtube-abos-status'); s.textContent = text || ''; s.classList.toggle('netzkino-error', !!error); };
  const ago = t => {
    if (!t) return 'noch nie geprüft';
    const m = Math.round((Date.now() / 1000 - t) / 60);
    return 'geprüft ' + (m < 1 ? 'gerade eben' : m < 60 ? 'vor ' + m + ' Min.' : m < 1440 ? 'vor ' + Math.round(m / 60) + ' Std.' : 'am ' + new Date(t * 1000).toLocaleDateString('de-DE'));
  };
  const PROFILES = {kinder: {icon: '★', label: 'Kinderecke', hint: 'erscheint nur in der Kinderecke'},
    erwachsene: {icon: '▶', label: 'Für mich', hint: 'erscheint nur im Ansehen-Modus'}};
  const CHIPS = [['done', 'offline', 'ok'], ['queued', 'werden geladen', 'busy'], ['retry', 'neuer Versuch geplant', 'wait'], ['wanted', 'warten', 'wait'],
    ['failed', 'Fehler', 'bad'], ['skipped', 'ausgelassen', 'muted'], ['expired', 'abgelaufen', 'muted']];
  let data = {abos: [], profiles: []}, current = 'kinder', timer = 0;

  // ------------------------------------------------------------ ein Formular für Neu und Ändern
  function form(values, isNew, onSubmit, onCancel) {
    const f = make('form', undefined, 'abo-form');
    const field = (label, input, cls) => { const l = make('label', label, cls || ''); l.append(input); return l; };
    const select = (options, value) => { const s = document.createElement('select'); for (const [v, t] of options) { const o = make('option', t); o.value = v; s.append(o); } s.value = String(value); return s; };
    const input = (value, attrs) => { const i = document.createElement('input'); Object.assign(i, attrs || {}); i.value = value ?? ''; return i; };
    const profile = select(Object.entries(PROFILES).map(([k, p]) => [k, p.icon + ' ' + p.label]), values.profile || current);
    const url = input('', {placeholder: 'youtube.com/@Kanal oder youtube.com/playlist?list=…', required: true});
    const mode = select([['new', 'Nur neue Videos'], ['all', 'Alle Videos (neueste zuerst)']], values.mode || 'new');
    const start = input(values.start_count ?? 5, {type: 'number', min: 0, max: 50});
    const include = input(values.include, {placeholder: 'z. B. Bluey, Folge'});
    const exclude = input(values.exclude, {placeholder: 'z. B. Trailer, Live'});
    const keep = input(values.keep ?? 30, {type: 'number', min: 1, max: 500});
    const quality = select([['480', '480p (spart Platz)'], ['720', '720p'], ['1080', '1080p']], values.quality || '720');
    const interval = select([[1, 'jede Stunde'], [3, 'alle 3 Stunden'], [6, 'alle 6 Stunden'], [12, 'alle 12 Stunden'], [24, 'einmal am Tag']], values.interval_hours || 3);
    const label = input(values.label, {placeholder: 'wie auf YouTube', maxLength: 80});
    const shorts = input('', {type: 'checkbox'}); shorts.checked = values.min_seconds === undefined ? true : values.min_seconds > 0;

    const main = make('div', undefined, 'abo-form-grid');
    main.append(field('Für wen?', profile));
    if (isNew) main.append(field('Kanal oder Playlist', url, 'abo-wide'));
    main.append(field('Was laden?', mode));
    const startField = field('Zum Start laden (neueste)', start);
    if (isNew) main.append(startField);
    main.append(field('Nur eine Reihe (Titelwörter)', include));
    const more = make('details', undefined, 'abo-more'); more.append(make('summary', 'Weitere Einstellungen'));
    const grid = make('div', undefined, 'abo-form-grid');
    const sl = make('label', undefined, 'check'); sl.append(shorts, document.createTextNode(' Shorts auslassen'));
    grid.append(field('Ausschließen (Titelwörter)', exclude), field('Höchstens offline', keep), field('Qualität', quality),
      field('Prüfen', interval), field('Eigener Name', label), sl);
    more.append(grid, make('p', 'Ist die Höchstzahl erreicht, macht das älteste schon gesehene Video Platz; ungesehene bleiben immer.', 'muted'));
    const hint = make('p', PROFILES[profile.value].hint, 'muted abo-profile-hint');
    profile.onchange = () => { hint.textContent = PROFILES[profile.value].hint; };
    const sync = () => { startField.hidden = mode.value !== 'new'; }; mode.onchange = sync; sync();
    const actions = make('div', undefined, 'abo-form-actions');
    const save = make('button', isNew ? 'Abonnieren' : 'Speichern', 'primary');
    const cancel = make('button', 'Abbrechen'); cancel.type = 'button'; cancel.onclick = onCancel;
    actions.append(save, cancel);
    f.append(main, hint, more, actions);
    f.onsubmit = ev => {
      ev.preventDefault();
      const out = {profile: profile.value, mode: mode.value, include: include.value, exclude: exclude.value, keep: keep.value,
        quality: quality.value, interval_hours: interval.value, label: label.value, min_seconds: shorts.checked ? 61 : 0};
      if (isNew) Object.assign(out, {url: url.value, start_count: start.value});
      onSubmit(out, save);
    };
    setTimeout(() => (isNew ? url : mode).focus(), 0);
    return f;
  }

  // ------------------------------------------------------------ Reiter und Karten
  function tabs() {
    const host = $('youtube-abos-profiles'); host.replaceChildren();
    for (const p of data.profiles || []) {
      const b = make('button', undefined, 'abo-tab'); b.type = 'button'; b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(p.key === current));
      b.append(make('span', (PROFILES[p.key]?.icon || '') + ' ' + (PROFILES[p.key]?.label || p.label), 'abo-tab-name'),
        make('span', p.abos + (p.abos === 1 ? ' Abo' : ' Abos') + ' · ' + p.done + ' offline', 'abo-tab-count'));
      b.onclick = () => { current = p.key; render(); };
      host.append(b);
    }
  }
  function avatar(a) {
    const box = make('span', undefined, 'abo-avatar');
    const letter = () => { box.textContent = (a.name || '?').replace(/^@/, '').trim().charAt(0).toUpperCase(); };
    if (a.avatar_local) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.src = '/api/kids-image?' + new URLSearchParams({abo: a.id, token: token()}); img.onerror = () => { img.remove(); letter(); }; box.append(img); }
    else letter();
    return box;
  }
  function iconButton(symbol, title, fn) {
    const b = make('button', symbol, 'abo-icon'); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title); b.onclick = fn; return b;
  }
  function card(a) {
    const box = make('article', undefined, 'abo-card' + (a.enabled ? '' : ' is-paused'));
    const body = make('div', undefined, 'abo-body');
    const head = make('div', undefined, 'abo-head');
    head.append(make('strong', a.name));
    if (!a.enabled) head.append(make('span', 'pausiert', 'abo-badge'));
    if (a.kind === 'playlist') head.append(make('span', 'Playlist', 'abo-badge'));
    body.append(head);
    const rules = [a.mode === 'all' ? 'alle Videos' : 'nur neue', a.include ? 'Reihe: ' + a.include : '', a.exclude ? 'ohne: ' + a.exclude : '',
      a.quality + 'p', 'max. ' + a.keep, ago(a.checked) + (a.via ? ' (' + (a.via === 'api' ? 'API' : 'yt-dlp') + ')' : '')].filter(Boolean);
    body.append(make('p', rules.join(' · '), 'abo-rules'));
    const chips = make('div', undefined, 'abo-chips');
    const c = a.counts || {};
    for (const [key, text, tone] of CHIPS) if (c[key]) chips.append(make('span', c[key] + ' ' + text, 'abo-chip abo-' + tone));
    if (!chips.childNodes.length) chips.append(make('span', a.checked ? 'keine passenden Videos' : 'wird gleich gelesen', 'abo-chip abo-muted'));
    if (a.last_new) chips.append(make('span', a.last_new + ' neu beim letzten Mal', 'abo-chip abo-ok'));
    body.append(chips);
    if (a.last_error) body.append(make('p', a.last_error, 'abo-error'));
    if (a.reasons?.length) {
      const why = make('details', undefined, 'abo-why'); why.append(make('summary', 'Warum ausgelassen oder verzögert?'));
      why.append(make('p', a.reasons.map(r => r.count + ' × ' + r.reason).join(' · '), 'muted')); body.append(why);
    }
    const acts = make('div', undefined, 'abo-actions');
    acts.append(
      iconButton('↻', 'Jetzt prüfen', () => act({action: 'check', id: a.id}, '„' + a.name + '“ wird geprüft …')),
      iconButton('⚙', 'Einstellungen', () => {
        const open = box.querySelector('.abo-form'); if (open) { open.remove(); return; }
        box.append(form(a, false, (values, button) => act({action: 'update', id: a.id, ...values},
          values.profile !== a.profile ? 'Verschoben nach „' + PROFILES[values.profile].label + '“.' : 'Gespeichert, wird gleich neu geprüft.', button), () => box.querySelector('.abo-form')?.remove()));
      }),
      iconButton(a.enabled ? '⏸' : '▶', a.enabled ? 'Pausieren' : 'Fortsetzen', () => act({action: 'update', id: a.id, enabled: !a.enabled}, a.enabled ? 'Pausiert.' : 'Fortgesetzt.')),
      iconButton('✕', 'Abo beenden', () => {
        if (window.confirm('Abo „' + a.name + '“ beenden? Geladene Videos bleiben bis zum Ablauf ihrer Frist.')) act({action: 'remove', id: a.id}, 'Abo beendet.');
      }));
    const link = make('a', '↗', 'abo-icon'); link.href = a.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.title = 'Auf YouTube öffnen';
    acts.append(link);
    box.append(avatar(a), body, acts);
    return box;
  }
  function render() {
    tabs();
    const list = $('youtube-abos-list'); list.replaceChildren();
    const own = (data.abos || []).filter(a => a.profile === current);
    if (!own.length) list.append(make('p', current === 'kinder' ? 'Noch keine Kanäle für die Kinderecke.' : 'Noch keine eigenen Kanäle für den Ansehen-Modus.', 'abo-empty'));
    for (const a of own) list.append(card(a));
    const add = $('youtube-abo-add');
    if (!add.querySelector('.abo-form')) {
      add.replaceChildren();
      const b = make('button', '＋ Kanal für „' + PROFILES[current].label + '“ abonnieren', 'primary abo-add-button'); b.type = 'button';
      b.onclick = () => {
        add.replaceChildren(form({profile: current}, true, async (values, button) => {
          if (await act({action: 'add', ...values}, 'Abonniert. Der Kanal wird jetzt gelesen.', button)) { current = values.profile; add.replaceChildren(); render(); }
        }, () => { add.replaceChildren(); render(); }));
      };
      add.append(b);
    }
  }
  function show(d) {
    data = d;
    const warn = $('youtube-abos-warning'); const problems = [];
    if (!d.offline?.enabled) problems.push('Der YouTube-Offline-Schalter (Schritt 3 oben) ist aus: Abos werden geprüft, aber nichts geladen.');
    else if (!d.offline?.tool) problems.push('yt-dlp fehlt noch: oben in Schritt 3 „yt-dlp einrichten“ wählen.');
    // 0.6.13: YouTube hat Anfragen als Bot eingestuft; Abo-Downloads warten, statt die Sperre zu verlängern.
    if (d.pause?.until) problems.push('YouTube bremst gerade (' + d.pause.reason + '). Abo-Downloads pausieren bis ' +
      new Date(d.pause.until * 1000).toLocaleString('de-DE', {weekday: 'short', hour: '2-digit', minute: '2-digit'}) + ' Uhr und laufen danach von selbst weiter.');
    warn.hidden = !problems.length; warn.textContent = problems.join(' ');
    const total = (d.abos || []).length, done = (d.profiles || []).reduce((n, p) => n + p.done, 0);
    $('youtube-abos-state').textContent = total ? '· ' + total + (total === 1 ? ' Abo' : ' Abos') + ' · ' + done + ' Videos offline' + (d.running ? ' · prüft gerade' : '') : '';
    render();
    clearTimeout(timer);
    if (d.running || (d.abos || []).some(a => (a.counts || {}).queued)) timer = setTimeout(load, 8000);
  }
  async function act(payload, message, button) {
    if (button) button.disabled = true;
    try { const d = await window.api('youtube-abos', payload); show(d); say(message); if (d.started) setTimeout(load, 4000); return true; }
    catch (e) { say(e.message, true); return false; }
    finally { if (button) button.disabled = false; }
  }
  async function load() {
    try { show(await window.api('youtube-abos')); } catch (e) { say(e.message, true); }
  }
  $('youtube-abos').addEventListener('toggle', () => { if ($('youtube-abos').open) load(); });
  window.MediathekAtlasYouTubeAbos = {refresh: load};
})();
