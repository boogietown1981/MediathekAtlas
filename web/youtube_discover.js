/* Neue YouTube-Kanäle entdecken (youtube_discover.py), 0.6.90.
   Björn (22.11.2026): Vorschläge aus dem eigenen Sehverhalten „anzeigen, validieren und dann ggf. für meine
   Tochter verfügbar machen“. Nur im Erwachsenenbereich (YouTube → Kanal-Abos); die Kinderecke sieht nie
   Vorschläge, nur freigegebene Abos. Vorschau im offiziellen YouTube-Player (window.playRef, Vorschau-Modus). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('youtube-discover')) return;
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined && text !== null) n.textContent = text; if (cls) n.className = cls; return n; };
  const say = (text, error) => { const s = $('youtube-discover-status'); s.textContent = text || ''; s.classList.toggle('netzkino-error', !!error); };
  const minutes = s => s ? (s >= 3600 ? Math.floor(s / 3600) + ':' + String(Math.floor(s / 60) % 60).padStart(2, '0') + ' Std.' : Math.max(1, Math.round(s / 60)) + ' Min.') : '';
  const PROFILE = {kinder: 'passt zu den Kinder-Abos', erwachsene: 'passt zu deinen Abos'};
  let timer = 0;

  function avatar(s) {
    const box = make('span', undefined, 'abo-avatar');
    if (s.avatar) { const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = s.avatar; img.onerror = () => { img.remove(); box.textContent = (s.title || '?').replace(/^@/, '').slice(0, 1).toUpperCase(); }; box.append(img); }
    else box.textContent = (s.title || '?').replace(/^@/, '').slice(0, 1).toUpperCase();
    return box;
  }
  function button(text, title, fn, cls) {
    const b = make('button', text, cls || ''); b.type = 'button'; b.title = title; b.onclick = () => fn(b); return b;
  }
  async function call(payload, button) {
    if (button) button.disabled = true;
    try { return await window.api('youtube-discover', payload); }
    catch (e) { say(e.message, true); return null; }
    finally { if (button) button.disabled = false; }
  }

  function videos(box, s, list) {
    const grid = make('div', undefined, 'discover-videos');
    if (!list.length) grid.append(make('p', 'Keine öffentlichen Videos gefunden.', 'abo-empty'));
    for (const v of list) {
      const tile = make('button', undefined, 'discover-video'); tile.type = 'button';
      tile.title = 'Im YouTube-Player ansehen (Vorschau, mit Werbung)';
      const img = make('img'); img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = v.poster;
      img.onload = () => { if (img.naturalHeight > img.naturalWidth) img.classList.add('is-portrait'); }; tile.append(img);
      tile.append(make('span', v.title || v.video, 'discover-video-title'));
      const meta = [minutes(v.duration), v.published ? new Date(v.published).toLocaleDateString('de-DE') : '', v.short ? 'Short' : '', v.age ? 'altersbeschränkt' : ''].filter(Boolean);
      tile.append(make('span', meta.join(' · '), 'discover-video-meta' + (v.age ? ' netzkino-error' : '')));
      tile.onclick = () => window.playRef ? window.playRef({youtube: 'v.' + v.video, preview: '1'}, v.title || 'YouTube', 'youtube:v.' + v.video)
        : window.open('https://www.youtube.com/watch?v=' + encodeURIComponent(v.video), '_blank', 'noopener');
      grid.append(tile);
    }
    box.querySelector('.discover-videos')?.remove();
    box.append(grid);
    if (s.note) box.append(make('p', s.note, 'nk-warning'));
  }

  function card(s) {
    const box = make('article', undefined, 'abo-card discover-card'); box.dataset.ref = s.ref;
    const body = make('div', undefined, 'abo-body');
    const head = make('div', undefined, 'abo-head'); head.append(make('strong', s.title));
    if (s.ref.startsWith('@') && s.title.toLowerCase() !== s.ref) head.append(make('span', s.ref, 'muted'));
    head.append(make('span', PROFILE[s.profile] || '', 'abo-badge'));
    body.append(head);
    body.append(make('p', (s.why || []).join(' · '), 'abo-rules'));
    const link = make('a', 'Kanal auf YouTube öffnen', 'muted'); link.href = s.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    body.append(link);
    const acts = make('div', undefined, 'abo-actions discover-actions');
    const look = button(s.checked ? 'Videos zeigen' : 'Videos ansehen', 'Die neuesten Videos des Kanals zeigen und probeschauen', async b => {
      say('Kanal wird gelesen …');
      const d = await call({action: 'preview', ref: s.ref}, b);
      if (!d) return;
      say(''); Object.assign(s, d); videos(box, s, d.videos || []); kids.disabled = me.disabled = false;
      kids.title = 'Als Abo in die Kinderecke aufnehmen (nur neue Videos, die 3 neuesten zum Start)';
    });
    const kids = button('★ Für die Kinderecke freigeben', 'Erst „Videos ansehen“, dann freigeben', async b => {
      const d = await call({action: 'kids', ref: s.ref}, b); if (d) { render(d); say('„' + s.title + '“ ist jetzt ein Abo der Kinderecke; die ersten Videos werden geladen.'); window.MediathekAtlasYouTubeAbos?.refresh(); }
    }, 'primary');
    const me = button('▶ Für mich abonnieren', 'Als Abo im Ansehen-Modus aufnehmen', async b => {
      const d = await call({action: 'me', ref: s.ref}, b); if (d) { render(d); say('„' + s.title + '“ ist jetzt ein Abo für dich.'); window.MediathekAtlasYouTubeAbos?.refresh(); }
    });
    // Freigeben erst nach dem Ansehen (validieren): die Knöpfe werden mit der Vorschau frei
    kids.disabled = me.disabled = !s.checked;
    const no = button('Nicht vorschlagen', 'Diesen Kanal nie wieder vorschlagen', async b => {
      const d = await call({action: 'reject', ref: s.ref}, b); if (d) { render(d); say('„' + s.title + '“ wird nicht mehr vorgeschlagen.'); }
    });
    acts.append(look, kids, me, no);
    box.append(avatar(s), body, acts);
    return box;
  }

  function decided(list) {
    if (!list.length) return null;
    const box = make('details', undefined, 'discover-decided');
    box.append(make('summary', 'Entschieden (' + list.length + ')'));
    for (const s of list) {
      const line = make('p', undefined, 'abo-rules');
      line.append((s.title || s.ref) + ' · ' + (s.state === 'approved' ? (s.decided_profile === 'kinder' ? 'für die Kinderecke freigegeben' : 'für dich abonniert') : 'nicht vorschlagen') + ' ');
      if (s.state === 'rejected') line.append(button('wieder vorschlagen', 'Wieder in die Vorschläge aufnehmen', async b => { const d = await call({action: 'reset', ref: s.ref}, b); if (d) render(d); }, 'link'));
      box.append(line);
    }
    return box;
  }

  function render(d) {
    const list = $('youtube-discover-list');
    const open = d.suggestions || [];
    $('youtube-discover-state').textContent = open.length ? '· ' + open.length + ' Vorschläge' : '';
    // 22.11.2026: Während die Suche läuft (alle 5 s), bleiben Karten mit geöffneter Vorschau oder Fokus stehen
    const old = new Map([...list.querySelectorAll(':scope > .discover-card')].map(n => [n.dataset.ref, n]));
    const wasOpen = !!list.querySelector(':scope > .discover-decided')?.open;
    const busy = n => n && (n.querySelector('.discover-videos') || n.contains(document.activeElement));
    const items = open.map(s => busy(old.get(s.ref)) ? old.get(s.ref) : card(s));
    if (!items.length) items.push(make('p', d.running ? 'Suche läuft …' : (d.last ? 'Gerade keine neuen Vorschläge.' : 'Noch nicht gesucht. „Vorschläge suchen“ wählen.'), 'abo-empty'));
    const past = decided(d.decided || []); if (past) { past.open = wasOpen; items.push(past); }
    const keep = window.MediathekAtlasYouTubeAbos?.keepInPlace;
    if (keep) keep(list, items); else list.replaceChildren(...items);
    const when = d.last ? 'Zuletzt gesucht am ' + new Date(d.last * 1000).toLocaleString('de-DE', {dateStyle: 'short', timeStyle: 'short'}) + ' Uhr.' : '';
    $('youtube-discover-info').textContent = [d.running ? d.progress : when, d.error ? 'Hinweis: ' + d.error : ''].filter(Boolean).join(' ');
    clearTimeout(timer);
    if (d.running) timer = setTimeout(load, 5000);
  }
  async function load() {
    try { render(await window.api('youtube-discover')); } catch (e) { say(e.message, true); }
  }
  $('youtube-discover-search').onclick = async e => { const d = await call({action: 'search'}, e.target); if (d) { render(d); say(d.started ? 'Suche gestartet; das kann einige Minuten dauern.' : 'Die Suche läuft bereits.'); } };
  $('youtube-discover').addEventListener('toggle', () => { if ($('youtube-discover').open) load(); });
})();
