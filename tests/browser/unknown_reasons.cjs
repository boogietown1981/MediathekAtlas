/* 0.6.49: "Art offen – warum?" in Verwaltung → Zuordnung → Erkennungsquote je Sender.

   Seeds a data folder (tests/browser/seed_0649.py: works of unknown kind, then the background sweep), starts
   MediathekAtlas without background work, opens the panel and checks the column "Art offen", the reasons per
   channel and the Sendungen with most open works.
   Usage: node tests/browser/unknown_reasons.cjs [screenshot folder] */
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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-0649-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  execFileSync(process.env.PYTHON || 'python3', ['tests/browser/seed_0649.py', path.join(home, 'data')], { cwd: ROOT });
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
    page.on('response', r => {
      const u = new URL(r.url());
      if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400) problems.push(r.status() + ' ' + u.pathname);
    });
    page.on('dialog', d => d.dismiss());
    await page.goto(url);
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
    await page.evaluate(() => window.AtlasDisplay.ready);
    await page.locator('aside nav .nav', { hasText: 'Verwaltung' }).click();
    await page.locator('#admin-tabs .admin-tab[data-view="review"]').click();
    const panel = page.locator('#review details.provider-panel', { hasText: 'Erkennungsquote je Sender' });
    await panel.locator('summary').click();
    await page.waitForSelector('#unknown-reasons:not([hidden]) #unknown-reasons-channels tr', { timeout: 30000 })
      .catch(() => problems.push('Gründe für offene Art nicht sichtbar'));
    await page.waitForFunction(() => document.querySelectorAll('#recognition-table tr').length > 1, null, { timeout: 30000 })
      .catch(() => problems.push('Erkennungstabelle leer'));
    const result = await page.evaluate(() => ({
      header: [...document.querySelectorAll('#recognition-table')].map(t => t.closest('table').querySelector('thead').textContent)[0],
      total: [...document.querySelectorAll('#recognition-table tr.total td')].map(td => td.textContent),
      channels: [...document.querySelectorAll('#unknown-reasons-channels tr')].map(tr => [...tr.children].map(td => td.textContent)),
      topics: [...document.querySelectorAll('#unknown-reasons-topics tr')].map(tr => [...tr.children].map(td => td.textContent)),
      status: document.getElementById('unknown-reasons-status').textContent,
    }));
    if (!/Art offen/.test(result.header || '')) problems.push('Spalte „Art offen“ fehlt');
    if (result.total[10] !== '11') problems.push('Art offen gesamt: ' + result.total[10]);
    const srf = result.channels.find(r => r[0] === 'SRF');
    if (!srf || srf[1] !== '4' || !/Vorschlag könnte passen: 3/.test(srf[2]) || !/Anbieterfehler/.test(srf[2])) problems.push('SRF-Zeile: ' + JSON.stringify(srf));
    if (!result.channels.some(r => r[0] === 'ARTE.IT' && /Serienrubrik/.test(r[2]))) problems.push('ARTE.IT-Zeile fehlt');
    if (!result.topics.some(r => r[0] === 'DOK' && r[1] === 'SRF' && r[2] === '3')) problems.push('Sendung DOK fehlt: ' + JSON.stringify(result.topics));
    if (!/6 Werke eingeordnet/.test(result.status) || !/3 davon trotz unpassender Vorschläge/.test(result.status)) problems.push('Status: ' + result.status);
    if (shots) {
      await panel.scrollIntoViewIfNeeded();
      await panel.screenshot({ path: path.join(shots, '0.6.49-art-offen.png') });
    }
  } finally {
    await browser.close();
    server.kill();
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('unknown_reasons: ohne Befund');
})().catch(e => { console.error(e); process.exit(1); });
