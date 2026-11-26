/* 0.6.151: Lokale Filmarchive (lokal.py, web/lokal_archive.js).
   Legt einen „Freigabe“-Ordner mit Filmen (einer mit NFO) und einer Serie an, startet MediathekAtlas ohne Hintergrunddienste
   und prüft in Chromium: Einstellungen → „Lokale Filmarchive“ Ordner eintragen, Speichern & einlesen, Stand; Katalog →
   Quelle „Lokales Archiv“ mit Kacheln „⬇ Geladen“, Titelseite, Abspielquelle; fremde Pfade werden abgelehnt.
   Aufruf: node tests/browser/lokal_archive.cjs [Ordner für Bildschirmfotos] */
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const PY = process.env.PYTHON || 'python3';
const SHOTS = process.argv[2] || '';
const BIG = 21 * 1000 * 1000;   // über lokal.MIN_SIZE, als dünn belegte Datei
const NFO = '<movie><title>Das Boot</title><year>1981</year><plot>U-96 im Atlantik.</plot><genre>Drama</genre>' +
  '<uniqueid type="imdb">tt0082096</uniqueid></movie>';

function video(file) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, ''); fs.truncateSync(file, BIG); }
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
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-lokal-'));
  const share = path.join(home, 'Freigabe');
  let server, browser;
  const problems = [];
  try {
    fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
    video(path.join(share, 'Filme', 'Das Boot (1981)', 'Das.Boot.1981.German.1080p.mkv'));
    fs.writeFileSync(path.join(share, 'Filme', 'Das Boot (1981)', 'Das.Boot.1981.German.1080p.nfo'), NFO);
    video(path.join(share, 'Filme', 'Lola.rennt.1998.720p.mp4'));
    video(path.join(share, 'Serien', 'Babylon Berlin', 'Staffel 1', 'Babylon.Berlin.S01E01.mkv'));
    video(path.join(share, 'Serien', 'Babylon Berlin', 'Staffel 1', 'Babylon.Berlin.S01E02.mkv'));
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
    await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasLokal, null, { timeout: 20000 });
    await page.evaluate(() => window.atlasShowView('settings'));
    await page.locator('#lokal-archive-panel > summary').click();
    await page.waitForFunction(() => /Noch kein Archivordner/.test(document.getElementById('lokal-archive-status').textContent), null, { timeout: 10000 })
      .catch(() => problems.push('Startzustand ohne Ordner fehlt'));
    // relativer Pfad wird abgelehnt
    await page.fill('#lokal-archive-dirs', 'Filme');
    await page.click('#lokal-archive-save');
    await page.waitForFunction(() => /absolute Pfade/.test(document.body.innerText), null, { timeout: 10000 })
      .catch(() => problems.push('Kein Hinweis bei relativem Pfad'));
    await page.fill('#lokal-archive-dirs', share);
    await page.click('#lokal-archive-save');
    await page.waitForFunction(() => /2 Filme/.test(document.getElementById('lokal-archive-status').textContent), null, { timeout: 30000 })
      .catch(async () => problems.push('Stand nach dem Einlesen: ' + await page.textContent('#lokal-archive-status')));
    const status = await page.textContent('#lokal-archive-status');
    if (!/1 Serien mit 2 Folgen/.test(status) || !/1 mit NFO-Datei/.test(status)) problems.push('Stand: ' + status);
    const folder = await page.textContent('#lokal-archive-folders');
    if (!folder.includes(share) || !/4 Videos/.test(folder)) problems.push('Ordnerzeile: ' + folder);
    if (SHOTS) await page.locator('#lokal-archive-panel').screenshot({ path: path.join(SHOTS, 'lokal-einstellungen.png') });
    // Katalog → Lokales Archiv
    await page.evaluate(() => window.atlasShowView('discover'));
    await page.locator('[data-catalog-source="lokal"]').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#atlas-cross-items .atlas-uc-card')].some(n => /Das Boot/.test(n.textContent)),
      null, { timeout: 30000 }).catch(() => problems.push('Katalog: Das Boot fehlt'));
    const cards = await page.$$eval('#atlas-cross-items .atlas-uc-card', n => n.map(c => c.textContent));
    if (cards.length !== 2) problems.push('Katalog-Kacheln: ' + cards.length);
    if (!cards.every(t => /Geladen/.test(t))) problems.push('Kacheln ohne „Geladen“: ' + cards.join(' | '));
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'lokal-katalog.png') });
    // Titelseite
    await page.locator('#atlas-cross-items .atlas-uc-card', { hasText: 'Das Boot' }).first().locator('button', { hasText: 'Details' }).click();
    await page.waitForFunction(() => document.body.innerText.includes('U-96 im Atlantik'), null, { timeout: 15000 })
      .catch(() => problems.push('Titelseite ohne Beschreibung aus der NFO'));
    const text = await page.evaluate(() => document.body.innerText);
    if (!text.includes('Lokales Archiv')) problems.push('Titelseite nennt die Quelle nicht');
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'lokal-titel.png') });
    // Abspielquelle und Schutz
    const result = await page.evaluate(async () => {
      const list = await window.api('unified?' + new URLSearchParams({ kind: 'movies', only: 'lokal' }));
      const id = list.items.find(i => i.title === 'Das Boot').offers[0].item.id;
      const play = await window.api('play?lokal=' + id);
      let bad = '';
      try { await window.api('play?lokal=f' + '0'.repeat(20)); } catch (e) { bad = e.message; }
      return { origin: play.origin, src: play.src, bad };
    });
    if (result.origin !== 'local' || !/lokal=/.test(result.src)) problems.push('Abspielquelle: ' + JSON.stringify(result));
    if (!/nicht im lokalen Archiv/.test(result.bad)) problems.push('Unbekannter Titel nicht abgelehnt: ' + result.bad);
    // Serie: Folgen
    await page.evaluate(() => window.atlasShowView('discover'));
    await page.locator('[data-cross-kind="series"]').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#atlas-cross-items .atlas-uc-card')].some(n => /Babylon Berlin/.test(n.textContent)),
      null, { timeout: 30000 }).catch(() => problems.push('Serie fehlt im Katalog'));
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
    fs.rmSync(home, { recursive: true, force: true });
  }
  if (problems.length) { console.error('FEHLER\n' + problems.join('\n')); process.exit(1); }
  console.log('OK lokale Filmarchive: Einstellungen, Einlesen, Katalog, Titelseite, Abspielquelle');
})();
