/* Netzkino: public GraphQL catalogue and HAR snapshot; official-site playback only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const endpoint = (p, data) => window.api(p, data);
  let searchSeq = 0;
  let timer;
  let offset = 0;
  let view = 'movies';
  let seriesKey = '';
  let genre = '';
  const cats = () => window.AtlasPortalCategories;
  const pageSize = 80;
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  const date = value => value ? new Date(value * 1000).toLocaleString('de-DE') : 'Noch kein erfolgreicher Abgleich';
  let pollTimer = null;
  const isVisible = () => {
    const portal = $('portals');
    return !!(portal && !portal.hidden && portal.dataset.platform === 'netzkino');
  };
  function scheduleRefresh(delay = 30000) {
    clearTimeout(pollTimer);
    if (isVisible()) pollTimer = setTimeout(() => { if (isVisible()) refresh(); }, delay);
  }

  function message(value, isError = false) {
    $('netzkino-status').textContent = value;
    $('netzkino-status').classList.toggle('netzkino-error', isError);
  }
  async function refresh() {
    const seq = ++searchSeq;
    const q = $('netzkino-filter').value.trim();
    const origin = $('netzkino-origin').value;
    try {
      const data = await endpoint('netzkino-grouped?' + new URLSearchParams({q, origin, offset,
        view, series_key: seriesKey, genre, sort: $('netzkino-sort')?.value || 'updated'}));
      if (seq !== searchSeq) return;
      const status = data.status || {};
      $('netzkino-auto').checked = !!status.auto;
      $('netzkino-sync').disabled = !!status.running;
      $('netzkino-sync').textContent = status.running ? 'Abgleich läuft …' : '↻ Katalog jetzt prüfen';
      const phase = status.running ? 'Läuft' : status.last_result === 'partial' ? 'Teilabgleich' :
        status.last_result === 'complete' ? 'Abgleich erfolgreich' : status.last_result === 'failed' ? 'Fehlgeschlagen' :
        'HAR-Startbestand, nicht live bestätigt';
      const categoryDetail = status.categories_total ?
        ` · Kategorien ${status.categories_checked || 0}/${status.categories_total}` +
        ` · Fehler ${status.category_errors || 0} · Leer ${status.categories_empty || 0}` +
        ` · Kategorien mit ≥20 Titeln ${status.category_cap_hits || 0}` +
        ` · über 20 Titel ${status.category_over_20 || 0}` +
        ` · größte Kategorie ${status.category_max_items || 0}` : '';
      const sitemapDetail = (status.sitemap_entries ? ` · Sitemap ${status.sitemap_entries} Titel (${status.sitemap_new || 0} neu)` : '') +
        (status.categories_discovered ? ` · ${status.categories_discovered} weitere Kategorien abgefragt` : '') +
        (status.categories_known ? ` · ${status.categories_known} Kategorien aus Filmdetails gemerkt` : '') +
        (status.related_new ? ` · ${status.related_new} Titel über Filmdetails ergänzt` : '') +
        (status.har_import_added ? ` · ${status.har_import_added} Titel aus Mitschnitt` : '');
      $('netzkino-sync-summary').textContent =
        `${status.catalog_count || 0} Katalogtitel · ${status.manual_count || 0} gemerkt · ` +
        `${phase} · Letzter Datenabruf: ${date(status.last_success)}` + categoryDetail + sitemapDetail +
        (status.last_error ? ` · Hinweis: ${status.last_error}` :
          !status.last_success ? ` · ${status.snapshot_seed_count || 0} Titel aus bereinigtem HAR.` :
          ` · Neu ${status.new || 0}, verändert ${status.changed || 0}, unverändert ${status.unchanged || 0}`);
      $('netzkino-sync-summary').dataset.phase = status.last_result || (status.running ? 'running' : 'never');
      const count = data.counts || {};
      $('netzkino-view-movies').textContent = 'Filme (' + (count.movies ?? '–') + ')';
      $('netzkino-view-series').textContent = 'Serien (' + (count.series ?? '–') + ')';
      $('netzkino-view-movies').classList.toggle('primary', view === 'movies');
      $('netzkino-view-series').classList.toggle('primary', view !== 'movies');
      $('netzkino-back-series').hidden = view !== 'episodes';
      $('netzkino-series-heading').textContent = view === 'episodes' ?
        (data.series?.title || 'Serie') + ' · ' + (data.series?.episode_count || 0) + ' Folgen' : '';
      const total = Number(data.total || 0);
      if (offset >= total && offset > 0) { offset = 0; return refresh(); }
      $('netzkino-prev').disabled = offset === 0;
      $('netzkino-next').disabled = offset + pageSize >= total;
      $('netzkino-page-label').textContent = `${total ? offset+1 : 0}–${Math.min(offset+pageSize,total)} von ${total}`;
      cats()?.render($('netzkino-categories'), data.genre_counts, genre, value => { genre = value; offset = 0; refresh(); });
      const host = $('netzkino-items'); host.replaceChildren();
      if (!data.items.length) host.append(make('p', q ? 'Keine passenden Einträge.' :
        'Noch keine Filmverknüpfungen. Du kannst einen Link speichern oder den Katalogabgleich starten.', 'empty'));
      for (const item of data.items) {
        const isGroup = view === 'series' && item.media_type === 'series';
        const card = make('article', undefined, 'netzkino-item');
        const title = make('h3', item.title);
        const label = make('small', isGroup ? 'Zusammengefasste Serie · Originaleinträge bleiben erhalten' : item.origin === 'manual' ? 'Manuell gemerkt · Streaming beim Anbieter' :
          item.source === 'har_snapshot' ? 'HAR-Startbestand vom 11.11.2026 · noch nicht live abgeglichen' :
          item.source === 'har_import' ? 'Aus eigenem Netzkino-Mitschnitt übernommen' :
          item.source === 'graphql_related' ? 'Über Netzkino-Filmdetails entdeckt' :
          'Netzkino-GraphQL-Katalog · Werkidentität nicht extern bestätigt');
        if (item.poster && /^https:\/\//i.test(item.poster)) {
          const img = make('img', undefined, 'netzkino-poster');
          img.src = item.poster; img.alt = `Cover: ${item.title}`; img.loading = 'lazy';
          img.referrerPolicy = 'no-referrer'; card.append(img);
        }
        const facts = [isGroup ? 'Serie · ' + (item.episode_count || 0) + ' bekannte Folgen' :
          view === 'episodes' ? ('Folge ' + (item.season ? 'S' + item.season + ' · ' : '') + 'E' + item.episode) : 'Film', item.year || null,
          item.fsk !== null && item.fsk !== undefined ? `FSK ${item.fsk}` : null,
          item.access_hint || null].filter(Boolean).join(' · ');
        const info = make('div', facts, 'netzkino-facts');
        const gaps = isGroup && item.numbering_gaps?.length ? make('small',
          'Nummerierungslücken im derzeitigen Katalog: ' + item.numbering_gaps.map(g =>
            'S' + g.season + ' E' + g.episodes.join(', E')).join('; ') +
          ' (keine Aussage zur Verfügbarkeit)', 'netzkino-gaps') : null;
        const genres = cats()?.categories(item.categories) || (item.genres ? make('small', item.genres, 'netzkino-genres') : null);
        const rating = cats()?.rating(item.score);
        const summary = item.summary ? make('p', item.summary, 'netzkino-description') : null;
        const actions = make('div', undefined, 'netzkino-actions');
        const play = make('button', '▶ In MediathekAtlas ansehen', 'netzkino-open');
        play.type = 'button';
        play.hidden = isGroup; // open a series via its episode list, not an arbitrary series URL
        play.onclick = async () => {
          play.disabled = true;
          try { await window.AtlasNetzkinoDetail.play(item.id, item.title); }
          catch (e) { message('Wiedergabe nicht möglich: ' + e.message, true); }
          finally { play.disabled = false; }
        };
        actions.append(play);
        if (isGroup && item.episode_count) {
          const episodes = make('button', 'Folgen anzeigen (' + item.episode_count + ')', 'netzkino-episodes');
          episodes.type = 'button';
          episodes.onclick = () => { view = 'episodes'; seriesKey = item.series_key; offset = 0; $('netzkino-filter').value=''; refresh(); };
          actions.prepend(episodes);
        }
        if (!isGroup && item.origin === 'manual') {
          const remove = make('button', 'Verknüpfung entfernen');
          remove.type = 'button';
          remove.onclick = async () => {
            if (!confirm(`Netzkino-Verknüpfung „${item.title}“ entfernen?`)) return;
            try {
              await endpoint('netzkino-remove', {id: item.id});
              await refresh();
            } catch (error) { message(error.message, true); }
          };
          actions.append(remove);
        }
        card.append(title, label, info);
        if (rating) card.append(rating);
        if (gaps) card.append(gaps);
        if (genres) card.append(genres);
        if (summary) card.append(summary);
        if (!isGroup && /^[a-f0-9]{32}$/.test(item.id || '')) {
          const detail = make('button', 'Details & Ansehen');
          detail.type = 'button';
          detail.onclick = () => window.AtlasNetzkinoDetail?.open(item.id);
          actions.prepend(detail);
        }
        card.append(actions); host.append(card);
      }
      if (status.running) message('Katalogabgleich läuft; bisherige Titel bleiben sichtbar.');
      else if (status.last_result === 'partial') message('Teilabgleich: einige Kategorien nicht verfügbar. Bereits erkannte Titel bleiben sichtbar.');
      else if (status.last_error) message(status.last_error, true);
      else message(`${data.items.length} Netzkino-Einträge angezeigt.`);
      scheduleRefresh(status.running ? 4000 : 30000);
    } catch (error) {
      const detail = `Kataloganzeige fehlgeschlagen: ${error.message}`;
      $('netzkino-sync-summary').textContent = detail;
      $('netzkino-sync-summary').dataset.phase = 'ui-error';
      message(detail, true);
      scheduleRefresh(30000);
    }
  }
  // Network recording (HAR) of netzkino.de: only answer texts of netzkino.de requests are sent,
  // in parts of about 3 MB; headers, cookies and request bodies stay in the browser.
  const recording = $('netzkino-recording-file');
  if (recording) recording.onchange = async () => {
    const file = recording.files?.[0]; const say = text => { $('netzkino-recording-status').textContent = text; };
    if (!file) return;
    recording.disabled = true; say('Mitschnitt wird gelesen …');
    try {
      const har = JSON.parse(await file.text());
      const hosts = ['data.netzkino.de', 'www.netzkino.de', 'netzkino.de'];
      const entries = [];
      for (const e of har?.log?.entries || []) {
        let url; try { url = new URL(e.request?.url || ''); } catch { continue; }
        const content = e.response?.content || {};
        if (url.protocol !== 'https:' || !hosts.includes(url.hostname) || !content.text) continue;
        let text = content.text;
        if (content.encoding === 'base64') { try { text = new TextDecoder().decode(Uint8Array.from(atob(text), c => c.charCodeAt(0))); } catch { continue; } }
        if (!/^\s*[{[]/.test(text) && !text.includes('__NEXT_DATA__')) continue;
        const op = url.searchParams.get('operationName');
        entries.push({url: url.origin + url.pathname + (op ? '?operationName=' + encodeURIComponent(op) : ''), text});
      }
      if (!entries.length) throw new Error('Keine Netzkino-Antworten im Mitschnitt gefunden.');
      let added = 0, answers = 0, total = 0, part = [], size = 0; const operations = new Set();
      const send = async () => {
        if (!part.length) return;
        const r = await endpoint('netzkino-recording', {entries: part});
        added += r.added || 0; answers += r.answers || 0; total = r.total || total;
        (r.operations || []).forEach(o => operations.add(o)); part = []; size = 0;
        say(`${answers} Antworten verarbeitet · ${added} neue Titel …`);
      };
      for (const entry of entries) {
        const length = entry.text.length + entry.url.length;
        if (length > 7000000) continue;
        if (size + length > 3000000) await send();
        part.push(entry); size += length;
      }
      await send();
      say(`Fertig: ${added} neue Titel aus ${answers} Netzkino-Antworten übernommen · Katalog jetzt ${total} Titel` +
        (operations.size ? ` · beobachtete Abfragen: ${[...operations].join(', ')}` : ''));
      offset = 0; refresh();
    } catch (e) { say('Mitschnitt nicht übernommen: ' + e.message); }
    finally { recording.disabled = false; recording.value = ''; }
  };
  $('netzkino-add').onsubmit = async event => {
    event.preventDefault();
    const submit = $('netzkino-add').querySelector('[type=submit]'); submit.disabled = true;
    try {
      await endpoint('netzkino-add', {title: $('netzkino-title').value.trim(), url: $('netzkino-url').value.trim()});
      $('netzkino-title').value = ''; $('netzkino-url').value = '';
      await refresh();
    } catch (error) { message(error.message, true); }
    finally { submit.disabled = false; }
  };
  $('netzkino-sync').onclick = async () => {
    try {
      const r = await endpoint('netzkino-sync', {});
      message(r.started ? 'Katalogprüfung gestartet.' : 'Katalogprüfung läuft bereits.');
      await refresh();
    } catch (error) { message(error.message, true); }
  };
  $('netzkino-auto').onchange = async () => {
    const checked = $('netzkino-auto').checked;
    try { await endpoint('netzkino-auto', {enabled: checked}); await refresh(); }
    catch (error) { $('netzkino-auto').checked = !checked; message(error.message, true); }
  };
  $('netzkino-view-movies').onclick = () => { view='movies'; seriesKey=''; genre=''; offset=0; refresh(); };
  $('netzkino-view-series').onclick = () => { view='series'; seriesKey=''; genre=''; offset=0; refresh(); };
  $('netzkino-back-series').onclick = () => { view='series'; seriesKey=''; offset=0; refresh(); };
  $('netzkino-filter').oninput = () => { offset = 0; clearTimeout(timer); timer = setTimeout(refresh, 250); };
  $('netzkino-origin').onchange = () => { offset = 0; refresh(); };
  if ($('netzkino-sort')) $('netzkino-sort').onchange = () => { offset = 0; refresh(); };
  $('netzkino-prev').onclick = () => { offset = Math.max(0,offset-pageSize); refresh(); };
  $('netzkino-next').onclick = () => { offset += pageSize; refresh(); };
  const sidebar = document.querySelector('[data-view="netzkino"]');
  if (sidebar) sidebar.addEventListener('click', refresh);
  const onPlatformClick = () => setTimeout(() => { if (isVisible()) refresh(); }, 0);
  for (const tab of document.querySelectorAll('.platform-tab[data-platform="netzkino"]'))
    tab.addEventListener('click', onPlatformClick);
  window.MediathekAtlasNetzkino = {refresh, openSeries: key => {view="episodes";seriesKey=key;offset=0;refresh();}};
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', () => { if (isVisible()) refresh(); });
  else if (isVisible()) refresh();
})();
