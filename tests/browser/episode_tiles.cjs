/* 0.6.59: Folgen als Kacheln mit Abspielknopf auf dem Bild.

   Starts MediathekAtlas without background work, answers /api/show, /api/portal-title and /api/pluto-downloads with
   test data (no catalogue needed, no network) and checks for a catalogue series and a Pluto TV series:
   tiles side by side (several columns wide, one column narrow), the route of each play button
   (local file → built-in player → provider), what a click calls (playMedia / playJob / playPluto / provider tab with
   the autostart mark), the "Gesehen"/progress marks, season tabs, the actions per episode and the list view.
   Usage: node tests/browser/episode_tiles.cjs [screenshot folder] */
'use strict';
const { spawn } = require('child_process');
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

const COLORS = [['#3b5b7a', '#1d2c3c'], ['#6a4b7d', '#2a1d36'], ['#7a5b3b', '#3c2c1d'], ['#3b7a5f', '#1d3c2f'], ['#7a3b4b', '#3c1d24'], ['#4b6a7d', '#1d2a36']];
function still(i) { return 'https://image.tmdb.org/t/p/w300/still' + i + '.jpg'; }
function svg(i) {
  const [a, b] = COLORS[i % COLORS.length];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="480" height="270" fill="url(#g)"/><circle cx="${120 + 40 * (i % 5)}" cy="${90 + 20 * (i % 3)}" r="60" fill="#ffffff14"/><rect x="0" y="200" width="480" height="70" fill="#00000022"/></svg>`;
}
const TITLES = ['Der Anruf', 'Spuren im Schnee', 'Grenzgänger', 'Die Brücke', 'Nachtzug', 'Alte Rechnungen', 'Funkstille', 'Der letzte Zeuge'];
function episode(n, season, opts) {
  const id = 'offer-s' + season + 'e' + n;
  return {
    id, work_id: 'work-s' + season + 'e' + n, offer_count: 1, state: 'matched', available: opts.available !== false,
    downloaded: !!opts.downloaded, file_state: opts.downloaded ? 'ok' : '', mesh_download: null, special: '',
    best: { quality: 'HD', height_hint: 1080 },
    links: opts.links === false ? [] : [{ quality: 'HD', height_hint: 1080, url: 'https://example.invalid/' + id + '.mp4' }],
    source: { title: 'Grenzland – ' + TITLES[(n - 1) % TITLES.length], channel: 'ZDF', duration: 2700, timestamp: 1763600000 + n * 86400,
              url_website: 'https://www.zdf.de/serien/grenzland/folge-' + n, description: '' },
    metadata: { kind: 'series', title: 'Grenzland', season, episode: n, episode_title: TITLES[(n - 1) % TITLES.length],
                still: still(n + season * 3), description: 'Folge ' + n + ': Ein Fall an der Grenze zieht weite Kreise. Kommissarin Weber und ihr Team ermitteln zwischen zwei Ländern.' },
  };
}
const EPISODES = [
  episode(1, 1, { downloaded: true }), episode(2, 1, {}), episode(3, 1, {}), episode(4, 1, { links: false }),
  episode(5, 1, {}), episode(6, 1, {}), episode(1, 2, {}), episode(2, 2, { links: false, available: false }),
];
const SHOW = {
  show: { show_key: 'grenzland', title: 'Grenzland', year: 2025, rating: 7.6, genres: ['Krimi', 'Drama'], channels: ['ZDF'], state: 'matched',
          provider: 'TMDB', reference_id: '123', poster: still(20), fanart: still(21), show_description: 'Eine Krimiserie an der deutsch-österreichischen Grenze.',
          seasons: [{ season: 1, episodes: 6 }, { season: 2, episodes: 2 }], episode_count: 8, downloaded: 1, available: 7, show_credits: {} },
  episodes: EPISODES, work_ids: EPISODES.map(e => e.work_id),
};
const PLUTO = {
  source: 'pluto', id: 'plutoseries01', kind: 'series', kind_label: 'Serie', provider: 'Pluto TV', title: 'Wildes Land', year: 2019,
  web_url: 'https://pluto.tv/de/on-demand/series/wildes-land', description: 'Naturdoku in sechs Folgen.', offline: null,
  episodes: [1, 2, 3, 4].map(n => ({ id: 'plutoepisode0' + n, season: 1, episode: n, title: 'Teil ' + n, duration: 2600, playable: n !== 4,
    offline: n !== 4, web_url: 'https://pluto.tv/de/on-demand/series/wildes-land/episode/' + n, poster: '' })),
};

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-0659-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  const port = await freePort();
  const server = spawn(process.env.PYTHON || 'python3', ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' },
  });
  const problems = [];
  const browser = await playwright.chromium.launch();
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: shots ? 2 : 1 });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    page.on('dialog', d => d.dismiss());
    await page.route('https://image.tmdb.org/**', r => {
      const i = Number((r.request().url().match(/still(\d+)/) || [0, 0])[1]);
      r.fulfill({ status: 200, contentType: 'image/svg+xml', body: svg(i) });
    });
    await page.route('**/api/show?**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHOW) }));
    await page.route('**/api/portal-title?**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLUTO) }));
    await page.route('**/api/pluto-downloads?**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      offline_days: 30, ffmpeg: true, items: [{ id: 'job-pluto-2', pluto_id: 'plutoepisode02', state: 'done', offline_until: Date.now() / 1000 + 20 * 86400, days_left: 20 }] }) }));
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasDisplay.ready);
    // Record what a play button calls instead of opening the player; remember one watched and one started episode.
    await page.evaluate(() => {
      window.__calls = [];
      window.playMedia = (item, list) => window.__calls.push(['playMedia', item.id, (list || []).length]);
      window.playJob = job => window.__calls.push(['playJob', job.id]);
      window.playPluto = (id) => window.__calls.push(['playPluto', id]);
      window.open = (u) => window.__calls.push(['open', u]);
      localStorage.setItem('atlas-play:work-s1e2', JSON.stringify({ done: true, at: Date.now() }));
      localStorage.setItem('atlas-play:work-s1e3', JSON.stringify({ pos: 1350, at: Date.now() }));
      localStorage.removeItem('atlas-episode-view');
      latestSettings.tmdb_set = false;
    });

    // 1. Catalogue series: tiles, routes, marks.
    await page.evaluate(() => openShow('grenzland'));
    await page.waitForSelector('#title-view .tv-episodes.tv-grid .tv-episode', { timeout: 10000 }).catch(() => problems.push('Kachelraster fehlt'));
    const tabs = await page.evaluate(() => [...document.querySelectorAll('#title-view .tv-tabs .tv-tab')].map(t => t.textContent));
    if (JSON.stringify(tabs) !== JSON.stringify(['Alle · 8', 'Staffel 1 · 6', 'Staffel 2 · 2'])) problems.push('Staffelwahl: ' + JSON.stringify(tabs));
    const grid = await page.evaluate(() => {
      const tiles = [...document.querySelectorAll('#title-view .tv-episode')];
      const tops = new Set(tiles.map(t => Math.round(t.getBoundingClientRect().top)));
      return { count: tiles.length, rows: tops.size, columns: getComputedStyle(document.querySelector('#title-view .tv-episodes')).gridTemplateColumns.split(' ').length,
        routes: tiles.map(t => t.querySelector('.tv-tileplay')?.dataset.route || ''),
        chips: tiles.map(t => t.querySelector('.tv-route')?.textContent || ''),
        provider: tiles.map(t => t.querySelector('a.tv-tileplay')?.getAttribute('href') || ''),
        seen: tiles.map(t => t.querySelector('.tv-seen') ? 'seen' : t.querySelector('.tv-progress') ? 'progress' : ''),
        actions: tiles.map(t => [...t.querySelectorAll('.tv-epactions > button, .tv-epactions summary')].map(b => b.textContent).join('|')) };
    });
    if (grid.count !== 8) problems.push('Folgen: ' + grid.count);
    if (grid.columns < 4) problems.push('Spalten bei 1400 px: ' + grid.columns);
    if (grid.rows > 2) problems.push('Zeilen bei 1400 px: ' + grid.rows);
    const want = ['local', 'player', 'player', 'provider', 'player', 'player', 'player', 'provider'];
    if (JSON.stringify(grid.routes) !== JSON.stringify(want)) problems.push('Wege: ' + JSON.stringify(grid.routes));
    if (grid.chips[0] !== 'Lokal' || grid.chips[1] !== 'Player' || grid.chips[3] !== 'Anbieter') problems.push('Kennzeichnung: ' + JSON.stringify(grid.chips));
    if (grid.provider[3] !== 'https://www.zdf.de/serien/grenzland/folge-4') problems.push('Anbieterlink: ' + grid.provider[3]);
    if (grid.seen[1] !== 'seen' || grid.seen[2] !== 'progress' || grid.seen[0]) problems.push('Gesehen/Fortschritt: ' + JSON.stringify(grid.seen));
    if (!/↓ Prüfen & laden/.test(grid.actions[1]) || !/Dateien & Qualität/.test(grid.actions[1])) problems.push('Aktionen je Folge: ' + grid.actions[1]);
    if (shots) {
      await page.locator('#title-view .tv-section').last().scrollIntoViewIfNeeded();
      await page.evaluate(() => window.scrollBy(0, -60));
      await page.locator('#title-view .tv-episode').nth(1).locator('.tv-thumb').hover();
      await page.screenshot({ path: path.join(shots, '0.6.59-folgen-kacheln.png'), fullPage: false });
    }
    await page.locator('#title-view .tv-episode').nth(0).locator('.tv-tileplay').click();
    await page.locator('#title-view .tv-episode').nth(1).locator('.tv-thumb img').click({ position: { x: 20, y: 70 } });   // the picture plays as well
    const calls = await page.evaluate(() => window.__calls.splice(0));
    if (JSON.stringify(calls) !== JSON.stringify([['playMedia', 'offer-s1e1', 6], ['playMedia', 'offer-s1e2', 6]])) problems.push('Abspielen: ' + JSON.stringify(calls));
    const target = await page.locator('#title-view .tv-episode').nth(3).locator('a.tv-tileplay').evaluate(a => [a.target, a.rel]);
    if (target[0] !== '_blank' || !/noopener/.test(target[1])) problems.push('Anbieterlink öffnet nicht im neuen Tab: ' + JSON.stringify(target));

    // Season tab keeps the tiles.
    await page.locator('#title-view .tv-tabs .tv-tab', { hasText: 'Staffel 2' }).click();
    const s2 = await page.evaluate(() => document.querySelectorAll('#title-view .tv-episodes.tv-grid .tv-episode').length);
    if (s2 !== 2) problems.push('Staffel 2: ' + s2);

    // List view is remembered.
    await page.locator('#title-view .tv-viewswitch button', { hasText: 'Liste' }).click();
    const list = await page.evaluate(() => ({ cls: document.querySelector('#title-view .tv-episodes').className, saved: localStorage.getItem('atlas-episode-view'),
      cols: getComputedStyle(document.querySelector('#title-view .tv-episodes')).gridTemplateColumns.split(' ').length }));
    if (!/tv-list/.test(list.cls) || list.saved !== 'list' || list.cols !== 1) problems.push('Listenansicht: ' + JSON.stringify(list));
    await page.locator('#title-view .tv-viewswitch button', { hasText: 'Kacheln' }).click();

    // Narrow window: one column.
    await page.setViewportSize({ width: 420, height: 900 });
    await page.locator('#title-view .tv-tabs .tv-tab', { hasText: 'Alle' }).click();
    const narrow = await page.evaluate(() => getComputedStyle(document.querySelector('#title-view .tv-episodes')).gridTemplateColumns.split(' ').length);
    if (narrow !== 1) problems.push('Spalten bei 420 px: ' + narrow);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (overflow) problems.push('Seite breiter als das Fenster bei 420 px');
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.evaluate(() => closeTitleView());

    // 2. Pluto TV series: offline copy → playJob, playable → playPluto, not playable → provider with the autostart mark.
    await page.evaluate(() => window.AtlasPortalTitle.open('pluto', 'plutoseries01'));
    await page.waitForSelector('#title-view .portal-title-episodes .tv-episodes.tv-grid .tv-episode', { timeout: 10000 }).catch(() => problems.push('Pluto-Kacheln fehlen'));
    await page.waitForFunction(() => document.querySelector('#title-view .portal-title-episodes .tv-episode:nth-child(2) .tv-tileplay')?.dataset.route === 'local', null, { timeout: 8000 })
      .catch(() => problems.push('Offline-Kopie wird nicht als lokal erkannt'));
    const pluto = await page.evaluate(() => [...document.querySelectorAll('#title-view .portal-title-episodes .tv-episode')].map(t => [
      t.querySelector('.tv-tileplay')?.dataset.route || '', t.querySelector('a.tv-tileplay')?.getAttribute('href') || '',
      !!t.querySelector('.atlas-offline, .atlas-offline-note'), [...t.querySelectorAll('.tv-epactions button')].some(b => b.textContent === 'Details')]));
    const routes = pluto.map(p => p[0]);
    if (JSON.stringify(routes) !== JSON.stringify(['player', 'local', 'player', 'provider'])) problems.push('Pluto-Wege: ' + JSON.stringify(routes));
    if (!pluto[3] || !pluto[3][1].startsWith('https://pluto.tv/')) problems.push('Pluto-Anbieterlink: ' + JSON.stringify(pluto[3]));
    if (!pluto.every(p => p[3])) problems.push('Details-Knopf fehlt');
    if (!pluto[0][2]) problems.push('Offline-Knopf je Folge fehlt');
    await page.locator('#title-view .portal-title-episodes .tv-episode').nth(0).locator('.tv-tileplay').click();
    await page.locator('#title-view .portal-title-episodes .tv-episode').nth(1).locator('.tv-tileplay').click();
    const pc = await page.evaluate(() => window.__calls.splice(0));
    if (JSON.stringify(pc) !== JSON.stringify([['playPluto', 'plutoepisode01'], ['playJob', 'job-pluto-2']])) problems.push('Pluto abspielen: ' + JSON.stringify(pc));
    if (shots) {
      await page.locator('#title-view .portal-title-episodes').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(shots, '0.6.59-folgen-kacheln-pluto.png'), fullPage: false });
    }
  } finally {
    await browser.close();
    server.kill();
  }
  if (problems.length) { console.error('Folgen als Kacheln: ' + problems.length + ' Problem(e)\n- ' + problems.join('\n- ')); process.exit(1); }
  console.log('Folgen als Kacheln: Raster, Abspielknopf lokal → Player → Anbieter, Gesehen, Staffeln, Liste, schmales Fenster, Pluto TV – ok');
})().catch(e => { console.error(e); process.exit(1); });
