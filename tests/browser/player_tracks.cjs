/* 0.6.6: Untertitel- und Tonspur-Auswahl im Player (Björn, 14.11.2026: Plex-Titel mit OmU spielte deutsch,
   Untertitel wurden weder gezeigt noch ließen sie sich auswählen).

   Starts MediathekAtlas like click_all.cjs, answers /api/play, /api/play-tracks and /api/subtitle in the
   browser with fixed data (no provider, no video needed) and checks: both choices appear, a chosen
   subtitle becomes a showing text track with its cues, the audio choice restarts the stream through
   MediathekAtlas with audio=a1, cues are shifted by the start position of the restarted stream, the
   choice is remembered and "Aus" switches the subtitles off.

   Usage: node tests/browser/player_tracks.cjs [chromium] [firefox] [webkit]   (default: chromium) */
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const playwright = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const wanted = process.argv.slice(2).length ? process.argv.slice(2) : ['chromium'];
const VTT = 'WEBVTT\n\n00:00:10.000 --> 00:00:15.000\nHallo Untertitel\n\n00:00:16.000 --> 00:00:18.000\nZwei\n';

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}

async function check(name, url) {
  const problems = [];
  const browser = await playwright[name].launch();
  try {
    const page = await browser.newPage();
    page.on('pageerror', e => problems.push('Skriptfehler: ' + e.message));
    const streams = [];
    await page.route('**/api/play?*', r => r.fulfill({ json: { mode: 'direct', origin: 'local', src: '/atlas-test-video.mp4', remux: '/api/stream?job=x', ffmpeg: true, title: 'Testfilm', duration: 60 } }));
    await page.route('**/api/play-tracks?*', r => r.fulfill({ json: { audio: [{ id: 'a0', label: 'Deutsch', lang: 'de' }, { id: 'a1', label: 'Englisch', lang: 'en' }], subtitles: [{ id: 's0', label: 'Deutsch', lang: 'de' }] } }));
    await page.route('**/api/subtitle?*', r => r.fulfill({ contentType: 'text/vtt', body: VTT }));
    await page.route('**/api/stream?*', r => { streams.push(r.request().url()); r.fulfill({ contentType: 'video/mp4', body: '' }); });
    await page.route('**/atlas-test-video.mp4', r => r.fulfill({ contentType: 'video/mp4', body: '' }));
    await page.goto(url);
    await page.evaluate(() => window.AtlasDisplay && window.AtlasDisplay.ready);
    await page.waitForTimeout(800);
    const state = () => page.evaluate(() => {
      const t = [...document.getElementById('player-video').textTracks].find(x => x.label === 'MediathekAtlas');
      return { subs: !document.getElementById('player-subs-box').hidden, audio: !document.getElementById('player-audio-box').hidden,
        mode: t ? t.mode : 'none', cues: t && t.cues ? [...t.cues].map(c => [Math.round(c.startTime * 10) / 10, c.text]) : [] };
    });
    const expect = (label, ok, got) => { if (!ok) problems.push(label + ': ' + JSON.stringify(got)); };
    await page.evaluate(() => { localStorage.removeItem('atlas-play-subs'); localStorage.removeItem('atlas-play-audio'); window.playRef({ job: 'x' }, 'Testfilm', 'job:x', 0); });
    await page.waitForTimeout(1200);
    let s = await state();
    expect('Auswahl Ton/Untertitel sichtbar', s.subs && s.audio, s);
    expect('Untertitel zu Beginn aus', s.mode !== 'showing', s);
    await page.selectOption('#player-subs', 's0');
    await page.waitForTimeout(800);
    s = await state();
    expect('Untertitel werden gezeigt', s.mode === 'showing' && s.cues.length === 2 && s.cues[0][0] === 10 && s.cues[0][1] === 'Hallo Untertitel', s);
    await page.evaluate(() => { const v = document.getElementById('player-video'); Object.defineProperty(v, 'currentTime', { configurable: true, get: () => 4, set: () => {} }); });
    await page.selectOption('#player-audio', 'a1');
    await page.waitForTimeout(800);
    s = await state();
    expect('Tonspur startet den Stream mit audio=a1', streams.some(u => /audio=a1/.test(u) && /[?&]t=4\.0/.test(u)), streams);
    expect('Untertitel um die Startposition verschoben', s.cues[0] && s.cues[0][0] === 6, s);
    const prefs = await page.evaluate(() => [localStorage.getItem('atlas-play-subs'), localStorage.getItem('atlas-play-audio')]);
    expect('Wahl gemerkt', prefs[0] === 'de' && prefs[1] === 'en', prefs);
    await page.evaluate(() => { delete document.getElementById('player-video').currentTime; window.playRef({ job: 'x' }, 'Testfilm', 'job:x', 0); });
    await page.waitForTimeout(1500);
    s = await state();
    expect('Gemerkte Untertitel beim nächsten Öffnen an', s.mode === 'showing' && s.cues.length === 2, s);
    await page.selectOption('#player-subs', '');
    await page.waitForTimeout(500);
    s = await state();
    expect('„Aus“ schaltet ab', s.mode !== 'showing', s);
  } finally {
    await browser.close();
  }
  return problems;
}

(async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-player-'));
  const port = await freePort();
  const server = spawn(process.env.PYTHON || 'python3', ['server.py', '--no-browser'], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, MEDIATHEKATLAS_HOME: path.join(home, 'data'), MEDIATHEKATLAS_DOWNLOAD_DIR: path.join(home, 'downloads'),
           MEDIATHEKATLAS_PORT: String(port), MEDIATHEKATLAS_DISABLE_BACKGROUND: '1' } });
  let failed = false;
  try {
    const url = 'http://127.0.0.1:' + port + '/';
    for (let i = 0; i < 120; i++) { try { if ((await fetch(url)).ok) break; } catch (e) { /* not up yet */ } await new Promise(r => setTimeout(r, 250)); }
    for (const name of wanted) {
      const problems = await check(name, url);
      console.log(name + ': ' + (problems.length ? problems.length + ' Problem(e)\n  ' + problems.join('\n  ') : 'Untertitel und Tonspur in Ordnung'));
      if (problems.length) failed = true;
    }
  } finally {
    server.kill();
    fs.rmSync(home, { recursive: true, force: true });
  }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
