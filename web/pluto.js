/* Pluto TV (0.5.36): public catalogue (films, series, live channels), playback in the in-app player. */
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
  let view = 'movies', series = null, offset = 0, seq = 0, timer = 0, poll = 0;
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
    }
    box.append(actions);
    return box;
  }

  async function refresh() {
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
