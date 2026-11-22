/* 0.6.94: Angefangene Serien automatisch laden (web/series_autoload.js).
   Legt eine Serie mit 8 Folgen an, meldet Folge 2 als zu Ende gesehen, lässt series_autoload mit Grenze 5 laufen,
   startet MediathekAtlas ohne Hintergrunddienste und prüft in Chromium: Kasten in den Downloads mit Stand und
   Grenzhinweis, 5 wartende Aufträge, „Automatik beenden“ bricht sie ab, Schalter „aus“ wird gespeichert.
   Aufruf: node tests/browser/series_autoload.cjs [Ordner für Bildschirmfotos] */
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
import json, sys, sqlite3, time
sys.path.insert(0, '.')
from pathlib import Path
import catalog, series_autoload, watch_state
root, downloads = Path(sys.argv[1]), sys.argv[2]
c = sqlite3.connect(root / 'catalog.db'); c.row_factory = sqlite3.Row
c.execute('PRAGMA journal_mode=WAL')
catalog.initialize(c)
c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
series_autoload.initialize(c)
ids = []
for n in range(1, 9):
    title = 'Abenteuer Nummer %d' % n
    catalog.ingest(c, [{'title': title, 'topic': 'Bibi und Tina', 'description': 'Bibi und Tina', 'channel': 'ZDF', 'duration': 1500,
                        'url_video': 'https://example.org/bibi%d.mp4' % n}])
    w = c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title')=?", (title,)).fetchone()
    m = json.loads(w['meta'])
    m.update(title='Bibi und Tina', kind='series', year=2004, season=1, episode=n, episode_title=title, episode_verified=True,
             provider='TMDB', reference_id='1')
    ids.append(catalog.save_metadata(c, w['id'], m, 'matched') or w['id'])
c.commit()
watch_state.progress(root, ids[1], 1500, 1500, True)
print(series_autoload.run(root, c, {'download_dir': downloads, 'series_autoload_max': 5}))
c.commit()
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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-autoload-'));
  let server, browser;
  const problems = [];
  try {
    fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
    execFileSync(PY, ['-c', SEED, path.join(home, 'data'), path.join(home, 'downloads')], { cwd: ROOT });
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
    await page.evaluate(() => showView('queue'));
    await page.waitForSelector('.sal-item', { timeout: 20000 });
    const head = await page.$eval('.sal-item', n => n.textContent);
    if (!/Bibi und Tina/.test(head) || !/\d in Warteschlange/.test(head) || !/S01E02/.test(head)) problems.push('Serienzeile: ' + head);
    if (!/Grenze erreicht/.test(head)) problems.push('Hinweis zur Grenze fehlt: ' + head);
    await page.waitForFunction(() => [...document.querySelectorAll('.q-origin strong, .queue-table')].some(n => /Angefangene Serie · Bibi und Tina/.test(n.textContent)) || document.querySelectorAll('.q-row').length >= 3, null, { timeout: 20000 });
    // Der Download-Arbeiter läuft auch ohne Hintergrunddienste und kann einen Auftrag schon begonnen haben (example.org).
    const rows = await page.$$eval('#jobs .q-row', n => n.length);
    if (rows !== 5) problems.push('Aufträge: ' + rows);
    if (!/3 weitere verfügbar|2 weitere verfügbar/.test(head)) problems.push('weitere verfügbar: ' + head);
    if (SHOTS) await page.locator('#queue').screenshot({ path: path.join(SHOTS, '0.6.94-angefangene-serien.png') });
    await page.getByRole('button', { name: 'Automatik beenden' }).click();
    await page.waitForFunction(() => /beendet/.test(document.querySelector('.sal-item')?.textContent || ''), null, { timeout: 10000 });
    const states = await page.evaluate(async () => {
      const token = document.querySelector('meta[name=atlas-token]').content;
      return (await (await fetch('/api/state', { headers: { 'X-Atlas-Token': token } })).json()).jobs.map(j => j.state);
    });
    if (states.some(s => s === 'queued')) problems.push('nach „Automatik beenden“ noch wartend: ' + states.join());
    await page.locator('#series-autoload-panel .sal-enabled').uncheck();
    await page.waitForFunction(() => document.getElementById('series-autoload-summary').textContent === 'aus', null, { timeout: 10000 });
    const saved = await page.evaluate(async () => {
      const token = document.querySelector('meta[name=atlas-token]').content;
      return (await (await fetch('/api/series-autoload', { headers: { 'X-Atlas-Token': token } })).json()).settings.enabled;
    });
    if (saved !== false) problems.push('Schalter nicht gespeichert');
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('series_autoload ok');
})();
