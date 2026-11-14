/* 0.5.99: Klicktest der Oberfläche in echten Browsern (Chromium, Firefox, WebKit).

   Starts MediathekAtlas with an empty data folder and without background work, opens every main
   view, every area of the Verwaltung and every platform tab, switches the design to light and
   back, and fails on any script error or any failed call to the own server. WebKit stands in for
   Safari; it is the closest check that runs without a Mac.

   Usage: node tests/browser/click_all.cjs [chromium] [firefox] [webkit]   (default: chromium)
   Needs the npm package "playwright" and its browsers; it is not part of the unit tests. */
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const wanted = process.argv.slice(2).length ? process.argv.slice(2) : ['chromium'];

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

async function clickThrough(name, url) {
  const problems = [];
  const browser = await playwright[name].launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
    page.on('response', r => {
      const u = new URL(r.url());
      if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400) problems.push(r.status() + ' ' + u.pathname);
    });
    page.on('dialog', d => d.dismiss());
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await window_ready(page);
    const expect = async (what, fn, arg) => { if (!(await page.evaluate(fn, arg))) problems.push('Erwartung nicht erfüllt: ' + what); };

    // Main navigation.
    const nav = await page.locator('aside nav .nav').count();
    if (nav < 5) problems.push('Navigation unvollständig (' + nav + ' Einträge)');
    for (let i = 0; i < nav; i++) { await page.locator('aside nav .nav').nth(i).click(); await page.waitForTimeout(500); }

    // Every area of the Verwaltung.
    await page.locator('aside nav .nav', { hasText: 'Verwaltung' }).click();
    const tabs = await page.locator('#admin-tabs .admin-tab').evaluateAll(n => n.map(x => x.dataset.view));
    if (tabs.length < 10) problems.push('Verwaltung unvollständig: ' + tabs.join(','));
    for (const view of tabs) {
      await page.locator('#admin-tabs .admin-tab[data-view="' + view + '"]').click();
      await page.waitForTimeout(700);
      await expect('Bereich ' + view + ' sichtbar', v => { const s = document.getElementById(v); return !!s && !s.hidden; }, view);
    }

    // System monitor and the blocks of the storage view.
    await page.locator('#admin-tabs .admin-tab[data-view="system"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#system-metrics .storage-metric').length === 4, null, { timeout: 10000 }).catch(() => problems.push('Systemmonitor zeigt keine Werte'));
    await page.locator('#admin-tabs .admin-tab[data-view="storage"]').click();
    await page.waitForFunction(() => /Umwandlung/.test(document.getElementById('encoder-status').textContent) || /ffmpeg/.test(document.getElementById('encoder-status').textContent), null, { timeout: 10000 }).catch(() => problems.push('Umwandeln-Block bleibt leer'));
    await page.waitForFunction(() => document.getElementById('receipts-status').textContent.length > 10, null, { timeout: 10000 }).catch(() => problems.push('Archivnachweise bleiben leer'));

    // Light design and back.
    const background = () => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor.match(/\d+/g).slice(0, 3).map(Number));
    const dark = await background();
    await page.evaluate(() => window.AtlasDisplay.save({ theme: 'light' }));
    await page.waitForTimeout(400);
    const light = await background();
    if (!(Math.min(...light) > 200 && Math.max(...dark) < 60)) problems.push('Helles Design greift nicht: dunkel ' + dark + ', hell ' + light);
    await expect('Text im hellen Design dunkel', () => getComputedStyle(document.documentElement).color.match(/\d+/g).slice(0, 3).every(v => Number(v) < 90));
    for (const view of ['discover', 'storage', 'settings']) { await page.evaluate(v => window.atlasShowView(v), view); await page.waitForTimeout(500); }
    await page.evaluate(() => window.AtlasDisplay.save({ theme: 'dark' }));
    await page.waitForTimeout(300);
    await expect('Dunkles Design wiederhergestellt', () => !document.documentElement.dataset.theme);

    // Every platform tab.
    await page.evaluate(() => window.atlasShowView('portals'));
    await page.waitForTimeout(800);
    const platforms = await page.locator('#portals button').evaluateAll(n => n.map(x => x.textContent.trim()).filter(t => /^(Übersicht|Internet Archive|Netzkino|Pluto TV|JustWatch TV|Rakuten TV|YouTube|Joyn|TOGGO)$/.test(t)));
    if (platforms.length < 9) problems.push('Plattform-Reiter unvollständig: ' + platforms.join(', '));
    for (const label of platforms) {
      await page.locator('#portals button', { hasText: new RegExp('^' + label + '$') }).first().click();
      await page.waitForTimeout(800);
    }
    await page.evaluate(() => window.atlasShowView('discover'));
    await page.waitForTimeout(800);
  } finally {
    await browser.close();
  }
  return problems;
}
async function window_ready(page) {
  await page.evaluate(() => window.AtlasDisplay.ready);
  await page.waitForTimeout(800);
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-click-'));
  const port = await freePort();
  const server = spawn(process.env.PYTHON || 'python3', ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' },
  });
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  let failed = false;
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    for (const name of wanted) {
      if (!playwright[name]) { console.log(name + ': unbekannter Browser'); failed = true; continue; }
      const problems = await clickThrough(name, url);
      console.log(name + ': ' + (problems.length ? problems.length + ' Problem(e)' : 'ohne Befund'));
      for (const p of problems) console.log('  - ' + p);
      failed = failed || problems.length > 0;
    }
  } catch (e) {
    console.log('Abbruch: ' + (e && e.stack || e)); failed = true;
  } finally {
    server.kill();
    try { fs.rmSync(home, { recursive: true, force: true }); } catch (e) { /* the temp folder of the run; leaving it is harmless */ }
  }
  process.exit(failed ? 1 : 0);
})();
