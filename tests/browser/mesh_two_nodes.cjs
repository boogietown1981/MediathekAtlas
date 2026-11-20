/* 0.6.51: two real MediathekAtlas instances form a Verbund over a shared cloud folder.

   Both instances run with all background services (offline: every outbound connection goes to a dead
   proxy), the same HOME with "iCloud Drive" (Library/Mobile Documents/com~apple~CloudDocs) and their own
   data folder and port. In each browser the one-click button „Über iCloud Drive verbinden“ is used.
   Checked: both systems see each other, the 256 areas are split, A's 30 earlier results reach B
   without a provider query, the differing manual assignment is kept on both sides and listed as a
   conflict, „Von … übernehmen“ resolves it.
   Usage: node tests/browser/mesh_two_nodes.cjs [screenshot folder] */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const shots = process.argv[2] || '';
const PY = process.env.PYTHON || 'python3';

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
  throw new Error('MediathekAtlas ist nach ' + seconds + ' s nicht erreichbar: ' + url);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-0651-'));
  const cloud = path.join(home, 'Library', 'Mobile Documents', 'com~apple~CloudDocs');
  fs.mkdirSync(cloud, { recursive: true });
  const nodes = [];
  for (const side of ['a', 'b']) {
    const data = path.join(home, 'data-' + side), downloads = path.join(home, 'downloads-' + side);
    fs.mkdirSync(data); fs.mkdirSync(downloads);
    execFileSync(PY, ['tests/browser/seed_0651.py', data, side], { cwd: ROOT });
    const port = await freePort();
    const log = fs.openSync(path.join(home, 'server-' + side + '.log'), 'w');
    const server = spawn(PY, ['server.py', '--no-browser'], {
      cwd: ROOT, stdio: ['ignore', log, log],
      env: { ...process.env, HOME: home, MEDIATHEKATLAS_HOME: data, MEDIATHEKATLAS_DOWNLOAD_DIR: downloads,
             MEDIATHEKATLAS_PORT: String(port), HTTPS_PROXY: 'http://127.0.0.1:9', HTTP_PROXY: 'http://127.0.0.1:9',
             https_proxy: 'http://127.0.0.1:9', http_proxy: 'http://127.0.0.1:9', NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost' },
    });
    nodes.push({ side, port, server, url: 'http://127.0.0.1:' + port + '/', data });
  }
  const problems = [];
  const browser = await playwright.chromium.launch();
  const state = n => n.page.evaluate(() => api('state'));  // the page carries the session token
  try {
    for (const n of nodes) await waitFor(n.url, 60);
    for (const n of nodes) {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1100 }, deviceScaleFactor: shots ? 2 : 1 });
      n.page = page;
      page.on('pageerror', e => problems.push(n.side + ': Skriptfehler: ' + String(e)));
      page.on('response', r => {
        const u = new URL(r.url());
        if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400 && !u.pathname.startsWith('/api/v1')) problems.push(n.side + ': ' + r.status() + ' ' + u.pathname);
      });
      page.on('dialog', d => d.accept());
      await page.goto(n.url);
      await page.waitForFunction(() => typeof window.atlasShowView === 'function', null, { timeout: 30000 });
      await page.evaluate(() => window.atlasShowView('settings'));
      const card = page.locator('details', { has: page.locator('#mesh-quick') });
      await card.locator('summary').first().click();
      const button = page.locator('#mesh-quick-buttons button', { hasText: 'Über iCloud Drive verbinden' });
      await button.waitFor({ timeout: 15000 });
      await button.click();
      await page.locator('#mesh-quick-buttons button', { hasText: '✓ Verbunden über iCloud Drive' }).waitFor({ timeout: 20000 })
        .catch(() => problems.push(n.side + ': Knopf zeigt keine Verbindung'));
    }
    if (!fs.existsSync(path.join(cloud, 'MediathekAtlas-Verbund', 'nodes'))) problems.push('Verbundordner im Cloud-Ordner fehlt');
    // Verbund rounds run every 30 s (2 s while importing); give both sides time to see each other and import.
    let a = {}, b = {};
    for (let i = 0; i < 60; i++) {
      const sa = await state(nodes[0]), sb = await state(nodes[1]);
      if (!sa.mesh || !sb.mesh) { problems.push('state ohne mesh: ' + JSON.stringify(sa).slice(0, 300)); break; }
      [a, b] = [sa.mesh, sb.mesh];
      if ((a.nodes || []).length === 2 && (b.nodes || []).length === 2 && (b.saved || {}).results >= 30 && a.conflicts && b.conflicts) break;
      await sleep(5000);
    }
    if ((a.nodes || []).length !== 2 || (b.nodes || []).length !== 2) problems.push('Systeme sehen sich nicht: ' + JSON.stringify([a.nodes, b.nodes]));
    if (a.partitions + b.partitions !== 256) problems.push('Bereiche nicht aufgeteilt: ' + a.partitions + ' + ' + b.partitions);
    if (!((b.saved || {}).results >= 30)) problems.push('B hat A-Ergebnisse nicht übernommen: ' + JSON.stringify(b.saved));
    if (a.conflicts !== 1 || b.conflicts !== 1) problems.push('Abweichung nicht gemeldet: ' + a.conflicts + '/' + b.conflicts);
    const fsNames = fs.readdirSync(path.join(cloud, 'MediathekAtlas-Verbund', 'nodes')).flatMap(d => fs.readdirSync(path.join(cloud, 'MediathekAtlas-Verbund', 'nodes', d)));
    if (fsNames.some(f => f.endsWith('.jsonl.partial'))) problems.push('Offenes Segment liegt im Cloud-Ordner: ' + fsNames.join(', '));
    // B: works recognised through A.
    const matched = Number(execFileSync(PY, ['-c', 'import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute("SELECT COUNT(*) FROM works WHERE state=\'matched\'").fetchone()[0])', path.join(nodes[1].data, 'catalog.db')]).toString());
    if (matched !== 30) problems.push('B: erkannte Werke ' + matched + ' statt 30');
    // Conflict on B: list shows both titles; adopt A's assignment.
    const pb = nodes[1].page;
    await pb.evaluate(() => loadMeshSetup());
    await pb.waitForSelector('#mesh-conflicts:not([hidden]) .peer-row', { timeout: 15000 }).catch(() => problems.push('B: Abweichungsliste fehlt'));
    const row = await pb.locator('#mesh-conflict-list .peer-row').first().textContent().catch(() => '');
    if (!/Eigener Titel B/.test(row) || !/Eigener Titel A/.test(row) || !/Mac A/.test(row)) problems.push('B: Abweichung unklar: ' + row);
    const status = await pb.locator('#mesh-status').textContent();
    if (!/übernommen statt selbst berechnet/.test(status)) problems.push('B: Ersparnis nicht angezeigt: ' + status);
    if (shots) {
      const card = pb.locator('details', { has: pb.locator('#mesh-quick') });
      await card.screenshot({ path: path.join(shots, '0.6.51-verbund-icloud.png') });
    }
    await pb.locator('#mesh-conflict-list button', { hasText: 'übernehmen' }).first().click();
    await pb.waitForSelector('#mesh-conflicts[hidden]', { state: 'attached', timeout: 15000 }).catch(() => problems.push('B: Abweichung nach Übernahme noch sichtbar'));
    const title = execFileSync(PY, ['-c', 'import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute("SELECT title FROM works WHERE state=\'manual\'").fetchone()[0])', path.join(nodes[1].data, 'catalog.db')]).toString().trim();
    if (title !== 'Eigener Titel A') problems.push('B: Übernahme nicht gespeichert: ' + title);
    // A keeps its own manual assignment.
    const titleA = execFileSync(PY, ['-c', 'import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute("SELECT title FROM works WHERE state=\'manual\'").fetchone()[0])', path.join(nodes[0].data, 'catalog.db')]).toString().trim();
    if (titleA !== 'Eigener Titel A') problems.push('A: eigene Zuordnung verändert: ' + titleA);
    console.log('A:', JSON.stringify({ partitions: a.partitions, saved: a.saved, conflicts: a.conflicts }), 'B:', JSON.stringify({ partitions: b.partitions, saved: b.saved, conflicts: b.conflicts }));
  } catch (e) {
    problems.push('Abbruch: ' + String(e).split('\n')[0]);
  } finally {
    await browser.close();
    for (const n of nodes) n.server.kill();
  }
  if (problems.length) { console.error(problems.join('\n')); console.error('Protokolle: ' + home); process.exit(1); }
  fs.rmSync(home, { recursive: true, force: true });
  console.log('mesh_two_nodes: ohne Befund');
})().catch(e => { console.error(e); process.exit(1); });
