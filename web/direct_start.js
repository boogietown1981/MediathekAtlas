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

  // Einstellungen → „Videostart bei Anbietern“: Schalter und Download der Erweiterung.
  function panel() {
    const box = document.getElementById('direct-start-panel');
    if (!box || box.dataset.ready) return;
    box.dataset.ready = '1';
    const toggle = document.getElementById('direct-start-toggle'), status = document.getElementById('direct-start-status');
    const get = document.getElementById('direct-start-download');
    if (toggle) {
      toggle.checked = enabled();
      toggle.onchange = () => { setEnabled(toggle.checked); if (status) status.textContent = toggle.checked ? 'Direkter Start ist an.' : 'Direkter Start ist aus: Links öffnen wieder die Detailseite des Anbieters.'; };
    }
    if (get) get.onclick = async () => {
      get.disabled = true;
      try {
        const r = await fetch('/api/browser-extension', {headers: {'X-Atlas-Token': document.querySelector('meta[name="atlas-token"]')?.content || ''}});
        if (!r.ok) throw Error('HTTP ' + r.status);
        const url = URL.createObjectURL(await r.blob()), a = document.createElement('a');
        a.href = url; a.download = 'MediathekAtlas-Videostart-Chrome.zip'; document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        if (status) status.textContent = 'ZIP heruntergeladen. Jetzt entpacken und wie unten beschrieben in Chrome laden.';
      } catch (e) {
        if (status) status.textContent = 'Download fehlgeschlagen: ' + e.message;
      } finally { get.disabled = false; }
    };
  }

  window.AtlasDirect = {href, enabled, setEnabled, MARK, HOSTS};
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', panel); else panel();
  }
})();
