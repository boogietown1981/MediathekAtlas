/* On-demand Netzkino editorial metadata; playback in the in-app player, optional yt-dlp check. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const node = (tag, text, css) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (css) el.className = css;
    return el;
  };
  const makeField = (host, name, value) => {
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return;
    const row = node('div', undefined, 'nk-detail-field');
    row.append(node('dt', name), node('dd', Array.isArray(value) ? value.join(' · ') : String(value)));
    if (['Originalsprache','Zugangshinweis','Originaltitel','Besetzung'].includes(name)) row.classList.add('nk-detail-field--wide');
    host.append(row);
  };
  let currentId = null;
  async function play(id, label) {
    if (!/^[a-f0-9]{32}$/.test(String(id || ''))) throw new Error('Ungültiger Film');
    if (typeof window.playNetzkino !== 'function') throw new Error('Der Player ist nicht geladen; Seite neu laden.');
    // Same in-app player as the Mediathek videos: offline copy first, otherwise the MP4 via ytdl-nightly.
    return window.playNetzkino(id, label);
  }
  async function open(id) {
    if (!/^[a-f0-9]{32}$/.test(String(id || ''))) return;
    const dialog = $('atlas-netzkino-detail');
    if (!dialog) return;
    currentId = id;
    const facts = $('atlas-nk-facts');
    const quickFacts = $('atlas-nk-quickfacts');
    const actions = $('atlas-nk-actions');
    $('atlas-nk-title').textContent = 'Netzkino · Details werden geladen …';
    $('atlas-nk-description').textContent = '';
    $('atlas-nk-evidence').textContent = '';
    $('atlas-nk-image').hidden = true;
    facts.replaceChildren(); quickFacts.replaceChildren(); actions.replaceChildren();
    $('atlas-nk-reference').replaceChildren();$('atlas-nk-reference-facts').replaceChildren();
    if (!dialog.open) dialog.showModal();
    try {
      const data = await window.api('netzkino-details?id=' + encodeURIComponent(id));
      if (id !== currentId) return;
      const m = data.details || {};
      if (window.AtlasNetzkinoDownloads) window.AtlasNetzkinoDownloads.mount(id);
      $('atlas-nk-title').textContent = m.title || 'Netzkino-Film';
      $('atlas-nk-description').textContent = m.description || 'Keine ausführliche Inhaltsbeschreibung veröffentlicht.';
      $('atlas-nk-evidence').textContent = (data.error_type ?
        'Detailabruf eingeschränkt (' + data.error_type + '); vorhandene Angaben werden angezeigt.' :
        'Öffentliche Anbieter-Metadaten · ' + (data.cached ? 'zwischengespeichert' : 'aktuell geladen')) +
        ' · Werkidentität und Wiedergaberechte nicht unabhängig bestätigt.';
      if (m.poster && /^https:\/\//.test(m.poster)) {
        const img = $('atlas-nk-image'); img.src = m.poster; img.hidden = false; img.alt = 'Filmcover';
        img.referrerPolicy = 'no-referrer';
      }
      // Compact sidebar, leaving the broad content area for descriptions/credits.
      makeField(quickFacts, 'Jahr', m.year == null ? '–' : m.year);
      makeField(quickFacts, 'FSK', m.fsk == null ? '–' : m.fsk);
      makeField(quickFacts, 'Laufzeit', m.duration_seconds ? Math.round(m.duration_seconds / 60) + ' Min.' : '–');
      makeField(quickFacts, 'Land', m.country || '–');
      makeField(quickFacts, 'Originalsprache', m.original_language || 'Unbekannt');
      makeField(quickFacts, 'Zugangshinweis', m.access_types?.length ? m.access_types : ['Nicht geprüft']);
      makeField(facts, 'Originaltitel', m.original_title);
      makeField(facts, 'Genres', m.genres);
      makeField(facts, 'Besetzung', m.cast);
      makeField(facts, 'Regie', m.directors);
      makeField(facts, 'Drehbuch', m.writers);
      const refArea = $('atlas-nk-reference');
      const refFields = $('atlas-nk-reference-facts');
      const sourceNames = {description:'Beschreibung', genres:'Genres', cast:'Besetzung',
          directors:'Regie',writers:'Drehbuch',poster:'Poster',rating:'Bewertung',
          votes:'Bewertungsstimmen',series_description:'Serienbeschreibung',reference_description:'Weitere Inhaltsangabe'};
      const renderReference = (report) => {
        if (id !== currentId) return;
        refArea.replaceChildren();refFields.replaceChildren();
        const messages = {unchecked:'Referenzen noch nicht abgeglichen',
          candidate:'Plausible Referenz gefunden · noch keine bestätigte Werkidentität',
          review:'Widersprüchliche Referenzen · bitte manuell prüfen',
          no_match:'Keine ausreichend eindeutige Referenz gefunden',
          partial:'Einige Anbieter waren nicht erreichbar; später erneut prüfen'};
        refArea.append(node('h3','IMDb / TMDB / TVDB / OMDb / Wikidata'),
          node('p',messages[report.status]||'Erkennung wird geprüft'));
        if (report.status==='unchecked') return;
        for (const [field,source] of Object.entries(report.field_sources||{})) {
          if (source==='Netzkino' || !Object.prototype.hasOwnProperty.call(sourceNames,field)) continue;
          const v=report.metadata?.[field];
          if (field==='poster') continue;
          makeField(refFields,sourceNames[field]+' · '+source,
            field==='rating' && typeof v==='number' ? v+' / 10' : v);
        }
        if (!m.description && report.metadata?.description && report.field_sources?.description!=='Netzkino') {
          $('atlas-nk-description').textContent=report.metadata.description;
        }
        for (const reference of (report.references||[]).slice(0,8)) {
          const box=node('div',undefined,'nk-ref-candidate');
          box.append(node('strong',reference.provider+' · '+reference.title),
            node('small',[reference.year,reference.reference_id,
              reference.episode_verified?'Episode unabhängig bestätigt':null]
              .filter(Boolean).join(' · ')));
          if (reference.issues?.length) box.append(node('small',reference.issues.join(' / '),'nk-ref-warning'));
          const container=refArea.querySelector('.nk-ref-candidates')||node('div',undefined,'nk-ref-candidates');
          if (!container.parentElement) refArea.append(container);
          container.append(box);
        }
        if (report.warnings?.length) refArea.append(node('p',report.warnings.join(' · '),'nk-ref-warning'));
        refArea.append(node('small','Referenzkandidaten sind keine Downloadberechtigung oder automatische Werkbestätigung.'));
      };
      window.api('netzkino-reference-report?id='+encodeURIComponent(id)).then(renderReference).catch(()=>{});
      const enrich=node('button','Mit IMDb, TMDB, TVDB und Co. abgleichen');
      enrich.type='button';
      enrich.onclick=async()=>{
        enrich.disabled=true;
        refArea.textContent='Externe Referenzen werden mit den vorhandenen Anbieterzugängen geprüft …';
        try {
          const result=await window.api('netzkino-enrich',{id,force:true});
          renderReference(result);
        } catch(e) {if (id===currentId)refArea.textContent='Referenzprüfung nicht verfügbar: '+e.message;}
        finally {enrich.disabled=false;}
      };
      actions.append(enrich);
      const watch = node('button', '▶ In MediathekAtlas ansehen', 'primary');
      watch.onclick = async () => {
        watch.disabled = true;
        try {
          await play(id, data.title);
        } catch (e) {
          $('atlas-nk-evidence').textContent = 'Wiedergabe konnte nicht gestartet werden: ' + e.message;
        } finally { watch.disabled = false; }
      };
      actions.append(watch);
      const official = node('a', 'Beim Anbieter öffnen');
      official.href = data.page_url || '#'; official.target = '_blank'; official.rel = 'noopener noreferrer';
      actions.append(official);
      const check = node('button', 'Mit yt-dlp gegenprüfen (ohne Download)');
      check.onclick = async () => {
        check.disabled = true;
        try {
          const result = await window.api('netzkino-metadata-probe', {id});
          const box = $('atlas-nk-validation'); box.replaceChildren();
          if (result.status !== 'ok') {
            box.textContent = (result.error || result.status) + ' · Keine Datei heruntergeladen.';
          } else {
            const m = result.metadata || {};
            box.append(node('strong', 'Unabhängiger Extraktorcheck – kein Download'),
              node('p', [m.title,m.year,m.duration_seconds ? Math.round(m.duration_seconds/60) + ' Minuten' : null]
                .filter(Boolean).join(' · ')));
            if (result.warnings?.length) box.append(node('p', 'Auffällig: ' + result.warnings.join('; '), 'nk-warning'));
            else box.append(node('p', 'Keine Abweichung in den gemeinsam vorhandenen Vergleichsfeldern.'));
            box.append(node('small', 'Technischer Zugriff ist kein Rechte- oder Verfügbarkeitsnachweis.'));
          }
        } catch (e) { $('atlas-nk-validation').textContent = 'Prüfung fehlgeschlagen: ' + e.message; }
        finally { check.disabled = false; }
      };
      actions.append(check);
    } catch (e) {
      $('atlas-nk-title').textContent = 'Netzkino-Details konnten nicht geladen werden';
      $('atlas-nk-evidence').textContent = e.message;
    }
  }
  $('atlas-nk-close')?.addEventListener('click', () => { currentId = null; $('atlas-netzkino-detail').close(); });
  window.AtlasNetzkinoDetail = {open, play};
})();
