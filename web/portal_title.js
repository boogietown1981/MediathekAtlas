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
      action: 'offline-download-action', enrich: 'pluto-enrich'},
    justwatch: {play: () => window.playJustWatch, jobs: id => 'justwatch-downloads?id=' + encodeURIComponent(id), add: 'justwatch-download-add',
      action: 'offline-download-action', enrich: 'justwatch-enrich', external: 'Bei JustWatch ansehen'},
    rakuten: {play: () => window.playRakuten, jobs: id => 'rakuten-downloads?id=' + encodeURIComponent(id), add: 'rakuten-download-add',
      action: 'offline-download-action', enrich: 'rakuten-enrich', external: 'Bei Rakuten TV ansehen'},
    joyn: {play: () => null, jobs: id => 'joyn-downloads?id=' + encodeURIComponent(id), add: '',
      action: 'offline-download-action', enrich: 'joyn-enrich', external: 'Bei Joyn ansehen'},
    plex: {play: () => window.playPlex, jobs: id => 'plex-downloads?id=' + encodeURIComponent(id), add: '',
      action: 'offline-download-action', enrich: 'plex-enrich', external: 'Bei Plex ansehen'},
    toggo: {play: () => window.playToggo, jobs: id => 'toggo-downloads?id=' + encodeURIComponent(id), add: '',
      action: 'offline-download-action', enrich: 'toggo-enrich', external: 'Bei TOGGO ansehen'},
    crunchyroll: {play: () => null, jobs: id => 'crunchyroll-downloads?id=' + encodeURIComponent(id), add: '',
      action: 'offline-download-action', enrich: 'crunchyroll-enrich', external: 'Bei Crunchyroll ansehen'},
    youtube: {play: () => window.playYouTube, jobs: id => 'youtube-downloads?id=' + encodeURIComponent(id), add: 'youtube-download-add',
      action: 'offline-download-action', enrich: 'youtube-enrich', external: 'Bei YouTube ansehen'}
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
  // 0.5.91: direkter Player-Link + Autostart-Kennung für Anbieter mit Kopierschutz (web/direct_start.js)
  const direct = (source, url) => window.AtlasDirect ? window.AtlasDirect.href(source, url) : url;
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
    if (typeof fn !== 'function') { window.notice?.(window.atlasPlayerMissing?.() || 'Der Player ist nicht geladen; Seite neu laden.', 'error'); return; }
    fn(m.id, label || m.title);
  }

  function ratingChip(r) {
    if (!r || typeof r.value !== 'number') return null;
    const s = make('span', '★ ' + r.value.toLocaleString('de-DE', {maximumFractionDigits: 1}) + (r.source ? ' ' + r.source : ''), 'tv-rating');
    if (r.votes) s.title = Number(r.votes).toLocaleString('de-DE') + ' Stimmen';
    return s;
  }

  // 0.5.70: the versions that can be saved, one click each (resolution levels of the provider).
  function versionSection(m, host) {
    const node = window.AtlasOffline?.versions(m.source, m.id, m.title); if (!node) return;
    const sec = section('Fassungen zum Herunterladen'); sec.classList.add('portal-title-versions'); sec.append(node); host.append(sec);
  }
  async function offlineSection(m, host) {
    const src = SOURCES[m.source], sec = section('Offline ansehen · ' + m.offline.days + ' Tage');
    const note = make('p', m.provider + ' erlaubt ' + m.offline.days + ' Tage Offline-Nutzung. Gespeichert wird wie bei Mediathek-Videos ' +
      '(gleicher Ordner, gleiche Benennung, MKV mit NFO); die Datei enthält die Werbung des Anbieters und wird danach automatisch entfernt.', 'muted');
    const list = make('div', undefined, 'portal-title-jobs');
    // 0.5.60: one offline button only (in the header); this section appears once a copy exists.
    window.AtlasOffline?.onChange(m.source, () => sec.isConnected ? (paint(), true) : false);
    sec.hidden = true;
    sec.append(note, list); host.append(sec);
    async function paint() {
      let data; try { data = await window.api(src.jobs(m.id)); } catch (e) { list.textContent = 'Downloadstatus nicht verfügbar: ' + e.message; return; }
      const jobs = (data.items || []).filter(j => !['expired', 'removed'].includes(j.state));
      list.replaceChildren(); sec.hidden = !jobs.length;
      for (const j of jobs) {
        const row = make('div', undefined, 'nk-offline-job nk-offline-' + j.state);
        row.append(make('strong', (LABELS[j.state] || j.state) + ' · ' + (j.target_name || j.title || '')));
        if (j.state === 'queued' && j.not_before) row.append(make('small', 'Startet um ' + new Date(j.not_before * 1000).toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'}) + ' Uhr (Jugendschutz-Zeitfenster von JustWatch)', 'muted'));
        if (j.state === 'downloading') row.append(make('small', mib(j.received) + (j.total ? ' / ca. ' + mib(j.total) : '')));
        if (j.state === 'done' && j.offline_until) row.append(make('small', 'Offline nutzbar bis ' + day(j.offline_until) + ' · noch ' + j.days_left + (j.days_left === 1 ? ' Tag' : ' Tage'), j.days_left <= 3 ? 'nk-warning' : 'muted'));
        if (j.error) row.append(make('small', 'Fehler: ' + j.error, 'nk-warning'));
        const act = (label, action) => button(label, '', async ev => {
          ev.target.disabled = true;
          try { action === 'retry' ? await window.api('retry', {id: j.id}) : await window.api(src.action, {id: j.id, action}); await paint(); window.AtlasOffline?.refresh(m.source); }
          catch (e) { note.textContent = e.message; ev.target.disabled = false; }
        });
        if (ACTIVE.includes(j.state)) row.append(act('Abbrechen', 'cancel'));
        if (['error', 'cancelled', 'interrupted'].includes(j.state)) row.append(act('Erneut versuchen', 'retry'));
        if (j.state === 'done') row.append(act('Jetzt löschen', 'delete'));
        list.append(row);
      }
    }
    await paint();
  }

  // 0.5.60 (Björn, 12.11.2026, title page of "#Roxy"): candidate lines with tt numbers, "IMDb Offline",
  // "Erscheinungsjahr widersprüchlich" and the provider's access hints do not belong on a film page.
  // Both blocks stay available in one closed area "Technische Angaben" at the end of the page.
  const refName = p => p === 'IMDb Offline' ? 'IMDb' : (p || '');
  function referenceSection(m, host) {
    const sec = section('Abgleich mit IMDb, TVDB, TMDB, OMDb und Wikidata');
    const body = make('div');
    const paint = report => {
      body.replaceChildren(make('p', REF[report.status] || 'Wird geprüft'));
      const meta = report.metadata || {}, src = report.field_sources || {}, dl = make('dl', undefined, 'tv-info');
      for (const [key, label] of [['genres', 'Genres'], ['rating', 'Bewertung'], ['directors', 'Regie'], ['writers', 'Drehbuch'], ['country', 'Land']]) {
        const v = meta[key]; if (v == null || v === '' || (Array.isArray(v) && !v.length) || !src[key] || src[key] === m.provider) continue;
        dl.append(make('dt', label + ' · ' + refName(src[key])), make('dd', key === 'rating' ? v + ' / 10' : Array.isArray(v) ? v.map(x => x.name || x).join(', ') : String(v)));
      }
      if (dl.childElementCount) body.append(dl);
      for (const r of (report.references || []).slice(0, 6))
        body.append(make('small', [refName(r.provider), r.title, r.year, r.reference_id, r.eligible ? 'ausgewählt' : (r.issues || []).join(' / ')].filter(Boolean).join(' · '), 'nk-ref-candidate'));
      if (report.warnings?.length) body.append(make('p', report.warnings.join(' · '), 'nk-ref-warning'));
    };
    paint(m.reference || {});
    const check = button('↻ Erneut abgleichen', '', async () => {
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
    if (m.source === 'netzkino' && m.kind !== 'series' && window.AtlasNetzkinoDetail?.open) {
      // Netzkino extras (yt-dlp cross-check, separately licensed file) stay in the expert view.
      sec.append(button('Netzkino-Expertenansicht (yt-dlp-Prüfung, separat lizenzierte Datei)', '', () => window.AtlasNetzkinoDetail.open(m.id)));
    }
    host.append(sec);
  }

  // 0.5.45: episodes come with the series model (portal_title.py) and are shown like the Mediathek
  // series page: season tabs ("Alle · n", "Staffel N · n"), one row per episode with play, offline
  // and details, the same for Netzkino, Pluto TV and JustWatch TV (Björn, 12.11.2026).
  function episodesSection(m, host) {
    const src = SOURCES[m.source], episodes = m.episodes || [];
    const sec = section('Staffeln & Folgen · ' + episodes.length, 'portal-title-episodes');
    const tabs = make('div', undefined, 'tv-tabs'), list = make('div', undefined, 'tv-episodes');
    tabs.setAttribute('role', 'tablist'); sec.append(tabs, list); host.append(sec);
    if (!episodes.length) { list.append(make('p', 'Keine Folgen im Katalog.', 'empty')); return; }
    const seasons = [...new Set(episodes.map(e => e.season))].sort((a, b) => (a ?? 1e9) - (b ?? 1e9));
    let current = 'all';
    const tab = (key, text, count) => {
      const t = button(text + ' · ' + count, 'tv-tab' + (key === current ? ' active' : ''), () => { current = key; paintTabs(); paintRows(); });
      t.setAttribute('role', 'tab'); t.setAttribute('aria-selected', String(key === current)); return t;
    };
    function paintTabs() {
      tabs.replaceChildren();
      if (seasons.length < 2) return;
      tabs.append(tab('all', 'Alle', episodes.length));
      for (const s of seasons) tabs.append(tab(s, s == null ? 'Ohne Staffel' : 'Staffel ' + s, episodes.filter(e => e.season === s).length));
    }
    function paintRows() {
      list.replaceChildren();
      for (const e of episodes) {
        if (current !== 'all' && e.season !== current) continue;
        const code = epCode(e.season, e.episode), row = make('article', undefined, 'tv-episode'), thumb = make('div', undefined, 'tv-thumb');
        const img = image(e.poster || m.poster, ''); if (img) thumb.append(img);
        thumb.append(make('span', code || 'Folge', 'tv-code')); row.append(thumb);
        const body = make('div', undefined, 'tv-epbody');
        body.append(make('h3', (Number.isInteger(e.episode) ? e.episode + '. ' : '') + (e.title || m.title)));
        const meta = [mins(e.duration), e.year, e.badge];
        body.append(make('p', meta.filter(Boolean).join(' · '), 'tv-epmeta'));
        if (e.summary) body.append(make('p', e.summary, 'tv-epdesc'));
        const acts = make('div', undefined, 'tv-epactions');
        if (e.playable) acts.append(button('▶ Abspielen', 'primary', () => play({...m, id: e.id}, m.title + ' · ' + (code ? code + ' · ' : '') + (e.title || ''))));
        // TOGGO: keep the way to toggo.de beside the player button.
        if (e.playable && m.source === 'toggo' && https(e.web_url)) acts.append(link(src.external, direct(m.source, e.web_url)));
        else if (https(e.web_url || m.web_url)) acts.append(link(src.external || 'Beim Anbieter ansehen', direct(m.source, e.web_url || m.web_url)));
        const off = e.offline && window.AtlasOffline?.control(m.source, e.id, m.title + (code ? ' · ' + code : ''), {night: !!e.night});
        if (off) acts.append(off);
        else if (e.protected) { const lock = window.AtlasOffline?.protectedNote(); if (lock) acts.append(lock); }
        acts.append(button('Details', '', () => open(m.source, e.id)));
        body.append(acts); row.append(body); list.append(row);
      }
    }
    paintTabs(); paintRows();
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
    if (m.kind === 'series') actions.push(button('Folgen anzeigen', 'primary', () => host.querySelector('.portal-title-episodes')?.scrollIntoView({behavior: 'smooth'})));
    else if (m.playable) actions.push(button(m.kind === 'channel' ? '▶ Live ansehen' : '▶ Abspielen', 'primary play-button', () => play(m, label)));
    if (m.offline?.allowed) {
      const save = window.AtlasOffline?.control(m.source, m.id, m.title, {night: !!m.offline.night});
      if (save) actions.push(save);
    }
    if (https(m.web_url) && (!m.playable || source === 'netzkino' || source === 'justwatch' || source === 'rakuten' || source === 'youtube' || source === 'joyn' || source === 'toggo' || source === 'crunchyroll' || source === 'plex')) actions.push(link(src.external || 'Beim Anbieter ansehen', direct(source, m.web_url)));
    if (m.series?.id) actions.push(button('Zur Serie', '', () => open(source, m.series.id)));
    const facts = [m.year ? String(m.year) : '', mins(m.duration), m.age_rating, ratingChip(m.rating), (m.categories || []).slice(0, 3).join(' · '),
      !m.playable && m.kind !== 'series' ? (m.offline?.night ? 'Tagsüber nur beim Anbieter · nachts speicherbar' : m.protected ? '🔒 Kopiergeschützt · nur im JustWatch-Player' : m.source === 'toggo' ? '🔒 Kopiergeschützt · nur bei TOGGO' : m.source === 'crunchyroll' ? '🔒 Kopiergeschützt · nur bei Crunchyroll (Abo)' : 'Nur beim Anbieter abspielbar') : ''];
    const info = [['Kategorien', (m.categories || []).join(', ')], ['Regie', (m.directors || []).join(', ')], ['Drehbuch', (m.writers || []).join(', ')],
      ['Land', m.country], ['Sprache', m.language], ['Altersfreigabe', m.age_rating], ['Anbieter', m.provider]];
    host.replaceChildren(...hero({meta: {title: label, poster: m.poster, fanart: m.fanart}, type: m.kind_label + ' · ' + m.provider, facts,
      overview: m.description, overviewHint: 'Keine Inhaltsangabe veröffentlicht.', actions, info,
      cast: (m.cast || []).map(name => ({name})), image,
      castRef: m.cast_ref && m.kind !== 'channel' ? {...m.cast_ref, kind: m.kind === 'episode' ? 'series' : m.kind, title: m.kind === 'episode' && m.series ? m.series.title : m.title, year: m.year} : null}));
    if (m.kind === 'series') episodesSection(m, host);
    if (m.offline?.allowed && m.kind !== 'series' && !m.offline.night) versionSection(m, host);
    if (m.offline?.allowed) offlineSection(m, host).catch(() => {});
    const expert = make('details', undefined, 'tv-section portal-title-expert');
    expert.append(make('summary', 'Technische Angaben · Abgleich und Anbieterdaten'));
    if (m.kind !== 'channel' && !(m.source === 'netzkino' && m.kind === 'series')) referenceSection(m, expert);
    providerSection(m, expert);
    host.append(expert);
    return true;
  }
  window.AtlasPortalTitle = {open};
})();
