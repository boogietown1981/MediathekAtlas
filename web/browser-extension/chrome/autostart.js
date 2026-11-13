/* MediathekAtlas Videostart (Chrome-Erweiterung, Manifest V3), seit 0.5.91.
 *
 * Wird nur aktiv, wenn MediathekAtlas den Anbieter-Link geöffnet hat (Kennung #mediathekatlas-autostart).
 * Dann, für höchstens 90 Sekunden in diesem Tab:
 *   - klickt sie den Abspielknopf der Seite (z. B. „Kostenlos ansehen“, „Abspielen“, Play-Symbol),
 *   - bestätigt sie einen Hinweis, der „HDCP“ erwähnt (Rakuten TV), mit „Weiter“/„OK“ o. ä.,
 *   - startet sie ein bereits geladenes, pausiertes Video; lehnt Chrome Autoplay mit Ton ab, startet es
 *     stumm und schaltet den Ton beim ersten Klick in die Seite ein.
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
    'jetzt schauen', 'weiterschauen', 'fortsetzen', 'abspielen', 'wiedergabe starten', 'wiedergabe', 'ansehen', 'play', 'watch now'];
  const NEVER = ['kauf', 'leih', 'miete', 'abo', 'abonn', 'plus', 'premium', 'anmeld', 'registr', 'login', 'log in', 'konto', 'trailer',
    'teilen', 'merkliste', 'merken', 'cookie', 'zustimm', 'akzeptier', 'einstellung', 'untertitel', 'sprache', 'mute', 'lautst',
    'pause', 'zurück', 'schließ', 'close', 'abbrech', 'cancel', 'bewert', 'herunterladen', 'download', 'werbung überspringen'];
  const CONTINUE_WORDS = ['weiter', 'fortfahren', 'trotzdem', 'ok', 'okay', 'verstanden', 'alles klar', 'ansehen', 'abspielen',
    'continue', 'got it', 'accept', 'sd'];
  const STOP_WORDS = ['abbrech', 'cancel', 'schließ', 'close', 'mehr erfahren', 'hilfe', 'learn more'];

  const settings = {autoplay: true, hdcp: true};
  let ready = false, done = false, playClicks = 0, lastPlayClick = 0, triedVideo = new WeakSet(), clicked = new WeakSet(), timer = 0, observer = null;

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
      const t = label(el), cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').toLowerCase();
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
    best.click();
    toast('Video wird gestartet …');
    return true;
  }

  function startVideo() {
    if (!settings.autoplay) return;
    for (const v of document.querySelectorAll('video')) {
      if (triedVideo.has(v) || !v.paused || v.readyState < 2 || !visible(v)) continue;
      triedVideo.add(v);
      v.play().catch(() => {
        v.muted = true;
        v.play().then(() => {
          toast('Gestartet ohne Ton (Chrome-Regel). Einmal in die Seite klicken schaltet den Ton ein.', 7000);
          document.addEventListener('pointerdown', () => { v.muted = false; }, {once: true, capture: true});
        }).catch(() => {});
      });
    }
  }

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
    if (playing()) return finish('Video läuft.');
    if (confirmHdcp()) return;
    if (clickPlay()) return;
    startVideo();
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
