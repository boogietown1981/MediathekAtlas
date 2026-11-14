/* YouTube (0.5.53): complete free films and series from official channels of rights holders, with the
   shared platform panel (web/portal_panel.js): tiles, categories, ratings, title page. Plays in the
   official embedded YouTube player. Setup: API key, channel/playlist list, offline opt-in switch
   (off by default; YouTube's terms forbid downloads without permission – Björn's decision 12.11.2026). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const panel = window.AtlasPortalPanel?.({
    key: 'youtube', name: 'YouTube', short: 'YouTube', offlineFlag: true, music: true,
    play: () => window.playYouTube, externalLink: 'Bei YouTube ansehen',
    offlineNote: days => `YouTube: ${days} Tage offline, nur nach Einschalten (auf eigene Verantwortung).`
  });
  if (!panel || !$('youtube-setup')) { window.MediathekAtlasYouTube = panel || undefined; return; }
  const say = (text, error) => { $('youtube-sources-status').textContent = text || ''; $('youtube-sources-status').classList.toggle('netzkino-error', !!error); };
  const when = t => t ? new Date(t * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : 'noch nie';
  let consentText = '';

  function renderSources(list) {
    const host = $('youtube-sources'); host.replaceChildren();
    const button = $('youtube-store-add'); if (button) button.hidden = list.some(s => s.ref === 'store:free');
    if (!list.length) host.append(make('p', 'Noch keine Kanäle eingetragen. Unten die Adresse eines offiziellen Kanals oder einer Playlist einfügen.', 'muted'));
    for (const s of list) {
      const row = make('div', undefined, 'youtube-source' + (s.enabled ? '' : ' disabled'));
      const music = s.kind === 'music', store = s.ref === 'store:free';
      row.append(make('strong', (s.label || s.title || s.ref) + (s.kind === 'series' ? ' · Serie' : music ? ' · Musikvideos' : ' · Filme')));
      const facts = [store ? 'Liste über JustWatch · kopiergeschützt, läuft bei YouTube' : s.ref.startsWith('v:') ? 'Video ' + s.ref.slice(2) : s.ref, s.title && s.title !== s.label ? (s.ref.startsWith('v:') ? 'Titel: ' : 'Kanal: ') + s.title : '',
        store ? '' : music ? 'ohne Längenfilter' : 'ab ' + s.min_minutes + ' Min.',
        s.checked ? s.films + ' ' + (s.kind === 'series' ? 'Folgen' : music ? 'Musikvideos' : 'Filme') + ' von ' + s.videos + ' Videos · Stand ' + when(s.checked) : 'noch nicht abgerufen',
        s.suggested ? 'Vorschlag (ungeprüft)' : ''].filter(Boolean).join(' · ');
      row.append(make('small', facts, 'muted'));
      // 0.5.54: what the check left out and why (ArchiveMedia format check, description, length).
      let skipped = {}; try { skipped = JSON.parse(s.skipped || '{}'); } catch (e) { skipped = {}; }
      const parts = Object.entries(skipped).sort((a, b) => b[1] - a[1]).map(([why, n]) => n + ' × ' + why);
      if (parts.length) row.append(make('small', 'Ausgelassen: ' + parts.join(' · '), 'muted'));
      if (s.last_error) row.append(make('small', 'Fehler: ' + s.last_error, 'nk-warning'));
      const acts = make('div', undefined, 'youtube-source-actions');
      for (const [label, action] of [[s.enabled ? 'Pausieren' : 'Aktivieren', s.enabled ? 'disable' : 'enable'], ['Entfernen', 'remove']]) {
        const b = make('button', label); b.type = 'button';
        b.onclick = async () => {
          b.disabled = true;
          try { const r = await window.api('youtube-sources', {action, id: s.id}); renderSources(r.sources || []);
            say(action === 'remove' ? 'Entfernt. Beim nächsten Abruf verschwinden seine Titel.' : r.started ? 'Gespeichert und wird jetzt eingelesen.' : 'Gespeichert. „↻ Katalog jetzt laden“ übernimmt die Änderung.');
            if (r.started) setTimeout(panel.refresh, 1500); }
          catch (e) { say(e.message, true); b.disabled = false; }
        };
        acts.append(b);
      }
      row.append(acts); host.append(row);
    }
  }

  function renderOffline(o) {
    consentText = o.consent_text || '';
    $('youtube-offline-policy').textContent = o.policy || '';
    $('youtube-offline-switch').checked = !!o.enabled;
    $('youtube-offline-tool').textContent = o.enabled ? (o.tool ? 'yt-dlp: ' + o.tool_origin + '. Für volle Qualität kann yt-dlp zusätzlich Deno oder Node.js benötigen.' : o.tool_hint) : '';
    $('youtube-ytdlp-install').hidden = !o.enabled || !!o.tool;
    $('youtube-offline').hidden = !o.enabled;
  }

  async function load() {
    try {
      const d = await window.api('youtube-sources');
      renderSources(d.sources || []); renderOffline(d.offline || {});
      const st = d.status || {};
      $('youtube-setup-state').textContent = '· ' + (st.key_set ? 'Schlüssel hinterlegt' : 'Schlüssel fehlt') + ' · ' + (st.sources || 0) + ' aktive Quellen' +
        (st.sources_failed ? ' · ' + st.sources_failed + ' mit Fehler' : '') + ' · Offline ' + (st.offline_enabled ? 'an' : 'aus');
      // 0.5.62: since 0.5.55 the setup sits in the collapsed "YouTube verwalten" block; without a key,
      // a source or a catalogue it opens by itself so channels and key are never out of sight.
      if (!st.key_set || !st.sources || !(st.movies || st.series || st.music)) { window.AtlasPlatformLayout?.open('youtube'); $('youtube-setup').open = true; }
    } catch (e) { say(e.message, true); }
  }

  $('youtube-key-form').onsubmit = async ev => {
    ev.preventDefault();
    const key = $('youtube-key').value.trim(); if (!key) return;
    try { const r = await window.api('youtube-key', {key}); $('youtube-key').value = ''; say(r.started ? 'Schlüssel gespeichert, Katalog wird geladen …' : 'Schlüssel gespeichert.'); await load(); setTimeout(panel.refresh, 1500); }
    catch (e) { say(e.message, true); }
  };
  $('youtube-key-clear').onclick = async () => {
    try { await window.api('youtube-key', {clear: true}); say('Schlüssel gelöscht.'); await load(); } catch (e) { say(e.message, true); }
  };
  $('youtube-source-form').onsubmit = async ev => {
    ev.preventDefault();
    try {
      const r = await window.api('youtube-sources', {action: 'add', url: $('youtube-source-url').value, kind: $('youtube-source-kind').value,
        label: $('youtube-source-label').value, min_minutes: $('youtube-source-min').value || null});
      renderSources(r.sources || []); $('youtube-source-url').value = ''; $('youtube-source-label').value = ''; $('youtube-source-min').value = '';
      // 0.5.74: the server reads a new source right away; the status line shows the progress.
      const where = $('youtube-source-kind').value === 'music' ? ' Sie erscheint danach unter „Musikvideos“.' : '';
      say(r.started ? 'Hinzugefügt und wird eingelesen (läuft schon ein Abruf, direkt danach); der Fortschritt steht oben im Status.' + where :
        'Hinzugefügt. „↻ Katalog jetzt laden“ liest die Quelle ein.' + where);
      if (r.started || r.status?.running) setTimeout(panel.refresh, 1500);
    } catch (e) { say(e.message, true); }
  };
  // 0.6.4: YouTube's own free films ("Filme & TV") as one source; the server reads it right away.
  const storeButton = $('youtube-store-add');
  if (storeButton) storeButton.onclick = async () => {
    storeButton.disabled = true;
    try {
      const r = await window.api('youtube-sources', {action: 'add', url: 'store:free', kind: 'movies'});
      renderSources(r.sources || []);
      say(r.started ? 'YouTube „Filme & TV“ aufgenommen und wird eingelesen; der Fortschritt steht oben im Status.' : 'YouTube „Filme & TV“ aufgenommen. „↻ Katalog jetzt laden“ liest die Filme ein.');
      if (r.started) setTimeout(panel.refresh, 1500);
    } catch (e) { say(e.message, true); }
    storeButton.disabled = false;
  };
  // Series episodes are shorter than films: the suggested minimum follows the kind (films 60, series 10 min).
  // 0.5.71: music videos have no minimum length (and no promo filter).
  const minHint = () => { const k = $('youtube-source-kind').value; $('youtube-source-min').placeholder = k === 'series' ? '10' : '60';
    $('youtube-source-min').disabled = k === 'music'; $('youtube-source-min').closest('label').hidden = k === 'music'; };
  $('youtube-source-kind').onchange = minHint; minHint();
  $('youtube-offline-switch').onchange = async ev => {
    const on = ev.target.checked;
    // Switching on needs an explicit confirmation of the terms (stored with its time).
    if (on && !window.confirm(consentText + '\n\nOffline-Speichern für YouTube jetzt einschalten?')) { ev.target.checked = false; return; }
    try { renderOffline(await window.api('youtube-offline', {enabled: on, confirmed: on})); await load(); panel.refresh(); }
    catch (e) { say(e.message, true); ev.target.checked = !on; }
  };
  $('youtube-ytdlp-install').onclick = async ev => {
    ev.target.disabled = true; ev.target.textContent = 'yt-dlp wird geladen …';
    try { renderOffline(await window.api('youtube-ytdlp-install', {})); say('yt-dlp eingerichtet.'); }
    catch (e) { say(e.message, true); }
    ev.target.disabled = false; ev.target.textContent = 'yt-dlp einrichten';
  };
  $('youtube-setup').addEventListener('toggle', () => { if ($('youtube-setup').open) load(); });
  window.MediathekAtlasYouTube = {refresh: () => { load(); return panel.refresh(); }, openDetail: panel.openDetail, openAlbum: panel.openAlbum};
})();
