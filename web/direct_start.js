/* 0.5.91: Videostart bei Anbietern mit Kopierschutz abkürzen (Björn, 13.11.2026).
 *
 * Titel von Rakuten TV, Joyn, TOGGO, JustWatch TV und Crunchyroll laufen wegen Kopierschutz (DRM) nur beim Anbieter.
 * 1. Direkter Player-Link: wo die Player-Adresse des Anbieters bekannt ist, öffnet der Link gleich den
 *    Player statt der Detailseite (Joyn: /play/filme/…, /play/serien/…/…, /play/compilation/…/… laut
 *    Routentabelle der Joyn-Seite im HAR vom 12.11.2026). Sonst bleibt die bisherige Seite.
 * 2. Kennung "#mediathekatlas-autostart": nur Links mit dieser Kennung startet die optionale
 *    Chrome-Erweiterung (web/browser-extension/chrome) automatisch. Die Kennung bleibt im Browser
 *    (Fragment), der Anbieter sieht sie nicht. Normales Surfen auf den Seiten bleibt unberührt.
 * Der Kopierschutz wird nicht umgangen; das Video läuft weiter im Player des Anbieters.
 * 0.6.38: Einrichtungsassistent für die Erweiterung (Ordner zeigen statt ZIP entpacken, automatische Erkennung,
 * Selbst-Update nach einer neuen App-Version).
 */
(function () {
  'use strict';
  const MARK = 'mediathekatlas-autostart';
  const KEY = 'atlas.directStart';
  // Anbieter, deren Titel nur beim Anbieter laufen, und deren Hosts (gleiche Liste wie manifest.json).
  const HOSTS = {joyn: ['www.joyn.de'], rakuten: ['www.rakuten.tv'], toggo: ['www.toggo.de'], justwatch: ['www.justwatch.com'], crunchyroll: ['www.crunchyroll.com'], rtlplus: ['plus.rtl.de']};
  const SAFE = /^https:\/\/[a-z0-9.-]+\/[^\s<>'"]*$/i;

  function enabled() {
    try { return localStorage.getItem(KEY) !== 'off'; } catch (e) { return true; }
  }
  function setEnabled(on) {
    try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (e) { /* privater Modus: bleibt an */ }
  }

  // Joyn: Detailseite -> Player (Routen PLAYER_MOVIE, PLAYER_SERIES, PLAYER_COMPILATION der Joyn-Seite).
  // Eine Serie selbst (/serien/<serie>) hat keinen Player und bleibt die Serienseite.
  function joyn(path) {
    const m = /^\/(filme)\/([a-z0-9-]{1,160})\/?$/.exec(path) || /^\/(serien|compilation)\/([a-z0-9-]{1,160}\/[a-z0-9-]{1,160})\/?$/.exec(path);
    return m ? '/play/' + m[1] + '/' + m[2] : path;
  }

  function href(source, url) {
    if (typeof url !== 'string' || !SAFE.test(url)) return url;
    const hosts = HOSTS[source];
    if (!hosts || !enabled()) return url;
    let u;
    try { u = new URL(url); } catch (e) { return url; }
    if (u.protocol !== 'https:' || !hosts.includes(u.hostname)) return url;
    if (source === 'joyn') u.pathname = joyn(u.pathname);
    u.hash = MARK;
    return u.toString();
  }

  // 0.6.38: Installationsstand der Erweiterung. Ab 0.6.38 meldet sie sich auf dieser Seite (atlas_bridge.js:
  // Attribut data-atlas-videostart am <html>-Element). Ältere Fassungen sind nicht erkennbar.
  function installed() {
    try { return document.documentElement.dataset.atlasVideostart || ''; } catch (e) { return ''; }
  }
  function newer(a, b) {   // true, wenn Version a neuer als b ist (nur Zahlen, wie Chrome)
    const x = String(a || '').split('.').map(Number), y = String(b || '').split('.').map(Number);
    for (let i = 0; i < Math.max(x.length, y.length); i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); }
    return false;
  }
  function chromium() {
    const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
    if (brands.some(b => /chrom|edge|brave|opera/i.test(b.brand))) return true;
    return /Chrome\/|Chromium\/|Edg\//.test(navigator.userAgent || '') && !/Firefox\//.test(navigator.userAgent || '');
  }
  // Was der Assistent anzeigt: ok | update | old | missing | unsupported | checking
  function extensionState(info, have, browserOk, asked) {
    if (!info) return 'checking';
    if (have && !newer(info.version, have)) return 'ok';
    if (have) return asked ? 'old' : 'update';
    return browserOk ? 'missing' : 'unsupported';
  }

  function token() { return document.querySelector('meta[name="atlas-token"]')?.content || ''; }

  // Einstellungen → „Videostart bei Anbietern“: Schalter, Einrichtungsassistent und ZIP für andere Rechner.
  function panel() {
    const box = document.getElementById('direct-start-panel');
    if (!box || box.dataset.ready) return;
    box.dataset.ready = '1';
    const $ = id => document.getElementById(id);
    const toggle = $('direct-start-toggle'), status = $('direct-start-status');
    const get = $('direct-start-download'), state = $('direct-start-ext-state'), steps = $('direct-start-wizard');
    if (toggle) {
      toggle.checked = enabled();
      toggle.onchange = () => { setEnabled(toggle.checked); if (status) status.textContent = toggle.checked ? 'Direkter Start ist an.' : 'Direkter Start ist aus: Links öffnen wieder die Detailseite des Anbieters.'; };
    }
    let info = null, asked = false, waitTimer = 0;
    const say = text => { if (status) status.textContent = text; };

    async function copy(text, label) {
      try { await navigator.clipboard.writeText(text); say(label + ' kopiert.'); }
      catch (e) { say(label + ': ' + text + ' (bitte von Hand kopieren)'); }
    }

    function render() {
      if (!state) return;
      const have = installed(), mode = extensionState(info, have, chromium(), asked);
      state.dataset.state = mode;
      state.textContent = {
        checking: 'Chrome-Erweiterung: wird geprüft …',
        ok: '✓ Chrome-Erweiterung ist installiert und aktuell (Version ' + have + ').',
        update: 'Chrome-Erweiterung wird auf Version ' + (info && info.version) + ' aktualisiert …',
        old: 'Chrome-Erweiterung ist veraltet (Version ' + have + ', aktuell ' + (info && info.version) + '). Auf chrome://extensions beim Eintrag „MediathekAtlas Videostart“ auf ↻ klicken – oder sie stammt aus einem anderen Ordner: dann entfernen und wie unten neu laden.',
        missing: 'Chrome-Erweiterung ist noch nicht installiert. Einmalig, etwa eine Minute:',
        unsupported: 'Dieser Browser lädt die Erweiterung nicht. Bitte MediathekAtlas in Chrome, Edge oder Brave öffnen.'
      }[mode];
      if (steps) steps.hidden = mode === 'ok' || mode === 'unsupported' || mode === 'checking';
      if (mode === 'update') reloadExtension();
    }

    // Neuere App-Version: die App hat den Ordner beim Start schon neu geschrieben, die Erweiterung lädt
    // sich daraus neu (background.js) und meldet sich danach mit der neuen Version (render über das Ereignis).
    function reloadExtension() {
      const key = 'atlas.videostartReload.' + info.version;
      let tried = false;
      try { tried = sessionStorage.getItem(key) === '1'; sessionStorage.setItem(key, '1'); } catch (e) { /* ohne sessionStorage einmal pro Seite */ }
      if (tried || !info.local) { asked = true; return render(); }
      window.postMessage({source: 'mediathekatlas', type: 'videostart-reload'}, location.origin);
      clearTimeout(waitTimer);
      waitTimer = setTimeout(() => { asked = true; render(); }, 6000);
    }

    function platformTexts() {
      const mac = info ? info.platform === 'darwin' : /Mac/.test(navigator.platform || '');
      const win = info ? /^win/.test(info.platform) : /Win/.test(navigator.platform || '');
      for (const k of box.querySelectorAll('kbd[data-key]')) {
        const key = k.dataset.key;
        k.textContent = key === 'goto' ? (mac ? '⌘⇧G' : 'Strg+L') : (mac ? '⌘' : 'Strg+') + key;
      }
      for (const f of box.querySelectorAll('[data-filer]')) f.textContent = mac ? 'Ordner im Finder zeigen' : win ? 'Ordner im Explorer zeigen' : 'Ordner im Dateimanager zeigen';
      for (const li of box.querySelectorAll('[data-local]')) li.hidden = !!info && !info.local;
      for (const li of box.querySelectorAll('[data-remote]')) li.hidden = !info || info.local;
      const path = $('direct-start-path');
      if (path && info) path.textContent = info.path || '';
    }

    async function load() {
      try {
        const r = await fetch('/api/browser-extension/status', {headers: {'X-Atlas-Token': token()}});
        if (!r.ok) throw Error('HTTP ' + r.status);
        info = await r.json();
      } catch (e) {
        info = {version: '', local: false, platform: '', path: ''};
      }
      platformTexts();
      render();
    }

    const copyUrl = $('direct-start-copy-url');
    if (copyUrl) copyUrl.onclick = () => copy('chrome://extensions', 'Adresse');
    const copyPath = $('direct-start-copy-path');
    if (copyPath) copyPath.onclick = () => copy((info && info.path) || '', 'Pfad');
    const reveal = $('direct-start-reveal');
    if (reveal) reveal.onclick = async () => {
      reveal.disabled = true;
      try {
        const r = await fetch('/api/browser-extension/reveal', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Atlas-Token': token()}, body: '{"show":true}'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw Error(data.error || 'HTTP ' + r.status);
        if (info) info.path = data.path;
        platformTexts();
        if (data.shown) say('Ordner bereitgelegt und angezeigt. Jetzt „MediathekAtlas-Videostart“ auf die Chrome-Seite ziehen.');
        else {
          say('Ordner bereitgelegt, ein Dateifenster ließ sich aber nicht öffnen. Bitte „Entpackte Erweiterung laden“ mit diesem Pfad: ' + (data.path || ''));
          const alt = box.querySelector('.ext-alt'); if (alt) alt.open = true;
        }
      } catch (e) {
        say('Ordner konnte nicht angezeigt werden: ' + e.message);
      } finally { reveal.disabled = false; }
    };
    if (get) get.onclick = async () => {
      get.disabled = true;
      try {
        const r = await fetch('/api/browser-extension', {headers: {'X-Atlas-Token': token()}});
        if (!r.ok) throw Error('HTTP ' + r.status);
        const url = URL.createObjectURL(await r.blob()), a = document.createElement('a');
        a.href = url; a.download = 'MediathekAtlas-Videostart-Chrome.zip'; document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        say('ZIP heruntergeladen. Entpacken und den Ordner auf chrome://extensions ziehen (Entwicklermodus an).');
      } catch (e) {
        say('Download fehlgeschlagen: ' + e.message);
      } finally { get.disabled = false; }
    };
    // Die Erweiterung meldet sich nach Installation oder Update selbst (atlas_bridge.js), ohne Neuladen.
    window.addEventListener('atlas-videostart', () => { clearTimeout(waitTimer); asked = false; render(); });
    // Rückfall: beim Zurückkehren in den Tab (z. B. von chrome://extensions) erneut prüfen.
    document.addEventListener('visibilitychange', () => { if (!document.hidden && info) render(); });
    load();
  }

  window.AtlasDirect = {href, enabled, setEnabled, MARK, HOSTS, newer, extensionState};
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', panel); else panel();
  }
})();
