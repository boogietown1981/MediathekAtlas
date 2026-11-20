/* 0.6.47: Red Bull TV als Plattform (redbulltv.py auf der ServusTV-Technik) und WELT/n-tv im Live-TV.

   Legt einen Red-Bull-TV-Katalog über die nachgestellte Plattform-Antwort an (tests/test_v0647_redbull_news.py),
   startet MediathekAtlas ohne Hintergrunddienste und prüft in Chromium:
   - Plattformen → „Red Bull TV“ zeigt Film und Sendung, die Sendung öffnet ihre Folgen,
   - Live-TV zeigt die Gruppe „Nachrichten (privat)“ mit WELT (▶, offizieller Stream) und n-tv (nur Link zu n-tv.de),
   - der WELT-Knopf fragt /api/play?sender=welt an (Stream aus der Cloud nicht erreichbar: verständliche Meldung),
   - keine Skriptfehler.
   Aufruf: node tests/browser/redbull_live.cjs [Ordner für Bildschirmfotos] */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const PY = process.env.PYTHON || 'python3';
const SHOTS = process.argv[2] || '';

const SEED = `
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import redbulltv, test_v0647_redbull_news as fixture
result = redbulltv.sync(sys.argv[1], opener=fixture.FakeRedBull(), now=fixture.NOW)
assert result['ok'], result
`;

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}
async function waitFor(url, seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    try { const r = await fetch(url); if (r.ok) return; } catch (e) { /* noch nicht da */ }
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('MediathekAtlas ist nach ' + seconds + ' s nicht erreichbar');
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-redbull-'));
  const port = await freePort();
  let server, browser;
  const problems = [];
  const check = (what, ok) => { if (!ok) problems.push('Erwartung nicht erfüllt: ' + what); };
  try {
    fs.mkdirSync(path.join(home, 'data'), { recursive: true });
    execFileSync(PY, ['-c', SEED, path.join(home, 'data')], { cwd: ROOT });
    server = spawn(PY, ['server.py', '--no-browser'], { cwd: ROOT, stdio: 'ignore',
      env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
             MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' } });
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url + 'api/instance', 60);
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    const plays = [];
    page.on('request', r => { const u = new URL(r.url()); if (u.pathname === '/api/play') plays.push(u.search); });
    await page.goto(url);
    await page.click('button.nav[data-view="portals"]');
    await page.click('.platform-tab[data-platform="redbulltv"]');
    await page.waitForSelector('#redbulltv-items article, #redbulltv-items .netzkino-card', { timeout: 30000 });
    const films = await page.locator('#redbulltv-items').innerText();
    check('Red-Bull-TV-Film in der Liste: ' + films.slice(0, 200), films.includes('Kilimanjaro'));
    const summary = await page.locator('#redbulltv-summary').textContent();
    check('Katalogstatus genannt: ' + summary, summary.length > 5 && !summary.includes('wird geladen'));
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.47-redbulltv.png') });
    await page.click('#redbulltv-view-series');
    await page.waitForFunction(() => document.querySelector('#redbulltv-items')?.innerText.includes('Frontiers'), null, { timeout: 30000 });

    await page.click('button.nav[data-view="livetv"]');
    await page.waitForSelector('.livetv-station[data-key="welt"]', { timeout: 30000 });
    const groups = await page.locator('.livetv-group-title').allTextContents();
    check('Gruppe „Nachrichten (privat)“: ' + groups.join(' | '), groups.some(g => g.startsWith('Nachrichten (privat)')));
    const ntvLink = await page.locator('.livetv-station[data-key="ntv"] a.button').getAttribute('href');
    check('n-tv öffnet n-tv.de: ' + ntvLink, String(ntvLink).startsWith('https://www.n-tv.de/'));
    check('n-tv hat keinen eigenen Abspielknopf', await page.locator('.livetv-station[data-key="ntv"] button.primary').count() === 0);
    if (SHOTS) await page.locator('.livetv-station[data-key="welt"]').scrollIntoViewIfNeeded();
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.47-livetv-nachrichten.png') });
    await page.locator('.livetv-station[data-key="welt"] button.primary').click();
    await page.waitForFunction(() => /WELT|nicht erreichbar|ansehen/.test(document.querySelector('#player')?.innerText || document.body.innerText), null, { timeout: 30000 });
    await page.waitForTimeout(1500);
    check('WELT fragt /api/play?sender=welt an: ' + plays.join(' '), plays.some(q => q.includes('sender=welt')));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill('SIGTERM');
    fs.rmSync(home, { recursive: true, force: true });
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('redbull_live ok');
})().catch(e => { console.error(e); process.exit(1); });
