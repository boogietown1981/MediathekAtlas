/* 0.5.38: one category bar and rating badge for every film source (Netzkino, Pluto TV …).
   0.5.83: categories are the fixed German list of categories.py, assigned after the reference check. */
(() => {
  'use strict';
  // 0.5.83: special values of categories.py (not a category of their own).
  const SPECIAL = ['Unklassifiziert', 'Sonstige', 'Unbekannt'];
  const make = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value !== undefined) n.textContent = value;
    if (cls) n.className = cls;
    return n;
  };
  // counts: [{genre, n}], current: selected genre ('' = all), pick(genre) reloads the view.
  function render(host, counts, current, pick) {
    if (!host) return;
    host.replaceChildren();
    const list = counts || [];
    if (!list.length) { host.hidden = true; return; }
    host.hidden = false;
    host.append(make('strong', 'Kategorien'));
    const total = list.reduce((sum, c) => sum + (c.n || 0), 0);
    const chip = (label, value, n) => {
      const special = SPECIAL.includes(value);
      const b = make('button', n === undefined ? label : `${label} · ${n}`, 'portal-category' + (special ? ' portal-category-special' : '') + (value === current ? ' primary' : ''));
      if (value === 'Unklassifiziert') b.title = 'Noch nicht mit IMDb/TMDB/TVDB abgeglichen – die Kategorie folgt nach dem Abgleich.';
      else if (value === 'Sonstige') b.title = 'Abgeglichen, aber kein Genre passt zu einer der festen Kategorien.';
      b.type = 'button'; b.setAttribute('aria-pressed', String(value === current));
      b.onclick = () => pick(value === current ? '' : value);
      return b;
    };
    host.append(chip('Alle', '', undefined));
    for (const c of list) host.append(chip(c.genre, c.genre, c.n));
    if (current && !list.some(c => c.genre === current)) host.append(chip(current, current, 0));
    host.title = total ? 'Einheitliche Kategorien aller Anbieter nach dem Metadaten-Abgleich. Ein Titel kann in mehreren Kategorien stehen.' : '';
  }
  function rating(r) {
    if (!r || typeof r.value !== 'number') return null;
    const text = '★ ' + r.value.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + (r.source ? ' ' + r.source : '');
    const n = make('span', text, 'portal-rating');
    if (r.votes) n.title = Number(r.votes).toLocaleString('de-DE') + ' Stimmen';
    return n;
  }
  function categories(list) {
    const names = (list || []).filter(c => c && !SPECIAL.includes(c));
    return names.length ? make('small', names.slice(0, 4).join(' · '), 'portal-category-line') : null;
  }
  window.AtlasPortalCategories = {render, rating, categories};
})();
