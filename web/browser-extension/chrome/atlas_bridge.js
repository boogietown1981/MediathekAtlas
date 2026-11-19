/* MediathekAtlas Videostart, seit 0.6.38: Verbindung zur eigenen MediathekAtlas-Seite (nur http://127.0.0.1 und localhost).
 *
 * - Meldet der Oberfläche, dass die Erweiterung installiert ist und in welcher Version
 *   (Attribut data-atlas-videostart am <html>-Element + Ereignis „atlas-videostart“). Damit zeigt
 *   Einstellungen → „Videostart bei Anbietern“ den Installationsstand ohne Zutun an.
 * - Auf Wunsch der Oberfläche (nur wenn die App eine neuere Version bereitgestellt hat) lädt sich die
 *   Erweiterung aus ihrem Ordner neu. So kommen Updates ohne Klick auf chrome://extensions an.
 * Liest nichts von der Seite und sendet keine Daten.
 */
(() => {
  'use strict';
  const version = chrome.runtime.getManifest().version;
  const root = document.documentElement;
  if (!root) return;
  root.dataset.atlasVideostart = version;
  window.dispatchEvent(new Event('atlas-videostart'));
  // Nach einem Neuladen der Erweiterung wird dieses Skript erneut eingesetzt: alten Empfänger ersetzen.
  if (window.__atlasVideostartBridge) window.removeEventListener('message', window.__atlasVideostartBridge);
  window.__atlasVideostartBridge = event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data;
    if (!data || data.source !== 'mediathekatlas' || data.type !== 'videostart-reload') return;
    try { chrome.runtime.sendMessage({type: 'reload'}); } catch (e) { /* alte, getrennte Fassung: nichts zu tun */ }
  };
  window.addEventListener('message', window.__atlasVideostartBridge);
})();
