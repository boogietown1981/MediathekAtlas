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
    meta = {'title': title if kind == 'movie' else show, 'kind': kind, 'genres': genres, 'genre_source': 'TMDB'}  # 0.6.106: Referenz-Genres (aus Namen abgeleitetes „Kinder“ zählt nicht)
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
# 0.6.98: eine Reihe muss selbst Kinderprogramm sein (mind. 80 % der eingeordneten Folgen); Nachrichtenreihe mit
# einzelnen „Kinder“-Werken bleibt draußen
add('m5', 'Die Maus im Schnee', ['Kinder'], 'series', 'Die Maus', 1, 5)
add('m6', 'Die Maus im Regen', ['Kinder'], 'series', 'Die Maus', 1, 6)
for i in range(12): add('pol%02d' % i, 'Politik heute %d' % i, ['Kinder'] if i < 2 else ['Talk'], 'series', 'Politik', 1, i + 1)
for i in range(260): add('kf%03d' % i, 'Kinderfilm %03d' % i, ['Kinder'])
# 0.6.93: Gruppen – drei Märchen, drei Zeichentrickfilme (kleinere Gruppen gehen in „Noch mehr“)
add('schnee', 'Schneewittchen', ['Fantasy'], channel='ZDF', topic='Märchenperlen')
add('holle', 'Frau Holle', ['Familie', 'Fantasy'], topic='Sechs auf einen Streich')
add('trick2', 'Bunte Trickwelt', ['Kinder', 'Animation'])
add('trick3', 'Comic-Abenteuer', ['Kinder', 'Animation'])
# 0.6.99: nicht erkannter Film aus einer Kinderreihe wartet auf Freigabe; KiKA-Livestream für „Fernsehen“
add('wartet', 'Wartender Kinderfilm', [], topic='Kinderfilme', state='retry')
c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts,topic) VALUES('kikalive','KiKA Livestream','other',NULL,'kikalive','{}','format',0,'Livestream')")
c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES('o-kikalive','kikalive',?,1)", (json.dumps({'title': 'KiKA Livestream', 'channel': 'KiKA', 'topic': 'Livestream', 'duration': 0, 'url_video': 'https://media.example.org/kikalive.mp4'}),))
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

// 0.6.99: „Fernsehen“ (Kindersender live) und Elternbereich (Wartet auf Freigabe → Freigeben)
async function liveAndParents(page, url, check, asked) {
  const titles = await page.locator('.kids-tile .kids-title').allTextContents();
  check('wartender, nicht erkannter Film fehlt zunächst', !titles.includes('Wartender Kinderfilm'));
  await page.locator('.kids-chip', { hasText: 'Fernsehen' }).click();
  await page.waitForSelector('.kids-tile[data-kind=live]', { timeout: 15000 }).catch(() => check('Kindersender erscheinen', false));
  const live = await page.locator('.kids-tile[data-kind=live] .kids-title').allTextContents();
  check('nur KiKA live: ' + live.join(' | '), live.length === 1 && live[0] === 'KiKA');
  await page.locator('.kids-tile[data-kind=live]').first().click();
  await page.waitForFunction(() => { const v = document.getElementById('kids-video'); return !document.getElementById('kids-stage').hidden && v.currentTime > 0.3; }, null, { timeout: 20000 })
    .catch(() => check('KiKA live spielt', false));
  check('Livestream von der Sender-Adresse', asked.some(u => u.endsWith('/kikalive.mp4')));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.99-kinderecke-live.png') });
  await page.locator('#kids-close').click();
  await page.waitForFunction(() => document.getElementById('kids-stage').hidden);
  // Elternbereich in der Verwaltung
  const admin = await page.context().browser().newPage({ viewport: { width: 1280, height: 900 } });
  await admin.goto(url);
  await admin.waitForFunction(() => typeof window.atlasShowView === 'function');
  await admin.evaluate(() => window.atlasShowView('settings'));
  await admin.locator('#kids-parents-panel > summary').click();
  await admin.waitForSelector('#kids-waiting .kids-parents-row', { timeout: 20000 }).catch(() => check('Wartet auf Freigabe gefüllt', false));
  check('Standardgrenze FSK 12', await admin.locator('#kids-max-age').inputValue() === '12');
  const row = admin.locator('#kids-waiting .kids-parents-row', { hasText: 'Wartender Kinderfilm' });
  check('Grund „Nicht erkannt“', (await row.textContent()).includes('Nicht erkannt'));
  if (SHOTS) await admin.screenshot({ path: path.join(SHOTS, '0.6.99-eltern.png'), fullPage: false });
  await row.locator('button', { hasText: 'Freigeben' }).click();
  await admin.waitForSelector('#kids-choices .kids-parents-row', { timeout: 10000 }).catch(() => check('Entscheidung erscheint', false));
  await admin.close();
  await page.reload();
  await page.waitForSelector('.kids-tile');
  // steht in „Noch mehr“ hinter den ersten 40 Kacheln → über „Alle …“ öffnen
  await page.locator('.kids-row', { has: page.locator('h2', { hasText: 'Noch mehr' }) }).first().locator('.kids-more').click();
  await page.waitForFunction(() => [...document.querySelectorAll('.kids-tile .kids-title')].some(t => t.textContent === 'Wartender Kinderfilm'), null, { timeout: 15000 })
    .catch(() => check('freigegebener Film erscheint in der Kinderecke', false));
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
  check('Nachrichten-/Talkreihe nicht in der Kinderecke', !titles.includes('Politik'));
  for (const bad of ['Kinderkrimi', 'Familiendrama', 'Noch nicht abgeglichen', 'Tatort'])
    check('„' + bad + '“ bleibt draußen', !titles.includes(bad));
  const chips = await page.locator('.kids-chip-name').allTextContents();
  check('Auswahl Filme/Serien oben: ' + chips.join(','), chips.includes('Filme') && chips.includes('Serien'));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.46-kinderecke.png') });
  await scrolling(page, check);
  await liveAndParents(page, url, check, asked);

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
  check('fünf Folgen, Krimi-Folge fehlt: ' + eps.join(' | '), eps.length === 5 && eps[0].includes('Die Maus im Zoo') && eps[1].includes('Die Maus am Meer') && eps[2].includes('Die Maus im Wald'));
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
  await visibleBlock(page, url, check);
  await page.close();
}

// 0.6.113: sichtbaren Titel in der Elternansicht sperren und zurücknehmen
async function visibleBlock(page, url, check) {
  const kidsTitles = () => page.evaluate(async () => {
    const token = document.querySelector('meta[name=atlas-token]').content;
    const cat = (await (await fetch('/api/kids', { headers: { 'X-Atlas-Token': token } })).json()).catalog;
    return [...cat.movies, ...cat.series].map(t => t.title);
  });
  const admin = await page.context().browser().newPage({ viewport: { width: 1280, height: 900 } });
  await admin.goto(url);
  await admin.waitForFunction(() => typeof window.atlasShowView === 'function');
  await admin.evaluate(() => window.atlasShowView('settings'));
  await admin.locator('#kids-parents-panel > summary').click();
  await admin.waitForFunction(() => /Titel in der Kinderecke/.test(document.getElementById('kids-visible').textContent), null, { timeout: 20000 })
    .catch(() => check('Sichtbare Titel werden gezählt', false));
  await admin.locator('#kids-visible-filter').fill('Frau Holle');
  const row = admin.locator('#kids-visible .kids-parents-row', { hasText: 'Frau Holle' });
  await row.waitFor({ timeout: 10000 }).catch(() => check('„Frau Holle“ in der Suche', false));
  if (SHOTS) await admin.screenshot({ path: path.join(SHOTS, '0.6.113-eltern-sperren.png'), fullPage: false });
  await row.locator('button', { hasText: 'Sperren' }).click();
  const choice = admin.locator('#kids-choices .kids-parents-row', { hasText: 'Frau Holle' });
  await choice.waitFor({ timeout: 10000 }).catch(() => check('Sperre erscheint unter „Deine Entscheidungen“', false));
  check('Sperre als „gesperrt“', (await choice.textContent()).includes('gesperrt'));
  check('gesperrter Titel fehlt in der Kinderecke', !(await kidsTitles()).includes('Frau Holle'));
  await choice.locator('button', { hasText: 'Zurücknehmen' }).click();
  await admin.waitForFunction(() => ![...document.querySelectorAll('#kids-choices .kids-parents-row')].some(r => r.textContent.includes('Frau Holle')), null, { timeout: 10000 })
    .catch(() => check('Zurücknehmen entfernt die Sperre', false));
  check('nach Zurücknehmen wieder da', (await kidsTitles()).includes('Frau Holle'));
  await admin.close();
}

// 0.6.91 (Björn: „kann nicht weiter nach rechts scrollen“): Pfeilknöpfe, „Alle …“-Kachel, ganze Liste
async function scrolling(page, check) {
  // 0.6.93: in „Alle“ stehen Filme und Serien in Gruppen; die große Gruppe „Noch mehr“ muss sich blättern lassen
  const rows = await page.locator('.kids-row h2').allTextContents();
  check('Gruppenreihen Märchen, Zeichentrick, Noch mehr: ' + rows.join(' | '), rows.some(r => r.startsWith('🏰 Märchen')) && rows.some(r => r.startsWith('🎨 Zeichentrick')) && rows.some(r => r.startsWith('⭐ Noch mehr')));
  const fairy = await page.locator('.kids-row', { has: page.locator('h2', { hasText: 'Märchen' }) }).locator('.kids-title').allTextContents();
  check('Märchen-Reihe: ' + fairy.join(' | '), fairy.length === 3 && fairy.includes('Frau Holle') && fairy.includes('Schneewittchen') && fairy.includes('Zz Die Gänsemagd'));
  const strip = page.locator('.kids-row', { has: page.locator('h2', { hasText: 'Noch mehr' }) }).first();
  const box = strip.locator('.kids-strip');
  const before = await box.evaluate(b => ({ left: b.scrollLeft, wide: b.scrollWidth > b.clientWidth + 50 }));
  check('Filmreihe ist breiter als das Fenster', before.wide);
  check('Pfeil „zurück“ am Anfang verborgen', await strip.locator('.kids-arrow-prev').isHidden());
  await strip.locator('.kids-arrow-next').click();
  await page.waitForFunction(() => { const b = [...document.querySelectorAll('.kids-row')].find(r => r.querySelector('h2').textContent.includes('Noch mehr')).querySelector('.kids-strip'); return b.scrollLeft > 300; }, null, { timeout: 5000 })
    .catch(() => check('Pfeil „weiter“ blättert die Reihe', false));
  check('Pfeil „zurück“ erscheint nach dem Blättern', await strip.locator('.kids-arrow-prev').isVisible());
  // 0.6.103: die Aktualisierung (alle 60 s) setzt die gescrollte Reihe nicht an den Anfang zurück –
  // weder bei unveränderten Daten noch wenn neu aufgebaut werden muss
  const leftOf = () => page.evaluate(() => [...document.querySelectorAll('.kids-row')].find(r => r.querySelector('h2').textContent.includes('Noch mehr')).querySelector('.kids-strip').scrollLeft);
  await page.waitForTimeout(600);
  const scrolled = await leftOf();
  await page.evaluate(() => window.__kidsReload());
  await page.waitForTimeout(800);
  check('Aktualisierung ohne Änderung behält die Scrollstelle (' + scrolled + ')', Math.abs(await leftOf() - scrolled) < 5);
  await page.evaluate(async () => { window.__kidsForce = true; await window.__kidsReload(); });
  await page.waitForTimeout(800);
  check('Neuaufbau behält die Scrollstelle', Math.abs(await leftOf() - scrolled) < 5);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.91-kinderecke-blaettern.png') });
  // bis ans Ende: zuletzt kommt die „Alle …“-Kachel
  for (let i = 0; i < 30 && await strip.locator('.kids-arrow-next').isVisible(); i++) { if (!await strip.locator('.kids-arrow-next').click({ timeout: 3000 }).then(() => true, () => false)) break; await page.waitForTimeout(350); }
  const more = strip.locator('.kids-more');
  check('„Alle …“-Kachel am Ende sichtbar', await more.isVisible());
  const total = await page.evaluate(async () => { const token = document.querySelector('meta[name=atlas-token]').content;
    return (await (await fetch('/api/kids', { headers: { 'X-Atlas-Token': token } })).json()).catalog.movies.length; });
  check('Liste nicht nach 240 abgeschnitten: ' + total, total === 268);
  await more.click();
  await page.waitForFunction(() => document.querySelectorAll('.kids-grid .kids-tile').length >= 262, null, { timeout: 10000 })
    .catch(() => check('„Alle …“ zeigt die ganze Gruppe', false));
  const all = await page.locator('.kids-grid .kids-title').allTextContents();
  check('ganze Gruppe „Noch mehr“ mit KiKA-Film und Serie: ' + all.length, all.includes('Ein KiKA-Film') && all.includes('Die Maus') && !all.includes('Frau Holle'));
  // Gruppen-Chip oben (Bild-Symbol) zeigt nur die Gruppe; Filme-Chip zeigt Gruppenreihen
  await page.locator('.kids-chip', { hasText: 'Zeichentrick' }).click();
  const trick = await page.locator('.kids-grid .kids-title').allTextContents();
  check('Chip Zeichentrick: ' + trick.join(' | '), trick.length === 3 && trick.includes('Trickfilm für alle'));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, '0.6.93-kinderecke-gruppe.png') });
  await page.locator('.kids-chip', { hasText: 'Filme' }).click();
  const filmRows = await page.locator('.kids-row h2').allTextContents();
  check('Filme in Gruppen: ' + filmRows.join(' | '), filmRows.some(r => r.includes('Märchen · Filme')) && !filmRows.some(r => r.includes('Serien')));
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
