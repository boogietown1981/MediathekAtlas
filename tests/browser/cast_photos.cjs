/* 0.6.55: Besetzung mit Fotos auf der Titelseite.

   Seeds the cast photo store (tests/browser/seed_0655.py: cached TMDB answers, two local photos), starts
   MediathekAtlas without background work and without network to TMDB, opens a film page and checks:
   Regie and Besetzung in one row, photos from /api/cast-photo (never image.tmdb.org), initials where no
   photo is known, and without a TMDB key the hint with the button to the settings.
   Usage: node tests/browser/cast_photos.cjs [screenshot folder] */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const shots = process.argv[2] || '';

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}
async function waitFor(url, seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    try { const r = await fetch(url); if (r.ok) return; } catch (e) { /* not up yet */ }
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('MediathekAtlas ist nach ' + seconds + ' s nicht erreichbar');
}

const FILM = {
  id: 'offer-1', work_id: 'work-1', offer_count: 1, state: 'matched', available: true,
  source: { title: 'Die Verurteilten', channel: 'ARD', duration: 8520, description: '' },
  metadata: {
    kind: 'movie', title: 'Die Verurteilten', year: 1994, provider: 'IMDb Offline', reference_id: 'tt0111161',
    genres: ['Drama'], directors: ['Frank Darabont'],
    cast: [{ name: 'Tim Robbins', role: 'Andy Dufresne', imdb_id: 'nm0000209' }, { name: 'Bob Gunton', role: 'Warden Norton' }],
  },
};

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-0655-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  execFileSync(process.env.PYTHON || 'python3', ['tests/browser/seed_0655.py', path.join(home, 'data')], { cwd: ROOT });
  const port = await freePort();
  const server = spawn(process.env.PYTHON || 'python3', ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' },
  });
  const problems = [];
  const remote = [];
  const browser = await playwright.chromium.launch();
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: shots ? 2 : 1 });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    page.on('request', r => { if (/tmdb\.org/.test(r.url())) remote.push(r.url()); });
    page.on('response', r => {
      const u = new URL(r.url());
      if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400) problems.push(r.status() + ' ' + u.pathname);
    });
    page.on('dialog', d => d.dismiss());
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasDisplay.ready);

    // 1. Without a TMDB key: names with initials and the hint pointing to the settings.
    await page.evaluate(f => { latestSettings.tmdb_set = false; openMovie(f); }, FILM);
    await page.waitForSelector('#title-view .tv-section-cast .tv-cast-note', { timeout: 10000 }).catch(() => problems.push('Hinweis ohne TMDB-Zugang fehlt'));
    const plain = await page.evaluate(() => ({
      head: document.querySelector('#title-view .tv-section-cast h2')?.textContent,
      people: [...document.querySelectorAll('#title-view .tv-person')].map(p => [p.querySelector('strong').textContent, p.querySelector('small')?.textContent || '']),
      note: document.querySelector('#title-view .tv-cast-note')?.textContent || '',
      photos: document.querySelectorAll('#title-view img.tv-photo').length,
    }));
    if (plain.head !== 'Besetzung & Regie') problems.push('Überschrift: ' + plain.head);
    if (JSON.stringify(plain.people) !== JSON.stringify([['Frank Darabont', 'Regie'], ['Tim Robbins', 'Andy Dufresne'], ['Bob Gunton', 'Warden Norton']]))
      problems.push('Reihe: ' + JSON.stringify(plain.people));
    if (!/TMDB-Zugang/.test(plain.note) || !/Einstellungen öffnen/.test(plain.note)) problems.push('Hinweis: ' + plain.note);
    if (plain.photos) problems.push('Fotos ohne Schlüssel');
    if (shots) await page.screenshot({ path: path.join(shots, '0.6.55-besetzung-ohne-schluessel.png'), fullPage: false });
    await page.locator('#title-view .tv-cast-note button').click();
    await page.waitForFunction(() => !document.getElementById('settings').hidden, null, { timeout: 5000 }).catch(() => problems.push('Einstellungen öffnen sich nicht'));

    // 2. With a TMDB key: photos from the local store, initials for the person without a photo.
    await page.evaluate(() => api('settings', { tmdb: 'k'.repeat(32) }));
    await page.evaluate(f => { latestSettings.tmdb_set = true; openMovie(f); }, FILM);
    await page.waitForFunction(() => document.querySelectorAll('#title-view img.tv-photo').length === 2
      && [...document.querySelectorAll('#title-view img.tv-photo')].every(i => i.complete && i.naturalWidth > 0), null, { timeout: 15000 })
      .catch(() => problems.push('Fotos erscheinen nicht'));
    const shown = await page.evaluate(() => ({
      photos: [...document.querySelectorAll('#title-view img.tv-photo')].map(i => [i.alt, new URL(i.src).pathname]),
      initials: [...document.querySelectorAll('#title-view span.tv-avatar')].map(s => s.textContent),
      note: document.querySelector('#title-view .tv-cast-note')?.textContent || '',
    }));
    if (JSON.stringify(shown.photos) !== JSON.stringify([['Frank Darabont', '/api/cast-photo'], ['Tim Robbins', '/api/cast-photo']])) problems.push('Fotos: ' + JSON.stringify(shown.photos));
    if (JSON.stringify(shown.initials) !== JSON.stringify(['BG'])) problems.push('Initialen: ' + JSON.stringify(shown.initials));
    if (shown.note) problems.push('Hinweis trotz Schlüssel: ' + shown.note);
    if (remote.length) problems.push('Browser fragt TMDB direkt: ' + remote[0]);
    // 0.6.57: further people of the title behind "Weitere … anzeigen".
    const moreButton = page.locator('#title-view .tv-cast-more');
    if (await moreButton.textContent().catch(() => '') !== 'Weitere 6 anzeigen') problems.push('Knopf weitere: ' + await moreButton.textContent().catch(() => 'fehlt'));
    else {
      await moreButton.click();
      const after = await page.evaluate(() => [...document.querySelectorAll('#title-view .tv-person strong')].map(s => s.textContent));
      if (after.length !== 9 || after[3] !== 'Morgan Freeman') problems.push('Nach „Weitere“: ' + JSON.stringify(after));
    }
    // 0.6.57: a film without own cast (Plex) gets the cast of its TMDB credits, 14 visible, the rest behind "Alle … anzeigen".
    await page.evaluate(f => openMovie(f), { ...FILM, id: 'offer-2', work_id: 'work-2',
      metadata: { kind: 'movie', title: 'Plexfilm', year: 2001, provider: 'IMDb Offline', reference_id: 'tt0000002', cast: [], directors: [] } });
    await page.waitForFunction(() => document.querySelectorAll('#title-view .tv-person').length === 14, null, { timeout: 10000 })
      .catch(() => problems.push('Besetzung ohne eigene Angaben fehlt'));
    const plex = await page.evaluate(() => ({
      hidden: document.querySelector('#title-view .tv-section-cast')?.hidden,
      head: document.querySelector('#title-view .tv-section-cast h2')?.textContent,
      first: document.querySelector('#title-view .tv-person small')?.textContent,
      button: document.querySelector('#title-view .tv-cast-more')?.textContent,
    }));
    if (plex.hidden !== false || plex.head !== 'Besetzung & Regie' || plex.first !== 'Regie' || plex.button !== 'Alle 2 anzeigen') problems.push('Plex-Fall: ' + JSON.stringify(plex));
    // A photo without a session token is refused.
    const status = await page.evaluate(() => fetch('/api/cast-photo?p=robbins.png&token=falsch').then(r => r.status));
    if (status !== 403) problems.push('Foto ohne Seitenschlüssel: ' + status);
    problems.splice(0, problems.length, ...problems.filter(p => p !== '403 /api/cast-photo'));
    if (shots) {
      await page.locator('#title-view .tv-section-cast').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(shots, '0.6.55-besetzung-mit-fotos.png'), fullPage: false });
    }
  } finally {
    await browser.close();
    server.kill();
  }
  if (problems.length) { console.error('Besetzung mit Fotos: ' + problems.length + ' Problem(e)\n- ' + problems.join('\n- ')); process.exit(1); }
  console.log('Besetzung mit Fotos: Regie in der Reihe, Fotos lokal, Initialen und Hinweis ohne Schlüssel – ok');
})().catch(e => { console.error(e); process.exit(1); });
