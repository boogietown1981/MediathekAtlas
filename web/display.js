/* 0.5.55: presentation of tiles and title pages, one set of choices for every platform
   (Verwaltung → Darstellung). The server keeps the choices (display.json); this file applies them
   as classes on <body>, so every tile and title page follows them without knowing about them. */
(() => {
  'use strict';
  const DEFAULTS = {card_size: 'normal', start_source: 'all', start_kind: 'movies', merge_duplicates: true};
  let prefs = {...DEFAULTS}, meta = {switches: [], sizes: []};
  const listeners = [];
  function apply() {
    const body = document.body;
    if (!body) return;
    for (const cls of [...body.classList]) if (cls.startsWith('atlas-hide-')) body.classList.remove(cls);
    for (const [key, value] of Object.entries(prefs))
      if (value === false && /^(card|title)_/.test(key)) body.classList.add('atlas-hide-' + key.replace(/_/g, '-'));
    body.dataset.cardSize = prefs.card_size || 'normal';
  }
  const ready = (async () => {
    // window.api comes from app.js; without a server answer the defaults apply.
    try {
      const data = await window.api('display');
      prefs = {...DEFAULTS, ...(data.display || {})};
      meta = {switches: data.switches || [], sizes: data.sizes || []};
    } catch (e) { console.warn('MediathekAtlas: Darstellung nicht geladen', e); }
    apply();
    return prefs;
  })();
  async function save(change) {
    const data = await window.api('display', {display: change});
    const before = prefs;
    prefs = {...DEFAULTS, ...(data.display || {})};
    apply();
    for (const fn of listeners) { try { fn(prefs, before); } catch (e) { console.warn(e); } }
    return prefs;
  }
  window.AtlasDisplay = {ready, save, apply, get: () => prefs, meta: () => meta, onChange: fn => listeners.push(fn)};
})();
