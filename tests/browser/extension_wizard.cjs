/* 0.6.38: Einrichtungsassistent der Chrome-Erweiterung, mit der echten Erweiterung in Chromium.

   1. App startet mit leerem Startordner → legt <Startordner>/Chrome-Erweiterung/MediathekAtlas-Videostart
      in der App-Version an.
   2. Ohne Erweiterung: Assistent zeigt „noch nicht installiert“ und die Schritte; „Ordner zeigen“ antwortet.
   3. Seite offen, dann Erweiterung (Fassung 0.0.1) geladen wie mit „Entpackte Erweiterung laden“: sie meldet
      sich ohne Neuladen der Seite.
   4. Die App schreibt die aktuelle Fassung in den Ordner: beim nächsten Seitenaufruf lädt sich die
      Erweiterung selbst neu und meldet sich mit der neuen Version.

   Aufruf: node tests/browser/extension_wizard.cjs   (startet Chromium aus Playwright selbst, headless=new) */
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const PY = process.env.PYTHON || 'python3';
const VERSION = execFileSync(PY, ['-c', 'import browser_extension,version;print(browser_extension.chrome_version(version.VERSION))'], { cwd: ROOT }).toString().trim();

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}
async function waitFor(url, seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    try { const r = await fetch(url); if (r.ok) return; } catch (e) { /* noch nicht da */ }
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('MediathekAtlas ist nach ' + seconds + ' s nicht erreichbar');
}
function provide(version, home) {
  execFileSync(PY, ['-c', 'import sys,browser_extension;browser_extension.provide(sys.argv[1],sys.argv[2])', version, home], { cwd: ROOT });
}
async function openPanel(page, url) {
  await page.goto(url);
  await page.waitForFunction(() => typeof window.atlasShowView === 'function' && !!window.AtlasDisplay, null, { timeout: 20000 });
  await page.evaluate(() => window.AtlasDisplay.ready);
  await page.evaluate(() => window.atlasShowView('settings'));
  await page.evaluate(() => { document.getElementById('direct-start-panel').open = true; });
}
async function waitState(page, wanted, ms) {
  await page.waitForFunction(w => document.getElementById('direct-start-ext-state').dataset.state === w, wanted, { timeout: ms });
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-ext-'));
  const port = await freePort();
  const server = spawn(PY, ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' },
  });
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  const problems = [];
  const check = (what, ok) => { console.log((ok ? '  ok  ' : '  FEHLER ') + what); if (!ok) problems.push(what); };
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);

    // 1. Ordner beim Start
    const folder = path.join(home, 'data', 'Chrome-Erweiterung', 'MediathekAtlas-Videostart');
    for (let i = 0; i < 40 && !fs.existsSync(path.join(folder, 'manifest.json')); i++) await new Promise(r => setTimeout(r, 250));
    const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'manifest.json'), 'utf8'));
    check('Start legt den Erweiterungsordner in Version ' + VERSION + ' an', manifest.version === VERSION);

    // 2. ohne Erweiterung
    {
      const browser = await playwright.chromium.launch({ channel: 'chromium' });
      const page = await browser.newPage();
      const errors = []; page.on('pageerror', e => errors.push(String(e)));
      await openPanel(page, url);
      await waitState(page, 'missing', 8000);
      check('ohne Erweiterung: Zustand „noch nicht installiert“', true);
      check('Schritte sichtbar', await page.isVisible('#direct-start-wizard'));
      check('Pfad im Assistenten', (await page.textContent('#direct-start-path')) === folder);
      const answer = page.waitForResponse(r => r.url().endsWith('/api/browser-extension/reveal'));
      await page.click('#direct-start-reveal');
      check('„Ordner zeigen“ antwortet mit 200', (await answer).status() === 200);
      await page.waitForFunction(() => /Ordner bereitgelegt/.test(document.getElementById('direct-start-status').textContent));
      check('keine Skriptfehler', errors.length === 0);
      await browser.close();
    }

    // 3./4. echte Erweiterung wie bei „Entpackte Erweiterung laden“ (CDP Extensions.loadUnpacked, Entwicklermodus an)
    {
      const extHome = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-ext-load-'));
      provide('0.0.1', extHome);
      const extDir = path.join(extHome, 'Chrome-Erweiterung', 'MediathekAtlas-Videostart');
      const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-ext-profile-'));
      const cdpPort = await freePort();
      const chrome = spawn(playwright.chromium.executablePath(), ['--headless=new', '--no-sandbox', '--no-first-run', '--remote-debugging-port=' + cdpPort,
        '--enable-unsafe-extension-debugging', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
      let browser = null;
      try {
        for (let i = 0; i < 40 && !browser; i++) {
          try { browser = await playwright.chromium.connectOverCDP('http://127.0.0.1:' + cdpPort); } catch (e) { await new Promise(r => setTimeout(r, 250)); }
        }
        const context = browser.contexts()[0], cdp = await browser.newBrowserCDPSession();
        { const dev = await context.newPage(); await dev.goto('chrome://extensions');
          await dev.evaluate(() => new Promise(r => chrome.developerPrivate.updateProfileConfiguration({ inDeveloperMode: true }, r))); await dev.close(); }

        // 3. Seite ist offen, dann wird die Erweiterung geladen → Erkennung ohne Neuladen der Seite
        const page = await context.newPage();
        const errors = []; page.on('pageerror', e => errors.push(String(e)));
        let navigations = 0; page.on('framenavigated', f => { if (f === page.mainFrame()) navigations++; });
        await openPanel(page, url);
        await waitState(page, 'missing', 8000);
        const before = navigations;
        await cdp.send('Extensions.loadUnpacked', { path: extDir });
        await page.waitForFunction(() => !!document.documentElement.dataset.atlasVideostart, null, { timeout: 8000 });
        check('frisch geladene Erweiterung meldet sich in der offenen Seite (0.0.1)', (await page.evaluate(() => document.documentElement.dataset.atlasVideostart)) === '0.0.1');

        // 4. App hat inzwischen die neue Fassung in den Ordner geschrieben → Selbst-Update
        provide(VERSION, extHome);
        await page.evaluate(() => sessionStorage.clear());
        await openPanel(page, url);   // nächster Seitenaufruf: alte Fassung erkannt, Neuladen angestoßen
        await waitState(page, 'ok', 15000);
        check('nach Selbst-Update: „installiert und aktuell“ mit ' + VERSION, (await page.evaluate(() => document.documentElement.dataset.atlasVideostart)) === VERSION);
        check('Seite wurde für Erkennung und Update nur durch den Test selbst geladen', navigations === before + 1);
        check('Schritte ausgeblendet', !(await page.isVisible('#direct-start-wizard')));
        const second = await context.newPage();
        await openPanel(second, url);
        await waitState(second, 'ok', 8000);
        check('neue Seite erkennt die aktuelle Erweiterung sofort', true);
        check('keine Skriptfehler', errors.length === 0);
      } finally {
        if (browser) await browser.close().catch(() => {});
        chrome.kill();
      }
    }
  } catch (e) {
    problems.push(String(e && e.stack || e));
    console.log('FEHLER: ' + (e && e.stack || e));
  } finally {
    server.kill();
  }
  console.log(problems.length ? 'extension_wizard: ' + problems.length + ' Problem(e)' : 'extension_wizard ok');
  process.exit(problems.length ? 1 : 0);
})();
