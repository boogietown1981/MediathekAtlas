/* On-demand Netzkino editorial metadata; official WKWebView, optional yt-dlp check. */
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
    if (!value || (Array.isArray(value) && !value.length)) return;
    const row = node('div', undefined, 'nk-detail-field');
    row.append(node('dt', name), node('dd', Array.isArray(value) ? value.join(' · ') : String(value)));
    host.append(row);
  };
  let currentId = null;
  async function open(id) {
    if (!/^[a-f0-9]{32}$/.test(String(id || ''))) return;
    const dialog = $('atlas-netzkino-detail');
    if (!dialog) return;
    currentId = id;
    const facts = $('atlas-nk-facts');
    const actions = $('atlas-nk-actions');
    $('atlas-nk-title').textContent = 'Netzkino · Details werden geladen …';
    $('atlas-nk-description').textContent = '';
    $('atlas-nk-evidence').textContent = '';
    $('atlas-nk-image').hidden = true;
    facts.replaceChildren(); actions.replaceChildren();
    if (!dialog.open) dialog.showModal();
    try {
      const data = await window.api('netzkino-details?id=' + encodeURIComponent(id));
      if (id !== currentId) return;
      const m = data.details || {};
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
      makeField(facts, 'Originaltitel', m.original_title);
      makeField(facts, 'Jahr', m.year);
      makeField(facts, 'Laufzeit', m.duration_seconds ? Math.round(m.duration_seconds / 60) + ' Minuten' : null);
      makeField(facts, 'Genres', m.genres);
      makeField(facts, 'FSK', m.fsk == null ? null : m.fsk);
      makeField(facts, 'Land', m.country);
      makeField(facts, 'Originalsprache', m.original_language);
      makeField(facts, 'Besetzung', m.cast);
      makeField(facts, 'Regie', m.directors);
      makeField(facts, 'Drehbuch', m.writers);
      makeField(facts, 'Zugangshinweis', m.access_types);
      const watch = node('button', '▶ In MediathekAtlas ansehen', 'primary');
      watch.onclick = async () => {
        watch.disabled = true;
        try {
          const result = await window.api('netzkino-watch', {id});
          if (result.mode === 'official_browser') {
            const popup = window.open(result.page_url, '_blank', 'noopener,noreferrer');
            $('atlas-nk-evidence').textContent = popup ? 'Offizielle Filmseite im Browser geöffnet.' :
              'WebKit-Helfer nicht verfügbar. Bitte „Beim Anbieter öffnen“ wählen, falls der Browser das Pop-up blockiert.';
          } else {
            $('atlas-nk-evidence').textContent = 'Der offizielle Netzkino-Player wurde im separaten macOS-Fenster geöffnet.';
          }
        } catch (e) {
          $('atlas-nk-evidence').textContent = 'Wiedergabefenster konnte nicht gestartet werden: ' + e.message;
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
  window.AtlasNetzkinoDetail = {open};
})();
