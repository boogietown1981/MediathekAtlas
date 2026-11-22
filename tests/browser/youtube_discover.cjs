/* 0.6.90: Kanal-Vorschläge in YouTube → Kanal-Abos (web/youtube_discover.js).
   Legt ein Kinder-Abo und drei Vorschläge an (einer schon angesehen), startet MediathekAtlas ohne
   Hintergrunddienste und prüft in Chromium: Liste mit Gründen, Freigabe erst nach „Videos ansehen“,
   „Für die Kinderecke freigeben“ legt ein Kinder-Abo an, „Nicht vorschlagen“ verschiebt nach „Entschieden“.
   Aufruf: node tests/browser/youtube_discover.cjs [Ordner für Bildschirmfotos] */
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
import json, sys, time
sys.path.insert(0, '.')
from pathlib import Path
import youtube_abos as ab, youtube_discover as d
root = Path(sys.argv[1])
ab.add(root, {'url': '@Kinderkanal', 'profile': 'kinder'})
db = d._connect(root)
now = time.time()
vids = [{'video': 'v%010d' % n, 'title': 'Wir malen einen Elefanten – Teil %d' % n, 'duration': 420 + n, 'published': '2026-11-%02dT08:00:00Z' % n,
         'poster': 'data:image/gif;base64,R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=', 'age': False, 'short': False} for n in range(1, 5)]
rows = [('UC' + 'f' * 22, 'Tierkanal', 7.75, ['von „Kinderkanal“ empfohlen'], ''),
        ('@malkanal', 'Malkanal', 2.0, ['in 2 gesehenen Videos von „Kinderkanal“ erwähnt'], json.dumps({'videos': vids, 'channel_id': 'UC' + 'm' * 22})),
        ('@andere', '@andere', 0.3, ['in 1 Videos von „Kinderkanal“ erwähnt'], '')]
for ref, title, score, why, sample in rows:
    db.execute('INSERT INTO youtube_suggestions(ref,title,score,why,profile,found,updated,sample,sampled) VALUES(?,?,?,?,?,?,?,?,?)',
               (ref, title, score, json.dumps(why), 'kinder', now, now, sample, now if sample else 0))
db.execute("INSERT OR REPLACE INTO youtube_state(name,value) VALUES('discover_last',?)", (str(now),))
db.commit()
`;

function freePort() {
  return new Promise(resolve => { const s = net.createServer(); s.listen(0, () => { const p = s.address().port; s.close(() => resolve(p)); }); });
}
async function waitFor(url, seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    try { const r = await fetch(url); if (r.ok) return; } catch (e) { /* startet noch */ }
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('Server startet nicht');
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-discover-'));
  let server, browser;
  const problems = [];
  try {
    fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
    execFileSync(PY, ['-c', SEED, path.join(home, 'data')], { cwd: ROOT });
    const port = await freePort();
    server = spawn(PY, ['server.py', '--no-browser'], { cwd: ROOT, stdio: 'ignore',
      env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
             MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' } });
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: SHOTS ? 2 : 1 });
    page.on('pageerror', e => problems.push('Seitenfehler: ' + e.message));
    await page.goto(url);
    await page.evaluate(() => {
      for (let n = document.getElementById('youtube-discover'); n; n = n.parentElement) {
        if (n.hidden) n.hidden = false;
        if (n.tagName === 'DETAILS') n.open = true;
        if (getComputedStyle(n).display === 'none') n.style.display = 'block';
      }
    });
    await page.waitForSelector('.discover-card', { timeout: 20000 });
    const cards = await page.$$eval('.discover-card strong', n => n.map(x => x.textContent));
    if (cards.join('|') !== 'Tierkanal|Malkanal|@andere') problems.push('Reihenfolge: ' + cards.join('|'));
    const disabled = await page.$$eval('.discover-card', n => n.map(c => [...c.querySelectorAll('button')].find(b => b.textContent.includes('Kinderecke')).disabled));
    if (disabled.join() !== 'true,false,true') problems.push('Freigabe vor dem Ansehen möglich: ' + disabled.join());
    // Malkanal ist angesehen (Vorschau im Speicher): Videos zeigen, dann freigeben
    const mal = page.locator('.discover-card', { hasText: 'Malkanal' });
    await mal.getByRole('button', { name: 'Videos zeigen' }).click();
    await mal.locator('.discover-video').first().waitFor();
    if (await mal.locator('.discover-video').count() !== 4) problems.push('Vorschau ohne 4 Videos');
    await mal.scrollIntoViewIfNeeded();
    if (SHOTS) await page.locator('#youtube-discover').screenshot({ path: path.join(SHOTS, '0.6.90-kanal-vorschlaege.png') });
    await mal.getByRole('button', { name: /Kinderecke freigeben/ }).click();
    await page.waitForFunction(() => /Kinderecke/.test(document.getElementById('youtube-discover-status').textContent), null, { timeout: 10000 });
    const abos = await page.evaluate(async () => {
      const token = document.querySelector('meta[name=atlas-token]').content;
      return (await (await fetch('/api/youtube-abos', { headers: { 'X-Atlas-Token': token } })).json()).abos.map(a => a.ref + ':' + a.profile);
    });
    if (!abos.includes('UC' + 'm'.repeat(22) + ':kinder')) problems.push('kein Kinder-Abo nach Freigabe: ' + abos.join());
    await page.locator('.discover-card', { hasText: '@andere' }).getByRole('button', { name: 'Nicht vorschlagen' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.discover-card').length === 1, null, { timeout: 10000 });
    const decided = await page.$eval('.discover-decided summary', n => n.textContent);
    if (decided !== 'Entschieden (2)') problems.push('Entschieden: ' + decided);
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('youtube_discover ok');
})();
