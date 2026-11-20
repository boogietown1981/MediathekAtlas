/* 0.6.48: DMAX & TLC tab and Joyn episode lists in a real browser.

   Seeds a data folder (tests/browser/seed_0648.py: made-up catalogue in the recorded shapes), starts
   MediathekAtlas without background work, opens the platform tab "DMAX & Co.", a programme with its
   episodes (badges for discovery+ / copy protection) and the Joyn series page with free and Joyn+ episodes.
   Usage: node tests/browser/dmax_joyn.cjs [screenshot folder] */
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

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-0648-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  execFileSync(process.env.PYTHON || 'python3', ['tests/browser/seed_0648.py', path.join(home, 'data')], { cwd: ROOT });
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
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    page.on('response', r => {
      const u = new URL(r.url());
      if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400) problems.push(r.status() + ' ' + u.pathname);
    });
    page.on('dialog', d => d.dismiss());
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasDisplay.ready);
    await page.evaluate(() => window.atlasShowView('portals'));
    await page.locator('#portals button.platform-tab', { hasText: /^DMAX & Co\.$/ }).click();
    await page.waitForSelector('#dmax-items .atlas-uc-card', { timeout: 30000 }).catch(() => problems.push('DMAX: keine Kacheln'));
    const tiles = await page.locator('#dmax-items .atlas-uc-card').count();
    if (tiles !== 3) problems.push('DMAX: ' + tiles + ' Sendungen statt 3');
    const summary = await page.locator('#dmax-summary').textContent();
    if (!/3 Serien · 5 Folgen/.test(summary)) problems.push('DMAX-Zusammenfassung: ' + summary);
    if (shots) await page.screenshot({ path: path.join(shots, 'dmax-tab.png') });
    // a programme opens the shared title page with its episodes
    await page.locator('#dmax-items .atlas-uc-card', { hasText: 'Feuerwache 3' }).first().locator('button', { hasText: 'Folgen & Details' }).click();
    await page.waitForFunction(() => document.body.innerText.includes('Nur mit discovery+'), null, { timeout: 15000 })
      .catch(() => problems.push('DMAX: Folgenliste mit Kennzeichnung fehlt'));
    if (shots) await page.screenshot({ path: path.join(shots, 'dmax-folgen.png') });
    const dmaxText = await page.evaluate(() => document.body.innerText);
    for (const t of ['24 Stunden auf der Feuerwache 3', 'Großeinsatz', 'Nachtschicht']) if (!dmaxText.includes(t)) problems.push('DMAX-Folge fehlt: ' + t);
    // Joyn series page with all episodes
    await page.goto(url);
    await page.waitForFunction(() => !!window.AtlasPortalTitle, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasPortalTitle.open('joyn', 's.a_stromberg'));
    await page.waitForFunction(() => document.body.innerText.includes('Das Praktikum'), null, { timeout: 15000 })
      .catch(() => problems.push('Joyn: Folgen fehlen auf der Serienseite'));
    const joynText = await page.evaluate(() => document.body.innerText);
    for (const t of ['Der Neue', 'Lebenslauf', 'Joyn+', 'Kostenlos']) if (!joynText.includes(t)) problems.push('Joyn-Serienseite ohne: ' + t);
    if (joynText.includes('Andere Serie')) problems.push('Joyn: Folge einer fremden Serie angezeigt');
    if (shots) await page.screenshot({ path: path.join(shots, 'joyn-folgen.png') });
    // 0.6.52: filmfriend tab with films and series, every title only on filmfriend.de
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasDisplay.ready);
    await page.evaluate(() => window.atlasShowView('portals'));
    await page.locator('#portals button.platform-tab', { hasText: /^filmfriend$/ }).click();
    await page.waitForSelector('#filmfriend-items .atlas-uc-card', { timeout: 30000 }).catch(() => problems.push('filmfriend: keine Kacheln'));
    const ffText = await page.locator('#filmfriend').innerText();
    if (!ffText.includes('Abschied')) problems.push('filmfriend: Film fehlt');
    if (!ffText.includes('Mit Bibliotheksausweis')) problems.push('filmfriend: Hinweis auf den Bibliotheksausweis fehlt');
    if (/▶ Abspielen/.test(ffText)) problems.push('filmfriend: Abspielen angeboten');
    await page.locator('#filmfriend-view-series').click();
    await page.waitForFunction(() => document.querySelector('#filmfriend').innerText.includes('Allein gegen die Zeit'), null, { timeout: 15000 })
      .catch(() => problems.push('filmfriend: Serie fehlt'));
    if (shots) await page.screenshot({ path: path.join(shots, 'filmfriend.png') });
  } catch (e) {
    problems.push('Abbruch: ' + (e && e.stack || e));
  } finally {
    await browser.close();
    server.kill();
    try { fs.rmSync(home, { recursive: true, force: true }); } catch (e) { /* temp folder */ }
  }
  console.log('chromium: ' + (problems.length ? problems.length + ' Problem(e)' : 'ohne Befund'));
  for (const p of problems) console.log('  - ' + p);
  process.exit(problems.length ? 1 : 0);
})();
