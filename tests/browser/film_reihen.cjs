/* 0.6.156: Filmreihen-/Mehrteiler-Kacheln im Browser (Mac-Prüfung 0.6.155: Klick auf eine Reihenkachel meldete
   „Serie nicht gefunden“, weil die Kachel den Reihennamen als show_key weitergab).
   Legt Reihenfilme unter zwei show_keys („Praxis mit Meerblick“), ein eigenes Filmwerk „Praxis mit Meerblick: …“ und einen
   Zweiteiler an, startet MediathekAtlas ohne Hintergrunddienste und prüft in Chromium unter Katalog → Filme:
   eine Reihenkachel „Filmreihe · 4 Filme“, Bild, Titel und „Alle Filme“ öffnen die Suche mit jedem Film einzeln,
   kein Fehler; Mehrteiler-Kachel „2 Teile“ öffnet die Teile.
   Aufruf: node tests/browser/film_reihen.cjs [Ordner für Bildschirmfotos] */
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
import json, sqlite3, sys
sys.path.insert(0, '.')
import catalog
c = sqlite3.connect(sys.argv[1]); c.row_factory = sqlite3.Row
catalog.initialize(c)
def work(wid, title, kind, show, meta, year=2022):
    c.execute('INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts,updated) VALUES(?,?,?,?,?,?,?,?,?)',
              (wid, title, kind, year, show, json.dumps(meta), 'matched', 1, 1.0))
    c.execute('INSERT INTO offers(id,work_id,payload,active,seen) VALUES(?,?,?,1,1.0)',
              ('o-' + wid, wid, json.dumps({'title': meta.get('series_film_title') or title, 'channel': 'Das Erste', 'duration': 5400,
                                          'url_video': 'https://media.example.org/%s.mp4' % wid})))
for wid, show, film, year in (('pm1', 'praxis mit meerblick', 'Der Anker', 2031), ('pm2', 'praxis mit meerblick', 'Sturmflut', 2032),
                              ('pm3', 'praxis mit meerblick (ard)', 'Herzenssache', 2033)):
    work(wid, 'Praxis mit Meerblick', 'series', show, {'title': 'Praxis mit Meerblick', 'kind': 'series', 'series_film': 1,
         'series_film_title': film, 'series_film_year': year, 'season': None, 'episode': None, 'episode_title': film}, year)
work('pm4', 'Praxis mit Meerblick: Leuchtfeuer', 'movie', '', {'title': 'Praxis mit Meerblick: Leuchtfeuer', 'kind': 'movie', 'year': 2034}, 2034)
work('zt1', 'Die Kinder von Mailand (1/2)', 'movie', '', {'title': 'Die Kinder von Mailand (1/2)', 'kind': 'movie', 'year': 2030}, 2030)
work('zt2', 'Die Kinder von Mailand (2/2)', 'movie', '', {'title': 'Die Kinder von Mailand (2/2)', 'kind': 'movie', 'year': 2030}, 2030)
work('ein', 'Einzelner Film', 'movie', '', {'title': 'Einzelner Film', 'kind': 'movie', 'year': 2019}, 2019)
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
const cardTexts = page => page.$$eval('#atlas-cross-items .atlas-uc-card', n => n.map(c => c.textContent));

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-reihen-'));
  let server, browser;
  const problems = [];
  try {
    fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
    execFileSync(PY, ['-c', SEED, path.join(home, 'data', 'catalog.db')], { cwd: ROOT });
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
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasUnifiedCatalog, null, { timeout: 20000 });
    await page.evaluate(() => window.atlasShowView('discover'));
    await page.locator('[data-catalog-source="all"]').first().click();
    await page.locator('[data-cross-kind="movies"]').click();
    await page.selectOption('#atlas-cross-sort', 'year');   // Testfilme 2030–2034 stehen vorn (vor Netzkino & Co.)
    const reihe = () => page.locator('#atlas-cross-items .atlas-uc-card', { hasText: 'Filmreihe' }).first();
    for (let i = 0; i < 40 && !(await reihe().count()); i++) {   // Liste wird beim ersten Aufruf gebaut
      await page.waitForTimeout(1000);
      await page.evaluate(() => window.AtlasUnifiedCatalog.refresh());
    }
    let cards = await cardTexts(page);
    if (!(await reihe().count())) throw new Error('keine Reihenkachel: ' + cards.join(' | '));
    const meta = await reihe().textContent();
    if (!/Praxis mit Meerblick/.test(meta) || !/4 Filme/.test(meta) || !/2034/.test(meta)) problems.push('Reihenkachel (Name, 4 Filme, Jahr 2034): ' + meta);
    if (cards.filter(t => /Praxis mit Meerblick/.test(t)).length !== 1) problems.push('Reihe nicht genau einmal: ' + cards.join(' | '));
    if (!cards.some(t => /Mehrteiler/.test(t) && /2 Teile/.test(t) && /Die Kinder von Mailand/.test(t))) problems.push('Mehrteiler fehlt: ' + cards.join(' | '));
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'reihen-katalog.png') });
    // jeder Weg in die Reihe: Knopf, Titel, Bild
    for (const how of ['button', 'title', 'poster']) {
      const target = how === 'button' ? reihe().locator('button', { hasText: 'Alle Filme' })
        : how === 'title' ? reihe().locator('h3') : reihe().locator('.atlas-uc-poster');
      if (!(await target.count())) { problems.push('Reihenkachel ohne ' + how); continue; }
      await target.first().click();
      await page.waitForFunction(() => document.getElementById('atlas-cross-query').value === 'Praxis mit Meerblick'
        && document.querySelectorAll('#atlas-cross-items .atlas-uc-card').length >= 4
        && ![...document.querySelectorAll('#atlas-cross-items .atlas-uc-card')].some(n => /Filmreihe/.test(n.textContent)), null, { timeout: 20000 })
        .catch(() => problems.push(how + ': Suche nach der Reihe öffnet nicht'));
      const text = await page.evaluate(() => document.body.innerText);
      if (/Serie nicht gefunden/.test(text)) problems.push(how + ': „Serie nicht gefunden“');
      cards = await cardTexts(page);
      for (const film of ['Der Anker', 'Sturmflut', 'Herzenssache', 'Leuchtfeuer'])
        if (!cards.some(t => t.includes(film))) problems.push(how + ': Film fehlt in der Reihe: ' + film + ' / ' + cards.slice(0, 6).join(' | ').slice(0, 600));
      if (await page.$eval('#atlas-cross-sort', s => s.value) !== 'year') problems.push(how + ': nicht nach Jahr sortiert');
      if (SHOTS && how === 'button') await page.screenshot({ path: path.join(SHOTS, 'reihen-filme.png') });
      await page.fill('#atlas-cross-query', '');
      await page.press('#atlas-cross-query', 'Enter');
      await page.selectOption('#atlas-cross-sort', 'year');
      await page.waitForFunction(() => [...document.querySelectorAll('#atlas-cross-items .atlas-uc-card')].some(n => /Filmreihe/.test(n.textContent)),
        null, { timeout: 20000 }).catch(() => problems.push('Liste nach dem Zurücksetzen ohne Reihe'));
    }
    // Mehrteiler: Klick zeigt die Teile
    await page.locator('#atlas-cross-items .atlas-uc-card', { hasText: 'Mehrteiler' }).first().locator('h3').click();
    await page.waitForFunction(() => document.getElementById('atlas-cross-query').value === 'Die Kinder von Mailand'
      && [...document.querySelectorAll('#atlas-cross-items .atlas-uc-card')].filter(n => /Mailand \(\d\/2\)/.test(n.textContent)).length === 2,
      null, { timeout: 20000 }).catch(() => problems.push('Mehrteiler öffnet die Teile nicht'));
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
    fs.rmSync(home, { recursive: true, force: true });
  }
  if (problems.length) { console.error('FEHLER\n' + problems.join('\n')); process.exit(1); }
  console.log('OK Filmreihen: eine Kachel, alle Wege öffnen die Filme, Mehrteiler öffnet die Teile');
})();
