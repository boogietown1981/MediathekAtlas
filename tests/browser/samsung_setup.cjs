/* 0.6.64: Samsung TV Plus – Region und Automatik im Live-TV (Code-Review 21.11.2026, Befund C2).

   Starts MediathekAtlas without background work with a stored Samsung channel list (test data from
   tests/test_v0597_samsung_tvplus.py, no network), opens Live-TV and checks the block „Samsung TV Plus ·
   Region und Automatik“: shows region, automatic switch and the state of the list; switching the
   automatic refresh off is stored on the server (real call); choosing another region sends
   /api/samsung-region (answered here, so no channel list is fetched from the internet) and then waits
   for the new list. Usage: node tests/browser/samsung_setup.cjs [screenshot file] */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const shot = process.argv[2] || '';

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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-samsung-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  execFileSync(process.env.PYTHON || 'python3', ['-c',
    'import sys,time;sys.path[:0]=[sys.argv[2]];from pathlib import Path;import storage_locations,samsung_tvplus as s;' +
    'from tests.test_v0597_samsung_tvplus import sample;r=storage_locations.data_root(Path(sys.argv[1]));r.mkdir(parents=True,exist_ok=True);' +
    's.sync(r,fetch=sample,now=time.time())', path.join(home, 'data'), ROOT], { cwd: ROOT });
  const port = await freePort();
  const server = spawn(process.env.PYTHON || 'python3', ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' },
  });
  const problems = [];
  let browser;
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    browser = await playwright.chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    page.on('dialog', d => d.dismiss());
    await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, r => r.abort());
    const sent = [];
    await page.route('**/api/samsung-region', async route => {
      const body = JSON.parse(route.request().postData() || '{}');
      sent.push(body.region);
      const status = await (await fetch(url + 'api/samsung', { headers: { 'X-Atlas-Token': await page.evaluate(() => document.querySelector('meta[name=atlas-token]').content) } })).json();
      await route.fulfill({ json: { status: { ...status, region: body.region }, started: false } });
    });
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function', null, { timeout: 20000 });
    await page.evaluate(() => window.atlasShowView('livetv'));
    await page.locator('#samsung-setup > summary').click();
    await page.waitForFunction(() => /2 Sender · Stand/.test(document.getElementById('samsung-setup-status').textContent), null, { timeout: 10000 })
      .catch(async () => problems.push('Stand der Senderliste fehlt: ' + await page.locator('#samsung-setup-status').textContent()));
    const check = async (what, fn) => { if (!(await page.evaluate(fn))) problems.push('Erwartung nicht erfüllt: ' + what); };
    await check('Region Deutschland vorgewählt', () => document.getElementById('samsung-region').value === 'de');
    await check('Automatik an', () => document.getElementById('samsung-auto').checked);
    await check('Kopfzeile nennt Region und Automatik', () => /Deutschland · Automatik an/.test(document.getElementById('samsung-setup-state').textContent));
    if (shot) await page.locator('#samsung-setup').screenshot({ path: shot });
    // automatic refresh off – real call, stored on the server
    await page.locator('#samsung-auto').uncheck();
    await page.waitForFunction(() => /Automatik aus/.test(document.getElementById('samsung-setup-state').textContent), null, { timeout: 10000 })
      .catch(() => problems.push('Automatik aus wird nicht angezeigt'));
    const stored = await page.evaluate(async () => (await window.api('samsung')).auto);
    if (stored !== false) problems.push('Automatik aus nicht gespeichert');
    // region
    await page.selectOption('#samsung-region', 'at');
    await page.waitForFunction(() => /Österreich/.test(document.getElementById('samsung-setup-state').textContent), null, { timeout: 10000 })
      .catch(() => problems.push('Region Österreich wird nicht angezeigt'));
    if (sent.join() !== 'at') problems.push('Region nicht gesendet: ' + sent.join());
    await page.locator('#samsung-auto').check();
    await page.waitForTimeout(500);
    if (await page.evaluate(async () => (await window.api('samsung')).auto) !== true) problems.push('Automatik an nicht gespeichert');
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
  if (problems.length) { console.log('samsung_setup: ' + problems.length + ' Befund(e)\n- ' + problems.join('\n- ')); process.exit(1); }
  console.log('samsung_setup: ohne Befund');
})();
