/* Abo-Einstellungen (22.11.2026): Einstellungen eines YouTube-Abos bleiben bei einer Aktualisierung offen (Björn 22.11.2026:
   „schließen sich nach Zeit x automatisch, oft zu schnell, um Änderungen vorzunehmen“).
   Ursache: show() zeichnete alle 8 s (solange geprüft/geladen wird) die Abo-Liste neu und verwarf das ⚙-Formular.
   Prüft: ⚙ öffnen, Werte eintippen, „Weitere Einstellungen“ aufklappen, zwei Aktualisierungen (derselbe Weg wie der
   8-s-Takt) → Formular offen, Eingaben stehen, Fokus bleibt; Speichern schließt es und übernimmt die Werte.
   Dazu „Neue Kanäle entdecken“: geöffnete Vorschau überlebt das Neuladen der Liste.
   Aufruf: node tests/browser/abo_settings.cjs */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const PY = process.env.PYTHON || 'python3';

const SEED = `
import json, sys, time
sys.path.insert(0, '.')
from pathlib import Path
import youtube_abos as ab, youtube_discover as d
root = Path(sys.argv[1])
ab.add(root, {'url': '@Kinderkanal', 'profile': 'kinder'})
ab.add(root, {'url': '@Zweitkanal', 'profile': 'kinder'})
db = d._connect(root)
now = time.time()
vids = [{'video': 'v%010d' % n, 'title': 'Video %d' % n, 'duration': 300, 'published': '2026-11-%02dT08:00:00Z' % n,
         'poster': 'data:image/gif;base64,R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=', 'age': False, 'short': False} for n in range(1, 4)]
db.execute('INSERT INTO youtube_suggestions(ref,title,score,why,profile,found,updated,sample,sampled) VALUES(?,?,?,?,?,?,?,?,?)',
           ('@malkanal', 'Malkanal', 2.0, json.dumps(['erwähnt']), 'kinder', now, now, json.dumps({'videos': vids, 'channel_id': 'UC' + 'm' * 22}), now))
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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-abo-settings-'));
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
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on('pageerror', e => problems.push('Seitenfehler: ' + e.message));
    await page.goto(url);
    await page.evaluate(() => {
      for (const id of ['youtube-abos', 'youtube-discover'])
        for (let n = document.getElementById(id); n; n = n.parentElement) {
          if (n.hidden) n.hidden = false;
          if (n.tagName === 'DETAILS') n.open = true;
          if (getComputedStyle(n).display === 'none') n.style.display = 'block';
        }
    });
    await page.waitForSelector('#youtube-abos-list .abo-card', { timeout: 20000 });
    const first = page.locator('#youtube-abos-list .abo-card').first();
    await first.getByRole('button', { name: 'Einstellungen' }).click();
    const form = first.locator('.abo-form');
    await form.getByLabel('Nur eine Reihe (Titelwörter)').fill('Bluey');
    await form.locator('summary', { hasText: 'Weitere Einstellungen' }).click();
    const exclude = form.getByLabel('Ausschließen (Titelwörter)');
    await exclude.fill('Trail');
    // Aktualisierung wie im 8-s-Takt (load → show → render), zweimal
    for (let i = 0; i < 2; i++) await page.evaluate(() => window.MediathekAtlasYouTubeAbos.refresh());
    const state = await page.evaluate(() => {
      const card = document.querySelector('#youtube-abos-list .abo-card');
      const f = card && card.querySelector('.abo-form');
      if (!f) return null;
      const inputs = [...f.querySelectorAll('input:not([type])')];
      return { values: inputs.map(i => i.value), more: f.querySelector('.abo-more').open,
               focus: document.activeElement && document.activeElement.placeholder, chips: !!card.querySelector('.abo-chips') };
    });
    if (!state) problems.push('Formular nach Aktualisierung geschlossen');
    else {
      if (!state.values.includes('Bluey') || !state.values.includes('Trail')) problems.push('Eingaben verloren: ' + state.values.join('|'));
      if (!state.more) problems.push('„Weitere Einstellungen“ zugeklappt');
      if (!/Trailer/.test(state.focus || '')) problems.push('Fokus verloren: ' + state.focus);
      if (!state.chips) problems.push('Karte ohne Statuszeile nach Aktualisierung');
    }
    await page.keyboard.type('er');
    await form.getByRole('button', { name: 'Speichern' }).click();
    await page.waitForFunction(() => !document.querySelector('#youtube-abos-list .abo-form'), null, { timeout: 10000 });
    const abo = await page.evaluate(async () => {
      const token = document.querySelector('meta[name=atlas-token]').content;
      return (await (await fetch('/api/youtube-abos', { headers: { 'X-Atlas-Token': token } })).json()).abos.find(a => /bluey/i.test(a.include));
    });
    if (!abo || !/^trailer$/i.test(abo.exclude)) problems.push('Gespeichert falsch: ' + JSON.stringify(abo && {include: abo.include, exclude: abo.exclude}));
    if (await page.locator('#youtube-abos-list .abo-card').count() !== 2) problems.push('Kartenzahl nach Speichern');

    // Kanal-Vorschläge: geöffnete Vorschau bleibt beim Neuladen der Liste
    const mal = page.locator('.discover-card', { hasText: 'Malkanal' });
    await mal.getByRole('button', { name: 'Videos zeigen' }).click();
    await mal.locator('.discover-video').first().waitFor();
    await page.evaluate(() => { const d = document.getElementById('youtube-discover'); d.open = false; d.open = true; });
    await page.waitForTimeout(1500);
    if (await page.locator('.discover-card .discover-video').count() !== 3) problems.push('Vorschau nach Neuladen weg');
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('abo_settings ok');
})();
