/* 0.6.7 YouTube-Kanal-Abos (youtube_abos.py): abonnieren, je Abo einstellen, was automatisch offline
   geladen wird, und sehen, was gerade passiert. Die fertigen Videos zeigt die Kinderecke (/kinder). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('youtube-abos')) return;
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const when = t => t ? new Date(t * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : 'noch nie';
  const say = (text, error) => { const s = $('youtube-abos-status'); s.textContent = text || ''; s.classList.toggle('netzkino-error', !!error); };
  const MODES = {new: 'nur neue', all: 'alle'};
  let timer = 0;

  function counts(a) {
    const c = a.counts || {};
    const parts = [];
    if (c.done) parts.push(c.done + ' offline');
    if (c.queued) parts.push(c.queued + ' in der Warteschlange');
    if (c.wanted) parts.push(c.wanted + ' warten');
    if (c.failed) parts.push(c.failed + ' fehlgeschlagen');
    if (c.skipped) parts.push(c.skipped + ' ausgelassen');
    if (c.expired) parts.push(c.expired + ' abgelaufen/entfernt');
    if (c.old) parts.push(c.old + ' ältere nicht geladen');
    return parts.join(' · ') || 'noch nicht geprüft';
  }

  function editor(a, row) {
    const form = make('form', undefined, 'youtube-abo-form youtube-abo-edit');
    const field = (label, input, hint) => { const l = make('label', label); l.append(input); if (hint) l.append(make('small', hint)); form.append(l); return input; };
    const select = (options, value) => { const s = document.createElement('select'); for (const [v, t] of options) { const o = make('option', t); o.value = v; s.append(o); } s.value = String(value); return s; };
    const number = (value, min, max) => { const i = document.createElement('input'); i.type = 'number'; i.min = min; i.max = max; i.value = value; return i; };
    const text = value => { const i = document.createElement('input'); i.value = value || ''; return i; };
    const mode = field('Was laden?', select([['new', 'Nur neue Videos'], ['all', 'Alle Videos']], a.mode));
    const include = field('Nur eine Reihe', text(a.include), 'Wörter, durch Komma getrennt');
    const exclude = field('Ausschließen', text(a.exclude));
    const keep = field('Höchstens offline', number(a.keep, 1, 500));
    const quality = field('Qualität', select([['480', '480p'], ['720', '720p'], ['1080', '1080p']], a.quality));
    const interval = field('Prüfen alle', select([[1, '1 Stunde'], [3, '3 Stunden'], [6, '6 Stunden'], [12, '12 Stunden'], [24, '24 Stunden']], a.interval_hours));
    const label = field('Name', text(a.label));
    const shorts = document.createElement('input'); shorts.type = 'checkbox'; shorts.checked = a.min_seconds > 0;
    const sl = make('label', undefined, 'check'); sl.append(shorts, document.createTextNode(' Shorts auslassen')); form.append(sl);
    const kids = document.createElement('input'); kids.type = 'checkbox'; kids.checked = !!a.kids;
    const kl = make('label', undefined, 'check'); kl.append(kids, document.createTextNode(' In der Kinderecke zeigen')); form.append(kl);
    const actions = make('div', undefined, 'wide'); const save = make('button', 'Speichern', 'primary'); const cancel = make('button', 'Abbrechen'); cancel.type = 'button';
    actions.append(save, cancel); form.append(actions);
    cancel.onclick = () => form.remove();
    form.onsubmit = async ev => {
      ev.preventDefault();
      await act({action: 'update', id: a.id, mode: mode.value, include: include.value, exclude: exclude.value, keep: keep.value,
        quality: quality.value, interval_hours: interval.value, label: label.value, min_seconds: shorts.checked ? 61 : 0, kids: kids.checked},
        mode.value === 'all' && a.mode === 'new' ? 'Gespeichert; ältere Videos werden jetzt nachgeladen.' : 'Gespeichert und wird gleich neu geprüft.');
    };
    row.append(form);
  }

  function render(d) {
    const list = $('youtube-abos-list'); list.replaceChildren();
    const abos = d.abos || [];
    const warn = $('youtube-abos-warning');
    const problems = [];
    if (!d.offline?.enabled) problems.push('Der YouTube-Offline-Schalter (Schritt 3 oben) ist aus: Abos werden geprüft, aber nichts geladen.');
    else if (!d.offline?.tool) problems.push('yt-dlp fehlt noch: oben in Schritt 3 „yt-dlp einrichten“ wählen.');
    warn.hidden = !problems.length; warn.textContent = problems.join(' ');
    const done = abos.reduce((n, a) => n + ((a.counts || {}).done || 0), 0);
    $('youtube-abos-state').textContent = abos.length ? '· ' + abos.length + (abos.length === 1 ? ' Abo' : ' Abos') + ' · ' + done + ' Videos offline' + (d.running ? ' · prüft gerade' : '') : '';
    if (!abos.length) list.append(make('p', 'Noch keine Abos. Unten einen Kanal oder eine Playlist eintragen.', 'muted'));
    for (const a of abos) {
      const row = make('div', undefined, 'youtube-source youtube-abo' + (a.enabled ? '' : ' disabled'));
      const head = make('strong', a.name);
      head.append(make('span', ' · ' + (MODES[a.mode] || a.mode) + (a.include ? ' · Reihe: ' + a.include : '') + (a.kids ? ' · Kinderecke' : ''), 'muted'));
      row.append(head);
      row.append(make('small', counts(a), 'muted'));
      row.append(make('small', 'Geprüft: ' + when(a.checked) + (a.via ? ' (' + (a.via === 'api' ? 'YouTube-API' : 'yt-dlp') + ')' : '') +
        (a.last_new ? ' · ' + a.last_new + ' neu beim letzten Mal' : '') + ' · alle ' + a.interval_hours + ' Std. · ' + a.quality + 'p · höchstens ' + a.keep, 'muted'));
      if (a.reasons?.length) row.append(make('small', 'Ausgelassen/Fehler: ' + a.reasons.map(r => r.count + ' × ' + r.reason).join(' · '), 'muted'));
      if (a.last_error) row.append(make('small', a.last_error, 'nk-warning'));
      const acts = make('div', undefined, 'youtube-source-actions');
      const button = (label, fn) => { const b = make('button', label); b.type = 'button'; b.onclick = fn; acts.append(b); return b; };
      button('Jetzt prüfen', () => act({action: 'check', id: a.id}, 'Wird geprüft …'));
      button('Einstellungen', () => { const open = row.querySelector('.youtube-abo-edit'); if (open) open.remove(); else editor(a, row); });
      button(a.enabled ? 'Pausieren' : 'Fortsetzen', () => act({action: 'update', id: a.id, enabled: !a.enabled}, a.enabled ? 'Pausiert.' : 'Fortgesetzt.'));
      button('Abo beenden', () => {
        if (window.confirm('Abo „' + a.name + '“ beenden? Bereits geladene Videos bleiben bis zum Ablauf ihrer Frist erhalten.'))
          act({action: 'remove', id: a.id}, 'Abo beendet.');
      });
      const link = make('a', 'Auf YouTube', 'muted'); link.href = a.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; acts.append(link);
      row.append(acts); list.append(row);
    }
    clearTimeout(timer);
    if (d.running || abos.some(a => (a.counts || {}).queued)) timer = setTimeout(load, 8000);
  }

  async function act(data, message) {
    try { const d = await window.api('youtube-abos', data); render(d); say(message); if (d.started) setTimeout(load, 4000); }
    catch (e) { say(e.message, true); }
  }
  async function load() {
    try { render(await window.api('youtube-abos')); } catch (e) { say(e.message, true); }
  }

  $('youtube-abo-form').onsubmit = async ev => {
    ev.preventDefault();
    const data = {action: 'add', url: $('youtube-abo-url').value, mode: $('youtube-abo-mode').value, start_count: $('youtube-abo-start').value,
      include: $('youtube-abo-include').value, exclude: $('youtube-abo-exclude').value, keep: $('youtube-abo-keep').value,
      quality: $('youtube-abo-quality').value, interval_hours: $('youtube-abo-interval').value, label: $('youtube-abo-label').value,
      min_seconds: $('youtube-abo-shorts').checked ? 61 : 0, kids: $('youtube-abo-kids').checked};
    try {
      const d = await window.api('youtube-abos', data);
      render(d);
      for (const id of ['youtube-abo-url', 'youtube-abo-include', 'youtube-abo-exclude', 'youtube-abo-label']) $(id).value = '';
      say('Abonniert. Der Kanal wird jetzt gelesen; fertige Videos erscheinen in der Kinderecke.');
      setTimeout(load, 4000);
    } catch (e) { say(e.message, true); }
  };
  const startHint = () => { $('youtube-abo-start').closest('label').hidden = $('youtube-abo-mode').value !== 'new'; };
  $('youtube-abo-mode').onchange = startHint; startHint();
  $('youtube-abos').addEventListener('toggle', () => { if ($('youtube-abos').open) load(); });
  window.MediathekAtlasYouTubeAbos = {refresh: load};
})();
