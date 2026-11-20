/* MediathekAtlas Videostart (Chrome-Erweiterung, Manifest V3), seit 0.5.91.
 *
 * Wird nur aktiv, wenn MediathekAtlas den Anbieter-Link geöffnet hat (Kennung #mediathekatlas-autostart).
 * Dann, für höchstens 90 Sekunden in diesem Tab:
 *   - klickt sie den Abspielknopf der Seite (z. B. „Kostenlos ansehen“, „Abspielen“, Play-Symbol),
 *   - bestätigt sie einen Hinweis, der „HDCP“ erwähnt (Rakuten TV), mit „Weiter“/„OK“ o. ä.,
 *   - startet sie ein bereits geladenes, pausiertes Video; lehnt Chrome Autoplay mit Ton ab, startet es
 *     stumm und schaltet den Ton beim ersten Klick in die Seite ein.
 *   - 0.6.46 (Björn, 20.11.2026: „Videos bei Anbietern gleich im Vollbild starten“): läuft das Video, stellt
 *     sie das Chrome-Fenster auf Vollbild (background.js, chrome.windows) und lässt den Player das Fenster
 *     füllen. Echtes Element-Vollbild erlaubt Chrome nur nach einer Eingabe des Nutzers: Der erste Klick
 *     oder Tastendruck schaltet deshalb zusätzlich das Vollbild des Players ein. Esc beendet alles wieder.
 * Sie klickt nie auf Kaufen, Leihen, Abo, Anmelden, Cookie-Zustimmung oder Links zu anderen Seiten.
 * Kopierschutz wird nicht umgangen: das Video läuft im Player des Anbieters. Es werden keine Daten gesendet.
 */
(() => {
  'use strict';
  const MARK = 'mediathekatlas-autostart';
  const FLAG = 'mediathekatlas.autostart';
  const WINDOW_MS = 90000, TICK_MS = 700, PLAY_CLICKS = 4;

  let since = 0;
  try {
    if (location.hash.replace(/^#/, '') === MARK) {
      sessionStorage.setItem(FLAG, String(Date.now()));
      // Kennung entfernen, damit die Seite (Router) sie nie zu sehen bekommt.
      history.replaceState(history.state, '', location.pathname + location.search);
    }
    since = Number(sessionStorage.getItem(FLAG) || 0);
  } catch (e) { return; }
  if (!since || Date.now() - since > WINDOW_MS) return;

  const PLAY_WORDS = ['kostenlos ansehen', 'gratis ansehen', 'jetzt ansehen', 'jetzt abspielen', 'film ansehen', 'folge ansehen',
    'jetzt schauen', 'weiterschauen', 'fortsetzen', 'abspielen', 'wiedergabe starten', 'wiedergabe', 'ansehen', 'anschauen', 'play', 'watch now', 'start watching'];
  const NEVER = ['kauf', 'leih', 'miete', 'abo', 'abonn', 'plus', 'premium', 'anmeld', 'registr', 'login', 'log in', 'konto', 'trailer',
    'teilen', 'merkliste', 'merken', 'cookie', 'zustimm', 'akzeptier', 'einstellung', 'untertitel', 'sprache', 'mute', 'lautst',
    'pause', 'zurück', 'schließ', 'close', 'abbrech', 'cancel', 'bewert', 'herunterladen', 'download', 'werbung überspringen'];
  const CONTINUE_WORDS = ['weiter', 'fortfahren', 'trotzdem', 'ok', 'okay', 'verstanden', 'alles klar', 'ansehen', 'abspielen',
    'continue', 'got it', 'accept', 'sd'];
  const STOP_WORDS = ['abbrech', 'cancel', 'schließ', 'close', 'mehr erfahren', 'hilfe', 'learn more'];

  const settings = {autoplay: true, hdcp: true, fullscreen: true, fill: true};
  let ready = false, done = false, playClicks = 0, lastPlayClick = 0, triedVideo = new WeakSet(), clicked = new WeakSet(), timer = 0, observer = null;
  let overlayClicks = 0, lastOverlay = 0, lastVideoTry = 0;
  const begun = Date.now();
  // 0.5.93: Play-Knöpfe ohne Beschriftung (Björn, 13.11.2026: pinker Knopf bei TOGGO, Mini-Player bei JustWatch).
  // Klassen der verbreiteten Web-Player und Klassennamen mit „play“ als eigenem Wortteil.
  const OVERLAY_SELECTORS = ['.vjs-big-play-button', '.jw-display-icon-display', '.jw-icon-display', '.bmpui-ui-hugeplaybacktogglebutton',
    '.shaka-play-button', '.theo-big-play-button', '.plyr__control--overlaid', '.mejs__overlay-play', '.fp-play', '.ytp-large-play-button',
    '[data-testid*="play" i]', '[class*="play" i]', '[id*="play" i]', '[aria-label*="play" i]', '[aria-label*="abspielen" i]', '[aria-label*="wiedergabe" i]'];
  const PLAYISH = /(^|[^a-z])(big-?|huge-?|large-?|center-?)?play(-?(btn|button|icon|overlay|toggle|circle|cta))?([^a-z]|$)|playbutton|play_button|playbtn|big-play/;
  const PLAYER_BOX = 'video, [class*="player" i], [id*="player" i], [data-testid*="player" i], [class*="video-container" i], [class*="videoplayer" i]';

  const label = el => [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('data-testid'), el.textContent]
    .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 160);
  // Kurze Wörter (play, ok, sd) nur als ganzes Wort; Ausschlusswörter (NEVER, STOP_WORDS) immer als Wortteil.
  const has = (text, words) => words.some(w => w.length <= 4 ? new RegExp('(^|[^a-zäöüß])' + w + '($|[^a-zäöüß])').test(text) : text.includes(w));
  const hasPart = (text, words) => words.some(w => text.includes(w));
  function visible(el) {
    if (!el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 12 || r.height < 12 || r.bottom < 0 || r.right < 0 || r.top > innerHeight * 1.5) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05 && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
  }
  function sameSite(el) {
    const a = el.closest('a[href]');
    if (!a) return true;
    try { return new URL(a.href, location.href).hostname === location.hostname; } catch (e) { return false; }
  }
  const clickables = root => Array.from(root.querySelectorAll('button, a[href], [role="button"], [aria-label][tabindex]'));
  const classOf = el => String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').toLowerCase();

  // Klick wie mit der Maus: Zeiger- und Maus-Ereignisse in der Mitte des Elements, dann click.
  // Manche Player hören auf pointerdown/mousedown statt auf click; SVG-Elemente haben kein .click().
  function press(el) {
    const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const o = {bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, button: 0, buttons: 1, view: window};
    for (const type of ['pointerover', 'pointerenter', 'mouseover', 'pointerdown', 'mousedown', 'pointerup', 'mouseup']) {
      try { el.dispatchEvent(type.startsWith('pointer') ? new PointerEvent(type, {...o, pointerType: 'mouse', isPrimary: true}) : new MouseEvent(type, o)); }
      catch (e) { /* ältere Engines */ }
    }
    if (typeof el.click === 'function') el.click(); else el.dispatchEvent(new MouseEvent('click', o));
  }

  function toast(text, ms) {
    try {
      let box = document.getElementById('mediathekatlas-videostart');
      if (!box) {
        box = document.createElement('div');
        box.id = 'mediathekatlas-videostart';
        box.style.cssText = 'position:fixed;z-index:2147483647;left:16px;bottom:16px;max-width:360px;padding:9px 13px;border-radius:9px;' +
          'background:rgba(20,24,32,.92);color:#fff;font:13px/1.35 system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.35);pointer-events:none';
        (document.body || document.documentElement).append(box);
      }
      box.textContent = 'MediathekAtlas: ' + text;
      clearTimeout(box._t); box._t = setTimeout(() => box.remove(), ms || 4000);
    } catch (e) { /* Hinweis ist nur Komfort */ }
  }

  function playing() {
    return Array.from(document.querySelectorAll('video')).some(v => !v.paused && !v.ended && v.readyState > 2 && v.currentTime > 0.2);
  }

  // HDCP-Hinweis (Rakuten TV): nur Dialoge/Overlays, deren Text „HDCP“ enthält.
  function confirmHdcp() {
    if (!settings.hdcp) return false;
    const boxes = document.querySelectorAll('[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog[open], [class*="modal" i], [class*="dialog" i], [class*="overlay" i], [class*="popup" i]');
    for (const box of boxes) {
      if (clicked.has(box) || !/hdcp/i.test(box.textContent || '') || !visible(box)) continue;
      const options = clickables(box).filter(b => visible(b) && sameSite(b));
      const pick = options.find(b => { const t = label(b); return t && has(t, CONTINUE_WORDS) && !hasPart(t, STOP_WORDS); });
      if (pick) {
        clicked.add(box); pick.click();
        toast('HDCP-Hinweis bestätigt.');
        return true;
      }
    }
    return false;
  }

  function clickPlay() {
    if (!settings.autoplay || playClicks >= PLAY_CLICKS || Date.now() - lastPlayClick < 2500) return false;
    let best = null, score = 0;
    for (const el of clickables(document)) {
      if (clicked.has(el) || !visible(el) || !sameSite(el)) continue;
      const t = label(el), cls = classOf(el);
      if (hasPart(t, NEVER)) continue;
      const i = PLAY_WORDS.findIndex(w => has(t, [w]));
      let s = i >= 0 ? 100 - i : 0;
      if (!s && /(^|[\s_-])play(-?button|-?icon)?($|[\s_-])/.test(cls)) s = 40;
      if (!s) continue;
      const r = el.getBoundingClientRect();
      s += Math.min(20, (r.width * r.height) / 4000);          // große Knöpfe zuerst
      if (s > score) { best = el; score = s; }
    }
    if (!best) return false;
    clicked.add(best); playClicks++; lastPlayClick = Date.now();
    press(best);
    toast('Video wird gestartet …');
    return true;
  }

  function startVideo() {
    if (!settings.autoplay) return;
    for (const v of document.querySelectorAll('video')) {
      // 0.5.93: auch Videos, die erst beim Abspielen laden (preload="none", readyState 0)
      if (triedVideo.has(v) || !v.paused || v.ended || !(v.currentSrc || v.src || v.querySelector('source') || v.srcObject) || !visible(v)) continue;
      triedVideo.add(v); lastVideoTry = Date.now();
      v.play().catch(() => {
        v.muted = true;
        v.play().then(() => {
          toast('Gestartet ohne Ton (Chrome-Regel). Einmal in die Seite klicken schaltet den Ton ein.', 7000);
          document.addEventListener('pointerdown', () => { v.muted = false; }, {once: true, capture: true});
        }).catch(() => {});
      });
    }
  }

  // 0.5.93: Play-Knopf ohne Beschriftung über dem Player (z. B. pinker Kreis bei TOGGO, Mini-Player bei JustWatch).
  // 1. bekannte Player-Klassen bzw. Elemente mit „play“ in Klasse/ID/Test-ID; 2. sonst die Mitte des größten Players.
  function players() {
    return Array.from(document.querySelectorAll(PLAYER_BOX)).filter(el => {
      if (!visible(el)) return false;
      const r = el.getBoundingClientRect();
      return r.width >= 200 && r.height >= 110 && r.width / r.height > 0.9 && r.width / r.height < 3;
    }).sort((a, b) => { const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return rb.width * rb.height - ra.width * ra.height; });
  }
  function inside(el, box) {
    const r = el.getBoundingClientRect(), b = box.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    return x >= b.left && x <= b.right && y >= b.top && y <= b.bottom;
  }
  function clickOverlay() {
    if (!settings.autoplay || overlayClicks >= 3 || Date.now() - begun < 1500 || Date.now() - lastOverlay < 3000 || Date.now() - lastPlayClick < 2500 || Date.now() - lastVideoTry < 2500) return false;
    const boxes = players();
    let pick = null;
    for (const el of document.querySelectorAll(OVERLAY_SELECTORS.join(','))) {
      if (clicked.has(el) || !visible(el) || !sameSite(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 260 || r.height > 260) continue;                       // Knopf, nicht der ganze Player
      const t = label(el).slice(0, 60);
      if (hasPart(t, NEVER) || /playlist|player-?(bar|controls?)/.test(classOf(el))) continue;
      const id = classOf(el) + ' ' + String(el.id || '').toLowerCase() + ' ' + String(el.getAttribute('data-testid') || '').toLowerCase()
        + ' ' + String(el.getAttribute('aria-label') || '').toLowerCase();
      if (!PLAYISH.test(id) && !/abspielen|wiedergabe/.test(id) && !el.matches(OVERLAY_SELECTORS.slice(0, 10).join(','))) continue;
      if (boxes.length && !boxes.some(b => inside(el, b))) continue;       // nur Knöpfe auf einem Player
      pick = el; break;
    }
    if (!pick && boxes.length && Date.now() - begun > 3000) {
      const b = boxes[0].getBoundingClientRect();
      const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      // nur eigene Beschriftung prüfen (aria-label/title), nicht den ganzen Text des Players
      const own = [hit && hit.getAttribute('aria-label'), hit && hit.getAttribute('title')].filter(Boolean).join(' ').toLowerCase();
      if (hit && !clicked.has(hit) && sameSite(hit) && !hasPart(own, NEVER) && hit.tagName !== 'A' && hit.tagName !== 'IFRAME') pick = hit;
    }
    if (!pick) return false;
    clicked.add(pick); overlayClicks++; lastOverlay = Date.now();
    press(pick);
    toast('Video wird gestartet …');
    return true;
  }

  // ------------------------------------------------------------ 0.6.46: Vollbild
  const FILL = 'mediathekatlas-fill', FILL_PATH = 'mediathekatlas-fill-path', FILL_ROOT = 'mediathekatlas-fill-root';
  let fullOn = false, filled = null;
  const tell = type => { try { chrome.runtime.sendMessage({type}, () => void chrome.runtime.lastError); } catch (e) { /* Erweiterung neu geladen */ } };
  function fillStyle() {
    if (document.getElementById(FILL + '-style')) return;
    const st = document.createElement('style'); st.id = FILL + '-style';
    st.textContent = 'html.' + FILL_ROOT + ',html.' + FILL_ROOT + ' body{overflow:hidden!important}' +
      '.' + FILL_PATH + '{transform:none!important;filter:none!important;perspective:none!important;contain:none!important;' +
      'backdrop-filter:none!important;will-change:auto!important;z-index:2147483646!important}' +
      '.' + FILL + '{position:fixed!important;inset:0!important;left:0!important;top:0!important;width:100vw!important;height:100vh!important;' +
      'max-width:none!important;max-height:none!important;min-width:0!important;min-height:0!important;margin:0!important;padding:0!important;' +
      'border:0!important;border-radius:0!important;z-index:2147483646!important;background:#000!important}' +
      'video.' + FILL + ',.' + FILL + ' video{width:100%!important;height:100%!important;max-height:none!important;object-fit:contain!important}';
    (document.head || document.documentElement).append(st);
  }
  // Der Kasten des Players: der höchste Vorfahre, der noch etwa so groß ist wie das Video (mit seinen Bedienelementen).
  function playerBox(v) {
    const base = v.getBoundingClientRect(), area = Math.max(1, base.width * base.height);
    let box = v;
    for (let el = v.parentElement; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      const r = el.getBoundingClientRect();
      if (r.width * r.height > area * 1.4 || r.width < base.width * 0.95) break;
      box = el;
    }
    return box;
  }
  function fill(el) {
    if (!settings.fill || filled || !el) return;
    fillStyle(); filled = el;
    el.classList.add(FILL);
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) p.classList.add(FILL_PATH);
    document.documentElement.classList.add(FILL_ROOT);
    if (window !== window.top) { try { window.parent.postMessage({mediathekatlas: 'fill'}, '*'); } catch (e) { /* egal */ } }
  }
  function unfill() {
    filled = null;
    for (const cls of [FILL, FILL_PATH, FILL_ROOT]) for (const el of document.querySelectorAll('.' + cls)) el.classList.remove(cls);
    for (const f of document.querySelectorAll('iframe')) { try { f.contentWindow.postMessage({mediathekatlas: 'unfill'}, '*'); } catch (e) { /* egal */ } }
  }
  function leaveFull(viaMessage) {
    if (!fullOn && !filled) return;
    fullOn = false; unfill(); tell('fullscreen-exit');
    if (document.fullscreenElement) { try { document.exitFullscreen().catch(() => {}); } catch (e) { /* egal */ } }
    if (!viaMessage && window !== window.top) { try { window.top.postMessage({mediathekatlas: 'unfill'}, '*'); } catch (e) { /* egal */ } }
  }
  // Echte Eingabe des Nutzers: erst jetzt erlaubt Chrome das Vollbild des Players selbst (ohne Leisten).
  function onGesture(e) {
    if (!fullOn || !e.isTrusted) return;
    if (e.type === 'keydown') {
      if (e.key === 'Escape') { if (!document.fullscreenElement) leaveFull(); return; }
      if (e.metaKey || e.ctrlKey || e.altKey || e.key === 'Tab') return;
    }
    if (document.fullscreenElement || !filled || !filled.requestFullscreen) return;
    try {
      const p = filled.requestFullscreen({navigationUI: 'hide'});
      if (p && p.catch) p.catch(() => {});
      // Der Klick, der nur das Vollbild einschaltet, soll das Video nicht anhalten (Knöpfe des Players bleiben bedienbar).
      if (e.type === 'pointerdown' && !e.target.closest('button, a, input, select, [role="button"], [role="slider"]')) {
        const swallow = ev => { ev.stopImmediatePropagation(); ev.preventDefault(); };
        for (const t of ['pointerup', 'mousedown', 'mouseup', 'click']) window.addEventListener(t, swallow, {capture: true, once: true});
        setTimeout(() => { for (const t of ['pointerup', 'mousedown', 'mouseup', 'click']) window.removeEventListener(t, swallow, {capture: true}); }, 600);
        e.stopImmediatePropagation();
      }
    } catch (err) { /* ohne Vollbild weiter */ }
  }
  function enterFull() {
    if (!settings.fullscreen || fullOn) return;
    const v = Array.from(document.querySelectorAll('video')).find(x => !x.paused && !x.ended && visible(x));
    if (!v) return;
    fullOn = true;
    tell('fullscreen');
    fill(playerBox(v));
    window.addEventListener('pointerdown', onGesture, true);
    window.addEventListener('keydown', onGesture, true);
    toast('Vollbild. Ein Klick oder Tastendruck blendet auch die Chrome-Leisten aus, Esc beendet.', 6000);
  }
  // Player in einem eingebetteten Rahmen: die Seite darüber lässt den Rahmen das Fenster füllen.
  window.addEventListener('message', e => {
    const kind = e.data && e.data.mediathekatlas;
    if (kind === 'fill' && settings.fill && settings.fullscreen) {
      const frame = Array.from(document.querySelectorAll('iframe')).find(f => f.contentWindow === e.source);
      if (frame) { fullOn = true; fill(frame); window.addEventListener('keydown', onGesture, true); }
    } else if (kind === 'unfill') { if (fullOn || filled) leaveFull(true); }
  });

  function finish(text) {
    if (done) return;
    done = true;
    try { sessionStorage.removeItem(FLAG); } catch (e) { /* egal */ }
    clearInterval(timer); if (observer) observer.disconnect();
    if (text) toast(text, 2500);
  }

  function step() {
    if (done || !ready) return;
    if (Date.now() - since > WINDOW_MS) return finish('');
    if (playing()) { finish(settings.fullscreen ? '' : 'Video läuft.'); enterFull(); return; }
    if (confirmHdcp()) return;
    if (clickPlay()) return;
    startVideo();
    clickOverlay();
  }

  function begin() {
    let pending = 0;
    observer = new MutationObserver(() => { if (!pending) pending = setTimeout(() => { pending = 0; step(); }, 150); });
    observer.observe(document.documentElement, {childList: true, subtree: true});
    timer = setInterval(step, TICK_MS);
    step();
  }

  try {
    chrome.storage.sync.get(settings, values => {
      Object.assign(settings, values || {});
      ready = true;
      if (!settings.autoplay && !settings.hdcp) return finish('');
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', begin, {once: true}); else begin();
    });
  } catch (e) {
    ready = true;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', begin, {once: true}); else begin();
  }
})();
