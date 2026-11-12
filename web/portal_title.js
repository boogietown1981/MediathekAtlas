/* One title page for Netzkino, Pluto TV and JustWatch TV (0.5.42).
   Björn (12.11.2026): details must look the same on every platform, in the catalogue and in the
   platform tabs, without losing what only one provider publishes. The page uses the Mediathek title
   page (titleview.js: hero with poster, facts, ★ rating, actions, overview, info, cast) and adds the
   same sections for every portal: episodes (series), offline copies (30 days), the IMDb/TVDB/TMDB/
   OMDb/Wikidata check and "Angaben von <Anbieter>". Data: /api/portal-title (portal_title.py). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const SOURCES = {
    netzkino: {play: () => window.playNetzkino, jobs: id => 'netzkino-downloads?id=' + encodeURIComponent(id), add: 'netzkino-download-add',
      action: 'netzkino-download-action', enrich: 'netzkino-enrich', external: 'Bei Netzkino öffnen'},
    pluto: {play: () => window.playPluto, jobs: id => 'pluto-downloads?id=' + encodeURIComponent(id), add: 'pluto-download-add',
      action: 'offline-download-action', enrich: 'pluto-enrich', episodes: id => 'pluto?view=episodes&series=' + encodeURIComponent(id)},
    justwatch: {play: () => window.playJustWatch, jobs: id => 'justwatch-downloads?id=' + encodeURIComponent(id), add: 'justwatch-download-add',
      action: 'offline-download-action', enrich: 'justwatch-enrich', external: 'Bei JustWatch ansehen',
      episodes: id => 'justwatch?view=episodes&series=' + encodeURIComponent(id)}
  };
  const ACTIVE = ['queued', 'downloading', 'tagging'];
  const LABELS = {queued: 'Vorgemerkt', downloading: 'Lädt', tagging: 'MKV wird erstellt', done: 'Offline verfügbar', error: 'Fehler',
    cancelled: 'Abgebrochen', interrupted: 'Unterbrochen', expired: 'Abgelaufen und entfernt', removed: 'Gelöscht'};
  const REF = {unchecked: 'Noch nicht abgeglichen; der Abgleich läuft automatisch im Hintergrund.',
    candidate: 'Eindeutige Referenz gefunden', review: 'Widersprüchliche Referenzen · keine automatische Zuordnung',
    no_match: 'Keine ausreichend eindeutige Referenz gefunden', partial: 'Einige Anbieter waren nicht erreichbar; wird später erneut geprüft'};
  const day = ts => new Date(ts * 1000).toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit', year: 'numeric'});
  const mib = n => (Number(n || 0) / 1048576).toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' MiB';
  const mins = s => s ? Math.round(s / 60) + ' Min.' : '';
  const https = v => typeof v === 'string' && /^https:\/\/[a-z0-9.-]+\//i.test(v) && !/[\s<>'"]/.test(v);
  // Portal artwork comes from the provider's own image hosts (validated https, no referrer).
  const image = (url, alt) => {
    if (!https(url)) return null;
    const img = make('img'); img.src = url; img.alt = alt || ''; img.loading = 'lazy'; img.decoding = 'async';
    img.referrerPolicy = 'no-referrer'; img.onerror = () => img.remove(); return img;
  };
  const epCode = (s, e) => Number.isInteger(s) && Number.isInteger(e) ? 'S' + String(s).padStart(2, '0') + 'E' + String(e).padStart(2, '0') :
    Number.isInteger(e) ? 'Folge ' + e : '';
  let seq = 0, timer = 0;

  function button(text, cls, onclick) { const b = make('button', text, cls); b.type = 'button'; b.onclick = onclick; return b; }
  function link(text, url) {
    const a = make('a', text, 'button');
    if (https(url)) { a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; } else a.setAttribute('aria-disabled', 'true');
    return a;
  }
  function section(title, cls) { const s = make('section', undefined, 'tv-section portal-title-section' + (cls ? ' ' + cls : '')); s.append(make('h2', title)); return s; }
  function play(m, label) {
    const fn = SOURCES[m.source].play();
    if (typeof fn !== 'function') { window.notice?.('Der Player ist nicht geladen; Seite neu laden.', 'error'); return; }
    fn(m.id, label || m.title);
  }

  function ratingChip(r) {
    if (!r || typeof r.value !== 'number') return null;
    const s = make('span', '★ ' + r.value.toLocaleString('de-DE', {maximumFractionDigits: 1}) + (r.source ? ' ' + r.source : ''), 'tv-rating');
    if (r.votes) s.title = Number(r.votes).toLocaleString('de-DE') + ' Stimmen';
    return s;
  }

  async function offlineSection(m, host) {
    const src = SOURCES[m.source], sec = section('Offline ansehen · ' + m.offline.days + ' Tage');
    const note = make('p', m.provider + ' erlaubt ' + m.offline.days + ' Tage Offline-Nutzung. Gespeichert wird wie bei Mediathek-Videos ' +
      '(gleicher Ordner, gleiche Benennung, MKV mit NFO); die Datei enthält die Werbung des Anbieters und wird danach automatisch entfernt.', 'muted');
    const list = make('div', undefined, 'portal-title-jobs');
    const add = button('⬇ Offline speichern (' + m.offline.days + ' Tage)', 'primary', async () => {
      add.disabled = true;
      try {
        const r = await window.api(src.add, {id: m.id});
        note.textContent = r.created ? 'Eingereiht. Fortschritt erscheint hier und unter „Downloads“.' : 'Bereits eingereiht oder offline verfügbar.';
        await paint();
      } catch (e) { note.textContent = 'Kein Download gestartet: ' + e.message; add.disabled = false; }
    });
    sec.append(note, add, list); host.append(sec);
    async function paint() {
      let data; try { data = await window.api(src.jobs(m.id)); } catch (e) { list.textContent = 'Downloadstatus nicht verfügbar: ' + e.message; return; }
      const jobs = (data.items || []).filter(j => !['expired', 'removed'].includes(j.state));
      const busy = jobs.some(j => ACTIVE.includes(j.state) || (j.state === 'done' && j.license !== 'licensed_file'));
      add.disabled = busy || data.ffmpeg === false || data.ytdl?.ok === false;
      add.title = data.ffmpeg === false ? 'ffmpeg fehlt in dieser Installation' : data.ytdl?.ok === false ? 'ytdl-nightly fehlt in dieser Installation' : busy ? 'Bereits eingereiht oder offline verfügbar' : '';
      list.replaceChildren();
      for (const j of jobs) {
        const row = make('div', undefined, 'nk-offline-job nk-offline-' + j.state);
        row.append(make('strong', (LABELS[j.state] || j.state) + ' · ' + (j.target_name || j.title || '')));
        if (j.state === 'downloading') row.append(make('small', mib(j.received) + (j.total ? ' / ca. ' + mib(j.total) : '')));
        if (j.state === 'done' && j.offline_until) row.append(make('small', 'Offline nutzbar bis ' + day(j.offline_until) + ' · noch ' + j.days_left + (j.days_left === 1 ? ' Tag' : ' Tage'), j.days_left <= 3 ? 'nk-warning' : 'muted'));
        if (j.error) row.append(make('small', 'Fehler: ' + j.error, 'nk-warning'));
        const act = (label, action) => button(label, '', async ev => {
          ev.target.disabled = true;
          try { action === 'retry' ? await window.api('retry', {id: j.id}) : await window.api(src.action, {id: j.id, action}); await paint(); }
          catch (e) { note.textContent = e.message; ev.target.disabled = false; }
        });
        if (ACTIVE.includes(j.state)) row.append(act('Abbrechen', 'cancel'));
        if (['error', 'cancelled', 'interrupted'].includes(j.state)) row.append(act('Erneut versuchen', 'retry'));
        if (j.state === 'done') row.append(act('Jetzt löschen', 'delete'));
        list.append(row);
      }
      clearTimeout(timer);
      if (jobs.some(j => ACTIVE.includes(j.state)) && !$('title-view').hidden && $('title-view').dataset.portal === m.source + ':' + m.id)
        timer = setTimeout(paint, 3000);
    }
    await paint();
  }

  function referenceSection(m, host) {
    const sec = section('Werkzuordnung · IMDb / TVDB / TMDB / OMDb / Wikidata');
    const body = make('div');
    const paint = report => {
      body.replaceChildren(make('p', REF[report.status] || 'Wird geprüft'));
      const meta = report.metadata || {}, src = report.field_sources || {}, dl = make('dl', undefined, 'tv-info');
      for (const [key, label] of [['genres', 'Genres'], ['rating', 'Bewertung'], ['directors', 'Regie'], ['writers', 'Drehbuch'], ['country', 'Land']]) {
        const v = meta[key]; if (v == null || v === '' || (Array.isArray(v) && !v.length) || !src[key] || src[key] === m.provider) continue;
        dl.append(make('dt', label + ' · ' + src[key]), make('dd', key === 'rating' ? v + ' / 10' : Array.isArray(v) ? v.map(x => x.name || x).join(', ') : String(v)));
      }
      if (dl.childElementCount) body.append(dl);
      for (const r of (report.references || []).slice(0, 6))
        body.append(make('small', [r.provider, r.title, r.year, r.reference_id, r.eligible ? 'passt' : (r.issues || []).join(' / ')].filter(Boolean).join(' · '), 'nk-ref-candidate'));
      if (report.warnings?.length) body.append(make('p', report.warnings.join(' · '), 'nk-ref-warning'));
    };
    paint(m.reference || {});
    const check = button('↻ Jetzt mit IMDb, TVDB, TMDB und Co. abgleichen', '', async () => {
      check.disabled = true; body.replaceChildren(make('p', 'Referenzen werden geprüft …'));
      try { paint(await window.api(SOURCES[m.source].enrich, {id: m.id, force: true})); }
      catch (e) { body.replaceChildren(make('p', 'Abgleich nicht möglich: ' + e.message)); }
      finally { check.disabled = false; }
    });
    sec.append(body, check); host.append(sec);
  }

  function providerSection(m, host) {
    const sec = section('Angaben von ' + m.provider, 'portal-title-provider');
    const dl = make('dl', undefined, 'tv-info');
    for (const [k, v] of m.provider_facts || []) if (v) dl.append(make('dt', k), make('dd', v));
    if (dl.childElementCount) sec.append(dl);
    for (const n of m.notes || []) sec.append(make('p', n, 'muted'));
    if (m.source === 'netzkino' && window.AtlasNetzkinoDetail?.open) {
      // Netzkino extras (yt-dlp cross-check, separately licensed file) stay in the expert view.
      sec.append(button('Netzkino-Expertenansicht (yt-dlp-Prüfung, separat lizenzierte Datei)', '', () => window.AtlasNetzkinoDetail.open(m.id)));
    }
    host.append(sec);
  }

  async function episodesSection(m, host, token) {
    const src = SOURCES[m.source]; if (!src.episodes) return;
    const sec = section('Staffeln & Folgen'), list = make('div', undefined, 'tv-episodes');
    list.append(make('p', 'Folgen werden geladen …', 'muted')); sec.append(list); host.append(sec);
    let data; try { data = await window.api(src.episodes(m.id)); } catch (e) { list.replaceChildren(make('p', 'Folgen nicht verfügbar: ' + e.message, 'empty')); return; }
    if (token !== seq) return;
    list.replaceChildren();
    if (data.error) list.append(make('p', 'Folgen konnten nicht aktualisiert werden: ' + data.error, 'muted'));
    const items = data.items || [];
    if (!items.length) list.append(make('p', 'Keine Folgen im Katalog.', 'empty'));
    for (const e of items) {
      const row = make('article', undefined, 'tv-episode'), thumb = make('div', undefined, 'tv-thumb');
      const img = image(e.poster || m.poster, ''); if (img) thumb.append(img);
      thumb.append(make('span', epCode(e.season, e.episode) || 'Folge', 'tv-code')); row.append(thumb);
      const body = make('div', undefined, 'tv-epbody');
      body.append(make('h3', (Number.isInteger(e.episode) ? e.episode + '. ' : '') + e.title));
      body.append(make('p', [mins(e.duration), e.year].filter(Boolean).join(' · '), 'tv-epmeta'));
      if (e.summary) body.append(make('p', e.summary, 'tv-epdesc'));
      const acts = make('div', undefined, 'tv-epactions'), canPlay = e.playable !== false && e.playable !== 0;
      if (canPlay) acts.append(button('▶ Abspielen', 'primary', () => play({...m, id: e.id}, m.title + ' · ' + (epCode(e.season, e.episode) ? epCode(e.season, e.episode) + ' · ' : '') + e.title)));
      else if (https(e.web_url || m.web_url)) acts.append(link(src.external || 'Beim Anbieter ansehen', e.web_url || m.web_url));
      acts.append(button('Details & offline speichern', '', () => open(m.source, e.id)));
      body.append(acts); row.append(body); list.append(row);
    }
  }

  async function open(source, id) {
    if (!SOURCES[source] || !id || typeof hero !== 'function') return false;
    const token = ++seq; clearTimeout(timer);
    showTitleView(); pushTitle();
    const host = $('title-view'); host.dataset.portal = source + ':' + id;
    host.replaceChildren(make('p', 'Titel wird geladen …', 'muted tv-loading'));
    let m;
    try { m = await window.api('portal-title?' + new URLSearchParams({source, id})); }
    catch (e) {
      if (token !== seq) return true;
      host.replaceChildren(make('p', 'Details nicht verfügbar: ' + e.message, 'empty'), button('← Zurück', '', () => closeTitleView()));
      return true;
    }
    if (token !== seq) return true;
    const src = SOURCES[source], label = m.kind === 'episode' && m.series ? m.series.title + ' · ' + (epCode(m.season, m.episode) ? epCode(m.season, m.episode) + ' · ' : '') + m.title : m.title;
    const actions = [];
    if (m.kind === 'series') actions.push(button('Folgen anzeigen', 'primary', () => host.querySelector('.tv-episodes')?.scrollIntoView({behavior: 'smooth'})));
    else if (m.playable) actions.push(button(m.kind === 'channel' ? '▶ Live ansehen' : '▶ Abspielen', 'primary play-button', () => play(m, label)));
    if (m.offline?.allowed) actions.push(button('⬇ Offline speichern (' + m.offline.days + ' Tage)', '', () => host.querySelector('.portal-title-jobs')?.parentElement?.scrollIntoView({behavior: 'smooth'})));
    if (https(m.web_url) && (!m.playable || source === 'netzkino' || source === 'justwatch')) actions.push(link(src.external || 'Beim Anbieter ansehen', m.web_url));
    if (m.series?.id) actions.push(button('Zur Serie', '', () => open(source, m.series.id)));
    const facts = [m.year ? String(m.year) : '', mins(m.duration), m.age_rating, ratingChip(m.rating), (m.categories || []).slice(0, 3).join(' · '),
      !m.playable && m.kind !== 'series' ? 'Nur beim Anbieter abspielbar' : ''];
    const info = [['Kategorien', (m.categories || []).join(', ')], ['Regie', (m.directors || []).join(', ')], ['Drehbuch', (m.writers || []).join(', ')],
      ['Land', m.country], ['Sprache', m.language], ['Altersfreigabe', m.age_rating], ['Quelle', m.provider],
      ['Zuordnung', REF[m.reference?.status] ? (m.reference.status === 'candidate' ? '✓ ' : '◌ ') + REF[m.reference.status].split(';')[0] : '']];
    host.replaceChildren(...hero({meta: {title: label, poster: m.poster, fanart: m.fanart}, type: m.kind_label + ' · ' + m.provider, facts,
      overview: m.description, overviewHint: 'Keine Inhaltsangabe veröffentlicht.', actions, info,
      cast: (m.cast || []).map(name => ({name})), image}));
    if (m.kind === 'series') await episodesSection(m, host, token);
    if (token !== seq) return true;
    if (m.offline?.allowed) offlineSection(m, host).catch(() => {});
    if (m.kind !== 'channel') referenceSection(m, host);
    providerSection(m, host);
    return true;
  }
  window.AtlasPortalTitle = {open};
})();
