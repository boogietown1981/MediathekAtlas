/* 0.6.46: Kinderecke mit Kinderfilmen und -serien aus dem Katalog (kids_catalog.py, web/kids.js) und
   Vollbild der Chrome-Erweiterung auf einer nachgestellten Anbieterseite (autostart.js).

   Legt einen Werkkatalog mit eindeutigen Kinderinhalten, einem Kinderkrimi und einer Serie mit einer
   Krimi-Folge an, startet MediathekAtlas ohne Hintergrunddienste und prüft in Chromium:
   - nur eindeutige Kinderinhalte erscheinen, Film und Folge spielen (Sender-Adresse wird durch ein
     kurzes Testvideo ersetzt), nach einer Folge wird die nächste angeboten,
   - /api/kids-play lehnt alles ab, was nicht in der Kinderecke steht,
   - autostart.js meldet „fullscreen“, lässt den Player das Fenster füllen, schaltet mit dem ersten
     echten Klick das Vollbild des Players ein und räumt mit Esc wieder auf (chrome.* nachgestellt).

   0.6.91: erkannter Märchenfilm/KiKA-Film erscheinen, Folgen ohne Abgleich, Reihe mit Pfeilen blättern,
   „Alle …“-Kachel und ganze Liste (264 Filme, früher nach 240 abgeschnitten).

   Aufruf: node tests/browser/kids_corner.cjs [Ordner für Bildschirmfotos] */
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
def add(wid, title, genres, kind='movie', show=None, season=None, episode=None, state='matched', attempts=1, channel='Das Erste', topic=''):
    meta = {'title': title if kind == 'movie' else show, 'kind': kind, 'genres': genres}
    if kind == 'series': meta.update(season=season, episode=episode, episode_title=title)
    c.execute('INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,?)',
              (wid, meta['title'], kind, 2015, show or wid, json.dumps(meta), state, attempts))
    c.execute('INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)',
              ('o-' + wid, wid, json.dumps({'title': title, 'channel': channel, 'topic': topic, 'duration': 3, 'url_video': 'https://media.example.org/%s.mp4' % wid})))
    for g in genres: c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))
add('rabe', 'Der kleine Rabe Socke', ['Kinder'])
add('trick', 'Trickfilm für alle', ['Familie', 'Animation'])
add('kidskrimi', 'Kinderkrimi', ['Kinder', 'Krimi'])
add('drama', 'Familiendrama', ['Familie', 'Drama'])
add('offen', 'Noch nicht abgeglichen', ['Kinder'], state='new', attempts=0)
add('m1', 'Die Maus im Zoo', ['Kinder'], 'series', 'Die Maus', 1, 1)
add('m2', 'Die Maus am Meer', ['Kinder'], 'series', 'Die Maus', 1, 2)
add('m3', 'Sonderfolge Krimi', ['Kinder', 'Krimi'], 'series', 'Die Maus', 1, 3)
add('t1', 'Tatort Folge', ['Krimi'], 'series', 'Tatort', 1, 1)
# 0.6.91: erkannter Märchenfilm (IMDb „Family, Fantasy“) aus „Sechs auf einen Streich“, KiKA-Film, Folge ohne Abgleich,
# viele Kinderfilme (Reihe muss sich blättern lassen, Liste nicht nach 240 abgeschnitten)
add('gaensemagd', 'Zz Die Gänsemagd', ['Familie', 'Fantasy'], topic='Sechs auf einen Streich')
add('kikafilm', 'Ein KiKA-Film', ['Abenteuer'], channel='KiKA')
add('m4', 'Die Maus im Wald', [], 'series', 'Die Maus', 1, 4, state='pending', attempts=0)
for i in range(260): add('kf%03d' % i, 'Kinderfilm %03d' % i, ['Kinder'])
c.commit()
`;

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

async function kidsCorner(browser, url, clip, problems) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('pageerror', e => problems.push('Skriptfehler: ' + String(e)));
  const refused = [];
  page.on('response', r => { const u = new URL(r.url()); if (u.hostname === '127.0.0.1' && u.pathname.startsWith('/api/') && r.status() >= 400) refused.push(r.status() + ' ' + u.pathname); });
  const asked = [];
  await page.route('https://media.example.org/**', route => { asked.push(route.request().url()); route.fulfill({ status: 200, contentType: 'video/webm', body: clip }); });
  const check = (what, ok) => { if (!ok) problems.push('Erwartung nicht erfüllt: ' + what); };
  await page.goto(url + 'kinder');
  await page.waitForSelector('.kids-tile', { timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll('.kids-tile[data-kind=movie]').length >= 2, null, { timeout: 30000 });
  const titles = await page.locator('.kids-tile .kids-title').allTextContents();
  check('Kinderfilme stehen in der Kinderecke: ' + titles.join(' | '), titles.includes('Der kleine Rabe Socke') && titles.includes('Ein KiKA-Film'));
  check('Serie steht in der Kinderecke', titles.includes('Die Maus'));
  for (const bad of ['Kinderkrimi', 'Familiendrama', 'Noch nicht abgeglichen', 'Tatort'])
    check('„' + bad + '“ bleibt draußen', !titles.includes(bad));
  const chips = await page.locator('.kids-chip-name').allTextContents();
  check('Auswahl Filme/Serien oben: ' + chips.join(','), chips.includes('Filme') && chips.includes('Serien'));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.46-kinderecke.png') });
  await scrolling(page, check);

  // Film abspielen
  await page.locator('.kids-tile', { hasText: 'Der kleine Rabe Socke' }).first().click();
  await page.waitForFunction(() => { const v = document.getElementById('kids-video'); return !document.getElementById('kids-stage').hidden && v.currentTime > 0.3; }, null, { timeout: 20000 })
    .catch(() => problems.push('Film spielt nicht: ' + refused.join(',')));
  check('Film kommt von der Adresse des Senders', asked.some(u => u.endsWith('/rabe.mp4')));
  await page.locator('#kids-close').click();
  await page.waitForFunction(() => document.getElementById('kids-stage').hidden);

  // Schutz: nichts außerhalb der Liste, auch nicht mit gültiger Sitzung
  const codes = await page.evaluate(async () => {
    const token = document.querySelector('meta[name=atlas-token]').content, out = {};
    for (const [name, query] of [['krimi', 'offer=o-kidskrimi'], ['offen', 'offer=o-offen'], ['tatort', 'offer=o-t1'], ['leer', ''], ['folge3', 'offer=o-m3'], ['rabe', 'offer=o-rabe']])
      out[name] = (await fetch('/api/kids-play?' + query, { headers: { 'X-Atlas-Token': token } })).status;
    out.serie = (await fetch('/api/kids-episodes?source=mediatheken&series=Tatort', { headers: { 'X-Atlas-Token': token } })).status;
    return out;
  });
  check('kids-play lehnt Fremdes ab: ' + JSON.stringify(codes), codes.krimi === 404 && codes.offen === 404 && codes.tatort === 404 && codes.leer === 404 && codes.folge3 === 404 && codes.rabe === 200 && codes.serie === 404);

  // Serie: Folgen, Abspielen, nächste Folge
  await page.locator('.kids-chip', { hasText: 'Serien' }).click();
  await page.locator('.kids-tile[data-kind=series]', { hasText: 'Die Maus' }).click();
  await page.waitForSelector('.kids-tile[data-kind=episode]', { timeout: 20000 });
  const eps = await page.locator('.kids-tile[data-kind=episode] .kids-title').allTextContents();
  // 0.6.91: Folgen ohne eigenen Abgleich gehören dazu, nur die Krimi-Folge fällt heraus
  check('drei Folgen, Krimi-Folge fehlt: ' + eps.join(' | '), eps.length === 3 && eps[0].includes('Die Maus im Zoo') && eps[1].includes('Die Maus am Meer') && eps[2].includes('Die Maus im Wald'));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.46-kinderecke-serie.png') });
  await page.locator('.kids-tile[data-kind=episode]').first().click();
  await page.waitForFunction(() => !document.getElementById('kids-next').hidden, null, { timeout: 30000 })
    .catch(() => problems.push('Nach der Folge wird keine nächste angeboten'));
  check('nächste Folge wird angeboten', (await page.locator('#kids-next-title').textContent()) === 'Die Maus am Meer');
  await page.locator('#kids-next-stop').click();
  await page.locator('.kids-back').click();
  check('zurück zur Übersicht', await page.locator('.kids-tile[data-kind=series]').count() >= 1);
  const marks = await page.evaluate(async () => {
    const token = document.querySelector('meta[name=atlas-token]').content;
    return (await (await fetch('/api/kids', { headers: { 'X-Atlas-Token': token } })).json()).catalog;
  });
  check('Liste ohne Fehler', !marks.error);
  await page.close();
}

// 0.6.91 (Björn: „kann nicht weiter nach rechts scrollen“): Pfeilknöpfe, „Alle …“-Kachel, ganze Liste
async function scrolling(page, check) {
  const strip = page.locator('.kids-row', { has: page.locator('h2', { hasText: 'Filme' }) }).first();
  const box = strip.locator('.kids-strip');
  const before = await box.evaluate(b => ({ left: b.scrollLeft, wide: b.scrollWidth > b.clientWidth + 50 }));
  check('Filmreihe ist breiter als das Fenster', before.wide);
  check('Pfeil „zurück“ am Anfang verborgen', await strip.locator('.kids-arrow-prev').isHidden());
  await strip.locator('.kids-arrow-next').click();
  await page.waitForFunction(() => { const b = [...document.querySelectorAll('.kids-row')].find(r => r.querySelector('h2').textContent.startsWith('Filme')).querySelector('.kids-strip'); return b.scrollLeft > 300; }, null, { timeout: 5000 })
    .catch(() => check('Pfeil „weiter“ blättert die Reihe', false));
  check('Pfeil „zurück“ erscheint nach dem Blättern', await strip.locator('.kids-arrow-prev').isVisible());
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.91-kinderecke-blaettern.png') });
  // bis ans Ende: zuletzt kommt die „Alle …“-Kachel
  for (let i = 0; i < 30 && await strip.locator('.kids-arrow-next').isVisible(); i++) { await strip.locator('.kids-arrow-next').click(); await page.waitForTimeout(350); }
  const more = strip.locator('.kids-more');
  check('„Alle … Filme“-Kachel am Ende sichtbar', await more.isVisible());
  const total = await page.evaluate(async () => { const token = document.querySelector('meta[name=atlas-token]').content;
    return (await (await fetch('/api/kids', { headers: { 'X-Atlas-Token': token } })).json()).catalog.movies.length; });
  check('Liste nicht nach 240 abgeschnitten: ' + total, total === 264);
  await more.click();
  await page.waitForFunction(n => document.querySelectorAll('.kids-grid .kids-tile[data-kind=movie]').length === n, total, { timeout: 10000 })
    .catch(() => check('„Alle Filme“ zeigt die ganze Liste', false));
  const all = await page.locator('.kids-grid .kids-title').allTextContents();
  check('erkannter Märchenfilm, KiKA-Film und Trickfilm dabei', all.includes('Zz Die Gänsemagd') && all.includes('Ein KiKA-Film') && all.includes('Trickfilm für alle'));
  // Kanal-/Auswahlleiste oben lässt sich ebenfalls ohne Seitwärtsrad bedienen (Pfeile vorhanden)
  check('Auswahlleiste hat Pfeilknöpfe', await page.locator('.kids-chips-scroller .kids-arrow-next').count() === 1);
  await page.locator('.kids-chip', { hasText: 'Alle' }).first().click();
  await page.waitForSelector('.kids-strip');
}

async function providerFullscreen(browser, clip, problems) {
  const check = (what, ok) => { if (!ok) problems.push('Erwartung nicht erfüllt: ' + what); };
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', e => problems.push('Skriptfehler (Anbieterseite): ' + String(e)));
  const html = `<!doctype html><html><body style="margin:0"><header style="height:120px;background:#333;color:#fff">Anbieter</header>
    <main style="transform:translateZ(0);padding:40px"><div id="player-box" class="player" style="position:relative;width:640px;height:360px">
      <video id="v" src="/clip.webm" loop muted style="width:640px;height:360px"></video>
      <button class="vjs-big-play-button" aria-label="Play" style="position:absolute;left:280px;top:140px;width:80px;height:80px" onclick="document.getElementById('v').play()">▶</button>
    </div><p>Weitere Titel …</p></main></body></html>`;
  await page.route('https://www.toggo.de/**', route => route.request().url().endsWith('/clip.webm')
    ? route.fulfill({ status: 200, contentType: 'video/webm', body: clip }) : route.fulfill({ status: 200, contentType: 'text/html', body: html }));
  await page.addInitScript(() => {
    window.__sent = [];
    window.chrome = { storage: { sync: { get: (defaults, cb) => cb(defaults) } }, runtime: { sendMessage: (m, cb) => { window.__sent.push(m.type); if (cb) cb(); } } };
  });
  await page.addInitScript({ path: path.join(ROOT, 'web', 'browser-extension', 'chrome', 'autostart.js') });
  await page.goto('https://www.toggo.de/videos/test#mediathekatlas-autostart');
  await page.waitForFunction(() => window.__sent.includes('fullscreen'), null, { timeout: 30000 })
    .catch(() => problems.push('Erweiterung meldet kein Vollbild'));
  const box = await page.evaluate(() => { const r = document.getElementById('player-box').getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight, playing: !document.getElementById('v').paused }; });
  check('Video läuft', box.playing);
  check('Player füllt das Fenster: ' + JSON.stringify(box), box.x === 0 && box.y === 0 && box.w === box.vw && box.h === box.vh);
  check('ohne Eingabe noch kein Element-Vollbild (Chrome-Regel)', !(await page.evaluate(() => !!document.fullscreenElement)));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.46-anbieter-vollbild.png') });
  await page.mouse.click(640, 400);                    // erster echter Klick
  await page.waitForFunction(() => !!document.fullscreenElement, null, { timeout: 5000 })
    .catch(() => problems.push('Erster Klick schaltet das Vollbild des Players nicht ein'));
  check('Klick hält das Video nicht an', await page.evaluate(() => !document.getElementById('v').paused));
  await page.evaluate(() => document.exitFullscreen());
  await page.waitForFunction(() => !document.fullscreenElement);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.__sent.includes('fullscreen-exit'), null, { timeout: 5000 })
    .catch(() => problems.push('Esc beendet das Vollbild nicht'));
  const after = await page.evaluate(() => { const r = document.getElementById('player-box').getBoundingClientRect(); return { w: r.width, h: r.height, classes: document.querySelectorAll('[class*=mediathekatlas-fill]').length }; });
  check('nach Esc wieder normale Größe: ' + JSON.stringify(after), after.w === 640 && after.h === 360 && after.classes === 0);
  await page.close();

  // Schalter aus: kein Vollbild
  const off = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await off.route('https://www.toggo.de/**', route => route.request().url().endsWith('/clip.webm')
    ? route.fulfill({ status: 200, contentType: 'video/webm', body: clip }) : route.fulfill({ status: 200, contentType: 'text/html', body: html }));
  await off.addInitScript(() => {
    window.__sent = [];
    window.chrome = { storage: { sync: { get: (defaults, cb) => cb({ ...defaults, fullscreen: false }) } }, runtime: { sendMessage: m => window.__sent.push(m.type) } };
  });
  await off.addInitScript({ path: path.join(ROOT, 'web', 'browser-extension', 'chrome', 'autostart.js') });
  await off.goto('https://www.toggo.de/videos/test#mediathekatlas-autostart');
  await off.waitForFunction(() => !document.getElementById('v').paused && document.getElementById('v').currentTime > 0.5, null, { timeout: 30000 }).catch(() => problems.push('Video startet ohne Vollbild-Schalter nicht'));
  await off.waitForTimeout(1500);
  check('Schalter aus: kein Vollbild', await off.evaluate(() => !window.__sent.includes('fullscreen') && !document.querySelector('.mediathekatlas-fill')));
  await off.close();
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-kids-'));
  fs.mkdirSync(path.join(home, 'data')); fs.mkdirSync(path.join(home, 'downloads'));
  const problems = [];
  let server = null, browser = null;
  try {
    const clipPath = path.join(home, 'clip.webm');
    execFileSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=3', '-c:v', 'libvpx', '-b:v', '100k', clipPath]);
    const clip = fs.readFileSync(clipPath);
    execFileSync(PY, ['-c', SEED, path.join(home, 'data', 'catalog.db')], { cwd: ROOT });
    const port = await freePort();
    server = spawn(PY, ['server.py', '--no-browser'], { cwd: ROOT, stdio: 'ignore',
      env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
             MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' } });
    const url = 'http://127.0.0.1:' + port + '/';
    await waitFor(url, 40);
    browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
    await kidsCorner(browser, url, clip, problems);
    await providerFullscreen(browser, clip, problems);
  } catch (e) {
    problems.push('Abbruch: ' + (e && e.stack || e));
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.kill();
    try { fs.rmSync(home, { recursive: true, force: true }); } catch (e) { /* Testordner */ }
  }
  console.log(problems.length ? 'kids_corner: ' + problems.length + ' Problem(e)' : 'kids_corner ok');
  for (const p of problems) console.log('  - ' + p);
  process.exit(problems.length ? 1 : 0);
})();
