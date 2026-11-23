/* 0.6.95 (Björn 22.11.2026: „Checker Tobi“-Shorts im Hochformat zeigten nur das obere Drittel): Hochformat-
   und Querformat-Videos müssen in jedem Abspielort vollständig im Bild liegen.
   Baut die Abspielflächen mit den echten Stilen nach (web/kids.css, web/style.css), lädt ein kurzes
   Hochformat-Testvideo (ffmpeg) und prüft das Rechteck des Videos gegen das Fenster:
   Kinderecke, Player-Dialog, Ansehen-Modus, Player im Vollbild.
   Aufruf: node tests/browser/portrait_video.cjs [Ordner für Bildschirmfotos] */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const SHOTS = process.argv[2] || '';

const PAGES = {
  kids: `<link rel="stylesheet" href="/kids.css"><div id="kids-stage" class="kids-stage"><video id="v" playsinline controls muted></video>
         <button class="kids-close">✕</button></div>`,
  player: `<link rel="stylesheet" href="/style.css"><dialog class="player" id="d"><div id="player-stage"><video id="player-video" controls muted></video><div id="player-bar">Leiste</div></div></dialog>
           <script>document.getElementById('d').showModal()</script>`,
  watch: `<link rel="stylesheet" href="/style.css"><dialog class="player" id="d"><div id="player-stage"><video id="player-video" controls muted></video><div id="player-bar">Leiste</div></div></dialog>
          <script>document.documentElement.dataset.mode='watch';document.getElementById('d').showModal()</script>`,
};

(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ma-portrait-'));
  const clips = {};
  for (const [name, size] of [['hoch', '360x640'], ['quer', '640x360']]) {
    clips[name] = path.join(tmp, name + '.webm');
    execFileSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', `testsrc=size=${size}:rate=10:duration=2`, '-c:v', 'libvpx', '-b:v', '100k', clips[name]]);
  }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname.endsWith('.webm')) { res.writeHead(200, { 'Content-Type': 'video/webm' }); return res.end(fs.readFileSync(clips[path.basename(url.pathname, '.webm')])); }
    if (url.pathname.endsWith('.css')) { res.writeHead(200, { 'Content-Type': 'text/css' }); return res.end(fs.readFileSync(path.join(ROOT, 'web', path.basename(url.pathname)))); }
    const kind = url.pathname.slice(1);
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<!doctype html><html><head><meta charset="utf-8"></head><body>' + PAGES[kind] + '</body></html>');
  }).listen(0);
  const base = 'http://127.0.0.1:' + server.address().port + '/';
  const browser = await chromium.launch();
  const problems = [];
  try {
    for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      for (const kind of Object.keys(PAGES)) {
        for (const clip of ['hoch', 'quer']) {
          for (const full of [false, true]) {
            if (full && kind === 'watch') continue;
            const page = await browser.newPage({ viewport });
            await page.goto(base + kind);
            await page.evaluate(src => { const v = document.querySelector("video"); v.src = src; }, base + clip + '.webm');
            await page.waitForFunction(() => document.querySelector("video").readyState >= 1, null, { timeout: 10000 });
            if (full) {
              const target = kind === 'kids' ? '#kids-stage' : '#player-stage';
              await page.evaluate(sel => document.querySelector(sel).requestFullscreen(), target);
              await page.waitForFunction(() => !!document.fullscreenElement, null, { timeout: 5000 });
            }
            await page.waitForTimeout(150);
            const r = await page.evaluate(() => { const b = document.querySelector("video").getBoundingClientRect();
              return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: innerWidth, h: innerHeight }; });
            const label = `${kind}/${clip}/${viewport.width}x${viewport.height}${full ? '/vollbild' : ''}`;
            if (r.top < -1 || r.bottom > r.h + 1 || r.left < -1 || r.right > r.w + 1) problems.push(label + ': Video ragt aus dem Fenster ' + JSON.stringify(r));
            if (r.bottom - r.top < 100) problems.push(label + ': Video zu klein ' + JSON.stringify(r));
            if (SHOTS && clip === 'hoch' && viewport.width === 1280 && !full) await page.screenshot({ path: path.join(SHOTS, `0.6.95-hochformat-${kind}.png`) });
            await page.close();
          }
        }
      }
    }
  } catch (e) {
    problems.push(String(e && e.stack || e));
  } finally {
    await browser.close();
    server.close();
  }
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
  console.log('portrait_video ok');
})();
