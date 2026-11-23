/* Programmführer (epg.py) im Live-TV: „Jetzt“ mit Fortschritt, „Danach“, Block mit Automatik und Laden.
   Starts MediathekAtlas without background work, with the Samsung test list (stations) and a stored programme for
   „Doku Welt“ (no network). Usage: node tests/browser/epg_live.cjs [screenshot file] */
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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-epg-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  // Samsung channel list (stations) plus a programme for „Doku Welt“: running now and the next broadcast
  execFileSync(process.env.PYTHON || 'python3', ['-c',
    'import sys,time;sys.path[:0]=[sys.argv[2]];from pathlib import Path;import storage_locations,samsung_tvplus as s,epg;' +
    'from tests.test_v0597_samsung_tvplus import sample;r=storage_locations.data_root(Path(sys.argv[1]));r.mkdir(parents=True,exist_ok=True);' +
    'n=time.time();s.sync(r,fetch=sample,now=n);db=epg.connect(r);' +
    'epg.store(db,[epg._row("ard","Doku Welt",int(n-1200),int(n+600),"Expedition Arktis",subtitle="Folge 2",genre="Dokumentation",season=1,episode=2),' +
    'epg._row("ard","Doku Welt",int(n+600),int(n+3600),"Planet Erde")]);db.commit();db.close()', path.join(home, 'data'), ROOT], { cwd: ROOT });
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
    // the load button must not reach the internet in the test: answered here
    let syncs = 0;
    await page.route('**/api/epg-sync', async route => { syncs++; await route.fulfill({ json: { started: false, status: { auto: true, running: false, broadcasts: 2, last_success: Date.now() / 1000, last_result: 'ok', sources: {}, first: 0, last: 0, next_attempt: 0 } } }); });
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function', null, { timeout: 20000 });
    await page.evaluate(() => window.atlasShowView('livetv'));
    const tile = page.locator('.livetv-station[data-key="dokuwelt"]');
    await tile.waitFor({ timeout: 15000 });
    const now = (await tile.locator('.livetv-now').textContent()) || '';
    if (!/Jetzt .*Expedition Arktis – Folge 2/.test(now)) problems.push('Jetzt-Zeile fehlt oder falsch: ' + now);
    if (!/S1 F2 · Dokumentation/.test(now)) problems.push('Staffel/Folge/Genre fehlen: ' + now);
    const next = (await tile.locator('.livetv-next').textContent()) || '';
    if (!/Danach \d\d:\d\d Planet Erde/.test(next)) problems.push('Danach-Zeile fehlt: ' + next);
    const width = await tile.locator('.livetv-progress span').evaluate(n => parseFloat(n.style.width));
    if (!(width > 50 && width < 80)) problems.push('Fortschritt unplausibel: ' + width);
    // a station without programme keeps its description
    const other = page.locator('.livetv-station[data-key="krimikanal"]');
    if (await other.locator('.livetv-programme').count()) problems.push('Krimi Kanal zeigt ein Programm ohne Daten');
    await page.locator('#epg-setup > summary').click();
    await page.waitForFunction(() => /2 Sendungen/.test(document.getElementById('epg-setup-state').textContent), null, { timeout: 10000 })
      .catch(async () => problems.push('Kopfzeile Programmführer: ' + await page.locator('#epg-setup-state').textContent()));
    if (shot) await page.locator('#livetv').screenshot({ path: shot });
    await page.locator('#epg-auto').uncheck();
    await page.waitForFunction(() => /Automatik aus/.test(document.getElementById('epg-setup-state').textContent), null, { timeout: 10000 })
      .catch(() => problems.push('Automatik aus wird nicht angezeigt'));
    if (await page.evaluate(async () => (await window.api('epg')).auto) !== false) problems.push('Automatik aus nicht gespeichert');
    await page.locator('#epg-sync').click();
    await page.waitForTimeout(800);
    if (syncs !== 1) problems.push('Laden nicht ausgelöst: ' + syncs);
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
  if (problems.length) { console.log('epg_live: ' + problems.length + ' Befund(e)\n- ' + problems.join('\n- ')); process.exit(1); }
  console.log('epg_live: ohne Befund');
})();
